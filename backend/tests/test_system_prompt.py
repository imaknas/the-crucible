"""The person's own system prompt, and no persona when there is none.

Every chat request used to carry an app-chosen persona and a request for a
self-assessed confidence in <metadata> tags. Models now get no system message
unless something needs one; a system prompt set in the Control Panel (or with
`--system` / `system_prompt`) reaches every model through ContextSettings.

Real graph and checkpointer; only the LLM is faked, and it records what each
call was sent.
"""

import json
import os
from typing import List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.exceptions import ToolError
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from typer.testing import CliRunner

from app.core import database as db
from app.llm import CallableModelFactory, use_model_factory
from app.services import arena as arena_svc
from app.services import debate as debate_svc
from app.services.context import MAX_SYSTEM_PROMPT_CHARS, ContextSettings
from app.services.graph import SYSTEM_PROMPT_CONFIG_KEY

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B = "gpt-5.4", "claude-sonnet-5"
PROMPT = "Answer as a terse field geologist."

# (model id, message list) for every call any model received
SEEN: List[tuple] = []


class _Recorder(FakeListChatModel):
    model_id: str = ""

    def _call(self, messages, *args, **kwargs):
        SEEN.append((self.model_id, list(messages)))
        return super()._call(messages, *args, **kwargs)

    def _stream(self, messages, *args, **kwargs):
        SEEN.append((self.model_id, list(messages)))
        yield from super()._stream(messages, *args, **kwargs)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    SEEN.clear()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "system.sqlite"))
    monkeypatch.setattr("app.cli._load_env", lambda: None)
    db.init_db()
    factory = CallableModelFactory(lambda model_id, _t: _Recorder(responses=[f"reply from {model_id}"], model_id=model_id))
    with use_model_factory(factory), patch.dict(os.environ, KEYS):
        yield


def _systems(model_id=None) -> List[str]:
    """The system message of every call (to `model_id`), "" for a call without one."""
    out = []
    for mid, messages in SEEN:
        if model_id is None or mid == model_id:
            out.append(next((str(m.content) for m in messages if m.type == "system"), ""))
    return out


# ─── ContextSettings ─────────────────────────────────────────────


def test_from_frame_reads_the_top_level_field_and_treats_blank_as_unset():
    assert ContextSettings.from_frame({"system_prompt": f"  {PROMPT}\n"}).system_prompt == PROMPT
    assert ContextSettings.from_frame({"system_prompt": "   "}).system_prompt is None
    assert ContextSettings.from_frame({}).system_prompt is None
    # Inside toggles it is not a system prompt.
    assert ContextSettings.from_frame({"toggles": {"system_prompt": PROMPT}}).system_prompt is None


def test_problem_refuses_an_oversize_or_non_string_prompt():
    assert ContextSettings(system_prompt="x" * MAX_SYSTEM_PROMPT_CHARS).problem({}) is None
    assert "limit" in ContextSettings(system_prompt="x" * (MAX_SYSTEM_PROMPT_CHARS + 1)).problem({})
    for value in (42, ["a"], {"a": 1}):
        assert "must be text" in ContextSettings.from_frame({"system_prompt": value}).problem({})


def test_apply_puts_the_prompt_on_the_run_config_only_when_set():
    assert ContextSettings(system_prompt=PROMPT).apply({"configurable": {}}, KEYS)["configurable"][SYSTEM_PROMPT_CONFIG_KEY] == PROMPT
    assert SYSTEM_PROMPT_CONFIG_KEY not in ContextSettings().apply({"configurable": {}}, KEYS)["configurable"]


def test_a_frame_names_settings_by_any_field():
    assert ContextSettings.named_in({"system_prompt": PROMPT})
    assert ContextSettings.named_in({"summarizer": "gpt-6-luna"})
    assert not ContextSettings.named_in({"message": "narrower"})


# ─── Chat ────────────────────────────────────────────────────────


def _ws_turn(client, thread_id, frame):
    with client.websocket_connect(f"/ws/{thread_id}") as ws:
        ws.send_json(frame)
        while (msg := ws.receive_json())["type"] not in ("stream_end", "error"):
            pass
    return msg


def test_a_chat_turn_sends_no_system_message_by_default():
    from app.main import server

    with TestClient(server) as client:
        msg = _ws_turn(client, "t-plain", {"message": "Hello", "model": A})
    assert msg["type"] == "stream_end", msg
    assert _systems(A) == [""]
    sent = "\n".join(str(m.content) for _, messages in SEEN for m in messages)
    assert "<metadata>" not in sent and "research assistant" not in sent


