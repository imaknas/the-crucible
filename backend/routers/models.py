from fastapi import APIRouter
import os
from typing import List, Dict, Any

router = APIRouter(tags=["models"])

# ─── Hardcoded Catalog ─────────────────────────────────────────

MODEL_REGISTRY: Dict[str, Dict[str, Any]] = {
    # OpenAI family
    "gpt-5.2": {
        "family": "openai",
        "id": "gpt-5.2",
        "name": "GPT-5.2",
        "desc": "Flagship",
        "limit": 100_000,
    },
    "gpt-5.2-pro": {
        "family": "openai",
        "id": "gpt-5.2-pro",
        "name": "GPT-5.2 Pro",
        "desc": "Reasoning",
        "limit": 100_000,
    },
    "gpt-5-mini": {
        "family": "openai",
        "id": "gpt-5-mini",
        "name": "GPT-5 Mini",
        "desc": "Balanced",
        "limit": 100_000,
    },
    "gpt-5-nano": {
        "family": "openai",
        "id": "gpt-5-nano",
        "name": "GPT-5 Nano",
        "desc": "Fast",
        "limit": 100_000,
    },
    # Anthropic family
    "claude-opus-4-6": {
        "family": "anthropic",
        "id": "claude-opus-4-6",
        "name": "Claude Opus 4.6",
        "desc": "Flagship",
        "limit": 30_000,  # 100% of standard Tier 1
    },
    "claude-sonnet-4-6": {
        "family": "anthropic",
        "id": "claude-sonnet-4-6",
        "name": "Claude Sonnet 4.6",
        "desc": "Balanced",
        "limit": 22_500,  # 75% of 30k to leave runway for prompt/response
    },
    "claude-haiku-4-5-20251001": {
        "family": "anthropic",
        "id": "claude-haiku-4-5-20251001",
        "name": "Claude Haiku 4.5",
        "desc": "Fast",
        "limit": 40_000,  # 80% of 50k to leave runway
    },
    # Google family
    "gemini-3-pro-preview": {
        "family": "google",
        "id": "gemini-3-pro-preview",
        "name": "Gemini 3 Pro",
        "desc": "Flagship",
        "limit": 800_000,
    },
    "gemini-3.1-pro-preview": {
        "family": "google",
        "id": "gemini-3.1-pro-preview",
        "name": "Gemini 3.1 Pro",
        "desc": "Flagship",
        "limit": 800_000,
    },
    "gemini-3-flash-preview": {
        "family": "google",
        "id": "gemini-3-flash-preview",
        "name": "Gemini 3 Flash",
        "desc": "Fast",
        "limit": 800_000,
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
