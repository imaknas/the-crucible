"""Saved cases: a turn copied whole (question, history, documents, settings,
answers, vote), outliving its thread, and replayed on other models in a new
seeded thread, compared old against new. Service, REST, CLI and MCP, against
the real graph and SQLite checkpointer; only the LLM is faked, and it records
what each model was sent."""

import asyncio
import itertools
import json
import os
from typing import List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.exceptions import ToolError
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, messages_to_dict
from typer.testing import CliRunner

from app.cli import app as cli_app
from app.core import database as db
from app.core.database import ThreadDocumentStore
from app.core.schema import is_summary_message, summary_message
from app.llm import CallableModelFactory, use_model_factory
from app.main import server
from app.services import arena, cases, history, votes
from app.services.chat import thread_state_map
from app.services.context import ContextSettings
from app.services.runs import is_seed, seed_thread
from tests.storage_helpers import point

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B, C = "gpt-5.4", "claude-sonnet-5", "gemini-3.1-pro-preview"
KEYLESS = "grok-4.7"  # no XAI_API_KEY in KEYS
SEEN: List[tuple] = []
_N = itertools.count()
DOC = {"brief.md": "The budget is 40k."}


class _Recorder(FakeListChatModel):
    model_id: str = ""

    def _call(self, messages, *args, **kwargs):
        SEEN.append((self.model_id, list(messages)))
        return super()._call(messages, *args, **kwargs)

    def _stream(self, messages, *args, **kwargs):
        SEEN.append((self.model_id, list(messages)))
        yield from super()._stream(messages, *args, **kwargs)


def _sent(model_id) -> str:
    return "\n".join(str(m.content) for mid, messages in SEEN if mid == model_id for m in messages)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    SEEN.clear()
    point(monkeypatch, db_path=str(tmp_path / "cases.sqlite"))
    monkeypatch.setattr("app.cli._load_env", lambda: None)
    db.init_db()
    factory = CallableModelFactory(
        # Every reply differs, so the diffs and the history say whose it is.
        lambda model_id, _t: _Recorder(responses=[f"Reply from {model_id}. Number {next(_N)}."], model_id=model_id)
    )
    with use_model_factory(factory), patch.dict(os.environ, KEYS):
        yield


async def _two_turns(graph_app, thread_id="t-case", *, toggles=None, deliberation=False):
    """Q1 answered by A and B; Q2 continues each model's own reply, with a
    document, a system prompt and a summarizer; the person votes B best."""
    first = await arena.collect(arena.run_arena(graph_app, "Which database?", thread_id, [A, B], {}, synthesizer=None))
    context = ContextSettings(system_prompt="Answer in one line.", summarizer=C)
    second = await arena.collect(arena.run_arena(
        graph_app, "" if deliberation else "What will it cost?", thread_id, [A, B], toggles or {"use_web_search": True},
        synthesizer=None, context=context, documents=DOC, is_deliberation=deliberation,
    ))
    b_reply = second["answers"][B]["checkpoint_id"]
    turn = await votes.turn_answers(graph_app, thread_id, b_reply)
    await votes.vote_turn(graph_app, thread_id, turn["turn_id"], "best", best=b_reply)
    return first, second


# ─── Saving ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_case_copies_the_turn_and_outlives_its_thread():
    async with arena.open_graph() as graph_app:
        first, second = await _two_turns(graph_app)
        case = await cases.save_case(graph_app, "t-case", second["answers"][B]["checkpoint_id"])

    assert case["question"] == "What will it cost?" and case["title"] == "What will it cost?"
    # B's branch: B continued its own answer, so A's first answer isn't in it.
    assert case["history_from"] == B
    assert [(m["role"], m["content"]) for m in case["history"]] == [
        ("user", "Which database?"), ("assistant", first["answers"][B]["content"])]
    assert case["history"][1]["model_name"] == "Claude Sonnet 5" and not case["summarized"]
    assert case["documents"] == [{"name": "brief.md", "characters": len(DOC["brief.md"])}]
    assert case["settings"] == {"use_web_search": True, "use_rag": False, "system_prompt": "Answer in one line.",
                                "summarizer": C, "is_deliberation": False}
    assert {a["model"]: a["content"] for a in case["answers"]} == {
        m: second["answers"][m]["content"] for m in (A, B)}
    assert case["vote"]["outcome"] == "best" and case["best_model"] == B
    assert case["source_thread_id"] == "t-case" and case["replays"] == []

    db.delete_thread_data("t-case")
    kept = cases.get_case(case["case_id"])
    assert kept["question"] == case["question"] and kept["answers"] == case["answers"]
    assert sorted(cases.list_cases()[0]["model_names"]) == ["Claude Sonnet 5", "GPT-5.4"]


