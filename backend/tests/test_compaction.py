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
    compare_conditions,
    run_experiment,
    summarize_results,
)

BUDGET = ModelBudget("gpt-5.4", soft_limit=10_000)


def snap(total, since=None, messages=20, since_msgs=None, summary=0):
    return ContextSnapshot(total, total if since is None else since, messages, since_msgs, summary)


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


def test_a_summary_larger_than_the_threshold_does_not_retrigger_itself():
    p = ThresholdPolicy()  # limit 10,000
    # Small summary: due when summary + new passes the limit, as before.
    assert not p.should_summarize(snap(30_000, since=10_000, since_msgs=8, summary=2_000), BUDGET)
    assert p.should_summarize(snap(30_000, since=10_001, since_msgs=8, summary=2_000), BUDGET)
    # A 12k summary alone is over the limit; still wait for half a limit of new text.
    assert not p.should_summarize(snap(30_000, since=13_000, since_msgs=8, summary=12_000), BUDGET)
    assert not p.should_summarize(snap(30_000, since=17_000, since_msgs=8, summary=12_000), BUDGET)
    assert p.should_summarize(snap(30_000, since=17_001, since_msgs=8, summary=12_000), BUDGET)
    # The floor is a knob.
    eager = ThresholdPolicy(min_new_fraction=0.1)
    assert eager.should_summarize(snap(30_000, since=13_001, since_msgs=8, summary=12_000), BUDGET)


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

    # Judged as a paired comparison: never-compacting recalls more.
    verdict = compare_conditions(results, "t2000", "never", min_effect=0.1)
    assert verdict.outcome.value == "b_better"
    assert verdict.interval[0] > 0

    # And the cost side: compacted calls read far fewer input tokens.
    def read(cond):
        return sum(u["input_tokens"] for r in results if r.condition == cond for u in r.usage.values())
    assert read("t2000") < read("never") / 2


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


def test_compare_recall_outcomes():
    from app.compaction import compare_recall

    keys = [f"f{i}" for i in range(20)]
    worse = {k: i < 6 for i, k in enumerate(keys)}
    better = {k: i < 18 for i, k in enumerate(keys)}
    assert compare_recall(worse, better).outcome.value == "b_better"
    assert compare_recall(better, worse).outcome.value == "a_better"
    # Identical results carry no evidence either way: not "equivalent".
    same = compare_recall(better, better)
    assert same.outcome.value in ("insufficient", "no_detectable_diff")


# ─── Dense scenarios, live compaction ────────────────────────────


def test_dense_scenario_plants_every_statement_once_and_in_order():
    from app.compaction import build_dense_scenario

    a, b = build_dense_scenario(seed=5), build_dense_scenario(seed=5)
    assert [t.text for t in a.turns] == [t.text for t in b.turns]
    assert {f.variant for f in a.facts} == {"plain", "distractor", "update"}
    text = "\n".join(t.text for t in a.turns)
    for fact in a.facts:
        assert text.count(fact.statement) == 1
        assert a.turns[a.positions[fact.key]].role == "user"
        extra_positions = a.extra_positions.get(fact.key, [])
        assert len(extra_positions) == len(fact.extras)
        for extra, pos in zip(fact.extras, extra_positions):
            assert text.count(extra) == 1 and extra in a.turns[pos].text
            if fact.variant == "update":
                assert pos < a.positions[fact.key]  # the old value comes first
        # One right answer: no accepted or stale value leaks into filler.
        for value in fact.answers + fact.stale:
            holders = [t.text for t in a.turns if value.lower() in t.text.lower()]
            assert all(fact.statement in h or any(e in h for e in fact.extras) for h in holders), value


def test_stale_values_make_an_answer_wrong():
    from app.compaction import PlantedFact, is_stale

    fact = PlantedFact("port", "port", "moved to 6610", "Which port?", ("6610",), stale=("6254",), variant="update")
    assert is_correct("6610", fact) and not is_stale("6610", fact)
    assert not is_correct("6254", fact) and is_stale("6254", fact)
    # Only the committed first line counts: quoting the source afterwards is fine,
    # listing both candidates without choosing is not.
    assert is_correct("6610\n\nIt said: 'moved from 6254 to 6610'", fact)
    assert not is_correct("I found two ports:\n1. 6254\n2. 6610", fact)
    assert is_correct("<answer>6610</answer>", fact)


