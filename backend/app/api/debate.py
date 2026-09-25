import asyncio
import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

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
async def get_debate_tree(session_id: str):
    session = db.get_debate_session(session_id)
    if not session:
        raise HTTPException(404, f"Session {session_id} not found")

    # We need graph_app from app state — accessed via request in the router.
    # Since this router doesn't have access to server.state directly,
    # we use a dependency-injection pattern via a module-level ref set by main.py.
    graph_app = _get_graph_app()
    if not graph_app:
        raise HTTPException(503, "Graph not ready")

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


# ─── graph_app injection ─────────────────────────────────────────────────────
# main.py calls set_graph_app(app.state.graph_app) after the lifespan starts.

_graph_app_ref = None


def set_graph_app(app):
    global _graph_app_ref
    _graph_app_ref = app


def _get_graph_app():
    return _graph_app_ref


# ─── WebSocket: Debate session ───────────────────────────────────────────────


@router.websocket("/ws/{session_id}")
async def debate_websocket(websocket: WebSocket, session_id: str):
    await websocket.accept()
    graph_app = _get_graph_app()
    if not graph_app:
        await websocket.send_json({"type": "error", "message": "Graph not ready"})
        await websocket.close()
        return

    ws_lock = asyncio.Lock()
    active_task: Optional[asyncio.Task] = None
    control = debate_svc.DebateControl()

    async def _send(event: dict):
        async with ws_lock:
            try:
                await websocket.send_json(event)
            except (RuntimeError, WebSocketDisconnect):
                pass

    def _debate_running() -> bool:
        return active_task is not None and not active_task.done()

    async def _cancel_active():
        nonlocal active_task
        if _debate_running():
            active_task.cancel()
            try:
                await active_task
            except (asyncio.CancelledError, Exception):
                pass
        active_task = None

    async def _run_debate(data: dict):
        session = db.get_debate_session(session_id)
        if not session:
            await _send({"type": "error", "message": f"Session {session_id} not found"})
            return
        async for event in debate_svc.run_debate(
            graph_app=graph_app,
            session_id=session_id,
            prompt=data.get("prompt", ""),
            toggles=data.get("toggles", {}),
            documents=data.get("documents", {}),
            parent_checkpoint_id=data.get("parent_checkpoint_id"),
            control=control,
        ):
            await _send(event)

    async def _run_synthesis(data: dict):
        session = db.get_debate_session(session_id)
        if not session:
            await _send({"type": "error", "message": f"Session {session_id} not found"})
            return
        model = data.get("synthesizer_model") or session.get("synthesizer_model")
        if not model:
            await _send({"type": "error", "message": "No synthesizer model specified"})
            return
        # Build last round responses from thread states
        participants = session["participants"]
        thread_ids = session["thread_ids"]
        last_responses: dict[str, str] = {}
        for m_id in participants:
            tid = thread_ids.get(m_id)
            if not tid:
                continue
            cfg = {"configurable": {"thread_id": tid}}
            try:
                state = await graph_app.aget_state(cfg)
                if state and state.values:
                    msgs = state.values.get("messages", [])
                    last_ai = next(
                        (msg for msg in reversed(msgs) if getattr(msg, "type", "") == "ai"),
                        None,
                    )
                    if last_ai:
                        from app.utils.helpers import extract_text
                        last_responses[m_id] = extract_text(last_ai.content)
            except Exception:
                pass

        session["synthesizer_model"] = model
        async for event in debate_svc._stream_synthesis(
            graph_app=graph_app,
            session_id=session_id,
            session=session,
            prompt=data.get("prompt", ""),
            all_responses=last_responses,
            toggles=data.get("toggles", {}),
        ):
            await _send(event)
        db.update_debate_session(session_id, status="completed")
        await _send({"type": "debate_session_status", "session_id": session_id, "status": "completed"})

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type")

            if msg_type == "debate_start":
                await _cancel_active()
                control = debate_svc.DebateControl()
                active_task = asyncio.create_task(_run_debate(data))

            elif msg_type == "debate_inject":
                message = (data.get("message") or "").strip()
                if not message:
                    continue
                if not _debate_running():
                    await _send({"type": "error", "session_id": session_id, "message": "No debate is running to add that to."})
                    continue
                control.inject(message)
                await _send({"type": "debate_session_status", "session_id": session_id, "status": "inject_queued"})

            elif msg_type == "debate_redirect":
                # A redirect restarts the debate on the new prompt, from each
                # model's current thread head.
                await _cancel_active()
                control = debate_svc.DebateControl()
                data["prompt"] = data.get("message", "")
                data["parent_checkpoint_id"] = None
                active_task = asyncio.create_task(_run_debate(data))

            elif msg_type == "debate_control":
                action = data.get("action")
                if action == "stop":
                    await _cancel_active()
                    db.update_debate_session(session_id, status="completed")
                    await _send({"type": "debate_session_status", "session_id": session_id, "status": "completed"})
                elif action == "pause" and _debate_running():
                    # Takes effect when the current round finishes; run_debate
                    # reports "paused" at that point.
                    control.pause()
                    await _send({"type": "debate_session_status", "session_id": session_id, "status": "pausing"})
                elif action == "resume":
                    control.resume()
                    if _debate_running():
                        db.update_debate_session(session_id, status="running")
                        await _send({"type": "debate_session_status", "session_id": session_id, "status": "running"})

            elif msg_type == "debate_synthesize":
                # Synthesising ends the debate: stop the rounds first so the
                # old task can't be orphaned beyond the reach of stop/disconnect.
                await _cancel_active()
                active_task = asyncio.create_task(_run_synthesis(data))

    except WebSocketDisconnect:
        pass
    finally:
        # The debate cannot outlive its socket. Record that it was cut short so
        # a reload doesn't restore it as "running" with nothing behind it.
        if active_task and not active_task.done():
            active_task.cancel()
            db.update_debate_session(session_id, status="interrupted")
