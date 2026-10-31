"""Deleting a thread and everything derived from it, wherever it is stored.

A thread lives in three places: SQLite (checkpoints, titles, positions,
attached documents, debate sessions and sub-threads), the vector store (RAG
chunks of its uploads) and the upload directory. Deleting only the SQLite
rows left the other two behind.
"""

from dataclasses import dataclass
from typing import Callable

from app.core import database as db
from app.services.uploads import delete_thread_uploads


@dataclass(frozen=True)
class ThreadDeleter:
    # Removes a thread's RAG chunks (rag.delete_thread_chunks in the app).
    delete_chunks: Callable[[str], None]
    # Root of the per-thread upload directories.
    upload_root: str

    def __call__(self, thread_id: str) -> None:
        # The other stores first: if one fails, the thread is still listed
        # and the delete can simply be retried.
        self.delete_chunks(thread_id)
        delete_thread_uploads(thread_id, self.upload_root)
        db.delete_thread_data(thread_id)


class ThreadNotFound(ValueError):
    pass


# What a thread with nothing to name it by is called. Never its id: people
# read this list, and "thread_k3x9q2a" names nothing.
UNTITLED = "Untitled conversation"


def list_threads() -> list:
    """Top-level threads, most recently active first: {id, title,
    title_derived, updated_at}.

    A thread nobody titled (one from before auto-titling, or a debate's
    parent) is named on the fly, the way auto-titling would have named it:
    from its first message, else as its latest debate ("Debate: …"), else
    UNTITLED. `title_derived` says the title is not stored, so clients can
    show it as provisional; renaming stores a real one. Nothing is written:
    this runs on every sidebar refresh.
    """
    db.init_db()
    threads = db.list_threads()
    untitled = [t["id"] for t in threads if not t["title"]]
    derived = derived_titles(untitled)
    for t in threads:
        t["title_derived"] = not t["title"]
        if not t["title"]:
            t["title"] = derived.get(t["id"]) or UNTITLED
    return threads


def derived_titles(thread_ids: list[str]) -> dict[str, str]:
    """A title for each of these untitled threads that has something to be
    named by: {thread_id: title}. Blocking (SQLite)."""
    from app.services.chat import thread_title

    titles: dict[str, str] = {}
    firsts = db.first_messages(thread_ids)
    for thread_id in thread_ids:
        title = thread_title(_first_prompt(firsts.get(thread_id, [])))
        if not title:
            question = _debate_question(thread_id)
            title = thread_title(question, "debate") if question else None
        if title:
            titles[thread_id] = title
    return titles


def _first_prompt(messages: list) -> str:
    """The text of the first message the person wrote, if any. These are the
    thread's first turn, so never a synthesis prompt (that needs answers)."""
    from app.utils.helpers import extract_text

    for message in messages:
        if getattr(message, "type", None) == "human":
            return extract_text(message.content)
    return ""


def _debate_question(thread_id: str) -> str:
    """The question the thread's latest debate started with. Sessions
    from before questions were stored have it only as their lanes' first
    message."""
    for session in db.list_debate_sessions(thread_id):
        questions = sorted(session.get("questions") or [], key=lambda q: q["round"])
        # Only a round-0 entry is the original question: a session stored
        # before questions were recorded and redirected since lists only the
        # redirect (as debate.debate_questions also assumes).
        if questions and questions[0]["round"] == 0 and questions[0].get("prompt"):
            return questions[0]["prompt"]
        lanes = [tid for key, tid in session["thread_ids"].items() if key != "synthesis"]
        firsts = db.first_messages(lanes)
        for lane in lanes:
            prompt = _first_prompt(firsts.get(lane, []))
            if prompt:
                return prompt
        if questions and questions[0].get("prompt"):
            return questions[0]["prompt"]
    return ""


def _require(thread_id: str) -> None:
    if "::" in thread_id:
        # A debate lane: removing or renaming one corrupts its debate.
        raise ThreadNotFound(f"{thread_id} is part of a debate, not a thread; use the debate's own commands.")
    if not db.thread_exists(thread_id):
        raise ThreadNotFound(f"Thread {thread_id} not found.")


def rename_thread(thread_id: str, title: str) -> str:
    """Give an existing thread a title; returns it. Blocking (SQLite)."""
    title = title.strip()
    if not title:
        raise ValueError("A title is required.")
    db.init_db()
    _require(thread_id)
    db.rename_thread(thread_id, title)
    return title


def delete_thread(thread_id: str, deleter: Callable[[str], None]) -> None:
    """Delete an existing thread through ``deleter`` (default_thread_deleter
    in the app). Blocking (SQLite, Chroma, the filesystem)."""
    db.init_db()
    _require(thread_id)
    deleter(thread_id)


def default_thread_deleter() -> ThreadDeleter:
    """The app's stores: the Chroma collection and the upload directory."""
    from app.services import rag
    from app.core.storage import current_storage

    return ThreadDeleter(delete_chunks=rag.delete_thread_chunks, upload_root=current_storage().upload_dir)