def test_a_ws_chat_turn_sends_the_system_prompt():
    from app.main import server

    with TestClient(server) as client:
        msg = _ws_turn(client, "t-ws", {"message": "Hello", "model": A, "system_prompt": PROMPT})
    assert msg["type"] == "stream_end", msg
    assert _systems(A) == [PROMPT]


def test_a_ws_chat_turn_with_an_oversize_prompt_is_refused():
    from app.main import server

    with TestClient(server) as client:
        msg = _ws_turn(client, "t-big", {"message": "Hello", "model": A, "system_prompt": "x" * (MAX_SYSTEM_PROMPT_CHARS + 1)})
    assert msg["type"] == "error" and "limit" in msg["message"]
    assert not SEEN


def test_post_chat_sends_the_system_prompt():
    from app.main import server

    with TestClient(server) as client:
        r = client.post("/chat", json={"message": "Hello", "thread_id": "t-rest", "model": A, "system_prompt": PROMPT})
    assert r.status_code == 200, r.text
    assert _systems(A) == [PROMPT]


# ─── Arena (service, CLI, MCP) ───────────────────────────────────


@pytest.mark.asyncio
async def test_arena_sends_the_prompt_to_every_model_and_the_synthesizer():
    async with arena_svc.open_graph() as graph_app:
        result = await arena_svc.collect(arena_svc.run_arena(
            graph_app, "Q?", "t-arena", [A, B], {}, synthesizer=A, context=ContextSettings(system_prompt=PROMPT),
        ))
    assert result["synthesis"]["content"] == f"reply from {A}"
    assert _systems(A) == [PROMPT, PROMPT]  # answer and synthesis
    assert _systems(B) == [PROMPT]


def test_cli_arena_system_option():
    from app.cli import app as cli_app

    result = CliRunner().invoke(cli_app, ["arena", "Q?", "-m", A, "-m", B, "--no-synthesize", "--system", PROMPT, "--format", "json"])
    assert result.exit_code == 0, (result.stdout, result.stderr, result.exception)
    assert set(json.loads(result.stdout)["answers"]) == {A, B}
    assert _systems() == [PROMPT, PROMPT]


def test_cli_arena_without_system_sends_none():
    from app.cli import app as cli_app

    result = CliRunner().invoke(cli_app, ["arena", "Q?", "-m", A, "-m", B, "--no-synthesize", "--format", "json"])
    assert result.exit_code == 0, (result.stdout, result.stderr, result.exception)
    assert _systems() == ["", ""]


@pytest.mark.asyncio
async def test_mcp_invoke_arena_system_prompt():
    from app.mcp_server import mcp

    async with Client(mcp) as client:
        await client.call_tool("invoke_arena", {"prompt": "Q?", "models": [A, B], "synthesize": False, "system_prompt": PROMPT})
        assert _systems() == [PROMPT, PROMPT]
        with pytest.raises(ToolError, match="limit"):
            await client.call_tool("invoke_arena", {"prompt": "Q?", "models": [A], "system_prompt": "x" * (MAX_SYSTEM_PROMPT_CHARS + 1)})


# ─── Debate ──────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("peer_labels", ["anonymous", "named"])
async def test_every_debate_participant_gets_the_prompt_in_every_round(peer_labels):
    policy = {"max_rounds": 2, "convergence_threshold": None, "llm_judge": None, "mode": "all"}
    session = debate_svc.create_session("t-deb", [A, B], policy, peer_labels=peer_labels)
    async with arena_svc.open_graph() as graph_app:
        events = [e async for e in debate_svc.run_debate(
            graph_app, session["session_id"], "Debate it.", {}, {}, context=ContextSettings(system_prompt=PROMPT),
        )]
    assert events[-1]["status"] == "completed", events
    for model in (A, B):
        round0, round1 = _systems(model)
        assert round0 == PROMPT
        if peer_labels == "named":
            # Later rounds are cross-examination: the person's prompt, then the critic role.
            assert round1.startswith(PROMPT) and "critical reviewer" in round1
        else:
            # Anonymous peers skip the graph's deliberation mode, whose critic
            # role names the model; the cross-examination prompt carries the
            # critique instructions instead.
            assert round1 == PROMPT

