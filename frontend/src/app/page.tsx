"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, Code2, Loader2 } from "lucide-react";
import { listRepos } from "@/lib/api";
import RepoCard from "@/components/repo-card";
import ConnectRepoDialog from "@/components/connect-repo-dialog";
import UserMenu from "@/components/user-menu";
import AuthGuard from "@/components/auth-guard";

export default function Home() {
  const [dialogOpen, setDialogOpen] = useState(false);

  const { data: repos, isLoading } = useQuery({
    queryKey: ["repos"],
    queryFn: listRepos,
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.some(
        (r) =>
          r.status === "pending" ||
          r.status === "cloning" ||
          r.status === "indexing"
      )
        ? 2000
        : false;
    },
  });

  return (
    <AuthGuard>
      <div className="flex-1 flex flex-col">
      {/* Header */}
      <header className="border-b border-zinc-200 dark:border-zinc-800 bg-white/80 dark:bg-zinc-900/80 backdrop-blur-sm sticky top-0 z-40">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Code2 className="w-6 h-6 text-blue-600" />
            <h1 className="text-xl font-bold tracking-tight">
              Codebase Intelligence
            </h1>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setDialogOpen(true)}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
            >
              <Plus className="w-4 h-4" />
              Connect Repo
            </button>
            <UserMenu />
          </div>
        </div>
      </header>

      {/* Main */}
      <main className="flex-1 max-w-6xl mx-auto px-6 py-8 w-full">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
          </div>
        ) : !repos || repos.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <Code2 className="w-16 h-16 text-zinc-300 dark:text-zinc-600 mb-4" />
            <h2 className="text-xl font-semibold text-zinc-700 dark:text-zinc-300 mb-2">
              No repositories connected
            </h2>
            <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-6 max-w-md">
              Connect a GitHub repository to start browsing, searching, and
              chatting about your code with AI.
            </p>
            <button
              onClick={() => setDialogOpen(true)}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
            >
              <Plus className="w-4 h-4" />
              Connect Your First Repo
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {repos.map((repo) => (
              <RepoCard key={repo.id} repo={repo} />
            ))}
          </div>
        )}
      </main>

      <ConnectRepoDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
      />
      </div>
    </AuthGuard>
  );
}
