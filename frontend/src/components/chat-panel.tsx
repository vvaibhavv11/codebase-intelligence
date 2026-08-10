"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  MessageSquare,
  Send,
  StopCircle,
  Loader2,
  ChevronDown,
} from "lucide-react";
import {
  streamChat,
  getSessions,
  getSession,
  type ChatSession,
} from "@/lib/api";

interface ChatPanelProps {
  repoId: string;
}

interface DisplayMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}

export default function ChatPanel({ repoId }: ChatPanelProps) {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

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
        })) ?? []
      );
    } catch {
      // ignore
    }
  }

  return (
    <div className="flex flex-col h-full bg-white dark:bg-zinc-900">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-200 dark:border-zinc-700">
        <MessageSquare className="w-4 h-4 text-zinc-500" />
        <span className="text-sm font-medium">AI Chat</span>
      </div>

      {/* Session picker */}
      <div className="px-3 py-2 border-b border-zinc-200 dark:border-zinc-700">
        <div className="relative">
          <select
            value={sessionId ?? ""}
            onChange={(e) => handleSessionChange(e.target.value)}
            className="w-full appearance-none bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg text-sm px-3 py-1.5 pr-8 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">New conversation</option>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title ?? "Untitled"}
              </option>
            ))}
          </select>
          <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400 pointer-events-none" />
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center text-zinc-400">
            <MessageSquare className="w-10 h-10 mb-3 opacity-50" />
            <p className="text-sm">Ask about the codebase</p>
            <p className="text-xs mt-1">
              e.g. &ldquo;What does this project do?&rdquo;
            </p>
          </div>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] rounded-xl px-4 py-2.5 text-sm ${
                m.role === "user"
                  ? "bg-blue-600 text-white"
                  : "bg-zinc-100 dark:bg-zinc-800 text-zinc-800 dark:text-zinc-200"
              }`}
            >
              <div className="whitespace-pre-wrap break-words">
                {m.content}
                {m.streaming && (
                  <span className="inline-block w-2 h-4 bg-zinc-400 dark:bg-zinc-500 animate-cursor-blink ml-0.5 align-middle rounded-sm" />
                )}
              </div>
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-3 border-t border-zinc-200 dark:border-zinc-700">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
              }
            }}
            placeholder='Ask about the codebase... e.g. "Explain how authentication works"'
            className="flex-1 text-sm border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 rounded-lg p-2.5 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder:text-zinc-400"
            rows={2}
          />
          {loading ? (
            <button
              onClick={handleAbort}
              className="self-end px-3 py-2.5 rounded-lg bg-red-600 text-white hover:bg-red-700 transition-colors"
              title="Stop generating"
            >
              <StopCircle className="w-4 h-4" />
            </button>
          ) : (
            <button
              onClick={sendMessage}
              disabled={!input.trim()}
              className="self-end px-3 py-2.5 rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              title="Send message"
            >
              <Send className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
