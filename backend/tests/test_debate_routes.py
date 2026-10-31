"""Every debate REST route over HTTP, against finished debates.

The app's lifespan compiles the real graph on the test's own SQLite file and
the debates run through the debate socket, as the web UI runs them; only the
LLM is faked (each model replies "argument from <id>"). No stability check
or judge, so nothing loads the embedding model. Request validation of
POST /debate/sessions is in test_debate_limits.py.
"""

import os
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.core import database as db
from app.llm import CallableModelFactory, use_model_factory
from app.main import server
from tests.storage_helpers import point
from tests.test_debate_continuation import _until

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B = "gpt-5.4", "claude-sonnet-5"
POLICY = {"max_rounds": 2, "convergence_threshold": None, "llm_judge": None, "mode": "all"}


def _model(model_id, _toggles):
    return FakeListChatModel(responses=[f"argument from {model_id}"])


@pytest.fixture
def client(tmp_path, monkeypatch):
    point(monkeypatch, db_path=str(tmp_path / "routes.sqlite"))
    with (
        use_model_factory(CallableModelFactory(_model)),
        patch.dict(os.environ, KEYS),
        TestClient(server) as test_client,
    ):
        yield test_client


def _create(client, thread_id: str, **overrides) -> dict:
    res = client.post(
        "/debate/sessions",
        json={"parent_thread_id": thread_id, "participants": [A, B], "termination_policy": POLICY, **overrides},
    )
    assert res.status_code == 200, res.text
    return res.json()


def _run(client, session_id: str, question: str) -> None:
    with client.websocket_connect(f"/debate/ws/{session_id}") as ws:
        ws.send_json({"type": "debate_start", "prompt": question, "toggles": {}})
        frames = _until(ws, lambda f: f["type"] == "debate_session_status" and f["status"] == "completed")
    assert not [f for f in frames if f["type"] == "error"], frames


def _debate(client, thread_id: str, question: str, **overrides) -> dict:
    session = _create(client, thread_id, **overrides)
    _run(client, session["session_id"], question)
    return session


def _utc(stamp: str) -> datetime:
    parsed = datetime.fromisoformat(stamp)
    assert parsed.utcoffset() == timedelta(0), stamp
    return parsed


# ─── POST /debate/sessions ───────────────────────────────────────


def test_creating_a_session_returns_it_with_its_own_threads(client):
    session = _create(client, "t-new", synthesizer_model=B)
    sid = session["session_id"]
    assert sid.startswith("debate-")
    assert session["parent_thread_id"] == "t-new"
    assert session["participants"] == [A, B]
    # One lane per participant plus the synthesis, all scoped to this session.
    assert session["thread_ids"] == {
        A: f"t-new::{sid}::{A}",
        B: f"t-new::{sid}::{B}",
        "synthesis": f"t-new::{sid}::synthesis",
    }
    assert session["status"] == "pending"
    assert session["current_round"] == 0
    assert session["termination_policy"] == POLICY
    assert session["auto_synthesize"] is False
    assert session["synthesizer_model"] == B
    assert session["peer_labels"] == "anonymous"
    # Defaults the request left out are filled in.
    bare = client.post(
        "/debate/sessions", json={"parent_thread_id": "t-new", "participants": [A, B], "termination_policy": {}}
    ).json()
    assert bare["termination_policy"] == {"max_rounds": 3, "convergence_threshold": None, "llm_judge": None, "mode": "all"}
    assert bare["synthesizer_model"] is None


# ─── GET /debate/sessions ────────────────────────────────────────


def test_an_empty_database_lists_no_sessions(client):
    assert client.get("/debate/sessions").json() == []


