"""
Debate session coordinator.

Orchestrates multi-round, multi-model debates. Each model gets its own
LangGraph thread ("{parent_thread_id}::{session_id}::{model_id}"). Rounds
progress through independent answers (round 0) → cross-examination, where
each model reads its peers as the session's PeerPresentation shows them
(services/peers.py) → an optional synthesis, which maps the arguments for the
user rather than declaring a consensus: debating models converge on
majorities and confident peers, so their agreement is not evidence.

Yields typed event dicts consumed by the WebSocket handler in api/debate.py.
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Container, Mapping, Optional, Sequence
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage

from app.registry import MODEL_REGISTRY, display_name
from app.core import database as db
from app.services.convergence import build_convergence_check
from app.services.context import DEFAULT_CONTEXT, ContextSettings
from app.services.documents import DOCUMENT_THREAD_CONFIG_KEY, attach_documents
from app.services.peers import (
    DEFAULT_PEER_LABELS,
    PEER_PRESENTATIONS,
    PeerPresentation,
    labelled,
    peer_presentation,
)
from app.services.synthesis import ARGUMENT_MAP, build_synthesis_prompt
from app.services.runs import (
    DEBATE_RECORD_KEY,
    seed_thread,
    seeded_message_count,
    thread_config,
)
from app.utils.helpers import extract_text

log = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────────

# Per-model budget for one round's graph run (summarise → draft and the
# pass-through nodes after it). A reply whose draft already finished is kept
# even if the later nodes run past it.
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
    peer_labels: str = DEFAULT_PEER_LABELS,
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
    if peer_labels not in PEER_PRESENTATIONS:
        raise ValueError(f"peer_labels must be one of: {', '.join(PEER_PRESENTATIONS)}")


def create_session(
    parent_thread_id: str,
    participants: list[str],
    termination_policy: dict[str, Any],
    auto_synthesize: bool = False,
    synthesizer_model: Optional[str] = None,
    known_models: Container[str] = MODEL_REGISTRY,
    peer_labels: str = DEFAULT_PEER_LABELS,
) -> dict[str, Any]:
    check_session_config(participants, termination_policy, synthesizer_model, known_models, peer_labels)
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
        "status": "pending",
        "termination_policy": termination_policy,
        "auto_synthesize": auto_synthesize,
        "synthesizer_model": synthesizer_model,
        # Stored so a restored session (a redirect, a later synthesis) keeps
        # presenting peers the way its earlier rounds did.
        "peer_labels": peer_labels,
    }
    db.create_debate_session(session)
    return session


def session_peers(session: Mapping[str, Any]) -> PeerPresentation:
    """How this session's participants are shown to each other, the judge and the synthesizer."""
    participants = list(dict.fromkeys(session["participants"]))
    return peer_presentation(session.get("peer_labels"), session["session_id"], participants)


def peer_legend(session: Mapping[str, Any]) -> dict[str, str]:
    """model id → the label the models used for it, for the reader of the
    debate; empty when the models saw each other's ids."""
    peers = session_peers(session)
    labels = {m: peers.label(m) for m in session["participants"]}
    return {m: label for m, label in labels.items() if label != m}


# ─── Core coordinator ────────────────────────────────────────────────────────


class DebateRefused(ValueError):
    """The debate can't run as asked (another client runs it, the round cap,
    a checkpoint that doesn't exist); the message says why."""


