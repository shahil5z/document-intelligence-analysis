import { DemoButton } from "@/components/demo/DemoButton";
import { ButtonLink } from "@/components/ui";
import { GITHUB_URL } from "@/lib/brand";

const CAPABILITIES = [
  {
    title: "Document processing",
    body: "PDF, DOCX and TXT files are extracted page by page, normalised and split into token-aware chunks that keep page numbers and character offsets.",
  },
  {
    title: "Hybrid search",
    body: "Each query runs a pgvector similarity search and a Postgres full-text search; the two ranked lists are merged with Reciprocal Rank Fusion.",
  },
  {
    title: "Cited RAG answers",
    body: "Retrieved passages are sent to the language model with numbered references. Citations that do not match a retrieved passage are removed.",
  },
  {
    title: "Background processing",
    body: "Uploads return immediately. A Celery worker extracts, chunks and embeds the document, and the interface tracks its status until it is ready or failed.",
  },
];

const STEPS = [
  { n: "01", title: "Upload", body: "Add a PDF, DOCX or TXT file (up to 10 MB with an account). Processing runs in the background." },
  { n: "02", title: "Search", body: "Search across your documents by meaning, by exact terms, or both. Results show the passage and its page." },
  { n: "03", title: "Ask", body: "Ask a question in plain language. The answer is generated only from passages retrieved from your documents." },
  { n: "04", title: "Verify", body: "Each claim carries a numbered citation. Open it to read the exact passage, file and page it came from." },
];

const PIPELINE: { label: string; detail: string }[] = [
  { label: "Document", detail: "PDF · DOCX · TXT" },
  { label: "Extraction & chunking", detail: "pypdf, python-docx, token-aware chunks" },
  { label: "Embeddings", detail: "bge-small-en-v1.5 on ONNX Runtime, 384-d" },
  { label: "Postgres + pgvector", detail: "HNSW vector index, GIN full-text index" },
  { label: "Hybrid retrieval", detail: "vector + keyword, Reciprocal Rank Fusion" },
  { label: "Passages", detail: "top passages with page and offsets" },
  { label: "LLM", detail: "OpenAI gpt-4o-mini, structured output" },
  { label: "Cited answer", detail: "citations checked against retrieved passages" },
];

const STACK: { group: string; items: string[] }[] = [
  { group: "Backend", items: ["Python", "FastAPI", "SQLAlchemy 2", "Alembic", "Pydantic", "Gunicorn / Uvicorn", "Argon2 password hashing", "JWT"] },
  { group: "Data / Retrieval", items: ["PostgreSQL 16", "pgvector (HNSW)", "Postgres full-text search (GIN)", "Reciprocal Rank Fusion", "Redis"] },
  { group: "AI", items: ["ONNX Runtime", "BAAI bge-small-en-v1.5", "OpenAI gpt-4o-mini", "Retrieval-augmented generation"] },
  { group: "Infrastructure", items: ["Celery (worker + beat)", "Docker Compose", "Caddy (HTTPS)", "Oracle Cloud VM", "Vercel"] },
  { group: "Frontend", items: ["Next.js 16", "React 19", "TypeScript", "Tailwind CSS 4", "Playwright"] },
];

const DECISIONS = [
  {
    title: "Why hybrid retrieval",
    body: "Dense embeddings find passages that use different words for the same idea; full-text search reliably finds exact names, codes and numbers. Fusing both by rank avoids having to calibrate two incompatible score scales.",
  },
  {
    title: "Why asynchronous processing",
    body: "Extraction and embedding can take seconds to minutes. Running them in a Celery worker keeps the upload request fast, allows retries for transient failures, and gives each document an explicit status.",
  },
  {
    title: "Why ONNX Runtime",
    body: "The backend runs on a small 1 GB VM. Serving the embedding model with ONNX Runtime avoids a full deep-learning framework, and only the API process loads it; the worker sends chunks to an internal endpoint instead of holding a second copy.",
  },
  {
    title: "Why citations",
    body: "A generated answer is only useful if it can be checked. Every answer references numbered passages, references that do not match a retrieved passage are dropped, and an answer with no valid citation is withheld.",
  },
];

