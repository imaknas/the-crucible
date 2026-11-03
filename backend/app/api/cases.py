"""Saved cases: save a turn, list and read cases, replay one on other models
(services/cases.py)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_graph_app
from app.services import cases

router = APIRouter(prefix="/cases", tags=["cases"])


def _http_error(e: ValueError) -> HTTPException:
    return HTTPException(404 if "not found" in str(e) else 400, str(e))


class SaveCaseRequest(BaseModel):
    thread_id: str
    # The turn's id, or one of its replies' checkpoints (whose branch the
    # history is read from).
    turn: str
    title: Optional[str] = None


@router.post("")
async def save_case(req: SaveCaseRequest, graph_app=Depends(get_graph_app)):
    """Copy a turn into a saved case (question, history, documents, settings, answers, vote)."""
    try:
        return await cases.save_case(graph_app, req.thread_id, req.turn, title=req.title)
    except ValueError as e:
        raise _http_error(e)


@router.get("")
def list_cases():
    """Every saved case, newest first."""
    return {"cases": cases.list_cases()}


@router.get("/{case_id}")
def get_case(case_id: str):
    """A case with its replays, newest first."""
    try:
        return cases.get_case(case_id)
    except ValueError as e:
        raise _http_error(e)


@router.delete("/{case_id}")
def delete_case(case_id: str):
    """Delete a case and its replay records (the replay threads stay)."""
    try:
        cases.delete_case(case_id)
    except ValueError as e:
        raise _http_error(e)
    return {"deleted": case_id}


class ReplayRequest(BaseModel):
    # Default: the case's own models.
    models: Optional[List[str]] = None


@router.post("/{case_id}/replay")
async def replay_case(case_id: str, req: ReplayRequest, graph_app=Depends(get_graph_app)):
    """Ask the models the case's question again in a new thread, and compare.
    Not streamed, like POST /chat: it answers once every model has. Costs a
    call per model."""
    try:
        return await cases.replay_case(graph_app, case_id, req.models)
    except ValueError as e:
        raise _http_error(e)
