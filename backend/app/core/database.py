import sqlite3
import json
from typing import Any, Mapping, Optional, Sequence

from app.core.storage import current_storage

def get_db_connection():
    """A connection to the run's database (core/storage.py)."""
    return sqlite3.connect(current_storage().db_path)


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
    # Older databases also have a node_metadata table (confidence/conflict
    # per node). Nothing ever filled it and nothing reads it; it is left in
    # place there and no longer created.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS debate_sessions (
            session_id TEXT PRIMARY KEY,
            parent_thread_id TEXT NOT NULL,
            participants TEXT NOT NULL,
            thread_ids TEXT NOT NULL,
            current_round INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            termination_policy TEXT NOT NULL,
            auto_synthesize INTEGER DEFAULT 0,
            synthesizer_model TEXT,
            round_scores TEXT DEFAULT '{}',
            peer_labels TEXT,
            parent_checkpoint_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migration: round_scores was added after the first debate sessions shipped.
    existing = {r[1] for r in conn.execute("PRAGMA table_info(debate_sessions)")}
    if "round_scores" not in existing:
        conn.execute(
            "ALTER TABLE debate_sessions ADD COLUMN round_scores TEXT DEFAULT '{}'"
        )
    # Migration: how participants see each other. No default on purpose:
    # older rows stay NULL, and the debate service decides what NULL means.
    if "peer_labels" not in existing:
        conn.execute("ALTER TABLE debate_sessions ADD COLUMN peer_labels TEXT")
    # Migration: the parent-thread checkpoint a debate started from, so a chat
    # turn after it continues from the same point. NULL: started from nothing.
    if "parent_checkpoint_id" not in existing:
        conn.execute("ALTER TABLE debate_sessions ADD COLUMN parent_checkpoint_id TEXT")
    # Migration: the question each stretch of rounds answered ([{round, prompt}];
    # a redirect starts a new one), what the person injected ([{round,
    # message}]) and the start's run settings, which continuing reuses.
    # Older sessions have none: their question is recovered from the lanes.
    for column in ("questions", "injected", "settings"):
        if column not in existing:
            conn.execute(f"ALTER TABLE debate_sessions ADD COLUMN {column} TEXT")

    # Added later: documents attached to a thread, once per (thread, filename),
    # instead of in the graph state of every checkpoint.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS thread_documents (
            thread_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (thread_id, filename)
        )
    """)

    # Backfill: ensure all debate parent threads appear in thread_metadata.
    # The row only lists the thread; its title stays NULL ("untitled") so the
    # debate can still name it. A placeholder title equal to the thread id read
    # as "already titled" and kept such threads named thread_xxxxxxx.
    conn.execute("""
        INSERT OR IGNORE INTO thread_metadata (thread_id, title)
        SELECT DISTINCT parent_thread_id, NULL
        FROM debate_sessions
    """)
    conn.execute("UPDATE thread_metadata SET title = NULL WHERE title = thread_id")
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
                 current_round, status, termination_policy, auto_synthesize, synthesizer_model,
                 peer_labels)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session["session_id"],
                session["parent_thread_id"],
                json.dumps(session["participants"]),
                json.dumps(session["thread_ids"]),
                session.get("current_round", 0),
                session.get("status", "pending"),
                json.dumps(session["termination_policy"]),
                int(session.get("auto_synthesize", False)),
                session.get("synthesizer_model"),
                session.get("peer_labels"),
            ),
        )
        # Ensure the parent thread is listed even with no chat checkpoints. No
        # title yet: the debate titles an untitled parent when it starts.
        conn.execute(
            "INSERT OR IGNORE INTO thread_metadata (thread_id, title) VALUES (?, NULL)",
            (session["parent_thread_id"],),
        )
        conn.commit()
    finally:
        conn.close()


def _decode_session(cols, row) -> dict[str, Any]:
    data = dict(zip(cols, row))
    data["participants"] = json.loads(data["participants"])
    data["thread_ids"] = json.loads(data["thread_ids"])
    data["termination_policy"] = json.loads(data["termination_policy"])
    data["auto_synthesize"] = bool(data["auto_synthesize"])
    data["round_scores"] = _decode_round_scores(data.get("round_scores"))
    for column, empty in (("questions", []), ("injected", []), ("settings", {})):
        try:
            data[column] = json.loads(data.get(column) or "null") or empty
        except ValueError:
            data[column] = empty
    return data


def get_debate_session(session_id: str) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM debate_sessions WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return _decode_session([d[0] for d in cursor.description], row)
    finally:
        conn.close()


def interrupt_running_debates() -> int:
    """Mark every debate still recorded as running (or paused) interrupted;
    returns how many. For server startup only: a debate can't outlive the
    process that ran it, so at startup none is running, and a stale mark
    would make every later run refuse the session as taken."""
    conn = get_db_connection()
    try:
        cursor = conn.execute("UPDATE debate_sessions SET status = 'interrupted' WHERE status IN ('running', 'paused')")
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def claim_debate_session(session_id: str, force: bool = False) -> bool:
    """Mark the session running unless another run already has it; True if
    this caller now runs it. One conditional UPDATE, so two clients can't
    both claim it. ``force`` takes a session left marked running by a
    process that died."""
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "UPDATE debate_sessions SET status = 'running' WHERE session_id = ? AND (status != 'running' OR ?)",
            (session_id, int(force)),
        )
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()


def append_debate_entry(session_id: str, column: str, entry: dict[str, Any]) -> None:
    """Add an entry to a session's `questions` or `injected` list."""
    if column not in ("questions", "injected"):
        raise ValueError(column)
    conn = get_db_connection()
    try:
        row = conn.execute(f"SELECT {column} FROM debate_sessions WHERE session_id = ?", (session_id,)).fetchone()
        if not row:
            return
        entries = json.loads(row[0] or "[]")
        entries.append(entry)
        conn.execute(f"UPDATE debate_sessions SET {column} = ? WHERE session_id = ?", (json.dumps(entries), session_id))
        conn.commit()
    finally:
        conn.close()


