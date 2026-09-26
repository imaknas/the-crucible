"""The scripted model used by the Playwright suite."""

import pytest
from langchain_core.messages import HumanMessage

from app.services import fake_llm
from app.services.graph import get_model


def test_get_model_returns_fake_only_when_enabled(monkeypatch):
    monkeypatch.setenv("CRUCIBLE_FAKE_LLM", "1")
    assert isinstance(get_model("gpt-5.4"), fake_llm.ScriptedChatModel)
    with pytest.raises(ValueError):
        get_model("not-a-model")  # the registry still applies
    monkeypatch.delenv("CRUCIBLE_FAKE_LLM")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")  # constructing the client makes no call
    assert not isinstance(get_model("gpt-5.4"), fake_llm.ScriptedChatModel)


def test_streams_deterministic_reply(monkeypatch):
    model = fake_llm.ScriptedChatModel(model_id="gpt-5.4", delay=0)
    chunks = [c.content for c in model.stream([HumanMessage(content="Q")])]
    assert len(chunks) > 5
    assert "".join(chunks) == model.invoke([HumanMessage(content="Q")]).content
    assert "gpt-5.4" in "".join(chunks)


def test_fail_hook_targets_one_model():
    msgs = [HumanMessage(content="Q [[fail:gpt-5.4]]")]
    with pytest.raises(RuntimeError, match="scripted"):
        fake_llm.ScriptedChatModel(model_id="gpt-5.4", delay=0).invoke(msgs)
    fake_llm.ScriptedChatModel(model_id="claude-sonnet-5", delay=0).invoke(msgs)
