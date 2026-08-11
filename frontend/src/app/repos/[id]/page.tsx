"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Loader2,
  Code2,
  PanelRightOpen,
  PanelRightClose,
  FileCode2,
  GitBranch,
  GitCommitHorizontal,
  FileText,
  AlertCircle,
  RefreshCw,
  X,
} from "lucide-react";
import Link from "next/link";
import { getRepo, getFileTree, getFileContent, triggerIndex } from "@/lib/api";
import AuthGuard from "@/components/auth-guard";
import type { FileTreeNode as FileTreeNodeType, FileContent, GraphNode } from "@/lib/api";
import FileTree from "@/components/file-tree";
import CodeViewer from "@/components/code-viewer";
import SearchBar from "@/components/search-bar";
import ChatPanel from "@/components/chat-panel";
import DependencyGraph from "@/components/dependency-graph";
import CommitList from "@/components/commit-list";
import GeneratedDocs from "@/components/generated-docs";

type Tab = "files" | "graph" | "commits" | "readme";

const TABS: { id: Tab; label: string; icon: typeof FileCode2 }[] = [
  { id: "files", label: "Files", icon: FileCode2 },
  { id: "graph", label: "Graph", icon: GitBranch },
  { id: "commits", label: "Commits", icon: GitCommitHorizontal },
  { id: "readme", label: "README", icon: FileText },
];

