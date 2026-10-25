"""Where uploaded files are kept: one directory per thread.

Files used to land flat in the upload directory under a random name, so
nothing tied them to a thread and deleting the thread left them behind. The
directory name is a hash of the thread id, because the id comes from the
client and must not become a path.
"""

import hashlib
import os
import shutil

UPLOAD_DIR = os.getenv(
    "UPLOAD_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "uploads")),
)


def thread_upload_dir(thread_id: str, root: str = UPLOAD_DIR) -> str:
    return os.path.join(root, hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:32])


def delete_thread_uploads(thread_id: str, root: str = UPLOAD_DIR) -> None:
    """Remove every file uploaded to one thread (nothing to do if none was)."""
    path = thread_upload_dir(thread_id, root)
    if os.path.isdir(path):
        shutil.rmtree(path)
