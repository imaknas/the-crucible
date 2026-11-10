"""Provider sources: one strategy per provider.

Each source lists models from the provider's own API, normalizes them into
CatalogEntry facts, decides which are chat-model candidates, and probes a
model with a real minimal request. HTTP goes through an injected httpx client
so tests can replay recorded responses.

Adding a provider: implement ProviderSource and add it to SOURCES.
"""

import re
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

import httpx

from app.catalog.entry import CatalogEntry

PROBE_PROMPT = "Reply with the single word OK."
SEARCH_PROMPT = "Use web search: what is today's top headline on bbc.com? One line."


SEARCH_TIMEOUT = 300.0  # reasoning models can search for minutes


class ProbeResult:
    """ok=True/False is a verdict; ok=None means inconclusive (timeout, network).
    `capabilities` are facts the probe learned (e.g. which API answered)."""

    def __init__(self, ok: Optional[bool], error: Optional[str] = None, capabilities: Optional[dict] = None,
                 served: Optional[str] = None):
        self.ok, self.error, self.capabilities = ok, error, capabilities or {}
        # The model the provider says answered (its response's model name):
        # a provider can route a retired id to another model and still answer.
        self.served = served


def anthropic_web_search_tool(code_execution: Optional[bool], max_uses: int = 3) -> dict[str, Any]:
    """The web-search tool definition for a Claude model.

    web_search_20260209 filters results dynamically through programmatic tool
    calling, which models without code execution reject (HTTP 400). For those,
    and when capabilities are unknown, the tool must be called directly.
    Shared by the app's provider and the catalog probe so both test the same thing.
    """
    tool: dict[str, Any] = {"type": "web_search_20260209", "name": "web_search", "max_uses": max_uses}
    if not code_execution:
        tool["allowed_callers"] = ["direct"]
    return tool


# xAI's own search tool, which exists only on its Responses API
# (https://docs.x.ai/developers/tools/web-search). Shared by the app's
# provider and the catalog probe.
XAI_WEB_SEARCH_TOOL: dict[str, Any] = {"type": "web_search"}


def guarded(call) -> ProbeResult:
    """Run one probe; transport failures are inconclusive, never a crash."""
    try:
        return call()
    except httpx.TimeoutException as e:
        return ProbeResult(None, f"timed out ({type(e).__name__})")
    except httpx.HTTPError as e:
        return ProbeResult(None, f"{type(e).__name__}: {e}")


class ProviderSource(Protocol):
    name: str
    env_key: str

    def list_models(self, client: httpx.Client, key: str) -> list[dict[str, Any]]: ...

    def is_chat_candidate(self, raw: dict[str, Any]) -> bool: ...

    def normalize(self, raw: dict[str, Any]) -> CatalogEntry: ...

    def probe_chat(self, client: httpx.Client, key: str, model_id: str) -> ProbeResult: ...

    def probe_web_search(self, client: httpx.Client, key: str, entry: CatalogEntry) -> ProbeResult: ...


# Error text is committed with the catalog (a public file): keep account
# identifiers out of it.
_ACCOUNT_IDS = re.compile(r"\b(org|proj|user|acct)[-_][A-Za-z0-9]{6,}\b")
# xAI names the account as a team, by UUID ("your team <uuid> does not have
# access"); any UUID in an error is an identifier nobody reading the catalog needs.
_UUIDS = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


def _redact(text: str) -> str:
    return _UUIDS.sub("…", _ACCOUNT_IDS.sub(lambda m: f"{m.group(1)}-…", text))


def _probe(response: httpx.Response) -> ProbeResult:
    if response.is_success:
        return ProbeResult(True, served=_served_model(response))
    try:
        detail = response.json()
        # OpenAI, Anthropic and Google answer {"error": {...}} or {"error": "..."};
        # xAI's errors can be a bare JSON string.
        if isinstance(detail, dict):
            err = detail.get("error")
            message = err.get("message") if isinstance(err, dict) else err
        else:
            message = detail
    except ValueError:
        message = response.text
    error = f"HTTP {response.status_code}: {_redact(str(message))[:200]}"
    # Rate limits and server errors say nothing about the model: inconclusive.
    if response.status_code == 429 or response.status_code >= 500:
        return ProbeResult(None, error)
    return ProbeResult(False, error)


