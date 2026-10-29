"""The private upstream symbols our fixes hook into still exist and are still used.

app/patches.py replaces a private langchain_anthropic function and
GoogleProvider overrides a private ChatGoogleGenerativeAI method. If a
dependency bump renames either, the fix would silently stop applying; these
tests make the bump fail instead.
"""

from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from app import patches


def test_the_patched_anthropic_method_exists_and_streaming_calls_it():
    from langchain_anthropic.chat_models import ChatAnthropic

    patches.apply_langchain_patches()
    hook = getattr(ChatAnthropic, patches.ANTHROPIC_HOOK)
    assert getattr(hook, patches.PATCHED_ATTR, False), "patch did not apply"
    assert callable(hook.__wrapped__)
    # The streaming methods call it as self.<hook>, which is what makes
    # replacing the class attribute effective.
    for method in (ChatAnthropic._stream, ChatAnthropic._astream):
        assert patches.ANTHROPIC_HOOK in method.__code__.co_names, method.__name__


def test_the_patched_method_still_parses_a_dict_container():
    from langchain_anthropic.chat_models import ChatAnthropic

    patches.apply_langchain_patches()
    llm = ChatAnthropic(model="claude-haiku-5-5", api_key="test-key")
    usage = SimpleNamespace(
        input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0,
        server_tool_use=None, cache_creation=None,
    )
    delta = SimpleNamespace(
        stop_reason="end_turn", stop_sequence=None, container={"id": "c1"},
        model_dump=lambda **_: {"stop_reason": "end_turn"},
    )
    event = SimpleNamespace(type="message_delta", usage=usage, delta=delta, context_management=None)
    chunk, _ = getattr(llm, patches.ANTHROPIC_HOOK)(event, coerce_content_to_string=True)
    assert chunk.response_metadata["container"] == {"id": "c1"}


def test_applying_twice_wraps_once():
    from langchain_anthropic.chat_models import ChatAnthropic

    patches.apply_langchain_patches()
    first = getattr(ChatAnthropic, patches.ANTHROPIC_HOOK)
    patches._applied = False
    patches.apply_langchain_patches()
    assert getattr(ChatAnthropic, patches.ANTHROPIC_HOOK) is first


def test_a_dict_container_gets_a_model_dump():
    event = SimpleNamespace(type="message_delta", delta=SimpleNamespace(container={"id": "c1"}))
    patches.wrap_dict_container(event)
    assert event.delta.container.model_dump() == {"id": "c1"}

    other = SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(container={"id": "c1"}))
    patches.wrap_dict_container(other)
    assert other.delta.container == {"id": "c1"}


def test_a_missing_anthropic_hook_fails_loudly(monkeypatch):
    from langchain_anthropic.chat_models import ChatAnthropic

    monkeypatch.setattr(patches, "_applied", False)
    monkeypatch.delattr(ChatAnthropic, patches.ANTHROPIC_HOOK)
    with pytest.raises(RuntimeError, match=patches.ANTHROPIC_HOOK):
        patches.apply_langchain_patches()


def test_the_overridden_google_method_exists_and_builds_the_request(monkeypatch):
    from langchain_google_genai import ChatGoogleGenerativeAI

    from app.llm.providers import PROVIDERS, SAMPLING_PARAMETERS

    assert "_build_base_generation_config" in vars(ChatGoogleGenerativeAI)
    # Upstream builds the request through _prepare_params, which calls the
    # overridden method; a rename or a bypass shows up as sampling fields
    # reappearing in the real request below.
    assert "_build_base_generation_config" in ChatGoogleGenerativeAI._prepare_params.__code__.co_names

    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    request = PROVIDERS["google"].create("gemini-3.8-flash")._prepare_request([HumanMessage(content="hi")])
    config = request["config"]
    for name in SAMPLING_PARAMETERS:
        assert getattr(config, name) is None, name
