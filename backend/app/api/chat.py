"""Chat transport: POST /chat and the per-thread WebSocket /ws/{thread_id}.

Only delivery lives here; what a turn does is services/chat.py, where it
forks from is services/arena.turn_start, and who owns a running turn is
services/live.py: the server, not the socket.
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.api.deps import get_graph_app, get_runs
from app.api.outbox import Outbox
from app.registry import DEFAULT_MODEL, model_color
from app.services.arena import TurnStart, question_point, synthesis_note, synthesis_request, turn_start
from app.services.chat import name_new_thread, stream_turn
from app.services.context import ContextSettings
from app.services.live import ChatRunState, ChatTurn, LiveRun, RunRegistry
from app.services.runs import SYNTHESIS_TURN, new_turn_id

log = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    thread_id: str
    model: str = DEFAULT_MODEL
    toggles: Dict[str, bool] = {}
    documents: Optional[Dict[str, str]] = None
    # Files already saved for the thread (uploaded or attached before).
    document_names: Optional[List[str]] = None
    parent_checkpoint_id: Optional[str] = None
    # Continue after this finished debate (without a parent).
    debate_session_id: Optional[str] = None
    is_deliberation: bool = False
    # Model that writes summaries for this turn; None = the app's default.
    summarizer: Optional[str] = None
    # The person's own system prompt; None = models get no system prompt.
    system_prompt: Optional[str] = None


@router.post("/chat")
async def chat(request: ChatRequest, graph_app=Depends(get_graph_app)):
    """One non-streaming turn, for REST callers: the same turn as the socket's."""
    context = ContextSettings.from_frame(request.model_dump())
    if problem := context.problem():
        raise HTTPException(status_code=400, detail=problem)
    try:
        start = await turn_start(graph_app, request.thread_id, request.parent_checkpoint_id, request.debate_session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    end = None
    async for event in stream_turn(
        graph_app,
        request.thread_id,
        start.parent_for(request.model),
        message=request.message,
        model=request.model,
        toggles=request.toggles,
        documents=request.documents,
        document_names=request.document_names,
        is_deliberation=request.is_deliberation,
        context=context,
        turn_id=new_turn_id(),
    ):
        if event["type"] == "end":
            end = event
    if start.new_thread:
        await name_new_thread(request.thread_id, request.message)
    return {
        "messages": end["messages"],
        "thread_id": request.thread_id,
        "checkpoint_id": end["checkpoint_id"],
        "notices": end["notices"],
    }


@router.websocket("/ws/{thread_id}")
async def chat_socket(websocket: WebSocket, thread_id: str, graph_app=Depends(get_graph_app), runs=Depends(get_runs)):
    await websocket.accept()
    await ChatConnection(websocket, graph_app, thread_id, runs.chat).serve()


class ChatConnection:
    """One browser tab's chat socket for one thread.

    Client frames:  {message, model, toggles, documents | document_names,
                     parent_checkpoint_id, is_deliberation, type?} — one per
                     model (type "synthesis" tags a synthesis turn, and with
                     answer_checkpoint_ids in place of a message synthesizes
                     those replies, hung from their question unless a parent
                     is given: synthesis_mode merge | compare | checklist
                     (with keep_components) | ask (with synthesis_question);
                     debate_session_id, without a parent, continues that
                     finished debate); or {type: "stop"}, which stops every
                     run on the thread, whichever socket started it.
    Server frames:  stream_start, stream_token, stream_end, stream_stopped,
                    stream_resume, attached, title_update, error.
                    stream_start, stream_end, stream_stopped and a model's
                    error carry the parent_checkpoint_id that model forked
                    from and the turn_id; stream_start also carries the
                    turn's kind ("synthesis" or null) and, for an ordinary
                    turn, its message; stream_end carries the reply's metrics
                    (services/metrics.py). stream_stopped: the run was
                    stopped before it finished.

    Runs belong to the server (services/live.py): a reload, a dropped socket
    or a closed tab doesn't stop them, and every socket on the thread gets
    their frames. A socket that connects while runs are live first gets one
    stream_resume per run — {model, parent_checkpoint_id, turn_id,
    model_color, content_so_far, message, kind, turn_models (the models the
    turn asked, in order)} — then ``attached`` {thread_id, runs: [{model,
    turn_id}]}, the runs it was caught up on (sent on every connect, so a
    client knows a reply it was showing has no live run), then live frames.

    Where a frame without a parent forks is turn_start(): each model from its
    own reply in the latest turn. The frontend sends a turn's frames back to
    back and waits for every model before the next turn, so frames that
    arrive while this socket's models are still running belong to the same
    turn: one turn id, and the fork points resolved once, before any of them
    wrote.
    """

    def __init__(self, websocket: WebSocket, graph_app, thread_id: str, runs: RunRegistry):
        self.websocket = websocket
        self.outbox = Outbox(websocket)
        self.graph_app = graph_app
        self.thread_id = thread_id
        self.runs = runs
        self._turn: Optional[ChatTurn] = None
        # The runs this socket started for its current turn.
        self._turn_runs: List[LiveRun] = []
        # Fork points resolved for this turn, by how the frame asked.
        self._starts: Dict[tuple, TurnStart] = {}

    async def serve(self) -> None:
        writer = asyncio.create_task(self.outbox.drain())
        resumed = self.runs.watch(self.thread_id, self.outbox.deliver)
        self.outbox.deliver({
            "type": "attached",
            "thread_id": self.thread_id,
            "runs": [{"model": run.state.model, "turn_id": run.state.turn.turn_id} for run in resumed],
        })
        try:
            while True:
                raw = await self.websocket.receive_text()
                try:
                    frame = json.loads(raw)
                except json.JSONDecodeError:
                    log.warning(f"[WS] Malformed frame from {self.thread_id}, skipping.")
                    continue
                if frame.get("type") == "stop":
                    await self.runs.cancel(self.thread_id)
                    continue
                await self._start_model(frame)
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("[WS] chat socket failed")
        finally:
            # The runs go on; only this socket stops watching them.
            self.runs.unwatch(self.thread_id, self.outbox.deliver)
            writer.cancel()

    async def _start_model(self, frame: dict) -> None:
        model = frame.get("model", DEFAULT_MODEL)
        if self._turn is None or all(run.done for run in self._turn_runs):
            self._turn = ChatTurn(new_turn_id())
            self._turn_runs = []
            self._starts = {}
        turn = self._turn
        try:
            parent = frame.get("parent_checkpoint_id")
            if not parent and frame.get("type") == SYNTHESIS_TURN and frame.get("answer_checkpoint_ids"):
                parent = await question_point(self.graph_app, self.thread_id, frame["answer_checkpoint_ids"][0])
            key = ("checkpoint", parent) if parent else ("debate", frame.get("debate_session_id"))
            if key not in self._starts:
                self._starts[key] = await turn_start(
                    self.graph_app, self.thread_id, parent, None if parent else frame.get("debate_session_id")
                )
            start = self._starts[key]
        except ValueError as e:
            self.outbox.deliver({"type": "error", "message": str(e), "model": model,
                                 "parent_checkpoint_id": frame.get("parent_checkpoint_id")})
            return
        # Every frame about this model's turn names the parent it forked from,
        # so a client can retry a failed model from exactly the same point.
        where = {"model": model, "parent_checkpoint_id": start.parent_for(model), "turn_id": turn.turn_id}
        context = ContextSettings.from_frame(frame)
        if problem := context.problem():
            self.outbox.deliver({"type": "error", "message": problem, **where})
            return
        kind = frame.get("type")
        turn.models.append(model)
        state = ChatRunState(
            turn, model, where,
            message=None if kind == SYNTHESIS_TURN else frame.get("message"),
            kind=kind,
        )
        graph_app, thread_id, new_thread = self.graph_app, self.thread_id, start.new_thread

        async def body(run: LiveRun) -> None:
            await run_model(run, graph_app, thread_id, frame, context, new_thread)

        self._turn_runs.append(self.runs.start(self.thread_id, state, body))


async def run_model(run: LiveRun, graph_app, thread_id: str, frame: dict, context: ContextSettings,
                    new_thread: bool) -> None:
    """One model's reply in a chat turn, as frames for whoever watches the
    thread. Runs to the end with or without a socket."""
    state: ChatRunState = run.state
    model, where, turn = state.model, state.where, state.turn
    try:
        message = frame.get("message")
        note = None
        if frame.get("type") == SYNTHESIS_TURN and frame.get("answer_checkpoint_ids"):
            # The answers to synthesize, by checkpoint: the prompt is the
            # backend's, the same one the CLI and MCP synthesis writes.
            mode = frame.get("synthesis_mode") or "merge"
            message = await synthesis_request(
                graph_app, thread_id, frame["answer_checkpoint_ids"], mode,
                keep=frame.get("keep_components") or (), question=frame.get("synthesis_question"),
            )
            note = synthesis_note(mode, frame.get("synthesis_question"))
        run.emit({"type": "stream_start", **where, "model_color": model_color(model),
                  "kind": state.kind, "message": state.message})
        async for event in stream_turn(
            graph_app,
            thread_id,
            where["parent_checkpoint_id"],
            message=message,
            model=model,
            toggles=frame.get("toggles", {}),
            documents=frame.get("documents") or {},
            document_names=frame.get("document_names"),
            is_deliberation=frame.get("is_deliberation", False),
            context=context,
            turn_kind=frame.get("type"),
            turn_id=turn.turn_id,
            turn_note=note,
        ):
            if event["type"] == "token":
                run.emit({"type": "stream_token", "token": event["token"], "model": model})
            elif event["type"] == "end":
                run.emit({
                    "type": "stream_end",
                    **where,
                    "messages": event["messages"],
                    "checkpoint_id": event["checkpoint_id"],
                    "attached_documents": event["attached_documents"],
                    "retrieved": event["retrieved"],
                    "notices": event["notices"],
                    "metrics": event["metrics"],
                })
                if new_thread and not turn.named:
                    turn.named = True
                    first_user = next((m.get("content", "") for m in event["messages"] if m.get("role") == "user"), "")
                    await name_thread(run, thread_id, first_user)
    except asyncio.CancelledError:
        # Stopped (from any tab) or the server is shutting down: tell every
        # watcher, or their cards would stream forever.
        run.emit({"type": "stream_stopped", **where})
        raise
    except Exception as e:
        log.exception(f"[WS] {model} failed")
        run.emit({"type": "error", "message": str(e), **where})


async def name_thread(run: LiveRun, thread_id: str, first_user_message: str) -> None:
    """Title a new thread from its first message and tell the watchers."""
    try:
        title = await name_new_thread(thread_id, first_user_message)
        if title:
            run.emit({"type": "title_update", "thread_id": thread_id, "title": title})
    except Exception as e:
        log.warning(f"[Auto-title] failed: {e}")
