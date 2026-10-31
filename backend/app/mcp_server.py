"""MCP server: The Crucible as a tool for external agents.

Everything the web UI does to a conversation is a tool here (the parity
table in tests/test_parity.py keeps it that way), except writing API keys:
a key passed through a tool call goes through the calling model's context.

Shapes are shared across tools: an answer is always {model, model_name,
content, checkpoint_id, error}; debate rounds are always a list of
{round, question, responses, errors, ...}; every checkpoint id is the tree
node's (get_thread_tree), so any id from any tool works with any other.

Tools return structured data (dicts) and raise ToolError on failure, so an
agent sees an error result instead of a successful call whose text happens to
start with "Error:". Each description states what the tool returns before
its arguments: FastMCP turns an ``Args:`` section into the parameters'
descriptions and drops the rest of the docstring after it.

Run with:  uv run python -m app.mcp_server   (stdio transport)
"""

import asyncio
import functools
import inspect
import logging
import sys
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from app.core import database as db
from app.core.database import ThreadDocumentStore
from app.core.schema import is_summary_message, summary_text
from app.registry import display_name
from app.services import arena as arena_svc
from app.services import debate as debate_svc
from app.services import history
from app.services import threads as threads_svc
from app.services.context import ContextSettings
from app.services.uploads import read_documents
from app.utils.helpers import extract_text

mcp = FastMCP("The Crucible")


def _quiet(fn):
    """Keep any stray print() off stdout, which is the stdio transport."""
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


def _maybe_context(system_prompt: Optional[str], summarizer: Optional[str]) -> Optional[ContextSettings]:
    """None (the debate's stored settings) unless the call names one."""
    return _context(system_prompt, summarizer) if system_prompt is not None or summarizer is not None else None


def _attachments(paths: Optional[List[str]]) -> Dict[str, str]:
    try:
        return read_documents(paths)
    except ValueError as e:
        raise _tool_error(e)


def _toggles(use_web_search: bool, use_rag: bool) -> Dict[str, bool]:
    return {"use_web_search": use_web_search, "use_rag": use_rag}


def _maybe_toggles(session: Dict[str, Any], use_web_search: Optional[bool], use_rag: Optional[bool]):
    """The debate's start toggles with the ones the call names; None (the
    stored ones) when it names none."""
    if use_web_search is None and use_rag is None:
        return None
    toggles = dict((session.get("settings") or {}).get("toggles") or {})
    if use_web_search is not None:
        toggles["use_web_search"] = use_web_search
    if use_rag is not None:
        toggles["use_rag"] = use_rag
    return toggles


def _answer(event: Dict[str, Any]) -> Dict[str, Any]:
    """One answer, the same shape in every tool."""
    return {
        "model": event.get("model"),
        "model_name": display_name(event.get("model")),
        "content": event.get("content") or "",
        "checkpoint_id": event.get("checkpoint_id"),
        "error": event.get("error"),
    }


async def _require_thread(thread_id: str) -> None:
    if not await asyncio.to_thread(db.thread_exists, thread_id):
        raise ToolError(f"Thread {thread_id} not found; omit thread_id to start a new thread (list_threads lists them).")


# ─── Models ──────────────────────────────────────────────────────


