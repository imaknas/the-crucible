"""Notes on tree nodes: a branch name, a bookmark and a subtree summary,
shown on the tree and reached from REST, the CLI and MCP; none of them is
written into the conversation."""

import json
import os
from unittest.mock import patch

import pytest
from fastmcp import Client
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage
from typer.testing import CliRunner

from app.cli import app as cli_app
from app.core import database as db
from app.llm import CallableModelFactory, use_model_factory
from app.services import arena, history, subtree
from tests.storage_helpers import point

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B = "gpt-5.4", "claude-sonnet-5"
PROMPTS: list = []


class _Summarizer(FakeListChatModel):
    async def ainvoke(self, messages, config=None, **kwargs):
        PROMPTS.append(messages[-1].content)
        return AIMessage(content="Both branches chose Postgres; one asked about cost.")


def _model(model_id, _toggles):
    if model_id == "gpt-6-luna":  # the default summarizer with these keys
        return _Summarizer(responses=["unused"])
    return FakeListChatModel(responses=[f"{model_id} says: use Postgres for the ledger."])


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    PROMPTS.clear()
    point(monkeypatch, db_path=str(tmp_path / "notes.sqlite"))
    monkeypatch.setattr("app.cli._load_env", lambda: None)
    db.init_db()
    with use_model_factory(CallableModelFactory(_model)), patch.dict(os.environ, KEYS):
        yield


async def _branched(graph_app, thread_id="t-notes"):
    """A question answered by two models, then a follow-up on A's branch."""
    first = await arena.collect(arena.run_arena(graph_app, "Which database?", thread_id, [A, B], {}, synthesizer=None))
    a_reply = first["answers"][A]["checkpoint_id"]
    await arena.collect(arena.run_arena(graph_app, "What does it cost?", thread_id, [A], {}, synthesizer=None,
                                        parent_checkpoint_id=a_reply))
    tree = await history.thread_tree(graph_app, thread_id)
    question = next(n["id"] for n in tree["nodes"] if n["metadata"].get("role") == "user")
    return tree, question, a_reply


def _meta(tree, node_id):
    return next(n["metadata"] for n in tree["nodes"] if n["id"] == node_id)


@pytest.mark.asyncio
async def test_a_node_is_named_and_bookmarked_and_cleared():
    async with arena.open_graph() as graph_app:
        _, question, _ = await _branched(graph_app)
        note = await subtree.label_node(graph_app, "t-notes", question, name="  Database   choice ", bookmarked=True)
        assert note == {"thread_id": "t-notes", "node_id": question, "name": "Database choice", "bookmarked": True}
        meta = _meta(await history.thread_tree(graph_app, "t-notes"), question)
        assert (meta["name"], meta["bookmarked"], meta["subtree_summary"]) == ("Database choice", True, None)

        # Each field changes alone; a node left with nothing has no row.
        await subtree.label_node(graph_app, "t-notes", question, bookmarked=False)
        assert db.load_node_notes("t-notes")[question]["name"] == "Database choice"
        await subtree.label_node(graph_app, "t-notes", question, name="")
        assert db.load_node_notes("t-notes") == {}

        with pytest.raises(ValueError, match="not found"):
            await subtree.label_node(graph_app, "t-notes", "no-such-node", name="x")
        with pytest.raises(ValueError, match="at most 80"):
            await subtree.label_node(graph_app, "t-notes", question, name="x" * 81)


@pytest.mark.asyncio
async def test_a_subtree_summary_reads_every_branch_and_is_never_written_to_the_thread():
    async with arena.open_graph() as graph_app:
        _, question, _ = await _branched(graph_app)
        before = len(db.get_thread_checkpoint_graph("t-notes"))
        result = await subtree.summarize_subtree(graph_app, "t-notes", question)

        assert result["model"] == "gpt-6-luna" and result["nodes"] == 5
        prompt = PROMPTS[-1]
        # Both answers, the follow-up, and which entry each replies to.
        assert f"{A} says" in prompt and f"{B} says" in prompt and "What does it cost?" in prompt
        assert "(replies to m1)" in prompt
        assert len(db.get_thread_checkpoint_graph("t-notes")) == before
        assert _meta(await history.thread_tree(graph_app, "t-notes"), question)["subtree_summary"] == {
            "text": "Both branches chose Postgres; one asked about cost.", "model": "gpt-6-luna", "nodes": 5,
        }

        await subtree.clear_subtree_summary(graph_app, "t-notes", question)
        assert _meta(await history.thread_tree(graph_app, "t-notes"), question)["subtree_summary"] is None


@pytest.mark.asyncio
async def test_notes_go_with_a_deleted_branch_and_a_deleted_thread():
    async with arena.open_graph() as graph_app:
        _, question, a_reply = await _branched(graph_app)
        await subtree.label_node(graph_app, "t-notes", question, bookmarked=True)
        await subtree.label_node(graph_app, "t-notes", a_reply, name="A's line")
        await history.delete_branch(graph_app, "t-notes", a_reply)
        assert set(db.load_node_notes("t-notes")) == {question}
    db.delete_thread_data("t-notes")
    assert db.load_node_notes("t-notes") == {}


def test_cli_rest_and_mcp_reach_the_same_notes():
    import asyncio

    from fastapi.testclient import TestClient

    from app.main import server
    from app.mcp_server import mcp

    runner = CliRunner()
    assert runner.invoke(cli_app, ["arena", "Which database?", "-m", A, "-m", B, "--no-synthesize", "-t", "t-cli"]).exit_code == 0
    nodes = json.loads(runner.invoke(cli_app, ["tree", "-t", "t-cli", "--format", "json"]).stdout)["nodes"]
    question = next(n["checkpoint_id"] for n in nodes if n["role"] == "user")

    named = runner.invoke(cli_app, ["node", question, "-t", "t-cli", "--name", "Databases", "--bookmark", "--format", "json"])
    assert named.exit_code == 0, named.stderr
    assert json.loads(named.stdout)["bookmarked"] is True
    assert runner.invoke(cli_app, ["node", question, "-t", "t-cli"]).exit_code == 2
    shown = runner.invoke(cli_app, ["tree", "-t", "t-cli"])
    assert "«Databases»" in shown.stdout and "★" in shown.stdout

    summarized = runner.invoke(cli_app, ["summarize-branch", question, "-t", "t-cli", "--format", "json"])
    assert summarized.exit_code == 0, summarized.stderr
    tree = json.loads(runner.invoke(cli_app, ["tree", "-t", "t-cli", "--format", "json"]).stdout)["nodes"]
    assert next(n for n in tree if n["checkpoint_id"] == question)["subtree_summary"]["nodes"] == 3

    with TestClient(server) as client:
        assert client.patch(f"/history/t-cli/nodes/{question}", json={"name": "Renamed"}).json()["name"] == "Renamed"
        assert client.patch("/history/t-cli/nodes/nope", json={"name": "x"}).status_code == 404
        assert client.delete(f"/history/t-cli/nodes/{question}/summary").status_code == 200
        assert client.post(f"/history/t-cli/nodes/{question}/summary", json={}).json()["nodes"] == 3

    async def over_mcp():
        async with Client(mcp) as c:
            note = (await c.call_tool("label_node", {"thread_id": "t-cli", "node_id": question, "bookmarked": False})).data
            cleared = (await c.call_tool("summarize_subtree", {"thread_id": "t-cli", "node_id": question, "clear": True})).data
            return note, cleared

    note, cleared = asyncio.run(over_mcp())
    assert note["bookmarked"] is False and note["name"] == "Renamed"
    assert cleared["summary"] is None
