from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Optional, Set
import json
import asyncio
from contextlib import asynccontextmanager

from graph import workflow
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
import db
from utils import extract_text, clean_string

from routers import threads, history, upload, models


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate environment on startup
    import os

    keys = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY"),
        "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY"),
    }
    available = [k for k, v in keys.items() if v]
    missing = [k for k, v in keys.items() if not v]
    if not available:
        print(
            "\n⚠️  WARNING: No API keys found! Set at least one of: OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY"
        )
        print("   See .env.example for details.\n")
    else:
        print(f"\n✅ API keys loaded: {', '.join(available)}")
        if missing:
            print(f"   ℹ️  Not configured: {', '.join(missing)}\n")

    async with AsyncSqliteSaver.from_conn_string(db.DB_PATH) as memory:
        app.state.graph_app = workflow.compile(checkpointer=memory)
        yield


db.init_db()
server = FastAPI(title="The Crucible API", lifespan=lifespan)

server.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Register Routers ────────────────────────────────────────────
server.include_router(threads.router)
server.include_router(history.router)
server.include_router(upload.router)
server.include_router(models.router)


# ─── Chat & WebSocket (tightly coupled to graph_app) ─────────────


class ChatRequest(BaseModel):
    message: str
    thread_id: str
    model: str = "gpt-4o"
    toggles: Dict[str, bool] = {}
    documents: Optional[Dict[str, str]] = None
    parent_checkpoint_id: Optional[str] = None


@server.post("/chat")
async def chat(request: ChatRequest):
    graph_app = server.state.graph_app
    config = {"configurable": {"thread_id": request.thread_id, "checkpoint_ns": ""}}

    if request.parent_checkpoint_id:
        config["configurable"]["checkpoint_id"] = request.parent_checkpoint_id
        state = await graph_app.aget_state(config)
        initial_state = {
            "messages": [("user", request.message)],
            "active_peer": request.model,
            "toggles": {**state.values.get("toggles", {}), **request.toggles},
        }
    else:
        state = await graph_app.aget_state(config)
        initial_state = {
            "messages": [("user", request.message)],
            "active_peer": request.model,
            "toggles": request.toggles,
        }
        if not state.values:
            initial_state.update(
                {
                    "current_thesis": "",
                    "documents": request.documents or {},
                    "branch_name": "main",
                }
            )

    try:
        result = await graph_app.ainvoke(initial_state, config)
        new_state = await graph_app.aget_state(config)

        formatted_messages = _format_messages(result.get("messages", []), request.model)
        return {
            "messages": formatted_messages,
            "thread_id": request.thread_id,
            "checkpoint_id": new_state.config["configurable"]["checkpoint_id"],
        }
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise e


async def auto_rename_thread(
    thread_id: str, messages: list, websocket: WebSocket, ws_lock: asyncio.Lock
):
    """Generate a short title from the first user message — no LLM call needed."""
    try:
        user_msg = next(
            (
                getattr(m, "content", "")
                for m in messages
                if getattr(m, "type", "") == "human"
                or (isinstance(m, dict) and m.get("type") == "human")
            ),
            None,
        )
        if not user_msg:
            return
        # Simple truncation: first line, max 40 chars
        title = user_msg.strip().split("\n")[0][:40]
        if len(user_msg.strip().split("\n")[0]) > 40:
            title = title.rsplit(" ", 1)[0] + "…"
        db.rename_thread(thread_id, title)
        async with ws_lock:
            await websocket.send_json(
                {"type": "title_update", "thread_id": thread_id, "title": title}
            )
    except Exception as e:
        print(f"[Auto-title] failed: {e}")


