from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import get_db
from backend.models.repository import Repository, RepoStatus

router = APIRouter(tags=["indexing"])


@router.post("/repos/{repo_id}/index")
async def trigger_index(
    repo_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    repo = await db.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if repo.status in (RepoStatus.cloning, RepoStatus.indexing):
        raise HTTPException(status_code=409, detail="Indexing already in progress")

    repo.status = RepoStatus.cloning
    repo.error_message = None
    await db.flush()

    # Run indexing in background
    from backend.services.indexer import run_indexing

    background_tasks.add_task(run_indexing, repo_id)

    return {"status": "indexing_started", "repo_id": str(repo_id)}


@router.get("/repos/{repo_id}/index/status")
async def index_status(repo_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    repo = await db.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    return {
        "repo_id": str(repo.id),
        "status": repo.status.value,
        "error_message": repo.error_message,
        "indexed_at": repo.indexed_at.isoformat() if repo.indexed_at else None,
    }
