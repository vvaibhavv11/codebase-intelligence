"use client";

import Link from "next/link";
import {
  GitBranch,
  Clock,
  RefreshCw,
  Loader2,
  CheckCircle2,
  XCircle,
  Circle,
  AlertCircle,
} from "lucide-react";
import type { Repo } from "@/lib/api";
import { triggerIndex } from "@/lib/api";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

const statusConfig: Record<
  Repo["status"],
  { label: string; color: string; icon: React.ReactNode }
> = {
  pending: {
    label: "Pending",
    color: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
    icon: <Circle className="w-3 h-3" />,
  },
  cloning: {
    label: "Cloning",
    color: "bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-400",
    icon: <Loader2 className="w-3 h-3 animate-spin" />,
  },
  indexing: {
    label: "Indexing",
    color:
      "bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-400",
    icon: <Loader2 className="w-3 h-3 animate-spin" />,
  },
  ready: {
    label: "Ready",
    color:
      "bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-400",
    icon: <CheckCircle2 className="w-3 h-3" />,
  },
  error: {
    label: "Error",
    color: "bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-400",
    icon: <XCircle className="w-3 h-3" />,
  },
};

export default function RepoCard({ repo }: { repo: Repo }) {
  const queryClient = useQueryClient();
  const [reindexing, setReindexing] = useState(false);
  const status = statusConfig[repo.status];
  const isInProgress = repo.status === "cloning" || repo.status === "indexing";

  async function handleReindex() {
    setReindexing(true);
    try {
      await triggerIndex(repo.id);
      queryClient.invalidateQueries({ queryKey: ["repos"] });
    } catch {
      // silently ignore -- status will reflect error
    } finally {
      setReindexing(false);
    }
  }

  return (
    <div className="group relative rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/50 p-5 transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <Link
            href={`/repos/${repo.id}`}
            className="text-lg font-semibold text-foreground hover:text-blue-600 dark:hover:text-blue-400 transition-colors truncate block"
          >
            {repo.name}
          </Link>
          <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-0.5">
            {repo.owner}
          </p>
        </div>
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${status.color}`}
        >
          {status.icon}
          {status.label}
        </span>
      </div>

      <div className="mt-4 flex items-center gap-4 text-xs text-zinc-500 dark:text-zinc-400">
        <span className="inline-flex items-center gap-1">
          <GitBranch className="w-3.5 h-3.5" />
          {repo.default_branch}
        </span>
        <span className="inline-flex items-center gap-1">
          <Clock className="w-3.5 h-3.5" />
          {new Date(repo.created_at).toLocaleDateString()}
        </span>
      </div>

      {repo.error_message && (
        <div className="mt-3 flex items-start gap-2 rounded-lg bg-red-50 dark:bg-red-900/20 px-3 py-2 text-xs text-red-700 dark:text-red-400">
          <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span className="line-clamp-2">{repo.error_message}</span>
        </div>
      )}

      {!isInProgress && repo.status !== "ready" && (
        <button
          onClick={handleReindex}
          disabled={reindexing}
          className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-zinc-100 dark:bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors disabled:opacity-50"
        >
          <RefreshCw
            className={`w-3 h-3 ${reindexing ? "animate-spin" : ""}`}
          />
          {repo.status === "error" ? "Retry" : "Index"}
        </button>
      )}

      {repo.status === "ready" && (
        <div className="mt-3 flex items-center gap-2">
          <Link
            href={`/repos/${repo.id}`}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 transition-colors"
          >
            Browse Code
          </Link>
          <button
            onClick={handleReindex}
            disabled={reindexing}
            className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-100 dark:bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors disabled:opacity-50"
          >
            <RefreshCw
              className={`w-3 h-3 ${reindexing ? "animate-spin" : ""}`}
            />
            Re-index
          </button>
        </div>
      )}
    </div>
  );
}