@mcp.tool()
@_quiet
def list_models(include_legacy: bool = False) -> Dict[str, Any]:
    """The model ids the other tools take: {models: [{id, name, family,
    legacy, key_available, native_search, context_window, price_per_mtok:
    {input, output, cached_input} | null}]}. Only models with
    key_available=true can be called; native_search says which can use
    use_web_search; prices are USD per million tokens today. Never assume a
    model is cheap from its name."""
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
    """Ask one or more models the same message in parallel: a chat turn (one
    model, synthesize=false), an arena turn, or a Deliberation.

    Returns {thread_id, new_thread, turn_id, answers: [{model, model_name,
    content, checkpoint_id, error, parent_checkpoint_id, attached_documents,
    retrieved, notices}], synthesis: answer | null, synthesis_skipped?}.
    Each answer's checkpoint_id is where to continue that model from.
    `notices` say what degraded a turn without failing it (a summary that
    couldn't be written, document search that failed). Raises if every
    model failed; a new thread whose first turn failed entirely is removed.

    Where each model starts: parent_checkpoint_id if given; else
    after_debate_session_id; else each model continues its own latest reply
    on the thread (models that answered side by side keep separate
    conversations) and a model with none continues the latest answer.

    Files: attachments are local paths whose text is in this turn only;
    upload_document indexes a file for use_rag on every later turn.

    Args:
        prompt: The message (optional with deliberation).
        models: Model IDs (list_models). Default: the standard arena trio, limited to models with keys.
        thread_id: An existing thread to continue; omit it to start a new thread.
        parent_checkpoint_id: Branch from this checkpoint (get_thread_tree). To edit a message, branch from the checkpoint before it with the new text; branching from a message itself adds yours to it.
        after_debate_session_id: Continue the debate's thread after it: its rounds and synthesis become context (the first time it is written down; later calls continue after the newest turn).
        deliberation: Each model critically reviews the conversation so far instead of answering a new question; needs a thread with history; no synthesis.
        synthesize: Add a synthesis of the answers (needs two that succeeded).
        synthesizer: Model that writes the synthesis. Default: the first model.
        attachments: Local file paths (.pdf .txt .md .csv, 10 MB each) in this turn's context.
        use_rag: Search the files uploaded to this thread (upload_document).
        use_web_search: Let models that support it (list_models native_search) search the web.
        system_prompt: Instructions sent to every model (and the synthesizer) before the conversation. Default: none.
        summarizer: Model that summarizes history once the thread outgrows a model's budget. Default: the app's.
    """
    if not prompt.strip() and not deliberation:
        raise ToolError("A prompt is required (it is optional only with deliberation).")
    if thread_id:
        await _require_thread(thread_id)
    elif after_debate_session_id:
        session = db.get_debate_session(after_debate_session_id)
        if not session:
            raise ToolError(f"Debate session {after_debate_session_id} not found.")
        thread_id = session["parent_thread_id"]
    else:
        thread_id = f"mcp-{uuid4().hex[:8]}"
    context = _context(system_prompt, summarizer)
    documents = _attachments(attachments)

    result: Dict[str, Any] = {"thread_id": thread_id, "new_thread": False, "turn_id": None, "answers": [], "synthesis": None}
    parents: Dict[str, str] = {}
    try:
        resolved = arena_svc.resolve_models(models)
        chosen_synth = (synthesizer or resolved[0]) if synthesize and not deliberation else None
        async with arena_svc.open_graph() as graph_app:
            async for event in arena_svc.run_arena(
                graph_app, prompt, thread_id, resolved, _toggles(use_web_search, use_rag), chosen_synth,
                context=context, parent_checkpoint_id=parent_checkpoint_id, after_debate=after_debate_session_id,
                documents=documents, is_deliberation=deliberation,
            ):
                if event["type"] == "start":
                    result["new_thread"], result["turn_id"] = event["new_thread"], event["turn_id"]
                    parents = event["parents"]
                elif event["type"] == "end":
                    result["answers"].append({
                        **_answer(event), "parent_checkpoint_id": parents.get(event["model"]),
                        **{k: event.get(k) or [] for k in ("attached_documents", "retrieved", "notices")},
                    })
                elif event["type"] == "synthesis":
                    result["synthesis"] = _answer(event)
    except ValueError as e:
        raise _tool_error(e)

    answered = [a for a in result["answers"] if not a["error"] and a["content"]]
    if result["answers"] and not answered:
        if result["new_thread"]:
            await asyncio.to_thread(db.delete_thread_data, thread_id)
        errors = "; ".join(f"{a['model']}: {a['error']}" for a in result["answers"])
        raise ToolError(f"Every model failed{'' if result['new_thread'] else f' (thread {thread_id})'}: {errors}")
    if chosen_synth and len(answered) < 2:
        result["synthesis_skipped"] = f"only {len(answered)} model(s) answered; a synthesis needs two"
    if result["new_thread"]:
        from app.services.chat import name_new_thread

        await name_new_thread(thread_id, prompt, kind="deliberation" if deliberation else None)
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
    """Synthesize answers already on a thread into one, as a new reply beside
    them (under the question they answer).

    Returns {thread_id, parent_checkpoint_id, answers: [answer] (exactly the
    ones synthesized), synthesis: answer}.

    Args:
        thread_id: The thread.
        checkpoint_ids: The answers to synthesize (invoke_arena or get_thread_tree ids). Default: every model's answer to the thread's latest question, syntheses left out.
        synthesizer: Model that writes it. Default: the first answer's model.
        parent_checkpoint_id: Where the synthesis goes instead.
        system_prompt: Instructions sent before the conversation.
        summarizer: Model that summarizes long history.
    """
    context = _context(system_prompt, summarizer)
    await _require_thread(thread_id)
    result: Dict[str, Any] = {"thread_id": thread_id, "parent_checkpoint_id": None, "answers": [], "synthesis": None}
    try:
        async with arena_svc.open_graph() as graph_app:
            async for event in arena_svc.synthesize_thread(
                graph_app, thread_id, synthesizer, context=context,
                checkpoint_ids=checkpoint_ids, parent_checkpoint_id=parent_checkpoint_id,
            ):
                if event["type"] == "start":
                    result["parent_checkpoint_id"] = event["parent_checkpoint_id"]
                elif event["type"] == "end":
                    result["answers"].append(_answer(event))
                elif event["type"] == "synthesis":
                    result["synthesis"] = _answer(event)
    except ValueError as e:
        raise _tool_error(e)
    if not result["synthesis"] or result["synthesis"]["error"]:
        raise ToolError(f"Synthesis failed: {(result['synthesis'] or {}).get('error')}")
    return result


