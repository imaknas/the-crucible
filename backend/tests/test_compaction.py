"""Compaction policies, retention scenarios, and the end-to-end cliff."""

import ast
import pathlib

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.api.models import SUMMARIZER_MODELS
from app.compaction import (
    DEFAULT_FACTS,
    ContextSnapshot,
    ModelBudget,
    NeverCompact,
    ThresholdPolicy,
    build_scenario,
    fixed_tokens,
    fraction_of_limit,
    is_correct,
)
from app.llm import CallableModelFactory
from app.services import graph as graph_mod
from app.services.compaction_eval import (
    AvailabilityOracle,
    Condition,
    FirstSentenceSummarizer,
    run_experiment,
    summarize_results,
)

BUDGET = ModelBudget("gpt-5.4", soft_limit=10_000)


def snap(total, since=None, messages=20, since_msgs=None):
    return ContextSnapshot(total, total if since is None else since, messages, since_msgs)


# ─── The package stays portable ──────────────────────────────────


def test_compaction_package_imports_nothing_from_the_app():
    pkg = pathlib.Path(__file__).parents[1] / "app" / "compaction"
    for path in pkg.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                assert not (name.startswith("app.") and not name.startswith("app.compaction")), (
                    f"{path.name} imports {name}; app/compaction must stay extractable"
                )


# ─── Policies ────────────────────────────────────────────────────


def test_threshold_policy_matches_the_original_rules():
    p = ThresholdPolicy()
    assert not p.should_summarize(snap(50_000, messages=4), BUDGET)  # too few messages
    assert not p.should_summarize(snap(50_000, since_msgs=3), BUDGET)  # summarized recently
    assert not p.should_summarize(snap(9_000), BUDGET)
    assert p.should_summarize(snap(50_000, since=12_000, since_msgs=8), BUDGET)
    assert not p.should_summarize(snap(50_000, since=8_000, since_msgs=8), BUDGET)
    assert p.should_prune(snap(10_001), BUDGET) and not p.should_prune(snap(10_000), BUDGET)


def test_thresholds_are_pluggable():
    assert ThresholdPolicy(fixed_tokens(2_000)).should_prune(snap(2_001), BUDGET)
    assert not ThresholdPolicy(fraction_of_limit(0.5)).should_prune(snap(5_000), BUDGET)
    assert ThresholdPolicy(fraction_of_limit(0.5)).should_prune(snap(5_001), BUDGET)
    never = NeverCompact()
    assert not never.should_summarize(snap(10**9), BUDGET) and not never.should_prune(snap(10**9), BUDGET)


def test_graph_uses_injected_policy_else_default():
    custom = NeverCompact()
    assert graph_mod.compaction_policy_from({"configurable": {"compaction_policy": custom}}) is custom
    assert isinstance(graph_mod.compaction_policy_from({}), ThresholdPolicy)


# ─── Scenarios ───────────────────────────────────────────────────


def test_scenario_is_deterministic_and_buries_facts_mid_message():
    a, b = build_scenario(seed=3), build_scenario(seed=3)
    assert [t.text for t in a.turns] == [t.text for t in b.turns]
    assert len(a.turns) == 80 and set(a.positions) == {f.key for f in DEFAULT_FACTS}
    for fact in DEFAULT_FACTS:
        turn = a.turns[a.positions[fact.key]]
        assert turn.role == "user" and fact.statement in turn.text
        assert not turn.text.startswith(fact.statement)


def test_scoring_normalizes():
    fact = next(f for f in DEFAULT_FACTS if f.key == "quote")
    assert is_correct("They said: “Latency first, features second.”", fact)
    budget = next(f for f in DEFAULT_FACTS if f.key == "budget")
    assert is_correct("47300 EUR", budget) and not is_correct("about 50k", budget)


# ─── End to end: the cliff ───────────────────────────────────────


@pytest.fixture
def eval_setup(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.database.DB_PATH", str(tmp_path / "eval.sqlite"))
    app = graph_mod.workflow.compile(checkpointer=MemorySaver())

    def models(model_id, _toggles):
        if model_id in SUMMARIZER_MODELS:
            return FirstSentenceSummarizer()
        return AvailabilityOracle(facts=DEFAULT_FACTS)

    return app, CallableModelFactory(models)


@pytest.mark.asyncio
async def test_summarizing_past_the_threshold_drops_buried_details(eval_setup):
    app, factory = eval_setup
    # The last fact sits in the final exchange, inside the verbatim tail.
    scenario = build_scenario(exchanges=30, fact_exchanges=[0, 4, 8, 12, 16, 20, 24, 29])
    results = await run_experiment(
        app,
        scenario,
        ["gpt-5.4"],
        [Condition("never", NeverCompact()), Condition("t2000", ThresholdPolicy(fixed_tokens(2_000)))],
        model_factory=factory,
    )
    table = summarize_results(results)
    assert table["never / gpt-5.4"]["recall"] == 1.0
    compacted = [r for r in results if r.condition == "t2000"]
    assert all(r.pruned and r.summarized for r in compacted)
    lost = {r.fact for r in compacted if not r.correct}
    kept = {r.fact for r in compacted if r.correct}
    # Everything buried before the tail is gone; the tail fact survives.
    assert "vendor" in kept
    assert {"budget", "reviewer", "key_label", "no_kafka", "freeze", "port", "quote"} <= lost


def test_resummarizing_folds_in_the_previous_verbatim_window():
    """The window a summary leaves verbatim must reach the next summary, or it
    is lost once it scrolls out of view."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    from app.llm import CallableModelFactory

    seen = []

    class Recorder:
        def invoke(self, msgs):
            seen.append(msgs[0].content)
            return AIMessage(content="new summary")

    window = [HumanMessage(content=f"window {i}") for i in range(5)]
    later = [AIMessage(content=f"later {i}") for i in range(8)]
    messages = [
        HumanMessage(content="ancient"),
        *window,
        SystemMessage(content="PREVIOUS CONTEXT SUMMARY: the old gist"),
        *later,
    ]
    config = {"configurable": {
        "model_factory": CallableModelFactory(lambda *_: Recorder()),
        "compaction_policy": ThresholdPolicy(fixed_tokens(1)),
    }}
    out = graph_mod.summarize_history({"messages": messages, "active_peer": "gpt-5.4"}, config)
    prompt = seen[0]
    assert "the old gist" in prompt
    assert all(f"window {i}" in prompt for i in range(5))
    assert "later 0" in prompt and "later 7" not in prompt  # newest 5 stay verbatim
    assert "ancient" not in prompt  # already inside the old summary
    assert "new summary" in out["messages"][0].content
