"""What the web UI does to a conversation, through the CLI and the MCP server.

Branching from a checkpoint, Deliberation, attached and uploaded documents,
continuing after a debate, synthesizing chosen answers, continuing,
redirecting and reading debates, the tree, search, deleting a branch,
threads and keys. Real graph and SQLite checkpointer; only the LLM is faked,
and it records what each model was sent.
"""

import asyncio
import itertools
import json
import os
from typing import List
from unittest.mock import patch

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from typer.testing import CliRunner

from app.cli import app as cli_app
from app.core import database as db
from app.llm import CallableModelFactory, use_model_factory
from app.services import arena as arena_svc

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B = "gpt-5.4", "claude-sonnet-5"

SEEN: List[tuple] = []
# Every reply differs: the tree merges identical sibling replies into one node.
_N = itertools.count()


class _Recorder(FakeListChatModel):
    model_id: str = ""

    def _call(self, messages, *args, **kwargs):
        SEEN.append((self.model_id, list(messages)))
        return super()._call(messages, *args, **kwargs)

    def _stream(self, messages, *args, **kwargs):
        SEEN.append((self.model_id, list(messages)))
        yield from super()._stream(messages, *args, **kwargs)


def _sent(model_id=None) -> str:
    """Everything the models (or one model) were sent, as one string."""
    return "\n".join(str(m.content) for mid, messages in SEEN if model_id in (None, mid) for m in messages)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    SEEN.clear()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "features.sqlite"))
    monkeypatch.setattr("app.cli._load_env", lambda: None)
    monkeypatch.setattr("app.services.uploads.UPLOAD_DIR", str(tmp_path / "uploads"))
    factory = CallableModelFactory(
        lambda model_id, _t: _Recorder(responses=[f"reply from {model_id} v{next(_N)}"], model_id=model_id)
    )
    with use_model_factory(factory), patch.dict(os.environ, KEYS):
        yield


@pytest.fixture
def indexed(monkeypatch):
    """rag.index_document stand-in: never loads the embedding model."""
    calls = []
    monkeypatch.setattr("app.services.rag.index_document", lambda text, name, tid: calls.append((tid, name, text)) or 1)
    return calls


runner = CliRunner()


def _json(args, input=None):
    result = runner.invoke(cli_app, [*args, "--format", "json"], input=input)
    assert result.exit_code == 0, (result.stdout, result.stderr, result.exception)
    return json.loads(result.stdout)


def _fails(args, match):
    result = runner.invoke(cli_app, [*args, "--format", "json"])
    assert result.exit_code == 1, (result.stdout, result.exception)
    assert match in result.stderr
    return result


def _state(thread_id, checkpoint_id=None):
    async def read():
        async with arena_svc.open_graph() as graph_app:
            from app.services.runs import thread_config

            return (await graph_app.aget_state(thread_config(thread_id, checkpoint_id))).values

    return asyncio.run(read())


# ─── CLI: turns ──────────────────────────────────────────────────


def test_chat_from_a_checkpoint_branches_there():
    first = _json(["chat", "one", "-m", A, "-t", "t"])
    _json(["chat", "two", "-m", A, "-t", "t"])
    branch = _json(["chat", "three", "-m", A, "-t", "t", "--from", first["checkpoint_id"]])
    assert branch["parent_checkpoint_id"] == first["checkpoint_id"]
    said = [m["content"] for m in _json(["messages", "-t", "t", "--at", branch["checkpoint_id"]])["messages"]]
    assert said == ["one", first["content"], "three", branch["content"]]


def test_a_checkpoint_the_thread_lacks_is_an_error():
    _json(["chat", "one", "-m", A, "-t", "t"])
    _fails(["chat", "two", "-m", A, "-t", "t", "--from", "nope"], "not found")
    _fails(["debate", "x", "-m", A, "-m", B, "-r", "1", "-t", "t", "--from", "nope"], "not found")


def test_deliberate_asks_for_a_review_without_a_prompt():
    _json(["chat", "Is the sky green?", "-m", A, "-t", "t"])
    SEEN.clear()
    out = _json(["arena", "-m", A, "-m", B, "-t", "t", "--deliberate"])
    assert out["synthesis"] is None  # Deliberation answers are reviews, not merged
    assert "a critical reviewer" in _sent(B)
    assert "Please review the conversation" in _sent(B)


