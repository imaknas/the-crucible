"""What differs between two answers, as text a person reads.

Pure: imports nothing from the app, reads nothing, so it is tested on its own.
``frontend/src/lib/diff.ts`` implements the same contract for the web UI;
change both together:

- An answer is cut into units. Prose becomes sentences (a paragraph break,
  heading, list item, quote or table row always starts a new one; a sentence
  ends at ``.``/``!``/``?``, optional closing quotes or brackets, then
  whitespace before anything but a lowercase letter; ``。！？`` always end
  one). Markdown formatting is stripped first (emphasis, links, inline code,
  heading and list markers), so the diff is of the text, not of how it is
  set. Fenced code blocks become lines (blank ones dropped); JSON (a code
  block that parses as JSON, or a whole answer that does) is pretty-printed
  with sorted keys first, so key order and whitespace are not changes.
- Units are aligned as a sequence (difflib here, an LCS in the frontend).
  A run of units only in A next to a run only in B is paired position by
  position: a pair of the same kind whose words overlap enough
  (``PAIR_SIMILARITY``) is one *changed* unit, diffed word by word; the rest
  stay *only in A* / *only in B*.
"""

import json
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

PAIR_SIMILARITY = 0.3
"""Word overlap (Dice) from which two units in the same spot count as one changed unit."""

SENTENCE = "sentence"
CODE = "code"
JSON = "json"

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_QUOTE = re.compile(r"^\s*>\s?")
_RULE = re.compile(r"^\s*(?:[-*_]\s*){3,}$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
_TOKEN = re.compile(r"\s+|[\w'-]+|[^\w\s]")
_ENDERS = ".!?"
_CJK_ENDERS = "。！？"
_CLOSERS = "\"'”’)]"


# ─── Cutting an answer into units ───────────────────────────────


def _strip_inline(text: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"`+([^`]*)`+", r"\1", text)
    text = re.sub(r"</?[A-Za-z][^>]*>", " ", text)
    text = text.replace("**", "").replace("~~", "")
    text = re.sub(r"(^|[^\w])__([^_\n]+)__(?=[^\w]|$)", r"\1\2", text)
    text = re.sub(r"(^|[^\w*])\*([^*\n]+)\*(?=[^\w*]|$)", r"\1\2", text)
    text = re.sub(r"(^|[^\w])_([^_\n]+)_(?=[^\w]|$)", r"\1\2", text)
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str) -> List[str]:
    """A paragraph's sentences, as described in the module docstring."""
    out: List[str] = []
    start, i, n = 0, 0, len(text)
    while i < n:
        ch = text[i]
        if ch in _CJK_ENDERS:
            out.append(text[start:i + 1])
            start = i + 1
        elif ch in _ENDERS:
            j = i + 1
            while j < n and (text[j] in _ENDERS or text[j] in _CLOSERS):
                j += 1
            k = j
            while k < n and text[k].isspace():
                k += 1
            if k > j and (k == n or not ("a" <= text[k] <= "z")):
                out.append(text[start:j])
                start, i = k, k
                continue
        i += 1
    out.append(text[start:])
    return [s.strip() for s in out if s.strip()]


def _parse_json(text: str) -> Optional[Any]:
    stripped = text.strip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        return json.loads(stripped)
    except ValueError:
        return None


def _json_lines(value: Any) -> List[Tuple[str, str]]:
    pretty = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)
    return [(JSON, line) for line in pretty.split("\n")]


def _code_lines(body: List[str]) -> List[Tuple[str, str]]:
    value = _parse_json("\n".join(body))
    if value is not None:
        return _json_lines(value)
    return [(CODE, line.rstrip()) for line in body if line.strip()]


