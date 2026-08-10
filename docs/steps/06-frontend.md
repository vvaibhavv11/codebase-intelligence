# Step 6: Frontend — Dashboard, Repo Browser, Code Viewer, Chat, Search, GitHub OAuth

## Goal

Build the Next.js 16 frontend that consumes the FastAPI backend. This step covers the full UI: landing/dashboard, connecting repos, browsing the file tree, viewing code with syntax highlighting, semantic search, AI chat with streaming, and GitHub OAuth login.

---

## Prerequisites

- Steps 1-5 complete (backend running on `http://localhost:8000`)
- At least one repo indexed so there's data to browse/search/chat about

---

## 6.0 Environment Setup

Create `frontend/.env.local`:

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

**Important**: Only `NEXT_PUBLIC_*` vars are exposed to the browser. The backend URL is fine to expose since the backend has CORS configured for `http://localhost:3000`.

### Install Dependencies

```bash
cd frontend
bun add @tanstack/react-query shiki lucide-react
bun add -d @types/node
```

Optionally add a component library (Radix) if you want accessible primitives — but plain Tailwind is sufficient for this UI.

---

## 6.1 API Client Layer

### File: `frontend/src/lib/api.ts`

```typescript
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Repo {
  id: string;
  github_url: string;
  name: string;
  owner: string;
  default_branch: string;
  status: "pending" | "cloning" | "indexing" | "ready" | "error";
  error_message: string | null;
  indexed_at: string | null;
  created_at: string;
}

export interface FileTreeNode {
  name: string;
  path: string;
  type: "file" | "directory";
  language: string | null;
  children?: FileTreeNode[];
}

export interface SymbolInfo {
  id: string;
  name: string;
  kind: string;
  start_line: number;
  end_line: number;
  signature: string | null;
  docstring: string | null;
}

export interface FileContent {
  path: string;
  language: string | null;
  content: string;
  symbols: SymbolInfo[];
}

export interface SearchResult {
  symbol_id: string;
  symbol_name: string;
  symbol_kind: string;
  file_path: string;
  start_line: number;
  end_line: number;
  source_preview: string;
  score: number;
}

export interface ChatSession {
  id: string;
  repo_id: string;
  title: string | null;
  created_at: string;
  messages?: ChatMessage[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
}
```

### API Functions

```typescript
// Repos
export async function listRepos(): Promise<Repo[]> {
  const res = await fetch(`${API_URL}/api/repos`);
  if (!res.ok) throw new Error("Failed to fetch repos");
  const data = await res.json();
  return data.repositories;
}

export async function connectRepo(githubUrl: string): Promise<Repo> {
  const res = await fetch(`${API_URL}/api/repos`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ github_url: githubUrl }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to connect repo");
  }
  return res.json();
}

export async function triggerIndex(repoId: string): Promise<void> {
  await fetch(`${API_URL}/api/repos/${repoId}/index`, { method: "POST" });
}

export async function getRepoStatus(repoId: string): Promise<Repo> {
  const res = await fetch(`${API_URL}/api/repos/${repoId}/index/status`);
  return res.json();
}

// File tree
export async function getFileTree(repoId: string): Promise<FileTreeNode[]> {
  const res = await fetch(`${API_URL}/api/repos/${repoId}/tree`);
  return res.json();
}

export async function getFileContent(repoId: string, path: string): Promise<FileContent> {
  const res = await fetch(`${API_URL}/api/repos/${repoId}/files/${path}`);
  return res.json();
}

// Search
export async function semanticSearch(repoId: string, query: string): Promise<SearchResult[]> {
  const res = await fetch(
    `${API_URL}/api/search?q=${encodeURIComponent(query)}&repo_id=${repoId}&limit=10`
  );
  const data = await res.json();
  return data.results;
}

// Chat
export async function getSessions(repoId: string): Promise<ChatSession[]> {
  const res = await fetch(`${API_URL}/api/chat/sessions?repo_id=${repoId}`);
  const data = await res.json();
  return data.sessions;
}

export async function getSession(sessionId: string): Promise<ChatSession> {
  const res = await fetch(`${API_URL}/api/chat/sessions/${sessionId}`);
  return res.json();
}

export async function streamChat(
  repoId: string,
  message: string,
  sessionId: string | null,
  onChunk: (text: string) => void,
  onDone: (sessionId: string) => void,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch(`${API_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo_id: repoId, message, session_id: sessionId }),
    signal,
  });

  if (!res.ok || !res.body) throw new Error("Chat request failed");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE events are separated by \n\n
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";

    for (const event of events) {
      const lines = event.split("\n");
      const type = lines.find((l) => l.startsWith("event:"))?.replace("event:", "").trim();
      const data = lines.find((l) => l.startsWith("data:"))?.replace("data:", "").trim();

      if (type === "done") {
        onDone(data ?? sessionId ?? "");
      } else if (data) {
        onChunk(data);
      }
    }
  }
}
```

---

## 6.2 React Query Provider & App Layout

### File: `frontend/src/app/providers.tsx` (Client Component)

```tsx
"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

