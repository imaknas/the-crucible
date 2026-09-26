"""
Debate session coordinator.

Orchestrates multi-round, multi-model debates. Each model gets its own
LangGraph thread (thread_id = "{parent_thread_id}::{model_id}"). Rounds
progress through Independent → Cross-Examination → (optional) Synthesis.

Yields typed event dicts consumed by the WebSocket handler in main.py.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional
from uuid import uuid4

from app.core import database as db
from app.services.convergence import compute_convergence, llm_judge_converged
from app.services.runs import final_state_of_run, tag_run, thread_config
from app.utils.helpers import extract_text

# ─── Constants ───────────────────────────────────────────────────────────────

SYNTHESIS_THREAD_SUFFIX = "::synthesis"

# Per-model budget for one round's graph run (summarise → draft → metadata →
# synthesis). A reply whose draft already finished is kept even if the later
# bookkeeping nodes run past it.
MODEL_TIMEOUT_SECONDS = 120


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


def make_thread_id(parent_thread_id: str, model_id: str) -> str:
    return f"{parent_thread_id}::{model_id}"


def make_synthesis_thread_id(parent_thread_id: str) -> str:
    return f"{parent_thread_id}{SYNTHESIS_THREAD_SUFFIX}"


# ─── Session factory ─────────────────────────────────────────────────────────


def create_session(
    parent_thread_id: str,
    participants: list[str],
    termination_policy: dict[str, Any],
    auto_synthesize: bool = False,
    synthesizer_model: Optional[str] = None,
) -> dict[str, Any]:
    session_id = f"debate-{uuid4().hex[:12]}"
    thread_ids = {m: make_thread_id(parent_thread_id, m) for m in participants}
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

    participants = session["participants"]
    thread_ids = session["thread_ids"]
    policy = session["termination_policy"]
    max_rounds = policy.get("max_rounds", 3)
    conv_threshold = policy.get("convergence_threshold")
    llm_judge_model = policy.get("llm_judge")
    conv_mode = policy.get("mode", "all")

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
            parent_checkpoint_id=parent_checkpoint_id if round_num == 0 else None,
            curr_round_responses=curr_round_responses,
        ):
            yield event

        # Check stopping conditions after round 0 (need at least one prior round
        # to compare). Done before the round_end event so a single event can
        # carry the score — emitting two made the client refetch the tree twice.
        converged, reason, score = False, None, None
        if round_num > 0 and prev_round_responses:
            converged, reason, score = await _check_convergence(
                graph_app=graph_app,
                session_id=session_id,
                round_num=round_num,
                prev_responses=prev_round_responses,
                curr_responses=curr_round_responses,
                conv_threshold=conv_threshold,
                conv_mode=conv_mode,
                llm_judge_model=llm_judge_model,
            )

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

        if converged:
            yield {
                "type": "debate_converged",
                "session_id": session_id,
                "round": round_num,
                "score": score,
                "reason": reason,
                "method": "judge" if llm_judge_model else "similarity",
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
        ):
            yield event

    db.update_debate_session(session_id, status="completed")
    yield {"type": "debate_session_status", "session_id": session_id, "status": "completed"}


# ─── Round helpers ───────────────────────────────────────────────────────────


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
            "Provide your updated position."
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
    parent_checkpoint_id: Optional[str],
    curr_round_responses: dict[str, str],
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream all models for one round concurrently, interleaving their tokens."""
    queue: asyncio.Queue = asyncio.Queue()
    finished: set[str] = set()

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
            langgraph_config = thread_config(
                thread_id, parent_checkpoint_id if round_num == 0 else None
            )
            run_id = tag_run(langgraph_config)

            await queue.put({
                "type": "stream_start",
                "model": model_id,
                "session_id": session_id,
                "round": round_num,
            })

            async with asyncio.timeout(MODEL_TIMEOUT_SECONDS):
                async for event in graph_app.astream_events(initial_state, langgraph_config, version="v2"):
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

    tasks = [asyncio.create_task(_model_producer(m)) for m in participants]

    try:
        while len(finished) < len(participants):
            event = await queue.get()
            if event["type"] == "__done__":
                finished.add(event["model"])
            else:
                yield event
    finally:
        # On stop/disconnect the consumer is cancelled at queue.get(); without
        # this the producers kept streaming and billing until their timeout.
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


