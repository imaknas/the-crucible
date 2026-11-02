"""Anonymous peer review: every author scores the other answers, never its
own, without model names and in its own order; the result is stored as
evidence and reached from REST, the CLI and MCP."""

import json
import os
import re
from unittest.mock import patch

import pytest
from fastmcp import Client
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage
from typer.testing import CliRunner

from app.cli import app as cli_app
from app.core import database as db
from app.llm import CallableModelFactory, use_model_factory
from app.services import arena, review
from tests.storage_helpers import point

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B, C = "gpt-5.4", "claude-sonnet-5", "gemini-3.1-pro-preview"
PROMPTS: dict = {}


class _Reviewer(FakeListChatModel):
    """Answers a turn with its own text; asked to review, scores every letter
    it is shown (7, or 3 for the answer that says "weak")."""

    model_id: str = ""

    async def ainvoke(self, messages, config=None, **kwargs):
        prompt = messages[-1].content
        PROMPTS[self.model_id] = prompt
        if self.model_id == C:
            raise RuntimeError("reviewer down")
        blocks = re.findall(r"\[([A-Z])\]:\n(.*?)(?=\n\n\[|\n\nScore each)", prompt, re.S)
        return AIMessage(content="\n".join(f"{label}: {3 if 'weak' in text else 7} — reads well" for label, text in blocks))


def _model(model_id, _toggles):
    answer = {A: "strong answer from A", B: "weak answer from B", C: "answer from C"}[model_id]
    return _Reviewer(responses=[answer], model_id=model_id)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    PROMPTS.clear()
    point(monkeypatch, db_path=str(tmp_path / "review.sqlite"))
    monkeypatch.setattr("app.cli._load_env", lambda: None)
    db.init_db()
    with use_model_factory(CallableModelFactory(_model)), patch.dict(os.environ, KEYS):
        yield


async def _turn(graph_app, thread_id, models=(A, B)):
    result = await arena.collect(arena.run_arena(graph_app, "Which?", thread_id, list(models), {}, synthesizer=None))
    return [result["answers"][m]["checkpoint_id"] for m in models]


def test_scores_parse_in_several_dash_forms_and_none_is_an_error():
    assert review.parse_scores("A: 7 — good\nB: 4/10 - thin\nZ: 9 — not shown", ["A", "B"]) == {
        "A": (7, "good"),
        "B": (4, "thin"),
    }
    with pytest.raises(ValueError, match="no scores"):
        review.parse_scores("They are both fine.", ["A", "B"])


@pytest.mark.asyncio
async def test_each_author_scores_the_others_never_its_own_and_without_names():
    async with arena.open_graph() as graph_app:
        ids = await _turn(graph_app, "t-rev")
        result = await review.review_answers(graph_app, "t-rev", ids)

    by_model = {a["model"]: a for a in result["answers"]}
    # A scored B's answer, B scored A's: one score each, never their own.
    assert [s["reviewer"] for s in by_model[A]["scores"]] == [B]
    assert [s["reviewer"] for s in by_model[B]["scores"]] == [A]
    assert (by_model[A]["average"], by_model[B]["average"]) == (7.0, 3.0)
    assert "strong answer from A" not in PROMPTS[A] and "weak answer from B" in PROMPTS[A]
    for prompt in PROMPTS.values():
        assert "gpt" not in prompt.lower() and "claude" not in prompt.lower()
    assert sorted(a["label"] for a in result["answers"]) == ["A", "B"]


@pytest.mark.asyncio
async def test_a_failed_reviewer_is_an_error_and_the_review_is_stored_and_deleted_with_its_thread():
    async with arena.open_graph() as graph_app:
        ids = await _turn(graph_app, "t-rev3", (A, B, C))
        result = await review.review_answers(graph_app, "t-rev3", ids)
    assert "reviewer down" in result["errors"][C]
    assert all(s["reviewer"] != C for a in result["answers"] for s in a["scores"])
    assert review.reviews_of("t-rev3")[0]["review_key"] == review.review_key(list(reversed(ids)))

    db.delete_thread_data("t-rev3")
    assert review.reviews_of("t-rev3") == []


@pytest.mark.asyncio
async def test_answers_by_one_model_cannot_be_peer_reviewed():
    async with arena.open_graph() as graph_app:
        first = await _turn(graph_app, "t-solo", (A,))
        second = await _turn(graph_app, "t-solo", (A,))
        with pytest.raises(ValueError, match="at least two different models"):
            await review.review_answers(graph_app, "t-solo", first + second)


def test_cli_and_rest_run_and_list_reviews():
    from fastapi.testclient import TestClient

    from app.main import server

    runner = CliRunner()
    assert runner.invoke(cli_app, ["arena", "Which?", "-m", A, "-m", B, "--no-synthesize", "-t", "t-cli"]).exit_code == 0
    ran = runner.invoke(cli_app, ["review", "-t", "t-cli", "--format", "json"])
    assert ran.exit_code == 0, ran.stderr
    assert {a["model"] for a in json.loads(ran.stdout)["answers"]} == {A, B}
    shown = runner.invoke(cli_app, ["review", "-t", "t-cli"])
    assert "evidence, not a verdict" in shown.stdout

    with TestClient(server) as client:
        listed = client.get("/synthesis/reviews/t-cli").json()["reviews"]
        assert len(listed) == 1
        refused = client.post("/synthesis/reviews", json={"thread_id": "t-cli", "checkpoint_ids": listed[0]["checkpoint_ids"][:1]})
        assert refused.status_code == 400


@pytest.mark.asyncio
async def test_mcp_review_tools():
    from app.mcp_server import mcp

    async with Client(mcp) as client:
        turn = (await client.call_tool("invoke_arena", {"prompt": "Which?", "models": [A, B], "synthesize": False})).data
        reviewed = (await client.call_tool("review_answers", {"thread_id": turn["thread_id"]})).data
        assert {a["model"] for a in reviewed["answers"]} == {A, B}
        listed = (await client.call_tool("list_answer_reviews", {"thread_id": turn["thread_id"]})).data
        assert listed["reviews"][0]["review_key"] == reviewed["review_key"]
