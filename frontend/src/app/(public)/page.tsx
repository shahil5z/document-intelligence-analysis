import Link from "next/link";

import { DemoButton } from "@/components/demo/DemoButton";
import { FullLogo } from "@/components/Logo";
import { ButtonLink } from "@/components/ui";
import { PRODUCT_NAME } from "@/lib/brand";

const STEPS = [
  {
    title: "Upload",
    body: "PDF, DOCX or TXT. Files are validated (type, signature, size) and processed in the background.",
  },
  {
    title: "Index",
    body: "Text is extracted, split into passages and embedded with bge-small-en-v1.5 into PostgreSQL + pgvector.",
  },
  {
    title: "Ask",
    body: "Hybrid retrieval finds the relevant passages; the model answers only from them and cites each claim as [n].",
  },
];

const FEATURES = [
  {
    title: "Answers with citations",
    body: "Every claim points to a numbered source card with file, page and the exact excerpt. Citations to passages that were not retrieved are removed.",
    icon: "M8 10h8M8 14h5M5 4h14a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1h-6l-4 3v-3H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z",
  },
  {
    title: "Honest about gaps",
    body: "When the documents only partly cover a question, you get the supported part and what is missing. With no relevant passage, no answer is invented.",
    icon: "M12 9v4m0 4h.01M10.3 3.9 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z",
  },
  {
    title: "Hybrid search",
    body: "Semantic similarity and PostgreSQL full-text search combined with reciprocal rank fusion, with matched terms highlighted.",
    icon: "m21 21-4.3-4.3M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z",
  },
  {
    title: "Private by default",
    body: "Documents, passages, searches and answers are filtered by owner in every query. The session token lives in an HttpOnly cookie.",
    icon: "M12 3 4.5 6v5.5c0 4.4 3.2 8.4 7.5 9.5 4.3-1.1 7.5-5.1 7.5-9.5V6L12 3Z",
  },
  {
    title: "Prompt-injection aware",
    body: "Retrieved text is escaped and treated as untrusted data; instructions inside documents are not followed.",
    icon: "M9 12l2 2 4-4M7 4h10l3 3v10l-3 3H7l-3-3V7l3-3Z",
  },
  {
    title: "Built to operate",
    body: "Rate limits, structured logs with request ids, Prometheus metrics, health checks, migrations and backups.",
    icon: "M4 19h16M7 16V9m5 7V5m5 11v-4",
  },
];

const STACK = [
  ["Frontend", "Next.js App Router, TypeScript, Tailwind CSS"],
  ["API", "FastAPI, SQLAlchemy 2, Pydantic, Alembic"],
  ["Search", "PostgreSQL 16 + pgvector (HNSW) and full-text search"],
  ["Processing", "Celery + Redis, pypdf, python-docx, sentence-transformers"],
  ["AI", "OpenAI-compatible chat model (gpt-4o-mini), structured outputs"],
  ["Ops", "Docker Compose, Caddy (HTTPS), Prometheus, GitHub Actions"],
];

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d={d} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function AnswerPreview() {
  return (
    <figure className="relative rounded-2xl border border-border bg-surface p-5 shadow-pop sm:p-6" aria-label="Illustration of an answer with citations">
      <div className="flex items-center gap-2 text-xs text-subtle">
        <span className="h-2 w-2 rounded-full bg-emerald-500" aria-hidden="true" />
        Illustration · refund-policy.pdf
      </div>
      <p className="mt-4 text-sm font-medium text-fg">How long do customers have to return an item?</p>
      <div className="mt-3 rounded-xl bg-surface-2 p-4 text-sm leading-6 text-fg">
        Customers can return unused items within <strong>30 days of delivery</strong>
        <span className="mx-1 rounded-md bg-brand-50 px-1.5 py-0.5 text-xs font-semibold text-brand-700 ring-1 ring-inset ring-brand-200">1</span>
        for a full refund, paid to the original payment method within 7 business days
        <span className="mx-1 rounded-md bg-brand-50 px-1.5 py-0.5 text-xs font-semibold text-brand-700 ring-1 ring-inset ring-brand-200">2</span>.
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {[
          ["1", "page 1", "…return unused items within 30 days of delivery…"],
          ["2", "page 1", "…issued to the original payment method within 7 business days."],
        ].map(([n, page, text]) => (
          <div key={n} className="rounded-lg border border-border p-3 text-xs">
            <p className="font-semibold text-fg">
              [{n}] refund-policy.pdf <span className="font-normal text-subtle">· {page}</span>
            </p>
            <p className="mt-1 text-muted">{text}</p>
          </div>
        ))}
      </div>
    </figure>
  );
}