export default function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 30_000, refetchOnWindowFocus: false },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
```

### File: `frontend/src/app/layout.tsx` (update)

Wrap children with `<Providers>`:

```tsx
import Providers from "./providers";

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={...}>
      <body className="min-h-full flex flex-col">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
```

### File: `frontend/src/app/globals.css`

Keep the existing Tailwind import. Set a dark, code-focused aesthetic:

```css
@import "tailwindcss";

:root {
  --background: #ffffff;
  --foreground: #171717;
}

@media (prefers-color-scheme: dark) {
  :root {
    --background: #0a0a0a;
    --foreground: #ededed;
  }
}

body {
  background: var(--background);
  color: var(--foreground);
  font-family: var(--font-geist-sans), system-ui, sans-serif;
}

/* Thin scrollbars for the file tree / code areas */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}
::-webkit-scrollbar-thumb {
  background: rgba(127, 127, 127, 0.4);
  border-radius: 4px;
}
```

---

## 6.3 Dashboard (Landing Page)

### File: `frontend/src/app/page.tsx`

Replace the default create-next-app page. Layout:

```
┌─────────────────────────────────────────────┐
│  Codebase Intelligence          [Connect]   │
├─────────────────────────────────────────────┤
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ │
│  │ Repo Card │ │ Repo Card │ │  (empty)  │ │
│  └───────────┘ └───────────┘ └───────────┘ │
└─────────────────────────────────────────────┘
```

**Components to build:**

### `frontend/src/components/repo-card.tsx`

Client component. Displays:
- Repo name (clickable → `/repos/[id]`)
- Owner, default branch, connection date
- Status badge: `pending` (gray), `cloning` (blue), `indexing` (amber, animated), `ready` (green), `error` (red)
- "Re-index" button if not ready

### `frontend/src/components/connect-repo-dialog.tsx`

Modal dialog (native `<dialog>` or custom overlay):
- Input: GitHub URL (placeholder `https://github.com/owner/repo`)
- Validate with regex before submit: `/^https:\/\/github\.com\/[^/]+\/[^/]+$/`
- On submit → `connectRepo(url)` → `triggerIndex(repoId)` → invalidate repos query
- Show error message from backend if connection fails

### Dashboard data fetching

Use React Query:

```tsx
"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { listRepos } from "@/lib/api";

export default function Home() {
  const { data: repos, isLoading } = useQuery({ queryKey: ["repos"], queryFn: listRepos });
  // ...render RepoCards
}
```

**Polling for indexing status**: while any repo is `cloning`/`indexing`, poll every 2 seconds:

```tsx
useQuery({
  queryKey: ["repos"],
  queryFn: listRepos,
  refetchInterval: repos?.some((r) => r.status === "cloning" || r.status === "indexing")
    ? 2000
    : false,
});
```

---

## 6.4 Repo Browser Page

### File: `frontend/src/app/repos/[id]/page.tsx`

Layout — split view:

```
┌──────────────────────────────┬───────────────────────────────────┐
│  File Tree        │ Search   │        Code Viewer        │ Chat │
│  (sidebar 280px)  │  bar     │                              │      │
├──────────────────────────────┼──────────────────┬────────────┤
│  📁 src/                     │  code goes here  │  chat      │
│  └── 📁 app/                 │  with syntax     │  panel     │
│      └── 📄 page.tsx         │  highlighting    │  (streams) │
│  ┌ Search results            │                  │            │
└──────────────────────────────┴──────────────────┴────────────┘
```

