from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import get_db
from backend.models.repository import Repository, RepoStatus
from backend.schemas.repo import RepoConnect, RepoResponse, RepoListResponse

router = APIRouter(tags=["repositories"])


def parse_github_url(url: str) -> tuple[str, str]:
    """Extract owner and repo name from a GitHub URL."""
    pattern = r"github\.com[/:]([^/]+)/([^/.]+)"
    match = re.search(pattern, url.strip().rstrip("/"))
    if not match:
        raise HTTPException(status_code=400, detail="Invalid GitHub URL")
    return match.group(1), match.group(2)


@router.post("/repos", response_model=RepoResponse, status_code=201)
async def connect_repo(body: RepoConnect, db: AsyncSession = Depends(get_db)):
    owner, name = parse_github_url(body.github_url)

    # Normalize URL
    github_url = f"https://github.com/{owner}/{name}"

    # Check if already exists
    existing = await db.execute(
        select(Repository).where(Repository.github_url == github_url)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Repository already connected")

    repo = Repository(
        github_url=github_url,
        name=name,
        owner=owner,
        status=RepoStatus.pending,
    )
    db.add(repo)
    await db.flush()
    await db.refresh(repo)
    return repo


@router.get("/repos", response_model=RepoListResponse)
async def list_repos(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Repository).order_by(Repository.created_at.desc())
    )
    repos = result.scalars().all()
    return RepoListResponse(repositories=repos)


@router.get("/repos/{repo_id}", response_model=RepoResponse)
async def get_repo(repo_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    repo = await db.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


@router.delete("/repos/{repo_id}", status_code=204)
async def delete_repo(repo_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    repo = await db.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    await db.delete(repo)
