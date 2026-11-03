"""A person's votes on a turn's answers, and the win rates they add up to.

A vote is one judgment per turn: the best answer, a tie, or "all bad", with
an optional reason and the kind of task it was (chosen by the person from
TASK_TYPES; nothing classifies it automatically, so every label is one the
person can stand behind). Read blind, the answers are lettered by
``blind_letters``, the same order the web UI shows, so a model is judged by
its answer, not its name. Votes are stored per turn
(core/database answer_votes); voting again replaces the vote.

Win rates are pairwise: a "best" vote over n answers is n−1 wins for the
winner and one loss for each other answer; a tie is a tie for every pair;
"all bad" is counted on its own for each model, never as a loss to another.
"""

import asyncio
from typing import Any, Dict, Iterable, List, Optional, Sequence

from app.core import database as db
from app.registry import display_name

OUTCOMES = ("best", "tie", "all_bad")
TASK_TYPES = ("general", "coding", "writing", "research", "reasoning", "other")
REASON_MAX_CHARS = 500


def _fnv1a(text: str) -> int:
    """32-bit FNV-1a; lib/blind.ts computes the same number."""
    h = 0x811C9DC5
    for byte in text.encode("utf-8"):
        h ^= byte
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def blind_order(turn_id: str, models: Sequence[str]) -> List[str]:
    """A turn's answering models in the order a blind comparison shows them:
    fixed for the turn (a reload shows the same letters), unrelated to who
    answered first. By model, not checkpoint: the web UI letters the cards
    while they stream, before the replies have checkpoints (a turn has one
    answer per model)."""
    return sorted(dict.fromkeys(models), key=lambda m: (_fnv1a(f"{turn_id}:{m}"), m))


