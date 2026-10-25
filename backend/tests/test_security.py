"""Browser guards wired in create_app (app/api/security.py).

Each test builds its own app with create_app(...) and never runs the lifespan:
a MagicMock graph on app.state is enough for a socket to be accepted.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.security import OriginPolicy
from app.main import create_app

EVIL = "https://evil.example"


def _client(**kwargs) -> TestClient:
    app = create_app(**kwargs)
    app.state.graph_app = MagicMock()
    return TestClient(app)


# ─── Origin policy ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:3000", "http://127.0.0.1:3141", "https://localhost", "http://[::1]:3000"],
)
def test_policy_allows_local_origins(origin):
    assert OriginPolicy().allows(origin)


@pytest.mark.parametrize(
    "origin",
    [EVIL, "http://localhost.evil.example", "http://evil.example/http://localhost", "null", "http://localhost:3000.evil"],
)
def test_policy_rejects_foreign_origins(origin):
    assert not OriginPolicy().allows(origin)


def test_policy_reads_extra_origins_from_env():
    policy = OriginPolicy.from_env({"CORS_ORIGINS": " https://a.example , https://b.example,"})
    assert policy.extra_origins == ("https://a.example", "https://b.example")
    assert policy.allows("https://b.example")


# ─── WebSocket origin check ──────────────────────────────────────────────────

SOCKETS = ["/ws/t1", "/debate/ws/s1"]


@pytest.mark.parametrize("path", SOCKETS)
def test_socket_from_foreign_origin_is_refused(path):
    with pytest.raises(WebSocketDisconnect) as refused:
        with _client().websocket_connect(path, headers={"origin": EVIL}):
            pass
    assert refused.value.code == 1008


@pytest.mark.parametrize("path", SOCKETS)
def test_socket_from_null_origin_is_refused(path):
    with pytest.raises(WebSocketDisconnect):
        with _client().websocket_connect(path, headers={"origin": "null"}):
            pass


def test_chat_socket_accepts_local_origin_and_no_origin():
    client = _client()
    for headers in ({"origin": "http://localhost:3000"}, {}):
        with client.websocket_connect("/ws/t1", headers=headers) as ws:
            ws.send_json({"type": "stop"})


def test_debate_socket_accepts_local_origin():
    with _client().websocket_connect("/debate/ws/s1", headers={"origin": "http://127.0.0.1:3000"}) as ws:
        ws.send_json({"type": "debate_inject", "message": "hi"})
        assert ws.receive_json()["type"] == "error"  # served: no debate is running


def test_one_policy_drives_cors_and_sockets():
    client = _client(origin_policy=OriginPolicy(extra_origins=("https://crucible.example",)))
    preflight = client.options(
        "/chat", headers={"Origin": "https://crucible.example", "Access-Control-Request-Method": "POST"}
    )
    assert preflight.headers.get("access-control-allow-origin") == "https://crucible.example"
    with client.websocket_connect("/ws/t1", headers={"origin": "https://crucible.example"}) as ws:
        ws.send_json({"type": "stop"})

    evil = client.options("/chat", headers={"Origin": EVIL, "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in evil.headers
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/t1", headers={"origin": EVIL}):
            pass
