"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { ErrorAlert } from "@/components/ErrorAlert";
import { useSession } from "@/components/SessionProvider";
import { useToast } from "@/components/Toast";
import { Button, ButtonLink, Field, inputClass } from "@/components/ui";
import { auth, onDemoLimit } from "@/lib/client/api";

const PASSWORD_MIN_LENGTH = 12;

const LIMIT_TEXT: Record<string, string> = {
  questions: "You've used all 3 demo questions.",
  uploads: "The demo includes one document.",
  file_size: "Demo uploads are limited to 5 MB.",
  file_type: "The demo accepts PDF files only.",
};

/**
 * "Create a free account to continue": opens on any demo_limit_reached answer, or from
 * the demo banner. Converts the demo account in place (documents are kept).
 */
export function DemoUpgradeDialog({ open, reason, onClose }: { open: boolean; reason: string | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const { refresh } = useSession();
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await auth.convertDemo(email, password);
      await refresh();
      toast.show({ tone: "success", title: "Account created", message: "Your documents were kept. Limits are lifted." });
      onClose();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={ref}
      aria-labelledby="demo-upgrade-title"
      aria-describedby="demo-upgrade-description"
      data-testid="demo-limit-modal"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
      className="m-auto w-[min(30rem,calc(100vw-2rem))] rounded-2xl border border-border bg-surface p-0 text-fg shadow-pop backdrop:bg-black/60 backdrop:backdrop-blur-sm open:animate-slide-up"
    >
      <div className="bg-brand-gradient h-1.5 rounded-t-2xl" aria-hidden="true" />
      <div className="p-6 sm:p-7">
        <h2 id="demo-upgrade-title" className="text-xl font-semibold tracking-tight">
          Create a free account to continue
        </h2>
        <p id="demo-upgrade-description" className="mt-2 text-sm text-muted">
          {reason ? `${LIMIT_TEXT[reason] ?? "You've reached a demo limit."} ` : ""}
          A free account keeps the document you uploaded, removes the demo limits and does
          not expire.
        </p>
        <form className="mt-5 space-y-4" onSubmit={onSubmit}>
          <Field id="upgrade-email" label="Email">
            <input id="upgrade-email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={inputClass} />
          </Field>
          <Field id="upgrade-password" label="Password" hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}>
            <input
              id="upgrade-password"
              type="password"
              autoComplete="new-password"
              required
              minLength={PASSWORD_MIN_LENGTH}
              maxLength={128}
              aria-describedby="upgrade-password-hint"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputClass}
            />
          </Field>
          {error ? <ErrorAlert error={error} /> : null}
          <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
            <Button type="button" variant="ghost" onClick={onClose} disabled={busy}>
              Not now
            </Button>
            <ButtonLink href="/login" variant="secondary" onClick={onClose}>
              I have an account
            </ButtonLink>
            <Button type="submit" disabled={busy} data-testid="demo-convert-submit">
              {busy ? "Creating…" : "Create free account"}
            </Button>
          </div>
        </form>
      </div>
    </dialog>
  );
}

function hoursLeft(expiresAt: string | null): string | null {
  if (!expiresAt) return null;
  const ms = new Date(expiresAt).getTime() - Date.now();
  if (!Number.isFinite(ms) || ms <= 0) return null;
  const hours = Math.floor(ms / 3_600_000);
  return hours >= 1 ? `${hours} h` : `${Math.max(1, Math.round(ms / 60_000))} min`;
}

/** Banner + modal for demo sessions; renders nothing for regular accounts. */
export function DemoBanner() {
  const { user } = useSession();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<string | null>(null);
  const openFor = useCallback((limit: string | null) => {
    setReason(limit);
    setOpen(true);
  }, []);

  useEffect(() => onDemoLimit((detail) => openFor(detail.limit ?? "questions")), [openFor]);

  const demo = user?.demo;
  if (!user?.is_demo || !demo) return null;
  const left = hoursLeft(demo.expires_at);
  return (
    <>
      <div
        role="status"
        data-testid="demo-banner"
        className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-brand-200 bg-brand-50 px-4 py-2.5 text-sm text-brand-900 sm:px-6"
      >
        <p>
          <strong className="font-semibold">Demo:</strong>{" "}
          <span data-testid="demo-questions-left">
            {demo.questions_remaining} of {demo.questions_limit} questions left
          </span>
          <span className="hidden sm:inline">
            {" "}· {Math.max(0, demo.uploads_limit - demo.uploads_used)} of {demo.uploads_limit} upload
            {demo.uploads_limit === 1 ? "" : "s"} left{left ? ` · deleted in ${left}` : ""}
          </span>
        </p>
        <Button size="sm" onClick={() => openFor(null)}>
          Create free account
        </Button>
      </div>
      <DemoUpgradeDialog open={open} reason={reason} onClose={() => setOpen(false)} />
    </>
  );
}
