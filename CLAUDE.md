# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project Overview

`codebase-intelligence` — a monorepo for a codebase analysis/intelligence tool.
Connect a GitHub repo, index its source code with tree-sitter, search it semantically (pgvector), and chat about it (RAG + LLM).

- **`backend/`** — Python 3.13 FastAPI API, managed with [uv](https://docs.astral.sh/uv/)
- **`frontend/`** — Next.js 16 (App Router, TypeScript, Tailwind CSS 4, Turbopack), managed with [bun](https://bun.sh/)

## Architecture

```
Next.js (Dashboard, Repo Browser, Code Viewer, AI Chat, Search, GitHub OAuth)
        │
        ▼
FastAPI (repos CRUD, indexing trigger, file tree/content, semantic search, SSE chat, OAuth)
        │
        ├── Tree-sitter (symbol extraction: functions/classes/methods)
        ├── OpenAI-compatible API (embeddings + chat completions)
        └── SQLAlchemy async → PostgreSQL + pgvector (embeddings in `code_embeddings`)
```

## Current Build Status

| Area | Status |
|---|---|
| Docker Compose (pgvector/pgvector:pg17) | **Done** — `docker compose up -d` |
| Backend infra (FastAPI, config, db, CORS) | **Done** |
| ORM models (repos, files, symbols, embeddings, chat) | **Done** |
| Alembic migrations (initial schema applied) | **Done** |
| Pydantic schemas + all 6 routers | **Done** (routers import services) |
| `services/github.py` (clone/pull/walk files) | **Done** |
| `services/parser.py` (tree-sitter symbol extraction) | **Done** |
| `services/embeddings.py` (OpenAI-compatible embeddings) | **TODO** — see `docs/steps/03-embeddings-and-indexing.md` |
| `services/indexer.py` (clone→parse→embed→store pipeline) | **TODO** — see `docs/steps/03-embeddings-and-indexing.md` |
| `services/search.py` (pgvector semantic search) | **TODO** — see `docs/steps/04-semantic-search.md` |
| `services/rag.py` (RAG chat, SSE streaming) | **TODO** — see `docs/steps/05-rag-chat.md` |
| Frontend (dashboard, browser, viewer, chat, search, OAuth) | **TODO** — see `docs/steps/06-frontend.md` |
| Phase 2 (dependency graph, git diffs, docs generation) | **TODO** — see `docs/steps/07-phase2-advanced.md` |

> **IMPORTANT**: The routers `index.py`, `search.py`, and `chat.py` import services that do NOT exist yet (`services.indexer.run_indexing`, `services.search.search_code`, `services.rag.stream_rag_response`). The API will not fully start / endpoints will fail until those services are implemented. Do NOT remove the imports — implement the services per the step docs.

## Step-by-Step Implementation Guides

Detailed, sequential implementation instructions live in `docs/steps/`:

| Guide | Covers |
|---|---|
| `01-infrastructure.md` | Docker, deps, config, models, routers, migrations (**completed**) |
| `02-tree-sitter-parsing.md` | `services/parser.py` — symbol extraction for Python/JS/TS |
| `03-embeddings-and-indexing.md` | `services/embeddings.py` + `services/indexer.py` |
| `04-semantic-search.md` | `services/search.py` — pgvector cosine similarity |
| `05-rag-chat.md` | `services/rag.py` — retrieval + LLM streaming |
| `06-frontend.md` | Dashboard, repo browser, code viewer (shiki), search, chat (SSE), GitHub OAuth |
| `07-phase2-advanced.md` | Dependency graph, git diff analysis, doc generation |

Build order: follow the guides 1→7 in sequence. Each guide has a "Definition of Done" checklist.

## Build & Run

### Database

```bash
docker compose up -d          # pgvector Postgres on :5432
docker compose exec db psql -U codebase -d codebase_intelligence -c "\dt"
```

### Backend (uv)

```bash
cd backend
cp ../.env.example .env       # fill in real values (API key, GitHub OAuth)
uv sync                       # Install deps into .venv (first time)
uv run alembic upgrade head   # Apply migrations
uv run python src/backend/main.py   # Run app on http://localhost:8000
uv add <package>              # Add a dependency
```

### Frontend (bun)

```bash
cd frontend
bun install                   # Install deps
bun run dev                   # Dev server on http://localhost:3000
bun run build                 # Production build
bun run start                 # Serve production build
```

> **IMPORTANT**: Do NOT prefix Next.js scripts with `bun --bun` (e.g. `bun --bun next dev`). Bun 1.3.13's runtime segfaults running Next.js 16's Turbopack page-data collection. Bun is used only as the package manager; Next.js runs on the Node runtime.

## Project Layout

```
├── docker-compose.yml        # pgvector Postgres (port 5432)
├── .env.example              # env template — copy to .env / frontend/.env.local
├── docs/
│   └── steps/                # Step-by-step implementation guides (01-07)
├── backend/                  # Python API (uv)
│   ├── pyproject.toml        # uv project config + deps
│   ├── .python-version       # Python 3.13
│   ├── alembic/              # migrations (env.py is async)
│   ├── alembic.ini           # prepend_sys_path = . src
│   ├── repos/                # cloned repos (gitignored)
│   └── src/backend/
│       ├── main.py           # FastAPI app + router registration
│       ├── config.py         # pydantic-settings (reads .env)
│       ├── db.py             # async engine/session/Base
│       ├── models/           # SQLAlchemy models (6 tables)
│       ├── schemas/          # Pydantic request/response models
│       ├── routers/          # repos, index, search, chat, files, auth
│       └── services/         # github (done); parser, embeddings, indexer, search, rag (TODO)
└── frontend/                 # Next.js app (bun)
    └── src/app/              # App Router pages
```

## Key Conventions

- **Python deps**: declare in `backend/pyproject.toml` via `uv add` — never pip-install directly
- **Node deps**: install with `bun add <package>` — never npm/pnpm
- **Python version**: pinned in `backend/.python-version` (3.13) — do not change
- **TypeScript**: strict, import alias `@/*` maps to `frontend/src/*`
- **Git**: monorepo with a single repo at the root; commit from the root
- **Database**: PostgreSQL + pgvector only (Docker Compose); use Alembic for all schema changes — never hand-edit tables
- **LLM**: OpenAI-compatible endpoint configured via `OPENAI_API_BASE`/`OPENAI_API_KEY` in `.env`
- **Streaming**: chat responses stream via SSE (`text/event-stream`); frontend parses `data:` / `event: done` events
- **Embeddings**: 1536-dim vector in `code_embeddings.embedding`, cosine distance (`<=>`) for search
- **Indexing runs as a FastAPI BackgroundTask** with its own DB session (`async_session`) — never reuse request-scoped sessions
- **Status enum**: `pending → cloning → indexing → ready` (or `error`), surfaced via `GET /api/repos/{id}/index/status`
