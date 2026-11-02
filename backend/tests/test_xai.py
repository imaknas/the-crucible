"""xAI (Grok): the family, its provider strategy and its catalog source.

No xAI model is registered until `crucible catalog-sync` has verified one
with a real call, so these tests use an injected registry and recorded
responses shaped like xAI's documented ones; nothing reaches the network.
"""

import json

import httpx
import pytest
from langchain_core.messages import HumanMessage

from app.catalog import CatalogEntry, sync_catalog
from app.catalog.sources import SOURCES, XAI_WEB_SEARCH_TOOL, XAISource, _redact
from app.llm.factory import ProviderModelFactory, has_credentials
from app.llm.providers import PROVIDERS, REQUEST_NOTES_HEADER, XAIProvider, _caching_chat_xai
from app.registry import FAMILY_META, models_by_family, provider_env_keys

GROK = "grok-test-1"
REGISTRY = {GROK: {"family": "xai", "id": GROK, "name": "Grok Test", "desc": "Test", "limit": 100_000,
                   "native_search": True}}


# ─── Family ──────────────────────────────────────────────────────


def test_xai_is_a_family_with_its_own_key_and_colour():
    meta = FAMILY_META["xai"]
    assert (meta["label"], meta["env_key"]) == ("xAI", "XAI_API_KEY")
    assert meta["color"] not in {m["color"] for f, m in FAMILY_META.items() if f != "xai"}
    assert "XAI_API_KEY" in provider_env_keys()
    assert "xai" in PROVIDERS and "xai" in SOURCES


def test_xai_is_listed_before_it_has_models(monkeypatch):
    """GET /models names the family (so the UI can take its key) even with no
    registered model; the frontend leaves it out of the model picker."""
    from app.api.models import _build_families
    from app.services import keys as keys_svc

    assert models_by_family()["xai"] == []
    monkeypatch.setenv("XAI_API_KEY", "xai-placeholder")
    xai = {f["key"]: f for f in _build_families()}["xai"]
    assert xai == {"key": "xai", "label": "xAI", "color": FAMILY_META["xai"]["color"], "env_key": "XAI_API_KEY",
                   "available": True, "models": []}
    assert "XAI_API_KEY" in keys_svc.KEY_NAMES
    assert keys_svc.key_status()["XAI_API_KEY"]["set"] is True


