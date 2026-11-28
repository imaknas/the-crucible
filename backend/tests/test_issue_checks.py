"""Checking an issue list problem by problem (services/checks.py).

The checkers read the source (the question and its attached documents) and
the problems, never who raised them; they don't see each other; their
verdicts are shown side by side, never tallied."""

import asyncio
import json
import os
from unittest.mock import patch

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from typer.testing import CliRunner

from app.cli import app as cli_app
from app.core import database as db
from app.llm import CallableModelFactory, use_model_factory
from app.llm.fake import ScriptedModelFactory
from app.registry import display_name
from app.services import arena, checks, history
from app.services.synthesis import Issue, parse_issues
from tests.storage_helpers import point

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B = "gpt-5.4", "claude-sonnet-5"
PLAN = "Step 1: migrate the database. Step 2: switch traffic. There is no backup step."


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    point(monkeypatch, db_path=str(tmp_path / "checks.sqlite"))
    monkeypatch.setattr("app.cli._load_env", lambda: None)
    with use_model_factory(ScriptedModelFactory(delay=0)), patch.dict(os.environ, KEYS):
        yield


async def _issue_list(graph_app, thread_id="t-check", documents=None):
    result = await arena.collect(arena.run_arena(
        graph_app, "Review this plan.", thread_id, [A, B], {}, synthesizer=A,
        documents=documents if documents is not None else {"plan.md": PLAN},
    ))
    ids = [result["answers"][m]["checkpoint_id"] for m in (A, B)]
    synthesis = await arena.collect(arena.synthesize_thread(graph_app, thread_id, A, checkpoint_ids=ids, mode="issues"))
    return synthesis["synthesis"]["checkpoint_id"]


# ─── The parsers ─────────────────────────────────────────────────


def test_an_issue_list_is_read_in_its_numbered_form():
    text = (
        "1. **No rollback.** If the migration fails\n   halfway, data is lost.\n"
        "   Raised by: GPT-5.4, Claude Sonnet 5\n   Why: There is no backup step.\n"
        "3) Cost is low-balled.\n   - **Raised by:** Claude Sonnet 5 (asked to answer from this angle: cost, mostly)\n"
        "   - **Why:** Egress is left out.\n\n"
        "Where the reviews contradict each other:\n1. GPT-5.4 calls the cost fine.\n"
    )
    issues = parse_issues(text)
    assert [i.number for i in issues] == [1, 2]  # by position, and the contradictions aren't problems
    assert issues[0].problem == "No rollback. If the migration fails halfway, data is lost."
    assert issues[0].why == "There is no backup step."
    assert checks.raised_by_models(issues[0], [A, B]) == [A, B]
    assert checks.raised_by_models(issues[1], [A, B]) == [B]


def test_a_list_in_another_form_is_an_error_not_an_empty_check():
    with pytest.raises(ValueError, match="numbered form"):
        parse_issues("The reviews mostly worry about the migration and its cost.")


def test_a_raised_by_label_matches_a_whole_model_name():
    issue = Issue(number=1, problem="p", raised_by="GPT-5.4 mini", why="")
    assert checks.raised_by_models(issue, ["gpt-5.4", "gpt-5.4-mini"]) == ["gpt-5.4-mini"]


def test_a_lettered_raised_by_goes_through_the_lists_legend():
    legend = [{"label": "Answer A", "model": B}, {"label": "Answer B", "model": A}]
    issue = Issue(number=1, problem="p", raised_by="Answer B, Answer A (asked to answer from this angle: cost)", why="")
    assert checks.raised_by_models(issue, [A, B], legend) == [A, B]
    assert checks.revealed("Answer B, Answer A", legend) == "Answer B (GPT-5.4), Answer A (Claude Sonnet 5)"
    # A list written before letters has no legend and keeps its names.
    assert checks.revealed("GPT-5.4", None) == "GPT-5.4"


def test_verdicts_are_read_line_by_line():
    text = "1: holds — Step 2 has no backup.\n**2**: Doesn't hold – step 3 is a backup.\n3. can’t tell - not said.\nnoise"
    assert checks.parse_verdicts(text, [1, 2, 3]) == {
        1: ("holds", "Step 2 has no backup."),
        2: ("does_not_hold", "step 3 is a backup."),
        3: ("cant_tell", "not said."),
    }
    with pytest.raises(ValueError, match="no verdicts"):
        checks.parse_verdicts("I think they all hold.", [1])


# ─── A check ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_each_problem_is_checked_by_every_reviewer_against_the_source():
    prompts: list = []

    class Recorder(FakeListChatModel):
        model_id: str = ""

        def _call(self, messages, *args, **kwargs):
            prompts.append((self.model_id, messages[-1].content))
            return super()._call(messages, *args, **kwargs)

    async with arena.open_graph() as graph_app:
        node = await _issue_list(graph_app)
        replies = {A: "1: holds — no backup step.\n2: does not hold — handled.",
                   B: "1: holds — 'There is no backup step.'"}
        factory = CallableModelFactory(lambda m, _t: Recorder(responses=[replies[m]], model_id=m))
        check = await checks.check_issues(graph_app, "t-check", node, factory=factory)
        stored = checks.checks_of("t-check")

    # The reviewers check, in the order the list read them (by letter).
    assert sorted(c["model"] for c in check["checkers"]) == sorted([A, B]) and check["errors"] == {}
    assert check["checkpoint_id"] == node and check["documents"] == ["plan.md"]
    first, second = check["issues"]
    assert sorted((v["checker"], v["verdict"]) for v in first["verdicts"]) == sorted([(A, "holds"), (B, "holds")])
    assert not first["disagree"]
    # B gave no verdict on the second problem: no row for it, not a guess.
    assert [(v["checker"], v["verdict"]) for v in second["verdicts"]] == [(A, "does_not_hold")]
    # The scripted list says the first problem was raised by the first
    # label, "Answer A": the check names its model and marks its own verdict.
    lettered_a = check["checkers"][0]["model"]
    assert first["raised_by"] == f"Answer A ({display_name(lettered_a)})"
    assert first["raised_by_models"] == [lettered_a]
    assert [v["checker"] for v in first["verdicts"] if v["own"]] == [lettered_a]
    assert stored == [check]

    # Each checker read the source and the problems, not who raised them.
    for _model, prompt in prompts:
        assert PLAN in prompt and "Review this plan." in prompt
        assert "Scripted problem one" in prompt and "Scripted problem two" in prompt
        assert "Raised by" not in prompt and "GPT-5.4" not in prompt and "Claude Sonnet 5" not in prompt


