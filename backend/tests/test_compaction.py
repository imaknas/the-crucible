"""Compaction policies, retention scenarios, and the end-to-end cliff."""

import ast
import pathlib
from dataclasses import replace

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
    assert all(r.correct and r.compactions == 0 and r.summary_tokens == 0 for r in never)
    assert all(r.summary_tokens > 0 for r in live)
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


def test_the_summary_instruction_is_replaceable():
    from langchain_core.messages import AIMessage, HumanMessage

    from app.compaction import DetailedBrief, LengthTarget

    seen = []

    class Recorder:
        def invoke(self, msgs):
            seen.append(msgs[0].content)
            return AIMessage(content="gist")

    messages = [HumanMessage(content=f"m{i}") for i in range(12)]
    base = {"model_factory": CallableModelFactory(lambda *_: Recorder()),
            "compaction_policy": ThresholdPolicy(fixed_tokens(1))}
    graph_mod.summarize_history({"messages": messages, "active_peer": "gpt-5.4"}, {"configurable": base})
    graph_mod.summarize_history({"messages": messages, "active_peer": "gpt-5.4"},
                                {"configurable": {**base, graph_mod.INSTRUCTION_CONFIG_KEY: LengthTarget(2_000)}})
    default, limited = seen
    assert default == DetailedBrief().prompt(default.partition("\n\n")[2])  # unchanged by default
    assert "at most about 1500 words" in limited and "at most" not in default
    # Only the length sentence differs; the transcript is the same.
    assert limited.partition("\n\n")[2] == default.partition("\n\n")[2]


def test_strict_availability_needs_the_value_attached_to_its_subject():
    from app.compaction import build_dense_scenario, value_attached

    fact = next(f for f in build_dense_scenario(seed=0).facts if f.kind == "port")
    value, subject = fact.answers[0], fact.subject
    other = next(x for x in __import__("app.compaction.probe", fromlist=["SUBJECTS"]).SUBJECTS if x != subject)
    # In its own section, however long the section is.
    section = f"### {subject.title()}\n" + "* filler line\n" * 40 + f"* listens on port {value}\n"
    assert value_attached(section, fact)
    # Same line, subject after the value.
    assert value_attached(f"### {other}\nPort {value} belongs to the {subject}.", fact)
    # Kept, but under another subject: detached.
    assert not value_attached(f"### {subject}\n* fine\n### {other}\n* port {value}", fact)
    assert value_attached(f"### {subject}\n* fine\n### {other}\n* port {value}", replace(fact, subject=""))
    # Hyphens and case don't matter for the subject.
    assert value_attached(f"{subject.upper().replace(' ', '-')}: {value}", fact)


def test_retention_rules():
    from app.compaction import EarlierMessage, KeepRecent, KeepUserMessages

    earlier = [EarlierMessage("user", 100), EarlierMessage("assistant", 500), EarlierMessage("system", 50)] * 4
    assert KeepRecent(5).keep(earlier) == [7, 9, 10]  # last 5 positions, system skipped
    user = KeepUserMessages(budget=250).keep(earlier)
    assert set(KeepRecent(5).keep(earlier)) <= set(user)
    assert [i for i in user if earlier[i].role == "user" and i < 7] == [3, 6]  # newest first within 250 tokens


def test_keeping_user_messages_keeps_user_stated_facts_through_a_lossy_summary(eval_setup):
    import asyncio

    from app.compaction import KeepUserMessages, build_dense_scenario
    from app.services.compaction_eval import ORACLE, EvalModelFactory, run_live_grid

    app, _ = eval_setup
    scenario = build_dense_scenario(n_facts=8, exchanges=40, seed=6, assistant_facts=0.5)
    t = ThresholdPolicy(fixed_tokens(1_500))
    results = asyncio.run(run_live_grid(
        app, {"6": scenario}, [ORACLE],
        [Condition("recent", t), Condition("keepuser", t, retention=KeepUserMessages(20_000))],
        model_factory=EvalModelFactory(scenario.facts),  # stand-in summary keeps no facts
    ))
    # Facts summarized away (outside the recent window when probed).
    old = [r for r in results if r.compactions >= 1 and r.planted_turn < len(scenario.turns) - 12]
    group = lambda cond, by: [r.correct for r in old if r.condition == cond and r.stated_by == by]  # noqa: E731
    assert group("keepuser", "user") and all(group("keepuser", "user"))
    assert group("keepuser", "assistant") and not any(group("keepuser", "assistant"))  # left to the summary
    assert group("recent", "user") and not any(group("recent", "user"))