# ─── Debates ─────────────────────────────────────────────────────


async def _collect_debate(events, session: Dict[str, Any]) -> Dict[str, Any]:
    """A debate run's events as one result. The run records the session's
    status itself (interrupted if this call is cancelled)."""
    from contextlib import aclosing

    result: Dict[str, Any] = {
        "session_id": session["session_id"],
        "thread_id": session["parent_thread_id"],
        "labels": debate_svc.peer_legend(session),
        "rounds": [],
        "converged": None,
        "synthesis": None,
        "failed": {},
        "errors": [],
        "status": None,
    }
    current: Optional[Dict[str, Any]] = None
    async with aclosing(events):
        async for event in events:
            kind = event["type"]
            if kind == "debate_round_start":
                current = {"round": event["round"], "responses": {}, "errors": {}, "convergence_score": None, "verdict": None}
                result["rounds"].append(current)
            elif kind == "stream_end" and current is not None:
                current["responses"][event["model"]] = event.get("content", "")
            elif kind == "error":
                if event.get("model") and current is not None:
                    current["errors"][event["model"]] = event["message"]
                    result["failed"].setdefault(event["model"], []).append(current["round"])
                else:
                    result["errors"].append(event["message"])
            elif kind == "debate_round_end" and current is not None:
                current["convergence_score"] = event.get("convergence_score")
                current["verdict"] = event.get("verdict")
            elif kind == "debate_converged":
                result["converged"] = {k: event.get(k) for k in ("round", "score", "reason", "method")}
            elif kind == "debate_synthesis_end":
                result["synthesis"] = _answer(event)
            elif kind == "debate_session_status":
                result["status"] = event.get("status")
    if not result["rounds"] and result["errors"]:
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
    """Run a multi-round structured debate between two or more models. Can
    take several minutes; rounds are numbered from 0 (round 0 is each
    model's independent answer).

    Returns {session_id, thread_id, labels, rounds, converged, synthesis,
    failed, errors, status}: see continue_debate. Use it to see the
    arguments, not as a trustworthy answer: debating models conform to each
    other, so for an answer prefer invoke_arena's independent answers and
    synthesis. A debate whose round 0 has fewer than two answers stops there.
    To pause, run fewer rounds and continue_debate later (it can add a
    message); to change the question, redirect_debate.

    Args:
        prompt: The question.
        models: Two or more different model ids.
        max_rounds: Rounds to run, 1-10 (a session runs at most 10 in all).
        convergence_threshold: Stop once every model's answer stops changing: cosine similarity to its own previous answer, 0-1. Stability, not agreement.
        mode: With both convergence_threshold and convergence_judge: "all" needs both, "any" either.
        convergence_judge: Model that judges whether the models now agree; stops the debate if so.
        synthesizer: Model that writes an argument map at the end (positions, strongest arguments, who changed position and why, what is unresolved). None: no map (synthesize_debate writes one later).
        thread_id: An existing thread the debate belongs to; omit for a new one.
        parent_checkpoint_id: A checkpoint of thread_id the debate starts from: the models see that conversation first.
        peer_labels: "anonymous" (Participant A/B…) or "named" (model ids; models then defer to names, which costs independence).
        attachments: Local files in every round's context.
        use_rag: Search the thread's uploaded files every round.
        use_web_search: Web search for models that support it.
        system_prompt: Sent to every participant (and the synthesizer); continuing and redirecting reuse it.
        summarizer: Model that summarizes long lanes; reused like system_prompt.
    """
    if len(set(models)) < 2:
        raise ToolError("A debate needs at least two different models.")
    if parent_checkpoint_id and not thread_id:
        raise ToolError("parent_checkpoint_id needs the thread_id it belongs to.")
    if thread_id:
        await _require_thread(thread_id)
    context = _context(system_prompt, summarizer)
    documents = _attachments(attachments)
    try:
        arena_svc.resolve_models(models + [m for m in (synthesizer, convergence_judge) if m])
    except ValueError as e:
        raise _tool_error(e)

    thread_id = thread_id or f"mcp-debate-{uuid4().hex[:8]}"
    async with arena_svc.open_graph() as graph_app:
        if parent_checkpoint_id:
            from app.services.runs import fork_point

            try:
                # Before the session exists: a bad checkpoint leaves nothing behind.
                await fork_point(graph_app, thread_id, parent_checkpoint_id)
            except ValueError as e:
                raise _tool_error(e)
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
        return await _collect_debate(
            debate_svc.run_debate(graph_app, session["session_id"], prompt, _toggles(use_web_search, use_rag), documents,
                                  parent_checkpoint_id=parent_checkpoint_id, context=context),
            session,
        )