async def run_debate(
    graph_app,
    session_id: str,
    prompt: str,
    toggles: Optional[dict[str, Any]] = None,
    documents: Optional[dict[str, str]] = None,
    parent_checkpoint_id: Optional[str] = None,
    control: Optional[DebateControl] = None,
    context: Optional[ContextSettings] = None,
    *,
    document_names: Optional[Sequence[str]] = None,
    force: bool = False,
) -> AsyncGenerator[dict[str, Any], None]:
    """Run a debate on ``prompt``. Yields event dicts:

    debate_session_created, debate_round_start,
    stream_start, stream_token, stream_end,
    debate_round_end (with the round's ``verdict`` when an early-stop check ran),
    debate_converged, debate_synthesis_start, debate_synthesis_end,
    debate_session_status, error

    A session with rounds already is redirected: the new question is stored
    and its rounds follow the earlier ones, each lane keeping what was said.
    A fresh session may start from ``parent_checkpoint_id`` of the parent
    thread. ``toggles`` and ``context`` (None: the start's, as stored) apply
    to every round. The run owns the session's status: it claims the session
    (refused while another client runs it, unless ``force``) and leaves it
    completed, or interrupted if it stops early.
    """
    async with _claimed(session_id, force) as claim:
        if claim.refusal:
            yield claim.refusal
            return
        session = claim.session
        done = await debate_rounds(graph_app, session)
        start = _rounds_run(done)
        policy = session["termination_policy"]
        try:
            rounds = _rounds_allowed(start, policy.get("max_rounds", DEFAULT_ROUNDS))
            toggles, context = _run_settings(session, toggles, context)
            if parent_checkpoint_id and start:
                raise DebateRefused("A debate that has rounds can't start again from a checkpoint; redirect it instead.")
            parent_thread_id = session["parent_thread_id"]
            if parent_checkpoint_id:
                parent = await graph_app.aget_state(thread_config(parent_thread_id, parent_checkpoint_id))
                if parent is None or parent.created_at is None:
                    # Seeding from it would quietly start the debate from nothing.
                    raise DebateRefused(f"Checkpoint {parent_checkpoint_id} not found on thread {parent_thread_id}.")
        except DebateRefused as e:
            yield _error(session_id, str(e))
            return

        # A debate started from a fresh session writes only to its sub-threads,
        # so the parent has no checkpoints; without a title row list_threads
        # never shows it and the debate can't be found again in the sidebar.
        from app.services.chat import name_new_thread

        await name_new_thread(parent_thread_id, prompt or ", ".join(session["participants"]), kind="debate")
        claim.ran()
        yield _created(session)

        if parent_checkpoint_id:
            await seed_from_parent(
                graph_app, parent_thread_id, parent_checkpoint_id,
                [session["thread_ids"][m] for m in _participants(session)],
            )
            await asyncio.to_thread(db.update_debate_session, session_id, parent_checkpoint_id=parent_checkpoint_id)
        if not start:
            # What continuing and redirecting reuse when they name nothing.
            await asyncio.to_thread(db.update_debate_session, session_id, settings={
                "system_prompt": context.system_prompt, "summarizer": context.summarizer, "toggles": dict(toggles),
            })
        await asyncio.to_thread(db.append_debate_entry, session_id, "questions", {"round": start, "prompt": prompt})

        # The start frame's documents are in context for every round. Their
        # content is stored once, for the parent thread; each participant's
        # turns name the files and read them from there. A redirect without
        # documents keeps the debate's.
        if documents:
            document_names = await attach_documents(context.apply(thread_config(parent_thread_id)), documents)
        elif document_names is not None:
            # Files already kept for the parent thread (uploaded, or attached before).
            document_names = list(document_names)
        else:
            document_names = await _debate_documents(graph_app, session)

        async for event in _run_rounds(
            graph_app, db.get_debate_session(session_id) or session, prompt, toggles, document_names,
            control or DebateControl(), context,
            start_round=start, rounds=rounds, previous={}, question_round=start,
        ):
            if event.get("type") == "debate_session_status" and event.get("status") == "completed":
                claim.completed()
            yield event


async def continue_debate(
    graph_app,
    session_id: str,
    rounds: int = 1,
    inject: Sequence[str] = (),
    toggles: Optional[dict[str, Any]] = None,
    control: Optional[DebateControl] = None,
    context: Optional[ContextSettings] = None,
    *,
    force: bool = False,
) -> AsyncGenerator[dict[str, Any], None]:
    """Run ``rounds`` more rounds of a debate that stopped (finished, stopped
    early, paused by ending the run, or interrupted), with ``inject`` added to
    the first new round's prompts. Same events as run_debate.

    This is how a client without a live connection pauses (run fewer
    rounds), resumes and injects: every round reads the previous one from the
    sub-threads, so nothing about a running debate needs to stay in memory.
    The question and attached documents are the debate's own; ``toggles``
    and ``context`` default to the start's.
    """
    async with _claimed(session_id, force) as claim:
        if claim.refusal:
            yield claim.refusal
            return
        session = claim.session
        done = await debate_rounds(graph_app, session)
        try:
            if not done:
                raise DebateRefused("This debate has no rounds yet; start it first.")
            if rounds < 1:
                raise DebateRefused("rounds must be at least 1.")
            start = _rounds_run(done)
            allowed = _rounds_allowed(start, rounds)
            toggles, context = _run_settings(session, toggles, context)
        except DebateRefused as e:
            yield _error(session_id, str(e))
            return
        claim.ran()
        previous = {m: replies[-1] for m, replies in done.items() if replies}
        control = control or DebateControl()
        for message in inject:
            if message.strip():
                control.inject(message.strip())

        question = await current_question(graph_app, session)
        yield _created(session)
        async for event in _run_rounds(
            graph_app, session, question["prompt"], toggles, await _debate_documents(graph_app, session),
            control, context,
            start_round=start, rounds=allowed, previous=previous, question_round=question["round"],
        ):
            if event.get("type") == "debate_session_status" and event.get("status") == "completed":
                claim.completed()
            yield event


