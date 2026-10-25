from fastapi import APIRouter
import os
from typing import List, Dict, Any

router = APIRouter(tags=["models"])

# ─── Hardcoded Catalog ─────────────────────────────────────────

# Every ID here is verified against the provider's live model list and a real
# chat completion (last full check: 2026-09-26, all entries). Two entries previously shipped broken: `gpt-5.4-pro` and
# `gpt-5.5-pro` are not chat models (404 on v1/chat/completions), and
# `gemini-3-flash-lite-preview` no longer exists.
#
# `limit` is the soft context threshold that triggers summarisation/pruning in
# `graph.py:get_token_limit()` — deliberately conservative, not the hard API
# window. Anthropic values are 70% of the window reported by the models API.
MODEL_REGISTRY: Dict[str, Dict[str, Any]] = {
    # ─── OpenAI ────────────────────────────────────────────────
    "gpt-6-astra": {
        "family": "openai",
        "id": "gpt-6-astra",
        "name": "GPT-6 Astra",
        "desc": "Flagship",
        "limit": 100_000,
        "native_search": True,
    },
    "gpt-6.1-sol": {
        "family": "openai",
        "id": "gpt-6.1-sol",
        "name": "GPT-6.1 Sol",
        "desc": "Balanced",
        "limit": 100_000,
        "native_search": True,
    },
    "gpt-6-sol": {
        "family": "openai",
        "id": "gpt-6-sol",
        "name": "GPT-6 Sol",
        "desc": "Balanced",
        "limit": 100_000,
        "native_search": True,
    },
    "gpt-6-luna": {
        "family": "openai",
        "id": "gpt-6-luna",
        "name": "GPT-6 Luna",
        "desc": "Fast",
        "limit": 100_000,
        "native_search": True,
    },
    "gpt-5.6-terra": {
        "family": "openai",
        "id": "gpt-5.6-terra",
        "name": "GPT-5.6 Terra",
        "desc": "Flagship",
        "limit": 100_000,
        "native_search": True,
    },
    "gpt-5.6-sol": {
        "family": "openai",
        "id": "gpt-5.6-sol",
        "name": "GPT-5.6 Sol",
        "desc": "Balanced",
        "limit": 100_000,
        "native_search": True,
    },
    "gpt-5.6-luna": {
        "family": "openai",
        "id": "gpt-5.6-luna",
        "name": "GPT-5.6 Luna",
        "desc": "Fast",
        "limit": 100_000,
        "native_search": True,
    },
    "gpt-5.5": {
        "family": "openai",
        "id": "gpt-5.5",
        "name": "GPT-5.5",
        "desc": "Flagship",
        "limit": 100_000,
        "native_search": True,
    },
    "gpt-5.4": {
        "family": "openai",
        "id": "gpt-5.4",
        "name": "GPT-5.4",
        "desc": "Balanced",
        "limit": 100_000,
        "native_search": True,
    },
    "gpt-5.4-mini": {
        "family": "openai",
        "id": "gpt-5.4-mini",
        "name": "GPT-5.4 Mini",
        "desc": "Balanced",
        "limit": 100_000,
        "native_search": True,
    },
    "gpt-5.4-nano": {
        "family": "openai",
        "id": "gpt-5.4-nano",
        "name": "GPT-5.4 Nano",
        "desc": "Fast",
        "limit": 100_000,
        "native_search": True,
    },
    # Retained: existing threads/debates in the checkpoint DB reference these.
    "gpt-5.2": {
        "family": "openai",
        "id": "gpt-5.2",
        "name": "GPT-5.2",
        "desc": "Legacy",
        "limit": 100_000,
        "native_search": True,
    },
    "gpt-5.2-pro": {
        "family": "openai",
        "id": "gpt-5.2-pro",
        "name": "GPT-5.2 Pro",
        "desc": "Reasoning",
        "limit": 100_000,
        # Answers only on the Responses API. Its web-search probe exceeds the
        # account's per-minute token limit, so search is unverified: off.
        "native_search": False,
    },
    "gpt-5-mini": {
        "family": "openai",
        "id": "gpt-5-mini",
        "name": "GPT-5 Mini",
        "desc": "Legacy",
        "limit": 100_000,
        "native_search": True,
    },
    "gpt-5-nano": {
        "family": "openai",
        "id": "gpt-5-nano",
        "name": "GPT-5 Nano",
        "desc": "Legacy",
        "limit": 100_000,
        "native_search": True,
    },
    # ─── Anthropic ─────────────────────────────────────────────
    "claude-opus-5-5": {
        "family": "anthropic",
        "id": "claude-opus-5-5",
        "name": "Claude Opus 5.5",
        "desc": "Flagship",
        "limit": 700_000,  # 70% of 1M window
        "native_search": True,
    },
    "claude-opus-5": {
        "family": "anthropic",
        "id": "claude-opus-5",
        "name": "Claude Opus 5",
        "desc": "Flagship",
        "limit": 700_000,  # 70% of 1M window
        "native_search": True,
    },
    "claude-sonnet-5-5": {
        "family": "anthropic",
        "id": "claude-sonnet-5-5",
        "name": "Claude Sonnet 5.5",
        "desc": "Balanced",
        "limit": 700_000,  # 70% of 1M window
        "native_search": True,
    },
    "claude-sonnet-5": {
        "family": "anthropic",
        "id": "claude-sonnet-5",
        "name": "Claude Sonnet 5",
        "desc": "Balanced",
        "limit": 700_000,  # 70% of 1M window
        "native_search": True,
    },
    "claude-fable-5-1": {
        "family": "anthropic",
        "id": "claude-fable-5-1",
        "name": "Claude Fable 5.1",
        "desc": "Balanced",
        "limit": 700_000,  # 70% of 1M window
        "native_search": True,
    },
    "claude-haiku-5-5": {
        "family": "anthropic",
        "id": "claude-haiku-5-5",
        "name": "Claude Haiku 5.5",
        "desc": "Fast",
        # Not the 1M window: a prompt over 100K tokens costs 5x per token,
        # so summarise before a thread gets there.
        "limit": 70_000,
        "native_search": True,
    },
    "claude-haiku-4-5-20251001": {
        "family": "anthropic",
        "id": "claude-haiku-4-5-20251001",
        "name": "Claude Haiku 4.5",
        "desc": "Fast",
        "limit": 140_000,  # 70% of 200k window
        "native_search": True,
    },
    # Retained: referenced by existing threads.
    "claude-opus-4-6": {
        "family": "anthropic",
        "id": "claude-opus-4-6",
        "name": "Claude Opus 4.6",
        "desc": "Legacy",
        "limit": 700_000,  # 70% of 1M window
        "native_search": True,
    },
    "claude-sonnet-4-6": {
        "family": "anthropic",
        "id": "claude-sonnet-4-6",
        "name": "Claude Sonnet 4.6",
        "desc": "Legacy",
        "limit": 700_000,  # 70% of 1M window
        "native_search": True,
    },
    # ─── Google ────────────────────────────────────────────────
    "gemini-4-argon": {
        "family": "google",
        "id": "gemini-4-argon",
        "name": "Gemini 4 Argon",
        "desc": "Flagship",
        "limit": 800_000,
        "native_search": True,
    },
    "gemini-3.1-pro-preview": {
        "family": "google",
        "id": "gemini-3.1-pro-preview",
        "name": "Gemini 3.1 Pro",
        "desc": "Flagship",
        "limit": 800_000,
        "native_search": True,
    },
    "gemini-3.8-flash": {
        "family": "google",
        "id": "gemini-3.8-flash",
        "name": "Gemini 3.8 Flash",
        "desc": "Balanced",
        "limit": 800_000,
        "native_search": True,
    },
    "gemini-3.7-flash": {
        "family": "google",
        "id": "gemini-3.7-flash",
        "name": "Gemini 3.7 Flash",
        "desc": "Balanced",
        "limit": 800_000,
        "native_search": True,
    },
    "gemini-3.5-flash": {
        "family": "google",
        "id": "gemini-3.5-flash",
        "name": "Gemini 3.5 Flash",
        "desc": "Fast",
        "limit": 800_000,
        "native_search": True,
    },
    "gemini-3.5-flash-lite": {
        "family": "google",
        "id": "gemini-3.5-flash-lite",
        "name": "Gemini 3.5 Flash-Lite",
        "desc": "Fast",
        "limit": 800_000,
        "native_search": True,
    },
    "gemini-3.1-flash-lite": {
        "family": "google",
        "id": "gemini-3.1-flash-lite",
        "name": "Gemini 3.1 Flash-Lite",
        "desc": "Fast",
        "limit": 800_000,
        "native_search": True,
    },
    # Retained: referenced by existing threads/debates.
    "gemini-3-flash-preview": {
        "family": "google",
        "id": "gemini-3-flash-preview",
        "name": "Gemini 3 Flash",
        "desc": "Legacy",
        "limit": 800_000,
        "native_search": True,
    },
}

