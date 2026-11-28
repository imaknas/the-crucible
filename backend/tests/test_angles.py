"""Per-model angles: in one arena turn each model can answer from its own
angle (a review's security, its cost, the case against it).

The question stays the same for every model of the turn (the tree merges it
by its text, and synthesis, joining, cases and votes all read one question);
the angle goes with that model's system prompt, stays on its reply, and is
never the synthesizer's. A debate refuses one: participants get sides."""

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
from app.services import arena, cases, history, votes
from app.services.context import MAX_ANGLE_CHARS, ContextSettings
from app.services.debate import DebateRefused, _run_settings
from tests.storage_helpers import point

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B = "gpt-5.4", "claude-sonnet-5"
CALLS: list = []  # (model, system text, last human text)


def _text(content) -> str:
    if isinstance(content, list):
        return "\n".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content)


class _Recorder(FakeListChatModel):
    model_id: str = ""

    def _record(self, messages):
        system = "\n".join(_text(m.content) for m in messages if m.type == "system")
        human = next((_text(m.content) for m in reversed(messages) if m.type == "human"), "")
        CALLS.append((self.model_id, system, human))

    def _call(self, messages, *args, **kwargs):
        self._record(messages)
        return super()._call(messages, *args, **kwargs)

    def _stream(self, messages, *args, **kwargs):
        self._record(messages)
        yield from super()._stream(messages, *args, **kwargs)


def _model(model_id, _toggles):
    return _Recorder(responses=[f"reply from {model_id}"], model_id=model_id)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    CALLS.clear()
    point(monkeypatch, db_path=str(tmp_path / "angles.sqlite"))
    monkeypatch.setattr("app.cli._load_env", lambda: None)
    with use_model_factory(CallableModelFactory(_model)), patch.dict(os.environ, KEYS):
        yield


def _drafts(model):
    """The answering calls a model got (a summary or recall call has no reply text)."""
    return [c for c in CALLS if c[0] == model]


@pytest.mark.asyncio
async def test_each_model_reads_only_its_own_angle_and_the_same_question():
    async with arena.open_graph() as graph_app:
        result = await arena.collect(arena.run_arena(
            graph_app, "Review this plan.", "t-angles", [A, B], {}, synthesizer=A,
            angles={A: "its security"},
        ))
        tree = await history.thread_tree(graph_app, "t-angles")
        path = await history.path_at(graph_app, "t-angles", result["answers"][A]["checkpoint_id"])

    (_, system_a, human_a), (_, system_b, human_b) = _drafts(A)[0], _drafts(B)[0]
    assert "Answer from this angle: its security" in system_a
    assert "angle" not in system_b
    # The question as asked (a request note with the time rides after it).
    assert human_a.splitlines()[0] == human_b.splitlines()[0] == "Review this plan."

    # One question node, each reply says its angle.
    questions = [n for n in tree["nodes"] if n["metadata"].get("role") == "user"]
    assert len(questions) == 1
    replies = {n["metadata"]["active_peer"]: n for n in tree["nodes"]
               if n["metadata"].get("role") == "ai" and n.get("type") != "synthesis"}
    assert replies[A]["metadata"]["angle"] == "its security"
    assert replies[B]["metadata"]["angle"] is None
    assert result["answers"][A]["angle"] == "its security" and result["answers"][B]["angle"] is None
    messages = path["messages"] if isinstance(path, dict) else path
    assert messages[-1]["angle"] == "its security"

    # The synthesizer is told who had which angle, and has none of its own.
    synthesis_system, synthesis_prompt = _drafts(A)[-1][1], _drafts(A)[-1][2]
    assert "(asked to answer from this angle: its security)" in synthesis_prompt
    assert "Answer from this angle" not in synthesis_system
    assert result["synthesis"]["error"] is None


@pytest.mark.asyncio
async def test_an_issue_list_names_the_angle_each_problem_was_seen_from():
    async with arena.open_graph() as graph_app:
        result = await arena.collect(arena.run_arena(
            graph_app, "Review this plan.", "t-issues", [A, B], {}, angles={A: "cost", B: "the case against it"},
        ))
        ids = [result["answers"][m]["checkpoint_id"] for m in (A, B)]
        CALLS.clear()
        await arena.collect(arena.synthesize_thread(graph_app, "t-issues", A, checkpoint_ids=ids, mode="issues"))

    prompt = CALLS[-1][2]
    assert "(asked to answer from this angle: cost)" in prompt
    assert "(asked to answer from this angle: the case against it)" in prompt
    assert "Answer from this angle" not in CALLS[-1][1]


@pytest.mark.asyncio
async def test_an_angle_for_a_model_not_answering_or_too_long_is_refused():
    async with arena.open_graph() as graph_app:
        with pytest.raises(ValueError, match="isn't answering"):
            await arena.collect(arena.run_arena(graph_app, "Q?", "t-bad", [A], {}, angles={B: "cost"}))
        with pytest.raises(ValueError, match="the limit is"):
            await arena.collect(arena.run_arena(graph_app, "Q?", "t-bad", [A], {}, angles={A: "x" * (MAX_ANGLE_CHARS + 1)}))
    assert CALLS == []