def test_sessions_are_listed_newest_first_with_their_questions(client):
    first = _debate(client, "t-list", "First question?")
    second = _debate(client, "t-list", "Second question?")
    elsewhere = _debate(client, "t-other", "Elsewhere?")
    pending = _create(client, "t-list")

    rows = client.get("/debate/sessions").json()
    assert [r["session_id"] for r in rows] == [
        pending["session_id"], elsewhere["session_id"], second["session_id"], first["session_id"]
    ]
    on_thread = client.get("/debate/sessions", params={"parent_thread_id": "t-list"}).json()
    assert [r["session_id"] for r in on_thread] == [pending["session_id"], second["session_id"], first["session_id"]]

    by_id = {r["session_id"]: r for r in on_thread}
    assert by_id[first["session_id"]]["question"] == "First question?"
    assert by_id[first["session_id"]]["questions"] == [{"round": 0, "prompt": "First question?"}]
    assert by_id[second["session_id"]]["question"] == "Second question?"
    assert by_id[first["session_id"]]["status"] == "completed"
    # A session that never ran has no question yet.
    assert by_id[pending["session_id"]]["question"] is None
    assert by_id[pending["session_id"]]["questions"] == []
    for row in on_thread:
        _utc(row["created_at"])


def test_sessions_created_in_the_same_second_list_newest_first(client):
    """created_at has one-second resolution; ties came back oldest first,
    while the web UI opens index 0 as the newest debate."""
    ids = [_create(client, "t-tie")["session_id"] for _ in range(3)]
    conn = db.get_db_connection()
    try:
        conn.execute("UPDATE debate_sessions SET created_at = '2026-10-31 12:00:00'")
        conn.commit()
    finally:
        conn.close()
    rows = client.get("/debate/sessions", params={"parent_thread_id": "t-tie"}).json()
    assert [r["session_id"] for r in rows] == ids[::-1]
    assert rows[0]["created_at"] == "2026-10-31T12:00:00+00:00"


# ─── GET /debate/sessions/{id} ───────────────────────────────────


def test_a_finished_session_reads_back_with_its_question(client):
    session = _debate(client, "t-get", "Is it yes?")
    row = client.get(f"/debate/sessions/{session['session_id']}").json()
    assert row["session_id"] == session["session_id"]
    assert row["parent_thread_id"] == "t-get"
    assert row["thread_ids"] == session["thread_ids"]
    assert row["status"] == "completed"
    assert row["question"] == "Is it yes?"
    assert row["questions"] == [{"round": 0, "prompt": "Is it yes?"}]
    assert row["peer_labels"] == "anonymous"
    _utc(row["created_at"])


def test_an_unknown_session_is_404(client):
    for path in ("", "/tree", "/transcript"):
        res = client.get(f"/debate/sessions/debate-missing{path}")
        assert res.status_code == 404, path
        assert "debate-missing" in res.json()["detail"]
    assert client.delete("/debate/sessions/debate-missing").status_code == 404


# ─── GET /debate/sessions/{id}/tree ──────────────────────────────


def test_the_tree_draws_the_question_every_round_and_the_synthesis(client):
    session = _debate(client, "t-tree", "Tree question?", auto_synthesize=True)
    tree = client.get(f"/debate/sessions/{session['session_id']}/tree").json()

    prompt = next(n for n in tree["nodes"] if n["id"] == "debate::prompt")
    assert prompt["metadata"]["preview"] == "Tree question?"
    replies = [n for n in tree["nodes"] if n["metadata"].get("role") == "ai"]
    assert sorted((n["metadata"]["active_peer"], n["metadata"]["round_num"]) for n in replies) == sorted(
        [(A, 0), (A, 1), (B, 0), (B, 1)]
    )
    # The question fans out to each lane's first round.
    round0 = {n["id"] for n in replies if n["metadata"]["round_num"] == 0}
    assert {e["target"] for e in tree["edges"] if e["source"] == "debate::prompt"} == round0
    synthesis = [n for n in tree["nodes"] if n.get("type") == "synthesis"]
    assert synthesis and not any(n["metadata"].get("pending") for n in synthesis)


def test_the_tree_of_a_debate_without_synthesis_has_none(client):
    session = _debate(client, "t-tree2", "No synthesis?")
    tree = client.get(f"/debate/sessions/{session['session_id']}/tree").json()
    assert not [n for n in tree["nodes"] if n.get("type") == "synthesis"]
    assert len([n for n in tree["nodes"] if n["metadata"].get("role") == "ai"]) == 4


# ─── GET /debate/sessions/{id}/transcript ────────────────────────