# ─── Convergence check ───────────────────────────────────────────────────────


async def _check_convergence(
    graph_app,
    session_id: str,
    round_num: int,
    prev_responses: dict[str, str],
    curr_responses: dict[str, str],
    conv_threshold: Optional[float],
    conv_mode: str,
    llm_judge_model: Optional[str],
) -> tuple[bool, Optional[str], Optional[float]]:
    """Returns (converged, reason, score)."""
    score: Optional[float] = None
    sim_converged = False

    if conv_threshold is not None:
        score, sim_converged = await compute_convergence(
            prev_responses, curr_responses, threshold=conv_threshold, mode=conv_mode
        )

    judge_converged = False
    judge_reason: Optional[str] = None
    if llm_judge_model:
        judge_converged, judge_reason = await llm_judge_converged(
            graph_app, llm_judge_model, session_id, curr_responses
        )

    # Combine based on what's enabled
    if conv_threshold is not None and llm_judge_model:
        if conv_mode == "all":
            converged = sim_converged and judge_converged
        else:
            converged = sim_converged or judge_converged
    elif conv_threshold is not None:
        converged = sim_converged
    elif llm_judge_model:
        converged = judge_converged
    else:
        converged = False

    reason = judge_reason or (f"similarity={score:.3f}" if score is not None else None)
    return converged, reason, score


# ─── Synthesis ───────────────────────────────────────────────────────────────


async def latest_responses(graph_app, session: dict[str, Any]) -> dict[str, str]:
    """Each participant's most recent reply, read from its sub-thread head."""
    responses: dict[str, str] = {}
    for model_id in session["participants"]:
        thread_id = session["thread_ids"].get(model_id)
        if not thread_id:
            continue
        try:
            state = await graph_app.aget_state(thread_config(thread_id))
        except Exception:
            continue
        msgs = state.values.get("messages", []) if state and state.values else []
        last_ai = next((m for m in reversed(msgs) if getattr(m, "type", "") == "ai"), None)
        if last_ai is not None:
            responses[model_id] = extract_text(last_ai.content)
    return responses


async def _original_question(graph_app, session: dict[str, Any]) -> str:
    """The round-0 prompt, which every participant's sub-thread starts with.

    Sessions don't store it; the web UI passes it along, the CLI recovers it.
    """
    for model_id in session["participants"]:
        thread_id = session["thread_ids"].get(model_id)
        if not thread_id:
            continue
        state = await graph_app.aget_state(thread_config(thread_id))
        msgs = state.values.get("messages", []) if state and state.values else []
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
) -> AsyncGenerator[dict[str, Any], None]:
    synthesizer = session["synthesizer_model"]
    parent_thread_id = session["parent_thread_id"]
    synthesis_thread_id = make_synthesis_thread_id(parent_thread_id)

    yield {"type": "debate_synthesis_start", "session_id": session_id, "model": synthesizer}

    arguments = "\n\n".join(
        f"[{model}]:\n{content}" for model, content in all_responses.items()
    )
    synthesis_prompt = (
        f"Original question: {prompt}\n\n"
        f"Arguments from all models:\n{arguments}\n\n"
        "As the synthesizer, produce a single cohesive academic consensus. "
        "Where do the models converge? What are the strongest arguments? "
        "Provide a definitive, balanced conclusion."
    )

    initial_state = {
        "active_peer": synthesizer,
        "messages": [("user", synthesis_prompt)],
        "toggles": {**toggles, "use_rag": False},
        "is_deliberation": False,
        "current_thesis": "",
        "documents": {},
    }
    config = thread_config(synthesis_thread_id)
    run_id = tag_run(config)
    buffer = ""
    checkpoint_id = ""

    try:
      async with asyncio.timeout(MODEL_TIMEOUT_SECONDS):
        async for event in graph_app.astream_events(initial_state, config, version="v2"):
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
