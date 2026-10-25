"""Browser-facing guards for an API without authentication.

The API trusts whoever can reach it, so it must not be reachable *through* the
user's browser by other sites. Each gap is closed by a middleware that
``main.create_app`` wires with its configuration:

- ``WebSocketOriginGuard``: CORS only governs HTTP. Browsers let any page open
  a WebSocket to localhost and send its Origin; without a check, any site the
  user visits could run turns on the user's API keys.

``OriginPolicy`` is the one definition of which browser origins may use the
API; CORS and the WebSocket guard both read it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

# Local frontends on any port: the dev server and start_dev.sh pick free ports.
LOCAL_ORIGIN_PATTERN = r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?"

# RFC 6455 "policy violation".
WS_POLICY_VIOLATION = 1008


def _env_list(value: str | None) -> tuple[str, ...]:
    return tuple(item.strip() for item in (value or "").split(",") if item.strip())


@dataclass(frozen=True)
class OriginPolicy:
    """Browser origins allowed to use the API: local ones plus ``extra_origins``."""

    extra_origins: tuple[str, ...] = ()
    pattern: str = LOCAL_ORIGIN_PATTERN

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "OriginPolicy":
        return cls(extra_origins=_env_list(env.get("CORS_ORIGINS")))

    def allows(self, origin: str) -> bool:
        # Same test as Starlette's CORSMiddleware.is_allowed_origin.
        return re.fullmatch(self.pattern, origin) is not None or origin in self.extra_origins

    def cors_options(self) -> dict:
        return {"allow_origins": list(self.extra_origins), "allow_origin_regex": self.pattern}


class WebSocketOriginGuard:
    """Refuse WebSocket handshakes from browser origins the policy rejects.

    A missing Origin is a non-browser client (CLI, scripts, tests) and passes:
    browsers always send one on a WebSocket handshake.
    """

    def __init__(self, app: ASGIApp, policy: OriginPolicy) -> None:
        self.app = app
        self.policy = policy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            origin = Headers(scope=scope).get("origin")
            if origin is not None and not self.policy.allows(origin):
                # Closing before accept refuses the handshake (HTTP 403 on the wire).
                await receive()  # websocket.connect
                await send({"type": "websocket.close", "code": WS_POLICY_VIOLATION})
                return
        await self.app(scope, receive, send)
