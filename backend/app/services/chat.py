"""One chat turn, independent of how it is delivered.

api/chat.py drives these over REST and WebSockets; nothing here knows about
either. A turn always forks from an explicit parent checkpoint and is tagged
with a run id (see services/runs.py), so parallel models in one turn stay on
their own branches.
"""

import asyncio
import logging
from typing import Any, AsyncIterator, Dict, Mapping, Optional, Sequence

from langchain_core.messages import HumanMessage

from app.services.context import DEFAULT_CONTEXT, ContextSettings
from app.services.documents import attach_documents
from app.services.recall import INTERNAL_TAG
from app.services.runs import (
    TURN_KIND_KEY,
    TURN_KINDS,
    final_state_of_run,
    tag_run,
    tag_turn,
    tag_turn_kind,
    thread_config,
)
from app.utils.helpers import clean_string, extract_text

log = logging.getLogger(__name__)

MAX_PROMPT_CHARS = 100_000
TITLE_CHARS = 40


def build_turn_input(
    state_values: Mapping[str, Any],
    *,
    message: Optional[str],
    model: str,
    toggles: Optional[Mapping[str, bool]] = None,
    document_names: Sequence[str] = (),
    is_deliberation: bool = False,
    turn_kind: Optional[str] = None,
) -> Dict[str, Any]:
    """The graph input for one model's turn, given the parent's state values.

    A special turn's prompt (a synthesis request) carries its kind in the
    message itself, so every reader of the path can hide it
    (tree.is_synthesis_prompt), not only readers of checkpoint metadata.

    The turn's attached documents are named, not included: their content is
    saved per thread (services/documents.py). Exactly the named ones are in
    context, so a turn sent without documents has none. `documents` (their
    content, as older checkpoints carry it) is reset so such a parent stops
    handing its copy down. Empty prompts get a stand-in: Anthropic rejects
    empty content.
    """
    text = clean_string(message or "")
    if len(text) > MAX_PROMPT_CHARS:
        text = text[:MAX_PROMPT_CHARS] + "\n\n[... truncated ...]"

    if text.strip():
        prompt = text
    elif is_deliberation:
        prompt = "Please review the conversation and provide your analysis."
    else:
        prompt = "Please continue."

    message = (
        HumanMessage(content=prompt, additional_kwargs={TURN_KIND_KEY: turn_kind})
        if turn_kind in TURN_KINDS
        else ("user", prompt)
    )
    return {
        "active_peer": model,
        "toggles": {**state_values.get("toggles", {}), **(toggles or {})},
        "is_deliberation": is_deliberation,
        "attached_documents": list(document_names),
        "documents": {},
        "notices": [],
        "messages": [message],
    }


def auto_title(first_user_message: str) -> Optional[str]:
    """A thread title from its first message: first line, word-trimmed to 40 chars."""
    first_line = first_user_message.strip().split("\n")[0]
    if not first_line:
        return None
    if len(first_line) <= TITLE_CHARS:
        return first_line
    return first_line[:TITLE_CHARS].rsplit(" ", 1)[0] + "…"


def thread_title(first_message: str, kind: Optional[str] = None) -> Optional[str]:
    """The title a new thread gets, whichever client started it: its first
    message (auto_title); a debate's says it is one."""
    title = auto_title(first_message or "")
    if kind == "debate":
        return f"Debate: {title}" if title else "Debate"
    if kind == "deliberation" and not title:
        return "Deliberation"
    return title


async def name_new_thread(thread_id: str, first_message: str, kind: Optional[str] = None) -> Optional[str]:
    """Title a thread from its first message unless it already has a title;
    returns the title written, or None.

    A thread can be titled before its first checkpoint (a debate's parent is
    named after the debate), so an existing title is never overwritten. The
    writes run off the event loop: the checkpointer commits on the loop, and
    a blocking write there can wait on a lock that is only released once it
    returns ("database is locked")."""
    from app.core import database as db

    title = thread_title(first_message, kind)
    if not title or await asyncio.to_thread(db.get_thread_title, thread_id):
        return None
    await asyncio.to_thread(db.rename_thread, thread_id, title)
    return title


async def path_messages(graph_app, final_state) -> list:
    """Client-ready messages on the path from the root to `final_state`.

    Built from the path's checkpoints rather than final_state's own messages,
    which may be pruned by summarisation. The thread's checkpoints come in
    one saver pass; walking parent links with a read per checkpoint made
    every reply's cost grow with the thread's length.
    """
    from app.services.tree import format_messages

    states = await thread_state_map(graph_app, final_state.config["configurable"]["thread_id"])
    cid = final_state.config["configurable"]["checkpoint_id"]
    states.setdefault(cid, final_state)
    return format_messages(cid, states)