def units(text: str) -> List[Tuple[str, str]]:
    """The answer as (kind, text) units: sentences, code lines, JSON lines."""
    text = (text or "").replace("\r\n", "\n")
    whole = _parse_json(text)
    if whole is not None:
        return _json_lines(whole)

    out: List[Tuple[str, str]] = []
    paragraph: List[str] = []

    def flush():
        if paragraph:
            out.extend((SENTENCE, s) for s in split_sentences(_strip_inline(" ".join(paragraph))))
            paragraph.clear()

    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        fence = _FENCE.match(line)
        if fence:
            flush()
            marker = fence.group(1)
            body: List[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(marker[0] * len(marker)):
                body.append(lines[i])
                i += 1
            out.extend(_code_lines(body))
            i += 1
            continue
        if not line.strip() or _RULE.match(line):
            flush()
        elif line.lstrip().startswith("|"):
            flush()
            if not _TABLE_SEP.match(line):
                cells = [_strip_inline(c) for c in line.strip().strip("|").split("|")]
                row = " | ".join(c for c in cells if c)
                if row:
                    out.append((SENTENCE, row))
        elif _HEADING.match(line):
            flush()
            paragraph.append(_HEADING.sub("", line))
            flush()  # a heading is never continued by the next line
        elif _LIST.match(line) or _QUOTE.match(line):
            flush()
            paragraph.append(_LIST.sub("", _QUOTE.sub("", line)))
        else:
            paragraph.append(line)
        i += 1
    flush()
    return out


# ─── Words ───────────────────────────────────────────────────────


def tokens(text: str) -> List[str]:
    return _TOKEN.findall(text)


def similarity(a: str, b: str) -> float:
    """Dice overlap of the two texts' words (case-insensitive)."""
    wa = [t.lower() for t in tokens(a) if not t.isspace()]
    wb = [t.lower() for t in tokens(b) if not t.isspace()]
    if not wa and not wb:
        return 1.0
    counts: Dict[str, int] = {}
    for w in wa:
        counts[w] = counts.get(w, 0) + 1
    common = 0
    for w in wb:
        if counts.get(w, 0) > 0:
            counts[w] -= 1
            common += 1
    return 2 * common / (len(wa) + len(wb))


def _push(segments: List[Dict[str, str]], op: str, text: str) -> None:
    if not text:
        return
    if segments and segments[-1]["op"] == op:
        segments[-1]["text"] += text
    else:
        segments.append({"op": op, "text": text})


def word_diff(a: str, b: str) -> List[Dict[str, str]]:
    """Segments {op: same | removed | added, text}: A is same + removed, B is same + added."""
    ta, tb = tokens(a), tokens(b)
    segments: List[Dict[str, str]] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        if tag == "equal":
            _push(segments, "same", "".join(ta[i1:i2]))
        else:
            _push(segments, "removed", "".join(ta[i1:i2]))
            _push(segments, "added", "".join(tb[j1:j2]))
    return segments


# ─── Two answers ─────────────────────────────────────────────────


def _group(kind: str) -> str:
    return "sentences" if kind == SENTENCE else "lines"


def _pair(rows: List[Dict[str, Any]], only_a: List[Tuple[str, str]], only_b: List[Tuple[str, str]]) -> None:
    for (ka, a), (kb, b) in zip(only_a, only_b):
        if _group(ka) == _group(kb) and similarity(a, b) >= PAIR_SIMILARITY:
            rows.append({"op": "changed", "kind": ka, "a": a, "b": b, "segments": word_diff(a, b)})
        else:
            rows.append({"op": "only_a", "kind": ka, "text": a})
            rows.append({"op": "only_b", "kind": kb, "text": b})
    rows.extend({"op": "only_a", "kind": k, "text": t} for k, t in only_a[len(only_b):])
    rows.extend({"op": "only_b", "kind": k, "text": t} for k, t in only_b[len(only_a):])


def diff_texts(a: str, b: str) -> Dict[str, Any]:
    """The difference between two answers.

    Returns {rows: [...], summary, summary_text, identical}. Each row is
    {op: "same", kind, text}, {op: "only_a" | "only_b", kind, text} or
    {op: "changed", kind, a, b, segments: [{op: same | removed | added,
    text}]}; kind is "sentence", "code" or "json". summary counts rows per
    group: {sentences: {same, changed, only_a, only_b}, lines: {...}}."""
    ua, ub = units(a), units(b)
    rows: List[Dict[str, Any]] = []
    matcher = SequenceMatcher(None, ua, ub, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            rows.extend({"op": "same", "kind": k, "text": t} for k, t in ua[i1:i2])
        else:
            _pair(rows, ua[i1:i2], ub[j1:j2])
    summary = {g: {"same": 0, "changed": 0, "only_a": 0, "only_b": 0} for g in ("sentences", "lines")}
    for row in rows:
        summary[_group(row["kind"])][row["op"]] += 1
    return {
        "rows": rows,
        "summary": summary,
        "summary_text": summary_text(summary),
        "identical": all(r["op"] == "same" for r in rows),
    }


def summary_text(summary: Dict[str, Dict[str, int]]) -> str:
    """"12 sentences the same, 3 changed, 2 only in A, 1 only in B" (and the
    same for code lines); what the CLI prints and the web UI shows."""
    parts = []
    for group, one, many in (("sentences", "sentence", "sentences"), ("lines", "line of code", "lines of code")):
        c = summary[group]
        if not any(c.values()):
            continue
        noun = one if c["same"] == 1 else many
        bits = [f"{c['same']} {noun} the same"]
        bits += [f"{c[k]} {label}" for k, label in (("changed", "changed"), ("only_a", "only in A"), ("only_b", "only in B")) if c[k]]
        parts.append(", ".join(bits))
    if not parts:
        return "Both answers are empty."
    if all(not c["changed"] and not c["only_a"] and not c["only_b"] for c in summary.values()):
        return "No differences: " + "; ".join(parts) + "."
    return "; ".join(parts)