@pytest.mark.asyncio
async def test_saving_by_turn_id_reads_the_first_answers_branch_and_a_vote_is_as_it_was():
    async with arena.open_graph() as graph_app:
        first, second = await _two_turns(graph_app)
        turn = await votes.turn_answers(graph_app, "t-case", second["answers"][A]["checkpoint_id"])
        case = await cases.save_case(graph_app, "t-case", turn["turn_id"], title="  Cost   question ")
        # A later vote doesn't change the case.
        await votes.vote_turn(graph_app, "t-case", turn["turn_id"], "tie")
    # The turn's first answer, in the order answered.
    earliest = turn["answers"][0]["model"]
    assert case["title"] == "Cost question" and case["history_from"] == earliest
    assert case["history"][1]["content"] == first["answers"][earliest]["content"]
    assert cases.get_case(case["case_id"])["vote"]["outcome"] == "best"


@pytest.mark.asyncio
async def test_saving_refuses_what_isnt_a_turn():
    async with arena.open_graph() as graph_app:
        await _two_turns(graph_app)
        with pytest.raises(ValueError, match="Thread nope not found"):
            await cases.save_case(graph_app, "nope", "x")
        with pytest.raises(ValueError, match="not found"):
            await cases.save_case(graph_app, "t-case", "no-such-turn")


# ─── Replaying ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_replay_runs_in_a_new_seeded_thread_and_never_touches_the_source():
    async with arena.open_graph() as graph_app:
        first, second = await _two_turns(graph_app)
        case = await cases.save_case(graph_app, "t-case", second["answers"][B]["checkpoint_id"])
        before = set(await thread_state_map(graph_app, "t-case"))
        SEEN.clear()
        replay = await cases.replay_case(graph_app, case["case_id"], [B, C])

        assert set(await thread_state_map(graph_app, "t-case")) == before
        thread = replay["thread_id"]
        assert thread != "t-case" and db.get_thread_title(thread) == "Replay: What will it cost?"
        # The case's history, documents, system prompt and question; not A's branch.
        sent = _sent(C)
        for text in ("Which database?", first["answers"][B]["content"], "The budget is 40k.", "Answer in one line.",
                     "What will it cost?"):
            assert text in sent, text
        assert first["answers"][A]["content"] not in sent
        assert ThreadDocumentStore().load(thread, ["brief.md"]) == DOC
        # The seeded history is context: the thread's transcript is the question and an answer.
        shown = (await history.thread_tree(graph_app, thread))["messages"]
        assert [m["role"] for m in shown] == ["user", "assistant"] and shown[0]["content"] == "What will it cost?"
        recorded = [s.metadata for s in (await thread_state_map(graph_app, thread)).values()]
        assert any(m.get("summarizer_model") == C and m.get("system_prompt") == "Answer in one line." for m in recorded)
        assert all(s.values.get("toggles", {}).get("use_web_search") for s in (await thread_state_map(graph_app, thread)).values()
                   if s.values.get("active_peer"))

    results = {r["model"]: r for r in replay["results"]}
    assert results[B]["baseline"] == {"model": B, "model_name": "Claude Sonnet 5", "reason": "same_model"}
    # C is new to the case: compared with the answer voted best (B's).
    assert results[C]["baseline"]["reason"] == "voted_best" and results[C]["baseline"]["model"] == B
    assert results[C]["diff"]["summary_text"] and not results[C]["diff"]["identical"]
    assert results[C]["content"].startswith(f"Reply from {C}")
    assert replay["question"] == "What will it cost?" and replay["models"] == [B, C]
    stored = cases.get_case(case["case_id"])
    assert [r["replay_id"] for r in stored["replays"]] == [replay["replay_id"]]
    assert cases.list_cases()[0]["replay_count"] == 1
    # The record outlives the replay's thread.
    db.delete_thread_data(thread)
    assert cases.get_case(case["case_id"])["replays"][0]["results"][1]["content"] == results[C]["content"]


@pytest.mark.asyncio
async def test_a_replay_defaults_to_the_cases_models_and_a_new_model_without_a_vote_has_no_baseline():
    async with arena.open_graph() as graph_app:
        first = await arena.collect(arena.run_arena(graph_app, "Hello?", "t-plain", [A, B], {}, synthesizer=None))
        case = await cases.save_case(graph_app, "t-plain", first["answers"][A]["checkpoint_id"])
        assert case["vote"] is None and case["history"] == [] and case["best_model"] is None
        replay = await cases.replay_case(graph_app, case["case_id"])
        assert sorted(replay["models"]) == sorted([A, B])
        assert all(r["baseline"]["reason"] == "same_model" for r in replay["results"])
        new = await cases.replay_case(graph_app, case["case_id"], [C])
    assert new["results"][0]["baseline"] is None and new["results"][0]["diff"] is None


