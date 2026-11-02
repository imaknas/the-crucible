"""Adding a model to a finished turn (arena.join_point): one more answer to
that turn's question, from where it was asked, under the turn's id; the
turn's other models are not asked again.

Against the real graph with a fake LLM, over every transport: the service,
the chat socket (resume included), POST /chat, the CLI and MCP.
"""

import json
import os
import time
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.exceptions import ToolError
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from typer.testing import CliRunner

from app.cli import app as cli_app
from app.core import database as db
from app.llm import CallableModelFactory, use_model_factory
from app.llm.fake import ScriptedModelFactory
from app.main import server
from app.services import arena
from app.services.chat import thread_state_map
from app.services.history import compact_tree
from app.services.runs import JOINED_KEY, TURN_ID_KEY, thread_config
from tests.storage_helpers import point

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B, C = "gpt-5.4", "claude-sonnet-5", "gemini-3.8-flash"


@pytest.fixture
def calls(tmp_path, monkeypatch):
    """The models asked to answer, in order; each replies "reply from <id>"."""
    point(monkeypatch, db_path=str(tmp_path / "join.sqlite"))
    monkeypatch.setattr("app.cli._load_env", lambda: None)
    db.init_db()
    asked: list[str] = []

    def fake(model_id, _toggles):
        asked.append(model_id)
        return FakeListChatModel(responses=[f"reply from {model_id}"])

    with use_model_factory(CallableModelFactory(fake)), patch.dict(os.environ, KEYS):
        yield asked


@pytest_asyncio.fixture
async def graph(calls):
    """The app's graph on the test's SQLite file (compact_tree reads the tables too)."""
    async with arena.open_graph() as graph_app:
        yield graph_app


async def _arena(graph_app, thread_id, models, prompt="", **kw):
    return await arena.collect(arena.run_arena(graph_app, prompt, thread_id, models, {}, None, **kw))


async def _turn_id(graph_app, thread_id, checkpoint_id):
    state = await graph_app.aget_state(thread_config(thread_id, checkpoint_id))
    return state.metadata[TURN_ID_KEY]


async def _path(graph_app, thread_id, checkpoint_id):
    from app.services.tree import format_messages

    return format_messages(checkpoint_id, await thread_state_map(graph_app, thread_id))


# ─── The service ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_joined_model_answers_the_turns_question_and_nobody_else_is_asked(calls, graph):
    first = await _arena(graph, "t", [A, B], "Which colour?")
    turn = await _turn_id(graph, "t", first["answers"][A]["checkpoint_id"])
    calls.clear()

    joined = await _arena(graph, "t", [C], join_turn=turn)

    assert calls == [C]
    reply = joined["answers"][C]
    assert reply["content"] == f"reply from {C}" and not reply["error"]
    assert await _turn_id(graph, "t", reply["checkpoint_id"]) == turn
    # The same question, asked from the same place: the tree shows one
    # question with three answers under it, all of one turn.
    tree = await compact_tree(graph, "t")
    questions = [n for n in tree["nodes"] if n["role"] == "user"]
    assert len(questions) == 1 and questions[0]["excerpt"] == "Which colour?"
    replies = [n for n in tree["nodes"] if n["role"] == "assistant"]
    assert {n["model"] for n in replies} == {A, B, C}
    assert {n["parent"] for n in replies} == {questions[0]["checkpoint_id"]}
    assert {n["turn_id"] for n in replies} == {turn}
    assert [m["content"] for m in await _path(graph, "t", reply["checkpoint_id"])] == ["Which colour?", f"reply from {C}"]


@pytest.mark.asyncio
async def test_a_reply_names_the_branch_the_new_answer_goes_on(calls, graph):
    first = await _arena(graph, "t", [A, B], "Start")
    # Each model continues its own reply: the second turn's question sits on two branches.
    second = await _arena(graph, "t", [A, B], "Go on")
    turn = await _turn_id(graph, "t", second["answers"][B]["checkpoint_id"])

    by_reply = await arena.join_point(graph, "t", second["answers"][B]["checkpoint_id"], C)
    by_turn = await arena.join_point(graph, "t", turn, C)

    assert by_reply.turn_id == by_turn.turn_id == turn
    assert by_reply.message == "Go on" and set(by_reply.answered) == {A, B}
    # By a reply: on that reply's branch, where the question was asked after B's first answer.
    assert by_reply.parent == first["answers"][B]["checkpoint_id"]
    # By the turn id: on its first reply's branch.
    first_model = by_turn.answered[0]
    assert by_turn.parent == first["answers"][first_model]["checkpoint_id"]

    joined = await _arena(graph, "t", [C], join_turn=second["answers"][B]["checkpoint_id"])
    path = await _path(graph, "t", joined["answers"][C]["checkpoint_id"])
    assert [m["content"] for m in path] == ["Start", f"reply from {B}", "Go on", f"reply from {C}"]


