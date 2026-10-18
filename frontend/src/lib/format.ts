export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "-";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unit]}`;
}

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "-";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "-" : dateFormatter.format(date);
}

const TYPE_LABELS: Record<string, string> = {
  "application/pdf": "PDF",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
  "text/plain": "TXT",
};

export function fileTypeLabel(contentType: string, filename?: string): string {
  const known = TYPE_LABELS[contentType];
  if (known) return known;
  const ext = filename?.split(".").pop();
  return ext ? ext.toUpperCase() : contentType;
}

export function pageLabel(start: number | null, end: number | null): string | null {
  if (start === null) return null;
  return end !== null && end !== start ? `pages ${start}-${end}` : `page ${start}`;
}
