"""Bringing pruned messages back when they are relevant.

Pruning hides history from the model, but the host usually still has it.
A HistoryRecall picks which hidden messages to show again for the current
request, so the summary no longer has to be the only copy of a detail.
"""

import math
import re
from collections import Counter
from typing import Protocol, Sequence

_WORD = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")
_STOP = frozenset(
    "a an and are as at be by did do does earlier for from has have in is it its of on or "
    "that the this to was we were what which who with you your just answer value quick check something "
    "conversation".split()
)


def _terms(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower().replace("-", " ")) if w not in _STOP]


class HistoryRecall(Protocol):
    name: str

    def select(self, query: str, candidates: Sequence[str], hint: str = "") -> list[int]:
        """Indexes into `candidates` (hidden messages, oldest first) to show
        again. `hint` is what the model can still see of the pruned history
        (the latest summary)."""
        ...


class KeywordRecall:
    """The hidden messages sharing the most distinctive words with the
    request (IDF-weighted overlap), at most `limit`, returned oldest first so
    a later correction still reads as later."""

    def __init__(self, limit: int = 4):
        self.limit = limit
        self.name = "keyword"

    def select(self, query: str, candidates: Sequence[str], hint: str = "") -> list[int]:
        docs = [set(_terms(c)) for c in candidates]
        if not docs:
            return []
        df = Counter(t for d in docs for t in d)
        idf = {t: math.log((len(docs) + 1) / (n + 0.5)) for t, n in df.items()}
        wanted = set(_terms(query))
        scored = [(sum(idf.get(t, 0.0) for t in wanted & d), i) for i, d in enumerate(docs)]
        best = sorted((s for s in scored if s[0] > 0), key=lambda si: (-si[0], -si[1]))[: self.limit]
        return sorted(i for _, i in best)


class EmbeddingRecall:
    """The hidden messages closest in meaning to the request (cosine
    similarity of embeddings), at most `limit`, oldest first. `embed` maps
    texts to vectors; the host supplies it (and any caching)."""

    def __init__(self, embed, limit: int = 4):
        self.embed = embed
        self.limit = limit
        self.name = "embedding"

    def select(self, query: str, candidates: Sequence[str], hint: str = "") -> list[int]:
        if not candidates:
            return []
        q, *docs = self.embed([query, *candidates])
        qn = math.sqrt(sum(x * x for x in q)) or 1.0

        def cosine(v):
            return sum(a * b for a, b in zip(q, v)) / (qn * (math.sqrt(sum(x * x for x in v)) or 1.0))

        best = sorted(range(len(docs)), key=lambda i: (-cosine(docs[i]), -i))[: self.limit]
        return sorted(best)


class GuidedRecall:
    """Lets a model decide what to look for: `rewrite(query, hint)` turns the
    request plus what is still visible (the summary, e.g. an index of topics)
    into search terms, which `base` then matches. Keeps the relevance
    decision with something that understands the question, rather than
    with word overlap alone."""

    def __init__(self, rewrite, base=None):
        self.rewrite = rewrite
        self.base = base or KeywordRecall()
        self.name = f"guided-{self.base.name}"

    def select(self, query: str, candidates: Sequence[str], hint: str = "") -> list[int]:
        terms = self.rewrite(query, hint)
        return self.base.select(f"{terms}\n{query}", candidates, hint)
