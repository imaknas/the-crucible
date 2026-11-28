"""Reasoning effort: one choice per run, resolved per model against the
levels the catalog recorded, sent only when the model takes it, stamped on
the reply as sent; a model that can't take it answers at its default with a
notice. Unset, nothing is sent."""

import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastmcp import Client
from langchain_core.messages import HumanMessage
from typer.testing import CliRunner

from app.cli import app as cli_app
from app.llm import ProviderModelFactory, use_model_factory
from app.llm.effort import available_choices, model_levels, resolve_level, timeout_factor
from app.llm.fake import ScriptedModelFactory
from app.llm.providers import PROVIDERS
from app.services import arena, cases
from app.services.context import ContextSettings
from app.services.debate import MODEL_TIMEOUT_SECONDS, model_timeout
from tests.storage_helpers import point

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY")}
A, B = "gpt-5.4", "claude-sonnet-5"
REASONING_KEYS = ("reasoning_effort", "reasoning", "output_config", "thinking", "extra_body")


def _catalog(levels):
    return lambda: {mid: SimpleNamespace(capabilities={} if lv is None else {"reasoning_effort": lv})
                    for mid, lv in levels.items()}


# ─── Choosing the level ──────────────────────────────────────────


def test_a_choice_resolves_to_a_level_the_model_takes():
    assert resolve_level(["low", "medium", "high", "xhigh"], "high") == "high"
    assert resolve_level(["low", "high", "xhigh", "max"], "max") == "max"
    assert resolve_level(["minimal", "low", "medium", "high"], "max") == "high"
    assert resolve_level(["low", "high"], "medium") is None
    assert resolve_level([], "high") is None and resolve_level(None, "high") is None
    assert available_choices(["low", "high"]) == ["low", "high", "max"]
    assert available_choices([]) == [] and available_choices(None) is None


def test_levels_come_from_the_catalog_and_unknown_is_not_none():
    registry = {"m1": {"id": "m1"}, "m2": {"id": "m2"}, "m3": {"id": "m3"}}
    catalog = _catalog({"m1": ["high", "low", "bogus"], "m2": [], "m3": None})
    assert model_levels("m1", catalog=catalog, registry=registry) == ["low", "high"]
    assert model_levels("m2", catalog=catalog, registry=registry) == []
    assert model_levels("m3", catalog=catalog, registry=registry) is None
    assert model_levels("nope", catalog=catalog, registry=registry) is None


def test_hard_choices_get_longer_time_limits():
    assert timeout_factor(None) == timeout_factor("low") == timeout_factor("medium") == 1
    assert timeout_factor("high") == timeout_factor("max") == 3
    assert model_timeout(ContextSettings(reasoning_effort="max")) == 3 * MODEL_TIMEOUT_SECONDS
    assert model_timeout(ContextSettings()) == MODEL_TIMEOUT_SECONDS


def test_an_unknown_choice_is_refused():
    assert "Unknown reasoning effort" in ContextSettings.from_frame({"reasoning_effort": "extreme"}).problem()
    assert ContextSettings.from_frame({"reasoning_effort": " high "}).problem() is None
    assert ContextSettings.from_frame({"reasoning_effort": ""}).reasoning_effort is None


# ─── What each provider sends ────────────────────────────────────


def _payload(llm, **kwargs):
    return llm._get_request_payload([HumanMessage("hi")], **kwargs)


def test_unset_nothing_reasoning_related_is_sent():
    factory = ProviderModelFactory(env=KEYS)
    for model in ("gpt-6.2-astra", "claude-opus-5-5", "grok-4.7"):
        payload = _payload(factory.chat(model, {}))
        assert not any(k in payload for k in REASONING_KEYS), (model, payload)
    google = factory.chat("gemini-4-carbon", {})
    assert "thinking_config" not in google._build_base_generation_config(None)


def test_each_provider_sends_the_level_where_its_api_wants_it():
    openai = PROVIDERS["openai"].create("gpt-6.2-astra", api_key="k", effort="high")
    assert _payload(openai)["reasoning_effort"] == "high"
    # Web search sends it to the Responses API, as `reasoning.effort`.
    searching = PROVIDERS["openai"].with_web_search(openai)
    assert _payload(searching.bound, **searching.kwargs)["reasoning"] == {"effort": "high"}

    anthropic = _payload(PROVIDERS["anthropic"].create("claude-opus-5-5", api_key="k", effort="max"))
    assert anthropic["output_config"] == {"effort": "max"} and "reasoning_effort" not in anthropic

    xai = PROVIDERS["xai"].create("grok-4.7", api_key="k", effort="xhigh")
    assert _payload(xai)["extra_body"] == {"reasoning_effort": "xhigh"}
    searching = PROVIDERS["xai"].with_web_search(xai)
    assert _payload(searching.bound, **searching.kwargs)["reasoning"] == {"effort": "xhigh"}

    config = PROVIDERS["google"].create("gemini-4-carbon", api_key="k", effort="high")._build_base_generation_config(None)
    assert config["thinking_config"].thinking_level.value == "HIGH"
    assert config["thinking_config"].thinking_budget is None
    assert not any(k in config for k in ("temperature", "top_p", "top_k"))


