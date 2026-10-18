"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorAlert } from "@/components/ErrorAlert";
import { isActiveStatus, StatusBadge } from "@/components/StatusBadge";
import { Button, ButtonLink, Card, LoadingRows, PageHeader } from "@/components/ui";
import { api } from "@/lib/client/api";
import { useApiResource, useInterval } from "@/lib/client/hooks";
import { ApiError, processingFailureMessage } from "@/lib/errors";
import { fileTypeLabel, formatBytes, formatDate } from "@/lib/format";
import type { DocumentItem, DocumentStatusResponse } from "@/lib/types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function DocumentDetail() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = params.id;
  const valid = UUID.test(id);
  const doc = useApiResource<DocumentItem>(valid ? `documents/${id}` : null);
  const status = useApiResource<DocumentStatusResponse>(valid ? `documents/${id}/status` : null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const [confirming, setConfirming] = useState(false);

  const current = status.data?.status ?? doc.data?.status;
  useInterval(
    () => {
      status.reload();
      doc.reload();
    },
    2500,
    current !== undefined && isActiveStatus(current),
  );

  if (!valid) return <ErrorAlert error={new ApiError(404, "not_found", "Not found")} />;
  const loadError = doc.error ?? status.error;
  if (loadError) {
    return (
      <>
        <PageHeader title="Document" />
        <ErrorAlert error={loadError} />
        <p className="mt-4 text-sm">
          <Link href="/documents" className="font-medium text-brand-700 hover:underline">
            Back to documents
          </Link>
        </p>
      </>
    );
  }
  if (!doc.data || !status.data) return <LoadingRows rows={6} label="Loading document" />;

  const job = status.data.job;

  async function reprocess() {
    setBusy(true);
    setActionError(null);
    try {
      await api.post(`documents/${id}/reprocess`);
      status.reload();
      doc.reload();
    } catch (err) {
      setActionError(err);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await api.delete(`documents/${id}`);
      router.replace("/documents");
    } catch (err) {
      setActionError(err);
      setConfirming(false);
      setBusy(false);
    }
  }

  const completed = status.data.status === "completed";
  return (
    <>
      <PageHeader
        title={doc.data.original_filename}
        description={<StatusBadge status={status.data.status} />}
        actions={
          <>
            {completed ? (
              <>
                <ButtonLink href={`/search?document=${id}`} variant="secondary">Search</ButtonLink>
                <ButtonLink href={`/ask?document=${id}`} variant="secondary">Ask AI</ButtonLink>
              </>
            ) : null}
            <Button
              variant="secondary"
              onClick={() => void reprocess()}
              disabled={busy || isActiveStatus(status.data.status)}
            >
              Reprocess
            </Button>
            <Button variant="danger" onClick={() => setConfirming(true)} disabled={busy}>
              Delete
            </Button>
          </>
        }
      />
      {actionError ? (
        <div className="mb-4">
          <ErrorAlert error={actionError} />
        </div>
      ) : null}
      {status.data.status === "failed" ? (
        <div role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900">
          {processingFailureMessage(job?.error_message)}
        </div>
      ) : null}
      {isActiveStatus(status.data.status) ? (
        <p role="status" className="mb-4 rounded-lg bg-blue-50 px-3 py-2 text-sm text-blue-900">
          Processing{job?.stage ? ` (${job.stage})` : ""}… this page updates automatically.
        </p>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <h2 className="font-semibold">Details</h2>
          <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-4 text-sm sm:grid-cols-2">
            <Item term="Type" value={fileTypeLabel(doc.data.content_type, doc.data.original_filename)} />
            <Item term="Size" value={formatBytes(doc.data.file_size)} />
            <Item term="Uploaded" value={formatDate(doc.data.created_at)} />
            <Item term="Last updated" value={formatDate(doc.data.updated_at)} />
            <Item term="Indexed chunks" value={String(status.data.chunk_count)} testId="chunk-count" />
            <Item term="Processing attempts" value={job ? String(job.attempts) : "-"} />
          </dl>
          <p className="mt-6 text-xs text-slate-500">
            A text preview is not available; use Search or Ask AI to read passages from this document.
          </p>
        </Card>

        <Card className="p-5">
          <details>
            <summary className="cursor-pointer text-sm font-semibold">Technical details</summary>
            <dl className="mt-3 space-y-3 text-xs">
              <Item term="Document ID" value={doc.data.id} mono />
              <Item term="Content type" value={doc.data.content_type} mono />
              <Item term="SHA-256" value={doc.data.checksum_sha256} mono />
              {job ? (
                <>
                  <Item term="Job ID" value={job.id} mono />
                  <Item term="Job status" value={job.status} mono />
                  <Item term="Stage" value={job.stage ?? "-"} mono />
                  <Item term="Started" value={formatDate(job.started_at)} />
                  <Item term="Finished" value={formatDate(job.completed_at)} />
                </>
              ) : null}
            </dl>
          </details>
        </Card>
      </div>

      <ConfirmDialog
        open={confirming}
        title="Delete document?"
        description={`"${doc.data.original_filename}" and all of its indexed passages will be permanently deleted.`}
        confirmLabel="Delete"
        busy={busy}
        onConfirm={() => void remove()}
        onCancel={() => setConfirming(false)}
      />
    </>
  );
}

function Item({ term, value, mono, testId }: { term: string; value: string; mono?: boolean; testId?: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-slate-500">{term}</dt>
      <dd data-testid={testId} className={`mt-0.5 break-all text-slate-900 ${mono ? "font-mono" : ""}`}>
        {value}
      </dd>
    </div>
  );
}
