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
     cached_input_tokens, cost_usd, helpers}
Reasoning and cached tokens are part of output and input, not added to them.
Times, tokens and cost_usd cover the answering model's call only. The other
calls the same run made before it (a history summary, document grading,
recall) are ``helpers`` (``usage_summary``), or None when there were none:
    {calls, kinds, input_tokens, output_tokens, reasoning_tokens,
     cached_input_tokens, cost_usd, unpriced}
A ``UsageMeter`` on the run records every call; the drafting node keeps
what it recorded before the answer on the reply (``HELPERS_KEY``), as raw
usage priced when read, like the reply's own. Only completed calls report
usage: a stopped or failed call is not counted.
"""

import datetime
import functools
import threading
import time
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs

from app.catalog.prices import ModelPrice, PriceBook, load_prices
from app.services.message_format import message_model
from app.services.recall import INTERNAL_TAG
from app.utils.helpers import extract_text

TIMING_KEY = "crucible_timing"
# The run's other model calls before the reply: [{model, kind, usage}].
HELPERS_KEY = "crucible_helper_calls"
# Where a run keeps its UsageMeter (config["configurable"]).
METER_KEY = "usage_meter"
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


# What a call was for, from the graph node that made it. An internal call
# inside the drafting node is recall's rewriter; the node's own untagged
# call is the answer.
NODE_KINDS = {"summarize": "summary", "grade_retrieval": "document grading", "retrieve": "document search"}


def call_entry(message: Any, model: Optional[str], kind: str) -> Optional[Dict[str, Any]]:
    """One model call's record, {model, kind, usage}: the model the provider
    says answered, else the one asked. None if the response reported no usage."""
    usage = getattr(message, "usage_metadata", None)
    if not usage:
        return None
    served = (getattr(message, "response_metadata", None) or {}).get("model_name")
    keep = ("input_tokens", "output_tokens", "input_token_details", "output_token_details")
    return {"model": served if isinstance(served, str) and served else model, "kind": kind,
            "usage": {k: dict(usage[k]) if isinstance(usage.get(k), Mapping) else usage.get(k)
                      for k in keep if usage.get(k) is not None}}


class UsageMeter(BaseCallbackHandler):
    """Records every completed model call of the run it is attached to.

    Calls the run makes on executor threads (graph nodes, recall) arrive
    here concurrently, hence the lock."""

    run_inline = True

    def __init__(self):
        super().__init__()
        self._asked: Dict[Any, tuple] = {}
        self._calls: list = []
        self._lock = threading.Lock()

    def on_chat_model_start(self, serialized, messages, *, run_id=None, tags=None, metadata=None, **kwargs: Any) -> None:
        metadata = metadata or {}
        model = metadata.get("ls_model_name") or ((serialized or {}).get("kwargs") or {}).get("model")
        node = metadata.get("langgraph_node")
        if node in NODE_KINDS:
            kind = NODE_KINDS[node]
        elif node == "draft":
            kind = "recall" if INTERNAL_TAG in (tags or []) else "answer"
        else:
            kind = "helper"
        with self._lock:
            self._asked[run_id] = (model, kind)

    def on_llm_error(self, error: BaseException, *, run_id=None, **kwargs: Any) -> None:
        with self._lock:
            self._asked.pop(run_id, None)

    def on_llm_end(self, response, *, run_id=None, **kwargs: Any) -> None:
        with self._lock:
            model, kind = self._asked.pop(run_id, (None, "helper"))
        try:
            message = response.generations[0][0].message
        except (IndexError, AttributeError):
            return
        entry = call_entry(message, model, kind)
        if entry is not None:
            with self._lock:
                self._calls.append(entry)

    def calls(self) -> list:
        """What it has recorded so far, oldest first."""
        with self._lock:
            return list(self._calls)


def meter_from(config: Optional[Mapping[str, Any]]) -> Optional[UsageMeter]:
    return ((config or {}).get("configurable") or {}).get(METER_KEY)


def metered(config: RunnableConfig) -> UsageMeter:
    """Attach a new UsageMeter to a run's config (its callbacks, and the
    configurable the drafting node reads it from) and return it."""
    meter = UsageMeter()
    config.setdefault("configurable", {})[METER_KEY] = meter
    config["callbacks"] = [*(config.get("callbacks") or []), meter]
    return meter


def usage_summary(
    calls: Iterable[Mapping[str, Any]],
    *,
    day: Optional[str],
    prices: Optional[Mapping[str, ModelPrice]] = None,
) -> Optional[Metrics]:
    """Calls' tokens and cost together (see the module docstring), priced
    as of ``day``; None for no calls."""
    calls = [c for c in calls if c]
    if not calls:
        return None
    book = PriceBook(prices if prices is not None else current_prices(), day or time.strftime("%Y-%m-%d"))
    costs, unpriced = [], 0
    for c in calls:
        cost = book.cost(c["model"], c.get("usage") or {}) if c.get("model") else None
        if cost is None:
            unpriced += 1
        else:
            costs.append(cost)

    def total(key: str, detail: Optional[str] = None, sub: Optional[str] = None) -> int:
        out = 0
        for c in calls:
            u = c.get("usage") or {}
            value = (u.get(detail) or {}).get(sub) if detail else u.get(key)
            out += _int(value) or 0
        return out

    return {
        "calls": len(calls),
        "kinds": sorted({c.get("kind") or "helper" for c in calls}),
        "input_tokens": total("input_tokens"),
        "output_tokens": total("output_tokens"),
        "reasoning_tokens": total("", "output_token_details", "reasoning"),
        "cached_input_tokens": total("", "input_token_details", "cache_read"),
        "cost_usd": sum(costs) if costs else None,
        "unpriced": unpriced,
    }


def with_calls(record: Dict[str, Any], calls: Iterable[Optional[Mapping[str, Any]]]) -> Dict[str, Any]:
    """``record`` with the model calls it took kept as raw usage and the
    day they were made, to store; ``priced`` turns them into ``usage``."""
    return {**record, "calls": {"day": utc_day(), "calls": [c for c in calls if c]}}


def priced(record: Dict[str, Any]) -> Dict[str, Any]:
    """A stored record as clients read it: its raw calls priced as
    ``usage`` (a usage_summary), None for a record from before they were kept."""
    out = {k: v for k, v in record.items() if k != "calls"}
    stored = record.get("calls") or {}
    out["usage"] = usage_summary(stored.get("calls") or [], day=stored.get("day"))
    return out


@functools.lru_cache(maxsize=1)
def current_prices() -> Mapping[str, ModelPrice]:
    """The price list, read once per process."""
    return load_prices()


def utc_day() -> str:
    """Today (YYYY-MM-DD, UTC), the day calls made now are priced on, like
    the checkpoints' own timestamps."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


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
    helper_calls = extra.get(HELPERS_KEY) if isinstance(extra, dict) else None
    if not timing and not usage and not helper_calls:
        return None

    input_tokens = _int(usage.get("input_tokens"))
    output_tokens = _int(usage.get("output_tokens"))
    cost = None
    if usage and input_tokens is not None and output_tokens is not None:
        book = PriceBook(prices if prices is not None else current_prices(), day or time.strftime("%Y-%m-%d"))
        # Priced as the model that answered when the provider says which and
        # it has a price: a routed id (gemini-3.5-flash answered by
        # gemini-3.6-flash) is billed as what served it.
        served = (getattr(msg, "response_metadata", None) or {}).get("model_name")
        model = served if isinstance(served, str) and book.resolve(served) else message_model(msg)
        if model:
            cost = book.cost(model, usage)
    return {
        "ttft_ms": _int(timing.get("ttft_ms")),
        "total_ms": _int(timing.get("total_ms")),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": _int((usage.get("output_token_details") or {}).get("reasoning")),
        "cached_input_tokens": _int((usage.get("input_token_details") or {}).get("cache_read")),
        "cost_usd": cost,
        "helpers": usage_summary(helper_calls or [], day=day, prices=prices) if isinstance(helper_calls, list) else None,
    }


