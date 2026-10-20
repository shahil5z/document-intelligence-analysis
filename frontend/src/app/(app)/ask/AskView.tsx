"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { Markdown } from "@/components/ask/Markdown";
import { DocumentFilter } from "@/components/DocumentFilter";
import { ErrorAlert } from "@/components/ErrorAlert";
import { useSession } from "@/components/SessionProvider";
import { useToast } from "@/components/Toast";
import { Badge, Button, Card } from "@/components/ui";
import { api } from "@/lib/client/api";
import { useSuggestions } from "@/lib/client/suggestions";
import { pageLabel } from "@/lib/format";
import type { AskResponse, Citation } from "@/lib/types";

const HISTORY_KEY = "dia-ask-history";
const HISTORY_LIMIT = 20;


const INSUFFICIENT_TEXT: Record<string, string> = {
  below_threshold: "No passage in your documents was relevant enough to this question, so no answer was generated.",
  model_declined: "The relevant passages don't contain the answer, so none was generated.",
  no_valid_citations: "The answer could not be tied to any retrieved passage, so it was withheld.",
  parse_failed: "The model's reply could not be read reliably, so it was withheld. Please try again.",
};

interface Turn {
  id: string;
  question: string;
  documentId: string;
  askedAt: number;
  response?: AskResponse;
  error?: unknown;
}

function loadHistory(): Turn[] {
  try {
    const raw = window.sessionStorage.getItem(HISTORY_KEY);
    const parsed = raw ? (JSON.parse(raw) as Turn[]) : [];
    return Array.isArray(parsed) ? parsed.filter((t) => t.response) : [];
  } catch {
    return [];
  }
}

function plainAnswer(response: AskResponse): string {
  const sources = response.citations
    .map((c) => `[${c.number}] ${c.filename}${pageLabel(c.page_start, c.page_end) ? `, ${pageLabel(c.page_start, c.page_end)}` : ""}`)
    .join("\n");
  return sources ? `${response.answer}\n\nSources:\n${sources}` : response.answer;
}

