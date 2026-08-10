# Step 5: RAG Chat Service

## Goal

Create `backend/src/backend/services/rag.py` — a Retrieval-Augmented Generation service that answers questions about a codebase by retrieving relevant code via semantic search and streaming LLM responses.

---

## Prerequisites

- Step 1 complete (DB, chat models)
- Step 3 complete (`services/embeddings.py`)
- Step 4 complete (`services/search.py`)
- At least one repository successfully indexed

---

## What to Build

### File: `backend/src/backend/services/rag.py`

### 5.1 Architecture

```
User question
    ↓
Embed question → pgvector similarity search
    ↓
Retrieve top-K relevant code chunks
    ↓
Build system prompt with code context
    ↓
Load recent conversation history
    ↓
Call LLM (streaming) → yield chunks
    ↓
Full response stored in chat_messages
```

### 5.2 Context Retrieval

Reuse the search service to find relevant code, but return more detail:

```python
async def _retrieve_context(
    db: AsyncSession,
    repo_id: uuid.UUID,
    query: str,
    top_k: int = 10,
) -> list[dict]:
    """Retrieve the most relevant code chunks for a query.

    Returns a list of dicts with: file_path, symbol_name, symbol_kind,
    source_text, start_line, end_line, score.
    """
    from backend.services.search import search_code

    results = await search_code(db, repo_id, query, limit=top_k)

    # For each result, fetch the full source text from code_symbols
    context_chunks = []
    for r in results:
        symbol = await db.get(CodeSymbol, r.symbol_id)
        if symbol:
            context_chunks.append({
                "file_path": r.file_path,
                "symbol_name": symbol.name,
                "symbol_kind": symbol.kind,
                "source_text": symbol.source_text,
                "start_line": symbol.start_line,
                "end_line": symbol.end_line,
                "score": r.score,
            })

    return context_chunks
```

### 5.3 System Prompt Construction

Build a system prompt that gives the LLM context about the codebase:

```python
def _build_system_prompt(repo_name: str, context_chunks: list[dict]) -> str:
    """Build the system prompt with retrieved code context."""

    context_text = ""
    for i, chunk in enumerate(context_chunks, 1):
        context_text += f"\n--- Code Chunk {i} ---\n"
        context_text += f"File: {chunk['file_path']} (lines {chunk['start_line']}-{chunk['end_line']})\n"
        context_text += f"Type: {chunk['symbol_kind']} | Name: {chunk['symbol_name']}\n"
        context_text += f"```\n{chunk['source_text']}\n```\n"

    return f"""You are a code intelligence assistant analyzing the repository "{repo_name}".

You answer questions about the codebase based on the indexed source code provided below.
When referencing code, always mention the file path and line numbers.
If the provided context doesn't contain enough information to answer, say so clearly.
Be precise, technical, and concise.

## Relevant Code Context
{context_text}"""
```

### 5.4 Conversation History

Load previous messages from the chat session to maintain context:

```python
async def _load_conversation_history(
    db: AsyncSession,
    session_id: uuid.UUID,
    max_messages: int = 20,
) -> list[dict]:
    """Load recent conversation messages for context."""
    from sqlalchemy import select

    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(max_messages)
    )
    result = await db.execute(stmt)
    messages = list(reversed(result.scalars().all()))

    return [
        {"role": msg.role, "content": msg.content}
        for msg in messages
    ]
```

### 5.5 Streaming LLM Response

```python
from openai import AsyncOpenAI
from backend.config import settings

async def stream_rag_response(
    db: AsyncSession,
    repo_id: uuid.UUID,
    session_id: uuid.UUID,
    user_message: str,
) -> AsyncGenerator[str, None]:
    """Stream a RAG response for a user's question about a codebase.

    Yields text chunks as they arrive from the LLM.
    """
    # 1. Get repo info
    repo = await db.get(Repository, repo_id)
    if not repo:
        yield "Error: Repository not found."
        return

    # 2. Retrieve relevant code context
    context_chunks = await _retrieve_context(db, repo_id, user_message)

    # 3. Build messages array
    system_prompt = _build_system_prompt(f"{repo.owner}/{repo.name}", context_chunks)

    messages = [{"role": "system", "content": system_prompt}]

    # 4. Add conversation history (excluding the current message, which was already saved)
    history = await _load_conversation_history(db, session_id)
    # The last message in history is the user's current message — skip it since we're about to add it
    if history and history[-1]["role"] == "user":
        history = history[:-1]
    messages.extend(history)

    # 5. Add current user message
    messages.append({"role": "user", "content": user_message})

    # 6. Call LLM with streaming
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_api_base,
    )

    stream = await client.chat.completions.create(
        model=settings.openai_model,
        messages=messages,
        stream=True,
        temperature=0.1,  # Low temperature for factual code analysis
        max_tokens=4096,
    )

    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
```

