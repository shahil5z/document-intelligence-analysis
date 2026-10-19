import type { ReactNode } from "react";

/** Clearly marked spot the site owner must fill in before going live. */
export function Placeholder({ children }: { children: ReactNode }) {
  return (
    <mark className="rounded bg-amber-100 px-1 py-0.5 font-medium text-amber-900 ring-1 ring-inset ring-amber-300 dark:bg-amber-50 dark:text-amber-900">
      [{children}]
    </mark>
  );
}

export function LegalPage({ title, updated, children }: { title: string; updated: string; children: ReactNode }) {
  return (
    <article className="mx-auto max-w-3xl px-4 py-12 sm:px-6 sm:py-16">
      <h1 className="text-3xl font-semibold tracking-tight text-fg">{title}</h1>
      <p className="mt-2 text-sm text-subtle">Last updated: {updated}</p>
      <div
        role="note"
        className="mt-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"
      >
        Template: the highlighted placeholders must be replaced with the operator&apos;s real
        details before this site is offered publicly. This page is not legal advice.
      </div>
      <div className="mt-8 space-y-6 text-[15px] leading-7 text-muted [&_h2]:mt-10 [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:text-fg [&_strong]:text-fg [&_ul]:list-disc [&_ul]:pl-5">
        {children}
      </div>
    </article>
  );
}
