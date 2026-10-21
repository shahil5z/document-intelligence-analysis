"use client";

import Link from "next/link";

import { ErrorAlert } from "@/components/ErrorAlert";
import { useSession } from "@/components/SessionProvider";
import { StatusBadge } from "@/components/StatusBadge";
import { ButtonLink, Card, EmptyState, LoadingRows, PageHeader, Skeleton } from "@/components/ui";
import { activityDetail, activityLabel, timeAgo, type AuditEntry } from "@/lib/activity";
import { useApiResource } from "@/lib/client/hooks";
import { fileTypeLabel, formatBytes, formatDate } from "@/lib/format";
import type { DocumentItem, Page } from "@/lib/types";

const COUNTERS = [
  { key: "total", label: "Total documents", tone: "text-fg" },
  { key: "processing", label: "Processing", tone: "text-blue-700" },
  { key: "completed", label: "Ready", tone: "text-emerald-700" },
  { key: "failed", label: "Failed", tone: "text-red-700" },
] as const;

const SHORTCUTS = [
  { href: "/upload", title: "Upload", body: "Add PDF, DOCX or TXT files.", icon: "M12 16V4m0 0-4 4m4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" },
  { href: "/search", title: "Search", body: "Hybrid search across your documents.", icon: "m21 21-4.3-4.3M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z" },
  { href: "/ask", title: "Ask AI", body: "Cited answers from your documents.", icon: "M8 10h8M8 14h5M5 4h14a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1h-6l-4 3v-3H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z" },
];

export function Dashboard() {
  const { user } = useSession();
  const { data, error, loading, reload } = useApiResource<Page<DocumentItem>>("documents?page=1&page_size=100");
  const activity = useApiResource<Page<AuditEntry>>("audit-logs/me?page=1&page_size=8");

  const items = data?.items ?? [];
  const counts = {
    total: data?.total ?? 0,
    processing: items.filter((d) => ["uploaded", "queued", "processing"].includes(d.status)).length,
    completed: items.filter((d) => d.status === "completed").length,
    failed: items.filter((d) => d.status === "failed").length,
  };
  const storage = items.reduce((sum, d) => sum + d.file_size, 0);
  const partial = data !== null && data.total > items.length;
  const description = user?.is_demo
    ? "Demo: upload one PDF and ask up to three questions."
    : user
      ? `Signed in as ${user.email}`
      : "Overview of your documents";

  return (
    <>
      <PageHeader
        title="Dashboard"
        description={description}
        actions={<ButtonLink href={counts.completed > 0 ? "/ask" : "/upload"}>{counts.completed > 0 ? "Ask a question" : "Upload documents"}</ButtonLink>}
      />

      {error ? (
        <ErrorAlert error={error} onRetry={reload} />
      ) : (
        <section aria-label="Document counts" className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
          {COUNTERS.map((counter) => (
            <Card key={counter.key} className="p-4">
              <p className="text-xs font-medium uppercase tracking-wider text-subtle">{counter.label}</p>
              {loading && !data ? (
                <Skeleton className="mt-2 h-8 w-12" />
              ) : (
                <p className={`mt-1 text-3xl font-semibold tabular-nums ${counter.tone}`} data-testid={`count-${counter.key}`}>
                  {counts[counter.key]}
                </p>
              )}
            </Card>
          ))}
        </section>
      )}
      <p className="mt-2 text-xs text-subtle">
        {data ? `${formatBytes(storage)} stored` : ""}
        {partial ? ` · counts cover your ${items.length} most recent documents` : ""}
      </p>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <h2 className="font-semibold text-fg">Recent documents</h2>
            <Link href="/documents" className="text-sm font-medium text-link hover:underline">
              View all
            </Link>
          </div>
          {loading && !data ? (
            <LoadingRows rows={4} label="Loading documents" />
          ) : items.length === 0 && !error ? (
            <EmptyState
              title="No documents yet"
              description="Upload a PDF, DOCX or TXT file to get started."
              action={<ButtonLink href="/upload">Upload your first document</ButtonLink>}
            />
          ) : (
            <ul className="divide-y divide-border">
              {items.slice(0, 5).map((doc) => (
                <li key={doc.id} className="flex items-center justify-between gap-3 px-4 py-3">
                  <div className="min-w-0">
                    <Link href={`/documents/${doc.id}`} className="block truncate text-sm font-medium text-fg hover:text-link">
                      {doc.original_filename}
                    </Link>
                    <p className="text-xs text-subtle">
                      {fileTypeLabel(doc.content_type, doc.original_filename)} · {formatBytes(doc.file_size)} · {formatDate(doc.created_at)}
                    </p>
                  </div>
                  <StatusBadge status={doc.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="space-y-6">
          <nav aria-label="Quick actions" className="grid gap-3">
            {SHORTCUTS.map((shortcut) => (
              <Link
                key={shortcut.href}
                href={shortcut.href}
                className="group flex items-start gap-3 rounded-xl border border-border bg-surface p-4 shadow-card transition-colors hover:border-brand-300"
              >
                <span aria-hidden="true" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-200">
                  <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="1.7">
                    <path d={shortcut.icon} strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </span>
                <span>
                  <span className="block font-semibold text-fg group-hover:text-link">{shortcut.title}</span>
                  <span className="mt-0.5 block text-sm text-muted">{shortcut.body}</span>
                </span>
              </Link>
            ))}
          </nav>

          <Card>
            <h2 className="border-b border-border px-4 py-3 font-semibold text-fg">Recent activity</h2>
            {activity.loading && !activity.data ? (
              <LoadingRows rows={3} label="Loading activity" />
            ) : activity.error ? (
              <div className="p-4">
                <ErrorAlert error={activity.error} onRetry={activity.reload} />
              </div>
            ) : (activity.data?.items.length ?? 0) === 0 ? (
              <p className="px-4 py-6 text-sm text-muted">No activity yet.</p>
            ) : (
              <ol className="space-y-3 px-4 py-3" data-testid="recent-activity">
                {activity.data!.items.map((entry) => (
                  <li key={entry.id} className="flex gap-3 text-sm">
                    <span aria-hidden="true" className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand-500" />
                    <span className="min-w-0">
                      <span className="block text-fg">{activityLabel(entry)}</span>
                      <span className="block truncate text-xs text-subtle">
                        {activityDetail(entry) ? `${activityDetail(entry)} · ` : ""}
                        <time dateTime={entry.created_at} title={formatDate(entry.created_at)}>
                          {timeAgo(entry.created_at)}
                        </time>
                      </span>
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
