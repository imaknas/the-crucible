"""Attached documents live once per thread, not in every checkpoint.

They used to be part of each turn's graph state, so every checkpoint (4-6 per
model per turn) stored the full text again.
"""

import os
import sqlite3
from typing import List
from unittest.mock import patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import BaseMessage
from langgraph.checkpoint.memory import MemorySaver

import app.services.graph as graph_mod
from app.core import database as db
from app.llm import CallableModelFactory, use_model_factory
from app.services import debate as debate_svc
from app.services.chat import stream_turn
from app.services.context import DEFAULT_CONTEXT
from app.services.documents import (
    DOCUMENT_STORE_CONFIG_KEY,
    attach_documents,
    documents_for_run,
    with_default_documents,
)
from app.services.runs import resolve_fork_point, tag_run, thread_config, final_state_of_run

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
DOC = {"paper.md": "The measured boiling point was 412 kelvin."}
SEEN: List[List[BaseMessage]] = []


class _Recorder(FakeListChatModel):
    """Answers like FakeListChatModel and records what each call was sent."""

    def _call(self, messages, *args, **kwargs):
        SEEN.append(list(messages))
        return super()._call(messages, *args, **kwargs)

    def _stream(self, messages, *args, **kwargs):  # what astream_events drives
        SEEN.append(list(messages))
        yield from super()._stream(messages, *args, **kwargs)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "docs.sqlite"))
    db.init_db()
    yield db


@pytest.fixture
def graph_app(isolated_db):
    SEEN.clear()
    factory = CallableModelFactory(lambda model_id, _t: _Recorder(responses=[f"reply from {model_id}"]))
    with use_model_factory(factory), patch.dict(os.environ, KEYS):
        yield graph_mod.workflow.compile(checkpointer=MemorySaver())


def _system_prompts():
    return [m.content for call in SEEN for m in call if m.type == "system"]


async def _turn(app, thread_id, parent, message, documents=None, model="gpt-5.4"):
    end = None
    async for event in stream_turn(app, thread_id, parent, message=message, model=model,
                                   documents=documents, context=DEFAULT_CONTEXT):
        if event["type"] == "end":
            end = event
    return end["checkpoint_id"]


# ─── The store ───────────────────────────────────────────────────


def test_saving_is_idempotent_and_a_new_version_replaces_the_old(isolated_db):
    store = db.ThreadDocumentStore()
    store.save("t1", {"a.md": "one", "b.md": "two"})
    store.save("t1", {"a.md": "one"})
    store.save("t1", {"b.md": "two, revised"})
    store.save("t2", {"a.md": "other thread"})
    assert store.load("t1") == {"a.md": "one", "b.md": "two, revised"}
    assert list(store.load("t1")) == ["a.md", "b.md"]
    conn = sqlite3.connect(db.DB_PATH)
    assert conn.execute("SELECT COUNT(*) FROM thread_documents").fetchone()[0] == 3
    conn.close()


