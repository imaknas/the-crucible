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

    The tree shows one node for checkpoints with the same parent and content
    (LangGraph writes several per turn), so all of those go too.
    """
    raw_graph = db.get_thread_checkpoint_graph(thread_id)
    child_map: Dict[str, List[str]] = {}
    parent_map: Dict[str, str] = {}
    for cid, pid in raw_graph:
        if pid:
            child_map.setdefault(pid, []).append(cid)
            parent_map[cid] = pid

    target_state = await graph_app.aget_state(thread_config(thread_id, checkpoint_id))
    if not target_state or not target_state.values:
        return 0

    target_key = get_content_key(target_state)
    target_parent = parent_map.get(checkpoint_id)
    to_delete = {checkpoint_id}
    for cid, pid in raw_graph:
        if pid == target_parent and cid != checkpoint_id:
            sibling = await graph_app.aget_state(thread_config(thread_id, cid))
            if sibling and sibling.values and get_content_key(sibling) == target_key:
                to_delete.add(cid)

    queue = deque(to_delete)
    while queue:
        for child in child_map.get(queue.popleft(), []):
            if child not in to_delete:
                to_delete.add(child)
                queue.append(child)

    # Off the loop: see database.py on writing from async code.
    await asyncio.to_thread(db.delete_checkpoint_data, thread_id, to_delete)
    return len(to_delete)


async def search_thread(graph_app, thread_id: str, query: str, limit: int = SEARCH_LIMIT) -> List[Dict[str, Any]]:
    """Messages on any branch of the thread containing ``query`` (case
    insensitive, at least two characters), each with an excerpt and the
    checkpoint to open. Summaries and synthesis prompts are not searched.

    A message sits at the end of several checkpoints (LangGraph writes a few
    per turn); the result is the first, which is the tree's node for it, so
    deleting it removes the whole turn."""
    if not query or len(query.strip()) < 2:
        return []
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
