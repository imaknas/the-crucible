"""Recall measured with no model in the loop (app/compaction/recall_eval.py)
and the no-shared-words probe it is measured with."""

import itertools

from app.compaction.probe import (
    FACT_KINDS,
    SUBJECTS,
    VARIANTS,
    build_dense_scenario,
    generate_facts,
    no_shared_words,
)
from app.compaction.recall import EmbeddingRecall, KeywordRecall, _terms
from app.compaction.recall_eval import measure, measure_recall, overlap, summarize


def test_no_shared_words_questions_share_no_term_with_anything_planted():
    seen = set()
    for seed in range(20):
        facts = no_shared_words(generate_facts(24, seed=seed, variants=VARIANTS))
        for f in facts:
            seen.add((f.subject, f.kind, f.variant.split("+")[0]))
            for planted in (f.statement, *f.extras):
                assert overlap(f.indirect_question, planted) == 0, (f.key, f.indirect_question, planted)
    # Every subject and every kind came up, each kind in each of its variants.
    assert {s for s, _, _ in seen} == set(SUBJECTS)
    assert {k for _, k, _ in seen} == set(FACT_KINDS)
    assert {v for _, _, v in seen} == set(VARIANTS)


def test_keyword_recall_never_returns_a_message_sharing_no_term_with_the_request():
    # The by-construction half: a zero score is never returned.
    scenario = build_dense_scenario(no_shared_words(generate_facts(24, seed=1)), exchanges=120, seed=1,
                                    questions="indirect")
    candidates = [t.text for t in scenario.turns[:-5]]
    recall = KeywordRecall()
    for fact in scenario.facts:
        query = scenario.probe_prompt(fact)
        for i in recall.select(query, candidates):
            assert set(_terms(query)) & set(_terms(candidates[i]))


def test_a_direct_probe_is_scored_by_fact_and_turn():
    scenario = build_dense_scenario(n_facts=24, exchanges=120, seed=0)
    probes = measure_recall(scenario, KeywordRecall())
    assert len(probes) == len(scenario.facts)
    hidden = len(scenario.turns) - 5
    for p in probes:
        assert p.visible == (scenario.positions[p.fact] >= hidden)
        if not p.visible:
            assert p.hit == (scenario.positions[p.fact] in p.returned_turns)
            assert p.returned == len(p.returned_turns) <= 4
            assert p.stale_without_current <= p.stale
    summary = summarize(probes)
    # Direct questions name the subject: keyword recall finds most facts.
    assert summary["all"]["hit_rate"] > 0.7
    assert set(summary["by_variant"]) <= {"plain", "distractor", "update"}


def test_an_update_whose_current_turn_is_missed_counts_as_stale_without_current():
    scenario = build_dense_scenario(n_facts=24, exchanges=120, seed=2, variants=("update",))
    update = next(f for f in scenario.facts if f.variant == "update")
    old_turn = scenario.extra_positions[update.key][0]

    class OnlyTheOld:
        name = "only-the-old"

        def select(self, query, candidates, hint=""):
            return [old_turn] if update.question in query else []

    probe = next(p for p in measure_recall(scenario, OnlyTheOld()) if p.fact == update.key)
    assert (probe.hit, probe.stale, probe.stale_without_current, probe.false_positives) == (False, True, True, 0)


def test_embedding_recall_is_measured_through_an_injected_embedder():
    # A bag-of-letters embedder: deterministic, no model.
    def embed(texts):
        return [[t.lower().count(c) for c in "abcdefghijklmnopqrstuvwxyz0123456789"] for t in texts]

    scenarios = [build_dense_scenario(n_facts=8, exchanges=40, seed=s) for s in range(2)]
    result = measure(scenarios, [KeywordRecall(), EmbeddingRecall(embed)], label="unit")
    assert set(result["recalls"]) == {"keyword", "embedding"}
    for name, entry in result["recalls"].items():
        assert entry["summary"]["all"]["probes"] + entry["summary"]["visible"] == 16
        assert len(entry["probes"]) == 16
    assert list(itertools.chain(result["recalls"]["keyword"]["summary"]["by_overlap"]))


def test_with_later_mentions_adds_the_newest_later_message_sharing_rare_terms():
    from app.compaction.recall import WithLaterMentions

    candidates = [
        "The budget for the zephyr relay is 10 euros.",
        "Nothing about it here.",
        "Update on the zephyr relay: its budget was revised to 20 euros.",
        "Still nothing.",
    ]

    class First:
        name = "first"

        def select(self, query, candidates, hint=""):
            return [0]

    assert WithLaterMentions(First()).select("q", candidates) == [0, 2]
    assert WithLaterMentions(First()).name == "first+later"
