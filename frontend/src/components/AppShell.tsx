"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { ErrorAlert } from "./ErrorAlert";
import { Logo } from "./Logo";
import { useSession } from "./SessionProvider";
import { Skeleton } from "./ui";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/upload", label: "Upload" },
  { href: "/documents", label: "Documents" },
  { href: "/search", label: "Search" },
  { href: "/ask", label: "Ask AI" },
  { href: "/settings", label: "Settings" },
];

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <ul className="space-y-1">
      {NAV.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <li key={item.href}>
            <Link
              href={item.href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={`block rounded-lg px-3 py-2 text-sm font-medium ${
                active ? "bg-brand-50 text-brand-700" : "text-slate-700 hover:bg-slate-100"
              }`}
            >
              {item.label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading, error, logout } = useSession();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="min-h-screen lg:flex">
      <aside className="hidden w-64 shrink-0 border-r border-slate-200 bg-white lg:flex lg:flex-col">
        <Link href="/dashboard" className="flex items-center gap-2 px-5 py-5">
          <Logo />
          <span className="text-sm font-semibold leading-tight text-slate-900">
            Document Intelligence
          </span>
        </Link>
        <nav aria-label="Main" className="flex-1 px-3">
          <NavLinks />
        </nav>
        <div className="border-t border-slate-200 p-4 text-xs text-slate-500">
          <Link href="/architecture" className="hover:text-slate-800">
            How it works
          </Link>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur sm:px-6">
          <div className="flex items-center gap-2 lg:hidden">
            <button
              type="button"
              className="rounded-lg p-2 text-slate-700 hover:bg-slate-100"
              aria-expanded={menuOpen}
              aria-controls="mobile-nav"
              onClick={() => setMenuOpen((open) => !open)}
            >
              <span className="sr-only">{menuOpen ? "Close menu" : "Open menu"}</span>
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                {menuOpen ? <path d="M6 6l12 12M18 6 6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
              </svg>
            </button>
            <Link href="/dashboard" className="flex items-center gap-2">
              <Logo className="h-6 w-6" />
              <span className="text-sm font-semibold">Document Intelligence</span>
            </Link>
          </div>
          <div className="hidden lg:block" />
          <div className="flex items-center gap-3">
            {loading ? (
              <Skeleton className="h-5 w-40" />
            ) : user ? (
              <span className="hidden max-w-[16rem] truncate text-sm text-slate-600 sm:inline" data-testid="user-email">
                {user.email}
              </span>
            ) : null}
            <button
              type="button"
              onClick={() => void logout()}
              className="rounded-lg px-3 py-1.5 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50"
            >
              Sign out
            </button>
          </div>
        </header>
        {menuOpen ? (
          <nav id="mobile-nav" aria-label="Main" className="border-b border-slate-200 bg-white px-3 py-3 lg:hidden">
            <NavLinks onNavigate={() => setMenuOpen(false)} />
          </nav>
        ) : null}
        <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {error ? <ErrorAlert error={error} onRetry={() => window.location.reload()} /> : children}
        </main>
      </div>
    </div>
  );
}
