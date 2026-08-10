"use client";

import { useState, useEffect, useRef } from "react";
import { Search, FileCode2, X, Loader2 } from "lucide-react";
import { semanticSearch, type SearchResult } from "@/lib/api";

interface SearchBarProps {
  repoId: string;
  onSelectResult: (filePath: string, line: number) => void;
}

export default function SearchBar({ repoId, onSelectResult }: SearchBarProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Debounced search
  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      setOpen(false);
      return;
    }

    setLoading(true);
    const timer = setTimeout(async () => {
      try {
        const r = await semanticSearch(repoId, query);
        setResults(r);
        setOpen(true);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [query, repoId]);

  // Close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  return (
    <div className="relative" ref={containerRef}>
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => results.length > 0 && setOpen(true)}
          placeholder='Search by meaning... (e.g. "how is auth handled")'
          className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 pl-10 pr-10 py-2 text-sm placeholder:text-zinc-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-shadow"
        />
        {query && (
          <button
            onClick={() => {
              setQuery("");
              setResults([]);
              setOpen(false);
            }}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {loading && (
        <div className="absolute right-10 top-1/2 -translate-y-1/2">
          <Loader2 className="w-4 h-4 animate-spin text-zinc-400" />
        </div>
      )}

      {open && results.length > 0 && (
        <ul className="absolute z-50 mt-1 w-full bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg shadow-xl max-h-96 overflow-auto">
          {results.map((r) => (
            <li key={r.symbol_id}>
              <button
                onClick={() => {
                  onSelectResult(r.file_path, r.start_line);
                  setOpen(false);
                  setQuery("");
                }}
                className="w-full text-left px-4 py-3 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors border-b border-zinc-100 dark:border-zinc-800 last:border-0"
              >
                <div className="flex items-center gap-2">
                  <FileCode2 className="w-4 h-4 shrink-0 text-zinc-400" />
                  <span className="font-mono text-sm font-medium text-zinc-800 dark:text-zinc-200">
                    <span className="text-zinc-400 text-xs mr-1">
                      {r.symbol_kind}
                    </span>
                    {r.symbol_name}
                  </span>
                  <span className="ml-auto text-[10px] text-zinc-400 font-mono">
                    {(r.score * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="text-xs text-zinc-500 mt-0.5 font-mono">
                  {r.file_path}:{r.start_line}
                </div>
                <div className="text-xs text-zinc-400 mt-1 truncate font-mono">
                  {r.source_preview}
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}

      {open && query.trim() && !loading && results.length === 0 && (
        <div className="absolute z-50 mt-1 w-full bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg shadow-xl p-4 text-sm text-zinc-500 text-center">
          No results found for &ldquo;{query}&rdquo;
        </div>
      )}
    </div>
  );
}
