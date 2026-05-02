from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict
import os
import re

router = APIRouter(prefix="/config", tags=["config"])

_ENV_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".env")
)

_ALLOWED_KEYS = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"}


@router.get("/keys")
def get_key_status() -> Dict[str, bool]:
    return {k: bool(os.getenv(k)) for k in _ALLOWED_KEYS}


class KeysPayload(BaseModel):
    keys: Dict[str, str]


@router.post("/keys")
def save_keys(payload: KeysPayload):
    unknown = set(payload.keys) - _ALLOWED_KEYS
    if unknown:
        raise HTTPException(400, f"Unknown keys: {unknown}")

    lines: list[str] = []
    if os.path.exists(_ENV_PATH):
        with open(_ENV_PATH, "r") as f:
            lines = f.readlines()

    for key_name, value in payload.keys.items():
        found = False
        for i, line in enumerate(lines):
            if re.match(rf"^\s*{re.escape(key_name)}\s*=", line):
                lines[i] = f'{key_name}="{value}"\n' if value else ""
                found = True
                break
        if not found and value:
            lines.append(f'{key_name}="{value}"\n')

    with open(_ENV_PATH, "w") as f:
        f.writelines(line for line in lines if line)

    for key_name, value in payload.keys.items():
        if value:
            os.environ[key_name] = value
        elif key_name in os.environ:
            del os.environ[key_name]

    return {"status": "ok"}
