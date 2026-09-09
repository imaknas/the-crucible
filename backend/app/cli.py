"""
The Crucible CLI — Multi-Model Reasoning Engine.

Usage:
    crucible arena "prompt" --models gpt-5.4 claude-sonnet-5 gemini-3.1-pro-preview
    crucible deliberate "topic" --models gpt-5.4 claude-sonnet-5 --rounds 3
    crucible chat "prompt" --model gpt-5.4
    crucible threads
    crucible tree --thread <id>
"""

import asyncio
import sys
from typing import List, Optional
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


# ─── Shared Utilities ────────────────────────────────────────────


def _load_env():
    """Load .env for API keys."""
    from dotenv import load_dotenv

    load_dotenv()


async def _get_graph():
    """Get a compiled graph with persistent checkpointer. Caller must call saver.__aexit__ in a finally block."""
    from app.services.graph import workflow
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from app.core import database as db

    ctx = AsyncSqliteSaver.from_conn_string(db.DB_PATH)
    saver = await ctx.__aenter__()
    try:
        return workflow.compile(checkpointer=saver), saver
    except Exception:
        await ctx.__aexit__(*__import__("sys").exc_info())
        raise


def _gen_thread_id(prefix: str = "cli") -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


def _parse_models(models: Optional[List[str]]) -> List[str]:
    """Validate and return models, or use defaults."""
    from app.api.models import MODEL_REGISTRY

    if not models:
        return []  # Will use service-layer defaults

    invalid = [m for m in models if m not in MODEL_REGISTRY]
    if invalid:
        from app.cli_display import print_error

        print_error(f"Invalid model(s): {', '.join(invalid)}")
        available = ", ".join(MODEL_REGISTRY.keys())
        console.print(f"[dim]Available: {available}[/dim]")
        raise typer.Exit(1)
    return models


# ─── ARENA Command ───────────────────────────────────────────────


@app.command()
def arena(
    prompt: str = typer.Argument(
        ..., help="The research question or topic to deliberate."
    ),
    models: Optional[List[str]] = typer.Option(
        None, "--models", "-m", help="Model IDs to include in the arena."
    ),
    thread: Optional[str] = typer.Option(
        None, "--thread", "-t", help="Existing thread ID to continue."
    ),
    web_search: bool = typer.Option(
        False, "--web-search", "-w", help="Enable web search grounding."
    ),
    format_output: str = typer.Option(
        "rich", "--format", "-f", help="Output format: rich or json."
    ),
):
    """
    [bold green]⚔️  Arena Mode[/bold green] — Multi-model parallel deliberation.

    Sends the prompt to multiple models simultaneously and synthesizes a consensus.
    """
    _load_env()
    from app.cli_display import print_header, print_info

    validated_models = _parse_models(models)
    thread_id = thread or _gen_thread_id("arena")

    if format_output == "rich":
        print_header()
        print_info(f"Thread: [dim]{thread_id}[/dim]")

    asyncio.run(
        _run_arena(prompt, validated_models, thread_id, web_search, format_output)
    )


async def _run_arena(
    prompt: str,
    models: List[str],
    thread_id: str,
    web_search: bool,
    format_output: str,
):
    from app.services.graph import run_arena_streaming
    from app.core import database as db
    from app.cli_display import (
        ArenaDisplay,
        render_synthesis,
        print_success,
        print_info,
    )
    import json

    graph_app, saver = await _get_graph()

    try:
        overrides = {"use_web_search": web_search}

        # Resolve models for display
        actual_models = models
        if not actual_models:
            from app.services.graph import _resolve_arena_models

            actual_models = _resolve_arena_models(models)

        if format_output == "rich":
            print_info(f"Models: {', '.join(actual_models)}")
            console.print()
            display = ArenaDisplay(actual_models)
            display.start()
        else:
            display = None

        results = {}
        async for event in run_arena_streaming(
            graph_app, prompt, thread_id, models=models, overrides=overrides
        ):
            model = event.get("model", "")
            etype = event.get("type", "")

            if etype == "token" and display:
                display.update_token(model, event.get("token", ""))
            elif etype == "end":
                if display:
                    display.finish_model(model)
                results[model] = event.get("content", "")
            elif etype == "synthesis":
                if display:
                    display.stop()
                    render_synthesis(event.get("content", ""))
                else:
                    # JSON mode
                    output = {
                        "thread_id": thread_id,
                        "models": results,
                        "synthesis": event.get("content", ""),
                    }
                    console.print(json.dumps(output, ensure_ascii=False, indent=2))

        if display:
            display.stop()

        # Auto-title the thread
        db.rename_thread(thread_id, f"Arena: {prompt[:40]}...")
        if format_output == "rich":
            print_success(f"Thread saved: {thread_id}")
    finally:
        await saver.__aexit__(None, None, None)