@pytest.mark.asyncio
async def test_a_summary_in_the_history_is_kept_and_seeded_again():
    async with arena.open_graph() as graph_app:
        await seed_thread(graph_app, "t-sum", {"messages": [
            HumanMessage(content="Old question"), summary_message("They chose Postgres."),
            AIMessage(content="Old answer", name=A)]})
        turn = await arena.collect(arena.run_arena(graph_app, "And now?", "t-sum", [A, B], {}, synthesizer=None))
        case = await cases.save_case(graph_app, "t-sum", turn["answers"][A]["checkpoint_id"])
        assert case["summarized"]
        assert [m["kind"] for m in case["history"]] == [None, "summary", None]
        assert case["history"][1]["content"] == "They chose Postgres."
        assert case["history"][2]["model_name"] == "GPT-5.4"
        replay = await cases.replay_case(graph_app, case["case_id"], [C])
        seeded = [s for s in (await thread_state_map(graph_app, replay["thread_id"])).values() if is_seed(s)]
    # Seeded again as the graph held it: still a summary to the sanitizer, the reply still its model's.
    messages = seeded[0].values["messages"]
    assert [is_summary_message(m) for m in messages] == [False, True, False]
    assert messages[2].name == A


@pytest.mark.asyncio
async def test_a_deliberation_case_replays_as_one():
    async with arena.open_graph() as graph_app:
        _first, second = await _two_turns(graph_app, deliberation=True)
        case = await cases.save_case(graph_app, "t-case", second["answers"][A]["checkpoint_id"])
        assert case["settings"]["is_deliberation"]
        replay = await cases.replay_case(graph_app, case["case_id"], [C])
        states = (await thread_state_map(graph_app, replay["thread_id"])).values()
    assert any(s.values.get("is_deliberation") for s in states)


@pytest.mark.asyncio
async def test_a_case_that_searched_documents_indexes_them_for_the_replay(monkeypatch):
    searched = []
    monkeypatch.setattr("app.services.rag.retrieve_context", lambda q, thread_id, k=5: searched.append(thread_id) or [])
    async with arena.open_graph() as graph_app:
        ThreadDocumentStore().save("t-rag", {"paper.txt": "Findings: small.", "notes.md": "Unrelated."})
        turn = await arena.collect(arena.run_arena(graph_app, "Findings?", "t-rag", [A, B], {"use_rag": True},
                                                   synthesizer=None))
        case = await cases.save_case(graph_app, "t-rag", turn["answers"][A]["checkpoint_id"])
        assert case["settings"]["use_rag"] and case["documents"] == []
        assert {d["name"] for d in case["searched_documents"]} == {"paper.txt", "notes.md"}
        indexed = []
        replay = await cases.replay_case(graph_app, case["case_id"], [C],
                                         indexer=lambda text, name, tid: indexed.append((tid, name, text)))
    assert sorted(indexed) == [(replay["thread_id"], "notes.md", "Unrelated."),
                               (replay["thread_id"], "paper.txt", "Findings: small.")]
    assert searched[-1] == replay["thread_id"]


@pytest.mark.asyncio
async def test_replay_refusals():
    async with arena.open_graph() as graph_app:
        first = await arena.collect(arena.run_arena(graph_app, "Hello?", "t-r", [A, B], {}, synthesizer=None))
        case = await cases.save_case(graph_app, "t-r", first["answers"][A]["checkpoint_id"])
        for models, match in [(["gpt-9"], "Invalid model"), ([KEYLESS], "No API key")]:
            with pytest.raises(ValueError, match=match):
                await cases.replay_case(graph_app, case["case_id"], models)
        with pytest.raises(ValueError, match="Case nope not found"):
            await cases.replay_case(graph_app, "nope", [A])
    assert cases.get_case(case["case_id"])["replays"] == []
    with pytest.raises(ValueError, match="not found"):
        cases.delete_case("nope")
    cases.delete_case(case["case_id"])
    assert cases.list_cases() == []


def test_the_readable_history_leaves_out_synthesis_prompts():
    from app.services.runs import SYNTHESIS_TURN, TURN_KIND_KEY

    shown = cases._readable_history(messages_to_dict([
        HumanMessage(content="Merge these", additional_kwargs={TURN_KIND_KEY: SYNTHESIS_TURN}),
        AIMessage(content="Merged", name=B),
    ]))
    assert shown == [{"role": "assistant", "kind": None, "content": "Merged", "model": B, "model_name": "Claude Sonnet 5"}]


# ─── REST ────────────────────────────────────────────────────────


