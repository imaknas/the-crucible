"""Tests for graph.py — model selection logic.

All LLM constructors are mocked — no API keys or tokens consumed.
"""

import os
import pytest
from unittest.mock import patch, MagicMock


def _patch_constructor(family: str):
    """Patch the constructor in _FAMILY_CONSTRUCTORS for a given family."""
    from app.services import graph as graph

    original = graph._FAMILY_CONSTRUCTORS[family]
    mock_cls = MagicMock()

    class _Ctx:
        def __enter__(self):
            graph._FAMILY_CONSTRUCTORS[family] = (original[0], mock_cls)
            return mock_cls

        def __exit__(self, *args):
            graph._FAMILY_CONSTRUCTORS[family] = original

    return _Ctx()


# ─── get_model() ──────────────────────────────────────────────────


class TestGetModel:
    """Tests for the get_model() function that maps model IDs to LLM instances."""

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-123"})
    def test_exact_match_openai(self):
        from app.services.graph import get_model

        with _patch_constructor("openai") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_model("gpt-5.2")
            mock_cls.assert_called_once_with(model="gpt-5.2")

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-123"})
    def test_exact_match_openai_pro(self):
        from app.services.graph import get_model

        with _patch_constructor("openai") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_model("gpt-5.2-pro")
            mock_cls.assert_called_once_with(model="gpt-5.2-pro")

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"})
    def test_exact_match_anthropic(self):
        from app.services.graph import get_model

        with _patch_constructor("anthropic") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_model("claude-sonnet-4-6")
            mock_cls.assert_called_once_with(model="claude-sonnet-4-6")

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "goog-test"})
    def test_exact_match_google(self):
        from app.services.graph import get_model

        with _patch_constructor("google") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_model("gemini-3-flash-preview")
            mock_cls.assert_called_once_with(model="gemini-3-flash-preview")

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_openai_key_raises(self):
        from app.services.graph import get_model

        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            get_model("gpt-5.2")

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_anthropic_key_raises(self):
        from app.services.graph import get_model

        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            get_model("claude-sonnet-4-6")

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_google_key_raises(self):
        from app.services.graph import get_model

        with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
            get_model("gemini-3-flash-preview")

    @patch.dict(os.environ, {}, clear=True)
    def test_unknown_model_not_in_whitelist(self):
        from app.services.graph import get_model

        with pytest.raises(ValueError, match="not supported in the whitelist"):
            get_model("totally-unknown-model")

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"})
    def test_case_insensitive(self):
        from app.services.graph import get_model

        with _patch_constructor("openai") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_model("GPT-5.2")
            mock_cls.assert_called_once_with(model="gpt-5.2")

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"})
    def test_strips_whitespace(self):
        from app.services.graph import get_model

        with _patch_constructor("openai") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_model("  gpt-5.2  ")
            mock_cls.assert_called_once_with(model="gpt-5.2")


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
    @patch("app.services.graph.get_model")
    def test_drafting_node(self, mock_get_model):
        from app.services.graph import drafting_node
        from langchain_core.messages import AIMessage, HumanMessage

        mock_llm = MagicMock()
        mock_response = AIMessage(content="Confidence: 95%\nThis is a test.")
        mock_llm.invoke.return_value = mock_response
        mock_get_model.return_value = mock_llm

        state = {
            "active_peer": "gpt-5.2",
            "toggles": {"strict_logic": True, "cot_enabled": True},
            "messages": [HumanMessage(content="Hello")],
            "is_deliberation": False,
            "retrieved_chunks": [{"filename": "doc.pdf", "text": "Some facts."}],
        }

        res = drafting_node(state, config={"configurable": {"thread_id": "test"}})

        mock_get_model.assert_called_once_with("gpt-5.2", state["toggles"])
        mock_llm.invoke.assert_called_once()
        invoked_msgs = mock_llm.invoke.call_args[0][0]
        assert any("Step-by-Step" in str(m.content) for m in invoked_msgs)

        out_msg = res["messages"][0]
        assert "This is a test" in out_msg.content
        assert out_msg.name == "gpt-5.2"
        assert out_msg.additional_kwargs["confidence"] == 0.95
        assert out_msg.additional_kwargs["conflict"] is False

    @patch("app.services.graph.get_model")
    def test_drafting_node_deliberation_conflict(self, mock_get_model):
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

        res = drafting_node(state, config={"configurable": {"thread_id": "test"}})
        out_msg = res["messages"][0]
        assert out_msg.additional_kwargs["conflict"] is True
        assert res["is_deliberation"] is False

    @patch("app.services.graph.get_model")
    def test_synthesis_node(self, mock_get_model):
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

        res = synthesis_node(state)
        assert res["current_thesis"] == "Updated thesis based on recent conversation."

        # Test short-circuit
        short_state = {
            "active_peer": "gpt-5.2",
            "messages": [HumanMessage(content="Short")],
            "current_thesis": "Old thesis.",
        }
        res_short = synthesis_node(short_state)
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
    @patch("app.services.graph.get_model")
    async def test_grade_retrieval_node(self, mock_get_model):
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

        res = await grade_retrieval_node(state, {})
        assert len(res["retrieved_chunks"]) == 1
        assert res["retrieved_chunks"][0]["text"] == "Fact 1"

    @patch("app.services.graph.get_model")
    def test_summarize_history(self, mock_get_model):
        from app.services.graph import summarize_history
        from langchain_core.messages import HumanMessage, AIMessage

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="Summarized.")
        mock_get_model.return_value = mock_llm

        messages = [HumanMessage(content=f"M{i}") for i in range(10)]
        state = {"messages": messages, "active_peer": "gpt-5.2"}

        with patch("app.services.graph.count_tokens", return_value=100000):
            with patch("app.services.graph.get_token_limit", return_value=10):
                res = summarize_history(state)

        assert len(res["messages"]) == 1
        assert "PREVIOUS CONTEXT SUMMARY:" in res["messages"][0].content


