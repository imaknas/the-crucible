"""Programmatic entry points shared by the CLI and the MCP server.

The web UI drives the graph over WebSockets from main.py and api/debate.py;
everything else (``crucible`` CLI, MCP tools) goes through here so the two
never grow separate copies of the arena / synthesis logic.
"""

import asyncio
import sys
from contextlib import asynccontextmanager, redirect_stdout
from typing import Any, AsyncGenerator, Dict, List, Optional

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.api.models import DEFAULT_ARENA_MODELS, FAMILY_META, MODEL_REGISTRY
from app.core import database as db
from app.llm import has_credentials
from app.services.graph import workflow
from app.services.runs import (
    final_state_of_run,
    resolve_fork_point,
    tag_run,
    thread_config,
)
from app.utils.helpers import extract_text

# Overall budget for one arena turn; models still running after it are
# cancelled and reported as timed out.
ARENA_TIMEOUT_SECONDS = 300


def stdout_to_stderr():
    """Send the graph's diagnostic print() output to stderr.

    The nodes log with print(); on stdout that corrupts CLI JSON output and,
    worse, the MCP stdio protocol stream.
    """
    return redirect_stdout(sys.stderr)


@asynccontextmanager
async def open_graph():
    """A compiled graph on the shared SQLite checkpointer, closed on exit."""
    db.init_db()
    async with AsyncSqliteSaver.from_conn_string(db.DB_PATH) as saver:
        await saver.setup()
        yield workflow.compile(checkpointer=saver)


# ─── Models ──────────────────────────────────────────────────────


def key_available(model_id: str) -> bool:
    return has_credentials(model_id)


def resolve_models(models: Optional[List[str]] = None) -> List[str]:
    """Validate explicitly requested models, or pick defaults that have keys.

    Raises ValueError with a message meant for the caller (CLI user or agent).
    """
    if models:
        unknown = [m for m in models if m not in MODEL_REGISTRY]
        if unknown:
            raise ValueError(
                f"Invalid model(s): {', '.join(unknown)}. "
                f"Available: {', '.join(MODEL_REGISTRY)}"
            )
        keyless = [m for m in models if not key_available(m)]
        if keyless:
            raise ValueError(f"No API key configured for: {', '.join(keyless)}")
        return list(dict.fromkeys(models))

    chosen = [m for m in DEFAULT_ARENA_MODELS if m in MODEL_REGISTRY and key_available(m)]
    if not chosen:
        chosen = [m for m in MODEL_REGISTRY if key_available(m)][:1]
    if not chosen:
        raise ValueError(
            "No API keys found. Set at least one of: "
            + ", ".join(meta["env_key"] for meta in FAMILY_META.values())
        )
    return chosen


def list_models() -> List[Dict[str, Any]]:
    return [
        {
            "id": model_id,
            "name": cfg.get("name", model_id),
            "family": cfg.get("family"),
            "legacy": cfg.get("desc") == "Legacy",
            "key_available": key_available(model_id),
        }
        for model_id, cfg in MODEL_REGISTRY.items()
    ]


# ─── Single run ──────────────────────────────────────────────────


