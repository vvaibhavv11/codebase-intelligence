"""Indexing pipeline — clone → parse → embed → store → resolve dependencies."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import async_session
from backend.models.dependency import Dependency
from backend.models.embedding import CodeEmbedding
from backend.models.file import File
from backend.models.generated_doc import GeneratedDoc
from backend.models.repository import Repository, RepoStatus
from backend.models.symbol import CodeSymbol
from backend.services.embeddings import (
    get_embeddings_batch,
    prepare_symbol_text,
    truncate_for_embedding,
)
from backend.services.github import clone_repo, get_default_branch, walk_source_files
from backend.services.parser import ExtractedFile, ExtractedSymbol, parse_file

logger = logging.getLogger(__name__)


async def run_indexing(repo_id: uuid.UUID) -> None:
    """Main indexing pipeline. Runs as a background task.

    Creates its own DB session since it executes outside the
    request lifecycle.
    """
    async with async_session() as db:
        try:
            await _do_indexing(db, repo_id)
        except Exception as e:
            logger.exception(f"Indexing failed for repo {repo_id}")
            # Rollback any dirty state before setting error status
            await db.rollback()
            # Update status to error
            repo = await db.get(Repository, repo_id)
            if repo:
                repo.status = RepoStatus.error
                repo.error_message = str(e)
                await db.commit()


async def _do_indexing(db: AsyncSession, repo_id: uuid.UUID) -> None:
    repo = await db.get(Repository, repo_id)
    if not repo:
        return

    # Step 1: Clone
    repo.status = RepoStatus.cloning
    await db.commit()

    repo_dir = await asyncio.to_thread(clone_repo, repo.github_url, repo.owner, repo.name)
    repo.default_branch = await asyncio.to_thread(get_default_branch, repo_dir)

    # Step 2: Index
    repo.status = RepoStatus.indexing
    await db.commit()

    # Clear old data for re-indexing
    await _clear_repo_data(db, repo_id)

    # Step 3: Walk and parse files
    source_files = await asyncio.to_thread(walk_source_files, repo_dir)
    all_symbols_for_embedding: list[
        tuple[CodeSymbol, str, str]
    ] = []  # (symbol_db_obj, prepared_text, file_path)
    file_extracts: list[tuple[File, ExtractedFile]] = []
    class_bases: list[tuple[CodeSymbol, list[str]]] = []

    for file_info in source_files:
        # Create File record
        file_record = File(
            repo_id=repo_id,
            path=file_info["path"],
            language=file_info["language"],
            content=file_info["content"],
            content_hash=hashlib.sha256(
                file_info["content"].encode()
            ).hexdigest(),
        )
        db.add(file_record)
        await db.flush()

        # Parse with tree-sitter — catch per-file errors so one bad file
        # doesn't abort the whole index.
        try:
            extracted = parse_file(file_info["content"], file_info["language"])
        except Exception:
            logger.warning(
                "Failed to parse %s, skipping", file_info["path"], exc_info=True
            )
            continue

        file_extracts.append((file_record, extracted))

        # Store symbols
        for symbol in extracted.symbols:
            sym_record = _create_symbol_record(
                symbol, file_record.id, repo_id, parent_id=None
            )
            db.add(sym_record)
            await db.flush()

            if symbol.kind == "class" and symbol.bases:
                class_bases.append((sym_record, symbol.bases))

            # Prepare text for embedding
            text = prepare_symbol_text(
                symbol_name=symbol.name,
                symbol_kind=symbol.kind,
                file_path=file_info["path"],
                source_text=symbol.source_text,
                docstring=symbol.docstring,
                signature=symbol.signature,
            )
            all_symbols_for_embedding.append(
                (sym_record, text, file_info["path"])
            )

            # Also process child symbols (methods in classes)
            for child in symbol.children:
                child_record = _create_symbol_record(
                    child, file_record.id, repo_id, parent_id=sym_record.id
                )
                db.add(child_record)
                await db.flush()

                child_text = prepare_symbol_text(
                    symbol_name=child.name,
                    symbol_kind=child.kind,
                    file_path=file_info["path"],
                    source_text=child.source_text,
                    docstring=child.docstring,
                    signature=child.signature,
                )
                all_symbols_for_embedding.append(
                    (child_record, child_text, file_info["path"])
                )

    await db.commit()

    # Step 4: Generate embeddings in batches
    if all_symbols_for_embedding:
        texts = [truncate_for_embedding(t) for _, t, _ in all_symbols_for_embedding]
        embeddings = await get_embeddings_batch(texts)

        for (sym_record, text, file_path), embedding in zip(
            all_symbols_for_embedding, embeddings
        ):
            emb_record = CodeEmbedding(
                symbol_id=sym_record.id,
                repo_id=repo_id,
                chunk_text=text,
                file_path=file_path,
                symbol_name=sym_record.name,
                symbol_kind=sym_record.kind,
                embedding=embedding,
            )
            db.add(emb_record)

        await db.commit()

    # Step 5: Resolve dependency edges
    await _resolve_dependencies(db, repo_id, file_extracts, class_bases)

    # Step 6: Mark as ready
    repo.status = RepoStatus.ready
    repo.indexed_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info(
        "Indexing complete for %s/%s: %d files, %d symbols",
        repo.owner,
        repo.name,
        len(source_files),
        len(all_symbols_for_embedding),
    )


# ---------------------------------------------------------------------------
# Dependency resolution
# ---------------------------------------------------------------------------

async def _resolve_dependencies(
    db: AsyncSession,
    repo_id: uuid.UUID,
    file_extracts: list[tuple[File, ExtractedFile]],
    class_bases: list[tuple[CodeSymbol, list[str]]],
) -> None:
    """Resolve imports, calls, and inheritance into Dependency edges."""
    if not file_extracts:
        return

    # Build lookup indexes
    files = await db.scalars(select(File).where(File.repo_id == repo_id))
    all_files = list(files.all())
    file_by_path = {f.path: f for f in all_files}
    module_index = _build_module_index(all_files)

    symbols = await db.scalars(select(CodeSymbol).where(CodeSymbol.repo_id == repo_id))
    all_symbols = list(symbols.all())
    sym_by_name: dict[str, list[CodeSymbol]] = defaultdict(list)
    for s in all_symbols:
        sym_by_name[s.name].append(s)

    edges: set[tuple[str, str, str, str, str]] = set()
    # (source_symbol_id or "", source_file_id or "", target_symbol_id or "", target_file_id or "", kind)

    for file_record, extracted in file_extracts:
        fpath = file_record.path

        for imp in extracted.imports:
            # 1. Symbol match: `from x import y` / `import { y } from "x"`
            if imp.imported_name:
                target = _find_symbol(imp.imported_name, sym_by_name, file_record.id)
                if target:
                    edges.add(("", str(file_record.id), str(target.id), "", "import"))

            # 2. Module match: import resolves to a file in the repo
            target_file = _resolve_module_file(
                imp.module, fpath, file_by_path, module_index
            )
            if target_file and target_file.id != file_record.id:
                edges.add(("", str(file_record.id), "", str(target_file.id), "module_import"))

        for call in extracted.calls:
            target = _find_symbol(call.callee_name, sym_by_name, file_record.id)
            if not target:
                continue
            if call.caller_name:
                caller = _find_symbol_in_file(
                    call.caller_name, call.line, file_record.id, sym_by_name
                )
                if caller and caller.id != target.id:
                    edges.add((str(caller.id), "", str(target.id), "", "call"))
                    continue
            edges.add(("", str(file_record.id), str(target.id), "", "call"))

    for sym_record, bases in class_bases:
        for base in bases:
            target = _find_symbol(base, sym_by_name, sym_record.file_id)
            if target and target.id != sym_record.id:
                edges.add((str(sym_record.id), "", str(target.id), "", "class_extend"))

    # Insert edges
    for src_sym, src_file, tgt_sym, tgt_file, kind in edges:
        db.add(Dependency(
            repo_id=repo_id,
            source_symbol_id=uuid.UUID(src_sym) if src_sym else None,
            source_file_id=uuid.UUID(src_file) if src_file else None,
            target_symbol_id=uuid.UUID(tgt_sym) if tgt_sym else None,
            target_file_id=uuid.UUID(tgt_file) if tgt_file else None,
            kind=kind,
        ))
    await db.commit()

    logger.info("Resolved %d dependency edges for repo %s", len(edges), repo_id)


def _find_symbol(
    name: str, sym_by_name: dict[str, list[CodeSymbol]], file_id: uuid.UUID
) -> CodeSymbol | None:
    """Find a symbol by name, preferring one in the same file."""
    matches = sym_by_name.get(name)
    if not matches:
        return None
    for m in matches:
        if m.file_id == file_id:
            return m
    return matches[0]


def _find_symbol_in_file(
    name: str,
    line: int,
    file_id: uuid.UUID,
    sym_by_name: dict[str, list[CodeSymbol]],
) -> CodeSymbol | None:
    """Find a symbol by name in a specific file, preferring the one enclosing `line`."""
    matches = [s for s in sym_by_name.get(name, []) if s.file_id == file_id]
    if not matches:
        return None
    for m in matches:
        if m.start_line <= line <= m.end_line:
            return m
    return matches[0]


def _build_module_index(files: list[File]) -> dict[str, File]:
    """Map module-ish paths (e.g. `foo.bar`, `foo/bar`, `utils`) to files."""
    index: dict[str, File] = {}
    for f in files:
        path = f.path
        suffix = Path(path).suffix
        stem = path[: -len(suffix)] if suffix else path

        # Python: `foo/bar.py` → `foo.bar`; `foo/__init__.py` → `foo`
        if f.language == "python":
            module = stem.replace("/", ".")
            index[module] = f
            if path.endswith("__init__.py"):
                index[module.rsplit(".", 1)[0]] = f
        else:
            # JS/TS: `foo/bar.ts` → `foo/bar`; `foo/index.ts` → `foo`
            index[stem] = f
            if path.endswith(("index.js", "index.jsx", "index.ts", "index.tsx", "index.mjs", "index.mts")):
                index[stem.rsplit("/", 1)[0]] = f
    return index


def _resolve_module_file(
    module: str,
    source_path: str,
    file_by_path: dict[str, File],
    module_index: dict[str, File],
) -> File | None:
    """Resolve an import module string to a file in the repo, if any."""
    if not module:
        return None

    candidates: list[str] = []

    if module.startswith("."):
        # Relative import: resolve against the source file's directory
        base_dir = str(Path(source_path).parent)
        leading_dots = len(module) - len(module.lstrip("."))
        rel = module[leading_dots:].lstrip("/")
        parts = base_dir.split("/")
        if leading_dots > 1:
            parts = parts[: -(leading_dots - 1)] if len(parts) >= leading_dots - 1 else []
        cand = "/".join(parts + ([rel] if rel else [])).lstrip("/")
        candidates.append(cand)
        candidates.append(cand + "/index")
    else:
        # Absolute module: try dotted and slashed forms
        cand = module.replace(".", "/")
        candidates.append(cand)
        candidates.append(cand.replace("/", "."))
        candidates.append(cand + "/index")
        candidates.append(module)

    # Try both slash and dotted forms of every candidate
    for cand in candidates:
        for form in (cand, cand.replace("/", "."), cand.replace(".", "/")):
            if form in module_index:
                return module_index[form]
            if form in file_by_path:
                return file_by_path[form]
    return None


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

async def _clear_repo_data(db: AsyncSession, repo_id: uuid.UUID) -> None:
    """Delete all indexed data for a repo (for re-indexing)."""
    await db.execute(
        delete(CodeEmbedding).where(CodeEmbedding.repo_id == repo_id)
    )
    await db.execute(
        delete(Dependency).where(Dependency.repo_id == repo_id)
    )
    await db.execute(
        delete(GeneratedDoc).where(GeneratedDoc.repo_id == repo_id)
    )
    await db.execute(
        delete(CodeSymbol).where(CodeSymbol.repo_id == repo_id)
    )
    await db.execute(delete(File).where(File.repo_id == repo_id))
    await db.commit()


def _create_symbol_record(
    symbol: ExtractedSymbol,
    file_id: uuid.UUID,
    repo_id: uuid.UUID,
    parent_id: uuid.UUID | None,
) -> CodeSymbol:
    """Map an ExtractedSymbol dataclass to a CodeSymbol ORM object."""
    return CodeSymbol(
        file_id=file_id,
        repo_id=repo_id,
        name=symbol.name,
        kind=symbol.kind,
        start_line=symbol.start_line,
        end_line=symbol.end_line,
        source_text=symbol.source_text,
        signature=symbol.signature,
        docstring=symbol.docstring,
        parent_id=parent_id,
    )
