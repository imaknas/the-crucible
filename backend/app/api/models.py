from fastapi import APIRouter
import os
from typing import List, Dict, Any

router = APIRouter(tags=["models"])

# ─── Hardcoded Catalog ─────────────────────────────────────────

MODEL_REGISTRY: Dict[str, Dict[str, Any]] = {
    # OpenAI family
    "gpt-5.4": {
        "family": "openai",
        "id": "gpt-5.4",
        "name": "GPT-5.4",
        "desc": "Flagship",
        "limit": 100_000,
        "native_search": True,
    },
    "gpt-5.4-pro": {
        "family": "openai",
        "id": "gpt-5.4-pro",
        "name": "GPT-5.4 Pro",
        "desc": "Flagship",
        "limit": 100_000,
        "native_search": True,
    },
    "gpt-5.2": {
        "family": "openai",
        "id": "gpt-5.2",
        "name": "GPT-5.2",
        "desc": "Flagship",
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
        "desc": "Balanced",
        "limit": 100_000,
        "native_search": True,
    },
    "gpt-5-nano": {
        "family": "openai",
        "id": "gpt-5-nano",
        "name": "GPT-5 Nano",
        "desc": "Fast",
        "limit": 100_000,
        "native_search": True,
    },
    # Anthropic family
    "claude-opus-4-6": {
        "family": "anthropic",
        "id": "claude-opus-4-6",
        "name": "Claude Opus 4.6",
        "desc": "Flagship",
        "limit": 700_000,  # 70% of 1M window
        "native_search": True,
    },
    "claude-sonnet-4-6": {
        "family": "anthropic",
        "id": "claude-sonnet-4-6",
        "name": "Claude Sonnet 4.6",
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
    # Google family
    "gemini-3.1-pro-preview": {
        "family": "google",
        "id": "gemini-3.1-pro-preview",
        "name": "Gemini 3.1 Pro",
        "desc": "Flagship",
        "limit": 800_000,
        "native_search": True,
    },
    "gemini-3-flash-preview": {
        "family": "google",
        "id": "gemini-3-flash-preview",
        "name": "Gemini 3 Flash",
        "desc": "Fast",
        "limit": 800_000,
        "native_search": True,
    },
    "gemini-3-flash-lite-preview": {
        "family": "google",
        "id": "gemini-3-flash-lite-preview",
        "name": "Gemini 3 Flash-Lite",
        "desc": "Fast",
        "limit": 800_000,
        "native_search": True,
    },
}

FAMILY_META: Dict[str, Dict[str, str]] = {
    "openai": {"label": "OpenAI", "color": "#10b981", "env_key": "OPENAI_API_KEY"},
    "anthropic": {
        "label": "Anthropic",
        "color": "#f59e0b",
        "env_key": "ANTHROPIC_API_KEY",
    },
    "google": {"label": "Google", "color": "#8b5cf6", "env_key": "GOOGLE_API_KEY"},
}


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
async def get_models() -> Dict[str, List[Dict[str, Any]]]:
    """Returns grouped list of available models."""
    return {"families": _build_families()}
