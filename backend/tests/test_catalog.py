"""Model catalog: provider sources, sync, overrides — against a fake HTTP transport."""

import ast
import json
import pathlib

import httpx
import pytest

from app.catalog import CatalogEntry, load_overrides, sync_catalog
from app.catalog.entry import Verification

OPENAI_MODELS = {"data": [
    {"id": "gpt-9", "created": 1790000000, "shutdown_date": None},
    {"id": "gpt-9-pro", "created": 1790000000, "shutdown_date": None},   # Responses API only
    {"id": "gpt-9-instruct", "created": 1790000000},                      # answers on neither API
    {"id": "gpt-9-tts", "created": 1790000000},                          # filtered out
    {"id": "text-embedding-4", "created": 1790000000},                   # filtered out
]}
ANTHROPIC_MODELS = {"data": [
    {"type": "model", "id": "claude-x", "display_name": "Claude X", "created_at": "2026-09-01T00:00:00Z",
     "max_input_tokens": 1_000_000, "max_tokens": 128_000,
     "capabilities": {"thinking": {"supported": True},
                      "context_management": {"supported": True, "compact_20260112": {"supported": True}}}},
], "has_more": False}
GOOGLE_MODELS = {"models": [
    {"name": "models/gemini-9-flash", "displayName": "Gemini 9 Flash", "inputTokenLimit": 1048576,
     "outputTokenLimit": 65536, "supportedGenerationMethods": ["generateContent", "createCachedContent"], "thinking": True},
    {"name": "models/gemini-9-flash-tts", "supportedGenerationMethods": ["generateContent"]},
]}


def transport(calls):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        path = request.url.path
        if request.url.host == "developers.openai.com":
            if path.endswith("/gpt-9"):
                return httpx.Response(200, text="<div>1,050,000</div> context window <b>128,000</b> max output tokens")
            return httpx.Response(404)
        if request.method == "GET":
            return httpx.Response(200, json={
                "api.openai.com": OPENAI_MODELS, "api.anthropic.com": ANTHROPIC_MODELS,
                "generativelanguage.googleapis.com": GOOGLE_MODELS,
            }[request.url.host])
        body = json.loads(request.content)
        if body.get("model") == "gpt-9-pro" and path.endswith("/chat/completions"):
            return httpx.Response(404, json={"error": {"message": "This model is only supported in v1/responses"}})
        if body.get("model") == "gpt-9-instruct":
            return httpx.Response(404, json={"error": {"message": "This is not a chat model"}})
        return httpx.Response(200, json={"ok": True})
    return httpx.MockTransport(handler)


KEYS = {"openai": "k", "anthropic": "k", "google": "k"}


def run(previous=None, calls=None, **kw):
    calls = calls if calls is not None else []
    with httpx.Client(transport=transport(calls)) as client:
        return sync_catalog(previous or {}, kw.pop("keys", KEYS), client=client, today="2026-09-26", **kw)


def test_catalog_package_imports_nothing_from_the_app():
    pkg = pathlib.Path(__file__).parents[1] / "app" / "catalog"
    for path in pkg.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not any(n.startswith("app.") and not n.startswith("app.catalog") for n in names), path.name


def test_first_sync_lists_normalizes_and_probes():
    catalog, diff = run(overrides={"gpt-9": {"input_limit": 900_000, "source": "https://example.test/gpt-9"}})
    assert sorted(catalog) == ["claude-x", "gemini-9-flash", "gpt-9", "gpt-9-instruct", "gpt-9-pro"]
    assert sorted(diff.added) == sorted(catalog)

    claude = catalog["claude-x"]
    assert (claude.input_limit, claude.output_limit, claude.released) == (1_000_000, 128_000, "2026-09-01")
    assert claude.capabilities["thinking"] and claude.capabilities["provider_compaction"]
    # Its thinking levels were probed (the fake answers every one).
    assert catalog["gemini-9-flash"].capabilities == {
        "thinking": True, "context_caching": True, "reasoning_effort": ["minimal", "low", "medium", "high"],
    }

    gpt = catalog["gpt-9"]
    # Overrides win over the docs page; the docs page supplied the output limit.
    assert gpt.input_limit == 900_000 and gpt.sources["input_limit"].startswith("override: https://example.test")
    assert gpt.output_limit == 128_000 and "openai docs" in gpt.sources["output_limit"]
    assert gpt.usable and gpt.verification.web_search_ok

    assert catalog["gpt-9"].capabilities["api"] == "chat_completions"
    # Only on the Responses API: still usable (LangChain routes it there).
    pro = catalog["gpt-9-pro"]
    assert pro.usable and pro.capabilities["api"] == "responses"
    # Answers on neither: kept, marked unusable, with the reason.
    instruct = catalog["gpt-9-instruct"]
    assert not instruct.usable and "not a chat model" in instruct.verification.error
    assert instruct.verification.web_search_ok is None  # no search probe after a failed chat probe


