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
        ├── Tree-sitter (symbol extraction: functions/classes/methods + imports/calls/inheritance)
        ├── NVIDIA nemotron-3-embed-1b (embeddings, 2048 dims)
        ├── OpenAI-compatible chat API (vcliproxy — deepseek-v4-flash-free)
        └── SQLAlchemy async → PostgreSQL + pgvector (embeddings in `code_embeddings`)
```

## Current Build Status

| Area | Status |
|---|---|
| Docker Compose (pgvector/pgvector:pg17) | **Done** — `docker compose up -d` |
| Backend infra (FastAPI, config, db, CORS) | **Done** |
| ORM models (repos, files, symbols, embeddings, chat, dependencies, generated_docs) | **Done** — 8 tables |
| Alembic migrations (3 applied: initial + deps/docs + embedding dim) | **Done** |
| Pydantic schemas + all 9 routers | **Done** |
| `services/github.py` (clone/pull/walk files) | **Done** |
| `services/parser.py` (tree-sitter: symbols + imports/calls/inheritance) | **Done** |
| `services/embeddings.py` (NVIDIA nemotron-3-embed-1b, 2048 dims) | **Done** |
| `services/indexer.py` (clone→parse→embed→store + dependency resolution) | **Done** |
| `services/search.py` (pgvector cosine similarity) | **Done** |
| `services/rag.py` (RAG chat + SSE streaming + impact analysis) | **Done** |
| `services/diffs.py` (git commit history + LLM diff analysis) | **Done** |
| `services/docs.py` (LLM doc generation + caching) | **Done** |
| Frontend (dashboard, browser, viewer, chat, search, OAuth) | **Done** — builds clean |
| Frontend Phase 2 (dependency graph, commit list, generated docs) | **Done** |
| End-to-end testing (index a real repo, verify all endpoints) | **TODO** |

## API Configuration

Chat and embeddings use **separate endpoints**:

| Purpose | Env Var | Default |
|---|---|---|
| Chat base URL | `OPENAI_API_BASE` | `https://vcliproxyapi.duckdns.org` |
| Chat API key | `OPENAI_API_KEY` | (required) |
| Chat model | `OPENAI_MODEL` | `deepseek-v4-flash-free` |
| Embedding base URL | `OPENAI_EMBEDDING_BASE` | `https://integrate.api.nvidia.com/v1` |
| Embedding API key | `OPENAI_EMBEDDING_API_KEY` | (required) |
| Embedding model | `OPENAI_EMBEDDING_MODEL` | `nvidia/nemotron-3-embed-1b` |

> **Note**: The embedding model produces 2048-dim vectors. pgvector's ivfflat/hnsw indexes cap at 2000 dims, so `code_embeddings` uses exact cosine search (no ANN index). This is performant for typical codebase sizes (<100k symbols).

## Step-by-Step Implementation Guides

Detailed, sequential implementation instructions live in `docs/steps/`:

| Guide | Covers | Status |
|---|---|---|
| `01-infrastructure.md` | Docker, deps, config, models, routers, migrations | **Done** |
| `02-tree-sitter-parsing.md` | `services/parser.py` — symbol extraction for Python/JS/TS | **Done** |
| `03-embeddings-and-indexing.md` | `services/embeddings.py` + `services/indexer.py` | **Done** |
| `04-semantic-search.md` | `services/search.py` — pgvector cosine similarity | **Done** |
| `05-rag-chat.md` | `services/rag.py` — retrieval + LLM streaming | **Done** |
| `06-frontend.md` | Dashboard, repo browser, code viewer, search, chat, GitHub OAuth | **Done** |
| `07-phase2-advanced.md` | Dependency graph, git diff analysis, doc generation | **Done** |

## Migrations

| Revision | Description |
|---|---|
| `454e27362b68` | Initial schema (repos, files, symbols, embeddings, chat) |
| `051b2df8478e` | Add dependencies + generated_docs tables |
| `ce78ab1e4c1c` | Change embedding dim 1536→2048, drop ivfflat index |

## Build & Run

### Database

```bash
docker compose up -d          # pgvector Postgres on :5432
docker compose exec db psql -U codebase -d codebase_intelligence -c "\dt"
```

### Backend (uv)

```bash
cd backend
cp ../.env.example .env       # fill in real values (API keys, GitHub OAuth)
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
│       ├── main.py           # FastAPI app + router registration (9 routers)
│       ├── config.py         # pydantic-settings (reads .env, split chat/embedding config)
│       ├── db.py             # async engine/session/Base
│       ├── models/           # SQLAlchemy models (8 tables)
│       ├── schemas/          # Pydantic request/response models
│       ├── routers/          # repos, index, search, chat, files, auth, dependencies, diffs, docs
│       └── services/         # github, parser, embeddings, indexer, search, rag, diffs, docs
└── frontend/                 # Next.js app (bun)
    ├── src/
    │   ├── app/              # App Router pages (dashboard, repo/[id], login, auth/callback)
    │   ├── components/       # UI components (file-tree, code-viewer, chat-panel, search-bar,
    │   │                     #   dependency-graph, commit-list, generated-docs, repo-card, etc.)
    │   └── lib/api.ts        # Typed API client for all backend endpoints
    └── package.json
```

## Key Conventions

- **Python deps**: declare in `backend/pyproject.toml` via `uv add` — never pip-install directly
- **Node deps**: install with `bun add <package>` — never npm/pnpm
- **Python version**: pinned in `backend/.python-version` (3.13) — do not change
- **TypeScript**: strict, import alias `@/*` maps to `frontend/src/*`
- **Git**: monorepo with a single repo at the root; commit from the root
- **Database**: PostgreSQL + pgvector only (Docker Compose); use Alembic for all schema changes — never hand-edit tables
- **LLM chat**: OpenAI-compatible endpoint configured via `OPENAI_API_BASE`/`OPENAI_API_KEY` in `.env`
- **Embeddings**: separate NVIDIA endpoint via `OPENAI_EMBEDDING_BASE`/`OPENAI_EMBEDDING_API_KEY` — 2048-dim vectors, cosine distance (`<=>`) for search, no ANN index
- **Streaming**: chat responses stream via SSE (`text/event-stream`); frontend parses `data:` / `event: done` events
- **Indexing runs as a FastAPI BackgroundTask** with its own DB session (`async_session`) — never reuse request-scoped sessions
- **Status enum**: `pending → cloning → indexing → ready` (or `error`), surfaced via `GET /api/repos/{id}/index/status`