### 5.6 How the Router Calls This

The router at `routers/chat.py` already has this wired up:

```python
from backend.services.rag import stream_rag_response

async def event_stream():
    full_response = []
    async for chunk in stream_rag_response(db, repo.id, session.id, body.message):
        full_response.append(chunk)
        yield f"data: {chunk}\n\n"

    # Save assistant message
    assistant_msg = ChatMessage(
        session_id=session.id,
        role="assistant",
        content="".join(full_response),
    )
    db.add(assistant_msg)
    await db.commit()

    yield f"event: done\ndata: {str(session.id)}\n\n"

return StreamingResponse(event_stream(), media_type="text/event-stream")
```

---

## Prompt Engineering Notes

### Good System Prompt Practices

1. **Be specific about the role**: "You are a code intelligence assistant analyzing repository X"
2. **Provide structured context**: file paths, line numbers, symbol types
3. **Set boundaries**: "If the context doesn't contain enough info, say so"
4. **Low temperature**: 0.1 for factual code analysis, higher for creative tasks

### Handling Different Question Types

The system prompt should handle these patterns:

| Question Pattern | Example | Expected Behavior |
|---|---|---|
| Explain | "Explain the authenticate function" | Describe what it does, step by step |
| Locate | "Where is authentication handled?" | Point to specific files and functions |
| Impact | "What breaks if I change the User model?" | Look at imports and references in context |
| Search | "Find all API endpoints" | List matching symbols from context |
| Document | "Generate docs for the Calculator class" | Write structured documentation |

### Context Window Management

LLM context windows are limited. If too many code chunks are retrieved:

1. **Prioritize by score**: Already sorted by cosine similarity
2. **Truncate long sources**: Show first/last N lines for very long functions
3. **Limit total context**: Keep total context under ~60% of the model's context window
4. **Summary fallback**: For very large responses, switch to summarization

Rough guide:
- `gpt-4o`: 128K context window → ~80K for code context is safe
- Most code symbols are < 100 lines → 10 chunks ≈ 5-10K tokens of context

---

## Error Handling

1. **LLM API errors** — catch `openai.APIError` and similar. Yield a user-friendly error message instead of crashing the stream.
2. **Empty context** — if no relevant code is found, inform the user: "I couldn't find relevant code for your question. Try rephrasing or make sure the repository is fully indexed."
3. **Token limits** — if the assembled prompt is too large, reduce `top_k` and retry.
4. **Network timeouts** — set a timeout on the OpenAI client.

```python
try:
    stream = await client.chat.completions.create(...)
    async for chunk in stream:
        ...
except Exception as e:
    logger.exception("LLM streaming failed")
    yield f"\n\nError: Failed to get response from LLM: {str(e)}"
```

---

## Testing

### 1. Manual curl test (streaming)

```bash
# Start a chat
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"repo_id": "...", "message": "Explain the main entry point of this project"}' \
  --no-buffer
```

You should see SSE events streaming in:
```
data: The
data:  main
data:  entry
data:  point
data:  of
data:  this
data:  project
data:  is
...
event: done
data: <session-id>
```

### 2. Follow-up in same session

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"repo_id": "...", "session_id": "<from-previous>", "message": "What does the second function do?"}' \
  --no-buffer
```

### 3. Check stored messages

```bash
curl http://localhost:8000/api/chat/sessions/<session-id>
```

Should show the full conversation with both user and assistant messages.

---

## Definition of Done

- [ ] `services/rag.py` exists with `stream_rag_response()`
- [ ] Retrieves relevant code context using semantic search
- [ ] Builds a system prompt with code context and repo metadata
- [ ] Includes conversation history for multi-turn chat
- [ ] Streams LLM response chunks via SSE
- [ ] `POST /api/chat` returns streaming events
- [ ] Full response is stored in `chat_messages` table
- [ ] Errors are caught and yield user-friendly messages
- [ ] Follow-up questions within a session maintain context
