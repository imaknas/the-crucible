"""MCP server: The Crucible as a tool for external agents.

Tools return structured data (dicts) and raise ToolError on failure, so an
agent sees an error result instead of a successful call whose text happens to
start with "Error:".

Run with:  uv run python -m app.mcp_server   (stdio transport)
"""

import functools
import inspect
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from app.core import database as db
from app.services import arena as arena_svc
from app.services import debate as debate_svc

load_dotenv()

mcp = FastMCP("The Crucible")


def _quiet(fn):
    """Keep the graph's print() diagnostics off stdout, which is the stdio transport."""
    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            with arena_svc.stdout_to_stderr():
                return await fn(*args, **kwargs)
    else:

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with arena_svc.stdout_to_stderr():
                return fn(*args, **kwargs)

    return wrapper


def _tool_error(e: Exception) -> ToolError:
    return ToolError(str(e) or e.__class__.__name__)


@mcp.tool()
@_quiet
def list_models(include_legacy: bool = False) -> Dict[str, Any]:
    """List model IDs usable in other tools, and whether each has an API key configured.

    Only models with key_available=true can actually be called.
    """
    models = [m for m in arena_svc.list_models() if include_legacy or not m["legacy"]]
    return {"models": models}


@mcp.tool()
@_quiet
async def invoke_arena(
    prompt: str,
    models: Optional[List[str]] = None,
    thread_id: Optional[str] = None,
    synthesize: bool = True,
    synthesizer: Optional[str] = None,
    use_rag: bool = False,
    use_web_search: bool = False,
) -> Dict[str, Any]:
    """Ask several models the same question in parallel and collect every answer.

    Each model answers independently on its own branch of the thread. When
    synthesize is true and at least two models answered, one more call
    (synthesizer, default: the first model) combines the answers.

    Args:
        prompt: The question.
        models: Model IDs (see list_models). Default: the standard arena trio, limited to models with keys.
        thread_id: Continue an existing thread; a new one is created otherwise.
        synthesize: Whether to add a synthesis of the answers.
        synthesizer: Model ID that writes the synthesis.
        use_rag: Search documents uploaded to this thread.
        use_web_search: Let models that support it search the web.

    Returns: {thread_id, answers: {model: {content, checkpoint_id, error}}, synthesis: {model, content, checkpoint_id, error} | null}
    """
    new_thread = not thread_id
    thread_id = thread_id or f"mcp-{uuid4().hex[:8]}"
    try:
        resolved = arena_svc.resolve_models(models)
        chosen_synth = (synthesizer or resolved[0]) if synthesize else None
        async with arena_svc.open_graph() as graph_app:
            result = await arena_svc.collect(
                arena_svc.run_arena(
                    graph_app,
                    prompt,
                    thread_id,
                    resolved,
                    {"use_rag": use_rag, "use_web_search": use_web_search},
                    chosen_synth,
                )
            )
    except ValueError as e:
        raise _tool_error(e)
    if new_thread:
        db.rename_thread(thread_id, f"Arena: {prompt[:40]}")
    if result["answers"] and all(a["error"] for a in result["answers"].values()):
        errors = "; ".join(f"{m}: {a['error']}" for m, a in result["answers"].items())
        raise ToolError(f"Every model failed (thread {thread_id}): {errors}")
    return result