def test_crucible_keys_lists_the_xai_key(monkeypatch):
    from typer.testing import CliRunner

    from app.cli import app as cli

    monkeypatch.setattr("app.cli._load_env", lambda: None)
    result = CliRunner().invoke(cli, ["keys", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["keys"]["XAI_API_KEY"]["set"] is False


# ─── Provider ────────────────────────────────────────────────────


def _factory(env, catalog=dict):
    return ProviderModelFactory(registry=REGISTRY, providers={"xai": XAIProvider(catalog=catalog)}, env=env)


def test_the_factory_builds_grok_with_the_key_it_checked():
    llm = _factory({"XAI_API_KEY": "xai-k"}).chat(GROK)
    assert isinstance(llm, _caching_chat_xai())
    assert llm.model_name == GROK
    assert llm.xai_api_key.get_secret_value() == "xai-k"
    assert str(llm.root_client.base_url).startswith("https://api.x.ai/v1")
    assert llm.stream_usage is True  # usage_metadata on the last streamed chunk
    assert llm._use_responses_api({}) is False  # plain turns: chat/completions


def test_the_factory_refuses_grok_without_a_key():
    assert not has_credentials(GROK, {}, REGISTRY)
    with pytest.raises(ValueError, match="XAI_API_KEY"):
        _factory({}).chat(GROK)


def test_web_search_binds_xais_tool_on_the_responses_api():
    bound = _factory({"XAI_API_KEY": "xai-k"}).chat(GROK, {"use_web_search": True})
    assert bound.kwargs["tools"] == [XAI_WEB_SEARCH_TOOL]
    assert bound.bound._use_responses_api(bound.kwargs) is True


def test_a_responses_only_model_is_sent_to_the_responses_api():
    catalog = {GROK: CatalogEntry(GROK, "xai", GROK, capabilities={"api": "responses"})}
    llm = _factory({"XAI_API_KEY": "xai-k"}, catalog=lambda: catalog).chat(GROK)
    assert llm._use_responses_api({}) is True


def _sse(events) -> bytes:
    return b"".join(f"data: {json.dumps(e)}\n\n".encode() for e in events) + b"data: [DONE]\n\n"


def _recording_llm(handler, **kw):
    """The provider's own class, on a transport that answers like api.x.ai."""
    return _caching_chat_xai()(
        model=GROK, api_key="xai-k", http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw,
    )


@pytest.mark.asyncio
async def test_a_streamed_chat_turn_reports_usage_and_moves_request_notes():
    """Chat Completions usage: https://docs.x.ai/developers/rest-api-reference/inference/chat-completions
    (`stream_options.include_usage`; `completion_tokens_details.reasoning_tokens`;
    `prompt_tokens_details.cached_tokens`)."""
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        chunk = {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": GROK}
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_sse([
            {**chunk, "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Hi"}, "finish_reason": None}]},
            {**chunk, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            {**chunk, "choices": [], "usage": {
                "prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 18,
                "prompt_tokens_details": {"cached_tokens": 4, "text_tokens": 10, "audio_tokens": 0, "image_tokens": 0},
                "completion_tokens_details": {"reasoning_tokens": 5, "audio_tokens": 0,
                                              "accepted_prediction_tokens": 0, "rejected_prediction_tokens": 0},
            }},
        ]))

    llm = _recording_llm(handler)
    question = HumanMessage(content=[{"type": "text", "text": "q"}, {"type": "text", "text": REQUEST_NOTES_HEADER + " now"}])
    usage = None
    async for chunk in llm.astream([question]):
        usage = chunk.usage_metadata or usage

    (request,) = requests
    assert request.url.host == "api.x.ai" and request.url.path == "/v1/chat/completions"
    body = json.loads(request.content)
    assert body["stream_options"] == {"include_usage": True}
    # The per-request block left the question, so the next turn repeats it exactly.
    assert body["messages"][-1]["role"] == "system" and body["messages"][-1]["content"].startswith(REQUEST_NOTES_HEADER)
    assert body["messages"][-2]["content"] == [{"type": "text", "text": "q"}]
    # langchain-xai counts reasoning tokens as output (xAI reports them apart).
    assert usage["input_tokens"] == 10 and usage["output_tokens"] == 3 + 5
    assert usage["input_token_details"]["cache_read"] == 4


@pytest.mark.asyncio
async def test_a_web_search_turn_streams_from_the_responses_api_with_usage():
    """Responses streaming events and usage: https://docs.x.ai/developers/rest-api-reference/inference/responses."""
    requests = []
    response = {"id": "resp_1", "object": "response", "created_at": 1, "model": GROK, "status": "in_progress",
                "output": [], "tools": [XAI_WEB_SEARCH_TOOL], "tool_choice": "auto", "parallel_tool_calls": True}
    message = {"id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
               "content": [{"type": "output_text", "text": "Found it", "annotations": []}]}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_sse([
            {"type": "response.created", "sequence_number": 0, "response": response},
            {"type": "response.output_item.added", "sequence_number": 1, "output_index": 0,
             "item": {**message, "status": "in_progress", "content": []}},
            {"type": "response.output_text.delta", "sequence_number": 2, "item_id": "msg_1", "output_index": 0,
             "content_index": 0, "delta": "Found it", "logprobs": []},
            {"type": "response.completed", "sequence_number": 3, "response": {
                **response, "status": "completed", "output": [message],
                "usage": {"input_tokens": 20, "output_tokens": 7, "total_tokens": 27,
                          "input_tokens_details": {"cached_tokens": 0},
                          "output_tokens_details": {"reasoning_tokens": 2}}}},
        ]))

    searching = PROVIDERS["xai"].with_web_search(_recording_llm(handler))
    text, usage = "", None
    async for chunk in searching.astream([HumanMessage(content="news?")]):
        text += chunk.text
        usage = chunk.usage_metadata or usage

    (request,) = requests
    assert request.url.host == "api.x.ai" and request.url.path == "/v1/responses"
    assert json.loads(request.content)["tools"] == [XAI_WEB_SEARCH_TOOL]
    assert text == "Found it"
    assert usage["input_tokens"] == 20 and usage["output_tokens"] == 7


