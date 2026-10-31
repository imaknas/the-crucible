"""Chat transport: POST /chat and the per-thread WebSocket /ws/{thread_id}.

Only delivery lives here; what a turn does is services/chat.py, where it
forks from is services/arena.turn_start.
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.api.deps import get_graph_app
from app.registry import DEFAULT_MODEL, model_color
from app.services.arena import TurnStart, question_point, synthesis_request, turn_start
from app.services.chat import name_new_thread, stream_turn
from app.services.context import ContextSettings
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
async def chat_socket(websocket: WebSocket, thread_id: str, graph_app=Depends(get_graph_app)):
    await websocket.accept()
    await ChatConnection(websocket, graph_app, thread_id).serve()


class ChatConnection:
    """One browser tab's chat socket for one thread.

    Client frames:  {message, model, toggles, documents | document_names,
                     parent_checkpoint_id, is_deliberation, type?} — one per
                     model (type "synthesis" tags a synthesis turn, and with
                     answer_checkpoint_ids in place of a message synthesizes
                     those replies, hung from their question unless a parent
                     is given; debate_session_id, without a parent, continues
                     that finished debate); or {type: "stop"}.
    Server frames:  stream_start, stream_token, stream_end, title_update, error.
                    stream_start, stream_end and a model's error carry the
                    parent_checkpoint_id that model forked from and the turn_id.

    Where a frame without a parent forks is turn_start(): each model from its
    own reply in the latest turn. The frontend sends a turn's frames back to
    back and waits for every model before the next turn, so frames that
    arrive while models are still running belong to the same turn: one turn
    id, and the fork points resolved once, before any of them wrote.
    """

    def __init__(self, websocket: WebSocket, graph_app, thread_id: str):
        self.websocket = websocket
        self.graph_app = graph_app
        self.thread_id = thread_id
        self._lock = asyncio.Lock()  # no interleaved frames
        self._tasks: Set[asyncio.Task] = set()
        self._model_tasks: Set[asyncio.Task] = set()
        self._turn_id: Optional[str] = None
        # Fork points resolved for this turn, by how the frame asked.
        self._starts: Dict[tuple, TurnStart] = {}
        self._named = False

    async def send(self, frame: dict) -> bool:
        """Send a frame; False if the socket is already gone."""
        async with self._lock:
            try:
                await self.websocket.send_json(frame)
                return True
            except (RuntimeError, WebSocketDisconnect):
                return False

    def _spawn(self, coro, *, model_task: bool = False) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        if model_task:
            self._model_tasks.add(task)
            task.add_done_callback(self._model_tasks.discard)

    def _cancel_all(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()

    async def serve(self) -> None:
        try:
            while True:
                raw = await self.websocket.receive_text()
                try:
                    frame = json.loads(raw)
                except json.JSONDecodeError:
                    log.warning(f"[WS] Malformed frame from {self.thread_id}, skipping.")
                    continue
                if frame.get("type") == "stop":
                    self._cancel_all()
                    continue
                await self._start_model(frame)
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("[WS] chat socket failed")
        finally:
            # Nobody is listening any more; stop billing for model calls.
            self._cancel_all()

    async def _start_model(self, frame: dict) -> None:
        model = frame.get("model", DEFAULT_MODEL)
        if not self._model_tasks or self._turn_id is None:
            self._turn_id = new_turn_id()
            self._starts = {}
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
            await self.send({"type": "error", "message": str(e), "model": model,
                             "parent_checkpoint_id": frame.get("parent_checkpoint_id")})
            return
        self._spawn(self._run_model(frame, model, start.parent_for(model), start.new_thread, self._turn_id),
                    model_task=True)

    async def _run_model(self, frame: dict, model: str, parent: str, new_thread: bool, turn_id: str) -> None:
        context = ContextSettings.from_frame(frame)
        # Every frame about this model's turn names the parent it forked from,
        # so a client can retry a failed model from exactly the same point.
        where = {"model": model, "parent_checkpoint_id": parent, "turn_id": turn_id}
        if problem := context.problem():
            await self.send({"type": "error", "message": problem, **where})
            return
        try:
            message = frame.get("message")
            if frame.get("type") == SYNTHESIS_TURN and frame.get("answer_checkpoint_ids"):
                # The answers to synthesize, by checkpoint: the prompt is the
                # backend's, the same one the CLI and MCP synthesis writes.
                message = await synthesis_request(self.graph_app, self.thread_id, frame["answer_checkpoint_ids"])
            await self.send({"type": "stream_start", **where, "model_color": model_color(model)})
            async for event in stream_turn(
                self.graph_app,
                self.thread_id,
                parent,
                message=message,
                model=model,
                toggles=frame.get("toggles", {}),
                documents=frame.get("documents") or {},
                document_names=frame.get("document_names"),
                is_deliberation=frame.get("is_deliberation", False),
                context=context,
                turn_kind=frame.get("type"),
                turn_id=turn_id,
            ):
                if event["type"] == "token":
                    if not await self.send({"type": "stream_token", "token": event["token"], "model": model}):
                        return
                elif event["type"] == "end":
                    sent = await self.send({
                        "type": "stream_end",
                        **where,
                        "messages": event["messages"],
                        "checkpoint_id": event["checkpoint_id"],
                        "attached_documents": event["attached_documents"],
                        "retrieved": event["retrieved"],
                        "notices": event["notices"],
                    })
                    if not sent:
                        return
                    if new_thread and not self._named:
                        self._named = True
                        first_user = next((m.get("content", "") for m in event["messages"] if m.get("role") == "user"), "")
                        self._spawn(self._name_thread(first_user))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception(f"[WS] {model} failed")
            await self.send({"type": "error", "message": str(e), **where})

    async def _name_thread(self, first_user_message: str) -> None:
        try:
            title = await name_new_thread(self.thread_id, first_user_message)
            if title:
                await self.send({"type": "title_update", "thread_id": self.thread_id, "title": title})
        except Exception as e:
            log.warning(f"[Auto-title] failed: {e}")
