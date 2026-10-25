"""Documents attached to a turn: content stored once per thread, names per turn.

A client sends the documents that are attached right now with every turn;
that set is what the turn's model sees, and a document the person removed
is gone from the next turn. The content used to go into the turn's graph
state, so every checkpoint of the turn carried the full text again.

Now an entry point saves the content to a store (attach_documents, keyed by
thread and filename, idempotent) and puts only the filenames in the turn's
state (`attached_documents`). drafting_node loads exactly those files from
the store (documents_for_run). The store reaches the graph only through the
run config, so a run that names none (experiments, tests) sees only what its
own state carries.
"""

import asyncio
from typing import Any, List, Mapping, MutableMapping, Optional

from app.core.database import ThreadDocumentStore

DOCUMENT_STORE_CONFIG_KEY = "document_store"
# Which thread's documents a run reads and saves, when not its own: debate
# participants draft on sub-threads but share the parent thread's copy.
DOCUMENT_THREAD_CONFIG_KEY = "document_thread_id"


def _configurable(config: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    return (config or {}).get("configurable") or {}


def document_store_from(config: Optional[Mapping[str, Any]]):
    """The run's document store (anything with save/load), or None."""
    return _configurable(config).get(DOCUMENT_STORE_CONFIG_KEY)


def document_thread(config: Optional[Mapping[str, Any]]) -> Optional[str]:
    """The thread whose stored documents the run uses."""
    configurable = _configurable(config)
    return configurable.get(DOCUMENT_THREAD_CONFIG_KEY) or configurable.get("thread_id")


def with_default_documents(config: MutableMapping[str, Any]):
    """Attach the app's SQLite document store to a run config that names
    none. Returns the config."""
    config.setdefault("configurable", {}).setdefault(DOCUMENT_STORE_CONFIG_KEY, ThreadDocumentStore())
    return config


async def attach_documents(config: Mapping[str, Any], documents: Optional[Mapping[str, str]]) -> List[str]:
    """Save a turn's documents for the run's document thread and return
    their names, which go into the turn's state. Re-sending the same
    documents writes nothing; a file sent with new content replaces the old."""
    if not documents:
        return []
    store = document_store_from(config)
    thread_id = document_thread(config)
    if store is None or not thread_id:
        raise ValueError("documents were sent, but the run has no document store or thread")
    await asyncio.to_thread(store.save, thread_id, dict(documents))
    return list(documents)


def documents_for_run(state: Mapping[str, Any], config: Optional[Mapping[str, Any]]) -> dict:
    """What drafting_node shows as attached documents: content a checkpoint
    from before the store still carries in `documents`, then the files the
    turn names in `attached_documents`, loaded from the store."""
    docs = dict(state.get("documents") or {})
    names = list(state.get("attached_documents") or [])
    store = document_store_from(config)
    thread_id = document_thread(config)
    if names and store is not None and thread_id:
        docs.update(store.load(thread_id, names))
    elif names:
        print(f"[Documents] {len(names)} attached, but the run has no document store; left out")
    return docs
