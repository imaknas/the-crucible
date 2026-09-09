from fastapi import APIRouter
import os
from typing import List, Dict, Any

router = APIRouter(tags=["models"])

# ─── Hardcoded Catalog ─────────────────────────────────────────

# Every ID here is verified against the provider's live model list and a real
# chat completion. Two entries previously shipped broken: `gpt-5.4-pro` and
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
        "native_search": True,
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
    "claude-opus-5": {
        "family": "anthropic",
        "id": "claude-opus-5",
        "name": "Claude Opus 5",
        "desc": "Flagship",
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
DEFAULT_MODEL = "gpt-5.4"
DEFAULT_ARENA_MODELS = ["gpt-5.4", "claude-sonnet-5", "gemini-3.1-pro-preview"]
# Cheap, fast models used to summarise history when the context limit is hit.
SUMMARIZER_MODELS = ["gemini-3.5-flash", "claude-haiku-4-5-20251001"]


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
    }
