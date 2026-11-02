"""Runs belong to the server, not the socket that started them (services/live.py).

Chat turns and debates over the real sockets, the real graph on the test's own
SQLite file, and the scripted fake LLM streaming word by word: a socket closes
mid-run, the run goes on, and another socket attaches to it.
"""

import asyncio
import os
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core import database as db
from app.llm import use_model_factory
from app.llm.fake import ScriptedModelFactory
from app.main import server
from app.services import debate as debate_svc
from app.services.live import ChatRunState, ChatTurn, DebateRunState, RunRegistry
from tests.storage_helpers import point

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B = "gpt-5.4", "claude-sonnet-5"
POLICY = {"max_rounds": 2, "convergence_threshold": None, "llm_judge": None, "mode": "all"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    point(monkeypatch, db_path=str(tmp_path / "live.sqlite"))
    # ~33 words a reply at 30 ms a word: about a second, long enough to drop
    # a socket mid-reply.
    with (
        use_model_factory(ScriptedModelFactory(delay=0.03)),
        patch.dict(os.environ, KEYS),
        TestClient(server) as test_client,
    ):
        yield test_client


def _until(ws, done, limit=500):
    frames = []
    for _ in range(limit):
        frame = ws.receive_json()
        frames.append(frame)
        if done(frame):
            return frames
    raise AssertionError(f"never satisfied; got {[f['type'] for f in frames]}")


def _send_turn(ws, prompt="Compare the two", models=(A, B)):
    for model in models:
        ws.send_json({"message": prompt, "model": model, "parent_checkpoint_id": None, "toggles": {}})


def _reply(end: dict) -> str:
    return [m for m in end["messages"] if m["role"] == "assistant"][-1]["content"]


def _wait(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


# ─── Chat ────────────────────────────────────────────────────────


def test_a_new_socket_with_nothing_running_is_told_so(client):
    with client.websocket_connect("/ws/t-quiet") as ws:
        assert ws.receive_json() == {"type": "attached", "thread_id": "t-quiet", "runs": []}


def test_a_turn_outlives_its_socket_and_a_new_socket_resumes_it(client):
    with client.websocket_connect("/ws/t-reload") as ws:
        _until(ws, lambda f: f["type"] == "attached")
        _send_turn(ws)
        seen: set[str] = set()
        _until(ws, lambda f: f["type"] == "stream_token" and (seen.add(f["model"]) or len(seen) == 2))
    # The tab reloaded mid-turn. The runs are still going.
    runs = client.app.state.runs.chat
    assert len(runs.live("t-reload")) == 2

    with client.websocket_connect("/ws/t-reload") as ws:
        frames = _until(ws, lambda f: f["type"] == "attached")
        resumes = {f["model"]: f for f in frames if f["type"] == "stream_resume"}
        assert set(resumes) == {A, B}
        assert frames[-1]["runs"] and {r["model"] for r in frames[-1]["runs"]} == {A, B}
        for model, resume in resumes.items():
            assert resume["content_so_far"].startswith("Scripted")
            assert resume["message"] == "Compare the two" and resume["kind"] is None
            assert resume["turn_models"] == [A, B]
            assert resume["parent_checkpoint_id"] and resume["turn_id"]
        # One coalesced frame per run, then only what came after it.
        text = {m: r["content_so_far"] for m, r in resumes.items()}
        ends = {}
        for frame in _until(ws, lambda f: f["type"] == "stream_end" and (ends.update({f["model"]: f}) or len(ends) == 2)):
            if frame["type"] == "stream_token":
                text[frame["model"]] += frame["token"]
        for model, end in ends.items():
            assert text[model] == _reply(end)
            assert end["turn_id"] == resumes[model]["turn_id"]
    _wait(lambda: not runs.live("t-reload"))


def test_a_turn_finishes_with_no_socket_at_all(client):
    with client.websocket_connect("/ws/t-gone") as ws:
        _until(ws, lambda f: f["type"] == "attached")
        _send_turn(ws, models=(A,))
        _until(ws, lambda f: f["type"] == "stream_start")
    runs = client.app.state.runs.chat
    _wait(lambda: not runs.live("t-gone"))
    history = client.get("/history/t-gone").json()
    replies = [n for n in history["nodes"] if "Scripted answer" in (n.get("data") or {}).get("label", "")]
    assert len(replies) == 1
    # The first turn of a new thread is titled even though nobody was watching.
    assert db.get_thread_title("t-gone")


def test_two_sockets_on_one_thread_both_get_the_stream(client):
    with client.websocket_connect("/ws/t-two") as first, client.websocket_connect("/ws/t-two") as second:
        _until(first, lambda f: f["type"] == "attached")
        _until(second, lambda f: f["type"] == "attached")
        _send_turn(first, models=(A,))
        mine = _until(first, lambda f: f["type"] == "stream_end")
        theirs = _until(second, lambda f: f["type"] == "stream_end")
    assert mine[-1]["checkpoint_id"] == theirs[-1]["checkpoint_id"]
    start = next(f for f in theirs if f["type"] == "stream_start")
    assert start["message"] == "Compare the two" and start["kind"] is None


def test_stop_from_another_socket_stops_the_turn(client):
    with client.websocket_connect("/ws/t-stop") as first:
        _until(first, lambda f: f["type"] == "attached")
        _send_turn(first)
        _until(first, lambda f: f["type"] == "stream_token")
        with client.websocket_connect("/ws/t-stop") as second:
            _until(second, lambda f: f["type"] == "attached")
            second.send_json({"type": "stop"})
            stopped: set[str] = set()
            _until(second, lambda f: f["type"] == "stream_stopped" and (stopped.add(f["model"]) or len(stopped) == 2))
        # The tab that started it is told too, or its cards would stream forever.
        stopped_first: set[str] = set()
        frames = _until(first, lambda f: f["type"] == "stream_stopped" and (stopped_first.add(f["model"]) or len(stopped_first) == 2))
        assert not [f for f in frames if f["type"] == "stream_end"]
    assert not client.app.state.runs.chat.live("t-stop")


# ─── Debates ─────────────────────────────────────────────────────


def test_a_debate_outlives_its_socket_and_a_new_socket_resumes_it(client):
    session = debate_svc.create_session("t-debate", [A, B], POLICY)
    sid = session["session_id"]
    with client.websocket_connect(f"/debate/ws/{sid}") as ws:
        assert ws.receive_json() == {"type": "attached", "session_id": sid, "live": False}
        ws.send_json({"type": "debate_start", "prompt": "Tabs or spaces?", "toggles": {}})
        _until(ws, lambda f: f["type"] == "stream_token")
    assert db.get_debate_session(sid)["status"] == "running"

    with client.websocket_connect(f"/debate/ws/{sid}") as ws:
        frames = _until(ws, lambda f: f["type"] == "attached")
        assert frames[-1]["live"] is True
        resume = next(f for f in frames if f["type"] == "debate_resume")
        assert resume["question"] == "Tabs or spaces?" and resume["status"] == "running"
        assert resume["round"] is not None and resume["answers"]
        assert any(a["content"].startswith("Scripted") for a in resume["answers"])
        _until(ws, lambda f: f["type"] == "debate_session_status" and f["status"] == "completed")
    assert db.get_debate_session(sid)["status"] == "completed"
    transcript = client.get(f"/debate/sessions/{sid}/transcript").json()
    assert len(transcript["rounds"]) == 2


def test_a_debate_left_by_every_socket_still_completes(client):
    session = debate_svc.create_session("t-debate-gone", [A, B], POLICY)
    sid = session["session_id"]
    with client.websocket_connect(f"/debate/ws/{sid}") as ws:
        ws.send_json({"type": "debate_start", "prompt": "Vim or Emacs?", "toggles": {}})
        _until(ws, lambda f: f["type"] == "debate_round_start")
    _wait(lambda: db.get_debate_session(sid)["status"] == "completed", timeout=20)
    assert not client.app.state.runs.debates.live(sid)


def test_server_shutdown_interrupts_a_running_debate(tmp_path, monkeypatch):
    point(monkeypatch, db_path=str(tmp_path / "shutdown.sqlite"))
    with use_model_factory(ScriptedModelFactory(delay=0.05)), patch.dict(os.environ, KEYS):
        with TestClient(server) as client:
            session = debate_svc.create_session("t-shutdown", [A, B], POLICY)
            sid = session["session_id"]
            with client.websocket_connect(f"/debate/ws/{sid}") as ws:
                ws.send_json({"type": "debate_start", "prompt": "Slow?", "toggles": {}})
                _until(ws, lambda f: f["type"] == "stream_token")
        # Leaving the block ran the lifespan's shutdown, which stopped the run.
        assert db.get_debate_session(sid)["status"] == "interrupted"


# ─── The registry itself ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_attaching_watcher_gets_the_resume_then_only_newer_frames():
    registry = RunRegistry()
    turn = ChatTurn("turn-1", models=[A])
    where = {"model": A, "parent_checkpoint_id": "cp", "turn_id": "turn-1"}
    release = asyncio.Event()

    async def body(run):
        run.emit({"type": "stream_start", **where, "model_color": "#123"})
        run.emit({"type": "stream_token", "token": "Hello ", "model": A})
        await release.wait()
        run.emit({"type": "stream_token", "token": "world", "model": A})
        run.emit({"type": "stream_end", **where})

    run = registry.start("t", ChatRunState(turn, A, where, message="Q", kind=None), body)
    await asyncio.sleep(0)
    seen: list[dict] = []
    assert registry.watch("t", seen.append) == [run]
    release.set()
    await run.task
    assert [f["type"] for f in seen] == ["stream_resume", "stream_token", "stream_end"]
    assert seen[0]["content_so_far"] == "Hello " and seen[0]["model_color"] == "#123"
    # Ended runs are gone, and a finished reply has nothing to resume.
    assert registry.live("t") == [] and run.state.resume() is None


@pytest.mark.asyncio
async def test_a_watcher_that_fails_is_dropped_and_the_run_goes_on():
    registry = RunRegistry()
    seen: list[dict] = []

    def broken(_frame):
        raise RuntimeError("socket gone")

    registry.watch("t", broken)
    registry.watch("t", seen.append)
    registry.publish("t", {"type": "x"})
    registry.publish("t", {"type": "y"})
    assert [f["type"] for f in seen] == ["x", "y"]


@pytest.mark.asyncio
async def test_a_run_that_has_said_its_last_is_not_reported_as_caught_up():
    """A chat run titles a new thread after its stream_end: still a task, but
    a reconnecting tab must not wait for a stream_end that already went."""
    registry = RunRegistry()
    turn = ChatTurn("turn-1", models=[A])
    where = {"model": A, "parent_checkpoint_id": "cp", "turn_id": "turn-1"}
    release = asyncio.Event()

    async def body(run):
        run.emit({"type": "stream_start", **where})
        run.emit({"type": "stream_end", **where})
        await release.wait()  # e.g. naming the thread

    run = registry.start("t", ChatRunState(turn, A, where, message="Q", kind=None), body)
    await asyncio.sleep(0)
    seen: list[dict] = []
    assert registry.live("t") == [run]
    assert registry.watch("t", seen.append) == [] and seen == []
    release.set()
    await run.task


def test_a_debate_resume_says_pausing_until_the_round_ends():
    state = DebateRunState("s")
    state.record({"type": "debate_session_created", "question": "Q"})
    state.record({"type": "debate_round_start", "round": 1})
    state.record({"type": "stream_start", "model": A})
    state.record({"type": "stream_token", "model": A, "token": "half"})
    state.record({"type": "stream_start", "model": B})
    state.record({"type": "stream_end", "model": B, "content": "whole", "checkpoint_id": "cp-b"})
    state.control.pause()
    resume = state.resume()
    assert resume["status"] == "pausing" and resume["round"] == 1 and resume["question"] == "Q"
    assert resume["answers"] == [
        {"model": A, "content": "half", "done": False},
        {"model": B, "content": "whole", "done": True, "checkpoint_id": "cp-b"},
    ]
    state.record({"type": "debate_session_status", "status": "paused"})
    assert state.resume()["status"] == "paused"
    # A synthesizer that also debated: its tokens go to the synthesis.
    state.record({"type": "debate_synthesis_start", "model": A})
    state.record({"type": "stream_token", "model": A, "token": "map"})
    assert state.resume()["synthesis"] == {"model": A, "content": "map", "done": False}
    assert state.resume()["answers"][0]["content"] == "half"
