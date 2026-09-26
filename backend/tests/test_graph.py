"""Tests for graph.py and the model factory.

No real client is ever built: providers and models are injected fakes.
"""

import pytest
from unittest.mock import patch, MagicMock

from app.llm import CallableModelFactory, ProviderModelFactory


def _cfg(get_model, **configurable):
    """A node config that injects `get_model(model_id, toggles)` as the model factory."""
    return {"configurable": {"model_factory": CallableModelFactory(get_model), **configurable}}


class _RecordingProvider:
    """A ChatProvider strategy that records what it was asked to build."""

    def __init__(self):
        self.created = []
        self.searched = []

    def create(self, model_id):
        self.created.append(model_id)
        return f"client:{model_id}"

    def with_web_search(self, llm):
        self.searched.append(llm)
        return f"search:{llm}"


def _factory(env=None):
    providers = {f: _RecordingProvider() for f in ("openai", "anthropic", "google")}
    return ProviderModelFactory(providers=providers, env=env or {}), providers


# ─── ProviderModelFactory ─────────────────────────────────────────


class TestProviderModelFactory:
    @pytest.mark.parametrize(
        "model_id, family, env_key",
        [
            ("gpt-5.2", "openai", "OPENAI_API_KEY"),
            ("claude-sonnet-4-6", "anthropic", "ANTHROPIC_API_KEY"),
            ("gemini-3-flash-preview", "google", "GOOGLE_API_KEY"),
        ],
    )
    def test_builds_through_the_family_strategy(self, model_id, family, env_key):
        factory, providers = _factory({env_key: "k"})
        assert factory.chat(model_id) == f"client:{model_id}"
        assert providers[family].created == [model_id]
        assert all(not p.created for f, p in providers.items() if f != family)

    @pytest.mark.parametrize(
        "model_id, env_key",
        [("gpt-5.2", "OPENAI_API_KEY"), ("claude-sonnet-4-6", "ANTHROPIC_API_KEY"), ("gemini-3-flash-preview", "GOOGLE_API_KEY")],
    )
    def test_missing_key_raises(self, model_id, env_key):
        factory, _ = _factory({})
        with pytest.raises(ValueError, match=env_key):
            factory.chat(model_id)

    def test_unknown_model_not_in_whitelist(self):
        factory, _ = _factory({"OPENAI_API_KEY": "k"})
        with pytest.raises(ValueError, match="not supported in the whitelist"):
            factory.chat("totally-unknown-model")

    def test_normalizes_case_and_whitespace(self):
        factory, providers = _factory({"OPENAI_API_KEY": "k"})
        factory.chat("  GPT-5.2  ")
        assert providers["openai"].created == ["gpt-5.2"]

    def test_web_search_only_for_native_search_models(self):
        from app.api.models import MODEL_REGISTRY

        searchable = next(m for m, c in MODEL_REGISTRY.items() if c.get("native_search") and c["family"] == "openai")
        plain = next((m for m, c in MODEL_REGISTRY.items() if not c.get("native_search") and c["family"] == "openai"), None)
        factory, providers = _factory({"OPENAI_API_KEY": "k"})
        assert factory.chat(searchable, {"use_web_search": True}).startswith("search:")
        assert not factory.chat(searchable, {}).startswith("search:")
        if plain:
            assert not factory.chat(plain, {"use_web_search": True}).startswith("search:")


# ─── sanitize_messages() ──────────────────────────────────────────


