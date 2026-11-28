"""How a run manages its history, as the person chose it.

One value carried from the transport to where a run's config is built, so a
new choice (which recall, which instruction) is a field here rather than a
new parameter on every function between them. Anything left unset uses the
app's default.
"""

import os
from dataclasses import dataclass, replace
from typing import Any, ClassVar, Mapping, MutableMapping, Optional

from app.services.documents import with_default_documents
from app.services.recall import with_default_recall

# A system prompt is instructions, not a document: a cap keeps a pasted file
# from riding along on every call of every model in the run.
MAX_SYSTEM_PROMPT_CHARS = 8_000
# An angle is a focus ("its security", "the case against it"), not a brief.
MAX_ANGLE_CHARS = 500


def _text_or_none(value):
    """Stripped text, None for blank; anything else left for problem()."""
    if isinstance(value, str):
        return value.strip() or None
    return value or None


@dataclass(frozen=True)
class ContextSettings:
    # Model that writes summaries; None = graph.default_summarizer().
    summarizer: Optional[str] = None
    # The person's own system prompt, sent to every model before the
    # conversation; None = no system prompt (each model's default behaviour).
    system_prompt: Optional[str] = None
    # The angle this run's one model answers from (a run is one model's
    # turn); None = none. An arena gives each model its own (run_arena's
    # `angles`). Not for a synthesis (stream_turn drops it) or a debate,
    # whose participants are given sides instead (services/stances.py).
    angle: Optional[str] = None

    # The top-level frame fields from_frame reads. A frame naming none of
    # them carries no choice (e.g. a debate redirect keeps the start's).
    FRAME_FIELDS: ClassVar[tuple[str, ...]] = ("summarizer", "system_prompt", "angle")

    @classmethod
    def from_frame(cls, frame: Mapping[str, Any]) -> "ContextSettings":
        return cls(
            summarizer=(frame.get("summarizer") or None),
            system_prompt=_text_or_none(frame.get("system_prompt")),
            angle=_text_or_none(frame.get("angle")),
        )

    def with_angle(self, angle: Optional[str]) -> "ContextSettings":
        """The same settings with this angle (None: without one)."""
        return replace(self, angle=_text_or_none(angle))

    @classmethod
    def named_in(cls, frame: Mapping[str, Any]) -> bool:
        """Whether a frame makes any of these choices."""
        return any(name in frame for name in cls.FRAME_FIELDS)

    def problem(self, env: Mapping[str, str] = os.environ) -> Optional[str]:
        """Why this run cannot use these settings, or None. A summarizer
        without a key would fail on every summary and history would grow
        unchecked, so it is refused up front."""
        if self.system_prompt is not None:
            if not isinstance(self.system_prompt, str):
                return "The system prompt must be text."
            if len(self.system_prompt) > MAX_SYSTEM_PROMPT_CHARS:
                return (f"The system prompt is {len(self.system_prompt):,} characters; "
                        f"the limit is {MAX_SYSTEM_PROMPT_CHARS:,}.")
        if self.angle is not None:
            if not isinstance(self.angle, str):
                return "An angle must be text."
            if len(self.angle) > MAX_ANGLE_CHARS:
                return f"An angle is {len(self.angle):,} characters; the limit is {MAX_ANGLE_CHARS:,}."
        if self.summarizer is None:
            return None
        from app.registry import MODEL_REGISTRY, display_name
        from app.llm.factory import has_credentials

        if self.summarizer not in MODEL_REGISTRY:
            return f"Unknown summarizer model: {self.summarizer}"
        if not has_credentials(self.summarizer, env):
            return f"No API key is set for {display_name(self.summarizer)}, so it cannot summarize."
        return None

    def apply(self, config: MutableMapping[str, Any], env: Mapping[str, str] = os.environ):
        """Put these settings, the app's default recall and its document
        store on a run config."""
        from app.services.graph import ANGLE_CONFIG_KEY, SUMMARIZER_CONFIG_KEY, SYSTEM_PROMPT_CONFIG_KEY

        if self.summarizer:
            config.setdefault("configurable", {})[SUMMARIZER_CONFIG_KEY] = self.summarizer
        if self.system_prompt:
            config.setdefault("configurable", {})[SYSTEM_PROMPT_CONFIG_KEY] = self.system_prompt
        if self.angle:
            config.setdefault("configurable", {})[ANGLE_CONFIG_KEY] = self.angle
        return with_default_documents(with_default_recall(config, env))


DEFAULT_CONTEXT = ContextSettings()
