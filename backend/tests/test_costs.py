"""Prices, spend tracking, the budget stop and the pre-run estimate."""

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langgraph.checkpoint.memory import MemorySaver

from app.catalog import ModelPrice, Price, PriceBook
from app.compaction import NeverCompact, ThresholdPolicy, build_dense_scenario, fixed_tokens
from app.services import graph as graph_mod
from app.services.compaction_eval import (
    ORACLE,
    CallProfile,
    Condition,
    EvalModelFactory,
    Spend,
    cheapest_models,
    estimate_cost,
    model_rewriter,
    run_live_grid,
)

BOOK = PriceBook({
    "cheap-1": ModelPrice(Price(1.0, 10.0, cached_input=0.1), source="test"),
    "cheap-1-mini": ModelPrice(Price(0.5, 2.0), source="test"),
    "promo": ModelPrice(Price(1.0, 1.0), source="test", until="2026-12-31", after=Price(2.0, 2.0)),
}, day="2026-09-27")


def test_price_lookup_resolves_snapshots_and_dates():
    assert BOOK.resolve("cheap-1-2026-03-17") == "cheap-1"
    assert BOOK.resolve("cheap-1-mini-2026-03-17") == "cheap-1-mini"  # longest id wins
    assert BOOK.resolve("models/cheap-1") == "cheap-1"
    assert BOOK.resolve("other") is None
    assert BOOK.price("promo").input == 1.0
    assert PriceBook(BOOK._prices, day="2027-01-01").price("promo").input == 2.0


def test_cost_counts_cached_input_at_the_cache_price():
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000, "input_token_details": {"cache_read": 400_000}}
    assert BOOK.cost("cheap-1", usage) == pytest.approx(0.6 + 0.04 + 1.0)
    assert BOOK.cost("unknown", usage) is None


