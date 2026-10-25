"""Debate sub-threads against the real graph and a real SQLite checkpointer.

Only the LLM is faked; it records every message list it is given, so these
tests assert on what a model was actually shown.
"""

import os
from unittest.mock import patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.api import debate as debate_api
from app.core import database as db
from app.llm import CallableModelFactory, use_model_factory
from app.services import debate as debate_svc
from app.services.arena import open_graph

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B = "gpt-5.4", "claude-sonnet-5"
POLICY = {"max_rounds": 1, "convergence_threshold": None, "llm_judge": None, "mode": "all"}

# model id -> every message list that model received
SEEN: dict[str, list[list]] = {}


class _Recorder(FakeListChatModel):
    model_id: str = ""

    def _record(self, messages):
        SEEN.setdefault(self.model_id, []).append([m.content for m in messages])

    def _call(self, messages, *args, **kwargs):
        self._record(messages)
        return super()._call(messages, *args, **kwargs)

    def _stream(self, messages, *args, **kwargs):
        self._record(messages)
        yield from super()._stream(messages, *args, **kwargs)


def _model(model_id, _toggles):
    return _Recorder(responses=[f"reply from {model_id}"], model_id=model_id)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    SEEN.clear()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "debate.sqlite"))
    with use_model_factory(CallableModelFactory(_model)), patch.dict(os.environ, KEYS):
        yield


def _draft_inputs(model_id: str, question: str) -> list[list[str]]:
    """The draft calls that answered `question`. The graph's bookkeeping calls
    (thesis update, judge) send a single message; a draft sends the system
    prompt and the history."""
    return [m for m in SEEN.get(model_id, []) if len(m) > 1 and question in str(m[-1])]


async def _debate(graph_app, thread_id: str, question: str, **kwargs) -> dict:
    session = debate_svc.create_session(thread_id, [A, B], dict(POLICY))
    events = [e async for e in debate_svc.run_debate(graph_app, session["session_id"], question, {}, {}, **kwargs)]
    assert events[-1]["status"] == "completed", events
    return session


# ─── Session scoping ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_two_debates_on_one_thread_do_not_share_history():
    async with open_graph() as graph_app:
        first = await _debate(graph_app, "t-shared", "Question one?")
        second = await _debate(graph_app, "t-shared", "Question two?")

    assert not set(first["thread_ids"].values()) & set(second["thread_ids"].values())
    for model in (A, B):
        (shown,) = _draft_inputs(model, "Question two?")
        assert not any("Question one?" in str(c) for c in shown), shown


@pytest.mark.asyncio
async def test_a_debate_tree_draws_only_its_own_rounds():
    async with open_graph() as graph_app:
        await _debate(graph_app, "t-shared", "Question one?")
        second = await _debate(graph_app, "t-shared", "Question two?")
        tree = await debate_api.get_debate_tree(second["session_id"], graph_app=graph_app)

    lanes = [n for n in tree["nodes"] if n["metadata"].get("role") == "ai"]
    assert sorted(n["metadata"]["active_peer"] for n in lanes) == sorted([A, B])
    assert all(n["metadata"]["round_num"] == 0 for n in lanes)
    prompt = next(n for n in tree["nodes"] if n["id"] == "debate::prompt")
    assert prompt["metadata"]["preview"] == "Question two?"


@pytest.mark.asyncio
async def test_deleting_one_debate_keeps_the_other_and_the_parent():
    async with open_graph() as graph_app:
        first = await _debate(graph_app, "t-shared", "Question one?")
        second = await _debate(graph_app, "t-shared", "Question two?")

    db.delete_debate_session(first["session_id"])
    for tid in first["thread_ids"].values():
        assert not db.get_thread_checkpoint_graph(tid)
    for model in (A, B):
        assert db.get_thread_checkpoint_graph(second["thread_ids"][model])
    assert db.get_debate_session(second["session_id"]) is not None


@pytest.mark.asyncio
async def test_synthesis_goes_to_the_session_s_own_stored_thread():
    async with open_graph() as graph_app:
        session = await _debate(graph_app, "t-syn", "Question?")
        events = [
            e async for e in debate_svc.synthesize_session(graph_app, session["session_id"], "Question?", synthesizer=A)
        ]
    end = next(e for e in events if e["type"] == "debate_synthesis_end")
    assert end["synthesis_thread_id"] == session["thread_ids"]["synthesis"]
    assert db.get_thread_checkpoint_graph(session["thread_ids"]["synthesis"])
    assert not db.get_thread_checkpoint_graph("t-syn::synthesis")
