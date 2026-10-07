"""Gemini requests carry no sampling parameters (the upcoming models reject them)."""

import pytest

from app.llm.providers import PROVIDERS, SAMPLING_PARAMETERS


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")


@pytest.mark.parametrize("model_id", ["gemini-3.8-flash", "gemini-3.5-flash"])
def test_generation_config_has_no_sampling_parameters(model_id):
    llm = PROVIDERS["google"].create(model_id)
    config = llm._build_base_generation_config(None)
    assert not set(SAMPLING_PARAMETERS) & set(config)


def test_thinking_level_is_still_passed_and_budget_is_not():
    llm = PROVIDERS["google"].create("gemini-3.8-flash").bind(thinking_level="low")
    bound = llm.kwargs
    assert bound == {"thinking_level": "low"}
    config = llm.bound._build_base_generation_config(None, **bound)
    thinking = config["thinking_config"]
    assert thinking.thinking_level is not None
    assert thinking.thinking_budget is None
