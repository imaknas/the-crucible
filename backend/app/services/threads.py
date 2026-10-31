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


def list_threads() -> list:
    """Top-level threads, most recently active first: {id, title, updated_at}."""
    db.init_db()
    return db.list_threads()


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