async def thread_state_map(graph_app, thread_id: str) -> Dict[str, Any]:
    """Every checkpoint of a thread by id, in one saver pass."""
    states: Dict[str, Any] = {}
    async for snapshot in graph_app.aget_state_history(thread_config(thread_id)):
        states[snapshot.config["configurable"]["checkpoint_id"]] = snapshot
    return states


def node_checkpoint(snapshot, states: Mapping[str, Any]) -> str:
    """The checkpoint the tree shows for the message ``snapshot`` ends on:
    the first of the run's consecutive checkpoints ending on it. Every id the
    backend hands out is this one, so an id from a reply, the tree, search or
    a path is the same id (deleting it deletes that reply)."""
    from app.services.tree import get_content_key

    key = get_content_key(snapshot)
    current = snapshot
    while current.parent_config:
        parent = states.get(current.parent_config["configurable"]["checkpoint_id"])
        if parent is None or get_content_key(parent) != key:
            break
        current = parent
    return current.config["configurable"]["checkpoint_id"]


async def stream_turn(
    graph_app,
    thread_id: str,
    parent_checkpoint_id: Optional[str],
    *,
    message: Optional[str],
    model: str,
    toggles: Optional[Mapping[str, bool]] = None,
    documents: Optional[Mapping[str, str]] = None,
    document_names: Optional[Sequence[str]] = None,
    is_deliberation: bool = False,
    context: ContextSettings = DEFAULT_CONTEXT,
    turn_kind: Optional[str] = None,
    turn_id: Optional[str] = None,
    configurable: Optional[Mapping[str, Any]] = None,
    with_path: bool = True,
) -> AsyncIterator[Dict[str, Any]]:
    """Run one model's turn: every client's turns (chat, arena, synthesis,
    debate rounds) go through here.

    Yields ``token`` events, ``drafted`` once the reply is written (later
    nodes are bookkeeping), then one ``end`` event: the reply's checkpoint
    (its tree node), text, turn id, the run's attached documents and
    retrieved sources, notices about anything that degraded the turn, and
    (``with_path``) the path's messages. Raises on failure.

    ``parent_checkpoint_id`` None continues from the thread head.
    ``documents`` are saved and attached; ``document_names`` attach files
    already saved for the run's document thread. ``turn_kind="synthesis"``
    tags the turn's checkpoints, so the tree and the transcript can show the
    reply as a synthesis. ``configurable`` adds run settings (e.g. the
    document thread a debate lane reads)."""
    config = context.apply(thread_config(thread_id, parent_checkpoint_id))
    config["configurable"].update(configurable or {})
    run_id = tag_run(config)
    tag_turn_kind(config, turn_kind)
    tag_turn(config, turn_id)
    names = list(document_names) if document_names is not None else await attach_documents(config, documents)
    state = await graph_app.aget_state(config)

    current = state.values.get("messages", [])
    if current:
        from app.services.graph import count_tokens, get_token_limit

        log.info(f"[Context] Current Tokens: {count_tokens(current)}, Limit: {get_token_limit(model)}")

    turn_input = build_turn_input(
        state.values,
        message=message,
        model=model,
        toggles=toggles,
        document_names=names,
        is_deliberation=is_deliberation,
        turn_kind=turn_kind,
    )

    async for event in graph_app.astream_events(turn_input, config, version="v2", exclude_tags=[INTERNAL_TAG]):
        kind = event.get("event")
        if kind == "on_chain_end" and event.get("name") == "draft":
            yield {"type": "drafted"}
            continue
        if kind != "on_chat_model_stream":
            continue
        if event.get("metadata", {}).get("langgraph_node") != "draft":
            continue
        chunk = event.get("data", {}).get("chunk")
        if chunk is None or getattr(chunk, "content", None) is None:
            continue
        token = extract_text(chunk.content, strip=False)
        if token:
            yield {"type": "token", "token": token}

    final = await final_state_of_run(graph_app, thread_id, run_id)
    if final is None:
        raise RuntimeError(f"{model} finished without writing a checkpoint")
    states = await thread_state_map(graph_app, thread_id)
    cid = final.config["configurable"]["checkpoint_id"]
    states.setdefault(cid, final)
    values = final.values or {}
    end = {
        "type": "end",
        "checkpoint_id": node_checkpoint(final, states),
        "content": reply_text(final),
        "turn_id": turn_id,
        "attached_documents": list(values.get("attached_documents") or []),
        "retrieved": sorted({c.get("filename") for c in values.get("retrieved_chunks") or [] if c.get("filename")}),
        "notices": list(values.get("notices") or []),
    }
    if with_path:
        from app.services.tree import format_messages

        end["messages"] = format_messages(cid, states)
    yield end


def reply_text(state) -> str:
    """The text of the last reply in a checkpoint's messages ("" if none)."""
    messages = (state.values or {}).get("messages", []) if state else []
    last_ai = next((m for m in reversed(messages) if getattr(m, "type", "") == "ai"), None)
    return extract_text(last_ai.content) if last_ai is not None else ""
