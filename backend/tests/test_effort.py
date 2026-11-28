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


@pytest.mark.asyncio
async def test_helper_calls_never_get_the_effort(isolated):
    """Only the answering call: a synthesis is an answering call (its own
    model's level), the summary, recall and grading are not."""
    async with arena.open_graph() as graph_app:
        await arena.collect(arena.run_arena(
            graph_app, "Q?", "t-helper", [A], {}, context=ContextSettings(reasoning_effort="low"),
        ))
    assert isolated == {A: "low"}


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
