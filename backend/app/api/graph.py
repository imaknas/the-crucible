from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any
from pydantic import BaseModel

from app.core import database as db
from app.api.deps import get_graph_app
from app.services import history

router = APIRouter(prefix="/graph", tags=["graph"])


class GraphTopology(BaseModel):
    thread_id: str
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]


@router.get("/{thread_id}/topology", response_model=GraphTopology)
async def get_graph_topology(thread_id: str, _graph_app=Depends(get_graph_app)):
    """
    Returns the topological structure of a conversation thread.
    Useful for agents to identify branch points, leaf nodes, and consensus areas.

    It reads the checkpoint tables directly; the graph dependency stays so the
    route answers 503 until the lifespan has set those tables up. Each node's
    `metadata` is empty: it used to carry a self-reported confidence and a
    keyword "conflict" flag, which models are no longer asked for.
    """
    try:
        raw_edges = db.get_thread_checkpoint_graph(thread_id)
        if not raw_edges:
            return GraphTopology(thread_id=thread_id, nodes=[], edges=[])

        nodes = []
        edges = []
        seen_nodes = set()

        for cid, parent_cid in raw_edges:
            if cid not in seen_nodes:
                nodes.append(
                    {"id": cid, "label": f"Node {cid[:8]}", "metadata": {}}
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
async def get_node_path(thread_id: str, checkpoint_id: str, graph_app=Depends(get_graph_app)):
    """
    Returns the complete message history from the root to a specific checkpoint.
    """
    try:
        messages = await history.path_at(graph_app, thread_id, checkpoint_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"thread_id": thread_id, "checkpoint_id": checkpoint_id, "messages": messages}
