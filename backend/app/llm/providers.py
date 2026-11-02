"""Provider strategies: how each model family is constructed.

To add a provider family:
  1. add its family to FAMILY_META (label, colour, env_key) in registry.py
  2. write a ChatProvider below and register it in PROVIDERS
  3. write a ProviderSource in catalog/sources.py, so catalog-sync lists and
     probes its models
  4. add its models to MODEL_REGISTRY once the catalog has verified them
Nothing else in the app branches on the provider.
"""

import functools
from typing import Any, Callable, Mapping, Optional, Protocol

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable


class ChatProvider(Protocol):
    """Builds chat models for one provider family."""

    def create(self, model_id: str, api_key: Optional[str] = None) -> BaseChatModel:
        """A client for `model_id` (the provider's own model name), using
        `api_key` (None: the SDK reads its environment variable)."""
        ...

    def with_web_search(self, llm: BaseChatModel) -> Runnable:
        """`llm` with the provider's native web-search tool bound."""
        ...


# Every turn re-sends the whole conversation, so the prefix is cached: a
# breakpoint on the last block (what the API's automatic caching does) makes
# the next turn read everything up to here at ~0.1x the input price, for a
# ~1.25x write on what is new. Prefixes under the model's minimum (4,096
# tokens on Haiku 4.5, 1,024 on Sonnet 5) are simply not cached, at no cost.
CACHE_CONTROL = {"type": "ephemeral"}
# Opens the block that carries context for one request only (the time,
# recalled excerpts). It follows the question, and the cache breakpoint goes
# on the block before it: the next turn's history contains the question but
# not this block, so a breakpoint on it would be written and never read.
REQUEST_NOTES_HEADER = "[Context for this request only]"


def mark_cache_breakpoint(messages: list) -> None:
    """Put one cache breakpoint on the last block that the next request will
    repeat: the last block of the last message, or the one before it when
    the last block is per-request context."""
    if not messages:
        return
    last = messages[-1]
    content = last.get("content")
    if isinstance(content, str):
        content = last["content"] = [{"type": "text", "text": content}]
    if not isinstance(content, list) or not content:
        return
    index = len(content) - 1
    block = content[index]
    if index > 0 and isinstance(block, dict) and str(block.get("text", "")).startswith(REQUEST_NOTES_HEADER):
        index -= 1
    if isinstance(content[index], dict):
        content[index]["cache_control"] = CACHE_CONTROL


@functools.lru_cache(maxsize=1)
def _caching_chat_anthropic():
    from langchain_anthropic import ChatAnthropic

    class CachingChatAnthropic(ChatAnthropic):
        """ChatAnthropic that marks every request's reusable prefix for caching."""

        def _get_request_payload(self, input_, *, stop=None, **kwargs):
            payload = super()._get_request_payload(input_, stop=stop, **kwargs)
            mark_cache_breakpoint(payload.get("messages") or [])
            return payload

    return CachingChatAnthropic


def split_request_notes(messages: list, role: str = "system") -> None:
    """Move a trailing per-request block out of the last user message into a
    message of its own. OpenAI (GPT-5.6+) places its implicit cache
    breakpoint at the end of the latest user message; with the per-request
    block inside it, the next turn never matched and every turn re-wrote the
    whole prefix at 1.25x. A trailing system message is not a breakpoint, so
    the breakpoint lands after the question, which the next turn repeats."""
    if not messages:
        return
    last = messages[-1]
    content = last.get("content")
    if last.get("role") != "user" or not isinstance(content, list) or len(content) < 2:
        return
    block = content[-1]
    text = block.get("text") if isinstance(block, dict) else None
    if not (isinstance(text, str) and text.startswith(REQUEST_NOTES_HEADER)):
        return
    last["content"] = content[:-1]
    messages.append({"role": role, "content": text})


@functools.lru_cache(maxsize=1)
def _caching_chat_openai():
    from langchain_openai import ChatOpenAI

    class CachingChatOpenAI(ChatOpenAI):
        """ChatOpenAI whose requests keep the implicit cache breakpoint reusable."""

        def _get_request_payload(self, input_, *, stop=None, **kwargs):
            payload = super()._get_request_payload(input_, stop=stop, **kwargs)
            if isinstance(payload.get("messages"), list):
                split_request_notes(payload["messages"])
            elif isinstance(payload.get("input"), list):  # Responses API
                split_request_notes(payload["input"], role="developer")
            return payload

    return CachingChatOpenAI


def _key(name: str, api_key: Optional[str]) -> dict:
    return {name: api_key} if api_key else {}


class OpenAIProvider:
    def create(self, model_id: str, api_key: Optional[str] = None) -> BaseChatModel:
        return _caching_chat_openai()(model=model_id, **_key("api_key", api_key))

    def with_web_search(self, llm: Any) -> Runnable:
        return llm.bind_tools([{"type": "web_search_preview"}])


