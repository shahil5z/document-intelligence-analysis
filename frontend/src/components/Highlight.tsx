import { Fragment } from "react";

const STOPWORDS = new Set(
  "a an and are as at be by can do does for from has have how i in is it its of on or that the their this to was what when where which who why will with you your".split(" "),
);

/** Distinct query words worth highlighting (3+ chars, not stopwords), longest first. */
export function highlightTerms(query: string): string[] {
  const words = query.toLowerCase().match(/[\p{L}\p{N}]{3,}/gu) ?? [];
  return [...new Set(words.filter((w) => !STOPWORDS.has(w)))].sort((a, b) => b.length - a.length).slice(0, 12);
}

function escape(term: string): string {
  return term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Wrap whole-word-prefix matches of `terms` in <mark>; text stays text (no HTML injection). */
export function Highlight({ text, terms }: { text: string; terms: string[] }) {
  if (terms.length === 0) return <>{text}</>;
  const pattern = new RegExp(`(?<![\\p{L}\\p{N}])(${terms.map(escape).join("|")})`, "giu");
  const parts = text.split(pattern);
  return (
    <>
      {parts.map((part, index) =>
        index % 2 === 1 ? (
          <mark key={index} className="hl">
            {part}
          </mark>
        ) : (
          <Fragment key={index}>{part}</Fragment>
        ),
      )}
    </>
  );
}
