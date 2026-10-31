"""MCP server: The Crucible as a tool for external agents.

Everything the web UI does to a conversation is a tool here (the parity
table in tests/test_parity.py keeps it that way), except writing API keys:
a key passed through a tool call goes through the calling model's context.

Tools return structured data (dicts) and raise ToolError on failure, so an
agent sees an error result instead of a successful call whose text happens to
start with "Error:".

Run with:  uv run python -m app.mcp_server   (stdio transport)
"""

import asyncio
import logging
import sys
import functools
import inspect
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from app.registry import DEFAULT_MODEL
from app.core import database as db
from app.core.schema import is_summary_message, summary_text
from app.services import arena as arena_svc
from app.services import debate as debate_svc
from app.services import history
from app.services.context import ContextSettings
from app.services.uploads import read_documents
from app.utils.helpers import extract_text


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


def _context(system_prompt: Optional[str] = None, summarizer: Optional[str] = None) -> ContextSettings:
    context = ContextSettings.from_frame({"system_prompt": system_prompt, "summarizer": summarizer})
    if problem := context.problem():
        raise ToolError(problem)
    return context


def _attachments(paths: Optional[List[str]]) -> Dict[str, str]:
    try:
        return read_documents(paths)
    except ValueError as e:
        raise _tool_error(e)


def _toggles(use_web_search: bool, use_rag: bool) -> Dict[str, bool]:
    return {"use_web_search": use_web_search, "use_rag": use_rag}


def _thread_for(thread_id: Optional[str], after_debate_session_id: Optional[str], prefix: str) -> str:
    if thread_id:
        return thread_id
    if after_debate_session_id:
        session = db.get_debate_session(after_debate_session_id)
        if not session:
            raise ToolError(f"Debate session {after_debate_session_id} not found.")
        return session["parent_thread_id"]
    return f"{prefix}-{uuid4().hex[:8]}"


# ─── Models ──────────────────────────────────────────────────────


@mcp.tool()
@_quiet
def list_models(include_legacy: bool = False) -> Dict[str, Any]:
    """List model IDs usable in other tools, and whether each has an API key configured.

    Only models with key_available=true can actually be called.
    """
    models = [m for m in arena_svc.list_models() if include_legacy or not m["legacy"]]
    return {"models": models}


# ─── Turns ───────────────────────────────────────────────────────


@mcp.tool()
@_quiet
async def invoke_arena(
    prompt: str = "",
    models: Optional[List[str]] = None,
    thread_id: Optional[str] = None,
    parent_checkpoint_id: Optional[str] = None,
    after_debate_session_id: Optional[str] = None,
    deliberation: bool = False,
    synthesize: bool = True,
    synthesizer: Optional[str] = None,
    attachments: Optional[List[str]] = None,
    use_rag: bool = False,
    use_web_search: bool = False,
    system_prompt: Optional[str] = None,
    summarizer: Optional[str] = None,
) -> Dict[str, Any]:
    """Ask one or more models the same question in parallel and collect every answer.

    Each model answers independently on its own branch of the thread. When
    synthesize is true and at least two models answered, one more call
    (synthesizer, default: the first model) combines the answers. With one
    model and synthesize=false this is a plain chat turn.

    Args:
        prompt: The question (optional with deliberation).
        models: Model IDs (see list_models). Default: the standard arena trio, limited to models with keys.
        thread_id: Continue an existing thread; a new one is created otherwise.
        parent_checkpoint_id: Branch from this checkpoint (see get_thread_tree) instead of the latest answer. To edit a message, branch from the checkpoint before it.
        after_debate_session_id: Continue the thread after this finished debate; its rounds and synthesis become context.
        deliberation: Deliberation: each model critically reviews the conversation so far instead of answering a new question; no synthesis.
        synthesize: Whether to add a synthesis of the answers.
        synthesizer: Model ID that writes the synthesis.
        attachments: Local file paths (.pdf .txt .md .csv) whose text is in this turn's context.
        use_rag: Search documents uploaded to this thread (upload_document).
        use_web_search: Let models that support it search the web.
        system_prompt: Instructions sent to every model (and the synthesizer) before the conversation. Default: none, so each model answers as it ships.
        summarizer: Model that summarizes history once the thread outgrows a model's budget. Default: the app's.

    Returns: {thread_id, parent_checkpoint_id, answers: {model: {content, checkpoint_id, error}}, synthesis: {model, content, checkpoint_id, error} | null}
    """
    if not prompt.strip() and not deliberation:
        raise ToolError("A prompt is required (it is optional only with deliberation).")
    new_thread = not thread_id and not after_debate_session_id
    thread_id = _thread_for(thread_id, after_debate_session_id, "mcp")
    context = _context(system_prompt, summarizer)
    documents = _attachments(attachments)
    try:
        resolved = arena_svc.resolve_models(models)
        chosen_synth = (synthesizer or resolved[0]) if synthesize and not deliberation else None
        async with arena_svc.open_graph() as graph_app:
            result = await arena_svc.collect(
                arena_svc.run_arena(
                    graph_app,
                    prompt,
                    thread_id,
                    resolved,
                    _toggles(use_web_search, use_rag),
                    chosen_synth,
                    context=context,
                    parent_checkpoint_id=parent_checkpoint_id,
                    after_debate=after_debate_session_id,
                    documents=documents,
                    is_deliberation=deliberation,
                )
            )
    except ValueError as e:
        raise _tool_error(e)
    if new_thread:
        db.rename_thread(thread_id, f"{'Deliberation' if deliberation else 'Arena'}: {prompt[:40]}")
    if result["answers"] and all(a["error"] for a in result["answers"].values()):
        errors = "; ".join(f"{m}: {a['error']}" for m, a in result["answers"].items())
        raise ToolError(f"Every model failed (thread {thread_id}): {errors}")
    return result


