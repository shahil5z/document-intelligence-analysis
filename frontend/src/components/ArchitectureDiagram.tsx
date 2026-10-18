function Box({ title, detail, tone = "slate" }: { title: string; detail: string; tone?: "brand" | "slate" | "emerald" | "amber" }) {
  const tones = {
    brand: "border-brand-200 bg-brand-50",
    slate: "border-slate-200 bg-white",
    emerald: "border-emerald-200 bg-emerald-50",
    amber: "border-amber-200 bg-amber-50",
  } as const;
  return (
    <div className={`rounded-lg border p-3 text-center ${tones[tone]}`}>
      <p className="text-sm font-semibold text-slate-900">{title}</p>
      <p className="mt-0.5 text-xs text-slate-600">{detail}</p>
    </div>
  );
}

function Arrow({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center py-1 text-slate-400" aria-hidden="true">
      <span className="h-4 w-px bg-slate-300" />
      {label ? <span className="text-[11px] text-slate-500">{label}</span> : null}
      <svg viewBox="0 0 10 6" className="h-2 w-3 fill-slate-400">
        <path d="M0 0h10L5 6z" />
      </svg>
    </div>
  );
}

/** Text-first diagram: readable by screen readers and on small screens. */
export function ArchitectureDiagram() {
  return (
    <figure aria-labelledby="arch-caption" className="rounded-xl border border-slate-200 bg-slate-50 p-4 sm:p-6">
      <div className="mx-auto max-w-3xl">
        <Box title="Browser" detail="Next.js UI (React, Tailwind)" tone="brand" />
        <div className="grid grid-cols-2 gap-3">
          <Arrow label="pages + /api/* (session cookie)" />
          <Arrow label="file upload (upload-only token)" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Box title="Next.js server (Vercel)" detail="Route handlers: HttpOnly cookie, CSRF checks, API proxy" />
          <Box title="Caddy (HTTPS)" detail="TLS, body limit, /metrics blocked" />
        </div>
        <Arrow label="HTTPS (Bearer token)" />
        <Box title="FastAPI API (gunicorn + uvicorn)" detail="Auth, documents, search, ask · per-user isolation · rate limits" tone="brand" />
        <div className="grid grid-cols-3 gap-3">
          <Arrow />
          <Arrow label="jobs" />
          <Arrow />
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Box title="PostgreSQL + pgvector" detail="Users, documents, chunks, 384-d embeddings, full-text index" tone="emerald" />
          <Box title="Redis" detail="Celery queue, rate-limit counters" tone="amber" />
          <Box title="File storage" detail="Local volume or S3-compatible (OCI Object Storage)" />
        </div>
        <Arrow label="Celery task" />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Box title="Worker" detail="Extract (PDF/DOCX/TXT) → chunk → embed (bge-small) → index" />
          <Box title="LLM (OpenAI-compatible)" detail="Only for /ask; answers limited to retrieved passages" />
        </div>
      </div>
      <figcaption id="arch-caption" className="mt-4 text-center text-xs text-slate-500">
        Request flow from the browser to storage, background processing and the optional LLM.
      </figcaption>
    </figure>
  );
}
