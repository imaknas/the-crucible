from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_graph_app
from app.services import arena

router = APIRouter(prefix="/synthesis", tags=["synthesis"])


class ComponentsRequest(BaseModel):
    thread_id: str
    checkpoint_ids: List[str]
    model: Optional[str] = None


@router.post("/components")
async def list_components(req: ComponentsRequest, graph_app=Depends(get_graph_app)):
    """The components of the answers, for the reader to tick before a
    checklist synthesis (sent back as the chat frame's keep_components)."""
    try:
        components = await arena.answer_components(graph_app, req.thread_id, req.checkpoint_ids, req.model)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"components": [{"text": c.text, "sources": list(c.sources)} for c in components]}
