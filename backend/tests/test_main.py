"""Tests for main.py — _format_messages helper and endpoint wiring.

No LLM calls — all responses are mocked.
"""

from unittest.mock import MagicMock


class TestFormatMessages:
    """Tests for the _format_messages() helper in main.py."""

    def test_human_message_object(self):
        from main import _format_messages

        msg = MagicMock()
        msg.type = "human"
        msg.content = "Hello"
        result = _format_messages([msg], "gpt-5.2")
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello"
        assert result[0]["model"] == "user"

    def test_ai_message_object(self):
        from main import _format_messages

        msg = MagicMock()
        msg.type = "ai"
        msg.content = "Reply from GPT"
        result = _format_messages([msg], "gpt-5.2")
        assert result[0]["role"] == "assistant"
        assert result[0]["content"] == "Reply from GPT"
        assert result[0]["model"] == "gpt-5.2"

    def test_dict_message(self):
        from main import _format_messages

        msg = {"type": "human", "content": "Hello", "role": "user"}
        result = _format_messages([msg], "gpt-5.2")
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello"

    def test_multiple_messages(self):
        from main import _format_messages

        m1 = MagicMock()
        m1.type = "human"
        m1.content = "Q"
        m2 = MagicMock()
        m2.type = "ai"
        m2.content = "A"
        m3 = MagicMock()
        m3.type = "human"
        m3.content = "Follow-up"
        result = _format_messages([m1, m2, m3], "claude-sonnet-4-6")
        assert len(result) == 3
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert result[1]["model"] == "claude-sonnet-4-6"
        assert result[2]["role"] == "user"

    def test_empty_messages(self):
        from main import _format_messages

        result = _format_messages([], "gpt-5.2")
        assert result == []

    def test_string_fallback(self):
        from main import _format_messages

        result = _format_messages(["raw string message"], "gpt-5.2")
        assert len(result) == 1
        assert result[0]["content"] == "raw string message"


class TestGraphNodes:
    """Tests for graph node functions (drafting_node, synthesis_node)."""

    def test_drafting_node_invokes_model(self):
        from unittest.mock import patch
        from graph import drafting_node
        from langchain_core.messages import HumanMessage, AIMessage

        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(content="Model response")

        state = {
            "active_peer": "gpt-5.2",
            "messages": [HumanMessage(content="Hello")],
            "toggles": {},
            "documents": {},
        }

        with patch("graph.get_model", return_value=mock_model):
            result = drafting_node(state)

        assert len(result["messages"]) == 1
        assert result["messages"][0].content == "Model response"
        mock_model.invoke.assert_called_once()

    def test_drafting_node_with_strict_logic(self):
        from unittest.mock import patch
        from graph import drafting_node
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(content="Logical response")

        state = {
            "active_peer": "gpt-5.2",
            "messages": [HumanMessage(content="Test")],
            "toggles": {"strict_logic": True},
            "documents": {},
        }

        with patch("graph.get_model", return_value=mock_model):
            drafting_node(state)

        # Check that system message includes "Step-by-Step"
        call_args = mock_model.invoke.call_args[0][0]
        system_msg = call_args[0]
        assert isinstance(system_msg, SystemMessage)
        assert "Step-by-Step" in system_msg.content

    def test_synthesis_node_updates_thesis(self):
        from unittest.mock import patch
        from graph import synthesis_node
        from langchain_core.messages import HumanMessage, AIMessage

        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(content="Updated thesis")

        state = {
            "messages": [HumanMessage(content="Test input")],
            "active_peer": "gpt-5.2",
        }

        with patch("graph.get_model", return_value=mock_model):
            result = synthesis_node(state)

        assert result["current_thesis"] == "Updated thesis"

    def test_summarize_history_short(self):
        from graph import summarize_history
        from langchain_core.messages import HumanMessage

        state = {
            "messages": [HumanMessage(content=f"Msg {i}") for i in range(5)],
            "active_peer": "gpt-4o",
        }
        result = summarize_history(state)
        # Should return state unchanged (<= 5 messages buffer)
        assert result == state

    def test_should_summarize_under_threshold(self):
        from graph import should_summarize
        from langchain_core.messages import HumanMessage

        # Provide an active peer and some tokens well under 100k
        state = {"messages": [HumanMessage(content="x")] * 10, "active_peer": "gpt-4o"}
        assert should_summarize(state) == "draft"

    def test_should_summarize_over_threshold(self):
        from graph import should_summarize
        from langchain_core.messages import HumanMessage

        # Each "word " is ~1 token. Let's create a message with 30,000 words.
        # With 4 of these, it's ~120k tokens -> over GPT-4o's 100k limit.
        long_content = "word " * 30000
        state = {
            "messages": [HumanMessage(content=long_content)] * 4,
            "active_peer": "gpt-4o",
        }
        # But wait, should_summarize also requires len(messages) > 5 as a safety buffer
        state["messages"].extend([HumanMessage(content="short")] * 2)

        assert should_summarize(state) == "summarize"
