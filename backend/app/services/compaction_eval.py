"""Run detail-retention experiments on The Crucible's graph.

The experiment design (scenarios, facts, scoring) and the policies live in
app/compaction; this module is the host side: it writes a scenario into a
thread, forks one branch per policy from the same checkpoint, asks every probe
on that branch, and records what the model got right.

Two stand-in models make the pipeline testable and give an upper bound:

- AvailabilityOracle answers a probe iff the answer is still somewhere in the
  context it was given. With it, recall measures what compaction *removed*,
  separately from whether a real model would notice what is left.
- FirstSentenceSummarizer keeps the first sentence of every message, a crude
  but deterministic lossy summary.

Two ways to put a scenario on a branch:

- seeded (run_grid): the whole conversation is written at once and the first
  probe triggers a single summary of all of it.
- live (run_live_grid): the conversation is replayed turn by turn through the
  graph's own summarize step, so a long one is summarized several times as it
  grows, the way the app does it — the setting for cumulative loss.
"""

import asyncio
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, List, Mapping, Optional, Sequence

from langchain_core.callbacks import BaseCallbackHandler, UsageMetadataCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda

from app.compaction import (
    CompactionPolicy,
    HistoryRecall,
    PlantedFact,
    Retention,
    Scenario,
    SummaryInstruction,
    compare_recall,
    is_correct,
)
from app.compaction.probe import is_stale, value_attached
from app.services.graph import (
    INSTRUCTION_CONFIG_KEY,
    POLICY_CONFIG_KEY,
    RECALL_CONFIG_KEY,
    RETENTION_CONFIG_KEY,
    SUMMARIZER_CONFIG_KEY,
    SUMMARY_MARKER,
    compaction_policy_from,
    context_snapshot,
    count_tokens,
    default_summarizer,
    model_budget,
    summarize_history,
)
from app.services.runs import final_state_of_run, tag_run, thread_config
from app.utils.helpers import extract_text


@dataclass(frozen=True)
class Condition:
    name: str
    policy: CompactionPolicy
    # Model that writes the summaries; None = the app's default summarizer.
    summarizer: Optional[str] = None
    # What the summarizer is asked to write; None = the app's default brief.
    instruction: Optional[SummaryInstruction] = None
    # What stays verbatim once history is pruned; None = the recent window.
    retention: Optional[Retention] = None
    # Which hidden messages come back for a request; None = none.
    recall: Optional[HistoryRecall] = None

    def configure(self, config: dict) -> dict:
        config["configurable"][POLICY_CONFIG_KEY] = self.policy
        if self.summarizer:
            config["configurable"][SUMMARIZER_CONFIG_KEY] = self.summarizer
        if self.instruction:
            config["configurable"][INSTRUCTION_CONFIG_KEY] = self.instruction
        if self.retention:
            config["configurable"][RETENTION_CONFIG_KEY] = self.retention
        if self.recall:
            config["configurable"][RECALL_CONFIG_KEY] = self.recall
        return config


@dataclass(frozen=True)
class ProbeResult:
    condition: str
    model: str
    fact: str
    kind: str
    planted_turn: int
    correct: bool
    # Whether the call that answered saw pruned (summary-jumped) history.
    pruned: bool
    # Whether any summary existed on the branch when the probe was answered.
    summarized: bool
    answer: str
    # Token usage of every model call this probe triggered (answer, summary,
    # thesis update), keyed by the provider's model name. Raw counts, so cost
    # can be computed later with whatever prices apply.
    usage: dict = field(default_factory=dict)
    # Which scenario (e.g. its seed) the probe came from.
    scenario: str = "0"
    # plain / distractor / update (see PlantedFact.variant)
    variant: str = "plain"
    # The answer gave a superseded or rejected value.
    stale: bool = False
    # Summaries written after the fact was stated and before it was probed.
    compactions: int = 0
    # Usage of building the branch (live replay summaries), recorded on the
    # first probe of each branch only, so totals count it once.
    setup_usage: dict = field(default_factory=dict)
    # Size in tokens of the latest summary the answering call saw (0: none).
    summary_tokens: int = 0
    # Who stated the fact in the conversation: "user" or "assistant".
    stated_by: str = "user"

    @property
    def key(self) -> str:
        """Pairs the same probe across conditions."""
        return f"{self.model}:{self.scenario}:{self.fact}"