def test_attached_files_are_in_the_turn_and_only_that_turn(tmp_path):
    notes = tmp_path / "notes.md"
    notes.write_text("The launch code is PELICAN.")
    out = _json(["chat", "What is the code?", "-m", A, "-t", "t", "--attach", str(notes)])
    assert "PELICAN" in _sent(A)
    assert _state("t", out["checkpoint_id"])["attached_documents"] == ["notes.md"]
    SEEN.clear()
    _json(["chat", "And now?", "-m", A, "-t", "t"])
    assert "PELICAN" not in _sent(A)


def test_attach_rejects_what_upload_rejects(tmp_path):
    exe = tmp_path / "tool.exe"
    exe.write_text("x")
    _fails(["chat", "hi", "-m", A, "--attach", str(exe)], "not supported")
    _fails(["chat", "hi", "-m", A, "--attach", str(tmp_path / "missing.txt")], "No such file")


def test_upload_then_rag(tmp_path, indexed, monkeypatch):
    doc = tmp_path / "paper.txt"
    doc.write_text("Findings: the effect is small.")
    out = _json(["upload", str(doc), "-t", "t"])
    assert out["uploaded"] == [{"filename": "paper.txt", "chunks": 1}]
    assert indexed == [("t", "paper.txt", "Findings: the effect is small.")]

    seen_queries = []
    monkeypatch.setattr("app.services.rag.retrieve_context",
                        lambda query, thread_id, k=5: seen_queries.append(thread_id) or [])
    _json(["chat", "What were the findings?", "-m", A, "-t", "t", "--rag"])
    assert seen_queries == ["t"]


def test_chat_after_a_debate_sees_the_debate():
    debate = _json(["debate", "Is P = NP?", "-m", A, "-m", B, "-r", "1", "--no-synthesize", "-t", "t"])
    SEEN.clear()
    out = _json(["chat", "Who argued what?", "-m", A, "--after-debate", debate["session_id"]])
    assert out["thread_id"] == "t"
    assert "A debate between" in _sent(A) and "Is P = NP?" in _sent(A)


def test_arena_synthesis_is_marked_and_its_prompt_hidden():
    out = _json(["arena", "Q?", "-m", A, "-m", B, "-t", "t"])
    nodes = _json(["tree", "-t", "t"])["nodes"]
    assert [n["metadata"]["preview"] for n in nodes if n["metadata"].get("kind") == "synthesis"] == [
        out["synthesis"]["content"]
    ]
    said = [m["content"] for m in _json(["messages", "-t", "t", "--at", out["synthesis"]["checkpoint_id"]])["messages"]]
    assert said == ["Q?", out["synthesis"]["content"]]


def test_synthesize_chosen_answers_beside_them():
    arena = _json(["arena", "Q?", "-m", A, "-m", B, "-t", "t", "--no-synthesize"])
    cps = [arena["answers"][m]["checkpoint_id"] for m in (A, B)]
    SEEN.clear()
    out = _json(["synthesize", "-t", "t", "-a", cps[0], "-a", cps[1], "-j", B])
    assert out["synthesis"]["model"] == B
    assert "Independent answers from 2 models" in _sent(B)
    tree = _json(["tree", "-t", "t"])
    parents = {e["target"]: e["source"] for e in tree["edges"]}
    node_of = {n["metadata"]["preview"]: n["id"] for n in tree["nodes"]}
    # The synthesis hangs where the answers do: off the same question.
    question = {parents[node_of[arena["answers"][m]["content"]]] for m in (A, B)}
    assert question == {parents[node_of[out["synthesis"]["content"]]]}


# ─── CLI: debates ────────────────────────────────────────────────


def test_debates_continue_with_an_injected_message():
    debate = _json(["debate", "Topic", "-m", A, "-m", B, "-r", "1", "--no-synthesize"])
    sid = debate["session_id"]
    SEEN.clear()
    more = _json(["debates", "continue", sid, "--rounds", "1", "--inject", "Consider cost."])
    assert [r["round"] for r in more["rounds"]] == [1]
    assert "Consider cost." in _sent(A) and "Consider cost." in _sent(B)
    record = _json(["debates", "show", sid])
    assert record["question"] == "Topic"
    assert {m: len(r) for m, r in record["rounds"].items()} == {A: 2, B: 2}
    assert db.get_debate_session(sid)["status"] == "completed"


