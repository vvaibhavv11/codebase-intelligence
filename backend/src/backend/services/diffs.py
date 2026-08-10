"""Git diff analysis service — commit history, diffs, and LLM-based diff analysis."""
from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

from git import Repo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.dependency import Dependency
from backend.models.file import File
from backend.models.repository import Repository
from backend.models.symbol import CodeSymbol
from backend.schemas.diff import CommitSummary, CommitDiff, FileDiff
from backend.services.embeddings import get_openai_client

logger = logging.getLogger(__name__)

# Matches function/class definition names in diff +/- lines
_SYMBOL_RE = re.compile(
    r"^\s*[+\-]\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)"
    r"|^\s*[+\-]\s*(?:function|const|let|var)\s+([A-Za-z_]\w*)"
    r"|^\s*[+\-]\s*(\w+)\s*=\s*(?:async\s*)?(?:\(|function|\w+\([^)]*\)\s*=>)"
)

MAX_DIFF_PATCH_CHARS = 12_000
MAX_AFFECTED_CODE_CHARS = 12_000


# ---------------------------------------------------------------------------
# Git access
# ---------------------------------------------------------------------------

def get_repo_dir(repo: Repository) -> Path:
    return settings.repos_path / f"{repo.owner}__{repo.name}"


def _ensure_history(repo_dir: Path) -> Repo:
    """Open the repo and unshallow it if it was cloned with --depth 1."""
    repo = Repo(repo_dir)
    shallow = repo_dir / ".git" / "shallow"
    if shallow.exists():
        logger.info("Repo is shallow, fetching full history: %s", repo_dir)
        repo.git.fetch("--unshallow")
    return repo


def get_recent_commits(repo_dir: Path, max_commits: int = 50) -> list[CommitSummary]:
    """Get recent commits with per-commit stats."""
    repo = _ensure_history(repo_dir)
    commits = list(repo.iter_commits(max_count=max_commits))

    result: list[CommitSummary] = []
    for commit in commits:
        parent = commit.parents[0] if commit.parents else None
        diff = commit.diff(parent, create_patch=True) if parent else commit.diff(create_patch=True)

        added = removed = 0
        files_changed = 0
        for d in diff:
            if d.change_type in ("A", "M", "D", "R"):
                files_changed += 1
            if d.diff:
                text = d.diff.decode("utf-8", errors="replace")
                added += sum(1 for l in text.split("\n") if l.startswith("+") and not l.startswith("+++"))
                removed += sum(1 for l in text.split("\n") if l.startswith("-") and not l.startswith("---"))

        result.append(CommitSummary(
            sha=commit.hexsha[:8],
            author=commit.author.name,
            date=commit.committed_datetime,
            message=commit.message.strip().split("\n")[0],
            files_changed=files_changed,
            added_lines=added,
            removed_lines=removed,
        ))
    return result


def get_commit_diff(repo_dir: Path, sha: str) -> CommitDiff:
    """Get the full diff of a specific commit."""
    repo = _ensure_history(repo_dir)
    try:
        commit = repo.commit(sha)
    except Exception:
        raise ValueError(f"Commit not found: {sha}")

    parent = commit.parents[0] if commit.parents else None
    diff = commit.diff(parent, create_patch=True) if parent else commit.diff(create_patch=True)

    files: list[FileDiff] = []
    for d in diff:
        if d.change_type not in ("A", "M", "D", "R"):
            continue
        patch = d.diff.decode("utf-8", errors="replace") if d.diff else None
        added = removed = 0
        if patch:
            added = sum(1 for l in patch.split("\n") if l.startswith("+") and not l.startswith("+++"))
            removed = sum(1 for l in patch.split("\n") if l.startswith("-") and not l.startswith("---"))
        files.append(FileDiff(
            file_path=d.a_path or d.b_path or "",
            change_type=d.change_type,
            patch=patch,
            added_lines=added,
            removed_lines=removed,
        ))

    return CommitDiff(
        sha=commit.hexsha[:8],
        author=commit.author.name,
        date=commit.committed_datetime,
        message=commit.message.strip(),
        files=files,
    )


# ---------------------------------------------------------------------------
# Breakage detection
# ---------------------------------------------------------------------------

def extract_symbol_names_from_patch(patch: str | None) -> set[str]:
    """Extract function/class names mentioned in a diff patch."""
    if not patch:
        return set()
    names: set[str] = set()
    for line in patch.split("\n"):
        if not (line.startswith("+") or line.startswith("-")):
            continue
        m = _SYMBOL_RE.match(line)
        if m:
            for group in m.groups():
                if group:
                    names.add(group)
    return names


