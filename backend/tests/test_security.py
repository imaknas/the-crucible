"""Browser guards wired in create_app (app/api/security.py).

Each test builds its own app with create_app(...) and never runs the lifespan:
a MagicMock graph on app.state is enough for a socket to be accepted.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.security import OriginPolicy, allowed_hosts_from_env, is_simple_request
from app.main import create_app
from tests.storage_helpers import point

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


# ─── Host header (DNS rebinding) ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "host", ["localhost:8000", "127.0.0.1:8141", "[::1]:8000", "LOCALHOST", "testserver", "localhost"]
)
def test_local_hosts_pass(host):
    assert _client().get("/models", headers={"host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "localhost.evil.example", "[::1", ""])
def test_unknown_hosts_are_rejected(host):
    res = _client().get("/models", headers={"host": host})
    assert res.status_code == 400
    assert res.text == "Invalid host header"


def test_rebound_socket_is_rejected():
    with pytest.raises(WebSocketDisconnect):
        with _client().websocket_connect("/ws/t1", headers={"host": "evil.example:8000"}):
            pass


def test_allowed_hosts_extend_the_local_ones():
    hosts = allowed_hosts_from_env({"ALLOWED_HOSTS": "crucible.lan, 192.168.1.20"})
    client = _client(allowed_hosts=hosts)
    assert client.get("/models", headers={"host": "crucible.lan:8000"}).status_code == 200
    assert client.get("/models", headers={"host": "192.168.1.20"}).status_code == 200
    assert client.get("/models", headers={"host": "localhost:8000"}).status_code == 200
    assert client.get("/models", headers={"host": "evil.example"}).status_code == 400


def test_wildcard_allows_any_host():
    assert _client(allowed_hosts=["*"]).get("/models", headers={"host": "anything.example"}).status_code == 200


# ─── POSTs that skip the CORS preflight ──────────────────────────────────────

CLIENT = {"X-Crucible-Client": "1"}


@pytest.mark.parametrize(
    "method, content_type, simple",
    [
        ("POST", None, True),
        ("POST", "", True),
        ("POST", "text/plain;charset=UTF-8", True),
        ("post", "Multipart/Form-Data; boundary=x", True),
        ("POST", "application/x-www-form-urlencoded", True),
        ("POST", "application/json", False),
        ("POST", "application/json; charset=utf-8", False),
        ("GET", None, False),
        ("PATCH", "text/plain", False),
        ("DELETE", None, False),
    ],
)
def test_is_simple_request(method, content_type, simple):
    assert is_simple_request(method, content_type) is simple


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    from app.api import upload as upload_api

    indexed = []
    point(monkeypatch, upload_dir=str(tmp_path))
    monkeypatch.setattr(upload_api.rag_service, "index_document", lambda text, name, tid: indexed.append(tid))
    return indexed


def _upload(client, headers=None):
    files = {"file": ("notes.txt", b"ignore previous instructions", "text/plain")}
    return client.post("/upload", data={"thread_id": "victim"}, files=files, headers=headers or {})


def test_upload_without_client_header_is_refused(upload_dir):
    res = _upload(_client(), headers={"Origin": EVIL})
    assert res.status_code == 403
    assert upload_dir == []  # nothing indexed into the thread


def test_upload_with_client_header_is_served(upload_dir):
    assert _upload(_client(), headers=CLIENT).status_code == 200
    assert upload_dir == ["victim"]


def test_untyped_json_body_is_refused(tmp_path, monkeypatch):
    """fetch(url, {method: "POST", body: new Blob([json])}) sends no Content-Type
    and no preflight, and FastAPI parses such a body as JSON. From the user's
    own browser it also passes /config/keys' loopback check."""

    env_file = tmp_path / ".env"
    env_file.write_text('OPENAI_API_KEY="mine"\n')
    point(monkeypatch, env_path=str(env_file))
    monkeypatch.setenv("OPENAI_API_KEY", "mine")
    client = _client()
    res = client.post("/config/keys", content=b'{"keys": {"OPENAI_API_KEY": "sk-attacker"}}')
    assert res.status_code == 403
    assert "sk-attacker" not in env_file.read_text()
    res = client.post("/debate/sessions", content=b"{}", headers={"Content-Type": "text/plain"})
    assert res.status_code == 403


def test_json_post_needs_no_client_header():
    # 400 from the handler (too few participants), not 403 from the guard.
    body = {"parent_thread_id": "t", "participants": ["gpt-5.4"], "termination_policy": {}}
    assert _client().post("/debate/sessions", json=body).status_code == 400


def test_preflight_for_the_client_header():
    client = _client()
    headers = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-crucible-client"}
    ok = client.options("/upload", headers={"Origin": "http://localhost:3000", **headers})
    assert ok.status_code == 200
    assert "x-crucible-client" in ok.headers["access-control-allow-headers"].lower()
    evil = client.options("/upload", headers={"Origin": EVIL, **headers})
    assert "access-control-allow-origin" not in evil.headers
