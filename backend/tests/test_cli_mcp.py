"""CLI and MCP against the real graph and a real SQLite checkpointer.

Only the LLM is faked (each model replies "reply from <id>"). These replace
tests that mocked the graph away, which is how a crash in every CLI command's
cleanup went unnoticed.
"""

import json
import os
from unittest.mock import patch

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from typer.testing import CliRunner

import app.services.graph as graph_mod
from app.cli import app as cli_app
from app.core import database as db

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B = "gpt-5.4", "claude-sonnet-5"


def _fake_model(model_id, *_a, **_kw):
    return FakeListChatModel(responses=[f"reply from {model_id}"])


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "cli.sqlite"))
    monkeypatch.setattr("app.cli._load_env", lambda: None)
    with patch.object(graph_mod, "get_model", side_effect=_fake_model), patch.dict(os.environ, KEYS):
        yield


runner = CliRunner()


def _json(args):
    result = runner.invoke(cli_app, args)
    assert result.exit_code == 0, (result.stdout, result.stderr, result.exception)
    return json.loads(result.stdout)


# ─── CLI ─────────────────────────────────────────────────────────


def test_arena_json_returns_every_answer_and_a_real_synthesis():
    out = _json(["arena", "Q?", "-m", A, "-m", B, "-t", "t-arena", "--format", "json"])
    assert out["answers"][A]["content"] == f"reply from {A}"
    assert out["answers"][B]["content"] == f"reply from {B}"
    assert out["answers"][A]["checkpoint_id"] != out["answers"][B]["checkpoint_id"]
    # Synthesis is its own call by the judge (default: first model).
    assert out["synthesis"]["model"] == A
    assert out["synthesis"]["checkpoint_id"] not in (
        out["answers"][A]["checkpoint_id"],
        out["answers"][B]["checkpoint_id"],
    )


def test_arena_no_synthesize_still_prints_json():
    out = _json(["arena", "Q?", "-m", A, "-m", B, "--no-synthesize", "--format", "json"])
    assert out["synthesis"] is None
    assert set(out["answers"]) == {A, B}


def test_arena_rich_output_exits_cleanly():
    result = runner.invoke(cli_app, ["arena", "Q?", "-m", A, "-m", B])
    assert result.exit_code == 0, result.exception


def test_arena_invalid_model_fails_with_message():
    result = runner.invoke(cli_app, ["arena", "Q?", "-m", "nope-1", "--format", "json"])
    assert result.exit_code == 1
    assert "nope-1" in result.stderr
    assert result.stdout == ""


def test_tree_renders_and_exits_zero():
    _json(["arena", "Q?", "-m", A, "-m", B, "-t", "t-tree", "--no-synthesize", "--format", "json"])
    result = runner.invoke(cli_app, ["tree", "-t", "t-tree"])
    assert result.exit_code == 0, result.exception
    assert "Q?" in result.stdout


def test_tree_unknown_thread_fails():
    assert runner.invoke(cli_app, ["tree", "-t", "missing"]).exit_code == 1


def test_synthesize_thread_combines_branch_answers():
    _json(["arena", "Q?", "-m", A, "-m", B, "-t", "t-syn", "--no-synthesize", "--format", "json"])
    out = _json(["synthesize", "-t", "t-syn", "-j", B, "--format", "json"])
    assert sorted(a["content"] for a in out["answers"].values()) == sorted([f"reply from {A}", f"reply from {B}"])
    assert out["synthesis"]["model"] == B
    assert out["synthesis"]["content"] == f"reply from {B}"


def test_synthesize_needs_two_answers():
    _json(["chat", "hi", "-m", A, "-t", "t-one", "--format", "json"])
    result = runner.invoke(cli_app, ["synthesize", "-t", "t-one", "--format", "json"])
    assert result.exit_code == 1
    assert "at least two" in result.stderr


def test_chat_json_and_continuation():
    first = _json(["chat", "one", "-m", A, "-t", "t-chat", "--format", "json"])
    second = _json(["chat", "two", "-m", A, "-t", "t-chat", "--format", "json"])
    assert first["content"] == second["content"] == f"reply from {A}"
    assert first["checkpoint_id"] != second["checkpoint_id"]


