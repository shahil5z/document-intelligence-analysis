import { Fragment, type ReactNode } from "react";

/**
 * A deliberately small Markdown subset rendered as React elements (never HTML strings, so
 * model output cannot inject markup): paragraphs, "-"/"*"/"1." lists, ### headings,
 * **bold**, *italic*, `code`, and [n] citation markers turned into chips via `renderCitation`.
 */
export type CitationRenderer = (number: number, key: string) => ReactNode;

const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\*[^*\s][^*\n]*\*|_[^_\s][^_\n]*_|\[\d{1,3}\])/g;

function inline(text: string, renderCitation: CitationRenderer, keyPrefix: string): ReactNode[] {
  return text.split(INLINE).map((part, index) => {
    const key = `${keyPrefix}-${index}`;
    if (!part) return null;
    const citation = /^\[(\d{1,3})\]$/.exec(part);
    if (citation) return renderCitation(Number(citation[1]), key);
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4)
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2)
      return <code key={key}>{part.slice(1, -1)}</code>;
    if ((part.startsWith("*") && part.endsWith("*")) || (part.startsWith("_") && part.endsWith("_")))
      if (part.length > 2) return <em key={key}>{part.slice(1, -1)}</em>;
    return <Fragment key={key}>{part}</Fragment>;
  });
}

type Block =
  | { kind: "p"; lines: string[] }
  | { kind: "ul" | "ol"; items: string[] }
  | { kind: "h"; text: string };

function toBlocks(source: string): Block[] {
  const blocks: Block[] = [];
  for (const raw of source.replace(/\r\n?/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    const last = blocks.at(-1);
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    const ordered = /^\s*\d{1,3}[.)]\s+(.*)$/.exec(line);
    const heading = /^\s*#{1,6}\s+(.*)$/.exec(line);
    if (!line.trim()) {
      blocks.push({ kind: "p", lines: [] });
    } else if (heading) {
      blocks.push({ kind: "h", text: heading[1] });
    } else if (bullet || ordered) {
      const kind = bullet ? "ul" : "ol";
      const text = (bullet ?? ordered)![1];
      if (last && last.kind === kind) last.items.push(text);
      else blocks.push({ kind, items: [text] });
    } else if (last && last.kind === "p") {
      last.lines.push(line.trim());
    } else if (last && (last.kind === "ul" || last.kind === "ol") && /^\s{2,}/.test(raw)) {
      last.items[last.items.length - 1] += ` ${line.trim()}`;
    } else {
      blocks.push({ kind: "p", lines: [line.trim()] });
    }
  }
  return blocks.filter((block) => block.kind !== "p" || block.lines.length > 0);
}

export function Markdown({ source, renderCitation }: { source: string; renderCitation: CitationRenderer }) {
  return (
    <div className="prose-answer">
      {toBlocks(source).map((block, index) => {
        const key = `b${index}`;
        if (block.kind === "h")
          return (
            <p key={key} className="font-semibold text-fg">
              {inline(block.text, renderCitation, key)}
            </p>
          );
        if (block.kind === "p") return <p key={key}>{inline(block.lines.join(" "), renderCitation, key)}</p>;
        const items = block.items.map((item, i) => (
          <li key={`${key}-${i}`}>{inline(item, renderCitation, `${key}-${i}`)}</li>
        ));
        return block.kind === "ol" ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>;
      })}
    </div>
  );
}