def test_openai_docs_limits_without_override():
    catalog, _ = run(probe="none")
    assert catalog["gpt-9"].input_limit == 1_050_000 - 128_000
    assert catalog["gpt-9-pro"].input_limit is None  # page unreadable: left unknown, not guessed


def test_resync_only_probes_what_changed_and_marks_delisted():
    first, _ = run()
    first["claude-old"] = CatalogEntry("claude-old", "anthropic", "Claude Old",
                                        verification=Verification(chat_ok=True, chat_checked="2026-01-01"))
    first["claude-x"].input_limit = 200_000  # the provider now reports a different limit
    calls = []
    second, diff = run(previous=first, calls=calls)
    assert diff.added == []
    assert diff.unlisted == ["claude-old"] and second["claude-old"].status == "unlisted"
    assert diff.changed == {"claude-x": {"input_limit": [200_000, 1_000_000]}}
    assert set(diff.probed) == {"claude-x"}  # unchanged, already-verified models are not re-probed
    assert sum(1 for m, _ in calls if m == "POST") == 2  # chat + web search for claude-x only


def test_provider_without_key_is_left_untouched():
    previous = {"gpt-old": CatalogEntry("gpt-old", "openai", "gpt-old")}
    catalog, diff = run(previous=previous, keys={"anthropic": "k"}, probe="none")
    assert "openai" in diff.skipped_providers and "google" in diff.skipped_providers
    assert catalog["gpt-old"].status == "listed"
    assert "gemini-9-flash" not in catalog


def test_overrides_require_a_source(tmp_path):
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps({"_note": "comments are allowed", "gpt-9": {"input_limit": 1}}))
    with pytest.raises(ValueError, match="gpt-9"):
        load_overrides(path)


def test_timeouts_are_inconclusive_and_retried():
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "gpt-9", "created": 1790000000}]}) \
                if request.url.host == "api.openai.com" else httpx.Response(404)
        if request.url.path.endswith("/responses"):
            raise httpx.ReadTimeout("slow search")
        return httpx.Response(200, json={})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        catalog, diff = sync_catalog({}, {"openai": "k"}, client=client, today="2026-09-26")
    v = catalog["gpt-9"].verification
    assert v.chat_ok and v.web_search_ok is None and v.web_search_checked is None
    assert "timed out" in v.error
    # Next sync retries the search even though nothing else changed.
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        _, diff2 = sync_catalog(catalog, {"openai": "k"}, client=client, today="2026-09-27")
    assert "gpt-9" in diff2.probed


def test_anthropic_search_tool_matches_code_execution():
    from app.catalog.sources import anthropic_web_search_tool

    assert "allowed_callers" not in anthropic_web_search_tool(True)
    assert anthropic_web_search_tool(False)["allowed_callers"] == ["direct"]
    assert anthropic_web_search_tool(None)["allowed_callers"] == ["direct"]  # unknown: the safe form


def test_rate_limits_are_inconclusive_and_account_ids_redacted():
    from app.catalog.sources import _probe

    r = _probe(httpx.Response(429, json={"error": {"message": "Rate limit reached in organization org-AbC123xyz789 on tokens"}}))
    assert r.ok is None and "org-AbC123xyz789" not in r.error and "org-…" in r.error
    assert _probe(httpx.Response(503, text="busy")).ok is None
    assert _probe(httpx.Response(400, json={"error": {"message": "bad tool"}})).ok is False


def test_inconclusive_keeps_success_but_clears_failure():
    from app.catalog.sync import _verdict

    assert _verdict(True, "2026-01-01", None, "2026-09-26") == (True, "2026-01-01")
    assert _verdict(False, "2026-01-01", None, "2026-09-26") == (None, None)
    assert _verdict(True, "2026-01-01", False, "2026-09-26") == (False, "2026-09-26")


