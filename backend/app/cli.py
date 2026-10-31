"""
The Crucible CLI — Multi-Model Reasoning Engine.

Usage:
    crucible chat "prompt" -m gpt-5.4              # --from <checkpoint> branches, --deliberate reviews
    crucible arena "prompt" -m gpt-5.4 -m claude-sonnet-5
    crucible debate "topic" -m gpt-5.4 -m claude-sonnet-5 --rounds 3
    crucible debates list                          # show / continue / redirect / delete a debate
    crucible synthesize --thread <id>              # or --answers <checkpoint>…, or --debate <session_id>
    crucible threads | tree -t <id> | messages -t <id> | search -t <id> "text"
    crucible delete-branch -t <id> <checkpoint>
    crucible upload -t <id> notes.pdf              # read by --rag
    crucible keys | models

Everything the web UI does to a conversation is a command here (the
parity table in tests/test_parity.py keeps it that way). Every command that
produces results takes ``--format json`` for scripting: the JSON document is
the only thing written to stdout, and failures exit non-zero with the message
on stderr.
"""

import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional
from uuid import uuid4

import typer
from rich.console import Console

from app.api.models import DEFAULT_MODEL

app = typer.Typer(
    name="crucible",
    help="The Crucible — Multi-Model Reasoning Engine",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
debates_app = typer.Typer(help="List, read, continue, redirect or delete debates.", no_args_is_help=True)
app.add_typer(debates_app, name="debates")

console = Console()

FORMAT_HELP = "Output format: rich or json."


# ─── Shared Utilities ────────────────────────────────────────────


def _load_env():
    """Load .env for API keys."""
    from dotenv import load_dotenv

    load_dotenv()


def _gen_thread_id(prefix: str = "cli") -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


def _check_format(fmt: str) -> bool:
    if fmt not in ("rich", "json"):
        raise typer.BadParameter("must be 'rich' or 'json'", param_hint="--format")
    return fmt == "json"


def _fail(message: str, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps({"error": message}), err=True)
    else:
        from app.cli_display import print_error

        print_error(message)
    raise typer.Exit(1)


def _run(coro, as_json: bool):
    """asyncio.run with user-facing errors (bad model, missing thread) as exit 1.

    In JSON mode the graph's diagnostic prints go to stderr, so stdout carries
    only the JSON document.
    """
    from contextlib import nullcontext

    from app.services.arena import stdout_to_stderr

    try:
        with stdout_to_stderr() if as_json else nullcontext():
            return asyncio.run(coro)
    except ValueError as e:
        _fail(str(e), as_json)


def _emit_json(data: Dict[str, Any]) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _validate_models(models: Optional[List[str]], as_json: bool) -> List[str]:
    from app.services.arena import resolve_models

    try:
        return resolve_models(models)
    except ValueError as e:
        _fail(str(e), as_json)
        return []  # unreachable


def _run_context(as_json: bool, summarizer: Optional[str] = None, system: Optional[str] = None):
    """The run settings a command's options name, checked like a frame's."""
    from app.services.context import ContextSettings

    context = ContextSettings.from_frame({"summarizer": summarizer, "system_prompt": system})
    if problem := context.problem():
        _fail(problem, as_json)
    return context


def _documents(paths: Optional[List[str]], as_json: bool) -> Dict[str, str]:
    """--attach files as a turn's documents ({filename: text})."""
    from app.services.uploads import read_documents

    try:
        return read_documents(paths)
    except ValueError as e:
        _fail(str(e), as_json)
        return {}  # unreachable


def _toggles(web_search: bool, rag: bool) -> Dict[str, bool]:
    return {"use_web_search": web_search, "use_rag": rag}


def _debate_thread(session_id: str, as_json: bool) -> str:
    """The thread a debate belongs to (where a turn after it goes)."""
    from app.core import database as db

    db.init_db()
    session = db.get_debate_session(session_id)
    if not session:
        _fail(f"Debate session {session_id} not found.", as_json)
    return session["parent_thread_id"]


# Options shared by the commands that run a turn. Factories, because every
# command needs its own option objects.
def _opt_from():
    return typer.Option(
        None, "--from", help="Checkpoint to branch from (ids are in `crucible tree`). "
        "To edit a message, branch from the checkpoint before it with the new text."
    )


def _opt_after_debate():
    return typer.Option(
        None, "--after-debate", help="Continue the thread from this finished debate (its rounds and synthesis become context)."
    )


def _opt_attach():
    return typer.Option(None, "--attach", "-a", help="Attach a file (.pdf .txt .md .csv) to this turn; repeat for more.")


def _opt_rag():
    return typer.Option(False, "--rag", help="Search the files uploaded to this thread (`crucible upload`).")


def _opt_web():
    return typer.Option(False, "--web-search", "-w", help="Enable web search grounding.")


def _opt_summarizer():
    return typer.Option(
        None, "--summarizer", help="Model that summarizes long history. Default: the first of SUMMARIZER_MODELS with a key."
    )


def _opt_system():
    return typer.Option(
        None, "--system", help="System prompt sent to every model. Default: none (each model's own behaviour)."
    )


def _opt_format():
    return typer.Option("rich", "--format", "-f", help=FORMAT_HELP)


def _opt_force():
    return typer.Option(
        False, "--force", help="Run even though the debate is marked running (left so by a backend that died)."
    )


# ─── CHAT / ARENA ────────────────────────────────────────────────


@app.command()
def chat(
    prompt: Optional[str] = typer.Argument(None, help="The message to send (or pipe via stdin)."),
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m", help="Model ID to use."),
    thread: Optional[str] = typer.Option(None, "--thread", "-t", help="Existing thread to continue."),
    from_checkpoint: Optional[str] = _opt_from(),
    after_debate: Optional[str] = _opt_after_debate(),
    deliberate: bool = typer.Option(
        False, "--deliberate", help="Deliberation: the model critically reviews the conversation so far (the prompt is optional)."
    ),
    attach: Optional[List[str]] = _opt_attach(),
    rag: bool = _opt_rag(),
    web_search: bool = _opt_web(),
    summarizer: Optional[str] = _opt_summarizer(),
    system: Optional[str] = _opt_system(),
    format_output: str = _opt_format(),
):
    """
    [bold green]💬 Chat[/bold green] — One model's turn.

    Supports stdin piping: echo "question" | crucible chat --model gpt-5.4
    """
    as_json = _check_format(format_output)
    _load_env()

    if prompt is None and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
    if not prompt and not deliberate:
        _fail("No prompt provided. Pass a message or pipe via stdin.", as_json)

    _validate_models([model], as_json)
    context = _run_context(as_json, summarizer, system)
    documents = _documents(attach, as_json)
    thread_id = thread or (_debate_thread(after_debate, as_json) if after_debate else _gen_thread_id("chat"))
    result = _run(
        _run_turn(prompt or "", [model], thread_id, None, _toggles(web_search, rag), as_json, context,
                  parent=from_checkpoint, after_debate=after_debate, documents=documents, deliberate=deliberate),
        as_json,
    )
    answer = result["answers"].get(model, {})
    out = {"thread_id": thread_id, "model": model, **answer, "parent_checkpoint_id": result["parent_checkpoint_id"]}
    if as_json:
        _emit_json(out)
    if answer.get("error"):
        raise typer.Exit(1)


@app.command()
def arena(
    prompt: Optional[str] = typer.Argument(None, help="The question to put to every model."),
    models: Optional[List[str]] = typer.Option(
        None, "--models", "-m", help="Model IDs to include (repeat the flag)."
    ),
    thread: Optional[str] = typer.Option(
        None, "--thread", "-t", help="Existing thread ID to continue."
    ),
    from_checkpoint: Optional[str] = _opt_from(),
    after_debate: Optional[str] = _opt_after_debate(),
    deliberate: bool = typer.Option(
        False, "--deliberate", help="Deliberation: every model critically reviews the conversation so far; no synthesis."
    ),
    judge: Optional[str] = typer.Option(
        None, "--judge", "-j", help="Model that synthesizes the answers (default: the first model)."
    ),
    no_synthesize: bool = typer.Option(
        False, "--no-synthesize", help="Only collect the individual answers."
    ),
    attach: Optional[List[str]] = _opt_attach(),
    rag: bool = _opt_rag(),
    web_search: bool = _opt_web(),
    summarizer: Optional[str] = _opt_summarizer(),
    system: Optional[str] = _opt_system(),
    format_output: str = _opt_format(),
):
    """
    [bold green]⚔️  Arena Mode[/bold green] — Multi-model parallel answers.

    Every model answers the same prompt independently (each on its own branch),
    then one model synthesizes the answers.
    """
    as_json = _check_format(format_output)
    _load_env()
    if not prompt and not deliberate:
        _fail("No prompt provided.", as_json)
    resolved = _validate_models(models, as_json)
    synthesizer = None if (no_synthesize or deliberate) else (judge or resolved[0])
    if synthesizer:
        _validate_models([synthesizer], as_json)
    context = _run_context(as_json, summarizer, system)
    documents = _documents(attach, as_json)
    thread_id = thread or (_debate_thread(after_debate, as_json) if after_debate else _gen_thread_id("arena"))

    result = _run(
        _run_turn(prompt or "", resolved, thread_id, synthesizer, _toggles(web_search, rag), as_json, context,
                  parent=from_checkpoint, after_debate=after_debate, documents=documents, deliberate=deliberate),
        as_json,
    )
    if as_json:
        _emit_json(result)
    if result["answers"] and all(a["error"] for a in result["answers"].values()):
        raise typer.Exit(1)


async def _run_turn(prompt, models, thread_id, synthesizer, toggles, as_json, context=None, *,
                    parent=None, after_debate=None, documents=None, deliberate=False):
    """One turn by every model in ``models`` (chat is one model), then the
    synthesis if a synthesizer is set."""
    from app.core import database as db
    from app.services.arena import open_graph, run_arena
    from app.services.chat import auto_title
    from app.services.context import DEFAULT_CONTEXT
    from app.cli_display import (
        ArenaDisplay, ReplyDisplay, print_header, print_info, print_success, print_error, render_synthesis,
    )

    single = len(models) == 1 and not synthesizer
    result: Dict[str, Any] = {"thread_id": thread_id, "prompt": prompt, "parent_checkpoint_id": None, "answers": {}, "synthesis": None}
    display = None
    if not as_json:
        if not single:
            print_header()
        print_info(f"Thread: [dim]{thread_id}[/dim]")
        if not single:
            print_info(f"Models: {', '.join(models)}")
        console.print()
        display = ReplyDisplay(models[0]) if single else ArenaDisplay(models)
        display.start()

    new_thread = False
    async with open_graph() as graph_app:
        try:
            async for event in run_arena(graph_app, prompt, thread_id, models, toggles, synthesizer,
                                         context=context or DEFAULT_CONTEXT, parent_checkpoint_id=parent,
                                         after_debate=after_debate, documents=documents, is_deliberation=deliberate):
                kind = event["type"]
                if kind == "start":
                    result["parent_checkpoint_id"] = event["parent_checkpoint_id"]
                    new_thread = event["new_thread"]
                elif kind == "token" and display:
                    display.update_token(event["model"], event["token"])
                elif kind == "end":
                    result["answers"][event["model"]] = {k: event[k] for k in ("content", "checkpoint_id", "error")}
                    if display:
                        if event["error"]:
                            display.update_token(event["model"], f"\n[error] {event['error']}")
                        display.finish_model(event["model"])
                elif kind == "synthesis_start" and display:
                    display.stop()
                    display = None
                    console.print()
                    print_info(f"Synthesizing with {event['model']}…")
                elif kind == "synthesis":
                    result["synthesis"] = {k: event[k] for k in ("model", "content", "checkpoint_id", "error")}
                    if not as_json:
                        if event["error"]:
                            print_error(f"Synthesis failed: {event['error']}")
                        else:
                            render_synthesis(event["content"], event["model"])
        finally:
            if display:
                display.stop()

    if new_thread and not db.get_thread_title(thread_id):
        if single:
            title = auto_title(prompt) or ("Deliberation" if deliberate else None)
        else:
            title = f"{'Deliberation' if deliberate else 'Arena'}: {prompt[:40]}"
        if title:
            db.rename_thread(thread_id, title)
    if not as_json:
        for model, answer in result["answers"].items():
            if answer.get("checkpoint_id"):
                print_info(f"{model}: checkpoint [dim]{answer['checkpoint_id']}[/dim]")
        print_success(f"Thread saved: {thread_id}")
    return result


# ─── DEBATE ──────────────────────────────────────────────────────


def debate(
    prompt: str = typer.Argument(..., help="The topic for the debate."),
    models: Optional[List[str]] = typer.Option(
        None, "--models", "-m", help="Model IDs to debate (repeat the flag; at least two)."
    ),
    rounds: int = typer.Option(2, "--rounds", "-r", min=1, help="Maximum number of rounds."),
    judge: Optional[str] = typer.Option(
        None, "--judge", "-j", help="Model that writes the final synthesis, an argument map (default: the first model)."
    ),
    no_synthesize: bool = typer.Option(False, "--no-synthesize", help="Skip the final synthesis."),
    peer_labels: str = typer.Option(
        "anonymous", "--peers", help="How models see each other: anonymous (Participant A, B…) or named (model ids)."
    ),
    threshold: Optional[float] = typer.Option(
        None, "--threshold", help="Stop early once every model's answer stops changing: similarity to its own previous round (0-1). Measures stability, not agreement."
    ),
    mode: str = typer.Option("all", "--mode", help="With both --threshold and --convergence-judge: all = both must hold, any = either is enough."),
    convergence_judge: Optional[str] = typer.Option(
        None, "--convergence-judge", help="Model that judges whether the models now agree; stops the debate if they do."
    ),
    thread: Optional[str] = typer.Option(
        None, "--thread", "-t", help="Parent thread for the debate (default: a new one)."
    ),
    from_checkpoint: Optional[str] = typer.Option(
        None, "--from", help="Checkpoint of --thread the debate starts from: the models see that conversation first."
    ),
    attach: Optional[List[str]] = _opt_attach(),
    rag: bool = _opt_rag(),
    web_search: bool = _opt_web(),
    summarizer: Optional[str] = _opt_summarizer(),
    system: Optional[str] = _opt_system(),
    format_output: str = _opt_format(),
):
    """
    [bold yellow]🗣️  Debate Mode[/bold yellow] — Multi-round structured debate.

    Runs the same debate engine as the web UI: each model debates on its own
    branch, sees its peers' previous answers every round, and the debate can
    stop early once answers stop changing or a judge finds agreement. The
    session shows up in the web UI. Pause by running fewer rounds and resume
    or inject with `crucible debates continue`.
    """
    as_json = _check_format(format_output)
    _load_env()
    if mode not in ("all", "any"):
        raise typer.BadParameter("must be 'all' or 'any'", param_hint="--mode")
    if peer_labels not in ("anonymous", "named"):
        raise typer.BadParameter("must be 'anonymous' or 'named'", param_hint="--peers")
    if from_checkpoint and not thread:
        raise typer.BadParameter("--from needs --thread (the checkpoint's thread)", param_hint="--from")
    resolved = _validate_models(models, as_json)
    if len(resolved) < 2:
        _fail("A debate needs at least two models with API keys.", as_json)
    synthesizer = None if no_synthesize else (judge or resolved[0])
    for extra in filter(None, [synthesizer, convergence_judge]):
        _validate_models([extra], as_json)
    context = _run_context(as_json, summarizer, system)
    documents = _documents(attach, as_json)

    policy = {
        "max_rounds": rounds,
        "convergence_threshold": threshold,
        "llm_judge": convergence_judge,
        "mode": mode,
    }
    result = _run(
        _run_debate(
            prompt, resolved, thread or _gen_thread_id("debate"), policy, synthesizer,
            _toggles(web_search, rag), as_json, peer_labels, context,
            parent=from_checkpoint, documents=documents,
        ),
        as_json,
    )
    if as_json:
        _emit_json(result)


# "deliberate" was this command's first name; Deliberation itself is
# `chat --deliberate` / `arena --deliberate`.
app.command("debate")(debate)
app.command("deliberate", hidden=True)(debate)


async def _run_debate(prompt, models, thread_id, policy, synthesizer, toggles, as_json, peer_labels="anonymous",
                      context=None, *, parent=None, documents=None):
    from app.core import database as db
    from app.services import debate as debate_svc
    from app.services.arena import open_graph
    from app.services.context import DEFAULT_CONTEXT

    async with open_graph() as graph_app:
        session = debate_svc.create_session(
            parent_thread_id=thread_id,
            participants=models,
            termination_policy=policy,
            auto_synthesize=bool(synthesizer),
            synthesizer_model=synthesizer,
            peer_labels=peer_labels,
        )
        if not db.get_thread_title(thread_id):
            db.rename_thread(thread_id, f"Debate: {prompt[:40]}")
        events = debate_svc.run_debate(graph_app, session["session_id"], prompt, toggles, documents or {},
                                       parent_checkpoint_id=parent, context=context or DEFAULT_CONTEXT)
        return await _follow_debate(events, session, prompt, as_json, f"up to {policy['max_rounds']} round(s)")


async def _follow_debate(events, session, prompt, as_json, plan: str) -> Dict[str, Any]:
    """Show (or collect) a debate run's events; mark the session interrupted
    if the run doesn't finish (Ctrl-C is how a CLI debate is stopped)."""
    from app.core import database as db
    from app.cli_display import ArenaDisplay, print_header, print_info, print_success, print_error, render_synthesis

    session_id, thread_id = session["session_id"], session["parent_thread_id"]
    models = list(dict.fromkeys(session["participants"]))
    result: Dict[str, Any] = {
        "session_id": session_id,
        "thread_id": thread_id,
        "prompt": prompt,
        "models": models,
        "rounds": [],
        "converged": None,
        "synthesis": None,
        "errors": [],
    }
    if not as_json:
        print_header()
        print_info(f"Thread: [dim]{thread_id}[/dim]  Session: [dim]{session_id}[/dim]")
        print_info(f"Models: {', '.join(models)}  ·  {plan}")

    display = None
    current: Optional[Dict[str, Any]] = None
    finished = False
    try:
        async for event in events:
            kind = event["type"]
            if kind == "debate_round_start":
                current = {"round": event["round"], "responses": {}, "errors": {}, "convergence_score": None}
                result["rounds"].append(current)
                if not as_json:
                    console.print()
                    console.rule(f"Round {event['round'] + 1}" + (" · independent answers" if event["round"] == 0 else ""))
                    display = ArenaDisplay(models)
                    display.start()
            elif kind == "stream_token" and display and current is not None:
                display.update_token(event["model"], event["token"])
            elif kind == "stream_end" and current is not None:
                current["responses"][event["model"]] = event.get("content", "")
                if display:
                    display.finish_model(event["model"])
            elif kind == "error":
                if event.get("model") and current is not None:
                    current["errors"][event["model"]] = event["message"]
                    if display:
                        display.update_token(event["model"], f"\n[error] {event['message']}")
                        display.finish_model(event["model"])
                else:
                    result["errors"].append(event["message"])
                    if not as_json:
                        print_error(event["message"])
            elif kind == "debate_round_end":
                if display:
                    display.stop()
                    display = None
                if current is not None:
                    current["convergence_score"] = event.get("convergence_score")
                if not as_json and event.get("convergence_score") is not None:
                    print_info(f"Stability: {event['convergence_score']:.3f}")
            elif kind == "debate_converged":
                result["converged"] = {k: event.get(k) for k in ("round", "score", "reason", "method")}
                if not as_json:
                    why = "the models agree" if event.get("method") == "judge" else "answers stopped changing"
                    print_success(f"Stopped after round {event['round'] + 1}: {why} ({event.get('reason')})")
            elif kind == "debate_synthesis_start" and not as_json:
                console.print()
                print_info(f"Synthesizing with {event['model']}…")
            elif kind == "debate_synthesis_end":
                result["synthesis"] = {"model": event["model"], "content": event["content"], "checkpoint_id": event.get("checkpoint_id")}
                if not as_json:
                    render_synthesis(event["content"], event["model"])
            elif kind == "debate_session_status" and event.get("status") == "completed":
                finished = True
    finally:
        if display:
            display.stop()
        if not finished:
            # Ctrl-C or a crash mid-debate: don't leave it marked running.
            db.update_debate_session(session_id, status="interrupted")

    if not finished and result["errors"] and not result["rounds"]:
        raise ValueError(result["errors"][0])
    if not as_json:
        console.print()
        print_success(f"Debate saved: {session_id} (thread {thread_id})")
    return result


@debates_app.command("list")
def debates_list(
    thread: Optional[str] = typer.Option(None, "--thread", "-t", help="Only this thread's debates."),
    format_output: str = _opt_format(),
):
    """Debate sessions, newest first."""
    as_json = _check_format(format_output)
    _load_env()
    from rich.table import Table

    from app.core import database as db

    db.init_db()
    sessions = db.list_debate_sessions(thread)
    if as_json:
        _emit_json({"sessions": sessions})
        return
    table = Table(box=None)
    for col in ("Session", "Thread", "Participants", "Rounds", "Status"):
        table.add_column(col)
    for s in sessions:
        table.add_row(s["session_id"], s["parent_thread_id"], ", ".join(s["participants"]),
                      str((s.get("current_round") or 0) + 1), s.get("status") or "")
    console.print(table)


@debates_app.command("show")
def debates_show(
    session_id: str = typer.Argument(..., help="Debate session id."),
    format_output: str = _opt_format(),
):
    """Every round of every participant, and the synthesis."""
    as_json = _check_format(format_output)
    _load_env()

    async def read():
        from app.services import debate as debate_svc
        from app.services.arena import open_graph

        async with open_graph() as graph_app:
            return await debate_svc.session_record(graph_app, session_id)

    record = _run(read(), as_json)
    if as_json:
        _emit_json(record)
        return
    from rich.markdown import Markdown

    console.print(f"[bold]{record['question']}[/bold]")
    for model, replies in record["rounds"].items():
        console.rule(f"{record['labels'].get(model, model)} · {model}")
        for i, text in enumerate(replies):
            console.print(f"[dim]Round {i + 1}[/dim]")
            console.print(Markdown(text or "_(no answer this round)_"))
    if record["synthesis"]:
        console.rule("Synthesis")
        console.print(Markdown(record["synthesis"]))


@debates_app.command("continue")
def debates_continue(
    session_id: str = typer.Argument(..., help="Debate session id."),
    rounds: int = typer.Option(1, "--rounds", "-r", min=1, help="How many more rounds."),
    inject: Optional[List[str]] = typer.Option(
        None, "--inject", "-i", help="Add this to the next round's prompts (repeat for more)."
    ),
    rag: bool = _opt_rag(),
    web_search: bool = _opt_web(),
    summarizer: Optional[str] = _opt_summarizer(),
    system: Optional[str] = _opt_system(),
    force: bool = _opt_force(),
    format_output: str = _opt_format(),
):
    """Run more rounds of a stopped debate (resume after a pause, or inject a message)."""
    as_json = _check_format(format_output)
    _load_env()
    context = _run_context(as_json, summarizer, system)

    async def go():
        from app.core import database as db
        from app.services import debate as debate_svc
        from app.services.arena import open_graph

        async with open_graph() as graph_app:
            session = db.get_debate_session(session_id)
            if not session:
                raise ValueError(f"Debate session {session_id} not found.")
            debate_svc.check_not_running(session, force)
            events = debate_svc.continue_debate(graph_app, session_id, rounds, inject or (),
                                                _toggles(web_search, rag), context=context)
            return await _follow_debate(events, session, "", as_json, f"{rounds} more round(s)")

    result = _run(go(), as_json)
    if as_json:
        _emit_json(result)


@debates_app.command("redirect")
def debates_redirect(
    session_id: str = typer.Argument(..., help="Debate session id."),
    prompt: str = typer.Argument(..., help="The new question the debate continues on."),
    attach: Optional[List[str]] = _opt_attach(),
    rag: bool = _opt_rag(),
    web_search: bool = _opt_web(),
    summarizer: Optional[str] = _opt_summarizer(),
    system: Optional[str] = _opt_system(),
    force: bool = _opt_force(),
    format_output: str = _opt_format(),
):
    """Restart a debate on a new question, from where each model's lane stands."""
    as_json = _check_format(format_output)
    _load_env()
    context = _run_context(as_json, summarizer, system)
    documents = _documents(attach, as_json)

    async def go():
        from app.core import database as db
        from app.services import debate as debate_svc
        from app.services.arena import open_graph

        async with open_graph() as graph_app:
            session = db.get_debate_session(session_id)
            if not session:
                raise ValueError(f"Debate session {session_id} not found.")
            debate_svc.check_not_running(session, force)
            events = debate_svc.run_debate(graph_app, session_id, prompt, _toggles(web_search, rag), documents,
                                           context=context)
            policy = session["termination_policy"]
            return await _follow_debate(events, session, prompt, as_json, f"up to {policy.get('max_rounds')} round(s)")

    result = _run(go(), as_json)
    if as_json:
        _emit_json(result)


@debates_app.command("delete")
def debates_delete(
    session_id: str = typer.Argument(..., help="Debate session id."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask first."),
):
    """Delete a debate and its lanes (the thread it started from stays)."""
    _load_env()
    from app.core import database as db
    from app.cli_display import print_success

    db.init_db()
    if not db.get_debate_session(session_id):
        _fail(f"Debate session {session_id} not found.", False)
    if not yes and not typer.confirm(f"Delete debate {session_id}? This cannot be undone."):
        return
    db.delete_debate_session(session_id)
    print_success(f"Deleted {session_id}")


# ─── SYNTHESIZE Command ─────────────────────────────────────────


@app.command()
def synthesize(
    thread: Optional[str] = typer.Option(None, "--thread", "-t", help="Thread whose answers to synthesize."),
    answers: Optional[List[str]] = typer.Option(
        None, "--answers", "-a", help="Checkpoint of an answer to include (repeat; default: the latest answer on every branch)."
    ),
    from_checkpoint: Optional[str] = typer.Option(
        None, "--from", help="Where the synthesis goes (default: beside --answers, else the thread head)."
    ),
    debate: Optional[str] = typer.Option(None, "--debate", "-d", help="Debate session to synthesize."),
    judge: Optional[str] = typer.Option(
        None, "--judge", "-j", help=f"Model that writes the synthesis (default: {DEFAULT_MODEL}, or the debate's own synthesizer)."
    ),
    summarizer: Optional[str] = _opt_summarizer(),
    system: Optional[str] = _opt_system(),
    format_output: str = _opt_format(),
):
    """
    [bold cyan]🔬 Synthesize[/bold cyan] — Combine existing answers into one.

    With --thread: the latest answer on every branch of the thread (e.g. each
    model's arena answer), or exactly the --answers given, is synthesized and
    the result added to the thread. With --debate: every round of every
    participant becomes an argument map.
    """
    as_json = _check_format(format_output)
    _load_env()
    if bool(thread) == bool(debate):
        raise typer.BadParameter("pass exactly one of --thread or --debate")
    if debate and (answers or from_checkpoint):
        raise typer.BadParameter("--answers and --from go with --thread")
    if judge:
        _validate_models([judge], as_json)
    context = _run_context(as_json, summarizer, system)

    if debate:
        result = _run(_run_synthesize_debate(debate, judge, as_json, context), as_json)
    else:
        result = _run(_run_synthesize_thread(thread, judge or DEFAULT_MODEL, as_json, context, answers, from_checkpoint), as_json)
    if as_json:
        _emit_json(result)
    if not result.get("synthesis") or result["synthesis"].get("error"):
        raise typer.Exit(1)


async def _run_synthesize_thread(thread_id, judge, as_json, context, answers=None, parent=None):
    from app.services.arena import open_graph, synthesize_thread
    from app.cli_display import print_header, print_info, print_error, render_synthesis

    result: Dict[str, Any] = {"thread_id": thread_id, "answers": {}, "synthesis": None}
    if not as_json:
        print_header()
    async with open_graph() as graph_app:
        async for event in synthesize_thread(graph_app, thread_id, judge, context=context,
                                             checkpoint_ids=answers, parent_checkpoint_id=parent):
            if event["type"] == "end":
                result["answers"][event["checkpoint_id"]] = {"model": event["model"], "content": event["content"]}
            elif event["type"] == "synthesis_start" and not as_json:
                print_info(f"Synthesizing {len(result['answers'])} answers with {event['model']}…")
            elif event["type"] == "synthesis":
                result["synthesis"] = {k: event[k] for k in ("model", "content", "checkpoint_id", "error")}
                if not as_json:
                    if event["error"]:
                        print_error(f"Synthesis failed: {event['error']}")
                    else:
                        render_synthesis(event["content"], event["model"])
    return result


async def _run_synthesize_debate(session_id, judge, as_json, context):
    from app.core import database as db
    from app.services import debate as debate_svc
    from app.services.arena import open_graph
    from app.cli_display import print_header, print_info, render_synthesis

    result: Dict[str, Any] = {"session_id": session_id, "synthesis": None}
    async with open_graph() as graph_app:
        if not db.get_debate_session(session_id):
            raise ValueError(f"Debate session {session_id} not found.")
        if not as_json:
            print_header()
        async for event in debate_svc.synthesize_session(graph_app, session_id, prompt="", synthesizer=judge,
                                                         context=context):
            if event["type"] == "error":
                raise ValueError(event["message"])
            if event["type"] == "debate_synthesis_start" and not as_json:
                print_info(f"Synthesizing with {event['model']}…")
            elif event["type"] == "debate_synthesis_end":
                result["synthesis"] = {"model": event["model"], "content": event["content"], "checkpoint_id": event.get("checkpoint_id"), "error": None}
                if not as_json:
                    render_synthesis(event["content"], event["model"])
    return result


# ─── Reading and editing threads ─────────────────────────────────


@app.command()
def tree(
    thread: str = typer.Option(..., "--thread", "-t", help="Thread ID to visualize."),
    open_browser: bool = typer.Option(
        False, "--open", "-o", help="Open the thread in the web UI instead."
    ),
    format_output: str = _opt_format(),
):
    """
    [bold magenta]🌳 Tree View[/bold magenta] — The conversation tree, with each node's checkpoint id.
    """
    as_json = _check_format(format_output)
    _load_env()
    if open_browser:
        import webbrowser
        from urllib.parse import quote

        base = os.getenv("CRUCIBLE_WEB_URL", "http://localhost:3000").rstrip("/")
        webbrowser.open(f"{base}/?thread={quote(thread)}")
        from app.cli_display import print_success

        print_success("Opened in browser.")
        return

    data = _run(_thread_tree(thread), as_json)
    if as_json:
        _emit_json({"thread_id": thread, "nodes": data["nodes"], "edges": data["edges"],
                    "current_checkpoint": data["current_checkpoint"]})
        return
    from app.cli_display import render_ascii_tree, print_header, print_info

    print_header()
    print_info(f"Thread: {thread} ({len(data['nodes'])} nodes)")
    console.print()
    render_ascii_tree(data["nodes"], data["edges"], data["current_checkpoint"])


async def _thread_tree(thread_id: str, checkpoint_id: Optional[str] = None):
    from app.services import history
    from app.services.arena import open_graph

    async with open_graph() as graph_app:
        data = await history.thread_tree(graph_app, thread_id, checkpoint_id)
    if not data["nodes"]:
        raise ValueError(f"Thread {thread_id} not found.")
    return data


@app.command()
def messages(
    thread: str = typer.Option(..., "--thread", "-t", help="Thread to read."),
    at: Optional[str] = typer.Option(None, "--at", help="Read the path to this checkpoint (default: the latest answer)."),
    format_output: str = _opt_format(),
):
    """The conversation on one path of a thread, as the chat view shows it."""
    as_json = _check_format(format_output)
    _load_env()

    async def read():
        from app.services import history
        from app.services.arena import open_graph

        if not at:
            return (await _thread_tree(thread))["messages"]
        async with open_graph() as graph_app:
            return await history.path_at(graph_app, thread, at)

    msgs = _run(read(), as_json)
    if as_json:
        _emit_json({"thread_id": thread, "checkpoint_id": at, "messages": msgs})
        return
    from rich.markdown import Markdown

    for m in msgs:
        who = "You" if m.get("role") == "user" else (m.get("model_name") or m.get("model") or "Assistant")
        console.rule(f"{who}  [dim]{m.get('checkpoint_id') or ''}[/dim]")
        console.print(Markdown(m.get("content") or ""))


@app.command()
def search(
    query: str = typer.Argument(..., help="Text to find (at least two characters)."),
    thread: str = typer.Option(..., "--thread", "-t", help="Thread to search, every branch."),
    format_output: str = _opt_format(),
):
    """Find messages on any branch of a thread."""
    as_json = _check_format(format_output)
    _load_env()

    async def go():
        from app.services import history
        from app.services.arena import open_graph

        async with open_graph() as graph_app:
            return await history.search_thread(graph_app, thread, query)

    results = _run(go(), as_json)
    if as_json:
        _emit_json({"thread_id": thread, "query": query, "results": results})
        return
    if not results:
        console.print("[dim]No matches.[/dim]")
    for r in results:
        console.print(f"[dim]{r['checkpoint_id']}[/dim]  {r['role']}{' · ' + r['model'] if r['model'] else ''}")
        console.print(f"  {r['excerpt']}")


@app.command("delete-branch")
def delete_branch(
    checkpoint: str = typer.Argument(..., help="Checkpoint of the node to delete, with everything below it."),
    thread: str = typer.Option(..., "--thread", "-t", help="The checkpoint's thread."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask first."),
    format_output: str = _opt_format(),
):
    """Delete a node of the conversation tree and every branch below it."""
    as_json = _check_format(format_output)
    _load_env()
    if not yes and not typer.confirm(f"Delete {checkpoint} and everything below it? This cannot be undone."):
        return

    async def go():
        from app.services import history
        from app.services.arena import open_graph

        async with open_graph() as graph_app:
            return await history.delete_branch(graph_app, thread, checkpoint)

    deleted = _run(go(), as_json)
    if not deleted:
        _fail(f"Checkpoint {checkpoint} not found on thread {thread}.", as_json)
    if as_json:
        _emit_json({"thread_id": thread, "checkpoint_id": checkpoint, "deleted_count": deleted})
    else:
        from app.cli_display import print_success

        print_success(f"Deleted {deleted} checkpoint(s).")


@app.command()
def upload(
    files: List[str] = typer.Argument(..., help="Files to upload (.pdf .txt .md .csv)."),
    thread: str = typer.Option(..., "--thread", "-t", help="Thread whose --rag searches these files."),
    format_output: str = _opt_format(),
):
    """Upload files to a thread for retrieval: turns run with --rag search them."""
    as_json = _check_format(format_output)
    _load_env()
    from app.services import rag
    from app.services.uploads import upload_file

    done = []
    for path in files:
        try:
            done.append(upload_file(thread, path, rag.index_document))
        except ValueError as e:
            _fail(str(e), as_json)
    if as_json:
        _emit_json({"thread_id": thread, "uploaded": done})
        return
    from app.cli_display import print_success

    for d in done:
        print_success(f"{d['filename']}: {d['chunks']} chunk(s) indexed for {thread}")


@app.command()
def threads(
    rename: Optional[str] = typer.Option(None, "--rename", help="Thread ID to rename."),
    title: Optional[str] = typer.Option(
        None, "--title", help="New title (used with --rename)."
    ),
    delete: Optional[str] = typer.Option(None, "--delete", help="Thread ID to delete."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask before deleting."),
    format_output: str = _opt_format(),
):
    """
    [bold]🧪 Threads[/bold] — List, rename, or delete experiments.
    """
    as_json = _check_format(format_output)
    _load_env()
    from app.core import database as db
    from app.cli_display import (
        render_threads_table,
        print_success,
        print_header,
    )

    db.init_db()
    if rename:
        if not title:
            raise typer.BadParameter("--rename needs --title")
        db.rename_thread(rename, title)
        print_success(f"Renamed {rename} → {title}")
        return

    if delete:
        if not yes and not typer.confirm(f"Delete thread {delete}? This cannot be undone."):
            return
        from app.services.threads import default_thread_deleter

        default_thread_deleter()(delete)
        print_success(f"Deleted {delete}")
        return

    thread_list = db.list_threads()
    if as_json:
        _emit_json({"threads": thread_list})
        return
    print_header()
    render_threads_table(thread_list)


# ─── MODELS and KEYS ─────────────────────────────────────────────


@app.command()
def models(
    format_output: str = _opt_format(),
    all_models: bool = typer.Option(False, "--all", help="Include legacy models."),
):
    """
    [bold]🧠 Models[/bold] — List model IDs and whether their API key is set.
    """
    as_json = _check_format(format_output)
    _load_env()
    from app.services.arena import list_models

    rows = [m for m in list_models() if all_models or not m["legacy"]]
    if as_json:
        _emit_json({"models": rows})
        return
    from rich.table import Table

    table = Table(box=None)
    table.add_column("ID", no_wrap=True)
    table.add_column("Name")
    table.add_column("Key", justify="center")
    for m in rows:
        table.add_row(m["id"], m["name"], "✓" if m["key_available"] else "[dim]–[/dim]")
    console.print(table)


@app.command()
def keys(
    set_key: Optional[str] = typer.Option(
        None, "--set", help="Key to set, e.g. OPENAI_API_KEY; the value is asked for without echoing."
    ),
    unset: Optional[str] = typer.Option(None, "--unset", help="Key to remove from backend/.env."),
    format_output: str = _opt_format(),
):
    """Which provider API keys are set (masked), and set or remove one in backend/.env."""
    as_json = _check_format(format_output)
    _load_env()
    from app.services import keys as keys_svc

    try:
        if set_key:
            keys_svc.check_names([set_key])
            value = typer.prompt(set_key, hide_input=True, err=True)
            keys_svc.save_keys({set_key: value})
        elif unset:
            keys_svc.save_keys({unset: ""})
    except ValueError as e:
        _fail(str(e), as_json)
    status = keys_svc.key_status()
    if as_json:
        _emit_json({"keys": status})
        return
    for name, s in status.items():
        console.print(f"{name:20} {s['masked'] if s['set'] else '[dim]not set[/dim]'}")


# ─── CATALOG-SYNC Command ───────────────────────────────────────


@app.command("catalog-sync")
def catalog_sync(
    probe: str = typer.Option("new", "--probe", help="Which models get a real test call: new (new/changed/untested), failed (last verdict was a failure), all, or none."),
    no_search: bool = typer.Option(False, "--no-search", help="Skip the web-search probe."),
    workers: int = typer.Option(6, "--workers", min=1, help="Parallel probes; lower it if a provider rate-limits."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change without writing catalog.json."),
    format_output: str = typer.Option("rich", "--format", "-f", help=FORMAT_HELP),
):
    """
    [bold]📚 Catalog sync[/bold] — Refresh the model catalog from the providers' own APIs.

    Lists models from OpenAI, Anthropic and Google, applies overrides.json,
    probes models with a real one-token call (and a web search), and writes
    app/catalog/data/catalog.json. Probes cost a few cents; --probe none is free.
    """
    as_json = _check_format(format_output)
    if probe not in ("new", "failed", "all", "none"):
        raise typer.BadParameter("must be new, failed, all or none", param_hint="--probe")
    _load_env()
    from datetime import date

    from app.catalog import load_catalog, load_overrides, save_catalog, sync_catalog
    from app.catalog.sources import SOURCES

    today = date.today().isoformat()
    keys = {name: os.getenv(src.env_key) for name, src in SOURCES.items()}
    catalog, diff = sync_catalog(
        load_catalog(), keys, overrides=load_overrides(), today=today,
        probe=probe, probe_web_search=not no_search, workers=workers,
    )
    if not dry_run:
        save_catalog(catalog, synced=today)
    report = {
        "written": not dry_run,
        "models": len(catalog),
        "added": diff.added,
        "unlisted": diff.unlisted,
        "changed": diff.changed,
        "probed": diff.probed,
        "skipped_providers": diff.skipped_providers,
    }
    if as_json:
        _emit_json(report)
        return
    from app.cli_display import print_info, print_success

    print_info(f"{len(catalog)} models; added {len(diff.added)}, unlisted {len(diff.unlisted)}, changed {len(diff.changed)}")
    for mid, r in diff.probed.items():
        mark = "✓" if r["chat"] else "✗"
        search = {True: "search ✓", False: "search ✗", None: ""}[r["web_search"]]
        console.print(f"  {mark} {mid} {search} {r['error'] or ''}")
    if diff.skipped_providers:
        print_info(f"No key, left unchanged: {', '.join(diff.skipped_providers)}")
    if not dry_run:
        print_success("Wrote app/catalog/data/catalog.json")
    if diff.added or diff.changed:
        from app.services import scaffold_audit

        history = scaffold_audit.load_history()
        last = max((r["date"] for r in history), default="never")
        print_info(f"Models were added or changed; context scaffolding was last audited: {last}. "
                   "Check it still earns its place: `uv run crucible scaffold-audit --estimate`")


# ─── COMPACTION-EVAL Command ────────────────────────────────────


@app.command("compaction-eval")
def compaction_eval(
    models: Optional[List[str]] = typer.Option(
        None, "--models", "-m",
        help="Models that answer the probes (default: the cheapest offered model of each provider, by the price list). 'oracle' answers iff the value is still in context.",
    ),
    thresholds: Optional[List[int]] = typer.Option(
        None, "--threshold", "-t", help="Compaction thresholds in tokens (repeat). Default: 6000 (dense), 2000 and 4000 (basic)."
    ),
    summarizers: Optional[List[str]] = typer.Option(
        None, "--summarizer", "-s", help="Summarizer models to compare (repeat); one condition per threshold and summarizer. Default: the app's. Gemini takes a thinking level: gemini-3.5-flash@minimal."
    ),
    lengths: Optional[List[int]] = typer.Option(
        None, "--length", "-l", help="Summary length targets in tokens (repeat); one condition per threshold, summarizer and length. Default: no limit (the app's brief)."
    ),
    keeps: Optional[List[str]] = typer.Option(
        None, "--keep", help="What stays verbatim after pruning (repeat): 'recent' (the last 5 messages, the app's rule) or 'user' (also every user message within --user-budget, as Codex CLI does). Default: recent."
    ),
    user_budget: int = typer.Option(20_000, "--user-budget", help="Token budget for --keep user (Codex CLI uses 20,000)."),
    instructions: Optional[List[str]] = typer.Option(
        None, "--instruction", help="Summary instruction (repeat): 'brief' (the app's), 'handoff' (Codex CLI's), 'state' (state + index), 'index' (topics only) or 'allsubjects' (brief + keep every subject's specifics, priorities may change). Default: brief."
    ),
    recalls: Optional[List[str]] = typer.Option(
        None, "--recall", help="Bring hidden messages back per request (repeat): 'none', 'keyword', 'embedding' (the app's local embedding model) or 'guided' (a model reads the summary and names what to search for, then keyword search). Default: none."
    ),
    rewriters: Optional[List[str]] = typer.Option(None, "--rewriter", help="Model that chooses search terms for --recall guided (repeat: one condition per model). Default: gpt-6-luna."),
    excerpts: Optional[List[str]] = typer.Option(None, "--excerpt", help="How recalled messages are shown (repeat to compare): 'message' (whole messages, the default) or 'sentences' (only the matching sentences)."),
    later_subject: str = typer.Option("unknown", "--later-subject", help="Task scenario only: what goal reminders say about the subject the conversation later switches to: 'unknown' (nothing), 'announced' (it is next) or 'mentioned' (named as often, as out of scope). Pair runs across values."),
    asides: bool = typer.Option(False, "--asides", help="State every fact as a throwaway remark (dense only); pair with a run without it."),
    questions: str = typer.Option("direct", "--questions", help="Probe by the subject's name ('direct') or by what it does ('indirect'; dense only)."),
    fact_variants: str = typer.Option("plain,distractor,update", "--fact-variants", help="Variants the facts cycle through (dense only), e.g. 'plain' for plain facts only."),
    repeat_facts: bool = typer.Option(False, "--repeat-facts", help="Restate every fact once more later with the same value (dense only); pair with a run without it."),
    assistant_facts: float = typer.Option(0.0, "--assistant-facts", help="Share of planted facts stated by the assistant instead of the user (dense only)."),
    scenario: str = typer.Option("dense", "--scenario", help="dense: specifics everywhere, distractors and updates. task: a stated goal, facts on and off it, then a switch of goal. basic: pilot 1's generic filler."),
    facts: int = typer.Option(24, "--facts", help="Planted facts per scenario (dense only)."),
    seeds: int = typer.Option(3, "--seeds", help="Number of scenarios (different filler and ordering)."),
    exchanges: Optional[int] = typer.Option(None, "--exchanges", help="User/assistant pairs per scenario. Default: 140 (dense), 40 (basic)."),
    compaction: str = typer.Option("live", "--compaction", help="live: summarize turn by turn as the conversation grows. once: one summary when probing starts."),
    baseline: bool = typer.Option(True, "--baseline/--no-baseline", help="Include the never-compact condition (the costliest: every probe reads the full history)."),
    oracle: bool = typer.Option(True, "--oracle/--no-oracle", help="Also probe the availability oracles: 'oracle' (value anywhere in context) and 'oracle-strict' (value next to its subject). No API cost beyond shared live summaries."),
    min_effect: float = typer.Option(0.1, "--min-effect", help="Smallest recall difference that matters (0.1 = 10 points)."),
    concurrency: int = typer.Option(4, "--concurrency", help="Branches run in parallel."),
    db: str = typer.Option("experiments/compaction.sqlite", "--db", help="Separate database for experiment threads."),
    out: Optional[str] = typer.Option(None, "--out", help="Write every probe result as JSON here."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Only the oracle answers, with a lossy stand-in summarizer; no API calls."),
    budget: Optional[float] = typer.Option(None, "--budget", help="Hard spending cap in USD for a real run (required). The run is refused if the estimate exceeds it, and stops starting new calls once reached."),
    estimate_only: bool = typer.Option(False, "--estimate", help="Only estimate the cost (a few cents of calibration calls) and exit."),
    rescore: Optional[str] = typer.Option(None, "--rescore", help="Rescore a results file for sibling-value answers (left by chained probes): recall and comparisons within bounds. No API calls; the file is not changed."),
    format_output: str = typer.Option("rich", "--format", "-f", help=FORMAT_HELP),
):
    """
    [bold]🧪 Compaction eval[/bold] — How much planted detail survives summarization?

    Every condition (never compact, and each threshold × summarizer) answers
    the same probes on the same conversation. Real runs call the chosen
    models; results include raw token usage.
    """
    from app.services.compaction_eval import ORACLE, ORACLES

    as_json = _check_format(format_output)
    if rescore:
        _rescore_eval(rescore, min_effect, as_json)
        return
    _load_env()
    if scenario not in ("dense", "task", "basic") or compaction not in ("live", "once"):
        _fail("--scenario is dense|task|basic and --compaction is live|once", as_json)
    if (not set(keeps or []) <= {"recent", "user"} or not set(instructions or []) <= {"brief", "handoff", "state", "index", "allsubjects"}
            or not set(recalls or []) <= {"none", "keyword", "embedding", "guided"} or questions not in ("direct", "indirect")
            or later_subject not in ("unknown", "announced", "mentioned")
            or not set(excerpts or []) <= {"message", "sentences"}):
        _fail("--keep is recent|user, --instruction brief|handoff|state|index|allsubjects, --recall none|keyword|embedding|guided, --questions direct|indirect, --later-subject unknown|announced|mentioned, --excerpt message|sentences", as_json)
    if not dry_run and budget is None and not estimate_only:
        _fail("a real run needs --budget (USD); use --estimate to see what it would cost", as_json)
    model_ids = [ORACLE] if dry_run else list(models or _cheapest_models())
    if oracle:
        model_ids += [o for o in ORACLES if o not in model_ids]
    if not dry_run:
        from app.services.compaction_eval import split_thinking

        try:
            bases = [split_thinking(s)[0] for s in summarizers or []]
        except ValueError as e:
            _fail(str(e), as_json)
        _validate_models([m for m in model_ids if m not in ORACLES] + bases + list(rewriters or []), as_json)
    options = {
        "scenario": scenario,
        "facts": facts,
        "seeds": seeds,
        "exchanges": exchanges or (40 if scenario == "basic" else 140),
        "thresholds": thresholds or ([2000, 4000] if scenario == "basic" else [6000]),
        "summarizers": list(summarizers or []),
        "lengths": list(lengths or []),
        "keeps": list(keeps or []),
        "user_budget": user_budget,
        "instructions": list(instructions or []),
        "recalls": list(recalls or []),
        "questions": questions,
        "rewriters": list(rewriters or ["gpt-6-luna"]),
        "asides": asides,
        "later_subject": later_subject,
        "excerpts": list(excerpts or ["message"]),
        "assistant_facts": assistant_facts,
        "fact_variants": fact_variants.split(","),
        "repeat_facts": repeat_facts,
        "compaction": compaction,
        "baseline": baseline,
        "concurrency": concurrency,
    }
    result = _run(_run_compaction_eval(model_ids, options, min_effect, db, out, dry_run, budget, estimate_only), as_json)
    if as_json or estimate_only:
        if estimate_only and not as_json:
            return
        _emit_json(result)
        return
    from rich.table import Table

    table = Table(title="Recall by condition", box=None)
    for col in ("condition / model", "recall", "n", "stale", "by variant", "by summaries survived"):
        table.add_column(col)
    for name, row in result["recall"].items():
        variants = ", ".join(f"{k} {c}/{n}" for k, (c, n) in sorted(row["by_variant"].items()))
        survived = ", ".join(f"{k}: {c}/{n}" for k, (c, n) in sorted(row["by_compactions"].items(), key=lambda kv: int(kv[0])))
        table.add_row(name, f"{row['recall']:.2f}", str(row["n"]), str(row["stale"]), variants, survived)
    console.print(table)
    for c in result["comparisons"]:
        console.print(f"  {c['model']}: {c['a']} vs {c['b']}: [bold]{c['outcome']}[/bold] "
                      f"effect {c['effect']} interval {c['interval']}")
    console.print(f"\nUsage: {json.dumps(result['usage'], indent=1)}")
    if result.get("spend", {}).get("model_errors"):
        console.print(f"[bold red]Stopped: a model call failed[/bold red] ({result['spend']['model_errors'][0]}). Results are incomplete.")
        if result["spend"].get("failed_requests"):
            console.print(f"The failed request is saved in {result['spend']['failed_requests']}; inspect it there "
                          "rather than sending it again (a provider that flagged a prompt may flag the account).")
    if result.get("spend"):
        sp = result["spend"]
        console.print(f"Spent ${sp['total']:.2f} of ${sp['budget']:.2f} (estimate was ${sp['estimate']:.2f})"
                      + (" — [bold]stopped at the budget[/bold]" if sp["stopped_by_budget"] else ""))
    if out:
        console.print(f"Wrote {out}")


def _cheapest_models() -> List[str]:
    from datetime import date

    from app.api.models import MODEL_REGISTRY
    from app.catalog import PriceBook, load_catalog, load_prices
    from app.services.compaction_eval import cheapest_models

    return cheapest_models(MODEL_REGISTRY, load_catalog(), PriceBook(load_prices(), date.today().isoformat()))


def _failures_path(prefix: str):
    """Where a run's failed requests are saved (gitignored)."""
    from pathlib import Path

    return Path(__file__).resolve().parents[1] / "experiments" / ".failures" / f"{prefix}.json"


def _catalog_synced():
    """When the committed model catalog was last synced (None: no catalog)."""
    from app.catalog.store import DEFAULT_CATALOG

    return json.loads(DEFAULT_CATALOG.read_text()).get("synced") if DEFAULT_CATALOG.exists() else None


def _replay_cache():
    """Replayed conversations with their summaries, reused across runs, keyed
    by the summarizer's catalog identity so a new model version replays anew."""
    from pathlib import Path

    from app.catalog import load_catalog
    from app.services import compaction_eval as ce

    return ce.ReplayCache(Path(__file__).resolve().parents[1] / "experiments" / ".replay-cache",
                          identity=ce.catalog_identity(load_catalog(), _catalog_synced()))


def _calibration_cache():
    """Today's calibration profiles, shared by --estimate and the run after it."""
    from datetime import date
    from pathlib import Path

    from app.services import compaction_eval as ce

    return ce.CalibrationCache(Path(__file__).resolve().parents[1] / "experiments" / ".calibration-cache.json",
                               date.today().isoformat())


def _planning_factor() -> float:
    """The cost margin learned from this project's past experiment runs."""
    from pathlib import Path

    from app.services import compaction_eval as ce

    return ce.planning_factor(ce.load_run_summaries(Path(__file__).resolve().parents[1] / "experiments" / "results"))


def _write_partial(out, prefix, options, results) -> None:
    """Save what has finished so far, so a stopped run keeps its completed conditions."""
    from pathlib import Path

    from app.services import compaction_eval as ce

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps({"run": prefix, **options, "partial": True, "recall": ce.summarize_results(results),
                                     "usage": ce.usage_totals(results), "probes": ce.results_as_dicts(results)},
                                    ensure_ascii=False, indent=1))


def _print_estimate(est, budget) -> None:
    lines = [f"Estimated cost: ${est.total:.2f} (plan for up to ${est.high:.2f}, ×{est.factor} learned from past runs), "
             f"calibration already spent ${est.calibration:.2f}"]
    lines += [f"  {name}: ${cost:.2f}" + (f" ({est.summaries[name]:.0f} summaries)" if name in est.summaries else "")
              for name, cost in est.by_condition.items()]
    lines += ["  by model: " + ", ".join(f"{m} ${c:.2f}" for m, c in sorted(est.by_model.items(), key=lambda kv: -kv[1]))]
    if budget is not None:
        lines.append(f"  budget: ${budget:.2f}")
    typer.echo("\n".join(lines), err=True)


def _eval_scenarios(options) -> dict:
    """The conversations a compaction-eval run probes, from its options (as
    a results file records them)."""
    from app.compaction import build_dense_scenario, build_scenario, build_task_scenario

    seeds = range(options["seeds"])
    if options["scenario"] == "dense":
        return {str(s): build_dense_scenario(n_facts=options["facts"], exchanges=options["exchanges"], seed=s,
                                             assistant_facts=options["assistant_facts"],
                                             variants=options["fact_variants"], repeat_facts=options["repeat_facts"],
                                             questions=options["questions"], asides=options["asides"])
                for s in seeds}
    if options["scenario"] == "task":
        return {str(s): build_task_scenario(exchanges=options["exchanges"], seed=s,
                                            assistant_facts=options["assistant_facts"], questions=options["questions"],
                                            later_subject=options["later_subject"])
                for s in seeds}
    return {str(s): build_scenario(exchanges=options["exchanges"], seed=s) for s in seeds}


def _audit_scenarios(seeds: int, questions: str) -> dict:
    """The conversations a scaffold audit probes."""
    from app.compaction import build_dense_scenario

    return {str(s): build_dense_scenario(n_facts=24, exchanges=140, seed=s, assistant_facts=0.5, questions=questions)
            for s in range(seeds)}


async def _run_compaction_eval(model_ids, options, min_effect, db_path, out, dry_run, budget=None, estimate_only=False):
    from datetime import datetime, timezone
    from itertools import combinations
    from pathlib import Path

    from app.compaction import (
        DetailedBrief,
        AllSubjects,
        HandoffBrief,
        SentenceRecall,
        EmbeddingRecall,
        GuidedRecall,
        IndexOnly,
        KeepUserMessages,
        KeywordRecall,
        StateAndIndex,
        LengthTarget,
        NeverCompact,
        ThresholdPolicy,
        fixed_tokens,
    )
    from app.core import database as db
    from app.llm import default_model_factory
    from app.services import compaction_eval as ce
    from app.services.arena import open_graph

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db.DB_PATH = db_path  # experiment threads never touch the app's database
    scenarios = _eval_scenarios(options)
    conditions = [ce.Condition("never", NeverCompact())] if options["baseline"] else []
    all_facts = [f for sc in scenarios.values() for f in sc.facts]
    factory = ce.EvalModelFactory(all_facts, inner=None if dry_run else default_model_factory(), scenarios=scenarios)
    retentions = {"recent": None, "user": KeepUserMessages(options["user_budget"])}
    bases = {"brief": None, "handoff": HandoffBrief(), "state": StateAndIndex(), "index": IndexOnly(), "allsubjects": AllSubjects()}
    recallers = {"none": None, "keyword": KeywordRecall()}
    if "embedding" in options["recalls"]:
        from app.services import rag

        recallers["embedding"] = EmbeddingRecall(ce.cached_embedder(rag.get_embeddings().embed_documents))
    recall_choices = [r for r in options["recalls"] or ["none"] if r != "guided"]
    if "guided" in options["recalls"]:
        for model in options["rewriters"]:
            guided = GuidedRecall(ce.model_rewriter(factory, model))
            if len(options["rewriters"]) > 1:  # one model keeps the historical name
                guided.name = f"guided-{model}"
            recallers[guided.name] = guided
            recall_choices.append(guided.name)
    if "sentences" in options["excerpts"]:
        narrowed = []
        for rec in recall_choices:
            if recallers[rec] is not None:
                wrapped = SentenceRecall(recallers[rec])
                recallers[wrapped.name] = wrapped
                narrowed.append(wrapped.name)
        keep_whole = "message" in options["excerpts"]
        recall_choices = [r for r in recall_choices if keep_whole or recallers[r] is None] + narrowed
    for t in options["thresholds"]:
        for summarizer in options["summarizers"] or [None]:
            for length in options["lengths"] or [None]:
                for keep in options["keeps"] or ["recent"]:
                    for base in options["instructions"] or ["brief"]:
                        for rec in recall_choices:
                            name = (f"t{t}" + (f"-{summarizer}" if summarizer else "") + (f"-len{length}" if length else "")
                                    + (f"-keep{retentions[keep].name}" if retentions[keep] else "")
                                    + (f"-{base}" if bases[base] else "")
                                    + (f"-recall{recallers[rec].name}" if recallers[rec] else ""))
                            instruction = bases[base]
                            if length:
                                instruction = LengthTarget(length, base=instruction or DetailedBrief())
                            conditions.append(ce.Condition(name, ThresholdPolicy(fixed_tokens(t), name=name), summarizer,
                                                           instruction, retentions[keep], recallers[rec]))

    prefix = "compaction-eval-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    grid = ce.run_live_grid if options["compaction"] == "live" else ce.run_grid
    prices = None
    if not dry_run:
        from app.catalog import PriceBook, load_prices

        prices = PriceBook(load_prices(), datetime.now(timezone.utc).date().isoformat())
    async with open_graph() as graph_app:
        run = await ce.run_budgeted(
            graph_app, scenarios, model_ids, conditions, factory, prices=prices, budget=budget,
            estimate_only=estimate_only, grid=grid, sample_tokens=max(options["thresholds"]),
            concurrency=options["concurrency"], prefix=prefix, on_estimate=lambda e: _print_estimate(e, budget),
            on_progress=(lambda rs: _write_partial(out, prefix, options, rs)) if out else None,
            factor=_planning_factor(), calibration_cache=_calibration_cache(),
            replay_cache=None if dry_run else _replay_cache(),
        )
    if estimate_only:
        e = run.estimate
        return {"estimate": {"total": round(e.total, 2), "high": round(e.high, 2), "by_condition": e.by_condition,
                             "by_model": e.by_model, "summaries": e.summaries, "calibration": round(e.calibration, 3)}}
    results = run.results

    comparisons = []
    for model_id in model_ids:
        mine = [r for r in results if r.model == model_id]
        for a, b in combinations([c.name for c in conditions], 2):
            verdict = ce.compare_conditions(mine, a, b, min_effect=min_effect)
            comparisons.append({
                "model": model_id,
                "a": a,
                "b": b,
                "outcome": verdict.outcome.value,
                "effect": None if verdict.effect is None else round(verdict.effect, 3),
                "interval": None if verdict.interval is None else [round(x, 3) for x in verdict.interval],
                "reason": verdict.reason,
            })
    summary = {
        "run": prefix,
        "models": list(model_ids),
        **options,
        "dry_run": dry_run,
        "recall": ce.summarize_results(results),
        "comparisons": comparisons,
        "usage": ce.usage_totals(results),
    }
    if run.spend:
        summary["spend"] = ce.spend_summary(run, budget)
        failures = ce.write_failures(run.spend, _failures_path(run.prefix))
        if failures:
            summary["spend"]["failed_requests"] = failures
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps({**summary, "probes": ce.results_as_dicts(results)}, ensure_ascii=False, indent=1))
    return summary


# ─── SCAFFOLD-AUDIT Command ─────────────────────────────────────


@app.command("scaffold-audit")
def scaffold_audit_cmd(
    budget: Optional[float] = typer.Option(None, "--budget", help="Hard spending cap in USD (required to run)."),
    estimate_only: bool = typer.Option(False, "--estimate", help="Only estimate the cost and exit."),
    report: bool = typer.Option(False, "--report", help="Show the latest verdicts and whether they are stale; no API calls."),
    models: Optional[List[str]] = typer.Option(None, "--models", "-m", help="Answering models (repeat). Default: the cheapest offered per provider, plus the strict oracle."),
    only: Optional[List[str]] = typer.Option(None, "--scaffold", help="Audit only these scaffolds (repeat)."),
    threshold: int = typer.Option(8000, "--threshold", "-t", help="Compaction threshold in tokens."),
    seeds: int = typer.Option(2, "--seeds", help="Conversations per condition."),
    questions: str = typer.Option("direct", "--questions", help="direct or indirect probes."),
    min_effect: float = typer.Option(0.1, "--min-effect", help="Smallest recall difference that matters."),
    db: str = typer.Option("experiments/audit.sqlite", "--db", help="Database for audit threads."),
    rescore: Optional[str] = typer.Option(None, "--rescore", help="Judge a recorded audit run (experiments/audit/runs/*.json) again within sibling-value bounds. No API calls; nothing is appended to the history."),
    format_output: str = typer.Option("rich", "--format", "-f", help=FORMAT_HELP),
):
    """
    [bold]🧹 Scaffold audit[/bold] — Does each piece of context scaffolding still beat its baseline?

    Every mechanism between the conversation and the model (compaction, the
    verbatim window, candidate instructions and recall) is compared, paired,
    against going without it on the current models. Verdicts (keep, retire,
    harmful, inconclusive, no_headroom) are appended to experiments/audit/history.jsonl.
    """
    from app.services import scaffold_audit as sa

    as_json = _check_format(format_output)
    if rescore:
        _rescore_audit(rescore, min_effect, as_json)
        return
    _load_env()  # the report compares against the recall model the keys select
    if report:
        _scaffold_report(as_json)
        return
    if budget is None and not estimate_only:
        _fail("a real audit needs --budget (USD); use --estimate to see what it would cost", as_json)
    from app.services.compaction_eval import STRICT_ORACLE

    model_ids = list(models or _cheapest_models()) + [STRICT_ORACLE]
    _validate_models([m for m in model_ids if m != STRICT_ORACLE], as_json)
    result = _run(_run_scaffold_audit(model_ids, only, threshold, seeds, questions, min_effect, db, budget, estimate_only), as_json)
    if as_json or estimate_only:
        if as_json:
            _emit_json(result)
        return
    from rich.table import Table

    table = Table(title="Scaffold audit", box=None)
    for col in ("scaffold", "model", "without", "with", "effect", "verdict"):
        table.add_column(col)
    for r in result["records"]:
        table.add_row(r["scaffold"] + ("" if r["active"] else " (candidate)"), r["model"], f"{r['baseline_recall']:.2f}",
                      f"{r['scaffold_recall']:.2f}", f"{r['effect']:+.2f} {r['interval']}", f"[bold]{r['verdict']}[/bold]")
    console.print(table)
    sp = result.get("spend") or {}
    console.print(f"Spent ${sp.get('total', 0):.2f} of ${budget:.2f}; appended to {sa.DEFAULT_HISTORY}")


def _scaffold_report(as_json: bool) -> None:
    from app.services import scaffold_audit as sa
    from app.services.graph import default_summarizer
    from app.services.recall import default_recall_model

    history = sa.load_history()
    stale = sa.staleness(history, summarizer=default_summarizer(), catalog_synced=_catalog_synced(),
                         recall_model=default_recall_model())
    rows = list(sa.latest(history).values())
    if as_json:
        _emit_json({"stale": stale, "latest": rows})
        return
    for r in rows:
        console.print(f"  {r['date']}  {r['scaffold']:20s} {r['model']:28s} {r['verdict']:12s} "
                      f"{r['baseline_recall']:.2f} → {r['scaffold_recall']:.2f}")
    console.print(f"[yellow]Stale:[/yellow] {stale}" if stale else "Verdicts are current.")


# recorded: as stored; lower / upper: sibling-value answers left out / counted
# correct; unaffected: only probes answered before any summary was written
# while their branch was being probed (sibling-value answers left out).
BOUNDS = ("recorded", "lower", "upper", "unaffected")


def _bounded(results, scenarios):
    """Stored results as recorded and within the sibling-value bounds."""
    from app.services import compaction_eval as ce

    report = ce.sibling_report(results, scenarios)
    return report, {"recorded": results, "lower": report["lower"], "upper": report["upper"],
                    "unaffected": report["unaffected"]}


def _fraction(cell) -> str:
    return f"{cell[0]}/{cell[1]}"


def _rescore_eval(path: str, min_effect: float, as_json: bool) -> None:
    """Sibling-value bounds for a compaction-eval results file."""
    from itertools import combinations
    from pathlib import Path

    from app.services import compaction_eval as ce

    data = json.loads(Path(path).read_text())
    options = {"facts": 24, "exchanges": 140, "assistant_facts": 0.0, "fact_variants": ["plain", "distractor", "update"],
               "repeat_facts": False, "questions": "direct", "asides": False, "later_subject": "unknown", **data}
    results = ce.results_from_dicts(data["probes"])
    report, arms = _bounded(results, _eval_scenarios(options))
    conditions = list(dict.fromkeys(r.condition for r in results))
    comparisons = []
    for model in dict.fromkeys(r.model for r in results):
        for a, b in combinations(conditions, 2):
            row = {"model": model, "a": a, "b": b}
            for bound in BOUNDS:
                v = ce.compare_conditions([r for r in arms[bound] if r.model == model], a, b, min_effect=min_effect)
                row[bound] = {"outcome": v.outcome.value, "effect": None if v.effect is None else round(v.effect, 3),
                              "interval": None if v.interval is None else [round(x, 3) for x in v.interval]}
            comparisons.append(row)
    out = {"run": data.get("run"), "cells": report["cells"], "flagged": report["flagged"], "comparisons": comparisons}
    if as_json:
        _emit_json(out)
        return
    from rich.table import Table

    table = Table(title=f"Sibling-value rescore of {data.get('run')}", box=None)
    for col in ("condition / model", "recorded", "lower", "upper", "unaffected", "earlier / later sibling",
                "summaries while probing"):
        table.add_column(col)
    for cell, c in report["cells"].items():
        table.add_row(cell, _fraction(c["recorded"]), _fraction(c["lower"]), _fraction(c["upper"]),
                      _fraction(c["unaffected"]),
                      f"{c['earlier_sibling']} / {c['later_sibling']}", str(c["summaries_during_probing"]))
    console.print(table)
    flips = [c for c in comparisons if len({c[b]["outcome"] for b in BOUNDS}) > 1]
    console.print(f"\nComparisons whose outcome depends on the bound ({len(flips)} of {len(comparisons)}):")
    for c in flips:
        console.print(f"  {c['model']}: {c['a']} vs {c['b']}: " + ", ".join(
            f"{b} {c[b]['outcome']} {c[b]['effect']} {c[b]['interval']}" for b in BOUNDS))


def _rescore_audit(path: str, min_effect: float, as_json: bool) -> None:
    """A recorded audit run judged again (current verdict rules) as recorded
    and within the sibling-value bounds. Reads the history; never writes it."""
    from pathlib import Path

    from app.services import compaction_eval as ce
    from app.services import scaffold_audit as sa

    run = json.loads(Path(path).read_text())
    setup = run.get("setup") or next(
        ({k: r[k] for k in ("threshold", "seeds", "questions")} for r in sa.load_history() if r.get("run") == run["run"]),
        None)
    if setup is None:
        _fail(f"{run['run']} is not in {sa.DEFAULT_HISTORY} and its file records no setup", as_json)
    results = ce.results_from_dicts(run["probes"])
    report, arms = _bounded(results, _audit_scenarios(setup["seeds"], setup["questions"]))
    scaffolds = sa.scaffolds_for_records(run["records"], setup["threshold"])
    models = list(dict.fromkeys(r["model"] for r in run["records"]))
    judged = {b: {(r["scaffold"], r["model"]): r for r in sa.audit(arms[b], scaffolds, models, min_effect=min_effect)}
              for b in BOUNDS}
    rows = []
    for rec in run["records"]:
        key = (rec["scaffold"], rec["model"])
        rows.append({"scaffold": rec["scaffold"], "model": rec["model"],
                     "as_recorded": {k: rec[k] for k in ("baseline_recall", "scaffold_recall", "verdict")},
                     **{b: {k: judged[b][key][k] for k in ("baseline_recall", "scaffold_recall", "n", "outcome", "effect",
                                                            "interval", "verdict")}
                        for b in BOUNDS if key in judged[b]}})
    out = {"run": run["run"], "setup": setup, "rows": rows, "cells": report["cells"], "flagged": report["flagged"]}
    if as_json:
        _emit_json(out)
        return
    from rich.table import Table

    table = Table(title=f"Rescored audit {run['run']} (verdicts under today's rules)", box=None)
    for col in ("scaffold", "model", "as recorded", "rejudged", "lower", "upper", "unaffected (n)"):
        table.add_column(col)

    def show(x, n=False):
        if not x:
            return "-"
        return f"{x['baseline_recall']:.2f} → {x['scaffold_recall']:.2f} {x['verdict']}" + (f" ({x['n']})" if n else "")

    for r in rows:
        table.add_row(r["scaffold"], r["model"], show(r["as_recorded"]), show(r.get("recorded")),
                      show(r.get("lower")), show(r.get("upper")), show(r.get("unaffected"), n=True))
    console.print(table)
    console.print("\nSibling-value answers (earlier / later sibling) and summaries written while probing:")
    disturbed = [(cell, c) for cell, c in report["cells"].items()
                 if c["earlier_sibling"] or c["later_sibling"] or c["summaries_during_probing"]]
    for cell, c in disturbed:
        console.print(f"  {cell}: {c['earlier_sibling']} / {c['later_sibling']}, {c['summaries_during_probing']} summaries")
    if not disturbed:
        console.print("  none")


async def _run_scaffold_audit(model_ids, only, threshold, seeds, questions, min_effect, db_path, budget, estimate_only):
    from datetime import datetime, timezone
    from pathlib import Path

    from app.catalog import PriceBook, load_prices
    from app.core import database as db
    from app.llm import default_model_factory
    from app.services import compaction_eval as ce
    from app.services import scaffold_audit as sa
    from app.services.arena import open_graph
    from app.services.graph import default_summarizer
    from app.services.recall import default_history_recall, default_recall_model

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db.DB_PATH = db_path
    scenarios = _audit_scenarios(seeds, questions)
    factory = ce.EvalModelFactory([f for sc in scenarios.values() for f in sc.facts], inner=default_model_factory(),
                                  scenarios=scenarios)
    # The recall the app itself attaches, built through the same function.
    recall = default_history_recall(factory)
    from app.api.models import SUMMARIZER_MODELS
    from app.llm.factory import has_credentials

    others = [m for m in SUMMARIZER_MODELS if m != default_summarizer() and has_credentials(m)]
    scaffolds = [s for s in sa.app_scaffolds(threshold, recall=recall, other_summarizers=others)
                 if not only or s.name in only]
    if not scaffolds:
        raise ValueError(f"no such scaffold; choose from {', '.join(s.name for s in sa.app_scaffolds(threshold))}")
    prices = PriceBook(load_prices(), datetime.now(timezone.utc).date().isoformat())
    prefix = "scaffold-audit-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    async with open_graph() as graph_app:
        run = await ce.run_budgeted(graph_app, scenarios, model_ids, sa.conditions_for(scaffolds), factory,
                                    prices=prices, budget=budget, estimate_only=estimate_only,
                                    sample_tokens=threshold, prefix=prefix,
                                    on_estimate=lambda e: _print_estimate(e, budget), factor=_planning_factor(),
                                    calibration_cache=_calibration_cache(), replay_cache=_replay_cache())
    if estimate_only:
        return {"estimate": round(run.estimate.total, 2), "high": round(run.estimate.high, 2)}
    records = sa.audit(run.results, scaffolds, model_ids, min_effect=min_effect)
    spend = ce.spend_summary(run, budget)
    if spend and spend["model_errors"]:
        failures = ce.write_failures(run.spend, _failures_path(prefix))
        raise ValueError(
            f"a model call failed, audit not recorded: {spend['model_errors'][0]}. "
            f"Spent ${spend['total']:.2f} of ${budget:.2f}."
            + (f" The failed request is saved in {failures}; inspect it there rather than sending it again."
               if failures else "")
        )
    # Every probe, so a verdict can be traced to the answers behind it.
    runs_dir = sa.DEFAULT_HISTORY.parent / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    setup = {"threshold": threshold, "seeds": seeds, "questions": questions}
    (runs_dir / f"{prefix}.json").write_text(json.dumps({"run": prefix, "setup": setup, "records": records, "spend": spend,
                                                         "probes": ce.results_as_dicts(run.results)},
                                                        ensure_ascii=False, indent=1))
    sa.append_history(records, {"run": prefix, "summarizer": default_summarizer(), "recall_model": default_recall_model(),
                                "threshold": threshold,
                                "seeds": seeds, "questions": questions, "cost": spend["total"] if spend else None})
    return {"run": prefix, "records": records, "spend": spend}


if __name__ == "__main__":
    app()