def turn_total(metrics: Iterable[Optional[Metrics]], extra: Iterable[Optional[Metrics]] = ()) -> Optional[Metrics]:
    """A turn's answers together: tokens and cost summed, time the slowest.

    Tokens and ``cost_usd`` include every answer's ``helpers`` and any
    ``extra`` usage summaries (a debate's judge), which are also summed on
    their own as ``helpers``. ``cost_usd`` sums the priced calls only;
    ``unpriced`` counts the answers and calls with tokens but no known
    price, so a total is never shown as complete when it isn't. None when
    nothing has metrics."""
    known = [m for m in metrics if m]
    helpers = [m["helpers"] for m in known if m.get("helpers")] + [e for e in extra if e]
    if not known and not helpers:
        return None

    def total(key: str) -> Optional[int]:
        values = [m[key] for m in known if m.get(key) is not None]
        return sum(values) if values else None

    def slowest(key: str) -> Optional[int]:
        values = [m[key] for m in known if m.get(key) is not None]
        return max(values) if values else None

    costs = [m["cost_usd"] for m in known if m.get("cost_usd") is not None]
    counted = [m for m in known if m.get("input_tokens") is not None and m.get("output_tokens") is not None]
    helper = combine_usage(helpers)

    def plus(key: str) -> Optional[int]:
        own = total(key)
        more = helper.get(key) if helper else None
        return own if more is None else (own or 0) + more

    helper_cost = helper.get("cost_usd") if helper else None
    return {
        "answers": len(known),
        "ttft_ms": slowest("ttft_ms"),
        "total_ms": slowest("total_ms"),
        "input_tokens": plus("input_tokens"),
        "output_tokens": plus("output_tokens"),
        "reasoning_tokens": plus("reasoning_tokens"),
        "cached_input_tokens": plus("cached_input_tokens"),
        "cost_usd": (sum(costs) + (helper_cost or 0)) if costs or helper_cost is not None else None,
        "unpriced": sum(1 for m in counted if m.get("cost_usd") is None) + (helper["unpriced"] if helper else 0),
        "helpers": helper,
    }