def test_a_debate_running_elsewhere_is_not_continued_unless_forced():
    debate = _json(["debate", "Topic", "-m", A, "-m", B, "-r", "1", "--no-synthesize"])
    sid = debate["session_id"]
    db.update_debate_session(sid, status="running")  # e.g. a web UI socket
    _fails(["debates", "continue", sid], "running in another client")
    _fails(["debates", "redirect", sid, "Other?"], "running in another client")
    assert db.get_debate_session(sid)["status"] == "running"  # left alone
    # A backend that died mid-debate leaves it marked running.
    assert [r["round"] for r in _json(["debates", "continue", sid, "--force"])["rounds"]] == [1]


def test_chat_renders_the_reply():
    result = runner.invoke(cli_app, ["chat", "hi", "-m", A, "-t", "t"])
    assert result.exit_code == 0, result.exception
    assert f"reply from {A}" in result.stdout


def test_debates_redirect_list_and_delete():
    debate = _json(["debate", "Topic", "-m", A, "-m", B, "-r", "1", "--no-synthesize", "-t", "t"])
    sid = debate["session_id"]
    SEEN.clear()
    _json(["debates", "redirect", sid, "New angle?"])
    assert "New angle?" in _sent(A)
    listed = _json(["debates", "list", "-t", "t"])["sessions"]
    assert [s["session_id"] for s in listed] == [sid]
    assert runner.invoke(cli_app, ["debates", "delete", sid, "-y"]).exit_code == 0
    assert db.get_debate_session(sid) is None


def test_debate_from_a_checkpoint_sees_that_conversation():
    first = _json(["chat", "Context: we sell tea.", "-m", A, "-t", "t"])
    SEEN.clear()
    _json(["debate", "Raise prices?", "-m", A, "-m", B, "-r", "1", "--no-synthesize", "-t", "t",
           "--from", first["checkpoint_id"]])
    assert "we sell tea" in _sent(B)


# ─── CLI: reading and editing threads ────────────────────────────


def test_tree_search_and_delete_branch():
    _json(["chat", "apples", "-m", A, "-t", "t"])
    _json(["chat", "bananas", "-m", A, "-t", "t"])
    hits = _json(["search", "banana", "-t", "t"])["results"]
    assert [h["role"] for h in hits] == ["user"]
    # Search points at the tree's node for the message.
    assert hits[0]["checkpoint_id"] in {n["id"] for n in _json(["tree", "-t", "t"])["nodes"]}

    out = _json(["delete-branch", hits[0]["checkpoint_id"], "-t", "t", "-y"])
    assert out["deleted_count"] >= 2
    assert _json(["search", "banana", "-t", "t"])["results"] == []
    assert _json(["search", "apples", "-t", "t"])["results"]