@pytest.mark.asyncio
async def test_a_frame_may_pin_the_fork_point(calls, graph):
    first = await _arena(graph, "t", [A, B], "Start")
    second = await _arena(graph, "t", [A, B], "Go on")
    turn = await _turn_id(graph, "t", second["answers"][A]["checkpoint_id"])
    join = await arena.join_point(graph, "t", turn, C, first["answers"][B]["checkpoint_id"])
    assert join.parent == first["answers"][B]["checkpoint_id"]


@pytest.mark.asyncio
async def test_joining_an_earlier_turn_leaves_the_latest_turn_the_latest(calls, graph):
    first = await _arena(graph, "t", [A, B], "Start")
    second = await _arena(graph, "t", [A, B], "Go on")
    before = await arena.turn_start(graph, "t")

    await _arena(graph, "t", [C], join_turn=first["answers"][A]["checkpoint_id"])

    after = await arena.turn_start(graph, "t")
    assert (after.default, after.parents) == (before.default, before.parents)
    assert after.parents == {m: second["answers"][m]["checkpoint_id"] for m in (A, B)}
    # The joining run's checkpoints are marked; the head passes over them.
    states = await thread_state_map(graph, "t")
    assert any(s.metadata.get(JOINED_KEY) for s in states.values())


@pytest.mark.asyncio
async def test_a_model_joining_the_latest_turn_then_continues_its_own_answer(calls, graph):
    first = await _arena(graph, "t", [A, B], "Start")
    joined = await _arena(graph, "t", [C], join_turn=first["answers"][A]["checkpoint_id"])

    start = await arena.turn_start(graph, "t")

    assert start.parent_for(C) == joined["answers"][C]["checkpoint_id"]
    assert start.parent_for(A) == first["answers"][A]["checkpoint_id"]


@pytest.mark.asyncio
async def test_the_turns_documents_and_deliberation_go_with_the_joined_question(calls, graph):
    await _arena(graph, "t", [A], "Start")
    first = await _arena(graph, "t", [A, B], documents={"notes.txt": "The code word is heron."},
                         is_deliberation=True)
    joined = await _arena(graph, "t", [C], join_turn=first["answers"][A]["checkpoint_id"])

    state = await graph.aget_state(thread_config("t", joined["answers"][C]["checkpoint_id"]))
    assert state.values["attached_documents"] == ["notes.txt"]
    # The draft resets the flag on the reply; the question C was asked carries it.
    asked = await graph.aget_state(state.parent_config)
    while asked.values["messages"][-1].type != "human":
        asked = await graph.aget_state(asked.parent_config)
    assert asked.values["is_deliberation"] is True
    assert (await arena.join_point(graph, "t", first["answers"][B]["checkpoint_id"], "gpt-6.1-sol")).is_deliberation


@pytest.mark.asyncio
@pytest.mark.parametrize("case, message", [
    ("unknown turn", "not found"),
    ("answered", "already answered"),
    ("question", "not a reply"),
    ("synthesis", "synthesis"),
    ("unknown model", "Invalid model"),
])
async def test_refusals(calls, graph, case, message):
    first = await _arena(graph, "t", [A, B], "Start")
    model, turn = C, await _turn_id(graph, "t", first["answers"][A]["checkpoint_id"])
    if case == "unknown turn":
        turn = "no-such-turn"
    elif case == "answered":
        model = B
    elif case == "question":
        turn = await arena.question_point(graph, "t", first["answers"][A]["checkpoint_id"])
    elif case == "synthesis":
        synthesis = await arena.collect(arena.synthesize_thread(graph, "t", A))
        turn = synthesis["synthesis"]["checkpoint_id"]
    elif case == "unknown model":
        model = "nope-1"
    calls.clear()
    with pytest.raises(ValueError, match=message):
        await arena.join_point(graph, "t", turn, model)
    assert calls == []


@pytest.mark.asyncio
async def test_a_join_takes_no_prompt_or_synthesis(calls, graph):
    first = await _arena(graph, "t", [A, B], "Start")
    turn = first["answers"][A]["checkpoint_id"]
    with pytest.raises(ValueError, match="no prompt"):
        await _arena(graph, "t", [C], "Another question", join_turn=turn)
    with pytest.raises(ValueError, match="synthesis"):
        await arena.collect(arena.run_arena(graph, "", "t", [C], {}, A, join_turn=turn))
    with pytest.raises(ValueError, match="Name the model"):
        await _arena(graph, "t", None, join_turn=turn)