@server.websocket("/ws/{thread_id}")
async def websocket_endpoint(websocket: WebSocket, thread_id: str):
    await websocket.accept()
    graph_app = server.state.graph_app
    ws_lock = asyncio.Lock()  # Prevent interleaved WS frames
    active_tasks: Set[asyncio.Task] = set()
    renamed = False  # Only auto-rename once per connection

    async def _process_model(request_data: dict):
        nonlocal renamed
        """Process a single model invocation — runs as a concurrent task."""
        message = request_data.get("message")
        model = request_data.get("model", "gpt-5.2")
        toggles = request_data.get("toggles", {})
        documents = request_data.get("documents", {})
        parent_checkpoint_id = request_data.get("parent_checkpoint_id")
        is_deliberation = request_data.get("is_deliberation", False)

        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}

        # 1. Establish the precise parent node we are branching/continuing from
        if parent_checkpoint_id:
            config["configurable"]["checkpoint_id"] = parent_checkpoint_id

        state = await graph_app.aget_state(config)

        # 2. Dynamic Context Management (Compression is handled by the Graph's entry node)
        current_msgs = state.values.get("messages", [])
        if current_msgs:
            from graph import count_tokens, get_token_limit

            print(
                f"[Context] Current Tokens: {count_tokens(current_msgs)}, Limit: {get_token_limit(model)}"
            )

        # 3. Format uploaded documents as ephemeral text embedded directly in the message
        safe_message = clean_string(message)
        user_msg = safe_message

        if documents:
            docs_parts = []
            for name, content in documents.items():
                safe_content = clean_string(content)
                docs_parts.append(f"--- Attached Document: {name} ---\n{safe_content}")
            docs_text = "\n\n".join(docs_parts)
            user_msg = f"{user_msg}\n\n{docs_text}" if user_msg else docs_text

        # 4. Hard safety cap: Truncate extremely large prompts (~500k chars / 125k tokens)
        # Anthropic Opus has a 160k-200k limit. A 2.5MB PDF is likely over 500k tokens.
        # We truncate here to ensure the API call doesn't fail with a 400 or payload error.
        # 4. Hard safety cap: Truncate large prompts to stay under 30k tokens
        # 100k chars is approx 25k tokens, leaving 5k for history/response.
        MAX_CHAR_LIMIT = 100_000
        if len(user_msg) > MAX_CHAR_LIMIT:
            print(
                f"[Safety] Truncating user_msg from {len(user_msg)} to {MAX_CHAR_LIMIT}"
            )
            user_msg = (
                user_msg[:MAX_CHAR_LIMIT]
                + "\n\n[... content truncated for stability ...]"
            )

        # 5. Construct Initial State for the new turn
        initial_state = {
            "active_peer": model,
            "toggles": {**state.values.get("toggles", {}), **toggles},
            "is_deliberation": is_deliberation,
        }

        # Fallback for empty messages to prevent LLM crashes (Anthropic)
        if not is_deliberation:
            initial_state["messages"] = [
                ("user", user_msg if user_msg.strip() else "Please continue.")
            ]
        elif user_msg.strip():
            initial_state["messages"] = [("user", user_msg)]
        else:
            initial_state["messages"] = [
                ("user", "Please review the conversation and provide your analysis.")
            ]

        if not state.values:
            initial_state.update(
                {
                    "current_thesis": "",
                    "branch_name": "main",
                }
            )

        initial_checkpoints = db.get_all_checkpoint_ids(thread_id)

        try:
            async with ws_lock:
                await websocket.send_json({"type": "stream_start", "model": model})

            async for event in graph_app.astream_events(
                initial_state, config, version="v2"
            ):
                kind = event.get("event")
                if kind == "on_chat_model_stream":
                    node_name = event.get("metadata", {}).get("langgraph_node", "")
                    if node_name != "draft":
                        continue
                    chunk = event.get("data", {}).get("chunk")
                    if (
                        chunk
                        and hasattr(chunk, "content")
                        and chunk.content is not None
                    ):
                        token = extract_text(chunk.content)
                        if token != "":
                            async with ws_lock:
                                try:
                                    await websocket.send_json(
                                        {
                                            "type": "stream_token",
                                            "token": token,
                                            "model": model,
                                        }
                                    )
                                except RuntimeError:
                                    # Socket closed
                                    return

            new_state = await graph_app.aget_state(config)
            # NEW: Graph-Path Reconstruction for final emission
            # We walk back the parents of new_state to get un-truncated history
            full_path_states = {}
            temp_state = new_state
            while temp_state:
                c_id = temp_state.config.get("configurable", {}).get("checkpoint_id")
                if not c_id:
                    break
                full_path_states[c_id] = temp_state

                # Move up
                p_id = (
                    temp_state.parent_config.get("configurable", {}).get(
                        "checkpoint_id"
                    )
                    if temp_state.parent_config
                    else None
                )
                if not p_id or p_id in full_path_states:
                    break

                # Fetch parent
                p_cfg = {
                    **config,
                    "configurable": {**config["configurable"], "checkpoint_id": p_id},
                }
                temp_state = await graph_app.aget_state(p_cfg)

            from history_tree import format_messages

            active_cid = new_state.config.get("configurable", {}).get("checkpoint_id")
            formatted_messages = format_messages(active_cid, full_path_states)

            async with ws_lock:
                try:
                    await websocket.send_json(
                        {
                            "type": "stream_end",
                            "model": model,
                            "messages": formatted_messages,
                            "checkpoint_id": active_cid,
                        }
                    )
                except RuntimeError:
                    return

            if not renamed and len(initial_checkpoints) == 0 and formatted_messages:
                renamed = True
                asyncio.create_task(
                    auto_rename_thread(thread_id, formatted_messages, websocket, ws_lock)
                )

        except Exception as e:
            import traceback

            traceback.print_exc()
            async with ws_lock:
                try:
                    await websocket.send_json(
                        {"type": "error", "message": str(e), "model": model}
                    )
                except RuntimeError:
                    pass

    try:
        while True:
            data = await websocket.receive_text()
            request_data = json.loads(data)
            if request_data.get("type") == "stop":
                print(
                    f"[WS] Stop requested for thread {thread_id}. Cancelling {len(active_tasks)} tasks."
                )
                for t in active_tasks:
                    t.cancel()
                active_tasks.clear()
                continue

            # Spawn as concurrent task — don't block the loop
            task = asyncio.create_task(_process_model(request_data))
            active_tasks.add(task)
            task.add_done_callback(active_tasks.discard)

    except WebSocketDisconnect:
        print(f"WebSocket disconnected for thread {thread_id}")
    except Exception:
        import traceback

        traceback.print_exc()


