from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_graph_app
from app.core import database as db
from app.services import votes

router = APIRouter(prefix="/votes", tags=["votes"])


class VoteRequest(BaseModel):
    thread_id: str
    # The turn's id or one of its replies' checkpoint; default: the latest turn.
    turn: Optional[str] = None
    outcome: Literal["best", "tie", "all_bad"]
    # The best answer's checkpoint id, or its letter when the vote was blind.
    best: Optional[str] = None
    reason: Optional[str] = None
    task_type: str = "general"
    blind: bool = False


@router.post("")
async def vote(body: VoteRequest, graph_app=Depends(get_graph_app)):
    """Record a vote on a turn's answers (services/votes.vote_turn)."""
    try:
        turn = body.turn or await votes.latest_turn(graph_app, body.thread_id)
        return await votes.vote_turn(
            graph_app, body.thread_id, turn, body.outcome, best=body.best, reason=body.reason,
            task_type=body.task_type, blind=body.blind,
        )
    except ValueError as e:
        raise HTTPException(404 if "not found" in str(e) else 400, str(e))


@router.get("")
def list_votes(thread_id: Optional[str] = None):
    """Votes, newest first: every thread's, or one thread's."""
    return {"votes": votes.votes_of(thread_id)}


@router.get("/stats")
def vote_stats(task_type: Optional[str] = None):
    """Win rates per model over every vote, optionally of one task type."""
    try:
        return votes.vote_stats(task_type)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/{thread_id}/{turn_id}")
def delete_vote(thread_id: str, turn_id: str):
    if not db.delete_answer_vote(thread_id, turn_id):
        raise HTTPException(404, f"No vote on turn {turn_id} of thread {thread_id}.")
    return {"status": "ok"}
