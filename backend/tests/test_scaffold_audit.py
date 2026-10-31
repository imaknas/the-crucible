"""Scaffolding must keep beating its baseline, or be flagged for removal."""

import asyncio

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.compaction import build_dense_scenario
from app.services import graph as graph_mod
from app.services import scaffold_audit as sa
from app.services.compaction_eval import STRICT_ORACLE, EvalModelFactory, run_live_grid
from tests.storage_helpers import point


def test_verdicts_follow_the_claim():
    assert sa.verdict(sa.IMPROVES, "b_better") == "keep"
    assert sa.verdict(sa.IMPROVES, "equivalent") == "retire"  # no longer earns its place
    assert sa.verdict(sa.IMPROVES, "a_better") == "harmful"
    assert sa.verdict(sa.IMPROVES, "no_detectable_diff") == "inconclusive"
    assert sa.verdict(sa.NON_INFERIOR, "equivalent") == "keep"  # compaction only has to not lose detail
    assert sa.verdict(sa.NON_INFERIOR, "a_better") == "harmful"


def test_verdicts_at_the_ceiling_say_there_is_no_headroom():
    # Both arms at the ceiling: the probes cannot tell them apart.
    assert sa.verdict(sa.IMPROVES, "equivalent", 1.0, 1.0) == "no_headroom"  # not "retire"
    assert sa.verdict(sa.NON_INFERIOR, "equivalent", 0.98, 0.96) == "no_headroom"  # not "keep"
    # A scaffold that has to improve on a baseline already at the ceiling cannot.
    assert sa.verdict(sa.IMPROVES, "no_detectable_diff", 1.0, 0.85) == "no_headroom"
    # A detectable loss is harmful however high the baseline.
    assert sa.verdict(sa.IMPROVES, "a_better", 1.0, 0.79) == "harmful"
    assert sa.verdict(sa.NON_INFERIOR, "a_better", 1.0, 0.85) == "harmful"
    # Below the ceiling the claim decides, as before.
    assert sa.verdict(sa.IMPROVES, "b_better", 0.40, 0.98) == "keep"
    assert sa.verdict(sa.NON_INFERIOR, "no_detectable_diff", 1.0, 0.85) == "inconclusive"
    assert sa.verdict(sa.IMPROVES, "equivalent", 0.90, 0.92) == "retire"


def test_audit_records_report_no_headroom():
    from app.services.compaction_eval import ProbeResult

    scaffolds = [s for s in sa.app_scaffolds(8000) if s.name == "verbatim-window"]
    rows = [ProbeResult(condition=c.name, model="m", fact=f"f{i}", kind="port", planted_turn=0, correct=True,
                        pruned=True, summarized=True, answer="x")
            for c in (scaffolds[0].baseline, scaffolds[0].treatment) for i in range(30)]
    [record] = sa.audit(rows, scaffolds, ["m"])
    assert record["verdict"] == "no_headroom" and (record["baseline_recall"], record["scaffold_recall"]) == (1.0, 1.0)


def test_a_recorded_audit_rebuilds_its_scaffolds_from_the_records():
    records = [{"scaffold": n} for n in ("compaction", "recall", "summarizer-claude-haiku-5-5", "recall-keyword")]
    rebuilt = {s.name: s for s in sa.scaffolds_for_records(records, 8000)}
    assert set(rebuilt) == {r["scaffold"] for r in records}
    assert rebuilt["summarizer-claude-haiku-5-5"].treatment.name == "t8000-app-claude-haiku-5-5"
    assert rebuilt["recall"].baseline.name == "t8000-norecall" and rebuilt["compaction"].treatment.name == "t8000-app"
    assert rebuilt["recall-keyword"].claim == sa.NON_INFERIOR  # recall was on in that audit


def test_every_scaffold_names_its_baseline():
    from app.compaction import GuidedRecall

    scaffolds = sa.app_scaffolds(8000, recall=GuidedRecall(lambda q, h: q))
    names = [s.name for s in scaffolds]
    assert len(names) == len(set(names))
    for s in scaffolds:
        assert s.baseline.name != s.treatment.name and s.claim in (sa.IMPROVES, sa.NON_INFERIOR) and s.why
    conditions = sa.conditions_for(scaffolds)
    assert len({c.name for c in conditions}) == len(conditions)  # shared baselines run once
    by_name = {s.name: s for s in scaffolds}
    assert by_name["recall"].active and by_name["recall"].baseline.recall is None
    assert by_name["compaction"].treatment is by_name["recall"].treatment  # the app's own path


def test_other_summarizers_have_to_beat_the_default():
    names = {s.name: s for s in sa.app_scaffolds(8000, other_summarizers=["gemini-3.8-flash"])}
    alt = names["summarizer-gemini-3.8-flash"]
    assert alt.claim == sa.IMPROVES and not alt.active
    assert alt.baseline is names["compaction"].treatment and alt.treatment.summarizer == "gemini-3.8-flash"


def test_without_a_recall_model_the_app_path_has_no_recall():
    names = {s.name: s for s in sa.app_scaffolds(8000)}
    assert "recall" not in names and names["compaction"].treatment.recall is None
    assert names["recall-keyword"].claim == sa.IMPROVES


def test_history_and_staleness(tmp_path):
    path = tmp_path / "history.jsonl"
    assert sa.staleness([], summarizer="m", catalog_synced=None) == "scaffolding has never been audited"
    sa.append_history([{"scaffold": "compaction", "model": "x", "verdict": "keep"}], {"summarizer": "m"}, path)
    history = sa.load_history(path)
    assert history[0]["scaffold"] == "compaction" and history[0]["summarizer"] == "m" and history[0]["date"]
    assert sa.staleness(history, summarizer="m", catalog_synced=None) is None
    assert "summarizer changed" in sa.staleness(history, summarizer="other", catalog_synced=None)
    assert "synced" in sa.staleness(history, summarizer="m", catalog_synced="2999-01-01")
    assert "recall model changed" in sa.staleness(history, summarizer="m", catalog_synced=None, recall_model="r")


@pytest.fixture
def graph_app(tmp_path, monkeypatch):
    point(monkeypatch, db_path=str(tmp_path / "audit.sqlite"))
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
