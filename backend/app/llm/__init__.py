"""Everything that turns a model ID into a chat model.

- providers.py: one strategy per provider family (how to build the client,
  how to enable web search). Add a provider here.
- factory.py: ModelFactory, the single way the rest of the app obtains a
  model, and how tests / e2e swap in fakes.
- fake.py: the scripted model used by tests and the Playwright suite.
"""

from app.llm.factory import (
    CallableModelFactory,
    ModelFactory,
    ProviderModelFactory,
    default_model_factory,
    has_credentials,
    model_factory_from,
    use_model_factory,
)

__all__ = [
    "CallableModelFactory",
    "ModelFactory",
    "ProviderModelFactory",
    "default_model_factory",
    "has_credentials",
    "model_factory_from",
    "use_model_factory",
]
