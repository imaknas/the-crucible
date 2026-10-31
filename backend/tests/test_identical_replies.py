"""Models that answer a turn with the same text are still separate replies.

The tree merged sibling checkpoints by text alone, so when two models both
answered "Red" one of them vanished from the tree (and from the compare cards
built from it after a reload), and its checkpoint id resolved to the other
model's node."""

import os
from unittest.mock import patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.core import database as db
from app.llm import CallableModelFactory, use_model_factory
from app.services import arena as arena_svc
from app.services import history
from tests.storage_helpers import point

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B, C = "gpt-5.4", "claude-sonnet-5", "gemini-3.1-pro-preview"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    point(monkeypatch, db_path=str(tmp_path / "identical.sqlite"))
    db.init_db()
    answers = {A: "Blue", B: "Red", C: "Red"}
    factory = CallableModelFactory(lambda model_id, _t: FakeListChatModel(responses=[answers[model_id]]))
    with use_model_factory(factory), patch.dict(os.environ, KEYS):
        yield


@pytest.mark.asyncio
async def test_identical_answers_are_separate_nodes():
    async with arena_svc.open_graph() as graph_app:
        result = await arena_svc.collect(
            arena_svc.run_arena(graph_app, "Name a primary colour.", "t-same", [A, B, C], {}, synthesizer=None)
        )
        tree = await history.thread_tree(graph_app, "t-same")

    replies = [n for n in tree["nodes"] if n["metadata"]["role"] == "ai"]
    by_model = {n["metadata"]["active_peer"]: n for n in replies}
    assert sorted(by_model) == sorted([A, B, C])
    assert by_model[B]["data"]["label"] == by_model[C]["data"]["label"] == "Red"
    # Each model's reply id (what stream_end reports) is its own node.
    for model in (A, B, C):
        assert by_model[model]["id"] == result["answers"][model]["checkpoint_id"]
    # The question is still one node, shared by all three replies.
    questions = [n for n in tree["nodes"] if n["metadata"]["role"] == "user"]
    assert len(questions) == 1
