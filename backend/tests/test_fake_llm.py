"""The scripted model used by the Playwright suite, and how it is selected."""

import pytest
from langchain_core.messages import HumanMessage

from app.llm import ProviderModelFactory, default_model_factory, use_model_factory
from app.llm import fake as fake_llm


def test_default_factory_is_scripted_only_when_enabled(monkeypatch):
    monkeypatch.setenv("CRUCIBLE_FAKE_LLM", "1")
    factory = default_model_factory()
    assert isinstance(factory, fake_llm.ScriptedModelFactory)
    assert isinstance(factory.chat("gpt-5.4"), fake_llm.ScriptedChatModel)
    with pytest.raises(ValueError):
        factory.chat("not-a-model")  # the registry still applies

    monkeypatch.delenv("CRUCIBLE_FAKE_LLM")
    assert isinstance(default_model_factory(), ProviderModelFactory)


def test_use_model_factory_overrides_and_restores():
    stub = fake_llm.ScriptedModelFactory(delay=0)
    with use_model_factory(stub):
        assert default_model_factory() is stub
    assert default_model_factory() is not stub


def test_streams_deterministic_reply():
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