@mcp.tool()
@_quiet
async def run_debate(
    prompt: str,
    models: List[str],
    max_rounds: int = 3,
    convergence_threshold: Optional[float] = None,
    mode: Literal["all", "any"] = "all",
    convergence_judge: Optional[str] = None,
    synthesizer: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a multi-round structured debate between two or more models.

    Every round, each model sees its peers' previous answers and responds. The
    debate stops after max_rounds, or earlier if convergence_threshold
    (cosine similarity between a model's consecutive answers, 0-1) or the
    convergence_judge model says the positions have converged. If synthesizer
    is set, it writes a final synthesis. This can take several minutes.

    Returns: {session_id, thread_id, rounds: [{round, responses, errors, convergence_score}], converged, synthesis}
    """
    if len(models) < 2:
        raise ToolError("A debate needs at least two models.")
    try:
        arena_svc.resolve_models(models + [m for m in (synthesizer, convergence_judge) if m])
    except ValueError as e:
        raise _tool_error(e)

    thread_id = thread_id or f"mcp-debate-{uuid4().hex[:8]}"
    async with arena_svc.open_graph() as graph_app:
        session = debate_svc.create_session(
            parent_thread_id=thread_id,
            participants=models,
            termination_policy={
                "max_rounds": max_rounds,
                "convergence_threshold": convergence_threshold,
                "llm_judge": convergence_judge,
                "mode": mode,
            },
            auto_synthesize=bool(synthesizer),
            synthesizer_model=synthesizer,
        )
        if not db.get_thread_title(thread_id):
            db.rename_thread(thread_id, f"Debate: {prompt[:40]}")

        result: Dict[str, Any] = {
            "session_id": session["session_id"],
            "thread_id": thread_id,
            "rounds": [],
            "converged": None,
            "synthesis": None,
        }
        current: Optional[Dict[str, Any]] = None
        finished = False
        try:
            async for event in debate_svc.run_debate(graph_app, session["session_id"], prompt, {}, {}):
                kind = event["type"]
                if kind == "debate_round_start":
                    current = {"round": event["round"], "responses": {}, "errors": {}, "convergence_score": None}
                    result["rounds"].append(current)
                elif kind == "stream_end" and current is not None:
                    current["responses"][event["model"]] = event.get("content", "")
                elif kind == "error" and event.get("model") and current is not None:
                    current["errors"][event["model"]] = event["message"]
                elif kind == "debate_round_end" and current is not None:
                    current["convergence_score"] = event.get("convergence_score")
                elif kind == "debate_converged":
                    result["converged"] = {k: event.get(k) for k in ("round", "score", "reason", "method")}
                elif kind == "debate_synthesis_end":
                    result["synthesis"] = {"model": event["model"], "content": event["content"]}
                elif kind == "debate_session_status" and event.get("status") == "completed":
                    finished = True
        finally:
            if not finished:
                db.update_debate_session(session["session_id"], status="interrupted")
    return result


@mcp.tool()
@_quiet
def list_threads() -> Dict[str, Any]:
    """List conversation threads (id and title), newest first."""
    db.init_db()
    return {"threads": db.list_threads()}


@mcp.tool()
@_quiet
async def get_thread_messages(thread_id: str, checkpoint_id: Optional[str] = None) -> Dict[str, Any]:
    """Read the conversation on one path of a thread, oldest first.

    Defaults to the most recent path; pass a checkpoint_id (from invoke_arena's
    answers) to read a specific model's branch.
    """
    async with arena_svc.open_graph() as graph_app:
        try:
            messages = await arena_svc.thread_messages(graph_app, thread_id, checkpoint_id)
        except ValueError as e:
            raise _tool_error(e)
    return {"thread_id": thread_id, "checkpoint_id": checkpoint_id, "messages": messages}


@mcp.tool()
@_quiet
async def get_branch_answers(thread_id: str) -> Dict[str, Any]:
    """The latest answer on every branch of a thread, e.g. each model's arena answer."""
    async with arena_svc.open_graph() as graph_app:
        answers = await arena_svc.latest_branch_answers(graph_app, thread_id)
    if not answers:
        raise ToolError(f"Thread {thread_id} not found or has no answers.")
    return {"thread_id": thread_id, "answers": answers}


@mcp.tool()
@_quiet
async def get_thread_summary(thread_id: str) -> Dict[str, Any]:
    """The thread's rolling thesis plus its latest context summary, if one has been written.

    Summaries only exist once a thread outgrows a model's context budget.
    """
    async with arena_svc.open_graph() as graph_app:
        state = await graph_app.aget_state({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    if not state.values:
        raise ToolError(f"Thread {thread_id} not found.")
    summary = None
    for msg in reversed(state.values.get("messages", [])):
        content = str(msg.content)
        if "PREVIOUS CONTEXT SUMMARY:" in content:
            summary = content.split("PREVIOUS CONTEXT SUMMARY:", 1)[1].strip()
            break
    return {
        "thread_id": thread_id,
        "thesis": state.values.get("current_thesis") or None,
        "context_summary": summary,
    }


@mcp.tool()
@_quiet
async def get_thread_status(thread_id: str) -> Dict[str, Any]:
    """Latest model, thesis and message count on the thread's most recent path."""
    async with arena_svc.open_graph() as graph_app:
        state = await graph_app.aget_state({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    if not state.values:
        raise ToolError(f"Thread {thread_id} not found.")
    return {
        "thread_id": thread_id,
        "title": db.get_thread_title(thread_id),
        "active_model": state.values.get("active_peer"),
        "thesis": state.values.get("current_thesis") or None,
        "message_count": len(state.values.get("messages", [])),
        "checkpoint_id": state.config["configurable"].get("checkpoint_id"),
    }


if __name__ == "__main__":
    mcp.run()
