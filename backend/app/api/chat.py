"""Chat transport: POST /chat and the per-thread WebSocket /ws/{thread_id}.

Only delivery lives here; what a turn does is services/chat.py.
"""

import asyncio
import json
from typing import Dict, Optional, Set

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.api.deps import get_graph_app
from app.api.models import DEFAULT_MODEL
from app.core import database as db
from app.services.chat import auto_title, build_turn_input
from app.services.chat import stream_turn
from app.services.message_format import format_chat_messages
from app.services.runs import (
    final_state_of_run,
    resolve_fork_point,
    resolve_fork_point_ex,
    tag_run,
    thread_config,
)

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    thread_id: str
    model: str = DEFAULT_MODEL
    toggles: Dict[str, bool] = {}
    documents: Optional[Dict[str, str]] = None
    parent_checkpoint_id: Optional[str] = None


@router.post("/chat")
async def chat(request: ChatRequest, graph_app=Depends(get_graph_app)):
    """One non-streaming turn, for REST callers."""
    parent_id = request.parent_checkpoint_id or await resolve_fork_point(graph_app, request.thread_id)
    config = thread_config(request.thread_id, parent_id)
    run_id = tag_run(config)
    state = await graph_app.aget_state(config)
    turn_input = build_turn_input(
        state.values,
        message=request.message,
        model=request.model,
        toggles=request.toggles,
        documents=request.documents,
    )
    result = await graph_app.ainvoke(turn_input, config)
    new_state = await final_state_of_run(graph_app, request.thread_id, run_id)
    return {
        "messages": format_chat_messages(result.get("messages", []), request.model),
        "thread_id": request.thread_id,
        "checkpoint_id": new_state.config["configurable"]["checkpoint_id"] if new_state else None,
    }


@router.websocket("/ws/{thread_id}")
async def chat_socket(websocket: WebSocket, thread_id: str, graph_app=Depends(get_graph_app)):
    await websocket.accept()
    await ChatConnection(websocket, graph_app, thread_id).serve()


class ChatConnection:
    """One browser tab's chat socket for one thread.

    Client frames:  {message, model, toggles, documents, parent_checkpoint_id,
                     is_deliberation}  — one per model; or {type: "stop"}.
    Server frames:  stream_start, stream_token, stream_end, title_update, error.

    Models sent together share one parent. The frontend sends a turn's frames
    back to back and waits for every model before the next turn, so a frame
    without a parent that arrives while models are still running belongs to
    that same turn.
    """

    def __init__(self, websocket: WebSocket, graph_app, thread_id: str):
        self.websocket = websocket
        self.graph_app = graph_app
        self.thread_id = thread_id
        self._lock = asyncio.Lock()  # no interleaved frames
        self._tasks: Set[asyncio.Task] = set()
        self._model_tasks: Set[asyncio.Task] = set()
        self._turn_parent: Optional[str] = None
        self._turn_is_new_thread = False
        self._renamed = False

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
                    print(f"[WS] Malformed frame from {self.thread_id}, skipping.")
                    continue
                if frame.get("type") == "stop":
                    self._cancel_all()
                    continue
                await self._start_model(frame)
        except WebSocketDisconnect:
            pass
        except Exception:
            import traceback

            traceback.print_exc()
        finally:
            # Nobody is listening any more; stop billing for model calls.
            self._cancel_all()

    async def _start_model(self, frame: dict) -> None:
        if frame.get("parent_checkpoint_id"):
            self._turn_parent = frame["parent_checkpoint_id"]
            self._turn_is_new_thread = False
        elif not (self._model_tasks and self._turn_parent):
            self._turn_parent, self._turn_is_new_thread = await resolve_fork_point_ex(
                self.graph_app, self.thread_id
            )
        self._spawn(
            self._run_model(frame, self._turn_parent, self._turn_is_new_thread),
            model_task=True,
        )

    async def _run_model(self, frame: dict, parent: Optional[str], is_new_thread: bool) -> None:
        model = frame.get("model", DEFAULT_MODEL)
        try:
            await self.send({"type": "stream_start", "model": model})
            async for event in stream_turn(
                self.graph_app,
                self.thread_id,
                parent,
                message=frame.get("message"),
                model=model,
                toggles=frame.get("toggles", {}),
                documents=frame.get("documents", {}),
                is_deliberation=frame.get("is_deliberation", False),
            ):
                if event["type"] == "token":
                    if not await self.send({"type": "stream_token", "token": event["token"], "model": model}):
                        return
                else:
                    sent = await self.send({
                        "type": "stream_end",
                        "model": model,
                        "messages": event["messages"],
                        "checkpoint_id": event["checkpoint_id"],
                    })
                    if not sent:
                        return
                    if is_new_thread and not self._renamed and event["messages"]:
                        self._renamed = True
                        self._spawn(self._auto_rename(event["messages"]))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            import traceback

            traceback.print_exc()
            await self.send({"type": "error", "message": str(e), "model": model})

    async def _auto_rename(self, messages: list) -> None:
        first_user = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
        title = auto_title(first_user or "")
        if not title:
            return
        try:
            db.rename_thread(self.thread_id, title)
            await self.send({"type": "title_update", "thread_id": self.thread_id, "title": title})
        except Exception as e:
            print(f"[Auto-title] failed: {e}")
