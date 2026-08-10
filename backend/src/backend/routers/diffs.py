from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import get_db
from backend.models.repository import Repository
from backend.routers.deps import require_repo
from backend.schemas.diff import CommitDiff, CommitSummary, DiffAnalyzeRequest
from backend.services.diffs import (
    get_commit_diff,
    get_recent_commits,
    get_repo_dir,
    stream_diff_analysis,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["diffs"])


@router.get("/repos/{repo_id}/commits", response_model=list[CommitSummary])
async def list_commits(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    repo: Repository = Depends(require_repo),
):
    repo_dir = get_repo_dir(repo)
    if not repo_dir.exists():
        raise HTTPException(status_code=400, detail="Repository not cloned locally yet")

    try:
        return get_recent_commits(repo_dir, max_commits=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read commit history: {e}")


@router.get("/repos/{repo_id}/commits/{sha}", response_model=CommitDiff)
async def get_commit(
    sha: str,
    db: AsyncSession = Depends(get_db),
    repo: Repository = Depends(require_repo),
):
    repo_dir = get_repo_dir(repo)
    if not repo_dir.exists():
        raise HTTPException(status_code=400, detail="Repository not cloned locally yet")

    try:
        return get_commit_diff(repo_dir, sha)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read commit: {e}")


@router.post("/repos/{repo_id}/diff/analyze")
async def analyze_diff(
    body: DiffAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    repo: Repository = Depends(require_repo),
):
    async def event_stream():
        try:
            async for chunk in stream_diff_analysis(db, repo, body.commit_sha, body.file_path):
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except Exception as e:
            logger.exception("Diff analysis streaming failed")
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