### File: `frontend/src/components/file-tree.tsx`

Recursive tree component:

```tsx
"use client";

interface FileTreeProps {
  nodes: FileTreeNode[];
  selectedPath: string | null;
  onSelect: (node: FileTreeNode) => void;
}

function FileTree({ nodes, selectedPath, onSelect }: FileTreeProps) {
  return (
    <ul className="text-sm">
      {nodes.map((node) => (
        <FileTreeItem key={node.path} node={node} ... />
      ))}
    </ul>
  );
}

function FileTreeItem({ node, selectedPath, onSelect, depth = 0 }: ...) {
  const [expanded, setExpanded] = useState(true);
  const isDir = node.type === "directory";
  const isSelected = node.path === selectedPath;

  return (
    <li>
      <button
        onClick={() => (isDir ? setExpanded(!expanded) : onSelect(node))}
        style={{ paddingLeft: `${depth * 16}px` }}
        className={isSelected ? "bg-blue-100 dark:bg-blue-900/50" : ""}
      >
        {isDir ? (expanded ? "📂" : "📁") : getFileIcon(node.name)}
        <span className="ml-1">{node.name}</span>
      </button>
      {isDir && expanded && node.children && (
        <ul>
          {node.children.map((child) => (
            <FileTreeItem key={child.path} node={child} depth={depth + 1} ... />
          ))}
        </ul>
      )}
    </li>
  );
}

function getFileIcon(name: string): string {
  const ext = name.split(".").pop();
  const icons: Record<string, string> = {
    py: "🐍", ts: "🟦", tsx: "⚛️", js: "🟨", jsx: "⚛️",
    json: "📦", md: "📝", css: "🎨", html: "🌐",
  };
  return icons[ext ?? ""] ?? "📄";
}
```

### File: `frontend/src/components/code-viewer.tsx`

Syntax highlighting with **shiki**:

```tsx
"use client";

import { useEffect, useState } from "react";
import { codeToHtml } from "shiki";

interface CodeViewerProps {
  content: string;
  language: string | null;
  symbols: SymbolInfo[];
}

export default function CodeViewer({ content, language, symbols }: CodeViewerProps) {
  const [html, setHtml] = useState("");

  useEffect(() => {
    let cancelled = false;
    const lang = normalizeLanguage(language);
    codeToHtml(content, { lang, theme: "github-dark" }).then((h) => {
      if (!cancelled) setHtml(h);
    });
    return () => { cancelled = true; };
  }, [content, language]);

  return (
    <div className="relative">
      {/* Symbols overview */}
      <SymbolSidebar symbols={symbols} />
      <div
        className="overflow-auto text-sm font-mono"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}

function normalizeLanguage(lang: string | null): string {
  switch (lang) {
    case "typescript": return "tsx"; // shiki uses tsx for .tsx; try "typescript" for .ts
    default: return lang ?? "plaintext";
  }
}
```

**Note on shiki**: import `codeToHtml` from `"shiki"` (the modern API). Alternatively use `"shiki/bundle/web"` for the browser bundle. For large files, consider lazy-loading shiki.

### Symbol navigation sidebar

On the right edge of the code viewer, show a clickable list of symbols with line numbers. Clicking scrolls to the line:

```tsx
function scrollToLine(line: number) {
  // Find the code line element by data-line attribute
  document
    .querySelector(`[data-line="${line}"]`)
    ?.scrollIntoView({ behavior: "smooth", block: "center" });
}
```

---

## 6.5 Semantic Search UI

### File: `frontend/src/components/search-bar.tsx`

Debounced search input that calls `semanticSearch` and shows results in a dropdown:

