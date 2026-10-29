"""Model names as providers report them."""

import re
from typing import Iterable, Optional

_DATE_SUFFIX = re.compile(r"[0-9]+(-[0-9]+)*")


def listed_id(model_name: str, known: Iterable[str]) -> Optional[str]:
    """The listed id a reported model name refers to.

    Providers report the model that answered by a dated snapshot name
    ("gpt-5.4-nano-2026-03-17"); such a name resolves to the longest listed
    id it extends. None when it extends none.
    """
    name = model_name.strip().lower().removeprefix("models/")
    ids = set(known)
    if name in ids:
        return name
    matches = [m for m in ids if name.startswith(m + "-")]
    return max(matches, key=len) if matches else None


def is_dated_snapshot(model_name: str, model_id: str) -> bool:
    """Whether `model_name` is `model_id` plus only a date or version stamp
    ("-2025-12-11", "-20251001"), rather than another model ("-pro")."""
    name = model_name.strip().lower().removeprefix("models/")
    return name.startswith(model_id + "-") and bool(_DATE_SUFFIX.fullmatch(name[len(model_id) + 1:]))
