"""Arena and synthesis runs, and the entry points the CLI and the MCP server share.

Every turn here is chat.stream_turn, the same turn the web UI runs over its
socket, so a feature of a turn (attached documents, Deliberation, a branch
point, a tagged synthesis) exists for every client at once.
"""

import asyncio
import sys
from contextlib import asynccontextmanager, redirect_stdout
from typing import Any, AsyncGenerator, Dict, List, Mapping, Optional, Sequence

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.registry import DEFAULT_ARENA_MODELS, FAMILY_META, MODEL_REGISTRY, display_name
from app.core import database as db
from app.llm import has_credentials
from app.services.chat import stream_turn
from app.services.graph import workflow
from app.services.context import DEFAULT_CONTEXT, ContextSettings
from app.services.synthesis import INDEPENDENT, build_synthesis_prompt
from app.services.runs import SYNTHESIS_TURN, fork_point, thread_config
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


# ─── One model's turn ────────────────────────────────────────────


async def model_turn(
    graph_app,
    thread_id: str,
    parent_checkpoint_id: Optional[str],
    model: str,
    prompt: Optional[str],
    toggles: Optional[Mapping[str, bool]] = None,
    context: ContextSettings = DEFAULT_CONTEXT,
    *,
    documents: Optional[Mapping[str, str]] = None,
    is_deliberation: bool = False,
    turn_kind: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """chat.stream_turn as model-tagged events: ``token`` {model, token}, then
    ``end`` {model, content, checkpoint_id, error}. Raises on failure."""
    async for event in stream_turn(
        graph_app,
        thread_id,
        parent_checkpoint_id,
        message=prompt,
        model=model,
        toggles=toggles,
        documents=documents,
        is_deliberation=is_deliberation,
        context=context,
        turn_kind=turn_kind,
    ):
        if event["type"] == "token":
            yield {"type": "token", "model": model, "token": event["token"]}
        else:
            yield {
                "type": "end",
                "model": model,
                "content": event["content"],
                "checkpoint_id": event["checkpoint_id"],
                "error": None,
            }


async def turn_parent(
    graph_app,
    thread_id: str,
    checkpoint_id: Optional[str] = None,
    after_debate: Optional[str] = None,
):
    """Where a turn forks from, and whether the thread was empty: the given
    checkpoint, the record of a finished debate on this thread
    (debate.continue_from_debate), or the thread head."""
    if after_debate:
        if checkpoint_id:
            raise ValueError("Pass a checkpoint or a debate to continue, not both.")
        from app.services.debate import continue_from_debate

        session = db.get_debate_session(after_debate)
        if not session:
            raise ValueError(f"Debate session {after_debate} not found.")
        if session["parent_thread_id"] != thread_id:
            raise ValueError(f"Debate session {after_debate} belongs to thread {session['parent_thread_id']}, not {thread_id}.")
        return await continue_from_debate(graph_app, after_debate), False
    return await fork_point(graph_app, thread_id, checkpoint_id)


# ─── Arena ───────────────────────────────────────────────────────


def _independent_synthesis_prompt(question: str, answers: List[Dict[str, Any]]) -> str:
    return build_synthesis_prompt(
        question, ((display_name(a["model"]), a["content"]) for a in answers), INDEPENDENT
    )


async def run_arena(
    graph_app,
    prompt: str,
    thread_id: str,
    models: Optional[List[str]] = None,
    toggles: Optional[Dict[str, Any]] = None,
    synthesizer: Optional[str] = None,
    timeout: float = ARENA_TIMEOUT_SECONDS,
    context: ContextSettings = DEFAULT_CONTEXT,
    *,
    parent_checkpoint_id: Optional[str] = None,
    after_debate: Optional[str] = None,
    documents: Optional[Mapping[str, str]] = None,
    is_deliberation: bool = False,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Ask every model the same question in parallel, then optionally synthesize.

    Events:
      start            {models, thread_id, parent_checkpoint_id, new_thread}
      token            {model, token}
      end              {model, content, checkpoint_id, error}
      synthesis_start  {model}
      synthesis_token  {model, token}
      synthesis        {model, content, checkpoint_id, error}

    All answers fork from one checkpoint (see services/runs.py): the thread
    head, ``parent_checkpoint_id``, or the record of the debate
    ``after_debate``. ``is_deliberation`` makes it a Deliberation turn: each
    model critically reviews the conversation. The synthesis is a separate,
    explicit model call over the answers, written as another branch from the
    same checkpoint; it runs only when ``synthesizer`` is set and at least two
    models answered.
    """
    models = resolve_models(models)
    if synthesizer:
        resolve_models([synthesizer])

    parent, new_thread = await turn_parent(graph_app, thread_id, parent_checkpoint_id, after_debate)
    yield {"type": "start", "models": models, "thread_id": thread_id, "parent_checkpoint_id": parent, "new_thread": new_thread}

    queue: asyncio.Queue = asyncio.Queue()

    async def _produce(model: str):
        try:
            async for event in model_turn(graph_app, thread_id, parent, model, prompt, toggles, context,
                                          documents=documents, is_deliberation=is_deliberation):
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

    usable = [answers[m] for m in models if not answers[m]["error"] and answers[m]["content"]]
    if not synthesizer or len(usable) < 2:
        return

    asked = await question_point(graph_app, thread_id, usable[0]["checkpoint_id"])
    async for event in _synthesize(graph_app, thread_id, asked, synthesizer, _independent_synthesis_prompt(prompt, usable), toggles, context):
        yield event


async def _synthesize(graph_app, thread_id, parent, synthesizer, synthesis_prompt, toggles, context=DEFAULT_CONTEXT):
    yield {"type": "synthesis_start", "model": synthesizer}
    try:
        async for event in model_turn(graph_app, thread_id, parent, synthesizer, synthesis_prompt, toggles, context,
                                      turn_kind=SYNTHESIS_TURN):
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
            result["parent_checkpoint_id"] = event["parent_checkpoint_id"]
        elif event["type"] == "end":
            result["answers"][event["model"]] = {k: event[k] for k in ("content", "checkpoint_id", "error")}
        elif event["type"] == "synthesis":
            result["synthesis"] = {k: event[k] for k in ("model", "content", "checkpoint_id", "error")}
    return result


# ─── Synthesize existing answers ─────────────────────────────────


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


async def answer_at(graph_app, thread_id: str, checkpoint_id: str) -> Dict[str, Any]:
    """The reply a checkpoint ends on and the question it answered:
    {model, content, checkpoint_id, question}. Raises ValueError if there is none."""
    state = await graph_app.aget_state(thread_config(thread_id, checkpoint_id))
    messages = (state.values or {}).get("messages", []) if state else []
    if not messages or getattr(messages[-1], "type", "") != "ai":
        raise ValueError(f"Checkpoint {checkpoint_id} on thread {thread_id} is not a reply.")
    last = messages[-1]
    question = next((extract_text(m.content) for m in reversed(messages) if getattr(m, "type", "") == "human"), "")
    return {
        "model": getattr(last, "name", None) or state.values.get("active_peer") or "model",
        "content": extract_text(last.content),
        "checkpoint_id": checkpoint_id,
        "question": question,
    }


def _ends_on_question(state) -> bool:
    messages = (state.values or {}).get("messages", []) if state else []
    return bool(messages) and getattr(messages[-1], "type", "") == "human"


async def question_point(graph_app, thread_id: str, answer_checkpoint_id: str) -> str:
    """The checkpoint where the question a reply answers was asked: the
    tree's node for that question, which a synthesis of its answers hangs
    from, as in the web UI. The reply's own checkpoint if no question
    precedes it."""
    state = await graph_app.aget_state(thread_config(thread_id, answer_checkpoint_id))
    while state is not None and not _ends_on_question(state) and state.parent_config:
        state = await graph_app.aget_state(state.parent_config)
    if not _ends_on_question(state):
        return answer_checkpoint_id
    # The run writes several checkpoints ending on the question; the first is
    # the tree's node.
    while state.parent_config:
        parent = await graph_app.aget_state(state.parent_config)
        if not _ends_on_question(parent):
            break
        state = parent
    return state.config["configurable"]["checkpoint_id"]


async def synthesis_request(graph_app, thread_id: str, checkpoint_ids: Sequence[str]) -> str:
    """The prompt asking a model to synthesize the replies at ``checkpoint_ids``
    (answers written independently, as an arena turn's are)."""
    answers = [await answer_at(graph_app, thread_id, cid) for cid in dict.fromkeys(checkpoint_ids)]
    if len(answers) < 2:
        raise ValueError(f"Synthesis needs at least two answers; got {len(answers)}.")
    return _independent_synthesis_prompt(answers[0]["question"] or "(see the answers below)", answers)


async def synthesize_thread(
    graph_app,
    thread_id: str,
    synthesizer: str,
    toggles: Optional[Dict[str, Any]] = None,
    context: ContextSettings = DEFAULT_CONTEXT,
    *,
    checkpoint_ids: Optional[Sequence[str]] = None,
    parent_checkpoint_id: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Synthesize answers already on a thread.

    By default the latest answer on every branch, written as a new turn from
    the thread head. With ``checkpoint_ids``, exactly those replies (the web
    UI's "Synthesize answers"), written beside them: from
    ``parent_checkpoint_id``, else the question they answer (question_point).
    Raises ValueError when there is nothing to synthesize.
    """
    resolve_models([synthesizer])
    if checkpoint_ids:
        picked = [await answer_at(graph_app, thread_id, cid) for cid in dict.fromkeys(checkpoint_ids)]
        if len(picked) < 2:
            raise ValueError(f"Synthesis needs at least two answers; got {len(picked)}.")
        answers = picked
        question = picked[0]["question"] or "(see the answers below)"
        parent, _ = await fork_point(
            graph_app, thread_id,
            parent_checkpoint_id or await question_point(graph_app, thread_id, picked[0]["checkpoint_id"]),
        )
    else:
        answers = await latest_branch_answers(graph_app, thread_id)
        if len(answers) < 2:
            raise ValueError(
                f"Thread {thread_id} has {len(answers)} branch answer(s); synthesis needs at least two."
            )
        question = await _latest_question(graph_app, thread_id)
        parent, _ = await fork_point(graph_app, thread_id, parent_checkpoint_id)
    yield {"type": "start", "models": [a["model"] for a in answers], "thread_id": thread_id, "parent_checkpoint_id": parent, "new_thread": False}
    for a in answers:
        yield {"type": "end", "model": a["model"], "content": a["content"], "checkpoint_id": a["checkpoint_id"], "error": None}
    async for event in _synthesize(graph_app, thread_id, parent, synthesizer, _independent_synthesis_prompt(question, answers), toggles, context):
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
    from app.services.tree import is_synthesis_prompt

    out = []
    for m in state.values.get("messages", []):
        kind = getattr(m, "type", "")
        if kind not in ("human", "ai") or is_synthesis_prompt(m):
            continue
        out.append({
            "role": "user" if kind == "human" else "assistant",
            "model": getattr(m, "name", None) if kind == "ai" else None,
            "content": extract_text(m.content),
        })
    return out
