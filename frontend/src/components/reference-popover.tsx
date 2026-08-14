"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { codeToHtml } from "shiki";
import { Loader2, FileWarning, ExternalLink } from "lucide-react";
import { getFileContent, type ChatReference } from "@/lib/api";
import { normalizeLanguage } from "@/components/code-viewer";

const POPOVER_WIDTH = 560;
const GAP = 8;

interface ReferencePopoverProps {
  repoId: string;
  reference: ChatReference;
  anchor: { left: number; top: number; width: number; height: number };
  onClose: () => void;
  onOpenFile?: (path: string, line?: number) => void;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
}

export default function ReferencePopover({
  repoId,
  reference,
  anchor,
  onClose,
  onOpenFile,
  onMouseEnter,
  onMouseLeave,
}: ReferencePopoverProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{
    left: number;
    top: number;
    maxHeight: number;
  } | null>(null);
  const [html, setHtml] = useState<string | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["file", repoId, reference.file_path],
    queryFn: () => getFileContent(repoId, reference.file_path),
  });

  const symbol = useMemo(() => {
    if (!data) return null;
    return (
      data.symbols.find((s) => s.start_line === reference.start_line) ??
      data.symbols.find(
        (s) =>
          s.start_line <= reference.start_line &&
          reference.start_line <= s.end_line
      ) ??
      null
    );
  }, [data, reference]);

  const snippet = useMemo(() => {
    if (!data) return "";
    const lines = data.content.split("\n");
    if (lines.length === 0) return "";
    const start = Math.min(Math.max(1, reference.start_line), lines.length);
    const end = Math.min(reference.end_line || start, lines.length);
    if (start > end) return "";
    return lines.slice(start - 1, end).join("\n");
  }, [data, reference]);

  useEffect(() => {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = anchor.left;
    if (left + POPOVER_WIDTH > vw - GAP) {
      left = Math.max(GAP, anchor.left + anchor.width / 2 - POPOVER_WIDTH / 2);
    }
    const spaceBelow = vh - (anchor.top + anchor.height) - GAP;
    const spaceAbove = anchor.top - GAP;
    if (spaceBelow >= 220 || spaceBelow >= spaceAbove) {
      setPos({
        left,
        top: anchor.top + anchor.height + GAP,
        maxHeight: Math.max(140, spaceBelow - GAP),
      });
    } else {
      const maxHeight = Math.max(140, spaceAbove - GAP);
      setPos({
        left,
        top: Math.max(GAP, anchor.top - maxHeight),
        maxHeight,
      });
    }
  }, [anchor]);

  useEffect(() => {
    let cancelled = false;
    if (!snippet) return;
    const lang = normalizeLanguage(data?.language ?? null);
    codeToHtml(snippet, { lang, theme: "github-dark" })
      .then((h) => {
        if (!cancelled) setHtml(h);
      })
      .catch(() => {
        codeToHtml(snippet, { lang: "text", theme: "github-dark" }).then((h) => {
          if (!cancelled) setHtml(h);
        });
      });
    return () => {
      cancelled = true;
    };
  }, [snippet, data?.language]);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        onClose();
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div
      ref={containerRef}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      className="fixed z-50 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-2xl overflow-hidden"
      style={{
        left: pos?.left ?? 0,
        top: pos?.top ?? 0,
        width: `min(${POPOVER_WIDTH}px, calc(100vw - ${GAP * 2}px))`,
        visibility: pos ? "visible" : "hidden",
      }}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2 px-3 py-2 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/80">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="font-mono font-semibold text-sm text-blue-700 dark:text-blue-300 truncate">
              {reference.symbol_name}
            </span>
            <KindBadge kind={reference.symbol_kind} />
          </div>
          <div className="font-mono text-[11px] text-zinc-500 dark:text-zinc-400 truncate mt-0.5">
            {reference.file_path}:{reference.start_line}
            {reference.end_line !== reference.start_line &&
              `-${reference.end_line}`}
          </div>
        </div>
        <button
          onClick={() =>
            onOpenFile?.(reference.file_path, reference.start_line)
          }
          className="shrink-0 flex items-center gap-1 rounded-md border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/40 px-2 py-1 text-[11px] font-medium text-blue-700 dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-blue-900/50 transition-colors"
          title="Open in code panel"
        >
          <ExternalLink className="w-3 h-3" />
          Open
        </button>
      </div>

      {/* Body */}
      <div style={{ maxHeight: pos?.maxHeight, overflowY: "auto" }}>
        {isLoading || !data ? (
          <div className="flex items-center gap-2 justify-center py-6 text-xs text-zinc-400">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading…
          </div>
        ) : isError ? (
          <div className="flex items-center gap-2 px-3 py-4 text-xs text-red-500">
            <FileWarning className="w-4 h-4 shrink-0" />
            Couldn&apos;t load {reference.file_path}
          </div>
        ) : (
          <div className="p-3 space-y-2">
            {symbol?.signature && (
              <div className="font-mono text-xs text-zinc-700 dark:text-zinc-300 bg-zinc-100 dark:bg-zinc-800 rounded-md px-2.5 py-1.5">
                {symbol.signature}
              </div>
            )}
            {symbol?.docstring && (
              <div className="text-xs text-zinc-500 dark:text-zinc-400 whitespace-pre-wrap max-h-24 overflow-y-auto leading-relaxed">
                {symbol.docstring}
              </div>
            )}
            {html ? (
              <div
                className="rounded-lg overflow-x-auto text-[12px] leading-relaxed"
                dangerouslySetInnerHTML={{ __html: html }}
              />
            ) : (
              <pre className="rounded-lg bg-zinc-900 text-zinc-200 p-3 text-[12px] font-mono overflow-x-auto whitespace-pre">
                {snippet || "—"}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function KindBadge({ kind }: { kind: string }) {
  const colors: Record<string, string> = {
    function:
      "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
    class: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
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
