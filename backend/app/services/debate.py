"""
Debate session coordinator.

Orchestrates multi-round, multi-model debates. Each model gets its own
LangGraph thread ("{parent_thread_id}::{session_id}::{model_id}"). Rounds
progress through Independent → Cross-Examination → (optional) Synthesis.

Yields typed event dicts consumed by the WebSocket handler in api/debate.py.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Container, Mapping, Optional
from uuid import uuid4

from app.api.models import MODEL_REGISTRY
from app.core import database as db
from app.services.convergence import build_convergence_check
from app.services.context import DEFAULT_CONTEXT, ContextSettings
from app.services.recall import INTERNAL_TAG
from app.services.synthesis import AFTER_DEBATE, build_synthesis_prompt
from app.services.runs import (
    final_state_of_run,
    seed_thread,
    seeded_message_count,
    tag_run,
    thread_config,
)
from app.utils.helpers import extract_text

# ─── Constants ───────────────────────────────────────────────────────────────

# Per-model budget for one round's graph run (summarise → draft → metadata →
# synthesis). A reply whose draft already finished is kept even if the later
# bookkeeping nodes run past it.
MODEL_TIMEOUT_SECONDS = 120

# Rounds a session may ask for. The API has no authentication, so this bounds
# what one request can spend: rounds × participants model calls.
DEFAULT_ROUNDS = 3
MAX_ROUNDS = 10


@dataclass
class DebateControl:
    """Live controls for a running debate, owned by its WebSocket connection.

    Pause takes effect between rounds; injected messages are added to the
    next round's prompts. Both live in memory because a debate only runs
    while its socket is connected.
    """

    resumed: asyncio.Event = field(default_factory=asyncio.Event)
    injected: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.resumed.set()

    @property
    def paused(self) -> bool:
        return not self.resumed.is_set()

    def pause(self) -> None:
        self.resumed.clear()

    def resume(self) -> None:
        self.resumed.set()

    def inject(self, message: str) -> None:
        self.injected.append(message)

    def take_injected(self) -> list[str]:
        taken, self.injected = self.injected, []
        return taken


def make_thread_id(parent_thread_id: str, session_id: str, model_id: str) -> str:
    """A participant's sub-thread. Scoped to the session: two debates on one
    parent thread must not read, draw or delete each other's rounds."""
    return f"{parent_thread_id}::{session_id}::{model_id}"


def make_synthesis_thread_id(parent_thread_id: str, session_id: str) -> str:
    return f"{parent_thread_id}::{session_id}::{db.SYNTHESIS_KEY}"


# ─── Session factory ─────────────────────────────────────────────────────────


def check_session_config(
    participants: list[str],
    termination_policy: Mapping[str, Any],
    synthesizer_model: Optional[str] = None,
    known_models: Container[str] = MODEL_REGISTRY,
) -> None:
    """Raise ValueError (with a caller-facing message) if a debate can't run as asked.

    Every round costs one call per participant, so the round count is bounded;
    each model a debate will call must be one the app offers.
    """
    if len(participants) != len(set(participants)):
        dupes = sorted({m for m in participants if participants.count(m) > 1})
        raise ValueError(f"Each model can take part only once: {', '.join(dupes)}")
    if len(participants) < 2:
        raise ValueError("A debate requires at least 2 participants")
    judge = termination_policy.get("llm_judge")
    unknown = [m for m in [*participants, synthesizer_model, judge] if m and m not in known_models]
    if unknown:
        raise ValueError(f"Unknown models: {', '.join(unknown)}")
    rounds = termination_policy.get("max_rounds", DEFAULT_ROUNDS)
    if not isinstance(rounds, int) or isinstance(rounds, bool) or not 1 <= rounds <= MAX_ROUNDS:
        raise ValueError(f"max_rounds must be between 1 and {MAX_ROUNDS}")
    if termination_policy.get("mode", "all") not in ("all", "any"):
        raise ValueError("mode must be 'all' or 'any'")


