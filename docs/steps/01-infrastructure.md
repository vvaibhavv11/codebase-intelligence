# Step 1: Infrastructure (COMPLETED)

## Status: DONE

Everything in this step has been implemented. This document exists for reference.

---

## What Was Built

### 1.1 Docker Compose (`docker-compose.yml`)

PostgreSQL 17 with the pgvector extension, running on port `5432`.

```yaml
services:
  db:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_USER: codebase
      POSTGRES_PASSWORD: codebase
      POSTGRES_DB: codebase_intelligence
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
```

**Start**: `docker compose up -d` from the repo root.
**Verify**: `docker compose exec db psql -U codebase -d codebase_intelligence -c "\dt"`

### 1.2 Backend Dependencies (`backend/pyproject.toml`)

Installed via `uv add`:

| Package | Purpose |
|---|---|
| `fastapi` | Web framework |
| `uvicorn[standard]` | ASGI server |
| `sqlalchemy` + `asyncpg` | Async ORM + PostgreSQL driver |
| `alembic` | Database migrations |
| `pgvector` | Vector similarity for SQLAlchemy |
| `openai` | OpenAI-compatible API client |
| `httpx` | Async HTTP (GitHub OAuth) |
| `gitpython` | Clone/pull repos |
| `tree-sitter` + language grammars | Code parsing |
| `pydantic-settings` + `python-dotenv` | Env-based config |

### 1.3 Environment Config (`.env.example`)

Template at repo root with all required variables:
- `DATABASE_URL` — async PostgreSQL connection string
- `OPENAI_API_BASE`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_EMBEDDING_MODEL`
- `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`
- `SECRET_KEY`, `FRONTEND_URL`, `BACKEND_URL`, `REPOS_DIR`

To use: `cp .env.example .env` and fill in real values.

### 1.4 Settings Module (`backend/src/backend/config.py`)

Pydantic `BaseSettings` class that loads from `.env`. Used globally as:
```python
from backend.config import settings
```

### 1.5 Database Layer (`backend/src/backend/db.py`)

- `engine` — async SQLAlchemy engine from `DATABASE_URL`
- `async_session` — session factory
- `Base` — `DeclarativeBase` for all models
- `get_db()` — FastAPI dependency that yields a session with auto commit/rollback

### 1.6 ORM Models (`backend/src/backend/models/`)

Six models across five files:

| Model | Table | Key Fields |
|---|---|---|
| `Repository` | `repositories` | github_url, name, owner, status (enum: pending/cloning/indexing/ready/error), indexed_at |
| `File` | `files` | repo_id (FK), path, language, content, content_hash |
| `CodeSymbol` | `code_symbols` | file_id (FK), repo_id (FK), name, kind, start/end_line, source_text, signature, docstring, parent_id (self-ref) |
| `CodeEmbedding` | `code_embeddings` | symbol_id (FK), repo_id (FK), embedding (Vector 1536), chunk_text, file_path, symbol_name, symbol_kind |
| `ChatSession` | `chat_sessions` | repo_id (FK), title |
| `ChatMessage` | `chat_messages` | session_id (FK), role, content |

All use UUID primary keys and cascade deletes.

### 1.7 Pydantic Schemas (`backend/src/backend/schemas/`)

Request/response models in three files:
- `repo.py` — `RepoConnect`, `RepoResponse`, `FileTreeNode`, `FileContentResponse`, `SymbolInfo`
- `search.py` — `SearchRequest`, `SearchResult`, `SearchResponse`
- `chat.py` — `ChatRequest`, `ChatMessageResponse`, `ChatSessionResponse`

### 1.8 API Routers (`backend/src/backend/routers/`)

Six routers, all mounted under `/api`:

| Router | Endpoints | Notes |
|---|---|---|
| `repos.py` | `POST /repos`, `GET /repos`, `GET /repos/{id}`, `DELETE /repos/{id}` | Fully functional |
| `index.py` | `POST /repos/{id}/index`, `GET /repos/{id}/index/status` | Calls `services.indexer.run_indexing` (NOT YET IMPLEMENTED) |
| `search.py` | `GET /search?q=&repo_id=&limit=` | Calls `services.search.search_code` (NOT YET IMPLEMENTED) |
| `chat.py` | `POST /chat` (SSE), `GET /chat/sessions`, `GET /chat/sessions/{id}` | Calls `services.rag.stream_rag_response` (NOT YET IMPLEMENTED) |
| `files.py` | `GET /repos/{id}/tree`, `GET /repos/{id}/files/{path}` | Fully functional (reads from DB) |
| `auth.py` | `GET /auth/github/login`, `GET /auth/github/callback` | Fully functional |

### 1.9 FastAPI App (`backend/src/backend/main.py`)

- Lifespan handler creates pgvector extension on startup
- CORS configured for `FRONTEND_URL`
- All routers registered
- `GET /api/health` endpoint
- Run via: `uv run python src/backend/main.py`

### 1.10 Alembic Migrations

- `alembic.ini` configured with async DB URL and `prepend_sys_path = . src`
- `alembic/env.py` rewritten for async (uses `async_engine_from_config`)
- Initial migration `454e27362b68_initial_schema.py` creates all tables + pgvector extension
- Migration applied: all 6 tables exist in the database

### 1.11 Partial Service

- `services/github.py` — Implemented: `clone_repo()`, `get_default_branch()`, `walk_source_files()`

---

## What's NOT Done Yet

The following services are imported by routers but **do not exist**:

1. `services/parser.py` — Tree-sitter code parsing → See **Step 2**
2. `services/embeddings.py` — Embedding generation → See **Step 3**
3. `services/indexer.py` — Orchestrates clone → parse → embed → store → See **Step 3**
4. `services/search.py` — pgvector similarity search → See **Step 4**
5. `services/rag.py` — RAG pipeline with LLM streaming → See **Step 5**
6. **Entire frontend** → See **Step 6**
