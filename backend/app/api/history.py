import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional

from app.core import database as db
from app.services import history, subtree
from app.api.deps import get_graph_app

router = APIRouter(prefix="/history", tags=["history"])


class PositionUpdate(BaseModel):
    node_id: str
    x: float
    y: float


@router.get("/{thread_id}")
async def get_history(
    thread_id: str, checkpoint_id: Optional[str] = None, graph_app=Depends(get_graph_app)
):
    return await history.thread_tree(graph_app, thread_id, checkpoint_id)


@router.get("/{thread_id}/context")
async def get_context(
    thread_id: str,
    checkpoint_id: Optional[str] = None,
    models: List[str] = Query(default=[]),
    graph_app=Depends(get_graph_app),
):
    """How much the next turn would send each model (history.context_report)."""
    try:
        return await history.context_report(graph_app, thread_id, checkpoint_id, models)
    except ValueError as e:
        raise HTTPException(404 if "not found" in str(e) else 400, str(e))


class NodeLabel(BaseModel):
    name: Optional[str] = None
    bookmarked: Optional[bool] = None


class SubtreeSummaryRequest(BaseModel):
    model: Optional[str] = None


def _http_error(e: ValueError) -> HTTPException:
    return HTTPException(404 if "not found" in str(e) else 400, str(e))


@router.patch("/{thread_id}/nodes/{node_id}")
async def label_node(thread_id: str, node_id: str, body: NodeLabel, graph_app=Depends(get_graph_app)):
    """Name a node's branch and/or bookmark it (subtree.label_node)."""
    try:
        return await subtree.label_node(graph_app, thread_id, node_id, name=body.name, bookmarked=body.bookmarked)
    except ValueError as e:
        raise _http_error(e)


@router.post("/{thread_id}/nodes/{node_id}/summary")
async def summarize_subtree(
    thread_id: str, node_id: str, body: SubtreeSummaryRequest, graph_app=Depends(get_graph_app)
):
    """Summarize the node and everything below it, stored on the node."""
    try:
        return await subtree.summarize_subtree(graph_app, thread_id, node_id, model=body.model)
    except ValueError as e:
        raise _http_error(e)


@router.delete("/{thread_id}/nodes/{node_id}/summary")
async def clear_subtree_summary(thread_id: str, node_id: str, graph_app=Depends(get_graph_app)):
    try:
        await subtree.clear_subtree_summary(graph_app, thread_id, node_id)
    except ValueError as e:
        raise _http_error(e)
    return {"status": "ok"}


@router.post("/{thread_id}/positions")
async def save_positions(thread_id: str, updates: List[PositionUpdate]):
    await asyncio.to_thread(db.save_node_positions, thread_id, updates)
    return {"status": "ok"}


@router.delete("/{thread_id}/checkpoints/{checkpoint_id}")
async def delete_checkpoint(thread_id: str, checkpoint_id: str, graph_app=Depends(get_graph_app)):
    try:
        deleted = await history.delete_branch(graph_app, thread_id, checkpoint_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not deleted:
        raise HTTPException(404, f"Checkpoint {checkpoint_id} not found on thread {thread_id}.")
    return {"status": "ok", "deleted_count": deleted}


@router.get("/{thread_id}/search")
async def search_history(thread_id: str, q: str, graph_app=Depends(get_graph_app)):
    # The sidebar searches as the person types: a too-short query finds nothing.
    if len(q.strip()) < 2:
        return {"results": []}
    try:
        return {"results": await history.search_thread(graph_app, thread_id, q)}
    except ValueError as e:
        raise HTTPException(404, str(e))
