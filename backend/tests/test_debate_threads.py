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
from app.api.history import get_history
from app.services.arena import open_graph
from app.services.runs import final_state_of_run, tag_run, thread_config
from app.utils.helpers import extract_text

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
    """The draft calls that answered `question`: the ones whose latest
    message asks it (no other call in these debates does)."""
    return [m for m in SEEN.get(model_id, []) if question in str(m[-1])]


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


# ─── Starting from a checkpoint of the parent conversation ───────


async def _chat_turn(graph_app, thread_id: str, text: str) -> str:
    """One chat turn on the parent thread; returns the checkpoint it produced."""
    config = thread_config(thread_id)
    run_id = tag_run(config)
    await graph_app.ainvoke(
        {"active_peer": A, "messages": [("user", text)], "toggles": {}, "documents": {}}, config
    )
    return (await final_state_of_run(graph_app, thread_id, run_id)).config["configurable"]["checkpoint_id"]


@pytest.mark.asyncio
async def test_a_debate_from_a_checkpoint_sees_the_conversation_up_to_it():
    question = "Debate: was that answer right?"
    async with open_graph() as graph_app:
        fork = await _chat_turn(graph_app, "t-conv", "Earlier question about boiling water")
        await _chat_turn(graph_app, "t-conv", "Later question after the fork")
        SEEN.clear()
        session = debate_svc.create_session("t-conv", [A, B], {**POLICY, "max_rounds": 2})
        events = [
            e async for e in debate_svc.run_debate(
                graph_app, session["session_id"], question, {}, {}, parent_checkpoint_id=fork
            )
        ]
        assert events[-1]["status"] == "completed", events
        tree = await debate_api.get_debate_tree(session["session_id"], graph_app=graph_app)
        recovered = await debate_svc._original_question(graph_app, session)
        history = await get_history(session["thread_ids"][B], graph_app=graph_app)

    for model in (A, B):
        # The round-1 prompt restates the question, so both drafts match it.
        round0, round1 = _draft_inputs(model, question)
        text = " ".join(str(c) for c in round0)
        # The conversation up to the fork, then the debate question.
        assert "Earlier question about boiling water" in text
        assert f"reply from {A}" in text
        assert "Later question after the fork" not in text
        assert text.index("Earlier question about boiling water") < text.index(question)
        # Later rounds keep the conversation too.
        assert "Other models' previous responses" in str(round1[-1])
        assert "Earlier question about boiling water" in " ".join(str(c) for c in round1)

    # The copied conversation is context, not a round: lanes hold rounds 0 and
    # 1, and the shared prompt node is the debate question.
    lanes = [n for n in tree["nodes"] if n["metadata"].get("role") == "ai"]
    assert sorted((n["metadata"]["active_peer"], n["metadata"]["round_num"]) for n in lanes) == sorted(
        [(A, 0), (A, 1), (B, 0), (B, 1)]
    )
    assert next(n for n in tree["nodes"] if n["id"] == "debate::prompt")["metadata"]["preview"] == question
    assert recovered == question
    # The restored transcript reads a sub-thread's history: it starts with the
    # debate question; the seeded conversation is not shown as its messages.
    contents = [m["content"] for m in history["messages"]]
    assert contents[0] == question
    assert "Earlier question about boiling water" not in contents
    assert f"reply from {A}" not in contents


@pytest.mark.asyncio
async def test_a_debate_without_a_checkpoint_starts_empty():
    question = "Fresh question?"
    async with open_graph() as graph_app:
        await _chat_turn(graph_app, "t-conv2", "Something said before")
        SEEN.clear()
        await _debate(graph_app, "t-conv2", question)

    for model in (A, B):
        (round0,) = _draft_inputs(model, question)
        assert "Something said before" not in " ".join(str(c) for c in round0)


@pytest.mark.asyncio
async def test_seeding_is_skipped_for_a_sub_thread_that_already_has_history():
    async with open_graph() as graph_app:
        fork = await _chat_turn(graph_app, "t-conv3", "Context message")
        session = debate_svc.create_session("t-conv3", [A, B], dict(POLICY))
        tid = session["thread_ids"][A]
        assert await debate_svc.seed_from_parent(graph_app, "t-conv3", fork, [tid]) == 2
        before = len(db.get_thread_checkpoint_graph(tid))
        await debate_svc.seed_from_parent(graph_app, "t-conv3", fork, [tid])
        assert len(db.get_thread_checkpoint_graph(tid)) == before
        # A checkpoint that isn't on the parent thread seeds nothing.
        assert await debate_svc.seed_from_parent(graph_app, "t-conv3", "no-such-checkpoint", [session["thread_ids"][B]]) == 0


@pytest.mark.asyncio
async def test_a_participant_that_never_replied_has_no_latest_response():
    """Its seeded sub-thread ends on the parent's answer; synthesis must not
    attribute that answer to it."""
    async with open_graph() as graph_app:
        fork = await _chat_turn(graph_app, "t-conv4", "Context message")
        session = debate_svc.create_session("t-conv4", [A, B], dict(POLICY))
        await debate_svc.seed_from_parent(graph_app, "t-conv4", fork, list(session["thread_ids"].values()))
        assert await debate_svc.debate_rounds(graph_app, session) == {}
        assert await debate_svc._original_question(graph_app, session) == ""


# ─── Anonymous peers, against the real graph ─────────────────────


def _neutral(model_id, _toggles):
    # A reply that doesn't name its author, so any model id a draft sees
    # came from the debate's own prompts.
    return _Recorder(responses=["My position is yes."], model_id=model_id)


@pytest.mark.asyncio
async def test_an_anonymous_debate_never_shows_a_model_id_to_a_debater():
    question = "Is it yes?"
    with use_model_factory(CallableModelFactory(_neutral)):
        async with open_graph() as graph_app:
            session = debate_svc.create_session("t-anon", [A, B], {**POLICY, "max_rounds": 2})
            events = [e async for e in debate_svc.run_debate(graph_app, session["session_id"], question, {}, {})]
    assert events[-1]["status"] == "completed", events

    peers = debate_svc.session_peers(session)
    for model in (A, B):
        round0, round1 = _draft_inputs(model, question)
        seen = " ".join(str(c) for c in round0 + round1)
        assert A not in seen and B not in seen
        other = B if model == A else A
        assert f"You are {peers.label(model)}." in str(round1[-1])
        assert f"[{peers.label(other)}]:" in str(round1[-1])


@pytest.mark.asyncio
async def test_the_argument_map_reads_every_round_under_participant_labels():
    question = "Is it yes?"
    with use_model_factory(CallableModelFactory(_neutral)):
        async with open_graph() as graph_app:
            session = debate_svc.create_session(
                "t-map", [A, B], {**POLICY, "max_rounds": 2}, auto_synthesize=True, synthesizer_model=A
            )
            events = [e async for e in debate_svc.run_debate(graph_app, session["session_id"], question, {}, {})]
    assert any(e["type"] == "debate_synthesis_end" for e in events), events

    peers = debate_svc.session_peers(session)
    # The synthesizer's draft is the first call whose request is the map
    # (the graph's thesis update afterwards may quote it).
    synthesis = next(m for m in SEEN[A] if "Write an argument map" in str(m[-1]))
    prompt = extract_text(synthesis[-1])
    assert A not in prompt and B not in prompt
    for model in (A, B):
        assert (
            f"[{peers.label(model)}]:\nRound 1 (independent answer):\nMy position is yes."
            "\n\nRound 2:\nMy position is yes."
        ) in prompt
