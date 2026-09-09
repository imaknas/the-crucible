import sqlite3
import json
import os
from typing import Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Default to backend/root (two levels up from app/core), but allow override for Docker/Prod
DB_PATH = os.getenv(
    "DATABASE_PATH",
    os.path.abspath(os.path.join(BASE_DIR, "..", "..", "checkpoints.sqlite")),
)


def get_db_connection():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS node_positions (
            thread_id TEXT,
            node_id TEXT,
            x REAL,
            y REAL,
            PRIMARY KEY (thread_id, node_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS thread_metadata (
            thread_id TEXT PRIMARY KEY,
            title TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS node_metadata (
            thread_id TEXT,
            node_id TEXT,
            confidence_score REAL,
            conflict_detected BOOLEAN,
            utility_rating REAL,
            PRIMARY KEY (thread_id, node_id)
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
            round_scores TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migration: round_scores was added after the first debate sessions shipped.
    existing = {r[1] for r in conn.execute("PRAGMA table_info(debate_sessions)")}
    if "round_scores" not in existing:
        conn.execute(
            "ALTER TABLE debate_sessions ADD COLUMN round_scores TEXT DEFAULT '{}'"
        )

    # Backfill: ensure all debate parent threads appear in thread_metadata
    conn.execute("""
        INSERT OR IGNORE INTO thread_metadata (thread_id, title)
        SELECT DISTINCT parent_thread_id, parent_thread_id
        FROM debate_sessions
    """)
    conn.commit()
    conn.close()


def _decode_round_scores(raw: Any) -> dict[str, float]:
    """round_scores is stored as a JSON object keyed by round number."""
    if not raw:
        return {}
    try:
        return {str(k): float(v) for k, v in json.loads(raw).items()}
    except (ValueError, TypeError, AttributeError):
        return {}


def record_round_score(session_id: str, round_num: int, score: float) -> None:
    """Persist one round's convergence score so the tree can show it after a reload."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT round_scores FROM debate_sessions WHERE session_id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
        if not row:
            return
        scores = _decode_round_scores(row[0])
        scores[str(round_num)] = float(score)
        conn.execute(
            "UPDATE debate_sessions SET round_scores = ? WHERE session_id = ?",
            (json.dumps(scores), session_id),
        )
        conn.commit()
    finally:
        conn.close()


def create_debate_session(session: dict[str, Any]) -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO debate_sessions
                (session_id, parent_thread_id, participants, thread_ids,
                 current_round, status, termination_policy, auto_synthesize, synthesizer_model)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session["session_id"],
                session["parent_thread_id"],
                json.dumps(session["participants"]),
                json.dumps(session["thread_ids"]),
                session.get("current_round", 0),
                session.get("status", "running"),
                json.dumps(session["termination_policy"]),
                int(session.get("auto_synthesize", False)),
                session.get("synthesizer_model"),
            ),
        )
        # Ensure parent thread appears in thread list even if it has no chat checkpoints
        conn.execute(
            "INSERT OR IGNORE INTO thread_metadata (thread_id, title) VALUES (?, ?)",
            (session["parent_thread_id"], session["parent_thread_id"]),
        )
        conn.commit()
    finally:
        conn.close()


def get_debate_session(session_id: str) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM debate_sessions WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cursor.description]
        data = dict(zip(cols, row))
        data["participants"] = json.loads(data["participants"])
        data["thread_ids"] = json.loads(data["thread_ids"])
        data["termination_policy"] = json.loads(data["termination_policy"])
        data["auto_synthesize"] = bool(data["auto_synthesize"])
        data["round_scores"] = _decode_round_scores(data.get("round_scores"))
        return data
    finally:
        conn.close()


def update_debate_session(session_id: str, **kwargs: Any) -> None:
    """Update any subset of debate session fields."""
    allowed = {"current_round", "status", "auto_synthesize", "synthesizer_model", "termination_policy"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    conn = get_db_connection()
    try:
        for key, value in updates.items():
            if key in ("termination_policy",):
                value = json.dumps(value)
            conn.execute(
                f"UPDATE debate_sessions SET {key} = ? WHERE session_id = ?",
                (value, session_id),
            )
        conn.commit()
    finally:
        conn.close()


def list_debate_sessions(parent_thread_id: str | None = None) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if parent_thread_id:
            cursor.execute(
                "SELECT * FROM debate_sessions WHERE parent_thread_id = ? ORDER BY created_at DESC",
                (parent_thread_id,),
            )
        else:
            cursor.execute("SELECT * FROM debate_sessions ORDER BY created_at DESC")
        cols = [d[0] for d in cursor.description]
        rows = []
        for row in cursor.fetchall():
            data = dict(zip(cols, row))
            data["participants"] = json.loads(data["participants"])
            data["thread_ids"] = json.loads(data["thread_ids"])
            data["termination_policy"] = json.loads(data["termination_policy"])
            data["auto_synthesize"] = bool(data["auto_synthesize"])
            data["round_scores"] = _decode_round_scores(data.get("round_scores"))
            rows.append(data)
        return rows
    finally:
        conn.close()


SYNTHESIS_THREAD_SUFFIX = "::synthesis"


def _purge_thread_rows(conn, thread_id: str) -> None:
    """Delete every row keyed to one thread_id. Caller commits."""
    conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
    conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
    conn.execute("DELETE FROM node_positions WHERE thread_id = ?", (thread_id,))
    conn.execute("DELETE FROM thread_metadata WHERE thread_id = ?", (thread_id,))


def delete_debate_session(session_id: str) -> None:
    """
    Delete a debate session and every checkpoint it created.

    Each participant debates in its own `{parent}::{model}` sub-thread and
    synthesis writes to `{parent}::synthesis`. Dropping only the session row
    left all of that behind, so the checkpoint DB grew without bound.
    """
    session = get_debate_session(session_id)
    conn = get_db_connection()
    try:
        if session:
            for sub_thread_id in session.get("thread_ids", {}).values():
                _purge_thread_rows(conn, sub_thread_id)
            _purge_thread_rows(
                conn, f"{session['parent_thread_id']}{SYNTHESIS_THREAD_SUFFIX}"
            )
        conn.execute("DELETE FROM debate_sessions WHERE session_id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()


def save_node_metadata(
    thread_id, node_id, confidence=None, conflict=None, utility=None
):
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO node_metadata (thread_id, node_id, confidence_score, conflict_detected, utility_rating)
            VALUES (?, ?, ?, ?, ?)
        """,
            (thread_id, node_id, confidence, conflict, utility),
        )
        conn.commit()
    finally:
        conn.close()


def load_node_metadata(thread_id, node_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT confidence_score, conflict_detected, utility_rating FROM node_metadata WHERE thread_id = ? AND node_id = ?",
            (thread_id, node_id),
        )
        row = cursor.fetchone()
        if row:
            return {
                "confidence_score": row[0],
                "conflict_detected": bool(row[1]),
                "utility_rating": row[2],
            }
        return None
    finally:
        conn.close()


def save_node_positions(thread_id, updates):
    conn = get_db_connection()
    try:
        for update in updates:
            conn.execute(
                """
                INSERT OR REPLACE INTO node_positions (thread_id, node_id, x, y)
                VALUES (?, ?, ?, ?)
            """,
                (thread_id, update.node_id, update.x, update.y),
            )
        conn.commit()
    finally:
        conn.close()


def load_node_positions(thread_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT node_id, x, y FROM node_positions WHERE thread_id = ?", (thread_id,)
        )
        return {row[0]: {"x": row[1], "y": row[2]} for row in cursor.fetchall()}
    finally:
        conn.close()


def list_threads():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT thread_id, title FROM (
                SELECT DISTINCT c.thread_id, m.title
                FROM checkpoints c
                LEFT JOIN thread_metadata m ON c.thread_id = m.thread_id
                WHERE c.thread_id NOT LIKE '%::%'
                UNION
                SELECT tm.thread_id, tm.title
                FROM thread_metadata tm
                INNER JOIN debate_sessions ds ON tm.thread_id = ds.parent_thread_id
                WHERE tm.thread_id NOT LIKE '%::%'
            )
            ORDER BY thread_id DESC
        """)
        return [{"id": row[0], "title": row[1] or row[0]} for row in cursor.fetchall()]
    finally:
        conn.close()


def rename_thread(thread_id, title):
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO thread_metadata (thread_id, title) VALUES (?, ?)",
            (thread_id, title),
        )
        conn.commit()
    finally:
        conn.close()


def delete_thread_data(thread_id):
    """
    Delete a thread and everything derived from it.

    That includes every debate sub-thread (`{thread_id}::{model}`) and the
    synthesis thread, plus the `debate_sessions` rows themselves — deleting only
    the parent used to orphan all of them.
    """
    conn = get_db_connection()
    try:
        _purge_thread_rows(conn, thread_id)
        # Sub-threads are namespaced "{thread_id}::{model}". Compared by prefix
        # rather than LIKE because thread ids contain "_", a LIKE wildcard.
        prefix = f"{thread_id}::"
        for table in ("checkpoints", "writes", "node_positions", "thread_metadata"):
            conn.execute(
                f"DELETE FROM {table} WHERE substr(thread_id, 1, ?) = ?",
                (len(prefix), prefix),
            )
        conn.execute(
            "DELETE FROM debate_sessions WHERE parent_thread_id = ?", (thread_id,)
        )
        conn.commit()
    finally:
        conn.close()


def delete_checkpoint_data(thread_id, checkpoint_ids):
    conn = get_db_connection()
    try:
        for cid in checkpoint_ids:
            conn.execute(
                "DELETE FROM checkpoints WHERE thread_id = ? AND checkpoint_id = ?",
                (thread_id, cid),
            )
            conn.execute(
                "DELETE FROM writes WHERE thread_id = ? AND checkpoint_id = ?",
                (thread_id, cid),
            )
            conn.execute(
                "DELETE FROM node_positions WHERE thread_id = ? AND node_id = ?",
                (thread_id, cid),
            )
        conn.commit()
    finally:
        conn.close()


def get_all_checkpoint_ids(thread_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT checkpoint_id FROM checkpoints WHERE thread_id = ?", (thread_id,)
        )
        return {row[0] for row in cursor.fetchall()}
    finally:
        conn.close()


def get_thread_checkpoint_graph(thread_id: str):
    """Returns all checkpoint_id and parent_checkpoint_id pairs for a thread."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT checkpoint_id, parent_checkpoint_id FROM checkpoints WHERE thread_id = ?",
            (thread_id,),
        )
        return cursor.fetchall()
    finally:
        conn.close()
