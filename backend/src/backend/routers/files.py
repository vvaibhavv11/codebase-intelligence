from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import get_db
from backend.models.repository import Repository
from backend.models.file import File
from backend.models.symbol import CodeSymbol
from backend.routers.deps import require_repo
from backend.schemas.repo import FileTreeNode, FileContentResponse, SymbolInfo

router = APIRouter(tags=["files"])


@router.get("/repos/{repo_id}/tree", response_model=list[FileTreeNode])
async def get_file_tree(
    repo: Repository = Depends(require_repo),
    db: AsyncSession = Depends(get_db),
):
    repo_id = repo.id

    result = await db.execute(
        select(File)
        .where(File.repo_id == repo_id)
        .order_by(File.path)
    )
    files = result.scalars().all()

    return build_tree(files)


def build_tree(files) -> list[FileTreeNode]:
    """Build a nested tree structure from flat file paths."""
    root: dict = {}

    for f in files:
        parts = f.path.split("/")
        current = root
        for i, part in enumerate(parts):
            if part not in current:
                current[part] = {}
            current = current[part]
            if i == len(parts) - 1:
                current["__file__"] = f

    def to_nodes(tree: dict, prefix: str = "") -> list[FileTreeNode]:
        nodes = []
        for key, value in sorted(tree.items()):
            if key == "__file__":
                continue
            path = f"{prefix}/{key}" if prefix else key
            if "__file__" in value:
                f = value["__file__"]
                nodes.append(
                    FileTreeNode(name=key, path=path, type="file", language=f.language)
                )
            else:
                children = to_nodes(value, path)
                nodes.append(
                    FileTreeNode(name=key, path=path, type="directory", children=children)
                )
        return nodes

    return to_nodes(root)


@router.get("/repos/{repo_id}/files/{file_path:path}", response_model=FileContentResponse)
async def get_file_content(
    file_path: str,
    repo: Repository = Depends(require_repo),
    db: AsyncSession = Depends(get_db),
):
    repo_id = repo.id

    result = await db.execute(
        select(File).where(File.repo_id == repo_id, File.path == file_path)
    )
    file = result.scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    # Get symbols for this file
    sym_result = await db.execute(
        select(CodeSymbol)
        .where(CodeSymbol.file_id == file.id)
        .order_by(CodeSymbol.start_line)
    )
    symbols = sym_result.scalars().all()

    return FileContentResponse(
        path=file.path,
        language=file.language,
        content=file.content or "",
        symbols=[SymbolInfo.model_validate(s) for s in symbols],
    )