def _served_model(response: httpx.Response) -> Optional[str]:
    """The model a successful response says answered: `model` (OpenAI,
    Anthropic, xAI) or `modelVersion` (Google)."""
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    served = body.get("model") or body.get("modelVersion")
    return str(served).removeprefix("models/") if served else None


def _day(ts: str | int | float | None) -> Optional[str]:
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
    return str(ts)[:10]


# ─── OpenAI ──────────────────────────────────────────────────────


class OpenAISource:
    """The list endpoint gives id, creation time and shutdown date only; context
    windows come from overrides. Whether an id is a chat model is only known by
    calling chat/completions — several listed "-pro" ids are Responses-only."""

    name = "openai"
    env_key = "OPENAI_API_KEY"
    base = "https://api.openai.com/v1"
    _chat_like = re.compile(r"^(gpt-\d|o\d)")
    _not_chat = re.compile(r"audio|tts|realtime|image|transcribe|search|embedding|moderation|codex|chat-latest|\d{4}-\d{2}-\d{2}$")

    def _headers(self, key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}"}

    def list_models(self, client, key):
        r = client.get(f"{self.base}/models", headers=self._headers(key))
        r.raise_for_status()
        return r.json()["data"]

    def is_chat_candidate(self, raw):
        mid = raw["id"]
        return bool(self._chat_like.match(mid)) and not self._not_chat.search(mid)

    def normalize(self, raw):
        return CatalogEntry(
            id=raw["id"],
            provider=self.name,
            display_name=raw["id"],
            released=_day(raw.get("created")),
            shutdown_date=_day(raw.get("shutdown_date")),
        )

    docs = "https://developers.openai.com/api/docs/models/{id}"
    _window = re.compile(r"([\d,]+)\s*context window", re.I)
    _max_out = re.compile(r"([\d,]+)\s*max output tokens", re.I)

    def enrich(self, client, entry: CatalogEntry) -> None:
        """Limits from OpenAI's own model page; the API doesn't expose them.

        The page's context window counts output too, so the input limit stored
        is window − max output. Leaves the entry alone if the page can't be read.
        """
        url = self.docs.format(id=entry.id)
        try:
            r = client.get(url, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True)
        except httpx.HTTPError:
            return
        if not r.is_success:
            return
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))
        window, max_out = self._window.search(text), self._max_out.search(text)
        if not (window and max_out):
            return
        window_n, out_n = int(window.group(1).replace(",", "")), int(max_out.group(1).replace(",", ""))
        entry.output_limit = out_n
        entry.input_limit = window_n - out_n
        entry.sources["input_limit"] = f"openai docs ({window_n:,} context window − {out_n:,} max output): {url}"
        entry.sources["output_limit"] = f"openai docs: {url}"

    def probe_chat(self, client, key, model_id):
        """chat/completions first; models that only answer on the Responses API
        (several "-pro" ids) are still usable — LangChain routes them there —
        so fall back and record which API answered."""
        chat = _probe(client.post(f"{self.base}/chat/completions", headers=self._headers(key), json={
            "model": model_id,
            "messages": [{"role": "user", "content": PROBE_PROMPT}],
            "max_completion_tokens": 64,
        }))
        if chat.ok or not chat.error or "HTTP 404" not in chat.error:
            return ProbeResult(chat.ok, chat.error, {"api": "chat_completions"} if chat.ok else {})
        responses = _probe(client.post(f"{self.base}/responses", headers=self._headers(key), json={
            "model": model_id, "input": PROBE_PROMPT, "max_output_tokens": 64,
        }))
        if responses.ok:
            return ProbeResult(True, None, {"api": "responses"})
        return ProbeResult(False, f"{chat.error}; responses: {responses.error}")

    def probe_web_search(self, client, key, entry):
        return _probe(client.post(f"{self.base}/responses", headers=self._headers(key), timeout=SEARCH_TIMEOUT, json={
            "model": entry.id,
            "input": SEARCH_PROMPT,
            "tools": [{"type": "web_search_preview"}],
        }))


# ─── Anthropic ───────────────────────────────────────────────────


