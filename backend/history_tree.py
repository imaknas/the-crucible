from typing import List, Dict, Optional, Any, Set, Tuple
from db import load_node_positions
from utils import extract_text


def get_checkpoint_role(state_obj) -> str:
    m_list = state_obj.values.get("messages", [])
    if not m_list:
        return "system"
    last = m_list[-1]
    if hasattr(last, "type"):
        return "user" if last.type == "human" else "assistant"
    elif isinstance(last, dict):
        return (
            "user"
            if last.get("role") == "user" or last.get("type") == "human"
            else "assistant"
        )
    return "assistant"


def get_content_key(state_obj) -> str:
    m_list = state_obj.values.get("messages", [])
    if not m_list:
        return "EMPTY"
    last = m_list[-1]
    if hasattr(last, "content"):
        content = last.content
    elif isinstance(last, dict):
        content = last.get("content", "")
    else:
        content = str(last)

    extracted = extract_text(content)
    role = get_checkpoint_role(state_obj)
    return f"{len(m_list)}|{role}|{extracted}"


# ─── Step 1: Build Parent-Child Graph ─────────────────────────────


def build_graph_structure(all_states: List[Any]) -> Tuple[Dict, Dict, List[str]]:
    """Returns (child_map, state_map, roots)."""
    child_map: Dict[str, List[str]] = {}
    state_map: Dict[str, Any] = {}
    roots = []

    for state in all_states:
        cp_id = state.config["configurable"]["checkpoint_id"]
        state_map[cp_id] = state
        parent_id = (
            state.parent_config["configurable"]["checkpoint_id"]
            if state.parent_config
            else None
        )
        if parent_id:
            child_map.setdefault(parent_id, []).append(cp_id)
        else:
            roots.append(cp_id)

    return child_map, state_map, roots


# ─── Step 2: Deduplicate Checkpoints ─────────────────────────────


def deduplicate_checkpoints(
    roots: List[str], child_map: Dict, state_map: Dict
) -> Tuple[Dict[str, str], Set[str]]:
    """Returns (id_to_vis mapping, significant_ids set)."""
    id_to_vis: Dict[str, str] = {}
    # Track (parent_vis_id, content_key) -> first_vis_id to merge siblings
    merged_siblings: Dict[Tuple[Optional[str], str], str] = {}

    # Process nodes in topological order using BFS to avoid KeyError
    queue = list(roots)
    processed = set()

    while queue:
        cp_id = queue.pop(0)
        if cp_id in processed:
            continue
        processed.add(cp_id)

        state = state_map[cp_id]
        parent_id = (
            state.parent_config["configurable"]["checkpoint_id"]
            if state.parent_config
            else None
        )
        p_vis = id_to_vis.get(parent_id) if parent_id else None

        content_key = get_content_key(state)
        merge_key = (p_vis, content_key)

        if merge_key in merged_siblings:
            # COLLAPSE SIBLINGS: If a sibling with same content and parent already exists
            id_to_vis[cp_id] = merged_siblings[merge_key]
        elif p_vis and content_key == get_content_key(state_map[p_vis]):
            # COLLAPSE INTO PARENT: Standard LangGraph redundancy
            id_to_vis[cp_id] = p_vis
        else:
            # Distinct node
            id_to_vis[cp_id] = cp_id
            merged_siblings[merge_key] = cp_id

        for child in child_map.get(cp_id, []):
            queue.append(child)

    significant_ids = set(id_to_vis.values())

    # Handle branch points: a node is significant if it has >1 distinct VISUAL child
    # We must collect children from ALL raw nodes that were merged into the vis_id
    vis_child_map: Dict[str, Set[str]] = {}
    for cp_id, vis_id in id_to_vis.items():
        for raw_child in child_map.get(cp_id, []):
            child_vis = id_to_vis.get(raw_child)
            if child_vis and child_vis != vis_id:
                vis_child_map.setdefault(vis_id, set()).add(child_vis)

    # FINAL PASS: Filter out technical synthesis prompts from significant_ids
    # We want them to be "pass-through" nodes so the AI result attaches to the parent
    synthesis_ids = set()
    for vis_id in significant_ids:
        state = state_map[vis_id]
        m_list = state.values.get("messages", [])
        if m_list:
            last = m_list[-1]
            content = ""
            if hasattr(last, "content"):
                content = last.content
            elif isinstance(last, dict):
                content = last.get("content", "")

            if (
                content
                and "Please act as the Crucible Lead. Synthesize these viewpoints"
                in content
            ):
                synthesis_ids.add(vis_id)

    significant_ids = significant_ids - synthesis_ids

    # 3. Filter out technical Summarization nodes
    # These are usually created by the system to compress memory and don't represent a user/AI turn
    summary_ids = set()
    for vis_id in significant_ids:
        state = state_map[vis_id]
        m_list = state.values.get("messages", [])
        if m_list:
            last = m_list[-1]
            content = ""
            if hasattr(last, "content"):
                content = last.content
            elif isinstance(last, dict):
                content = last.get("content", "")

            if content and "PREVIOUS CONTEXT SUMMARY:" in content:
                summary_ids.add(vis_id)

    significant_ids = significant_ids - summary_ids

    return id_to_vis, significant_ids