class TestSanitizeMessages:
    """Tests for the robust message sanitization logic."""

    def test_empty_messages(self):
        from app.services.graph import sanitize_messages

        res = sanitize_messages([])
        assert len(res) == 1
        assert res[0].type == "human"

    def test_strip_empty_content(self):
        from app.services.graph import sanitize_messages
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

        messages = [
            SystemMessage(content=""),  # Should get fallback "System Instruction"
            HumanMessage(content="\x00"),  # null byte, becomes empty and gets dropped
            AIMessage(content="Hello"),
        ]
        res = sanitize_messages(messages)
        # Sys Instruction + Human(Continue.) + AI(Hello)
        assert len(res) == 3
        assert res[0].type == "system"
        assert res[0].content == "System Instruction"
        assert res[1].type == "human"  # inserted because first non-sys must be human
        assert res[1].content == "Continue."
        assert res[2].type == "ai"
        assert res[2].content == "Hello"

    def test_merge_consecutive_roles(self):
        from app.services.graph import sanitize_messages
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

        messages = [
            SystemMessage(content="Sys 1"),
            SystemMessage(content="Sys 2"),
            HumanMessage(content="H1"),
            HumanMessage(content="H2"),
            AIMessage(content="A1"),
            AIMessage(content="A2"),
        ]
        res = sanitize_messages(messages)
        # Sys messages are NOT merged in the final output in graph.py currently, only user/ai pairs.
        assert len(res) == 4
        assert res[0].type == "system" and "Sys 1" in res[0].content
        assert res[1].type == "system" and "Sys 2" in res[1].content
        assert res[2].type == "human" and "H1\n\n---\n\nH2" in res[2].content
        assert res[3].type == "ai" and "A1\n\n---\n\nA2" in res[3].content

    def test_prune_history(self):
        from app.services.graph import sanitize_messages
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

        messages = [
            SystemMessage(content="Base Rule"),
            HumanMessage(content="Old 1"),
            AIMessage(content="Old 2"),
            SystemMessage(content="PREVIOUS CONTEXT SUMMARY: We talked about X"),
            HumanMessage(content="New 1"),
        ]
        res = sanitize_messages(messages)
        # Should keep Base Rule, jump to Summary, and keep New 1. Old 1 & 2 dropped but Old 1 might be recovered if it was right before summary
        assert any(m.type == "system" and "Base Rule" in m.content for m in res)
        assert any(
            m.type == "system" and "PREVIOUS CONTEXT SUMMARY:" in m.content for m in res
        )
        assert any(m.type == "human" and "New 1" in m.content for m in res)
        assert not any(m.type == "ai" and "Old 2" in m.content for m in res)


# ─── Token Limits ────────────────────────────────────────────────


class TestTokenUtils:
    def test_get_token_limit(self):
        from app.services.graph import get_token_limit

        assert get_token_limit("gpt-5.2") >= 60000
        assert get_token_limit("claude-sonnet-4-6") >= 20000
        assert get_token_limit("unknown-model") == 60_000

    def test_count_tokens(self):
        from app.services.graph import count_tokens
        from langchain_core.messages import HumanMessage

        messages = [HumanMessage(content="Hello world!")]
        assert count_tokens(messages) > 0
        assert count_tokens([]) == 0


# ─── LangGraph Nodes ────────────────────────────────────────────────


