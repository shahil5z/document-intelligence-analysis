import { DemoButton } from "@/components/demo/DemoButton";
import { FullLogo } from "@/components/Logo";
import { ButtonLink } from "@/components/ui";

const STEPS = [
  { title: "Upload", body: "Add lecture notes, papers or assignment briefs (PDF, Word .docx or .txt, up to 10 MB)." },
  { title: "Search", body: "Find a topic by meaning or by exact words, across all your files." },
  { title: "Ask", body: "Get a short answer with numbered sources that show the exact page." },
];

const FEATURES = [
  {
    title: "Answers you can check",
    body: "Every answer links to the passage it came from. If your files don't cover a question, it says so.",
    icon: "M8 10h8M8 14h5M5 4h14a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1h-6l-4 3v-3H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z",
  },
  {
    title: "Question ideas for each file",
    body: "After upload you get a few suggested questions based on that file, so you know where to start.",
    icon: "M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.4 1 1.1 1 1.8V16h5v-.3c0-.7.4-1.4 1-1.8A6 6 0 0 0 12 3Z",
  },
  {
    title: "Your files stay yours",
    body: "Only your account can see your files, searches and answers. You can delete a file at any time.",
    icon: "M12 3 4.5 6v5.5c0 4.4 3.2 8.4 7.5 9.5 4.3-1.1 7.5-5.1 7.5-9.5V6L12 3Z",
  },
];

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d={d} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Chip({ n }: { n: string }) {
  return (
    <span className="mx-1 rounded-md bg-brand-50 px-1.5 py-0.5 text-xs font-semibold text-brand-700 ring-1 ring-inset ring-brand-200">{n}</span>
  );
}

function AnswerPreview() {
  return (
    <figure className="relative rounded-2xl border border-border bg-surface p-5 shadow-pop sm:p-6" aria-label="Example of an answer with sources">
      <div className="flex items-center gap-2 text-xs text-subtle">
        <span className="h-2 w-2 rounded-full bg-emerald-500" aria-hidden="true" />
        Example · biology-lecture-04.pdf
      </div>
      <p className="mt-4 text-sm font-medium text-fg">What is the difference between mitosis and meiosis?</p>
      <div className="mt-3 rounded-xl bg-surface-2 p-4 text-sm leading-6 text-fg">
        Mitosis makes <strong>two identical cells</strong> for growth and repair
        <Chip n="1" />. Meiosis makes <strong>four cells with half the chromosomes</strong>, used for
        reproduction
        <Chip n="2" />.
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {[
          ["1", "page 3", "…mitosis produces two genetically identical daughter cells…"],
          ["2", "page 5", "…meiosis results in four haploid cells…"],
        ].map(([n, page, text]) => (
          <div key={n} className="rounded-lg border border-border p-3 text-xs">
            <p className="font-semibold text-fg">
              [{n}] biology-lecture-04.pdf <span className="font-normal text-subtle">· {page}</span>
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
              Study with your own material. <span className="text-gradient">Get answers you can check.</span>
            </h1>
            <p className="mt-5 max-w-xl text-lg leading-relaxed text-muted">
              Upload your notes or papers, search them, and ask questions with answers that
              point back to the exact page.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <DemoButton size="lg" variant="primary" />
              <ButtonLink href="/register" size="lg" variant="secondary">
                Create free account
              </ButtonLink>
            </div>
            <p className="mt-4 text-xs text-subtle">
              Demo: no sign-up, 1 PDF up to 5 MB, 3 questions, deleted after 24 hours.
            </p>
          </div>
          <AnswerPreview />
        </div>
      </section>

      <section id="how-it-works" aria-labelledby="how-heading" className="scroll-mt-20 border-y border-border bg-surface">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <h2 id="how-heading" className="text-2xl font-semibold tracking-tight text-fg sm:text-3xl">
            How it works
          </h2>
          <ol className="mt-8 grid gap-6 md:grid-cols-3">
            {STEPS.map((step, index) => (
              <li key={step.title} className="rounded-xl border border-border bg-background p-6">
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

      <section aria-label="Features" className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <div className="grid gap-4 md:grid-cols-3">
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

      <section className="mx-auto max-w-6xl px-4 pb-16 sm:px-6">
        <div className="bg-brand-gradient relative overflow-hidden rounded-2xl px-6 py-12 text-center text-white sm:px-12">
          <h2 className="text-2xl font-semibold sm:text-3xl">Try it with your own notes</h2>
          <p className="mx-auto mt-3 max-w-xl text-sm text-white/90">
            Start the demo, or create a free account to keep your files.
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
