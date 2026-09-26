"""Compaction policies: when to write a summary, and when to stop showing the
model the raw history in front of it.

Two separate decisions, because they are in the host app:

- should_summarize: produce a new summary of everything since the last one.
- should_prune:     for this model call, replace the history before the latest
                    summary with the summary itself.

A policy sees only numbers (ContextSnapshot) and model facts (ModelBudget),
never messages, so it can be unit-tested and swapped per run.
"""

from dataclasses import dataclass
from typing import Callable, Optional, Protocol


@dataclass(frozen=True)
class ModelBudget:
    """Facts about the model being called, supplied by the host."""

    model_id: str
    # The host's soft threshold (tokens). Today this is the app's registry
    # `limit`; a model catalog can supply it instead.
    soft_limit: int
    context_window: Optional[int] = None


@dataclass(frozen=True)
class ContextSnapshot:
    """The conversation as token and message counts."""

    total_tokens: int
    # Tokens from the latest summary onward (== total_tokens if none yet).
    tokens_since_summary: int
    total_messages: int
    # Messages after the latest summary; None when nothing was summarized yet.
    messages_since_summary: Optional[int] = None
    # Size of the latest summary itself (included in tokens_since_summary).
    summary_tokens: int = 0

    @property
    def new_tokens(self) -> int:
        """Tokens written since the latest summary, the summary excluded."""
        return self.tokens_since_summary - self.summary_tokens


@dataclass(frozen=True)
class Decision:
    act: bool
    reason: str

    def __bool__(self) -> bool:
        return self.act


class CompactionPolicy(Protocol):
    name: str

    def should_summarize(self, ctx: ContextSnapshot, budget: ModelBudget) -> Decision: ...

    def should_prune(self, ctx: ContextSnapshot, budget: ModelBudget) -> Decision: ...


Threshold = Callable[[ModelBudget], int]


def fraction_of_limit(fraction: float) -> Threshold:
    """Threshold at a fraction of the host's soft limit (1.0 = the limit itself)."""
    return lambda budget: int(budget.soft_limit * fraction)


def fixed_tokens(tokens: int) -> Threshold:
    """The same threshold for every model — the knob experiments sweep."""
    return lambda _budget: tokens


class ThresholdPolicy:
    """Summarize and prune once the history passes a token threshold.

    With the defaults this is The Crucible's original behaviour: threshold =
    the model's soft limit, keep the last `keep_recent` messages verbatim, and
    don't re-summarize until at least that many new messages have arrived.

    Re-summarizing waits for new material, not just a full context: the
    next summary is due when the summary plus what came after it passes the
    threshold, but never before `min_new_fraction` of the threshold is new.
    Without that floor, a summary that grows past the threshold makes every
    eligible turn re-summarize (pilot 2: 132 summaries instead of ~20), each
    one re-compressing the last for almost nothing new.
    """

    def __init__(
        self,
        threshold: Threshold = fraction_of_limit(1.0),
        keep_recent: int = 5,
        name: str = "",
        min_new_fraction: float = 0.5,
    ):
        self.threshold = threshold
        self.keep_recent = keep_recent
        self.name = name or "threshold"
        self.min_new_fraction = min_new_fraction

    def should_summarize(self, ctx: ContextSnapshot, budget: ModelBudget) -> Decision:
        if ctx.total_messages <= self.keep_recent:
            return Decision(False, "too few messages")
        if ctx.messages_since_summary is not None and ctx.messages_since_summary < self.keep_recent:
            return Decision(False, "summarized recently")
        limit = self.threshold(budget)
        if ctx.messages_since_summary is None:
            if ctx.tokens_since_summary <= limit:
                return Decision(False, f"{ctx.tokens_since_summary} <= {limit}")
            return Decision(True, f"{ctx.tokens_since_summary} > {limit}")
        # Same as tokens_since_summary > limit while the summary is small.
        due = max(limit - ctx.summary_tokens, int(limit * self.min_new_fraction))
        if ctx.new_tokens <= due:
            return Decision(False, f"{ctx.new_tokens} new <= {due} (summary {ctx.summary_tokens})")
        return Decision(True, f"{ctx.new_tokens} new > {due} (summary {ctx.summary_tokens})")

    def should_prune(self, ctx: ContextSnapshot, budget: ModelBudget) -> Decision:
        limit = self.threshold(budget)
        if ctx.total_tokens > limit:
            return Decision(True, f"{ctx.total_tokens} > {limit}")
        return Decision(False, f"{ctx.total_tokens} <= {limit}")


class NeverCompact:
    """Baseline: the model always sees the full raw history."""

    name = "never"

    def should_summarize(self, ctx: ContextSnapshot, budget: ModelBudget) -> Decision:
        return Decision(False, "never compact")

    def should_prune(self, ctx: ContextSnapshot, budget: ModelBudget) -> Decision:
        return Decision(False, "never compact")