class _Claim:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.session: Optional[dict[str, Any]] = None
        self.prior_status: Optional[str] = None
        self.refusal: Optional[dict[str, Any]] = None
        self.started = False
        self.finished = False

    def ran(self) -> None:
        self.started = True

    def completed(self) -> None:
        self.finished = True


class _claimed:
    """Claim a session for one run and settle its status when the run ends:
    completed, interrupted if rounds started but didn't finish (a stop, a
    disconnect, Ctrl-C, an error), or back to what it was if nothing ran."""

    def __init__(self, session_id: str, force: bool):
        self.claim = _Claim(session_id)
        self.force = force

    async def __aenter__(self) -> _Claim:
        claim = self.claim
        session = await asyncio.to_thread(db.get_debate_session, claim.session_id)
        if not session:
            claim.refusal = {"type": "error", "message": f"Session {claim.session_id} not found"}
            return claim
        claim.prior_status = session.get("status")
        if not await asyncio.to_thread(db.claim_debate_session, claim.session_id, self.force):
            claim.refusal = _error(
                claim.session_id,
                f"Debate {claim.session_id} is running in another client (the web UI or another command). "
                "Continue it once that run stops, or force it if that run is gone.",
            )
            claim.prior_status = None
            return claim
        claim.session = {**session, "status": "running"}
        return claim

    async def __aexit__(self, *exc) -> None:
        claim = self.claim
        if claim.session is None or claim.finished:
            return
        status = "interrupted" if claim.started else (claim.prior_status or "pending")
        # Shielded: this runs while the run is being cancelled.
        await asyncio.shield(asyncio.to_thread(db.update_debate_session, claim.session_id, status=status))


def _error(session_id: str, message: str) -> dict[str, Any]:
    return {"type": "error", "session_id": session_id, "message": message}


def _created(session: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "debate_session_created",
        "session_id": session["session_id"],
        "participants": _participants(session),
        "thread_ids": session["thread_ids"],
    }


def _participants(session: Mapping[str, Any]) -> list[str]:
    # Sessions stored before duplicates were rejected may list a model twice;
    # it has one sub-thread, so it debates once.
    return list(dict.fromkeys(session["participants"]))


def _rounds_run(done: Mapping[str, Sequence[str]]) -> int:
    return max((len(replies) for replies in done.values()), default=0)


def _rounds_allowed(start: int, wanted: int) -> int:
    """How many of ``wanted`` rounds may run after ``start``: a session runs
    at most MAX_ROUNDS in all, however many calls it takes, since the round
    cap is what bounds one session's spend."""
    left = MAX_ROUNDS - start
    if left <= 0:
        raise DebateRefused(f"This debate has run {start} rounds, the limit of {MAX_ROUNDS}; start a new one.")
    return max(1, min(wanted, left))


def _run_settings(session: Mapping[str, Any], toggles, context):
    """The run's toggles and context: as given, else the start's (stored)."""
    stored = session.get("settings") or {}
    if toggles is None:
        toggles = dict(stored.get("toggles") or {})
    if context is None:
        context = ContextSettings.from_frame(stored) if stored else DEFAULT_CONTEXT
    return toggles, context


async def _debate_documents(graph_app, session: Mapping[str, Any]) -> list[str]:
    """The attached documents a debate's rounds name (stored for the parent)."""
    for model_id in session["participants"]:
        thread_id = session["thread_ids"].get(model_id)
        if not thread_id:
            continue
        state = await graph_app.aget_state(thread_config(thread_id))
        names = (state.values or {}).get("attached_documents") if state else None
        if names:
            return list(names)
    return []


