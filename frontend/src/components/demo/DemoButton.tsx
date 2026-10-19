"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Button, Spinner } from "@/components/ui";
import { auth } from "@/lib/client/api";
import { friendlyError } from "@/lib/errors";

/** Starts an ephemeral demo session (POST /api/auth/demo) and opens the upload page. */
export function DemoButton({
  size = "md",
  variant = "secondary",
  className = "",
  label = "Try the demo",
}: {
  size?: "sm" | "md" | "lg";
  variant?: "primary" | "secondary";
  className?: string;
  label?: string;
}) {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  async function start() {
    setBusy(true);
    try {
      await auth.demo();
      router.replace("/upload?demo=1");
      router.refresh();
    } catch (error) {
      const { title, message } = friendlyError(error);
      toast.show({ tone: "error", title: title === "Demo limit reached" ? "Demo unavailable" : title, message });
      setBusy(false);
    }
  }

  return (
    <Button
      type="button"
      size={size}
      variant={variant}
      className={className}
      onClick={() => void start()}
      disabled={busy}
      data-testid="try-demo"
    >
      {busy ? <Spinner /> : (
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z" strokeLinejoin="round" />
        </svg>
      )}
      {busy ? "Starting demo…" : label}
    </Button>
  );
}
