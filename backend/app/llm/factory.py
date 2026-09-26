"""ModelFactory: the one way the app obtains a chat model.

Code asks a factory for a model instead of constructing clients itself, so the
choice of real provider, scripted fake or test stub is made in one place:

- Graph nodes call ``model_factory_from(config).chat(model_id, toggles)``. A
  run may inject its own factory as ``config["configurable"]["model_factory"]``.
- Everything else uses ``default_model_factory()``: the real providers, or the
  scripted fake when CRUCIBLE_FAKE_LLM is set.
- Tests swap the default with ``with use_model_factory(factory): ...``.
"""

import os
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Mapping, Optional, Protocol

from langchain_core.runnables import Runnable

from app.api.models import FAMILY_META, MODEL_REGISTRY
from app.llm.providers import PROVIDERS, ChatProvider

FACTORY_CONFIG_KEY = "model_factory"


class ModelFactory(Protocol):
    def chat(self, model_id: str, toggles: Optional[Mapping[str, Any]] = None) -> Runnable:
        """A chat model for a registered model ID. Raises ValueError if unusable."""
        ...


def normalize_model_id(model_id: str) -> str:
    """Registry keys are lowercase; callers may pass padding or capitals."""
    key = model_id.strip().lower()
    if key not in MODEL_REGISTRY:
        raise ValueError(f"Model '{model_id.strip()}' is not supported in the whitelist.")
    return key


def has_credentials(model_id: str, env: Mapping[str, str] = os.environ) -> bool:
    """Whether the API key for this model's provider family is set."""
    family = MODEL_REGISTRY.get(model_id.strip().lower(), {}).get("family")
    meta = FAMILY_META.get(family) if isinstance(family, str) else None
    return bool(env.get(meta["env_key"])) if meta else True


class ProviderModelFactory:
    """Builds real clients through the provider strategy of each model's family."""

    def __init__(
        self,
        registry: Mapping[str, Mapping[str, Any]] = MODEL_REGISTRY,
        providers: Mapping[str, ChatProvider] = PROVIDERS,
        env: Mapping[str, str] = os.environ,
    ):
        self._registry = registry
        self._providers = providers
        self._env = env

    def chat(self, model_id: str, toggles: Optional[Mapping[str, Any]] = None) -> Runnable:
        key = normalize_model_id(model_id)
        config = self._registry[key]
        family = config["family"]
        if not has_credentials(key, self._env):
            env_key = FAMILY_META[family]["env_key"]
            raise ValueError(f"{env_key} is not set in environment or .env file.")

        provider = self._providers[family]
        llm = provider.create(config["id"])
        if (toggles or {}).get("use_web_search") and config.get("native_search"):
            return provider.with_web_search(llm)
        return llm


class CallableModelFactory:
    """Adapts ``fn(model_id, toggles) -> model`` to ModelFactory, for tests and scripts.

    Model IDs are still validated against the registry.
    """

    def __init__(self, fn: Callable[[str, Mapping[str, Any]], Runnable]):
        self._fn = fn

    def chat(self, model_id: str, toggles: Optional[Mapping[str, Any]] = None) -> Runnable:
        return self._fn(normalize_model_id(model_id), toggles or {})


_override: Optional[ModelFactory] = None


def default_model_factory() -> ModelFactory:
    if _override is not None:
        return _override
    from app.llm import fake

    if fake.enabled():
        return fake.ScriptedModelFactory()
    return ProviderModelFactory()


@contextmanager
def use_model_factory(factory: ModelFactory) -> Iterator[ModelFactory]:
    """Make `factory` the process default inside the block (tests, scripts)."""
    global _override
    previous, _override = _override, factory
    try:
        yield factory
    finally:
        _override = previous


def model_factory_from(config: Optional[Mapping[str, Any]]) -> ModelFactory:
    """The factory a graph node should use: the run's own, else the default."""
    injected = ((config or {}).get("configurable") or {}).get(FACTORY_CONFIG_KEY)
    return injected or default_model_factory()
