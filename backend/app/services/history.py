"""Reading and editing a thread's checkpoint history: the tree, one path,
search, deleting a branch.

The REST routes, the CLI and the MCP server all call these; none of them
knows about the others.
"""

import asyncio
from collections import deque
from typing import Any, Dict, List, Optional

from app.core import database as db
from app.core.schema import is_summary_message
from app.services.runs import answered_head, thread_config
from app.services.tree import (
    build_history_tree,
    get_checkpoint_role,
    get_content_key,
    is_synthesis_prompt,
    load_thread_states,
)
from app.utils.helpers import extract_text

SEARCH_LIMIT = 20


async def thread_tree(graph_app, thread_id: str, checkpoint_id: Optional[str] = None) -> Dict[str, Any]:
    """The thread's conversation tree, and the messages on the path to
    ``checkpoint_id`` (default: the answered head, where the next turn goes).

    Empty nodes/edges for a thread with no checkpoints."""
    # One saver pass for the whole thread, with an individual-fetch fallback
    # for parallel branches outside the main lineage.
    all_states = await load_thread_states(graph_app, thread_id)
    if not all_states:
        return {"nodes": [], "edges": [], "current_checkpoint": None, "messages": []}

    if checkpoint_id:
        active_state = await graph_app.aget_state(thread_config(thread_id, checkpoint_id))
    else:
        # The composer replies to this: never an unanswered, abandoned turn.
        active_state = await answered_head(graph_app, thread_id)

    tree_data = build_history_tree(thread_id, all_states, active_state)
    return {
        "nodes": tree_data["nodes"],
        "edges": tree_data["edges"],
        "current_checkpoint": tree_data["current_checkpoint"],
        "messages": tree_data["messages"],
    }


def topology(thread_id: str) -> Dict[str, Any]:
    """Every raw checkpoint of a thread and its parent link: {nodes: [{id,
    label, metadata}], edges: [{source, target}]}. Read from the checkpoint
    tables, so it includes the pass-through checkpoints the tree collapses.
    `metadata` is empty: it used to carry a self-reported confidence and a
    keyword "conflict" flag, which models are no longer asked for."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, str]] = []
    seen = set()
    for cid, parent in db.get_thread_checkpoint_graph(thread_id):
        for node in (cid, parent):
            if node and node not in seen:
                seen.add(node)
                nodes.append({"id": node, "label": f"Node {node[:8]}", "metadata": {}})
        if parent:
            edges.append({"source": parent, "target": cid})
    return {"nodes": nodes, "edges": edges}


async def path_at(graph_app, thread_id: str, checkpoint_id: str) -> List[Dict[str, Any]]:
    """The messages from the root to ``checkpoint_id``, as the transcript shows
    them. Raises ValueError when the thread has no such checkpoint."""
    from app.services.chat import path_messages

    state = await graph_app.aget_state(thread_config(thread_id, checkpoint_id))
    if not state.values:
        raise ValueError(f"Checkpoint {checkpoint_id} not found on thread {thread_id}.")
    return await path_messages(graph_app, state)


async def delete_branch(graph_app, thread_id: str, checkpoint_id: str) -> int:
    """Delete a node of the tree and everything below it; returns how many
    checkpoints were removed (0 when the checkpoint doesn't exist).

    Any checkpoint of the node counts as the node (a reply's last checkpoint,
    as older clients were given, deletes the reply, not just what follows
    it), and the tree shows one node for checkpoints with the same parent and
    content, so all of those go too. The root can't be deleted this way: that
    is deleting the thread.
    """
    from app.services.chat import node_checkpoint, thread_state_map

    states = await thread_state_map(graph_app, thread_id)
    if checkpoint_id not in states:
        return 0
    node = node_checkpoint(states[checkpoint_id], states)
    if not states[node].parent_config:
        raise ValueError(f"{checkpoint_id} is the start of thread {thread_id}; delete the thread instead.")

    child_map: Dict[str, List[str]] = {}
    for cid, snapshot in states.items():
        if snapshot.parent_config:
            child_map.setdefault(snapshot.parent_config["configurable"]["checkpoint_id"], []).append(cid)

    target_key = get_content_key(states[node])
    target_parent = states[node].parent_config["configurable"]["checkpoint_id"]
    to_delete = {node} | {
        cid for cid in child_map.get(target_parent, []) if get_content_key(states[cid]) == target_key
    }
    queue = deque(to_delete)
    while queue:
        for child in child_map.get(queue.popleft(), []):
            if child not in to_delete:
                to_delete.add(child)
                queue.append(child)

    # Off the loop: see database.py on writing from async code.
    await asyncio.to_thread(db.delete_checkpoint_data, thread_id, to_delete)
    return len(to_delete)


async def compact_tree(graph_app, thread_id: str, excerpt_chars: int = 300) -> Dict[str, Any]:
    """The conversation tree for a reader that isn't a canvas (the CLI's
    JSON, MCP): one entry per node with its checkpoint id, parent, role,
    model, kind, turn, time and the start of its text as written.

    A thread that so far holds only debates has no nodes; its debates are
    listed. Raises ValueError for a thread that doesn't exist."""
    data = await thread_tree(graph_app, thread_id)
    debates = [s["session_id"] for s in await asyncio.to_thread(db.list_debate_sessions, thread_id)]
    if not data["nodes"] and not debates and not await asyncio.to_thread(db.thread_exists, thread_id):
        raise ValueError(f"Thread {thread_id} not found.")
    parents = {e["target"]: e["source"] for e in data["edges"]}
    nodes = []
    for n in data["nodes"]:
        meta = n.get("metadata", {})
        is_reply = meta.get("role") == "ai"
        nodes.append({
            "checkpoint_id": n["id"],
            "parent": parents.get(n["id"]),
            "role": "assistant" if is_reply else meta.get("role"),
            "model": meta.get("active_peer") if is_reply else None,
            "model_name": meta.get("model_name") if is_reply else None,
            "kind": meta.get("kind"),
            "turn_id": meta.get("turn_id"),
            "created_at": meta.get("created_at"),
            "excerpt": (meta.get("excerpt") or "")[:excerpt_chars],
        })
    return {"thread_id": thread_id, "current_checkpoint": data["current_checkpoint"], "nodes": nodes, "debates": debates}


