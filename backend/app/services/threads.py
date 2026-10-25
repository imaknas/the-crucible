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


def default_thread_deleter() -> ThreadDeleter:
    """The app's stores: the Chroma collection and the upload directory."""
    from app.services import rag
    from app.services.uploads import UPLOAD_DIR

    return ThreadDeleter(delete_chunks=rag.delete_thread_chunks, upload_root=UPLOAD_DIR)
