"use client";

import { useState, useEffect, useRef } from "react";
import { LogOut, User } from "lucide-react";

export default function UserMenu() {
  const [username, setUsername] = useState<string | null>(null);
  const [avatar, setAvatar] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setUsername(localStorage.getItem("gh_username"));
    setAvatar(localStorage.getItem("gh_avatar"));
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  function handleSignOut() {
    localStorage.removeItem("gh_token");
    localStorage.removeItem("gh_username");
    localStorage.removeItem("gh_avatar");
    setUsername(null);
    setAvatar(null);
    setOpen(false);
  }

  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  if (!username) {
    return (
      <a
        href={`${apiUrl}/api/auth/github/login`}
        className="inline-flex items-center gap-2 rounded-lg border border-zinc-200 dark:border-zinc-700 px-3 py-1.5 text-sm font-medium text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
      >
        <User className="w-4 h-4" />
        Sign in
      </a>
    );
  }

  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 rounded-lg px-2 py-1 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
      >
        {avatar ? (
          <img
            src={avatar}
            alt={username}
            className="w-7 h-7 rounded-full"
          />
        ) : (
          <User className="w-5 h-5 text-zinc-500" />
        )}
        <span className="text-sm font-medium">{username}</span>
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-48 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-lg z-50">
          <button
            onClick={handleSignOut}
            className="flex w-full items-center gap-2 rounded-lg px-4 py-2.5 text-sm text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