# ─── Shared Helpers ───────────────────────────────────────────────


def _format_messages(raw_messages: list, active_model: str) -> list:
    formatted = []

    # 1. First pass: Filter technical markers to ensure correct indexing
    meaningful_messages = []
    for m in raw_messages:
        content = (
            getattr(m, "content", "")
            if hasattr(m, "content")
            else (m.get("content", "") if isinstance(m, dict) else str(m))
        )
        # Skip technical system markers
        if "PREVIOUS CONTEXT SUMMARY:" in str(content):
            continue
        meaningful_messages.append(m)

    for i, msg in enumerate(meaningful_messages):
        role = "user"
        if hasattr(msg, "type"):
            role = "user" if msg.type == "human" else "assistant"
        elif isinstance(msg, dict):
            role = msg.get("role") or (
                "user" if msg.get("type") == "human" else "assistant"
            )

        content = (
            getattr(msg, "content", "")
            if hasattr(msg, "content")
            else (msg.get("content", "") if isinstance(msg, dict) else str(msg))
        )
        if not content and role != "assistant":
            continue

        # Heavy Duty Attribution Recovery
        msg_model = None

        # Priority 1: Direct name attribute
        msg_model = getattr(msg, "name", None)

        # Priority 2: additional_kwargs
        if not msg_model and hasattr(msg, "additional_kwargs"):
            add_kwargs = getattr(msg, "additional_kwargs", {})
            msg_model = add_kwargs.get(
                "model", add_kwargs.get("model_id")
            ) or add_kwargs.get("name")

        # Priority 3: response_metadata
        if not msg_model and hasattr(msg, "response_metadata"):
            resp_meta = getattr(msg, "response_metadata", {})
            msg_model = resp_meta.get(
                "model_name", resp_meta.get("model_id")
            ) or resp_meta.get("model")

        # Priority 4: Dictionary keys (for JSON serialized state)
        if not msg_model and isinstance(msg, dict):
            msg_model = (
                msg.get("name")
                or msg.get("model")
                or msg.get("additional_kwargs", {}).get("model_id")
                or msg.get("metadata", {}).get("active_peer")
            )

        # Context Fallback: Only the VERY LAST message in the meaningful list defaults to active_model
        if not msg_model:
            is_last = i == len(meaningful_messages) - 1
            if role == "assistant":
                msg_model = active_model if is_last else "Assistant"
            else:
                msg_model = "User"

        formatted.append(
            {
                "role": role,
                "content": extract_text(content),
                "type": role,
                "model": msg_model,
            }
        )
    return formatted


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:server", host="0.0.0.0", port=8000, reload=True)
