"""Deleting a thread removes it from every store: SQLite, the vector store and
the upload directory. Only SQLite used to be cleaned.

The vector store is always a fake here; the embedding model is never loaded.
"""

import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.core import database as db
from app.services import rag
from app.services.threads import ThreadDeleter
from app.services.uploads import thread_upload_dir


class _FakeCollection:
    def __init__(self):
        self.deleted = []

    def delete(self, where=None, **_):
        self.deleted.append(where)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "del.sqlite"))
    db.init_db()
    conn = sqlite3.connect(db.DB_PATH)  # LangGraph's own tables
    conn.execute("CREATE TABLE checkpoints (thread_id TEXT, checkpoint_id TEXT)")
    conn.execute("CREATE TABLE writes (thread_id TEXT, checkpoint_id TEXT)")
    for tid in ("t1", "t1::gpt-5.4", "t2"):
        conn.execute("INSERT INTO checkpoints VALUES (?, 'cp')", (tid,))
    conn.commit()
    conn.close()
    store = db.ThreadDocumentStore()
    store.save("t1", {"a.md": "one"})
    store.save("t2", {"b.md": "two"})
    return db


def _upload(root, thread_id, name="f.txt"):
    path = thread_upload_dir(thread_id, str(root))
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, name), "w") as f:
        f.write("x")
    return path


def _checkpoint_threads():
    conn = sqlite3.connect(db.DB_PATH)
    rows = {r[0] for r in conn.execute("SELECT thread_id FROM checkpoints")}
    conn.close()
    return rows


def test_a_deleted_thread_leaves_nothing_behind(isolated_db, tmp_path):
    root = tmp_path / "uploads"
    mine, other = _upload(root, "t1"), _upload(root, "t2")
    collection = _FakeCollection()
    ThreadDeleter(delete_chunks=lambda tid: rag.delete_thread_chunks(tid, collection), upload_root=str(root))("t1")

    assert collection.deleted == [{"thread_id": "t1"}]
    assert not os.path.exists(mine) and os.path.exists(other)
    assert _checkpoint_threads() == {"t2"}
    assert db.ThreadDocumentStore().load("t1") == {}
    assert db.ThreadDocumentStore().load("t2") == {"b.md": "two"}


def test_a_thread_without_uploads_deletes_cleanly(isolated_db, tmp_path):
    ThreadDeleter(delete_chunks=lambda tid: None, upload_root=str(tmp_path / "none"))("t1")
    assert _checkpoint_threads() == {"t2"}


def test_if_the_vector_store_fails_the_thread_stays_for_a_retry(isolated_db, tmp_path):
    def broken(_tid):
        raise RuntimeError("chroma is down")

    with pytest.raises(RuntimeError):
        ThreadDeleter(delete_chunks=broken, upload_root=str(tmp_path))("t1")
    assert "t1" in _checkpoint_threads()


def test_chunks_are_deleted_by_thread_metadata():
    collection = _FakeCollection()
    rag.delete_thread_chunks("thread_abc", collection)
    assert collection.deleted == [{"thread_id": "thread_abc"}]
    with pytest.raises(ValueError):
        rag.delete_thread_chunks("", collection)


def test_upload_dirs_stay_under_the_root(tmp_path):
    root = str(tmp_path)
    for tid in ("../../etc", "/abs/path", "a/b", "thread_1"):
        path = thread_upload_dir(tid, root)
        assert os.path.dirname(path) == root
    assert thread_upload_dir("t1", root) != thread_upload_dir("t2", root)


def test_uploads_land_in_their_threads_directory(tmp_path, monkeypatch):
    from app.api import upload as upload_api
    from app.main import server

    monkeypatch.setattr(upload_api, "_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(upload_api.rag_service, "index_document", lambda *a: 0)
    with TestClient(server) as client:
        res = client.post(
            "/upload", data={"thread_id": "t1"}, files={"file": ("n.txt", b"hello", "text/plain")},
            headers={"X-Crucible-Client": "1"},  # multipart POSTs need it (api/security.py)
        )
    assert res.status_code == 200
    (stored,) = os.listdir(thread_upload_dir("t1", str(tmp_path)))
    assert stored.endswith("_n.txt")