def test_run_may_choose_the_summarizer():
    from langchain_core.messages import AIMessage, HumanMessage

    asked = []

    class Stub:
        def invoke(self, _msgs):
            return AIMessage(content="gist")

    factory = CallableModelFactory(lambda m, _t: asked.append(m) or Stub())
    messages = [HumanMessage(content=f"m{i}") for i in range(12)]
    config = {"configurable": {
        "model_factory": factory,
        "compaction_policy": ThresholdPolicy(fixed_tokens(1)),
        graph_mod.SUMMARIZER_CONFIG_KEY: "claude-haiku-4-5-20251001",
    }}
    graph_mod.summarize_history({"messages": messages, "active_peer": "gpt-5.4"}, config)
    assert asked == ["claude-haiku-4-5-20251001"]


@pytest.mark.asyncio
async def test_live_replay_summarizes_repeatedly_and_shares_summaries(eval_setup):
    from app.compaction import build_dense_scenario
    from app.services.compaction_eval import ORACLE, EvalModelFactory, run_live_grid

    app, _ = eval_setup
    scenario = build_dense_scenario(n_facts=8, exchanges=40, seed=1)
    factory = EvalModelFactory(scenario.facts)  # oracle answers, stand-in summarizes
    results = await run_live_grid(
        app, {"1": scenario}, [ORACLE],
        [Condition("never", NeverCompact()), Condition("t1500", ThresholdPolicy(fixed_tokens(1_500)))],
        model_factory=factory,
    )
    never = [r for r in results if r.condition == "never"]
    live = [r for r in results if r.condition == "t1500"]
    assert all(r.correct and r.compactions == 0 for r in never)
    # Early facts went through several summaries; the stand-in keeps none of them.
    assert max(r.compactions for r in live) >= 3
    assert not any(r.correct for r in live if r.compactions >= 2)


@pytest.mark.asyncio
async def test_live_replay_with_a_growing_summary_does_not_thrash():
    """A summarizer whose output keeps growing past the threshold (as
    gemini-3.5-flash's did in pilot 2) must not re-summarize every turn."""
    from langchain_core.messages import AIMessage

    from app.compaction import build_dense_scenario
    from app.services.compaction_eval import replay_with_compaction

    class Bloated:
        calls = 0

        def invoke(self, _msgs):
            Bloated.calls += 1
            return AIMessage(content="kept detail " * (1_000 + 200 * Bloated.calls))

    scenario = build_dense_scenario(n_facts=8, exchanges=60, seed=2)  # ~10k tokens
    factory = CallableModelFactory(lambda *_: Bloated())
    messages, _ = await replay_with_compaction(
        scenario, Condition("t2000", ThresholdPolicy(fixed_tokens(2_000))), "gpt-5.4", factory
    )
    summaries = sum(graph_mod.SUMMARY_MARKER in m.content for m in messages if m.type == "system")
    # ~10k tokens at >=1k new per summary: about ten, not one per user turn (60).
    assert 3 <= summaries <= 12


def test_eval_factory_applies_a_gemini_thinking_level():
    from app.services.compaction_eval import EvalModelFactory, split_thinking

    bound = []

    class Model:
        def bind(self, **kw):
            bound.append(kw)
            return self

    inner = CallableModelFactory(lambda m, _t: Model())
    factory = EvalModelFactory([], inner=inner)
    factory.chat("gemini-3.5-flash@minimal")
    factory.chat("gemini-3.5-flash")
    assert bound == [{"thinking_level": "minimal"}]
    assert split_thinking("gemini-3.5-flash") == ("gemini-3.5-flash", None)
    with pytest.raises(ValueError):
        split_thinking("gemini-3.5-flash@huge")
    with pytest.raises(ValueError):
        split_thinking("gpt-5.4-nano@low")
