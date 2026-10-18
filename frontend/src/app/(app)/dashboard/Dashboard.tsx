"use client";

import Link from "next/link";

import { ErrorAlert } from "@/components/ErrorAlert";
import { useSession } from "@/components/SessionProvider";
import { StatusBadge } from "@/components/StatusBadge";
import { ButtonLink, Card, EmptyState, LoadingRows, PageHeader, Skeleton } from "@/components/ui";
import { useApiResource } from "@/lib/client/hooks";
import { fileTypeLabel, formatBytes, formatDate } from "@/lib/format";
import type { DocumentItem, Page } from "@/lib/types";

const COUNTERS = [
  { key: "total", label: "Total documents" },
  { key: "processing", label: "Processing" },
  { key: "completed", label: "Completed" },
  { key: "failed", label: "Failed" },
] as const;

const SHORTCUTS = [
  { href: "/upload", title: "Upload documents", body: "Add PDF, DOCX or TXT files." },
  { href: "/search", title: "Search", body: "Find passages by meaning or keyword." },
  { href: "/ask", title: "Ask AI", body: "Get an answer with citations." },
];

export function Dashboard() {
  const { user } = useSession();
  const { data, error, loading, reload } = useApiResource<Page<DocumentItem>>(
    "documents?page=1&page_size=100",
  );

  const items = data?.items ?? [];
  const counts = {
    total: data?.total ?? 0,
    processing: items.filter((d) => ["uploaded", "queued", "processing"].includes(d.status)).length,
    completed: items.filter((d) => d.status === "completed").length,
    failed: items.filter((d) => d.status === "failed").length,
  };
  const partial = data !== null && data.total > items.length;

  return (
    <>
      <PageHeader
        title="Dashboard"
        description={user ? `Signed in as ${user.email}` : "Overview of your documents"}
        actions={<ButtonLink href="/upload">Upload documents</ButtonLink>}
      />

      {error ? (
        <ErrorAlert error={error} onRetry={reload} />
      ) : (
        <section aria-label="Document counts" className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {COUNTERS.map((counter) => (
            <Card key={counter.key} className="p-4">
              <p className="text-sm text-slate-600">{counter.label}</p>
              {loading && !data ? (
                <Skeleton className="mt-2 h-8 w-12" />
              ) : (
                <p className="mt-1 text-3xl font-semibold" data-testid={`count-${counter.key}`}>
                  {counts[counter.key]}
                </p>
              )}
            </Card>
          ))}
        </section>
      )}
      {partial ? (
        <p className="mt-2 text-xs text-slate-500">
          Status counts cover your {items.length} most recent documents.
        </p>
      ) : null}

      <div className="mt-8 grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
            <h2 className="font-semibold">Recent documents</h2>
            <Link href="/documents" className="text-sm font-medium text-brand-700 hover:underline">
              View all
            </Link>
          </div>
          {loading && !data ? (
            <LoadingRows rows={4} label="Loading documents" />
          ) : items.length === 0 && !error ? (
            <EmptyState
              title="No documents yet"
              description="Upload a PDF, DOCX or TXT file to search it and ask questions about it."
              action={<ButtonLink href="/upload">Upload your first document</ButtonLink>}
            />
          ) : (
            <ul className="divide-y divide-slate-100">
              {items.slice(0, 5).map((doc) => (
                <li key={doc.id} className="flex items-center justify-between gap-3 px-4 py-3">
                  <div className="min-w-0">
                    <Link href={`/documents/${doc.id}`} className="block truncate text-sm font-medium text-slate-900 hover:text-brand-700">
                      {doc.original_filename}
                    </Link>
                    <p className="text-xs text-slate-500">
                      {fileTypeLabel(doc.content_type, doc.original_filename)} · {formatBytes(doc.file_size)} · {formatDate(doc.created_at)}
                    </p>
                  </div>
                  <StatusBadge status={doc.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="space-y-4">
          {SHORTCUTS.map((shortcut) => (
            <Link
              key={shortcut.href}
              href={shortcut.href}
              className="block rounded-xl border border-slate-200 bg-white p-4 shadow-sm hover:border-brand-300 hover:shadow"
            >
              <p className="font-semibold text-slate-900">{shortcut.title}</p>
              <p className="mt-1 text-sm text-slate-600">{shortcut.body}</p>
            </Link>
          ))}
        </div>
      </div>
    </>
  );
}
