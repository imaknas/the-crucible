"""What the web UI does to a conversation, through the CLI and the MCP server.

Branching, per-model continuation, Deliberation, attached and uploaded
documents, continuing after a debate, synthesis, continuing, redirecting
and reading debates, the tree, search, deleting a branch, threads and keys.
Real graph and SQLite checkpointer; only the LLM is faked, and it records
what each model was sent.
"""

import asyncio
import itertools
from contextlib import aclosing
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

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B = "gpt-5.4", "claude-sonnet-5"

SEEN: List[tuple] = []
# Every reply differs: the tree merges identical sibling replies into one node.
_N = itertools.count()
FAIL = set()


class _Recorder(FakeListChatModel):
    model_id: str = ""

    def _call(self, messages, *args, **kwargs):
        SEEN.append((self.model_id, list(messages)))
        if self.model_id in FAIL:
            raise RuntimeError(f"{self.model_id} is down")
        return super()._call(messages, *args, **kwargs)

    def _stream(self, messages, *args, **kwargs):
        SEEN.append((self.model_id, list(messages)))
        if self.model_id in FAIL:
            raise RuntimeError(f"{self.model_id} is down")
        yield from super()._stream(messages, *args, **kwargs)


def _sent(model_id=None) -> str:
    """Everything the models (or one model) were sent, as one string."""
    return "\n".join(str(m.content) for mid, messages in SEEN if model_id in (None, mid) for m in messages)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    SEEN.clear()
    FAIL.clear()
    monkeypatch.setattr("app.cli._load_env", lambda: None)
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


def _fails(args, match, code=1):
    result = runner.invoke(cli_app, [*args, "--format", "json"])
    assert result.exit_code == code, (result.stdout, result.stderr, result.exception)
    assert match in result.stderr + result.stdout
    return result


def _answers(out):
    return {a["model"]: a for a in out["answers"]} if isinstance(out["answers"], list) else out["answers"]


# ─── CLI: turns ──────────────────────────────────────────────────


def test_chat_from_a_checkpoint_branches_there():
    first = _json(["chat", "one", "-m", A, "-t", "t"])
    assert first["new_thread"] is True
    _json(["chat", "two", "-m", A, "-t", "t"])
    branch = _json(["chat", "three", "-m", A, "-t", "t", "--from", first["checkpoint_id"]])
    assert branch["parent_checkpoint_id"] == first["checkpoint_id"]
    said = [m["content"] for m in _json(["messages", "-t", "t", "--at", branch["checkpoint_id"]])["messages"]]
    assert said == ["one", first["content"], "three", branch["content"]]


def test_each_model_continues_its_own_reply():
    first = _answers(_json(["arena", "Q1", "-m", A, "-m", B, "-t", "t", "--no-synthesize"]))
    SEEN.clear()
    second = _json(["arena", "Q2", "-m", A, "-m", B, "-t", "t", "--no-synthesize"])
    assert second["parents"] == {A: first[A]["checkpoint_id"], B: first[B]["checkpoint_id"]}
    # Each saw its own earlier answer, not the other's.
    assert first[A]["content"] in _sent(A) and first[B]["content"] not in _sent(A)
    assert first[B]["content"] in _sent(B) and first[A]["content"] not in _sent(B)


def test_argument_combinations_are_refused_before_anything_runs():
    _fails(["chat", "x", "--from", "cp"], "--from needs --thread", code=2)
    _fails(["chat", "x", "-t", "t", "--from", "cp", "--after-debate", "d"], "not both", code=2)
    _fails(["chat", "x", "-m", A, "-m", B], "arena", code=2)
    _fails(["search", "a", "-t", "t"], "two characters", code=2)
    _fails(["threads", "--title", "x"], "--rename", code=2)
    assert db.list_threads() == []


def test_a_checkpoint_the_thread_lacks_is_an_error():
    _json(["chat", "one", "-m", A, "-t", "t"])
    _fails(["chat", "two", "-m", A, "-t", "t", "--from", "nope"], "not found")
    _fails(["debate", "x", "-m", A, "-m", B, "-r", "1", "-t", "t", "--from", "nope"], "not found")
    assert db.list_debate_sessions("t") == []  # refused before a session was made