class TestNodes:
    def test_drafting_node(self):
        mock_get_model = MagicMock()
        from app.services.graph import drafting_node
        from langchain_core.messages import AIMessage, HumanMessage

        mock_llm = MagicMock()
        mock_response = AIMessage(content="Confidence: 95%\nThis is a test.")
        mock_llm.invoke.return_value = mock_response
        mock_get_model.return_value = mock_llm

        state = {
            "active_peer": "gpt-5.2",
            "toggles": {},
            "messages": [HumanMessage(content="Hello")],
            "is_deliberation": False,
            "retrieved_chunks": [{"filename": "doc.pdf", "text": "Some facts."}],
        }

        res = drafting_node(state, config=_cfg(mock_get_model, thread_id="test"))

        mock_get_model.assert_called_once_with("gpt-5.2", state["toggles"])
        mock_llm.invoke.assert_called_once()

        out_msg = res["messages"][0]
        assert "This is a test" in out_msg.content
        assert out_msg.name == "gpt-5.2"
        assert out_msg.additional_kwargs["confidence"] == 0.95
        assert out_msg.additional_kwargs["conflict"] is False

    def test_drafting_node_deliberation_conflict(self):
        mock_get_model = MagicMock()
        from app.services.graph import drafting_node
        from langchain_core.messages import AIMessage, HumanMessage

        mock_llm = MagicMock()
        mock_response = AIMessage(content="There is a contradiction here.")
        mock_llm.invoke.return_value = mock_response
        mock_get_model.return_value = mock_llm

        state = {
            "active_peer": "claude-sonnet-4-6",
            "toggles": {},
            "messages": [HumanMessage(content="Hello")],
            "is_deliberation": True,
        }

        res = drafting_node(state, config=_cfg(mock_get_model, thread_id="test"))
        out_msg = res["messages"][0]
        assert out_msg.additional_kwargs["conflict"] is True
        assert res["is_deliberation"] is False

    def test_synthesis_node(self):
        mock_get_model = MagicMock()
        from app.services.graph import synthesis_node
        from langchain_core.messages import AIMessage, HumanMessage

        mock_llm = MagicMock()
        mock_response = AIMessage(
            content="Updated thesis based on recent conversation."
        )
        mock_llm.invoke.return_value = mock_response
        mock_get_model.return_value = mock_llm

        state = {
            "active_peer": "gpt-5.2",
            "toggles": {},
            "messages": [
                HumanMessage(
                    content="This is a long enough message to trigger synthesis."
                )
            ],
            "current_thesis": "Old thesis.",
        }

        res = synthesis_node(state, _cfg(mock_get_model))
        assert res["current_thesis"] == "Updated thesis based on recent conversation."

        # Test short-circuit
        short_state = {
            "active_peer": "gpt-5.2",
            "messages": [HumanMessage(content="Short")],
            "current_thesis": "Old thesis.",
        }
        res_short = synthesis_node(short_state, _cfg(mock_get_model))
        assert (
            res_short["current_thesis"] == "Old thesis."
        )  # Should not update because of short-circuit
        # LLM invoke count should remain 1 from previous call
        assert mock_llm.invoke.call_count == 1

    @patch("app.services.graph.rag_service.retrieve_context")
    def test_retrieve_node(self, mock_retrieve):
        from app.services.graph import retrieve_node
        from langchain_core.messages import HumanMessage

        # RAG disabled
        assert retrieve_node({"toggles": {"use_rag": False}}, {}) == {
            "retrieved_chunks": []
        }

        # RAG enabled, no query
        assert retrieve_node({"toggles": {"use_rag": True}, "messages": []}, {}) == {
            "retrieved_chunks": []
        }

        # RAG enabled, query
        mock_doc = MagicMock()
        mock_doc.page_content = "Fact"
        mock_doc.metadata = {"filename": "test.pdf"}
        mock_retrieve.return_value = [mock_doc]

        state = {
            "toggles": {"use_rag": True},
            "messages": [HumanMessage(content="Query")],
        }
        res = retrieve_node(state, {"configurable": {"thread_id": "test"}})
        assert len(res["retrieved_chunks"]) == 1
        assert res["retrieved_chunks"][0]["text"] == "Fact"
        mock_retrieve.assert_called_once_with("Query", "test")

    @pytest.mark.asyncio
    async def test_grade_retrieval_node(self):
        mock_get_model = MagicMock()
        from app.services.graph import grade_retrieval_node
        from langchain_core.messages import AIMessage, HumanMessage

        mock_llm = MagicMock()
        mock_get_model.return_value = mock_llm

        async def mock_ainvoke(*args, **kwargs):
            content = args[0][0].content
            if "Fact 1" in content:
                return AIMessage(content="yes")
            return AIMessage(content="no")

        mock_llm.ainvoke = mock_ainvoke

        state = {
            "retrieved_chunks": [
                {"text": "Fact 1", "filename": "test1"},
                {"text": "Fact 2", "filename": "test2"},
            ],
            "messages": [HumanMessage(content="Query")],
            "active_peer": "gpt-5.2",
        }

        res = await grade_retrieval_node(state, _cfg(mock_get_model))
        assert len(res["retrieved_chunks"]) == 1
        assert res["retrieved_chunks"][0]["text"] == "Fact 1"

    def test_summarize_history(self):
        mock_get_model = MagicMock()
        from app.services.graph import summarize_history
        from langchain_core.messages import HumanMessage, AIMessage

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="Summarized.")
        mock_get_model.return_value = mock_llm

        messages = [HumanMessage(content=f"M{i}") for i in range(10)]
        state = {"messages": messages, "active_peer": "gpt-5.2"}

        with patch("app.services.graph.count_tokens", return_value=100000):
            with patch("app.services.graph.get_token_limit", return_value=10):
                res = summarize_history(state, _cfg(mock_get_model))

        assert len(res["messages"]) == 1
        assert "PREVIOUS CONTEXT SUMMARY:" in res["messages"][0].content