@mcp.tool()
@_quiet
async def synthesize_answers(
    thread_id: str,
    checkpoint_ids: Optional[List[str]] = None,
    synthesizer: Optional[str] = None,
    parent_checkpoint_id: Optional[str] = None,
    system_prompt: Optional[str] = None,
    summarizer: Optional[str] = None,
) -> Dict[str, Any]:
    """Synthesize answers already on a thread into one, as a new reply.

    Args:
        thread_id: The thread.
        checkpoint_ids: The answers to synthesize (checkpoints from invoke_arena or get_thread_tree). Default: the latest answer on every branch.
        synthesizer: Model that writes it. Default: the app's default model.
        parent_checkpoint_id: Where the synthesis goes. Default: beside the chosen answers, else the latest answer.

    Returns: {thread_id, parent_checkpoint_id, answers: {model: {...}}, synthesis: {model, content, checkpoint_id, error}}
    """
    context = _context(system_prompt, summarizer)
    try:
        async with arena_svc.open_graph() as graph_app:
            result = await arena_svc.collect(arena_svc.synthesize_thread(
                graph_app, thread_id, synthesizer or DEFAULT_MODEL, context=context,
                checkpoint_ids=checkpoint_ids, parent_checkpoint_id=parent_checkpoint_id,
            ))
    except ValueError as e:
        raise _tool_error(e)
    if not result["synthesis"] or result["synthesis"]["error"]:
        raise ToolError(f"Synthesis failed: {(result['synthesis'] or {}).get('error')}")
    return result


# ─── Debates ─────────────────────────────────────────────────────