function RepoBrowser() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const repoId = params.id;

  const [activeTab, setActiveTab] = useState<Tab>("files");
  const [selectedPath, setSelectedPath] = useState<string | null>(
    searchParams.get("file")
  );
  const [scrollToLine, setScrollToLine] = useState<number | null>(
    searchParams.get("line") ? Number(searchParams.get("line")) : null
  );
  // Code panel is hidden by default — chat is the main experience
  const [codeOpen, setCodeOpen] = useState(false);
  const queryClient = useQueryClient();

  const isInProgress = (s?: string) =>
    s === "pending" || s === "cloning" || s === "indexing";

  // Fetch repo info — poll every 2s while indexing
  const { data: repo } = useQuery({
    queryKey: ["repo", repoId],
    queryFn: () => getRepo(repoId),
    refetchInterval: (query) =>
      isInProgress(query.state.data?.status) ? 2000 : false,
  });

  const repoReady = repo?.status === "ready";

  // Fetch file tree
  const {
    data: tree,
    isLoading: treeLoading,
    error: treeError,
  } = useQuery({
    queryKey: ["tree", repoId],
    queryFn: () => getFileTree(repoId),
    enabled: repoReady && activeTab === "files" && codeOpen,
  });

  // Fetch file content
  const {
    data: fileContent,
    isLoading: fileLoading,
  } = useQuery({
    queryKey: ["file", repoId, selectedPath],
    queryFn: () => getFileContent(repoId, selectedPath!),
    enabled: repoReady && activeTab === "files" && !!selectedPath && codeOpen,
  });

  const navigateToFile = useCallback(
    (filePath: string, line?: number) => {
      setActiveTab("files");
      setSelectedPath(filePath);
      setScrollToLine(line ?? null);
      setCodeOpen(true); // Open the code panel when navigating to a file
      const url = new URL(window.location.href);
      url.searchParams.set("file", filePath);
      if (line) url.searchParams.set("line", String(line));
      else url.searchParams.delete("line");
      router.replace(url.pathname + url.search, { scroll: false });
    },
    [router]
  );

  const handleFileSelect = useCallback(
    (node: FileTreeNodeType) => {
      navigateToFile(node.path);
    },
    [navigateToFile]
  );

  const handleSearchSelect = useCallback(
    (filePath: string, line: number) => {
      navigateToFile(filePath, line);
    },
    [navigateToFile]
  );

  const handleGraphNodeSelect = useCallback(
    (node: GraphNode) => {
      if (node.kind === "file") {
        navigateToFile(node.file_path);
      } else if (node.lines) {
        navigateToFile(node.file_path, node.lines[0]);
      }
    },
    [navigateToFile]
  );

  // Sync from URL on mount / query param change
  useEffect(() => {
    const file = searchParams.get("file");
    const line = searchParams.get("line");
    if (file && file !== selectedPath) {
      setSelectedPath(file);
      setCodeOpen(true); // Open code panel if URL has a file param
    }
    if (line) {
      setScrollToLine(Number(line));
    }
  }, [searchParams]);

  const handleRetryIndex = useCallback(async () => {
    try {
      await triggerIndex(repoId);
      queryClient.invalidateQueries({ queryKey: ["repo", repoId] });
    } catch {
      // ignore — status will show error on next poll
    }
  }, [repoId, queryClient]);

  // Show interstitial when repo is not ready
  if (repo && !repoReady) {
    const statusLabels: Record<string, string> = {
      pending: "Waiting to start",
      cloning: "Cloning repository",
      indexing: "Indexing files and symbols",
      error: "Indexing failed",
    };

    return (
      <div className="flex flex-col h-screen">
        <header className="flex items-center gap-3 px-4 h-12 border-b border-zinc-200 dark:border-zinc-800 bg-white/80 dark:bg-zinc-900/80 backdrop-blur-sm shrink-0">
          <Link
            href="/"
            className="text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-300 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <Code2 className="w-5 h-5 text-blue-600" />
          <span className="font-semibold text-sm truncate">
            {repo.owner}/{repo.name}
          </span>
        </header>

        <div className="flex-1 flex flex-col items-center justify-center gap-4 text-zinc-500">
          {repo.status === "error" ? (
            <>
              <AlertCircle className="w-12 h-12 text-red-400" />
              <p className="text-lg font-medium text-red-500">
                {statusLabels[repo.status]}
              </p>
              {repo.error_message && (
                <p className="text-sm text-zinc-400 max-w-md text-center">
                  {repo.error_message}
                </p>
              )}
              <button
                onClick={handleRetryIndex}
                className="flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium bg-blue-600 text-white hover:bg-blue-700 transition-colors"
              >
                <RefreshCw className="w-4 h-4" />
                Retry Indexing
              </button>
            </>
          ) : (
            <>
              <Loader2 className="w-10 h-10 animate-spin text-blue-500" />
              <p className="text-lg font-medium">
                {statusLabels[repo.status] ?? "Processing"}
              </p>
              <p className="text-sm text-zinc-400">
                This may take a minute depending on repository size
              </p>
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <header className="flex items-center gap-3 px-4 h-12 border-b border-zinc-200 dark:border-zinc-800 bg-white/80 dark:bg-zinc-900/80 backdrop-blur-sm shrink-0">
        <Link
          href="/"
          className="text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-300 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <Code2 className="w-5 h-5 text-blue-600" />
        <span className="font-semibold text-sm truncate">
          {repo?.owner}/{repo?.name}
        </span>
        {repo && (
          <span className="text-xs text-zinc-400 ml-1">
            ({repo.default_branch})
          </span>
        )}

        <div className="flex-1 max-w-lg ml-4">
          <SearchBar repoId={repoId} onSelectResult={handleSearchSelect} />
        </div>

        <button
          onClick={() => setCodeOpen(!codeOpen)}
          className={`ml-auto flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
            codeOpen
              ? "text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-950/40"
              : "text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800"
          }`}
          title={codeOpen ? "Close code browser" : "Open code browser"}
        >
          {codeOpen ? (
            <PanelRightClose className="w-4 h-4" />
          ) : (
            <PanelRightOpen className="w-4 h-4" />
          )}
          Code
        </button>
      </header>

      {/* Main content: Chat (center) + Code panel (right, on demand) */}
      <div className="flex flex-1 overflow-hidden">
        {/* Chat — always visible, takes remaining space */}
        <main className="flex-1 overflow-hidden">
          <ChatPanel repoId={repoId} />
        </main>

        {/* Code panel — slides in from the right */}
        {codeOpen && (
          <aside className="w-[55%] max-w-[900px] shrink-0 border-l border-zinc-200 dark:border-zinc-700 flex flex-col bg-white dark:bg-zinc-900 overflow-hidden">
            {/* Code panel header with tabs */}
            <div className="flex items-center gap-1 px-3 h-10 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50/60 dark:bg-zinc-900/60 shrink-0 overflow-x-auto">
              {TABS.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  onClick={() => setActiveTab(id)}
                  className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors ${
                    activeTab === id
                      ? "text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-950/40"
                      : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  {label}
                </button>
              ))}

              <button
                onClick={() => setCodeOpen(false)}
                className="ml-auto flex items-center justify-center w-7 h-7 rounded-lg text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
                title="Close code panel"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Code panel content */}
            <div className="flex flex-1 overflow-hidden">
              {activeTab === "graph" ? (
                <div className="flex-1 overflow-auto p-4">
                  <DependencyGraph
                    repoId={repoId}
                    onSelectNode={handleGraphNodeSelect}
                  />
                </div>
              ) : activeTab === "commits" ? (
                <div className="flex-1 overflow-auto p-4">
                  <CommitList repoId={repoId} />
                </div>
              ) : activeTab === "readme" ? (
                <div className="flex-1 overflow-hidden">
                  <GeneratedDocs repoId={repoId} mode="readme" />
                </div>
              ) : (
                <>
                  {/* File tree sidebar */}
                  <div className="w-60 shrink-0 border-r border-zinc-200 dark:border-zinc-700 bg-zinc-50/50 dark:bg-zinc-900/50 overflow-y-auto">
                    {treeLoading ? (
                      <div className="flex items-center justify-center py-20">
                        <Loader2 className="w-5 h-5 animate-spin text-zinc-400" />
                      </div>
                    ) : treeError ? (
                      <div className="p-4 text-sm text-red-500">
                        Failed to load file tree
                      </div>
                    ) : tree ? (
                      <div className="py-2">
                        <FileTree
                          nodes={tree}
                          selectedPath={selectedPath}
                          onSelect={handleFileSelect}
                        />
                      </div>
                    ) : null}
                  </div>

                  {/* Code viewer */}
                  <div className="flex-1 overflow-hidden">
                    {!selectedPath ? (
                      <div className="flex flex-col items-center justify-center h-full text-zinc-400">
                        <FileCode2 className="w-12 h-12 mb-3 opacity-30" />
                        <p className="text-sm">Select a file to view</p>
                      </div>
                    ) : fileLoading ? (
                      <div className="flex items-center justify-center h-full">
                        <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
                      </div>
                    ) : fileContent ? (
                      <div className="h-full flex flex-col">
                        {/* File path breadcrumb */}
                        <div className="flex items-center gap-1 px-4 py-2 border-b border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900/80 text-xs text-zinc-500 font-mono">
                          {fileContent.path}
                          {fileContent.language && (
                            <span className="ml-2 rounded bg-zinc-200 dark:bg-zinc-700 px-1.5 py-0.5 text-[10px] uppercase">
                              {fileContent.language}
                            </span>
                          )}
                        </div>
                        <div className="flex-1 overflow-auto">
                          <CodeViewer
                            content={fileContent.content}
                            language={fileContent.language}
                            symbols={fileContent.symbols}
                            scrollToLine={scrollToLine}
                          />
                        </div>
                      </div>
                    ) : null}
                  </div>
                </>
              )}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}

export default function RepoPage() {
  return (
    <AuthGuard>
      <Suspense
        fallback={
          <div className="flex items-center justify-center h-screen">
            <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
          </div>
        }
      >
        <RepoBrowser />
      </Suspense>
    </AuthGuard>
  );
}
