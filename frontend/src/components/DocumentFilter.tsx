"use client";

import { useApiResource } from "@/lib/client/hooks";
import type { DocumentItem, Page } from "@/lib/types";

import { inputClass } from "./ui";

/** "All documents" or one completed document. */
export function DocumentFilter({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const { data, loading } = useApiResource<Page<DocumentItem>>("documents?page=1&page_size=100");
  const completed = (data?.items ?? []).filter((d) => d.status === "completed");
  const selectedMissing = value !== "" && data !== null && !completed.some((d) => d.id === value);
  return (
    <select
      id={id}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={inputClass}
      disabled={loading && !data}
    >
      <option value="">All my documents</option>
      {selectedMissing ? <option value={value}>Selected document (not ready)</option> : null}
      {completed.map((doc) => (
        <option key={doc.id} value={doc.id}>
          {doc.original_filename}
        </option>
      ))}
    </select>
  );
}
