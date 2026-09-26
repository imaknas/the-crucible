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
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, List, Optional, Sequence

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.compaction import CompactionPolicy, PlantedFact, Scenario, compare_recall, is_correct
from app.services.graph import SUMMARY_MARKER, compaction_policy_from, context_snapshot, model_budget
from app.services.runs import final_state_of_run, tag_run, thread_config
from app.utils.helpers import extract_text


@dataclass(frozen=True)
class Condition:
    name: str
    policy: CompactionPolicy


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

    @property
    def key(self) -> str:
        """Pairs the same probe across conditions."""
        return f"{self.model}:{self.fact}"


async def seed_scenario(graph_app, thread_id: str, scenario: Scenario, model_id: str) -> str:
    """Write the scenario's turns into a thread without calling any model."""
    messages: List[BaseMessage] = [
        HumanMessage(content=t.text) if t.role == "user" else AIMessage(content=t.text, name=model_id)
        for t in scenario.turns
    ]
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


async def run_condition(
    graph_app,
    thread_id: str,
    base_checkpoint_id: str,
    scenario: Scenario,
    model_id: str,
    condition: Condition,
    model_factory=None,
) -> list[ProbeResult]:
    """Ask every probe, in order, on one branch forked from the seeded checkpoint."""
    results: list[ProbeResult] = []
    parent = base_checkpoint_id
    for fact in scenario.facts:
        config = thread_config(thread_id, parent)
        run_id = tag_run(config)
        config["configurable"]["compaction_policy"] = condition.policy
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


def summarize_results(results: Iterable[ProbeResult]) -> dict[str, Any]:
    """Recall per condition and model, overall and split by fact kind."""
    table: dict[str, Any] = {}
    for r in results:
        row = table.setdefault(f"{r.condition} / {r.model}", {"n": 0, "correct": 0, "by_kind": {}})
        row["n"] += 1
        row["correct"] += r.correct
        kind = row["by_kind"].setdefault(r.kind, [0, 0])
        kind[0] += r.correct
        kind[1] += 1
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
        fact = next((f for f in self.facts if f.question in question), None)
        if fact is None:
            reply = "Noted."
        else:
            context = _visible_text(messages).lower()
            found = next((a for a in fact.answers if a.lower() in context), None)
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
