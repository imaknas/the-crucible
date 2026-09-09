import asyncio
from collections import deque
from typing import List, Dict, Optional, Any, Set, Tuple
from app.core import database as db
from app.core.database import load_node_positions
from app.api.models import display_name
from app.utils.helpers import extract_text, get_preview_text


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


# ─── Step 0: Load Checkpoint States ──────────────────────────────


async def load_thread_states(graph_app, thread_id: str) -> List[Any]:
    """
    Load every checkpoint state for a thread.

    ``aget_state_history`` walks the whole thread in a single saver pass. The
    previous approach issued one ``aget_state`` per checkpoint, and LangGraph
    writes 4-6 checkpoints per turn — so a long thread meant hundreds of round
    trips, repeated on every node click and on every debate-tree poll.

    Anything the history walk does not surface (parallel branches outside the
    main lineage) is still fetched individually, so coverage is unchanged.
    """
    known_ids = {row[0] for row in db.get_thread_checkpoint_graph(thread_id)}
    states: List[Any] = []
    seen: Set[str] = set()

    cfg = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        async for snapshot in graph_app.aget_state_history(cfg):
            if not snapshot or not snapshot.values:
                continue
            cid = snapshot.config.get("configurable", {}).get("checkpoint_id")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            states.append(snapshot)
    except Exception:
        states, seen = [], set()

    missing = [cid for cid in known_ids if cid not in seen]
    if missing:

        async def _one(cid: str):
            try:
                return await graph_app.aget_state(
                    {
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_id": cid,
                            "checkpoint_ns": "",
                        }
                    }
                )
            except Exception:
                return None

        for extra in await asyncio.gather(*[_one(cid) for cid in missing]):
            if extra and extra.values:
                states.append(extra)

    return states


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
    queue = deque(roots)
    processed = set()

    while queue:
        cp_id = queue.popleft()
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
        elif (
            p_vis
            and p_vis in state_map
            and content_key == get_content_key(state_map[p_vis])
        ):
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

# Layout constants. NODE_SPACING_X must stay wider than the frontend's rendered
# node width (220px) so neighbouring columns never touch.
NODE_SPACING_X = 260
LEVEL_HEIGHT_Y = 150
ROOT_GAP_X = 120


def build_significant_forest(
    id_to_vis: Dict[str, str],
    state_map: Dict,
    significant_ids: Set[str],
) -> Tuple[Dict[str, List[str]], Dict[str, Optional[str]], List[str]]:
    """
    Collapse the raw visual graph down to significant nodes only.

    Non-significant nodes (synthesis prompts, summarisation checkpoints) become
    pass-throughs: their children are re-parented onto the nearest significant
    ancestor. Child lists are sorted — checkpoint IDs are monotonic, so this
    yields chronological order and a layout that is stable across refetches.

    Returns (children, parents, roots) over significant IDs only.
    """
    raw_children: Dict[str, Set[str]] = {}
    raw_parent: Dict[str, Optional[str]] = {}

    for cp_id, vis_id in id_to_vis.items():
        state = state_map[cp_id]
        parent_id = (
            state.parent_config["configurable"]["checkpoint_id"]
            if state.parent_config
            else None
        )
        p_vis = id_to_vis.get(parent_id) if parent_id else None
        if p_vis and p_vis != vis_id:
            raw_children.setdefault(p_vis, set()).add(vis_id)
            raw_parent.setdefault(vis_id, p_vis)

    def nearest_significant_ancestor(v_id: str) -> Optional[str]:
        seen = {v_id}
        curr = raw_parent.get(v_id)
        while curr is not None and curr not in significant_ids:
            if curr in seen:  # defensive: never loop on malformed parent links
                return None
            seen.add(curr)
            curr = raw_parent.get(curr)
        return curr

    children: Dict[str, List[str]] = {}
    parents: Dict[str, Optional[str]] = {}
    roots: List[str] = []

    for v_id in sorted(significant_ids):
        ancestor = nearest_significant_ancestor(v_id)
        parents[v_id] = ancestor
        if ancestor is None:
            roots.append(v_id)
        else:
            children.setdefault(ancestor, []).append(v_id)

    for kids in children.values():
        kids.sort()

    return children, parents, roots


