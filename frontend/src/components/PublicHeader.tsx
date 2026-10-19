import Link from "next/link";

import { Wordmark } from "./Logo";
import { ThemeToggle } from "./theme/ThemeToggle";
import { ButtonLink } from "./ui";
import { GITHUB_URL, PRODUCT_NAME } from "@/lib/brand";

export function PublicHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6">
        <Link href="/" className="rounded-md" aria-label={`${PRODUCT_NAME} home`}>
          <Wordmark />
        </Link>
        <nav aria-label="Site" className="flex items-center gap-1 text-sm sm:gap-2">
          <Link href="/#how-it-works" className="hidden rounded-lg px-3 py-2 text-muted hover:bg-surface-2 hover:text-fg md:inline-block">
            How it works
          </Link>
          <Link href="/architecture" className="hidden rounded-lg px-3 py-2 text-muted hover:bg-surface-2 hover:text-fg md:inline-block">
            Architecture
          </Link>
          <ThemeToggle />
          <Link href="/login" className="whitespace-nowrap rounded-lg px-2.5 py-2 font-medium text-fg hover:bg-surface-2 sm:px-3">
            Sign in
          </Link>
          <span className="hidden sm:block">
            <ButtonLink href="/register" size="sm">
              Create account
            </ButtonLink>
          </span>
        </nav>
      </div>
    </header>
  );
}

export function PublicFooter() {
  const year = 2026;
  return (
    <footer className="border-t border-border bg-surface">
      <div className="mx-auto grid max-w-6xl gap-8 px-4 py-10 text-sm sm:px-6 md:grid-cols-[1.5fr_1fr_1fr]">
        <div>
          <Wordmark compact />
          <p className="mt-3 max-w-sm text-muted">
            A portfolio project. AI answers can be wrong: always check the cited passages.
          </p>
          <p className="mt-2 max-w-sm text-xs text-subtle">
            Privacy: no analytics, no tracking cookies. One strictly necessary session cookie
            keeps you signed in.
          </p>
        </div>
        <nav aria-label="Product" className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-subtle">Product</p>
          <Link href="/#features" className="block text-muted hover:text-fg">Features</Link>
          <Link href="/architecture" className="block text-muted hover:text-fg">Architecture</Link>
          <a href={GITHUB_URL} className="block text-muted hover:text-fg" rel="noopener noreferrer">
            GitHub <span className="text-xs text-subtle">(link placeholder)</span>
          </a>
        </nav>
        <nav aria-label="Legal" className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-subtle">Legal</p>
          <Link href="/impressum" className="block text-muted hover:text-fg">Impressum</Link>
          <Link href="/privacy" className="block text-muted hover:text-fg">Privacy policy</Link>
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
