/**
 * What differs between two answers, as text a person reads.
 *
 * The same contract as the backend's `services/textdiff.py` (which `crucible
 * diff` and the MCP `diff_answers` tool use); change both together:
 *
 * - An answer is cut into units. Prose becomes sentences (a paragraph break,
 *   heading, list item, quote or table row always starts a new one; a
 *   sentence ends at `.`/`!`/`?`, optional closing quotes or brackets, then
 *   whitespace before anything but a lowercase letter; `。！？` always end
 *   one). Markdown formatting is stripped first (emphasis, links, inline
 *   code, heading and list markers): the diff is of the text, not of how it
 *   is set. Fenced code blocks become lines (blank ones dropped); JSON (a code
 *   block that parses as JSON, or a whole answer that does) is pretty-printed
 *   with sorted keys first, so key order and whitespace are not changes.
 * - Units are aligned with a longest common subsequence. A run of units only
 *   in A next to a run only in B is paired position by position: a pair of
 *   the same group whose words overlap enough (`PAIR_SIMILARITY`) is one
 *   *changed* unit, diffed word by word; the rest stay *only in A* / *only
 *   in B*.
 */

export type UnitKind = "sentence" | "code" | "json";

export interface Unit {
  kind: UnitKind;
  text: string;
}

export interface Segment {
  op: "same" | "removed" | "added";
  text: string;
}

export type DiffRow =
  | { op: "same" | "only_a" | "only_b"; kind: UnitKind; text: string }
  | {
      op: "changed";
      kind: UnitKind;
      a: string;
      b: string;
      segments: Segment[];
    };

export interface DiffCounts {
  same: number;
  changed: number;
  only_a: number;
  only_b: number;
}

export interface DiffSummary {
  sentences: DiffCounts;
  lines: DiffCounts;
}

/** One answer as the diff view shows it. */
export interface DiffSide {
  /** Display name: never a raw model id. */
  label: string;
  /** The raw id, for a tooltip. */
  model?: string;
  text: string;
}

export interface AnswerDiff {
  rows: DiffRow[];
  summary: DiffSummary;
  /** Every unit is the same in both (also true for two empty answers). */
  identical: boolean;
}

/** Word overlap (Dice) from which two units in the same spot count as one changed unit. */
export const PAIR_SIMILARITY = 0.3;

/** Beyond this many cells the unit LCS gives up and treats the middle as one changed run. */
const MAX_CELLS = 4_000_000;

const FENCE = /^\s*(`{3,}|~{3,})/;
const HEADING = /^\s{0,3}#{1,6}\s+/;
const LIST = /^\s*(?:[-*+]|\d+[.)])\s+/;
const QUOTE = /^\s*>\s?/;
const RULE = /^\s*(?:[-*_]\s*){3,}$/;
const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const TOKEN = /\s+|[\p{L}\p{N}_'-]+|[^\p{L}\p{N}_'\s-]/gu;
const ENDERS = ".!?";
const CJK_ENDERS = "。！？";
const CLOSERS = "\"'”’)]";

// ─── Cutting an answer into units ───────────────────────────────

function stripInline(text: string): string {
  return text
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/`+([^`]*)`+/g, "$1")
    .replace(/<\/?[A-Za-z][^>]*>/g, " ")
    .replaceAll("**", "")
    .replaceAll("~~", "")
    .replace(/(^|[^\p{L}\p{N}_])__([^_\n]+)__(?=[^\p{L}\p{N}_]|$)/gu, "$1$2")
    .replace(/(^|[^\p{L}\p{N}_*])\*([^*\n]+)\*(?=[^\p{L}\p{N}_*]|$)/gu, "$1$2")
    .replace(/(^|[^\p{L}\p{N}_])_([^_\n]+)_(?=[^\p{L}\p{N}_]|$)/gu, "$1$2")
    .replace(/\s+/g, " ")
    .trim();
}

const isSpace = (ch: string) => /\s/.test(ch);

/** A paragraph's sentences, as described at the top of this file. */
export function splitSentences(text: string): string[] {
  const out: string[] = [];
  let start = 0;
  let i = 0;
  const n = text.length;
  while (i < n) {
    const ch = text[i];
    if (CJK_ENDERS.includes(ch)) {
      out.push(text.slice(start, i + 1));
      start = i + 1;
    } else if (ENDERS.includes(ch)) {
      let j = i + 1;
      while (j < n && (ENDERS.includes(text[j]) || CLOSERS.includes(text[j])))
        j++;
      let k = j;
      while (k < n && isSpace(text[k])) k++;
      if (k > j && (k === n || !(text[k] >= "a" && text[k] <= "z"))) {
        out.push(text.slice(start, j));
        start = k;
        i = k;
        continue;
      }
    }
    i++;
  }
  out.push(text.slice(start));
  return out.map((s) => s.trim()).filter(Boolean);
}

function parseJson(text: string): { value: unknown } | null {
  const stripped = text.trim();
  if (!stripped || !"{[".includes(stripped[0])) return null;
  try {
    return { value: JSON.parse(stripped) };
  } catch {
    return null;
  }
}

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    return Object.fromEntries(
      Object.keys(obj)
        .sort()
        .map((k) => [k, sortKeys(obj[k])]),
    );
  }
  return value;
}

