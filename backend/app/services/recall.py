"""The app's default history recall, and the model step it uses.

Once a thread has been summarized, the originals are still in the
checkpoint. Guided recall asks a small model which of them the current
request is about and shows those again, so a detail the summary dropped is
not lost (experiments/NOTES.md, pilots 16-20).

The default is attached where the app starts a run (chat, arena, debate),
not inside the graph: runs that build their own config, such as the
compaction experiments, get exactly the recall they ask for.
"""

import os
from dataclasses import dataclass, replace
from typing import Any, Mapping, MutableMapping, Optional

from langchain_core.messages import HumanMessage

from app.compaction import GuidedRecall, HistoryRecall
from app.utils.helpers import extract_text

# Tags the rewriter's own model call. Stream consumers exclude it so its
# search terms never reach the chat as part of the reply; callbacks (and so
# spend metering) still see it.
INTERNAL_TAG = "crucible:internal"

REWRITE_PROMPT = (
    "Earlier parts of this conversation are hidden. What is still visible about them:\n{hint}\n\n"
    "A new question: {query}\n\n"
    "Which topics or subjects from the earlier conversation is this question about? Reply with their exact "
    "names and the key terms to search for, on one line, nothing else."
)


@dataclass(frozen=True)
class ModelRewriter:
    """A GuidedRecall rewrite step backed by chat model `model_id` from
    `factory`. Knows its model, so an estimate can meter it with a stand-in
    (`on`) instead of calling the real one."""

    model_id: str
    factory: Any

    def prompt(self, query: str, hint: str) -> str:
        return REWRITE_PROMPT.format(hint=hint[:8000], query=query)

    def __call__(self, query: str, hint: str) -> str:
        reply = self.factory.chat(self.model_id).invoke(
            [HumanMessage(content=self.prompt(query, hint))], config={"tags": [INTERNAL_TAG]}
        )
        return extract_text(reply.content)

    def on(self, factory) -> "ModelRewriter":
        return replace(self, factory=factory)


def default_recall_model(env: Mapping[str, str] = os.environ) -> Optional[str]:
    """The first of RECALL_MODELS that is offered and has an API key."""
    from app.api.models import MODEL_REGISTRY, RECALL_MODELS
    from app.llm.factory import has_credentials

    return next((m for m in RECALL_MODELS if m in MODEL_REGISTRY and has_credentials(m, env)), None)


def default_history_recall(factory, env: Mapping[str, str] = os.environ) -> Optional[HistoryRecall]:
    """Guided recall with the default model, or None when no key allows it."""
    model = default_recall_model(env)
    return GuidedRecall(ModelRewriter(model, factory)) if model else None


def with_default_recall(config: MutableMapping[str, Any], env: Mapping[str, str] = os.environ):
    """Attach the default recall to a run config that names none, using the
    run's own model factory. Returns the config."""
    from app.llm.factory import model_factory_from
    from app.services.graph import RECALL_CONFIG_KEY

    configurable = config.setdefault("configurable", {})
    if RECALL_CONFIG_KEY not in configurable:
        recall = default_history_recall(model_factory_from(config), env)
        if recall is not None:
            configurable[RECALL_CONFIG_KEY] = recall
    return config
