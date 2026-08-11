from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks

from backend.models.repository import Repository, RepoStatus
from backend.routers.deps import require_repo

router = APIRouter(tags=["indexing"])


@router.post("/repos/{repo_id}/index")
async def trigger_index(
    background_tasks: BackgroundTasks,
    repo: Repository = Depends(require_repo),
):
    repo_id = repo.id
    if repo.status in (RepoStatus.cloning, RepoStatus.indexing):
        raise HTTPException(status_code=409, detail="Indexing already in progress")

    # NOTE: keep this endpoint read-only. The background task owns all status
    # mutations and commits them itself; an uncommitted UPDATE here would hold
    # a row lock the task blocks on while this request's post-yield commit is
    # chained behind the task's execution (permanent deadlock).
    from backend.services.indexer import run_indexing

    background_tasks.add_task(run_indexing, repo_id)

    return {"status": "indexing_started", "repo_id": str(repo_id)}


@router.get("/repos/{repo_id}/index/status")
async def index_status(repo: Repository = Depends(require_repo)):
    return {
        "repo_id": str(repo.id),
        "status": repo.status.value,
        "error_message": repo.error_message,
        "indexed_at": repo.indexed_at.isoformat() if repo.indexed_at else None,
    }