# ─── DELIBERATE Command ─────────────────────────────────────────


@app.command()
def deliberate(
    prompt: str = typer.Argument(..., help="The topic for adversarial debate."),
    models: Optional[List[str]] = typer.Option(
        None, "--models", "-m", help="Model IDs to debate."
    ),
    rounds: int = typer.Option(2, "--rounds", "-r", help="Number of debate rounds."),
    judge: Optional[str] = typer.Option(
        None, "--judge", "-j", help="Model ID to synthesize the final verdict."
    ),
    web_search: bool = typer.Option(
        False, "--web-search", "-w", help="Enable web search grounding."
    ),
):
    """
    [bold yellow]🗣️  Deliberation Mode[/bold yellow] — Multi-round adversarial debate.

    Models debate the topic across multiple rounds, responding to each other's arguments.
    """
    _load_env()
    validated_models = _parse_models(models)
    thread_id = _gen_thread_id("debate")

    from app.cli_display import print_header, print_info

    print_header()
    print_info(f"Thread: [dim]{thread_id}[/dim]")
    print_info(f"Rounds: {rounds}")

    asyncio.run(
        _run_deliberate(prompt, validated_models, thread_id, rounds, judge, web_search)
    )


async def _run_deliberate(
    prompt: str,
    models: List[str],
    thread_id: str,
    rounds: int,
    judge: Optional[str],
    web_search: bool,
):
    from app.services.graph import run_deliberation
    from app.core import database as db
    from app.cli_display import (
        DeliberationDisplay,
        render_synthesis,
        print_success,
        print_info,
    )

    graph_app, saver = await _get_graph()

    try:
        overrides = {"use_web_search": web_search}

        # Resolve models
        if not models:
            from app.services.graph import _resolve_arena_models

            models = _resolve_arena_models(None)

        print_info(f"Models: {', '.join(models)}")
        console.print()

        display = DeliberationDisplay(models, rounds)

        async for event in run_deliberation(
            graph_app,
            prompt,
            thread_id,
            models=models,
            rounds=rounds,
            judge=judge,
            overrides=overrides,
        ):
            etype = event.get("type", "")
            if etype == "round_start":
                display.start_round(event["round"])
            elif etype == "model_start":
                display.start_model(event["model"])
            elif etype == "token":
                display.update_token(event.get("token", ""))
            elif etype == "model_end":
                display.finish_model()
            elif etype == "synthesis":
                render_synthesis(event.get("content", ""), judge)

        db.rename_thread(thread_id, f"Debate: {prompt[:40]}...")
        print_success(f"Thread saved: {thread_id}")
    finally:
        await saver.__aexit__(None, None, None)


# ─── SYNTHESIZE Command ─────────────────────────────────────────


@app.command()
def synthesize(
    thread: str = typer.Option(..., "--thread", "-t", help="Thread ID to synthesize."),
    judge: Optional[str] = typer.Option(
        None, "--judge", "-j", help="Model to use as judge for synthesis."
    ),
):
    """
    [bold cyan]🔬 Synthesize[/bold cyan] — Generate consensus from an existing thread.
    """
    _load_env()
    asyncio.run(_run_synthesize(thread, judge))


async def _run_synthesize(thread_id: str, judge: Optional[str]):
    from app.cli_display import render_synthesis, print_info, print_header

    print_header()

    graph_app, saver = await _get_graph()
    try:
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        state = await graph_app.aget_state(config)

        if not state.values:
            from app.cli_display import print_error

            print_error(f"Thread {thread_id} not found.")
            raise typer.Exit(1)

        thesis = state.values.get("current_thesis", "")
        if thesis:
            print_info("Current thesis found in thread state:")
            render_synthesis(thesis, judge)
        else:
            from app.cli_display import print_error

            print_error(
                "No thesis found in this thread. Run 'arena' or 'deliberate' first."
            )
    finally:
        await saver.__aexit__(None, None, None)


# ─── TREE Command ────────────────────────────────────────────────


@app.command()
def tree(
    thread: str = typer.Option(..., "--thread", "-t", help="Thread ID to visualize."),
    open_browser: bool = typer.Option(
        False, "--open", "-o", help="Open in browser (Web UI)."
    ),
):
    """
    [bold magenta]🌳 Tree View[/bold magenta] — Inspect the reasoning tree.
    """
    _load_env()
    if open_browser:
        import webbrowser

        webbrowser.open(f"http://localhost:3000?thread={thread}")
        from app.cli_display import print_success

        print_success("Opened in browser.")
        return

    asyncio.run(_render_tree(thread))


