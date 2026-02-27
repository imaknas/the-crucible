from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import List, Optional

import db
from history_tree import build_history_tree

router = APIRouter(prefix="/history", tags=["history"])


class PositionUpdate(BaseModel):
    node_id: str
    x: float
    y: float


@router.get("/{thread_id}")
async def get_history(
    request: Request, thread_id: str, checkpoint_id: Optional[str] = None
):
    graph_app = request.app.state.graph_app

    # Use direct SQL scan to discover ALL checkpoints in this thread
    # This ensures we see parallel branches that aren't in a single lineage
    raw_graph = db.get_thread_checkpoint_graph(thread_id)
    all_checkpoint_ids = [row[0] for row in raw_graph]

    all_states = []
    for cid in all_checkpoint_ids:
        cfg = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": cid,
                "checkpoint_ns": "",
            }
        }
        state = await graph_app.aget_state(cfg)
        if state and state.values:
            all_states.append(state)

    if not all_states:
        return {"nodes": [], "edges": [], "current_checkpoint": None}

    # Identify the specific state the user is viewing
    active_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    if checkpoint_id:
        active_config["configurable"]["checkpoint_id"] = checkpoint_id
    active_state = await graph_app.aget_state(active_config)

    tree_data = build_history_tree(thread_id, all_states, active_state)

    return {
        "nodes": tree_data["nodes"],
        "edges": tree_data["edges"],
        "current_checkpoint": tree_data["current_checkpoint"],
        "messages": tree_data["messages"],
    }


@router.post("/{thread_id}/positions")
async def save_positions(thread_id: str, updates: List[PositionUpdate]):
    try:
        db.save_node_positions(thread_id, updates)
        return {"status": "ok"}
    except Exception as e:
        return {"error": str(e)}


@router.delete("/{thread_id}/checkpoints/{checkpoint_id}")
async def delete_checkpoint(request: Request, thread_id: str, checkpoint_id: str):
    try:
        graph_app = request.app.state.graph_app
        # Use a global SQL scan to build a complete parent->child map for the thread
        raw_graph = db.get_thread_checkpoint_graph(thread_id)

        child_map: dict[str, list[str]] = {}
        parent_map: dict[str, str] = {}
        for cid, pid in raw_graph:
            if pid:
                child_map.setdefault(pid, []).append(cid)
                parent_map[cid] = pid

        # 1. Identify "Sibling Clones" of the target node
        # We need to find nodes with the same parent and same content key
        target_state = await graph_app.aget_state(
            {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_id": checkpoint_id,
                    "checkpoint_ns": "",
                }
            }
        )
        if not target_state or not target_state.values:
            return {"status": "ok", "deleted_count": 0}

        from history_tree import get_content_key

        target_ckey = get_content_key(target_state)
        target_parent = parent_map.get(checkpoint_id)

        to_delete = {checkpoint_id}

        # Find all raw nodes that would be visually merged into this one
        for cid, pid in raw_graph:
            if pid == target_parent and cid != checkpoint_id:
                s_state = await graph_app.aget_state(
                    {
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_id": cid,
                            "checkpoint_ns": "",
                        }
                    }
                )
                if (
                    s_state
                    and s_state.values
                    and get_content_key(s_state) == target_ckey
                ):
                    to_delete.add(cid)

        # 2. Recursively find all descendants of all clones
        queue = list(to_delete)
        while queue:
            curr = queue.pop(0)
            for child in child_map.get(curr, []):
                if child not in to_delete:
                    to_delete.add(child)
                    queue.append(child)

        db.delete_checkpoint_data(thread_id, to_delete)
        return {"status": "ok", "deleted_count": len(to_delete)}
    except Exception as e:
        import traceback

        traceback.print_exc()
        return {"error": str(e)}


@router.get("/{thread_id}/search")
async def search_history(request: Request, thread_id: str, q: str):
    if not q or len(q.strip()) < 2:
        return {"results": []}

    query = q.lower()
    graph_app = request.app.state.graph_app

    # 1. Discover all checkpoints in the thread
    raw_graph = db.get_thread_checkpoint_graph(thread_id)
    all_checkpoint_ids = [row[0] for row in raw_graph]

    from history_tree import extract_text, get_checkpoint_role

    results = []
    seen_content = set()  # Deduplicate within search results

    for cid in all_checkpoint_ids:
        cfg = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": cid,
                "checkpoint_ns": "",
            }
        }
        state = await graph_app.aget_state(cfg)

        if not state or not state.values or "messages" not in state.values:
            continue

        m_list = state.values["messages"]
        if not m_list:
            continue

        last_msg = m_list[-1]

        # Extract content
        content = (
            getattr(last_msg, "content", "")
            if hasattr(last_msg, "content")
            else (
                last_msg.get("content", "")
                if isinstance(last_msg, dict)
                else str(last_msg)
            )
        )
        content_str = str(content)

        # Filter technical markers (summaries, synthesis prompts, remove operations)
        if (
            "PREVIOUS CONTEXT SUMMARY:" in content_str
            or "Please act as the Crucible Lead" in content_str
            or getattr(last_msg, "type", "") == "remove"
        ):
            continue

        text = extract_text(content)
        if not text.strip():
            continue

        # Match query
        if query in text.lower():
            # Deduplicate by (role, content_prefix) to avoid showing identical LangGraph intermediate steps
            role = get_checkpoint_role(state)
            dedup_key = (role, text[:200])
            if dedup_key in seen_content:
                continue
            seen_content.add(dedup_key)

            # Extract excerpt
            idx = text.lower().find(query)
            start = max(0, idx - 40)
            end = min(len(text), idx + len(q) + 60)
            excerpt = (
                ("..." if start > 0 else "")
                + text[start:end]
                + ("..." if end < len(text) else "")
            )

            results.append(
                {
                    "checkpoint_id": cid,
                    "role": role,
                    "model": getattr(last_msg, "name", None)
                    or (last_msg.get("name") if isinstance(last_msg, dict) else None),
                    "excerpt": excerpt,
                    "timestamp": getattr(state, "created_at", None),  # If available
                }
            )

    # Limit to top 20 results for performance
    return {"results": results[:20]}
