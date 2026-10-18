"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "./api";

export interface Resource<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => void;
}

/** GET a proxied backend path; `path = null` skips the request. Keeps the last data while reloading. */
export function useApiResource<T>(path: string | null): Resource<T> {
  const [version, setVersion] = useState(0);
  const key = path === null ? null : `${path}#${version}`;
  const [settled, setSettled] = useState<{ key: string | null; data: T | null; error: unknown }>({
    key: null,
    data: null,
    error: null,
  });

  useEffect(() => {
    if (path === null || key === null) return;
    let cancelled = false;
    api
      .get<T>(path)
      .then((value) => {
        if (!cancelled) setSettled({ key, data: value, error: null });
      })
      .catch((err: unknown) => {
        if (!cancelled) setSettled((prev) => ({ key, data: prev.data, error: err }));
      });
    return () => {
      cancelled = true;
    };
  }, [path, key]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return {
    data: settled.data,
    error: settled.key === key ? settled.error : null,
    loading: key !== null && settled.key !== key,
    reload,
  };
}

/** Call `tick` every `intervalMs` while `active`; stops when the page is hidden/unmounted. */
export function useInterval(tick: () => void, intervalMs: number, active: boolean): void {
  const saved = useRef(tick);
  useEffect(() => {
    saved.current = tick;
  }, [tick]);
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") saved.current();
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs, active]);
}
