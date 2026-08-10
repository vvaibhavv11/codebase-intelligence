"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
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
} from "lucide-react";
import Link from "next/link";
import { getRepo, getFileTree, getFileContent } from "@/lib/api";
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
  const [chatOpen, setChatOpen] = useState(false);

  // Fetch repo info
  const { data: repo } = useQuery({
    queryKey: ["repo", repoId],
    queryFn: () => getRepo(repoId),
  });

  // Fetch file tree
  const {
    data: tree,
    isLoading: treeLoading,
    error: treeError,
  } = useQuery({
    queryKey: ["tree", repoId],
    queryFn: () => getFileTree(repoId),
    enabled: activeTab === "files",
  });

  // Fetch file content
  const {
    data: fileContent,
    isLoading: fileLoading,
  } = useQuery({
    queryKey: ["file", repoId, selectedPath],
    queryFn: () => getFileContent(repoId, selectedPath!),
    enabled: activeTab === "files" && !!selectedPath,
  });

  const navigateToFile = useCallback(
    (filePath: string, line?: number) => {
      setActiveTab("files");
      setSelectedPath(filePath);
      setScrollToLine(line ?? null);
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
    }
    if (line) {
      setScrollToLine(Number(line));
    }
  }, [searchParams]);

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
          onClick={() => setChatOpen(!chatOpen)}
          className="ml-auto flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
          title={chatOpen ? "Close chat" : "Open chat"}
        >
          {chatOpen ? (
            <PanelRightClose className="w-4 h-4" />
          ) : (
            <PanelRightOpen className="w-4 h-4" />
          )}
          Chat
        </button>
      </header>

      {/* Tab bar */}
      <div className="flex items-center gap-1 px-4 h-10 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50/60 dark:bg-zinc-900/60 shrink-0 overflow-x-auto">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
              activeTab === id
                ? "text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-950/40"
                : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {activeTab === "graph" ? (
          <main className="flex-1 overflow-auto p-4">
            <DependencyGraph
              repoId={repoId}
              onSelectNode={handleGraphNodeSelect}
            />
          </main>
        ) : activeTab === "commits" ? (
          <main className="flex-1 overflow-auto p-4">
            <CommitList repoId={repoId} />
          </main>
        ) : activeTab === "readme" ? (
          <main className="flex-1 overflow-hidden">
            <GeneratedDocs repoId={repoId} mode="readme" />
          </main>
        ) : (
          <>
            {/* File tree sidebar */}
            <aside className="w-72 shrink-0 border-r border-zinc-200 dark:border-zinc-700 bg-zinc-50/50 dark:bg-zinc-900/50 overflow-y-auto">
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
            </aside>

            {/* Code viewer */}
            <main className="flex-1 overflow-hidden">
              {!selectedPath ? (
                <div className="flex flex-col items-center justify-center h-full text-zinc-400">
                  <FileCode2 className="w-16 h-16 mb-4 opacity-30" />
                  <p className="text-sm">Select a file to view its contents</p>
                  <p className="text-xs mt-1">
                    Or use the search bar to find code by meaning
                  </p>
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
            </main>
          </>
        )}

        {/* Chat panel */}
        {chatOpen && (
          <aside className="w-96 shrink-0 border-l border-zinc-200 dark:border-zinc-700">
            <ChatPanel repoId={repoId} />
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
