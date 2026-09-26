"""Build a new catalog from the previous one, fresh listings, overrides and probes."""

import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Mapping, Optional

import httpx

from app.catalog.entry import CatalogEntry
from app.catalog.sources import SOURCES, ProviderSource, guarded

ProbeMode = Literal["new", "failed", "all", "none"]
OVERRIDABLE = {"display_name", "released", "input_limit", "output_limit", "shutdown_date"}


@dataclass
class CatalogDiff:
    added: list[str] = field(default_factory=list)
    unlisted: list[str] = field(default_factory=list)
    changed: dict[str, dict[str, Any]] = field(default_factory=dict)
    probed: dict[str, dict[str, Any]] = field(default_factory=dict)
    skipped_providers: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.added or self.unlisted or self.changed or self.probed)


def _verdict(old_ok, old_checked, new_ok, today):
    """Record a probe outcome. An inconclusive probe (None) keeps a previous
    success — a transient 429 must not un-verify a working model — but clears a
    previous failure so it is retried rather than trusted."""
    if new_ok is not None:
        return new_ok, today
    if old_ok:
        return old_ok, old_checked
    return None, None


def apply_overrides(entry: CatalogEntry, overrides: Mapping[str, Mapping[str, Any]]) -> None:
    o = overrides.get(entry.id)
    if not o:
        return
    for key, value in o.items():
        if key in OVERRIDABLE:
            setattr(entry, key, value)
            entry.sources[key] = f"override: {o['source']}"


def sync_catalog(
    previous: Mapping[str, CatalogEntry],
    keys: Mapping[str, Optional[str]],
    *,
    overrides: Mapping[str, Mapping[str, Any]] = {},
    today: str,
    probe: ProbeMode = "new",
    probe_web_search: bool = True,
    sources: Iterable[ProviderSource] = SOURCES.values(),
    client: Optional[httpx.Client] = None,
    workers: int = 6,
) -> tuple[dict[str, CatalogEntry], CatalogDiff]:
    """Returns the new catalog and what changed. Providers without a key are
    left exactly as they were."""
    own_client = client is None
    client = client or httpx.Client(timeout=120)
    diff = CatalogDiff()
    catalog = {k: copy.deepcopy(v) for k, v in previous.items()}
    to_probe: list[tuple[ProviderSource, str, CatalogEntry]] = []

    try:
        for source in sources:
            key = keys.get(source.name)
            if not key:
                diff.skipped_providers.append(source.name)
                continue
            listed = [source.normalize(r) for r in source.list_models(client, key) if source.is_chat_candidate(r)]
            enrich = getattr(source, "enrich", None)
            if enrich:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    list(pool.map(lambda e: enrich(client, e), listed))
            seen = set()
            for fresh in listed:
                seen.add(fresh.id)
                apply_overrides(fresh, overrides)  # manual values win over fetched ones
                old = catalog.get(fresh.id)
                if old is None:
                    diff.added.append(fresh.id)
                else:
                    fresh.verification = old.verification
                    # Keep what earlier probes learned (e.g. which API answers);
                    # the listing doesn't report it, so it isn't a change.
                    for k, v in old.capabilities.items():
                        fresh.capabilities.setdefault(k, v)
                    changes = {
                        k: [old.facts()[k], v] for k, v in fresh.facts().items() if old.facts()[k] != v
                    }
                    if changes:
                        diff.changed[fresh.id] = changes
                catalog[fresh.id] = fresh
                v = fresh.verification
                needs = probe == "all" or (probe == "new" and (
                    old is None
                    or fresh.id in diff.changed
                    or v.chat_checked is None
                    or (probe_web_search and v.chat_ok and v.web_search_checked is None)  # inconclusive last time
                )) or (probe == "failed" and (v.chat_ok is False or v.web_search_ok is False))
                if needs:
                    to_probe.append((source, key, fresh))
            for entry in catalog.values():
                if entry.provider == source.name and entry.id not in seen and entry.status == "listed":
                    entry.status = "unlisted"
                    diff.unlisted.append(entry.id)

        def run(item):
            source, key, entry = item
            chat = guarded(lambda: source.probe_chat(client, key, entry.id))
            search = guarded(lambda: source.probe_web_search(client, key, entry)) if (probe_web_search and chat.ok) else None
            return entry, chat, search

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for entry, chat, search in pool.map(run, to_probe):
                v = entry.verification
                v.chat_ok, v.chat_checked = _verdict(v.chat_ok, v.chat_checked, chat.ok, today)
                entry.capabilities.update(chat.capabilities)
                v.error = chat.error
                if search is not None:
                    v.web_search_ok, v.web_search_checked = _verdict(
                        v.web_search_ok, v.web_search_checked, search.ok, today
                    )
                    if not search.ok:
                        v.error = f"web search: {search.error}"
                diff.probed[entry.id] = {"chat": chat.ok, "web_search": None if search is None else search.ok, "error": v.error}
    finally:
        if own_client:
            client.close()
    return catalog, diff
