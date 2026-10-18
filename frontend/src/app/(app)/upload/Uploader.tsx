"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";

import { ErrorAlert } from "@/components/ErrorAlert";
import { StatusBadge } from "@/components/StatusBadge";
import { Button, Card, LoadingRows, PageHeader } from "@/components/ui";
import { api, uploadDocument } from "@/lib/client/api";
import { useApiResource, useInterval } from "@/lib/client/hooks";
import { friendlyError, processingFailureMessage } from "@/lib/errors";
import { formatBytes } from "@/lib/format";
import type { DocumentStatus, DocumentStatusResponse, UploadPolicy } from "@/lib/types";

type Phase = "rejected" | "uploading" | "upload-failed" | DocumentStatus;

interface UploadItem {
  key: string;
  file: File;
  phase: Phase;
  progress: number;
  documentId?: string;
  error?: unknown;
  reason?: string;
  chunkCount?: number;
  failure?: string | null;
}

const POLL_MS = 2000;

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : "";
}

/** Same checks as the API's first pass, so obviously bad files never leave the browser. */
export function validateFile(file: File, policy: UploadPolicy): string | null {
  const ext = extensionOf(file.name);
  const allowed = policy.allowed_extensions.map((e) => e.toLowerCase().replace(/^\./, ""));
  if (!allowed.includes(ext)) {
    return `Unsupported file type${ext ? ` ".${ext}"` : ""}. Allowed: ${allowed.map((e) => e.toUpperCase()).join(", ")}.`;
  }
  if (file.size === 0) return "The file is empty.";
  if (file.size > policy.max_upload_size_bytes) {
    return `File is too large (${formatBytes(file.size)}). The limit is ${formatBytes(policy.max_upload_size_bytes)}.`;
  }
  return null;
}