async def search_thread(graph_app, thread_id: str, query: str, limit: int = SEARCH_LIMIT) -> List[Dict[str, Any]]:
    """Messages on any branch of the thread containing ``query`` (case
    insensitive, at least two characters), each with an excerpt and the
    checkpoint to open. Summaries and synthesis prompts are not searched.

    A message sits at the end of several checkpoints (LangGraph writes a few
    per turn); the result is the first, which is the tree's node for it, so
    deleting it removes the whole turn."""
    if not query or len(query.strip()) < 2:
        raise ValueError("Search for at least two characters.")
    if not await asyncio.to_thread(db.thread_exists, thread_id):
        raise ValueError(f"Thread {thread_id} not found.")
    needle = query.lower()

    results: List[Dict[str, Any]] = []
    seen = set()
    states = sorted(await load_thread_states(graph_app, thread_id), key=lambda s: s.created_at or "")
    for state in states:
        messages = (state.values or {}).get("messages") or []
        if not messages:
            continue
        last = messages[-1]
        if is_summary_message(last) or is_synthesis_prompt(last) or getattr(last, "type", "") == "remove":
            continue
        text = extract_text(getattr(last, "content", "") if hasattr(last, "content") else
                            (last.get("content", "") if isinstance(last, dict) else str(last)))
        if not text.strip() or needle not in text.lower():
            continue
        role = get_checkpoint_role(state)
        key = (role, text[:200])
        if key in seen:
            continue
        seen.add(key)

        idx = text.lower().find(needle)
        start = max(0, idx - 40)
        end = min(len(text), idx + len(query) + 60)
        results.append({
            "checkpoint_id": state.config.get("configurable", {}).get("checkpoint_id"),
            "role": role,
            "model": getattr(last, "name", None) or (last.get("name") if isinstance(last, dict) else None),
            "excerpt": ("..." if start > 0 else "") + text[start:end] + ("..." if end < len(text) else ""),
            "timestamp": getattr(state, "created_at", None),
        })
        if len(results) >= limit:
            break
    return results