# ─── The chat socket ─────────────────────────────────────────────


@pytest.fixture
def client(tmp_path, monkeypatch):
    point(monkeypatch, db_path=str(tmp_path / "ws.sqlite"))
    with (
        use_model_factory(ScriptedModelFactory(delay=0.03)),
        patch.dict(os.environ, KEYS),
        TestClient(server) as test_client,
    ):
        yield test_client


def _wait(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


def _until(ws, done, limit=800):
    frames = []
    for _ in range(limit):
        frame = ws.receive_json()
        frames.append(frame)
        if done(frame):
            return frames
    raise AssertionError(f"never satisfied; got {[f['type'] for f in frames]}")


def _first_turn(ws, models=(A, B), prompt="Which colour?"):
    for model in models:
        ws.send_json({"message": prompt, "model": model, "parent_checkpoint_id": None, "toggles": {}})
    ends = {}
    _until(ws, lambda f: f["type"] == "stream_end" and (ends.update({f["model"]: f}) or len(ends) == len(models)))
    return ends


def test_the_socket_adds_a_model_to_a_finished_turn(client):
    with client.websocket_connect("/ws/t-join") as ws:
        _until(ws, lambda f: f["type"] == "attached")
        ends = _first_turn(ws)
        turn = ends[A]["turn_id"]
        ws.send_json({"model": C, "join_turn": turn, "toggles": {}})
        frames = _until(ws, lambda f: f["type"] in ("stream_end", "error") and f["model"] == C)

    start = next(f for f in frames if f["type"] == "stream_start")
    end = frames[-1]
    assert end["type"] == "stream_end", end
    assert start["joins_turn"] is True and start["message"] is None and start["turn_id"] == turn
    assert end["turn_id"] == turn and end["joins_turn"] is True
    assert start["parent_checkpoint_id"] == ends[A]["parent_checkpoint_id"]
    assert [m["content"] for m in end["messages"]][0] == "Which colour?"
    assert {f["model"] for f in frames if f["type"] == "stream_start"} == {C}
    tree = client.get("/history/t-join").json()
    replies = [n for n in tree["nodes"] if n["metadata"].get("role") == "ai"]
    assert {n["metadata"]["active_peer"] for n in replies} == {A, B, C}
    assert {n["metadata"]["turn_id"] for n in replies} == {turn}


def test_the_socket_refuses_a_model_that_already_answered(client):
    with client.websocket_connect("/ws/t-twice") as ws:
        _until(ws, lambda f: f["type"] == "attached")
        ends = _first_turn(ws)
        ws.send_json({"model": B, "join_turn": ends[A]["checkpoint_id"], "toggles": {}})
        error = _until(ws, lambda f: f["type"] == "error")[-1]
    assert error["model"] == B and "already answered" in error["message"] and error["joins_turn"] is True


def test_a_joining_run_resumes_on_a_new_socket_as_one_more_card_of_its_turn(client):
    with client.websocket_connect("/ws/t-rejoin") as ws:
        _until(ws, lambda f: f["type"] == "attached")
        ends = _first_turn(ws, models=(A,))
        turn = ends[A]["turn_id"]
        ws.send_json({"model": C, "join_turn": turn, "toggles": {}})
        _until(ws, lambda f: f["type"] == "stream_token" and f["model"] == C)

    with client.websocket_connect("/ws/t-rejoin") as ws:
        frames = _until(ws, lambda f: f["type"] == "attached")
        resume = next(f for f in frames if f["type"] == "stream_resume")
        assert resume["model"] == C and resume["turn_id"] == turn and resume["joins_turn"] is True
        # The question is on the thread already; the turn's models say it is a card among them.
        assert resume["message"] is None and resume["turn_models"] == [A, C]
        assert frames[-1]["runs"] == [{"model": C, "turn_id": turn}]
        end = _until(ws, lambda f: f["type"] == "stream_end")[-1]
    assert end["turn_id"] == turn


def test_a_join_while_a_turn_runs_keeps_its_own_turn(client):
    with client.websocket_connect("/ws/t-mixed") as ws:
        _until(ws, lambda f: f["type"] == "attached")
        ends = _first_turn(ws, models=(A,))
        old = ends[A]["turn_id"]
        # Frames that arrive while the socket's runs are still finishing belong to their turn.
        _wait(lambda: not client.app.state.runs.chat.live("t-mixed"))
        ws.send_json({"message": "Next", "model": A, "parent_checkpoint_id": None, "toggles": {}})
        ws.send_json({"model": C, "join_turn": old, "toggles": {}})
        ws.send_json({"message": "Next", "model": B, "parent_checkpoint_id": None, "toggles": {}})
        got = {}
        _until(ws, lambda f: f["type"] == "stream_end" and (got.update({f["model"]: f}) or len(got) == 3))
    assert got[C]["turn_id"] == old
    assert got[A]["turn_id"] == got[B]["turn_id"] != old


def test_post_chat_joins_a_turn(client):
    first = client.post("/chat", json={"message": "Which colour?", "thread_id": "t-rest", "model": A}).json()
    joined = client.post("/chat", json={"thread_id": "t-rest", "model": C, "join_turn": first["checkpoint_id"]})
    assert joined.status_code == 200, joined.text
    assert joined.json()["turn_id"] == first["turn_id"]
    assert [m["content"] for m in joined.json()["messages"]][0] == "Which colour?"
    again = client.post("/chat", json={"thread_id": "t-rest", "model": C, "join_turn": first["checkpoint_id"]})
    assert again.status_code == 400 and "already answered" in again.json()["detail"]
    assert client.post("/chat", json={"thread_id": "t-rest", "model": A}).status_code == 400


# ─── CLI and MCP ─────────────────────────────────────────────────

runner = CliRunner()


def _json(args):
    result = runner.invoke(cli_app, args)
    assert result.exit_code == 0, (result.stdout, result.stderr, result.exception)
    return json.loads(result.stdout)


def test_the_cli_adds_a_model_by_a_replys_checkpoint(calls):
    first = _json(["arena", "Which colour?", "-m", A, "-m", B, "-t", "t-cli", "--no-synthesize", "--format", "json"])
    calls.clear()
    out = _json(["arena", "-t", "t-cli", "--join-turn", first["answers"][B]["checkpoint_id"], "-m", C,
                 "--format", "json"])
    assert calls == [C]
    assert out["turn_id"] == first["turn_id"] and out["prompt"] == "Which colour?"
    assert out["answers"][C]["content"] == f"reply from {C}" and out["synthesis"] is None

    chat = _json(["chat", "-t", "t-cli", "--join-turn", first["turn_id"], "-m", "gpt-6.1-sol", "--format", "json"])
    assert chat["turn_id"] == first["turn_id"] and chat["content"] == "reply from gpt-6.1-sol"

    refused = runner.invoke(cli_app, ["chat", "-t", "t-cli", "--join-turn", first["turn_id"], "-m", A, "--format", "json"])
    assert refused.exit_code == 1 and "already answered" in refused.stderr


@pytest.mark.parametrize("args", [
    ["arena", "A prompt", "-t", "t", "--join-turn", "x", "-m", C],
    ["arena", "--join-turn", "x", "-m", C],
    ["arena", "-t", "t", "--join-turn", "x"],
    ["arena", "-t", "t", "--join-turn", "x", "-m", C, "--deliberate"],
    ["arena", "-t", "t", "--join-turn", "x", "-m", C, "--judge", A],
])
def test_the_cli_refuses_join_options_that_cant_work(calls, args):
    result = runner.invoke(cli_app, args)
    assert result.exit_code == 2, (result.stdout, result.stderr)
    assert calls == []


@pytest.mark.asyncio
async def test_mcp_adds_a_model_to_a_turn(calls):
    from app.mcp_server import mcp

    async with Client(mcp) as client:
        first = (await client.call_tool("invoke_arena", {"prompt": "Which colour?", "models": [A, B],
                                                         "synthesize": False})).data
        calls.clear()
        joined = (await client.call_tool("invoke_arena", {"thread_id": first["thread_id"], "models": [C],
                                                          "join_turn": first["turn_id"]})).data
        assert calls == [C]
        assert joined["turn_id"] == first["turn_id"] and joined["synthesis"] is None
        assert [a["model"] for a in joined["answers"]] == [C]
        with pytest.raises(ToolError, match="already answered"):
            await client.call_tool("invoke_arena", {"thread_id": first["thread_id"], "models": [A],
                                                    "join_turn": first["turn_id"]})
        with pytest.raises(ToolError, match="no prompt"):
            await client.call_tool("invoke_arena", {"thread_id": first["thread_id"], "models": [C],
                                                    "prompt": "Q", "join_turn": first["turn_id"]})
