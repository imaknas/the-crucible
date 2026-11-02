"""Every client gets each answer's metrics in the same shape.

Real graph, real SQLite checkpointer, the scripted fake LLM (the one the e2e
suite uses), which reports deterministic usage, so registry models get a cost.
"""

import json
import os
from unittest.mock import patch

import pytest
from fastmcp import Client
from typer.testing import CliRunner

from app.cli import app as cli_app
from app.llm import use_model_factory
from app.llm.fake import ScriptedModelFactory
from tests.storage_helpers import point

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B = "gpt-5.4", "claude-sonnet-5"
FIELDS = {"ttft_ms", "total_ms", "input_tokens", "output_tokens", "reasoning_tokens", "cached_input_tokens", "cost_usd"}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    point(monkeypatch, db_path=str(tmp_path / "m.sqlite"))
    monkeypatch.setattr("app.cli._load_env", lambda: None)
    with use_model_factory(ScriptedModelFactory(delay=0)), patch.dict(os.environ, KEYS):
        yield


def _complete(metrics):
    assert metrics is not None and set(metrics) == FIELDS
    assert metrics["total_ms"] is not None and metrics["ttft_ms"] is not None
    assert metrics["input_tokens"] > 0 and metrics["output_tokens"] > 0
    # Reasoning is part of the output, never more than it.
    assert 0 <= metrics["reasoning_tokens"] <= metrics["output_tokens"]
    assert metrics["cost_usd"] > 0
    return metrics


runner = CliRunner()


def test_cli_json_has_metrics_per_answer_and_for_the_synthesis():
    result = runner.invoke(cli_app, ["arena", "Q?", "-m", A, "-m", B, "-t", "t-m", "--format", "json"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    out = json.loads(result.stdout)
    for model in (A, B):
        _complete(out["answers"][model]["metrics"])
    _complete(out["synthesis"]["metrics"])

    # Answers already on the thread keep theirs when synthesized again.
    syn = json.loads(runner.invoke(cli_app, ["synthesize", "-t", "t-m", "-j", B, "--format", "json"]).stdout)
    assert all(_complete(a["metrics"]) for a in syn["answers"])
    _complete(syn["synthesis"]["metrics"])

    chat = json.loads(runner.invoke(cli_app, ["chat", "more", "-m", A, "-t", "t-m", "--format", "json"]).stdout)
    _complete(chat["metrics"])


def test_cli_prints_a_metrics_line_per_answer_and_a_turn_total():
    result = runner.invoke(cli_app, ["arena", "Q?", "-m", A, "-m", B, "--no-synthesize"])
    assert result.exit_code == 0, result.exception
    assert result.stdout.count("to first token") == 3  # two answers and the turn
    assert "turn:" in result.stdout and " in / " in result.stdout and "$" in result.stdout


@pytest.mark.asyncio
async def test_mcp_answers_messages_and_tree_carry_metrics():
    from app.mcp_server import mcp

    async with Client(mcp) as client:
        res = (await client.call_tool("invoke_arena", {"prompt": "Q?", "models": [A, B]})).data
        for answer in res["answers"]:
            _complete(answer["metrics"])
        _complete(res["synthesis"]["metrics"])
        thread = res["thread_id"]
        answer = res["answers"][0]

        path = (await client.call_tool(
            "get_thread_messages", {"thread_id": thread, "checkpoint_id": answer["checkpoint_id"]}
        )).data["messages"]
        assert path[0]["metrics"] is None  # the question
        assert path[1]["metrics"] == answer["metrics"]

        nodes = (await client.call_tool("get_thread_tree", {"thread_id": thread})).data["nodes"]
        node = next(n for n in nodes if n["checkpoint_id"] == answer["checkpoint_id"])
        assert node["metrics"] == answer["metrics"]

        branches = (await client.call_tool("get_branch_answers", {"thread_id": thread})).data["answers"]
        assert all(_complete(a["metrics"]) for a in branches)


def test_websocket_stream_end_and_post_chat_carry_metrics():
    from fastapi.testclient import TestClient

    from app.main import server

    with TestClient(server) as client:
        with client.websocket_connect("/ws/t-ws") as ws:
            ws.send_json({"message": "Q?", "model": A})
            while (msg := ws.receive_json())["type"] != "stream_end":
                assert msg["type"] != "error", msg
        metrics = _complete(msg["metrics"])
        reply = next(m for m in msg["messages"] if m["role"] == "assistant")
        assert reply["metrics"] == metrics

        # After a reload: the tree node and the path say the same.
        history = client.get(f"/history/t-ws?checkpoint_id={msg['checkpoint_id']}").json()
        node = next(n for n in history["nodes"] if n["id"] == msg["checkpoint_id"])
        assert node["metadata"]["metrics"] == metrics

        r = client.post("/chat", json={"message": "again", "thread_id": "t-ws", "model": B})
        assert r.status_code == 200, r.text
        _complete(r.json()["messages"][-1]["metrics"])