def test_a_model_the_catalog_says_has_no_effort_gets_none():
    # Haiku 4.5's listing: effort unsupported.
    assert model_levels("claude-haiku-4-5-20251001") == []
    assert resolve_level(model_levels("claude-haiku-4-5-20251001"), "high") is None


# ─── A turn ──────────────────────────────────────────────────────


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    point(monkeypatch, db_path=str(tmp_path / "effort.sqlite"))
    monkeypatch.setattr("app.cli._load_env", lambda: None)
    levels = {A: ["low", "medium", "high", "xhigh"], B: None}
    monkeypatch.setattr("app.services.graph.model_levels", lambda model_id: levels.get(model_id))
    sent: dict = {}

    class Recording(ScriptedModelFactory):
        def chat(self, model_id, toggles=None, **kwargs):
            if "effort" in kwargs:
                sent[model_id] = kwargs["effort"]
            return super().chat(model_id, toggles, **kwargs)

    with use_model_factory(Recording(delay=0)), patch.dict(os.environ, KEYS):
        yield sent


@pytest.mark.asyncio
async def test_each_model_gets_its_level_or_a_notice_and_the_reply_says_which(isolated):
    async with arena.open_graph() as graph_app:
        result = await arena.collect(arena.run_arena(
            graph_app, "Review this plan.", "t-effort", [A, B], {}, context=ContextSettings(reasoning_effort="max"),
        ))
        case = await cases.save_case(graph_app, "t-effort", result["answers"][A]["checkpoint_id"])
    assert isolated[A] == "xhigh" and B not in isolated
    assert result["answers"][A]["effort"] == {"choice": "max", "level": "xhigh"}
    assert result["answers"][B]["effort"] is None
    notices = result["answers"][B].get("notices") or []
    assert any("haven't been verified" in n and "max" in n for n in notices), result["answers"][B]
    assert case["settings"]["reasoning_effort"] == "max"


def test_a_summary_never_gets_the_effort():
    """The summarizer is a helper call: the run's effort is the answering
    model's alone (as are recall and grading, built the same way)."""
    from langchain_core.messages import AIMessage

    from app.compaction import ThresholdPolicy
    from app.compaction.policy import fixed_tokens
    from app.llm import CallableModelFactory
    from app.services import graph as graph_mod

    calls: list = []

    class Summarizer:
        def invoke(self, msgs, *args, **kwargs):
            return AIMessage(content="a summary")

    def factory(model_id, _toggles):
        calls.append(model_id)
        return Summarizer()

    class Strict(CallableModelFactory):
        def chat(self, model_id, toggles=None, **kwargs):
            assert "effort" not in kwargs, "a helper call was handed the run's effort"
            return super().chat(model_id, toggles)

    messages = [HumanMessage(content=f"turn {i}") if i % 2 == 0 else AIMessage(content=f"reply {i}") for i in range(12)]
    config = {"configurable": {
        "model_factory": Strict(factory),
        "compaction_policy": ThresholdPolicy(fixed_tokens(1)),
        "reasoning_effort": "max",
    }}
    out = graph_mod.summarize_history({"messages": messages, "active_peer": A}, config)
    assert calls and "a summary" in out["messages"][0].content


def test_cli_and_mcp_take_an_effort(isolated):
    bad = CliRunner().invoke(cli_app, ["arena", "Q?", "-m", A, "--effort", "extreme"])
    assert bad.exit_code == 1 and "Unknown reasoning effort" in bad.output
    out = CliRunner().invoke(cli_app, ["chat", "Q?", "-m", A, "--effort", "high", "-t", "t-cli", "--format", "json"])
    assert out.exit_code == 0, out.output
    assert json.loads(out.stdout)["effort"] == {"choice": "high", "level": "high"}

    import asyncio

    from app.mcp_server import mcp

    async def go():
        async with Client(mcp) as client:
            return (await client.call_tool("invoke_arena", {
                "prompt": "Q?", "models": [A], "synthesize": False, "reasoning_effort": "medium",
            })).structured_content

    result = asyncio.run(go())
    assert result["answers"][0]["effort"] == {"choice": "medium", "level": "medium"}