function jsonLines(value: unknown): Unit[] {
  return JSON.stringify(sortKeys(value), null, 2)
    .split("\n")
    .map((text) => ({ kind: "json", text }));
}

function codeLines(body: string[]): Unit[] {
  const parsed = parseJson(body.join("\n"));
  if (parsed) return jsonLines(parsed.value);
  return body
    .filter((l) => l.trim())
    .map((l) => ({ kind: "code", text: l.trimEnd() }));
}

/** The answer as units: sentences, code lines, JSON lines. */
export function units(text: string): Unit[] {
  const source = (text ?? "").replace(/\r\n/g, "\n");
  const whole = parseJson(source);
  if (whole) return jsonLines(whole.value);

  const out: Unit[] = [];
  let paragraph: string[] = [];
  const flush = () => {
    if (paragraph.length) {
      for (const s of splitSentences(stripInline(paragraph.join(" "))))
        out.push({ kind: "sentence", text: s });
      paragraph = [];
    }
  };

  const lines = source.split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const fence = FENCE.exec(line);
    if (fence) {
      flush();
      const marker = fence[1];
      const closing = marker[0].repeat(marker.length);
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith(closing)) {
        body.push(lines[i]);
        i++;
      }
      out.push(...codeLines(body));
      i++;
      continue;
    }
    if (!line.trim() || RULE.test(line)) {
      flush();
    } else if (line.trimStart().startsWith("|")) {
      flush();
      if (!TABLE_SEP.test(line)) {
        const row = line
          .trim()
          .replace(/^\|+|\|+$/g, "")
          .split("|")
          .map(stripInline)
          .filter(Boolean)
          .join(" | ");
        if (row) out.push({ kind: "sentence", text: row });
      }
    } else if (HEADING.test(line)) {
      flush();
      paragraph.push(line.replace(HEADING, ""));
      flush(); // a heading is never continued by the next line
    } else if (LIST.test(line) || QUOTE.test(line)) {
      flush();
      paragraph.push(line.replace(QUOTE, "").replace(LIST, ""));
    } else {
      paragraph.push(line);
    }
    i++;
  }
  flush();
  return out;
}

// ─── Alignment ───────────────────────────────────────────────────

interface Block<T> {
  equal: boolean;
  a: T[];
  b: T[];
}

/**
 * The two sequences as alternating runs: equal, or a change (what only A has
 * next to what only B has). A longest common subsequence after trimming the
 * shared start and end; past `maxCells` the middle is one change.
 */
export function align<T>(
  a: T[],
  b: T[],
  key: (x: T) => string,
  maxCells = MAX_CELLS,
): Block<T>[] {
  const ka = a.map(key);
  const kb = b.map(key);
  let pre = 0;
  while (pre < a.length && pre < b.length && ka[pre] === kb[pre]) pre++;
  let suf = 0;
  while (
    suf < a.length - pre &&
    suf < b.length - pre &&
    ka[a.length - 1 - suf] === kb[b.length - 1 - suf]
  )
    suf++;

  const ops: ("e" | "d" | "i")[] = [];
  const n = a.length - pre - suf;
  const m = b.length - pre - suf;
  if (n * m > maxCells) {
    for (let x = 0; x < n; x++) ops.push("d");
    for (let y = 0; y < m; y++) ops.push("i");
  } else {
    const w = m + 1;
    const table = new Uint32Array((n + 1) * w);
    for (let x = n - 1; x >= 0; x--) {
      for (let y = m - 1; y >= 0; y--) {
        table[x * w + y] =
          ka[pre + x] === kb[pre + y]
            ? table[(x + 1) * w + y + 1] + 1
            : Math.max(table[(x + 1) * w + y], table[x * w + y + 1]);
      }
    }
    let x = 0;
    let y = 0;
    while (x < n || y < m) {
      if (x < n && y < m && ka[pre + x] === kb[pre + y]) {
        ops.push("e");
        x++;
        y++;
      } else if (
        y >= m ||
        (x < n && table[(x + 1) * w + y] >= table[x * w + y + 1])
      ) {
        ops.push("d");
        x++;
      } else {
        ops.push("i");
        y++;
      }
    }
  }

  const blocks: Block<T>[] = [];
  const push = (
    equal: boolean,
    from: "a" | "b" | "both",
    ia: number,
    ib: number,
  ) => {
    let last = blocks[blocks.length - 1];
    if (!last || last.equal !== equal) {
      last = { equal, a: [], b: [] };
      blocks.push(last);
    }
    if (from !== "b") last.a.push(a[ia]);
    if (from !== "a") last.b.push(b[ib]);
  };
  for (let p = 0; p < pre; p++) push(true, "both", p, p);
  let ia = pre;
  let ib = pre;
  for (const op of ops) {
    if (op === "e") push(true, "both", ia++, ib++);
    else if (op === "d") push(false, "a", ia++, ib);
    else push(false, "b", ia, ib++);
  }
  for (let s = 0; s < suf; s++) push(true, "both", ia++, ib++);
  return blocks;
}

