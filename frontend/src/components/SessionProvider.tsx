"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { auth, onSessionExpired } from "@/lib/client/api";
import { ApiError, apiErrorFromBody } from "@/lib/errors";
import type { User } from "@/lib/types";

interface SessionState {
  user: User | null;
  loading: boolean;
  error: unknown;
  logout: () => Promise<void>;
  /** Reload /auth/me (e.g. after a demo question or a demo conversion). */
  refresh: () => Promise<void>;
  /** Apply the questions-left count an /ask answer reported, without a round trip. */
  setDemoQuestionsRemaining: (remaining: number) => void;
}

const SessionContext = createContext<SessionState | null>(null);

export function useSession(): SessionState {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <SessionProvider>");
  return value;
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const toLogin = useCallback(
    (reason: string) => {
      const params = new URLSearchParams({ reason });
      if (pathname && pathname !== "/") params.set("next", pathname);
      router.replace(`/login?${params.toString()}`);
    },
    [pathname, router],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch("/api/auth/session", { cache: "no-store" });
        const body: unknown = await response.json().catch(() => null);
        if (cancelled) return;
        if (response.status === 401) {
          toLogin("expired");
          return;
        }
        if (!response.ok) throw apiErrorFromBody(response.status, body, response.headers);
        setUser(body as User);
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err : new ApiError(0, "network_error", "Network error"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // Load once per app mount; later 401s arrive through onSessionExpired.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => onSessionExpired(() => toLogin("expired")), [toLogin]);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch("/api/auth/session", { cache: "no-store" });
      if (response.ok) setUser((await response.json()) as User);
    } catch {
      // keep the current user; the next API call surfaces real problems
    }
  }, []);

  const setDemoQuestionsRemaining = useCallback((remaining: number) => {
    setUser((current) =>
      current?.demo
        ? {
            ...current,
            demo: {
              ...current.demo,
              questions_remaining: remaining,
              questions_used: current.demo.questions_limit - remaining,
            },
          }
        : current,
    );
  }, []);

  const logout = useCallback(async () => {
    try {
      await auth.logout();
    } finally {
      setUser(null);
      router.replace("/login?reason=signed-out");
      router.refresh();
    }
  }, [router]);

  return (
    <SessionContext.Provider value={{ user, loading, error, logout, refresh, setDemoQuestionsRemaining }}>
      {children}
    </SessionContext.Provider>
  );
}