def test_rest_routes():
    async def make():
        async with arena.open_graph() as graph_app:
            return await arena.collect(arena.run_arena(graph_app, "Hello?", "t-rest", [A, B], {}, synthesizer=None))

    turn = asyncio.run(make())
    with TestClient(server) as client:
        res = client.post("/cases", json={"thread_id": "t-rest", "turn": turn["answers"][B]["checkpoint_id"]})
        assert res.status_code == 200, res.text
        case_id = res.json()["case_id"]
        assert client.post("/cases", json={"thread_id": "t-rest", "turn": "nope"}).status_code == 404
        assert [c["case_id"] for c in client.get("/cases").json()["cases"]] == [case_id]

        res = client.post(f"/cases/{case_id}/replay", json={"models": [C]})
        assert res.status_code == 200, res.text
        assert res.json()["results"][0]["model_name"] == "Gemini 3.1 Pro"
        assert client.post(f"/cases/{case_id}/replay", json={"models": [KEYLESS]}).status_code == 400
        assert client.post("/cases/nope/replay", json={}).status_code == 404

        got = client.get(f"/cases/{case_id}").json()
        assert len(got["replays"]) == 1 and got["replays"][0]["results"][0]["baseline"] is None
        assert client.get("/cases/nope").status_code == 404
        assert client.delete(f"/cases/{case_id}").json() == {"deleted": case_id}
        assert client.delete(f"/cases/{case_id}").status_code == 404


# ─── CLI ─────────────────────────────────────────────────────────

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


def test_cli_save_list_show_replay_and_delete():
    out = _json(["arena", "Which database?", "-m", A, "-m", B, "-t", "t-cli", "--no-synthesize"])
    reply = out["answers"][A]["checkpoint_id"]
    case = _json(["cases", "save", reply, "-t", "t-cli", "--title", "DB choice"])
    assert case["title"] == "DB choice"
    assert [c["case_id"] for c in _json(["cases", "list"])["cases"]] == [case["case_id"]]

    # Asked first: declining runs nothing.
    declined = runner.invoke(cli_app, ["replay", case["case_id"], "-m", C], input="n\n")
    assert declined.exit_code == 0 and "Not replayed" in declined.stderr
    assert "Gemini 3.1 Pro (gemini-3.1-pro-preview)" in declined.stderr
    assert _json(["cases", "show", case["case_id"]])["replays"] == []

    accepted = runner.invoke(cli_app, ["replay", case["case_id"], "-m", C], input="y\n")
    assert accepted.exit_code == 0, (accepted.stdout, accepted.stderr)
    assert "nothing to compare with" in accepted.stdout

    replay = _json(["replay", case["case_id"], "--yes"])
    assert sorted(replay["models"]) == sorted([A, B]) and all(r["diff"] for r in replay["results"])
    shown = runner.invoke(cli_app, ["cases", "show", case["case_id"]])
    assert shown.exit_code == 0 and "Which database?" in shown.stdout and "its own answer in the case" in shown.stdout
    assert len(_json(["cases", "show", case["case_id"]])["replays"]) == 2

    _fails(["replay", case["case_id"], "-m", KEYLESS, "--yes"], "No API key")
    _fails(["replay", "nope", "--yes"], "Case nope not found")
    _fails(["cases", "show", "nope"], "not found")
    _fails(["cases", "save", "nope", "-t", "t-cli"], "not found")
    assert _json(["cases", "delete", case["case_id"], "--yes"]) == {"deleted": case["case_id"]}
    _fails(["cases", "delete", case["case_id"], "--yes"], "not found")


# ─── MCP ─────────────────────────────────────────────────────────


@pytest.fixture
def mcp_server():
    from app.mcp_server import mcp

    return mcp


async def _call(client, tool, args):
    return (await client.call_tool(tool, args)).data


@pytest.mark.asyncio
async def test_mcp_tools(mcp_server):
    async with Client(mcp_server) as client:
        first = await _call(client, "invoke_arena", {"prompt": "Hello?", "models": [A, B], "synthesize": False})
        thread = first["thread_id"]
        case = await _call(client, "save_case", {"thread_id": thread, "turn": first["answers"][0]["checkpoint_id"]})
        assert [c["case_id"] for c in (await _call(client, "list_cases", {}))["cases"]] == [case["case_id"]]
        replay = await _call(client, "replay_case", {"case_id": case["case_id"], "models": [A]})
        assert replay["results"][0]["baseline"]["reason"] == "same_model" and "total" in replay
        assert (await _call(client, "get_case", {"case_id": case["case_id"]}))["replays"][0]["replay_id"] == \
            replay["replay_id"]
        with pytest.raises(ToolError, match="No API key"):
            await client.call_tool("replay_case", {"case_id": case["case_id"], "models": [KEYLESS]})
        with pytest.raises(ToolError, match="not found"):
            await client.call_tool("get_case", {"case_id": "nope"})
        assert await _call(client, "delete_case", {"case_id": case["case_id"]}) == {"deleted": case["case_id"]}
        tools = {t.name: t for t in await client.list_tools()}
    for name in ("save_case", "get_case", "replay_case", "list_cases"):
        assert "Returns" in tools[name].description, name
