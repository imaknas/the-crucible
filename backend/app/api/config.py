from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Dict, Any
import ipaddress
import os

from app.services import keys as keys_svc

router = APIRouter(prefix="/config", tags=["config"])

_ENV_PATH = keys_svc.ENV_PATH


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


@router.get("/keys")
def get_key_status(request: Request) -> Dict[str, Any]:
    _require_local(request)
    return keys_svc.key_status()


class KeysPayload(BaseModel):
    keys: Dict[str, str]


@router.post("/keys")
def save_keys(payload: KeysPayload, request: Request):
    _require_local(request)
    try:
        keys_svc.save_keys(payload.keys, _ENV_PATH)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok"}