# ─── Catalog source ──────────────────────────────────────────────

# Shaped like the documented responses of GET /v1/language-models and
# GET /v1/models (https://docs.x.ai/developers/rest-api-reference/inference/models),
# with made-up ids.
LANGUAGE_MODELS = {"models": [
    {"id": "grok-9", "fingerprint": "fp_1", "created": 1790000000, "object": "model", "owned_by": "xai",
     "version": "1.0", "input_modalities": ["text", "image"], "output_modalities": ["text"],
     "prompt_text_token_price": 20000, "cached_prompt_text_token_price": 5000, "prompt_image_token_price": 20000,
     "completion_text_token_price": 60000, "search_price": 0, "prompt_text_token_price_long_context": 40000,
     "cached_prompt_text_token_price_long_context": 0, "completion_text_token_price_long_context": 120000,
     "long_context_threshold": 200000, "aliases": ["grok-9-latest", "grok-latest"],
     "capabilities": {"reasoning_effort": ["low", "medium", "high"], "default_reasoning_effort": "high"}},
    {"id": "grok-9-responses-only", "fingerprint": "fp_2", "created": 1790000000, "object": "model",
     "owned_by": "xai", "version": "1.0", "input_modalities": ["text"], "output_modalities": ["text"],
     "prompt_text_token_price": 12500, "cached_prompt_text_token_price": 2000, "prompt_image_token_price": 0,
     "completion_text_token_price": 25000, "search_price": 0, "prompt_text_token_price_long_context": 0,
     "cached_prompt_text_token_price_long_context": 0, "completion_text_token_price_long_context": 0,
     "long_context_threshold": 0, "aliases": []},
    {"id": "grok-9-imagine-vision", "fingerprint": "fp_3", "created": 1790000000, "object": "model",
     "owned_by": "xai", "version": "1.0", "input_modalities": ["text", "image"], "output_modalities": ["image"],
     "prompt_text_token_price": 0, "cached_prompt_text_token_price": 0, "prompt_image_token_price": 0,
     "completion_text_token_price": 0, "search_price": 0, "prompt_text_token_price_long_context": 0,
     "cached_prompt_text_token_price_long_context": 0, "completion_text_token_price_long_context": 0,
     "long_context_threshold": 0, "aliases": []},
]}
MODELS = {"object": "list", "data": [
    {"id": "grok-9", "aliases": [], "context_length": 500000, "created": 1790000000, "object": "model",
     "owned_by": "xai", "prompt_text_token_price": 20000, "completion_text_token_price": 60000},
    {"id": "grok-9-responses-only", "aliases": [], "context_length": None, "created": 1790000000,
     "object": "model", "owned_by": "xai"},
    {"id": "grok-imagine-image", "aliases": [], "context_length": 1024, "created": 1790000000, "object": "model",
     "owned_by": "xai", "image_price": 200000000},
]}


def xai_transport(calls):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.headers.get("authorization"),
                      json.loads(request.content) if request.content else None))
        assert request.url.host == "api.x.ai"
        if request.method == "GET":
            return httpx.Response(200, json={"/v1/language-models": LANGUAGE_MODELS, "/v1/models": MODELS}[request.url.path])
        body = json.loads(request.content)
        if body["model"] == "grok-9-responses-only" and request.url.path == "/v1/chat/completions":
            return httpx.Response(404, json={"code": "Some resource could not be found",
                                             "error": "The model is not available on chat completions."})
        return httpx.Response(200, json={"id": "ok"})
    return httpx.MockTransport(handler)


