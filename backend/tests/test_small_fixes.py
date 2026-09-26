"""Regression tests for the sanitizer trim guard, summarizer input and uploads."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.services.graph import sanitize_messages


def test_trim_keeps_the_newest_human_not_the_oldest():
    # Each message is capped at 100k, but consecutive AI replies are merged
    # after the cap: eleven and a half of them (~1.15M) leave no room under the 1.2M total
    # for the latest question, so the trim drops it.
    latest = "latest question " + "q" * 99_000
    msgs = [HumanMessage(content="first question"), AIMessage(content="a"), HumanMessage(content=latest)]
    msgs += [AIMessage(content=c * 100_000) for c in "rstuvwxyzab"] + [AIMessage(content="c" * 50_000)]
    out = sanitize_messages(msgs)
    humans = [m.content for m in out if m.type == "human"]
    assert humans == [latest]
    # Chronological: the kept question comes before the reply to it.
    assert [m.type for m in out if m.type != "system"] == ["human", "ai"]


def test_summarizer_starts_from_previous_summary():
    from app.services import graph as graph_mod

    history = [HumanMessage(content=f"old {i}") for i in range(20)]
    history.append(SystemMessage(content="PREVIOUS CONTEXT SUMMARY: earlier stuff"))
    history += [HumanMessage(content=f"new {i}") if i % 2 == 0 else AIMessage(content=f"new {i}") for i in range(30)]

    captured = {}
    fake = MagicMock()
    fake.invoke.side_effect = lambda msgs: captured.setdefault("prompt", msgs[0].content) and MagicMock(content="s")
    from app.llm import CallableModelFactory

    config = {"configurable": {"model_factory": CallableModelFactory(lambda *_: fake)}}
    with patch.object(graph_mod, "get_token_limit", return_value=1):
        graph_mod.summarize_history({"messages": history, "active_peer": "gpt-5.4"}, config)

    assert "earlier stuff" in captured["prompt"]
    assert "old 3" not in captured["prompt"]


def test_concurrent_same_name_uploads_do_not_cross(tmp_path, monkeypatch):
    from app.api import upload as upload_api
    from app.main import server

    monkeypatch.setattr(upload_api, "_UPLOAD_DIR", str(tmp_path))
    indexed = []
    monkeypatch.setattr(upload_api.rag_service, "index_document", lambda text, name, tid: indexed.append((tid, text)))

    with TestClient(server) as client:
        a = client.post("/upload", data={"thread_id": "A"}, files={"file": ("notes.txt", b"alpha", "text/plain")})
        b = client.post("/upload", data={"thread_id": "B"}, files={"file": ("notes.txt", b"beta", "text/plain")})
    assert a.json()["full_content"] == "alpha"
    assert b.json()["full_content"] == "beta"
    assert len(list(tmp_path.iterdir())) == 2
    assert sorted(indexed) == [("A", "alpha"), ("B", "beta")]


def test_upload_over_limit_rejected(tmp_path, monkeypatch):
    from app.api import upload as upload_api
    from app.main import server

    monkeypatch.setattr(upload_api, "_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(upload_api, "_MAX_FILE_BYTES", 10)
    with TestClient(server) as client:
        res = client.post("/upload", data={"thread_id": "A"}, files={"file": ("big.txt", b"x" * 50, "text/plain")})
    assert res.status_code == 400
    assert not list(tmp_path.iterdir())




def test_auto_title():
    from app.services.chat import auto_title

    assert auto_title("Short question\nmore lines") == "Short question"
    long = "This is a fairly long opening question about branching trees"
    title = auto_title(long)
    assert title.endswith("…") and len(title) <= 41 and long.startswith(title[:-1])
    assert auto_title("   ") is None


def test_ws_first_turn_titles_the_thread(tmp_path, monkeypatch):
    """Web chat threads used to stay untitled: the rename read dicts as objects."""
    import os
    from unittest.mock import patch

    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from app.core import database as db
    from app.llm import CallableModelFactory, use_model_factory
    from app.main import server

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "title.sqlite"))
    fake = CallableModelFactory(lambda m, _t: FakeListChatModel(responses=["ok"]))
    with (
        use_model_factory(fake),
        patch.dict(os.environ, {"OPENAI_API_KEY": "k"}),
        TestClient(server) as client,
        client.websocket_connect("/ws/thread_title_test") as ws,
    ):
        ws.send_json({"message": "How do branching trees work?", "model": "gpt-5.4", "parent_checkpoint_id": None})
        for _ in range(50):
            msg = ws.receive_json()
            if msg["type"] == "title_update":
                break
        assert msg == {"type": "title_update", "thread_id": "thread_title_test", "title": "How do branching trees work?"}
    assert db.get_thread_title("thread_title_test") == "How do branching trees work?"