def test_sanitize_default_keeps_the_original_recent_window():
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    msgs = [HumanMessage(content=f"u{i}") if i % 2 == 0 else AIMessage(content=f"a{i}") for i in range(12)]
    msgs.append(SystemMessage(content="PREVIOUS CONTEXT SUMMARY: gist"))
    msgs.append(HumanMessage(content="now"))
    text = " ".join(str(m.content) for m in graph_mod.sanitize_messages(msgs))
    assert all(f"{'u' if i % 2 == 0 else 'a'}{i}" in text for i in range(7, 12))
    assert "u6" not in text and "u0" not in text


def test_keyword_recall_finds_the_messages_about_the_asked_subject():
    from app.compaction import KeywordRecall

    hidden = [
        "The budget for the fraud scorer is capped at 17,400 euros.",
        "The p95 latency of the audit service is 212 ms.",
        "Someone proposed capping the budget for the fraud scorer at 97,800 euros, but that was turned down.",
        "The audit service has 12 alerts configured.",
    ]
    picked = KeywordRecall(limit=2).select("What is the budget cap for the fraud scorer, in euros?", hidden)
    assert picked == [0, 2]  # both mentions of the subject, oldest first
    assert KeywordRecall().select("Unrelated words entirely", hidden) == []


def test_sanitize_brings_recalled_messages_back_as_an_excerpt():
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    from app.compaction import KeywordRecall

    msgs = [HumanMessage(content="The staging port for the ledger service is 6543.")]
    msgs += [HumanMessage(content=f"filler {i}") if i % 2 == 0 else AIMessage(content=f"reply {i}") for i in range(10)]
    msgs += [SystemMessage(content="PREVIOUS CONTEXT SUMMARY: gist"), HumanMessage(content="Which port does the ledger service use?")]
    plain = " ".join(str(m.content) for m in graph_mod.sanitize_messages(msgs))
    recalled = " ".join(str(m.content) for m in graph_mod.sanitize_messages(msgs, recall=KeywordRecall()))
    assert "6543" not in plain and "6543" in recalled
    assert recalled.count("Which port does the ledger service use?") == 1  # the request stays the last turn


def test_recall_brings_back_what_a_lossy_summary_dropped(eval_setup):
    import asyncio

    from app.compaction import KeywordRecall, build_dense_scenario
    from app.services.compaction_eval import ORACLE, EvalModelFactory, run_live_grid

    app, _ = eval_setup
    scenario = build_dense_scenario(n_facts=8, exchanges=40, seed=7, assistant_facts=0.5)
    t = ThresholdPolicy(fixed_tokens(1_500))
    results = asyncio.run(run_live_grid(
        app, {"7": scenario}, [ORACLE],
        [Condition("none", t), Condition("recall", t, recall=KeywordRecall())],
        model_factory=EvalModelFactory(scenario.facts),
    ))
    old = [r for r in results if r.compactions >= 1 and r.planted_turn < len(scenario.turns) - 12]
    assert not any(r.correct for r in old if r.condition == "none")
    recalled = [r.correct for r in old if r.condition == "recall"]
    assert recalled and all(recalled)


def test_embedding_recall_ranks_by_meaning_with_an_injected_embedder():
    from app.compaction import EmbeddingRecall

    vectors = {"q": [1.0, 0.0], "a": [0.9, 0.1], "b": [0.0, 1.0], "c": [0.7, 0.7]}
    recall = EmbeddingRecall(lambda texts: [vectors[t] for t in texts], limit=2)
    assert recall.select("q", ["a", "b", "c"]) == [0, 2]


def test_indirect_questions_avoid_the_subject_and_the_oracle_still_answers(eval_setup):
    import asyncio

    from app.compaction import build_dense_scenario
    from app.services.compaction_eval import ORACLE, EvalModelFactory, run_live_grid

    app, _ = eval_setup
    scenario = build_dense_scenario(n_facts=8, exchanges=40, seed=8, questions="indirect")
    for fact in scenario.facts:
        prompt = scenario.probe_prompt(fact)
        assert fact.subject.lower() not in prompt.lower() and fact.indirect_question in prompt
    results = asyncio.run(run_live_grid(app, {"8": scenario}, [ORACLE], [Condition("never", NeverCompact())],
                                        model_factory=EvalModelFactory(scenario.facts)))
    assert all(r.correct for r in results)


def test_guided_recall_searches_with_the_models_terms():
    from app.compaction import GuidedRecall

    hidden = ["The CDN purge job listens on port 5592.", "The audit service has 12 alerts configured."]
    seen = []

    def rewrite(query, hint):
        seen.append(hint)
        return "CDN purge job port"

    picked = GuidedRecall(rewrite).select("Which port for the task that clears cached files?", hidden, hint="- CDN purge job")
    assert picked == [0] and seen == ["- CDN purge job"]


