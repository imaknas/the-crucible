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
    # Migration: how the participants were told to argue (services/stances.py:
    # {mode, sides, advocate}). NULL: an open debate, as every session before it.
    if "stance" not in existing:
        conn.execute("ALTER TABLE debate_sessions ADD COLUMN stance TEXT")

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
    # Peer reviews of a set of answers (services/review.py): the latest per
    # set, keyed by the sorted answer checkpoints. Not tree nodes: n reviews
    # of one turn would crowd the tree.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS answer_reviews (
            thread_id TEXT NOT NULL,
            review_key TEXT NOT NULL,
            data TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (thread_id, review_key)
        )
    """)

    # A person's vote on one turn's answers (services/votes.py): the best
    # answer, a tie or "all bad", read blind or not. One per turn; voting
    # again replaces it. Deleted with the thread.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS answer_votes (
            thread_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            outcome TEXT NOT NULL,
            winner_checkpoint_id TEXT,
            answers TEXT NOT NULL,
            reason TEXT,
            task_type TEXT NOT NULL,
            blind INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (thread_id, turn_id)
        )
    """)
    # What a person wrote on a tree node: a branch name, a bookmark, and the
    # summary of the subtree below it (services/subtree.py). Keyed by the
    # node's checkpoint id; never part of the conversation itself.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS node_notes (
            thread_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            name TEXT,
            bookmarked INTEGER NOT NULL DEFAULT 0,
            summary TEXT,
            summary_model TEXT,
            summary_nodes INTEGER,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (thread_id, node_id)
        )
    """)
    # A saved case (services/cases.py): one turn copied whole, so it can be
    # replayed on other models. Deliberately NOT deleted with its thread
    # (_purge_thread_rows): the source ids are a reference only. `data` is
    # the question, history, settings, answers and vote; `documents` is kept
    # apart so listing cases doesn't read files.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS saved_cases (
            case_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            question TEXT NOT NULL,
            data TEXT NOT NULL,
            documents TEXT NOT NULL,
            source_thread_id TEXT,
            source_turn_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # A replay of a saved case: the thread it ran in and each model's answer,
    # copied, so the record outlives that thread. Deleted with its case.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS case_replays (
            replay_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            models TEXT NOT NULL,
            results TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                 peer_labels, stance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                json.dumps(session["stance"]) if session.get("stance") else None,
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
    for column, empty in (("questions", []), ("injected", []), ("settings", {}), ("stance", None)):
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
    conn.execute("DELETE FROM answer_reviews WHERE thread_id = ?", (thread_id,))
    conn.execute("DELETE FROM node_notes WHERE thread_id = ?", (thread_id,))
    conn.execute("DELETE FROM answer_votes WHERE thread_id = ?", (thread_id,))


VOTE_FIELDS = ("thread_id", "turn_id", "outcome", "winner_checkpoint_id", "answers", "reason", "task_type", "blind",
               "created_at")


def _vote_row(row) -> dict:
    vote = dict(zip(VOTE_FIELDS, row))
    vote["answers"] = json.loads(vote["answers"])
    vote["blind"] = bool(vote["blind"])
    return vote


def save_answer_vote(thread_id: str, turn_id: str, *, outcome: str, winner_checkpoint_id: Optional[str],
                     answers: list, reason: Optional[str], task_type: str, blind: bool) -> dict:
    """Store a turn's vote, replacing an earlier one. ``answers`` is
    [{checkpoint_id, model}]. Blocking: call from async code through
    asyncio.to_thread."""
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO answer_votes (thread_id, turn_id, outcome, winner_checkpoint_id, answers, reason, "
            "task_type, blind) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (thread_id, turn_id, outcome, winner_checkpoint_id, json.dumps(answers), reason, task_type, int(blind)),
        )
        conn.commit()
        row = conn.execute(f"SELECT {', '.join(VOTE_FIELDS)} FROM answer_votes WHERE thread_id = ? AND turn_id = ?",
                           (thread_id, turn_id)).fetchone()
    finally:
        conn.close()
    return _vote_row(row)


def get_answer_vote(thread_id: str, turn_id: str) -> Optional[dict]:
    """A turn's vote, or None."""
    conn = get_db_connection()
    try:
        row = conn.execute(f"SELECT {', '.join(VOTE_FIELDS)} FROM answer_votes WHERE thread_id = ? AND turn_id = ?",
                           (thread_id, turn_id)).fetchone()
    finally:
        conn.close()
    return _vote_row(row) if row else None


