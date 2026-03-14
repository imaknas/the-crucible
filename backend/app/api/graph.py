from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from pydantic import BaseModel
from langchain_core.runnables import RunnableConfig

from app.core import database as db
from app.services.graph import workflow
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

router = APIRouter(prefix="/graph", tags=["graph"])


class GraphTopology(BaseModel):
    thread_id: str
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]


@router.get("/{thread_id}/topology", response_model=GraphTopology)
async def get_graph_topology(thread_id: str):
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

        async with AsyncSqliteSaver.from_conn_string(db.DB_PATH) as saver:
            graph_app = workflow.compile(checkpointer=saver)

            for cid, parent_cid in raw_edges:
                if cid not in seen_nodes:
                    # Load state to get metadata
                    config: RunnableConfig = {
                        "configurable": {"thread_id": thread_id, "checkpoint_id": cid}
                    }
                    state = await graph_app.aget_state(config)
                    metadata = {}
                    if state.values and state.values.get("messages"):
                        last_msg = state.values["messages"][-1]
                        # Use internal property extraction
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
                            # Re-run extraction if it missed it (robustness)
                            import re

                            conf_match = re.search(
                                r"confidence:\s*(\d+)%", str(content_text).lower()
                            )
                            if conf_match:
                                metadata["confidence"] = (
                                    int(conf_match.group(1)) / 100.0
                                )

                    nodes.append(
                        {"id": cid, "label": f"Node {cid[:8]}", "metadata": metadata}
                    )
                    seen_nodes.add(cid)

                if parent_cid and parent_cid not in seen_nodes:
                    # (Similar logic for parent, though usually it will be found as a cid)
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
async def get_node_path(thread_id: str, checkpoint_id: str):
    """
    Returns the complete message history from the root to a specific checkpoint.
    """
    try:
        async with AsyncSqliteSaver.from_conn_string(db.DB_PATH) as saver:
            graph_app = workflow.compile(checkpointer=saver)
            config: RunnableConfig = {
                "configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}
            }
            state = await graph_app.aget_state(config)

            if not state.values:
                raise HTTPException(status_code=404, detail="Checkpoint not found")

            # Reuse existing formatter
            from app.services.tree import format_messages

            # Get full path states
            all_states = []
            curr_config = config
            while curr_config.get("configurable", {}).get("checkpoint_id"):
                curr_state = await graph_app.aget_state(curr_config)
                if not curr_state.values:
                    break
                all_states.insert(0, curr_state)
                # Actually, aget_state_history is better for this
                break  # Simplified for now, we'll refine

            # Fallback: using aget_state_history
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

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
