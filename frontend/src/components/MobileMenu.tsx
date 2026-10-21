"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { DemoButton } from "./demo/DemoButton";

const itemClass = "block rounded-lg px-3 py-3 text-base text-fg hover:bg-surface-2";

export function MobileMenu({ signedIn, githubUrl }: { signedIn: boolean; githubUrl: string }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const buttonRef = useRef<HTMLButtonElement>(null);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const close = () => setOpen(false);

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        aria-expanded={open}
        aria-controls="mobile-menu"
        aria-label={open ? "Close menu" : "Open menu"}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-11 w-11 items-center justify-center rounded-lg text-fg hover:bg-surface-2"
      >
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          {open ? <path d="M6 6l12 12M18 6 6 18" strokeLinecap="round" /> : <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round" />}
        </svg>
      </button>
      {open ? (
        <nav
          id="mobile-menu"
          aria-label="Site"
          className="absolute inset-x-0 top-16 border-b border-border bg-background px-4 pb-5 pt-2 shadow-pop"
        >
          <Link href="/#how-it-works" className={itemClass} onClick={close}>How it works</Link>
          <Link href="/#architecture" className={itemClass} onClick={close}>Architecture</Link>
          <a href={githubUrl} className={itemClass} rel="noopener noreferrer">GitHub</a>
          <div className="mt-3 grid gap-2 border-t border-border pt-4">
            {signedIn ? (
              <Link href="/dashboard" className={`${itemClass} text-center font-medium ring-1 ring-inset ring-border-strong`} onClick={close}>
                Dashboard
              </Link>
            ) : (
              <>
                <DemoButton size="lg" variant="primary" label="Try Demo" className="w-full" />
                <Link href="/login" className={`${itemClass} text-center font-medium ring-1 ring-inset ring-border-strong`} onClick={close}>
                  Sign in
                </Link>
              </>
            )}
          </div>
        </nav>
      ) : null}
    </>
  );
}