def tidy_tree_layout(
    roots: List[str], children: Dict[str, List[str]]
) -> Dict[str, Dict[str, int]]:
    """
    Reingold-Tilford style layout: every leaf gets its own column and every
    parent is centred over its children.

    This replaces the old per-level grid, which packed each depth independently
    and therefore interleaved siblings from different parents — the cause of the
    crossing edges whenever a thread had more than one branch.
    """
    positions: Dict[str, Dict[str, int]] = {}
    cols: Dict[str, float] = {}
    next_leaf_col = 0.0

    for root in roots:
        # Iterative post-order: a long linear thread must not blow the stack.
        stack: List[Tuple[str, int, bool]] = [(root, 0, False)]
        while stack:
            v_id, depth, expanded = stack.pop()
            kids = children.get(v_id, [])
            if kids and not expanded:
                stack.append((v_id, depth, True))
                for kid in reversed(kids):
                    stack.append((kid, depth + 1, False))
                continue
            if kids:
                col = (cols[kids[0]] + cols[kids[-1]]) / 2
            else:
                col = next_leaf_col
                next_leaf_col += 1.0
            cols[v_id] = col
            positions[v_id] = {
                "x": int(round(col * NODE_SPACING_X)),
                "y": depth * LEVEL_HEIGHT_Y,
            }
        # Gutter between independent roots
        next_leaf_col += ROOT_GAP_X / NODE_SPACING_X

    return positions


