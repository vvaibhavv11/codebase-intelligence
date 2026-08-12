"""RAG (Retrieval-Augmented Generation) chat service.

Answers questions about a codebase by retrieving relevant code via
semantic search and streaming LLM responses. Also detects impact-analysis
questions ("what breaks if I change X") and augments the context with
dependency-graph dependents.
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.chat import ChatMessage
from backend.models.dependency import Dependency
from backend.models.file import File
from backend.models.repository import Repository
from backend.models.symbol import CodeSymbol
from backend.services.embeddings import get_openai_client
from backend.services.search import search_code

logger = logging.getLogger(__name__)

# Questions asking about the impact of changing code
_IMPACT_KEYWORDS = (
    "what breaks",
    "break if",
    "would break",
    "impact",
    "affect",
    "who uses",
    "who calls",
    "who depends",
    "what happens if",
    "dependents",
    "change this",
    "refactor",
)

# High-level questions about the whole project (symbol search won't retrieve
# anything relevant for these — fall back to repo-level context instead).
_OVERVIEW_KEYWORDS = (
    "what does this project do",
    "what does this repo do",
    "what is this project",
    "what is this repo",
    "what's this project",
    "whats this project",
    "about this project",
    "about this repo",
    "project overview",
    "repo overview",
    "describe this project",
    "describe this repo",
    "what is the purpose",
    "high level",
    "architecture",
    "overview",
    "readme",
    "getting started",
)


def _is_impact_question(message: str) -> bool:
    lower = message.lower()
    return any(k in lower for k in _IMPACT_KEYWORDS)


def _is_overview_question(message: str) -> bool:
    lower = message.lower()
    return any(k in lower for k in _OVERVIEW_KEYWORDS)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _retrieve_context(
    db: AsyncSession,
    repo_id: uuid.UUID,
    query: str,
    top_k: int = 10,
) -> list[dict]:
    """Retrieve the most relevant code chunks for a query.

    Returns a list of dicts with: file_path, symbol_name, symbol_kind,
    source_text, start_line, end_line, score.
    """
    results = await search_code(db, repo_id, query, limit=top_k)

    # For each result, fetch the full source text from code_symbols
    # (search results only contain a truncated preview).
    context_chunks: list[dict] = []
    for r in results:
        symbol = await db.get(CodeSymbol, r.symbol_id)
        if symbol:
            context_chunks.append({
                "symbol_id": str(symbol.id),
                "file_path": r.file_path,
                "symbol_name": symbol.name,
                "symbol_kind": symbol.kind,
                "source_text": symbol.source_text,
                "start_line": symbol.start_line,
                "end_line": symbol.end_line,
                "score": r.score,
            })

    return context_chunks


async def _retrieve_dependents(
    db: AsyncSession,
    repo_id: uuid.UUID,
    context_chunks: list[dict],
    max_chunks: int = 6,
) -> list[dict]:
    """Retrieve code that depends on the retrieved symbols (reverse graph edges)."""
    target_ids = [uuid.UUID(c["symbol_id"]) for c in context_chunks if c.get("symbol_id")]
    if not target_ids:
        return []

    edge_result = await db.execute(
        select(Dependency).where(
            Dependency.repo_id == repo_id,
            Dependency.target_symbol_id.in_(target_ids),
            Dependency.kind.in_(("call", "import", "class_extend")),
        )
    )
    edges = edge_result.scalars().all()

    source_ids = [e.source_symbol_id for e in edges if e.source_symbol_id]
    if not source_ids:
        return []

    sym_result = await db.execute(
        select(CodeSymbol).where(CodeSymbol.id.in_(source_ids))
    )
    symbols = sym_result.scalars().all()

    file_result = await db.execute(
        select(File).where(
            File.id.in_({s.file_id for s in symbols})
        )
    )
    file_paths = {f.id: f.path for f in file_result.scalars().all()}

    # Order dependents by number of edges pointing at them
    by_id: dict[uuid.UUID, dict] = {}
    for sym in symbols:
        by_id[sym.id] = {
            "file_path": file_paths.get(sym.file_id, ""),
            "symbol_name": sym.name,
            "symbol_kind": sym.kind,
            "source_text": sym.source_text[:3000],
            "start_line": sym.start_line,
            "end_line": sym.end_line,
            "score": 0.0,
            "dependents": 0,
        }
    for edge in edges:
        if edge.source_symbol_id and edge.source_symbol_id in by_id:
            by_id[edge.source_symbol_id]["dependents"] += 1

    return sorted(by_id.values(), key=lambda c: c["dependents"], reverse=True)[:max_chunks]


async def _build_repo_overview(
    db: AsyncSession,
    repo: Repository,
    max_readme_chars: int = 6000,
    max_files: int = 40,
) -> str | None:
    """Build a repository-level overview: README + file/language summary.

    Used for high-level questions ("what does this project do") where
    symbol-level retrieval finds nothing relevant. The README (and other
    docs) are stored in ``files`` during indexing but never embedded, so
    this reads them directly from the DB.
    """
    files_result = await db.execute(
        select(File.path, File.language)
        .where(File.repo_id == repo.id)
        .order_by(File.path)
    )
    files = files_result.all()
    if not files:
        return None

    root_readme = next(
        (
            f.path
            for f in files
            if f.path.lower().endswith("readme.md") and "/" not in f.path.rstrip("/")
        ),
        None,
    )
    readme_text = ""
    if root_readme:
        readme_result = await db.execute(
            select(File.content).where(
                File.repo_id == repo.id, File.path == root_readme
            )
        )
        readme_text = (readme_result.scalar_one_or_none() or "")[:max_readme_chars]

    lang_counts: dict[str, int] = {}
    for _, lang in files:
        lang_counts[lang or "other"] = lang_counts.get(lang or "other", 0) + 1
    lang_summary = ", ".join(
        f"{lang} ({count})"
        for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1])[:8]
    )

    paths = "\n".join(f.path for f in files[:max_files])
    if len(files) > max_files:
        paths += f"\n... and {len(files) - max_files} more files"

    parts = [
        f"Repository: {repo.owner}/{repo.name}",
        f"Files indexed: {len(files)}",
        f"Languages: {lang_summary}",
    ]
    if readme_text:
        parts.append(f"\nREADME (from {root_readme}):\n{readme_text}")
    parts.append(f"\nFile tree (first {max_files} files):\n{paths}")
    return "\n".join(parts)


def _build_references(
    context_chunks: list[dict], max_refs: int = 8
) -> tuple[list[dict], str]:
    """Extract deduplicated code references from retrieved context.

    Returns (references, marker) where marker is an HTML comment carrying the
    same references. The marker is appended to the persisted chat message so
    source chips survive session reloads (ReactMarkdown drops HTML comments).
    """
    refs: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for chunk in context_chunks:
        key = (chunk["file_path"], chunk["start_line"])
        if key in seen:
            continue
        seen.add(key)
        refs.append({
            "file_path": chunk["file_path"],
            "symbol_name": chunk["symbol_name"],
            "symbol_kind": chunk["symbol_kind"],
            "start_line": chunk["start_line"],
            "end_line": chunk["end_line"],
        })
        if len(refs) >= max_refs:
            break

    marker = f"<!--refs:{json.dumps(refs)}-->" if refs else ""
    return refs, marker


def _build_system_prompt(
    repo_name: str,
    context_chunks: list[dict],
    impact_chunks: list[dict] | None = None,
    repo_overview: str | None = None,
) -> str:
    """Build the system prompt with retrieved code context."""
    context_text = ""
    for i, chunk in enumerate(context_chunks, 1):
        context_text += f"\n--- Code Chunk {i} ---\n"
        context_text += (
            f"File: {chunk['file_path']} "
            f"(lines {chunk['start_line']}-{chunk['end_line']})\n"
        )
        context_text += f"Type: {chunk['symbol_kind']} | Name: {chunk['symbol_name']}\n"
        context_text += f"```\n{chunk['source_text']}\n```\n"

    impact_text = ""
    if impact_chunks:
        impact_text = "\n\n## Code That Depends on the Retrieved Symbols\n"
        for i, chunk in enumerate(impact_chunks, 1):
            impact_text += f"\n--- Dependent {i} ---\n"
            impact_text += (
                f"File: {chunk['file_path']} "
                f"(lines {chunk['start_line']}-{chunk['end_line']})\n"
            )
            impact_text += f"Type: {chunk['symbol_kind']} | Name: {chunk['symbol_name']}\n"
            impact_text += f"```\n{chunk['source_text']}\n```\n"

    impact_instruction = ""
    if impact_chunks:
        impact_instruction = (
            "\n"
            "The user is asking about the impact of changing code. "
            "Analyze the impact of changing the retrieved symbol(s) and list affected "
            "code with file:line references. Use the dependents section to identify "
            "callers that would break or need changes."
        )

    overview_section = ""
    if repo_overview:
        overview_section = "\n\n## Repository Overview\n" + repo_overview + "\n"

    return (
        f'You are a code intelligence assistant analyzing the repository "{repo_name}".\n'
        "\n"
        "You answer questions about the codebase based on the indexed source code provided below.\n"
        "When referencing code, always mention the file path and line numbers.\n"
        "If the provided context doesn't contain enough information to answer, say so clearly.\n"
        "Be precise, technical, and concise.\n"
        "\n"
        "## Relevant Code Context\n"
        f"{context_text}"
        f"{overview_section}"
        f"{impact_text}"
        f"{impact_instruction}"
    )


async def _load_conversation_history(
    db: AsyncSession,
    session_id: uuid.UUID,
    max_messages: int = 20,
) -> list[dict]:
    """Load recent conversation messages for context."""
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(max_messages)
    )
    result = await db.execute(stmt)
    messages = list(reversed(result.scalars().all()))

    return [
        {"role": msg.role, "content": msg.content}
        for msg in messages
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def stream_rag_response(
    db: AsyncSession,
    repo_id: uuid.UUID,
    session_id: uuid.UUID,
    user_message: str,
) -> AsyncGenerator[tuple[str, str] | tuple[str, dict], None]:
    """Stream a RAG response for a user's question about a codebase.

    Yields (kind, payload) tuples:
      ("refs", {"references": [...], "marker": "..."}) — emitted once, first
      ("text", chunk) — LLM text chunks as they arrive
    """
    # 1. Get repo info
    repo = await db.get(Repository, repo_id)
    if not repo:
        yield "text", "Error: Repository not found."
        return

    # 2. Retrieve relevant code context
    context_chunks = await _retrieve_context(db, repo_id, user_message)

    # 2b. Impact questions get dependency-graph dependents added to context
    impact_chunks: list[dict] | None = None
    if context_chunks and _is_impact_question(user_message):
        impact_chunks = await _retrieve_dependents(db, repo_id, context_chunks)

    # 2c. Extract code references for clickable source chips
    refs, marker = _build_references(context_chunks)
    if refs:
        yield "refs", {"references": refs, "marker": marker}

    # 2d. High-level questions ("what does this project do") and queries with
    #     no retrieval hits get repo-level context (README + file list) so
    #     the LLM is never left with zero source material.
    repo_overview = None
    if not context_chunks or _is_overview_question(user_message):
        repo_overview = await _build_repo_overview(db, repo)

    if not context_chunks:
        logger.warning(
            "No relevant code found for query %r in repo %s",
            user_message,
            repo_id,
        )
        # Still call the LLM so it can explain the situation naturally,
        # but use an empty-context system prompt.

    # 3. Build messages array
    system_prompt = _build_system_prompt(
        f"{repo.owner}/{repo.name}",
        context_chunks,
        impact_chunks,
        repo_overview=repo_overview,
    )
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    # 4. Add conversation history (excluding the current message which was
    #    already saved by the router before calling us).
    history = await _load_conversation_history(db, session_id)
    if history and history[-1]["role"] == "user":
        history = history[:-1]
    messages.extend(history)

    # 5. Add current user message
    messages.append({"role": "user", "content": user_message})

    # 6. Call LLM with streaming
    client = get_openai_client()

    try:
        stream = await client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            stream=True,
            temperature=0.1,
            max_tokens=4096,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield "text", chunk.choices[0].delta.content

    except Exception as e:
        logger.exception("LLM streaming failed")
        yield "text", f"\n\nError: Failed to get response from LLM: {e}"