# ─── Spend ───────────────────────────────────────────────────────

# Stand-in models report usage too; they cost nothing.
STAND_INS = frozenset({"availability-oracle", "first-sentence-summarizer", "sized-summarizer"})


class BudgetExhausted(RuntimeError):
    pass


class Spend(BaseCallbackHandler):
    """Running cost of every model call it is attached to, priced by a
    PriceBook, against an optional limit. Calls to models the book cannot
    price are counted in `unpriced` instead of silently costing nothing."""

    def __init__(self, prices, limit: Optional[float] = None, free: Iterable[str] = STAND_INS):
        super().__init__()
        self.prices = prices
        self.limit = limit
        self.free = frozenset(free)
        self.total = 0.0
        self.by_model: dict[str, float] = {}
        self.unpriced: dict[str, int] = {}
        self._lock = threading.Lock()

    def on_llm_end(self, response, **kwargs: Any) -> None:
        try:
            message = response.generations[0][0].message
        except (IndexError, AttributeError):
            return
        usage = getattr(message, "usage_metadata", None)
        name = (getattr(message, "response_metadata", None) or {}).get("model_name")
        if not usage or not name or name in self.free:
            return
        cost = self.prices.cost(name, usage)
        with self._lock:
            if cost is None:
                self.unpriced[name] = self.unpriced.get(name, 0) + 1
            else:
                self.total += cost
                self.by_model[name] = self.by_model.get(name, 0.0) + cost

    @property
    def exhausted(self) -> bool:
        return self.limit is not None and self.total >= self.limit

    def check(self) -> None:
        if self.exhausted:
            raise BudgetExhausted(f"spent ${self.total:.2f} of ${self.limit:.2f}")


def _callbacks(*handlers) -> list:
    return [h for h in handlers if h is not None]


def scenario_messages(scenario: Scenario, assistant_name: Optional[str]) -> List[BaseMessage]:
    return [
        HumanMessage(content=t.text) if t.role == "user" else AIMessage(content=t.text, name=assistant_name)
        for t in scenario.turns
    ]


async def seed_scenario(graph_app, thread_id: str, scenario: Scenario, model_id: str) -> str:
    """Write the scenario's turns into a thread without calling any model."""
    return await seed_messages(graph_app, thread_id, scenario_messages(scenario, model_id), model_id)


async def seed_messages(graph_app, thread_id: str, messages: List[BaseMessage], model_id: str) -> str:
    """Write prepared messages into a new thread; returns the checkpoint id."""
    written = await graph_app.aupdate_state(
        thread_config(thread_id),
        {
            "messages": messages,
            "active_peer": model_id,
            "current_thesis": "",
            "toggles": {"use_rag": False},
        },
        as_node="synthesis",
    )
    return written["configurable"]["checkpoint_id"]


async def replay_with_compaction(
    scenario: Scenario,
    condition: Condition,
    active_peer: str,
    model_factory=None,
    assistant_name: Optional[str] = "assistant",
    spend: Optional[Spend] = None,
) -> tuple[List[BaseMessage], dict]:
    """The conversation as the app would have stored it, summaries included.

    Turn by turn, the graph's own summarize step runs whenever a user message
    arrives (as it does at the start of every turn in the app), under the
    condition's policy and summarizer. No answering model is called. Returns
    the messages and the summarizer's token usage.
    """
    usage = UsageMetadataCallbackHandler()
    config = condition.configure({"configurable": {}, "callbacks": _callbacks(usage, spend)})
    if model_factory is not None:
        config["configurable"]["model_factory"] = model_factory
    summarize = RunnableLambda(summarize_history)
    messages: List[BaseMessage] = []
    for message in scenario_messages(scenario, assistant_name):
        messages.append(message)
        if message.type == "human":
            if spend:
                spend.check()
            out = await summarize.ainvoke({"messages": list(messages), "active_peer": active_peer}, config)
            messages += out["messages"]
    return messages, {name: dict(u) for name, u in usage.usage_metadata.items()}


