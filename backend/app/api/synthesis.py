from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_graph_app
from app.services import arena, checks, review

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


class ReviewRequest(BaseModel):
    thread_id: str
    checkpoint_ids: List[str]


@router.post("/reviews")
async def run_review(req: ReviewRequest, graph_app=Depends(get_graph_app)):
    """Have the models that wrote these answers score each other's, anonymously; stored and returned."""
    try:
        return await review.review_answers(graph_app, req.thread_id, req.checkpoint_ids)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/reviews/{thread_id}")
def list_reviews(thread_id: str):
    """Every stored peer review on a thread, newest first."""
    return {"reviews": review.reviews_of(thread_id)}


class CheckRequest(BaseModel):
    thread_id: str
    checkpoint_id: str
    models: Optional[List[str]] = None


@router.post("/checks")
async def run_check(req: CheckRequest, graph_app=Depends(get_graph_app)):
    """Check every problem of an issue list against the source the reviews
    answered: each checker's verdict side by side; stored and returned."""
    try:
        return await checks.check_issues(graph_app, req.thread_id, req.checkpoint_id, req.models)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/checks/{thread_id}")
def list_checks(thread_id: str):
    """Every stored check of an issue list on a thread, newest first."""
    return {"checks": checks.checks_of(thread_id)}
