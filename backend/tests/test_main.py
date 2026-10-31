"""Tests for message formatting and graph nodes.

No LLM calls — all responses are mocked.
"""

from unittest.mock import MagicMock
from app.llm import CallableModelFactory


class TestMessageFacts:
    """Who wrote a message and what it cites (services/message_format)."""

    def test_author_from_name_kwargs_metadata_or_dict(self):
        from langchain_core.messages import AIMessage

        from app.services.message_format import message_model

        assert message_model(AIMessage(content="x", name="gpt-5.4")) == "gpt-5.4"
        assert message_model(AIMessage(content="x", additional_kwargs={"model_id": "claude-x"})) == "claude-x"
        assert message_model(AIMessage(content="x", response_metadata={"model_name": "gemini-x"})) == "gemini-x"
        assert message_model({"type": "ai", "content": "x", "model": "m"}) == "m"
        assert message_model(AIMessage(content="x")) is None

    def test_sources_stored_or_native(self):
        from langchain_core.messages import AIMessage

        from app.services.message_format import message_sources

        stored = [{"text": "Doc", "filename": "a.md"}]
        assert message_sources(AIMessage(content="x", additional_kwargs={"sources": stored})) == stored
        gemini = AIMessage(content="x", response_metadata={
            "grounding_metadata": {"grounding_chunks": [{"web": {"uri": "https://e.x", "title": "E"}}]}})
        assert message_sources(gemini) == [{"text": "E", "filename": "https://e.x"}]
        cited = AIMessage(content=[{"type": "text", "text": "x", "annotations": [{"url": "https://o.x", "title": "O"}]}])
        assert message_sources(cited) == [{"text": "O", "filename": "https://o.x"}]
        assert message_sources(AIMessage(content="plain")) is None


class TestTranscript:
    """tree.format_messages: the path's messages, one per message."""

    @staticmethod
    def _path(*steps):
        """steps: message lists, one per checkpoint, each the parent of the next."""
        from types import SimpleNamespace

        states = {}
        for i, messages in enumerate(steps):
            states[f"c{i}"] = SimpleNamespace(
                values={"messages": messages, "active_peer": "gpt-5.4"},
                metadata={"crucible_turn_id": f"t{i // 3}"},
                parent_config={"configurable": {"checkpoint_id": f"c{i - 1}"}} if i else None,
                config={"configurable": {"checkpoint_id": f"c{i}"}},
            )
        return f"c{len(steps) - 1}", states

    def test_identical_replies_on_one_path_both_stay(self):
        from langchain_core.messages import AIMessage, HumanMessage

        from app.services.tree import format_messages

        q1, a1 = HumanMessage(content="Ready?"), AIMessage(content="OK", name="gpt-5.4")
        q2, a2 = HumanMessage(content="Go on"), AIMessage(content="OK", name="gpt-5.4")
        shown = format_messages(*self._path([q1], [q1, a1], [q1, a1, q2], [q1, a1, q2, a2]))
        assert [m["content"] for m in shown] == ["Ready?", "OK", "Go on", "OK"]

    def test_each_message_carries_its_first_checkpoint(self):
        from langchain_core.messages import AIMessage, HumanMessage

        from app.services.tree import format_messages

        q, a = HumanMessage(content="Q"), AIMessage(content="A", name="gpt-5.4")
        # LangGraph repeats the reply over the run's last checkpoints.
        shown = format_messages(*self._path([q], [q, a], [q, a], [q, a]))
        assert [(m["content"], m["checkpoint_id"]) for m in shown] == [("Q", "c0"), ("A", "c1")]
        assert shown[1]["model_name"] and shown[1]["turn_id"] == "t0"


class TestGraphNodes:
    """Tests for graph node functions (drafting_node, synthesis_node)."""

    def test_drafting_node_invokes_model(self):
        from app.services.graph import drafting_node
        from langchain_core.messages import HumanMessage, AIMessage

        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(content="Model response")

        state = {
            "active_peer": "gpt-5.2",
            "messages": [HumanMessage(content="Hello")],
            "toggles": {},
            "documents": {},
        }

        result = drafting_node(
            state,
            config={
                "configurable": {
                    "thread_id": "test_thread",
                    "model_factory": CallableModelFactory(lambda *_: mock_model),
                }
            },
        )

        assert len(result["messages"]) == 1
        assert result["messages"][0].content == "Model response"
        mock_model.invoke.assert_called_once()

    def test_summarize_history_short(self):
        from app.services.graph import summarize_history
        from langchain_core.messages import HumanMessage

        state = {
            "messages": [HumanMessage(content=f"Msg {i}") for i in range(5)],
            "active_peer": "gpt-4o",
        }
        result = summarize_history(state, {})
        # Should return delta as empty list (<= 5 messages buffer)
        assert result == {"messages": []}

    def test_the_drafting_note_uses_the_runs_clock(self):
        import datetime

        from langchain_core.messages import AIMessage, HumanMessage

        from app.services.graph import drafting_node

        seen = []

        class Model:
            def invoke(self, messages, *a, **k):
                seen.append("\n".join(str(m.content) for m in messages))
                return AIMessage(content="ok")

        fixed = datetime.datetime(2031, 5, 4, 12, 0, 0, tzinfo=datetime.timezone.utc)
        config = {"configurable": {"model_factory": CallableModelFactory(lambda *_: Model()), "clock": lambda: fixed}}
        drafting_node({"active_peer": "gpt-5.4", "toggles": {}, "messages": [HumanMessage(content="hi")]}, config)
        assert "2031-05-04 12:00:00" in seen[0]