# ─── Step 3: Layout Nodes & Edges ────────────────────────────────


def build_graph_layout(
    id_to_vis: Dict[str, str],
    roots: List[str],
    child_map: Dict,
    state_map: Dict,
    significant_ids: Set[str],
    saved_positions: Dict,
) -> Tuple[List[Dict], List[Dict]]:
    """Returns (nodes, edges)."""
    nodes: List[Dict] = []
    edges: List[Dict] = []
    level_counts: Dict[int, int] = {}

    # 1. Build the visual graph (vis_id -> set of visual children)
    vis_child_map: Dict[str, Set[str]] = {}
    vis_parent_map: Dict[str, Optional[str]] = {}
    vis_roots = set()

    for cp_id, vis_id in id_to_vis.items():
        state = state_map[cp_id]
        parent_id = (
            state.parent_config["configurable"]["checkpoint_id"]
            if state.parent_config
            else None
        )
        p_vis = id_to_vis.get(parent_id) if parent_id else None

        if p_vis and p_vis != vis_id:
            vis_child_map.setdefault(p_vis, set()).add(vis_id)
            vis_parent_map[vis_id] = p_vis
        elif not p_vis:
            vis_roots.add(vis_id)

    # Filter significant nodes that we actually want to render
    # A node is kept if it is in significant_ids
    # We also keep roots and leaves automatically by logic

    laid_out = set()

    def layout_vis_node(v_id: str, level: int = 0):
        if v_id in laid_out:
            return

        if v_id not in significant_ids:
            # Pass through: don't render this visual node, but layout its visual children
            for child_v_id in vis_child_map.get(v_id, []):
                layout_vis_node(child_v_id, level)
            return

        laid_out.add(v_id)

        if v_id in saved_positions:
            pos = saved_positions[v_id]
        else:
            y = level * 140
            x_idx = level_counts.get(level, 0)
            level_counts[level] = x_idx + 1
            x = x_idx * 240
            pos = {"x": x, "y": y}

        state = state_map[v_id]
        role = get_checkpoint_role(state)
        visual_role = "ai" if role == "assistant" else role

        last_msg_obj = (
            state.values.get("messages", [])[-1]
            if state.values.get("messages")
            else None
        )
        if last_msg_obj:
            raw_content = (
                last_msg_obj.content
                if hasattr(last_msg_obj, "content")
                else last_msg_obj.get("content", "")
                if isinstance(last_msg_obj, dict)
                else str(last_msg_obj)
            )
            content = extract_text(raw_content)

            # Detect synthesis prompts and use a cleaner label
            if (
                content
                and "Please act as the Crucible Lead. Synthesize these viewpoints"
                in content
            ):
                display_label = "Consensus Convergence"
            else:
                display_label = content[:30] + "..." if content else ""
        else:
            display_label = ""

        nodes.append(
            {
                "id": v_id,
                "data": {"label": display_label or "Start"},
                "position": pos,
                "metadata": {
                    "role": visual_role,
                    "active_peer": state.values.get("active_peer"),
                    "thesis_preview": state.values.get("current_thesis", "")[:50],
                },
            }
        )

        # Find nearest significant visual ancestor for edge creation
        curr = vis_parent_map.get(v_id)
        while curr and curr not in significant_ids:
            curr = vis_parent_map.get(curr)

        if curr:
            edges.append(
                {
                    "id": f"e-{curr}-{v_id}",
                    "source": curr,
                    "target": v_id,
                }
            )

        for child_v_id in vis_child_map.get(v_id, []):
            layout_vis_node(child_v_id, level + 1)

    for r_v_id in vis_roots:
        layout_vis_node(r_v_id)

    # Center nodes if no saved positions
    if not saved_positions:
        for level, total in level_counts.items():
            offset = (total - 1) * 220 / 2
            for node in nodes:
                if node["position"]["y"] == level * 140:
                    node["position"]["x"] -= offset

    return nodes, edges


