"""Scaffolding must keep beating its baseline, or be flagged for removal."""

import asyncio

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.compaction import build_dense_scenario
from app.services import graph as graph_mod
from app.services import scaffold_audit as sa
from app.services.compaction_eval import STRICT_ORACLE, EvalModelFactory, run_live_grid


def test_verdicts_follow_the_claim():
    assert sa.verdict(sa.IMPROVES, "b_better") == "keep"
    assert sa.verdict(sa.IMPROVES, "equivalent") == "retire"  # no longer earns its place
    assert sa.verdict(sa.IMPROVES, "a_better") == "harmful"
    assert sa.verdict(sa.IMPROVES, "no_detectable_diff") == "inconclusive"
    assert sa.verdict(sa.NON_INFERIOR, "equivalent") == "keep"  # compaction only has to not lose detail
    assert sa.verdict(sa.NON_INFERIOR, "a_better") == "harmful"


def test_every_scaffold_names_its_baseline():
    scaffolds = sa.app_scaffolds(8000, rewriter=lambda q, h: q)
    names = [s.name for s in scaffolds]
    assert len(names) == len(set(names))
    for s in scaffolds:
        assert s.baseline.name != s.treatment.name and s.claim in (sa.IMPROVES, sa.NON_INFERIOR) and s.why
    conditions = sa.conditions_for(scaffolds)
    assert len({c.name for c in conditions}) == len(conditions)  # shared baselines run once


def test_history_and_staleness(tmp_path):
    path = tmp_path / "history.jsonl"
    assert sa.staleness([], summarizer="m", catalog_synced=None) == "scaffolding has never been audited"
    sa.append_history([{"scaffold": "compaction", "model": "x", "verdict": "keep"}], {"summarizer": "m"}, path)
    history = sa.load_history(path)
    assert history[0]["scaffold"] == "compaction" and history[0]["summarizer"] == "m" and history[0]["date"]
    assert sa.staleness(history, summarizer="m", catalog_synced=None) is None
    assert "summarizer changed" in sa.staleness(history, summarizer="other", catalog_synced=None)
    assert "synced" in sa.staleness(history, summarizer="m", catalog_synced="2999-01-01")


@pytest.fixture
def graph_app(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.database.DB_PATH", str(tmp_path / "audit.sqlite"))
    return graph_mod.workflow.compile(checkpointer=MemorySaver())


def test_audit_flags_a_lossy_compaction_as_harmful(graph_app):
    """With a stand-in summary that keeps no facts, compaction loses detail
    against the full history, so it must not be kept."""
    scenario = build_dense_scenario(n_facts=8, exchanges=40, seed=5)
    scaffolds = [s for s in sa.app_scaffolds(1_500) if s.name in ("compaction", "recall-keyword")]
    results = asyncio.run(run_live_grid(graph_app, {"5": scenario}, [STRICT_ORACLE], sa.conditions_for(scaffolds),
                                        model_factory=EvalModelFactory(scenario.facts)))
    records = {r["scaffold"]: r for r in sa.audit(results, scaffolds, [STRICT_ORACLE], min_effect=0.1)}
    assert records["compaction"]["verdict"] in ("harmful", "inconclusive")
    assert records["compaction"]["baseline_recall"] > records["compaction"]["scaffold_recall"]
    assert records["recall-keyword"]["scaffold_recall"] >= records["recall-keyword"]["baseline_recall"]
