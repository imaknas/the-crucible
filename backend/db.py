import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Default to local file, but allow override for Docker/Prod
DB_PATH = os.getenv("DATABASE_PATH", os.path.join(BASE_DIR, "checkpoints.sqlite"))


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
    conn.commit()
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
            SELECT DISTINCT c.thread_id, m.title 
            FROM checkpoints c 
            LEFT JOIN thread_metadata m ON c.thread_id = m.thread_id
            ORDER BY c.thread_id DESC
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
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
        conn.execute("DELETE FROM node_positions WHERE thread_id = ?", (thread_id,))
        conn.execute("DELETE FROM thread_metadata WHERE thread_id = ?", (thread_id,))
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
