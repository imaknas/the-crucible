"""Notes on a tree node: a branch name, a bookmark, and a summary of the
subtree below it, so a big tree can be read and moved around.

None of this is part of the conversation. A subtree summary is a helper
call (like a checklist's parts): it is stored on the node
(core/database node_notes) and shown when the subtree is collapsed; it is
never written into the thread, where the compaction policy and the path
readers would take it for a history summary.
"""

import asyncio
from collections import deque
from typing import Any, Dict, List, Optional

from app.core import database as db

NAME_MAX_CHARS = 80
# What one summary call reads at most; a bigger subtree keeps its first
# entries (closest to the node) and says how many it left out.
SUBTREE_CHAR_LIMIT = 200_000
ENTRY_CHAR_LIMIT = 6_000


def subtree_outline(nodes: List[Dict], edges: List[Dict], root: str) -> List[Dict[str, Any]]:
    """The node and everything below it, closest first: [{label, id,
    parent_label, role, author}]. ``nodes`` / ``edges`` are the
    tree's (history.thread_tree)."""
    by_id = {n["id"]: n for n in nodes}
    children: Dict[str, List[str]] = {}
    for e in edges:
        children.setdefault(e["source"], []).append(e["target"])
    labels: Dict[str, str] = {}
    out: List[Dict[str, Any]] = []
    queue = deque([(root, None)])
    while queue:
        node_id, parent = queue.popleft()
        if node_id in labels or node_id not in by_id:
            continue
        labels[node_id] = f"m{len(labels) + 1}"
        meta = by_id[node_id].get("metadata") or {}
        out.append({
            "label": labels[node_id],
            "id": node_id,
            "parent_label": labels.get(parent) if parent else None,
            "role": meta.get("role"),
            "author": "Person" if meta.get("role") == "user" else meta.get("model_name") or meta.get("active_peer"),
        })
        queue.extend((child, node_id) for child in children.get(node_id, []))
    return out


def subtree_request(entries: List[Dict[str, Any]], texts: Dict[str, str]) -> str:
    """The summarizer's prompt: every entry with its full text, labelled,
    saying which entry it replies to (entries replying to the same one are
    alternative branches)."""
    blocks, used, left_out = [], 0, 0
    for e in entries:
        if e["role"] not in ("user", "ai"):
            continue
        text = texts.get(e["id"], "").strip()
        if len(text) > ENTRY_CHAR_LIMIT:
            text = text[:ENTRY_CHAR_LIMIT] + " […]"
        block = f"[{e['label']}] {e['author'] or 'Assistant'}" + (
            f" (replies to {e['parent_label']})" if e["parent_label"] else ""
        ) + f":\n{text}"
        if used + len(block) > SUBTREE_CHAR_LIMIT:
            left_out += 1
            continue
        blocks.append(block)
        used += len(block)
    note = f"\n\n({left_out} later entries were left out for length.)" if left_out else ""
    return (
        "Below is one part of a branching conversation: a message and everything that branches from it. "
        "Each entry is labelled; \"replies to\" names the entry it follows, so entries that reply to the "
        "same one are alternative branches.\n\n"
        + "\n\n".join(blocks)
        + note
        + "\n\nWrite a summary someone can read instead of this part of the tree: what was asked, how the "
        "branches differ (name them by their models or what they tried), what each concluded, and what is "
        "still open. Keep names, numbers and decisions exactly as written. Add nothing that isn't there."
    )


async def _tree(graph_app, thread_id: str, node_id: str):
    from app.services.history import thread_tree

    data = await thread_tree(graph_app, thread_id)
    if not any(n["id"] == node_id for n in data["nodes"]):
        raise ValueError(f"Node {node_id} not found on thread {thread_id}.")
    return data


async def label_node(
    graph_app, thread_id: str, node_id: str, *, name: Optional[str] = None, bookmarked: Optional[bool] = None
) -> Dict[str, Any]:
    """Name a node (its branch) and/or bookmark it; an empty name clears
    it. Returns {thread_id, node_id, name, bookmarked}. ValueError for a
    node the tree lacks or a name over ``NAME_MAX_CHARS``."""
    await _tree(graph_app, thread_id, node_id)
    fields: Dict[str, Any] = {}
    if name is not None:
        name = " ".join(name.split())
        if len(name) > NAME_MAX_CHARS:
            raise ValueError(f"A branch name is at most {NAME_MAX_CHARS} characters.")
        fields["name"] = name or None
    if bookmarked is not None:
        fields["bookmarked"] = bookmarked
    note = await asyncio.to_thread(db.save_node_note, thread_id, node_id, **fields) or {}
    return {"thread_id": thread_id, "node_id": node_id, "name": note.get("name"),
            "bookmarked": bool(note.get("bookmarked"))}


async def summarize_subtree(
    graph_app, thread_id: str, node_id: str, *, model: Optional[str] = None, factory=None
) -> Dict[str, Any]:
    """Summarize a node and everything below it with the summarizer model
    (``model``, else ``graph.default_summarizer()``) and store it on the
    node. Returns {thread_id, node_id, summary, model, nodes}. One helper
    call; nothing is written to the thread. ValueError for an unknown node,
    a model without a key, or an empty reply."""
    from langchain_core.messages import HumanMessage

    from app.llm import model_factory_from
    from app.services.arena import resolve_models
    from app.services.graph import default_summarizer
    from app.services.recall import INTERNAL_TAG
    from app.services.tree import load_thread_states
    from app.utils.helpers import extract_text

    data = await _tree(graph_app, thread_id, node_id)
    entries = subtree_outline(data["nodes"], data["edges"], node_id)
    states = {s.config["configurable"]["checkpoint_id"]: s for s in await load_thread_states(graph_app, thread_id)}
    texts = {}
    for e in entries:
        messages = ((states.get(e["id"]) and states[e["id"]].values) or {}).get("messages") or []
        if messages:
            texts[e["id"]] = extract_text(messages[-1].content)
    if not any(texts.values()):
        raise ValueError("There is nothing to summarize below this node.")

    model = model or default_summarizer()
    resolve_models([model])
    config = {"configurable": {"model_factory": factory}} if factory else {}
    llm = model_factory_from(config).chat(model, {})
    response = await llm.ainvoke([HumanMessage(content=subtree_request(entries, texts))], config={"tags": [INTERNAL_TAG]})
    summary = extract_text(response.content).strip()
    if not summary:
        raise ValueError(f"{model} returned an empty summary.")
    count = sum(1 for e in entries if e["role"] in ("user", "ai"))
    await asyncio.to_thread(
        db.save_node_note, thread_id, node_id, summary=summary, summary_model=model, summary_nodes=count
    )
    return {"thread_id": thread_id, "node_id": node_id, "summary": summary, "model": model, "nodes": count}


async def clear_subtree_summary(graph_app, thread_id: str, node_id: str) -> None:
    """Forget a node's subtree summary (its name and bookmark stay)."""
    await _tree(graph_app, thread_id, node_id)
    await asyncio.to_thread(
        db.save_node_note, thread_id, node_id, summary=None, summary_model=None, summary_nodes=None
    )
