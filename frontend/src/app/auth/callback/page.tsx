"use client";

import { useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";

function CallbackHandler() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const token = searchParams.get("token");
    const username = searchParams.get("username");
    const avatar = searchParams.get("avatar");

    if (token) {
      localStorage.setItem("gh_token", token);
      if (username) localStorage.setItem("gh_username", username);
      if (avatar) localStorage.setItem("gh_avatar", avatar);
      router.push("/");
    } else {
      router.push("/login?error=failed");
    }
  }, [router, searchParams]);

  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-3">
      <Loader2 className="w-8 h-8 animate-spin text-blue-600" />
      <p className="text-sm text-zinc-500">Signing in...</p>
    </div>
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="flex flex-col items-center justify-center min-h-screen gap-3">
          <Loader2 className="w-8 h-8 animate-spin text-blue-600" />
          <p className="text-sm text-zinc-500">Signing in...</p>
        </div>
      }
    >
      <CallbackHandler />
    </Suspense>
  );
}
