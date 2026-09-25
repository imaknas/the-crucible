"""Parallel model runs on one thread, against the real LangGraph workflow.

Only the LLM is faked. These guard the bug where unpinned concurrent runs
resumed from each other's half-written turns.
"""

import asyncio
import os
from unittest.mock import patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.checkpoint.memory import MemorySaver

import app.services.graph as graph_mod
from app.services.runs import (
    final_state_of_run,
    resolve_fork_point,
    tag_run,
    thread_config,
)

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}


class _SlowFake(FakeListChatModel):
    """Yields to the loop mid-call so concurrent runs genuinely interleave."""

    async def _agenerate(self, *args, **kwargs):
        await asyncio.sleep(0.05)
        return await super()._agenerate(*args, **kwargs)


def _fake_model(model_id, *_a, **_kw):
    return _SlowFake(responses=[f"reply from {model_id}"])


@pytest.fixture
def graph_app(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.database.DB_PATH", str(tmp_path / "t.sqlite"))
    from app.core import database as db

    db.init_db()
    with patch.object(graph_mod, "get_model", side_effect=_fake_model), patch.dict(os.environ, KEYS):
        yield graph_mod.workflow.compile(checkpointer=MemorySaver())


async def _run(app, thread_id, parent, model, text):
    config = thread_config(thread_id, parent)
    run_id = tag_run(config)
    await app.ainvoke(
        {"active_peer": model, "messages": [("user", text)], "toggles": {}, "documents": {}},
        config,
    )
    return await final_state_of_run(app, thread_id, run_id)


def _contents(state):
    return [m.content for m in state.values["messages"]]


@pytest.mark.asyncio
async def test_first_turn_models_fork_from_one_parent(graph_app):
    parent = await resolve_fork_point(graph_app, "t-new")
    a, b = await asyncio.gather(
        _run(graph_app, "t-new", parent, "gpt-5.4", "Q"),
        _run(graph_app, "t-new", parent, "claude-sonnet-5", "Q"),
    )
    # Each run sees exactly one prompt and its own reply, not the other's turn.
    assert _contents(a) == ["Q", "reply from gpt-5.4"]
    assert _contents(b) == ["Q", "reply from claude-sonnet-5"]
    assert a.config["configurable"]["checkpoint_id"] != b.config["configurable"]["checkpoint_id"]


@pytest.mark.asyncio
async def test_final_state_is_the_new_checkpoint_not_the_parent(graph_app):
    parent = await resolve_fork_point(graph_app, "t1")
    first = await _run(graph_app, "t1", parent, "gpt-5.4", "one")
    first_id = first.config["configurable"]["checkpoint_id"]

    second = await _run(graph_app, "t1", first_id, "gpt-5.4", "two")
    assert second.config["configurable"]["checkpoint_id"] != first_id
    assert _contents(second)[-1] == "reply from gpt-5.4"
    assert _contents(second)[-2] == "two"


@pytest.mark.asyncio
async def test_resolve_fork_point_returns_head_for_existing_thread(graph_app):
    parent = await resolve_fork_point(graph_app, "t2")
    done = await _run(graph_app, "t2", parent, "gpt-5.4", "hi")
    assert await resolve_fork_point(graph_app, "t2") == done.config["configurable"]["checkpoint_id"]


def test_ws_first_turn_arena_gives_each_model_its_own_branch(tmp_path, monkeypatch):
    """Two models sent together on a new thread over /ws, real sqlite checkpointer."""
    from fastapi.testclient import TestClient

    from app.core import database as db
    from app.main import server

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "ws.sqlite"))
    with (
        patch.object(graph_mod, "get_model", side_effect=_fake_model),
        patch.dict(os.environ, KEYS),
        TestClient(server) as client,
        client.websocket_connect("/ws/thread_ws_test") as ws,
    ):
        for model in ("gpt-5.4", "claude-sonnet-5"):
            ws.send_json({"message": "Q", "model": model, "parent_checkpoint_id": None, "toggles": {}})

        ends = {}
        while len(ends) < 2:
            msg = ws.receive_json()
            assert msg["type"] != "error", msg
            if msg["type"] == "stream_end":
                ends[msg["model"]] = msg

    for model, end in ends.items():
        contents = [m["content"] for m in end["messages"]]
        assert contents == ["Q", f"reply from {model}"], contents
    assert ends["gpt-5.4"]["checkpoint_id"] != ends["claude-sonnet-5"]["checkpoint_id"]