# ─── Orchestrators ──────────────────────────────────────────────────


class TestOrchestrators:
    @pytest.fixture
    def mock_graph_app(self):
        class MockChunk:
            def __init__(self, content):
                self.content = content

        class MockApp:
            async def astream_events(self, state, config, version):
                # Simulate a stream event
                yield {
                    "event": "on_chat_model_stream",
                    "metadata": {"langgraph_node": "draft"},
                    "data": {"chunk": MockChunk("Token")},
                }
                # Simulate a chain end event
                yield {
                    "event": "on_chain_end",
                    "name": "LangGraph",
                    "data": {"output": {"current_thesis": "Final Consensus"}},
                }

            async def aget_state(self, config):
                mock_state = MagicMock()
                mock_state.values = {"current_thesis": "Final Consensus"}
                return mock_state

        return MockApp()

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-1", "ANTHROPIC_API_KEY": "sk-2"})
    async def test_run_crucible_arena(self, mock_graph_app):
        from app.services.graph import run_crucible_arena

        # Test basic parallel run
        res = await run_crucible_arena(
            mock_graph_app, "Prompt", "thread_id", models=["gpt-5.2"]
        )
        assert res == "Final Consensus"

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-1", "ANTHROPIC_API_KEY": "sk-2"})
    async def test_run_arena_streaming(self, mock_graph_app):
        from app.services.graph import run_arena_streaming

        events = []
        async for evt in run_arena_streaming(
            mock_graph_app, "Prompt", "thread_id", models=["gpt-5.2"]
        ):
            events.append(evt)

        assert any(e["type"] == "token" and e["token"] == "Token" for e in events)
        assert any(e["type"] == "end" for e in events)
        assert any(
            e["type"] == "synthesis" and e["content"] == "Final Consensus"
            for e in events
        )

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-1", "ANTHROPIC_API_KEY": "sk-2"})
    async def test_run_deliberation(self, mock_graph_app):
        from app.services.graph import run_deliberation

        events = []
        async for evt in run_deliberation(
            mock_graph_app, "Prompt", "thread_id", models=["gpt-5.2"], rounds=1
        ):
            events.append(evt)

        assert any(e["type"] == "round_start" and e["round"] == 1 for e in events)
        assert any(
            e["type"] == "model_start" and e["model"] == "gpt-5.2" for e in events
        )
        assert any(e["type"] == "token" and e["token"] == "Token" for e in events)
        assert any(e["type"] == "synthesis" for e in events)
