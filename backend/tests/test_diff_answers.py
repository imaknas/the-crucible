"""Diffing two replies: history.diff_answers, `crucible diff` and the MCP
diff_answers tool, against the real graph with only the LLM faked (as in
tests/test_cli_mcp.py)."""

import json
import os
from unittest.mock import patch

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from typer.testing import CliRunner

from app.cli import app as cli_app
from app.llm import CallableModelFactory, use_model_factory
from tests.storage_helpers import point

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B = "gpt-5.4", "claude-sonnet-5"
REPLIES = {
    A: "Paris is the capital of France. It sits on the Seine. Its museums are famous.",
    B: "Paris is the capital of France. It sits on the river Seine. Lyon is the second city.",
}

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    point(monkeypatch, db_path=str(tmp_path / "diff.sqlite"))
    monkeypatch.setattr("app.cli._load_env", lambda: None)
    factory = CallableModelFactory(lambda model_id, _toggles: FakeListChatModel(responses=[REPLIES[model_id]]))
    with use_model_factory(factory), patch.dict(os.environ, KEYS):
        yield


def _json(args):
    result = runner.invoke(cli_app, args)
    assert result.exit_code == 0, (result.stdout, result.stderr, result.exception)
    return json.loads(result.stdout)


def _arena(thread):
    out = _json(["arena", "Where is Paris?", "-m", A, "-m", B, "-t", thread, "--no-synthesize", "--format", "json"])
    return out["answers"][A]["checkpoint_id"], out["answers"][B]["checkpoint_id"]


def test_cli_diff_json_compares_two_answers_sentence_by_sentence():
    a, b = _arena("t-diff")
    out = _json(["diff", a, b, "-t", "t-diff", "--format", "json"])
    assert out["a"]["checkpoint_id"] == a and out["a"]["model"] == A and out["a"]["model_name"]
    assert out["b"]["model"] == B
    assert out["summary"]["sentences"] == {"same": 1, "changed": 1, "only_a": 1, "only_b": 1}
    assert out["summary_text"] == "1 sentence the same, 1 changed, 1 only in A, 1 only in B"
    changed = next(r for r in out["rows"] if r["op"] == "changed")
    assert changed["a"] == "It sits on the Seine." and changed["b"] == "It sits on the river Seine."
    assert {"op": "added", "text": "river "} in changed["segments"]
    assert not out["identical"]


def test_cli_diff_prints_marks_and_escapes_model_text():
    REPLIES[B] = "Paris is the capital of France. It sits on the [bold]Seine[/x]. Lyon is the second city."
    try:
        a, b = _arena("t-diff-rich")
        result = runner.invoke(cli_app, ["diff", a, b, "-t", "t-diff-rich"])
    finally:
        REPLIES[B] = "Paris is the capital of France. It sits on the river Seine. Lyon is the second city."
    assert result.exit_code == 0, result.exception
    out = result.stdout
    assert "1 sentence the same" in out
    assert "− Its museums are famous." in out and "+ Lyon is the second city." in out
    assert "[bold]Seine[/x]" in out  # printed as written, not read as markup
    assert "… 1 the same" in out


def test_cli_diff_refuses_what_is_not_a_reply():
    a, _b = _arena("t-diff-bad")
    tree = _json(["tree", "-t", "t-diff-bad", "--format", "json"])
    question = next(n["checkpoint_id"] for n in tree["nodes"] if n["role"] == "user")
    result = runner.invoke(cli_app, ["diff", question, a, "-t", "t-diff-bad", "--format", "json"])
    assert result.exit_code == 1 and "not a reply" in result.stderr
    assert runner.invoke(cli_app, ["diff", a, a, "-t", "missing"]).exit_code == 1


@pytest.mark.asyncio
async def test_mcp_diff_answers_returns_the_structure():
    from app.mcp_server import mcp

    async with Client(mcp) as client:
        res = (await client.call_tool("invoke_arena", {"prompt": "Where is Paris?", "models": [A, B], "synthesize": False})).data
        ids = {x["model"]: x["checkpoint_id"] for x in res["answers"]}
        out = (await client.call_tool(
            "diff_answers", {"thread_id": res["thread_id"], "checkpoint_a": ids[A], "checkpoint_b": ids[B]}
        )).data
        assert out["a"]["model"] == A and out["b"]["model"] == B
        assert [r["op"] for r in out["rows"]] == ["same", "changed", "only_a", "only_b"]
        assert out["summary_text"].startswith("1 sentence the same")

        same = (await client.call_tool(
            "diff_answers", {"thread_id": res["thread_id"], "checkpoint_a": ids[A], "checkpoint_b": ids[A]}
        )).data
        assert same["identical"]

        with pytest.raises(ToolError, match="not found"):
            await client.call_tool("diff_answers", {"thread_id": "missing", "checkpoint_a": "x", "checkpoint_b": "y"})
        with pytest.raises(ToolError, match="not found"):
            await client.call_tool(
                "diff_answers", {"thread_id": res["thread_id"], "checkpoint_a": ids[A], "checkpoint_b": "nope"}
            )