def test_deliberate_asks_for_a_review_and_needs_a_conversation():
    _fails(["chat", "--deliberate", "-m", A, "-t", "empty"], "has none yet")
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
    assert out["attached_documents"] == ["notes.md"]
    SEEN.clear()
    _json(["chat", "And now?", "-m", A, "-t", "t"])
    assert "PELICAN" not in _sent(A)


def test_attach_rejects_what_upload_rejects(tmp_path):
    exe = tmp_path / "tool.exe"
    exe.write_text("x")
    _fails(["chat", "hi", "-m", A, "--attach", str(exe)], "not supported")
    _fails(["chat", "hi", "-m", A, "--attach", str(tmp_path / "missing.txt")], "No such file")


def test_upload_then_rag_and_a_failed_search_is_a_notice(tmp_path, indexed, monkeypatch):
    doc = tmp_path / "paper.txt"
    doc.write_text("Findings: the effect is small.")
    out = _json(["upload", str(doc), "-t", "t"])
    assert out["uploaded"] == [{"filename": "paper.txt", "chunks": 1}]
    assert indexed == [("t", "paper.txt", "Findings: the effect is small.")]
    assert _json(["upload", "-t", "t", "--list"])["files"] == ["paper.txt"]

    seen_queries = []
    monkeypatch.setattr("app.services.rag.retrieve_context",
                        lambda query, thread_id, k=5: seen_queries.append(thread_id) or [])
    _json(["chat", "What were the findings?", "-m", A, "-t", "t", "--rag"])
    assert seen_queries == ["t"]

    def broken(*_a, **_k):
        raise RuntimeError("index offline")

    monkeypatch.setattr("app.services.rag.retrieve_context", broken)
    out = _json(["chat", "Again?", "-m", A, "-t", "t", "--rag"])
    assert any("index offline" in n for n in out["notices"])


def test_a_debate_with_rag_searches_the_threads_files(monkeypatch):
    seen = []
    monkeypatch.setattr("app.services.rag.retrieve_context", lambda q, thread_id, k=5: seen.append(thread_id) or [])
    _json(["debate", "Topic", "-m", A, "-m", B, "-r", "1", "--no-synthesize", "-t", "t", "--rag"])
    # Uploads are indexed for the thread, not for the debate's lanes.
    assert seen and set(seen) == {"t"}


def test_chat_after_a_debate_sees_the_debate_and_follows_on():
    debate = _json(["debate", "Is P = NP?", "-m", A, "-m", B, "-r", "1", "--no-synthesize", "-t", "t"])
    SEEN.clear()
    first = _json(["chat", "Who argued what?", "-m", A, "--after-debate", debate["session_id"]])
    assert first["thread_id"] == "t"
    assert "A debate between" in _sent(A) and "Is P = NP?" in _sent(A)
    # A second turn "after the debate" follows the first instead of branching beside it.
    second = _json(["chat", "And then?", "-m", A, "--after-debate", debate["session_id"]])
    assert second["parent_checkpoint_id"] == first["checkpoint_id"]


def test_arena_synthesis_is_marked_hung_under_the_question_and_its_prompt_hidden():
    out = _json(["arena", "Q?", "-m", A, "-m", B, "-t", "t"])
    nodes = {n["checkpoint_id"]: n for n in _json(["tree", "-t", "t"])["nodes"]}
    synthesis = nodes[out["synthesis"]["checkpoint_id"]]
    assert synthesis["kind"] == "synthesis"
    answers = _answers(out)
    assert synthesis["parent"] == nodes[answers[A]["checkpoint_id"]]["parent"]
    said = [m["content"] for m in _json(["messages", "-t", "t", "--at", out["synthesis"]["checkpoint_id"]])["messages"]]
    assert said == ["Q?", out["synthesis"]["content"]]


def test_synthesize_defaults_to_the_latest_question_and_its_first_model():
    _json(["arena", "Old?", "-m", A, "-m", B, "-t", "t"])
    arena = _answers(_json(["arena", "New?", "-m", A, "-m", B, "-t", "t", "--no-synthesize"]))
    SEEN.clear()
    out = _json(["synthesize", "-t", "t"])
    assert sorted(a["checkpoint_id"] for a in out["answers"]) == sorted(a["checkpoint_id"] for a in arena.values())
    assert out["synthesis"]["model"] == A
    assert "New?" in _sent(A) and "Old?" not in _sent(A).split("Independent answers")[-1]


