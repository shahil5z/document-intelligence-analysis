/**
 * Defensive mirror of the backend's strip_citation_markers (app/services/answer_format.py):
 * removes bare [n] / [n][m] / [n, m] citation markers (n <= 100) outside code, with the
 * whitespace before them. Links ([t](u), [1](u)), reference links and definitions,
 * images, escaped brackets, numbered lists and code are left alone.
 */
const FENCE = /^\s*(```|~~~)/;
const RUN = /[ \t]*(?<![\]!\\])((?:\[\s*\d{1,3}(?:\s*,\s*\d{1,3})*\s*\])+)(?![(:[])/g;
const INLINE_CODE = /(`+)(.+?)\1/g;

function stripSegment(text: string): string {
  return text
    .replace(RUN, (whole, run: string) =>
      (run.match(/\d+/g) ?? []).every((n) => Number(n) > 0 && Number(n) <= 100) ? "" : whole,
    )
    .replace(/(?<=\S)[ \t]+([.,;:!?)])/g, "$1")
    .replace(/(?<=\S)[ \t]{2,}(?=\S)/g, " ")
    .replace(/[ \t]+$/, "");
}

function stripLine(line: string): string {
  const spans: string[] = [];
  const held = line.replace(INLINE_CODE, (code) => {
    spans.push(code);
    return `\u0000${spans.length - 1}\u0000`;
  });
  return stripSegment(held).replace(/\u0000(\d+)\u0000/g, (_, i: string) => spans[Number(i)]);
}

export function stripCitationMarkers(text: string): string {
  let fence: string | null = null;
  return text
    .split("\n")
    .map((line) => {
      const match = FENCE.exec(line);
      if (fence !== null) {
        if (match && match[1] === fence) fence = null;
        return line;
      }
      if (match) {
        fence = match[1];
        return line;
      }
      return line.includes("[") ? stripLine(line) : line;
    })
    .join("\n")
    .trim();
}
