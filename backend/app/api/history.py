import asyncio
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Optional

from app.core import database as db
from app.services import history
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


@router.post("/{thread_id}/positions")
async def save_positions(thread_id: str, updates: List[PositionUpdate]):
    try:
        await asyncio.to_thread(db.save_node_positions, thread_id, updates)
        return {"status": "ok"}
    except Exception as e:
        return {"error": str(e)}


@router.delete("/{thread_id}/checkpoints/{checkpoint_id}")
async def delete_checkpoint(thread_id: str, checkpoint_id: str, graph_app=Depends(get_graph_app)):
    try:
        return {"status": "ok", "deleted_count": await history.delete_branch(graph_app, thread_id, checkpoint_id)}
    except Exception as e:
        import traceback

        traceback.print_exc()
        return {"error": str(e)}


@router.get("/{thread_id}/search")
async def search_history(thread_id: str, q: str, graph_app=Depends(get_graph_app)):
    return {"results": await history.search_thread(graph_app, thread_id, q)}
