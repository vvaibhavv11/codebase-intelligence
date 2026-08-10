"""Documentation generation service — LLM-generated docs for symbols and repos."""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.file import File
from backend.models.generated_doc import GeneratedDoc
from backend.models.repository import Repository
from backend.models.symbol import CodeSymbol
from backend.services.embeddings import get_openai_client

logger = logging.getLogger(__name__)


async def get_cached_doc(
    db: AsyncSession,
    repo_id: uuid.UUID,
    kind: str,
    symbol_id: uuid.UUID | None = None,
) -> GeneratedDoc | None:
    """Look up a cached generated doc."""
    stmt = select(GeneratedDoc).where(
        GeneratedDoc.repo_id == repo_id,
        GeneratedDoc.kind == kind,
    )
    if symbol_id:
        stmt = stmt.where(GeneratedDoc.symbol_id == symbol_id)
    else:
        stmt = stmt.where(GeneratedDoc.symbol_id.is_(None))
    result = await db.execute(stmt.order_by(GeneratedDoc.created_at.desc()).limit(1))
    return result.scalar_one_or_none()


async def save_doc(
    db: AsyncSession,
    repo_id: uuid.UUID,
    kind: str,
    content: str,
    symbol_id: uuid.UUID | None = None,
) -> GeneratedDoc:
    """Cache a generated doc, replacing any previous version."""
    await db.execute(
        delete(GeneratedDoc).where(
            GeneratedDoc.repo_id == repo_id,
            GeneratedDoc.kind == kind,
            (
                GeneratedDoc.symbol_id == symbol_id
                if symbol_id
                else GeneratedDoc.symbol_id.is_(None)
            ),
        )
    )
    doc = GeneratedDoc(
        repo_id=repo_id,
        symbol_id=symbol_id,
        kind=kind,
        content=content,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


async def generate_symbol_doc(db: AsyncSession, symbol: CodeSymbol) -> str:
    """Generate markdown documentation for a single symbol."""
    file = await db.get(File, symbol.file_id) if symbol.file_id else None
    file_path = file.path if file else "unknown"
    language = file.language if file else "text"

    prompt = f"""You are a technical documentation writer.
Generate concise, accurate markdown documentation for this code symbol.

File: {file_path}
Type: {symbol.kind}
Name: {symbol.name}
Signature: {symbol.signature}

```{language}
{symbol.source_text[:4000]}
```

Include: purpose, parameters, return value, side effects, and a usage example.
Use markdown formatting with headings where appropriate."""

    client = get_openai_client()
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1024,
    )
    return response.choices[0].message.content or ""


async def generate_repo_readme(db: AsyncSession, repo: Repository) -> str:
    """Generate a project README from the repo's indexed symbols."""
    # 1. Get all top-level symbols grouped by file
    file_result = await db.execute(
        select(File).where(File.repo_id == repo.id).order_by(File.path)
    )
    files = file_result.scalars().all()

    symbol_result = await db.execute(
        select(CodeSymbol)
        .where(CodeSymbol.repo_id == repo.id, CodeSymbol.parent_id.is_(None))
        .order_by(CodeSymbol.file_id, CodeSymbol.start_line)
    )
    symbols = symbol_result.scalars().all()

    symbols_by_file: dict[str, list[CodeSymbol]] = {}
    for s in symbols:
        f = next((f for f in files if f.id == s.file_id), None)
        path = f.path if f else "unknown"
        symbols_by_file.setdefault(path, []).append(s)

    # 2. Summarize architecture
    overview_lines = [
        f"Repository: {repo.owner}/{repo.name}",
        f"Default branch: {repo.default_branch}",
        f"Files indexed: {len(files)}",
        f"Top-level symbols: {len(symbols)}",
        "",
        "## Key modules and symbols",
    ]
    for path, syms in list(symbols_by_file.items())[:60]:
        overview_lines.append(f"\n### {path}")
        for s in syms[:20]:
            sig = s.signature or s.name
            doc = (s.docstring or "").strip().split("\n")[0]
            overview_lines.append(f"- `{sig}`" + (f" — {doc}" if doc else ""))

    architecture_text = "\n".join(overview_lines)

    prompt = f"""You are a technical documentation writer.
Generate a structured README.md for the following code repository.

{architecture_text}

The README must include these sections (in markdown):
1. Project title and one-paragraph overview (infer the project's purpose from the code)
2. Architecture — how the modules relate to each other
3. Key modules — brief description of each module with file paths
4. Getting started — general setup steps
5. API reference — list the most important symbols with file:line references

Be concise and accurate. Do not invent details not present in the code."""

    client = get_openai_client()
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=2048,
    )
    return response.choices[0].message.content or ""