class AnthropicSource:
    """The richest listing: display name, input/output limits and capabilities."""

    name = "anthropic"
    env_key = "ANTHROPIC_API_KEY"
    base = "https://api.anthropic.com/v1"
    version = "2023-06-01"

    def _headers(self, key: str) -> dict[str, str]:
        return {"x-api-key": key, "anthropic-version": self.version}

    def list_models(self, client, key):
        models, after = [], None
        while True:
            params = {"limit": 100, **({"after_id": after} if after else {})}
            r = client.get(f"{self.base}/models", headers=self._headers(key), params=params)
            r.raise_for_status()
            body = r.json()
            models += body["data"]
            if not body.get("has_more"):
                return models
            after = body["last_id"]

    def is_chat_candidate(self, raw):
        return raw.get("type", "model") == "model"

    def normalize(self, raw):
        caps = raw.get("capabilities") or {}
        flat = {name: bool((v or {}).get("supported")) for name, v in caps.items() if isinstance(v, dict)}
        ctx = caps.get("context_management") or {}
        flat["provider_compaction"] = any(
            k.startswith("compact") and (v or {}).get("supported") for k, v in ctx.items() if isinstance(v, dict)
        )
        return CatalogEntry(
            id=raw["id"],
            provider=self.name,
            display_name=raw.get("display_name") or raw["id"],
            released=_day(raw.get("created_at")),
            input_limit=raw.get("max_input_tokens"),
            output_limit=raw.get("max_tokens"),
            capabilities=flat,
        )

    def probe_chat(self, client, key, model_id):
        return _probe(client.post(f"{self.base}/messages", headers=self._headers(key), json={
            "model": model_id,
            "max_tokens": 16,
            "messages": [{"role": "user", "content": PROBE_PROMPT}],
        }))

    def probe_web_search(self, client, key, entry):
        return _probe(client.post(f"{self.base}/messages", headers=self._headers(key), timeout=SEARCH_TIMEOUT, json={
            "model": entry.id,
            "max_tokens": 1024,
            "tools": [anthropic_web_search_tool(entry.capabilities.get("code_execution"), max_uses=1)],
            "messages": [{"role": "user", "content": SEARCH_PROMPT}],
        }))


# ─── Google ──────────────────────────────────────────────────────


class GoogleSource:
    """Listing includes input/output limits, supported methods and thinking."""

    name = "google"
    env_key = "GOOGLE_API_KEY"
    base = "https://generativelanguage.googleapis.com/v1beta"
    _not_chat = re.compile(r"image|tts|transcribe|embedding|aqa|robotics|computer-use|live|native-audio|customtools")

    def _headers(self, key: str) -> dict[str, str]:
        return {"x-goog-api-key": key}

    def list_models(self, client, key):
        models, token = [], None
        while True:
            params = {"pageSize": 1000, **({"pageToken": token} if token else {})}
            r = client.get(f"{self.base}/models", headers=self._headers(key), params=params)
            r.raise_for_status()
            body = r.json()
            models += body.get("models", [])
            token = body.get("nextPageToken")
            if not token:
                return models

    def is_chat_candidate(self, raw):
        mid = raw["name"].split("/")[-1]
        return (
            mid.startswith("gemini-")
            and "generateContent" in raw.get("supportedGenerationMethods", [])
            and not self._not_chat.search(mid)
        )

    def normalize(self, raw):
        return CatalogEntry(
            id=raw["name"].split("/")[-1],
            provider=self.name,
            display_name=raw.get("displayName") or raw["name"],
            input_limit=raw.get("inputTokenLimit"),
            output_limit=raw.get("outputTokenLimit"),
            capabilities={
                "thinking": bool(raw.get("thinking")),
                "context_caching": "createCachedContent" in raw.get("supportedGenerationMethods", []),
            },
        )

    def _generate(self, client, key, model_id, body, timeout=None):
        return _probe(client.post(
            f"{self.base}/models/{model_id}:generateContent", headers=self._headers(key), json=body,
            **({"timeout": timeout} if timeout else {}),
        ))

    def probe_chat(self, client, key, model_id):
        return self._generate(client, key, model_id, {"contents": [{"parts": [{"text": PROBE_PROMPT}]}]})

    def probe_web_search(self, client, key, entry):
        return self._generate(client, key, entry.id, {
            "contents": [{"parts": [{"text": SEARCH_PROMPT}]}],
            "tools": [{"google_search": {}}],
        }, timeout=SEARCH_TIMEOUT)


