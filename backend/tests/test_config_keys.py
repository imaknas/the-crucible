import pytest
from fastapi.testclient import TestClient

from app.api import config as config_api
from app.main import server as app


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text('OTHER="keep"\n')
    monkeypatch.setattr(config_api, "_ENV_PATH", str(path))
    monkeypatch.delenv("CRUCIBLE_ALLOW_REMOTE_CONFIG", raising=False)
    for k in config_api._ALLOWED_KEYS:
        monkeypatch.delenv(k, raising=False)
    return path


def _client(host: str) -> TestClient:
    return TestClient(app, client=(host, 50000))


def test_save_key_from_loopback(env_file, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "placeholder")
    res = _client("127.0.0.1").post("/config/keys", json={"keys": {"OPENAI_API_KEY": "sk-abc123XYZ"}})
    assert res.status_code == 200
    assert 'OPENAI_API_KEY="sk-abc123XYZ"' in env_file.read_text()
    assert 'OTHER="keep"' in env_file.read_text()


def test_remote_client_rejected(env_file):
    res = _client("192.168.1.50").post("/config/keys", json={"keys": {"OPENAI_API_KEY": "sk-attacker"}})
    assert res.status_code == 403
    assert "sk-attacker" not in env_file.read_text()
    assert _client("192.168.1.50").get("/config/keys").status_code == 403


def test_remote_allowed_when_opted_in(env_file, monkeypatch):
    monkeypatch.setenv("CRUCIBLE_ALLOW_REMOTE_CONFIG", "1")
    assert _client("172.17.0.1").get("/config/keys").status_code == 200


@pytest.mark.parametrize("value", ['sk-a"\nDATABASE_PATH="/tmp/x', "sk a", "sk-a\\b", "sk-$HOME"])
def test_env_injection_rejected(env_file, value):
    res = _client("127.0.0.1").post("/config/keys", json={"keys": {"OPENAI_API_KEY": value}})
    assert res.status_code == 400
    assert "DATABASE_PATH" not in env_file.read_text()


def test_mask_reveals_only_last_four():
    assert config_api._mask("sk-abcdefghijkl") == "•" * 11 + "ijkl"


def test_cors_rejects_foreign_origin():
    c = _client("127.0.0.1")
    evil = c.options("/config/keys", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in evil.headers
    ok = c.options("/config/keys", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