export function AskView() {
  const params = useSearchParams();
  const { user, setDemoQuestionsRemaining } = useSession();
  const toast = useToast();
  const [question, setQuestion] = useState(() => (params.get("q") ?? "").slice(0, 1000));
  const [documentId, setDocumentId] = useState(params.get("document") ?? "");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [hydrated, setHydrated] = useState(false);
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const { suggestions, loading: suggestionsLoading } = useSuggestions(documentId);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    // sessionStorage is only readable after mount; this keeps SSR and first paint identical.
    setTurns(loadHistory());
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    try {
      const keep = turns.filter((t) => t.response).slice(-HISTORY_LIMIT);
      window.sessionStorage.setItem(HISTORY_KEY, JSON.stringify(keep));
    } catch {
      // storage full or disabled: history simply isn't kept
    }
  }, [turns, hydrated]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [turns.length, busy]);

  async function ask(text: string) {
    const asked = text.trim();
    if (!asked || busy) return;
    const turn: Turn = { id: crypto.randomUUID(), question: asked, documentId, askedAt: Date.now() };
    setTurns((prev) => [...prev, turn]);
    setQuestion("");
    setBusy(true);
    try {
      const response = await api.post<AskResponse>("ask", { question: asked, document_id: documentId || null });
      setTurns((prev) => prev.map((t) => (t.id === turn.id ? { ...t, response } : t)));
      if (typeof response.demo_questions_remaining === "number") setDemoQuestionsRemaining(response.demo_questions_remaining);
    } catch (err) {
      setTurns((prev) => prev.map((t) => (t.id === turn.id ? { ...t, error: err } : t)));
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void ask(question);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void ask(question);
    }
  }

  const demo = user?.is_demo ? user.demo : null;
  const outOfQuestions = demo ? demo.questions_remaining <= 0 : false;

  return (
    <div className="mx-auto flex max-w-3xl flex-col">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-fg">Ask AI</h1>
          <p className="mt-1 text-sm text-muted">Answers come only from your files, with page sources.</p>
        </div>
        {turns.length > 0 ? (
          <Button variant="ghost" size="sm" onClick={() => setTurns([])} disabled={busy}>
            Clear conversation
          </Button>
        ) : null}
      </div>

      <div className="mt-6 flex-1 space-y-6" aria-live="polite" aria-busy={busy}>
        {hydrated && turns.length === 0 ? (
          <Card className="p-6 text-center sm:p-8">
            <div aria-hidden="true" className="bg-brand-gradient mx-auto flex h-11 w-11 items-center justify-center rounded-xl text-white">
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M8 10h8M8 14h5M5 4h14a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1h-6l-4 3v-3H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <h2 className="mt-4 font-semibold text-fg">Ask about your files</h2>
            <p className="mt-1 text-sm text-muted">
              {suggestions.generated
                ? suggestions.source
                  ? <>Suggested from <span className="font-medium text-fg">{suggestions.source}</span>:</>
                  : "Suggested from your recent documents:"
                : "Pick a file below or ask across all of them."}
            </p>
            {suggestions.pending ? (
              <p role="status" className="mt-3 text-xs text-subtle" data-testid="suggestions-pending">
                <span className="mr-1.5 inline-block h-2 w-2 animate-pulse rounded-full bg-brand-500 align-middle" aria-hidden="true" />
                Preparing question ideas for this file…
              </p>
            ) : null}
            <ul
              className={`mt-5 grid gap-2 text-left sm:grid-cols-2 ${suggestionsLoading ? "opacity-60" : ""}`}
              aria-busy={suggestionsLoading}
              data-testid="suggestions"
              data-generated={suggestions.generated ? "true" : "false"}
            >
              {suggestions.questions.map((starter) => (
                <li key={starter}>
                  <button
                    type="button"
                    data-testid="starter-question"
                    disabled={busy}
                    onClick={() => void ask(starter)}
                    className="w-full rounded-lg border border-border bg-surface px-3 py-2.5 text-sm text-muted transition-colors hover:border-brand-300 hover:bg-brand-50 hover:text-fg disabled:opacity-50"
                  >
                    {starter}
                  </button>
                </li>
              ))}
            </ul>
          </Card>
        ) : null}

        {turns.map((turn) => (
          <TurnView key={turn.id} turn={turn} onCopy={(text) => {
            void navigator.clipboard.writeText(text).then(
              () => toast.show({ tone: "success", title: "Copied", message: "Answer and sources copied to the clipboard." }),
              () => toast.show({ tone: "error", title: "Copy failed", message: "Your browser blocked clipboard access." }),
            );
          }} />
        ))}
        <div ref={endRef} />
      </div>

      <form onSubmit={onSubmit} className="sticky bottom-14 z-10 -mx-4 mt-6 bg-background/95 px-4 pb-3 pt-2 backdrop-blur-sm sm:-mx-6 sm:px-6 lg:bottom-0 lg:mx-0 lg:px-0 lg:pb-4">
        <div className="rounded-2xl border border-border bg-surface p-3 shadow-pop focus-within:border-brand-400 focus-within:ring-2 focus-within:ring-ring/30">
          <label htmlFor="question" className="sr-only">
            Your question
          </label>
          <textarea
            id="question"
            ref={inputRef}
            required
            rows={2}
            maxLength={1000}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={outOfQuestions ? "All demo questions used. Create a free account to keep asking." : "Ask a question…  (Enter to send)"}
            className="block w-full resize-none bg-transparent px-1 text-[15px] text-fg placeholder:text-subtle focus:outline-none disabled:cursor-not-allowed"
          />
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2">
              <label htmlFor="ask-document" className="sr-only text-xs font-medium text-subtle sm:not-sr-only">
                Document
              </label>
              <div className="w-48 max-w-[60vw] sm:w-56">
                <DocumentFilter id="ask-document" value={documentId} onChange={setDocumentId} compact />
              </div>
            </div>
            <Button type="submit" disabled={busy || !question.trim()}>
              {busy ? "Thinking…" : "Ask"}
            </Button>
          </div>
        </div>
        <p className="mt-2 text-center text-xs text-subtle">
          AI answers can be wrong. Check the sources.
        </p>
      </form>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div role="status" className="flex items-center gap-2 text-sm text-muted" data-testid="typing-indicator">
      <span className="flex gap-1" aria-hidden="true">
        {[0, 150, 300].map((delay) => (
          <span key={delay} className="h-2 w-2 animate-bounce rounded-full bg-brand-500" style={{ animationDelay: `${delay}ms` }} />
        ))}
      </span>
      Reading your files…
    </div>
  );
}

