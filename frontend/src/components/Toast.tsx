"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";

type Tone = "success" | "error" | "info";

interface ToastItem {
  id: number;
  tone: Tone;
  title: string;
  message?: string;
}

interface ToastApi {
  show: (toast: Omit<ToastItem, "id">) => void;
}

const ToastContext = createContext<ToastApi | null>(null);
const DURATION_MS = 5000;

export function useToast(): ToastApi {
  return useContext(ToastContext) ?? { show: () => undefined };
}

const TONES: Record<Tone, string> = {
  success: "text-emerald-700 dark:text-emerald-800",
  error: "text-red-700 dark:text-red-800",
  info: "text-brand-700",
};

const ICONS: Record<Tone, React.ReactNode> = {
  success: <path d="m5 12 4.5 4.5L19 7" strokeLinecap="round" strokeLinejoin="round" />,
  error: <path d="M12 8v5m0 3.5v.5M10.3 3.9 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" strokeLinecap="round" strokeLinejoin="round" />,
  info: <path d="M12 11v6m0-9.5V8M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" strokeLinecap="round" />,
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const next = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const show = useCallback(
    (toast: Omit<ToastItem, "id">) => {
      const id = next.current++;
      setToasts((current) => [...current.slice(-2), { ...toast, id }]);
      window.setTimeout(() => dismiss(id), DURATION_MS);
    },
    [dismiss],
  );

  const api = useMemo(() => ({ show }), [show]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed inset-x-0 bottom-20 z-[60] flex flex-col items-center gap-2 px-4 sm:bottom-6 sm:items-end sm:pr-6"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role={toast.tone === "error" ? "alert" : "status"}
            data-testid="toast"
            className="pointer-events-auto flex w-full max-w-sm animate-slide-up items-start gap-3 rounded-xl border border-border bg-surface p-3.5 text-sm shadow-pop"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={`mt-0.5 h-4 w-4 shrink-0 ${TONES[toast.tone]}`} aria-hidden="true">
              {ICONS[toast.tone]}
            </svg>
            <div className="min-w-0 flex-1">
              <p className="font-medium text-fg">{toast.title}</p>
              {toast.message ? <p className="mt-0.5 text-muted">{toast.message}</p> : null}
            </div>
            <button
              type="button"
              onClick={() => dismiss(toast.id)}
              className="rounded p-0.5 text-subtle hover:text-fg"
              aria-label="Dismiss notification"
            >
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M6 6l12 12M18 6 6 18" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
