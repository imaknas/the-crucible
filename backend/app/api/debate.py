import asyncio
import json
import logging
from contextlib import aclosing
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.api.deps import get_graph_app
from app.core import database as db
from app.services import debate as debate_svc
from app.services.context import ContextSettings

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
        return debate_svc.create_session(
            parent_thread_id=req.parent_thread_id,
            participants=req.participants,
            termination_policy=req.termination_policy.model_dump(),
            auto_synthesize=req.auto_synthesize,
            synthesizer_model=req.synthesizer_model,
            peer_labels=req.peer_labels,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


def _row(session: dict[str, Any]) -> dict[str, Any]:
    """The stored session plus what a reader wants (its question)."""
    view = debate_svc.session_view(session)
    return {**session, "question": view["question"], "questions": view["questions"], "created_at": view["created_at"]}


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
async def debate_websocket(websocket: WebSocket, session_id: str, graph_app=Depends(get_graph_app)):
    await websocket.accept()
    await DebateConnection(websocket, graph_app, session_id).serve()


class DebateConnection:
    """One client socket driving one debate session.

    Each client frame type maps to a handler in COMMANDS; add a command by
    writing a handler and registering it there. The debate runs as a task
    owned by this connection and cannot outlive it.
    """

    def __init__(self, websocket: WebSocket, graph_app, session_id: str):
        self.websocket = websocket
        self.graph_app = graph_app
        self.session_id = session_id
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self.control = debate_svc.DebateControl()

    # ─── plumbing ────────────────────────────────────────────────
    async def send(self, event: dict) -> None:
        async with self._lock:
            try:
                await self.websocket.send_json(event)
            except (RuntimeError, WebSocketDisconnect):
                pass

    async def status(self, status: str) -> None:
        await self.send({"type": "debate_session_status", "session_id": self.session_id, "status": status})

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _cancel(self) -> None:
        if self.running:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None

    async def _run(self, events) -> None:
        try:
            async with aclosing(events):
                async for event in events:
                    await self.send(event)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # The task has no other way to tell the client; without this the
            # debate just stopped streaming.
            log.exception("[Debate WS] run failed")
            await self.send({"type": "error", "session_id": self.session_id, "message": f"The debate stopped: {e}"})

    async def _settings(self, data: dict) -> tuple[bool, Optional[ContextSettings]]:
        """(usable, the frame's context settings or None = the debate's
        stored ones); reports why a frame's settings can't be used."""
        if not ContextSettings.named_in(data):
            return True, None
        context = ContextSettings.from_frame(data)
        if problem := context.problem():
            await self.send({"type": "error", "session_id": self.session_id, "message": problem})
            return False, None
        return True, context

    async def _restart(self, prompt: str, data: dict, parent_checkpoint_id: Optional[str]) -> None:
        # Our own run first: its claim on the session ends with it.
        await self._cancel()
        usable, context = await self._settings(data)
        if not usable:
            return
        self.control = debate_svc.DebateControl()
        self._task = asyncio.create_task(self._run(debate_svc.run_debate(
            graph_app=self.graph_app,
            session_id=self.session_id,
            prompt=prompt,
            toggles=data.get("toggles"),
            documents=data.get("documents") or {},
            document_names=data.get("document_names"),
            parent_checkpoint_id=parent_checkpoint_id,
            control=self.control,
            context=context,
        )))

    # ─── commands ────────────────────────────────────────────────
    async def on_start(self, data: dict) -> None:
        await self._restart(data.get("prompt", ""), data, data.get("parent_checkpoint_id"))

    async def on_redirect(self, data: dict) -> None:
        # Restart on the new prompt, from each model's current thread head.
        await self._restart(data.get("message", ""), data, None)

    async def on_continue(self, data: dict) -> None:
        """More rounds of a stopped debate (e.g. one interrupted by a reload),
        with an optional message injected into the first."""
        await self._cancel()
        usable, context = await self._settings(data)
        if not usable:
            return
        self.control = debate_svc.DebateControl()
        message = (data.get("message") or "").strip()
        self._task = asyncio.create_task(self._run(debate_svc.continue_debate(
            self.graph_app,
            self.session_id,
            rounds=int(data.get("rounds") or 1),
            inject=[message] if message else [],
            toggles=data.get("toggles"),
            control=self.control,
            context=context,
        )))

    async def on_inject(self, data: dict) -> None:
        message = (data.get("message") or "").strip()
        if not message:
            return
        if not self.running:
            await self.send({"type": "error", "session_id": self.session_id, "message": "No debate is running to add that to."})
            return
        self.control.inject(message)
        await self.status("inject_queued")

    async def on_control(self, data: dict) -> None:
        action = data.get("action")
        if action == "stop":
            await self._cancel()
            await asyncio.to_thread(db.update_debate_session, self.session_id, status="completed")
            await self.status("completed")
        elif action == "pause" and self.running:
            # Takes effect when the current round finishes; run_debate reports
            # "paused" at that point.
            self.control.pause()
            await self.status("pausing")
        elif action == "resume":
            self.control.resume()
            if self.running:
                await asyncio.to_thread(db.update_debate_session, self.session_id, status="running")
                await self.status("running")

    async def on_synthesize(self, data: dict) -> None:
        # Synthesising ends the debate: stop the rounds first so the old task
        # can't be orphaned beyond the reach of stop/disconnect.
        await self._cancel()
        usable, context = await self._settings(data)
        if not usable:
            return

        async def synthesize():
            await self._run(debate_svc.synthesize_session(
                self.graph_app,
                self.session_id,
                prompt=data.get("prompt", ""),
                synthesizer=data.get("synthesizer_model"),
                toggles=data.get("toggles"),
                context=context,
            ))

        self._task = asyncio.create_task(synthesize())

    COMMANDS = {
        "debate_start": on_start,
        "debate_redirect": on_redirect,
        "debate_continue": on_continue,
        "debate_inject": on_inject,
        "debate_control": on_control,
        "debate_synthesize": on_synthesize,
    }

    async def serve(self) -> None:
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
            # The debate cannot outlive its socket. The run records that it
            # was cut short, so a reload doesn't restore it as "running".
            if self.running:
                self._task.cancel()
