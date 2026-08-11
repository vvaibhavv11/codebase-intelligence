from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db import get_db
from backend.models.repository import Repository, RepoStatus
from backend.models.chat import ChatSession, ChatMessage
from backend.models.user import User
from backend.routers.deps import get_current_user, require_repo
from backend.schemas.chat import (
    ChatRequest,
    ChatSessionResponse,
    ChatSessionListResponse,
    ChatMessageResponse,
    ChatSessionUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    repo = await db.get(Repository, body.repo_id)
    if not repo or repo.user_id != user.id:
        raise HTTPException(status_code=404, detail="Repository not found")
    if repo.status != RepoStatus.ready:
        raise HTTPException(status_code=400, detail="Repository not yet indexed")

    # Get or create session
    if body.session_id:
        session = await db.get(ChatSession, body.session_id)
        if not session or session.repo_id != repo.id:
            raise HTTPException(status_code=404, detail="Chat session not found")
    else:
        session = ChatSession(repo_id=body.repo_id, title=body.message[:100])
        db.add(session)
        await db.flush()

    # Auto-title: untitled sessions get a title from the first message
    if session.title is None:
        first_line = body.message.splitlines()[0].strip() if body.message.strip() else ""
        session.title = (first_line or body.message)[:100]
        db.add(session)

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
        marker = ""
        try:
            async for kind, payload in stream_rag_response(
                db, repo.id, session.id, body.message
            ):
                if await request.is_disconnected():
                    logger.info("Client disconnected, stopping stream")
                    break
                if kind == "refs":
                    marker = payload.get("marker", "")
                    yield (
                        "event: references\n"
                        f"data: {json.dumps({'references': payload.get('references', [])})}\n\n"
                    )
                else:
                    full_response.append(payload)
                    yield f"data: {json.dumps({'text': payload})}\n\n"
        except Exception as e:
            logger.exception("Chat streaming failed")
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        finally:
            # Save assistant message — even a partial one (client aborted mid-stream)
            if full_response:
                try:
                    assistant_msg = ChatMessage(
                        session_id=session.id,
                        role="assistant",
                        content="".join(full_response) + marker,
                    )
                    db.add(assistant_msg)
                    await db.commit()
                except Exception:
                    logger.exception("Failed to save assistant message")
                    await db.rollback()

        # Only emit the done event if the client is still connected
        if not await request.is_disconnected():
            yield f"event: done\ndata: {json.dumps({'session_id': str(session.id)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/chat/sessions", response_model=ChatSessionListResponse)
async def list_sessions(
    repo_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    _repo: Repository = Depends(require_repo),
):
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.repo_id == repo_id)
        .order_by(ChatSession.created_at.desc())
    )
    sessions = result.scalars().all()
    return ChatSessionListResponse(sessions=sessions)

@router.get("/chat/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(selectinload(ChatSession.messages))
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    repo = await db.get(Repository, session.repo_id)
    if not repo or repo.user_id != user.id:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return session


@router.patch("/chat/sessions/{session_id}", response_model=ChatSessionResponse)
async def rename_session(
    session_id: uuid.UUID,
    body: ChatSessionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = await db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    repo = await db.get(Repository, session.repo_id)
    if not repo or repo.user_id != user.id:
        raise HTTPException(status_code=404, detail="Chat session not found")

    session.title = body.title
    await db.commit()

    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(selectinload(ChatSession.messages))
    )
    return result.scalar_one()


@router.delete("/chat/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = await db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    repo = await db.get(Repository, session.repo_id)
    if not repo or repo.user_id != user.id:
        raise HTTPException(status_code=404, detail="Chat session not found")

    await db.delete(session)
    await db.commit()