const PRIVACY = [
  "Documents and everything derived from them are scoped to your account; other accounts cannot access them.",
  "You can delete a document at any time; this removes the file, its passages and its embeddings.",
  "No analytics or tracking scripts. A single HttpOnly cookie keeps you signed in.",
  "When you ask a question, the question and the retrieved passages are sent to OpenAI. After an upload, the beginning of the document text is sent once to suggest questions.",
];

function SectionHeading({ id, eyebrow, title, intro }: { id: string; eyebrow: string; title: string; intro?: string }) {
  return (
    <div className="max-w-2xl">
      <p className="font-mono text-xs uppercase tracking-[0.14em] text-subtle">{eyebrow}</p>
      <h2 id={id} className="mt-3 text-2xl font-semibold tracking-tight text-fg sm:text-3xl">
        {title}
      </h2>
      {intro ? <p className="mt-3 leading-relaxed text-muted">{intro}</p> : null}
    </div>
  );
}

function Cite({ n }: { n: number }) {
  return (
    <span className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-md bg-brand-50 px-1 align-text-top text-[11px] font-semibold text-brand-700 ring-1 ring-inset ring-brand-200">
      {n}
    </span>
  );
}

function ExampleAnswer() {
  const sources = [
    { n: 1, file: "annual-report-2025.pdf", page: "page 2", text: "The report finds that operating costs rose 8% year over year, driven mainly by energy and logistics…" },
    { n: 2, file: "annual-report-2025.pdf", page: "pages 6-7", text: "We recommend consolidating regional warehouses and renegotiating long-term energy contracts…" },
  ];
  return (
    <figure className="rounded-xl border border-border bg-surface p-5 sm:p-6" aria-labelledby="example-caption">
      <figcaption id="example-caption" className="flex items-center justify-between gap-3 text-xs text-subtle">
        <span className="font-mono uppercase tracking-[0.14em]">Example answer</span>
        <span>Illustrative content, not real output</span>
      </figcaption>
      <p className="mt-5 text-sm font-medium text-fg">What are the main findings of this document?</p>
      <p className="mt-3 text-[15px] leading-7 text-fg">
        The document reports that operating costs increased year over year, mainly because of
        energy and logistics expenses <Cite n={1} />. It recommends consolidating regional
        warehouses and renegotiating energy contracts to reduce them <Cite n={2} />.
      </p>
      <div className="mt-5 border-t border-border pt-4">
        <p className="mb-2 text-sm font-semibold text-fg">Sources</p>
        <ol className="space-y-2">
          {sources.map((s) => (
            <li key={s.n} className="rounded-lg border border-border bg-surface-2 p-3">
              <p className="flex flex-wrap items-center gap-x-2 text-sm font-medium text-fg">
                <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-md bg-primary px-1 text-[11px] font-semibold text-white">
                  {s.n}
                </span>
                <span className="text-link">{s.file}</span>
                <span className="font-normal text-subtle">{s.page}</span>
              </p>
              <p className="mt-1.5 text-sm text-muted">{s.text}</p>
            </li>
          ))}
        </ol>
      </div>
    </figure>
  );
}