def test_asides_change_only_the_wording():
    from app.compaction import build_dense_scenario, is_correct

    plain = build_dense_scenario(n_facts=8, exchanges=40, seed=9, variants=("plain",))
    aside = build_dense_scenario(n_facts=8, exchanges=40, seed=9, variants=("plain",), asides=True)
    assert plain.positions == aside.positions
    for a, b in zip(plain.facts, aside.facts):
        assert a.answers == b.answers and a.statement != b.statement
        assert is_correct(b.statement, b) or any(x.lower() in b.statement.lower() for x in b.answers)
    differ = [i for i, (x, y) in enumerate(zip(plain.turns, aside.turns)) if x.text != y.text]
    assert len(differ) == len(plain.facts)  # only the planting turns changed


def test_volatile_context_rides_with_the_latest_request():
    """Providers cache the longest unchanged prefix: the time and recalled
    excerpts must not sit in the system prompt, or every call re-reads the
    whole history at full price."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    history = [SystemMessage(content="You are helpful.")]
    history += [HumanMessage(content=f"q{i}") if i % 2 == 0 else AIMessage(content=f"a{i}") for i in range(9)]
    first = graph_mod.sanitize_messages(history, request_notes=["[Current System Time: 10:00:01]"])
    second = graph_mod.sanitize_messages(history, request_notes=["[Current System Time: 10:00:02]"])
    assert [m.content for m in first[:-1]] == [m.content for m in second[:-1]]  # identical prefix
    assert "10:00" not in first[0].content
    question, notes = first[-1].content
    assert question["text"] == "q8" and "10:00:01" in notes["text"]  # the question stays reusable


def test_anthropic_breakpoint_skips_the_per_request_block():
    from app.llm.providers import REQUEST_NOTES_HEADER, mark_cache_breakpoint

    messages = [{"role": "user", "content": "q0"}, {"role": "assistant", "content": "a0"},
                {"role": "user", "content": [{"type": "text", "text": "q1"},
                                             {"type": "text", "text": REQUEST_NOTES_HEADER + " time"}]}]
    mark_cache_breakpoint(messages)
    q1, notes = messages[-1]["content"]
    assert q1.get("cache_control") and "cache_control" not in notes
    plain = [{"role": "user", "content": "only"}]
    mark_cache_breakpoint(plain)
    assert plain[0]["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_openai_payload_moves_the_per_request_block_out_of_the_user_message():
    from app.llm.providers import REQUEST_NOTES_HEADER, split_request_notes

    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": [
        {"type": "text", "text": "q1"}, {"type": "text", "text": REQUEST_NOTES_HEADER + "\n[time]"}]}]
    split_request_notes(messages)
    assert messages[-2] == {"role": "user", "content": [{"type": "text", "text": "q1"}]}
    assert messages[-1]["role"] == "system" and messages[-1]["content"].startswith(REQUEST_NOTES_HEADER)
    untouched = [{"role": "user", "content": "plain"}]
    split_request_notes(untouched)
    assert untouched == [{"role": "user", "content": "plain"}]


def test_task_scenario_sets_relevance_by_goal_not_wording():
    from app.compaction import build_task_scenario

    a, b = build_task_scenario(seed=2), build_task_scenario(seed=2)
    assert [t.text for t in a.turns] == [t.text for t in b.turns]
    on = [f for f in a.facts if f.variant == "on-goal"]
    off = [f for f in a.facts if f.variant == "off-goal"]
    assert len(on) == len(off) == 8
    goal, later = on[0].subject, off[0].subject
    before_switch = [t.text for t in a.turns[:-2]]
    # The later subject is only ever mentioned in its own fact statements...
    assert sum(later in t for t in before_switch) == len(off)
    # ...stated like every other fact (no aside markers), and the goal dominates.
    assert all("Side note" not in f.statement and "irrelevant" not in f.statement for f in off)
    assert sum(goal in t for t in before_switch) > 100
    assert later in a.turns[-2].text and "priority" in a.turns[-2].text  # the switch comes last
    for f in a.facts:
        assert f.statement in a.turns[a.positions[f.key]].text


def test_guided_recall_sees_the_summary_and_the_recent_turns():
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    from app.compaction import GuidedRecall

    seen = []
    msgs = [HumanMessage(content="The ledger service listens on port 6543.")]
    msgs += [HumanMessage(content=f"filler {i}") if i % 2 == 0 else AIMessage(content=f"reply {i}") for i in range(10)]
    msgs += [SystemMessage(content="PREVIOUS CONTEXT SUMMARY: gist"),
             HumanMessage(content="Change of plans: the ledger service is now the priority."), AIMessage(content="ok"),
             HumanMessage(content="Which port for the system of record for money movements?")]
    graph_mod.sanitize_messages(msgs, recall=GuidedRecall(lambda q, h: seen.append(h) or "ledger service port"))
    assert "gist" in seen[0] and "Change of plans" in seen[0]


def test_replay_key_changes_only_with_what_shapes_the_summaries():
    from app.compaction import HandoffBrief, KeywordRecall, build_task_scenario
    from app.services.compaction_eval import replay_key

    direct = build_task_scenario(seed=1)
    indirect = build_task_scenario(seed=1, questions="indirect")
    t = ThresholdPolicy(fixed_tokens(8000))
    base = Condition("a", t, "gpt-6-sol")
    assert replay_key(direct, base, "m") == replay_key(indirect, base, "m")  # wording is answer-time
    assert replay_key(direct, base, "m") == replay_key(direct, Condition("b", t, "gpt-6-sol", recall=KeywordRecall()), "m")
    assert replay_key(direct, base, "m") != replay_key(direct, Condition("a", t, "claude-sonnet-5"), "m")
    assert replay_key(direct, base, "m") != replay_key(direct, Condition("a", t, "gpt-6-sol", HandoffBrief()), "m")
    assert replay_key(direct, base, "m") != replay_key(direct, Condition("a", ThresholdPolicy(fixed_tokens(4000)), "gpt-6-sol"), "m")
    assert replay_key(direct, base, "m") != replay_key(build_task_scenario(seed=2), base, "m")


def test_a_cached_replay_is_not_summarized_again(eval_setup, tmp_path):
    import asyncio

    from app.compaction import build_dense_scenario
    from app.services.compaction_eval import ORACLE, EvalModelFactory, ReplayCache, run_live_grid

    app, _ = eval_setup
    calls = []

    class CountingFactory(EvalModelFactory):
        def chat(self, model_id, toggles=None):
            if model_id != ORACLE:
                calls.append(model_id)
            return super().chat(model_id, toggles)

    scenario = build_dense_scenario(n_facts=8, exchanges=40, seed=3)
    cache = ReplayCache(tmp_path / "replays")
    cond = [Condition("t1500", ThresholdPolicy(fixed_tokens(1_500)))]
    first = asyncio.run(run_live_grid(app, {"3": scenario}, [ORACLE], cond, model_factory=CountingFactory(scenario.facts),
                                      replay_cache=cache, thread_prefix="first"))
    replayed = len(calls)
    second = asyncio.run(run_live_grid(app, {"3": scenario}, [ORACLE], cond, model_factory=CountingFactory(scenario.facts),
                                       replay_cache=cache, thread_prefix="second"))
    assert replayed > 0
    assert len(calls) - replayed < replayed  # only summaries written while probing, none for the replay
    assert [r.correct for r in first] == [r.correct for r in second]


def test_the_later_subject_is_unknown_announced_or_only_mentioned():
    from app.compaction import build_task_scenario

    plain, told, named = (build_task_scenario(seed=3, later_subject=v) for v in ("unknown", "announced", "mentioned"))
    assert plain.facts == told.facts == named.facts and plain.positions == told.positions == named.positions
    later = next(f.subject for f in told.facts if f.variant == "off-goal")
    mentions = lambda sc: sum(later in t.text for t in sc.turns[:-2])  # noqa: E731
    assert mentions(told) == mentions(named) > mentions(plain)  # same salience, different meaning
    assert "next priority will be the " + later in told.turns[0].text
    assert "out of scope" in named.turns[0].text and "next priority" not in named.turns[0].text
    assert "As planned" in told.turns[-2].text
    assert "Change of plans" in plain.turns[-2].text and "Change of plans" in named.turns[-2].text
    with pytest.raises(ValueError):
        build_task_scenario(later_subject="soon")


def test_all_subjects_adds_a_generic_hedge_to_its_base():
    from app.compaction import AllSubjects, DetailedBrief, HandoffBrief

    brief = AllSubjects()
    assert brief.name == "brief-allsubjects"
    assert brief.prompt("T").startswith(DetailedBrief.instruction) and "every subject" in brief.prompt("T")
    handoff = AllSubjects(HandoffBrief())
    assert handoff.prompt("T").startswith("T\n\n") and "every subject" in handoff.prompt("T")