def test_deliberate_uses_the_debate_engine():
    out = _json(["deliberate", "Topic", "-m", A, "-m", B, "-r", "2", "--format", "json"])
    assert [r["round"] for r in out["rounds"]] == [0, 1]
    assert out["rounds"][1]["responses"] == {A: f"reply from {A}", B: f"reply from {B}"}
    assert out["synthesis"]["model"] == A
    session = db.get_debate_session(out["session_id"])
    assert session["status"] == "completed"
    assert session["parent_thread_id"] == out["thread_id"]


def test_synthesize_debate_recovers_question():
    out = _json(["deliberate", "Topic", "-m", A, "-m", B, "-r", "1", "--no-synthesize", "--format", "json"])
    syn = _json(["synthesize", "-d", out["session_id"], "-j", B, "--format", "json"])
    assert syn["synthesis"]["content"] == f"reply from {B}"


def test_threads_and_models_json():
    _json(["chat", "hi", "-m", A, "-t", "t-list", "--format", "json"])
    threads = _json(["threads", "--format", "json"])["threads"]
    assert {"id": "t-list", "title": "hi"} in threads
    models = _json(["models", "--format", "json"])["models"]
    assert any(m["id"] == A and m["key_available"] for m in models)


# ─── MCP ─────────────────────────────────────────────────────────


@pytest.fixture
def mcp_server():
    from app.mcp_server import mcp

    return mcp


@pytest.mark.asyncio
async def test_mcp_exposes_tools(mcp_server):
    async with Client(mcp_server) as client:
        names = {t.name for t in await client.list_tools()}
    assert {
        "list_models", "invoke_arena", "run_debate", "list_threads",
        "get_thread_messages", "get_branch_answers", "get_thread_summary", "get_thread_status",
    } <= names


@pytest.mark.asyncio
async def test_mcp_arena_returns_answers_and_branches_are_readable(mcp_server):
    async with Client(mcp_server) as client:
        res = (await client.call_tool("invoke_arena", {"prompt": "Q?", "models": [A, B], "thread_id": "m1"})).data
        assert res["answers"][B]["content"] == f"reply from {B}"
        assert res["synthesis"]["model"] == A

        branch = (await client.call_tool(
            "get_thread_messages", {"thread_id": "m1", "checkpoint_id": res["answers"][B]["checkpoint_id"]}
        )).data
        assert [m["content"] for m in branch["messages"]] == ["Q?", f"reply from {B}"]

        answers = (await client.call_tool("get_branch_answers", {"thread_id": "m1"})).data["answers"]
        # The synthesis branch is a tip too, but the fake gives it the same
        # text as gpt-5.4's answer and identical tips are deduplicated.
        assert {a["content"] for a in answers} == {f"reply from {A}", f"reply from {B}"}

        status = (await client.call_tool("get_thread_status", {"thread_id": "m1"})).data
        assert status["message_count"] >= 2


@pytest.mark.asyncio
async def test_mcp_errors_are_tool_errors(mcp_server):
    async with Client(mcp_server) as client:
        with pytest.raises(ToolError, match="nope-1"):
            await client.call_tool("invoke_arena", {"prompt": "Q?", "models": ["nope-1"]})
        with pytest.raises(ToolError, match="not found"):
            await client.call_tool("get_thread_status", {"thread_id": "missing"})
        with pytest.raises(ToolError, match="at least two"):
            await client.call_tool("run_debate", {"prompt": "Q?", "models": [A]})


@pytest.mark.asyncio
async def test_mcp_run_debate(mcp_server):
    async with Client(mcp_server) as client:
        res = (await client.call_tool(
            "run_debate", {"prompt": "Topic", "models": [A, B], "max_rounds": 2, "synthesizer": B}
        )).data
    assert len(res["rounds"]) == 2
    assert res["synthesis"]["content"] == f"reply from {B}"
    assert db.get_debate_session(res["session_id"])["status"] == "completed"