def test_the_transcript_aligns_every_round_and_carries_the_synthesis(client):
    session = _debate(client, "t-script", "Transcript question?", auto_synthesize=True)
    transcript = client.get(f"/debate/sessions/{session['session_id']}/transcript").json()

    assert transcript["question"] == "Transcript question?"
    assert transcript["session"]["session_id"] == session["session_id"]
    assert transcript["session"]["status"] == "completed"
    assert set(transcript["labels"]) == {A, B}
    assert [r["round"] for r in transcript["rounds"]] == [0, 1]
    for r in transcript["rounds"]:
        assert r["question"] == "Transcript question?"
        assert r["responses"] == {A: f"argument from {A}", B: f"argument from {B}"}
        assert r["errors"] == {}
    # No synthesizer named: the first participant writes it.
    assert transcript["synthesis"]["model"] == A
    assert transcript["synthesis"]["model_name"]
    assert transcript["synthesis"]["content"] == f"argument from {A}"
    assert transcript["injected"] == []


def test_a_session_that_never_ran_has_an_empty_transcript(client):
    session = _create(client, "t-empty")
    transcript = client.get(f"/debate/sessions/{session['session_id']}/transcript").json()
    assert transcript["rounds"] == []
    assert transcript["synthesis"] is None
    assert transcript["session"]["status"] == "pending"


# ─── DELETE /debate/sessions/{id} ────────────────────────────────


def test_deleting_a_session_removes_its_threads_and_keeps_the_others(client):
    doomed = _debate(client, "t-del", "Doomed?", auto_synthesize=True)
    kept = _debate(client, "t-del", "Kept?", auto_synthesize=True)
    doomed_threads = db.session_thread_ids(db.get_debate_session(doomed["session_id"]))
    assert all(db.get_thread_checkpoint_graph(t) for t in doomed_threads)

    res = client.delete(f"/debate/sessions/{doomed['session_id']}")
    assert res.status_code == 204
    assert res.content == b""

    assert client.get(f"/debate/sessions/{doomed['session_id']}").status_code == 404
    for tid in doomed_threads:
        assert not db.get_thread_checkpoint_graph(tid), tid
    # The other debate on the same thread is untouched, and still reads in full.
    for tid in db.session_thread_ids(db.get_debate_session(kept["session_id"])):
        assert db.get_thread_checkpoint_graph(tid), tid
    assert [r["session_id"] for r in client.get("/debate/sessions").json()] == [kept["session_id"]]
    transcript = client.get(f"/debate/sessions/{kept['session_id']}/transcript").json()
    assert len(transcript["rounds"]) == 2 and transcript["synthesis"]
    # The parent conversation stays listed.
    assert "t-del" in [t["id"] for t in client.get("/threads").json()["threads"]]


def test_deleting_a_session_keeps_threads_another_session_still_names(client):
    """Sessions stored before thread ids were scoped share their parent's
    `{parent}::{model}` lanes; deleting one must not erase the other's."""
    legacy_ids = {A: f"t-legacy::{A}", B: f"t-legacy::{B}"}
    for sid in ("debate-legacy1", "debate-legacy2"):
        db.create_debate_session({
            "session_id": sid,
            "parent_thread_id": "t-legacy",
            "participants": [A, B],
            "thread_ids": dict(legacy_ids),
            "termination_policy": dict(POLICY),
        })
    _run(client, "debate-legacy1", "Shared lanes?")
    assert all(db.get_thread_checkpoint_graph(t) for t in legacy_ids.values())

    assert client.delete("/debate/sessions/debate-legacy1").status_code == 204
    for tid in legacy_ids.values():
        assert db.get_thread_checkpoint_graph(tid), tid
    tree = client.get("/debate/sessions/debate-legacy2/tree").json()
    assert len([n for n in tree["nodes"] if n["metadata"].get("role") == "ai"]) == 4

    # Once no session names them, they go with the last one.
    assert client.delete("/debate/sessions/debate-legacy2").status_code == 204
    for tid in legacy_ids.values():
        assert not db.get_thread_checkpoint_graph(tid), tid
    assert client.get("/debate/sessions", params={"parent_thread_id": "t-legacy"}).json() == []
