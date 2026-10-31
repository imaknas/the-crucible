"""App-table writes never block the event loop.

LangGraph's AsyncSqliteSaver writes checkpoints to the same SQLite file on
its own thread, but resumes on the event loop between its INSERT and its
commit. A blocking write made on the loop in that gap waits for a lock whose
holder needs the loop to release it: SQLite's busy timeout expires and the
write fails with "database is locked" (seen as "[Auto-title] failed" while
several models were writing checkpoints).
"""

import asyncio
import os
import sqlite3
import time
from unittest.mock import patch

import aiosqlite
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.api.chat import ChatConnection
from app.core import database as db
from app.llm import CallableModelFactory, use_model_factory
from app.services import debate as debate_svc
from app.services.arena import open_graph
from app.services.chat import auto_title

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
WRITES = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}


def _model(model_id, _toggles):
    return FakeListChatModel(responses=[f"reply from {model_id}"])


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "t.sqlite")
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")  # as AsyncSqliteSaver.setup() leaves it
    return path


@pytest.fixture
def writes_on_loop(db_path, monkeypatch):
    """Every app-table write statement prepared on a thread that is running
    an event loop."""
    seen: list[str] = []
    connect = db.get_db_connection

    def guarded():
        conn = connect()

        def authorize(action, arg1, *_):
            if action in WRITES:
                try:
                    asyncio.get_running_loop()
                    seen.append(f"{action}:{arg1}")
                except RuntimeError:
                    pass
            return sqlite3.SQLITE_OK

        conn.set_authorizer(authorize)
        return conn

    monkeypatch.setattr(db, "get_db_connection", guarded)
    # The schema was created by db_path; startup and open_graph() create it
    # before any run can be writing checkpoints.
    monkeypatch.setattr(db, "init_db", lambda: None)
    return seen


class _Socket:
    def __init__(self):
        self.frames: list[dict] = []

    async def send_json(self, frame):
        self.frames.append(frame)


@pytest.mark.asyncio
async def test_auto_title_survives_a_checkpoint_write_awaiting_commit(db_path):
    prompt = "Why is the sky blue at noon?"
    socket = _Socket()
    connection = ChatConnection(socket, graph_app=None, thread_id="t-title")
    held = asyncio.Event()

    async def checkpoint_write(conn):
        # What AsyncSqliteSaver.aput does: INSERT on aiosqlite's thread, then
        # come back to the loop before committing.
        async with conn.execute("INSERT INTO node_positions VALUES ('x', 'n', 0, 0)"):
            held.set()
            await asyncio.sleep(0)
            await conn.commit()

    async def title():
        await held.wait()
        started = time.monotonic()
        await connection._name_thread(prompt)
        return time.monotonic() - started

    async with aiosqlite.connect(db_path) as conn:
        _, elapsed = await asyncio.gather(checkpoint_write(conn), title())

    assert db.get_thread_title("t-title") == auto_title(prompt)
    assert {"type": "title_update", "thread_id": "t-title", "title": auto_title(prompt)} in socket.frames
    # A write that blocked the loop waited out the whole busy timeout (5 s).
    assert elapsed < 2


def test_first_chat_turn_titles_the_thread_off_the_loop(writes_on_loop):
    from app.main import server

    with (
        use_model_factory(CallableModelFactory(_model)),
        patch.dict(os.environ, KEYS),
        TestClient(server) as client,
        client.websocket_connect("/ws/t-ws") as ws,
    ):
        for model in ("gpt-5.4", "claude-sonnet-5"):
            ws.send_json({"message": "Name this thread", "model": model, "parent_checkpoint_id": None, "toggles": {}})
        while (msg := ws.receive_json())["type"] != "title_update":
            assert msg["type"] != "error", msg

        assert client.patch("/threads/t-ws/rename", json={"title": "Renamed"}).json() == {"status": "ok"}
        assert client.post("/history/t-ws/positions", json=[{"node_id": "n", "x": 1, "y": 2}]).json() == {"status": "ok"}

    assert db.get_thread_title("t-ws") == "Renamed"
    assert writes_on_loop == []


@pytest.mark.asyncio
async def test_debate_writes_its_session_off_the_loop(writes_on_loop):
    policy = {"max_rounds": 2, "convergence_threshold": None, "llm_judge": None, "mode": "all"}
    with use_model_factory(CallableModelFactory(_model)), patch.dict(os.environ, KEYS):
        session = debate_svc.create_session("t-debate", ["gpt-5.4", "claude-sonnet-5"], policy)
        writes_on_loop.clear()  # created before any run starts, by the caller's thread
        async with open_graph() as graph_app:
            events = [e async for e in debate_svc.run_debate(graph_app, session["session_id"], "Q?", {}, {})]

    assert events[-1]["status"] == "completed", events
    assert db.get_thread_title("t-debate") == "Debate: Q?"
    assert db.get_debate_session(session["session_id"])["status"] == "completed"
    assert writes_on_loop == []