def combine_usage(summaries: Iterable[Optional[Metrics]]) -> Optional[Metrics]:
    """Several usage summaries (``usage_summary``) as one."""
    known = [s for s in summaries if s]
    if not known:
        return None
    costs = [s["cost_usd"] for s in known if s.get("cost_usd") is not None]
    keys = ("calls", "input_tokens", "output_tokens", "reasoning_tokens", "cached_input_tokens", "unpriced")
    return {
        **{k: sum(s.get(k) or 0 for s in known) for k in keys},
        "kinds": sorted({k for s in known for k in s.get("kinds") or []}),
        "cost_usd": sum(costs) if costs else None,
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
    helpers = metrics.get("helpers")
    if helpers:
        # A reply's own numbers leave its helper calls out; a total has them in.
        word = "incl." if "answers" in metrics else "+"
        parts.append(f"{word} {describe_helpers(helpers)}")
    return " · ".join(parts)


def describe_usage(usage: Optional[Metrics]) -> str:
    """Calls on their own (a usage_summary): "2 calls · 1,234 in / 56 out · $0.0012"."""
    if not usage:
        return ""
    calls = usage.get("calls") or 0
    cost = format_cost(usage.get("cost_usd")) if usage.get("cost_usd") is not None else "price unknown"
    if usage.get("unpriced") and usage.get("cost_usd") is not None:
        cost += f" + {usage['unpriced']} price unknown"
    return (f"{calls} call{'s' if calls != 1 else ''} · {usage.get('input_tokens') or 0:,} in / "
            f"{usage.get('output_tokens') or 0:,} out · {cost}")


def describe_helpers(helpers: Metrics) -> str:
    """"$0.0012 for 3 other calls (summary, recall)"."""
    calls = helpers.get("calls") or 0
    cost = format_cost(helpers.get("cost_usd")) if helpers.get("cost_usd") is not None else "price unknown"
    if helpers.get("unpriced") and helpers.get("cost_usd") is not None:
        cost += f" + {helpers['unpriced']} price unknown"
    kinds = ", ".join(helpers.get("kinds") or [])
    return f"{cost} for {calls} other call{'s' if calls != 1 else ''}" + (f" ({kinds})" if kinds else "")