def test_models_say_which_efforts_each_takes():
    from fastapi.testclient import TestClient

    from app.main import server

    with TestClient(server) as client:
        body = client.get("/models").json()
    assert body["reasoning_efforts"] == ["low", "medium", "high", "max"]
    by_id = {m["id"]: m for f in body["families"] for m in f["models"]}
    assert by_id["claude-opus-5-5"]["reasoning_efforts"] == ["low", "medium", "high", "max"]
    assert by_id["claude-haiku-4-5-20251001"]["reasoning_efforts"] == []
    rows = {m["id"]: m for m in arena.list_models()}
    assert rows["claude-opus-5-5"]["reasoning_efforts"] == by_id["claude-opus-5-5"]["reasoning_efforts"]


# ─── Thinking blocks (an Anthropic effort turns adaptive thinking on) ──


THINKING_REPLY = [
    {"type": "thinking", "thinking": "Let me weigh the migration first.", "signature": "sig"},
    {"type": "text", "text": "The plan lacks a rollback."},
]


def test_thinking_stays_out_of_what_other_calls_read_but_the_transcript_folds_it():
    from langchain_core.messages import AIMessage

    from app.services.graph import sanitize_messages
    from app.utils.helpers import extract_text

    assert extract_text(THINKING_REPLY) == "The plan lacks a rollback."
    assert extract_text(THINKING_REPLY, wrap_thinking=True).startswith("<think>\nLet me weigh")
    history = sanitize_messages([HumanMessage("Review it."), AIMessage(content=THINKING_REPLY), HumanMessage("And cost?")])
    sent = " ".join(str(m.content) for m in history)
    assert "The plan lacks a rollback." in sent and "Let me weigh" not in sent


@pytest.mark.asyncio
async def test_a_reply_with_thinking_streams_and_reads_as_its_answer(isolated):
    """The streamed tokens, the stored answer a synthesis reads, and the
    path the transcript shows."""
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    from app.llm import CallableModelFactory
    from app.services import history

    class Thinker(BaseChatModel):
        """Answers with a thinking block and a text block, as Claude does."""

        @property
        def _llm_type(self):
            return "thinker"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if run_manager:  # streamed as Anthropic streams it: the thinking, then the text
                from langchain_core.messages import AIMessageChunk
                from langchain_core.outputs import ChatGenerationChunk

                for block in THINKING_REPLY:
                    run_manager.on_llm_new_token("", chunk=ChatGenerationChunk(message=AIMessageChunk(content=[block])))
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=THINKING_REPLY))])

    factory = CallableModelFactory(lambda m, _t: Thinker())
    tokens: list = []
    with use_model_factory(factory):
        async with arena.open_graph() as graph_app:
            async for event in arena.run_arena(graph_app, "Review it.", "t-think", [B], {}):
                if event["type"] == "token":
                    tokens.append(event["token"])
                if event["type"] == "end":
                    end = event
            answer = await arena.answer_at(graph_app, "t-think", end["checkpoint_id"])
            path = await history.path_at(graph_app, "t-think", end["checkpoint_id"])
    assert "".join(tokens) == "The plan lacks a rollback."  # streamed, without the thinking
    assert end["content"] == answer["content"] == "The plan lacks a rollback."
    messages = path["messages"] if isinstance(path, dict) else path
    assert messages[-1]["content"].startswith("<think>")


def test_a_socket_frame_and_post_chat_carry_an_effort(isolated):
    from fastapi.testclient import TestClient

    from app.main import server

    with TestClient(server) as client:
        with client.websocket_connect("/ws/t-ws") as ws:
            ws.send_json({"message": "Q?", "model": A, "reasoning_effort": "high"})
            while (end := ws.receive_json())["type"] not in ("stream_end", "error"):
                pass
        assert end["type"] == "stream_end" and end["effort"] == {"choice": "high", "level": "high"}, end
        with client.websocket_connect("/ws/t-ws2") as ws:
            ws.send_json({"message": "Q?", "model": A, "reasoning_effort": "extreme"})
            while (refused := ws.receive_json())["type"] not in ("stream_end", "error"):
                pass
        assert refused["type"] == "error" and "Unknown reasoning effort" in refused["message"]
        isolated.clear()
        r = client.post("/chat", json={"message": "Q?", "thread_id": "t-rest", "model": A, "reasoning_effort": "low"})
        assert r.status_code == 200, r.text
    assert isolated == {A: "low"}


def test_continuing_a_debate_with_one_setting_keeps_the_others(monkeypatch):
    from app.services import debate

    stored = {"settings": {"system_prompt": "Be brief.", "summarizer": None, "reasoning_effort": "high", "toggles": {}}}
    monkeypatch.setattr(debate.db, "get_debate_session", lambda _sid: stored)
    assert debate.stored_context("s") is None  # nothing named: the stored settings as they are
    merged = debate.stored_context("s", reasoning_effort="max")
    assert (merged.system_prompt, merged.reasoning_effort) == ("Be brief.", "max")
    merged = debate.stored_context("s", system_prompt="Be thorough.")
    assert (merged.system_prompt, merged.reasoning_effort) == ("Be thorough.", "high")