def _latest_summary_tokens(messages: Sequence[BaseMessage]) -> int:
    for m in reversed(messages):
        if SUMMARY_MARKER in extract_text(m.content):
            return count_tokens([m])
    return 0


def _compactions_since(messages: Sequence[BaseMessage], statement: str) -> int:
    """Summaries after the first message (user's or assistant's) stating `statement`."""
    texts = [extract_text(m.content) for m in messages]
    start = next((i for i, (m, t) in enumerate(zip(messages, texts)) if m.type in ("human", "ai") and statement in t), None)
    if start is None:
        return 0
    return sum(1 for t in texts[start + 1:] if SUMMARY_MARKER in t)


async def run_condition(
    graph_app,
    thread_id: str,
    base_checkpoint_id: str,
    scenario: Scenario,
    model_id: str,
    condition: Condition,
    model_factory=None,
    scenario_label: str = "0",
    setup_usage: Optional[dict] = None,
    spend: Optional[Spend] = None,
) -> list[ProbeResult]:
    """Ask every probe, in order, on one branch forked from the seeded
    checkpoint. Stops early (keeping what it has) once `spend` is exhausted."""
    results: list[ProbeResult] = []
    parent = base_checkpoint_id
    for fact in scenario.facts:
        if spend and spend.exhausted:
            break
        config = condition.configure(thread_config(thread_id, parent))
        run_id = tag_run(config)
        if model_factory is not None:
            config["configurable"]["model_factory"] = model_factory
        usage = UsageMetadataCallbackHandler()
        config["callbacks"] = _callbacks(usage, spend)

        await graph_app.ainvoke(
            {
                "active_peer": model_id,
                "messages": [("user", scenario.probe_prompt(fact))],
                "toggles": {"use_rag": False},
            },
            config,
        )
        final = await final_state_of_run(graph_app, thread_id, run_id)
        if final is None:
            raise RuntimeError(f"probe {fact.key} wrote no checkpoint")
        messages = final.values.get("messages", [])
        answer = next((extract_text(m.content) for m in reversed(messages) if m.type == "ai"), "")
        # Reconstruct what the drafting call saw: history up to and including
        # the probe (and any summary this turn appended).
        before_answer = messages[:-1] if messages and messages[-1].type == "ai" else messages
        pruned = compaction_policy_from(config).should_prune(
            context_snapshot(before_answer), model_budget(model_id)
        ).act
        summarized = any(SUMMARY_MARKER in extract_text(m.content) for m in before_answer)
        results.append(ProbeResult(
            condition=condition.name,
            model=model_id,
            fact=fact.key,
            kind=fact.kind,
            planted_turn=scenario.positions[fact.key],
            correct=is_correct(answer, fact),
            pruned=pruned,
            summarized=summarized,
            answer=answer[:200],
            usage={name: dict(u) for name, u in usage.usage_metadata.items()},
            scenario=scenario_label,
            variant=fact.variant,
            stale=is_stale(answer, fact),
            compactions=_compactions_since(before_answer, fact.statement),
            summary_tokens=_latest_summary_tokens(before_answer),
            stated_by=scenario.stated_by.get(fact.key, "user"),
            setup_usage=(setup_usage or {}) if not results else {},
        ))
        parent = final.config["configurable"]["checkpoint_id"]
    return results


async def run_experiment(
    graph_app,
    scenario: Scenario,
    model_ids: Sequence[str],
    conditions: Sequence[Condition],
    *,
    thread_prefix: str = "compaction-eval",
    model_factory=None,
) -> list[ProbeResult]:
    """Every condition for every model; each model gets its own seeded thread."""
    results: list[ProbeResult] = []
    for model_id in model_ids:
        thread_id = f"{thread_prefix}::{model_id}"
        base = await seed_scenario(graph_app, thread_id, scenario, model_id)
        for condition in conditions:
            results += await run_condition(graph_app, thread_id, base, scenario, model_id, condition, model_factory)
    return results


