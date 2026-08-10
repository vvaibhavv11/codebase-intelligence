from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import get_db
from backend.models.repository import Repository, RepoStatus
from backend.models.user import User
from backend.routers.deps import get_current_user
from backend.schemas.search import SearchResponse

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchResponse)
async def semantic_search(
    q: str = Query(..., min_length=1),
    repo_id: uuid.UUID = Query(...),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    repo = await db.get(Repository, repo_id)
    if not repo or repo.user_id != user.id:
        raise HTTPException(status_code=404, detail="Repository not found")
    if repo.status != RepoStatus.ready:
        raise HTTPException(status_code=400, detail="Repository not yet indexed")

    from backend.services.search import search_code

    results = await search_code(db, repo_id, q, limit)

    return SearchResponse(
        query=q,
        results=results,
        total=len(results),
    )
