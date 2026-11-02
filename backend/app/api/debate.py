import asyncio
import json
import logging
from contextlib import aclosing
from typing import Any, AsyncIterator, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.api.deps import get_graph_app, get_runs
from app.api.outbox import Outbox
from app.core import database as db
from app.services import debate as debate_svc
from app.services.context import ContextSettings
from app.services.live import DebateRunState, LiveRun, RunRegistry

log = logging.getLogger(__name__)

router = APIRouter(prefix="/debate", tags=["debate"])


# ─── REST: Session CRUD ───────────────────────────────────────────────────────


class TerminationPolicy(BaseModel):
    max_rounds: int = debate_svc.DEFAULT_ROUNDS
    convergence_threshold: Optional[float] = None
    llm_judge: Optional[str] = None
    mode: str = "all"


class CreateSessionRequest(BaseModel):
    parent_thread_id: str
    participants: list[str]
    termination_policy: TerminationPolicy
    auto_synthesize: bool = False
    synthesizer_model: Optional[str] = None
    # How participants see each other: "anonymous" (default) or "named".
    peer_labels: str = debate_svc.DEFAULT_PEER_LABELS


@router.post("/sessions")
def create_session(req: CreateSessionRequest) -> dict[str, Any]:
    try:
        session = debate_svc.create_session(
            parent_thread_id=req.parent_thread_id,
            participants=req.participants,
            termination_policy=req.termination_policy.model_dump(),
            auto_synthesize=req.auto_synthesize,
            synthesizer_model=req.synthesizer_model,
            peer_labels=req.peer_labels,
        )
        return {**session, "warnings": debate_svc.role_warnings(session)}
    except ValueError as e:
        raise HTTPException(400, str(e))


def _row(session: dict[str, Any]) -> dict[str, Any]:
    """The stored session plus what a reader wants (its question)."""
    view = debate_svc.session_view(session)
    return {
        **session,
        "question": view["question"],
        "questions": view["questions"],
        "created_at": view["created_at"],
        "warnings": view["warnings"],
    }


@router.get("/sessions")
def list_sessions(parent_thread_id: str | None = None) -> list[dict[str, Any]]:
    return [_row(s) for s in db.list_debate_sessions(parent_thread_id)]


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    session = db.get_debate_session(session_id)
    if not session:
        raise HTTPException(404, f"Session {session_id} not found")
    return _row(session)


@router.get("/sessions/{session_id}/transcript")
async def get_transcript(session_id: str, graph_app=Depends(get_graph_app)):
    """Every round of every participant, aligned by round, plus the synthesis."""
    try:
        return await debate_svc.debate_transcript(graph_app, session_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str):
    session = db.get_debate_session(session_id)
    if not session:
        raise HTTPException(404, f"Session {session_id} not found")
    db.delete_debate_session(session_id)


# ─── REST: Debate Tree ───────────────────────────────────────────────────────


@router.get("/sessions/{session_id}/tree")
async def get_debate_tree(session_id: str, graph_app=Depends(get_graph_app)):
    session = db.get_debate_session(session_id)
    if not session:
        raise HTTPException(404, f"Session {session_id} not found")
    return await debate_svc.debate_tree(graph_app, session)


# ─── WebSocket: Debate session ───────────────────────────────────────────────


@router.websocket("/ws/{session_id}")
async def debate_websocket(websocket: WebSocket, session_id: str, graph_app=Depends(get_graph_app),
                           runs=Depends(get_runs)):
    await websocket.accept()
    await DebateConnection(websocket, graph_app, session_id, runs.debates).serve()


