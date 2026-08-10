from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import get_db
from backend.models.dependency import Dependency
from backend.models.file import File
from backend.models.repository import Repository
from backend.models.symbol import CodeSymbol
from backend.schemas.graph import GraphNode, GraphEdge, GraphResponse

router = APIRouter(tags=["dependencies"])


def _sym_node(sym: CodeSymbol, file_path: str) -> GraphNode:
    return GraphNode(
        id=f"sym:{sym.id}",
        name=sym.name,
        kind=sym.kind,
        file_path=file_path,
        lines=(sym.start_line, sym.end_line),
    )


def _file_node(file: File) -> GraphNode:
    return GraphNode(
        id=f"file:{file.id}",
        name=file.path.rsplit("/", 1)[-1],
        kind="file",
        file_path=file.path,
        lines=None,
    )


def _edge(dep: Dependency) -> GraphEdge:
    source = f"sym:{dep.source_symbol_id}" if dep.source_symbol_id else f"file:{dep.source_file_id}"
    target = f"sym:{dep.target_symbol_id}" if dep.target_symbol_id else f"file:{dep.target_file_id}"
    return GraphEdge(source=source, target=target, kind=dep.kind)


async def _file_paths(db: AsyncSession, repo_id: uuid.UUID) -> dict[uuid.UUID, str]:
    result = await db.execute(select(File).where(File.repo_id == repo_id))
    return {f.id: f.path for f in result.scalars().all()}


@router.get("/repos/{repo_id}/graph", response_model=GraphResponse)
async def get_dependency_graph(repo_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    repo = await db.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    file_paths = await _file_paths(db, repo_id)

    sym_result = await db.execute(
        select(CodeSymbol).where(CodeSymbol.repo_id == repo_id)
    )
    symbols = sym_result.scalars().all()

    file_result = await db.execute(
        select(File).where(File.repo_id == repo_id)
    )
    files = file_result.scalars().all()

    dep_result = await db.execute(
        select(Dependency).where(Dependency.repo_id == repo_id)
    )
    deps = dep_result.scalars().all()

    nodes: list[GraphNode] = [_file_node(f) for f in files]
    nodes += [_sym_node(s, file_paths.get(s.file_id, "")) for s in symbols]
    edges: list[GraphEdge] = [_edge(d) for d in deps if d.source_symbol_id or d.source_file_id]

    return GraphResponse(nodes=nodes, edges=edges)


async def _related_nodes(
    db: AsyncSession,
    repo_id: uuid.UUID,
    symbol_id: uuid.UUID,
    direction: str,
) -> list[GraphNode]:
    """Return nodes related to a symbol — `dependents` (reverse edges) or `dependencies` (forward edges)."""
    symbol = await db.get(CodeSymbol, symbol_id)
    if not symbol:
        raise HTTPException(status_code=404, detail="Symbol not found")
    if symbol.repo_id != repo_id:
        raise HTTPException(status_code=404, detail="Symbol not found in this repo")

    if direction == "dependents":
        stmt = select(Dependency).where(
            Dependency.repo_id == repo_id,
            Dependency.target_symbol_id == symbol_id,
        )
    else:
        stmt = select(Dependency).where(
            Dependency.repo_id == repo_id,
            Dependency.source_symbol_id == symbol_id,
        )
    dep_result = await db.execute(stmt)
    deps = dep_result.scalars().all()

    file_paths = await _file_paths(db, repo_id)

    nodes: list[GraphNode] = []
    seen: set[str] = set()
    for dep in deps:
        if direction == "dependents":
            if dep.source_symbol_id:
                src = await db.get(CodeSymbol, dep.source_symbol_id)
                if src and str(src.id) not in seen:
                    seen.add(str(src.id))
                    nodes.append(_sym_node(src, file_paths.get(src.file_id, "")))
            elif dep.source_file_id:
                f = await db.get(File, dep.source_file_id)
                if f and f"file:{f.id}" not in seen:
                    seen.add(f"file:{f.id}")
                    nodes.append(_file_node(f))
        else:
            if dep.target_symbol_id:
                tgt = await db.get(CodeSymbol, dep.target_symbol_id)
                if tgt and str(tgt.id) not in seen:
                    seen.add(str(tgt.id))
                    nodes.append(_sym_node(tgt, file_paths.get(tgt.file_id, "")))
            elif dep.target_file_id:
                f = await db.get(File, dep.target_file_id)
                if f and f"file:{f.id}" not in seen:
                    seen.add(f"file:{f.id}")
                    nodes.append(_file_node(f))

    return nodes


@router.get("/repos/{repo_id}/symbols/{symbol_id}/dependents", response_model=list[GraphNode])
async def get_dependents(
    repo_id: uuid.UUID, symbol_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    return await _related_nodes(db, repo_id, symbol_id, "dependents")


@router.get("/repos/{repo_id}/symbols/{symbol_id}/dependencies", response_model=list[GraphNode])
async def get_dependencies(
    repo_id: uuid.UUID, symbol_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    return await _related_nodes(db, repo_id, symbol_id, "dependencies")