function TurnView({ turn, onCopy }: { turn: Turn; onCopy: (text: string) => void }) {
  const [active, setActive] = useState<number | null>(null);
  const response = turn.response;

  function focusCitation(number: number) {
    setActive(number);
    document.getElementById(`citation-${turn.id}-${number}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  return (
    <article className="animate-slide-up space-y-3">
      <div className="flex justify-end">
        <p className="max-w-[85%] whitespace-pre-line rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-[15px] text-white" data-testid="question-bubble">
          {turn.question}
        </p>
      </div>

      {!response && !turn.error ? (
        <Card className="p-4">
          <TypingIndicator />
        </Card>
      ) : null}

      {turn.error ? <ErrorAlert error={turn.error} /> : null}

      {response?.insufficient_evidence ? (
        <Card className="border-amber-200 bg-amber-50 p-5" data-testid="insufficient-evidence">
          <h2 className="font-semibold text-amber-900">Not enough evidence</h2>
          <p className="mt-1 text-sm text-amber-900">
            {INSUFFICIENT_TEXT[response.insufficient_reason ?? ""] ?? INSUFFICIENT_TEXT.model_declined} Try rephrasing,
            choosing another document, or uploading a document that covers the topic.
          </p>
        </Card>
      ) : null}

      {response && !response.insufficient_evidence ? (
        <Card className="p-5" data-testid="answer">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-subtle">Answer</span>
              {response.partial ? <Badge tone="warning">Partial</Badge> : null}
            </div>
            <Button variant="ghost" size="sm" onClick={() => onCopy(plainAnswer(response))} aria-label="Copy answer">
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                <rect x="9" y="9" width="11" height="11" rx="2" />
                <path d="M5 15V5a1 1 0 0 1 1-1h10" />
              </svg>
              Copy
            </Button>
          </div>
          <div className="text-[15px] leading-7 text-fg">
            <Markdown
              source={response.answer}
              renderCitation={(number, key) =>
                response.citations.some((c) => c.number === number) ? (
                  <button
                    key={key}
                    type="button"
                    onClick={() => focusCitation(number)}
                    aria-label={`Citation ${number}`}
                    data-testid="citation-chip"
                    className={`mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-md px-1 align-text-top text-[11px] font-semibold transition-colors ${
                      active === number ? "bg-primary text-white" : "bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-200 hover:bg-brand-100"
                    }`}
                  >
                    {number}
                  </button>
                ) : null
              }
            />
          </div>
          {response.partial && response.missing_information ? (
            <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900" data-testid="missing-information">
              <strong className="font-semibold">Not covered by your documents:</strong> {response.missing_information}
            </p>
          ) : null}
          <p className="mt-4 text-xs text-subtle">
            Based on {response.sources_considered} retrieved passage{response.sources_considered === 1 ? "" : "s"}
            {response.model ? ` · ${response.model}` : ""}
            {response.warnings.includes("invalid_citations_removed") ? " · references that could not be verified were removed" : ""}
          </p>
          {response.citations.length > 0 ? (
            <div className="mt-4 border-t border-border pt-4">
              <h2 className="mb-2 text-sm font-semibold text-fg">Sources</h2>
              <ol className="space-y-2">
                {response.citations.map((citation) => (
                  <CitationCard
                    key={citation.chunk_id}
                    turnId={turn.id}
                    citation={citation}
                    active={active === citation.number}
                    onToggle={(open) => setActive(open ? citation.number : null)}
                  />
                ))}
              </ol>
            </div>
          ) : null}
        </Card>
      ) : null}
    </article>
  );
}

function CitationCard({
  turnId,
  citation,
  active,
  onToggle,
}: {
  turnId: string;
  citation: Citation;
  active: boolean;
  onToggle: (open: boolean) => void;
}) {
  const page = pageLabel(citation.page_start, citation.page_end);
  const preview = citation.snippet.length > 160 ? `${citation.snippet.slice(0, 160)}…` : citation.snippet;
  return (
    <li id={`citation-${turnId}-${citation.number}`} className="scroll-mt-24">
      <div
        data-testid="citation"
        data-active={active ? "true" : "false"}
        className={`rounded-lg border p-3 transition-colors ${active ? "border-brand-400 bg-brand-50 ring-2 ring-ring/25" : "border-border bg-surface-2"}`}
      >
        <p className="flex flex-wrap items-center gap-x-2 text-sm font-medium text-fg">
          <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-md bg-primary px-1 text-[11px] font-semibold text-white">
            {citation.number}
          </span>
          <Link href={`/documents/${citation.document_id}`} className="text-link hover:underline">
            {citation.filename}
          </Link>
          {page ? <span className="font-normal text-subtle">{page}</span> : null}
        </p>
        {!active ? <p className="mt-1.5 text-sm text-muted">{preview}</p> : null}
        <details open={active} onToggle={(e) => { if (e.currentTarget.open !== active) onToggle(e.currentTarget.open); }} className="mt-1.5">
          <summary className="cursor-pointer text-xs font-medium text-link">
            {active ? "Hide cited passage" : "Show cited passage"}
          </summary>
          <blockquote className="mt-2 whitespace-pre-line border-l-2 border-brand-300 pl-3 text-sm leading-6 text-fg">
            {citation.snippet}
            {citation.char_end - citation.char_start > citation.snippet.length ? "…" : ""}
          </blockquote>
          <p className="mt-2 text-xs text-subtle">
            Passage {citation.chunk_index + 1} · characters {citation.char_start}-{citation.char_end}
          </p>
        </details>
      </div>
    </li>
  );
}
