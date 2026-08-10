# TODO — Remaining Work

## 1. End-to-End Testing (HIGH priority)

All code is written but has never been run against a real repo. This is the critical next step.

- [ ] Start backend: `cd backend && uv run python src/backend/main.py`
- [ ] Start frontend: `cd frontend && bun run dev`
- [ ] Connect a small GitHub repo via `POST /api/repos` (e.g. a small Python or JS project)
- [ ] Trigger indexing via `POST /api/repos/{id}/index`
- [ ] Monitor status via `GET /api/repos/{id}/index/status` until `ready`
- [ ] Verify file tree: `GET /api/files/{repo_id}/tree`
- [ ] Verify file content: `GET /api/files/{repo_id}/content?path=...`
- [ ] Verify semantic search: `GET /api/search?q=...&repo_id=...`
- [ ] Verify chat (SSE): `POST /api/chat` with a question about the indexed repo
- [ ] Verify dependency graph: `GET /api/dependencies/{repo_id}/graph`
- [ ] Verify commit list: `GET /api/diffs/{repo_id}/commits`
- [ ] Verify diff analysis (SSE): `POST /api/diffs/{repo_id}/analyze`
- [ ] Verify doc generation: `POST /api/docs/{repo_id}/symbol/{symbol_id}`
- [ ] Verify repo README generation: `POST /api/docs/{repo_id}/readme`
- [ ] Open frontend in browser and verify all tabs (Files, Graph, Commits, README) render data

## 2. Bug Fixes & Edge Cases (discovered during E2E)

These will likely surface during testing:

- [ ] Fix any import/runtime errors when indexing runs
- [ ] Fix any NVIDIA embedding API rate limiting or batch size issues
- [ ] Fix any SSE streaming issues in chat/diff analysis endpoints
- [ ] Fix any frontend rendering issues with real data
- [ ] Handle repos with no symbols (empty or non-code repos)
- [ ] Handle indexing failures gracefully (set status to `error` with message)

## 3. `.env.example` Update

- [ ] Update `.env.example` to reflect the split chat/embedding config:
  - `OPENAI_EMBEDDING_BASE=https://integrate.api.nvidia.com/v1`
  - `OPENAI_EMBEDDING_API_KEY=`
  - `OPENAI_EMBEDDING_MODEL=nvidia/nemotron-3-embed-1b`

## 4. GitHub OAuth (LOW priority)

- [ ] Register a GitHub OAuth App and fill in `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` in `.env`
- [ ] Test the full OAuth flow: login page → GitHub redirect → callback → session
- [ ] Currently the app works without auth (all endpoints are unauthenticated)

## 5. Production Deployment (FUTURE)

- [ ] Add `frontend/.env.local` with `NEXT_PUBLIC_API_URL` pointing to the production backend
- [ ] Set up reverse proxy (nginx/caddy) for frontend + backend
- [ ] Configure CORS for production domain
- [ ] Set a real `SECRET_KEY` in `.env`
- [ ] Set up SSL/TLS
- [ ] Consider adding rate limiting to embedding/chat endpoints (NVIDIA free tier limits)

## 6. Nice-to-Haves (FUTURE)

- [ ] Re-indexing support (detect changed files only, skip unchanged)
- [ ] Webhook-based auto-reindex on push
- [ ] Multi-language support beyond Python/JS/TS (Go, Rust, Java, etc.)
- [ ] Export dependency graph as SVG/PNG
- [ ] Persistent chat sessions across browser reloads
- [ ] User-scoped repos (requires OAuth to be set up)
- [ ] Repo deletion cleanup (remove cloned files + all DB records)

## Architecture Notes

- **Chat LLM**: `vcliproxyapi.duckdns.org` → `deepseek-v4-flash-free` (used by rag.py, diffs.py, docs.py)
- **Embeddings**: `integrate.api.nvidia.com/v1` → `nvidia/nemotron-3-embed-1b` (2048 dims, used by embeddings.py)
- **Vector search**: exact cosine distance (no ANN index — pgvector caps ivfflat/hnsw at 2000 dims, our vectors are 2048)
- **Migrations**: 3 applied (`454e27362b68` → `051b2df8478e` → `ce78ab1e4c1c`)