def blind_letters(turn_id: str, answers: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    """{checkpoint_id: "A" | "B" | …} for answers [{checkpoint_id, model}], in ``blind_order``."""
    order = blind_order(turn_id, [a["model"] for a in answers])
    return {a["checkpoint_id"]: chr(ord("A") + order.index(a["model"])) for a in answers}


def win_rates(votes: Iterable[Dict[str, Any]], task_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Per model, over ``votes`` (of ``task_type`` only, when given):
    {model, model_name, wins, losses, ties, all_bad, votes, win_rate}, best
    first. win_rate = (wins + ties / 2) / (wins + losses + ties), None for a
    model with no pairwise result."""
    rows: Dict[str, Dict[str, Any]] = {}

    def row(model: str) -> Dict[str, Any]:
        return rows.setdefault(model, {"model": model, "wins": 0, "losses": 0, "ties": 0, "all_bad": 0, "votes": 0})

    for vote in votes:
        if task_type and vote.get("task_type") != task_type:
            continue
        models = [a["model"] for a in vote["answers"]]
        for m in models:
            row(m)["votes"] += 1
        if vote["outcome"] == "all_bad":
            for m in models:
                row(m)["all_bad"] += 1
        elif vote["outcome"] == "tie":
            for m in models:
                row(m)["ties"] += len(models) - 1
        else:
            winner = next((a["model"] for a in vote["answers"] if a["checkpoint_id"] == vote["winner_checkpoint_id"]), None)
            for m in models:
                if m == winner:
                    row(m)["wins"] += len(models) - 1
                else:
                    row(m)["losses"] += 1
    out = []
    for r in rows.values():
        games = r["wins"] + r["losses"] + r["ties"]
        out.append({**r, "model_name": display_name(r["model"]),
                    "win_rate": round((r["wins"] + r["ties"] / 2) / games, 3) if games else None})
    return sorted(out, key=lambda r: (r["win_rate"] is None, -(r["win_rate"] or 0), -r["votes"], r["model"]))


async def turn_answers(graph_app, thread_id: str, turn: str) -> Dict[str, Any]:
    """A turn's answers, by its id or one of its replies' checkpoint:
    {turn_id, answers: [{checkpoint_id, model, model_name}]} (tree node ids,
    in the order answered; syntheses left out). ValueError for a turn the
    thread lacks or a reply written before turns were recorded."""
    from app.services.arena import _turn_replies
    from app.services.chat import node_checkpoint, thread_state_map
    from app.services.runs import TURN_ID_KEY

    states = await thread_state_map(graph_app, thread_id)
    turn_id = turn
    if turn in states:
        turn_id = (states[turn].metadata or {}).get(TURN_ID_KEY)
        if not turn_id:
            raise ValueError(f"Reply {turn} was written before turns were recorded; it can't be voted on.")
    replies = _turn_replies(states, turn_id)
    if not replies:
        raise ValueError(f"Turn {turn} not found on thread {thread_id}.")
    return {
        "turn_id": turn_id,
        "answers": [
            {"checkpoint_id": node_checkpoint(snapshot, states), "model": model, "model_name": display_name(model)}
            for model, snapshot in replies.items()
        ],
    }


async def latest_turn(graph_app, thread_id: str) -> str:
    """The id of the thread's latest turn (the answered head's). ValueError
    when the thread has none."""
    from app.services.runs import TURN_ID_KEY, answered_head

    head = await answered_head(graph_app, thread_id)
    turn_id = (getattr(head, "metadata", None) or {}).get(TURN_ID_KEY) if head and head.values else None
    if not turn_id:
        raise ValueError(f"Thread {thread_id} has no turn to vote on.")
    return turn_id


async def vote_turn(
    graph_app,
    thread_id: str,
    turn: str,
    outcome: str,
    *,
    best: Optional[str] = None,
    reason: Optional[str] = None,
    task_type: str = "general",
    blind: bool = False,
) -> Dict[str, Any]:
    """Record a vote on a turn's answers (replacing an earlier one): the
    stored vote, its answers with their blind letters. ``best`` is the
    winning answer's checkpoint id, or its letter when ``blind`` (as the
    person saw them). ValueError for an unknown outcome or task type, a turn
    with fewer than two answers, or a ``best`` that isn't one of them."""
    if outcome not in OUTCOMES:
        raise ValueError(f"The outcome is one of {', '.join(OUTCOMES)}.")
    if task_type not in TASK_TYPES:
        raise ValueError(f"The task type is one of {', '.join(TASK_TYPES)}.")
    reason = " ".join((reason or "").split()) or None
    if reason and len(reason) > REASON_MAX_CHARS:
        raise ValueError(f"A reason is at most {REASON_MAX_CHARS} characters.")
    turn_data = await turn_answers(graph_app, thread_id, turn)
    answers = turn_data["answers"]
    if len(answers) < 2:
        raise ValueError("A vote needs a turn with at least two answers.")
    letters = blind_letters(turn_data["turn_id"], answers)
    winner = None
    if outcome == "best":
        if not best:
            raise ValueError("Name the best answer.")
        by_letter = {letter: cid for cid, letter in letters.items()}
        winner = by_letter.get(best.upper()) if len(best) == 1 else best
        if winner not in letters:
            raise ValueError(f"{best} is not one of this turn's answers.")
    elif best:
        raise ValueError(f"A {outcome.replace('_', ' ')} vote names no best answer.")
    stored = await asyncio.to_thread(
        db.save_answer_vote, thread_id, turn_data["turn_id"], outcome=outcome, winner_checkpoint_id=winner,
        answers=[{"checkpoint_id": a["checkpoint_id"], "model": a["model"]} for a in answers],
        reason=reason, task_type=task_type, blind=blind,
    )
    return with_names(stored)


def with_names(vote: Dict[str, Any]) -> Dict[str, Any]:
    """A stored vote as clients read it: each answer with its display name and blind letter."""
    letters = blind_letters(vote["turn_id"], vote["answers"])
    return {
        **vote,
        "answers": [
            {**a, "model_name": display_name(a["model"]), "letter": letters[a["checkpoint_id"]]} for a in vote["answers"]
        ],
    }


def votes_of(thread_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every vote (or one thread's), newest first, as clients read them."""
    return [with_names(v) for v in db.list_answer_votes(thread_id)]


def vote_stats(task_type: Optional[str] = None) -> Dict[str, Any]:
    """Win rates over every vote: {task_type, task_types: {type: count}, votes, models: win_rates(...)}."""
    if task_type and task_type not in TASK_TYPES:
        raise ValueError(f"The task type is one of {', '.join(TASK_TYPES)}.")
    votes = db.list_answer_votes()
    counts: Dict[str, int] = {}
    for v in votes:
        counts[v["task_type"]] = counts.get(v["task_type"], 0) + 1
    return {
        "task_type": task_type,
        "task_types": counts,
        "votes": sum(1 for v in votes if not task_type or v["task_type"] == task_type),
        "models": win_rates(votes, task_type),
    }