# ─── xAI ─────────────────────────────────────────────────────────


class XAISource:
    """Two listings (https://docs.x.ai/developers/rest-api-reference/inference/models):
    /v1/language-models lists the chat models with their modalities, aliases
    and reasoning efforts; only /v1/models reports `context_length`. Both
    report prices too, which stay in prices.json like every provider's.

    xAI calls Chat Completions legacy and puts its tools (web search included)
    on the Responses API only, so chat is probed on chat/completions — what
    ChatXAI sends — with the Responses API as the fallback, and web search on
    the Responses API."""

    name = "xai"
    env_key = "XAI_API_KEY"
    base = "https://api.x.ai/v1"
    docs = "https://docs.x.ai/developers/rest-api-reference/inference/models"
    _not_chat = re.compile(r"imagine|image|video|voice|tts|transcribe|embed")

    def _headers(self, key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}"}

    def list_models(self, client, key):
        r = client.get(f"{self.base}/language-models", headers=self._headers(key))
        r.raise_for_status()
        models = r.json()["models"]
        r = client.get(f"{self.base}/models", headers=self._headers(key))
        r.raise_for_status()
        windows = {m["id"]: m.get("context_length") for m in r.json().get("data", [])}
        return [{**m, "context_length": windows.get(m["id"])} for m in models]

    def is_chat_candidate(self, raw):
        mid = raw["id"]
        return (
            mid.startswith("grok-")
            and "text" in raw.get("output_modalities", [])
            and not self._not_chat.search(mid)
        )

    def normalize(self, raw):
        caps = raw.get("capabilities") or {}
        capabilities: dict[str, Any] = {"image_input": "image" in raw.get("input_modalities", [])}
        if caps.get("reasoning_effort"):
            capabilities["reasoning_effort"] = list(caps["reasoning_effort"])
        # A request may name a model by an alias, but the registry and the
        # price list key on the id: knowing the aliases says which id that is.
        if raw.get("aliases"):
            capabilities["aliases"] = sorted(raw["aliases"])
        entry = CatalogEntry(
            id=raw["id"],
            provider=self.name,
            display_name=raw["id"],
            released=_day(raw.get("created")),
            input_limit=raw.get("context_length"),
            capabilities=capabilities,
        )
        if entry.input_limit is not None:
            entry.sources["input_limit"] = (
                f"xai /v1/models context_length (shared by input and output; no output limit is reported): {self.docs}"
            )
        return entry

    def _post(self, client, key, path, body, timeout=None):
        return _probe(client.post(
            f"{self.base}/{path}", headers=self._headers(key), json=body,
            **({"timeout": timeout} if timeout else {}),
        ))

    def probe_chat(self, client, key, model_id):
        chat = self._post(client, key, "chat/completions", {
            "model": model_id,
            "messages": [{"role": "user", "content": PROBE_PROMPT}],
            "max_completion_tokens": 64,
        })
        if chat.ok or not chat.error or "HTTP 404" not in chat.error:
            return ProbeResult(chat.ok, chat.error, {"api": "chat_completions"} if chat.ok else {})
        responses = self._post(client, key, "responses", {
            "model": model_id, "input": PROBE_PROMPT, "max_output_tokens": 64, "store": False,
        })
        if responses.ok:
            return ProbeResult(True, None, {"api": "responses"})
        return ProbeResult(False, f"{chat.error}; responses: {responses.error}")

    def probe_web_search(self, client, key, entry):
        return self._post(client, key, "responses", {
            "model": entry.id,
            "input": SEARCH_PROMPT,
            "tools": [dict(XAI_WEB_SEARCH_TOOL)],
            "store": False,
        }, timeout=SEARCH_TIMEOUT)


SOURCES: dict[str, ProviderSource] = {
    s.name: s for s in (OpenAISource(), AnthropicSource(), GoogleSource(), XAISource())
}
