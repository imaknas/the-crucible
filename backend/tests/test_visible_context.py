"""What a turn was written from is visible: a summary is a marker on the
path, each reply records what its call saw (tokens, the jump to the
summary, what recall brought back), and the next turn's size can be read
before it is sent."""

import os
from unittest.mock import patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.checkpoint.memory import MemorySaver

import app.services.graph as graph_mod
from app.compaction import ThresholdPolicy, fixed_tokens
from app.core.schema import SUMMARY_MARKER
from app.llm import CallableModelFactory, use_model_factory
from app.services import history
from app.services.chat import stream_turn
from app.services.runs import resolve_fork_point, thread_config
from app.services.tree import build_history_tree
from tests.storage_helpers import point

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}


@pytest.fixture
def compacting_graph(tmp_path, monkeypatch):
    """The real graph and a threshold low enough that a few turns summarize,
    prune and recall."""
    point(monkeypatch, db_path=str(tmp_path / "t.sqlite"))
    monkeypatch.setattr(graph_mod, "_DEFAULT_POLICY", ThresholdPolicy(fixed_tokens(120)))
    from app.core import database as db

    db.init_db()

    def fake(model_id, _toggles):
        if model_id == "gpt-6-luna":  # the recall rewriter and the summarizer
            return FakeListChatModel(responses=["vendor budget"])
        return FakeListChatModel(responses=["We discussed the vendor budget and the rollout plan in some detail. " * 3])

    with use_model_factory(CallableModelFactory(fake)), patch.dict(os.environ, KEYS):
        yield graph_mod.workflow.compile(checkpointer=MemorySaver())


async def _turns(graph_app, count):
    parent = await resolve_fork_point(graph_app, "t")
    end = None
    for i in range(count):
        async for event in stream_turn(graph_app, "t", parent, model="gpt-5.4",
                                       message=f"Turn {i}: what did we decide about the vendor budget and the rollout?"):
            if event["type"] == "end":
                end = event
                parent = event["checkpoint_id"]
    return end


@pytest.mark.asyncio
async def test_the_path_marks_the_summary_and_each_reply_says_what_it_saw(compacting_graph):
    end = await _turns(compacting_graph, 8)
    messages = end["messages"]

    summaries = [m for m in messages if m.get("kind") == "summary"]
    assert summaries, "no summary was written: the test did not reach the path it guards"
    assert all(m["role"] == "system" and m["checkpoint_id"] is None for m in summaries)
    assert not summaries[0]["content"].startswith(SUMMARY_MARKER)
    assert len({m["id"] for m in summaries}) == len(summaries)

    replies = [m for m in messages if m["role"] == "assistant"]
    first, last = replies[0]["context"], replies[-1]["context"]
    assert first["pruned"] is False and first["recalled"] == []
    assert last["pruned"] is True and last["tokens"] > 0 and last["soft_limit"] > 0
    assert last["recalled"] and all(r["excerpt"] for r in last["recalled"])
    assert last["kept_verbatim"] + last["hidden"] > 0

    # The tree's nodes carry it too (MemorySaver: no checkpoint tables to read).
    states = [s async for s in compacting_graph.aget_state_history(thread_config("t"))]
    tree = build_history_tree("t", states, await compacting_graph.aget_state(thread_config("t")))
    replies_in_tree = [n for n in tree["nodes"] if n["metadata"].get("role") == "ai"]
    assert any((n["metadata"].get("context") or {}).get("pruned") for n in replies_in_tree)


@pytest.mark.asyncio
async def test_the_next_turn_is_measured_per_model_before_it_is_sent(compacting_graph):
    await _turns(compacting_graph, 1)
    small = await history.context_report(compacting_graph, "t")
    assert [m["model"] for m in small["models"]] == ["gpt-5.4"]  # who answered there
    assert small["models"][0]["summarized"] is False and small["models"][0]["messages"] == 2

    await _turns(compacting_graph, 7)
    report = await history.context_report(compacting_graph, "t", models=["gpt-5.4", "claude-sonnet-5"])
    row = report["models"][0]
    assert row["summarized"] and row["from_summary"]
    # Jumping to the summary sends less than the whole path.
    assert 0 < row["tokens"] < row["history_tokens"]
    assert {m["model"] for m in report["models"]} == {"gpt-5.4", "claude-sonnet-5"}

    with pytest.raises(ValueError, match="Unknown model"):
        await history.context_report(compacting_graph, "t", models=["no-such-model"])
    with pytest.raises(ValueError, match="not found"):
        await history.context_report(compacting_graph, "t", "1f000000-0000-6000-8000-000000000000")
