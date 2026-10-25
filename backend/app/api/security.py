"""Browser-facing guards for an API without authentication.

The API trusts whoever can reach it, so it must not be reachable *through* the
user's browser by other sites. Each gap is closed by a middleware that
``main.create_app`` wires with its configuration:

- ``WebSocketOriginGuard``: CORS only governs HTTP. Browsers let any page open
  a WebSocket to localhost and send its Origin; without a check, any site the
  user visits could run turns on the user's API keys.
- ``TrustedHostGuard``: DNS rebinding points an attacker's hostname at
  127.0.0.1, which makes the attacker's page same-origin with the API. The
  Host header still carries the attacker's name, so only known hosts pass.
- ``SimpleRequestGuard``: a POST whose body is form data, text or untyped
  (``fetch`` with a Blob) is a CORS "simple request": the browser sends it
  cross-origin without a preflight and the handler runs, even though the page
  cannot read the response. FastAPI parses an untyped body as JSON, so this
  reaches the JSON endpoints too (including /config/keys, whose loopback check
  the user's own browser passes). A required custom header makes the browser
  preflight, and CORS refuses the preflight for foreign origins.

``OriginPolicy`` is the one definition of which browser origins may use the
API; CORS and the WebSocket guard both read it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# Local frontends on any port: the dev server and start_dev.sh pick free ports.
LOCAL_ORIGIN_PATTERN = r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?"

# TestClient sends Host: testserver.
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "testserver")

CLIENT_HEADER = "x-crucible-client"

# Content types a browser may send cross-origin without a preflight; no
# Content-Type at all is the same.
_SIMPLE_CONTENT_TYPES = frozenset({"application/x-www-form-urlencoded", "multipart/form-data", "text/plain"})

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


def allowed_hosts_from_env(env: Mapping[str, str]) -> tuple[str, ...]:
    """Local hosts plus ``ALLOWED_HOSTS`` (comma separated; ``*`` allows any)."""
    return LOCAL_HOSTS + _env_list(env.get("ALLOWED_HOSTS"))


def host_name(host_header: str) -> str:
    """The host part of a Host header, lower-cased, without port or IPv6 brackets."""
    try:
        return urlsplit(f"//{host_header}").hostname or ""
    except ValueError:  # e.g. an unterminated "[" bracket
        return ""


class TrustedHostGuard:
    """Reject requests whose Host header names a host the API isn't served as.

    Starlette's TrustedHostMiddleware cuts the Host header at its first ':',
    so an IPv6 literal such as ``[::1]:8000`` could never match; this parses it.
    """

    def __init__(self, app: ASGIApp, allowed_hosts: Iterable[str]) -> None:
        self.app = app
        self.allowed = frozenset(host.lower().strip("[]") for host in allowed_hosts)
        self.allow_any = "*" in self.allowed

    def allows(self, host_header: str) -> bool:
        return self.allow_any or host_name(host_header) in self.allowed

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and not self.allows(Headers(scope=scope).get("host", "")):
            await PlainTextResponse("Invalid host header", status_code=400)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def is_simple_request(method: str, content_type: str | None) -> bool:
    """True for a POST a browser would send cross-origin without a preflight."""
    if method.upper() != "POST":
        return False
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    return not media_type or media_type in _SIMPLE_CONTENT_TYPES


class SimpleRequestGuard:
    """Require ``X-Crucible-Client`` on POSTs that would skip the CORS preflight.

    GET/HEAD must not change state and PUT/PATCH/DELETE always preflight.
    JSON POSTs preflight too, so REST callers sending
    ``Content-Type: application/json`` need nothing extra.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = Headers(scope=scope)
            if is_simple_request(scope["method"], headers.get("content-type")) and CLIENT_HEADER not in headers:
                message = f"Form, text and untyped POST requests need the {CLIENT_HEADER} header"
                await PlainTextResponse(message, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)
