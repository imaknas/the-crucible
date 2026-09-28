"""WebSocket control flow in api/debate.py, with run_debate stubbed out."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api import debate as debate_api
from app.main import server as app

SESSION = {
    "session_id": "debate-ws",
    "parent_thread_id": "t",
    "participants": ["gpt-5.4", "claude-sonnet-5"],
    "thread_ids": {},
    "status": "running",
    "synthesizer_model": "gpt-5.4",
}


@pytest.fixture
def ws_env():
    state = {"cancelled": 0, "statuses": [], "controls": []}

    async def slow_debate(**kwargs):
        state["controls"].append(kwargs.get("control"))
        state.setdefault("contexts", []).append(kwargs.get("context"))
        yield {"type": "debate_round_start", "round": 0}
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            state["cancelled"] += 1
            raise

    async def fake_synthesis(**kwargs):
        yield {"type": "debate_synthesis_end", "content": "done"}

    with (
        patch.object(debate_api.db, "get_debate_session", return_value=dict(SESSION)),
        patch.object(debate_api.db, "update_debate_session", side_effect=lambda sid, **kw: state["statuses"].append(kw.get("status"))),
        patch.object(debate_api.debate_svc, "run_debate", side_effect=slow_debate),
        patch.object(debate_api.debate_svc, "_stream_synthesis", side_effect=fake_synthesis),
        TestClient(app) as client,
    ):
        client.app.state.graph_app = MagicMock()
        yield client, state


def _recv_until(ws, type_, status=None):
    for _ in range(20):
        msg = ws.receive_json()
        if msg["type"] == type_ and (status is None or msg.get("status") == status):
            return msg
    raise AssertionError(f"never received {type_}/{status}")


def test_inject_without_running_debate_errors(ws_env):
    client, _ = ws_env
    with client.websocket_connect("/debate/ws/debate-ws") as ws:
        ws.send_json({"type": "debate_inject", "message": "hi"})
        assert "No debate is running" in _recv_until(ws, "error")["message"]


def test_inject_reaches_the_running_debate(ws_env):
    client, state = ws_env
    with client.websocket_connect("/debate/ws/debate-ws") as ws:
        ws.send_json({"type": "debate_start", "prompt": "Q"})
        _recv_until(ws, "debate_round_start")
        ws.send_json({"type": "debate_inject", "message": "consider cost"})
        _recv_until(ws, "debate_session_status", "inject_queued")
        assert state["controls"][0].injected == ["consider cost"]
        ws.send_json({"type": "debate_control", "action": "stop"})
        _recv_until(ws, "debate_session_status", "completed")


def test_stop_cancels_the_debate(ws_env):
    client, state = ws_env
    with client.websocket_connect("/debate/ws/debate-ws") as ws:
        ws.send_json({"type": "debate_start", "prompt": "Q"})
        _recv_until(ws, "debate_round_start")
        ws.send_json({"type": "debate_control", "action": "stop"})
        _recv_until(ws, "debate_session_status", "completed")
    assert state["cancelled"] == 1


def test_synthesize_cancels_running_debate_first(ws_env):
    client, state = ws_env
    with client.websocket_connect("/debate/ws/debate-ws") as ws:
        ws.send_json({"type": "debate_start", "prompt": "Q"})
        _recv_until(ws, "debate_round_start")
        ws.send_json({"type": "debate_synthesize", "prompt": "Q"})
        _recv_until(ws, "debate_synthesis_end")
        _recv_until(ws, "debate_session_status", "completed")
    assert state["cancelled"] == 1


def test_pause_is_acknowledged_and_resume_restores(ws_env):
    client, state = ws_env
    with client.websocket_connect("/debate/ws/debate-ws") as ws:
        ws.send_json({"type": "debate_start", "prompt": "Q"})
        _recv_until(ws, "debate_round_start")
        ws.send_json({"type": "debate_control", "action": "pause"})
        _recv_until(ws, "debate_session_status", "pausing")
        assert state["controls"][0].paused
        ws.send_json({"type": "debate_control", "action": "resume"})
        _recv_until(ws, "debate_session_status", "running")
        assert not state["controls"][0].paused
        ws.send_json({"type": "debate_control", "action": "stop"})
        _recv_until(ws, "debate_session_status", "completed")


def test_disconnect_mid_debate_marks_interrupted(ws_env):
    client, state = ws_env
    with client.websocket_connect("/debate/ws/debate-ws") as ws:
        ws.send_json({"type": "debate_start", "prompt": "Q"})
        _recv_until(ws, "debate_round_start")
    # The handler's finally runs on the server loop after the client closes.
    for _ in range(50):
        if "interrupted" in state["statuses"]:
            break
        import time
        time.sleep(0.02)
    assert "interrupted" in state["statuses"]


def test_a_redirect_keeps_the_summarizer_the_debate_started_with(ws_env, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    client, state = ws_env
    with client.websocket_connect("/debate/ws/debate-ws") as ws:
        ws.send_json({"type": "debate_start", "prompt": "Q", "summarizer": "gpt-6-luna"})
        _recv_until(ws, "debate_round_start")
        ws.send_json({"type": "debate_redirect", "message": "narrower"})
        _recv_until(ws, "debate_round_start")
        assert [c.summarizer for c in state["contexts"]] == ["gpt-6-luna", "gpt-6-luna"]
        ws.send_json({"type": "debate_control", "action": "stop"})
        _recv_until(ws, "debate_session_status", "completed")


def test_a_summarizer_without_a_key_is_refused_before_the_debate_starts(ws_env, monkeypatch):
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    client, state = ws_env
    with client.websocket_connect("/debate/ws/debate-ws") as ws:
        ws.send_json({"type": "debate_start", "prompt": "Q", "summarizer": "gpt-6-luna"})
        assert "No API key" in _recv_until(ws, "error")["message"]
    assert not state.get("contexts")
