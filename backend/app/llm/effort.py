"""Reasoning effort: how hard a model thinks before it answers.

A person picks one of EFFORT_CHOICES for a run. Each provider names its own
levels (OpenAI none…xhigh, Anthropic low…max, Google's thinking levels
minimal…high, xAI low…xhigh), and each model accepts only some of them, so
the choice is resolved per model against the levels the catalog recorded for
it (`capabilities.reasoning_effort`: from the provider's own listing where it
reports them, Anthropic and xAI, else from catalog-sync's probe). "max" is
the highest level the model has. A model with no such level, or whose levels
nobody has verified, gets nothing sent: the caller reports that it answered
at its default, never a level it may not take.
"""

from typing import Any, Callable, Mapping, Optional, Sequence

EFFORT_CHOICES = ("low", "medium", "high", "max")
# Every provider level, lowest first: how "max" finds a model's highest.
LEVEL_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
CAPABILITY = "reasoning_effort"
# A model asked to reason hard takes longer: the time limits on a debate
# round, a synthesis and an arena turn grow by this much for high and max.
HARD_CHOICES = ("high", "max")
HARD_TIMEOUT_FACTOR = 3


def timeout_factor(choice: Optional[str]) -> int:
    """How many times the usual time limit a run at `choice` gets."""
    return HARD_TIMEOUT_FACTOR if choice in HARD_CHOICES else 1


def model_levels(model_id: str, catalog: Optional[Callable[[], Mapping[str, Any]]] = None,
                 registry: Optional[Mapping[str, Mapping[str, Any]]] = None) -> Optional[list[str]]:
    """The provider levels a registered model accepts, lowest first; [] when
    it has none, None when nobody has recorded them."""
    if registry is None:
        from app.registry import MODEL_REGISTRY as registry
    if catalog is None:
        from app.catalog import load_catalog as catalog
    config = registry.get(model_id)
    entry = catalog().get(config["id"]) if config else None
    levels = entry.capabilities.get(CAPABILITY) if entry is not None else None
    if not isinstance(levels, list):
        return None
    return sorted((lv for lv in levels if lv in LEVEL_ORDER), key=LEVEL_ORDER.index)


def resolve_level(levels: Optional[Sequence[str]], choice: str) -> Optional[str]:
    """The provider level to send for `choice`, or None when the model has
    no such level (or its levels aren't known)."""
    if not levels:
        return None
    if choice == "max":
        return max(levels, key=LEVEL_ORDER.index)
    return choice if choice in levels else None


def available_choices(levels: Optional[Sequence[str]]) -> Optional[list[str]]:
    """Which of EFFORT_CHOICES a model can take; None when its levels aren't known."""
    if levels is None:
        return None
    return [c for c in EFFORT_CHOICES if resolve_level(levels, c)]


def effort_for(model_id: str, choice: str, **lookup) -> Optional[str]:
    """The provider level a run's `choice` sends to `model_id`, or None."""
    return resolve_level(model_levels(model_id, **lookup), choice)
