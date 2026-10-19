export interface AuditEntry {
  id: string;
  action: string;
  resource_type: string | null;
  resource_id?: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
}

export const ACTION_LABELS: Record<string, string> = {
  "user.registered": "Account created",
  "user.login": "Signed in",
  "user.login_failed": "Failed sign-in attempt",
  "user.demo_created": "Demo session started",
  "user.demo_converted": "Demo converted to a free account",
  "document.uploaded": "Document uploaded",
  "document.deleted": "Document deleted",
  "document.reprocess_requested": "Reprocessing requested",
};

export function activityLabel(entry: AuditEntry): string {
  return ACTION_LABELS[entry.action] ?? entry.action;
}

export function activityDetail(entry: AuditEntry): string | null {
  const name = entry.metadata?.original_filename;
  return typeof name === "string" ? name : null;
}

const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

export function timeAgo(iso: string, now: number = Date.now()): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000);
  if (!Number.isFinite(seconds)) return "";
  const abs = Math.abs(seconds);
  if (abs < 60) return relative.format(seconds, "second");
  if (abs < 3600) return relative.format(Math.round(seconds / 60), "minute");
  if (abs < 86400) return relative.format(Math.round(seconds / 3600), "hour");
  return relative.format(Math.round(seconds / 86400), "day");
}