@pytest.mark.asyncio
async def test_a_failed_checker_is_an_error_and_named_checkers_replace_the_reviewers():
    async with arena.open_graph() as graph_app:
        node = await _issue_list(graph_app, documents={})
        failing = CallableModelFactory(lambda m, _t: FakeListChatModel(responses=["They all hold, I think."]))
        check = await checks.check_issues(graph_app, "t-check", node, [B], factory=failing)
    assert [c["model"] for c in check["checkers"]] == [B]
    assert "no verdicts" in check["errors"][B]
    assert all(row["verdicts"] == [] for row in check["issues"])
    assert check["documents"] == []


@pytest.mark.asyncio
async def test_only_an_issue_list_can_be_checked():
    async with arena.open_graph() as graph_app:
        result = await arena.collect(arena.run_arena(graph_app, "Review this plan.", "t-merge", [A, B], {}, synthesizer=A))
        with pytest.raises(ValueError, match="Only an issue list"):
            await checks.check_issues(graph_app, "t-merge", result["synthesis"]["checkpoint_id"])
        with pytest.raises(ValueError, match="Only an issue list"):
            await checks.check_issues(graph_app, "t-merge", result["answers"][A]["checkpoint_id"])
        with pytest.raises(ValueError, match="not on thread"):
            await checks.check_issues(graph_app, "t-merge", "nope")
        with pytest.raises(ValueError, match="not found"):
            await checks.check_issues(graph_app, "t-nothing", "nope")


@pytest.mark.asyncio
async def test_a_check_is_deleted_with_its_branch_and_its_thread():
    async with arena.open_graph() as graph_app:
        node = await _issue_list(graph_app)
        await checks.check_issues(graph_app, "t-check", node)
        assert len(checks.checks_of("t-check")) == 1
        await history.delete_branch(graph_app, "t-check", node)
        assert checks.checks_of("t-check") == []

        node = await _issue_list(graph_app, "t-check2")
        await checks.check_issues(graph_app, "t-check2", node)
    db.delete_thread_data("t-check2")
    assert checks.checks_of("t-check2") == []


# ─── CLI, MCP and REST ───────────────────────────────────────────


runner = CliRunner()


def _make_list(thread_id="t-check"):
    async def go():
        async with arena.open_graph() as graph_app:
            return await _issue_list(graph_app, thread_id)

    return asyncio.run(go())


def test_cli_and_rest_check_an_issue_list():
    from fastapi.testclient import TestClient

    from app.main import server

    node = _make_list()
    out = runner.invoke(cli_app, ["check", node, "-t", "t-check", "--format", "json"])
    assert out.exit_code == 0, out.output
    check = json.loads(out.stdout)
    assert [row["verdicts"][0]["verdict"] for row in check["issues"]] == ["holds", "cant_tell"]
    listed = runner.invoke(cli_app, ["check", "--list", "-t", "t-check", "--format", "json"])
    assert json.loads(listed.stdout)["checks"][0]["checkpoint_id"] == node
    shown = runner.invoke(cli_app, ["check", node, "-t", "t-check", "-m", A])
    assert shown.exit_code == 0 and "Holds" in shown.output and "Can't tell" in shown.output
    assert runner.invoke(cli_app, ["check", "-t", "t-check"]).exit_code == 2

    with TestClient(server) as client:
        r = client.post("/synthesis/checks", json={"thread_id": "t-check", "checkpoint_id": node, "models": [B]})
        assert r.status_code == 200, r.text
        assert [c["model"] for c in r.json()["checkers"]] == [B]
        assert client.get("/synthesis/checks/t-check").json()["checks"][0]["checkers"][0]["model"] == B
        assert client.post("/synthesis/checks", json={"thread_id": "t-check", "checkpoint_id": "nope"}).status_code == 400


@pytest.mark.asyncio
async def test_mcp_checks_an_issue_list():
    from app.mcp_server import mcp

    async with arena.open_graph() as graph_app:
        node = await _issue_list(graph_app)
    async with Client(mcp) as client:
        result = (await client.call_tool("check_issues", {"thread_id": "t-check", "checkpoint_id": node})).structured_content
        assert len(result["issues"]) == 2
        assert (await client.call_tool("list_issue_checks", {"thread_id": "t-check"})).structured_content["checks"]
        with pytest.raises(ToolError, match="not on thread"):
            await client.call_tool("check_issues", {"thread_id": "t-check", "checkpoint_id": "nope"})
