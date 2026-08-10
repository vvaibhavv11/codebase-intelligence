from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db import get_db
from backend.models.repository import Repository, RepoStatus
from backend.models.chat import ChatSession, ChatMessage
from backend.schemas.chat import (
    ChatRequest,
    ChatSessionResponse,
    ChatSessionListResponse,
    ChatMessageResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


@router.post("/chat")
async def chat(body: ChatRequest, db: AsyncSession = Depends(get_db)):
    repo = await db.get(Repository, body.repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    if repo.status != RepoStatus.ready:
        raise HTTPException(status_code=400, detail="Repository not yet indexed")

    # Get or create session
    if body.session_id:
        session = await db.get(ChatSession, body.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")
    else:
        session = ChatSession(repo_id=body.repo_id, title=body.message[:100])
        db.add(session)
        await db.flush()

    # Save user message
    user_msg = ChatMessage(
        session_id=session.id,
        role="user",
        content=body.message,
    )
    db.add(user_msg)
    await db.flush()
    await db.commit()

    # Stream the response
    from backend.services.rag import stream_rag_response

    async def event_stream():
        full_response = []
        try:
            async for chunk in stream_rag_response(db, repo.id, session.id, body.message):
                full_response.append(chunk)
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except Exception as e:
            logger.exception("Chat streaming failed")
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

        # Save assistant message
        try:
            assistant_msg = ChatMessage(
                session_id=session.id,
                role="assistant",
                content="".join(full_response),
            )
            db.add(assistant_msg)
            await db.commit()
        except Exception:
            logger.exception("Failed to save assistant message")
            await db.rollback()

        yield f"event: done\ndata: {json.dumps({'session_id': str(session.id)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/chat/sessions", response_model=ChatSessionListResponse)
async def list_sessions(
    repo_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.repo_id == repo_id)
        .order_by(ChatSession.created_at.desc())
    )
    sessions = result.scalars().all()
    return ChatSessionListResponse(sessions=sessions)


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(selectinload(ChatSession.messages))
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return session
