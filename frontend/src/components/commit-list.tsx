"use client";

import { useMemo, useState, useCallback, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Loader2,
  GitCommitHorizontal,
  ChevronDown,
  ChevronRight,
  Sparkles,
  X,
} from "lucide-react";
import {
  getCommits,
  getCommitDiff,
  streamDiffAnalysis,
} from "@/lib/api";
import type { CommitSummary, FileDiff } from "@/lib/api";
import ReactMarkdown from "react-markdown";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function DiffView({ file }: { file: FileDiff }) {
  const [expanded, setExpanded] = useState(false);
  const lines = useMemo(() => {
    if (!file.patch) return [];
    const out: { text: string; type: "add" | "del" | "ctx" }[] = [];
    for (const line of file.patch.split("\n")) {
      if (line.startsWith("+") && !line.startsWith("+++")) {
        out.push({ text: line, type: "add" });
      } else if (line.startsWith("-") && !line.startsWith("---")) {
        out.push({ text: line, type: "del" });
      } else {
        out.push({ text: line, type: "ctx" });
      }
    }
    return out;
  }, [file.patch]);

  return (
    <div className="border border-zinc-200 dark:border-zinc-700 rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left text-xs font-mono bg-zinc-50 dark:bg-zinc-900 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
      >
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5 text-zinc-400" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-zinc-400" />
        )}
        <span className="truncate flex-1">{file.file_path}</span>
        <span className="text-[10px] rounded bg-zinc-200 dark:bg-zinc-700 px-1.5 py-0.5 uppercase">
          {file.change_type}
        </span>
        <span className="text-[10px] text-green-600 dark:text-green-400">
          +{file.added_lines}
        </span>
        <span className="text-[10px] text-red-600 dark:text-red-400">
          -{file.removed_lines}
        </span>
      </button>
      {expanded && (
        <pre className="max-h-96 overflow-auto text-[11px] leading-5 font-mono p-3 bg-zinc-50 dark:bg-zinc-950">
          {lines.map((l, i) => (
            <div
              key={i}
              className={
                l.type === "add"
                  ? "bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300"
                  : l.type === "del"
                    ? "bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-300"
                    : "text-zinc-600 dark:text-zinc-400"
              }
            >
              {l.text}
            </div>
          ))}
        </pre>
      )}
    </div>
  );
}

export default function CommitList({ repoId }: { repoId: string }) {
  const [expandedSha, setExpandedSha] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<{
    sha: string;
    text: string;
    loading: boolean;
  } | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const { data: commits, isLoading, isError, refetch } = useQuery({
    queryKey: ["commits", repoId],
    queryFn: () => getCommits(repoId),
  });

  const { data: commitDiff, isFetching: diffLoading } = useQuery({
    queryKey: ["commit-diff", repoId, expandedSha],
    queryFn: () => getCommitDiff(repoId, expandedSha!),
    enabled: !!expandedSha,
  });

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const handleExpand = useCallback((sha: string) => {
    setExpandedSha((prev) => (prev === sha ? null : sha));
  }, []);

  const handleAnalyze = useCallback(
    (sha: string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setAnalysis({ sha, text: "", loading: true });

      streamDiffAnalysis(
        repoId,
        sha,
        null,
        (chunk) =>
          setAnalysis((prev) =>
            prev && prev.sha === sha
              ? { ...prev, text: prev.text + chunk }
              : prev
          ),
        () =>
          setAnalysis((prev) =>
            prev && prev.sha === sha ? { ...prev, loading: false } : prev
          ),
        controller.signal
      ).catch(() => {
        setAnalysis((prev) =>
          prev && prev.sha === sha ? { ...prev, loading: false } : prev
        );
      });
    },
    [repoId]
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16 text-zinc-400">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />
        Loading commits…
      </div>
    );
  }

  if (isError || !commits) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-sm text-red-500 gap-2">
        Failed to load commit history
        <button
          onClick={() => refetch()}
          className="text-xs rounded-lg px-3 py-1.5 bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  if (commits.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-zinc-400 gap-2">
        <GitCommitHorizontal className="w-10 h-10 opacity-40" />
        <p className="text-sm">No commits found.</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {commits.map((c: CommitSummary) => (
        <div key={c.sha} className="rounded-lg border border-zinc-200 dark:border-zinc-700 overflow-hidden">
          <button
            onClick={() => handleExpand(c.sha)}
            className="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-zinc-50 dark:hover:bg-zinc-900 transition-colors"
          >
            {expandedSha === c.sha ? (
              <ChevronDown className="w-4 h-4 text-zinc-400 shrink-0" />
            ) : (
              <ChevronRight className="w-4 h-4 text-zinc-400 shrink-0" />
            )}
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{c.message}</p>
              <p className="text-xs text-zinc-400 mt-0.5">
                {c.sha} · {c.author} · {formatDate(c.date)}
              </p>
            </div>
            <div className="flex items-center gap-2 text-xs font-mono shrink-0">
              <span className="text-green-600 dark:text-green-400">
                +{c.added_lines}
              </span>
              <span className="text-red-600 dark:text-red-400">
                -{c.removed_lines}
              </span>
              <span className="text-zinc-400">
                {c.files_changed} file{c.files_changed === 1 ? "" : "s"}
              </span>
            </div>
          </button>

          {expandedSha === c.sha && (
            <div className="border-t border-zinc-200 dark:border-zinc-700 p-3 space-y-3">
              {diffLoading ? (
                <div className="flex items-center justify-center py-6 text-zinc-400 text-sm">
                  <Loader2 className="w-4 h-4 animate-spin mr-2" />
                  Loading diff…
                </div>
              ) : commitDiff ? (
                <>
                  <div className="flex items-center justify-between">
                    <p className="text-xs text-zinc-500">{commitDiff.message}</p>
                    <button
                      onClick={() => handleAnalyze(c.sha)}
                      disabled={
                        analysis?.sha === c.sha && analysis.loading
                      }
                      className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-950/40 transition-colors disabled:opacity-50"
                    >
                      {analysis?.sha === c.sha && analysis.loading ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Sparkles className="w-3.5 h-3.5" />
                      )}
                      Analyze with AI
                    </button>
                  </div>

                  {commitDiff.files.map((f) => (
                    <DiffView key={f.file_path + f.change_type} file={f} />
                  ))}

                  {analysis && analysis.sha === c.sha && (
                    <div className="rounded-lg border border-violet-200 dark:border-violet-800 bg-violet-50/50 dark:bg-violet-950/30 p-3">
                      <div className="flex items-center justify-between mb-2">
                        <p className="text-xs font-semibold text-violet-700 dark:text-violet-300 flex items-center gap-1.5">
                          <Sparkles className="w-3.5 h-3.5" />
                          AI Analysis
                          {analysis.loading && (
                            <Loader2 className="w-3 h-3 animate-spin" />
                          )}
                        </p>
                        <button
                          onClick={() => setAnalysis(null)}
                          className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                      <div className="prose prose-sm dark:prose-invert max-w-none text-sm text-zinc-700 dark:text-zinc-300">
                        <ReactMarkdown>{analysis.text || "…"}</ReactMarkdown>
                      </div>
                    </div>
                  )}
                </>
              ) : null}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
