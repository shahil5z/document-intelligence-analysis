import { cookies } from "next/headers";
import Link from "next/link";
import { Suspense } from "react";

import { Wordmark } from "./Logo";
import { MobileMenu } from "./MobileMenu";
import { ThemeToggle } from "./theme/ThemeToggle";
import { ButtonLink } from "./ui";
import { DemoButton } from "./demo/DemoButton";
import { GITHUB_URL, PRODUCT_NAME } from "@/lib/brand";

const SESSION_COOKIE = "dip_session";

const linkClass = "rounded-lg px-3 py-2 text-muted hover:bg-surface-2 hover:text-fg";

async function isSignedIn(): Promise<boolean> {
  // Presence only: an expired cookie is detected by the app and sent to /login.
  return Boolean((await cookies()).get(SESSION_COOKIE)?.value);
}

function DesktopAuth({ signedIn }: { signedIn: boolean }) {
  return signedIn ? (
    <ButtonLink href="/dashboard" size="sm">Dashboard</ButtonLink>
  ) : (
    <>
      <Link href="/login" className={`${linkClass} font-medium text-fg`}>Sign in</Link>
      <DemoButton size="sm" variant="primary" label="Try Demo" />
    </>
  );
}

async function DesktopAuthDynamic() {
  return <DesktopAuth signedIn={await isSignedIn()} />;
}

async function MobileMenuDynamic() {
  return <MobileMenu signedIn={await isSignedIn()} githubUrl={GITHUB_URL} />;
}

export function PublicHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background/95">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6">
        <Link href="/" className="min-w-0 rounded-md" aria-label={`${PRODUCT_NAME} home`}>
          <Wordmark />
        </Link>
        <nav aria-label="Site" className="hidden items-center gap-1 text-sm lg:flex">
          <Link href="/#how-it-works" className={linkClass}>How it works</Link>
          <Link href="/#architecture" className={linkClass}>Architecture</Link>
          <a href={GITHUB_URL} className={linkClass} rel="noopener noreferrer">GitHub</a>
          <span className="mx-1 h-5 w-px bg-border" aria-hidden="true" />
          <ThemeToggle />
          <Suspense fallback={<DesktopAuth signedIn={false} />}>
            <DesktopAuthDynamic />
          </Suspense>
        </nav>
        <div className="flex items-center gap-1 lg:hidden">
          <ThemeToggle />
          <Suspense fallback={<MobileMenu signedIn={false} githubUrl={GITHUB_URL} />}>
            <MobileMenuDynamic />
          </Suspense>
        </div>
      </div>
    </header>
  );
}

export function PublicFooter() {
  const year = 2026;
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-10 text-sm sm:px-6 md:flex-row md:items-start md:justify-between">
        <div className="max-w-md">
          <Wordmark compact />
          <p className="mt-3 text-muted">
            AI answers can be wrong. Check the cited passages before relying on an answer.
          </p>
        </div>
        <nav aria-label="Footer" className="flex flex-wrap gap-x-6 gap-y-2">
          <Link href="/impressum" className="text-muted hover:text-fg">Impressum</Link>
          <Link href="/privacy" className="text-muted hover:text-fg">Privacy</Link>
          <a href={GITHUB_URL} className="text-muted hover:text-fg" rel="noopener noreferrer">GitHub</a>
        </nav>
      </div>
      <div className="border-t border-border">
        <p className="mx-auto max-w-6xl px-4 py-4 text-xs text-subtle sm:px-6">
          © {year} {PRODUCT_NAME}
        </p>
      </div>
    </footer>
  );
}
