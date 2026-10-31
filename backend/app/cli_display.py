"""
Rich-powered terminal display for The Crucible CLI.
Handles colored model panels, streaming output, and tree visualization.
"""

from typing import Dict, Optional, List, Any
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.columns import Columns
from rich.markdown import Markdown
from rich.text import Text
from rich.tree import Tree as RichTree
from rich.table import Table
from rich.spinner import Spinner
from rich import box
from rich.markup import escape

from app.registry import model_color

console = Console()

# ─── Colours: the family's, as the web UI draws it ─────────────


def get_model_color(model_id: str) -> str:
    return model_color(model_id, default="cyan")


def get_model_icon(model_id: str) -> str:
    return f"[{get_model_color(model_id)}]●[/]"


# ─── Streaming Arena Display ───────────────────────────────────


class ArenaDisplay:
    """Manages live multi-panel streaming display for arena mode."""

    def __init__(self, models: List[str]):
        self.models = models
        self.buffers: Dict[str, str] = {m: "" for m in models}
        self.finished: Dict[str, bool] = {m: False for m in models}
        self._live: Optional[Live] = None

    def _build_layout(self) -> Columns:
        panels = []
        for model in self.models:
            color = get_model_color(model)
            icon = get_model_icon(model)
            content = self.buffers[model]

            if not content and not self.finished[model]:
                panel_content = Spinner("dots", text="Thinking...")
            else:
                panel_content = Text(content) if content else Text("(no response)")

            panel = Panel(
                panel_content,
                title=f"{icon} {model}",
                border_style=color,
                box=box.ROUNDED,
                expand=True,
            )
            panels.append(panel)

        return Columns(panels, equal=True, expand=True)

    def start(self):
        self._live = Live(
            self._build_layout(),
            console=console,
            refresh_per_second=8,
            transient=False,
        )
        self._live.__enter__()

    def update_token(self, model: str, token: str):
        if model in self.buffers:
            self.buffers[model] += token
            if self._live:
                self._live.update(self._build_layout())

    def finish_model(self, model: str):
        self.finished[model] = True
        if self._live:
            self._live.update(self._build_layout())

    def stop(self):
        if self._live:
            self._live.__exit__(None, None, None)
            self._live = None
            # The live panel ends without a newline; the next line would
            # otherwise start on its bottom border.
            console.line()

    @property
    def all_finished(self) -> bool:
        return all(self.finished.values())


class ReplyDisplay:
    """One model's reply, as `crucible chat` shows it: the raw text while it
    streams, then rendered Markdown. Same methods as ArenaDisplay."""

    def __init__(self, model: str):
        self.model = model
        self.buffer = ""
        self._live: Optional[Live] = None

    def start(self):
        color = get_model_color(self.model)
        console.print(f"{get_model_icon(self.model)} [bold {color}]{self.model}[/bold {color}]:\n")
        self._live = Live(Text("▌", style="dim"), console=console, refresh_per_second=8, transient=True)
        self._live.__enter__()

    def update_token(self, model: str, token: str):
        self.buffer += token
        if self._live:
            self._live.update(Text(self.buffer + "▌"))

    def finish_model(self, model: str):
        pass

    def stop(self):
        if self._live:
            self._live.__exit__(None, None, None)
            self._live = None
            console.print(Markdown(self.buffer))


# ─── Tree Rendering ─────────────────────────────────────────────


def render_ascii_tree(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    active_id: Optional[str] = None,
) -> None:
    """Render a history tree as an ASCII tree in the terminal."""
    if not nodes:
        console.print("[dim]No nodes in this thread.[/dim]")
        return

    # Build adjacency
    child_map: Dict[str, List[str]] = {}
    parents: set = set()
    for edge in edges:
        src, tgt = edge["source"], edge["target"]
        child_map.setdefault(src, []).append(tgt)
        parents.add(src)

    node_map = {n["id"]: n for n in nodes}

    # Find roots (nodes that are never a target)
    all_targets = {e["target"] for e in edges}
    roots = [n["id"] for n in nodes if n["id"] not in all_targets]

    if not roots:
        roots = [nodes[0]["id"]]

    tree = RichTree("🌳 [bold]Reasoning Tree[/bold]")

    def _add_node(parent_tree, node_id: str):
        node = node_map.get(node_id)
        if not node:
            return

        meta = node.get("metadata", {})
        # The text as written: the canvas label drops markdown and brackets.
        excerpt = (meta.get("excerpt") or node.get("data", {}).get("label", "?")).strip().splitlines()
        label = excerpt[0][:60] + ("…" if len(excerpt[0]) > 60 or len(excerpt) > 1 else "") if excerpt else "(empty)"
        role = meta.get("role", "")
        model = meta.get("active_peer", "")
        kind = meta.get("kind")
        is_active = node_id == active_id

        # Style
        if is_active:
            style = "bold white on blue"
            marker = " ← active"
        elif role == "user":
            style = "cyan"
            marker = ""
        else:
            color = get_model_color(model) if model else "white"
            style = color
            marker = f" [{model}]" if model else ""
        if kind:
            marker += f" ({kind})"

        # The checkpoint id is what --from, delete-branch and synthesize
        # --answers take.
        text = Text(f"{label}{marker}", style=style)
        text.append(f"  {node_id}", style="dim")
        branch = parent_tree.add(text)

        for child_id in child_map.get(node_id, []):
            _add_node(branch, child_id)

    for root_id in roots:
        _add_node(tree, root_id)

    console.print(tree)


# ─── Thread Listing ──────────────────────────────────────────────


def render_threads_table(threads: List[Dict[str, str]]) -> None:
    """Render a table of threads, most recently active first."""
    if not threads:
        console.print("[dim]No threads yet.[/dim]")
        return

    table = Table(title="🧪 Threads", box=box.SIMPLE_HEAVY)
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Title", style="bold")
    table.add_column("Last active", style="dim", no_wrap=True)

    for t in threads:
        # Text cells: a title like "list[int]" is not markup.
        updated = (t.get("updated_at") or "").replace("T", " ")[:16]
        table.add_row(Text(t["id"]), Text(t.get("title") or t["id"]), updated)

    console.print(table)


# ─── Consensus / Synthesis Display ───────────────────────────────


def render_synthesis(content: str, judge_model: Optional[str] = None, kind: str = "Synthesis") -> None:
    """Render a synthesis panel: of independent answers ("Synthesis"), or a
    debate's "Argument map", which maps positions and never declares a
    consensus."""
    title = f"🔬 {kind}"
    if judge_model:
        icon = get_model_icon(judge_model)
        title = f"🔬 {kind} (by {icon} {judge_model})"

    console.print()
    console.print(
        Panel(
            Markdown(content),
            title=title,
            border_style="bold cyan",
            box=box.DOUBLE,
            padding=(1, 2),
        )
    )


# ─── Simple Helpers ──────────────────────────────────────────────


def print_header():
    console.print()
    console.print(
        Panel(
            "[bold]THE CRUCIBLE[/bold]\n[dim]Multi-Model Reasoning Engine[/dim]",
            style="bold blue",
            box=box.DOUBLE_EDGE,
            expand=False,
        )
    )
    console.print()


def print_success(msg: str):
    """``msg`` is plain text (user and model text included), not markup."""
    console.print(f"[bold green]✓[/bold green] {escape(msg)}")


def print_error(msg: str):
    """``msg`` is plain text (user and model text included), not markup."""
    console.print(f"[bold red]✗[/bold red] {escape(msg)}")


def print_info(msg: str):
    console.print(f"[bold blue]ℹ[/bold blue] {msg}")
