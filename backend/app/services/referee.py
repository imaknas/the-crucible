"""Who combines answers when the caller names no one: a model from a
provider that didn't write any of them.

A synthesizer, an argument map's author or a checklist's reader that also
answered reads its own text among the others', and models favour text they
recognise as their own. Debates, arena syntheses and the web UI's
"Synthesize answers" all pick through this one rule; the web UI mirrors it
in ``frontend/src/lib/referee.ts`` (both test the same cases).
"""

import os
from typing import Mapping, Sequence

from app.registry import MODEL_REGISTRY, REFEREE_MODELS


def default_synthesizer(
    answering: Sequence[str],
    candidates: Sequence[str] = REFEREE_MODELS,
    env: Mapping[str, str] = os.environ,
) -> str:
    """The first of `candidates` (registry REFEREE_MODELS, one per family)
    whose family wrote none of the answers and whose key is set, else the
    first answering model. With one model per family answering (the default
    arena) and no fourth family's key, there is no outsider; the callers'
    warnings say so."""
    from app.llm.factory import first_offered_with_key

    answered = {MODEL_REGISTRY[m]["family"] for m in answering if m in MODEL_REGISTRY}
    outsiders = [m for m in candidates if m in MODEL_REGISTRY and MODEL_REGISTRY[m]["family"] not in answered]
    return first_offered_with_key(outsiders, env) or answering[0]
