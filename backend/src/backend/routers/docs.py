from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import get_db
from backend.models.generated_doc import GeneratedDoc
from backend.models.repository import Repository
from backend.models.symbol import CodeSymbol
from backend.schemas.docs import GeneratedDocListResponse, GeneratedDocResponse
from backend.services.docs import (
    generate_repo_readme,
    generate_symbol_doc,
    get_cached_doc,
    save_doc,
)

router = APIRouter(tags=["docs"])


@router.post("/repos/{repo_id}/docs/readme", response_model=GeneratedDocResponse)
async def generate_readme(repo_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    repo = await db.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Return cached version if present
    cached = await get_cached_doc(db, repo_id, "readme")
    if cached:
        return cached

    try:
        content = await generate_repo_readme(db, repo)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate README: {e}")

    return await save_doc(db, repo_id, "readme", content)


@router.post("/symbols/{symbol_id}/doc", response_model=GeneratedDocResponse)
async def generate_symbol_docs(symbol_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    symbol = await db.get(CodeSymbol, symbol_id)
    if not symbol:
        raise HTTPException(status_code=404, detail="Symbol not found")

    cached = await get_cached_doc(db, symbol.repo_id, "symbol_doc", symbol_id)
    if cached:
        return cached

    try:
        content = await generate_symbol_doc(db, symbol)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate doc: {e}")

    return await save_doc(db, symbol.repo_id, "symbol_doc", content, symbol_id)


@router.get("/repos/{repo_id}/docs", response_model=GeneratedDocListResponse)
async def list_docs(repo_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    repo = await db.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    result = await db.execute(
        select(GeneratedDoc)
        .where(GeneratedDoc.repo_id == repo_id)
        .order_by(GeneratedDoc.created_at.desc())
    )
    docs = result.scalars().all()
    return GeneratedDocListResponse(docs=docs)
