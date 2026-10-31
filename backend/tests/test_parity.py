"""Everything the web UI can do to a conversation, the CLI and the MCP server can too.

PARITY names, for every HTTP route, WebSocket command and chat-frame field
the web UI uses, the CLI command (and option) and the MCP tool (and argument)
that do the same. The tests fail when a route, command or frame field has no
entry, or an entry names a command, option, tool or argument that doesn't
exist. A capability added to the web UI alone is a gap: the behaviour belongs
in services/, reachable from all three.

What the CLI and MCP do is tested in tests/test_cli_mcp.py and
tests/test_cli_mcp_features.py; this file only keeps the map complete.
"""

import pytest
import typer.main
from fastmcp import Client

from app.api.chat import ChatConnection
from app.api.debate import DebateConnection
from app.cli import app as cli_app
from app.services.context import ContextSettings

# Each entry: ((CLI command, option or None), (MCP tool, argument or None)).

# Web-only by nature: where nodes sit on the canvas.
UI_ONLY = {("POST", "/history/{thread_id}/positions")}
# Not offered over MCP: a key passed to a tool goes through the calling
# model's context. The CLI asks for it without echoing.
NOT_OVER_MCP = {("POST", "/config/keys")}

ROUTES: dict = {
    ("POST", "/chat"): (("chat", None), ("invoke_arena", None)),
    ("WS", "/ws/{thread_id}"): (("arena", None), ("invoke_arena", None)),
    ("GET", "/threads"): (("threads", None), ("list_threads", None)),
    ("PATCH", "/threads/{thread_id}/rename"): (("threads", "--rename"), ("rename_thread", None)),
    ("DELETE", "/threads/{thread_id}"): (("threads", "--delete"), ("delete_thread", None)),
    ("GET", "/history/{thread_id}"): (("tree", None), ("get_thread_tree", None)),
    ("DELETE", "/history/{thread_id}/checkpoints/{checkpoint_id}"): (("delete-branch", None), ("delete_branch", None)),
    ("GET", "/history/{thread_id}/search"): (("search", None), ("search_thread", None)),
    ("POST", "/upload"): (("upload", None), ("upload_document", None)),
    ("GET", "/models"): (("models", None), ("list_models", None)),
    ("GET", "/graph/{thread_id}/topology"): (("tree", None), ("get_thread_tree", None)),
    ("GET", "/graph/{thread_id}/path/{checkpoint_id}"): (("messages", "--at"), ("get_thread_messages", "checkpoint_id")),
    ("GET", "/config/keys"): (("keys", None), ("list_models", None)),
    ("POST", "/config/keys"): (("keys", "--set"), None),
    ("POST", "/debate/sessions"): (("debate", None), ("run_debate", None)),
    ("GET", "/debate/sessions"): (("debates list", None), ("list_debates", None)),
    ("GET", "/debate/sessions/{session_id}"): (("debates show", None), ("get_debate", None)),
    ("DELETE", "/debate/sessions/{session_id}"): (("debates delete", None), ("delete_debate", None)),
    ("GET", "/debate/sessions/{session_id}/tree"): (("debates show", None), ("get_debate", None)),
    ("WS", "/debate/ws/{session_id}"): (("debate", None), ("run_debate", None)),
}

# The debate socket's commands. A live control maps to running a debate in
# steps: pause = run fewer rounds, resume / inject = continue it; stop is
# Ctrl-C (CLI) or cancelling the call (MCP), which marks it interrupted.
DEBATE_COMMANDS: dict = {
    "debate_start": (("debate", None), ("run_debate", None)),
    "debate_redirect": (("debates redirect", None), ("redirect_debate", None)),
    "debate_inject": (("debates continue", "--inject"), ("continue_debate", "inject")),
    "debate_control": (("debates continue", "--rounds"), ("continue_debate", "rounds")),
    "debate_synthesize": (("synthesize", "--debate"), ("synthesize_debate", None)),
}