def list_answer_votes(thread_id: Optional[str] = None) -> list[dict]:
    """Every vote (or a thread's), newest first."""
    conn = get_db_connection()
    try:
        sql = f"SELECT {', '.join(VOTE_FIELDS)} FROM answer_votes"
        rows = conn.execute(sql + (" WHERE thread_id = ?" if thread_id else "") + " ORDER BY created_at DESC, rowid DESC",
                            (thread_id,) if thread_id else ()).fetchall()
    finally:
        conn.close()
    return [_vote_row(r) for r in rows]


def delete_answer_vote(thread_id: str, turn_id: str) -> bool:
    conn = get_db_connection()
    try:
        deleted = conn.execute("DELETE FROM answer_votes WHERE thread_id = ? AND turn_id = ?", (thread_id, turn_id)).rowcount
        conn.commit()
    finally:
        conn.close()
    return bool(deleted)


NOTE_FIELDS = ("name", "bookmarked", "summary", "summary_model", "summary_nodes")


def save_node_note(thread_id: str, node_id: str, **fields: Any) -> Optional[dict]:
    """Change some of a node's notes (``NOTE_FIELDS``), keeping the others;
    a node left with none loses its row. Returns the node's notes, or None.
    Blocking: call from async code through asyncio.to_thread."""
    unknown = set(fields) - set(NOTE_FIELDS)
    if unknown:
        raise ValueError(f"Unknown node note field(s): {', '.join(sorted(unknown))}")
    conn = get_db_connection()
    try:
        row = conn.execute(
            f"SELECT {', '.join(NOTE_FIELDS)} FROM node_notes WHERE thread_id = ? AND node_id = ?",
            (thread_id, node_id),
        ).fetchone()
        note = dict(zip(NOTE_FIELDS, row)) if row else {f: None for f in NOTE_FIELDS}
        note.update(fields)
        note["bookmarked"] = bool(note["bookmarked"])
        if not (note["name"] or note["bookmarked"] or note["summary"]):
            conn.execute("DELETE FROM node_notes WHERE thread_id = ? AND node_id = ?", (thread_id, node_id))
            conn.commit()
            return None
        conn.execute(
            f"INSERT OR REPLACE INTO node_notes (thread_id, node_id, {', '.join(NOTE_FIELDS)}, updated_at) "
            f"VALUES (?, ?, {', '.join('?' for _ in NOTE_FIELDS)}, CURRENT_TIMESTAMP)",
            (thread_id, node_id, *(int(note[f]) if f == "bookmarked" else note[f] for f in NOTE_FIELDS)),
        )
        conn.commit()
        return note
    finally:
        conn.close()


def load_node_notes(thread_id: str) -> dict[str, dict]:
    """Every node's notes on a thread, by node id."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            f"SELECT node_id, {', '.join(NOTE_FIELDS)} FROM node_notes WHERE thread_id = ?", (thread_id,)
        ).fetchall()
    finally:
        conn.close()
    return {r[0]: {**dict(zip(NOTE_FIELDS, r[1:])), "bookmarked": bool(r[2])} for r in rows}


def save_answer_review(thread_id: str, review_key: str, data: dict) -> None:
    """Store a peer review, replacing an earlier one of the same answers. Blocking: call from async code through asyncio.to_thread."""
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO answer_reviews (thread_id, review_key, data) VALUES (?, ?, ?)",
            (thread_id, review_key, json.dumps(data)),
        )
        conn.commit()
    finally:
        conn.close()


def list_answer_reviews(thread_id: str) -> list[dict]:
    """Every stored peer review on a thread, newest first."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT data FROM answer_reviews WHERE thread_id = ? ORDER BY created_at DESC, rowid DESC", (thread_id,)
        ).fetchall()
    finally:
        conn.close()
    return [json.loads(r[0]) for r in rows]


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
    # An untitled thread's title is None here; services/threads names it.
    return [
        {"id": t, "title": titles.get(t) or None, "updated_at": _iso(activity.get(t))}
        for t in ordered
    ]


# How many of a thread's earliest checkpoints first_messages reads. A turn
# starts with an empty root and the run's input checkpoint (no messages yet);
# the next one holds the person's first message.
_FIRST_MESSAGES_SCAN = 8


