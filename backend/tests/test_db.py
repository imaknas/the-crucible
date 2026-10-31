"""Tests for db.py — SQLite CRUD operations.

Uses an isolated in-memory database for each test.
"""

import sqlite3
import pytest
from unittest.mock import MagicMock
from app.core.storage import current_storage
from tests.storage_helpers import point


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """A temp database per test, with LangGraph's tables stubbed."""
    test_db = str(tmp_path / "test.sqlite")

    # Create required tables
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS node_positions (
            thread_id TEXT, node_id TEXT, x REAL, y REAL,
            PRIMARY KEY (thread_id, node_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS thread_metadata (
            thread_id TEXT PRIMARY KEY, title TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS checkpoints (
            thread_id TEXT, checkpoint_id TEXT,
            PRIMARY KEY (thread_id, checkpoint_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS writes (
            thread_id TEXT, checkpoint_id TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS debate_sessions (
            session_id TEXT PRIMARY KEY,
            parent_thread_id TEXT NOT NULL,
            participants TEXT NOT NULL,
            thread_ids TEXT NOT NULL,
            current_round INTEGER DEFAULT 0,
            status TEXT DEFAULT 'running',
            termination_policy TEXT NOT NULL,
            auto_synthesize INTEGER DEFAULT 0,
            synthesizer_model TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

    point(monkeypatch, db_path=test_db)
    from app.core import database as db

    db.init_db()  # the app's own tables and migrations on top
    yield test_db


class TestThreadMetadata:
    def test_rename_and_list(self):
        from app.core import database as db

        db.rename_thread("t1", "My Thread")
        # We can't test list_threads without checkpoints table data
        # But we can check rename worked
        conn = sqlite3.connect(current_storage().db_path)
        row = conn.execute(
            "SELECT title FROM thread_metadata WHERE thread_id = ?", ("t1",)
        ).fetchone()
        conn.close()
        assert row[0] == "My Thread"

    def test_rename_overwrites(self):
        from app.core import database as db

        db.rename_thread("t1", "First")
        db.rename_thread("t1", "Second")
        conn = sqlite3.connect(current_storage().db_path)
        row = conn.execute(
            "SELECT title FROM thread_metadata WHERE thread_id = ?", ("t1",)
        ).fetchone()
        conn.close()
        assert row[0] == "Second"


class TestNodePositions:
    def test_save_and_load(self):
        from app.core import database as db

        update = MagicMock()
        update.node_id = "node1"
        update.x = 100.0
        update.y = 200.0
        db.save_node_positions("t1", [update])

        positions = db.load_node_positions("t1")
        assert "node1" in positions
        assert positions["node1"]["x"] == 100.0
        assert positions["node1"]["y"] == 200.0

    def test_load_empty(self):
        from app.core import database as db

        positions = db.load_node_positions("nonexistent")
        assert positions == {}

    def test_overwrite_position(self):
        from app.core import database as db

        u1 = MagicMock()
        u1.node_id = "n1"
        u1.x = 10
        u1.y = 20
        u2 = MagicMock()
        u2.node_id = "n1"
        u2.x = 30
        u2.y = 40
        db.save_node_positions("t1", [u1])
        db.save_node_positions("t1", [u2])
        positions = db.load_node_positions("t1")
        assert positions["n1"]["x"] == 30
        assert positions["n1"]["y"] == 40


class TestDeleteThread:
    def test_delete_cleans_all_tables(self):
        from app.core import database as db

        conn = sqlite3.connect(current_storage().db_path)
        conn.execute("INSERT INTO checkpoints VALUES ('t1', 'cp1')")
        conn.execute("INSERT INTO writes VALUES ('t1', 'cp1')")
        conn.execute("INSERT INTO thread_metadata VALUES ('t1', 'title')")
        conn.execute("INSERT INTO node_positions VALUES ('t1', 'n1', 0, 0)")
        conn.commit()
        conn.close()

        db.delete_thread_data("t1")

        conn = sqlite3.connect(current_storage().db_path)
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM checkpoints WHERE thread_id='t1'"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM writes WHERE thread_id='t1'").fetchone()[
                0
            ]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM thread_metadata WHERE thread_id='t1'"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM node_positions WHERE thread_id='t1'"
            ).fetchone()[0]
            == 0
        )
        conn.close()


class TestDeleteCheckpoint:
    def test_delete_specific_checkpoints(self):
        from app.core import database as db

        conn = sqlite3.connect(current_storage().db_path)
        conn.execute("INSERT INTO checkpoints VALUES ('t1', 'cp1')")
        conn.execute("INSERT INTO checkpoints VALUES ('t1', 'cp2')")
        conn.execute("INSERT INTO checkpoints VALUES ('t1', 'cp3')")
        conn.execute("INSERT INTO writes VALUES ('t1', 'cp1')")
        conn.execute("INSERT INTO writes VALUES ('t1', 'cp2')")
        conn.commit()
        conn.close()

        db.delete_checkpoint_data("t1", {"cp1", "cp2"})

        conn = sqlite3.connect(current_storage().db_path)
        remaining = conn.execute(
            "SELECT checkpoint_id FROM checkpoints WHERE thread_id='t1'"
        ).fetchall()
        conn.close()
        assert len(remaining) == 1
        assert remaining[0][0] == "cp3"


class TestGetAllCheckpointIds:
    def test_returns_set(self):
        from app.core import database as db

        conn = sqlite3.connect(current_storage().db_path)
        conn.execute("INSERT INTO checkpoints VALUES ('t1', 'cp1')")
        conn.execute("INSERT INTO checkpoints VALUES ('t1', 'cp2')")
        conn.commit()
        conn.close()

        result = db.get_all_checkpoint_ids("t1")
        assert result == {"cp1", "cp2"}

    def test_empty_thread(self):
        from app.core import database as db

        result = db.get_all_checkpoint_ids("nonexistent")
        assert result == set()


class TestDebateCascadeDelete:
    """Deleting a thread or session must not orphan its debate sub-threads."""

    @staticmethod
    def _seed(db):
        """One parent thread with a 2-model debate and a synthesis thread."""
        session = {
            "session_id": "d1",
            "parent_thread_id": "t1",
            "participants": ["m1", "m2"],
            "thread_ids": {"m1": "t1::m1", "m2": "t1::m2"},
            "current_round": 0,
            "status": "running",
            "termination_policy": {"max_rounds": 3},
            "auto_synthesize": False,
            "synthesizer_model": None,
        }
        db.create_debate_session(session)

        conn = sqlite3.connect(current_storage().db_path)
        for tid in ("t1", "t1::m1", "t1::m2", "t1::synthesis", "t2"):
            conn.execute("INSERT INTO checkpoints VALUES (?, 'cp1')", (tid,))
            conn.execute("INSERT INTO writes VALUES (?, 'cp1')", (tid,))
            conn.execute("INSERT INTO node_positions VALUES (?, 'n1', 0, 0)", (tid,))
            conn.execute("INSERT OR IGNORE INTO thread_metadata VALUES (?, 't')", (tid,))
        conn.commit()
        conn.close()

    @staticmethod
    def _threads_left(db):
        conn = sqlite3.connect(current_storage().db_path)
        rows = {r[0] for r in conn.execute("SELECT DISTINCT thread_id FROM checkpoints")}
        conn.close()
        return rows

    def test_delete_thread_removes_debate_sub_threads(self):
        from app.core import database as db

        self._seed(db)
        db.delete_thread_data("t1")

        # Unrelated threads survive; every "t1"-derived thread is gone.
        assert self._threads_left(db) == {"t2"}

        conn = sqlite3.connect(current_storage().db_path)
        for table in ("writes", "node_positions", "thread_metadata"):
            remaining = {
                r[0]
                for r in conn.execute(f"SELECT DISTINCT thread_id FROM {table}")
            }
            assert remaining == {"t2"}, table
        assert conn.execute("SELECT COUNT(*) FROM debate_sessions").fetchone()[0] == 0
        conn.close()

    def test_delete_thread_does_not_match_similar_prefixes(self):
        """Thread ids contain "_", a LIKE wildcard — prefix matching must be exact."""
        from app.core import database as db

        conn = sqlite3.connect(current_storage().db_path)
        conn.execute("INSERT INTO checkpoints VALUES ('thread_a', 'cp1')")
        conn.execute("INSERT INTO checkpoints VALUES ('threadXa::m1', 'cp1')")
        conn.execute("INSERT INTO checkpoints VALUES ('thread_a::m1', 'cp1')")
        conn.commit()
        conn.close()

        db.delete_thread_data("thread_a")
        assert self._threads_left(db) == {"threadXa::m1"}

    def test_delete_session_removes_its_checkpoints(self):
        from app.core import database as db

        self._seed(db)
        db.delete_debate_session("d1")

        # The parent thread is untouched; only the debate's own threads go.
        assert self._threads_left(db) == {"t1", "t2"}
        assert db.get_debate_session("d1") is None

    @staticmethod
    def _scoped(db, session_id):
        """A session as created now: every thread id scoped to the session."""
        thread_ids = {m: f"t1::{session_id}::{m}" for m in ("m1", "m2")}
        thread_ids["synthesis"] = f"t1::{session_id}::synthesis"
        db.create_debate_session({
            "session_id": session_id,
            "parent_thread_id": "t1",
            "participants": ["m1", "m2"],
            "thread_ids": thread_ids,
            "termination_policy": {"max_rounds": 3},
        })
        conn = sqlite3.connect(current_storage().db_path)
        for tid in thread_ids.values():
            conn.execute("INSERT INTO checkpoints VALUES (?, 'cp1')", (tid,))
        conn.commit()
        conn.close()
        return set(thread_ids.values())

    def test_deleting_one_session_leaves_another_on_the_same_thread(self):
        from app.core import database as db

        a = self._scoped(db, "dA")
        b = self._scoped(db, "dB")
        db.delete_debate_session("dA")

        assert self._threads_left(db) == b
        assert not a & self._threads_left(db)
        assert db.get_debate_session("dB") is not None

    def test_legacy_sessions_sharing_threads_keep_them_until_the_last_goes(self):
        """Sessions created before ids were scoped share "{parent}::{model}" and
        "{parent}::synthesis"; deleting one must not erase the other's debate."""
        from app.core import database as db

        self._seed(db)
        db.create_debate_session({
            "session_id": "d2",
            "parent_thread_id": "t1",
            "participants": ["m1", "m2"],
            "thread_ids": {"m1": "t1::m1", "m2": "t1::m2"},
            "termination_policy": {"max_rounds": 3},
        })

        db.delete_debate_session("d1")
        assert self._threads_left(db) == {"t1", "t1::m1", "t1::m2", "t1::synthesis", "t2"}

        db.delete_debate_session("d2")
        assert self._threads_left(db) == {"t1", "t2"}

    def test_delete_thread_removes_scoped_sub_threads(self):
        from app.core import database as db

        self._scoped(db, "dA")
        db.delete_thread_data("t1")
        assert self._threads_left(db) == set()

    def test_synthesis_thread_of_a_legacy_session_is_derived(self):
        from app.core import database as db

        legacy = {"parent_thread_id": "p", "thread_ids": {"m": "p::m"}}
        scoped = {"parent_thread_id": "p", "thread_ids": {"m": "p::s::m", "synthesis": "p::s::synthesis"}}
        assert db.synthesis_thread_id(legacy) == "p::synthesis"
        assert db.synthesis_thread_id(scoped) == "p::s::synthesis"
        assert db.session_thread_ids(legacy) == {"p::m", "p::synthesis"}


class TestDebateParentTitle:
    """A debate's parent thread is listed but stays untitled until the debate names it."""

    def _session(self, parent):
        return {
            "session_id": "s1",
            "parent_thread_id": parent,
            "participants": ["a", "b"],
            "thread_ids": {"a": f"{parent}::a", "b": f"{parent}::b"},
            "termination_policy": {"max_rounds": 1},
        }

    def test_creating_a_session_lists_the_parent_without_a_placeholder_title(self, tmp_path, monkeypatch):
        from app.core import database as db

        point(monkeypatch, db_path=tmp_path / "fresh.sqlite")
        db.init_db()
        # LangGraph owns this table; list_threads reads it.
        with sqlite3.connect(current_storage().db_path) as conn:
            conn.execute("CREATE TABLE checkpoints (thread_id TEXT, checkpoint_id TEXT)")
        db.create_debate_session(self._session("thread_new"))
        assert db.get_thread_title("thread_new") is None
        # Untitled in the database; services/threads names it for display.
        assert {"id": "thread_new", "title": None} in [{"id": t["id"], "title": t["title"]} for t in db.list_threads()]

    def test_init_clears_placeholder_titles(self, tmp_path, monkeypatch):
        from app.core import database as db

        point(monkeypatch, db_path=tmp_path / "old.sqlite")
        db.init_db()
        db.rename_thread("thread_old", "thread_old")
        db.rename_thread("thread_named", "A real title")
        db.init_db()
        assert db.get_thread_title("thread_old") is None
        assert db.get_thread_title("thread_named") == "A real title"