def create_session(
    parent_thread_id: str,
    participants: list[str],
    termination_policy: dict[str, Any],
    auto_synthesize: bool = False,
    synthesizer_model: Optional[str] = None,
    known_models: Container[str] = MODEL_REGISTRY,
) -> dict[str, Any]:
    check_session_config(participants, termination_policy, synthesizer_model, known_models)
    session_id = f"debate-{uuid4().hex[:12]}"
    # Stored, not derived, so the id scheme can change without losing the
    # threads of sessions created under an older one.
    thread_ids = {m: make_thread_id(parent_thread_id, session_id, m) for m in participants}
    thread_ids[db.SYNTHESIS_KEY] = make_synthesis_thread_id(parent_thread_id, session_id)
    session = {
        "session_id": session_id,
        "parent_thread_id": parent_thread_id,
        "participants": participants,
        "thread_ids": thread_ids,
        "current_round": 0,
        "status": "running",
        "termination_policy": termination_policy,
        "auto_synthesize": auto_synthesize,
        "synthesizer_model": synthesizer_model,
    }
    db.create_debate_session(session)
    return session


# ─── Core coordinator ────────────────────────────────────────────────────────


async def run_debate(
    graph_app,
    session_id: str,
    prompt: str,
    toggles: dict[str, Any],
    documents: dict[str, str],
    parent_checkpoint_id: Optional[str] = None,
    control: Optional[DebateControl] = None,
    context: ContextSettings = DEFAULT_CONTEXT,
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Main debate generator. Yields WS-ready event dicts:

    debate_session_created, debate_round_start,
    stream_start, stream_token, stream_end,
    debate_round_end, debate_converged,
    debate_synthesis_start, debate_synthesis_end,
    debate_session_status, error
    """
    session = db.get_debate_session(session_id)
    if not session:
        yield {"type": "error", "message": f"Session {session_id} not found"}
        return

    # Sessions stored before duplicates were rejected may list a model twice;
    # it has one sub-thread, so it debates once.
    participants = list(dict.fromkeys(session["participants"]))
    thread_ids = session["thread_ids"]
    policy = session["termination_policy"]
    max_rounds = min(policy.get("max_rounds", DEFAULT_ROUNDS), MAX_ROUNDS)
    convergence = build_convergence_check(policy)

    # A debate started from a fresh session writes only to its sub-threads, so
    # the parent has no checkpoints; without a title row list_threads never
    # shows it and the debate can't be found again in the sidebar.
    parent_thread_id = session["parent_thread_id"]
    if not db.get_thread_title(parent_thread_id):
        db.rename_thread(parent_thread_id, f"Debate: {prompt.strip().splitlines()[0][:40] if prompt.strip() else ', '.join(participants)}")

    yield {
        "type": "debate_session_created",
        "session_id": session_id,
        "participants": participants,
        "thread_ids": thread_ids,
    }

    if parent_checkpoint_id:
        await seed_from_parent(
            graph_app, parent_thread_id, parent_checkpoint_id,
            [thread_ids[m] for m in participants],
        )

    # Track per-model responses per round for convergence detection
    prev_round_responses: dict[str, str] = {}
    curr_round_responses: dict[str, str] = {}

    control = control or DebateControl()

    for round_num in range(max_rounds):
        if control.paused:
            db.update_debate_session(session_id, status="paused")
            yield {"type": "debate_session_status", "session_id": session_id, "status": "paused"}
            await control.resumed.wait()
            yield {"type": "debate_session_status", "session_id": session_id, "status": "running"}

        db.update_debate_session(session_id, current_round=round_num, status="running")
        yield {"type": "debate_round_start", "session_id": session_id, "round": round_num}

        curr_round_responses = {}

        # Build per-model prompts
        model_prompts = _build_round_prompts(
            round_num=round_num,
            prompt=prompt,
            participants=participants,
            prev_round_responses=prev_round_responses,
            injected=control.take_injected(),
        )

        # Stream all models concurrently
        async for event in _stream_round(
            graph_app=graph_app,
            round_num=round_num,
            session_id=session_id,
            participants=participants,
            thread_ids=thread_ids,
            model_prompts=model_prompts,
            toggles=toggles,
            documents=documents,
            curr_round_responses=curr_round_responses,
            context=context,
        ):
            yield event

        # Check stopping conditions after round 0 (need at least one prior round
        # to compare). Done before the round_end event so a single event can
        # carry the score — emitting two made the client refetch the tree twice.
        verdict = None
        if convergence and round_num > 0 and prev_round_responses:
            verdict = await convergence.evaluate(prev_round_responses, curr_round_responses)
        score = verdict.score if verdict else None

        round_end: dict[str, Any] = {
            "type": "debate_round_end",
            "session_id": session_id,
            "round": round_num,
        }
        if score is not None:
            round_end["convergence_score"] = score
            db.record_round_score(session_id, round_num, score)
        yield round_end

        # Promote before the convergence break, otherwise synthesis would run
        # on the second-to-last round's answers.
        prev_round_responses = dict(curr_round_responses)

        if verdict and verdict.converged:
            yield {
                "type": "debate_converged",
                "session_id": session_id,
                "round": round_num,
                "score": verdict.score,
                "reason": verdict.reason,
                "method": verdict.method,
            }
            break

    unused = control.take_injected()
    if unused:
        yield {
            "type": "error",
            "session_id": session_id,
            "message": "The debate ended before your injected message could be used: "
            + " / ".join(unused),
        }

    # Auto-synthesize if configured
    if session.get("auto_synthesize") and session.get("synthesizer_model"):
        async for event in _stream_synthesis(
            graph_app=graph_app,
            session_id=session_id,
            session=session,
            prompt=prompt,
            all_responses=prev_round_responses,
            toggles=toggles,
            context=context,
        ):
            yield event

    db.update_debate_session(session_id, status="completed")
    yield {"type": "debate_session_status", "session_id": session_id, "status": "completed"}


# ─── Round helpers ───────────────────────────────────────────────────────────


async def seed_from_parent(
    graph_app,
    parent_thread_id: str,
    checkpoint_id: str,
    sub_thread_ids: list[str],
) -> int:
    """Give each empty sub-thread the parent conversation as it stood at
    ``checkpoint_id``; returns how many messages were copied.

    A debate started from a node of a conversation is about that
    conversation. The checkpoint id belongs to the parent thread, so running
    round 0 "from" it on a sub-thread found nothing there and the models saw
    only the debate prompt. A sub-thread that already has history (a start
    frame sent again) is left alone.
    """
    parent = await graph_app.aget_state(thread_config(parent_thread_id, checkpoint_id))
    messages = list((parent.values or {}).get("messages", [])) if parent else []
    if not messages:
        return 0
    for thread_id in sub_thread_ids:
        head = await graph_app.aget_state(thread_config(thread_id))
        if head and head.values:
            continue
        await seed_thread(graph_app, thread_id, {"messages": messages})
    return len(messages)


def _build_round_prompts(
    round_num: int,
    prompt: str,
    participants: list[str],
    prev_round_responses: dict[str, str],
    injected: Optional[list[str]] = None,
) -> dict[str, str]:
    """Round 0: original prompt. Round 1+: each model sees all peers' previous responses.

    Messages the user injected since the last round are appended to every prompt.
    """
    prompts = _base_round_prompts(round_num, prompt, participants, prev_round_responses)
    if injected:
        note = "\n\n".join(injected)
        prompts = {
            m: f"{p}\n\nThe user has added this to the debate; take it into account:\n{note}"
            for m, p in prompts.items()
        }
    return prompts


def _base_round_prompts(
    round_num: int,
    prompt: str,
    participants: list[str],
    prev_round_responses: dict[str, str],
) -> dict[str, str]:
    if round_num == 0:
        return {m: prompt for m in participants}

    prompts: dict[str, str] = {}
    for model_id in participants:
        peer_context = "\n\n".join(
            f"[{peer}]:\n{content}"
            for peer, content in prev_round_responses.items()
            if peer != model_id
        )
        prompts[model_id] = (
            f"Original question: {prompt}\n\n"
            f"Other models' previous responses:\n{peer_context}\n\n"
            f"You are {model_id}. Critically analyze the other models' arguments. "
            "Where do you agree? Where do you disagree? What are they missing? "
            "State your position now. If it changed, name the argument or evidence that "
            "changed it; agreement alone, or how many models hold a view, is not a reason."
        )
    return prompts


async def _stream_round(
    graph_app,
    round_num: int,
    session_id: str,
    participants: list[str],
    thread_ids: dict[str, str],
    model_prompts: dict[str, str],
    toggles: dict[str, Any],
    documents: dict[str, str],
    curr_round_responses: dict[str, str],
    context: ContextSettings = DEFAULT_CONTEXT,
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream all models for one round concurrently, interleaving their tokens."""
    queue: asyncio.Queue = asyncio.Queue()

    async def _model_producer(model_id: str):
        thread_id = thread_ids[model_id]
        model_prompt = model_prompts[model_id]
        buffer = ""
        draft_done = False
        run_id = ""
        try:
            initial_state = {
                "active_peer": model_id,
                "messages": [("user", model_prompt)],
                "toggles": {**toggles, "use_rag": toggles.get("use_rag", False)},
                "is_deliberation": round_num > 0,
                "current_thesis": "",
                "documents": documents,
            }
            # Each model has its own sub-thread, so every round continues from
            # that thread's head: the seeded conversation, or the last round.
            langgraph_config = context.apply(thread_config(thread_id))
            run_id = tag_run(langgraph_config)

            await queue.put({
                "type": "stream_start",
                "model": model_id,
                "session_id": session_id,
                "round": round_num,
            })

            async with asyncio.timeout(MODEL_TIMEOUT_SECONDS):
                async for event in graph_app.astream_events(initial_state, langgraph_config, version="v2", exclude_tags=[INTERNAL_TAG]):
                    kind = event.get("event")
                    if kind == "on_chain_end" and event.get("name") == "draft":
                        draft_done = True
                    if kind == "on_chat_model_stream":
                        node_name = event.get("metadata", {}).get("langgraph_node", "")
                        if node_name != "draft":
                            continue
                        chunk = event.get("data", {}).get("chunk")
                        if chunk and hasattr(chunk, "content") and chunk.content:
                            token = extract_text(chunk.content, strip=False)
                            if token:
                                buffer += token
                                await queue.put({
                                    "type": "stream_token",
                                    "token": token,
                                    "model": model_id,
                                    "session_id": session_id,
                                })
                    elif kind == "on_chain_end" and event.get("name") == "LangGraph":
                        data = event.get("data", {}).get("output", {})
                        msgs = data.get("messages", [])
                        final = await final_state_of_run(graph_app, thread_id, run_id)
                        checkpoint_id = (
                            final.config["configurable"]["checkpoint_id"] if final else ""
                        )
                        await queue.put({
                            "type": "stream_end",
                            "model": model_id,
                            "session_id": session_id,
                            "round": round_num,
                            "checkpoint_id": checkpoint_id,
                            "content": buffer,
                            "messages": [
                                {"role": getattr(m, "type", "ai"), "content": extract_text(m.content), "model": getattr(m, "name", model_id)}
                                for m in msgs if getattr(m, "type", "") == "ai"
                            ],
                        })
                        curr_round_responses[model_id] = buffer

        except asyncio.TimeoutError:
            if draft_done and buffer:
                # The answer is complete; only the post-draft bookkeeping ran long.
                await queue.put({
                    "type": "stream_end",
                    "model": model_id,
                    "session_id": session_id,
                    "round": round_num,
                    "checkpoint_id": "",
                    "content": buffer,
                    "messages": [],
                })
                curr_round_responses[model_id] = buffer
            else:
                await queue.put({"type": "error", "model": model_id, "session_id": session_id, "round": round_num, "message": f"{model_id} timed out after {MODEL_TIMEOUT_SECONDS}s"})
                curr_round_responses[model_id] = ""
        except Exception as e:
            await queue.put({"type": "error", "model": model_id, "session_id": session_id, "round": round_num, "message": str(e)})
            curr_round_responses[model_id] = ""
        finally:
            await queue.put({"type": "__done__", "model": model_id})

    # One producer per model, and the round ends when every producer has
    # reported done. Counting done events per producer (not distinct model
    # ids) keeps a repeated model from leaving the round waiting forever.
    tasks = [asyncio.create_task(_model_producer(m)) for m in dict.fromkeys(participants)]
    pending = len(tasks)

    try:
        while pending:
            event = await queue.get()
            if event["type"] == "__done__":
                pending -= 1
            else:
                yield event
    finally:
        # On stop/disconnect the consumer is cancelled at queue.get(); without
        # this the producers kept streaming and billing until their timeout.
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


# ─── Synthesis ───────────────────────────────────────────────────────────────


async def _debate_messages(graph_app, thread_id: str) -> list:
    """What was said on a sub-thread: its head's messages after any seeded
    parent conversation, which is context the debate started from."""
    state = await graph_app.aget_state(thread_config(thread_id))
    msgs = state.values.get("messages", []) if state and state.values else []
    return msgs[await seeded_message_count(graph_app, thread_id):]


async def latest_responses(graph_app, session: dict[str, Any]) -> dict[str, str]:
    """Each participant's most recent debate reply, read from its sub-thread head.

    A participant that never replied has no entry, even when its sub-thread
    was seeded with a conversation that ends on someone's answer.
    """
    responses: dict[str, str] = {}
    for model_id in session["participants"]:
        thread_id = session["thread_ids"].get(model_id)
        if not thread_id:
            continue
        try:
            msgs = await _debate_messages(graph_app, thread_id)
        except Exception:
            continue
        last_ai = next((m for m in reversed(msgs) if getattr(m, "type", "") == "ai"), None)
        if last_ai is not None:
            responses[model_id] = extract_text(last_ai.content)
    return responses


async def _original_question(graph_app, session: dict[str, Any]) -> str:
    """The round-0 prompt: the first message of each participant's debate.

    Sessions don't store it; the web UI passes it along, the CLI recovers it.
    """
    for model_id in session["participants"]:
        thread_id = session["thread_ids"].get(model_id)
        if not thread_id:
            continue
        msgs = await _debate_messages(graph_app, thread_id)
        first = next((m for m in msgs if getattr(m, "type", "") == "human"), None)
        if first is not None:
            return extract_text(first.content)
    return ""


async def synthesize_session(
    graph_app,
    session_id: str,
    prompt: str,
    synthesizer: Optional[str] = None,
    toggles: Optional[dict[str, Any]] = None,
    context: ContextSettings = DEFAULT_CONTEXT,
    known_models: Container[str] = MODEL_REGISTRY,
) -> AsyncGenerator[dict[str, Any], None]:
    """Synthesize a finished (or interrupted) debate from its latest responses."""
    session = db.get_debate_session(session_id)
    if not session:
        yield {"type": "error", "session_id": session_id, "message": f"Session {session_id} not found"}
        return
    model = synthesizer or session.get("synthesizer_model")
    if not model:
        yield {"type": "error", "session_id": session_id, "message": "No synthesizer model specified"}
        return
    if model not in known_models:
        yield {"type": "error", "session_id": session_id, "message": f"Unknown models: {model}"}
        return
    responses = await latest_responses(graph_app, session)
    if not prompt:
        prompt = await _original_question(graph_app, session)
    async for event in _stream_synthesis(
        graph_app=graph_app,
        session_id=session_id,
        session={**session, "synthesizer_model": model},
        prompt=prompt,
        all_responses=responses,
        toggles=toggles or {},
        context=context,
    ):
        yield event
    db.update_debate_session(session_id, status="completed")


async def _stream_synthesis(
    graph_app,
    session_id: str,
    session: dict[str, Any],
    prompt: str,
    all_responses: dict[str, str],
    toggles: dict[str, Any],
    context: ContextSettings = DEFAULT_CONTEXT,
) -> AsyncGenerator[dict[str, Any], None]:
    synthesizer = session["synthesizer_model"]
    synthesis_thread_id = db.synthesis_thread_id(session)

    yield {"type": "debate_synthesis_start", "session_id": session_id, "model": synthesizer}

    synthesis_prompt = build_synthesis_prompt(prompt, all_responses.items(), AFTER_DEBATE)

    initial_state = {
        "active_peer": synthesizer,
        "messages": [("user", synthesis_prompt)],
        "toggles": {**toggles, "use_rag": False},
        "is_deliberation": False,
        "current_thesis": "",
        "documents": {},
    }
    config = context.apply(thread_config(synthesis_thread_id))
    run_id = tag_run(config)
    buffer = ""
    checkpoint_id = ""

    try:
      async with asyncio.timeout(MODEL_TIMEOUT_SECONDS):
        async for event in graph_app.astream_events(initial_state, config, version="v2", exclude_tags=[INTERNAL_TAG]):
            kind = event.get("event")
            if kind == "on_chat_model_stream":
                node_name = event.get("metadata", {}).get("langgraph_node", "")
                if node_name != "draft":
                    continue
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    token = extract_text(chunk.content, strip=False)
                    if token:
                        buffer += token
                        yield {
                            "type": "stream_token",
                            "token": token,
                            "model": synthesizer,
                            "session_id": session_id,
                        }
            elif kind == "on_chain_end" and event.get("name") == "LangGraph":
                final = await final_state_of_run(graph_app, synthesis_thread_id, run_id)
                if final:
                    checkpoint_id = final.config["configurable"]["checkpoint_id"]
    except asyncio.TimeoutError:
        pass  # Still emit synthesis_end with whatever was buffered

    yield {
        "type": "debate_synthesis_end",
        "session_id": session_id,
        "model": synthesizer,
        "checkpoint_id": checkpoint_id,
        "content": buffer,
        "synthesis_thread_id": synthesis_thread_id,
    }
