"""The registry (policy) may only offer models the catalog (facts) has verified."""

from app.api.models import MODEL_REGISTRY
from app.catalog import load_catalog

CATALOG = load_catalog()


def test_every_registry_model_is_listed_and_answered_a_real_call():
    problems = []
    for model_id in MODEL_REGISTRY:
        entry = CATALOG.get(model_id)
        if entry is None:
            problems.append(f"{model_id}: not in catalog (run `crucible catalog-sync`)")
        elif not entry.usable:
            problems.append(f"{model_id}: {entry.status}, chat_ok={entry.verification.chat_ok} {entry.verification.error or ''}")
    assert not problems, "\n".join(problems)


def test_native_search_claims_are_verified():
    unverified = [
        m for m, cfg in MODEL_REGISTRY.items()
        if cfg.get("native_search") and m in CATALOG and CATALOG[m].verification.web_search_ok is not True
    ]
    assert not unverified, f"registry claims native search, catalog probe disagrees: {unverified}"


def test_model_budget_reads_the_window_from_the_catalog():
    from app.services.graph import model_budget

    budget = model_budget("claude-sonnet-5")
    assert budget.context_window == CATALOG["claude-sonnet-5"].input_limit
    assert budget.soft_limit == MODEL_REGISTRY["claude-sonnet-5"]["limit"]
