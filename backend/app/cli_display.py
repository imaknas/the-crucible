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

console = Console()

# ─── Color Mapping (matching Web UI) ────────────────────────────

MODEL_COLORS: Dict[str, str] = {
    "openai": "green",
    "anthropic": "yellow",
    "google": "magenta",
}

FAMILY_ICONS: Dict[str, str] = {
    "openai": "🟢",
    "anthropic": "🟡",
    "google": "🟣",
}


def get_model_color(model_id: str) -> str:
    if "gpt" in model_id or "o1" in model_id or "o3" in model_id:
        return MODEL_COLORS["openai"]
    elif "claude" in model_id:
        return MODEL_COLORS["anthropic"]
    elif "gemini" in model_id:
        return MODEL_COLORS["google"]
    return "cyan"


def get_model_icon(model_id: str) -> str:
    if "gpt" in model_id or "o1" in model_id or "o3" in model_id:
        return FAMILY_ICONS["openai"]
    elif "claude" in model_id:
        return FAMILY_ICONS["anthropic"]
    elif "gemini" in model_id:
        return FAMILY_ICONS["google"]
    return "🔵"


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

    @property
    def all_finished(self) -> bool:
        return all(self.finished.values())


# ─── Deliberation Display ───────────────────────────────────────


class DeliberationDisplay:
    """Displays multi-round adversarial debate."""

    def __init__(self, models: List[str], rounds: int):
        self.models = models
        self.rounds = rounds
        self.current_round = 0
        self._live: Optional[Live] = None
        self.current_model = ""
        self.current_buffer = ""

    def start_round(self, round_num: int):
        self.current_round = round_num
        console.rule(
            f"[bold cyan]Round {round_num}/{self.rounds}[/bold cyan]",
            style="dim",
        )

    def start_model(self, model: str):
        self.current_model = model
        self.current_buffer = ""
        color = get_model_color(model)
        icon = get_model_icon(model)
        console.print(f"\n{icon} [bold {color}]{model}[/bold {color}]:")

        self._live = Live(
            Text("▌", style="dim"),
            console=console,
            refresh_per_second=8,
            transient=True,
        )
        self._live.__enter__()

    def update_token(self, token: str):
        self.current_buffer += token
        if self._live:
            self._live.update(Text(self.current_buffer + "▌"))

    def finish_model(self):
        if self._live:
            self._live.__exit__(None, None, None)
            self._live = None
        # Print the final content as markdown
        console.print(Markdown(self.current_buffer))
        self.current_buffer = ""


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

        label = node.get("data", {}).get("label", "?")
        role = node.get("metadata", {}).get("role", "")
        model = node.get("metadata", {}).get("active_peer", "")
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

        branch = parent_tree.add(Text(f"{label}{marker}", style=style))

        for child_id in child_map.get(node_id, []):
            _add_node(branch, child_id)

    for root_id in roots:
        _add_node(tree, root_id)

    console.print(tree)


# ─── Thread Listing ──────────────────────────────────────────────


def render_threads_table(threads: List[Dict[str, str]]) -> None:
    """Render a table of threads."""
    if not threads:
        console.print("[dim]No experiments found.[/dim]")
        return

    table = Table(title="🧪 Experiments", box=box.SIMPLE_HEAVY)
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Title", style="bold")

    for t in threads:
        table.add_row(t["id"], t.get("title", t["id"]))

    console.print(table)


# ─── Consensus / Synthesis Display ───────────────────────────────


def render_synthesis(content: str, judge_model: Optional[str] = None) -> None:
    """Render the final consensus panel."""
    title = "🔬 Consensus"
    if judge_model:
        icon = get_model_icon(judge_model)
        title = f"🔬 Consensus (Judge: {icon} {judge_model})"

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
    console.print(f"[bold green]✓[/bold green] {msg}")


def print_error(msg: str):
    console.print(f"[bold red]✗[/bold red] {msg}")


def print_info(msg: str):
    console.print(f"[bold blue]ℹ[/bold blue] {msg}")