async def _find_dependents(
    db: AsyncSession, repo_id: uuid.UUID, symbol_names: set[str]
) -> list[dict]:
    """Find code that depends on the given symbols (reverse dependency edges)."""
    if not symbol_names:
        return []

    sym_result = await db.execute(
        select(CodeSymbol).where(
            CodeSymbol.repo_id == repo_id,
            CodeSymbol.name.in_(symbol_names),
        )
    )
    symbols = sym_result.scalars().all()
    if not symbols:
        return []

    symbol_ids = [s.id for s in symbols]
    edge_result = await db.execute(
        select(Dependency).where(
            Dependency.repo_id == repo_id,
            Dependency.target_symbol_id.in_(symbol_ids),
            Dependency.kind.in_(("call", "import", "class_extend")),
        )
    )
    edges = edge_result.scalars().all()

    # Load source symbols eagerly (avoid lazy loading in async session)
    source_ids = [e.source_symbol_id for e in edges if e.source_symbol_id]
    source_syms: dict[uuid.UUID, CodeSymbol] = {}
    if source_ids:
        syms_result = await db.execute(
            select(CodeSymbol).where(CodeSymbol.id.in_(source_ids))
        )
        source_syms = {s.id: s for s in syms_result.scalars().all()}

    file_result = await db.execute(
        select(File).where(File.repo_id == repo_id)
    )
    file_paths = {f.id: f.path for f in file_result.scalars().all()}

    dependents: list[dict] = []
    seen: set[str] = set()
    for edge in edges:
        if edge.source_symbol_id:
            source_sym = source_syms.get(edge.source_symbol_id)
            if source_sym and str(source_sym.id) not in seen:
                seen.add(str(source_sym.id))
                dependents.append({
                    "file_path": file_paths.get(source_sym.file_id, ""),
                    "name": source_sym.name,
                    "kind": source_sym.kind,
                    "source_text": source_sym.source_text[:2000],
                    "start_line": source_sym.start_line,
                    "end_line": source_sym.end_line,
                    "via": edge.kind,
                })
        elif edge.source_file_id:
            key = f"file:{edge.source_file_id}"
            if key not in seen:
                seen.add(key)
                dependents.append({
                    "file_path": file_paths.get(edge.source_file_id, ""),
                    "name": "(module)",
                    "kind": "file",
                    "source_text": "",
                    "start_line": 0,
                    "end_line": 0,
                    "via": edge.kind,
                })
    return dependents


def _build_analysis_prompt(
    repo_name: str, diff: CommitDiff, dependents: list[dict]
) -> str:
    """Build the LLM prompt for diff analysis with breakage detection."""
    diff_text = ""
    for f in diff.files:
        diff_text += f"\n--- {f.file_path} ({f.change_type}) ---\n"
        patch = f.patch or ""
        diff_text += patch[:MAX_DIFF_PATCH_CHARS]
        if len(patch) > MAX_DIFF_PATCH_CHARS:
            diff_text += "\n... (truncated)"

    affected_text = ""
    for d in dependents:
        if not d["source_text"]:
            continue
        affected_text += (
            f"\n--- {d['kind']} {d['name']} in {d['file_path']} "
            f"(lines {d['start_line']}-{d['end_line']}, depends via {d['via']}) ---\n"
            f"```\n{d['source_text']}\n```\n"
        )

    return (
        f'You are a code review assistant analyzing a commit in the repository "{repo_name}".\n'
        "\n"
        "Analyze the following commit diff.\n"
        "For each change: explain what was changed, why it might matter, and whether it "
        "could break existing code.\n"
        "If any affected/dependent code is listed below, analyze the impact on those callers "
        "specifically, referencing file paths and line numbers.\n"
        "Be precise, technical, and concise. Format the answer with markdown headers.\n"
        "\n"
        "## Commit\n"
        f"Message: {diff.message}\n"
        f"Author: {diff.author}\n"
        f"Date: {diff.date.isoformat()}\n"
        "\n"
        "## Diff\n"
        f"{diff_text}"
        "\n"
        "## Affected Code (dependents that may break)\n"
        f"{affected_text if affected_text else '(none found)'}"
    )


async def stream_diff_analysis(
    db: AsyncSession,
    repo: Repository,
    commit_sha: str | None,
    file_path: str | None,
) -> AsyncGenerator[str, None]:
    """Stream an LLM analysis of a diff, including breakage detection."""
    repo_dir = get_repo_dir(repo)
    if not repo_dir.exists():
        yield "Error: Repo is not cloned locally. Trigger indexing first."
        return

    try:
        if commit_sha:
            diff = get_commit_diff(repo_dir, commit_sha)
        elif file_path:
            # Current working-tree changes for one file
            git_repo = _ensure_history(repo_dir)
            repo_obj = git_repo
            head = repo_obj.head.commit
            diff = _working_tree_file_diff(repo_obj, head, file_path)
            if diff is None:
                yield "Error: No changes found for this file."
                return
        else:
            yield "Error: Provide either commit_sha or file_path."
            return
    except ValueError as e:
        yield f"Error: {e}"
        return
    except Exception as e:
        logger.exception("Failed to compute diff")
        yield f"Error: Failed to compute diff: {e}"
        return

    # Breakage detection: symbols changed in this diff → their dependents
    symbol_names: set[str] = set()
    for f in diff.files:
        symbol_names |= extract_symbol_names_from_patch(f.patch)
    dependents = await _find_dependents(db, repo.id, symbol_names)

    prompt = _build_analysis_prompt(f"{repo.owner}/{repo.name}", diff, dependents)

    client = get_openai_client()
    try:
        stream = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            temperature=0.1,
            max_tokens=4096,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        logger.exception("LLM diff analysis failed")
        yield f"\n\nError: Failed to get analysis from LLM: {e}"


def _working_tree_file_diff(repo: Repo, head, file_path: str) -> CommitDiff | None:
    """Build a CommitDiff from uncommitted working-tree changes of one file."""
    diffs = list(repo.index.diff(None, paths=[file_path], create_patch=True))
    if not diffs:
        return None
    files: list[FileDiff] = []
    for d in diffs:
        patch = d.diff.decode("utf-8", errors="replace") if d.diff else None
        added = removed = 0
        if patch:
            added = sum(1 for l in patch.split("\n") if l.startswith("+") and not l.startswith("+++"))
            removed = sum(1 for l in patch.split("\n") if l.startswith("-") and not l.startswith("---"))
        files.append(FileDiff(
            file_path=d.a_path or d.b_path or file_path,
            change_type=d.change_type or "M",
            patch=patch,
            added_lines=added,
            removed_lines=removed,
        ))
    return CommitDiff(
        sha=head.hexsha[:8],
        author="working-tree",
        date=head.committed_datetime,
        message="Uncommitted changes",
        files=files,
    )