```tsx
"use client";

import { useState, useEffect, useRef } from "react";
import { semanticSearch, SearchResult } from "@/lib/api";

export default function SearchBar({ repoId }: { repoId: string }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);

  // Debounce 300ms
  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      return;
    }
    const t = setTimeout(async () => {
      const r = await semanticSearch(repoId, query);
      setResults(r);
      setOpen(true);
    }, 300);
    return () => clearTimeout(t);
  }, [query, repoId]);

  return (
    <div className="relative">
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search by meaning... (e.g. 'how is auth handled')"
        onFocus={() => results.length && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 200)}
      />
      {open && (
        <ul className="absolute z-10 bg-white dark:bg-zinc-900 border rounded shadow-lg max-h-96 overflow-auto">
          {results.map((r) => (
            <li key={r.symbol_id}>
              <button
                onClick={() => openFile(r.file_path, r.start_line)}
                className="w-full text-left px-3 py-2 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              >
                <div className="font-mono text-sm">
                  {r.symbol_kind} {r.symbol_name}
                </div>
                <div className="text-xs text-zinc-500">{r.file_path}:{r.start_line}</div>
                <div className="text-xs truncate">{r.source_preview}</div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

Clicking a result should navigate to `/repos/[id]?file=path&line=start_line` and the repo page loads that file + scrolls to the line.

---

## 6.6 AI Chat Panel

### File: `frontend/src/components/chat-panel.tsx`

The chat UI with streaming:

```tsx
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { streamChat, ChatMessage, getSessions, getSession } from "@/lib/api";

interface ChatPanelProps {
  repoId: string;
}

interface DisplayMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}