def sync_xai(calls, **kw):
    with httpx.Client(transport=xai_transport(calls)) as client:
        return sync_catalog({}, {"xai": "xai-k"}, client=client, today="2026-11-02", sources=[XAISource()], **kw)


def test_xai_listing_is_normalized_with_its_context_window():
    calls = []
    catalog, diff = sync_xai(calls, probe="none")
    assert sorted(catalog) == ["grok-9", "grok-9-responses-only"]  # image output: not a chat model
    grok = catalog["grok-9"]
    assert (grok.provider, grok.display_name, grok.released) == ("xai", "grok-9", "2026-09-21")
    assert grok.input_limit == 500_000 and grok.output_limit is None
    assert "context_length" in grok.sources["input_limit"] and "docs.x.ai" in grok.sources["input_limit"]
    assert grok.capabilities == {"image_input": True, "reasoning_effort": ["low", "medium", "high"],
                                 "aliases": ["grok-9-latest", "grok-latest"]}
    # No window reported: left unknown, not guessed.
    assert catalog["grok-9-responses-only"].input_limit is None
    assert "input_limit" not in catalog["grok-9-responses-only"].sources
    assert {(m, p, auth) for m, p, auth, _ in calls} == {
        ("GET", "/v1/language-models", "Bearer xai-k"), ("GET", "/v1/models", "Bearer xai-k")}


def test_xai_probes_chat_then_web_search_on_the_responses_api():
    calls = []
    catalog, diff = sync_xai(calls)
    grok = catalog["grok-9"]
    assert grok.usable and grok.verification.web_search_ok and grok.capabilities["api"] == "chat_completions"
    # Answers only on the Responses API: usable, and the provider sends it there.
    assert catalog["grok-9-responses-only"].usable
    assert catalog["grok-9-responses-only"].capabilities["api"] == "responses"

    posts = [(p, body) for m, p, _, body in calls if m == "POST" and body["model"] == "grok-9"]
    chat, search = posts
    assert chat[0] == "/v1/chat/completions" and chat[1]["max_completion_tokens"] == 64
    assert search[0] == "/v1/responses" and search[1]["tools"] == [XAI_WEB_SEARCH_TOOL]
    assert search[1]["store"] is False


def test_sync_skips_xai_without_a_key():
    previous = {"grok-old": CatalogEntry("grok-old", "xai", "grok-old")}
    calls = []
    with httpx.Client(transport=xai_transport(calls)) as client:
        catalog, diff = sync_catalog(previous, {"openai": None, "xai": None}, client=client, today="2026-11-02",
                                     sources=[XAISource()])
    assert diff.skipped_providers == ["xai"] and calls == []
    assert catalog["grok-old"].status == "listed"


def test_catalog_sync_command_reads_the_xai_key(monkeypatch):
    """`crucible catalog-sync` asks each source for its env_key; without
    XAI_API_KEY, xAI is reported as skipped and nothing is called."""
    from typer.testing import CliRunner

    from app.cli import app as cli

    seen = {}

    def fake_sync(previous, keys, **kw):
        seen.update(keys)
        from app.catalog import CatalogDiff

        return dict(previous), CatalogDiff(skipped_providers=[k for k, v in keys.items() if not v])

    monkeypatch.setattr("app.cli._load_env", lambda: None)
    monkeypatch.setattr("app.catalog.sync_catalog", fake_sync)
    result = CliRunner().invoke(cli, ["catalog-sync", "--dry-run", "--probe", "none", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert "xai" in seen and seen["xai"] is None
    assert "xai" in json.loads(result.stdout)["skipped_providers"]


def test_xai_team_ids_are_redacted_from_errors():
    error = "The model grok-9 does not exist or your team 1b2c3d4e-0000-4abc-8def-0123456789ab does not have access to it."
    assert "1b2c3d4e" not in _redact(error)
    assert _redact("org-abcdef123456 says no") == "org-… says no"
