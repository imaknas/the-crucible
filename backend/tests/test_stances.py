"""Assigned sides and a devil's advocate: what each model is told, what the
others see of it, what the synthesizer and the record read, and the checks
and surfaces (REST, CLI, MCP)."""

import json
import os
from unittest.mock import patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.core import database as db
from app.llm import CallableModelFactory, use_model_factory
from app.services import debate as debate_svc
from app.services.arena import open_graph
from app.services.peers import AnonymousPeers
from app.services.stances import AssignedSides, DevilsAdvocate, check_stance, stance_from_choices
from tests.storage_helpers import point

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B, C = "gpt-5.4", "claude-sonnet-5", "gemini-3.1-pro-preview"
POLICY = {"max_rounds": 2, "convergence_threshold": None, "llm_judge": None, "mode": "all"}
SEEN: dict[str, list[str]] = {}


class _Recorder(FakeListChatModel):
    model_id: str = ""

    def _record(self, messages):
        SEEN.setdefault(self.model_id, []).append("\n".join(str(m.content) for m in messages))

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
    SEEN.clear()
    point(monkeypatch, db_path=str(tmp_path / "stances.sqlite"))
    monkeypatch.setattr("app.cli._load_env", lambda: None)
    db.init_db()
    with use_model_factory(CallableModelFactory(_model)), patch.dict(os.environ, KEYS):
        yield


def test_the_checks_refuse_what_cant_run():
    check_stance(None, [A, B], None)
    with pytest.raises(ValueError, match="agreement judge"):
        check_stance({"mode": "sides", "sides": {A: "Yes", B: "No"}}, [A, B], C)
    with pytest.raises(ValueError, match="needs a side"):
        check_stance({"mode": "sides", "sides": {A: "Yes"}}, [A, B], None)
    with pytest.raises(ValueError, match="two different sides"):
        check_stance({"mode": "sides", "sides": {A: "Yes", B: " yes "}}, [A, B], None)
    with pytest.raises(ValueError, match="one of the participants"):
        check_stance({"mode": "advocate", "advocate": C}, [A, B], None)
    assert stance_from_choices([A, B, C], ["Yes", "No"])["sides"] == {A: "Yes", B: "No", C: "Yes"}
    with pytest.raises(ValueError, match="not both"):
        stance_from_choices([A, B], ["Yes", "No"], A)


def test_sides_are_briefed_in_the_first_round_and_shown_to_everyone_after():
    peers = AnonymousPeers("s1", [A, B])
    sides = AssignedSides({A: "Remote work is better", B: "Office work is better"})
    first = debate_svc._build_round_prompts(0, "Remote or office?", [A, B], {}, peers, stance=sides)
    assert "Your side: Remote work is better" in first[A] and "Office work is better" not in first[A]
    later = debate_svc._build_round_prompts(1, "Remote or office?", [A, B], {A: "a says", B: "b says"}, peers,
                                            stance=sides)
    assert f"[{peers.label(B)} — arguing: Office work is better]" in later[A]
    assert "Your assigned side is still: Remote work is better" in later[A] and "Don't switch sides" in later[A]
    # The open closing ("State your position now…") would contradict the side.
    assert "State your position now" not in later[A]


def test_the_advocate_is_told_from_round_two_and_nobody_else_is_told_who_it_is():
    peers = AnonymousPeers("s2", [A, B, C])
    advocate = DevilsAdvocate(C)
    first = debate_svc._build_round_prompts(0, "Is X true?", [A, B, C], {}, peers, stance=advocate)
    assert all(p == "Is X true?" for p in first.values())  # everyone answers for itself first
    later = debate_svc._build_round_prompts(1, "Is X true?", [A, B, C], {m: f"{m} says" for m in (A, B, C)}, peers,
                                            stance=advocate)
    assert "devil's advocate" in later[C]
    for m in (A, B):
        assert "devil" not in later[m] and "State your position now" in later[m]


@pytest.mark.asyncio
async def test_an_assigned_sides_debate_end_to_end():
    stance = {"mode": "sides", "sides": {A: "Yes", B: "No"}}
    session = debate_svc.create_session("t-sides", [A, B], dict(POLICY), auto_synthesize=True, synthesizer_model=C,
                                        stance=stance)
    async with open_graph() as graph_app:
        events = [e async for e in debate_svc.run_debate(graph_app, session["session_id"], "Is it worth it?", {}, {})]
        assert events[-1]["status"] == "completed", events
        tree = await debate_svc.debate_tree(graph_app, db.get_debate_session(session["session_id"]))
        stored = db.get_debate_session(session["session_id"])
        record = debate_svc.debate_record_text(stored, await debate_svc.debate_rounds(graph_app, stored),
                                               questions=await debate_svc.debate_questions(graph_app, stored))

    assert any("Your side: Yes" in seen for seen in SEEN[A])
    assert any("Your assigned side is still: No" in seen for seen in SEEN[B])
    synthesis_prompt = next(s for s in SEEN[C] if "argument map" in s)
    assert "(assigned to argue: Yes)" in synthesis_prompt and "The sides were assigned" in synthesis_prompt
    assert "Round 1 (opening case)" in synthesis_prompt

    view = debate_svc.session_view(stored)
    assert view["stance"] == {"mode": "sides", "sides": {A: "Yes", B: "No"}, "advocate": None}
    assert view["stance_notes"] == {A: "assigned to argue: Yes", B: "assigned to argue: No"}
    assert {lane["model_id"]: lane["stance_note"] for lane in tree["lanes"]} == view["stance_notes"]
    assert "assigned to argue: Yes" in record and "what a participant argued is not what it believes" in record


def test_rest_cli_and_mcp_take_a_stance():
    import asyncio

    from fastapi.testclient import TestClient
    from fastmcp import Client
    from typer.testing import CliRunner

    from app.cli import app as cli_app
    from app.main import server
    from app.mcp_server import mcp

    with TestClient(server) as client:
        made = client.post("/debate/sessions", json={
            "parent_thread_id": "t-rest", "participants": [A, B], "termination_policy": POLICY,
            "stance": {"mode": "advocate", "advocate": B},
        })
        assert made.status_code == 200, made.text
        assert client.get(f"/debate/sessions/{made.json()['session_id']}").json()["stance"]["advocate"] == B
        refused = client.post("/debate/sessions", json={
            "parent_thread_id": "t-rest", "participants": [A, B],
            "termination_policy": {**POLICY, "llm_judge": C}, "stance": {"mode": "advocate", "advocate": B},
        })
        assert refused.status_code == 400

    runner = CliRunner()
    assert runner.invoke(cli_app, ["debate", "Q?", "-m", A, "-m", B, "--side", "Yes", "--advocate", A]).exit_code == 2
    assert runner.invoke(cli_app, ["debate", "Q?", "-m", A, "-m", B, "--advocate", C]).exit_code == 2
    ran = runner.invoke(cli_app, ["debate", "Q?", "-m", A, "-m", B, "--side", "Yes", "--side", "No", "--rounds", "1",
                                  "--no-synthesize", "--format", "json"])
    assert ran.exit_code == 0, ran.stderr
    session = db.get_debate_session(json.loads(ran.stdout)["session_id"])
    assert session["stance"]["sides"] == {A: "Yes", B: "No"}

    async def over_mcp():
        async with Client(mcp) as c:
            return (await c.call_tool("run_debate", {"prompt": "Q?", "models": [A, B], "max_rounds": 1,
                                                     "advocate": A})).data

    result = asyncio.run(over_mcp())
    assert db.get_debate_session(result["session_id"])["stance"] == {"mode": "advocate", "sides": None, "advocate": A}
