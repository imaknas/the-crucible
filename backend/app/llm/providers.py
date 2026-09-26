"""Provider strategies: how each model family is constructed.

To add a provider family:
  1. add its family to FAMILY_META (label, colour, env_key) in api/models.py
  2. write a ChatProvider below and register it in PROVIDERS
  3. add its models to MODEL_REGISTRY
Nothing else in the app branches on the provider.
"""

from typing import Any, Protocol

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable


class ChatProvider(Protocol):
    """Builds chat models for one provider family."""

    def create(self, model_id: str) -> BaseChatModel:
        """A client for `model_id` (the provider's own model name)."""
        ...

    def with_web_search(self, llm: BaseChatModel) -> Runnable:
        """`llm` with the provider's native web-search tool bound."""
        ...


class OpenAIProvider:
    def create(self, model_id: str) -> BaseChatModel:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model_id)

    def with_web_search(self, llm: Any) -> Runnable:
        return llm.bind_tools([{"type": "web_search_preview"}])


class AnthropicProvider:
    def create(self, model_id: str) -> BaseChatModel:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model_id)

    def with_web_search(self, llm: Any) -> Runnable:
        # Models without code execution (e.g. Haiku 4.5) reject the dynamic-
        # filtering search tool unless it is called directly; the catalog says
        # which models have it, and unknown models get the safe direct form.
        from app.catalog import load_catalog
        from app.catalog.sources import anthropic_web_search_tool

        entry = load_catalog().get(getattr(llm, "model", ""))
        code_execution = entry.capabilities.get("code_execution") if entry else None
        return llm.bind_tools([anthropic_web_search_tool(code_execution)])


class GoogleProvider:
    def create(self, model_id: str) -> BaseChatModel:
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=model_id)

    def with_web_search(self, llm: Any) -> Runnable:
        return llm.bind_tools([{"google_search": {}}])


# Keyed by MODEL_REGISTRY[...]["family"].
PROVIDERS: dict[str, ChatProvider] = {
    "openai": OpenAIProvider(),
    "anthropic": AnthropicProvider(),
    "google": GoogleProvider(),
}