async def stream_run(
    graph_app,
    thread_id: str,
    parent_checkpoint_id: Optional[str],
    model: str,
    prompt: str,
    toggles: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """One graph turn. Yields token events, then one ``end`` event.

    The ``end`` event carries the full reply and the checkpoint this run
    wrote (not its parent).
    """
    config = thread_config(thread_id, parent_checkpoint_id)
    run_id = tag_run(config)
    initial_state = {
        "active_peer": model,
        "messages": [("user", prompt)],
        "toggles": {"use_rag": False, **(toggles or {})},
    }
    buffer = ""
    async for event in graph_app.astream_events(initial_state, config, version="v2"):
        if event.get("event") != "on_chat_model_stream":
            continue
        if event.get("metadata", {}).get("langgraph_node") != "draft":
            continue
        chunk = event.get("data", {}).get("chunk")
        token = extract_text(chunk.content, strip=False) if chunk is not None and chunk.content else ""
        if token:
            buffer += token
            yield {"type": "token", "model": model, "token": token}

    final = await final_state_of_run(graph_app, thread_id, run_id)
    content = buffer
    if final:
        # Prefer the stored reply: it is what the tree shows, and it exists
        # even for models that don't stream.
        last_ai = next(
            (m for m in reversed(final.values.get("messages", [])) if getattr(m, "type", "") == "ai"),
            None,
        )
        if last_ai is not None:
            content = extract_text(last_ai.content) or buffer
    yield {
        "type": "end",
        "model": model,
        "content": content,
        "checkpoint_id": final.config["configurable"]["checkpoint_id"] if final else None,
        "error": None,
    }


# ─── Arena ───────────────────────────────────────────────────────


def build_synthesis_prompt(question: str, answers: List[Dict[str, str]]) -> str:
    body = "\n\n".join(f"[{a['model']}]:\n{a['content']}" for a in answers)
    return (
        f"Original question: {question}\n\n"
        f"Independent answers from {len(answers)} models:\n\n{body}\n\n"
        "Synthesize these into one answer. State where the models agree, resolve "
        "or flag where they contradict each other, and keep the strongest "
        "supported points. Attribute claims to models where it matters."
    )


async def run_arena(
    graph_app,
    prompt: str,
    thread_id: str,
    models: Optional[List[str]] = None,
    toggles: Optional[Dict[str, Any]] = None,
    synthesizer: Optional[str] = None,
    timeout: float = ARENA_TIMEOUT_SECONDS,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Ask every model the same question in parallel, then optionally synthesize.

    Events:
      start            {models, thread_id, parent_checkpoint_id}
      token            {model, token}
      end              {model, content, checkpoint_id, error}
      synthesis_start  {model}
      synthesis_token  {model, token}
      synthesis        {model, content, checkpoint_id, error}

    All answers fork from one checkpoint (see services/runs.py). The synthesis
    is a separate, explicit model call over those answers, written as another
    branch from the same checkpoint; it runs only when ``synthesizer`` is set
    and at least two models answered.
    """
    models = resolve_models(models)
    if synthesizer:
        resolve_models([synthesizer])

    parent = await resolve_fork_point(graph_app, thread_id)
    yield {"type": "start", "models": models, "thread_id": thread_id, "parent_checkpoint_id": parent}

    queue: asyncio.Queue = asyncio.Queue()

    async def _produce(model: str):
        try:
            async for event in stream_run(graph_app, thread_id, parent, model, prompt, toggles):
                await queue.put(event)
        except Exception as e:
            await queue.put({"type": "end", "model": model, "content": "", "checkpoint_id": None, "error": str(e)})

    tasks = [asyncio.create_task(_produce(m)) for m in models]
    answers: Dict[str, Dict[str, Any]] = {}
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        while len(answers) < len(models):
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            if event["type"] == "end":
                answers[event["model"]] = event
            yield event
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    for model in models:
        if model not in answers:
            event = {"type": "end", "model": model, "content": "", "checkpoint_id": None, "error": f"timed out after {timeout:.0f}s"}
            answers[model] = event
            yield event

    usable = [{"model": m, "content": answers[m]["content"]} for m in models if not answers[m]["error"] and answers[m]["content"]]
    if not synthesizer or len(usable) < 2:
        return

    async for event in _synthesize(graph_app, thread_id, parent, synthesizer, build_synthesis_prompt(prompt, usable), toggles):
        yield event


async def _synthesize(graph_app, thread_id, parent, synthesizer, synthesis_prompt, toggles):
    yield {"type": "synthesis_start", "model": synthesizer}
    try:
        async for event in stream_run(graph_app, thread_id, parent, synthesizer, synthesis_prompt, toggles):
            if event["type"] == "token":
                yield {"type": "synthesis_token", "model": synthesizer, "token": event["token"]}
            else:
                yield {**event, "type": "synthesis"}
    except Exception as e:
        yield {"type": "synthesis", "model": synthesizer, "content": "", "checkpoint_id": None, "error": str(e)}


async def collect(events: AsyncGenerator[Dict[str, Any], None]) -> Dict[str, Any]:
    """Drain a run_arena / synthesize_thread stream into one JSON-able result."""
    result: Dict[str, Any] = {"thread_id": None, "answers": {}, "synthesis": None}
    async for event in events:
        if event["type"] == "start":
            result["thread_id"] = event["thread_id"]
        elif event["type"] == "end":
            result["answers"][event["model"]] = {k: event[k] for k in ("content", "checkpoint_id", "error")}
        elif event["type"] == "synthesis":
            result["synthesis"] = {k: event[k] for k in ("model", "content", "checkpoint_id", "error")}
    return result


# ─── Synthesize an existing thread ───────────────────────────────


async def latest_branch_answers(graph_app, thread_id: str) -> List[Dict[str, Any]]:
    """The final AI reply on every branch tip of a thread, oldest first.

    For an arena turn that is each model's answer; for a branched chat it is
    where each line of the conversation ended up.
    """
    from app.services.tree import load_thread_states

    states = await load_thread_states(graph_app, thread_id)
    parents = {
        s.parent_config["configurable"]["checkpoint_id"]
        for s in states
        if s.parent_config
    }
    answers: List[Dict[str, Any]] = []
    seen: set = set()
    for s in sorted(states, key=lambda s: s.created_at or ""):
        cid = s.config["configurable"]["checkpoint_id"]
        if cid in parents or s.next:
            continue
        last_ai = next(
            (m for m in reversed(s.values.get("messages", [])) if getattr(m, "type", "") == "ai"),
            None,
        )
        if last_ai is None:
            continue
        content = extract_text(last_ai.content)
        if not content or content in seen:
            continue
        seen.add(content)
        answers.append({
            "model": getattr(last_ai, "name", None) or s.values.get("active_peer") or "model",
            "content": content,
            "checkpoint_id": cid,
        })
    return answers


async def synthesize_thread(
    graph_app,
    thread_id: str,
    synthesizer: str,
    toggles: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Synthesize the latest answer on every branch of a thread.

    Written as a new turn from the thread head. Raises ValueError when there is
    nothing to synthesize.
    """
    resolve_models([synthesizer])
    answers = await latest_branch_answers(graph_app, thread_id)
    if len(answers) < 2:
        raise ValueError(
            f"Thread {thread_id} has {len(answers)} branch answer(s); synthesis needs at least two."
        )
    question = await _latest_question(graph_app, thread_id)
    parent = await resolve_fork_point(graph_app, thread_id)
    yield {"type": "start", "models": [a["model"] for a in answers], "thread_id": thread_id, "parent_checkpoint_id": parent}
    for a in answers:
        yield {"type": "end", "model": a["model"], "content": a["content"], "checkpoint_id": a["checkpoint_id"], "error": None}
    async for event in _synthesize(graph_app, thread_id, parent, synthesizer, build_synthesis_prompt(question, answers), toggles):
        yield event


async def _latest_question(graph_app, thread_id: str) -> str:
    state = await graph_app.aget_state(thread_config(thread_id))
    for m in reversed(state.values.get("messages", []) if state.values else []):
        if getattr(m, "type", "") == "human":
            return extract_text(m.content)
    return "(see the answers below)"


# ─── Reading threads ─────────────────────────────────────────────


async def thread_messages(graph_app, thread_id: str, checkpoint_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """The conversation on one path (head by default), oldest first."""
    state = await graph_app.aget_state(thread_config(thread_id, checkpoint_id))
    if not state.values:
        raise ValueError(f"Thread {thread_id} not found.")
    out = []
    for m in state.values.get("messages", []):
        kind = getattr(m, "type", "")
        if kind not in ("human", "ai"):
            continue
        out.append({
            "role": "user" if kind == "human" else "assistant",
            "model": getattr(m, "name", None) if kind == "ai" else None,
            "content": extract_text(m.content),
        })
    return out
