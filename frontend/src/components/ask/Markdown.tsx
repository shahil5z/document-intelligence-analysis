import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Safe Markdown for AI answers: react-markdown builds a React tree from the Markdown AST,
 * raw HTML is never rendered (no rehype-raw, skipHtml), and unsafe URLs are dropped by the
 * default urlTransform. Answer headings start at h3: they sit under the page h1 and each answer's h2.
 */
const components: Components = {
  h1: ({ children }) => <h3 className="mb-2 mt-5 text-lg font-semibold text-fg first:mt-0">{children}</h3>,
  h2: ({ children }) => <h3 className="mb-2 mt-5 text-lg font-semibold text-fg first:mt-0">{children}</h3>,
  h3: ({ children }) => <h4 className="mb-2 mt-4 text-base font-semibold text-fg first:mt-0">{children}</h4>,
  h4: ({ children }) => <h5 className="mb-1.5 mt-4 font-semibold text-fg first:mt-0">{children}</h5>,
  h5: ({ children }) => <h5 className="mb-1.5 mt-4 font-semibold text-fg first:mt-0">{children}</h5>,
  h6: ({ children }) => <h5 className="mb-1.5 mt-4 font-semibold text-fg first:mt-0">{children}</h5>,
  p: ({ children }) => <p className="my-3 first:mt-0 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="my-3 list-disc space-y-1.5 pl-6 marker:text-subtle first:mt-0 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="my-3 list-decimal space-y-1.5 pl-6 marker:text-subtle first:mt-0 last:mb-0">{children}</ol>,
  li: ({ children }) => <li className="pl-1">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-fg">{children}</strong>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-link underline underline-offset-2 hover:no-underline">
      {children}
    </a>
  ),
  blockquote: ({ children }) => <blockquote className="my-3 border-l-2 border-brand-400 pl-4 text-muted">{children}</blockquote>,
  hr: () => <hr className="my-5 border-border" />,
  pre: ({ children }) => (
    <pre className="my-3 overflow-x-auto rounded-lg border border-border bg-surface-2 p-3 font-mono text-[13px] leading-6 [&>code]:bg-transparent [&>code]:p-0">
      {children}
    </pre>
  ),
  code: ({ children }) => <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[0.875em]">{children}</code>,
  table: ({ children }) => (
    <div className="my-3 max-w-full overflow-x-auto rounded-lg border border-border" tabIndex={0} role="region" aria-label="Table">
      <table className="w-full border-collapse text-left text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-surface-2">{children}</thead>,
  th: ({ children }) => <th className="whitespace-nowrap border-b border-border px-3 py-2 font-semibold text-fg">{children}</th>,
  td: ({ children }) => <td className="border-b border-border px-3 py-2 align-top [tr:last-child>&]:border-b-0">{children}</td>,
  img: ({ alt }) => <span className="text-muted">{alt}</span>,
};

export function Markdown({ source }: { source: string }) {
  return (
    <div className="min-w-0 break-words text-[15px] leading-7 text-fg [overflow-wrap:anywhere]" data-testid="answer-markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={components}>
        {source}
      </ReactMarkdown>
    </div>
  );
}
