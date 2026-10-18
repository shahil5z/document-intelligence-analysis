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
    <SessionContext.Provider value={{ user, loading, error, logout }}>
      {children}
    </SessionContext.Provider>
  );
}
