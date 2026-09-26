"""
The Crucible CLI — Multi-Model Reasoning Engine.

Usage:
    crucible arena "prompt" --models gpt-5.4 --models claude-sonnet-5
    crucible deliberate "topic" --models gpt-5.4 --models claude-sonnet-5 --rounds 3
    crucible synthesize --thread <id>          # or --debate <session_id>
    crucible chat "prompt" --model gpt-5.4
    crucible threads
    crucible tree --thread <id>
    crucible models

Every command that produces results takes ``--format json`` for scripting:
the JSON document is the only thing written to stdout, and failures exit
non-zero with the message on stderr.
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
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


def _validate_models(models: Optional[List[str]], as_json: bool) -> List[str]:
    from app.services.arena import resolve_models

    try:
        return resolve_models(models)
    except ValueError as e:
        _fail(str(e), as_json)
        return []  # unreachable


# ─── ARENA Command ───────────────────────────────────────────────


@app.command()
def arena(
    prompt: str = typer.Argument(..., help="The question to put to every model."),
    models: Optional[List[str]] = typer.Option(
        None, "--models", "-m", help="Model IDs to include (repeat the flag)."
    ),
    thread: Optional[str] = typer.Option(
        None, "--thread", "-t", help="Existing thread ID to continue."
    ),
    judge: Optional[str] = typer.Option(
        None, "--judge", "-j", help="Model that synthesizes the answers (default: the first model)."
    ),
    no_synthesize: bool = typer.Option(
        False, "--no-synthesize", help="Only collect the individual answers."
    ),
    web_search: bool = typer.Option(
        False, "--web-search", "-w", help="Enable web search grounding."
    ),
    format_output: str = typer.Option("rich", "--format", "-f", help=FORMAT_HELP),
):
    """
    [bold green]⚔️  Arena Mode[/bold green] — Multi-model parallel answers.

    Every model answers the same prompt independently (each on its own branch),
    then one model synthesizes the answers.
    """
    as_json = _check_format(format_output)
    _load_env()
    resolved = _validate_models(models, as_json)
    synthesizer = None if no_synthesize else (judge or resolved[0])
    if synthesizer:
        _validate_models([synthesizer], as_json)
    thread_id = thread or _gen_thread_id("arena")

    result = _run(
        _run_arena(prompt, resolved, thread_id, synthesizer, {"use_web_search": web_search}, as_json),
        as_json,
    )
    if as_json:
        _emit_json(result)
    if result["answers"] and all(a["error"] for a in result["answers"].values()):
        raise typer.Exit(1)


async def _run_arena(prompt, models, thread_id, synthesizer, toggles, as_json):
    from app.core import database as db
    from app.services.arena import open_graph, run_arena
    from app.cli_display import ArenaDisplay, print_header, print_info, print_success, print_error, render_synthesis

    result: Dict[str, Any] = {"thread_id": thread_id, "prompt": prompt, "answers": {}, "synthesis": None}
    display = None
    if not as_json:
        print_header()
        print_info(f"Thread: [dim]{thread_id}[/dim]")
        print_info(f"Models: {', '.join(models)}")
        console.print()
        display = ArenaDisplay(models)
        display.start()

    async with open_graph() as graph_app:
        is_new = not (await graph_app.aget_state({"configurable": {"thread_id": thread_id}})).values
        try:
            async for event in run_arena(graph_app, prompt, thread_id, models, toggles, synthesizer):
                kind = event["type"]
                if kind == "token" and display:
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

    if is_new:
        db.rename_thread(thread_id, f"Arena: {prompt[:40]}")
    if not as_json:
        print_success(f"Thread saved: {thread_id}")
    return result


# ─── DELIBERATE Command ─────────────────────────────────────────


@app.command()
def deliberate(
    prompt: str = typer.Argument(..., help="The topic for the debate."),
    models: Optional[List[str]] = typer.Option(
        None, "--models", "-m", help="Model IDs to debate (repeat the flag; at least two)."
    ),
    rounds: int = typer.Option(2, "--rounds", "-r", min=1, help="Maximum number of rounds."),
    judge: Optional[str] = typer.Option(
        None, "--judge", "-j", help="Model that writes the final synthesis (default: the first model)."
    ),
    no_synthesize: bool = typer.Option(False, "--no-synthesize", help="Skip the final synthesis."),
    threshold: Optional[float] = typer.Option(
        None, "--threshold", help="Stop early when round-over-round similarity reaches this (0-1)."
    ),
    mode: str = typer.Option("all", "--mode", help="Convergence mode: all or any model must converge."),
    convergence_judge: Optional[str] = typer.Option(
        None, "--convergence-judge", help="Model that judges whether the debate has converged."
    ),
    thread: Optional[str] = typer.Option(
        None, "--thread", "-t", help="Parent thread for the debate (default: a new one)."
    ),
    web_search: bool = typer.Option(
        False, "--web-search", "-w", help="Enable web search grounding."
    ),
    format_output: str = typer.Option("rich", "--format", "-f", help=FORMAT_HELP),
):
    """
    [bold yellow]🗣️  Deliberation Mode[/bold yellow] — Multi-round structured debate.

    Runs the same debate engine as the web UI: each model debates on its own
    branch, sees its peers' previous answers every round, and the debate can
    stop early on convergence. The session shows up in the web UI.
    """
    as_json = _check_format(format_output)
    _load_env()
    if mode not in ("all", "any"):
        raise typer.BadParameter("must be 'all' or 'any'", param_hint="--mode")
    resolved = _validate_models(models, as_json)
    if len(resolved) < 2:
        _fail("A debate needs at least two models with API keys.", as_json)
    synthesizer = None if no_synthesize else (judge or resolved[0])
    for extra in filter(None, [synthesizer, convergence_judge]):
        _validate_models([extra], as_json)

    policy = {
        "max_rounds": rounds,
        "convergence_threshold": threshold,
        "llm_judge": convergence_judge,
        "mode": mode,
    }
    result = _run(
        _run_deliberate(
            prompt, resolved, thread or _gen_thread_id("debate"), policy, synthesizer,
            {"use_web_search": web_search}, as_json,
        ),
        as_json,
    )
    if as_json:
        _emit_json(result)


async def _run_deliberate(prompt, models, thread_id, policy, synthesizer, toggles, as_json):
    from app.core import database as db
    from app.services import debate as debate_svc
    from app.services.arena import open_graph
    from app.cli_display import ArenaDisplay, print_header, print_info, print_success, print_error, render_synthesis

    async with open_graph() as graph_app:
        session = debate_svc.create_session(
            parent_thread_id=thread_id,
            participants=models,
            termination_policy=policy,
            auto_synthesize=bool(synthesizer),
            synthesizer_model=synthesizer,
        )
        session_id = session["session_id"]
        if not db.get_thread_title(thread_id):
            db.rename_thread(thread_id, f"Debate: {prompt[:40]}")

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
            print_info(f"Models: {', '.join(models)}  ·  up to {policy['max_rounds']} round(s)")

        display = None
        current: Optional[Dict[str, Any]] = None
        finished = False
        try:
            async for event in debate_svc.run_debate(graph_app, session_id, prompt, toggles, {}):
                kind = event["type"]
                if kind == "debate_round_start":
                    current = {"round": event["round"], "responses": {}, "errors": {}, "convergence_score": None}
                    result["rounds"].append(current)
                    if not as_json:
                        console.print()
                        console.rule(f"Round {event['round'] + 1}")
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
                        print_info(f"Convergence: {event['convergence_score']:.3f}")
                elif kind == "debate_converged":
                    result["converged"] = {k: event.get(k) for k in ("round", "score", "reason", "method")}
                    if not as_json:
                        print_success(f"Converged after round {event['round'] + 1} ({event.get('reason')})")
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

    if not as_json:
        console.print()
        print_success(f"Debate saved: {session_id} (thread {thread_id})")
    return result


# ─── SYNTHESIZE Command ─────────────────────────────────────────


@app.command()
def synthesize(
    thread: Optional[str] = typer.Option(None, "--thread", "-t", help="Thread whose branch answers to synthesize."),
    debate: Optional[str] = typer.Option(None, "--debate", "-d", help="Debate session to synthesize."),
    judge: Optional[str] = typer.Option(
        None, "--judge", "-j", help=f"Model that writes the synthesis (default: {DEFAULT_MODEL}, or the debate's own synthesizer)."
    ),
    format_output: str = typer.Option("rich", "--format", "-f", help=FORMAT_HELP),
):
    """
    [bold cyan]🔬 Synthesize[/bold cyan] — Combine existing answers into one.

    With --thread: the latest answer on every branch of the thread (e.g. each
    model's arena answer) is synthesized, and the result is added to the
    thread. With --debate: each participant's final answer is synthesized.
    """
    as_json = _check_format(format_output)
    _load_env()
    if bool(thread) == bool(debate):
        raise typer.BadParameter("pass exactly one of --thread or --debate")
    if judge:
        _validate_models([judge], as_json)

    if debate:
        result = _run(_run_synthesize_debate(debate, judge, as_json), as_json)
    else:
        result = _run(_run_synthesize_thread(thread, judge or DEFAULT_MODEL, as_json), as_json)
    if as_json:
        _emit_json(result)
    if not result.get("synthesis") or result["synthesis"].get("error"):
        raise typer.Exit(1)


async def _run_synthesize_thread(thread_id, judge, as_json):
    from app.services.arena import open_graph, synthesize_thread
    from app.cli_display import print_header, print_info, print_error, render_synthesis

    result: Dict[str, Any] = {"thread_id": thread_id, "answers": {}, "synthesis": None}
    if not as_json:
        print_header()
    async with open_graph() as graph_app:
        async for event in synthesize_thread(graph_app, thread_id, judge):
            if event["type"] == "end":
                result["answers"][event["checkpoint_id"]] = {"model": event["model"], "content": event["content"]}
            elif event["type"] == "synthesis_start" and not as_json:
                print_info(f"Synthesizing {len(result['answers'])} branch answers with {event['model']}…")
            elif event["type"] == "synthesis":
                result["synthesis"] = {k: event[k] for k in ("model", "content", "checkpoint_id", "error")}
                if not as_json:
                    if event["error"]:
                        print_error(f"Synthesis failed: {event['error']}")
                    else:
                        render_synthesis(event["content"], event["model"])
    return result


async def _run_synthesize_debate(session_id, judge, as_json):
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
        async for event in debate_svc.synthesize_session(graph_app, session_id, prompt="", synthesizer=judge):
            if event["type"] == "error":
                raise ValueError(event["message"])
            if event["type"] == "debate_synthesis_start" and not as_json:
                print_info(f"Synthesizing with {event['model']}…")
            elif event["type"] == "debate_synthesis_end":
                result["synthesis"] = {"model": event["model"], "content": event["content"], "checkpoint_id": event.get("checkpoint_id"), "error": None}
                if not as_json:
                    render_synthesis(event["content"], event["model"])
    return result


# ─── TREE Command ────────────────────────────────────────────────


@app.command()
def tree(
    thread: str = typer.Option(..., "--thread", "-t", help="Thread ID to visualize."),
    open_browser: bool = typer.Option(
        False, "--open", "-o", help="Open the thread in the web UI instead."
    ),
):
    """
    [bold magenta]🌳 Tree View[/bold magenta] — Inspect the reasoning tree.
    """
    _load_env()
    if open_browser:
        import webbrowser
        from urllib.parse import quote

        base = os.getenv("CRUCIBLE_WEB_URL", "http://localhost:3000").rstrip("/")
        webbrowser.open(f"{base}/?thread={quote(thread)}")
        from app.cli_display import print_success

        print_success("Opened in browser.")
        return

    _run(_render_tree(thread), False)


async def _render_tree(thread_id: str):
    from app.services.arena import open_graph
    from app.services.tree import build_history_tree, load_thread_states
    from app.cli_display import render_ascii_tree, print_header, print_info

    async with open_graph() as graph_app:
        all_states = await load_thread_states(graph_app, thread_id)
        if not all_states:
            raise ValueError(f"Thread {thread_id} not found.")
        active_state = await graph_app.aget_state({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
        tree_data = build_history_tree(thread_id, all_states, active_state)

    print_header()
    active_id = active_state.config.get("configurable", {}).get("checkpoint_id")
    print_info(f"Thread: {thread_id} ({len(tree_data['nodes'])} nodes)")
    console.print()
    render_ascii_tree(tree_data["nodes"], tree_data["edges"], active_id)


# ─── THREADS Command ────────────────────────────────────────────


@app.command()
def threads(
    rename: Optional[str] = typer.Option(None, "--rename", help="Thread ID to rename."),
    title: Optional[str] = typer.Option(
        None, "--title", help="New title (used with --rename)."
    ),
    delete: Optional[str] = typer.Option(None, "--delete", help="Thread ID to delete."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask before deleting."),
    format_output: str = typer.Option("rich", "--format", "-f", help=FORMAT_HELP),
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
        db.delete_thread_data(delete)
        print_success(f"Deleted {delete}")
        return

    thread_list = db.list_threads()
    if as_json:
        _emit_json({"threads": thread_list})
        return
    print_header()
    render_threads_table(thread_list)


# ─── MODELS Command ─────────────────────────────────────────────


@app.command()
def models(
    format_output: str = typer.Option("rich", "--format", "-f", help=FORMAT_HELP),
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


# ─── COMPACTION-EVAL Command ────────────────────────────────────


CHEAP_MODELS = ["gpt-5.4-nano", "claude-haiku-4-5-20251001", "gemini-3.5-flash-lite"]


@app.command("compaction-eval")
def compaction_eval(
    models: Optional[List[str]] = typer.Option(
        None, "--models", "-m",
        help=f"Models that answer the probes (default: {', '.join(CHEAP_MODELS)}). 'oracle' answers iff the value is still in context.",
    ),
    thresholds: Optional[List[int]] = typer.Option(
        None, "--threshold", "-t", help="Compaction thresholds in tokens (repeat). Default: 6000 (dense), 2000 and 4000 (basic)."
    ),
    summarizers: Optional[List[str]] = typer.Option(
        None, "--summarizer", "-s", help="Summarizer models to compare (repeat); one condition per threshold and summarizer. Default: the app's. Gemini takes a thinking level: gemini-3.5-flash@minimal."
    ),
    scenario: str = typer.Option("dense", "--scenario", help="dense: specifics everywhere, distractors and updates. basic: pilot 1's generic filler."),
    facts: int = typer.Option(24, "--facts", help="Planted facts per scenario (dense only)."),
    seeds: int = typer.Option(3, "--seeds", help="Number of scenarios (different filler and ordering)."),
    exchanges: Optional[int] = typer.Option(None, "--exchanges", help="User/assistant pairs per scenario. Default: 140 (dense), 40 (basic)."),
    compaction: str = typer.Option("live", "--compaction", help="live: summarize turn by turn as the conversation grows. once: one summary when probing starts."),
    baseline: bool = typer.Option(True, "--baseline/--no-baseline", help="Include the never-compact condition (the costliest: every probe reads the full history)."),
    oracle: bool = typer.Option(True, "--oracle/--no-oracle", help="Also probe the availability oracle (no API cost beyond shared live summaries)."),
    min_effect: float = typer.Option(0.1, "--min-effect", help="Smallest recall difference that matters (0.1 = 10 points)."),
    concurrency: int = typer.Option(4, "--concurrency", help="Branches run in parallel."),
    db: str = typer.Option("experiments/compaction.sqlite", "--db", help="Separate database for experiment threads."),
    out: Optional[str] = typer.Option(None, "--out", help="Write every probe result as JSON here."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Only the oracle answers, with a lossy stand-in summarizer; no API calls."),
    format_output: str = typer.Option("rich", "--format", "-f", help=FORMAT_HELP),
):
    """
    [bold]🧪 Compaction eval[/bold] — How much planted detail survives summarization?

    Every condition (never compact, and each threshold × summarizer) answers
    the same probes on the same conversation. Real runs call the chosen
    models; results include raw token usage.
    """
    from app.services.compaction_eval import ORACLE

    as_json = _check_format(format_output)
    _load_env()
    if scenario not in ("dense", "basic") or compaction not in ("live", "once"):
        _fail("--scenario is dense|basic and --compaction is live|once", as_json)
    model_ids = [ORACLE] if dry_run else list(models or CHEAP_MODELS)
    if oracle and ORACLE not in model_ids:
        model_ids.append(ORACLE)
    if not dry_run:
        from app.services.compaction_eval import split_thinking

        try:
            bases = [split_thinking(s)[0] for s in summarizers or []]
        except ValueError as e:
            _fail(str(e), as_json)
        _validate_models([m for m in model_ids if m != ORACLE] + bases, as_json)
    options = {
        "scenario": scenario,
        "facts": facts,
        "seeds": seeds,
        "exchanges": exchanges or (140 if scenario == "dense" else 40),
        "thresholds": thresholds or ([6000] if scenario == "dense" else [2000, 4000]),
        "summarizers": list(summarizers or []),
        "compaction": compaction,
        "baseline": baseline,
        "concurrency": concurrency,
    }
    result = _run(_run_compaction_eval(model_ids, options, min_effect, db, out, dry_run), as_json)
    if as_json:
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
    if out:
        console.print(f"Wrote {out}")


async def _run_compaction_eval(model_ids, options, min_effect, db_path, out, dry_run):
    from datetime import datetime, timezone
    from itertools import combinations
    from pathlib import Path

    from app.compaction import NeverCompact, ThresholdPolicy, build_dense_scenario, build_scenario, fixed_tokens
    from app.core import database as db
    from app.llm import default_model_factory
    from app.services import compaction_eval as ce
    from app.services.arena import open_graph

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db.DB_PATH = db_path  # experiment threads never touch the app's database
    if options["scenario"] == "dense":
        scenarios = {str(s): build_dense_scenario(n_facts=options["facts"], exchanges=options["exchanges"], seed=s)
                     for s in range(options["seeds"])}
    else:
        scenarios = {str(s): build_scenario(exchanges=options["exchanges"], seed=s) for s in range(options["seeds"])}
    conditions = [ce.Condition("never", NeverCompact())] if options["baseline"] else []
    for t in options["thresholds"]:
        for summarizer in options["summarizers"] or [None]:
            name = f"t{t}" + (f"-{summarizer}" if summarizer else "")
            conditions.append(ce.Condition(name, ThresholdPolicy(fixed_tokens(t), name=name), summarizer))
    all_facts = [f for sc in scenarios.values() for f in sc.facts]
    factory = ce.EvalModelFactory(all_facts, inner=None if dry_run else default_model_factory())

    prefix = "compaction-eval-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    grid = ce.run_live_grid if options["compaction"] == "live" else ce.run_grid
    async with open_graph() as graph_app:
        results = await grid(graph_app, scenarios, model_ids, conditions, thread_prefix=prefix,
                             model_factory=factory, concurrency=options["concurrency"])

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
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps({**summary, "probes": ce.results_as_dicts(results)}, ensure_ascii=False, indent=1))
    return summary


# ─── CHAT Command ────────────────────────────────────────────────


@app.command()
def chat(
    prompt: Optional[str] = typer.Argument(
        None, help="The message to send (or pipe via stdin)."
    ),
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m", help="Model ID to use."),
    thread: Optional[str] = typer.Option(
        None, "--thread", "-t", help="Existing thread to continue."
    ),
    web_search: bool = typer.Option(
        False, "--web-search", "-w", help="Enable web search."
    ),
    format_output: str = typer.Option("rich", "--format", "-f", help=FORMAT_HELP),
):
    """
    [bold green]💬 Chat Mode[/bold green] — Single-model turn.

    Supports stdin piping: echo "question" | crucible chat --model gpt-5.4
    """
    as_json = _check_format(format_output)
    _load_env()

    if prompt is None:
        if not sys.stdin.isatty():
            prompt = sys.stdin.read().strip()
        if not prompt:
            _fail("No prompt provided. Pass a message or pipe via stdin.", as_json)

    _validate_models([model], as_json)
    thread_id = thread or _gen_thread_id("chat")
    result = _run(_run_chat(prompt, model, thread_id, {"use_web_search": web_search}, as_json), as_json)
    if as_json:
        _emit_json(result)


async def _run_chat(prompt: str, model: str, thread_id: str, toggles, as_json: bool):
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.text import Text

    from app.core import database as db
    from app.services.arena import open_graph, stream_run
    from app.services.runs import resolve_fork_point_ex
    from app.cli_display import print_info, print_success, get_model_color, get_model_icon

    live = None
    if not as_json:
        color = get_model_color(model)
        print_info(f"Thread: [dim]{thread_id}[/dim]")
        console.print(f"\n{get_model_icon(model)} [bold {color}]{model}[/bold {color}]:\n")
        live = Live(Text("▌", style="dim"), console=console, refresh_per_second=8, transient=True)
        live.__enter__()

    result: Dict[str, Any] = {"thread_id": thread_id, "model": model}
    buffer = ""
    try:
        async with open_graph() as graph_app:
            parent, is_new = await resolve_fork_point_ex(graph_app, thread_id)
            async for event in stream_run(graph_app, thread_id, parent, model, prompt, toggles):
                if event["type"] == "token":
                    buffer += event["token"]
                    if live:
                        live.update(Text(buffer + "▌"))
                else:
                    result["content"] = event["content"]
                    result["checkpoint_id"] = event["checkpoint_id"]
    finally:
        if live:
            live.__exit__(None, None, None)

    if is_new:
        db.rename_thread(thread_id, prompt.strip().split("\n")[0][:40])
    if not as_json:
        console.print(Markdown(result.get("content", buffer)))
        print_success(f"Thread saved: {thread_id}")
    return result


if __name__ == "__main__":
    app()
