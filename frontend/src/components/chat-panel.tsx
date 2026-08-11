"use client";

import { useCallback, useEffect, useRef, useState, useMemo } from "react";
import {
  MessageSquare,
  Send,
  StopCircle,
  Loader2,
  ChevronDown,
  Sparkles,
  Bot,
  User,
  FileCode2,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { codeToHtml } from "shiki";
import {
  streamChat,
  getSessions,
  getSession,
  type ChatSession,
  type ChatReference,
} from "@/lib/api";

interface ChatPanelProps {
  repoId: string;
  onOpenFile?: (path: string, line?: number) => void;
}

interface DisplayMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
  references?: ChatReference[];
}

/* ---------- Persisted reference marker ---------- */

const REFS_MARKER_RE = /<!--refs:[\s\S]*?-->/;

function stripRefsMarker(content: string): string {
  return content.replace(REFS_MARKER_RE, "");
}

function extractRefsFromContent(content: string): ChatReference[] | undefined {
  const match = content.match(REFS_MARKER_RE);
  if (!match) return undefined;
  try {
    const parsed = JSON.parse(match[0].slice(8, -3)); // strip <!--refs: and -->
    return Array.isArray(parsed) ? (parsed as ChatReference[]) : undefined;
  } catch {
    return undefined;
  }
}

/* ---------- Shiki-highlighted code block (async) ---------- */