# What a chat frame can ask for, beyond a message and a model.
CHAT_FRAME: dict = {
    "parent_checkpoint_id": (("chat", "--from"), ("invoke_arena", "parent_checkpoint_id")),
    "is_deliberation": (("arena", "--deliberate"), ("invoke_arena", "deliberation")),
    "documents": (("arena", "--attach"), ("invoke_arena", "attachments")),
    "debate_session_id": (("chat", "--after-debate"), ("invoke_arena", "after_debate_session_id")),
    "answer_checkpoint_ids": (("synthesize", "--answers"), ("synthesize_answers", "checkpoint_ids")),
    "toggles.use_rag": (("arena", "--rag"), ("invoke_arena", "use_rag")),
    "toggles.use_web_search": (("arena", "--web-search"), ("invoke_arena", "use_web_search")),
    "summarizer": (("arena", "--summarizer"), ("invoke_arena", "summarizer")),
    "system_prompt": (("arena", "--system"), ("invoke_arena", "system_prompt")),
}
# Debates take the same per-run choices.
DEBATE_FRAME: dict = {
    "parent_checkpoint_id": (("debate", "--from"), ("run_debate", "parent_checkpoint_id")),
    "documents": (("debate", "--attach"), ("run_debate", "attachments")),
    "toggles.use_rag": (("debate", "--rag"), ("run_debate", "use_rag")),
    "toggles.use_web_search": (("debate", "--web-search"), ("run_debate", "use_web_search")),
    "summarizer": (("debate", "--summarizer"), ("run_debate", "summarizer")),
    "system_prompt": (("debate", "--system"), ("run_debate", "system_prompt")),
}


def _routes(routes):
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from _routes(inner.routes)
        elif hasattr(route, "path"):
            for method in sorted(getattr(route, "methods", None) or {"WS"}):
                if method != "HEAD":
                    yield method, route.path


def _app_routes():
    from app.main import server

    return {r for r in _routes(server.routes) if not r[1].startswith(("/docs", "/openapi", "/redoc"))}


def _cli_command(path: str):
    command = typer.main.get_command(cli_app)
    for name in path.split():
        command = command.commands[name]
    return command


def _entries():
    for table in (ROUTES, DEBATE_COMMANDS, CHAT_FRAME, DEBATE_FRAME):
        yield from table.values()


def test_every_route_has_a_cli_and_mcp_entry():
    missing = _app_routes() - set(ROUTES) - UI_ONLY
    assert not missing, f"Web routes with no CLI/MCP equivalent: {sorted(missing)}"
    stale = set(ROUTES) - _app_routes()
    assert not stale, f"PARITY lists routes that no longer exist: {sorted(stale)}"


def test_every_debate_command_has_an_entry():
    assert set(DEBATE_COMMANDS) == set(DebateConnection.COMMANDS)


def test_every_per_run_choice_has_an_entry():
    for field in ContextSettings.FRAME_FIELDS:
        assert field in CHAT_FRAME and field in DEBATE_FRAME, field


def test_only_listed_exceptions_skip_mcp():
    skipped = {key for key, (_cli, mcp) in ROUTES.items() if mcp is None}
    assert skipped == NOT_OVER_MCP


def test_chat_frame_fields_are_listed():
    """The chat socket's documented frame fields, from its docstring."""
    doc = ChatConnection.__doc__
    for field in ("parent_checkpoint_id", "is_deliberation", "documents", "debate_session_id", "answer_checkpoint_ids"):
        assert field in doc and field in CHAT_FRAME, field


def test_every_cli_entry_exists():
    for cli, _mcp in _entries():
        path, option = cli
        command = _cli_command(path)
        if option:
            options = {o for p in command.params for o in p.opts}
            assert option in options, f"crucible {path} has no {option}"


@pytest.mark.asyncio
async def test_every_mcp_entry_exists():
    from app.mcp_server import mcp

    async with Client(mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}
    for _cli, entry in _entries():
        if entry is None:
            continue
        name, argument = entry
        assert name in tools, f"no MCP tool {name}"
        if argument:
            assert argument in tools[name].input_schema["properties"], f"{name} has no {argument}"
