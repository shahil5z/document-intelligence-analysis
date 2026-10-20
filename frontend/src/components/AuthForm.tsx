"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { auth } from "@/lib/client/api";
import { DemoButton } from "./demo/DemoButton";
import { ErrorAlert } from "./ErrorAlert";
import { LogoMark } from "./Logo";
import { Button, Card, Field, inputClass } from "./ui";

const PASSWORD_MIN_LENGTH = 12;

const NOTICES: Record<string, string> = {
  expired: "Your session has expired. Please sign in again.",
  "signed-out": "You have been signed out.",
};

/** Only same-site relative paths are accepted as a post-login destination. */
function safeNext(value: string | null): string {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/dashboard";
}

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const notice = mode === "login" ? NOTICES[params.get("reason") ?? ""] : undefined;
  const isRegister = mode === "register";

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (isRegister) await auth.register(email, password);
      else await auth.login(email, password);
      router.replace(safeNext(params.get("next")));
      router.refresh();
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-md flex-col px-4 py-12 sm:py-16">
      <div className="mb-6 flex justify-center">
        <LogoMark height={44} decorative={false} />
      </div>
      <Card className="p-6 shadow-pop sm:p-8">
        <h1 className="text-2xl font-semibold tracking-tight text-fg">
          {isRegister ? "Create your account" : "Sign in"}
        </h1>
        <p className="mt-1 text-sm text-muted">
          {isRegister
            ? "Keep your notes and papers in one private place."
            : "Welcome back."}
        </p>
        {notice ? (
          <p role="status" className="mt-4 rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-900">
            {notice}
          </p>
        ) : null}
        <form className="mt-6 space-y-4" onSubmit={onSubmit} noValidate={false}>
          <Field id="email" label="Email">
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field
            id="password"
            label="Password"
            hint={isRegister ? `At least ${PASSWORD_MIN_LENGTH} characters.` : undefined}
          >
            <input
              id="password"
              name="password"
              type="password"
              autoComplete={isRegister ? "new-password" : "current-password"}
              required
              minLength={isRegister ? PASSWORD_MIN_LENGTH : 1}
              maxLength={128}
              aria-describedby={isRegister ? "password-hint" : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputClass}
            />
          </Field>
          {error ? <ErrorAlert error={error} /> : null}
          <Button type="submit" size="lg" className="w-full" disabled={busy}>
            {busy ? "Please wait…" : isRegister ? "Create account" : "Sign in"}
          </Button>
        </form>
        <div className="my-6 flex items-center gap-3 text-xs text-subtle" aria-hidden="true">
          <span className="h-px flex-1 bg-border" />
          or
          <span className="h-px flex-1 bg-border" />
        </div>
        <DemoButton className="w-full" size="lg" label="Try the demo first" />
        <p className="mt-2 text-center text-xs text-subtle">
          1 PDF, 3 questions, deleted after 24 hours.
        </p>
        <p className="mt-6 text-center text-sm text-muted">
          {isRegister ? "Already have an account? " : "New here? "}
          <Link
            href={isRegister ? "/login" : "/register"}
            className="font-medium text-link hover:underline"
          >
            {isRegister ? "Sign in" : "Create an account"}
          </Link>
        </p>
      </Card>
    </div>
  );
}