async def _collect_debate(events, session: Dict[str, Any]) -> Dict[str, Any]:
    """A debate run's events as one result; the session is marked
    interrupted if the run doesn't finish (the call was cancelled)."""
    result: Dict[str, Any] = {
        "session_id": session["session_id"],
        "thread_id": session["parent_thread_id"],
        "rounds": [],
        "converged": None,
        "synthesis": None,
        "errors": [],
    }
    current: Optional[Dict[str, Any]] = None
    finished = False
    try:
        async for event in events:
            kind = event["type"]
            if kind == "debate_round_start":
                current = {"round": event["round"], "responses": {}, "errors": {}, "convergence_score": None}
                result["rounds"].append(current)
            elif kind == "stream_end" and current is not None:
                current["responses"][event["model"]] = event.get("content", "")
            elif kind == "error":
                if event.get("model") and current is not None:
                    current["errors"][event["model"]] = event["message"]
                else:
                    result["errors"].append(event["message"])
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
            await asyncio.to_thread(db.update_debate_session, session["session_id"], status="interrupted")
    if not finished and result["errors"] and not result["rounds"]:
        raise ToolError(result["errors"][0])
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
    parent_checkpoint_id: Optional[str] = None,
    peer_labels: Literal["anonymous", "named"] = "anonymous",
    attachments: Optional[List[str]] = None,
    use_rag: bool = False,
    use_web_search: bool = False,
    system_prompt: Optional[str] = None,
    summarizer: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a multi-round structured debate between two or more models.

    Every round, each model sees its peers' previous answers and responds. The
    debate stops after max_rounds, or earlier if convergence_threshold is
    reached by every model (cosine similarity between each model's answer
    and its own previous one, 0-1: stability, not agreement) or the
    convergence_judge model says the models agree. With both set, mode="all"
    needs both, mode="any" either. Models see each other as "Participant A/B…"
    unless peer_labels="named". If synthesizer is set, it writes an argument
    map: the positions, their strongest arguments, who changed position and
    why, and what is unresolved. Use it to see the arguments, not as a
    trustworthy answer: debating models conform to each other, so for an
    answer prefer invoke_arena's independent answers and synthesis. This can
    take several minutes; to pause, run fewer rounds and resume (or inject a
    message) with continue_debate.

    parent_checkpoint_id: a checkpoint of thread_id the debate starts from
    (the models see that conversation first). attachments: local files in
    every round's context. system_prompt is sent to every participant (and
    the synthesizer) before the conversation; default none.

    Returns: {session_id, thread_id, rounds: [{round, responses, errors, convergence_score}], converged, synthesis, errors}.
    convergence_score is that round's stability; converged.method says why the
    debate stopped early: "stability" or "judge" (agreement).
    """
    if len(models) < 2:
        raise ToolError("A debate needs at least two models.")
    if parent_checkpoint_id and not thread_id:
        raise ToolError("parent_checkpoint_id needs the thread_id it belongs to.")
    context = _context(system_prompt, summarizer)
    documents = _attachments(attachments)
    try:
        arena_svc.resolve_models(models + [m for m in (synthesizer, convergence_judge) if m])
    except ValueError as e:
        raise _tool_error(e)

    thread_id = thread_id or f"mcp-debate-{uuid4().hex[:8]}"
    async with arena_svc.open_graph() as graph_app:
        try:
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
                peer_labels=peer_labels,
            )
        except ValueError as e:
            raise _tool_error(e)
        if not db.get_thread_title(thread_id):
            db.rename_thread(thread_id, f"Debate: {prompt[:40]}")
        return await _collect_debate(
            debate_svc.run_debate(graph_app, session["session_id"], prompt, _toggles(use_web_search, use_rag), documents,
                                  parent_checkpoint_id=parent_checkpoint_id, context=context),
            session,
        )


def _idle_session(session_id: str, force: bool) -> Dict[str, Any]:
    session = db.get_debate_session(session_id)
    if not session:
        raise ToolError(f"Debate session {session_id} not found.")
    try:
        debate_svc.check_not_running(session, force)
    except ValueError as e:
        raise _tool_error(e)
    return session


@mcp.tool()
@_quiet
async def continue_debate(
    session_id: str,
    rounds: int = 1,
    inject: Optional[List[str]] = None,
    use_rag: bool = False,
    use_web_search: bool = False,
    system_prompt: Optional[str] = None,
    summarizer: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Run more rounds of a debate that stopped: resume after running fewer
    rounds (a pause), or add messages (inject) to the next round's prompts.
    The session's auto-synthesis, if set, is rewritten over every round.
    Refused while another client runs the debate; force=true only for one
    left marked running by a backend that died.

    Returns the same shape as run_debate, for the new rounds.
    """
    context = _context(system_prompt, summarizer)
    session = _idle_session(session_id, force)
    async with arena_svc.open_graph() as graph_app:
        return await _collect_debate(
            debate_svc.continue_debate(graph_app, session_id, rounds, inject or (),
                                       _toggles(use_web_search, use_rag), context=context),
            session,
        )


