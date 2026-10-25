"""Documents attached to a conversation: saved once per thread, read per run.

Clients send attached documents with a turn. They used to go into the
turn's graph state, so every checkpoint of the turn carried their full text
again. Entry points now save them to a store (attach_documents) and give
the run the store through its config; drafting_node reads the thread's
documents from there (documents_for_run). The store reaches the graph only
through the config, so a run that names none (experiments, tests) sees only
what its own state carries.

Once attached, a document is part of its thread: every later turn of the
thread, on any branch, sees it.
"""

import asyncio
from typing import Any, Mapping, MutableMapping, Optional

from app.core.database import ThreadDocumentStore

DOCUMENT_STORE_CONFIG_KEY = "document_store"


def document_store_from(config: Optional[Mapping[str, Any]]):
    """The run's document store (anything with save/load), or None."""
    return ((config or {}).get("configurable") or {}).get(DOCUMENT_STORE_CONFIG_KEY)


def with_default_documents(config: MutableMapping[str, Any]):
    """Attach the app's SQLite document store to a run config that names
    none. Returns the config."""
    config.setdefault("configurable", {}).setdefault(DOCUMENT_STORE_CONFIG_KEY, ThreadDocumentStore())
    return config


async def attach_documents(config: Mapping[str, Any], documents: Optional[Mapping[str, str]]) -> None:
    """Save a turn's documents for the config's thread. Re-sending the same
    documents is a no-op."""
    if not documents:
        return
    store = document_store_from(config)
    thread_id = ((config or {}).get("configurable") or {}).get("thread_id")
    if store is None or not thread_id:
        raise ValueError("documents were sent, but the run has no document store or thread")
    await asyncio.to_thread(store.save, thread_id, dict(documents))


def documents_for_run(state: Mapping[str, Any], config: Optional[Mapping[str, Any]]) -> dict:
    """What drafting_node shows as attached documents: any still in the
    state (checkpoints written before the store existed), then the thread's
    stored documents."""
    docs = dict(state.get("documents") or {})
    store = document_store_from(config)
    thread_id = ((config or {}).get("configurable") or {}).get("thread_id")
    if store is not None and thread_id:
        docs.update(store.load(thread_id))
    return docs
