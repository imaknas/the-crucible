"""What stays verbatim once history is pruned to its latest summary.

When a call jumps to the summary, everything written before it is gone
unless a Retention keeps it. The host describes each earlier message by role
and size only; a Retention returns which of them to show verbatim.
"""

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class EarlierMessage:
    role: str  # "user" | "assistant" | "system"
    tokens: int


class Retention(Protocol):
    name: str

    def keep(self, earlier: Sequence[EarlierMessage]) -> list[int]:
        """Indexes into `earlier` (messages before the summary, oldest first)
        to show verbatim, ascending."""
        ...


class KeepRecent:
    """The Crucible's rule: the last `n` messages before the summary, which
    the summary deliberately left out."""

    def __init__(self, n: int = 5):
        self.n = n
        self.name = "recent" if n == 5 else f"recent{n}"

    def keep(self, earlier: Sequence[EarlierMessage]) -> list[int]:
        start = max(0, len(earlier) - self.n)
        return [i for i in range(start, len(earlier)) if earlier[i].role in ("user", "assistant")]


class KeepUserMessages:
    """Codex CLI's rule: everything the user wrote survives verbatim, newest
    first, up to `budget` tokens, on top of the recent window — what the user
    said is never left to the summarizer. (Codex truncates the message that
    crosses the budget; here it is left out whole.)"""

    def __init__(self, budget: int = 20_000, recent: KeepRecent = KeepRecent()):
        self.budget = budget
        self.recent = recent
        self.name = f"user{budget // 1000}k"

    def keep(self, earlier: Sequence[EarlierMessage]) -> list[int]:
        kept = set(self.recent.keep(earlier))
        left = self.budget
        for i in range(len(earlier) - 1, -1, -1):
            if i in kept or earlier[i].role != "user":
                continue
            if earlier[i].tokens > left:
                break
            kept.add(i)
            left -= earlier[i].tokens
        return sorted(kept)