# Single source of truth for defaults. These were previously duplicated across
# main.py, cli.py, graph.py and page.tsx, which is how they drifted stale.
# gpt-6.1-sol and Sonnet 5.5 are the newest balanced models and cost no
# more than what they replace (gpt-5.4 was set before the gpt-6 family
# existed). Gemini stays on 3.1 Pro: 4 Argon doubles to $4/$20 on
# 2026-12-01 and has half the output limit.
DEFAULT_MODEL = "gpt-6.1-sol"
DEFAULT_ARENA_MODELS = ["gpt-6.1-sol", "claude-sonnet-5-5", "gemini-3.1-pro-preview"]
# Models used to summarise history when the context limit is hit: the first
# offered one with an API key wins (a run may name another). Chosen with
# recall on, as the app runs (experiments/NOTES.md, pilot 22): gpt-6-luna was
# the only one no worse than the best on both scenarios (93/96 and 62/64
# facts) and the cheapest, ~1/25 of gemini-3.8-flash per summary at 2027
# prices. Its summaries alone keep much less (42/96): it relies on recall.
# gemini-3.8-flash keeps the most without recall; haiku trails on dense detail.
# On an Anthropic key alone it is claude-haiku-5-5: a tenth of claude-haiku-4-5's
# price and not detectably worse in the 2026-10-25 audit. (That audit's
# "4.5 harmful, 1.00 → 0.79" reading was a harness artifact; NOTES.md,
# 2026-10-25 "Harness bias".) Rescored, pilot 22's rule picks gemini-3.8-flash
# over luna by a margin inside the noise; luna stays first on cost (17–30×
# cheaper per summary) until a rerun on the fixed harness with more
# conversations settles it.
SUMMARIZER_MODELS = ["gpt-6-luna", "gemini-3.8-flash", "claude-haiku-5-5"]

