"use client";

import { useState, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Sparkles, FileText } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  getRepoDocs,
  generateReadme,
  generateSymbolDoc,
} from "@/lib/api";
import type { GeneratedDoc } from "@/lib/api";

export default function GeneratedDocs({
  repoId,
  symbolId = null,
  symbolName = "",
  mode,
}: {
  repoId: string;
  symbolId?: string | null;
  symbolName?: string;
  mode: "readme" | "symbol";
}) {
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: docs, refetch } = useQuery({
    queryKey: ["docs", repoId],
    queryFn: () => getRepoDocs(repoId),
  });

  const doc: GeneratedDoc | undefined = docs?.find((d) =>
    mode === "readme"
      ? d.kind === "readme"
      : d.kind === "symbol_doc" && d.symbol_id === symbolId
  );

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    setError(null);
    try {
      if (mode === "readme") {
        await generateReadme(repoId);
      } else if (symbolId) {
        await generateSymbolDoc(symbolId);
      }
      await refetch();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed");
    } finally {
      setGenerating(false);
    }
  }, [mode, repoId, symbolId, refetch]);

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-4 py-2 border-b border-zinc-200 dark:border-zinc-700">
        <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wide">
          {mode === "readme" ? "README" : "AI Documentation"}
        </p>
        {!doc && (
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-950/40 transition-colors disabled:opacity-50"
          >
            {generating ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Sparkles className="w-3.5 h-3.5" />
            )}
            {generating
              ? "Generating…"
              : mode === "readme"
                ? "Generate README"
                : "Generate docs"}
          </button>
        )}
      </div>

      {error && (
        <div className="px-4 py-2 text-xs text-red-500 border-b border-red-200 dark:border-red-900">
          {error}
        </div>
      )}

      {doc ? (
        <div className="flex-1 overflow-auto p-4">
          <div className="prose prose-sm dark:prose-invert max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {doc.content}
            </ReactMarkdown>
          </div>
          <div className="mt-4 flex items-center justify-between">
            <p className="text-[10px] text-zinc-400">
              Generated {new Date(doc.created_at).toLocaleString()}
              {symbolName ? ` for ${symbolName}` : ""}
            </p>
            <button
              onClick={handleGenerate}
              disabled={generating}
              className="text-[11px] text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 transition-colors disabled:opacity-50"
            >
              Regenerate
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center flex-1 text-zinc-400 gap-2 p-6 text-center">
          <FileText className="w-10 h-10 opacity-40" />
          <p className="text-sm">
            {mode === "readme"
              ? "No README generated yet."
              : symbolId
                ? "No documentation for this symbol yet."
                : "Select a symbol to document."}
          </p>
          <p className="text-xs">
            {mode === "readme"
              ? "Generate an AI-written README from the indexed symbols."
              : "The AI will write docs from the symbol's source code."}
          </p>
        </div>
      )}
    </div>
  );
}
