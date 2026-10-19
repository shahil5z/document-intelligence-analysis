"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { DemoBanner } from "./demo/DemoUpgrade";
import { ErrorAlert } from "./ErrorAlert";
import { Wordmark } from "./Logo";
import { useSession } from "./SessionProvider";
import { ThemeToggle } from "./theme/ThemeToggle";
import { Badge, Skeleton } from "./ui";

const ICONS = {
  dashboard: "M4 13h6V4H4v9Zm0 7h6v-5H4v5Zm10 0h6v-9h-6v9Zm0-16v5h6V4h-6Z",
  upload: "M12 16V4m0 0-4 4m4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3",
  documents: "M7 3h7l5 5v13H7V3Zm7 0v5h5M10 13h6M10 17h4",
  search: "m21 21-4.3-4.3M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z",
  ask: "M8 10h8M8 14h5M5 4h14a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1h-6l-4 3v-3H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7.6 7.6 0 0 0-2-1.2L14.5 3h-5l-.4 2.6a7.6 7.6 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7.6 7.6 0 0 0 2 1.2l.4 2.6h5l.4-2.6a7.6 7.6 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2Z",
} as const;

const NAV: Array<{ href: string; label: string; icon: keyof typeof ICONS; mobile?: boolean }> = [
  { href: "/dashboard", label: "Dashboard", icon: "dashboard", mobile: true },
  { href: "/upload", label: "Upload", icon: "upload", mobile: true },
  { href: "/documents", label: "Documents", icon: "documents", mobile: true },
  { href: "/search", label: "Search", icon: "search", mobile: true },
  { href: "/ask", label: "Ask AI", icon: "ask", mobile: true },
  { href: "/settings", label: "Settings", icon: "settings" },
];

function NavIcon({ name, className = "h-[18px] w-[18px]" }: { name: keyof typeof ICONS; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d={ICONS[name]} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <ul className="space-y-0.5">
      {NAV.map((item) => {
        const active = isActive(pathname, item.href);
        return (
          <li key={item.href}>
            <Link
              href={item.href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={`group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                active ? "bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-200" : "text-muted hover:bg-surface-2 hover:text-fg"
              }`}
            >
              <NavIcon name={item.icon} />
              {item.label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function BottomNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md lg:hidden">
      <ul className="mx-auto grid max-w-lg grid-cols-5">
        {NAV.filter((item) => item.mobile).map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`flex flex-col items-center gap-1 py-2 text-[11px] font-medium ${active ? "text-brand-700" : "text-subtle hover:text-fg"}`}
              >
                <NavIcon name={item.icon} className="h-5 w-5" />
                {item.label.replace(" AI", "")}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function UserBlock() {
  const { user, loading, logout } = useSession();
  if (loading) return <Skeleton className="h-9 w-full" />;
  if (!user) return null;
  const initial = user.is_demo ? "D" : user.email.slice(0, 1).toUpperCase();
  return (
    <div className="flex items-center gap-3">
      <span aria-hidden="true" className="bg-brand-gradient flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white">
        {initial}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-fg" data-testid="user-email">
          {user.is_demo ? "Demo session" : user.email}
        </p>
        <button type="button" onClick={() => void logout()} className="text-xs text-subtle hover:text-fg">
          Sign out
        </button>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, error, logout } = useSession();
  const [menuOpen, setMenuOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  return (
    <div className="min-h-screen lg:flex">
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-border bg-surface lg:flex">
        <Link href="/dashboard" className="flex h-16 items-center px-5" aria-label="Dashboard">
          <Wordmark />
        </Link>
        <nav aria-label="Main" className="flex-1 overflow-y-auto px-3 py-2">
          <p className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-subtle">Workspace</p>
          <SidebarNav />
        </nav>
        <div className="space-y-3 border-t border-border p-4">
          <UserBlock />
          <div className="flex items-center justify-between text-xs text-subtle">
            <Link href="/architecture" className="hover:text-fg">How it works</Link>
            <ThemeToggle />
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between gap-3 border-b border-border bg-background/85 px-4 backdrop-blur-md lg:hidden">
          <div className="flex items-center gap-1">
            <button
              type="button"
              className="rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-fg"
              aria-expanded={menuOpen}
              aria-controls="mobile-nav"
              onClick={() => setMenuOpen((open) => !open)}
            >
              <span className="sr-only">{menuOpen ? "Close menu" : "Open menu"}</span>
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                {menuOpen ? <path d="M6 6l12 12M18 6 6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
              </svg>
            </button>
            <Link href="/dashboard" aria-label="Dashboard">
              <Wordmark compact />
            </Link>
          </div>
          <div className="flex items-center gap-2">
            {user?.is_demo ? <Badge tone="brand">Demo</Badge> : null}
            <ThemeToggle />
          </div>
        </header>
        {menuOpen ? (
          <div id="mobile-nav" className="animate-fade-in border-b border-border bg-surface px-3 py-3 lg:hidden">
            <nav aria-label="Menu">
              <SidebarNav onNavigate={() => setMenuOpen(false)} />
            </nav>
            <div className="mt-3 border-t border-border px-3 pt-3">
              {user ? (
                <p className="truncate text-sm text-muted" data-testid="user-email-mobile">
                  {user.is_demo ? "Demo session" : user.email}
                </p>
              ) : null}
              <button type="button" onClick={() => void logout()} className="mt-2 text-sm font-medium text-fg">
                Sign out
              </button>
            </div>
          </div>
        ) : null}
        <DemoBanner />
        <main id="main" key={pathname} className="mx-auto w-full max-w-6xl flex-1 animate-fade-in px-4 pb-24 pt-6 sm:px-6 lg:px-8 lg:pb-10 lg:pt-8">
          {error ? <ErrorAlert error={error} onRetry={() => window.location.reload()} /> : children}
        </main>
        <BottomNav />
      </div>
    </div>
  );
}