def test_init_db_adds_the_table_to_an_existing_database(tmp_path, monkeypatch):
    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE thread_metadata (thread_id TEXT PRIMARY KEY, title TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", str(path))
    db.init_db()
    db.ThreadDocumentStore().save("t", DOC)
    assert db.ThreadDocumentStore().load("t") == DOC


def test_deleting_a_thread_deletes_its_documents_and_its_sub_threads(isolated_db):
    conn = sqlite3.connect(db.DB_PATH)  # LangGraph's tables, which its saver creates
    conn.execute("CREATE TABLE checkpoints (thread_id TEXT, checkpoint_id TEXT)")
    conn.execute("CREATE TABLE writes (thread_id TEXT, checkpoint_id TEXT)")
    conn.commit()
    conn.close()
    store = db.ThreadDocumentStore()
    for tid in ("t1", "t1::gpt-5.4", "t1_other"):
        store.save(tid, DOC)
    db.delete_thread_data("t1")
    assert store.load("t1") == {} and store.load("t1::gpt-5.4") == {}
    assert store.load("t1_other") == DOC


@pytest.mark.asyncio
async def test_attaching_needs_a_store():
    with pytest.raises(ValueError):
        await attach_documents({"configurable": {"thread_id": "t"}}, DOC)
    await attach_documents({"configurable": {"thread_id": "t"}}, {})  # nothing to save: fine


def test_run_documents_combine_legacy_state_and_the_store():
    class _Store:
        def load(self, thread_id):
            return {"new.md": f"stored for {thread_id}"}

    config = {"configurable": {"thread_id": "t9", DOCUMENT_STORE_CONFIG_KEY: _Store()}}
    state = {"documents": {"old.md": "from an old checkpoint"}}
    assert documents_for_run(state, config) == {"old.md": "from an old checkpoint", "new.md": "stored for t9"}
    # A run that names no store (experiments) sees only its state.
    assert documents_for_run(state, {"configurable": {"thread_id": "t9"}}) == state["documents"]
    assert DOCUMENT_STORE_CONFIG_KEY in with_default_documents({})["configurable"]


# ─── Through the graph ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_documents_reach_the_model_but_no_checkpoint(graph_app):
    parent = await resolve_fork_point(graph_app, "t-doc")
    # Two models in one turn: the client sends the documents on both frames.
    first = await _turn(graph_app, "t-doc", parent, "What was measured?", DOC, "gpt-5.4")
    await _turn(graph_app, "t-doc", parent, "What was measured?", DOC, "claude-sonnet-5")
    prompts = _system_prompts()
    assert len(prompts) == 2 and all("412 kelvin" in s for s in prompts)
    assert db.ThreadDocumentStore().load("t-doc") == DOC

    # A follow-up without documents still sees them: they belong to the thread.
    SEEN.clear()
    await _turn(graph_app, "t-doc", first, "And in Celsius?")
    assert any("412 kelvin" in s for s in _system_prompts())

    async for snapshot in graph_app.aget_state_history(thread_config("t-doc")):
        assert not snapshot.values.get("documents"), snapshot.config


@pytest.mark.asyncio
async def test_a_legacy_checkpoint_still_shows_its_documents(graph_app):
    # A thread written before the store: the documents sit in the state.
    legacy = await graph_app.aupdate_state(
        thread_config("t-old"), {"documents": {"old.md": "Legacy text about argon."}}, as_node="synthesis"
    )
    config = with_default_documents(thread_config("t-old", legacy["configurable"]["checkpoint_id"]))
    run_id = tag_run(config)
    # A run that does not reset documents (as arena runs don't) inherits them.
    await graph_app.ainvoke({"active_peer": "gpt-5.4", "messages": [("user", "Which gas?")], "toggles": {}}, config)
    assert any("Legacy text about argon." in s for s in _system_prompts())
    assert await final_state_of_run(graph_app, "t-old", run_id) is not None


@pytest.mark.asyncio
async def test_debate_participants_get_the_documents_on_their_sub_threads(graph_app):
    models = ["gpt-5.4", "claude-sonnet-5"]
    thread_ids = {m: f"t-deb::{m}" for m in models}
    events = [e async for e in debate_svc._stream_round(
        graph_app=graph_app, round_num=0, session_id="s1", participants=models, thread_ids=thread_ids,
        model_prompts={m: "Debate the measurement." for m in models}, toggles={}, documents=DOC,
        parent_checkpoint_id=None, curr_round_responses={},
    )]
    assert not [e for e in events if e["type"] == "error"], events
    for tid in thread_ids.values():
        assert db.ThreadDocumentStore().load(tid) == DOC
        async for snapshot in graph_app.aget_state_history(thread_config(tid)):
            assert not snapshot.values.get("documents")
    assert sum("412 kelvin" in s for s in _system_prompts()) == len(models)