function CodeBlock({
  code,
  language,
}: {
  code: string;
  language: string;
}) {
  const [html, setHtml] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    codeToHtml(code, { lang: language || "text", theme: "github-dark" })
      .then((h) => {
        if (!cancelled) setHtml(h);
      })
      .catch(() => {
        // fallback — try plaintext
        codeToHtml(code, { lang: "text", theme: "github-dark" }).then((h) => {
          if (!cancelled) setHtml(h);
        });
      });
    return () => {
      cancelled = true;
    };
  }, [code, language]);

  if (!html) {
    return (
      <pre className="chat-code-block bg-zinc-900 text-zinc-200 rounded-lg p-4 overflow-x-auto text-sm font-mono">
        <code>{code}</code>
      </pre>
    );
  }

  return (
    <div
      className="chat-code-block rounded-lg overflow-x-auto text-sm"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

/* ---------- Markdown renderer for assistant messages ---------- */

function MarkdownMessage({
  content,
  streaming,
}: {
  content: string;
  streaming?: boolean;
}) {
  // Memoize components object to avoid re-creating on every render
  const components = useMemo(
    () => ({
      code(props: React.ComponentProps<"code"> & { className?: string }) {
        const { children, className, ...rest } = props;
        const match = /language-(\w+)/.exec(className || "");

        // Fenced code block (has language class from markdown parser)
        if (match) {
          const code = String(children).replace(/\n$/, "");
          return (
            <div className="my-3 not-prose">
              <div className="flex items-center justify-between bg-zinc-800 rounded-t-lg px-3 py-1.5 text-xs text-zinc-400 font-mono">
                <span>{match[1]}</span>
              </div>
              <CodeBlock code={code} language={match[1]} />
            </div>
          );
        }

        // Check if this is a standalone code block (multi-line, no explicit language)
        const codeStr = String(children);
        const isBlock =
          !className &&
          (props as Record<string, unknown>).node &&
          ((props as Record<string, unknown>).node as { position?: { start?: { line?: number }; end?: { line?: number } } })?.position &&
          ((props as Record<string, unknown>).node as { position: { start: { line: number }; end: { line: number } } }).position.start.line !==
            ((props as Record<string, unknown>).node as { position: { start: { line: number }; end: { line: number } } }).position.end.line;

        if (isBlock) {
          return (
            <div className="my-3 not-prose">
              <CodeBlock code={codeStr.replace(/\n$/, "")} language="text" />
            </div>
          );
        }

        // Inline code
        return (
          <code
            className="bg-zinc-200 dark:bg-zinc-700 text-zinc-800 dark:text-zinc-200 rounded px-1.5 py-0.5 text-[0.85em] font-mono"
            {...rest}
          >
            {children}
          </code>
        );
      },
      pre(props: React.ComponentProps<"pre">) {
        // Strip the <pre> wrapper — our CodeBlock handles its own container
        const { children } = props;
        return <>{children}</>;
      },
    }),
    []
  );

  return (
    <div className="chat-markdown prose prose-sm dark:prose-invert max-w-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
      {streaming && (
        <span className="inline-block w-2 h-4 bg-blue-500 dark:bg-blue-400 animate-cursor-blink ml-0.5 align-middle rounded-sm" />
      )}
    </div>
  );
}

/* ---------- Main ChatPanel component ---------- */

export default function ChatPanel({ repoId, onOpenFile }: ChatPanelProps) {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Load sessions on mount
  useEffect(() => {
    getSessions(repoId)
      .then(setSessions)
      .catch(() => {});
  }, [repoId]);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg: DisplayMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
    };
    const assistantMsg: DisplayMessage = {
      id: crypto.randomUUID(),
      role: "assistant",
      content: "",
      streaming: true,
    };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput("");
    setLoading(true);

    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }

    const controller = new AbortController();
    abortRef.current = controller;

    let accumulated = "";

    try {
      await streamChat(
        repoId,
        text,
        sessionId,
        (chunk) => {
          accumulated += chunk;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsg.id ? { ...m, content: accumulated } : m
            )
          );
        },
        (newSessionId) => {
          setSessionId(newSessionId);
          getSessions(repoId)
            .then(setSessions)
            .catch(() => {});
        },
        (refs) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsg.id ? { ...m, references: refs } : m
            )
          );
        },
        controller.signal,
        (errorMessage) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsg.id
                ? { ...m, content: errorMessage, streaming: false }
                : m
            )
          );
        }
      );
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id
              ? {
                  ...m,
                  content:
                    accumulated + "\n\n_Error: failed to get response_",
                  streaming: false,
                }
              : m
          )
        );
      }
    } finally {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsg.id ? { ...m, streaming: false } : m
        )
      );
      setLoading(false);
      abortRef.current = null;
    }
  }, [input, loading, repoId, sessionId]);

  function handleAbort() {
    abortRef.current?.abort();
  }

  async function handleSessionChange(id: string) {
    if (id === "") {
      setSessionId(null);
      setMessages([]);
      return;
    }
    setSessionId(id);
    try {
      const session = await getSession(id);
      setMessages(
        session.messages?.map((m) => ({
          id: m.id,
          role: m.role as "user" | "assistant",
          content: m.content,
          references: extractRefsFromContent(m.content),
        })) ?? []
      );
    } catch {
      // ignore
    }
  }

  // Auto-resize textarea
  const handleTextareaChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      setInput(e.target.value);
      // Auto-resize
      e.target.style.height = "auto";
      e.target.style.height = Math.min(e.target.scrollHeight, 200) + "px";
    },
    []
  );

  return (
    <div className="flex flex-col h-full bg-white dark:bg-zinc-950">
      {/* Session bar */}
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50/80 dark:bg-zinc-900/80 shrink-0">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-blue-500" />
          <span className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
            AI Chat
          </span>
        </div>

        <div className="relative ml-auto">
          <select
            value={sessionId ?? ""}
            onChange={(e) => handleSessionChange(e.target.value)}
            className="appearance-none bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg text-xs px-3 py-1.5 pr-7 focus:outline-none focus:ring-2 focus:ring-blue-500 text-zinc-600 dark:text-zinc-400 cursor-pointer"
          >
            <option value="">New conversation</option>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title ?? "Untitled"}
              </option>
            ))}
          </select>
          <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-zinc-400 pointer-events-none" />
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-6">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500/10 to-purple-500/10 dark:from-blue-500/20 dark:to-purple-500/20 flex items-center justify-center mb-5">
              <Bot className="w-8 h-8 text-blue-500/70 dark:text-blue-400/70" />
            </div>
            <h2 className="text-lg font-semibold text-zinc-700 dark:text-zinc-300 mb-2">
              Ask about this codebase
            </h2>
            <p className="text-sm text-zinc-400 max-w-md leading-relaxed">
              I can explain how code works, find relevant functions,
              analyze dependencies, and help you understand the architecture.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-6 max-w-lg w-full">
              {[
                "What does this project do?",
                "How is authentication handled?",
                "What happens if I change the database schema?",
                "Explain the main entry point",
              ].map((suggestion) => (
                <button
                  key={suggestion}
                  onClick={() => {
                    setInput(suggestion);
                    textareaRef.current?.focus();
                  }}
                  className="text-left text-xs px-3 py-2.5 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-500 dark:text-zinc-400 hover:border-blue-300 dark:hover:border-blue-700 hover:text-blue-600 dark:hover:text-blue-400 hover:bg-blue-50/50 dark:hover:bg-blue-950/30 transition-colors"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
            {messages.map((m) => (
              <div key={m.id} className="flex gap-3">
                {/* Avatar */}
                <div
                  className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5 ${
                    m.role === "user"
                      ? "bg-blue-600 text-white"
                      : "bg-zinc-200 dark:bg-zinc-700 text-zinc-600 dark:text-zinc-300"
                  }`}
                >
                  {m.role === "user" ? (
                    <User className="w-3.5 h-3.5" />
                  ) : (
                    <Bot className="w-3.5 h-3.5" />
                  )}
                </div>

                {/* Message content */}
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium text-zinc-400 mb-1">
                    {m.role === "user" ? "You" : "Assistant"}
                  </div>
                  {m.role === "user" ? (
                    <div className="text-sm text-zinc-800 dark:text-zinc-200 whitespace-pre-wrap break-words">
                      {m.content}
                    </div>
                  ) : (
                    <>
                      <MarkdownMessage
                        content={stripRefsMarker(m.content)}
                        streaming={m.streaming}
                      />
                      {m.references && m.references.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mt-2">
                          {m.references.map((ref, index) => (
                            <button
                              key={`${ref.file_path}:${ref.start_line}:${index}`}
                              onClick={() =>
                                onOpenFile?.(ref.file_path, ref.start_line)
                              }
                              title={`View ${ref.symbol_name} in ${ref.file_path}`}
                              className="flex items-center gap-1.5 rounded-full border border-blue-200 dark:border-blue-800 bg-blue-50/60 dark:bg-blue-950/30 px-2.5 py-1 text-xs font-mono text-blue-700 dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-blue-900/40 hover:border-blue-300 dark:hover:border-blue-700 transition-colors"
                            >
                              <FileCode2 className="w-3 h-3 shrink-0" />
                              <span className="font-semibold">
                                {ref.symbol_name}
                              </span>
                              <span className="text-blue-400 dark:text-blue-500">
                                {ref.file_path}:{ref.start_line}
                              </span>
                            </button>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="border-t border-zinc-200 dark:border-zinc-800 bg-zinc-50/80 dark:bg-zinc-900/80 p-4 shrink-0">
        <div className="max-w-3xl mx-auto">
          <div className="flex items-end gap-3 bg-white dark:bg-zinc-800 rounded-xl border border-zinc-200 dark:border-zinc-700 focus-within:ring-2 focus-within:ring-blue-500 focus-within:border-transparent transition-shadow px-4 py-3">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={handleTextareaChange}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  sendMessage();
                }
              }}
              placeholder="Ask about the codebase..."
              className="flex-1 text-sm bg-transparent resize-none focus:outline-none placeholder:text-zinc-400 text-zinc-800 dark:text-zinc-200 min-h-[24px] max-h-[200px]"
              rows={1}
            />
            {loading ? (
              <button
                onClick={handleAbort}
                className="shrink-0 w-8 h-8 flex items-center justify-center rounded-lg bg-red-600 text-white hover:bg-red-700 transition-colors"
                title="Stop generating"
              >
                <StopCircle className="w-4 h-4" />
              </button>
            ) : (
              <button
                onClick={sendMessage}
                disabled={!input.trim()}
                className="shrink-0 w-8 h-8 flex items-center justify-center rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                title="Send message"
              >
                <Send className="w-4 h-4" />
              </button>
            )}
          </div>
          <p className="text-[10px] text-zinc-400 text-center mt-2">
            Enter to send, Shift+Enter for new line
          </p>
        </div>
      </div>
    </div>
  );
}
