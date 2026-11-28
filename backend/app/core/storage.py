"""Where the app keeps what it stores: one value, chosen by the entry point.

The SQLite database (checkpoints, titles, debates, documents), the upload
directory, the Chroma directory and the .env file used to be module globals
read from the environment at import, and the experiment harness rewrote one
of them to point a run elsewhere. Now an entry point builds a Storage
(`Storage.from_env()` for the app) and sets it for what it runs:

- the server: `create_app(storage=...)` keeps it on `app.state.storage` and
  sets it for every request and socket (main.StorageMiddleware);
- the CLI and the MCP server: once at startup;
- tests: per test (tests/conftest.py).

Code that stores something asks `current_storage()`. Nothing falls back to
the environment on its own: a run that was never given a storage fails
saying so, instead of quietly writing to the app's real database.
"""

import os
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
from typing import Mapping, Optional

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


# Set by brunna when it runs the app as a service: an absolute, writable
# folder for everything the app keeps. The code folder is read-only then,
# and the provider keys arrive as environment variables, with no .env.
SERVICE_STATE_VAR = "BRUNNA_SERVICE_STATE"


def env_file(environ: Mapping[str, str] = os.environ) -> Optional[str]:
    """The .env an entry point loads keys from: backend/.env, or None when
    the app runs as a service."""
    return None if environ.get(SERVICE_STATE_VAR) else os.path.join(_BACKEND, ".env")


@dataclass(frozen=True)
class Storage:
    db_path: str
    upload_dir: str
    chroma_dir: str
    # The .env file keys are read from and written to; None when keys come
    # only from the environment (run as a brunna service).
    env_path: Optional[str]

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> "Storage":
        """The app's own locations: backend/, or the state folder brunna gives
        a service (SERVICE_STATE_VAR), unless DATABASE_PATH, UPLOAD_DIR or
        CHROMA_DIR say otherwise (Docker, the e2e fixture)."""
        root = environ.get(SERVICE_STATE_VAR) or _BACKEND
        return cls(
            db_path=environ.get("DATABASE_PATH") or os.path.join(root, "checkpoints.sqlite"),
            upload_dir=environ.get("UPLOAD_DIR") or os.path.join(root, "uploads"),
            chroma_dir=environ.get("CHROMA_DIR") or os.path.join(root, "chroma_db"),
            env_path=env_file(environ),
        )

    def under(self, root: str) -> "Storage":
        """Every location inside ``root`` (a scratch area for a run)."""
        return replace(
            self,
            db_path=os.path.join(root, "checkpoints.sqlite"),
            upload_dir=os.path.join(root, "uploads"),
            chroma_dir=os.path.join(root, "chroma_db"),
            env_path=os.path.join(root, ".env"),
        )


_current: ContextVar[Optional[Storage]] = ContextVar("crucible_storage", default=None)


class NoStorage(RuntimeError):
    pass


def current_storage() -> Storage:
    storage = _current.get()
    if storage is None:
        raise NoStorage(
            "No storage was set for this run: an entry point sets one "
            "(create_app, the CLI, the MCP server, or set_storage)."
        )
    return storage


def has_storage() -> bool:
    return _current.get() is not None


def set_storage(storage: Storage) -> Token:
    """Use ``storage`` from here on in this context (tasks started from it
    inherit it). Returns the token that undoes it (``reset_storage``)."""
    return _current.set(storage)


def reset_storage(token: Token) -> None:
    _current.reset(token)