export default function LandingPage() {
  return (
    <>
      {/* A. Hero */}
      <section className="mx-auto max-w-6xl px-4 pb-16 pt-14 sm:px-6 sm:pt-20 lg:pb-24">
        <h1 className="max-w-3xl text-4xl font-semibold tracking-tight text-fg sm:text-5xl lg:text-6xl">
          Document Intelligence &amp; Analysis
        </h1>
        <p className="mt-6 max-w-2xl text-lg leading-relaxed text-fg sm:text-xl">
          Search, understand, and ask questions about your documents with cited AI answers.
        </p>
        <p className="mt-4 max-w-2xl leading-relaxed text-muted">
          Documents are extracted and chunked in a background worker, embedded with an ONNX model,
          and indexed in Postgres with pgvector. Questions are answered with retrieval-augmented
          generation over hybrid (vector + full-text) search, and every answer cites its sources.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <DemoButton size="lg" variant="primary" label="Try the Demo" />
          <ButtonLink href={GITHUB_URL} size="lg" variant="secondary" rel="noopener noreferrer">
            View on GitHub
          </ButtonLink>
          <ButtonLink href="/#how-it-works" size="lg" variant="ghost">
            How it works
          </ButtonLink>
        </div>
      </section>

      {/* B. Capabilities */}
      <section aria-labelledby="capabilities-heading" className="border-t border-border">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <SectionHeading id="capabilities-heading" eyebrow="Capabilities" title="What the system does" />
          <dl className="mt-10 grid gap-x-10 gap-y-8 sm:grid-cols-2">
            {CAPABILITIES.map((c) => (
              <div key={c.title} className="border-l-2 border-border pl-5">
                <dt className="font-semibold text-fg">{c.title}</dt>
                <dd className="mt-2 text-sm leading-relaxed text-muted">{c.body}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {/* C + D. Demo and example */}
      <section aria-labelledby="demo-heading" className="border-t border-border">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:px-6 lg:grid-cols-[1fr_1.2fr] lg:items-start">
          <div>
            <SectionHeading
              id="demo-heading"
              eyebrow="Live demo"
              title="Try it without an account"
              intro="The demo creates a temporary, isolated account. Limits are enforced by the backend."
            />
            <ul className="mt-6 divide-y divide-border rounded-xl border border-border text-sm">
              <li className="flex justify-between gap-4 px-4 py-3"><span className="text-muted">Documents</span><span className="font-medium text-fg">1 PDF</span></li>
              <li className="flex justify-between gap-4 px-4 py-3"><span className="text-muted">Maximum file size</span><span className="font-medium text-fg">5 MB</span></li>
              <li className="flex justify-between gap-4 px-4 py-3"><span className="text-muted">AI questions</span><span className="font-medium text-fg">3</span></li>
              <li className="flex justify-between gap-4 px-4 py-3"><span className="text-muted">Data retention</span><span className="font-medium text-fg">Deleted after 24 hours</span></li>
            </ul>
            <div className="mt-6">
              <DemoButton size="lg" variant="primary" label="Try the Demo" />
            </div>
          </div>
          <ExampleAnswer />
        </div>
      </section>

      {/* E. How it works */}
      <section id="how-it-works" aria-labelledby="how-heading" className="scroll-mt-20 border-t border-border bg-surface">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <SectionHeading id="how-heading" eyebrow="Workflow" title="How it works" />
          <ol className="mt-10 grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((s) => (
              <li key={s.n}>
                <span className="font-mono text-sm text-subtle" aria-hidden="true">{s.n}</span>
                <h3 className="mt-2 font-semibold text-fg">{s.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{s.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* F. Architecture */}
      <section id="architecture" aria-labelledby="arch-heading" className="scroll-mt-20 border-t border-border">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <SectionHeading
            id="arch-heading"
            eyebrow="Architecture"
            title="Built as an AI retrieval system"
            intro="The path from an uploaded file to a cited answer, as implemented in the backend."
          />
          <ol className="mt-10 grid gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
            {PIPELINE.map((step, i) => (
              <li key={step.label} className="bg-background p-5">
                <span className="font-mono text-xs text-subtle">{String(i + 1).padStart(2, "0")}</span>
                <p className="mt-2 font-medium text-fg">{step.label}</p>
                <p className="mt-1 text-sm text-muted">{step.detail}</p>
              </li>
            ))}
          </ol>
          <p className="mt-6 max-w-3xl text-sm leading-relaxed text-muted">
            <span className="font-medium text-fg">Asynchronous processing:</span> steps 02 to 04 run in a
            Celery worker with Redis as the broker. The worker sends chunks to a private embedding
            endpoint in the API, so the model is loaded once. A scheduled task removes expired demo
            accounts and re-queues stalled jobs.
          </p>
        </div>
      </section>

      {/* G. Tech stack */}
      <section aria-labelledby="stack-heading" className="border-t border-border bg-surface">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <SectionHeading id="stack-heading" eyebrow="Stack" title="Technologies used" />
          <dl className="mt-10 grid gap-8 sm:grid-cols-2 lg:grid-cols-5">
            {STACK.map((g) => (
              <div key={g.group}>
                <dt className="text-sm font-semibold text-fg">{g.group}</dt>
                <dd className="mt-3">
                  <ul className="space-y-1.5 text-sm text-muted">
                    {g.items.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {/* H. Engineering decisions */}
      <section aria-labelledby="decisions-heading" className="border-t border-border">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <SectionHeading id="decisions-heading" eyebrow="Design" title="Engineering decisions" />
          <div className="mt-10 grid gap-4 md:grid-cols-2">
            {DECISIONS.map((d) => (
              <article key={d.title} className="rounded-xl border border-border p-6">
                <h3 className="font-semibold text-fg">{d.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{d.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* I + J. Privacy and limitations */}
      <section aria-labelledby="privacy-heading" className="border-t border-border">
        <div className="mx-auto grid max-w-6xl gap-12 px-4 py-16 sm:px-6 lg:grid-cols-2">
          <div>
            <SectionHeading id="privacy-heading" eyebrow="Privacy" title="How your data is handled" />
            <ul className="mt-6 space-y-3 text-sm leading-relaxed text-muted">
              {PRIVACY.map((p) => (
                <li key={p} className="flex gap-3">
                  <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-subtle" aria-hidden="true" />
                  <span>{p}</span>
                </li>
              ))}
            </ul>
            <a href="/privacy" className="mt-4 inline-block text-sm text-link hover:underline">Read the privacy policy</a>
          </div>
          <div>
            <SectionHeading id="limits-heading" eyebrow="Limitations" title="What to keep in mind" />
            <ul className="mt-6 space-y-3 text-sm leading-relaxed text-muted">
              <li className="flex gap-3"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-subtle" aria-hidden="true" /><span>Answers are generated by a language model and can be wrong or incomplete. Check the cited passages.</span></li>
              <li className="flex gap-3"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-subtle" aria-hidden="true" /><span>Extraction quality depends on the document. Scanned PDFs without a text layer are not supported (there is no OCR), and complex tables or multi-column layouts may be extracted imperfectly.</span></li>
              <li className="flex gap-3"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-subtle" aria-hidden="true" /><span>The embedding model is English-focused, so semantic search works best on English text.</span></li>
            </ul>
          </div>
        </div>
      </section>

      {/* K. About */}
      <section aria-labelledby="about-heading" className="border-t border-border bg-surface">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <SectionHeading id="about-heading" eyebrow="About" title="About the system" />
          <p className="mt-6 max-w-3xl leading-relaxed text-muted">
            Document Intelligence &amp; Analysis explores the engineering behind a retrieval-augmented
            generation system end to end: reliable text extraction with page provenance, combining
            dense and lexical retrieval, keeping generated answers grounded in verifiable citations,
            and running asynchronous document processing with an embedding model on a single small
            cloud VM. The backend exposes a REST API with per-account isolation, rate
            limiting and an automated test suite; the frontend is a Next.js application that keeps
            the session token server-side.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <DemoButton size="lg" variant="primary" label="Try the Demo" />
            <ButtonLink href={GITHUB_URL} size="lg" variant="secondary" rel="noopener noreferrer">
              View on GitHub
            </ButtonLink>
          </div>
        </div>
      </section>
    </>
  );
}
