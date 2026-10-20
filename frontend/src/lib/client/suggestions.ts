"use client";

import { useEffect, useState } from "react";

import { isActiveStatus } from "@/components/StatusBadge";
import type { DocumentItem, Page } from "@/lib/types";

import { api } from "./api";
import { useInterval } from "./hooks";

/** Generic starters, used when no document-specific questions exist. */
export const STATIC_SUGGESTIONS = [
  "Summarize this document in a few bullet points.",
  "What are the key dates, deadlines or time limits?",
  "What obligations or requirements does it describe?",
  "Are there any fees, costs or amounts mentioned?",
];

const MAX_SUGGESTIONS = 4;

export interface Suggestions {
  questions: string[];
  /** True when the questions were generated from document content. */
  generated: boolean;
  /** A selected document is still processing; its questions are not ready yet. */
  pending: boolean;
  /** Filename the questions come from (single document), if any. */
  source: string | null;
}

const FALLBACK: Suggestions = { questions: STATIC_SUGGESTIONS, generated: false, pending: false, source: null };

function fromDocument(doc: DocumentItem): Suggestions {
  const qs = doc.suggested_questions ?? [];
  if (qs.length >= 3) {
    return { questions: qs.slice(0, MAX_SUGGESTIONS), generated: true, pending: false, source: doc.original_filename };
  }
  return { ...FALLBACK, pending: isActiveStatus(doc.status) };
}

function fromRecent(docs: DocumentItem[]): Suggestions {
  // Most recent completed documents first; take up to two per document, then fill.
  const withQuestions = docs.filter((d) => d.status === "completed" && (d.suggested_questions?.length ?? 0) >= 3);
  if (withQuestions.length === 0) return FALLBACK;
  if (withQuestions.length === 1) return fromDocument(withQuestions[0]);
  const picked: string[] = [];
  for (const round of [0, 1, 2, 3]) {
    for (const doc of withQuestions.slice(0, 2)) {
      const q = doc.suggested_questions?.[round];
      if (q && !picked.includes(q) && picked.length < MAX_SUGGESTIONS) picked.push(q);
    }
  }
  return { questions: picked, generated: true, pending: false, source: null };
}

/**
 * Suggested questions for the Ask panel: the selected document's generated questions
 * (polled while it is processing), otherwise questions from the most recent completed
 * documents, otherwise the static starters. Errors fall back silently.
 */
export function useSuggestions(documentId: string): { suggestions: Suggestions; loading: boolean } {
  const [state, setState] = useState<{ key: string; value: Suggestions } | null>(null);
  const [tick, setTick] = useState(0);
  const key = documentId || "*";

  useEffect(() => {
    let cancelled = false;
    const load = documentId
      ? api.get<DocumentItem>(`documents/${documentId}`).then(fromDocument)
      : api.get<Page<DocumentItem>>("documents?page=1&page_size=10").then((page) => fromRecent(page.items));
    load
      .then((value) => {
        if (!cancelled) setState({ key, value });
      })
      .catch(() => {
        if (!cancelled) setState({ key, value: FALLBACK });
      });
    return () => {
      cancelled = true;
    };
  }, [documentId, key, tick]);

  const current = state?.key === key ? state.value : null;
  useInterval(() => setTick((t) => t + 1), 3000, Boolean(current?.pending));
  return { suggestions: current ?? FALLBACK, loading: current === null };
}
