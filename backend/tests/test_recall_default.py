"""The app's default history recall: which model, where it is attached, and
that its own model call never streams into the reply."""

import os
from unittest.mock import patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.checkpoint.memory import MemorySaver

import app.services.graph as graph_mod
from app.compaction import KeywordRecall, ThresholdPolicy, fixed_tokens
from app.llm import CallableModelFactory, use_model_factory
from app.services.chat import stream_turn
from app.services.recall import ModelRewriter, default_recall_model, with_default_recall
from app.services.runs import resolve_fork_point

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
MARKER = "REWRITERTERMS"


def test_the_first_offered_recall_model_with_a_key_is_chosen():
    assert default_recall_model(KEYS) == "gpt-6-luna"
    assert default_recall_model({"ANTHROPIC_API_KEY": "k"}) == "claude-haiku-4-5-20251001"
    assert default_recall_model({"GOOGLE_API_KEY": "k"}) == "gemini-3.8-flash"
    assert default_recall_model({}) is None


def test_the_default_is_attached_only_where_a_run_names_none():
    config = with_default_recall({"configurable": {"thread_id": "t"}}, KEYS)
    recall = config["configurable"][graph_mod.RECALL_CONFIG_KEY]
    assert isinstance(recall.rewrite, ModelRewriter) and recall.rewrite.model_id == "gpt-6-luna"
    mine = KeywordRecall()
    assert with_default_recall({"configurable": {graph_mod.RECALL_CONFIG_KEY: mine}}, KEYS)["configurable"][
        graph_mod.RECALL_CONFIG_KEY] is mine
    assert graph_mod.RECALL_CONFIG_KEY not in with_default_recall({"configurable": {}}, {})["configurable"]


@pytest.fixture
def compacting_graph(tmp_path, monkeypatch):
    """The real graph, a fake LLM, and a threshold low enough that a few
    turns summarize and prune, so the default recall runs."""
    monkeypatch.setattr("app.core.database.DB_PATH", str(tmp_path / "t.sqlite"))
    monkeypatch.setattr(graph_mod, "_DEFAULT_POLICY", ThresholdPolicy(fixed_tokens(120)))
    from app.core import database as db

    db.init_db()
    rewrites = []

    def fake(model_id, _toggles):
        if model_id == "gpt-6-luna":
            rewrites.append(model_id)
            return FakeListChatModel(responses=[f"{MARKER} vendor budget"])
        return FakeListChatModel(responses=["We discussed the vendor budget and the rollout plan in some detail. " * 3])

    with use_model_factory(CallableModelFactory(fake)), patch.dict(os.environ, KEYS):
        yield graph_mod.workflow.compile(checkpointer=MemorySaver()), rewrites


@pytest.mark.asyncio
async def test_the_rewriter_call_never_streams_into_the_reply(compacting_graph):
    graph_app, rewrites = compacting_graph
    parent = await resolve_fork_point(graph_app, "t")
    streamed = []
    for i in range(8):
        async for event in stream_turn(graph_app, "t", parent, model="gpt-5.4",
                                       message=f"Turn {i}: what did we decide about the vendor budget and the rollout?"):
            if event["type"] == "token":
                streamed.append(event["token"])
            else:
                parent = event["checkpoint_id"]
                assert MARKER not in str(event)
    assert rewrites, "recall never ran: the test did not reach the path it guards"
    assert MARKER not in "".join(streamed)
