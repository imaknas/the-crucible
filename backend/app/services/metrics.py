"""What one reply took: time to first token, total time, tokens and cost.

The drafting node times its model call (``ReplyTimer``) and stores the
timing on the reply it writes (``additional_kwargs[TIMING_KEY]``); token
counts are the provider's own ``usage_metadata`` on the same message. Both
live in the checkpoint, so a reply read back after a reload has the same
numbers as the one that just streamed.

Cost is derived when a reply is read (``message_metrics``), priced on the
day the reply was written, from the hand-kept price list
(catalog/prices.py). A model without a price has ``cost_usd`` None: the
cost is unknown, never guessed.

Every client gets the same ``metrics`` object, or None for a reply that
recorded neither timing nor usage (one written before this existed):
    {ttft_ms, total_ms, input_tokens, output_tokens, reasoning_tokens,
     cached_input_tokens, cost_usd}
Reasoning and cached tokens are part of output and input, not added to them.
Times cover the answering model's call only: a summary or document search
before it is not the model's latency.
"""

import functools
import time
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs

from app.catalog.prices import ModelPrice, PriceBook, load_prices
from app.services.message_format import message_model
from app.utils.helpers import extract_text

TIMING_KEY = "crucible_timing"
# A run may inject its own monotonic clock (seconds) under this key.
CLOCK_KEY = "monotonic_clock"

Metrics = Dict[str, Any]


def clock_from(config: Optional[Mapping[str, Any]]) -> Callable[[], float]:
    """The run's monotonic clock, else the system's."""
    return ((config or {}).get("configurable") or {}).get(CLOCK_KEY) or time.perf_counter


class ReplyTimer(BaseCallbackHandler):
    """Times one model call: when it started, when its first visible output
    arrived and when it returned.

    It listens to the call's own callbacks (``watch``), so the first token is
    seen when the provider sends it, not when a client gets round to reading
    the stream. A chunk with no text (Anthropic's opening event, a chunk
    carrying only usage) is not a first token: the person sees nothing yet.
    """

    run_inline = True

    def __init__(self, clock: Callable[[], float]):
        self._clock = clock
        self._started: Optional[float] = None
        self._first: Optional[float] = None
        self._ended: Optional[float] = None

    def watch(self, config: Optional[RunnableConfig]) -> RunnableConfig:
        """``config`` with this timer added to its callbacks, the run's own
        kept (they are what streams the reply to clients). Starts the clock."""
        self._started = self._clock()
        return merge_configs(config, {"callbacks": [self]})

    def on_llm_new_token(self, token: str, *, chunk: Any = None, **kwargs: Any) -> None:
        if self._first is not None:
            return
        content = getattr(getattr(chunk, "message", None), "content", None)
        if token or (content and extract_text(content, strip=False)):
            self._first = self._clock()

    def stop(self) -> None:
        self._ended = self._clock()

    def timing(self) -> Dict[str, Optional[int]]:
        """{ttft_ms, total_ms}; ttft_ms is None if nothing was streamed."""
        def ms(t: Optional[float]) -> Optional[int]:
            return None if t is None or self._started is None else max(0, round((t - self._started) * 1000))

        return {"ttft_ms": ms(self._first), "total_ms": ms(self._ended)}

    def stamp(self, message: Any) -> None:
        """Record the timing on the reply the call returned."""
        extra = getattr(message, "additional_kwargs", None)
        if isinstance(extra, dict):
            extra[TIMING_KEY] = self.timing()


@functools.lru_cache(maxsize=1)
def current_prices() -> Mapping[str, ModelPrice]:
    """The price list, read once per process."""
    return load_prices()


def snapshot_day(snapshot: Any) -> Optional[str]:
    """The day (YYYY-MM-DD, UTC) a checkpoint was written, from its timestamp."""
    created = getattr(snapshot, "created_at", None)
    return created[:10] if isinstance(created, str) and len(created) >= 10 else None


