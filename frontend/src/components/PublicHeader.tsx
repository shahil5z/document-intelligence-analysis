import Link from "next/link";

import { Logo } from "./Logo";

export function PublicHeader() {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2">
          <Logo />
          <span className="text-sm font-semibold text-slate-900">Document Intelligence Platform</span>
        </Link>
        <nav aria-label="Site" className="flex items-center gap-1 text-sm sm:gap-2">
          <Link href="/architecture" className="hidden rounded-lg px-3 py-2 text-slate-700 hover:bg-slate-100 sm:inline-block">
            Architecture
          </Link>
          <Link href="/login" className="rounded-lg px-3 py-2 font-medium text-slate-700 hover:bg-slate-100">
            Sign in
          </Link>
          <Link href="/register" className="rounded-lg bg-brand-600 px-3 py-2 font-medium text-white hover:bg-brand-700">
            Create account
          </Link>
        </nav>
      </div>
    </header>
  );
}

export function PublicFooter() {
  return (
    <footer className="border-t border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-6 text-xs text-slate-500 sm:flex-row sm:justify-between sm:px-6">
        <p>Document Intelligence Platform · portfolio project by Shahil Haque</p>
        <p>AI answers can be wrong. Always check the cited passages.</p>
      </div>
    </footer>
  );
}