// ─── Words ───────────────────────────────────────────────────────

export function tokens(text: string): string[] {
  return text.match(TOKEN) ?? [];
}

/** The text's words, lowercased: punctuation and spaces don't make two sentences alike. */
const words = (text: string) =>
  tokens(text)
    .filter((t) => /[\p{L}\p{N}]/u.test(t))
    .map((t) => t.toLowerCase());

/** Dice overlap of the two texts' words (case-insensitive). */
export function similarity(a: string, b: string): number {
  const wa = words(a);
  const wb = words(b);
  if (!wa.length && !wb.length) return 1;
  const counts = new Map<string, number>();
  for (const w of wa) counts.set(w, (counts.get(w) ?? 0) + 1);
  let common = 0;
  for (const w of wb) {
    const c = counts.get(w) ?? 0;
    if (c > 0) {
      counts.set(w, c - 1);
      common++;
    }
  }
  return (2 * common) / (wa.length + wb.length);
}

function pushSegment(segments: Segment[], op: Segment["op"], text: string) {
  if (!text) return;
  const last = segments[segments.length - 1];
  if (last && last.op === op) last.text += text;
  else segments.push({ op, text });
}

/** Segments: A reads as same + removed, B as same + added. */
export function wordDiff(a: string, b: string): Segment[] {
  const segments: Segment[] = [];
  for (const block of align(tokens(a), tokens(b), (t) => t, 250_000)) {
    if (block.equal) pushSegment(segments, "same", block.a.join(""));
    else {
      pushSegment(segments, "removed", block.a.join(""));
      pushSegment(segments, "added", block.b.join(""));
    }
  }
  return segments;
}

// ─── Two answers ─────────────────────────────────────────────────

const group = (kind: UnitKind): keyof DiffSummary =>
  kind === "sentence" ? "sentences" : "lines";

export function diffAnswers(a: string, b: string): AnswerDiff {
  const rows: DiffRow[] = [];
  for (const block of align(
    units(a),
    units(b),
    (u) => `${u.kind}\u0000${u.text}`,
  )) {
    if (block.equal) {
      for (const u of block.a)
        rows.push({ op: "same", kind: u.kind, text: u.text });
      continue;
    }
    const paired = Math.min(block.a.length, block.b.length);
    for (let p = 0; p < paired; p++) {
      const ua = block.a[p];
      const ub = block.b[p];
      if (
        group(ua.kind) === group(ub.kind) &&
        similarity(ua.text, ub.text) >= PAIR_SIMILARITY
      ) {
        rows.push({
          op: "changed",
          kind: ua.kind,
          a: ua.text,
          b: ub.text,
          segments: wordDiff(ua.text, ub.text),
        });
      } else {
        rows.push({ op: "only_a", kind: ua.kind, text: ua.text });
        rows.push({ op: "only_b", kind: ub.kind, text: ub.text });
      }
    }
    for (const u of block.a.slice(paired))
      rows.push({ op: "only_a", kind: u.kind, text: u.text });
    for (const u of block.b.slice(paired))
      rows.push({ op: "only_b", kind: u.kind, text: u.text });
  }
  const empty = (): DiffCounts => ({
    same: 0,
    changed: 0,
    only_a: 0,
    only_b: 0,
  });
  const summary: DiffSummary = { sentences: empty(), lines: empty() };
  for (const row of rows) summary[group(row.kind)][row.op]++;
  return { rows, summary, identical: rows.every((r) => r.op === "same") };
}

/** "12 sentences the same, 3 changed, 2 only in A, 1 only in B" (and the same for code lines). */
export function diffSummaryText(summary: DiffSummary): string {
  const parts: string[] = [];
  const groups = [
    ["sentences", "sentence", "sentences"],
    ["lines", "line of code", "lines of code"],
  ] as const;
  for (const [key, one, many] of groups) {
    const c = summary[key];
    if (!c.same && !c.changed && !c.only_a && !c.only_b) continue;
    const bits = [`${c.same} ${c.same === 1 ? one : many} the same`];
    if (c.changed) bits.push(`${c.changed} changed`);
    if (c.only_a) bits.push(`${c.only_a} only in A`);
    if (c.only_b) bits.push(`${c.only_b} only in B`);
    parts.push(bits.join(", "));
  }
  if (!parts.length) return "Both answers are empty.";
  const differs = Object.values(summary).some(
    (c: DiffCounts) => c.changed || c.only_a || c.only_b,
  );
  return differs ? parts.join("; ") : `No differences: ${parts.join("; ")}.`;
}