def _node_content(state) -> Tuple[str, str, bool]:
    """Returns (extracted_text, raw_content_as_str, has_thoughts)."""
    m_list = state.values.get("messages", [])
    if not m_list:
        return "", "", False
    last = m_list[-1]
    if hasattr(last, "content"):
        raw = last.content
    elif isinstance(last, dict):
        raw = last.get("content", "")
    else:
        raw = str(last)
    has_thoughts = "<think>" in raw if isinstance(raw, str) else False
    return extract_text(raw), raw if isinstance(raw, str) else "", has_thoughts


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

    children, parents, forest_roots = build_significant_forest(
        id_to_vis, state_map, significant_ids
    )
    positions = tidy_tree_layout(forest_roots, children)

    for v_id in sorted(significant_ids):
        state = state_map.get(v_id)
        if state is None:
            continue

        # A position the user dragged always wins; the computed layout is only
        # the default. Because layout is computed independently of iteration
        # order, one pinned node no longer shifts its siblings.
        pos = saved_positions.get(v_id) or positions.get(v_id) or {"x": 0, "y": 0}

        role = get_checkpoint_role(state)
        visual_role = "ai" if role == "assistant" else role
        content, _raw, has_thoughts = _node_content(state)

        if content and "Please act as the Crucible Lead. Synthesize these viewpoints" in content:
            display_label = "Consensus Convergence"
        else:
            display_label = get_preview_text(content, max_length=40)

        nodes.append(
            {
                "id": v_id,
                "data": {"label": display_label or "Start"},
                "position": pos,
                "metadata": {
                    "role": visual_role,
                    "active_peer": state.values.get("active_peer")
                    if visual_role == "ai"
                    else None,
                    "model_name": display_name(state.values.get("active_peer"))
                    if visual_role == "ai"
                    else None,
                    "thesis_preview": state.values.get("current_thesis", "")[:50],
                    "has_thoughts": has_thoughts,
                    # Longer excerpt, revealed when the node is selected
                    "preview": get_preview_text(content, max_length=400),
                },
            }
        )

        parent = parents.get(v_id)
        if parent:
            edges.append({"id": f"e-{parent}-{v_id}", "source": parent, "target": v_id})

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
                text = extract_text(content, wrap_thinking=True)
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

                    sources = None
                    if hasattr(msg, "additional_kwargs"):
                        sources = getattr(msg, "additional_kwargs", {}).get("sources")
                    if not sources and isinstance(msg, dict):
                        sources = msg.get("additional_kwargs", {}).get("sources")

                    path_messages.append(
                        {
                            "role": role,
                            "content": text,
                            "type": role,
                            "model": msg_model,
                            "sources": sources,
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


# ─── Debate Tree ──────────────────────────────────────────────────

# Kept in sync with the frontend (useDebateTree.addPendingNode / TreeCanvas
# lane headers) so optimistic pending nodes land exactly where the real node
# will appear once the round is persisted.
LANE_WIDTH = 300
ROUND_HEIGHT = 160
SYNTHESIS_GAP = 140
PROMPT_NODE_ID = "debate::prompt"


def build_single_thread_for_debate(
    model_id: str,
    all_states: List[Any],
    lane_index: int,
    model_color: str = "#6366f1",
) -> Tuple[List[Dict], List[Dict], str]:
    """
    Build namespaced nodes and edges for one model's lane in debate mode.

    Only AI responses become lane nodes. Each round also writes a human
    checkpoint (round 0 the original prompt, round 1+ a long generated
    cross-examination prompt); rendering those in every lane both duplicated
    the question N times and made `round_num` count checkpoint depth rather
    than debate rounds, which put optimistic pending nodes on top of real ones.

    Node IDs are prefixed: "{model_id}::{checkpoint_id}".
    Returns (nodes, edges, root_prompt_text).
    """
    if not all_states:
        return [], [], ""

    child_map, state_map, roots = build_graph_structure(all_states)
    id_to_vis, significant_ids = deduplicate_checkpoints(roots, child_map, state_map)
    children, _parents, forest_roots = build_significant_forest(
        id_to_vis, state_map, significant_ids
    )

    nodes: List[Dict] = []
    edges: List[Dict] = []
    root_prompt = ""

    for forest_root in forest_roots:
        # (vis_id, round_num, last emitted namespaced node id)
        stack: List[Tuple[str, int, Optional[str]]] = [(forest_root, 0, None)]
        while stack:
            v_id, round_num, prev_node_id = stack.pop()
            state = state_map.get(v_id)
            if state is None:
                continue

            role = get_checkpoint_role(state)
            content, _raw, _ = _node_content(state)

            if role != "assistant":
                # Prompt checkpoint: not rendered in the lane, but the very
                # first one is the debate question shown above all lanes.
                if not root_prompt and content:
                    root_prompt = content
                for kid in reversed(children.get(v_id, [])):
                    stack.append((kid, round_num, prev_node_id))
                continue

            namespaced_id = f"{model_id}::{v_id}"
            nodes.append(
                {
                    "id": namespaced_id,
                    "data": {"label": get_preview_text(content, max_length=40) or "…"},
                    "position": {
                        "x": lane_index * LANE_WIDTH,
                        "y": round_num * ROUND_HEIGHT,
                    },
                    "metadata": {
                        "role": "ai",
                        "active_peer": model_id,
                        "model_name": display_name(model_id),
                        "lane_index": lane_index,
                        "round_num": round_num,
                        "model_color": model_color,
                        "preview": get_preview_text(content, max_length=400),
                    },
                }
            )
            if prev_node_id:
                edges.append(
                    {
                        "id": f"e-{prev_node_id}-{namespaced_id}",
                        "source": prev_node_id,
                        "target": namespaced_id,
                    }
                )

            for kid in reversed(children.get(v_id, [])):
                stack.append((kid, round_num + 1, namespaced_id))

    return nodes, edges, root_prompt


def build_debate_tree(
    session: Dict[str, Any],
    all_thread_states: Dict[str, List[Any]],
    synthesis_states: List[Any],
    family_colors: Dict[str, str],
) -> Dict[str, Any]:
    """
    Merge all model lanes + the shared prompt + synthesis into one React Flow
    graph. Returns { nodes, edges, lanes, session_metadata }.
    """
    participants = session["participants"]
    all_nodes: List[Dict] = []
    all_edges: List[Dict] = []
    lanes = []
    max_round = 0
    debate_prompt = ""

    first_node_per_model: Dict[str, str] = {}
    last_node_per_model: Dict[str, str] = {}

    for lane_idx, model_id in enumerate(participants):
        color = family_colors.get(model_id, "#6366f1")
        nodes, edges, prompt_text = build_single_thread_for_debate(
            model_id, all_thread_states.get(model_id, []), lane_idx, color
        )
        all_nodes.extend(nodes)
        all_edges.extend(edges)
        lanes.append(
            {
                "model_id": model_id,
                "label": display_name(model_id),
                "lane_index": lane_idx,
                "color": color,
            }
        )
        if prompt_text and not debate_prompt:
            debate_prompt = prompt_text

        if nodes:
            first_node_per_model[model_id] = min(
                nodes, key=lambda n: n["metadata"]["round_num"]
            )["id"]
            last = max(nodes, key=lambda n: n["metadata"]["round_num"])
            last_node_per_model[model_id] = last["id"]
            max_round = max(max_round, last["metadata"]["round_num"])

    lane_center_x = int(((len(participants) - 1) / 2) * LANE_WIDTH)

    # Shared prompt node above every lane, so the question is stated once.
    if debate_prompt and first_node_per_model:
        all_nodes.append(
            {
                "id": PROMPT_NODE_ID,
                "data": {"label": get_preview_text(debate_prompt, max_length=60)},
                "position": {"x": lane_center_x, "y": -ROUND_HEIGHT},
                "metadata": {
                    "role": "user",
                    "round_num": -1,
                    "preview": get_preview_text(debate_prompt, max_length=400),
                },
            }
        )
        for model_id, first_id in first_node_per_model.items():
            all_edges.append(
                {
                    "id": f"e-prompt-{model_id}",
                    "source": PROMPT_NODE_ID,
                    "target": first_id,
                }
            )

    synthesis_y = (max_round + 1) * ROUND_HEIGHT + SYNTHESIS_GAP

    if synthesis_states:
        syn_model = session.get("synthesizer_model", "synthesis")
        syn_color = family_colors.get(syn_model, "#8b5cf6")
        syn_nodes, syn_edges, _ = build_single_thread_for_debate(
            "synthesis", synthesis_states, lane_index=0, model_color=syn_color
        )
        for n in syn_nodes:
            n["position"]["x"] = lane_center_x
            n["position"]["y"] = synthesis_y + n["metadata"]["round_num"] * ROUND_HEIGHT
            n["type"] = "synthesis"
            n["metadata"]["role"] = "synthesis"
        all_nodes.extend(syn_nodes)
        all_edges.extend(syn_edges)

        if syn_nodes:
            syn_root = min(syn_nodes, key=lambda n: n["metadata"]["round_num"])
            for model_id, last_node_id in last_node_per_model.items():
                all_edges.append(
                    {
                        "id": f"e-synthesis-{model_id}",
                        "source": last_node_id,
                        "target": syn_root["id"],
                        "type": "synthesis_edge",
                    }
                )
    elif last_node_per_model:
        all_nodes.append(
            {
                "id": "synthesis::pending",
                "type": "synthesis",
                "data": {"label": "Synthesis pending..."},
                "position": {"x": lane_center_x, "y": synthesis_y},
                "metadata": {"role": "synthesis", "pending": True},
            }
        )
        for model_id, last_node_id in last_node_per_model.items():
            all_edges.append(
                {
                    "id": f"e-synthesis-{model_id}",
                    "source": last_node_id,
                    "target": "synthesis::pending",
                    "type": "synthesis_edge",
                }
            )

    return {
        "nodes": all_nodes,
        "edges": all_edges,
        "lanes": lanes,
        "session_metadata": {
            "session_id": session["session_id"],
            "status": session.get("status", "running"),
            "current_round": session.get("current_round", 0),
            # Per-round convergence, keyed by round number as a string.
            "round_scores": session.get("round_scores", {}),
            "max_round": max_round,
        },
    }


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
