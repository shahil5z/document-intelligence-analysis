import Link from "next/link";

import { ArchitectureDiagram } from "@/components/ArchitectureDiagram";
import { ButtonLink } from "@/components/ui";

const FEATURES = [
  {
    title: "Upload PDF, DOCX and TXT",
    body: "Drag and drop files up to the server's size limit. Each upload is validated, stored privately and processed in the background with live status.",
  },
  {
    title: "Hybrid search",
    body: "Combines vector similarity (pgvector) with PostgreSQL full-text search, so both meaning and exact terms find the right passage.",
  },
  {
    title: "Answers with citations",
    body: "Ask a question and get an answer built only from your retrieved passages, with numbered citations you can check. If the evidence is weak, it says so.",
  },
  {
    title: "Private by default",
    body: "Every document, search and answer is scoped to your account. Other users cannot list, open or search your files.",
  },
];

const STACK = [
  ["Frontend", "Next.js (App Router), TypeScript, Tailwind CSS"],
  ["API", "FastAPI, SQLAlchemy 2, Pydantic, gunicorn + uvicorn"],
  ["Data", "PostgreSQL 16 with pgvector (HNSW), Alembic migrations"],
  ["Processing", "Celery + Redis, pypdf / python-docx, sentence-transformers (bge-small-en-v1.5)"],
  ["AI", "OpenAI-compatible chat model, used only for question answering"],
  ["Operations", "Docker Compose, Caddy (automatic HTTPS), Prometheus metrics, GitHub Actions"],
];

export default function LandingPage() {
  return (
    <>
      <section className="bg-gradient-to-b from-white to-slate-50">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-24">
          <p className="text-sm font-semibold uppercase tracking-wide text-brand-600">
            Document Intelligence Platform
          </p>
          <h1 className="mt-3 max-w-3xl text-4xl font-semibold tracking-tight text-slate-900 sm:text-5xl">
            Upload documents, search their contents, and ask AI questions with grounded citations.
          </h1>
          <p className="mt-5 max-w-2xl text-lg text-slate-600">
            A full-stack retrieval-augmented generation (RAG) application: background document
            processing, hybrid semantic and keyword search, and answers that point to the exact
            passages they came from.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <ButtonLink href="/register" className="px-5 py-2.5">
              Create a free account
            </ButtonLink>
            <ButtonLink href="/login" variant="secondary" className="px-5 py-2.5">
              Sign in
            </ButtonLink>
            <ButtonLink href="/architecture" variant="ghost" className="px-5 py-2.5">
              See the architecture
            </ButtonLink>
          </div>
        </div>
      </section>

      <section aria-labelledby="features" className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
        <h2 id="features" className="text-2xl font-semibold tracking-tight">What it does</h2>
        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          {FEATURES.map((feature) => (
            <div key={feature.title} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <h3 className="font-semibold text-slate-900">{feature.title}</h3>
              <p className="mt-2 text-sm text-slate-600">{feature.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="architecture" className="border-y border-slate-200 bg-white">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 py-14 sm:px-6 lg:grid-cols-2">
          <div>
            <h2 id="architecture" className="text-2xl font-semibold tracking-tight">How it is built</h2>
            <dl className="mt-6 space-y-4">
              {STACK.map(([term, detail]) => (
                <div key={term}>
                  <dt className="text-sm font-semibold text-slate-900">{term}</dt>
                  <dd className="text-sm text-slate-600">{detail}</dd>
                </div>
              ))}
            </dl>
            <Link href="/architecture" className="mt-6 inline-block text-sm font-medium text-brand-700 hover:underline">
              Read the architecture overview →
            </Link>
          </div>
          <ArchitectureDiagram />
        </div>
      </section>

      <section aria-labelledby="security" className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
        <h2 id="security" className="text-2xl font-semibold tracking-tight">Security and privacy</h2>
        <ul className="mt-6 grid gap-4 text-sm text-slate-700 sm:grid-cols-2">
          <li className="rounded-xl border border-slate-200 bg-white p-5">
            <strong className="block text-slate-900">Session token never exposed to page scripts</strong>
            Your session lives in an HttpOnly, SameSite cookie on this site; state-changing
            requests are protected against CSRF.
          </li>
          <li className="rounded-xl border border-slate-200 bg-white p-5">
            <strong className="block text-slate-900">Per-user isolation</strong>
            Documents, chunks, searches and answers are filtered by owner in every query.
          </li>
          <li className="rounded-xl border border-slate-200 bg-white p-5">
            <strong className="block text-slate-900">Validated uploads</strong>
            File type, signature and size are checked before anything is stored.
          </li>
          <li className="rounded-xl border border-slate-200 bg-white p-5">
            <strong className="block text-slate-900">Honest limits</strong>
            This is a demo: rate limits apply, and AI answers can be wrong. Don&apos;t upload
            confidential documents.
          </li>
        </ul>
      </section>

      <section className="mx-auto max-w-6xl px-4 pb-16 sm:px-6">
        <div className="rounded-2xl bg-brand-900 px-6 py-10 text-center text-white sm:px-12">
          <h2 className="text-2xl font-semibold">Try it with your own documents</h2>
          <p className="mx-auto mt-2 max-w-xl text-sm text-brand-100">
            Create an account, upload a PDF and ask a question. It takes about a minute.
          </p>
          <div className="mt-6 flex justify-center">
            <ButtonLink href="/register" variant="secondary">
              Get started
            </ButtonLink>
          </div>
        </div>
      </section>
    </>
  );
}