@mcp.tool()
@_quiet
async def redirect_debate(
    session_id: str,
    prompt: str,
    attachments: Optional[List[str]] = None,
    use_rag: bool = False,
    use_web_search: bool = False,
    system_prompt: Optional[str] = None,
    summarizer: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Restart a debate on a new question, from where each participant's
    lane stands (they keep what was said). Runs the session's rounds again.
    Refused while another client runs the debate (see continue_debate's force).

    Returns the same shape as run_debate.
    """
    context = _context(system_prompt, summarizer)
    documents = _attachments(attachments)
    session = _idle_session(session_id, force)
    async with arena_svc.open_graph() as graph_app:
        return await _collect_debate(
            debate_svc.run_debate(graph_app, session_id, prompt, _toggles(use_web_search, use_rag), documents,
                                  context=context),
            session,
        )


@mcp.tool()
@_quiet
async def synthesize_debate(
    session_id: str,
    synthesizer: Optional[str] = None,
    system_prompt: Optional[str] = None,
    summarizer: Optional[str] = None,
) -> Dict[str, Any]:
    """Write (or rewrite) a debate's argument map from every round.

    Args:
        synthesizer: Model that writes it. Default: the session's synthesizer, else its first participant.

    Returns: {session_id, synthesis: {model, content, checkpoint_id}}
    """
    context = _context(system_prompt, summarizer)
    result: Dict[str, Any] = {"session_id": session_id, "synthesis": None}
    async with arena_svc.open_graph() as graph_app:
        async for event in debate_svc.synthesize_session(graph_app, session_id, prompt="", synthesizer=synthesizer,
                                                         context=context):
            if event["type"] == "error":
                raise ToolError(event["message"])
            if event["type"] == "debate_synthesis_end":
                result["synthesis"] = {k: event.get(k) for k in ("model", "content", "checkpoint_id")}
    return result


@mcp.tool()
@_quiet
def list_debates(thread_id: Optional[str] = None) -> Dict[str, Any]:
    """Debate sessions (newest first), optionally only one thread's: id,
    participants, status, current round, policy."""
    db.init_db()
    return {"sessions": db.list_debate_sessions(thread_id)}


@mcp.tool()
@_quiet
async def get_debate(session_id: str) -> Dict[str, Any]:
    """Everything a debate said: the question, each participant's replies
    round by round, the label each was shown under ("Participant A"), and
    the synthesis ("" if none).

    Returns: {session, question, labels: {model: label}, rounds: {model: [reply per round]}, synthesis}
    """
    async with arena_svc.open_graph() as graph_app:
        try:
            return await debate_svc.session_record(graph_app, session_id)
        except ValueError as e:
            raise _tool_error(e)


@mcp.tool()
@_quiet
def delete_debate(session_id: str) -> Dict[str, Any]:
    """Delete a debate and its lanes; the thread it started from stays."""
    db.init_db()
    if not db.get_debate_session(session_id):
        raise ToolError(f"Debate session {session_id} not found.")
    db.delete_debate_session(session_id)
    return {"deleted": session_id}


# ─── Threads ─────────────────────────────────────────────────────


@mcp.tool()
@_quiet
def list_threads() -> Dict[str, Any]:
    """List conversation threads (id and title), newest first."""
    db.init_db()
    return {"threads": db.list_threads()}


@mcp.tool()
@_quiet
def rename_thread(thread_id: str, title: str) -> Dict[str, Any]:
    """Give a thread a new title."""
    if not title.strip():
        raise ToolError("A title is required.")
    db.init_db()
    db.rename_thread(thread_id, title.strip())
    return {"thread_id": thread_id, "title": title.strip()}


@mcp.tool()
@_quiet
async def delete_thread(thread_id: str) -> Dict[str, Any]:
    """Delete a thread with its debates, uploaded files and their search index. Cannot be undone."""
    from app.services.threads import default_thread_deleter

    db.init_db()
    await asyncio.to_thread(default_thread_deleter(), thread_id)
    return {"deleted": thread_id}


@mcp.tool()
@_quiet
async def get_thread_tree(thread_id: str) -> Dict[str, Any]:
    """The conversation tree: every node with its checkpoint id, parent,
    role, model and a preview. Checkpoint ids are what parent_checkpoint_id,
    synthesize_answers, get_thread_messages and delete_branch take.

    Returns: {thread_id, current_checkpoint (where the next turn goes by default), nodes: [{checkpoint_id, parent, role, model, model_name, kind, preview}]}
    """
    async with arena_svc.open_graph() as graph_app:
        data = await history.thread_tree(graph_app, thread_id)
    if not data["nodes"]:
        raise ToolError(f"Thread {thread_id} not found.")
    parents = {e["target"]: e["source"] for e in data["edges"]}
    nodes = []
    for n in data["nodes"]:
        meta = n.get("metadata", {})
        nodes.append({
            "checkpoint_id": n["id"],
            "parent": parents.get(n["id"]),
            "role": meta.get("role"),
            "model": meta.get("active_peer") if meta.get("role") == "ai" else None,
            "model_name": meta.get("model_name") if meta.get("role") == "ai" else None,
            "kind": meta.get("kind"),
            "preview": meta.get("preview") or n.get("data", {}).get("label", ""),
        })
    return {"thread_id": thread_id, "current_checkpoint": data["current_checkpoint"], "nodes": nodes}


@mcp.tool()
@_quiet
async def get_thread_messages(thread_id: str, checkpoint_id: Optional[str] = None) -> Dict[str, Any]:
    """Read the conversation on one path of a thread, oldest first.

    Defaults to the most recent path; pass a checkpoint_id (from invoke_arena's
    answers or get_thread_tree) to read that branch.
    """
    async with arena_svc.open_graph() as graph_app:
        try:
            messages = await arena_svc.thread_messages(graph_app, thread_id, checkpoint_id)
        except ValueError as e:
            raise _tool_error(e)
    return {"thread_id": thread_id, "checkpoint_id": checkpoint_id, "messages": messages}


@mcp.tool()
@_quiet
async def search_thread(thread_id: str, query: str) -> Dict[str, Any]:
    """Find messages containing query (at least two characters) on any
    branch of a thread: excerpt, role, model and the checkpoint to open."""
    async with arena_svc.open_graph() as graph_app:
        results = await history.search_thread(graph_app, thread_id, query)
    return {"thread_id": thread_id, "query": query, "results": results}


@mcp.tool()
@_quiet
async def delete_branch(thread_id: str, checkpoint_id: str) -> Dict[str, Any]:
    """Delete a node of the conversation tree and every branch below it. Cannot be undone."""
    async with arena_svc.open_graph() as graph_app:
        deleted = await history.delete_branch(graph_app, thread_id, checkpoint_id)
    if not deleted:
        raise ToolError(f"Checkpoint {checkpoint_id} not found on thread {thread_id}.")
    return {"thread_id": thread_id, "checkpoint_id": checkpoint_id, "deleted_count": deleted}


@mcp.tool()
@_quiet
async def upload_document(thread_id: str, path: str) -> Dict[str, Any]:
    """Upload a local file (.pdf .txt .md .csv, up to 10 MB) to a thread for
    retrieval: turns with use_rag search it.

    Returns: {thread_id, filename, chunks}
    """
    from app.services import rag
    from app.services.uploads import upload_file

    try:
        uploaded = await asyncio.to_thread(upload_file, thread_id, path, rag.index_document)
    except ValueError as e:
        raise _tool_error(e)
    return {"thread_id": thread_id, **uploaded}


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
    """The thread's latest context summary, if one has been written, and the
    latest answer on its most recent path.

    Returns: {thread_id, context_summary, latest_answer: {model, content} | null, thesis}.
    Summaries only exist once a thread outgrows a model's context budget.
    `thesis` is always null: the rolling thesis is no longer maintained, and
    the value older threads still carry stopped tracking the conversation.
    """
    async with arena_svc.open_graph() as graph_app:
        state = await graph_app.aget_state({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    if not state.values:
        raise ToolError(f"Thread {thread_id} not found.")
    messages = state.values.get("messages", [])
    summary = next((summary_text(m) for m in reversed(messages) if is_summary_message(m)), None)
    last_ai = next((m for m in reversed(messages) if getattr(m, "type", "") == "ai"), None)
    return {
        "thread_id": thread_id,
        "context_summary": summary,
        "latest_answer": (
            {"model": getattr(last_ai, "name", None), "content": extract_text(last_ai.content)}
            if last_ai is not None else None
        ),
        "thesis": None,
    }


@mcp.tool()
@_quiet
async def get_thread_status(thread_id: str) -> Dict[str, Any]:
    """Latest model and message count on the thread's most recent path.

    `thesis` is always null (kept so existing callers still find the key):
    the rolling thesis is no longer maintained.
    """
    async with arena_svc.open_graph() as graph_app:
        state = await graph_app.aget_state({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    if not state.values:
        raise ToolError(f"Thread {thread_id} not found.")
    return {
        "thread_id": thread_id,
        "title": db.get_thread_title(thread_id),
        "active_model": state.values.get("active_peer"),
        "thesis": None,
        "message_count": len(state.values.get("messages", [])),
        "checkpoint_id": state.config["configurable"].get("checkpoint_id"),
    }


if __name__ == "__main__":
    from dotenv import load_dotenv

    # The entry point reads backend/.env; importing this module (tests) doesn't.
    load_dotenv()
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    mcp.run()