def _int(value: Any) -> Optional[int]:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def message_metrics(
    msg: Any,
    *,
    day: Optional[str],
    prices: Optional[Mapping[str, ModelPrice]] = None,
) -> Optional[Metrics]:
    """A reply's metrics (see the module docstring), or None if it recorded
    neither timing nor usage. ``day`` is when it was written (its price
    that day); None prices it as of today's list."""
    if getattr(msg, "type", None) != "ai":
        return None
    extra = getattr(msg, "additional_kwargs", None) or {}
    timing = extra.get(TIMING_KEY) if isinstance(extra, dict) else None
    timing = timing if isinstance(timing, dict) else {}
    usage = getattr(msg, "usage_metadata", None) or {}
    if not timing and not usage:
        return None

    input_tokens = _int(usage.get("input_tokens"))
    output_tokens = _int(usage.get("output_tokens"))
    cost = None
    if usage and input_tokens is not None and output_tokens is not None:
        model = message_model(msg)
        if model:
            book = PriceBook(prices if prices is not None else current_prices(), day or time.strftime("%Y-%m-%d"))
            cost = book.cost(model, usage)
    return {
        "ttft_ms": _int(timing.get("ttft_ms")),
        "total_ms": _int(timing.get("total_ms")),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": _int((usage.get("output_token_details") or {}).get("reasoning")),
        "cached_input_tokens": _int((usage.get("input_token_details") or {}).get("cache_read")),
        "cost_usd": cost,
    }


def turn_total(metrics: Iterable[Optional[Metrics]]) -> Optional[Metrics]:
    """A turn's answers together: tokens and cost summed, time the slowest.

    ``cost_usd`` sums the priced answers only; ``unpriced`` counts the
    answers with tokens but no known price, so a total is never shown as
    complete when it isn't. None when no answer has metrics."""
    known = [m for m in metrics if m]
    if not known:
        return None

    def total(key: str) -> Optional[int]:
        values = [m[key] for m in known if m.get(key) is not None]
        return sum(values) if values else None

    def slowest(key: str) -> Optional[int]:
        values = [m[key] for m in known if m.get(key) is not None]
        return max(values) if values else None

    costs = [m["cost_usd"] for m in known if m.get("cost_usd") is not None]
    counted = [m for m in known if m.get("input_tokens") is not None and m.get("output_tokens") is not None]
    return {
        "answers": len(known),
        "ttft_ms": slowest("ttft_ms"),
        "total_ms": slowest("total_ms"),
        "input_tokens": total("input_tokens"),
        "output_tokens": total("output_tokens"),
        "reasoning_tokens": total("reasoning_tokens"),
        "cached_input_tokens": total("cached_input_tokens"),
        "cost_usd": sum(costs) if costs else None,
        "unpriced": sum(1 for m in counted if m.get("cost_usd") is None),
    }


def _seconds(ms: int) -> str:
    return f"{ms / 1000:.1f} s"


def format_cost(cost: Optional[float]) -> str:
    if cost is None:
        return "price unknown"
    if cost == 0:
        return "$0"
    if cost < 0.0001:  # four decimals would round it to "$0.0000"
        return "<$0.0001"
    return f"${cost:.4f}" if cost < 1 else f"${cost:,.2f}"


def describe(metrics: Optional[Metrics]) -> str:
    """One line for a person: "1.2 s to first token · 8.4 s · 1,234 in /
    567 out (120 reasoning) · $0.0123". Empty for None."""
    if not metrics:
        return ""
    parts = []
    if metrics.get("ttft_ms") is not None:
        parts.append(f"{_seconds(metrics['ttft_ms'])} to first token")
    if metrics.get("total_ms") is not None:
        parts.append(_seconds(metrics["total_ms"]) + (" (slowest)" if "answers" in metrics else ""))
    if metrics.get("input_tokens") is not None and metrics.get("output_tokens") is not None:
        tokens = f"{metrics['input_tokens']:,} in / {metrics['output_tokens']:,} out"
        if metrics.get("reasoning_tokens"):
            tokens += f" ({metrics['reasoning_tokens']:,} reasoning)"
        parts.append(tokens)
        unpriced = metrics.get("unpriced") or 0
        if "answers" in metrics and unpriced and metrics.get("cost_usd") is not None:
            parts.append(f"{format_cost(metrics['cost_usd'])} + {unpriced} price unknown")
        else:
            parts.append(format_cost(metrics.get("cost_usd")))
    return " · ".join(parts)
