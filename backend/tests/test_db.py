"""Tests for db.py — SQLite CRUD operations.

Uses an isolated in-memory database for each test.
"""

import sqlite3
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    """Override db.DB_PATH to use a temp file for each test."""
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

    with patch("app.core.database.DB_PATH", test_db):
        yield test_db


class TestThreadMetadata:
    def test_rename_and_list(self):
        from app.core import database as db

        db.rename_thread("t1", "My Thread")
        # We can't test list_threads without checkpoints table data
        # But we can check rename worked
        conn = sqlite3.connect(db.DB_PATH)
        row = conn.execute(
            "SELECT title FROM thread_metadata WHERE thread_id = ?", ("t1",)
        ).fetchone()
        conn.close()
        assert row[0] == "My Thread"

    def test_rename_overwrites(self):
        from app.core import database as db

        db.rename_thread("t1", "First")
        db.rename_thread("t1", "Second")
        conn = sqlite3.connect(db.DB_PATH)
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

        conn = sqlite3.connect(db.DB_PATH)
        conn.execute("INSERT INTO checkpoints VALUES ('t1', 'cp1')")
        conn.execute("INSERT INTO writes VALUES ('t1', 'cp1')")
        conn.execute("INSERT INTO thread_metadata VALUES ('t1', 'title')")
        conn.execute("INSERT INTO node_positions VALUES ('t1', 'n1', 0, 0)")
        conn.commit()
        conn.close()

        db.delete_thread_data("t1")

        conn = sqlite3.connect(db.DB_PATH)
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

        conn = sqlite3.connect(db.DB_PATH)
        conn.execute("INSERT INTO checkpoints VALUES ('t1', 'cp1')")
        conn.execute("INSERT INTO checkpoints VALUES ('t1', 'cp2')")
        conn.execute("INSERT INTO checkpoints VALUES ('t1', 'cp3')")
        conn.execute("INSERT INTO writes VALUES ('t1', 'cp1')")
        conn.execute("INSERT INTO writes VALUES ('t1', 'cp2')")
        conn.commit()
        conn.close()

        db.delete_checkpoint_data("t1", {"cp1", "cp2"})

        conn = sqlite3.connect(db.DB_PATH)
        remaining = conn.execute(
            "SELECT checkpoint_id FROM checkpoints WHERE thread_id='t1'"
        ).fetchall()
        conn.close()
        assert len(remaining) == 1
        assert remaining[0][0] == "cp3"


class TestGetAllCheckpointIds:
    def test_returns_set(self):
        from app.core import database as db

        conn = sqlite3.connect(db.DB_PATH)
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

        conn = sqlite3.connect(db.DB_PATH)
        for tid in ("t1", "t1::m1", "t1::m2", "t1::synthesis", "t2"):
            conn.execute("INSERT INTO checkpoints VALUES (?, 'cp1')", (tid,))
            conn.execute("INSERT INTO writes VALUES (?, 'cp1')", (tid,))
            conn.execute("INSERT INTO node_positions VALUES (?, 'n1', 0, 0)", (tid,))
            conn.execute("INSERT OR IGNORE INTO thread_metadata VALUES (?, 't')", (tid,))
        conn.commit()
        conn.close()

    @staticmethod
    def _threads_left(db):
        conn = sqlite3.connect(db.DB_PATH)
        rows = {r[0] for r in conn.execute("SELECT DISTINCT thread_id FROM checkpoints")}
        conn.close()
        return rows

    def test_delete_thread_removes_debate_sub_threads(self):
        from app.core import database as db

        self._seed(db)
        db.delete_thread_data("t1")

        # Unrelated threads survive; every "t1"-derived thread is gone.
        assert self._threads_left(db) == {"t2"}

        conn = sqlite3.connect(db.DB_PATH)
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

        conn = sqlite3.connect(db.DB_PATH)
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