export default function ChatPanel({ repoId }: ChatPanelProps) {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Load session list on mount
  useEffect(() => {
    getSessions(repoId).then(setSessions);
  }, [repoId]);

  // Auto-scroll on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg: DisplayMessage = { id: crypto.randomUUID(), role: "user", content: text };
    const assistantMsg: DisplayMessage = { id: crypto.randomUUID(), role: "assistant", content: "", streaming: true };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput("");
    setLoading(true);

    const controller = new AbortController();
    abortRef.current = controller;

    let accumulated = "";

    try {
      await streamChat(
        repoId,
        text,
        sessionId,
        (chunk) => {
          accumulated += chunk;
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantMsg.id ? { ...m, content: accumulated } : m))
          );
        },
        (newSessionId) => {
          setSessionId(newSessionId);
          getSessions(repoId).then(setSessions);
        },
        controller.signal
      );
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id
              ? { ...m, content: accumulated + "\n\n_Error: failed to get response_", streaming: false }
              : m
          )
        );
      }
    } finally {
      setMessages((prev) =>
        prev.map((m) => (m.id === assistantMsg.id ? { ...m, streaming: false } : m))
      );
      setLoading(false);
      abortRef.current = null;
    }
  }, [input, loading, repoId, sessionId]);

  return (
    <div className="flex flex-col h-full">
      {/* Session history */}
      <select
        value={sessionId ?? ""}
        onChange={(e) => {
          const id = e.target.value;
          setSessionId(id);
          if (id) {
            getSession(id).then((s) =>
              setMessages(
                s.messages?.map((m) => ({
                  id: m.id,
                  role: m.role,
                  content: m.content,
                })) ?? []
              )
            );
          } else {
            setMessages([]);
          }
        }}
        className="text-sm border rounded p-1"
      >
        <option value="">New conversation</option>
        {sessions.map((s) => (
          <option key={s.id} value={s.id}>{s.title ?? "Untitled"}</option>
        ))}
      </select>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-4 p-4">
        {messages.map((m) => (
          <div
            key={m.id}
            className={m.role === "user" ? "text-right" : "text-left"}
          >
            <div
              className={`inline-block max-w-[85%] rounded-lg px-4 py-2 text-sm whitespace-pre-wrap ${
                m.role === "user"
                  ? "bg-blue-600 text-white"
                  : "bg-zinc-100 dark:bg-zinc-800"
              }`}
            >
              {m.content}
              {m.streaming && <CursorBlink />}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-3 border-t">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
              }
            }}
            placeholder='Ask about the codebase... e.g. "Explain how authentication works"'
            className="flex-1 text-sm border rounded-lg p-2 resize-none"
            rows={2}
          />
          <button
            onClick={sendMessage}
            disabled={loading || !input.trim()}
            className="px-4 rounded-lg bg-blue-600 text-white text-sm disabled:opacity-50"
          >
            {loading ? "..." : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}

function CursorBlink() {
  return <span className="inline-block w-2 h-4 bg-zinc-400 animate-pulse ml-1 align-middle" />;
}
```

### Chat on repo page

The repo page layout has the ChatPanel as a right-side collapsible drawer (toggle button), or fixed column. For mobile, it becomes a bottom sheet / separate route.

---

## 6.7 GitHub OAuth Login

### Backend routes already exist

- `GET /api/auth/github/login` — redirects to GitHub's authorization page
- `GET /api/auth/github/callback` — exchanges code, redirects to `{FRONTEND_URL}/auth/callback?token=...&username=...&avatar=...`

### Frontend: handle the callback

### File: `frontend/src/app/auth/callback/page.tsx`

```tsx
"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

export default function AuthCallback() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const token = searchParams.get("token");
    const username = searchParams.get("username");
    const avatar = searchParams.get("avatar");

    if (token) {
      localStorage.setItem("gh_token", token);
      if (username) localStorage.setItem("gh_username", username);
      if (avatar) localStorage.setItem("gh_avatar", avatar);
      router.push("/");
    } else {
      router.push("/login?error=failed");
    }
  }, [router, searchParams]);

  return <div className="text-center p-8">Signing in...</div>;
}
```

### File: `frontend/src/app/login/page.tsx`

```tsx
export default function LoginPage() {
  return (
    <div className="flex flex-col items-center justify-center min-h-full gap-4">
      <h1 className="text-2xl font-bold">Codebase Intelligence</h1>
      <p className="text-sm text-zinc-500">
        Connect your GitHub account to browse, search, and chat with your repositories.
      </p>
      <a
        href={`${process.env.NEXT_PUBLIC_API_URL}/api/auth/github/login`}
        className="px-6 py-3 bg-zinc-900 dark:bg-white text-white dark:text-black rounded-lg font-medium hover:opacity-90"
      >
        Continue with GitHub
      </a>
    </div>
  );
}
```

### File: `frontend/src/components/user-menu.tsx`

Shows avatar/username from localStorage (or "Sign in" link if absent).

### Note on token storage

For the MVP, storing the GitHub token in localStorage is acceptable. In production you'd:
1. Have the backend store the token server-side (sessions table + `Authorization` header)
2. Use the token server-side for cloning private repos
3. Add middleware to protect routes

---

## 6.8 Routing Summary

| Route | Purpose | Auth required |
|---|---|---|
| `/` | Dashboard — repo list + connect dialog | No (show login prompt) |
| `/login` | GitHub OAuth sign-in | — |
| `/auth/callback` | OAuth callback handler | — |
| `/repos/[id]` | Repo browser: file tree + code viewer + chat | No |

---

## 6.9 Testing Checklist

1. **Dashboard**: `bun run dev` → http://localhost:3000 shows the app, not create-next-app default
2. **Connect repo**: Paste a valid GitHub URL → repo card appears with `pending`/`cloning`/`indexing` → becomes `ready`
3. **File tree**: Open a ready repo → tree loads → directories expand/collapse → files open
4. **Code viewer**: File content renders with syntax highlighting → line numbers match backend
5. **Symbol sidebar**: Functions/classes listed → clicking scrolls to the right line
6. **Search**: Type "authentication" → relevant code results appear → clicking navigates to the file
7. **Chat**: Ask "What does this project do?" → streaming response appears → stored in session → reloading shows history
8. **OAuth**: Click "Continue with GitHub" → GitHub auth → redirect back → logged in state persists

---

## Definition of Done

- [ ] `src/lib/api.ts` with typed API functions for all endpoints
- [ ] React Query providers configured
- [ ] Dashboard with repo cards, status badges, connect dialog
- [ ] Repo browser with file tree (recursive, collapsible)
- [ ] Code viewer with shiki syntax highlighting and symbol navigation
- [ ] Debounced semantic search with dropdown results
- [ ] Chat panel with SSE streaming, session history, abort support
- [ ] GitHub OAuth login flow (login page + callback)
- [ ] Dark mode friendly (Tailwind dark: classes)
- [ ] `bun run build` passes with no TypeScript errors
