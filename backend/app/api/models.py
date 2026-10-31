import os
from typing import Any, Dict, List

from fastapi import APIRouter

from app.registry import (
    DEFAULT_ARENA_MODELS,
    DEFAULT_MODEL,
    FAMILY_META,
    models_by_family,
)

router = APIRouter(tags=["models"])


def _build_families() -> List[Dict[str, Any]]:
    grouped = models_by_family()
    return [
        {
            "key": key,
            "label": meta["label"],
            "color": meta["color"],
            "env_key": meta["env_key"],
            "available": bool(os.getenv(meta["env_key"])),
            "models": [
                {
                    "id": str(cfg["id"]),
                    "name": str(cfg["name"]),
                    "desc": str(cfg["desc"]),
                    "native_search": cfg.get("native_search", False),
                }
                for cfg in grouped[key]
            ],
        }
        for key, meta in FAMILY_META.items()
    ]


def _limits() -> Dict[str, int]:
    """Caps the backend enforces, so the UI can show them before a request fails."""
    from app.services.chat import MAX_PROMPT_CHARS
    from app.services.context import MAX_SYSTEM_PROMPT_CHARS
    from app.services.debate import MAX_ROUNDS

    return {
        "max_prompt_chars": MAX_PROMPT_CHARS,
        "max_system_prompt_chars": MAX_SYSTEM_PROMPT_CHARS,
        "max_debate_rounds": MAX_ROUNDS,
    }


@router.get("/models")
async def get_models() -> Dict[str, Any]:
    """Returns grouped list of available models plus the server-side defaults."""
    return {
        "families": _build_families(),
        "default_model": DEFAULT_MODEL,
        "default_arena_models": DEFAULT_ARENA_MODELS,
        # Resolved for the keys that are set, so the UI can name it.
        "default_summarizer": _default_summarizer(),
        "limits": _limits(),
    }


def _default_summarizer() -> str:
    from app.services.graph import default_summarizer

    return default_summarizer()