def test_keys_set_and_status(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    monkeypatch.setattr("app.services.keys.ENV_PATH", str(env))
    out = _json(["keys", "--set", "OPENAI_API_KEY"], input="sk-new-value-1234\n")
    assert out["keys"]["OPENAI_API_KEY"] == {"set": True, "masked": "•" * 13 + "1234"}
    assert 'OPENAI_API_KEY="sk-new-value-1234"' in env.read_text()
    assert oct(env.stat().st_mode)[-3:] == "600"
    _fails(["keys", "--set", "PATH"], "Unknown keys")


# ─── MCP ─────────────────────────────────────────────────────────


@pytest.fixture
def mcp_server():
    from app.mcp_server import mcp

    return mcp


async def _call(client, tool, args):
    return (await client.call_tool(tool, args)).data


@pytest.mark.asyncio
async def test_mcp_branch_deliberate_attach_and_synthesize(mcp_server, tmp_path):
    notes = tmp_path / "brief.txt"
    notes.write_text("Budget is 40k.")
    async with Client(mcp_server) as client:
        first = await _call(client, "invoke_arena", {"prompt": "one", "models": [A], "thread_id": "m", "synthesize": False})
        await _call(client, "invoke_arena", {"prompt": "two", "models": [A], "thread_id": "m", "synthesize": False})
        cp = first["answers"][A]["checkpoint_id"]

        SEEN.clear()
        branch = await _call(client, "invoke_arena", {
            "prompt": "three", "models": [A, B], "thread_id": "m", "parent_checkpoint_id": cp,
            "attachments": [str(notes)], "synthesize": False,
        })
        assert branch["parent_checkpoint_id"] == cp
        assert "Budget is 40k." in _sent(B) and "two" not in _sent(B)

        review = await _call(client, "invoke_arena", {"models": [B], "thread_id": "m", "deliberation": True,
                                                      "parent_checkpoint_id": branch["answers"][B]["checkpoint_id"]})
        assert review["synthesis"] is None

        syn = await _call(client, "synthesize_answers", {
            "thread_id": "m", "synthesizer": B,
            "checkpoint_ids": [branch["answers"][A]["checkpoint_id"], branch["answers"][B]["checkpoint_id"]],
        })
        assert syn["synthesis"]["content"].startswith(f"reply from {B}")

        tree = await _call(client, "get_thread_tree", {"thread_id": "m"})
        by_preview = {n["preview"]: n for n in tree["nodes"]}
        assert by_preview[syn["synthesis"]["content"]]["kind"] == "synthesis"
        assert by_preview[first["answers"][A]["content"]]["model"] == A

        with pytest.raises(ToolError, match="not found"):
            await client.call_tool("invoke_arena", {"prompt": "x", "models": [A], "thread_id": "m",
                                                    "parent_checkpoint_id": "nope"})


@pytest.mark.asyncio
async def test_mcp_debate_lifecycle(mcp_server):
    async with Client(mcp_server) as client:
        run = await _call(client, "run_debate", {"prompt": "Topic", "models": [A, B], "max_rounds": 1,
                                                 "thread_id": "d", "use_web_search": True})
        sid = run["session_id"]
        SEEN.clear()
        more = await _call(client, "continue_debate", {"session_id": sid, "inject": ["Mind the cost."]})
        assert [r["round"] for r in more["rounds"]] == [1]
        assert "Mind the cost." in _sent(A)

        await _call(client, "redirect_debate", {"session_id": sid, "prompt": "Other question?"})
        syn = await _call(client, "synthesize_debate", {"session_id": sid, "synthesizer": B})
        assert syn["synthesis"]["model"] == B

        record = await _call(client, "get_debate", {"session_id": sid})
        assert record["synthesis"] == syn["synthesis"]["content"]
        assert set(record["labels"]) == {A, B}
        assert [s["session_id"] for s in (await _call(client, "list_debates", {"thread_id": "d"}))["sessions"]] == [sid]

        SEEN.clear()
        after = await _call(client, "invoke_arena", {"prompt": "Summarize it", "models": [A],
                                                     "after_debate_session_id": sid, "synthesize": False})
        assert after["thread_id"] == "d" and "A debate between" in _sent(A)

        db.update_debate_session(sid, status="running")
        with pytest.raises(ToolError, match="running in another client"):
            await client.call_tool("continue_debate", {"session_id": sid})

        await _call(client, "delete_debate", {"session_id": sid})
        with pytest.raises(ToolError, match="not found"):
            await client.call_tool("get_debate", {"session_id": sid})


@pytest.mark.asyncio
async def test_mcp_threads_search_branches_and_uploads(mcp_server, tmp_path, indexed):
    doc = tmp_path / "data.csv"
    doc.write_text("a,b\n1,2\n")
    async with Client(mcp_server) as client:
        first = await _call(client, "invoke_arena", {"prompt": "kiwis", "models": [A], "thread_id": "s", "synthesize": False})
        await _call(client, "invoke_arena", {"prompt": "mangos", "models": [A], "thread_id": "s", "synthesize": False})

        hits = (await _call(client, "search_thread", {"thread_id": "s", "query": "mango"}))["results"]
        assert len(hits) == 1
        deleted = await _call(client, "delete_branch", {"thread_id": "s", "checkpoint_id": hits[0]["checkpoint_id"]})
        assert deleted["deleted_count"] >= 2
        assert (await _call(client, "search_thread", {"thread_id": "s", "query": "mango"}))["results"] == []
        assert (await _call(client, "get_thread_messages", {"thread_id": "s",
                "checkpoint_id": first["answers"][A]["checkpoint_id"]}))["messages"][0]["content"] == "kiwis"

        up = await _call(client, "upload_document", {"thread_id": "s", "path": str(doc)})
        assert up == {"thread_id": "s", "filename": "data.csv", "chunks": 1}
        with pytest.raises(ToolError, match="not supported"):
            await client.call_tool("upload_document", {"thread_id": "s", "path": str(tmp_path / "x.exe")})

        await _call(client, "rename_thread", {"thread_id": "s", "title": "Fruit"})
        assert {"id": "s", "title": "Fruit"} in (await _call(client, "list_threads", {}))["threads"]

        deleted_threads = []
        with patch("app.services.threads.default_thread_deleter", return_value=deleted_threads.append):
            await _call(client, "delete_thread", {"thread_id": "s"})
        assert deleted_threads == ["s"]
