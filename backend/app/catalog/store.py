"""The committed catalog snapshot and the hand-maintained overrides."""

import json
from pathlib import Path
from typing import Any

from app.catalog.entry import CatalogEntry

DATA = Path(__file__).parent / "data"
DEFAULT_CATALOG = DATA / "catalog.json"
DEFAULT_OVERRIDES = DATA / "overrides.json"


def load_catalog(path: Path = DEFAULT_CATALOG) -> dict[str, CatalogEntry]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {e["id"]: CatalogEntry.from_dict(e) for e in raw.get("models", [])}


def save_catalog(entries: dict[str, CatalogEntry], path: Path = DEFAULT_CATALOG, *, synced: str) -> None:
    """Stable ordering and formatting, so a sync's git diff shows only real changes."""
    models = sorted(entries.values(), key=lambda e: (e.provider, e.id))
    body = {"synced": synced, "models": [m.to_dict() for m in models]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=1, ensure_ascii=False, sort_keys=True) + "\n")


def load_overrides(path: Path = DEFAULT_OVERRIDES) -> dict[str, dict[str, Any]]:
    """{model_id: {field: value, ..., "source": "where the value came from"}}.

    For facts no provider API exposes (e.g. OpenAI context windows). Every
    entry must say where its values came from.
    """
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    overrides = {k: v for k, v in data.items() if not k.startswith("_")}
    missing = [k for k, v in overrides.items() if not v.get("source")]
    if missing:
        raise ValueError(f"overrides without a source: {', '.join(missing)}")
    return overrides
