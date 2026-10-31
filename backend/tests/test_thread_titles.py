"""An untitled thread is listed under a readable name, never its raw id.

Threads from before auto-titling (and debate parents) have no stored title.
services/threads names them on the fly from their first message, or their
debate's question, without a model call and without writing anything.
Real LangGraph workflow on the SQLite checkpointer, fake LLM.
"""

import os
from unittest.mock import patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.core import database as db
from app.llm import CallableModelFactory, use_model_factory
from app.services import threads as threads_svc
from app.services.arena import open_graph
from app.services.chat import stream_turn
from app.services.runs import resolve_fork_point
from tests.storage_helpers import point

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
QUESTION = "Why did Paris become the capital of France rather than Lyon or Orléans?"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    point(monkeypatch, db_path=str(tmp_path / "titles.sqlite"))
    db.init_db()
    factory = CallableModelFactory(lambda model_id, _t: FakeListChatModel(responses=[f"reply from {model_id}"]))
    with use_model_factory(factory), patch.dict(os.environ, KEYS):
        yield


async def _turn(graph_app, thread, text):
    """One chat turn. stream_turn doesn't title the thread (the transports
    do), which is exactly the state a thread from before auto-titling is in."""
    parent = await resolve_fork_point(graph_app, thread)
    async for _ in stream_turn(graph_app, thread, parent, message=text, model="gpt-5.4"):
        pass


def _listed(thread_id):
    return next(t for t in threads_svc.list_threads() if t["id"] == thread_id)


def _debate(parent, session_id, questions):
    db.create_debate_session({
        "session_id": session_id,
        "parent_thread_id": parent,
        "participants": ["gpt-5.4", "claude-sonnet-5"],
        "thread_ids": {
            "gpt-5.4": f"{parent}::{session_id}::gpt-5.4",
            "claude-sonnet-5": f"{parent}::{session_id}::claude-sonnet-5",
            "synthesis": f"{parent}::{session_id}::synthesis",
        },
        "termination_policy": {"max_rounds": 1},
    })
    for q in questions:
        db.append_debate_entry(session_id, "questions", q)


@pytest.mark.asyncio
async def test_untitled_thread_is_named_by_its_first_message():
    async with open_graph() as graph_app:
        await _turn(graph_app, "thread_old", QUESTION)
        await _turn(graph_app, "thread_old", "And what about the second turn?")

    row = _listed("thread_old")
    assert row["title"] == "Why did Paris become the capital of…"
    assert row["title_derived"] is True
    # Nothing was written: the thread is still untitled in the database.
    assert db.get_thread_title("thread_old") is None


@pytest.mark.asyncio
async def test_a_real_title_wins_and_is_not_derived():
    async with open_graph() as graph_app:
        await _turn(graph_app, "thread_named", QUESTION)
    threads_svc.rename_thread("thread_named", "Capitals")

    row = _listed("thread_named")
    assert row["title"] == "Capitals"
    assert row["title_derived"] is False


@pytest.mark.asyncio
async def test_debate_only_parent_is_named_by_its_latest_debate():
    async with open_graph() as graph_app:
        # The lanes have checkpoints; the parent has none of its own.
        await resolve_fork_point(graph_app, "thread_debates::s-old::gpt-5.4")
        await resolve_fork_point(graph_app, "thread_debates::s-new::gpt-5.4")
    _debate("thread_debates", "s-old", [{"round": 0, "prompt": "An older debate"}])
    _debate("thread_debates", "s-new", [
        {"round": 2, "prompt": "A redirect"},
        {"round": 0, "prompt": "Is a hot dog a sandwich?"},
    ])

    row = _listed("thread_debates")
    # The question the newest debate started with, as auto-titling names a
    # debate's parent.
    assert row["title"] == "Debate: Is a hot dog a sandwich?"
    assert row["title_derived"] is True


@pytest.mark.asyncio
async def test_legacy_debate_without_stored_questions_is_named_from_its_lanes():
    async with open_graph() as graph_app:
        await _turn(graph_app, "thread_legacy::s1::gpt-5.4", "Should cities ban cars?")
    _debate("thread_legacy", "s1", [])

    assert _listed("thread_legacy")["title"] == "Debate: Should cities ban cars?"

    # Redirected after questions were recorded: only the redirect is stored,
    # and the debate is still named by the question it started with.
    db.append_debate_entry("s1", "questions", {"round": 3, "prompt": "What about bikes?"})
    assert _listed("thread_legacy")["title"] == "Debate: Should cities ban cars?"


@pytest.mark.asyncio
async def test_empty_thread_gets_a_plain_label_never_its_id():
    async with open_graph() as graph_app:
        await resolve_fork_point(graph_app, "thread_empty")

    row = _listed("thread_empty")
    assert row["title"] == threads_svc.UNTITLED == "Untitled conversation"
    assert row["title_derived"] is True
    assert "thread_empty" not in row["title"]


def test_naming_reads_only_the_first_checkpoints(monkeypatch):
    """list_threads runs on every sidebar refresh: titled threads cost
    nothing, untitled ones a bounded scan from the start of the thread."""
    calls = []
    monkeypatch.setattr(db, "list_threads", lambda: [
        {"id": "a", "title": "Named", "updated_at": None},
        {"id": "b", "title": None, "updated_at": None},
    ])
    monkeypatch.setattr(db, "first_messages", lambda ids: calls.append(list(ids)) or {})
    monkeypatch.setattr(db, "list_debate_sessions", lambda parent: [])

    assert [t["title"] for t in threads_svc.list_threads()] == ["Named", "Untitled conversation"]
    assert calls == [["b"]]