# Which model chooses what to fetch back once history is summarized; the
# first offered one with an API key wins, none means no recall. Choosing is
# easy once the question is known: gpt-6-luna matched the strongest models
# at 1/24 the cost (30/32 off-goal facts; haiku 28, gemini-3.8-flash 31,
# gemini-3.5-flash-lite only 25), experiments/NOTES.md pilot 18.
RECALL_MODELS = ["gpt-6-luna", "claude-haiku-4-5-20251001", "gemini-3.8-flash"]

# Which model grades retrieved RAG chunks for relevance (one yes/no call per
# chunk, no tools); the first offered one with an API key wins, otherwise the
# answering model grades without tools. A short classification like recall's
# rewrite step, so the same small models, cheapest first.
GRADER_MODELS = RECALL_MODELS


FAMILY_META: Dict[str, Dict[str, str]] = {
    "openai": {"label": "OpenAI", "color": "#10b981", "env_key": "OPENAI_API_KEY"},
    "anthropic": {
        "label": "Anthropic",
        "color": "#f59e0b",
        "env_key": "ANTHROPIC_API_KEY",
    },
    "google": {"label": "Google", "color": "#8b5cf6", "env_key": "GOOGLE_API_KEY"},
}


def display_name(model_id: str | None) -> str:
    """
    Human-facing label for a model ID.

    Raw IDs like "claude-haiku-4-5-20251001" are 25 characters and get clipped
    mid-identifier wherever the UI shows them, so anything a person reads uses
    this instead. Unknown IDs fall through unchanged.
    """
    if not model_id:
        return ""
    cfg = MODEL_REGISTRY.get(model_id)
    if cfg:
        return str(cfg["name"])
    return "Synthesis" if model_id == "synthesis" else model_id


def _build_families() -> List[Dict[str, Any]]:
    families: List[Dict[str, Any]] = []

    # Group models by family for structure
    grouped_models: Dict[str, List[Dict[str, str]]] = {
        "openai": [],
        "anthropic": [],
        "google": [],
    }
    for cfg in MODEL_REGISTRY.values():
        fam = cfg.get("family")
        if fam in grouped_models:
            grouped_models[fam].append(
                {
                    "id": str(cfg["id"]),
                    "name": str(cfg["name"]),
                    "desc": str(cfg["desc"]),
                    "native_search": cfg.get("native_search", False),
                }
            )

    for key, meta in FAMILY_META.items():
        is_available = bool(os.getenv(meta["env_key"]))
        models = grouped_models.get(key, [])

        families.append(
            {
                "key": key,
                "label": meta["label"],
                "color": meta["color"],
                "available": is_available,
                "models": models,
            }
        )

    return families


@router.get("/models")
async def get_models() -> Dict[str, Any]:
    """Returns grouped list of available models plus the server-side defaults."""
    return {
        "families": _build_families(),
        "default_model": DEFAULT_MODEL,
        "default_arena_models": DEFAULT_ARENA_MODELS,
        # Resolved for the keys that are set, so the UI can name it.
        "default_summarizer": _default_summarizer(),
    }


def _default_summarizer() -> str:
    from app.services.graph import default_summarizer  # graph imports this module

    return default_summarizer()
