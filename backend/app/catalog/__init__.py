"""A model catalog built from the providers' own APIs plus our own checks.

Self-contained like app/compaction: nothing here imports from `app.*`.

- entry.py      CatalogEntry: the facts about one model
- sources.py    One ProviderSource strategy per provider: list, normalize,
                classify, and probe (a real one-token call, and a web search)
- sync.py       Merge the previous catalog, fresh listings, manual overrides
                and probe results into a new catalog, with a diff
- store.py      Read/write the committed JSON snapshot and overrides

Facts come from first-party sources only: the providers' model endpoints,
our own probes, and hand-maintained overrides (each with its source) for
what no API exposes, such as OpenAI context windows.
"""

from app.catalog.entry import CatalogEntry, Verification
from app.catalog.store import DEFAULT_CATALOG, DEFAULT_OVERRIDES, load_catalog, load_overrides, save_catalog
from app.catalog.sync import CatalogDiff, sync_catalog

__all__ = [
    "CatalogEntry",
    "Verification",
    "CatalogDiff",
    "sync_catalog",
    "DEFAULT_CATALOG",
    "DEFAULT_OVERRIDES",
    "load_catalog",
    "load_overrides",
    "save_catalog",
]