class AnthropicProvider:
    def create(self, model_id: str, api_key: Optional[str] = None) -> BaseChatModel:
        return _caching_chat_anthropic()(model=model_id, **_key("api_key", api_key))

    def with_web_search(self, llm: Any) -> Runnable:
        # Models without code execution (e.g. Haiku 4.5) reject the dynamic-
        # filtering search tool unless it is called directly; the catalog says
        # which models have it, and unknown models get the safe direct form.
        from app.catalog import load_catalog
        from app.catalog.sources import anthropic_web_search_tool

        entry = load_catalog().get(getattr(llm, "model", ""))
        code_execution = entry.capabilities.get("code_execution") if entry else None
        return llm.bind_tools([anthropic_web_search_tool(code_execution)])


# Gemini 3.6+ ignores sampling parameters and the upcoming models reject
# requests that carry them, but langchain-google-genai fills in
# temperature=1.0 for every Gemini 3+ id. Leave the three out of the request
# so the model uses its own defaults. (Thinking depth is `thinking_level`;
# `thinking_budget` is rejected too, and nothing here sets it.)
SAMPLING_PARAMETERS = ("temperature", "top_p", "top_k")


@functools.lru_cache(maxsize=1)
def _chat_google():
    from langchain_google_genai import ChatGoogleGenerativeAI

    class SamplingFreeChatGoogle(ChatGoogleGenerativeAI):
        """ChatGoogleGenerativeAI that never sends temperature, top_p or top_k."""

        def _build_base_generation_config(self, stop, **kwargs):
            config = super()._build_base_generation_config(stop, **kwargs)
            for name in SAMPLING_PARAMETERS:
                config.pop(name, None)
            return config

    return SamplingFreeChatGoogle


class GoogleProvider:
    def create(self, model_id: str, api_key: Optional[str] = None) -> BaseChatModel:
        return _chat_google()(model=model_id, **_key("google_api_key", api_key))

    def with_web_search(self, llm: Any) -> Runnable:
        return llm.bind_tools([{"google_search": {}}])


# xAI caches the longest run of leading messages that matches an earlier
# request exactly (https://docs.x.ai/developers/advanced-api-usage/prompt-caching/how-it-works),
# so a per-request block inside the question has the same effect as on
# OpenAI: the next turn's copy of that message differs, and nothing after the
# previous answer's prompt is reused. xAI accepts system messages anywhere in
# a conversation ("No role order limitation", https://docs.x.ai/developers/models)
# and documents only system/user/assistant roles, so the moved block is a
# system message on both of its APIs.
@functools.lru_cache(maxsize=1)
def _caching_chat_xai():
    from langchain_xai import ChatXAI

    class CachingChatXAI(ChatXAI):
        """ChatXAI whose requests keep the reusable prefix intact."""

        def _get_request_payload(self, input_, *, stop=None, **kwargs):
            payload = super()._get_request_payload(input_, stop=stop, **kwargs)
            if isinstance(payload.get("messages"), list):
                split_request_notes(payload["messages"])
            elif isinstance(payload.get("input"), list):  # Responses API
                split_request_notes(payload["input"])
            return payload

    return CachingChatXAI


class XAIProvider:
    """Grok models through langchain-xai. ChatXAI turns `stream_usage` on by
    itself, so a streamed reply ends with its usage_metadata like the others.

    Plain turns go to chat/completions (ChatXAI's default). A model the
    catalog probe found answering only on the Responses API is sent there.
    Web search binds xAI's search tool, which exists only on the Responses
    API; binding a built-in tool makes langchain-openai, which ChatXAI
    extends, send the request to api.x.ai/v1/responses."""

    def __init__(self, catalog: Optional[Callable[[], Mapping[str, Any]]] = None):
        # What the catalog knows about each model; the committed catalog by default.
        self._catalog = catalog

    def _entry(self, model_id: str) -> Any:
        if self._catalog is None:
            from app.catalog import load_catalog

            return load_catalog().get(model_id)
        return self._catalog().get(model_id)

    def create(self, model_id: str, api_key: Optional[str] = None) -> BaseChatModel:
        entry = self._entry(model_id)
        responses_only = bool(entry and entry.capabilities.get("api") == "responses")
        return _caching_chat_xai()(
            model=model_id,
            **_key("api_key", api_key),
            **({"use_responses_api": True} if responses_only else {}),
        )

    def with_web_search(self, llm: Any) -> Runnable:
        from app.catalog.sources import XAI_WEB_SEARCH_TOOL

        return llm.bind_tools([dict(XAI_WEB_SEARCH_TOOL)])


# Keyed by MODEL_REGISTRY[...]["family"].
PROVIDERS: dict[str, ChatProvider] = {
    "openai": OpenAIProvider(),
    "anthropic": AnthropicProvider(),
    "google": GoogleProvider(),
    "xai": XAIProvider(),
}