class DebateConnection:
    """One client socket on one debate session.

    Each client frame type maps to a handler in COMMANDS; add a command by
    writing a handler and registering it there.

    The debate runs as a task the server owns (services/live.py), keyed by
    session, with its DebateControl: a reload, a dropped socket or a closed
    tab doesn't stop it, and pause, resume, inject, redirect and stop from
    any socket on the session reach the same run. Every socket on the
    session gets the run's frames (run_debate's events, plus the
    pausing/running/completed statuses these handlers report).

    On connect the server sends, when a run is live, one ``debate_resume``
    {session_id, status (running | pausing | paused | completed), round (the
    round in progress, null before the first), question, answers: [{model,
    content, done, checkpoint_id?, error?}] (that round's answers so far),
    synthesis: {model, content, done, error?} | null, convergence_score};
    then, always, ``attached`` {session_id, live}. Earlier rounds are the
    transcript endpoint's to tell.
    """

    def __init__(self, websocket: WebSocket, graph_app, session_id: str, runs: RunRegistry):
        self.websocket = websocket
        self.outbox = Outbox(websocket)
        self.graph_app = graph_app
        self.session_id = session_id
        self.runs = runs

    # ─── plumbing ────────────────────────────────────────────────
    def send(self, event: dict) -> None:
        """To this socket only (answers to its own frames)."""
        self.outbox.deliver(event)

    @property
    def run(self) -> Optional[LiveRun]:
        live = self.runs.live(self.session_id)
        return live[-1] if live else None

    @property
    def running(self) -> bool:
        return self.run is not None

    async def _cancel(self) -> int:
        return await self.runs.cancel(self.session_id)

    def _start(self, events_for: Callable[[debate_svc.DebateControl], AsyncIterator[dict]]) -> None:
        """Run the debate as a task the registry owns; its frames go to every
        socket on the session."""
        session_id = self.session_id

        async def body(run: LiveRun) -> None:
            events = events_for(run.state.control)
            try:
                async with aclosing(events):
                    async for event in events:
                        run.emit(event)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # The task has no other way to tell the clients; without this
                # the debate just stopped streaming.
                log.exception("[Debate WS] run failed")
                run.emit({"type": "error", "session_id": session_id, "message": f"The debate stopped: {e}"})

        self.runs.start(session_id, DebateRunState(session_id), body)

    async def _settings(self, data: dict) -> tuple[bool, Optional[ContextSettings]]:
        """(usable, the frame's context settings or None = the debate's
        stored ones); reports why a frame's settings can't be used."""
        if not ContextSettings.named_in(data):
            return True, None
        context = ContextSettings.from_frame(data)
        if problem := context.problem():
            self.send({"type": "error", "session_id": self.session_id, "message": problem})
            return False, None
        return True, context

    async def _restart(self, prompt: str, data: dict, parent_checkpoint_id: Optional[str]) -> None:
        # The session's live run first, whichever socket started it: its
        # claim on the session ends with it.
        await self._cancel()
        usable, context = await self._settings(data)
        if not usable:
            return
        graph_app, session_id = self.graph_app, self.session_id
        self._start(lambda control: debate_svc.run_debate(
            graph_app=graph_app,
            session_id=session_id,
            prompt=prompt,
            toggles=data.get("toggles"),
            documents=data.get("documents") or {},
            document_names=data.get("document_names"),
            parent_checkpoint_id=parent_checkpoint_id,
            control=control,
            context=context,
        ))

    # ─── commands ────────────────────────────────────────────────
    async def on_start(self, data: dict) -> None:
        await self._restart(data.get("prompt", ""), data, data.get("parent_checkpoint_id"))

    async def on_redirect(self, data: dict) -> None:
        # Restart on the new prompt, from each model's current thread head.
        await self._restart(data.get("message", ""), data, None)

    async def on_continue(self, data: dict) -> None:
        """More rounds of a stopped debate (e.g. one interrupted by a server
        restart), with an optional message injected into the first."""
        await self._cancel()
        usable, context = await self._settings(data)
        if not usable:
            return
        message = (data.get("message") or "").strip()
        graph_app, session_id = self.graph_app, self.session_id
        self._start(lambda control: debate_svc.continue_debate(
            graph_app,
            session_id,
            rounds=int(data.get("rounds") or 1),
            inject=[message] if message else [],
            toggles=data.get("toggles"),
            control=control,
            context=context,
        ))

    async def on_inject(self, data: dict) -> None:
        message = (data.get("message") or "").strip()
        if not message:
            return
        run = self.run
        if run is None:
            self.send({"type": "error", "session_id": self.session_id, "message": "No debate is running to add that to."})
            return
        run.state.control.inject(message)
        self.send({"type": "debate_session_status", "session_id": self.session_id, "status": "inject_queued"})

    async def on_control(self, data: dict) -> None:
        action = data.get("action")
        run = self.run
        if action == "stop":
            if not await self._cancel():
                return
            await asyncio.to_thread(db.update_debate_session, self.session_id, status="completed")
            self.runs.publish(self.session_id, self._status("completed"))
        elif action == "pause" and run is not None:
            # Takes effect when the current round finishes; run_debate reports
            # "paused" at that point.
            run.state.control.pause()
            run.emit(self._status("pausing"))
        elif action == "resume" and run is not None:
            run.state.control.resume()
            await asyncio.to_thread(db.update_debate_session, self.session_id, status="running")
            run.emit(self._status("running"))

    def _status(self, status: str) -> dict:
        return {"type": "debate_session_status", "session_id": self.session_id, "status": status}

    async def on_synthesize(self, data: dict) -> None:
        # Synthesising ends the debate: stop the rounds first.
        await self._cancel()
        usable, context = await self._settings(data)
        if not usable:
            return
        graph_app, session_id = self.graph_app, self.session_id
        self._start(lambda _control: debate_svc.synthesize_session(
            graph_app,
            session_id,
            prompt=data.get("prompt", ""),
            synthesizer=data.get("synthesizer_model"),
            toggles=data.get("toggles"),
            context=context,
        ))

    COMMANDS = {
        "debate_start": on_start,
        "debate_redirect": on_redirect,
        "debate_continue": on_continue,
        "debate_inject": on_inject,
        "debate_control": on_control,
        "debate_synthesize": on_synthesize,
    }

    async def serve(self) -> None:
        writer = asyncio.create_task(self.outbox.drain())
        live = self.runs.watch(self.session_id, self.outbox.deliver)
        self.send({"type": "attached", "session_id": self.session_id, "live": bool(live)})
        try:
            while True:
                raw = await self.websocket.receive_text()
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                handler = self.COMMANDS.get(data.get("type"))
                if handler:
                    await handler(self, data)
        except WebSocketDisconnect:
            pass
        finally:
            # The debate goes on; only this socket stops watching it.
            self.runs.unwatch(self.session_id, self.outbox.deliver)
            writer.cancel()
