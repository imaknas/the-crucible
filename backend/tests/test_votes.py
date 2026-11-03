"""Votes on a turn's answers: blind letters, the stored vote, and pairwise
win rates by task type."""

import os
from unittest.mock import patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.core import database as db
from app.llm import CallableModelFactory, use_model_factory
from app.services import arena, votes
from tests.storage_helpers import point

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B, C = "gpt-5.4", "claude-sonnet-5", "gemini-3.1-pro-preview"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    point(monkeypatch, db_path=str(tmp_path / "votes.sqlite"))
    db.init_db()
    with use_model_factory(CallableModelFactory(lambda m, _t: FakeListChatModel(responses=[f"{m} answers"]))), \
            patch.dict(os.environ, KEYS):
        yield


def test_the_hash_matches_the_frontend_and_letters_are_fixed_per_turn():
    # The same vectors are in frontend/src/lib/blind.test.ts.
    assert votes._fnv1a("") == 0x811C9DC5
    assert votes._fnv1a("a") == 0xE40C292C
    assert votes._fnv1a("turn-1:cp-x") == votes._fnv1a("turn-1:cp-x")
    ids = ["cp-1", "cp-2", "cp-3"]
    letters = votes.blind_letters("turn-1", ids)
    assert sorted(letters.values()) == ["A", "B", "C"]
    assert votes.blind_letters("turn-1", list(reversed(ids))) == letters  # not the order answered


def _vote(outcome, answers, winner=None, task="general"):
    return {"outcome": outcome, "winner_checkpoint_id": winner, "task_type": task,
            "answers": [{"checkpoint_id": f"cp-{m}", "model": m} for m in answers]}


def test_win_rates_are_pairwise_and_all_bad_is_not_a_loss():
    rates = {r["model"]: r for r in votes.win_rates([
        _vote("best", [A, B, C], winner=f"cp-{A}"),    # A: 2 wins; B, C: 1 loss each
        _vote("tie", [A, B]),                           # A, B: 1 tie each
        _vote("all_bad", [B, C]),                       # counted apart
        _vote("best", [B, C], winner=f"cp-{B}", task="coding"),
    ])}
    assert (rates[A]["wins"], rates[A]["losses"], rates[A]["ties"], rates[A]["win_rate"]) == (2, 0, 1, 0.833)
    assert (rates[B]["wins"], rates[B]["losses"], rates[B]["ties"], rates[B]["all_bad"]) == (1, 1, 1, 1)
    assert rates[C]["win_rate"] == 0.0 and rates[C]["all_bad"] == 1
    coding = votes.win_rates([_vote("best", [B, C], winner=f"cp-{B}", task="coding"),
                              _vote("best", [A, C], winner=f"cp-{A}")], task_type="coding")
    assert [r["model"] for r in coding] == [B, C]
    assert votes.win_rates([_vote("all_bad", [A, B])])[0]["win_rate"] is None


@pytest.mark.asyncio
async def test_a_vote_is_stored_per_turn_replaced_and_deleted_with_its_thread():
    async with arena.open_graph() as graph_app:
        result = await arena.collect(arena.run_arena(graph_app, "Which?", "t-v", [A, B, C], {}, synthesizer=None))
        b_reply = result["answers"][B]["checkpoint_id"]
        turn = await votes.turn_answers(graph_app, "t-v", b_reply)
        assert [a["model"] for a in turn["answers"]] and {a["checkpoint_id"] for a in turn["answers"]} == {
            result["answers"][m]["checkpoint_id"] for m in (A, B, C)}

        # Blind: the person names the letter they saw.
        letter = votes.blind_letters(turn["turn_id"], [b_reply, *[a["checkpoint_id"] for a in turn["answers"]]])[b_reply]
        vote = await votes.vote_turn(graph_app, "t-v", turn["turn_id"], "best", best=letter, task_type="coding",
                                     reason="  shorter  and right ", blind=True)
        assert vote["winner_checkpoint_id"] == b_reply and vote["reason"] == "shorter and right" and vote["blind"]
        assert {a["letter"] for a in vote["answers"]} == {"A", "B", "C"}

        again = await votes.vote_turn(graph_app, "t-v", b_reply, "tie")
        assert again["outcome"] == "tie" and again["winner_checkpoint_id"] is None
        assert len(votes.votes_of("t-v")) == 1
        assert votes.vote_stats()["models"][0]["ties"] == 2

        for bad, match in [
            (dict(outcome="won"), "outcome"),
            (dict(outcome="best"), "Name the best"),
            (dict(outcome="best", best="Z"), "not one of"),
            (dict(outcome="tie", best=b_reply), "names no best"),
            (dict(outcome="tie", task_type="poetry"), "task type"),
        ]:
            with pytest.raises(ValueError, match=match):
                await votes.vote_turn(graph_app, "t-v", b_reply, **bad)
        with pytest.raises(ValueError, match="not found"):
            await votes.vote_turn(graph_app, "t-v", "no-such-turn", "tie")

        solo = await arena.collect(arena.run_arena(graph_app, "Alone?", "t-solo", [A], {}, synthesizer=None))
        with pytest.raises(ValueError, match="at least two answers"):
            await votes.vote_turn(graph_app, "t-solo", solo["answers"][A]["checkpoint_id"], "tie")

    db.delete_thread_data("t-v")
    assert votes.votes_of("t-v") == []
