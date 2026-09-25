from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Dict, Any
import ipaddress
import os
import re

router = APIRouter(prefix="/config", tags=["config"])

_ENV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

_ALLOWED_KEYS = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"}

# Printable ASCII without quotes, backslashes or whitespace. Real provider keys
# fit this; anything else could break out of the quoted .env value.
_VALID_VALUE = re.compile(r'^[\x21-\x7e]+$')
_FORBIDDEN_CHARS = set('"\'\\`$')


def _remote_config_allowed() -> bool:
    # Docker publishes the backend on 127.0.0.1 only, but requests reach the
    # container from the bridge gateway rather than loopback, so compose opts in.
    return os.getenv("CRUCIBLE_ALLOW_REMOTE_CONFIG", "").lower() in ("1", "true", "yes")


def _require_local(request: Request) -> None:
    """Key management reads and writes secrets; only the local machine may use it."""
    if _remote_config_allowed():
        return
    host = request.client.host if request.client else ""
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        if host in ("localhost", "testclient"):
            return
    raise HTTPException(403, "API key configuration is only available from localhost")


def _mask(val: str) -> str:
    if len(val) <= 8:
        return "•" * len(val)
    return "•" * (len(val) - 4) + val[-4:]


@router.get("/keys")
def get_key_status(request: Request) -> Dict[str, Any]:
    _require_local(request)
    result = {}
    for k in _ALLOWED_KEYS:
        val = os.getenv(k) or ""
        result[k] = {"set": bool(val), "masked": _mask(val) if val else ""}
    return result


class KeysPayload(BaseModel):
    keys: Dict[str, str]


@router.post("/keys")
def save_keys(payload: KeysPayload, request: Request):
    _require_local(request)
    unknown = set(payload.keys) - _ALLOWED_KEYS
    if unknown:
        raise HTTPException(400, f"Unknown keys: {unknown}")

    cleaned: Dict[str, str] = {}
    for key_name, value in payload.keys.items():
        value = value.strip()
        if value and (not _VALID_VALUE.match(value) or _FORBIDDEN_CHARS & set(value)):
            raise HTTPException(400, f"{key_name} contains characters an API key cannot have")
        cleaned[key_name] = value

    lines: list[str] = []
    if os.path.exists(_ENV_PATH):
        with open(_ENV_PATH, "r") as f:
            lines = f.readlines()

    for key_name, value in cleaned.items():
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

    for key_name, value in cleaned.items():
        if value:
            os.environ[key_name] = value
        elif key_name in os.environ:
            del os.environ[key_name]

    return {"status": "ok"}