@pytest.mark.asyncio
async def test_a_vote_is_refused_when_the_answers_had_different_angles():
    async with arena.open_graph() as graph_app:
        result = await arena.collect(arena.run_arena(graph_app, "Q?", "t-vote", [A, B], {}, angles={A: "cost"}))
        turn = result["answers"][A]["checkpoint_id"]
        assert votes.angles_differ((await votes.turn_answers(graph_app, "t-vote", turn))["answers"])
        with pytest.raises(ValueError, match="different angles"):
            await votes.vote_turn(graph_app, "t-vote", turn, "tie")

        same = await arena.collect(arena.run_arena(graph_app, "Q2?", "t-vote", [A, B], {}, angles={A: "cost", B: "cost"}))
        stored = await votes.vote_turn(graph_app, "t-vote", same["answers"][A]["checkpoint_id"], "tie")
    assert stored["outcome"] == "tie"


@pytest.mark.asyncio
async def test_a_case_keeps_each_answers_angle_and_a_replay_gives_it_again():
    async with arena.open_graph() as graph_app:
        result = await arena.collect(arena.run_arena(graph_app, "Review this plan.", "t-case", [A, B], {},
                                                     angles={A: "its security"}))
        case = await cases.save_case(graph_app, "t-case", result["answers"][A]["checkpoint_id"])
        assert {a["model"]: a["angle"] for a in case["answers"]} == {A: "its security", B: None}
        CALLS.clear()
        replay = await cases.replay_case(graph_app, case["case_id"], indexer=lambda *a: None)

    assert "Answer from this angle: its security" in _drafts(A)[0][1]
    assert "angle" not in _drafts(B)[0][1]
    assert {r["model"]: r["angle"] for r in replay["results"]} == {A: "its security", B: None}


def test_a_debate_takes_no_angle():
    with pytest.raises(DebateRefused, match="no angle"):
        _run_settings({"settings": {}}, {}, ContextSettings(angle="cost"))
    with pytest.raises(DebateRefused, match="no angle"):
        _run_settings({"settings": {"angle": "cost"}}, None, None)


def test_a_blank_angle_is_none():
    assert ContextSettings.from_frame({"angle": "   "}).angle is None
    assert ContextSettings.from_frame({"angle": " cost "}).angle == "cost"
    assert ContextSettings.from_frame({"angle": 3}).problem() == "An angle must be text."


# ─── CLI and MCP ─────────────────────────────────────────────────


runner = CliRunner()


def test_cli_angles():
    bad = runner.invoke(cli_app, ["arena", "Q?", "-m", A, "-m", B, "--angle", "security"])
    assert bad.exit_code == 2 and "MODEL=ANGLE" in bad.output
    stray = runner.invoke(cli_app, ["arena", "Q?", "-m", A, "--angle", f"{B}=cost"])
    assert stray.exit_code == 2

    out = runner.invoke(cli_app, ["arena", "Review it.", "-m", A, "-m", B, "--angle", f"{A}=its cost",
                                  "--no-synthesize", "-t", "t-cli", "--format", "json"])
    assert out.exit_code == 0, out.output
    answers = json.loads(out.stdout)["answers"]
    assert answers[A]["angle"] == "its cost" and answers[B]["angle"] is None

    single = runner.invoke(cli_app, ["chat", "Review it.", "-m", A, "--angle", "the case against it",
                                     "-t", "t-cli-chat", "--format", "json"])
    assert single.exit_code == 0, single.output
    assert json.loads(single.stdout)["angle"] == "the case against it"


@pytest.mark.asyncio
async def test_mcp_angles():
    from app.mcp_server import mcp

    async with Client(mcp) as client:
        result = (await client.call_tool("invoke_arena", {
            "prompt": "Review it.", "models": [A, B], "synthesize": False, "angles": {B: "cost"},
        })).structured_content
        assert {a["model"]: a["angle"] for a in result["answers"]} == {A: None, B: "cost"}
        with pytest.raises(ToolError, match="isn't answering"):
            await client.call_tool("invoke_arena", {"prompt": "Q?", "models": [A], "angles": {B: "cost"}})


# ─── The socket and POST /chat ───────────────────────────────────


def _ws_turn(client, thread_id, frame):
    with client.websocket_connect(f"/ws/{thread_id}") as ws:
        ws.send_json(frame)
        while (msg := ws.receive_json())["type"] not in ("stream_end", "error"):
            pass
    return msg


def test_a_socket_frame_and_post_chat_carry_an_angle():
    from fastapi.testclient import TestClient

    from app.main import server

    with TestClient(server) as client:
        end = _ws_turn(client, "t-ws", {"message": "Review it.", "model": A, "angle": "its cost"})
        assert end["type"] == "stream_end" and end["angle"] == "its cost", end
        refused = _ws_turn(client, "t-ws2", {"message": "Q?", "model": A, "angle": "x" * (MAX_ANGLE_CHARS + 1)})
        assert refused["type"] == "error" and "limit" in refused["message"]
        r = client.post("/chat", json={"message": "Review it.", "thread_id": "t-rest", "model": B, "angle": "risk"})
        assert r.status_code == 200, r.text
        limits = client.get("/models").json()["limits"]
    assert "Answer from this angle: its cost" in _drafts(A)[0][1]
    assert "Answer from this angle: risk" in _drafts(B)[0][1]
    assert limits["max_angle_chars"] == MAX_ANGLE_CHARS
