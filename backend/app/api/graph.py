from fastapi import APIRouter, HTTPException, Request
from typing import List, Dict, Any
from pydantic import BaseModel
from langchain_core.runnables import RunnableConfig

from app.core import database as db

router = APIRouter(prefix="/graph", tags=["graph"])


class GraphTopology(BaseModel):
    thread_id: str
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]


@router.get("/{thread_id}/topology", response_model=GraphTopology)
async def get_graph_topology(request: Request, thread_id: str):
    """
    Returns the topological structure of a conversation thread.
    Useful for agents to identify branch points, leaf nodes, and consensus areas.
    """
    try:
        raw_edges = db.get_thread_checkpoint_graph(thread_id)
        if not raw_edges:
            return GraphTopology(thread_id=thread_id, nodes=[], edges=[])

        nodes = []
        edges = []
        seen_nodes = set()

        graph_app = request.app.state.graph_app

        for cid, parent_cid in raw_edges:
            if cid not in seen_nodes:
                config: RunnableConfig = {
                    "configurable": {"thread_id": thread_id, "checkpoint_id": cid}
                }
                state = await graph_app.aget_state(config)
                metadata = {}
                if state.values and state.values.get("messages"):
                    last_msg = state.values["messages"][-1]
                    add_kwargs = {}
                    if hasattr(last_msg, "additional_kwargs"):
                        add_kwargs = last_msg.additional_kwargs
                    elif isinstance(last_msg, dict):
                        add_kwargs = last_msg.get("additional_kwargs", {})

                    metadata["confidence"] = add_kwargs.get("confidence")
                    metadata["conflict"] = add_kwargs.get("conflict")

                    content_text = getattr(last_msg, "content", None)
                    if content_text is None:
                        content_text = (
                            last_msg.get("content", "")
                            if isinstance(last_msg, dict)
                            else str(last_msg)
                        )

                    if (
                        metadata["confidence"] is None
                        and "confidence" in str(content_text).lower()
                    ):
                        import re

                        conf_match = re.search(
                            r"confidence:\s*(\d+)%", str(content_text).lower()
                        )
                        if conf_match:
                            metadata["confidence"] = int(conf_match.group(1)) / 100.0

                nodes.append(
                    {"id": cid, "label": f"Node {cid[:8]}", "metadata": metadata}
                )
                seen_nodes.add(cid)

            if parent_cid and parent_cid not in seen_nodes:
                nodes.append(
                    {
                        "id": parent_cid,
                        "label": f"Node {parent_cid[:8]}",
                        "metadata": {},
                    }
                )
                seen_nodes.add(parent_cid)

            if parent_cid:
                edges.append({"source": parent_cid, "target": cid})

        return GraphTopology(thread_id=thread_id, nodes=nodes, edges=edges)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{thread_id}/path/{checkpoint_id}")
async def get_node_path(request: Request, thread_id: str, checkpoint_id: str):
    """
    Returns the complete message history from the root to a specific checkpoint.
    """
    try:
        graph_app = request.app.state.graph_app
        config: RunnableConfig = {
            "configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}
        }
        state = await graph_app.aget_state(config)

        if not state.values:
            raise HTTPException(status_code=404, detail="Checkpoint not found")

        from app.services.tree import format_messages

        history_states = []
        async for s in graph_app.aget_state_history(config):
            history_states.append(s)

        state_map = {
            s.config["configurable"]["checkpoint_id"]: s for s in history_states
        }
        formatted = format_messages(checkpoint_id, state_map)
        return {
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id,
            "messages": formatted,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