def test_synthesize_chosen_answers_beside_them():
    arena = _answers(_json(["arena", "Q?", "-m", A, "-m", B, "-t", "t", "--no-synthesize"]))
    SEEN.clear()
    out = _json(["synthesize", "-t", "t", "-a", arena[A]["checkpoint_id"], "-a", arena[B]["checkpoint_id"], "-j", B])
    assert out["synthesis"]["model"] == B
    assert "Independent answers from 2 models" in _sent(B)
    nodes = {n["checkpoint_id"]: n for n in _json(["tree", "-t", "t"])["nodes"]}
    assert nodes[out["synthesis"]["checkpoint_id"]]["parent"] == nodes[arena[A]["checkpoint_id"]]["parent"]


def test_failures_exit_non_zero_and_say_why():
    FAIL.add(B)
    result = runner.invoke(cli_app, ["arena", "Q?", "-m", A, "-m", B, "-t", "t", "--format", "json"])
    assert result.exit_code == 1
    out = json.loads(result.stdout)
    assert _answers(out)[B]["error"] and out["synthesis_skipped"]


def test_text_with_brackets_is_printed_not_parsed_as_markup():
    prompt = "What does arr[0] and list[int] mean? Also [red]x[/red] and [/oops]"
    assert runner.invoke(cli_app, ["chat", prompt, "-m", A, "-t", "br"]).exit_code == 0
    result = runner.invoke(cli_app, ["search", "arr", "-t", "br"])
    assert result.exit_code == 0, result.exception
    assert "[/oops]" in result.stdout
    assert "list[int]" in runner.invoke(cli_app, ["threads"]).stdout


def test_json_output_is_only_json(tmp_path, indexed):
    doc = tmp_path / "n.txt"
    doc.write_text("data")
    for args in (["upload", str(doc), "-t", "j"], ["chat", "hi", "-m", A, "-t", "j"], ["models"]):
        result = runner.invoke(cli_app, [*args, "--format", "json"])
        assert result.exit_code == 0, result.stderr
        json.loads(result.stdout)


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
    assert [sorted(r["responses"]) for r in record["rounds"]] == [sorted([A, B])] * 2
    assert record["injected"] == [{"round": 1, "message": "Consider cost."}]
    assert db.get_debate_session(sid)["status"] == "completed"


def test_a_redirect_keeps_numbering_and_records_its_question():
    debate = _json(["debate", "Hot dog a sandwich?", "-m", A, "-m", B, "-r", "1", "--no-synthesize", "-t", "t"])
    sid = debate["session_id"]
    SEEN.clear()
    out = _json(["debates", "redirect", sid, "Taco a sandwich?", "--rounds", "1"])
    assert [r["round"] for r in out["rounds"]] == [1]
    record = _json(["debates", "show", sid])
    assert [r["question"] for r in record["rounds"]] == ["Hot dog a sandwich?", "Taco a sandwich?"]
    assert record["question"] == "Taco a sandwich?"
    assert [s["question"] for s in _json(["debates", "list", "-t", "t"])["sessions"]] == ["Taco a sandwich?"]
    # The record a chat turn reads names both questions.
    SEEN.clear()
    _json(["chat", "Summarize", "-m", A, "--after-debate", sid])
    assert "Taco a sandwich?" in _sent(A) and "Hot dog a sandwich?" in _sent(A)


def test_a_debate_runs_ten_rounds_at_most_in_all():
    debate = _json(["debate", "Topic", "-m", A, "-m", B, "-r", "9", "--no-synthesize"])
    sid = debate["session_id"]
    assert [r["round"] for r in _json(["debates", "continue", sid, "--rounds", "5"])["rounds"]] == [9]
    _fails(["debates", "continue", sid], "limit of 10")


def test_continuing_reuses_the_debates_settings():
    debate = _json(["debate", "Topic", "-m", A, "-m", B, "-r", "1", "--no-synthesize", "--system", "Answer in French."])
    SEEN.clear()
    _json(["debates", "continue", debate["session_id"]])
    systems = [str(m.content) for _mid, messages in SEEN for m in messages if m.type == "system"]
    assert systems and all("Answer in French." in s for s in systems)