def first_messages(thread_ids: Sequence[str]) -> dict[str, list]:
    """The message list of each thread's earliest checkpoint that has one:
    {thread_id: [messages]}, threads without any left out.

    Reads at most a few rows per thread, in checkpoint id order (UUIDv6,
    so the oldest first), and deserializes only until one holds messages.
    The first turn's checkpoints are the smallest of a thread, so naming an
    untitled thread costs a handful of small reads, not its whole history.
    """
    if not thread_ids:
        return {}
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    serde = JsonPlusSerializer()
    found: dict[str, list] = {}
    conn = get_db_connection()
    try:
        for thread_id in thread_ids:
            try:
                rows = conn.execute(
                    "SELECT type, checkpoint FROM checkpoints WHERE thread_id = ? AND checkpoint_ns = '' "
                    "ORDER BY checkpoint_id LIMIT ?",
                    (thread_id, _FIRST_MESSAGES_SCAN),
                )
            except sqlite3.OperationalError:  # LangGraph's tables don't exist yet
                return found
            for kind, blob in rows:
                try:
                    checkpoint = serde.loads_typed((kind, blob))
                except Exception:  # a checkpoint this version can't read: skip it
                    continue
                messages = (checkpoint.get("channel_values") or {}).get("messages")
                if messages:
                    found[thread_id] = list(messages)
                    break
    finally:
        conn.close()
    return found


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
        for table in ("checkpoints", "writes", "node_positions", "thread_metadata", "thread_documents", "node_notes"):
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
            conn.execute(
                "DELETE FROM node_notes WHERE thread_id = ? AND node_id = ?",
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


# ─── Saved cases (services/cases.py) ─────────────────────────────

CASE_FIELDS = ("case_id", "title", "question", "data", "source_thread_id", "source_turn_id", "created_at")
REPLAY_FIELDS = ("replay_id", "case_id", "thread_id", "models", "results", "created_at")


def _case_row(row, with_documents: bool = False) -> dict:
    case = dict(zip(CASE_FIELDS, row))
    case["data"] = json.loads(case["data"])
    if with_documents:
        case["documents"] = json.loads(row[len(CASE_FIELDS)])
    return case


def _replay_row(row) -> dict:
    replay = dict(zip(REPLAY_FIELDS, row))
    replay["models"] = json.loads(replay["models"])
    replay["results"] = json.loads(replay["results"])
    return replay


def save_case(case_id: str, *, title: str, question: str, data: dict, documents: dict,
              source_thread_id: Optional[str], source_turn_id: Optional[str]) -> dict:
    """Store a saved case; returns it as get_case does. Blocking: call from
    async code through asyncio.to_thread."""
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO saved_cases (case_id, title, question, data, documents, source_thread_id, source_turn_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (case_id, title, question, json.dumps(data), json.dumps(documents), source_thread_id, source_turn_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_case(case_id)


def get_case(case_id: str) -> Optional[dict]:
    """A saved case with its documents ({attached: {name: text}, searched: {...}}), or None."""
    conn = get_db_connection()
    try:
        row = conn.execute(f"SELECT {', '.join(CASE_FIELDS)}, documents FROM saved_cases WHERE case_id = ?",
                           (case_id,)).fetchone()
    finally:
        conn.close()
    return _case_row(row, with_documents=True) if row else None


def list_cases() -> list[dict]:
    """Every saved case, newest first, without its documents' content, each
    with how often it was replayed and when last."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            f"SELECT {', '.join('c.' + f for f in CASE_FIELDS)}, COUNT(r.replay_id), MAX(r.created_at) "
            "FROM saved_cases c LEFT JOIN case_replays r ON r.case_id = c.case_id "
            "GROUP BY c.case_id ORDER BY c.created_at DESC, c.rowid DESC"
        ).fetchall()
    finally:
        conn.close()
    cases = []
    for row in rows:
        case = _case_row(row[:len(CASE_FIELDS)])
        case["replay_count"], case["last_replayed_at"] = row[len(CASE_FIELDS)], row[len(CASE_FIELDS) + 1]
        cases.append(case)
    return cases


def delete_case(case_id: str) -> bool:
    """Delete a saved case and its replay records (the replay threads are
    ordinary threads and stay). False when there was no such case."""
    conn = get_db_connection()
    try:
        deleted = conn.execute("DELETE FROM saved_cases WHERE case_id = ?", (case_id,)).rowcount
        conn.execute("DELETE FROM case_replays WHERE case_id = ?", (case_id,))
        conn.commit()
    finally:
        conn.close()
    return bool(deleted)


def save_case_replay(replay_id: str, case_id: str, thread_id: str, models: list, results: list) -> dict:
    """Store one replay of a case; returns it. Blocking: see save_case."""
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO case_replays (replay_id, case_id, thread_id, models, results) VALUES (?, ?, ?, ?, ?)",
            (replay_id, case_id, thread_id, json.dumps(models), json.dumps(results)),
        )
        conn.commit()
        row = conn.execute(f"SELECT {', '.join(REPLAY_FIELDS)} FROM case_replays WHERE replay_id = ?",
                           (replay_id,)).fetchone()
    finally:
        conn.close()
    return _replay_row(row)


def list_case_replays(case_id: str) -> list[dict]:
    """A case's replays, newest first."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            f"SELECT {', '.join(REPLAY_FIELDS)} FROM case_replays WHERE case_id = ? "
            "ORDER BY created_at DESC, rowid DESC",
            (case_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_replay_row(r) for r in rows]
