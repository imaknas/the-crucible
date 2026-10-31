"""Uploaded and attached files: where they are kept (one directory per
thread) and what text they hold.

Files used to land flat in the upload directory under a random name, so
nothing tied them to a thread and deleting the thread left them behind. The
directory name is a hash of the thread id, because the id comes from the
client and must not become a path.
"""

import hashlib
import os
import shutil
import uuid
from dataclasses import dataclass
from typing import Optional

from app.core.storage import current_storage
from app.utils.parser import extract_text_from_pdf



def thread_upload_dir(thread_id: str, root: Optional[str] = None) -> str:
    """The thread's directory under ``root`` (default: the run's upload directory)."""
    root = root or current_storage().upload_dir
    return os.path.join(root, hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:32])


def delete_thread_uploads(thread_id: str, root: Optional[str] = None) -> None:
    """Remove every file uploaded to one thread (nothing to do if none was)."""
    path = thread_upload_dir(thread_id, root)
    if os.path.isdir(path):
        shutil.rmtree(path)


# ─── Documents: what a file says ─────────────────────────────────

ALLOWED_EXTENSIONS = frozenset({".pdf", ".txt", ".md", ".csv"})
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB


@dataclass(frozen=True)
class Document:
    filename: str
    text: str


def checked_filename(filename: str) -> str:
    """The file's base name, if its type can be read; raises ValueError otherwise.

    The base name only: a client-sent "../../x.txt" must not become a path."""
    name = os.path.basename(filename or "")
    if not name:
        raise ValueError("Missing filename")
    ext = os.path.splitext(name.lower())[1]
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File type '{ext}' is not supported. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")
    return name


def check_size(size: int) -> None:
    if size > MAX_FILE_BYTES:
        raise ValueError("File exceeds the 10 MB size limit.")


def _text_of(path: str) -> str:
    if path.lower().endswith(".pdf"):
        return extract_text_from_pdf(path)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def save_upload(thread_id: str, filename: str, data: bytes, root: Optional[str] = None) -> Document:
    """Keep an uploaded file under the thread's directory and return its text.

    Unique on disk: a shared name let two concurrent uploads of the same
    filename read back (and index into their thread) each other's content.
    Indexing it for retrieval (rag.index_document) is the caller's step.
    """
    name = checked_filename(filename)
    check_size(len(data))
    thread_dir = thread_upload_dir(thread_id, root)
    os.makedirs(thread_dir, exist_ok=True)
    path = os.path.join(thread_dir, f"{uuid.uuid4().hex}_{name}")
    with open(path, "wb") as f:
        f.write(data)
    return Document(name, _text_of(path))


def read_document(path: str) -> Document:
    """A local file's text, checked like an upload: how the CLI and MCP
    attach a document to a turn, where the web UI uploads it first."""
    name = checked_filename(path)
    if not os.path.isfile(path):
        raise ValueError(f"No such file: {path}")
    check_size(os.path.getsize(path))
    return Document(name, _text_of(path))


def keep_upload(thread_id: str, doc: Document, index, documents) -> dict:
    """What an upload does once its text is known, whoever received it:
    index it for retrieval (``use_rag``; ``index`` is rag.index_document or a
    stand-in) and keep it as a document the thread's turns can attach by
    name (``documents`` is a ThreadDocumentStore). Returns {filename, chunks}."""
    documents.save(thread_id, {doc.filename: doc.text})
    return {"filename": doc.filename, "chunks": index(doc.text, doc.filename, thread_id)}


def upload_file(thread_id: str, path: str, index, documents, root: Optional[str] = None) -> dict:
    """Upload a local file to a thread, as the web UI's upload does
    (keep_upload). Returns {filename, chunks}."""
    name = checked_filename(path)
    if not os.path.isfile(path):
        raise ValueError(f"No such file: {path}")
    check_size(os.path.getsize(path))
    with open(path, "rb") as f:
        doc = save_upload(thread_id, name, f.read(), root)
    return keep_upload(thread_id, doc, index, documents)


def read_documents(paths) -> dict:
    """{filename: text} for local files, the shape a turn's `documents` take."""
    documents = {}
    for path in paths or ():
        doc = read_document(path)
        documents[doc.filename] = doc.text
    return documents