def update_debate_session(session_id: str, **kwargs: Any) -> None:
    """Update any subset of debate session fields."""
    allowed = {
        "current_round", "status", "auto_synthesize", "synthesizer_model", "termination_policy",
        "parent_checkpoint_id", "settings",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    conn = get_db_connection()
    try:
        for key, value in updates.items():
            if key in ("termination_policy", "settings"):
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
        # Newest first. created_at has one-second resolution, and SQLite
        # returns ties in insertion order (oldest first), so sessions created
        # within the same second came back oldest first; rowid breaks the tie.
        order = "ORDER BY created_at DESC, rowid DESC"
        if parent_thread_id:
            cursor.execute(
                f"SELECT * FROM debate_sessions WHERE parent_thread_id = ? {order}",
                (parent_thread_id,),
            )
        else:
            cursor.execute(f"SELECT * FROM debate_sessions {order}")
        cols = [d[0] for d in cursor.description]
        return [_decode_session(cols, row) for row in cursor.fetchall()]
    finally:
        conn.close()


# The synthesis thread is stored in a session's thread_ids under this key,
# beside one entry per participant (model ids never take this name).
SYNTHESIS_KEY = "synthesis"


def synthesis_thread_id(session: dict[str, Any]) -> str:
    """The thread a session's synthesis is written to.

    Sessions created before thread ids were scoped to their session don't
    store it; theirs is the parent's shared "{parent}::synthesis".
    """
    return session["thread_ids"].get(SYNTHESIS_KEY) or f"{session['parent_thread_id']}::{SYNTHESIS_KEY}"


def session_synthesizer(session: dict[str, Any]) -> str:
    """The model that writes a session's synthesis: the one it names, else its
    first participant (what "First participant" in the debate dialog stores
    as no model)."""
    return session.get("synthesizer_model") or session["participants"][0]


def session_thread_ids(session: dict[str, Any]) -> set[str]:
    """Every thread a debate session writes to: its participants' and its synthesis."""
    return {*session["thread_ids"].values(), synthesis_thread_id(session)}


def _purge_thread_rows(conn, thread_id: str) -> None:
    """Delete every row keyed to one thread_id. Caller commits."""
    conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
    conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
    conn.execute("DELETE FROM node_positions WHERE thread_id = ?", (thread_id,))
    conn.execute("DELETE FROM thread_metadata WHERE thread_id = ?", (thread_id,))
    conn.execute("DELETE FROM thread_documents WHERE thread_id = ?", (thread_id,))


class ThreadDocumentStore:
    """Documents attached to a conversation, stored once per thread and filename.

    Their content used to travel in graph state, so every checkpoint a turn
    wrote (4-6 per model) carried the full text again (up to 10 MB a file);
    a turn's state now names the files and the content lives here. Saving is
    idempotent: clients re-send the same documents, and a re-sent file with
    new content replaces the old one.
    """

    def save(self, thread_id: str, documents: Mapping[str, str]) -> None:
        if not documents:
            return
        conn = get_db_connection()
        try:
            conn.executemany(
                """
                INSERT INTO thread_documents (thread_id, filename, content) VALUES (?, ?, ?)
                ON CONFLICT (thread_id, filename) DO UPDATE SET content = excluded.content
                WHERE thread_documents.content <> excluded.content
                """,
                [(thread_id, str(name), str(text)) for name, text in documents.items()],
            )
            conn.commit()
        finally:
            conn.close()

    def load(self, thread_id: str, names: Optional[Sequence[str]] = None) -> dict[str, str]:
        """The thread's documents named in `names`, in that order (all of
        them, in the order first attached, when `names` is None). A name
        with nothing stored is left out."""
        query = "SELECT filename, content FROM thread_documents WHERE thread_id = ?"
        params: list = [thread_id]
        if names is not None:
            if not names:
                return {}
            query += f" AND filename IN ({', '.join('?' for _ in names)})"
            params += [str(n) for n in names]
        conn = get_db_connection()
        try:
            rows = conn.execute(query + " ORDER BY created_at, rowid", params).fetchall()
        finally:
            conn.close()
        stored = {name: content for name, content in rows}
        if names is None:
            return stored
        return {name: stored[name] for name in names if name in stored}


def delete_debate_session(session_id: str) -> None:
    """
    Delete a debate session and every checkpoint only it wrote.

    Dropping only the session row left its sub-threads behind, so the
    checkpoint DB grew without bound. A session's threads are the ids it
    stores (`{parent}::{session_id}::{model}` and `::synthesis`). Sessions
    created before ids were scoped share `{parent}::{model}` and
    `{parent}::synthesis` with every other such debate on that parent, so a
    thread another session still names is kept.
    """
    session = get_debate_session(session_id)
    if session:
        others = [
            s for s in list_debate_sessions(session["parent_thread_id"])
            if s["session_id"] != session_id
        ]
        still_used = set().union(*(session_thread_ids(s) for s in others))
        doomed = session_thread_ids(session) - still_used
    else:
        doomed = set()
    conn = get_db_connection()
    try:
        for thread_id in doomed:
            _purge_thread_rows(conn, thread_id)
        conn.execute("DELETE FROM debate_sessions WHERE session_id = ?", (session_id,))
        conn.commit()
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


# 100 ns intervals between the UUID epoch (1582-10-15) and the Unix epoch.
_UUID_EPOCH_OFFSET = 0x01B21DD213814000


def checkpoint_time(checkpoint_id: str | None) -> float:
    """When a checkpoint was written, from its id (Unix seconds; 0 if unknown).

    LangGraph checkpoint ids are UUIDv6: the timestamp is the first 60 bits,
    most significant first, with the version nibble in between.
    """
    if not checkpoint_id:
        return 0.0
    digits = checkpoint_id.replace("-", "")
    if len(digits) != 32 or digits[12] != "6":
        return 0.0
    try:
        ticks = int(digits[:12] + digits[13:16], 16)
    except ValueError:
        return 0.0
    return max(0.0, (ticks - _UUID_EPOCH_OFFSET) / 1e7)


def _sqlite_time(value: str | None) -> float:
    """A CURRENT_TIMESTAMP value (UTC) as Unix seconds; 0 if unknown."""
    if not value:
        return 0.0
    try:
        from datetime import datetime, timezone

        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


def list_threads():
    """Top-level threads, most recently active first.

    Activity is the newest checkpoint on the thread or any of its debate
    sub-threads ({thread}::…), else when its newest debate was created. They
    used to be ordered by thread id, which is random, so a new thread landed
    anywhere in the sidebar.
    """
    conn = get_db_connection()
    try:
        try:
            conn.execute("SELECT 1 FROM checkpoints LIMIT 1")
        except sqlite3.OperationalError:
            # LangGraph creates its tables on the first run: nothing yet.
            conn.close()
            return []
        last_checkpoint = conn.execute("""
            SELECT CASE WHEN instr(thread_id, '::') > 0
                        THEN substr(thread_id, 1, instr(thread_id, '::') - 1)
                        ELSE thread_id END AS root,
                   MAX(checkpoint_id)
            FROM checkpoints
            GROUP BY root
        """).fetchall()
        own = {row[0] for row in conn.execute(
            "SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id NOT LIKE '%::%'"
        )}
        titles = dict(conn.execute("SELECT thread_id, title FROM thread_metadata").fetchall())
        last_debate = dict(conn.execute(
            "SELECT parent_thread_id, MAX(created_at) FROM debate_sessions GROUP BY parent_thread_id"
        ).fetchall())
    finally:
        conn.close()

    # Listed: threads with checkpoints of their own, and debate parents (which
    # may have none) that have a metadata row.
    listed = own | {t for t in last_debate if t in titles and "::" not in t}
    activity = {root: checkpoint_time(cid) for root, cid in last_checkpoint}
    for parent, created_at in last_debate.items():
        activity[parent] = max(activity.get(parent, 0.0), _sqlite_time(created_at))
    ordered = sorted(listed, key=lambda t: (activity.get(t, 0.0), t), reverse=True)
    return [
        {"id": t, "title": titles.get(t) or t, "updated_at": _iso(activity.get(t))}
        for t in ordered
    ]


def _iso(timestamp: Optional[float]) -> Optional[str]:
    if not timestamp:
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")


def thread_exists(thread_id: str) -> bool:
    """Whether a thread has anything: checkpoints, a title row or a debate.
    Debate sub-threads ({thread}::…) are not threads of their own."""
    if "::" in thread_id:
        return False
    conn = get_db_connection()
    try:
        for query in (
            "SELECT 1 FROM thread_metadata WHERE thread_id = ? LIMIT 1",
            "SELECT 1 FROM debate_sessions WHERE parent_thread_id = ? LIMIT 1",
            "SELECT 1 FROM checkpoints WHERE thread_id = ? LIMIT 1",
        ):
            try:
                if conn.execute(query, (thread_id,)).fetchone():
                    return True
            except sqlite3.OperationalError:  # LangGraph's tables don't exist yet
                continue
        return False
    finally:
        conn.close()


def get_thread_title(thread_id):
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT title FROM thread_metadata WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        return row[0] if row else None
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

    That includes every debate sub-thread and synthesis thread (all named
    `{thread_id}::…`), plus the `debate_sessions` rows themselves — deleting
    only the parent used to orphan all of them.
    """
    conn = get_db_connection()
    try:
        _purge_thread_rows(conn, thread_id)
        # Sub-threads are namespaced "{thread_id}::…". Compared by prefix
        # rather than LIKE because thread ids contain "_", a LIKE wildcard.
        prefix = f"{thread_id}::"
        for table in ("checkpoints", "writes", "node_positions", "thread_metadata", "thread_documents"):
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