def _result(name, inp, out):
    msg = AIMessage(content="x", response_metadata={"model_name": name},
                    usage_metadata={"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out})
    return LLMResult(generations=[[ChatGeneration(message=msg)]])


def test_spend_prices_calls_and_reports_unpriced_ones():
    spend = Spend(BOOK, limit=1.0)
    spend.on_llm_end(_result("cheap-1-2026-03-17", 500_000, 0))
    spend.on_llm_end(_result("availability-oracle", 10**9, 0))  # stand-ins are free
    spend.on_llm_end(_result("mystery", 10, 10))
    assert spend.total == pytest.approx(0.5) and not spend.exhausted
    assert spend.unpriced == {"mystery": 1}
    spend.on_llm_end(_result("cheap-1", 500_000, 0))
    assert spend.exhausted


@pytest.fixture
def graph_app(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.database.DB_PATH", str(tmp_path / "costs.sqlite"))
    return graph_mod.workflow.compile(checkpointer=MemorySaver())


@pytest.mark.asyncio
async def test_a_run_stops_starting_calls_once_the_budget_is_spent(graph_app):
    scenario = build_dense_scenario(n_facts=8, exchanges=30, seed=3)
    spend = Spend(BOOK, limit=0.0)  # already exhausted
    results = await run_live_grid(
        graph_app, {"3": scenario}, [ORACLE], [Condition("t1500", ThresholdPolicy(fixed_tokens(1_500)))],
        model_factory=EvalModelFactory(scenario.facts), spend=spend,
    )
    assert results == []  # the replay refused to summarize; nothing ran


@pytest.mark.asyncio
async def test_estimate_prices_the_dry_run_with_calibrated_profiles(graph_app):
    scenario = build_dense_scenario(n_facts=8, exchanges=40, seed=4)
    conditions = [Condition("never", NeverCompact()), Condition("t2000", ThresholdPolicy(fixed_tokens(2_000)), "cheap-1")]
    answerers = {"cheap-1-mini": CallProfile("cheap-1-mini", input_ratio=1.2, output_tokens=300)}
    summarizers = {"t2000": CallProfile("cheap-1", input_ratio=1.0, output_tokens=5_000, summary_tokens=800)}
    est = await estimate_cost(graph_app, {"4": scenario}, ["cheap-1-mini", ORACLE], conditions, BOOK,
                              answerers, summarizers, thread_prefix="est")
    assert set(est.by_condition) == {"never", "t2000"}
    # Never compacting reads more than compacting; summaries are counted only where they happen.
    never_read = est.by_model  # sanity: both models priced
    assert "cheap-1-mini" in never_read and "cheap-1" in never_read
    assert est.summaries["t2000"] >= 2 and "never" not in est.summaries
    assert est.by_condition["never"] > 0 and est.high >= est.total


@pytest.mark.asyncio
@pytest.mark.parametrize("wrap", [False, True])
async def test_estimate_meters_the_recall_rewriter_without_calling_it(graph_app, wrap):
    from app.compaction import GuidedRecall, SentenceRecall

    class Forbidden:
        def chat(self, model_id, toggles=None):
            raise AssertionError("an estimate called a real rewriter")

    scenario = build_dense_scenario(n_facts=8, exchanges=40, seed=4)
    policy = ThresholdPolicy(fixed_tokens(2_000))
    recall = GuidedRecall(model_rewriter(Forbidden(), "cheap-1-mini"))
    conditions = [Condition("t2000-guided", policy, "cheap-1", recall=SentenceRecall(recall) if wrap else recall)]
    summarizers = {"t2000-guided": CallProfile("cheap-1", input_ratio=1.0, output_tokens=5_000, summary_tokens=800)}
    rewriters = {"cheap-1-mini": CallProfile("cheap-1-mini", input_ratio=1.0, output_tokens=200)}
    est = await estimate_cost(graph_app, {"4": scenario}, [ORACLE], conditions, BOOK, {}, summarizers,
                              thread_prefix="est", rewriters=rewriters)
    assert est.by_model["cheap-1-mini"] > 0


def test_default_models_are_the_cheapest_offered_per_family():
    class Entry:
        usable = True

    registry = {
        "cheap-1": {"family": "a"}, "cheap-1-mini": {"family": "a"},
        "promo": {"family": "b"}, "old": {"family": "b", "desc": "Legacy"},
    }
    catalog = {k: Entry() for k in registry}
    assert cheapest_models(registry, catalog, BOOK) == ["cheap-1-mini", "promo"]


def test_a_failed_model_call_halts_the_run():
    spend = Spend(BOOK, limit=100.0)
    assert not spend.exhausted
    spend.on_llm_error(RuntimeError("429 RESOURCE_EXHAUSTED: monthly spending cap"))
    assert spend.exhausted
    with pytest.raises(Exception, match="a model call failed"):
        spend.check()


def test_conditions_are_admitted_cheapest_first_within_the_budget():
    from app.compaction import NeverCompact
    from app.services.compaction_eval import HIGH_FACTOR, admit

    conds = [Condition(n, NeverCompact()) for n in ("big", "small", "medium")]
    order, skipped = admit(conds, {"big": 3.0, "small": 0.5, "medium": 1.0}, spent=0.2, limit=0.2 + 1.5 * HIGH_FACTOR)
    assert [c.name for c in order] == ["small", "medium"] and skipped == ["big"]


def test_the_planning_margin_is_learned_from_past_runs():
    from app.services.compaction_eval import HIGH_FACTOR, planning_factor

    assert planning_factor([]) == HIGH_FACTOR
    runs = [{"spend": {"total": r, "estimate": 1.0}} for r in (0.6, 0.8, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.7, 1.8)]
    assert planning_factor(runs) == 1.8
    assert planning_factor([{"spend": {"total": 0.5, "estimate": 1.0}}]) == HIGH_FACTOR  # never below the floor


def test_calibration_profiles_are_reused_for_the_day(tmp_path):
    from app.services.compaction_eval import CalibrationCache

    path = tmp_path / "cache.json"
    today = CalibrationCache(path, "2026-09-28")
    assert today.get("summarizer:x:brief:8000") is None
    today.put("summarizer:x:brief:8000", CallProfile("x", 1.1, 900.0, 3000, 0.02))
    again = CalibrationCache(path, "2026-09-28")
    assert again.get("summarizer:x:brief:8000") == CallProfile("x", 1.1, 900.0, 3000, 0.02)
    assert CalibrationCache(path, "2026-09-29").get("summarizer:x:brief:8000") is None  # stale next day


@pytest.mark.asyncio
async def test_a_rejected_answer_stops_the_run_and_keeps_the_request(graph_app, tmp_path):
    """A provider rejecting the answering call (OpenAI's invalid_prompt, say)
    used to escape run_live_grid as an exception, losing the spend report and
    any trace of which request it was."""
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from app.llm import CallableModelFactory
    from app.services.compaction_eval import write_failures

    class Rejecting(FakeListChatModel):
        def _call(self, *args, **kwargs):
            raise ValueError("Invalid prompt: flagged")

        async def _acall(self, *args, **kwargs):
            raise ValueError("Invalid prompt: flagged")

    scenario = build_dense_scenario(n_facts=4, exchanges=10, seed=3)
    spend = Spend(BOOK, limit=100.0)
    factory = CallableModelFactory(lambda *_: Rejecting(responses=["unused"]))
    results = await run_live_grid(
        graph_app, {"3": scenario}, ["gpt-6-luna"], [Condition("never", NeverCompact())],
        model_factory=factory, spend=spend,
    )
    assert results == []
    assert spend.exhausted and "Invalid prompt" in spend.errors[0]
    failure = spend.failures[0]
    assert failure["node"] == "draft" and "Invalid prompt" in failure["error"]
    assert failure["last_human"]  # the rejected request, to read locally

    saved = write_failures(spend, tmp_path / "failed.json")
    assert saved and "last_human" in (tmp_path / "failed.json").read_text()
    assert write_failures(Spend(BOOK), tmp_path / "none.json") is None
