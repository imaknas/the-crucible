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
    conn.commit()
    conn.close()

    with patch("db.DB_PATH", test_db):
        yield test_db


class TestThreadMetadata:
    def test_rename_and_list(self):
        import db

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
        import db

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
        import db

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
        import db

        positions = db.load_node_positions("nonexistent")
        assert positions == {}

    def test_overwrite_position(self):
        import db

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
        import db

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
        import db

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
        import db

        conn = sqlite3.connect(db.DB_PATH)
        conn.execute("INSERT INTO checkpoints VALUES ('t1', 'cp1')")
        conn.execute("INSERT INTO checkpoints VALUES ('t1', 'cp2')")
        conn.commit()
        conn.close()

        result = db.get_all_checkpoint_ids("t1")
        assert result == {"cp1", "cp2"}

    def test_empty_thread(self):
        import db

        result = db.get_all_checkpoint_ids("nonexistent")
        assert result == set()