export default function LandingPage() {
  return (
    <>
      <section className="relative overflow-hidden">
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 -z-10">
          <div className="absolute -left-40 -top-40 h-[480px] w-[480px] rounded-full bg-brand-600/15 blur-3xl" />
          <div className="absolute -right-32 top-20 h-[420px] w-[420px] rounded-full bg-violet-600/15 blur-3xl" />
        </div>
        <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 pb-16 pt-12 sm:px-6 sm:pt-16 lg:grid-cols-[1.1fr_1fr] lg:pb-24">
          <div>
            <FullLogo width={220} className="mb-6" />
            <h1 className="max-w-xl text-4xl font-semibold tracking-tight text-fg sm:text-5xl">
              Ask your documents. <span className="text-gradient">Get answers you can verify.</span>
            </h1>
            <p className="mt-5 max-w-xl text-lg leading-relaxed text-muted">
              {PRODUCT_NAME} indexes your PDFs and Word files, finds the passages that matter
              and answers questions with numbered citations to the exact page and excerpt.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <DemoButton size="lg" variant="primary" />
              <ButtonLink href="/login" size="lg" variant="secondary">
                Sign in
              </ButtonLink>
            </div>
            <p className="mt-4 text-xs text-subtle">
              Demo: no sign-up, 1 PDF up to 5 MB, 3 questions, deleted after 24 hours.
              Please don&apos;t upload confidential documents.
            </p>
          </div>
          <AnswerPreview />
        </div>
      </section>

      <section id="how-it-works" aria-labelledby="how-heading" className="scroll-mt-20 border-y border-border bg-surface">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <p className="text-sm font-semibold text-brand-700">How it works</p>
          <h2 id="how-heading" className="mt-1 text-2xl font-semibold tracking-tight text-fg sm:text-3xl">
            From file to cited answer in three steps
          </h2>
          <ol className="mt-10 grid gap-6 md:grid-cols-3">
            {STEPS.map((step, index) => (
              <li key={step.title} className="relative rounded-xl border border-border bg-background p-6">
                <span className="bg-brand-gradient flex h-8 w-8 items-center justify-center rounded-lg text-sm font-semibold text-white" aria-hidden="true">
                  {index + 1}
                </span>
                <h3 className="mt-4 font-semibold text-fg">{step.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{step.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section id="features" aria-labelledby="features-heading" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-16 sm:px-6">
        <p className="text-sm font-semibold text-brand-700">Features</p>
        <h2 id="features-heading" className="mt-1 text-2xl font-semibold tracking-tight text-fg sm:text-3xl">
          Grounded by design
        </h2>
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((feature) => (
            <div key={feature.title} className="rounded-xl border border-border bg-surface p-6 shadow-card">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-200">
                <Icon d={feature.icon} />
              </div>
              <h3 className="mt-4 font-semibold text-fg">{feature.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">{feature.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="stack-heading" className="border-y border-border bg-surface">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:px-6 lg:grid-cols-[1fr_1.4fr]">
          <div>
            <p className="text-sm font-semibold text-brand-700">Tech stack</p>
            <h2 id="stack-heading" className="mt-1 text-2xl font-semibold tracking-tight text-fg sm:text-3xl">
              Production-style, end to end
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-muted">
              A full-stack retrieval-augmented generation (RAG) application built as a
              portfolio project, with tests, migrations and deployment scripts.
            </p>
            <Link href="/architecture" className="mt-5 inline-block text-sm font-medium text-link hover:underline">
              Read the architecture overview →
            </Link>
          </div>
          <dl className="grid gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-2">
            {STACK.map(([term, detail]) => (
              <div key={term} className="bg-surface p-5">
                <dt className="text-xs font-semibold uppercase tracking-wider text-subtle">{term}</dt>
                <dd className="mt-1 text-sm text-fg">{detail}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <div className="bg-brand-gradient relative overflow-hidden rounded-2xl px-6 py-12 text-center text-white sm:px-12">
          <h2 className="text-2xl font-semibold sm:text-3xl">Try it with a document of your own</h2>
          <p className="mx-auto mt-3 max-w-xl text-sm text-white/90">
            Start the demo without an account, or create a free account to keep your documents.
          </p>
          <div className="mt-7 flex flex-wrap justify-center gap-3">
            <DemoButton size="lg" variant="secondary" />
            <ButtonLink href="/register" size="lg" variant="ghost" className="text-white ring-1 ring-inset ring-white/50 hover:bg-white/10 hover:text-white">
              Create free account
            </ButtonLink>
          </div>
        </div>
      </section>
    </>
  );
}