def test_a_probe_records_which_model_answered_when_it_is_another():
    """Google answers a retired id with its replacement; a dated snapshot of
    the same model is not a different model."""
    from app.catalog.sync import routed_to

    assert routed_to("gemini-3.5-flash", "gemini-3.6-flash") == "gemini-3.6-flash"
    assert routed_to("gemini-3.5-flash", "models/gemini-3.5-flash") is None
    assert routed_to("gpt-5.4-nano", "gpt-5.4-nano-2026-03-17") is None
    assert routed_to("gpt-5.4-nano", None) is None

    def answer_as_another(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return transport([]).handle_request(request)
        if request.url.host == "generativelanguage.googleapis.com":
            return httpx.Response(200, json={"candidates": [], "modelVersion": "gemini-10-flash"})
        return httpx.Response(200, json={"model": "claude-x-20260901"})

    with httpx.Client(transport=httpx.MockTransport(answer_as_another)) as client:
        catalog, _ = sync_catalog({}, {"anthropic": "k", "google": "k"}, client=client, today="2026-11-10",
                                  probe_web_search=False)
    assert catalog["gemini-9-flash"].verification.served_as == "gemini-10-flash"
    assert catalog["gemini-9-flash"].routed
    assert catalog["claude-x"].verification.served_as is None  # a dated snapshot of itself


# ─── Reasoning-effort levels ─────────────────────────────────────


def effort_transport(calls, refuse=(), flaky=(), broken=()):
    """Answers every listing; refuses (400, naming the parameter) the effort
    levels in `refuse`, rate-limits those in `flaky` and refuses those in
    `broken` for another reason."""
    inner = transport(calls)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            level = (body.get("reasoning_effort") or (body.get("reasoning") or {}).get("effort")
                     or ((body.get("generationConfig") or {}).get("thinkingConfig") or {}).get("thinkingLevel"))
            if level in refuse:
                return httpx.Response(400, json={"error": {
                    "message": f"Unsupported value: 'reasoning_effort' does not support '{level}' with this model."}})
            if level in broken:
                return httpx.Response(400, json={"error": {"message": "Unknown parameter: 'max_completion_tokens'."}})
            if level in flaky:
                return httpx.Response(429, json={"error": {"message": "slow down"}})
        return inner.handle_request(request)

    return httpx.MockTransport(handler)


def test_anthropic_effort_levels_come_from_its_listing():
    from app.catalog.sources import AnthropicSource

    raw = {**ANTHROPIC_MODELS["data"][0], "capabilities": {
        "effort": {"supported": True, "low": {"supported": True}, "high": {"supported": True}, "max": {"supported": False}},
    }}
    assert AnthropicSource().normalize(raw).capabilities["reasoning_effort"] == ["low", "high"]
    raw["capabilities"]["effort"]["supported"] = False
    assert AnthropicSource().normalize(raw).capabilities["reasoning_effort"] == []
    # A listing that says nothing about effort records nothing: unknown, not none.
    assert "reasoning_effort" not in AnthropicSource().normalize(ANTHROPIC_MODELS["data"][0]).capabilities


def test_effort_probes_record_the_levels_a_model_takes_and_only_for_offered_models():
    calls: list = []
    with httpx.Client(transport=effort_transport(calls, refuse=("minimal", "xhigh"))) as client:
        catalog, diff = sync_catalog({}, KEYS, client=client, today="2026-09-26", effort_ids={"gpt-9", "gpt-9-pro"})
    assert catalog["gpt-9"].capabilities["reasoning_effort"] == ["low", "medium", "high"]
    assert diff.probed["gpt-9"]["efforts"] == ["low", "medium", "high"]
    # The Responses-only model is probed there, with `reasoning.effort`.
    assert catalog["gpt-9-pro"].capabilities["reasoning_effort"] == ["low", "medium", "high"]
    assert ("POST", "/v1/responses") in calls
    # Not offered: not probed.
    assert "reasoning_effort" not in catalog["gemini-9-flash"].capabilities


def test_an_inconclusive_effort_probe_records_nothing_and_effort_mode_retries_it():
    with httpx.Client(transport=effort_transport([], flaky=("high",))) as client:
        catalog, diff = sync_catalog({}, KEYS, client=client, today="2026-09-26", effort_ids={"gpt-9"})
    assert "reasoning_effort" not in catalog["gpt-9"].capabilities
    assert diff.probed["gpt-9"]["efforts"] is None

    calls: list = []
    with httpx.Client(transport=effort_transport(calls)) as client:
        again, diff = sync_catalog(catalog, KEYS, client=client, today="2026-09-27", probe="effort", effort_ids={"gpt-9"})
    assert again["gpt-9"].capabilities["reasoning_effort"] == ["minimal", "low", "medium", "high", "xhigh"]
    assert list(diff.probed) == ["gpt-9"] and diff.probed["gpt-9"]["chat"] is None
    # Only effort calls: no chat or search probe went out again.
    posts = [c for c in calls if c[0] == "POST"]
    assert len(posts) == 5

    # Recorded levels are kept: effort mode doesn't call again.
    calls.clear()
    with httpx.Client(transport=effort_transport(calls)) as client:
        _, diff = sync_catalog(again, KEYS, client=client, today="2026-09-28", probe="effort", effort_ids={"gpt-9"})
    assert diff.probed == {} and not [c for c in calls if c[0] == "POST"]


def test_a_refusal_that_isnt_about_the_effort_records_nothing():
    """A request shape the provider stopped taking would refuse every level:
    that must not become "this model has no reasoning effort"."""
    with httpx.Client(transport=effort_transport([], broken=("minimal", "low", "medium", "high", "xhigh"))) as client:
        catalog, diff = sync_catalog({}, KEYS, client=client, today="2026-09-26", effort_ids={"gpt-9"})
    assert "reasoning_effort" not in catalog["gpt-9"].capabilities
    assert diff.probed["gpt-9"]["efforts"] is None