def _idle_session(session_id: str) -> Dict[str, Any]:
    session = db.get_debate_session(session_id)
    if not session:
        raise ToolError(f"Debate session {session_id} not found.")
    return session


@mcp.tool()
@_quiet
async def continue_debate(
    session_id: str,
    rounds: int = 1,
    inject: Optional[List[str]] = None,
    use_rag: Optional[bool] = None,
    use_web_search: Optional[bool] = None,
    system_prompt: Optional[str] = None,
    summarizer: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Run more rounds of a debate that stopped (resume after running fewer
    rounds, or after an interruption), optionally adding messages to the next
    round's prompts. The session's auto-synthesis, if set, is rewritten over
    every round. Refused while another client runs the debate.

    Returns {session_id, thread_id, labels: {model: label the models saw},
    rounds: [{round, responses: {model: text}, errors: {model: message},
    convergence_score, verdict}] (the new rounds only), converged, synthesis:
    answer | null, failed: {model: [rounds]}, errors: [message], status}.

    Args:
        session_id: The debate.
        rounds: How many more rounds, at least 1 (a session runs at most 10 in all).
        inject: Messages added to the next round's prompts.
        use_rag: Search the thread's uploads. Default: as the debate started.
        use_web_search: Web search. Default: as the debate started.
        system_prompt: Default: the debate's.
        summarizer: Default: the debate's.
        force: Run although the debate is marked running: only for one left so by a backend that died.
    """
    session = _idle_session(session_id)
    async with arena_svc.open_graph() as graph_app:
        return await _collect_debate(
            debate_svc.continue_debate(
                graph_app, session_id, rounds, inject or (), _maybe_toggles(session, use_web_search, use_rag),
                context=_maybe_context(system_prompt, summarizer), force=force,
            ),
            session,
        )


@mcp.tool()
@_quiet
async def redirect_debate(
    session_id: str,
    prompt: str,
    rounds: Optional[int] = None,
    attachments: Optional[List[str]] = None,
    use_rag: Optional[bool] = None,
    use_web_search: Optional[bool] = None,
    system_prompt: Optional[str] = None,
    summarizer: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Put a new question to a debate: its rounds follow the earlier ones
    (numbering continues), each participant keeping what it said; get_debate
    shows which rounds answered which question. Refused while another client
    runs the debate.

    Returns the same shape as continue_debate.

    Args:
        session_id: The debate.
        prompt: The new question.
        rounds: Rounds on it. Default: the debate's max_rounds (a session runs at most 10 in all).
        attachments: Local files for these rounds. Default: the debate's.
        use_rag: Default: as the debate started.
        use_web_search: Default: as the debate started.
        system_prompt: Default: the debate's.
        summarizer: Default: the debate's.
        force: As in continue_debate.
    """
    session = _idle_session(session_id)
    documents = _attachments(attachments)
    if rounds:
        policy = {**session["termination_policy"], "max_rounds": rounds}
        await asyncio.to_thread(db.update_debate_session, session_id, termination_policy=policy)
        session = {**session, "termination_policy": policy}
    async with arena_svc.open_graph() as graph_app:
        return await _collect_debate(
            debate_svc.run_debate(
                graph_app, session_id, prompt, _maybe_toggles(session, use_web_search, use_rag), documents,
                context=_maybe_context(system_prompt, summarizer), force=force,
            ),
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

    Returns {session_id, synthesis: answer} (answer.error is set when the
    synthesizer failed or ran out of time; content is then what arrived).

    Args:
        session_id: The debate.
        synthesizer: Model that writes it. Default: the session's synthesizer, else its first participant.
        system_prompt: Default: the debate's.
        summarizer: Default: the debate's.
    """
    result: Dict[str, Any] = {"session_id": session_id, "synthesis": None}
    async with arena_svc.open_graph() as graph_app:
        async for event in debate_svc.synthesize_session(graph_app, session_id, prompt="", synthesizer=synthesizer,
                                                         context=_maybe_context(system_prompt, summarizer)):
            if event["type"] == "error":
                raise ToolError(event["message"])
            if event["type"] == "debate_synthesis_end":
                result["synthesis"] = _answer(event)
    return result


@mcp.tool()
@_quiet
def list_debates(thread_id: Optional[str] = None) -> Dict[str, Any]:
    """Debate sessions, newest first, optionally one thread's: {sessions:
    [{session_id, thread_id, question, questions, participants, labels,
    status, current_round, termination_policy, synthesizer_model,
    peer_labels, created_at}]}. current_round is the last round started,
    from 0."""
    db.init_db()
    return {"sessions": [debate_svc.session_view(s) for s in db.list_debate_sessions(thread_id)]}


@mcp.tool()
@_quiet
async def get_debate(session_id: str, rounds_from: int = 0, max_chars: Optional[int] = None) -> Dict[str, Any]:
    """Everything a debate said, aligned by round.

    Returns {session, question, labels: {model: label the models saw},
    rounds: [{round, question, responses: {model: text}, errors: {model:
    message}, score}], synthesis: {model, model_name, content} | null,
    injected: [{round, message}]}. A failed answer is an errors entry, so
    later rounds keep their numbers.

    Args:
        session_id: The debate.
        rounds_from: Only rounds from this one on (0-based), to skip what you already read.
        max_chars: Cut each reply and the synthesis to this many characters.
    """
    async with arena_svc.open_graph() as graph_app:
        try:
            record = await debate_svc.debate_transcript(graph_app, session_id)
        except ValueError as e:
            raise _tool_error(e)
    record["rounds"] = [r for r in record["rounds"] if r["round"] >= rounds_from]
    if max_chars:
        for r in record["rounds"]:
            r["responses"] = {m: text[:max_chars] for m, text in r["responses"].items()}
        if record["synthesis"]:
            record["synthesis"]["content"] = record["synthesis"]["content"][:max_chars]
    return record


@mcp.tool()
@_quiet
def delete_debate(session_id: str) -> Dict[str, Any]:
    """Delete a debate and its lanes. Its thread stays if it holds anything
    else (a thread with nothing but this debate goes too). Returns {deleted}."""
    db.init_db()
    if not db.get_debate_session(session_id):
        raise ToolError(f"Debate session {session_id} not found.")
    db.delete_debate_session(session_id)
    return {"deleted": session_id}


# ─── Threads ─────────────────────────────────────────────────────


@mcp.tool()
@_quiet
def list_threads() -> Dict[str, Any]:
    """Conversation threads, most recently active first: {threads: [{id,
    title, updated_at}]}."""
    return {"threads": threads_svc.list_threads()}


@mcp.tool()
@_quiet
def rename_thread(thread_id: str, title: str) -> Dict[str, Any]:
    """Give an existing thread a new title. Returns {thread_id, title}."""
    try:
        return {"thread_id": thread_id, "title": threads_svc.rename_thread(thread_id, title)}
    except ValueError as e:
        raise _tool_error(e)


@mcp.tool()
@_quiet
async def delete_thread(thread_id: str) -> Dict[str, Any]:
    """Delete a thread with its debates, uploaded files and their search
    index. Cannot be undone. Returns {deleted}."""
    from app.services.threads import default_thread_deleter

    try:
        await asyncio.to_thread(threads_svc.delete_thread, thread_id, default_thread_deleter())
    except ValueError as e:
        raise _tool_error(e)
    return {"deleted": thread_id}


@mcp.tool()
@_quiet
async def get_thread_tree(thread_id: str, excerpt_chars: int = 300) -> Dict[str, Any]:
    """The conversation tree.

    Returns {thread_id, current_checkpoint (where a turn with no
    parent_checkpoint_id continues), nodes: [{checkpoint_id, parent, role
    (user | assistant), model, model_name, kind (synthesis | debate | null),
    turn_id (replies sent together share it), created_at, excerpt (the text
    as written)}], debates: [session_id]}. A thread holding only debates has
    no nodes yet. Checkpoint ids work with every tool that takes one.

    Args:
        thread_id: The thread.
        excerpt_chars: Characters of each message to include (up to 300).
    """
    async with arena_svc.open_graph() as graph_app:
        try:
            return await history.compact_tree(graph_app, thread_id, excerpt_chars)
        except ValueError as e:
            raise _tool_error(e)


@mcp.tool()
@_quiet
async def get_thread_messages(thread_id: str, checkpoint_id: Optional[str] = None) -> Dict[str, Any]:
    """The conversation on one path of a thread, oldest first, as the chat
    view shows it (synthesis prompts and summaries left out).

    Returns {thread_id, checkpoint_id, messages: [{role (user | assistant),
    content, model, model_name, kind, checkpoint_id, turn_id, sources}]}.

    Args:
        thread_id: The thread.
        checkpoint_id: The path to read up to (a reply's id reads that branch). Default: where the thread continues.
    """
    async with arena_svc.open_graph() as graph_app:
        try:
            if checkpoint_id:
                messages = await history.path_at(graph_app, thread_id, checkpoint_id)
            else:
                await history.compact_tree(graph_app, thread_id, 0)  # raises for an unknown thread
                messages = (await history.thread_tree(graph_app, thread_id))["messages"]
        except ValueError as e:
            raise _tool_error(e)
    keep = ("role", "content", "model", "model_name", "kind", "checkpoint_id", "turn_id", "sources")
    return {"thread_id": thread_id, "checkpoint_id": checkpoint_id,
            "messages": [{k: m.get(k) for k in keep} for m in messages]}


@mcp.tool()
@_quiet
async def search_thread(thread_id: str, query: str) -> Dict[str, Any]:
    """Find messages containing query (case-insensitive, two characters or
    more) on any branch of a thread.

    Returns {thread_id, query, results: [{checkpoint_id, role, model,
    excerpt, timestamp}]} (at most 20; the checkpoint is the message's tree
    node).

    Args:
        thread_id: The thread.
        query: Text to find.
    """
    async with arena_svc.open_graph() as graph_app:
        try:
            results = await history.search_thread(graph_app, thread_id, query)
        except ValueError as e:
            raise _tool_error(e)
    return {"thread_id": thread_id, "query": query, "results": results}


@mcp.tool()
@_quiet
async def delete_branch(thread_id: str, checkpoint_id: str) -> Dict[str, Any]:
    """Delete a message and everything below it on the tree (any id of that
    message works). The thread's start can't be deleted: use delete_thread.
    Cannot be undone. Returns {thread_id, checkpoint_id, deleted_count}."""
    async with arena_svc.open_graph() as graph_app:
        try:
            deleted = await history.delete_branch(graph_app, thread_id, checkpoint_id)
        except ValueError as e:
            raise _tool_error(e)
    if not deleted:
        raise ToolError(f"Checkpoint {checkpoint_id} not found on thread {thread_id}.")
    return {"thread_id": thread_id, "checkpoint_id": checkpoint_id, "deleted_count": deleted}


@mcp.tool()
@_quiet
async def upload_document(thread_id: str, path: str) -> Dict[str, Any]:
    """Upload a local file (.pdf .txt .md .csv, up to 10 MB) to a thread:
    turns with use_rag search it from then on (attachments, by contrast, put
    a file's whole text in one turn). Uploading the same file again replaces
    it. The thread may be new: upload before its first message.

    Returns {thread_id, filename, chunks}.

    Args:
        thread_id: The thread whose turns search the file.
        path: Local path of the file.
    """
    from app.services import rag
    from app.services.uploads import upload_file

    if "::" in thread_id:
        raise ToolError(f"{thread_id} is part of a debate; upload to its thread instead.")
    db.init_db()
    try:
        uploaded = await asyncio.to_thread(upload_file, thread_id, path, rag.index_document, ThreadDocumentStore())
    except ValueError as e:
        raise _tool_error(e)
    return {"thread_id": thread_id, **uploaded}


@mcp.tool()
@_quiet
async def get_branch_answers(thread_id: str) -> Dict[str, Any]:
    """The latest answer on every branch tip of a thread, syntheses
    included: {thread_id, answers: [answer]}. For "the answers to the latest
    question" use synthesize_answers' default or get_thread_tree's turn_id."""
    await _require_thread(thread_id)
    async with arena_svc.open_graph() as graph_app:
        answers = await arena_svc.latest_branch_answers(graph_app, thread_id)
    if not answers:
        raise ToolError(f"Thread {thread_id} has no answers yet.")
    return {"thread_id": thread_id, "answers": [_answer(a) for a in answers]}


@mcp.tool()
@_quiet
async def get_thread_summary(thread_id: str) -> Dict[str, Any]:
    """The thread's latest context summary, if one was written (summaries
    exist once a thread outgrows a model's budget), and the latest answer on
    its most recent path: {thread_id, context_summary, latest_answer: {model,
    content} | null, thesis}. `thesis` is always null: the rolling thesis is
    no longer maintained."""
    async with arena_svc.open_graph() as graph_app:
        state = await graph_app.aget_state({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    if not state.values:
        raise ToolError(f"Thread {thread_id} not found or has no messages yet.")
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
    """The thread's title, the latest model and message count on its most
    recent path, and where a turn with no parent continues: {thread_id,
    title, active_model, message_count, checkpoint_id, thesis}. `thesis` is
    always null (kept for existing callers)."""
    async with arena_svc.open_graph() as graph_app:
        state = await graph_app.aget_state({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
        if not state.values:
            raise ToolError(f"Thread {thread_id} not found or has no messages yet.")
        tree = await history.compact_tree(graph_app, thread_id, 0)
    return {
        "thread_id": thread_id,
        "title": db.get_thread_title(thread_id),
        "active_model": state.values.get("active_peer"),
        "thesis": None,
        "message_count": len(state.values.get("messages", [])),
        "checkpoint_id": tree["current_checkpoint"],
    }


if __name__ == "__main__":
    from dotenv import load_dotenv

    # The entry point reads backend/.env; importing this module (tests) doesn't.
    load_dotenv()
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    from app.core.storage import Storage, set_storage

    set_storage(Storage.from_env())
    mcp.run()
