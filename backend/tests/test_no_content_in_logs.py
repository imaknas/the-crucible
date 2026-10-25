"""The graph's diagnostics never print conversation text, only counts and ids."""

from langchain_core.messages import AIMessage, HumanMessage

from app.llm import CallableModelFactory
from app.services import graph as graph_mod
from app.services import rag

SECRET = "zebra-quartz-71 is my account password"


class _Model:
    def invoke(self, messages, *args, **kwargs):
        return AIMessage(content="noted")


def test_drafting_logs_no_message_text(capsys):
    state = {
        "active_peer": "gpt-6-luna",
        "toggles": {},
        "messages": [
            HumanMessage(content=f"Earlier: {SECRET}"),
            AIMessage(content=f"You said {SECRET}", name="gpt-6-luna"),
            HumanMessage(content=f"Remember {SECRET}?"),
        ],
        "documents": {"notes.txt": SECRET},
        "retrieved_chunks": [{"text": SECRET, "filename": "kb.md"}],
    }
    config = {"configurable": {"model_factory": CallableModelFactory(lambda *_: _Model()), "thread_id": "t-log"}}
    graph_mod.drafting_node(state, config)
    out = capsys.readouterr()
    assert "[INVOKE] Model: gpt-6-luna" in out.out
    assert "zebra-quartz" not in out.out + out.err


def test_retrieval_logs_no_query(capsys, monkeypatch):
    class _Store:
        def similarity_search_with_score(self, query, k, filter):
            return []

    monkeypatch.setattr(rag, "get_vector_store", lambda: _Store())
    rag.retrieve_context(SECRET, "t-log")
    out = capsys.readouterr()
    assert "[RAG] Retrieved 0 chunks" in out.out
    assert "zebra-quartz" not in out.out + out.err
