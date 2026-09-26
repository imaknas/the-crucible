import asyncio
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.api.deps import get_graph_app
from app.api.models import MODEL_REGISTRY, FAMILY_META
from app.core import database as db
from app.services import debate as debate_svc
from app.services.tree import build_debate_tree, load_thread_states

router = APIRouter(prefix="/debate", tags=["debate"])


# ─── Helper ──────────────────────────────────────────────────────────────────


def _family_colors() -> dict[str, str]:
    """Returns {model_id: hex_color} for all registered models."""
    colors: dict[str, str] = {}
    for model_id, cfg in MODEL_REGISTRY.items():
        family = cfg.get("family", "")
        color = FAMILY_META.get(family, {}).get("color", "#6366f1")
        colors[model_id] = color
    # Synthesis pseudo-model
    colors["synthesis"] = "#8b5cf6"
    return colors


# ─── REST: Session CRUD ───────────────────────────────────────────────────────


class TerminationPolicy(BaseModel):
    max_rounds: int = 3
    convergence_threshold: Optional[float] = None
    llm_judge: Optional[str] = None
    mode: str = "all"


class CreateSessionRequest(BaseModel):
    parent_thread_id: str
    participants: list[str]
    termination_policy: TerminationPolicy
    auto_synthesize: bool = False
    synthesizer_model: Optional[str] = None


@router.post("/sessions")
def create_session(req: CreateSessionRequest) -> dict[str, Any]:
    unknown = [m for m in req.participants if m not in MODEL_REGISTRY]
    if unknown:
        raise HTTPException(400, f"Unknown models: {unknown}")
    if len(req.participants) < 2:
        raise HTTPException(400, "A debate requires at least 2 participants")

    session = debate_svc.create_session(
        parent_thread_id=req.parent_thread_id,
        participants=req.participants,
        termination_policy=req.termination_policy.model_dump(),
        auto_synthesize=req.auto_synthesize,
        synthesizer_model=req.synthesizer_model,
    )
    return session


@router.get("/sessions")
def list_sessions(parent_thread_id: str | None = None) -> list[dict[str, Any]]:
    return db.list_debate_sessions(parent_thread_id)


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    session = db.get_debate_session(session_id)
    if not session:
        raise HTTPException(404, f"Session {session_id} not found")
    return session


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

    participants = session["participants"]
    thread_ids = session["thread_ids"]
    synthesis_thread_id = debate_svc.make_synthesis_thread_id(session["parent_thread_id"])

    all_thread_states: dict[str, list] = {}

    async def _fetch(model_id: str):
        tid = thread_ids.get(model_id)
        if not tid:
            return
        all_thread_states[model_id] = await load_thread_states(graph_app, tid)

    # Every lane plus the synthesis thread, one saver pass each, in parallel.
    _, synthesis_states = await asyncio.gather(
        asyncio.gather(*[_fetch(m) for m in participants]),
        load_thread_states(graph_app, synthesis_thread_id),
    )

    return build_debate_tree(
        session=session,
        all_thread_states=all_thread_states,
        synthesis_states=synthesis_states,
        family_colors=_family_colors(),
    )


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
        async for event in events:
            await self.send(event)

    async def _restart(self, prompt: str, data: dict, parent_checkpoint_id: Optional[str]) -> None:
        await self._cancel()
        if not db.get_debate_session(self.session_id):
            await self.send({"type": "error", "message": f"Session {self.session_id} not found"})
            return
        self.control = debate_svc.DebateControl()
        self._task = asyncio.create_task(self._run(debate_svc.run_debate(
            graph_app=self.graph_app,
            session_id=self.session_id,
            prompt=prompt,
            toggles=data.get("toggles", {}),
            documents=data.get("documents", {}),
            parent_checkpoint_id=parent_checkpoint_id,
            control=self.control,
        )))

    # ─── commands ────────────────────────────────────────────────
    async def on_start(self, data: dict) -> None:
        await self._restart(data.get("prompt", ""), data, data.get("parent_checkpoint_id"))

    async def on_redirect(self, data: dict) -> None:
        # Restart on the new prompt, from each model's current thread head.
        await self._restart(data.get("message", ""), data, None)

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
            db.update_debate_session(self.session_id, status="completed")
            await self.status("completed")
        elif action == "pause" and self.running:
            # Takes effect when the current round finishes; run_debate reports
            # "paused" at that point.
            self.control.pause()
            await self.status("pausing")
        elif action == "resume":
            self.control.resume()
            if self.running:
                db.update_debate_session(self.session_id, status="running")
                await self.status("running")

    async def on_synthesize(self, data: dict) -> None:
        # Synthesising ends the debate: stop the rounds first so the old task
        # can't be orphaned beyond the reach of stop/disconnect.
        await self._cancel()

        async def synthesize():
            await self._run(debate_svc.synthesize_session(
                self.graph_app,
                self.session_id,
                prompt=data.get("prompt", ""),
                synthesizer=data.get("synthesizer_model"),
                toggles=data.get("toggles", {}),
            ))
            await self.status("completed")

        self._task = asyncio.create_task(synthesize())

    COMMANDS = {
        "debate_start": on_start,
        "debate_redirect": on_redirect,
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
            # The debate cannot outlive its socket. Record that it was cut
            # short so a reload doesn't restore it as "running".
            if self.running:
                self._task.cancel()
                db.update_debate_session(self.session_id, status="interrupted")
