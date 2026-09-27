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

    def select(self, query: str, candidates: Sequence[str]) -> list[int]:
        """Indexes into `candidates` (hidden messages, oldest first) to show again."""
        ...


class KeywordRecall:
    """The hidden messages sharing the most distinctive words with the
    request (IDF-weighted overlap), at most `limit`, returned oldest first so
    a later correction still reads as later."""

    def __init__(self, limit: int = 4):
        self.limit = limit
        self.name = "keyword"

    def select(self, query: str, candidates: Sequence[str]) -> list[int]:
        docs = [set(_terms(c)) for c in candidates]
        if not docs:
            return []
        df = Counter(t for d in docs for t in d)
        idf = {t: math.log((len(docs) + 1) / (n + 0.5)) for t, n in df.items()}
        wanted = set(_terms(query))
        scored = [(sum(idf.get(t, 0.0) for t in wanted & d), i) for i, d in enumerate(docs)]
        best = sorted((s for s in scored if s[0] > 0), key=lambda si: (-si[0], -si[1]))[: self.limit]
        return sorted(i for _, i in best)
