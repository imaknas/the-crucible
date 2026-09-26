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
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, List, Mapping, Optional, Sequence

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda

from app.compaction import CompactionPolicy, PlantedFact, Scenario, compare_recall, is_correct
from app.compaction.probe import is_stale
from app.services.graph import (
    POLICY_CONFIG_KEY,
    SUMMARIZER_CONFIG_KEY,
    SUMMARY_MARKER,
    compaction_policy_from,
    context_snapshot,
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

    def configure(self, config: dict) -> dict:
        config["configurable"][POLICY_CONFIG_KEY] = self.policy
        if self.summarizer:
            config["configurable"][SUMMARIZER_CONFIG_KEY] = self.summarizer
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

    @property
    def key(self) -> str:
        """Pairs the same probe across conditions."""
        return f"{self.model}:{self.scenario}:{self.fact}"


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
) -> tuple[List[BaseMessage], dict]:
    """The conversation as the app would have stored it, summaries included.

    Turn by turn, the graph's own summarize step runs whenever a user message
    arrives (as it does at the start of every turn in the app), under the
    condition's policy and summarizer. No answering model is called. Returns
    the messages and the summarizer's token usage.
    """
    usage = UsageMetadataCallbackHandler()
    config = condition.configure({"configurable": {}, "callbacks": [usage]})
    if model_factory is not None:
        config["configurable"]["model_factory"] = model_factory
    summarize = RunnableLambda(summarize_history)
    messages: List[BaseMessage] = []
    for message in scenario_messages(scenario, assistant_name):
        messages.append(message)
        if message.type == "human":
            out = await summarize.ainvoke({"messages": list(messages), "active_peer": active_peer}, config)
            messages += out["messages"]
    return messages, {name: dict(u) for name, u in usage.usage_metadata.items()}


def _compactions_since(messages: Sequence[BaseMessage], statement: str) -> int:
    """Summaries after the first message stating `statement`."""
    texts = [extract_text(m.content) for m in messages]
    start = next((i for i, (m, t) in enumerate(zip(messages, texts)) if m.type == "human" and statement in t), None)
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
) -> list[ProbeResult]:
    """Ask every probe, in order, on one branch forked from the seeded checkpoint."""
    results: list[ProbeResult] = []
    parent = base_checkpoint_id
    for fact in scenario.facts:
        config = condition.configure(thread_config(thread_id, parent))
        run_id = tag_run(config)
        if model_factory is not None:
            config["configurable"]["model_factory"] = model_factory
        usage = UsageMetadataCallbackHandler()
        config["callbacks"] = [usage]

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
                    graph_app, thread_id, base, scenario, model_id, condition, model_factory, label
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
            return await replay_with_compaction(scenario, condition, model_ids[0], model_factory)

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
                                       model_factory, label, setup_usage=setup if owner else None)

    batches = await asyncio.gather(*(
        one(m, label, sc, cond) for m in model_ids for label, sc in scenarios.items() for cond in conditions
    ))
    return [r for batch in batches for r in batch]


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
                               {"n": 0, "correct": 0, "stale": 0, "by_kind": {}, "by_variant": {}, "by_compactions": {}})
        row["n"] += 1
        row["correct"] += r.correct
        row["stale"] += r.stale
        for split, value in (("by_kind", r.kind), ("by_variant", r.variant), ("by_compactions", str(r.compactions))):
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
    """Answers a probe correctly iff the answer is still in its visible context."""

    facts: tuple[PlantedFact, ...]

    @property
    def _llm_type(self) -> str:
        return "availability-oracle"

    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        question = extract_text(messages[-1].content) if messages else ""
        # Scenarios with different seeds can ask the same question with
        # different answers; only the one in this context can be found.
        candidates = [f for f in self.facts if f.question in question]
        if not candidates:
            reply = "Noted."
        else:
            context = _visible_text(messages).lower()
            found = next((a for f in candidates for a in f.answers if a.lower() in context), None)
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


class EvalModelFactory:
    """Routes the pseudo-model "oracle" to AvailabilityOracle and every other
    id to `inner` — the real factory, or, when None (dry runs), the lossy
    stand-in summarizer. With a real inner factory, the oracle answers from
    real summaries: recall then measures what the summarizer kept (H1),
    independent of whether a model would use it (H2)."""

    def __init__(self, facts: Iterable[PlantedFact], inner=None):
        self.facts = tuple(facts)
        self.inner = inner

    def chat(self, model_id: str, toggles: Optional[Mapping[str, Any]] = None):
        if model_id == ORACLE:
            return AvailabilityOracle(facts=self.facts)
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
