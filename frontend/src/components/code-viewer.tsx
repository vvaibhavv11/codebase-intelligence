"use client";

import { useEffect, useState, useCallback } from "react";
import { codeToHtml } from "shiki";
import { Loader2, List } from "lucide-react";
import type { SymbolInfo } from "@/lib/api";

interface CodeViewerProps {
  content: string;
  language: string | null;
  symbols: SymbolInfo[];
  scrollToLine?: number | null;
}

export default function CodeViewer({
  content,
  language,
  symbols,
  scrollToLine,
}: CodeViewerProps) {
  const [html, setHtml] = useState("");
  const [loading, setLoading] = useState(true);
  const [showSymbols, setShowSymbols] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    const lang = normalizeLanguage(language);
    codeToHtml(content, {
      lang,
      theme: "github-dark",
      transformers: [
        {
          line(node, line) {
            node.properties["data-line"] = line;
          },
        },
      ],
    })
      .then((h) => {
        if (!cancelled) {
          setHtml(h);
          setLoading(false);
        }
      })
      .catch(() => {
        // Fallback to plaintext if language isn't supported
        if (!cancelled) {
          codeToHtml(content, {
            lang: "text",
            theme: "github-dark",
            transformers: [
              {
                line(node, line) {
                  node.properties["data-line"] = line;
                },
              },
            ],
          }).then((h) => {
            if (!cancelled) {
              setHtml(h);
              setLoading(false);
            }
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [content, language]);

  // Scroll to line after rendering
  useEffect(() => {
    if (!loading && scrollToLine) {
      setTimeout(() => {
        const el = document.querySelector(`[data-line="${scrollToLine}"]`);
        el?.scrollIntoView({ behavior: "smooth", block: "center" });
        // Brief highlight
        if (el) {
          (el as HTMLElement).style.backgroundColor = "rgba(59, 130, 246, 0.2)";
          setTimeout(() => {
            (el as HTMLElement).style.backgroundColor = "";
          }, 2000);
        }
      }, 100);
    }
  }, [loading, scrollToLine]);

  const handleSymbolClick = useCallback((line: number) => {
    const el = document.querySelector(`[data-line="${line}"]`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    if (el) {
      (el as HTMLElement).style.backgroundColor = "rgba(59, 130, 246, 0.2)";
      setTimeout(() => {
        (el as HTMLElement).style.backgroundColor = "";
      }, 2000);
    }
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
      </div>
    );
  }

  return (
    <div className="flex h-full">
      {/* Code */}
      <div
        className="flex-1 overflow-auto"
        dangerouslySetInnerHTML={{ __html: html }}
      />

      {/* Symbol sidebar */}
      {symbols.length > 0 && (
        <div
          className={`border-l border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900/50 transition-all ${
            showSymbols ? "w-64" : "w-10"
          }`}
        >
          <button
            onClick={() => setShowSymbols(!showSymbols)}
            className="w-full flex items-center gap-2 px-3 py-2 text-xs font-medium text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 border-b border-zinc-200 dark:border-zinc-700"
            title="Toggle symbol list"
          >
            <List className="w-3.5 h-3.5 shrink-0" />
            {showSymbols && <span>Symbols ({symbols.length})</span>}
          </button>
          {showSymbols && (
            <ul className="overflow-y-auto max-h-[calc(100vh-12rem)] p-2 space-y-0.5">
              {symbols.map((sym) => (
                <li key={sym.id}>
                  <button
                    onClick={() => handleSymbolClick(sym.start_line)}
                    className="w-full text-left rounded px-2 py-1.5 text-xs hover:bg-zinc-200 dark:hover:bg-zinc-800 transition-colors group"
                  >
                    <div className="flex items-center gap-1.5">
                      <SymbolKindBadge kind={sym.kind} />
                      <span className="font-mono truncate font-medium text-zinc-700 dark:text-zinc-300 group-hover:text-blue-600 dark:group-hover:text-blue-400">
                        {sym.name}
                      </span>
                    </div>
                    <div className="text-[10px] text-zinc-400 mt-0.5">
                      L{sym.start_line}
                      {sym.end_line !== sym.start_line && `-${sym.end_line}`}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function SymbolKindBadge({ kind }: { kind: string }) {
  const colors: Record<string, string> = {
    function:
      "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
    class:
      "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
    method:
      "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  };

  const abbrev: Record<string, string> = {
    function: "fn",
    class: "cls",
    method: "mt",
  };

  return (
    <span
      className={`inline-flex items-center justify-center w-5 h-4 rounded text-[9px] font-bold uppercase shrink-0 ${
        colors[kind] ??
        "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
      }`}
    >
      {abbrev[kind] ?? kind.slice(0, 2)}
    </span>
  );
}

function normalizeLanguage(lang: string | null): string {
  if (!lang) return "text";
  const map: Record<string, string> = {
    typescript: "typescript",
    javascript: "javascript",
    python: "python",
    tsx: "tsx",
    jsx: "jsx",
    css: "css",
    html: "html",
    json: "json",
    yaml: "yaml",
    yml: "yaml",
    markdown: "markdown",
    md: "markdown",
    toml: "toml",
    shell: "bash",
    bash: "bash",
    sh: "bash",
    sql: "sql",
    rust: "rust",
    go: "go",
    java: "java",
    c: "c",
    cpp: "cpp",
    "c++": "cpp",
    ruby: "ruby",
    php: "php",
  };
  return map[lang.toLowerCase()] ?? lang.toLowerCase();
}
