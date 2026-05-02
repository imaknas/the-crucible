from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Optional, Set
import json
import asyncio
from contextlib import asynccontextmanager

from app.services.graph import workflow
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from app.core import database as db
from app.utils.helpers import extract_text, clean_string

from app.api import threads, history, upload, models, graph, config


# --- MONKEYPATCH for langchain_anthropic 1.3.2 bug ---
# Fixes AttributeError: 'dict' object has no attribute 'model_dump'
# during web-search beta event streaming.
try:
    import langchain_anthropic.chat_models

    _original_make_chunk = (
        langchain_anthropic.chat_models._make_message_chunk_from_anthropic_event
    )

    def _safe_make_chunk(event, *args, **kwargs):
        if getattr(event, "type", None) == "message_delta":
            delta = getattr(event, "delta", None)
            if delta and getattr(delta, "container", None) is not None:
                if isinstance(delta.container, dict):

                    class MockContainer:
                        def __init__(self, d):
                            self.d = d

                        def model_dump(self, mode=None, **kw):
                            return self.d

                    delta.container = MockContainer(delta.container)
        return _original_make_chunk(event, *args, **kwargs)

    langchain_anthropic.chat_models._make_message_chunk_from_anthropic_event = (
        _safe_make_chunk
    )
except Exception:
    pass
# -----------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()

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


server = FastAPI(title="The Crucible API", lifespan=lifespan)

server.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Register Routers ────────────────────────────────────────────
server.include_router(threads.router)
server.include_router(history.router)
server.include_router(upload.router)
server.include_router(models.router)
server.include_router(graph.router)
server.include_router(config.router)


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
        """Process a single model invocation — runs as a concurrent task."""
        nonlocal renamed
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
            from app.services.graph import count_tokens, get_token_limit

            print(
                f"[Context] Current Tokens: {count_tokens(current_msgs)}, Limit: {get_token_limit(model)}"
            )

        # 3. Handle uploaded documents — we now pass them through the state
        # instead of appending them to the user's message to keep chat history clean.
        user_msg = clean_string(message)

        # 4. Truncate large prompts for stability
        MAX_CHAR_LIMIT = 100_000
        if user_msg and len(user_msg) > MAX_CHAR_LIMIT:
            user_msg = user_msg[:MAX_CHAR_LIMIT] + "\n\n[... truncated ...]"

        # 5. Construct Initial State for the new turn
        initial_state = {
            "active_peer": model,
            "toggles": {**state.values.get("toggles", {}), **toggles},
            "is_deliberation": is_deliberation,
            "documents": documents or {},  # Pass documents in the state
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

            from app.services.tree import format_messages

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
                rename_task = asyncio.create_task(
                    auto_rename_thread(
                        thread_id, formatted_messages, websocket, ws_lock
                    )
                )
                active_tasks.add(rename_task)
                rename_task.add_done_callback(active_tasks.discard)

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
            try:
                request_data = json.loads(data)
            except json.JSONDecodeError:
                print(f"[WS] Malformed frame from {thread_id}, skipping.")
                continue
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
        if msg_model and not isinstance(msg_model, str):
            msg_model = None

        # Priority 2: additional_kwargs
        if not msg_model and hasattr(msg, "additional_kwargs"):
            add_kwargs = getattr(msg, "additional_kwargs", {})
            if isinstance(add_kwargs, dict):
                msg_model = add_kwargs.get(
                    "model", add_kwargs.get("model_id")
                ) or add_kwargs.get("name")

        # Priority 3: response_metadata
        if not msg_model and hasattr(msg, "response_metadata"):
            resp_meta = getattr(msg, "response_metadata", {})
            if isinstance(resp_meta, dict):
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
                msg_model = active_model if is_last else "assistant"
            else:
                msg_model = "user"

        # Extract sources if present
        sources = None
        if hasattr(msg, "additional_kwargs"):
            sources = getattr(msg, "additional_kwargs", {}).get("sources")
        if not sources and isinstance(msg, dict):
            sources = msg.get("additional_kwargs", {}).get("sources")

        # Native Grounding Metadata Extraction
        if not sources:
            extracted_sources = []

            # 1. Google Gemini Grounding (`groundingMetadata` in response_metadata or additional_kwargs)
            resp_meta = getattr(msg, "response_metadata", {})
            add_kwargs = getattr(msg, "additional_kwargs", {})

            gm = (
                resp_meta.get("groundingMetadata")
                or resp_meta.get("grounding_metadata")
                or add_kwargs.get("groundingMetadata")
                or add_kwargs.get("grounding_metadata")
            )
            if isinstance(gm, dict):
                # Handle both camelCase from raw API and snake_case from some wrappers
                chunks = gm.get("groundingChunks") or gm.get("grounding_chunks") or []
                for chunk in chunks:
                    web = chunk.get("web", {})
                    if not web:
                        # Fallback if structure is different
                        continue

                    uri = web.get("uri") or web.get("url")
                    title = web.get("title") or "Web Result"
                    if uri:
                        extracted_sources.append({"text": title, "filename": uri})

            # 2. OpenAI & Anthropic Native Search Extraction
            # Models might return `content_blocks` (OpenAI Python SDK) or list-based `content`
            c_blocks = []
            if hasattr(msg, "content_blocks"):
                c_blocks = msg.content_blocks
            elif hasattr(msg, "content") and isinstance(msg.content, list):
                c_blocks = msg.content
            elif isinstance(msg, dict) and isinstance(msg.get("content"), list):
                c_blocks = msg["content"]

            for block in c_blocks:
                if isinstance(block, dict) and block.get("type") in (
                    "text",
                    "server_tool_result",
                ):
                    # OpenAI uses 'annotations'
                    if "annotations" in block:
                        for ann in block["annotations"]:
                            if ann.get("url"):
                                extracted_sources.append(
                                    {
                                        "text": ann.get("title", "Web Source"),
                                        "filename": ann.get("url"),
                                    }
                                )
                    # Anthropic or general citation array fallback
                    # Check for 'citations' (plural) or 'citation' (singular)
                    citations = block.get("citations") or block.get("citation")
                    if citations:
                        if isinstance(citations, dict):
                            citations = [citations]

                        if isinstance(citations, list):
                            for cit in citations:
                                if isinstance(cit, dict):
                                    url = (
                                        cit.get("document_url")
                                        or cit.get("url")
                                        or "Web Search"
                                    )
                                    title = (
                                        cit.get("document_title")
                                        or cit.get("title")
                                        or cit.get("source_name")
                                        or "Web Source"
                                    )
                                    extracted_sources.append(
                                        {
                                            "text": title,
                                            "filename": url,
                                        }
                                    )

            if extracted_sources:
                # Deduplicate by URL
                unique_sources = []
                seen = set()
                for s in extracted_sources:
                    if s["filename"] not in seen:
                        seen.add(s["filename"])
                        unique_sources.append(s)
                sources = unique_sources

        formatted.append(
            {
                "role": role,
                "content": extract_text(content, wrap_thinking=True),
                "type": role,
                "model": msg_model,
                "sources": sources,
            }
        )
    return formatted


if __name__ == "__main__":
    import uvicorn
    import os

    desired_port = int(os.getenv("PORT", 8000))
    uvicorn.run("app.main:server", host="0.0.0.0", port=desired_port, reload=True)
