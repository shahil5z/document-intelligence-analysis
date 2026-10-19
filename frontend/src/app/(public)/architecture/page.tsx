import type { Metadata } from "next";

import { ArchitectureDiagram } from "@/components/ArchitectureDiagram";

export const metadata: Metadata = { title: "Architecture" };

const SECTIONS = [
  {
    title: "Upload and processing",
    body: "The browser asks the Next.js server for a five-minute, upload-only token and sends the file directly to the API (no serverless body limit). The API checks size, extension, content type and file signature, stores the file and queues a Celery job. A worker extracts text (pypdf, python-docx), normalises it, splits it into overlapping token chunks with page numbers, embeds them with BAAI/bge-small-en-v1.5 (384 dimensions) and writes them to PostgreSQL. Status moves queued → processing → completed or failed; failed jobs can be reprocessed.",
  },
  {
    title: "Search",
    body: "Hybrid mode runs a pgvector HNSW cosine search and a PostgreSQL full-text search over your chunks and merges them with reciprocal rank fusion. Semantic-only and keyword-only modes are available too. Every query is filtered by owner, so results only ever come from your documents.",
  },
  {
    title: "Ask AI",
    body: "The question is answered from the top retrieved passages only. If no passage is similar enough, the API returns an insufficient-evidence answer without calling the model. Otherwise the model must cite passages as [S1], [S2] …; citations that do not match a retrieved passage are removed before the answer is shown.",
  },
  {
    title: "Sessions and security",
    body: "The API issues short-lived JWTs. The frontend keeps the token in an HttpOnly, SameSite=Lax cookie on its own domain and forwards calls through route handlers that check a custom CSRF header and the Origin. The API adds security headers, request body limits, Redis-backed rate limits and an audit log.",
  },
  {
    title: "Deployment",
    body: "Production runs on one VM with Docker Compose: Caddy (automatic HTTPS) in front of the API (gunicorn with uvicorn workers), a Celery worker, a single beat scheduler, PostgreSQL with pgvector and Redis on an internal network. The frontend is deployed separately (for example on Vercel).",
  },
];

export default function ArchitecturePage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
      <h1 className="text-3xl font-semibold tracking-tight">Architecture</h1>
      <p className="mt-2 max-w-3xl text-slate-600">
        How a document travels from upload to a cited answer, and which component is
        responsible for each step.
      </p>
      <div className="mt-8">
        <ArchitectureDiagram />
      </div>
      <div className="mt-10 grid gap-6 md:grid-cols-2">
        {SECTIONS.map((section) => (
          <section key={section.title} className="rounded-xl border border-slate-200 bg-surface p-5 shadow-sm">
            <h2 className="font-semibold text-slate-900">{section.title}</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">{section.body}</p>
          </section>
        ))}
      </div>
    </div>
  );
}
