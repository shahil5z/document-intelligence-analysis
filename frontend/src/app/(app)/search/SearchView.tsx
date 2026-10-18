"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { DocumentFilter } from "@/components/DocumentFilter";
import { ErrorAlert } from "@/components/ErrorAlert";
import { Button, Card, EmptyState, Field, LoadingRows, PageHeader, inputClass } from "@/components/ui";
import { api } from "@/lib/client/api";
import { pageLabel } from "@/lib/format";
import type { SearchMode, SearchResponse, SearchResult } from "@/lib/types";

const MODES: { value: SearchMode; label: string; hint: string }[] = [
  { value: "hybrid", label: "Hybrid", hint: "Meaning and exact words (recommended)" },
  { value: "semantic", label: "Semantic", hint: "Similar meaning, different wording" },
  { value: "keyword", label: "Keyword", hint: "Exact terms (full-text)" },
];

const MAX_TOP_K = 20;

export function SearchView() {
  const params = useSearchParams();
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [documentId, setDocumentId] = useState(params.get("document") ?? "");
  const [topK, setTopK] = useState(5);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [response, setResponse] = useState<SearchResponse | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setResponse(
        await api.post<SearchResponse>("search", {
          query: query.trim(),
          mode,
          top_k: topK,
          document_id: documentId || null,
        }),
      );
    } catch (err) {
      setError(err);
      setResponse(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Search" description="Find passages across your completed documents." />
      <Card className="p-4 sm:p-6">
        <form onSubmit={onSubmit} className="space-y-4">
          <Field id="query" label="Search query">
            <input
              id="query"
              type="search"
              required
              maxLength={1000}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. return policy for unused items"
              className={inputClass}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-3">
            <fieldset>
              <legend className="block text-sm font-medium text-slate-800">Mode</legend>
              <div className="mt-1 flex rounded-lg bg-slate-100 p-1" role="radiogroup" aria-label="Search mode">
                {MODES.map((m) => (
                  <label
                    key={m.value}
                    title={m.hint}
                    className={`flex-1 cursor-pointer rounded-md px-2 py-1.5 text-center text-sm has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-brand-600 ${
                      mode === m.value ? "bg-white font-medium text-slate-900 shadow-sm" : "text-slate-600"
                    }`}
                  >
                    <input
                      type="radio"
                      name="mode"
                      value={m.value}
                      checked={mode === m.value}
                      onChange={() => setMode(m.value)}
                      className="sr-only"
                    />
                    {m.label}
                  </label>
                ))}
              </div>
            </fieldset>
            <Field id="document" label="Document">
              <DocumentFilter id="document" value={documentId} onChange={setDocumentId} />
            </Field>
            <Field id="top-k" label="Results">
              <input
                id="top-k"
                type="number"
                min={1}
                max={MAX_TOP_K}
                value={topK}
                onChange={(e) => setTopK(Math.min(MAX_TOP_K, Math.max(1, Number(e.target.value) || 1)))}
                className={inputClass}
              />
            </Field>
          </div>
          <Button type="submit" disabled={busy || !query.trim()}>
            {busy ? "Searching…" : "Search"}
          </Button>
        </form>
      </Card>

      <section aria-label="Search results" aria-live="polite" className="mt-6">
        {error ? <ErrorAlert error={error} /> : null}
        {busy ? <LoadingRows rows={3} label="Searching" /> : null}
        {!busy && response && response.results.length === 0 ? (
          <Card>
            <EmptyState
              title="No matching passages"
              description="Try different words, switch to semantic mode, or check that your documents have finished processing."
            />
          </Card>
        ) : null}
        {!busy && response && response.results.length > 0 ? (
          <>
            <p className="mb-3 text-sm text-slate-600">
              {response.results.length} result{response.results.length === 1 ? "" : "s"} ·{" "}
              {MODES.find((m) => m.value === response.mode)?.label} search
              {response.reranked ? " · reranked" : ""}
            </p>
            <ol className="space-y-3">
              {response.results.map((result, index) => (
                <ResultCard key={result.chunk_id} result={result} rank={index + 1} />
              ))}
            </ol>
          </>
        ) : null}
      </section>
    </>
  );
}

function ResultCard({ result, rank }: { result: SearchResult; rank: number }) {
  const [expanded, setExpanded] = useState(false);
  const long = result.text.length > 420;
  const text = expanded || !long ? result.text : `${result.text.slice(0, 420)}…`;
  const page = pageLabel(result.page_start, result.page_end);
  return (
    <li>
      <Card className="p-4" data-testid="search-result">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
          <p>
            <span className="font-semibold text-slate-700">#{rank}</span>{" "}
            <Link href={`/documents/${result.document_id}`} className="font-medium text-brand-700 hover:underline">
              {result.filename}
            </Link>
            {page ? ` · ${page}` : ""} · chunk {result.chunk_index + 1}
          </p>
          <p title="Relevance score from the retrieval engine">
            score {result.score.toFixed(3)}
            {result.similarity !== null ? ` · similarity ${result.similarity.toFixed(2)}` : ""}
          </p>
        </div>
        <p className="mt-2 whitespace-pre-line text-sm leading-6 text-slate-800">{text}</p>
        {long ? (
          <button
            type="button"
            className="mt-2 text-sm font-medium text-brand-700 hover:underline"
            aria-expanded={expanded}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? "Show less" : "Show full passage"}
          </button>
        ) : null}
      </Card>
    </li>
  );
}
