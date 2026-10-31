"""A chat synthesis turn is tagged, and the tree and transcript say so.

Real LangGraph workflow, fake LLM. Before the tag, a synthesis reply was just
another sibling answer: same node, same bubble, detected (if at all) by
matching the prompt's wording in the frontend.
"""

import os
from unittest.mock import patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.checkpoint.memory import MemorySaver

import app.services.graph as graph_mod
from app.llm import CallableModelFactory, use_model_factory
from app.services.chat import stream_turn
from app.services.runs import SYNTHESIS_TURN, TURN_KIND_KEY, resolve_fork_point
from app.services.tree import SYNTHESIS_PROMPT_MARKER, build_history_tree

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}


@pytest.fixture
def graph_app(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.database.DB_PATH", str(tmp_path / "t.sqlite"))
    from app.core import database as db

    db.init_db()
    factory = CallableModelFactory(lambda model_id, _t: FakeListChatModel(responses=[f"reply from {model_id}"]))
    with use_model_factory(factory), patch.dict(os.environ, KEYS):
        yield graph_mod.workflow.compile(checkpointer=MemorySaver())


async def _turn(app, thread, parent, model, text, kind=None):
    end = None
    async for event in stream_turn(app, thread, parent, message=text, model=model, turn_kind=kind):
        if event["type"] == "end":
            end = event
    return end


async def _tree(app, thread, active_id):
    states = [s async for s in app.aget_state_history({"configurable": {"thread_id": thread, "checkpoint_ns": ""}})]
    active = next(s for s in states if s.config["configurable"]["checkpoint_id"] == active_id)
    with patch("app.services.tree.load_node_positions", return_value={}):
        return build_history_tree(thread, states, active)


@pytest.mark.asyncio
async def test_synthesis_turn_is_tagged_and_shown_as_synthesis(graph_app):
    root = await resolve_fork_point(graph_app, "t")
    await _turn(graph_app, "t", root, "gpt-5.4", "Q")
    # Synthesis forks from the same parent the answers did.
    synth = await _turn(
        graph_app, "t", root, "claude-sonnet-5", f"Model 1: a\n\n{SYNTHESIS_PROMPT_MARKER}.", kind=SYNTHESIS_TURN
    )

    state = await graph_app.aget_state(
        {"configurable": {"thread_id": "t", "checkpoint_ns": "", "checkpoint_id": synth["checkpoint_id"]}}
    )
    assert state.metadata.get(TURN_KIND_KEY) == SYNTHESIS_TURN

    tree = await _tree(graph_app, "t", synth["checkpoint_id"])
    # The run's last checkpoint collapses into the node that shows its reply.
    synth_node = next(n for n in tree["nodes"] if n["id"] == tree["current_checkpoint"])
    assert synth_node["type"] == "synthesis"
    assert synth_node["metadata"]["kind"] == "synthesis"
    assert synth_node["metadata"]["active_peer"] == "claude-sonnet-5"
    answers = [n for n in tree["nodes"] if n["metadata"]["role"] == "ai" and n.get("type") != "synthesis"]
    assert [n["metadata"]["active_peer"] for n in answers] == ["gpt-5.4"]
    # The transcript marks the reply too, and hides the internal prompt.
    assert [m["kind"] for m in tree["messages"] if m["role"] == "assistant"] == ["synthesis"]
    assert not any(SYNTHESIS_PROMPT_MARKER in m["content"] for m in tree["messages"])


@pytest.mark.asyncio
async def test_unknown_turn_kinds_are_ignored(graph_app):
    root = await resolve_fork_point(graph_app, "u")
    end = await _turn(graph_app, "u", root, "gpt-5.4", "Q", kind="something-else")
    state = await graph_app.aget_state(
        {"configurable": {"thread_id": "u", "checkpoint_ns": "", "checkpoint_id": end["checkpoint_id"]}}
    )
    assert TURN_KIND_KEY not in state.metadata
    tree = await _tree(graph_app, "u", end["checkpoint_id"])
    assert all(n.get("type") != "synthesis" for n in tree["nodes"])


def test_ws_synthesis_frame_tags_the_turn(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.core import database as db
    from app.main import server

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "ws.sqlite"))
    factory = CallableModelFactory(lambda model_id, _t: FakeListChatModel(responses=[f"reply from {model_id}"]))
    with (
        use_model_factory(factory),
        patch.dict(os.environ, KEYS),
        TestClient(server) as client,
        client.websocket_connect("/ws/thread_synth") as ws,
    ):
        ws.send_json({"message": f"x {SYNTHESIS_PROMPT_MARKER}", "model": "gpt-5.4", "type": "synthesis"})
        while (msg := ws.receive_json())["type"] != "stream_end":
            assert msg["type"] != "error", msg
        history = client.get(f"/history/thread_synth?checkpoint_id={msg['checkpoint_id']}").json()

    node = next(n for n in history["nodes"] if n["id"] == history["current_checkpoint"])
    assert node.get("type") == "synthesis"


def test_ws_synthesis_of_named_answers_uses_the_backend_prompt(tmp_path, monkeypatch):
    """The web UI names the answers; the prompt is the one the CLI and MCP
    synthesis write, flagged so every reader hides it."""
    from fastapi.testclient import TestClient

    from app.core import database as db
    from app.main import server

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "ws.sqlite"))
    seen = []

    class Recorder(FakeListChatModel):
        def _call(self, messages, *a, **kw):
            seen.append("\n".join(str(m.content) for m in messages))
            return super()._call(messages, *a, **kw)

        def _stream(self, messages, *a, **kw):
            seen.append("\n".join(str(m.content) for m in messages))
            yield from super()._stream(messages, *a, **kw)

    factory = CallableModelFactory(lambda model_id, _t: Recorder(responses=[f"reply from {model_id}"]))

    def finish(ws):
        while (msg := ws.receive_json())["type"] != "stream_end":
            assert msg["type"] != "error", msg
        return msg

    with (
        use_model_factory(factory),
        patch.dict(os.environ, KEYS),
        TestClient(server) as client,
        client.websocket_connect("/ws/named") as ws,
    ):
        for model in ("gpt-5.4", "claude-sonnet-5"):
            ws.send_json({"message": "Which is larger?", "model": model})
        answers = [finish(ws)["checkpoint_id"], finish(ws)["checkpoint_id"]]
        seen.clear()
        ws.send_json({"type": "synthesis", "model": "gpt-5.4", "answer_checkpoint_ids": answers})
        end = finish(ws)

    assert "Independent answers from 2 models" in seen[-1]
    assert "Original question: Which is larger?" in seen[-1]
    assert [m["kind"] for m in end["messages"] if m["role"] == "assistant"][-1] == "synthesis"
    assert not any("Independent answers" in m["content"] for m in end["messages"])
