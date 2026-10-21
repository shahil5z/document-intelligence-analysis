"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { Markdown } from "@/components/ask/Markdown";
import { DocumentFilter } from "@/components/DocumentFilter";
import { useSession } from "@/components/SessionProvider";
import { Button, Card, Skeleton } from "@/components/ui";
import { api } from "@/lib/client/api";
import { useSuggestions } from "@/lib/client/suggestions";
import { stripCitationMarkers } from "@/lib/answer";
import { ApiError, friendlyError } from "@/lib/errors";
import type { AskResponse } from "@/lib/types";

const HISTORY_KEY = "dia-ask-history";
const HISTORY_LIMIT = 20;


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

export function AskView() {
  const params = useSearchParams();
  const { user, setDemoQuestionsRemaining } = useSession();
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
          <p className="mt-1 text-sm text-muted">Ask questions about your documents. Answers are based only on their content.</p>
        </div>
        {turns.length > 0 ? (
          <Button variant="ghost" size="sm" onClick={() => setTurns([])} disabled={busy}>
            Clear conversation
          </Button>
        ) : null}
      </div>

      <div className="mt-6 flex-1 space-y-6" aria-busy={busy}>
        {hydrated && turns.length === 0 ? (
          <Card className="p-6 text-center sm:p-8">
            <div aria-hidden="true" className="bg-brand-gradient mx-auto flex h-11 w-11 items-center justify-center rounded-xl text-white">
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M8 10h8M8 14h5M5 4h14a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1h-6l-4 3v-3H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <h2 className="mt-4 font-semibold text-fg">Ask about your documents</h2>
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
              className="mt-5 grid gap-2 text-left sm:grid-cols-2"
              aria-busy={suggestionsLoading}
              data-testid="suggestions"
              data-generated={suggestions.generated ? "true" : "false"}
            >
              {suggestionsLoading
                ? [0, 1, 2, 3].map((n) => (
                    <li key={n}>
                      <Skeleton className="h-10 w-full rounded-lg" />
                    </li>
                  ))
                : suggestions.questions.map((starter) => (
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
          <TurnView key={turn.id} turn={turn} />
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
              {busy ? "Generating…" : "Ask"}
            </Button>
          </div>
        </div>
        <p className="mt-2 text-center text-xs text-subtle">
          AI answers can be wrong. Verify important details in the document.
        </p>
      </form>
    </div>
  );
}

function GeneratingIndicator() {
  return (
    <div role="status" className="flex items-center gap-2 text-sm text-muted" data-testid="typing-indicator">
      <span className="h-2 w-2 animate-pulse rounded-full bg-brand-500" aria-hidden="true" />
      Generating answer…
    </div>
  );
}

const GENERIC_ASK_ERROR = "Something went wrong while generating the answer. Please try again.";

/** Friendly copy for auth, rate-limit, demo-limit and input errors; everything else is generic. */
function askError(error: unknown): { title: string; message: string } {
  if (error instanceof ApiError) {
    if (error.status === 401 || error.status === 429 || error.code === "demo_limit_reached" || error.status === 404) {
      const { title, message } = friendlyError(error);
      return { title, message };
    }
    if (error.status === 400 || error.status === 422) {
      return { title: "Check your question", message: "Please enter a question of up to 1000 characters." };
    }
    if (error.status === 0) {
      return { title: "Connection problem", message: "The server could not be reached. Check your connection and try again." };
    }
  }
  return { title: "Answer not available", message: GENERIC_ASK_ERROR };
}

function CopyButton({ text }: { text: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  useEffect(() => {
    if (state === "idle") return;
    const timer = window.setTimeout(() => setState("idle"), 2000);
    return () => window.clearTimeout(timer);
  }, [state]);
  return (
    <>
      <button
        type="button"
        onClick={() => {
          void navigator.clipboard.writeText(text).then(
            () => setState("copied"),
            () => setState("failed"),
          );
        }}
        className="inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium text-muted transition-colors hover:bg-surface-2 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label="Copy answer"
        data-testid="copy-answer"
      >
        <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          {state === "copied" ? <path d="m5 12 5 5 9-10" strokeLinecap="round" strokeLinejoin="round" /> : <><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a1 1 0 0 1 1-1h10" /></>}
        </svg>
        {state === "copied" ? "Copied" : "Copy"}
      </button>
      <span className="sr-only" aria-live="polite">
        {state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : ""}
      </span>
    </>
  );
}

function TurnView({ turn }: { turn: Turn }) {
  const response = turn.response;
  const answer = response ? stripCitationMarkers(response.answer) : "";
  const error = turn.error ? askError(turn.error) : null;

  return (
    <article className="animate-slide-up space-y-3" aria-label={`Question: ${turn.question}`}>
      <div className="flex justify-end">
        <p
          className="max-w-[85%] whitespace-pre-line break-words rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-[15px] text-white [overflow-wrap:anywhere]"
          data-testid="question-bubble"
        >
          <span className="sr-only">You asked: </span>
          {turn.question}
        </p>
      </div>

      {!response && !turn.error ? (
        <div className="px-1 py-2">
          <GeneratingIndicator />
        </div>
      ) : null}

      {error ? (
        <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900" data-testid="ask-error">
          <p className="font-semibold">{error.title}</p>
          <p className="mt-1">{error.message}</p>
        </div>
      ) : null}

      {response ? (
        <section
          className="rounded-2xl border border-border bg-surface px-5 pb-4 pt-4 sm:px-6"
          aria-label="Answer"
          data-testid={response.insufficient_evidence ? "insufficient-evidence" : "answer"}
        >
          <div className="mb-2 flex items-center justify-between gap-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-subtle">Answer</h2>
            {answer ? <CopyButton text={answer} /> : null}
          </div>
          <div aria-live="polite">
            <Markdown source={answer || "I couldn't find enough information in this document to answer that confidently."} />
          </div>
        </section>
      ) : null}
    </article>
  );
}