def test_a_failed_participant_stops_round_one_and_a_failed_map_says_so():
    FAIL.add(B)
    result = runner.invoke(cli_app, ["debate", "Topic", "-m", A, "-m", B, "-r", "2", "--format", "json"])
    assert result.exit_code == 1
    out = json.loads(result.stdout)
    assert [r["round"] for r in out["rounds"]] == [0]
    assert out["failed"] == {B: [0]} and any("nothing to debate" in e for e in out["errors"])
    FAIL.clear()
    FAIL.add(A)
    debate = _json(["debate", "Topic", "-m", B, "-m", "gemini-3.1-pro-preview", "-r", "1", "--no-synthesize"])
    result = runner.invoke(cli_app, ["synthesize", "-d", debate["session_id"], "-j", A, "--format", "json"])
    assert result.exit_code == 1
    assert "failed to write the synthesis" in json.loads(result.stdout)["synthesis"]["error"]


def test_a_debate_running_elsewhere_is_not_continued_unless_forced():
    debate = _json(["debate", "Topic", "-m", A, "-m", B, "-r", "1", "--no-synthesize"])
    sid = debate["session_id"]
    db.update_debate_session(sid, status="running")  # e.g. a web UI socket
    _fails(["debates", "continue", sid], "running in another client")
    _fails(["debates", "redirect", sid, "Other?"], "running in another client")
    assert db.get_debate_session(sid)["status"] == "running"  # left alone
    # A backend that died mid-debate leaves it marked running.
    assert [r["round"] for r in _json(["debates", "continue", sid, "--force"])["rounds"]] == [1]


def test_debates_list_and_delete():
    debate = _json(["debate", "Topic", "-m", A, "-m", B, "-r", "1", "--no-synthesize", "-t", "t"])
    sid = debate["session_id"]
    assert [s["session_id"] for s in _json(["debates", "list", "-t", "t"])["sessions"]] == [sid]
    assert _json(["debates", "delete", sid, "-y"]) == {"deleted": sid}
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
    bananas = _json(["chat", "bananas", "-m", A, "-t", "t"])
    hits = _json(["search", "banana", "-t", "t"])["results"]
    assert [h["role"] for h in hits] == ["user"]
    # Search, the tree and the turn hand out the same ids.
    ids = {n["checkpoint_id"] for n in _json(["tree", "-t", "t"])["nodes"]}
    assert hits[0]["checkpoint_id"] in ids and bananas["checkpoint_id"] in ids

    # A reply's id deletes that reply and what follows, not only what follows.
    out = _json(["delete-branch", bananas["checkpoint_id"], "-t", "t", "-y"])
    assert out["deleted_count"] >= 1
    assert not [h for h in _json(["search", "banana", "-t", "t"])["results"] if h["role"] == "assistant"]
    assert _json(["search", "apples", "-t", "t"])["results"]

    root = next(n for n in _json(["tree", "-t", "t"])["nodes"] if n["parent"] is None)
    _fails(["delete-branch", root["checkpoint_id"], "-t", "t", "-y"], "delete the thread")


def test_unknown_threads_are_errors_not_successes():
    _fails(["threads", "--rename", "nope", "--title", "x"], "not found")
    _fails(["threads", "--delete", "nope", "-y"], "not found")
    _fails(["search", "xx", "-t", "nope"], "not found")
    _fails(["tree", "-t", "nope"], "not found")
    _json(["chat", "hi", "-m", A, "-t", "real"])
    assert _json(["threads", "--rename", "real", "--title", "Real"]) == {"thread_id": "real", "title": "Real"}


