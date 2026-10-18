import type { DocumentStatus, JobStatus } from "@/lib/types";

const STYLES: Record<string, string> = {
  uploaded: "bg-slate-100 text-slate-700 ring-slate-300",
  pending: "bg-slate-100 text-slate-700 ring-slate-300",
  queued: "bg-amber-50 text-amber-800 ring-amber-300",
  processing: "bg-blue-50 text-blue-800 ring-blue-300",
  retrying: "bg-amber-50 text-amber-800 ring-amber-300",
  completed: "bg-emerald-50 text-emerald-800 ring-emerald-300",
  failed: "bg-red-50 text-red-800 ring-red-300",
};

const LABELS: Record<string, string> = {
  uploaded: "Uploaded",
  pending: "Pending",
  queued: "Queued",
  processing: "Processing",
  retrying: "Retrying",
  completed: "Completed",
  failed: "Failed",
};

export function StatusBadge({ status }: { status: DocumentStatus | JobStatus }) {
  const active = status === "processing" || status === "queued" || status === "retrying";
  return (
    <span
      data-testid="status-badge"
      data-status={status}
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${STYLES[status] ?? STYLES.uploaded}`}
    >
      <span
        aria-hidden="true"
        className={`h-1.5 w-1.5 rounded-full bg-current ${active ? "animate-pulse" : ""}`}
      />
      {LABELS[status] ?? status}
    </span>
  );
}

export function isActiveStatus(status: DocumentStatus): boolean {
  return status === "uploaded" || status === "queued" || status === "processing";
}
