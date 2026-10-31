"""Helpers for running several graph invocations against one thread at once.

Parallel runs on a thread must each fork from an explicit checkpoint. Without a
pinned ``checkpoint_id`` a run resumes from the thread head, so the second
model picks up the first model's half-written turn and only one reply ends up
at the head. Each run is also tagged with a run id in its checkpoint metadata,
because re-reading the pinned config afterwards returns the parent, not the
checkpoint the run produced.
"""

import uuid
from typing import Any, Dict, Optional, Tuple

RUN_ID_KEY = "crucible_run_id"
# Marks a checkpoint holding context copied in from elsewhere (a debate's
# parent conversation), which is not a turn of the thread it sits on.
SEED_KEY = "crucible_seed"
# What a run is for, when it is not an ordinary turn. Also copied into the
# checkpoint metadata, so the tree can tell a synthesis reply from an answer.
TURN_KIND_KEY = "crucible_turn"
SYNTHESIS_TURN = "synthesis"
TURN_KINDS = frozenset({SYNTHESIS_TURN})
# Shared by every run of one turn (each model answering the same message), so
# readers can group the replies to it even when they sit on different branches.
TURN_ID_KEY = "crucible_turn_id"
# Names the debate session a parent-thread checkpoint records (written by
# debate.continue_from_debate when a chat turn follows a debate).
DEBATE_RECORD_KEY = "crucible_debate"


def thread_config(thread_id: str, checkpoint_id: Optional[str] = None) -> Dict[str, Any]:
    config: Dict[str, Any] = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    if checkpoint_id:
        config["configurable"]["checkpoint_id"] = checkpoint_id
    return config


def tag_run(config: Dict[str, Any]) -> str:
    """Attach a fresh run id to ``config``; LangGraph copies it into checkpoint metadata."""
    run_id = uuid.uuid4().hex
    config["metadata"] = {**config.get("metadata", {}), RUN_ID_KEY: run_id}
    return run_id


def new_turn_id() -> str:
    return uuid.uuid4().hex


def tag_turn(config: Dict[str, Any], turn_id: Optional[str]) -> None:
    """Mark the run as part of turn ``turn_id`` (copied into checkpoint metadata)."""
    if turn_id:
        config["metadata"] = {**config.get("metadata", {}), TURN_ID_KEY: turn_id}


def tag_turn_kind(config: Dict[str, Any], kind: Optional[str]) -> None:
    """Mark the run as a special kind of turn (e.g. a synthesis); unknown kinds are ignored."""
    if kind in TURN_KINDS:
        config["metadata"] = {**config.get("metadata", {}), TURN_KIND_KEY: kind}


async def resolve_fork_point(graph_app, thread_id: str) -> str:
    """Return the checkpoint new parallel runs should fork from.

    That is the thread head (see answered_head), or, for an empty thread, a
    freshly written empty root, so that every model in the first turn shares
    one parent.
    """
    head, _ = await resolve_fork_point_ex(graph_app, thread_id)
    return head


def _ends_on_person(snapshot) -> bool:
    messages = (snapshot.values or {}).get("messages", []) if snapshot else []
    return bool(messages) and getattr(messages[-1], "type", "") == "human"


async def answered_head(graph_app, thread_id: str):
    """The thread head, skipping a turn that never got its reply.

    A turn cut off before any model answered (a closed tab, a dropped socket,
    a model that failed) leaves the head on the person's message. Continuing
    from it put the next message after an unanswered one, merged into one
    request. The head is then its nearest ancestor that ends on a reply (or
    the empty root), so the next turn is a sibling of the abandoned one,
    which stays in the tree.
    """
    head = await graph_app.aget_state(thread_config(thread_id))
    if not _ends_on_person(head):
        return head
    current = head
    # The abandoned run's own input checkpoint still ends on the last reply,
    # but holds that run's input as a pending write: walk past it too.
    while (_ends_on_person(current) or _is_run_input(current)) and current.parent_config:
        current = await graph_app.aget_state(current.parent_config)
    return head if _ends_on_person(current) else current


def _is_run_input(snapshot) -> bool:
    metadata = getattr(snapshot, "metadata", None)
    return isinstance(metadata, dict) and metadata.get("source") == "input"


async def resolve_fork_point_ex(graph_app, thread_id: str) -> Tuple[str, bool]:
    """Like resolve_fork_point, also reporting whether the thread was empty."""
    state = await answered_head(graph_app, thread_id)
    head = state.config.get("configurable", {}).get("checkpoint_id") if state.config else None
    if head:
        return head, False
    seeded = await graph_app.aupdate_state(
        thread_config(thread_id),
        {"branch_name": "main"},
        as_node="synthesis",
    )
    return seeded["configurable"]["checkpoint_id"], True


async def fork_point(graph_app, thread_id: str, checkpoint_id: Optional[str]) -> Tuple[str, bool]:
    """The checkpoint a turn forks from: ``checkpoint_id`` when given (it must
    exist on the thread), otherwise the head (resolve_fork_point_ex). Also
    reports whether the thread was empty.

    A checkpoint id the thread doesn't have would read back as an empty
    state, and the turn would quietly start a conversation from nothing.
    """
    if not checkpoint_id:
        return await resolve_fork_point_ex(graph_app, thread_id)
    state = await graph_app.aget_state(thread_config(thread_id, checkpoint_id))
    if state is None or state.created_at is None:
        raise ValueError(f"Checkpoint {checkpoint_id} not found on thread {thread_id}.")
    return checkpoint_id, False


async def seed_thread(graph_app, thread_id: str, values: Dict[str, Any]) -> str:
    """Write ``values`` as a checkpoint marked as seed; returns its id.

    Written as the ``synthesis`` node, the last before END, so the next run
    starts a fresh turn from it.
    """
    config = thread_config(thread_id)
    config["metadata"] = {SEED_KEY: True}
    written = await graph_app.aupdate_state(config, values, as_node="synthesis")
    return written["configurable"]["checkpoint_id"]


def is_seed(snapshot) -> bool:
    """Whether a checkpoint was written by ``seed_thread``."""
    metadata = getattr(snapshot, "metadata", None)
    return isinstance(metadata, dict) and bool(metadata.get(SEED_KEY))


async def seeded_message_count(graph_app, thread_id: str) -> int:
    """How many of the thread's first messages were seeded rather than said on it."""
    async for snapshot in graph_app.aget_state_history(
        thread_config(thread_id), filter={SEED_KEY: True}, limit=1
    ):
        return len((snapshot.values or {}).get("messages", []))
    return 0


async def final_state_of_run(graph_app, thread_id: str, run_id: str):
    """The last checkpoint written by the run tagged ``run_id``, or None."""
    async for snapshot in graph_app.aget_state_history(
        thread_config(thread_id), filter={RUN_ID_KEY: run_id}, limit=1
    ):
        return snapshot
    return None
