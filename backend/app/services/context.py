"""How a run manages its history, as the person chose it.

One value carried from the transport to where a run's config is built, so a
new choice (which recall, which instruction) is a field here rather than a
new parameter on every function between them. Anything left unset uses the
app's default.
"""

import os
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Optional

from app.services.recall import with_default_recall


@dataclass(frozen=True)
class ContextSettings:
    # Model that writes summaries; None = graph.default_summarizer().
    summarizer: Optional[str] = None

    @classmethod
    def from_frame(cls, frame: Mapping[str, Any]) -> "ContextSettings":
        return cls(summarizer=(frame.get("summarizer") or None))

    def problem(self, env: Mapping[str, str] = os.environ) -> Optional[str]:
        """Why this run cannot use these settings, or None. A summarizer
        without a key would fail on every summary and history would grow
        unchecked, so it is refused up front."""
        if self.summarizer is None:
            return None
        from app.api.models import MODEL_REGISTRY, display_name
        from app.llm.factory import has_credentials

        if self.summarizer not in MODEL_REGISTRY:
            return f"Unknown summarizer model: {self.summarizer}"
        if not has_credentials(self.summarizer, env):
            return f"No API key is set for {display_name(self.summarizer)}, so it cannot summarize."
        return None

    def apply(self, config: MutableMapping[str, Any], env: Mapping[str, str] = os.environ):
        """Put these settings, and the app's default recall, on a run config."""
        from app.services.graph import SUMMARIZER_CONFIG_KEY

        if self.summarizer:
            config.setdefault("configurable", {})[SUMMARIZER_CONFIG_KEY] = self.summarizer
        return with_default_recall(config, env)


DEFAULT_CONTEXT = ContextSettings()