async def run_grid(
    graph_app,
    scenarios: dict[str, Scenario],
    model_ids: Sequence[str],
    conditions: Sequence[Condition],
    *,
    thread_prefix: str = "compaction-eval",
    model_factory=None,
    concurrency: int = 4,
    spend: Optional[Spend] = None,
) -> list[ProbeResult]:
    """Every (model, scenario) in parallel; conditions within one run in order.

    Each (model, scenario) gets its own thread, seeded once; every condition
    is a branch from that same checkpoint, so conditions see identical input.
    """
    import asyncio

    sem = asyncio.Semaphore(concurrency)

    async def one(model_id: str, label: str, scenario: Scenario) -> list[ProbeResult]:
        async with sem:
            thread_id = f"{thread_prefix}::{label}::{model_id}"
            base = await seed_scenario(graph_app, thread_id, scenario, model_id)
            out: list[ProbeResult] = []
            for condition in conditions:
                out += await run_condition(
                    graph_app, thread_id, base, scenario, model_id, condition, model_factory, label, spend=spend
                )
            return out

    batches = await asyncio.gather(
        *(one(m, label, sc) for m in model_ids for label, sc in scenarios.items())
    )
    return [r for batch in batches for r in batch]


async def run_live_grid(
    graph_app,
    scenarios: dict[str, Scenario],
    model_ids: Sequence[str],
    conditions: Sequence[Condition],
    *,
    thread_prefix: str = "compaction-eval",
    model_factory=None,
    concurrency: int = 4,
    spend: Optional[Spend] = None,
) -> list[ProbeResult]:
    """Like run_grid, but each condition's branch is built by live replay.

    The replay (and so every summary) is computed once per (scenario,
    condition) and shared by all answering models, so models are compared on
    the very same compacted context; assistant turns carry a neutral name.
    Thresholds are therefore evaluated against the first model's budget —
    use fixed thresholds here. Each (scenario, condition, model) gets its own
    thread, since branches no longer share a seeded checkpoint.
    """
    sem = asyncio.Semaphore(concurrency)
    replays: dict[tuple[str, str], asyncio.Task] = {}

    async def replay(label: str, scenario: Scenario, condition: Condition):
        async with sem:
            return await replay_with_compaction(scenario, condition, model_ids[0], model_factory, spend=spend)

    for label, scenario in scenarios.items():
        for condition in conditions:
            replays[(label, condition.name)] = asyncio.create_task(replay(label, scenario, condition))

    async def one(model_id: str, label: str, scenario: Scenario, condition: Condition) -> list[ProbeResult]:
        messages, setup = await replays[(label, condition.name)]
        async with sem:
            thread_id = f"{thread_prefix}::{label}::{condition.name}::{model_id}"
            base = await seed_messages(graph_app, thread_id, messages, model_id)
            # The replay's cost belongs to the condition, not to each model.
            owner = model_id == model_ids[0]
            return await run_condition(graph_app, thread_id, base, scenario, model_id, condition,
                                       model_factory, label, setup_usage=setup if owner else None, spend=spend)

    batches = await asyncio.gather(*(
        one(m, label, sc, cond) for m in model_ids for label, sc in scenarios.items() for cond in conditions
    ), return_exceptions=True)
    # A branch whose replay hit the budget has no results; anything else is a real failure.
    failures = [b for b in batches if isinstance(b, BaseException) and not isinstance(b, BudgetExhausted)]
    if failures:
        raise failures[0]
    return [r for batch in batches if not isinstance(batch, BaseException) for r in batch]


def _add_usage(totals: dict, key: str, usage: Mapping[str, Mapping[str, Any]]) -> None:
    for name, u in usage.items():
        row = totals.setdefault(f"{key} / {name}", {"input_tokens": 0, "output_tokens": 0, "cache_read": 0})
        row["input_tokens"] += u.get("input_tokens", 0)
        row["output_tokens"] += u.get("output_tokens", 0)
        row["cache_read"] += (u.get("input_token_details") or {}).get("cache_read", 0) or 0


