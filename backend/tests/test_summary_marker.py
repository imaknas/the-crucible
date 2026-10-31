"""Summaries are recognised by a flag on the system message, not by its text.

A user message or an attached document that quotes the marker used to be
taken for a summary: everything before it was pruned and the system prompt
(which carries the documents) was dropped.
"""

from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.core.schema import SUMMARY_FLAG, SUMMARY_MARKER, is_summary_message, summary_message, summary_text
from app.llm import CallableModelFactory
from app.services import graph as graph_mod
from types import SimpleNamespace

from app.services.tree import format_messages

QUOTE = f"My notes say '{SUMMARY_MARKER} the plan failed'. Is that right?"


class _Capture:
    """A chat model that records what it was sent."""

    def __init__(self):
        self.seen = None

    def invoke(self, messages, *args, **kwargs):
        self.seen = messages
        return AIMessage(content="ok")


def _cfg(model, **configurable):
    return {"configurable": {"model_factory": CallableModelFactory(lambda *_: model), **configurable}}


def _history():
    return [
        HumanMessage(content="First question about alpha"),
        AIMessage(content="Answer about alpha", name="gpt-6-luna"),
    ]


def test_the_written_summary_is_flagged():
    msg = summary_message("the gist")
    assert msg.additional_kwargs[SUMMARY_FLAG] is True
    assert msg.content.startswith(SUMMARY_MARKER)
    assert is_summary_message(msg)
    assert summary_text(msg) == "the gist"


def test_summarize_history_writes_a_flagged_message():
    model = _Capture()
    model.invoke = lambda *_a, **_k: AIMessage(content="Summarized.")
    state = {"messages": [HumanMessage(content=f"M{i}") for i in range(10)], "active_peer": "gpt-6-luna"}
    with patch.object(graph_mod, "count_tokens", return_value=100_000), \
            patch.object(graph_mod, "get_token_limit", return_value=10):
        out = graph_mod.summarize_history(state, _cfg(model))
    (written,) = out["messages"]
    assert written.additional_kwargs.get(SUMMARY_FLAG) is True


def test_a_user_message_quoting_the_marker_is_not_a_summary():
    messages = _history() + [HumanMessage(content=f"{SUMMARY_MARKER} pasted from somewhere")]
    assert not is_summary_message(messages[-1])
    assert graph_mod._last_summary_index(messages) == -1
    assert graph_mod.context_snapshot(messages).messages_since_summary is None


def test_sanitize_keeps_history_and_system_prompt_around_a_quoting_user_message():
    # More history than the verbatim window, so a false summary would prune it.
    filler = [m for i in range(4) for m in (HumanMessage(content=f"q{i}"), AIMessage(content=f"a{i}"))]
    messages = [SystemMessage(content="You are an assistant.")] + _history() + filler + [HumanMessage(content=QUOTE)]
    out = graph_mod.sanitize_messages(messages, prune_history=True)
    text = "\n".join(str(m.content) for m in out)
    assert out[0].type == "system" and "You are an assistant." in out[0].content
    assert "First question about alpha" in text
    assert QUOTE in text

    unpruned = graph_mod.sanitize_messages(messages, prune_history=False)
    assert QUOTE in "\n".join(str(m.content) for m in unpruned)


def test_an_attached_document_quoting_the_marker_reaches_the_model():
    model = _Capture()
    state = {
        "active_peer": "gpt-6-luna",
        "toggles": {},
        "messages": _history() + [HumanMessage(content="Summarise the attached file")],
        "documents": {"notes.md": f"Minutes.\n{SUMMARY_MARKER} we agreed on beta.\n"},
    }
    graph_mod.drafting_node(state, _cfg(model, thread_id="t-doc"))
    system = model.seen[0]
    assert system.type == "system"
    assert "[ATTACHED DOCUMENTS]" in system.content
    assert "we agreed on beta" in system.content
    sent = "\n".join(str(m.content) for m in model.seen)
    assert "First question about alpha" in sent


def test_a_legacy_unflagged_summary_still_prunes():
    legacy = SystemMessage(content=f"{SUMMARY_MARKER} the old gist")
    assert is_summary_message(legacy)
    older = [HumanMessage(content=f"old {i}") if i % 2 == 0 else AIMessage(content=f"reply {i}") for i in range(12)]
    messages = older + [legacy, HumanMessage(content="new question")]
    assert graph_mod._last_summary_index(messages) == len(older)
    out = graph_mod.sanitize_messages(messages, prune_history=True)
    text = "\n".join(str(m.content) for m in out)
    assert "the old gist" in text
    assert "old 0" not in text  # pruned: before the summary and outside the verbatim window


def test_only_system_messages_count_even_with_the_flag():
    forged = HumanMessage(content=f"{SUMMARY_MARKER} x", additional_kwargs={SUMMARY_FLAG: True})
    assert not is_summary_message(forged)
    assert is_summary_message({"type": "system", "content": f"{SUMMARY_MARKER} x"})
    assert not is_summary_message({"type": "system", "content": f"Docs: {SUMMARY_MARKER} x"})


def test_the_flag_survives_a_checkpoint_round_trip():
    """State is persisted with LangGraph's serializer; a summary read back
    from a checkpoint (as the eval harness's settled branches are) must
    still carry its flag."""
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    serde = JsonPlusSerializer()
    restored = serde.loads_typed(serde.dumps_typed(summary_message("gist")))
    assert restored.additional_kwargs.get(SUMMARY_FLAG) is True
    assert is_summary_message(restored)


def _path(messages):
    """A checkpoint per message, each one's parent the one before."""
    states = {}
    for i in range(len(messages)):
        states[f"c{i}"] = SimpleNamespace(
            values={"messages": messages[: i + 1]},
            metadata={},
            parent_config={"configurable": {"checkpoint_id": f"c{i - 1}"}} if i else None,
            config={"configurable": {"checkpoint_id": f"c{i}"}},
        )
    return f"c{len(messages) - 1}", states


def test_the_chat_view_shows_a_user_message_quoting_the_marker():
    raw = _history() + [HumanMessage(content=QUOTE), summary_message("gist")]
    shown = [m["content"] for m in format_messages(*_path(raw))]
    assert QUOTE in shown
    assert not any("gist" == c or c.startswith(SUMMARY_MARKER) for c in shown)
