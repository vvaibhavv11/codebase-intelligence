const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ────────────────────────────────────────────────────────────────────

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

// ── Phase 2: Dependency graph ───────────────────────────────────────────────

export interface GraphNode {
  id: string;
  name: string;
  kind: string;
  file_path: string;
  lines: [number, number] | null;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ── Phase 2: Diffs ──────────────────────────────────────────────────────────

export interface CommitSummary {
  sha: string;
  author: string;
  date: string;
  message: string;
  files_changed: number;
  added_lines: number;
  removed_lines: number;
}

export interface FileDiff {
  file_path: string;
  change_type: string;
  patch: string | null;
  added_lines: number;
  removed_lines: number;
}

export interface CommitDiff {
  sha: string;
  author: string;
  date: string;
  message: string;
  files: FileDiff[];
}

// ── Phase 2: Generated docs ────────────────────────────────────────────────

export interface GeneratedDoc {
  id: string;
  repo_id: string;
  symbol_id: string | null;
  content: string;
  kind: "symbol_doc" | "readme";
  created_at: string;
}

// ── Repos ────────────────────────────────────────────────────────────────────

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

export async function getRepo(repoId: string): Promise<Repo> {
  const res = await fetch(`${API_URL}/api/repos/${repoId}`);
  if (!res.ok) throw new Error("Failed to fetch repo");
  return res.json();
}

export async function deleteRepo(repoId: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/repos/${repoId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete repo");
}

export async function triggerIndex(repoId: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/repos/${repoId}/index`, {
    method: "POST",
  });
  if (!res.ok) throw new Error("Failed to trigger indexing");
}

export async function getRepoStatus(
  repoId: string
): Promise<{ repo_id: string; status: string; error_message: string | null; indexed_at: string | null }> {
  const res = await fetch(`${API_URL}/api/repos/${repoId}/index/status`);
  if (!res.ok) throw new Error("Failed to get repo status");
  return res.json();
}

// ── File tree ────────────────────────────────────────────────────────────────

export async function getFileTree(repoId: string): Promise<FileTreeNode[]> {
  const res = await fetch(`${API_URL}/api/repos/${repoId}/tree`);
  if (!res.ok) throw new Error("Failed to fetch file tree");
  return res.json();
}

export async function getFileContent(
  repoId: string,
  path: string
): Promise<FileContent> {
  const res = await fetch(`${API_URL}/api/repos/${repoId}/files/${path}`);
  if (!res.ok) throw new Error("Failed to fetch file content");
  return res.json();
}

// ── Search ───────────────────────────────────────────────────────────────────

export async function semanticSearch(
  repoId: string,
  query: string,
  limit = 10
): Promise<SearchResult[]> {
  const res = await fetch(
    `${API_URL}/api/search?q=${encodeURIComponent(query)}&repo_id=${repoId}&limit=${limit}`
  );
  if (!res.ok) throw new Error("Search failed");
  const data = await res.json();
  return data.results;
}

// ── Dependency graph ────────────────────────────────────────────────────────

export async function getDependencyGraph(repoId: string): Promise<GraphData> {
  const res = await fetch(`${API_URL}/api/repos/${repoId}/graph`);
  if (!res.ok) throw new Error("Failed to fetch dependency graph");
  return res.json();
}

export async function getDependents(
  repoId: string,
  symbolId: string
): Promise<GraphNode[]> {
  const res = await fetch(
    `${API_URL}/api/repos/${repoId}/symbols/${symbolId}/dependents`
  );
  if (!res.ok) throw new Error("Failed to fetch dependents");
  return res.json();
}

// ── Diffs ───────────────────────────────────────────────────────────────────

export async function getCommits(
  repoId: string,
  limit = 50
): Promise<CommitSummary[]> {
  const res = await fetch(
    `${API_URL}/api/repos/${repoId}/commits?limit=${limit}`
  );
  if (!res.ok) throw new Error("Failed to fetch commits");
  return res.json();
}

export async function getCommitDiff(
  repoId: string,
  sha: string
): Promise<CommitDiff> {
  const res = await fetch(`${API_URL}/api/repos/${repoId}/commits/${sha}`);
  if (!res.ok) throw new Error("Failed to fetch commit diff");
  return res.json();
}

export async function streamDiffAnalysis(
  repoId: string,
  commitSha: string | null,
  filePath: string | null,
  onChunk: (text: string) => void,
  onDone: () => void,
  signal?: AbortSignal,
  onError?: (message: string) => void
): Promise<void> {
  const res = await fetch(`${API_URL}/api/repos/${repoId}/diff/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ commit_sha: commitSha, file_path: filePath }),
    signal,
  });

  if (!res.ok || !res.body) throw new Error("Diff analysis failed");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";

    for (const event of events) {
      const lines = event.split("\n");
      const type = lines
        .find((l) => l.startsWith("event:"))
        ?.replace("event:", "")
        .trim();
      const data = lines
        .find((l) => l.startsWith("data:"))
        ?.replace("data:", "")
        .trim();

      if (type === "done") {
        onDone();
      } else if (type === "error") {
        const payload = parseSseData(data);
        onError?.(payload?.error ?? "Streaming error");
      } else if (data) {
        const payload = parseSseData(data);
        if (payload?.text != null) {
          onChunk(payload.text);
        } else {
          onChunk(data);
        }
      }
    }
  }
}

