"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Fragment, useState, type FormEvent, type ReactNode } from "react";

import { DocumentFilter } from "@/components/DocumentFilter";
import { ErrorAlert } from "@/components/ErrorAlert";
import { Button, Card, Field, PageHeader, Skeleton, inputClass } from "@/components/ui";
import { api } from "@/lib/client/api";
import { pageLabel } from "@/lib/format";
import type { AskResponse, Citation } from "@/lib/types";

/** Replace the model's [S1] markers with [1] links, only for citations the API returned. */
function renderAnswer(answer: string, numbers: Map<string, number>): ReactNode[] {
  return answer.split(/(\[S\d+\])/g).map((part, index) => {
    const match = /^\[(S\d+)\]$/.exec(part);
    const number = match ? numbers.get(match[1]) : undefined;
    if (number === undefined) return <Fragment key={index}>{part}</Fragment>;
    return (
      <a
        key={index}
        href={`#citation-${number}`}
        className="mx-0.5 rounded bg-brand-50 px-1 text-xs font-semibold text-brand-700 no-underline hover:bg-brand-100"
        aria-label={`Citation ${number}`}
      >
        [{number}]
      </a>
    );
  });
}

export function AskView() {
  const params = useSearchParams();
  const [question, setQuestion] = useState("");
  const [documentId, setDocumentId] = useState(params.get("document") ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<{ question: string; response: AskResponse } | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const asked = question.trim();
    if (!asked) return;
    setBusy(true);
    setError(null);
    try {
      const response = await api.post<AskResponse>("ask", {
        question: asked,
        document_id: documentId || null,
      });
      setResult({ question: asked, response });
    } catch (err) {
      setError(err);
      setResult(null);
    } finally {
      setBusy(false);
    }
  }

  const response = result?.response;
  const numbers = new Map((response?.citations ?? []).map((c, i) => [c.source_id, i + 1]));

  return (
    <>
      <PageHeader
        title="Ask AI"
        description="Answers are generated only from passages retrieved from your documents."
      />
      <Card className="p-4 sm:p-6">
        <form onSubmit={onSubmit} className="space-y-4">
          <Field id="question" label="Your question">
            <textarea
              id="question"
              required
              rows={3}
              maxLength={1000}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. How many days do customers have to return an item?"
              className={inputClass}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="ask-document" label="Document">
              <DocumentFilter id="ask-document" value={documentId} onChange={setDocumentId} />
            </Field>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <Button type="submit" disabled={busy || !question.trim()}>
              {busy ? "Thinking…" : "Ask"}
            </Button>
            <p className="text-xs text-slate-500">
              AI answers can be wrong or incomplete. Check the cited passages before relying on them.
            </p>
          </div>
        </form>
      </Card>

      <section aria-label="Answer" aria-live="polite" className="mt-6 space-y-4">
        {error ? <ErrorAlert error={error} /> : null}
        {busy ? (
          <Card className="space-y-3 p-5" role="status">
            <span className="sr-only">Generating answer…</span>
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
          </Card>
        ) : null}

        {!busy && result && response ? (
          response.insufficient_evidence ? (
            <Card className="border-amber-200 bg-amber-50 p-5" data-testid="insufficient-evidence">
              <h2 className="font-semibold text-amber-900">Not enough evidence</h2>
              <p className="mt-1 text-sm text-amber-900">
                Your documents don&apos;t contain passages that answer this question well enough,
                so no answer was generated. Try rephrasing, choosing another document, or
                uploading a document that covers the topic.
              </p>
            </Card>
          ) : (
            <>
              <Card className="p-5" data-testid="answer">
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Answer</p>
                <p className="mt-1 text-sm font-medium text-slate-700">{result.question}</p>
                <div className="mt-3 whitespace-pre-line text-[15px] leading-7 text-slate-900">
                  {renderAnswer(response.answer, numbers)}
                </div>
                <p className="mt-4 text-xs text-slate-500">
                  Based on {response.sources_considered} retrieved passage
                  {response.sources_considered === 1 ? "" : "s"}
                  {response.model ? ` · model ${response.model}` : ""}
                  {response.warnings.includes("invalid_citations_removed")
                    ? " · references the system could not verify were removed"
                    : ""}
                </p>
              </Card>
              {response.citations.length > 0 ? (
                <div>
                  <h2 className="mb-2 text-sm font-semibold text-slate-900">Sources</h2>
                  <ol className="space-y-3">
                    {response.citations.map((citation, index) => (
                      <CitationCard key={citation.chunk_id} citation={citation} number={index + 1} />
                    ))}
                  </ol>
                </div>
              ) : (
                <p className="text-sm text-slate-600">The answer did not cite any passage.</p>
              )}
            </>
          )
        ) : null}
      </section>
    </>
  );
}

function CitationCard({ citation, number }: { citation: Citation; number: number }) {
  const page = pageLabel(citation.page_start, citation.page_end);
  const preview = citation.snippet.length > 160 ? `${citation.snippet.slice(0, 160)}…` : citation.snippet;
  return (
    <li id={`citation-${number}`} className="scroll-mt-24">
      <Card className="p-4" data-testid="citation">
        <p className="text-sm font-semibold text-slate-900">
          [{number}]{" "}
          <Link href={`/documents/${citation.document_id}`} className="text-brand-700 hover:underline">
            {citation.filename}
          </Link>
          {page ? <span className="font-normal text-slate-600"> - {page}</span> : null}
        </p>
        <p className="mt-2 text-sm text-slate-700">{preview}</p>
        <details className="mt-2">
          <summary className="cursor-pointer text-sm font-medium text-brand-700">Show cited passage</summary>
          <blockquote className="mt-2 whitespace-pre-line border-l-2 border-brand-200 pl-3 text-sm leading-6 text-slate-800">
            {citation.snippet}
            {citation.char_end - citation.char_start > citation.snippet.length ? "…" : ""}
          </blockquote>
          <p className="mt-2 text-xs text-slate-500">
            Chunk {citation.chunk_index + 1} · characters {citation.char_start}-{citation.char_end}
          </p>
        </details>
      </Card>
    </li>
  );
}