# ─── Step 4: Format Messages ─────────────────────────────────────


def format_messages(active_state_id: str, state_map: Dict) -> List[Dict]:
    """
    Graph-Path Reconstruction: Walks backwards from the active checkpoint
    to the root, collecting the last (unique) message from each node.
    This bypasses any state-level summarization truncation.
    """
    path_messages = []
    seen_keys = set()
    curr_id = active_state_id

    while curr_id in state_map:
        state = state_map[curr_id]
        m_list = state.values.get("messages", [])

        if m_list:
            msg = m_list[-1]

            # 1. Identify role
            role = "user"
            if hasattr(msg, "type"):
                role = "user" if msg.type == "human" else "assistant"
            elif isinstance(msg, dict):
                role = msg.get("role") or (
                    "user" if msg.get("type") == "human" else "assistant"
                )

            # 2. Extract content
            content = (
                getattr(msg, "content", "")
                if hasattr(msg, "content")
                else (msg.get("content", "") if isinstance(msg, dict) else str(msg))
            )
            content_str = str(content)

            # 3. Filter technical markers
            is_technical = (
                "PREVIOUS CONTEXT SUMMARY:" in content_str
                or "Please act as the Crucible Lead" in content_str
                or getattr(msg, "type", "") == "remove"
            )

            if not is_technical and content_str.strip():
                # 4. Deduplicate (LangGraph creates multiple checkpoints per turn)
                text = extract_text(content)
                key = (role, text[:200])  # Use prefix for speed
                if key not in seen_keys:
                    # 5. Heavy Duty Attribution Recovery
                    msg_model = None
                    msg_model = getattr(msg, "name", None)
                    if not msg_model and hasattr(msg, "additional_kwargs"):
                        add_kwargs = getattr(msg, "additional_kwargs", {})
                        if isinstance(add_kwargs, dict):
                            msg_model = add_kwargs.get(
                                "model", add_kwargs.get("model_id")
                            ) or add_kwargs.get("name")
                    if not msg_model and hasattr(msg, "response_metadata"):
                        resp_meta = getattr(msg, "response_metadata", {})
                        if isinstance(resp_meta, dict):
                            msg_model = resp_meta.get(
                                "model_name", resp_meta.get("model_id")
                            ) or resp_meta.get("model")
                    if not msg_model and isinstance(msg, dict):
                        msg_model = (
                            msg.get("name")
                            or msg.get("model")
                            or msg.get("additional_kwargs", {}).get("model_id")
                            or msg.get("metadata", {}).get("active_peer")
                        )
                    if not msg_model and role == "assistant":
                        msg_model = (state.values or {}).get("active_peer")

                    if not msg_model:
                        msg_model = "assistant" if role == "assistant" else "user"

                    path_messages.append(
                        {
                            "role": role,
                            "content": text,
                            "type": role,
                            "model": msg_model,
                        }
                    )
                    seen_keys.add(key)

        # Move up
        curr_id = (
            state.parent_config["configurable"]["checkpoint_id"]
            if state.parent_config
            else None
        )

    # Return in chronological order
    return list(reversed(path_messages))


# ─── Orchestrator ─────────────────────────────────────────────────


def build_history_tree(
    thread_id: str,
    all_states: List[Any],
    active_state: Any,
    vis_active_id_override: Optional[str] = None,
) -> Dict:
    child_map, state_map, roots = build_graph_structure(all_states)
    id_to_vis, significant_ids = deduplicate_checkpoints(roots, child_map, state_map)
    saved_positions = load_node_positions(thread_id)
    nodes, edges = build_graph_layout(
        id_to_vis, roots, child_map, state_map, significant_ids, saved_positions
    )

    # NEW: Reconstruct history from graph path
    active_id = active_state.config.get("configurable", {}).get("checkpoint_id")
    messages = format_messages(active_id, state_map)

    vis_active_id = id_to_vis.get(active_id, active_id) if active_id else None

    return {
        "nodes": nodes,
        "edges": edges,
        "current_checkpoint": vis_active_id,
        "messages": messages,
        "state_map": state_map,
        "child_map": child_map,
    }
