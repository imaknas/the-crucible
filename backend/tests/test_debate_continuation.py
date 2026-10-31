"""A chat turn sent after a finished debate continues that debate.

The debate writes only to its sub-threads, so a turn on the parent thread
used to start from nothing ("I don't see any arguments above") while the
screen showed the whole debate, and, being the parent's first checkpoint,
its auto-title overwrote the debate's title. Real graph and checkpointer
(the app's lifespan), fake LLM that records what each call was shown.
"""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.core import database as db
from app.llm import CallableModelFactory, use_model_factory
from app.main import server
from app.services import debate as debate_svc
from tests.storage_helpers import point

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B = "gpt-5.4", "claude-sonnet-5"
QUESTION = "Monolith or microservices?"

SEEN: dict[str, list[str]] = {}


class _Recorder(FakeListChatModel):
    model_id: str = ""

    def _record(self, messages):
        SEEN.setdefault(self.model_id, []).append("\n".join(str(m.content) for m in messages))

    def _call(self, messages, *args, **kwargs):
        self._record(messages)
        return super()._call(messages, *args, **kwargs)

    def _stream(self, messages, *args, **kwargs):
        self._record(messages)
        yield from super()._stream(messages, *args, **kwargs)


def _model(model_id, _toggles):
    return _Recorder(responses=[f"argument from {model_id}"], model_id=model_id)


@pytest.fixture
def client(tmp_path, monkeypatch):
    SEEN.clear()
    point(monkeypatch, db_path=str(tmp_path / "continue.sqlite"))
    with (
        use_model_factory(CallableModelFactory(_model)),
        patch.dict(os.environ, KEYS),
        TestClient(server) as test_client,
    ):
        yield test_client


def _until(ws, predicate, limit=200):
    frames = []
    for _ in range(limit):
        frames.append(ws.receive_json())
        if predicate(frames[-1]):
            return frames
    raise AssertionError(f"condition never met: {frames[-5:]}")


def _run_debate(client, thread_id: str, auto_synthesize=False) -> str:
    session = client.post(
        "/debate/sessions",
        json={
            "parent_thread_id": thread_id,
            "participants": [A, B],
            "termination_policy": {"max_rounds": 2},
            "auto_synthesize": auto_synthesize,
        },
    ).json()
    with client.websocket_connect(f"/debate/ws/{session['session_id']}") as ws:
        ws.send_json({"type": "debate_start", "prompt": QUESTION, "toggles": {}})
        _until(ws, lambda f: f["type"] == "debate_session_status" and f["status"] == "completed")
    return session["session_id"]


def _chat(client, thread_id: str, frame: dict) -> list[dict]:
    with client.websocket_connect(f"/ws/{thread_id}") as ws:
        ws.send_json({"model": A, "toggles": {}, **frame})
        return _until(ws, lambda f: f["type"] in ("stream_end", "error"))


def test_a_turn_after_a_debate_sees_the_question_and_every_round(client):
    session_id = _run_debate(client, "t-debate", auto_synthesize=True)
    SEEN.clear()
    frames = _chat(client, "t-debate", {"message": "Which argument was weakest?", "debate_session_id": session_id})
    end = frames[-1]
    assert end["type"] == "stream_end", frames

    seen = SEEN[A][-1]
    assert QUESTION in seen
    peers = debate_svc.session_peers(db.get_debate_session(session_id))
    for model in (A, B):
        assert f"[{peers.label(model)}]:\nRound 1 (independent answer):\nargument from {model}" in seen
    assert "Synthesis by" in seen
    assert "Which argument was weakest?" in seen

    # The parent's transcript now shows the debate it continues, marked as such.
    record = next(m for m in end["messages"] if m.get("kind") == "debate")
    assert record["model_name"] == "Debate"
    assert [m["role"] for m in end["messages"]] == ["user", "assistant", "user", "assistant"]


def test_later_turns_reuse_the_debate_record(client):
    session_id = _run_debate(client, "t-again")
    first = _chat(client, "t-again", {"message": "One?", "debate_session_id": session_id})[-1]
    second = _chat(client, "t-again", {"message": "Two?", "debate_session_id": session_id})[-1]
    first_parent = [m["content"] for m in first["messages"][:2]]
    second_parent = [m["content"] for m in second["messages"][:2]]
    assert first_parent == second_parent
    records = [m for m in second["messages"] if m.get("kind") == "debate"]
    assert len(records) == 1


def test_a_turn_after_a_debate_keeps_the_debate_title(client):
    session_id = _run_debate(client, "t-title")
    title = db.get_thread_title("t-title")
    assert title.startswith("Debate:")
    frames = _chat(client, "t-title", {"message": "Follow-up question", "debate_session_id": session_id})
    assert frames[-1]["type"] == "stream_end", frames
    assert db.get_thread_title("t-title") == title


def test_an_untitled_threads_first_turn_is_still_titled(client):
    with client.websocket_connect("/ws/t-fresh") as ws:
        ws.send_json({"message": "Plain first question", "model": A, "toggles": {}})
        _until(ws, lambda f: f["type"] == "title_update")
    assert db.get_thread_title("t-fresh") == "Plain first question"


def test_an_unknown_debate_is_reported(client):
    frames = _chat(client, "t-none", {"message": "Hi", "debate_session_id": "debate-missing"})
    assert frames[-1]["type"] == "error"
    assert "not found" in frames[-1]["message"]