async def _run_rounds(
    graph_app,
    session: dict[str, Any],
    prompt: str,
    toggles: dict[str, Any],
    document_names: Sequence[str],
    control: DebateControl,
    context: ContextSettings,
    *,
    start_round: int,
    rounds: int,
    previous: dict[str, str],
    question_round: int = 0,
) -> AsyncGenerator[dict[str, Any], None]:
    """Rounds ``start_round`` to ``start_round + rounds - 1``, then the
    auto-synthesis if configured; ``previous`` is the round before
    ``start_round`` (empty for a question's first round,
    ``question_round``)."""
    session_id = session["session_id"]
    participants = _participants(session)
    thread_ids = session["thread_ids"]
    peers = session_peers(session)
    convergence = build_convergence_check(session["termination_policy"], peers=peers)
    parent_thread_id = session["parent_thread_id"]

    # Track per-model responses per round for convergence detection
    prev_round_responses: dict[str, str] = dict(previous)
    curr_round_responses: dict[str, str] = {}
    single_answer = False

    for round_num in range(start_round, start_round + rounds):
        if control.paused:
            await asyncio.to_thread(db.update_debate_session, session_id, status="paused")
            yield {"type": "debate_session_status", "session_id": session_id, "status": "paused"}
            await control.resumed.wait()
            await asyncio.to_thread(db.update_debate_session, session_id, status="running")
            yield {"type": "debate_session_status", "session_id": session_id, "status": "running"}

        await asyncio.to_thread(db.update_debate_session, session_id, current_round=round_num, status="running")
        yield {"type": "debate_round_start", "session_id": session_id, "round": round_num}

        curr_round_responses = {}
        injected = control.take_injected()
        for message in injected:
            await asyncio.to_thread(db.append_debate_entry, session_id, "injected", {"round": round_num, "message": message})

        model_prompts = _build_round_prompts(
            round_num=round_num,
            prompt=prompt,
            participants=participants,
            prev_round_responses=prev_round_responses,
            peers=peers,
            injected=injected,
            question_round=question_round,
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
            document_names=document_names,
            document_thread_id=parent_thread_id,
            curr_round_responses=curr_round_responses,
            context=context,
            deliberation=round_num > question_round and peers.names_in_history,
        ):
            yield event

        answered = [m for m in participants if curr_round_responses.get(m)]
        if round_num == question_round and len(answered) < 2:
            # One answer has nothing to debate: later rounds would only have
            # that model answer itself, and a map of one position maps nothing.
            failed = [m for m in participants if m not in answered]
            yield {"type": "debate_round_end", "session_id": session_id, "round": round_num}
            if start_round + rounds > round_num + 1 or session.get("auto_synthesize"):
                yield _error(session_id, f"Only {len(answered)} participant(s) answered ({', '.join(failed)} failed), "
                                         "so the debate stops here. Fix the failing model and continue the debate.")
            single_answer = True
            break

        # Check stopping conditions after a question's first round (need a
        # prior round to compare). Done before the round_end event so a
        # single event can carry the score — emitting two made the client
        # refetch the tree twice.
        verdict = None
        if convergence and round_num > question_round and prev_round_responses:
            verdict = await convergence.evaluate(prev_round_responses, curr_round_responses)
        score = verdict.score if verdict else None

        round_end: dict[str, Any] = {
            "type": "debate_round_end",
            "session_id": session_id,
            "round": round_num,
        }
        if verdict is not None:
            round_end["verdict"] = {"method": verdict.method, "reached": verdict.converged,
                                    "score": verdict.score, "reason": verdict.reason}
        if score is not None:
            round_end["convergence_score"] = score
            await asyncio.to_thread(db.record_round_score, session_id, round_num, score)
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
        yield _error(session_id, "The debate ended before your injected message could be used: " + " / ".join(unused))

    # Auto-synthesize if configured
    if session.get("auto_synthesize") and not single_answer:
        async for event in _stream_synthesis(
            graph_app=graph_app,
            session_id=session_id,
            session={**session, "synthesizer_model": db.session_synthesizer(session)},
            prompt=prompt,
            rounds=await debate_rounds(graph_app, session),
            toggles=toggles,
            context=context,
        ):
            yield event

    await asyncio.to_thread(db.update_debate_session, session_id, status="completed")
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
    peers: PeerPresentation,
    injected: Optional[list[str]] = None,
    question_round: int = 0,
) -> dict[str, str]:
    """A question's first round (``question_round``: 0, or where a redirect
    started): the question alone. Later rounds: each model sees all peers'
    previous responses, labelled and ordered by `peers`.

    Messages the user injected since the last round are appended to every prompt.
    """
    prompts = _base_round_prompts(round_num, prompt, participants, prev_round_responses, peers, question_round)
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
    peers: PeerPresentation,
    question_round: int = 0,
) -> dict[str, str]:
    if round_num == question_round or not prev_round_responses:
        return {m: prompt for m in participants}

    # One order per round, shared by every participant's prompt.
    listed = peers.order(list(prev_round_responses), round_num)
    prompts: dict[str, str] = {}
    for model_id in participants:
        peer_context = "\n\n".join(
            f"[{peers.label(peer)}]:\n{prev_round_responses[peer]}"
            for peer in listed
            if peer != model_id
        )
        prompts[model_id] = (
            f"Original question: {prompt}\n\n"
            f"Other models' previous responses:\n{peer_context}\n\n"
            f"{peers.introduce(model_id)} Critically analyze the other models' arguments. "
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
    curr_round_responses: dict[str, str],
    context: ContextSettings = DEFAULT_CONTEXT,
    document_names: Sequence[str] = (),
    document_thread_id: Optional[str] = None,
    deliberation: bool = False,
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream all models for one round concurrently, interleaving their tokens.

    Each participant's turn is chat.stream_turn on its own sub-thread, from
    that thread's head (the seeded conversation, or the last round).
    `document_names` are attached documents already stored for
    `document_thread_id` (the parent thread). `deliberation` runs the graph's
    deliberation mode, which shows each earlier turn tagged with its model id."""
    from app.services.chat import stream_turn

    queue: asyncio.Queue = asyncio.Queue()
    configurable = {DOCUMENT_THREAD_CONFIG_KEY: document_thread_id} if document_thread_id else None

    async def _model_producer(model_id: str):
        buffer = ""
        drafted = False
        try:
            await queue.put({"type": "stream_start", "model": model_id, "session_id": session_id, "round": round_num})
            end = None
            async with asyncio.timeout(MODEL_TIMEOUT_SECONDS):
                async for event in stream_turn(
                    graph_app,
                    thread_ids[model_id],
                    None,
                    message=model_prompts[model_id],
                    model=model_id,
                    toggles=toggles,
                    document_names=document_names,
                    is_deliberation=deliberation,
                    context=context,
                    configurable=configurable,
                    with_path=False,
                ):
                    if event["type"] == "token":
                        buffer += event["token"]
                        await queue.put({"type": "stream_token", "token": event["token"], "model": model_id,
                                         "session_id": session_id})
                    elif event["type"] == "drafted":
                        drafted = True
                    elif event["type"] == "end":
                        end = event
            # The stored reply, which exists even for a model that doesn't stream.
            reply = (end or {}).get("content") or buffer
            await queue.put({
                "type": "stream_end", "model": model_id, "session_id": session_id, "round": round_num,
                "checkpoint_id": (end or {}).get("checkpoint_id", ""), "content": reply,
            })
            curr_round_responses[model_id] = reply
        except TimeoutError:
            if drafted and buffer:
                # The answer is complete; only the post-draft bookkeeping ran long.
                await queue.put({"type": "stream_end", "model": model_id, "session_id": session_id,
                                 "round": round_num, "checkpoint_id": "", "content": buffer})
                curr_round_responses[model_id] = buffer
            else:
                await queue.put({"type": "error", "model": model_id, "session_id": session_id, "round": round_num,
                                 "message": f"{model_id} timed out after {MODEL_TIMEOUT_SECONDS}s"})
                curr_round_responses[model_id] = ""
        except Exception as e:
            await queue.put({"type": "error", "model": model_id, "session_id": session_id, "round": round_num,
                             "message": str(e)})
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


async def _read_lane(graph_app, thread_id: str, attempts: int = 3) -> list:
    """A lane's messages. A read can fail while a cancelled run is still
    being stopped (e.g. right after a reload); it is retried briefly, then
    the error propagates. Skipping the lane left a transcript with the
    question but none of that participant's rounds, and an argument map
    written then silently left the participant out."""
    for attempt in range(attempts):
        try:
            return await _debate_messages(graph_app, thread_id)
        except Exception:
            if attempt == attempts - 1:
                raise
            log.warning(f"[Debate] reading {thread_id} failed; retrying")
            await asyncio.sleep(0.2 * (attempt + 1))
    return []


async def debate_rounds(graph_app, session: Mapping[str, Any]) -> dict[str, list[str]]:
    """Each participant's replies, round by round, read from its sub-thread.

    Every round begins with a prompt (a human message); the last reply after
    it is that round's answer, "" when the model failed that round, so a
    failure doesn't shift later rounds. A participant that never replied has
    no entry, even when its sub-thread was seeded with a conversation that
    ends on someone's answer.
    """
    rounds: dict[str, list[str]] = {}
    for model_id in session["participants"]:
        thread_id = session["thread_ids"].get(model_id)
        if not thread_id:
            continue
        msgs = await _read_lane(graph_app, thread_id)
        replies: list[str] = []
        for m in msgs:
            kind = getattr(m, "type", "")
            if kind == "human":
                replies.append("")
            elif kind == "ai" and replies:
                replies[-1] = extract_text(m.content)
        if any(replies):
            rounds[model_id] = replies
    return rounds


async def debate_questions(graph_app, session: Mapping[str, Any]) -> list[dict[str, Any]]:
    """[{round, prompt}]: the question each stretch of rounds answered, in
    order (a redirect starts a new one). Sessions stored before questions
    were kept have their first one recovered from the lanes."""
    questions = sorted(session.get("questions") or [], key=lambda q: q["round"])
    if not questions or questions[0]["round"] > 0:
        first = await _first_prompt(graph_app, session)
        if first or not questions:
            questions = [{"round": 0, "prompt": first}, *questions]
    return questions


async def current_question(graph_app, session: Mapping[str, Any]) -> dict[str, Any]:
    """The question the latest rounds answer: {round, prompt}."""
    return (await debate_questions(graph_app, session))[-1]


def _question_at(questions: Sequence[Mapping[str, Any]], round_num: int) -> Mapping[str, Any]:
    return next((q for q in reversed(questions) if q["round"] <= round_num), questions[0])


def _participant_record(replies: Sequence[str], questions: Sequence[Mapping[str, Any]] = ()) -> str:
    """One participant's debate as the synthesizer reads it. A round that
    starts a new question (a redirect) says so."""
    starts = {q["round"]: q["prompt"] for q in questions if q["round"] > 0}
    parts = []
    for i, text in enumerate(replies):
        if i in starts:
            heading = f"Round {i + 1} (independent answer to a new question: {starts[i]})"
        else:
            heading = f"Round {i + 1}{' (independent answer)' if i == 0 else ''}"
        parts.append(f"{heading}:\n{text or '(no answer this round)'}")
    return "\n\n".join(parts)


async def _first_prompt(graph_app, session: Mapping[str, Any]) -> str:
    """The round-0 prompt as the lanes recorded it: the first message of
    each participant's debate."""
    for model_id in session["participants"]:
        thread_id = session["thread_ids"].get(model_id)
        if not thread_id:
            continue
        msgs = await _debate_messages(graph_app, thread_id)
        first = next((m for m in msgs if getattr(m, "type", "") == "human"), None)
        if first is not None:
            return extract_text(first.content)
    return ""


# ─── Reading a debate ────────────────────────────────────────────────────────


def session_view(session: Mapping[str, Any]) -> dict[str, Any]:
    """A session as clients read it: no internal lane ids, the question, the
    rounds run (1-based count) and a timezone-aware creation time."""
    questions = sorted(session.get("questions") or [], key=lambda q: q["round"])
    created = session.get("created_at")
    if isinstance(created, str) and created and "T" not in created:
        created = created.replace(" ", "T") + "+00:00"  # SQLite CURRENT_TIMESTAMP is UTC
    return {
        "session_id": session["session_id"],
        "thread_id": session["parent_thread_id"],
        "parent_thread_id": session["parent_thread_id"],
        "question": questions[-1]["prompt"] if questions else None,
        "questions": questions,
        "participants": session["participants"],
        "labels": peer_legend(session),
        "status": session.get("status"),
        "current_round": session.get("current_round"),
        "termination_policy": session["termination_policy"],
        "auto_synthesize": session.get("auto_synthesize"),
        "synthesizer_model": db.session_synthesizer(dict(session)),
        "peer_labels": session.get("peer_labels"),
        "parent_checkpoint_id": session.get("parent_checkpoint_id"),
        "round_scores": session.get("round_scores") or {},
        "created_at": created,
    }


async def debate_transcript(graph_app, session_id: str) -> dict[str, Any]:
    """Everything a debate said, aligned by round: {session, question,
    labels, rounds: [{round, question, responses, errors, score}],
    synthesis: {model, content} | None, injected: [{round, message}]}.

    A participant that failed a round has an ``errors`` entry for it, so
    later rounds keep their numbers. Raises ValueError for an unknown session."""
    session = db.get_debate_session(session_id)
    if not session:
        raise ValueError(f"Debate session {session_id} not found.")
    replies = await debate_rounds(graph_app, session)
    questions = await debate_questions(graph_app, session)
    scores = session.get("round_scores") or {}
    rounds = []
    for i in range(_rounds_run(replies)):
        responses = {m: r[i] for m, r in replies.items() if i < len(r) and r[i]}
        rounds.append({
            "round": i,
            "question": _question_at(questions, i)["prompt"],
            "responses": responses,
            "errors": {m: "no answer this round" for m in _participants(session) if m not in responses},
            "score": scores.get(str(i)),
        })
    synthesis = await synthesis_text(graph_app, session)
    return {
        "session": session_view(session),
        "question": questions[-1]["prompt"],
        "labels": peer_legend(session),
        "rounds": rounds,
        "synthesis": {"model": db.session_synthesizer(session), "model_name": display_name(db.session_synthesizer(session)),
                      "content": synthesis} if synthesis else None,
        "injected": session.get("injected") or [],
    }


# ─── Continuing the conversation ─────────────────────────────────────────────


def debate_record_text(
    session: Mapping[str, Any],
    rounds: Mapping[str, Sequence[str]],
    synthesis: str = "",
    questions: Sequence[Mapping[str, Any]] = (),
) -> str:
    """The whole debate as one message: every round of every participant
    under the label the models used, which model that label was, each
    question it answered, and the synthesis if one was written."""
    peers = session_peers(session)
    records = {m: _participant_record(replies, questions) for m, replies in rounds.items()}
    who = ", ".join(
        f"{peers.label(m)} = {display_name(m)}" if peers.label(m) != m else display_name(m)
        for m in sorted(rounds, key=peers.label)
    )
    n_rounds = max((len(r) for r in rounds.values()), default=0)
    parts = [f"A debate between {who} ({n_rounds} rounds)."]
    if len(questions) > 1:
        parts.append("Questions: " + "; ".join(f"from round {q['round'] + 1}: {q['prompt']}" for q in questions))
    parts += [f"[{label}]:\n{record}" for label, record in labelled(peers, records)]
    if synthesis:
        parts.append(f"Synthesis by {display_name(db.session_synthesizer(dict(session)))}:\n{synthesis}")
    return "\n\n".join(parts)


async def debate_tree(graph_app, session: Mapping[str, Any]) -> dict[str, Any]:
    """The debate as one React Flow graph: a lane per participant, the shared
    question, the synthesis (tree.build_debate_tree)."""
    from app.services.tree import build_debate_tree, load_thread_states

    thread_ids = session["thread_ids"]

    async def lane(model_id: str):
        tid = thread_ids.get(model_id)
        return model_id, (await load_thread_states(graph_app, tid) if tid else [])

    # Every lane plus the synthesis thread, one saver pass each, in parallel.
    lanes, synthesis_states = await asyncio.gather(
        asyncio.gather(*[lane(m) for m in session["participants"]]),
        load_thread_states(graph_app, db.synthesis_thread_id(dict(session))),
    )
    return build_debate_tree(
        session=dict(session),
        all_thread_states={m: states for m, states in lanes if states},
        synthesis_states=synthesis_states,
        peer_labels=peer_legend(session),
    )


async def synthesis_text(graph_app, session: Mapping[str, Any]) -> str:
    """The debate's latest synthesis (argument map), "" if none was written."""
    state = await graph_app.aget_state(thread_config(db.synthesis_thread_id(dict(session))))
    msgs = (state.values or {}).get("messages", []) if state else []
    last = msgs[-1] if msgs else None
    return extract_text(last.content) if last is not None and last.type == "ai" else ""


# Which state of the debate a record on the parent thread wrote down.
DEBATE_RECORD_VERSION_KEY = "crucible_debate_version"


async def continue_from_debate(graph_app, session_id: str) -> str:
    """The parent-thread checkpoint a chat turn after this debate forks from.

    A debate writes only to its sub-threads, so a turn sent on the parent
    after it used to see nothing of it ("I don't see any arguments above")
    while the screen showed the whole debate. The first such turn writes the
    debate onto the parent, as the question and one message recording every
    round and the synthesis, from the checkpoint the debate started at.
    Later turns reuse that record while the debate is unchanged; once it has
    run more rounds or a new synthesis, a new record is written.
    """
    session = db.get_debate_session(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")
    parent_thread_id = session["parent_thread_id"]
    questions = await debate_questions(graph_app, session)
    rounds = await debate_rounds(graph_app, session)
    synthesis = await synthesis_text(graph_app, session)
    version = f"{_rounds_run(rounds)}:{len(questions)}:{hashlib.sha1(synthesis.encode()).hexdigest()[:12]}"
    marker = {DEBATE_RECORD_KEY: session_id, DEBATE_RECORD_VERSION_KEY: version}
    async for snapshot in graph_app.aget_state_history(thread_config(parent_thread_id), filter=marker, limit=1):
        return snapshot.config["configurable"]["checkpoint_id"]

    config = thread_config(parent_thread_id, session.get("parent_checkpoint_id"))
    config["metadata"] = dict(marker)
    # Written as the graph's last node, so the next run starts a fresh turn.
    asked = await graph_app.aupdate_state(
        config, {"messages": [HumanMessage(content=questions[-1]["prompt"])]}, as_node="synthesis"
    )
    asked["metadata"] = dict(marker)
    recorded = await graph_app.aupdate_state(
        asked,
        {
            "messages": [
                AIMessage(
                    content=debate_record_text(session, rounds, synthesis, questions),
                    additional_kwargs={DEBATE_RECORD_KEY: session_id},
                )
            ],
            "active_peer": None,
        },
        as_node="synthesis",
    )
    return recorded["configurable"]["checkpoint_id"]


async def synthesize_session(
    graph_app,
    session_id: str,
    prompt: str = "",
    synthesizer: Optional[str] = None,
    toggles: Optional[dict[str, Any]] = None,
    context: Optional[ContextSettings] = None,
    known_models: Container[str] = MODEL_REGISTRY,
    *,
    force: bool = False,
) -> AsyncGenerator[dict[str, Any], None]:
    """Map the arguments of a debate, from every round. Refused while another
    client runs the debate (unless ``force``); leaves it completed."""
    async with _claimed(session_id, force) as claim:
        if claim.refusal:
            yield claim.refusal
            return
        session = claim.session
        model = synthesizer or db.session_synthesizer(session)
        if model not in known_models:
            yield _error(session_id, f"Unknown models: {model}")
            return
        claim.ran()
        toggles, context = _run_settings(session, toggles, context)
        if not prompt:
            prompt = (await current_question(graph_app, session))["prompt"]
        async for event in _stream_synthesis(
            graph_app=graph_app,
            session_id=session_id,
            session={**session, "synthesizer_model": model},
            prompt=prompt,
            rounds=await debate_rounds(graph_app, session),
            toggles=toggles,
            context=context,
        ):
            yield event
        # Stored so readers of the session (the tree's colour, the restored
        # transcript) name the model that wrote this synthesis.
        await asyncio.to_thread(db.update_debate_session, session_id, synthesizer_model=model, status="completed")
        claim.completed()
        yield {"type": "debate_session_status", "session_id": session_id, "status": "completed"}


async def _stream_synthesis(
    graph_app,
    session_id: str,
    session: dict[str, Any],
    prompt: str,
    rounds: Mapping[str, Sequence[str]],
    toggles: dict[str, Any],
    context: ContextSettings = DEFAULT_CONTEXT,
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream the debate's argument map. `rounds` is each participant's
    replies by round (debate_rounds): changes of position can only be traced
    from every round, not from the final one.

    ``debate_synthesis_end`` always comes, with ``error`` set when the
    synthesizer failed or ran out of time (``content`` is then what arrived,
    possibly nothing): a cut-off map must not read as a complete one."""
    from app.services.chat import stream_turn

    synthesizer = session["synthesizer_model"]
    synthesis_thread_id = db.synthesis_thread_id(session)
    yield {"type": "debate_synthesis_start", "session_id": session_id, "model": synthesizer}

    questions = await debate_questions(graph_app, session)
    records = {m: _participant_record(replies, questions) for m, replies in rounds.items()}
    synthesis_prompt = build_synthesis_prompt(prompt, labelled(session_peers(session), records), ARGUMENT_MAP)

    buffer = ""
    checkpoint_id = ""
    error = None
    try:
        async with asyncio.timeout(MODEL_TIMEOUT_SECONDS):
            async for event in stream_turn(
                graph_app, synthesis_thread_id, None,
                message=synthesis_prompt, model=synthesizer,
                toggles={**toggles, "use_rag": False}, document_names=[],
                context=context, with_path=False,
            ):
                if event["type"] == "token":
                    buffer += event["token"]
                    yield {"type": "stream_token", "token": event["token"], "model": synthesizer, "session_id": session_id}
                elif event["type"] == "end":
                    checkpoint_id = event["checkpoint_id"]
                    buffer = event["content"] or buffer
    except TimeoutError:
        error = f"The synthesis timed out after {MODEL_TIMEOUT_SECONDS}s; what arrived is incomplete."
    except Exception as e:
        error = f"{synthesizer} failed to write the synthesis: {e}. Try another synthesizer."

    yield {
        "type": "debate_synthesis_end",
        "session_id": session_id,
        "model": synthesizer,
        "checkpoint_id": checkpoint_id,
        "content": buffer,
        "error": error,
        "synthesis_thread_id": synthesis_thread_id,
    }