def usage_totals(results: Iterable[ProbeResult]) -> dict[str, dict[str, int]]:
    """Summed token usage per condition and provider model name; building the
    branches (live replay summaries) is listed as "<condition> setup"."""
    totals: dict[str, dict[str, int]] = {}
    for r in results:
        _add_usage(totals, r.condition, r.usage)
        _add_usage(totals, f"{r.condition} setup", r.setup_usage)
    return totals


def summarize_results(results: Iterable[ProbeResult]) -> dict[str, Any]:
    """Recall per condition and model, overall and split by fact kind, variant
    and number of summaries the fact went through; `stale` counts answers that
    gave a superseded or rejected value."""
    table: dict[str, Any] = {}
    for r in results:
        row = table.setdefault(f"{r.condition} / {r.model}",
                               {"n": 0, "correct": 0, "stale": 0, "by_kind": {}, "by_variant": {}, "by_compactions": {},
                                "by_stated_by": {}})
        row["n"] += 1
        row["correct"] += r.correct
        row["stale"] += r.stale
        for split, value in (("by_kind", r.kind), ("by_variant", r.variant), ("by_compactions", str(r.compactions)),
                             ("by_stated_by", r.stated_by)):
            cell = row[split].setdefault(value, [0, 0])
            cell[0] += r.correct
            cell[1] += 1
    for row in table.values():
        row["recall"] = round(row["correct"] / row["n"], 3) if row["n"] else None
    return table


def compare_conditions(
    results: Iterable[ProbeResult], a: str, b: str, *, min_effect: float = 0.1
):
    """Does condition `b` recall more than `a`? Paired by (model, fact)."""
    results = list(results)
    arm = lambda name: {r.key: r.correct for r in results if r.condition == name}  # noqa: E731
    return compare_recall(arm(a), arm(b), min_effect=min_effect, label=f"{a} vs {b}")


def results_as_dicts(results: Iterable[ProbeResult]) -> list[dict[str, Any]]:
    return [asdict(r) for r in results]


def results_from_dicts(rows: Iterable[Mapping[str, Any]]) -> list[ProbeResult]:
    return [ProbeResult(**row) for row in rows]


def rescore(results: Iterable[ProbeResult], scenarios: Mapping[str, Scenario]) -> list[ProbeResult]:
    """Score stored answers again (after a scoring fix) against the scenarios
    they came from. Stored answers are truncated to 200 characters, which
    keeps the committed first line."""
    from dataclasses import replace

    facts = {(label, f.key): f for label, sc in scenarios.items() for f in sc.facts}
    out = []
    for r in results:
        fact = facts[(r.scenario, r.fact)]
        out.append(replace(r, correct=is_correct(r.answer, fact), stale=is_stale(r.answer, fact)))
    return out


# ─── Stand-in models ─────────────────────────────────────────────


def _visible_text(messages: Sequence[BaseMessage]) -> str:
    return "\n".join(extract_text(m.content) for m in messages[:-1])


