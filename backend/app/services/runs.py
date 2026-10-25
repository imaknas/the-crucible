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


def tag_turn_kind(config: Dict[str, Any], kind: Optional[str]) -> None:
    """Mark the run as a special kind of turn (e.g. a synthesis); unknown kinds are ignored."""
    if kind in TURN_KINDS:
        config["metadata"] = {**config.get("metadata", {}), TURN_KIND_KEY: kind}


async def resolve_fork_point(graph_app, thread_id: str) -> str:
    """Return the checkpoint new parallel runs should fork from.

    That is the thread head, or, for an empty thread, a freshly written empty
    root, so that every model in the first turn shares one parent.
    """
    head, _ = await resolve_fork_point_ex(graph_app, thread_id)
    return head


async def resolve_fork_point_ex(graph_app, thread_id: str) -> Tuple[str, bool]:
    """Like resolve_fork_point, also reporting whether the thread was empty."""
    state = await graph_app.aget_state(thread_config(thread_id))
    head = state.config.get("configurable", {}).get("checkpoint_id") if state.config else None
    if head:
        return head, False
    seeded = await graph_app.aupdate_state(
        thread_config(thread_id),
        {"branch_name": "main"},
        as_node="synthesis",
    )
    return seeded["configurable"]["checkpoint_id"], True


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