async def _render_tree(thread_id: str):
    from app.core import database as db
    from app.services.tree import build_history_tree
    from app.cli_display import render_ascii_tree, print_header, print_info

    print_header()

    graph_app, saver = await _get_graph()
    try:
        raw_graph = db.get_thread_checkpoint_graph(thread_id)
        all_checkpoint_ids = [row[0] for row in raw_graph]

        if not all_checkpoint_ids:
            from app.cli_display import print_error

            print_error(f"Thread {thread_id} not found.")
            raise typer.Exit(1)

        all_states = []
        for cid in all_checkpoint_ids:
            cfg = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_id": cid,
                    "checkpoint_ns": "",
                }
            }
            state = await graph_app.aget_state(cfg)
            if state and state.values:
                all_states.append(state)

        active_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        active_state = await graph_app.aget_state(active_config)

        tree_data = build_history_tree(thread_id, all_states, active_state)

        active_id = active_state.config.get("configurable", {}).get("checkpoint_id")
        print_info(f"Thread: {thread_id} ({len(tree_data['nodes'])} nodes)")
        console.print()
        render_ascii_tree(tree_data["nodes"], tree_data["edges"], active_id)
    finally:
        await saver.__aexit__(None, None, None)


# ─── THREADS Command ────────────────────────────────────────────


@app.command()
def threads(
    rename: Optional[str] = typer.Option(None, "--rename", help="Thread ID to rename."),
    title: Optional[str] = typer.Option(
        None, "--title", help="New title (used with --rename)."
    ),
    delete: Optional[str] = typer.Option(None, "--delete", help="Thread ID to delete."),
):
    """
    [bold]🧪 Threads[/bold] — List, rename, or delete experiments.
    """
    _load_env()
    from app.core import database as db
    from app.cli_display import (
        render_threads_table,
        print_success,
        print_header,
    )

    if rename and title:
        db.rename_thread(rename, title)
        print_success(f"Renamed {rename} → {title}")
        return

    if delete:
        if not typer.confirm(f"Delete thread {delete}? This cannot be undone."):
            return
        db.delete_thread_data(delete)
        print_success(f"Deleted {delete}")
        return

    # Default: list all threads
    print_header()
    thread_list = db.list_threads()
    render_threads_table(thread_list)


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
):
    """
    [bold green]💬 Chat Mode[/bold green] — Single-model interactive session.

    Supports stdin piping: echo "question" | crucible chat --model gpt-5.4
    """
    _load_env()

    # Handle stdin piping
    if prompt is None:
        if not sys.stdin.isatty():
            prompt = sys.stdin.read().strip()
        if not prompt:
            console.print(
                "[red]No prompt provided. Pass a message or pipe via stdin.[/red]"
            )
            raise typer.Exit(1)

    _parse_models([model])  # Validate model exists
    thread_id = thread or _gen_thread_id("chat")

    asyncio.run(_run_chat(prompt, model, thread_id, web_search))


async def _run_chat(prompt: str, model: str, thread_id: str, web_search: bool):
    from app.utils.helpers import extract_text
    from app.cli_display import print_info, get_model_color, get_model_icon

    graph_app, saver = await _get_graph()

    try:
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        state = await graph_app.aget_state(config)

        initial_state = {
            "active_peer": model,
            "messages": [("user", prompt)],
            "toggles": {"use_web_search": web_search},
        }
        if not state.values:
            initial_state.update({"current_thesis": "", "branch_name": "main"})

        color = get_model_color(model)
        icon = get_model_icon(model)
        print_info(f"Thread: [dim]{thread_id}[/dim]")
        console.print(f"\n{icon} [bold {color}]{model}[/bold {color}]:\n")

        from rich.live import Live
        from rich.text import Text

        buffer = ""
        live = Live(
            Text("▌", style="dim"),
            console=console,
            refresh_per_second=8,
            transient=True,
        )
        live.__enter__()

        try:
            async for event in graph_app.astream_events(
                initial_state, config, version="v2"
            ):
                kind = event.get("event")
                if kind == "on_chat_model_stream":
                    node_name = event.get("metadata", {}).get("langgraph_node", "")
                    if node_name != "draft":
                        continue
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        token = extract_text(chunk.content)
                        if token:
                            buffer += token
                            live.update(Text(buffer + "▌"))
        finally:
            live.__exit__(None, None, None)

        # Print final content as markdown
        from rich.markdown import Markdown

        console.print(Markdown(buffer))

        from app.cli_display import print_success

        print_success(f"Thread saved: {thread_id}")
    finally:
        await saver.__aexit__(None, None, None)


if __name__ == "__main__":
    app()