class AvailabilityOracle(BaseChatModel):
    """Answers a probe correctly iff the answer is still in its visible context.

    With `strict`, the value must also still be attached to the fact's
    subject (probe.value_attached): a summary can keep "5592" while losing
    that it was the CDN purge job's port.
    """

    facts: tuple[PlantedFact, ...]
    strict: bool = False

    @property
    def _llm_type(self) -> str:
        return "availability-oracle"

    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        question = extract_text(messages[-1].content) if messages else ""
        # Scenarios with different seeds can ask the same question with
        # different answers; only the one in this context can be found.
        candidates = [f for f in self.facts
                      if f.question in question or (f.indirect_question and f.indirect_question in question)]
        if not candidates:
            reply = "Noted."
        else:
            context = _visible_text(messages)
            if self.strict:
                found = next((f.answers[0] for f in candidates if value_attached(context, f)), None)
            else:
                lowered = context.lower()
                found = next((a for f in candidates for a in f.answers if a.lower() in lowered), None)
            reply = found if found else "I don't know."
        # Report roughly how much it had to read (~4 chars/token), so a dry
        # run shows the input-token side of the trade-off too.
        read = sum(len(extract_text(m.content)) for m in messages) // 4
        message = AIMessage(
            content=reply,
            response_metadata={"model_name": self._llm_type},
            usage_metadata={"input_tokens": read, "output_tokens": 1, "total_tokens": read + 1},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


ORACLE = "oracle"
STRICT_ORACLE = "oracle-strict"
# Pseudo-models answered by an AvailabilityOracle: strict or not.
ORACLES = {ORACLE: False, STRICT_ORACLE: True}


class EvalModelFactory:
    """Routes the pseudo-models in ORACLES to AvailabilityOracle and every other
    id to `inner` — the real factory, or, when None (dry runs), the lossy
    stand-in summarizer. With a real inner factory, the oracle answers from
    real summaries: recall then measures what the summarizer kept (H1),
    independent of whether a model would use it (H2)."""

    def __init__(self, facts: Iterable[PlantedFact], inner=None):
        self.facts = tuple(facts)
        self.inner = inner

    def chat(self, model_id: str, toggles: Optional[Mapping[str, Any]] = None):
        if model_id in ORACLES:
            return AvailabilityOracle(facts=self.facts, strict=ORACLES[model_id])
        if self.inner is None:
            return FirstSentenceSummarizer()
        base, level = split_thinking(model_id)
        model = self.inner.chat(base, toggles)
        return model.bind(thinking_level=level) if level else model


def split_thinking(model_id: str) -> tuple[str, Optional[str]]:
    """"gemini-3.5-flash@minimal" -> ("gemini-3.5-flash", "minimal").

    Experiments only: a summarizer condition with a fixed Gemini thinking
    level (minimal, low, medium, high), applied per call with .bind().
    """
    base, _, level = model_id.partition("@")
    if level and level not in THINKING_LEVELS:
        raise ValueError(f"thinking level must be one of {', '.join(THINKING_LEVELS)}")
    if level and not base.startswith("gemini-"):
        raise ValueError("a thinking level (@...) is only supported for Gemini models")
    return base, level or None


THINKING_LEVELS = ("minimal", "low", "medium", "high")


class FirstSentenceSummarizer(BaseChatModel):
    """A lossy summary: the first sentence of every line of the transcript."""

    @property
    def _llm_type(self) -> str:
        return "first-sentence-summarizer"

    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        transcript = extract_text(messages[-1].content)
        kept = []
        for line in transcript.splitlines():
            if line.startswith("["):
                speaker, _, text = line.partition("]: ")
                kept.append(f"{speaker}]: {text.split('. ')[0].rstrip('.')}.")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="\n".join(kept)))])