// ── Generated docs ──────────────────────────────────────────────────────────

export async function generateReadme(repoId: string): Promise<GeneratedDoc> {
  const res = await fetch(`${API_URL}/api/repos/${repoId}/docs/readme`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to generate README");
  }
  return res.json();
}

export async function generateSymbolDoc(symbolId: string): Promise<GeneratedDoc> {
  const res = await fetch(`${API_URL}/api/symbols/${symbolId}/doc`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to generate symbol doc");
  }
  return res.json();
}

export async function getRepoDocs(repoId: string): Promise<GeneratedDoc[]> {
  const res = await fetch(`${API_URL}/api/repos/${repoId}/docs`);
  if (!res.ok) throw new Error("Failed to fetch docs");
  const data = await res.json();
  return data.docs;
}

// ── Chat ─────────────────────────────────────────────────────────────────────

export async function getSessions(repoId: string): Promise<ChatSession[]> {
  const res = await fetch(
    `${API_URL}/api/chat/sessions?repo_id=${repoId}`
  );
  if (!res.ok) throw new Error("Failed to fetch sessions");
  const data = await res.json();
  return data.sessions;
}

export async function getSession(sessionId: string): Promise<ChatSession> {
  const res = await fetch(`${API_URL}/api/chat/sessions/${sessionId}`);
  if (!res.ok) throw new Error("Failed to fetch session");
  return res.json();
}

export async function streamChat(
  repoId: string,
  message: string,
  sessionId: string | null,
  onChunk: (text: string) => void,
  onDone: (sessionId: string) => void,
  signal?: AbortSignal,
  onError?: (message: string) => void
): Promise<void> {
  const res = await fetch(`${API_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      repo_id: repoId,
      message,
      session_id: sessionId,
    }),
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
      const type = lines
        .find((l) => l.startsWith("event:"))
        ?.replace("event:", "")
        .trim();
      const data = lines
        .find((l) => l.startsWith("data:"))
        ?.replace("data:", "")
        .trim();

      if (type === "done") {
        const payload = parseSseData(data);
        onDone(payload?.session_id ?? sessionId ?? "");
      } else if (type === "error") {
        onError?.(parseSseData(data)?.error ?? "Streaming error");
      } else if (data) {
        const payload = parseSseData(data);
        if (payload?.text != null) {
          onChunk(payload.text);
        } else {
          onChunk(data);
        }
      }
    }
  }
}

function parseSseData(data: string | undefined): { [key: string]: string } | null {
  if (!data) return null;
  try {
    return JSON.parse(data);
  } catch {
    return null;
  }
}