def test_keys_set_and_status(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    monkeypatch.setattr("app.services.keys.ENV_PATH", str(env))
    out = _json(["keys", "--set", "OPENAI_API_KEY"], input="sk-new-value-1234\n")
    assert out["keys"]["OPENAI_API_KEY"] == {"set": True, "masked": "••••1234"}
    assert 'OPENAI_API_KEY="sk-new-value-1234"' in env.read_text()
    assert oct(env.stat().st_mode)[-3:] == "600"
    _fails(["keys", "--set", "PATH"], "Unknown key(s): PATH")


# ─── MCP ─────────────────────────────────────────────────────────


@pytest.fixture
def mcp_server():
    from app.mcp_server import mcp

    return mcp


async def _call(client, tool, args):
    return (await client.call_tool(tool, args)).data


@pytest.mark.asyncio
async def test_mcp_descriptions_say_what_tools_return(mcp_server):
    async with Client(mcp_server) as client:
        tools = {t.name: t for t in await client.list_tools()}
    for name in ("invoke_arena", "synthesize_answers", "run_debate", "continue_debate", "get_debate", "get_thread_tree"):
        assert "Returns" in tools[name].description, name
    assert tools["continue_debate"].input_schema["properties"]["force"].get("description")


@pytest.mark.asyncio
async def test_mcp_branch_deliberate_attach_and_synthesize(mcp_server, tmp_path):
    notes = tmp_path / "brief.txt"
    notes.write_text("Budget is 40k.")
    async with Client(mcp_server) as client:
        with pytest.raises(ToolError, match="not found"):
            await client.call_tool("invoke_arena", {"prompt": "x", "models": [A], "thread_id": "typo"})

        first = await _call(client, "invoke_arena", {"prompt": "one", "models": [A], "synthesize": False})
        thread = first["thread_id"]
        await _call(client, "invoke_arena", {"prompt": "two", "models": [A], "thread_id": thread, "synthesize": False})
        cp = first["answers"][0]["checkpoint_id"]

        SEEN.clear()
        branch = await _call(client, "invoke_arena", {
            "prompt": "three", "models": [A, B], "thread_id": thread, "parent_checkpoint_id": cp,
            "attachments": [str(notes)], "synthesize": False,
        })
        answers = {a["model"]: a for a in branch["answers"]}
        assert answers[B]["parent_checkpoint_id"] == cp and answers[B]["attached_documents"] == ["brief.txt"]
        assert "Budget is 40k." in _sent(B) and "two" not in _sent(B)

        review = await _call(client, "invoke_arena", {"models": [B], "thread_id": thread, "deliberation": True,
                                                      "parent_checkpoint_id": answers[B]["checkpoint_id"]})
        assert review["synthesis"] is None

        syn = await _call(client, "synthesize_answers", {
            "thread_id": thread, "synthesizer": B,
            "checkpoint_ids": [answers[A]["checkpoint_id"], answers[B]["checkpoint_id"]],
        })
        assert syn["synthesis"]["content"].startswith(f"reply from {B}")
        assert [a["checkpoint_id"] for a in syn["answers"]] == [answers[A]["checkpoint_id"], answers[B]["checkpoint_id"]]

        tree = await _call(client, "get_thread_tree", {"thread_id": thread})
        nodes = {n["checkpoint_id"]: n for n in tree["nodes"]}
        assert nodes[syn["synthesis"]["checkpoint_id"]]["kind"] == "synthesis"
        assert nodes[cp]["model"] == A and nodes[cp]["excerpt"] == first["answers"][0]["content"]

        with pytest.raises(ToolError, match="not found"):
            await client.call_tool("invoke_arena", {"prompt": "x", "models": [A], "thread_id": thread,
                                                    "parent_checkpoint_id": "nope"})


@pytest.mark.asyncio
async def test_mcp_a_new_thread_whose_first_turn_failed_is_removed(mcp_server):
    FAIL.add(A)
    async with Client(mcp_server) as client:
        with pytest.raises(ToolError, match="Every model failed"):
            await client.call_tool("invoke_arena", {"prompt": "hi", "models": [A]})
        assert (await _call(client, "list_threads", {}))["threads"] == []


@pytest.mark.asyncio
async def test_mcp_debate_lifecycle(mcp_server):
    async with Client(mcp_server) as client:
        run = await _call(client, "run_debate", {"prompt": "Topic", "models": [A, B], "max_rounds": 1,
                                                 "use_web_search": True, "system_prompt": "Be brief."})
        sid = run["session_id"]
        assert run["status"] == "completed" and run["rounds"][0]["round"] == 0

        with pytest.raises(ToolError, match="at least 1"):
            await client.call_tool("continue_debate", {"session_id": sid, "rounds": 0})

        SEEN.clear()
        more = await _call(client, "continue_debate", {"session_id": sid, "inject": ["Mind the cost."]})
        assert [r["round"] for r in more["rounds"]] == [1]
        assert "Mind the cost." in _sent(A) and "Be brief." in _sent(A)

        await _call(client, "redirect_debate", {"session_id": sid, "prompt": "Other question?", "rounds": 1})
        syn = await _call(client, "synthesize_debate", {"session_id": sid, "synthesizer": B})
        assert syn["synthesis"]["model"] == B and syn["synthesis"]["error"] is None

        record = await _call(client, "get_debate", {"session_id": sid, "rounds_from": 2})
        assert [r["question"] for r in record["rounds"]] == ["Other question?"]
        assert record["synthesis"]["content"] == syn["synthesis"]["content"]
        assert set(record["labels"]) == {A, B}
        listed = (await _call(client, "list_debates", {"thread_id": run["thread_id"]}))["sessions"]
        assert [s["session_id"] for s in listed] == [sid] and "thread_ids" not in listed[0]

        SEEN.clear()
        after = await _call(client, "invoke_arena", {"prompt": "Summarize it", "models": [A],
                                                     "after_debate_session_id": sid, "synthesize": False})
        assert after["thread_id"] == run["thread_id"] and "A debate between" in _sent(A)

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
        first = await _call(client, "invoke_arena", {"prompt": "kiwis", "models": [A], "synthesize": False})
        thread = first["thread_id"]
        await _call(client, "invoke_arena", {"prompt": "mangos", "models": [A], "thread_id": thread, "synthesize": False})

        with pytest.raises(ToolError, match="two characters"):
            await client.call_tool("search_thread", {"thread_id": thread, "query": "m"})
        hits = (await _call(client, "search_thread", {"thread_id": thread, "query": "mango"}))["results"]
        assert len(hits) == 1
        deleted = await _call(client, "delete_branch", {"thread_id": thread, "checkpoint_id": hits[0]["checkpoint_id"]})
        assert deleted["deleted_count"] >= 2
        assert (await _call(client, "search_thread", {"thread_id": thread, "query": "mango"}))["results"] == []
        messages = (await _call(client, "get_thread_messages", {"thread_id": thread,
                    "checkpoint_id": first["answers"][0]["checkpoint_id"]}))["messages"]
        assert messages[0]["content"] == "kiwis" and messages[1]["model_name"]
        with pytest.raises(ToolError, match="Checkpoint nope not found"):
            await client.call_tool("get_thread_messages", {"thread_id": thread, "checkpoint_id": "nope"})

        up = await _call(client, "upload_document", {"thread_id": thread, "path": str(doc)})
        assert up == {"thread_id": thread, "filename": "data.csv", "chunks": 1}
        with pytest.raises(ToolError, match="not supported"):
            await client.call_tool("upload_document", {"thread_id": thread, "path": str(tmp_path / "x.exe")})

        await _call(client, "rename_thread", {"thread_id": thread, "title": "Fruit"})
        assert {"id": thread, "title": "Fruit"} in [
            {"id": t["id"], "title": t["title"]} for t in (await _call(client, "list_threads", {}))["threads"]
        ]
        with pytest.raises(ToolError, match="not found"):
            await client.call_tool("rename_thread", {"thread_id": "ghost", "title": "Ghost"})
        with pytest.raises(ToolError, match="part of a debate"):
            await client.call_tool("delete_thread", {"thread_id": f"{thread}::debate-x::{A}"})

        deleted_threads = []
        with patch("app.services.threads.default_thread_deleter", return_value=deleted_threads.append):
            await _call(client, "delete_thread", {"thread_id": thread})
        assert deleted_threads == [thread]


# ─── The debate session's status, owned by the run ──────────────


@pytest.mark.asyncio
async def test_a_cancelled_debate_is_left_interrupted_and_a_refused_start_untouched():
    from app.services import debate as debate_svc
    from app.services.arena import open_graph

    started = asyncio.Event()

    async with open_graph() as graph_app:
        session = debate_svc.create_session("t", [A, B], {"max_rounds": 3})
        sid = session["session_id"]

        async def run():
            # Closed when cancelled, as every transport consumes a run: the
            # run's own cleanup records the status.
            async with aclosing(debate_svc.run_debate(graph_app, sid, "Q", {}, {})) as events:
                async for e in events:
                    if e["type"] == "debate_round_start":
                        started.set()
                        await asyncio.sleep(10)

        task = asyncio.create_task(run())
        await started.wait()
        assert db.get_debate_session(sid)["status"] == "running"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert db.get_debate_session(sid)["status"] == "interrupted"

        fresh = debate_svc.create_session("t", [A, B], {"max_rounds": 1})
        events = [e async for e in debate_svc.run_debate(graph_app, fresh["session_id"], "Q", {}, {},
                                                          parent_checkpoint_id="nope")]
        assert events[-1]["type"] == "error"
        assert db.get_debate_session(fresh["session_id"])["status"] == "pending"