class SizedSummarizer(BaseChatModel):
    """A stand-in summary of a fixed size, for estimating what a run will
    read and how often it will summarize, without calling a model."""

    tokens: int

    @property
    def _llm_type(self) -> str:
        return "sized-summarizer"

    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        read = count_tokens(messages)
        message = AIMessage(
            content=" ".join(["detail"] * self.tokens),
            response_metadata={"model_name": self._llm_type},
            usage_metadata={"input_tokens": read, "output_tokens": self.tokens, "total_tokens": read + self.tokens},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


class _SizedFactory:
    def __init__(self, tokens: int):
        self.tokens = tokens

    def chat(self, model_id: str, toggles: Optional[Mapping[str, Any]] = None):
        return SizedSummarizer(tokens=self.tokens)


# ─── Cost estimate ───────────────────────────────────────────────


@dataclass(frozen=True)
class CallProfile:
    """What one real call showed: provider input tokens per token we count
    (tokenizers differ), output tokens per call (answer + thesis update for
    an answering model; reasoning + text for a summarizer), and for a
    summarizer the size of what it wrote."""

    model: str
    input_ratio: float
    output_tokens: float
    summary_tokens: int = 0
    cost: float = 0.0


def summarizer_of(condition: Condition) -> str:
    return condition.summarizer or default_summarizer()


def _sample_transcript(tokens: int) -> str:
    """About `tokens` of dense conversation, formatted as summarize_history does."""
    from app.compaction import build_dense_scenario

    lines, used = [], 0
    for t in build_dense_scenario(seed=97).turns:
        line = ("[User]: " if t.role == "user" else "[assistant]: ") + t.text
        used += count_tokens([HumanMessage(content=line)])
        lines.append(line)
        if used >= tokens:
            break
    return "\n".join(lines)


async def calibrate_summarizer(condition: Condition, factory, spend: Spend, sample_tokens: int) -> CallProfile:
    """One real summary of a threshold-sized transcript."""
    from app.services.graph import summary_instruction_from

    prompt = summary_instruction_from(condition.configure({"configurable": {}})).prompt(_sample_transcript(sample_tokens))
    usage = UsageMetadataCallbackHandler()
    before = spend.total
    reply = await factory.chat(summarizer_of(condition)).ainvoke(
        [HumanMessage(content=prompt)], config={"callbacks": [usage, spend]}
    )
    used = next(iter(usage.usage_metadata.values()))
    return CallProfile(
        model=summarizer_of(condition),
        input_ratio=used["input_tokens"] / count_tokens([HumanMessage(content=prompt)]),
        output_tokens=used["output_tokens"],
        summary_tokens=count_tokens([HumanMessage(content=extract_text(reply.content))]),
        cost=spend.total - before,
    )


async def calibrate_answerer(graph_app, model_id: str, factory, spend: Spend, thread_prefix: str) -> CallProfile:
    """One real probe through the graph on a short conversation, next to the
    oracle on the same conversation: the ratio of their input counts carries
    the oracle's dry-run reading over to this model."""
    from app.compaction import NeverCompact, build_dense_scenario

    scenario = build_dense_scenario(n_facts=1, exchanges=12, seed=98)
    never = Condition("calibrate", NeverCompact())
    counted = {}
    before = spend.total
    for who, f in ((model_id, factory), (ORACLE, EvalModelFactory(scenario.facts))):
        thread = f"{thread_prefix}::calibrate::{model_id}::{who}"
        base = await seed_scenario(graph_app, thread, scenario, model_id)
        [result] = await run_condition(graph_app, thread, base, scenario, who, never, f, spend=spend)
        counted[who] = (sum(u.get("input_tokens", 0) for u in result.usage.values()),
                        sum(u.get("output_tokens", 0) for u in result.usage.values()))
    return CallProfile(
        model=model_id,
        input_ratio=counted[model_id][0] / max(1, counted[ORACLE][0]),
        output_tokens=counted[model_id][1],
        cost=spend.total - before,
    )


HIGH_FACTOR = 1.35


@dataclass
class CostEstimate:
    total: float
    by_condition: dict[str, float]
    by_model: dict[str, float]
    summaries: dict[str, float]
    calibration: float

    @property
    def high(self) -> float:
        """What to plan for. Later summaries fold in the previous one, so
        they read and reason more than the one calibration call, and real
        answers are longer than the oracle's. Back-tested on pilot 2c: the
        estimate was $6.27, the run cost $8.28 (×1.32)."""
        return self.total * HIGH_FACTOR


async def estimate_cost(
    graph_app,
    scenarios: dict[str, Scenario],
    model_ids: Sequence[str],
    conditions: Sequence[Condition],
    prices,
    answerers: Mapping[str, CallProfile],
    summarizers: Mapping[str, CallProfile],
    *,
    thread_prefix: str,
    calibration_cost: float = 0.0,
    grid=None,
) -> CostEstimate:
    """Dry-run every condition with the oracle answering and a stand-in
    summary of the calibrated size: that gives exactly what each probe reads
    and how many summaries are written (shared replay, plus per-branch ones
    while probing). Priced with the calibrated profiles.

    `summarizers` is keyed by condition name; `answerers` by model id.
    """
    facts = [f for sc in scenarios.values() for f in sc.facts]
    branches = len(model_ids)  # every answering model, oracles included, probes each condition
    real = [m for m in model_ids if m not in ORACLES]
    by_condition: dict[str, float] = {}
    by_model: dict[str, float] = {}
    summaries: dict[str, float] = {}
    for condition in conditions:
        dry = await (grid or run_live_grid)(
            graph_app, scenarios, [ORACLE], [condition],
            thread_prefix=f"{thread_prefix}::estimate", model_factory=EvalModelFactory(
                facts, inner=_SizedFactory(summarizers[condition.name].summary_tokens if condition.name in summarizers else 0)),
        )
        read = sum(u.get("input_tokens", 0) for r in dry for n, u in r.usage.items() if n == "availability-oracle")
        probes = len(dry)
        cost = 0.0
        for m in real:
            p, price = answerers[m], prices.price(m)
            c = price.cost(int(read * p.input_ratio), int(probes * p.output_tokens))
            by_model[m] = by_model.get(m, 0.0) + c
            cost += c
        if condition.name in summarizers:
            s = summarizers[condition.name]
            setup = [u for r in dry for n, u in r.setup_usage.items() if n == "sized-summarizer"]
            during = [u for r in dry for n, u in r.usage.items() if n == "sized-summarizer"]
            calls = (sum(u["output_tokens"] for u in setup) + branches * sum(u["output_tokens"] for u in during)) / max(1, s.summary_tokens)
            read_in = sum(u["input_tokens"] for u in setup) + branches * sum(u["input_tokens"] for u in during)
            price = prices.price(split_thinking(s.model)[0])
            c = price.cost(int(read_in * s.input_ratio), int(calls * s.output_tokens))
            summaries[condition.name] = calls
            by_model[s.model] = by_model.get(s.model, 0.0) + c
            cost += c
        by_condition[condition.name] = cost
    return CostEstimate(sum(by_condition.values()), by_condition, by_model, summaries, calibration_cost)


def cheapest_models(registry: Mapping[str, Mapping[str, Any]], catalog: Mapping[str, Any], prices) -> list[str]:
    """Per provider family, the offered, verified, priced model that is
    cheapest to read with (input price first: experiments are input-heavy)."""
    best: dict[str, tuple] = {}
    for model_id, cfg in registry.items():
        entry = catalog.get(model_id)
        price = prices.price(model_id)
        if cfg.get("desc") == "Legacy" or price is None or entry is None or not entry.usable:
            continue
        key = (price.input, price.output)
        if cfg["family"] not in best or key < best[cfg["family"]][0]:
            best[cfg["family"]] = (key, model_id)
    return [model_id for _, model_id in sorted(best.values(), key=lambda kv: kv[1])]


def cached_embedder(embed_documents, size: int = 20_000):
    """Wraps a batch embedding function with a per-text cache: recall embeds
    the same hidden messages on every probe."""
    cache: dict[str, list[float]] = {}
    lock = threading.Lock()

    def embed(texts: Sequence[str]) -> list[list[float]]:
        with lock:
            missing = [t for t in dict.fromkeys(texts) if t not in cache]
        if missing:
            vectors = embed_documents(missing)
            with lock:
                if len(cache) > size:
                    cache.clear()
                cache.update(zip(missing, vectors))
        with lock:
            return [cache[t] for t in texts]

    return embed


REWRITE_PROMPT = (
    "Earlier parts of this conversation are hidden. What is still visible about them:\n{hint}\n\n"
    "A new question: {query}\n\n"
    "Which topics or subjects from the earlier conversation is this question about? Reply with their exact "
    "names and the key terms to search for, on one line, nothing else."
)


def model_rewriter(factory, model_id: str):
    """A GuidedRecall rewrite step backed by a chat model from `factory`."""

    def rewrite(query: str, hint: str) -> str:
        reply = factory.chat(model_id).invoke([HumanMessage(content=REWRITE_PROMPT.format(hint=hint[:8000], query=query))])
        return extract_text(reply.content)

    return rewrite
