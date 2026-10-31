"""A turn that never got a reply is not where the next turn continues.

A closed tab, a dropped socket or a failing model leaves the thread head on
the person's message. The next turn (and the composer after a reload) used
to continue from it, so two messages from the person reached the model as
one. Real graph and checkpointer, fake LLM.
"""

import os
from unittest.mock import patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.api.history import get_history
from app.core import database as db
from app.llm import CallableModelFactory, use_model_factory
from app.services.arena import open_graph, turn_start
from app.services.chat import stream_turn
from app.services.runs import resolve_fork_point

KEYS = {"OPENAI_API_KEY": "test-key"}
MODEL = "gpt-5.4"
SEEN: list[str] = []


class _Model(FakeListChatModel):
    def _stream(self, messages, *args, **kwargs):
        text = "\n".join(str(m.content) for m in messages)
        SEEN.append(text)
        if "[[fail]]" in text.split("ABANDONED-MARK")[-1]:
            raise RuntimeError("model failed")
        yield from super()._stream(messages, *args, **kwargs)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    SEEN.clear()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "abandoned.sqlite"))
    factory = CallableModelFactory(lambda _m, _t: _Model(responses=["an answer"]))
    with use_model_factory(factory), patch.dict(os.environ, KEYS):
        yield


async def _turn(graph_app, thread_id, text):
    # Where the app forks a turn nobody pointed anywhere.
    parent = (await turn_start(graph_app, thread_id)).default
    end = None
    async for event in stream_turn(graph_app, thread_id, parent, message=text, model=MODEL):
        if event["type"] == "end":
            end = event
    return parent, end


@pytest.mark.asyncio
async def test_the_next_turn_forks_from_the_last_answer_not_the_abandoned_prompt():
    async with open_graph() as graph_app:
        _, first = await _turn(graph_app, "t", "First question")
        with pytest.raises(RuntimeError):
            await _turn(graph_app, "t", "ABANDONED-MARK [[fail]]")
        parent, _ = await _turn(graph_app, "t", "Second question")

    assert parent == first["checkpoint_id"]
    assert "ABANDONED-MARK" not in SEEN[-1]
    assert "First question" in SEEN[-1] and "Second question" in SEEN[-1]


@pytest.mark.asyncio
async def test_history_points_the_composer_at_the_last_answer():
    async with open_graph() as graph_app:
        await _turn(graph_app, "t2", "First question")
        with patch("app.services.tree.load_node_positions", return_value={}):
            # The tree's node for that answer (a turn's checkpoints collapse into one).
            answered = (await get_history("t2", graph_app=graph_app))["current_checkpoint"]
            with pytest.raises(RuntimeError):
                await _turn(graph_app, "t2", "ABANDONED-MARK [[fail]]")
            history = await get_history("t2", graph_app=graph_app)

    assert history["current_checkpoint"] == answered
    assert [m["content"] for m in history["messages"]] == ["First question", "an answer"]
    # The abandoned prompt is still in the tree, as a branch of its own.
    assert any("ABANDONED-MARK" in n["metadata"].get("preview", "") for n in history["nodes"])


@pytest.mark.asyncio
async def test_a_thread_whose_only_turn_was_abandoned_restarts_from_its_root():
    async with open_graph() as graph_app:
        with pytest.raises(RuntimeError):
            root, _ = await _turn(graph_app, "t3", "ABANDONED-MARK [[fail]]")
        root = await resolve_fork_point(graph_app, "t3")
        parent, _ = await _turn(graph_app, "t3", "Fresh start")
    assert parent == root
    assert "ABANDONED-MARK" not in SEEN[-1]