export function Uploader() {
  const policy = useApiResource<UploadPolicy>("documents/upload-policy");
  const [items, setItems] = useState<UploadItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const counter = useRef(0);

  const update = useCallback((key: string, patch: Partial<UploadItem>) => {
    setItems((current) => current.map((item) => (item.key === key ? { ...item, ...patch } : item)));
  }, []);

  const start = useCallback(
    (key: string, file: File) => {
      update(key, { phase: "uploading", progress: 0, error: undefined });
      const handle = uploadDocument(file, (fraction) => update(key, { progress: fraction }));
      handle.promise
        .then((result) => update(key, { phase: result.status, documentId: result.id, progress: 1 }))
        .catch((error: unknown) => update(key, { phase: "upload-failed", error }));
    },
    [update],
  );

  const addFiles = useCallback(
    (files: FileList | File[]) => {
      if (!policy.data) return;
      const added: UploadItem[] = [];
      for (const file of Array.from(files)) {
        counter.current += 1;
        const reason = validateFile(file, policy.data);
        added.push({
          key: `${counter.current}-${file.name}`,
          file,
          phase: reason ? "rejected" : "uploading",
          progress: 0,
          reason: reason ?? undefined,
        });
      }
      setItems((current) => [...added, ...current]);
      for (const item of added) if (item.phase === "uploading") start(item.key, item.file);
    },
    [policy.data, start],
  );

  const pollable = items.filter(
    (item) => item.documentId && ["uploaded", "queued", "processing"].includes(item.phase),
  );

  const poll = useCallback(() => {
    for (const item of pollable) {
      api
        .get<DocumentStatusResponse>(`documents/${item.documentId}/status`)
        .then((status) =>
          update(item.key, {
            phase: status.status,
            chunkCount: status.chunk_count,
            failure: status.job?.error_message ?? null,
          }),
        )
        .catch(() => undefined);
    }
  }, [pollable, update]);

  useInterval(poll, POLL_MS, pollable.length > 0);

  useEffect(() => {
    if (pollable.length > 0) poll();
    // Poll once immediately whenever a new document starts processing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pollable.length]);

  async function reprocess(item: UploadItem) {
    if (!item.documentId) return;
    try {
      const result = await api.post<{ status: DocumentStatus }>(`documents/${item.documentId}/reprocess`);
      update(item.key, { phase: result.status, failure: null, error: undefined });
    } catch (error) {
      update(item.key, { error });
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.files.length > 0) addFiles(event.dataTransfer.files);
  }

  const accept = policy.data?.allowed_extensions.map((e) => `.${e.replace(/^\./, "")}`).join(",");

  return (
    <>
      <PageHeader
        title="Upload documents"
        description="Files are processed in the background: text extraction, chunking and embedding."
      />
      {policy.error ? <ErrorAlert error={policy.error} onRetry={policy.reload} /> : null}
      {policy.loading && !policy.data ? <LoadingRows rows={2} label="Loading upload settings" /> : null}
      {policy.data ? (
        <Card className="p-4 sm:p-6">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors ${
              dragging ? "border-brand-500 bg-brand-50" : "border-slate-300 bg-slate-50"
            }`}
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" className="h-10 w-10 text-brand-600" fill="none" stroke="currentColor" strokeWidth="1.6">
              <path d="M12 16V4m0 0-4 4m4-4 4 4" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" strokeLinecap="round" />
            </svg>
            <p className="mt-3 text-sm font-medium text-slate-900">Drag and drop files here</p>
            <p className="mt-1 text-xs text-slate-600">
              {policy.data.allowed_extensions.map((e) => e.toUpperCase()).join(", ")} · up to{" "}
              {formatBytes(policy.data.max_upload_size_bytes)} each
            </p>
            <Button type="button" variant="secondary" className="mt-4" onClick={() => inputRef.current?.click()}>
              Choose files
            </Button>
            <label htmlFor="file-input" className="sr-only">
              Choose files to upload
            </label>
            <input
              id="file-input"
              ref={inputRef}
              type="file"
              multiple
              accept={accept}
              className="sr-only"
              data-testid="file-input"
              onChange={(e) => {
                if (e.target.files) addFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>
          <p className="mt-3 text-xs text-slate-500">
            Demo service: please don&apos;t upload confidential or personal documents.
          </p>
        </Card>
      ) : null}

      {items.length > 0 ? (
        <section aria-label="Uploads" className="mt-6">
          <h2 className="sr-only">Uploads</h2>
          <ul className="space-y-3" aria-live="polite">
            {items.map((item) => (
              <UploadRow key={item.key} item={item} onRetryUpload={() => start(item.key, item.file)} onReprocess={() => void reprocess(item)} />
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}

function UploadRow({
  item,
  onRetryUpload,
  onReprocess,
}: {
  item: UploadItem;
  onRetryUpload: () => void;
  onReprocess: () => void;
}) {
  const percent = Math.round(item.progress * 100);
  return (
    <li>
      <Card className="p-4" data-testid="upload-item">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-slate-900">{item.file.name}</p>
            <p className="text-xs text-slate-500">{formatBytes(item.file.size)}</p>
          </div>
          {item.phase === "rejected" || item.phase === "upload-failed" ? (
            <span className="rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-medium text-red-800 ring-1 ring-inset ring-red-300">
              {item.phase === "rejected" ? "Not uploaded" : "Upload failed"}
            </span>
          ) : item.phase === "uploading" ? (
            <span className="text-xs font-medium text-slate-600">Uploading {percent}%</span>
          ) : (
            <StatusBadge status={item.phase} />
          )}
        </div>

        {item.phase === "uploading" ? (
          <div
            className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100"
            role="progressbar"
            aria-label={`Uploading ${item.file.name}`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
          >
            <div className="h-full bg-brand-600 transition-all" style={{ width: `${percent}%` }} />
          </div>
        ) : null}

        {item.phase === "rejected" ? <p className="mt-2 text-sm text-red-800">{item.reason}</p> : null}

        {item.phase === "upload-failed" ? (
          <div className="mt-3 space-y-2">
            <p className="text-sm text-red-800">
              {friendlyError(item.error).title}: {friendlyError(item.error).message}
            </p>
            <Button type="button" variant="secondary" onClick={onRetryUpload}>
              Retry upload
            </Button>
          </div>
        ) : null}

        {item.phase === "completed" && item.documentId ? (
          <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
            <span className="text-slate-600">
              Ready{typeof item.chunkCount === "number" ? ` · ${item.chunkCount} chunks indexed` : ""}
            </span>
            <Link className="font-medium text-brand-700 hover:underline" href={`/documents/${item.documentId}`}>
              View
            </Link>
            <Link className="font-medium text-brand-700 hover:underline" href={`/search?document=${item.documentId}`}>
              Search
            </Link>
            <Link className="font-medium text-brand-700 hover:underline" href={`/ask?document=${item.documentId}`}>
              Ask
            </Link>
          </div>
        ) : null}

        {item.phase === "failed" ? (
          <div className="mt-3 space-y-2">
            <p className="text-sm text-red-800">{processingFailureMessage(item.failure)}</p>
            <Button type="button" variant="secondary" onClick={onReprocess}>
              Retry processing
            </Button>
          </div>
        ) : null}

        {item.error && item.phase !== "upload-failed" ? (
          <div className="mt-3">
            <ErrorAlert error={item.error} />
          </div>
        ) : null}
      </Card>
    </li>
  );
}
