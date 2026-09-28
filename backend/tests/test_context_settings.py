"""The history choices a person makes per run, and the app's default summarizer."""

import pytest

from app.services.context import ContextSettings
from app.services.graph import RECALL_CONFIG_KEY, SUMMARIZER_CONFIG_KEY

KEYS = {"OPENAI_API_KEY": "k", "ANTHROPIC_API_KEY": "k", "GOOGLE_API_KEY": "k"}


def test_a_chosen_summarizer_goes_on_the_run_config_with_the_default_recall():
    config = ContextSettings(summarizer="claude-haiku-4-5-20251001").apply({"configurable": {}}, KEYS)
    assert config["configurable"][SUMMARIZER_CONFIG_KEY] == "claude-haiku-4-5-20251001"
    assert RECALL_CONFIG_KEY in config["configurable"]
    assert SUMMARIZER_CONFIG_KEY not in ContextSettings().apply({"configurable": {}}, KEYS)["configurable"]


@pytest.mark.parametrize("model, env, fragment", [
    ("no-such-model", KEYS, "Unknown summarizer"),
    ("claude-haiku-4-5-20251001", {"OPENAI_API_KEY": "k"}, "No API key"),
])
def test_a_summarizer_that_cannot_run_is_refused(model, env, fragment):
    assert fragment in ContextSettings(summarizer=model).problem(env)


def test_unset_or_usable_settings_have_no_problem():
    assert ContextSettings().problem({}) is None
    assert ContextSettings(summarizer="gpt-6-luna").problem({"OPENAI_API_KEY": "k"}) is None
    assert ContextSettings.from_frame({"summarizer": ""}).summarizer is None  # "" = automatic


def test_models_endpoint_names_the_resolved_default_summarizer(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import create_app

    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    body = TestClient(create_app()).get("/models").json()
    assert body["default_summarizer"] == "claude-haiku-4-5-20251001"


def test_post_chat_refuses_a_summarizer_without_a_key(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import create_app

    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    client = TestClient(create_app())
    client.app.state.graph_app = object()  # never reached
    r = client.post("/chat", json={"message": "hi", "thread_id": "t", "summarizer": "gpt-6-luna"})
    assert r.status_code == 400 and "No API key" in r.json()["detail"]
