"use client";

import Link from "next/link";
import { useState } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorAlert } from "@/components/ErrorAlert";
import { isActiveStatus, StatusBadge } from "@/components/StatusBadge";
import { Button, ButtonLink, Card, EmptyState, LoadingRows, PageHeader } from "@/components/ui";
import { api } from "@/lib/client/api";
import { useApiResource, useInterval } from "@/lib/client/hooks";
import { fileTypeLabel, formatBytes, formatDate } from "@/lib/format";
import type { DocumentItem, Page } from "@/lib/types";

const PAGE_SIZE = 20;

export function DocumentsList() {
  const [page, setPage] = useState(1);
  const { data, error, loading, reload } = useApiResource<Page<DocumentItem>>(
    `documents?page=${page}&page_size=${PAGE_SIZE}`,
  );
  const [pendingDelete, setPendingDelete] = useState<DocumentItem | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const items = data?.items ?? [];
  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  useInterval(reload, 4000, items.some((d) => isActiveStatus(d.status)));

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    setActionError(null);
    try {
      await api.delete(`documents/${pendingDelete.id}`);
      setNotice(`Deleted "${pendingDelete.original_filename}".`);
      setPendingDelete(null);
      reload();
    } catch (err) {
      setActionError(err);
      setPendingDelete(null);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Documents"
        description={data ? `${data.total} document${data.total === 1 ? "" : "s"}` : "Your uploaded files"}
        actions={<ButtonLink href="/upload">Upload</ButtonLink>}
      />
      {notice ? (
        <p role="status" className="mb-4 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
          {notice}
        </p>
      ) : null}
      {actionError ? (
        <div className="mb-4">
          <ErrorAlert error={actionError} />
        </div>
      ) : null}

      <Card>
        {error ? (
          <div className="p-4">
            <ErrorAlert error={error} onRetry={reload} />
          </div>
        ) : loading && !data ? (
          <LoadingRows rows={5} label="Loading documents" />
        ) : items.length === 0 ? (
          <EmptyState
            title="No documents"
            description="Your uploaded files will show up here."
            action={<ButtonLink href="/upload">Upload a document</ButtonLink>}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <caption className="sr-only">Your documents</caption>
              <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
                <tr>
                  <th scope="col" className="px-4 py-3">Name</th>
                  <th scope="col" className="hidden px-4 py-3 sm:table-cell">Type</th>
                  <th scope="col" className="hidden px-4 py-3 md:table-cell">Size</th>
                  <th scope="col" className="px-4 py-3">Status</th>
                  <th scope="col" className="hidden px-4 py-3 lg:table-cell">Uploaded</th>
                  <th scope="col" className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-surface">
                {items.map((doc) => (
                  <tr key={doc.id} data-testid="document-row">
                    <td className="max-w-[14rem] px-4 py-3">
                      <Link href={`/documents/${doc.id}`} className="block truncate font-medium text-slate-900 hover:text-brand-700">
                        {doc.original_filename}
                      </Link>
                    </td>
                    <td className="hidden px-4 py-3 text-slate-600 sm:table-cell">
                      {fileTypeLabel(doc.content_type, doc.original_filename)}
                    </td>
                    <td className="hidden px-4 py-3 text-slate-600 md:table-cell">{formatBytes(doc.file_size)}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={doc.status} />
                    </td>
                    <td className="hidden px-4 py-3 text-slate-600 lg:table-cell">{formatDate(doc.created_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-1 whitespace-nowrap">
                        <Link className="rounded-md px-2 py-1 text-brand-700 hover:bg-brand-50" href={`/documents/${doc.id}`}>
                          View<span className="sr-only"> {doc.original_filename}</span>
                        </Link>
                        <Link className="hidden rounded-md px-2 py-1 text-brand-700 hover:bg-brand-50 sm:inline" href={`/search?document=${doc.id}`}>
                          Search<span className="sr-only"> in {doc.original_filename}</span>
                        </Link>
                        <Link className="hidden rounded-md px-2 py-1 text-brand-700 hover:bg-brand-50 sm:inline" href={`/ask?document=${doc.id}`}>
                          Ask<span className="sr-only"> about {doc.original_filename}</span>
                        </Link>
                        <button
                          type="button"
                          className="rounded-md px-2 py-1 text-red-700 hover:bg-red-50"
                          onClick={() => {
                            setNotice(null);
                            setPendingDelete(doc);
                          }}
                        >
                          Delete<span className="sr-only"> {doc.original_filename}</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {data && totalPages > 1 ? (
        <nav aria-label="Pagination" className="mt-4 flex items-center justify-between text-sm">
          <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Previous
          </Button>
          <span className="text-slate-600">
            Page {page} of {totalPages}
          </span>
          <Button variant="secondary" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
            Next
          </Button>
        </nav>
      ) : null}

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete document?"
        description={
          pendingDelete
            ? `"${pendingDelete.original_filename}" and all of its indexed passages will be permanently deleted.`
            : ""
        }
        confirmLabel="Delete"
        busy={deleting}
        onConfirm={() => void confirmDelete()}
        onCancel={() => setPendingDelete(null)}
      />
    </>
  );
}
