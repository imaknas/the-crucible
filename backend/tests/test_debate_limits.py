"""What a debate session may ask for: participants, rounds, and the models it calls.

The API has no authentication, so these bounds are what stops one request
from running an unbounded number of paid model calls.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core import database as db
from app.services import debate as debate_svc
from app.services.debate import MAX_ROUNDS, _stream_round, check_session_config
from types import SimpleNamespace

from langchain_core.messages import AIMessage

from app.services.runs import SEED_KEY
from tests.storage_helpers import point

A, B = "gpt-5.4", "claude-sonnet-5"


def _policy(**kw):
    return {"max_rounds": 3, "convergence_threshold": None, "llm_judge": None, "mode": "all", **kw}


# ─── check_session_config ────────────────────────────────────────


def test_a_valid_config_passes():
    check_session_config([A, B], _policy(llm_judge=A, max_rounds=MAX_ROUNDS), synthesizer_model=B)


@pytest.mark.parametrize("rounds", [0, -1, MAX_ROUNDS + 1, 1000])
def test_rounds_outside_the_bounds_are_refused(rounds):
    with pytest.raises(ValueError, match="max_rounds"):
        check_session_config([A, B], _policy(max_rounds=rounds))


def test_duplicate_participants_are_refused():
    with pytest.raises(ValueError, match="only once"):
        check_session_config([A, A, B], _policy())


def test_two_distinct_participants_are_required():
    with pytest.raises(ValueError, match="at least 2"):
        check_session_config([A], _policy())


def test_an_unknown_synthesizer_is_refused():
    with pytest.raises(ValueError, match="no-such-model"):
        check_session_config([A, B], _policy(), synthesizer_model="no-such-model")


def test_an_unknown_judge_is_refused():
    with pytest.raises(ValueError, match="no-such-judge"):
        check_session_config([A, B], _policy(llm_judge="no-such-judge"))


def test_an_unknown_mode_is_refused():
    with pytest.raises(ValueError, match="mode"):
        check_session_config([A, B], _policy(mode="most"))


def test_the_registry_is_injectable():
    check_session_config(["x", "y"], _policy(), known_models={"x", "y"})
    with pytest.raises(ValueError, match="Unknown"):
        check_session_config([A, B], _policy(), known_models={"x", "y"})


# ─── REST ────────────────────────────────────────────────────────


@pytest.fixture
def client(tmp_path, monkeypatch):
    point(monkeypatch, db_path=str(tmp_path / "limits.sqlite"))
    from app.main import server as app

    with TestClient(app) as c:
        yield c


def _create(client, **overrides):
    body = {
        "parent_thread_id": "t-limits",
        "participants": [A, B],
        "termination_policy": _policy(),
        **overrides,
    }
    return client.post("/debate/sessions", json=body)


def test_rest_creates_a_valid_session(client):
    res = _create(client)
    assert res.status_code == 200
    stored = db.get_debate_session(res.json()["session_id"])
    assert stored is not None
    # Peers are anonymous unless the request asks for names.
    assert stored["peer_labels"] == "anonymous"
    named = _create(client, peer_labels="named")
    assert db.get_debate_session(named.json()["session_id"])["peer_labels"] == "named"


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"termination_policy": _policy(max_rounds=MAX_ROUNDS + 1)}, "max_rounds"),
        ({"termination_policy": _policy(max_rounds=0)}, "max_rounds"),
        ({"participants": [A, A]}, "only once"),
        ({"participants": [A, A, B]}, "only once"),
        ({"participants": [A]}, "at least 2"),
        ({"participants": [A, "nope"]}, "nope"),
        ({"synthesizer_model": "nope-synth"}, "nope-synth"),
        ({"termination_policy": _policy(llm_judge="nope-judge")}, "nope-judge"),
        ({"peer_labels": "pseudonymous"}, "peer_labels"),
    ],
)
def test_rest_refuses_what_the_service_refuses(client, overrides, message):
    res = _create(client, **overrides)
    assert res.status_code == 400
    assert message in res.json()["detail"]
    assert db.list_debate_sessions("t-limits") == []


# ─── Running a stored session ────────────────────────────────────


class _OneReply:
    """A graph stand-in: every model answers "ok" at once."""

    async def astream_events(self, state, config, version="v2", **_kwargs):
        yield {"event": "on_chain_end", "name": "draft", "data": {}}
        yield {"event": "on_chain_end", "name": "LangGraph", "data": {"output": {"messages": []}}}

    async def aget_state(self, config):
        return SimpleNamespace(values={}, created_at="t0", config=config, parent_config=None, metadata={}, next=())

    async def aget_state_history(self, config, filter=None, limit=None):
        if filter and SEED_KEY in filter:
            return
        yield SimpleNamespace(
            values={"messages": [AIMessage(content="ok")]},
            config={"configurable": {**config["configurable"], "checkpoint_id": "cp-final"}},
            parent_config=None, metadata={}, next=(), created_at="t1",
        )


@pytest.mark.asyncio
async def test_a_round_with_a_repeated_participant_still_ends():
    """Sessions stored before duplicates were refused can list a model twice;
    the round used to wait forever for a second "done" from that model."""
    events = []

    async def run():
        async for e in _stream_round(
            graph_app=_OneReply(),
            round_num=0,
            session_id="s",
            participants=[A, A, B],
            thread_ids={A: "t::a", B: "t::b"},
            model_prompts={A: "q", B: "q"},
            toggles={},
            curr_round_responses={},
        ):
            events.append(e)

    await asyncio.wait_for(run(), timeout=5)
    assert sorted(e["model"] for e in events if e["type"] == "stream_start") == sorted([A, B])


@pytest.mark.asyncio
async def test_a_stored_round_count_above_the_limit_is_capped(monkeypatch):
    session = {
        "session_id": "d-old",
        "parent_thread_id": "t",
        "participants": [A, B],
        "thread_ids": {A: "t::a", B: "t::b"},
        "termination_policy": _policy(max_rounds=MAX_ROUNDS + 40),
        "auto_synthesize": False,
        "synthesizer_model": None,
    }
    monkeypatch.setattr(debate_svc.db, "get_debate_session", lambda _sid: session)
    monkeypatch.setattr(debate_svc.db, "update_debate_session", lambda *a, **k: None)
    monkeypatch.setattr(debate_svc.db, "get_thread_title", lambda _t: "titled")
    monkeypatch.setattr(debate_svc.db, "claim_debate_session", lambda *_a: True)
    monkeypatch.setattr(debate_svc.db, "append_debate_entry", lambda *_a: None)
    monkeypatch.setattr(debate_svc.db, "record_round_score", lambda *_a: None)

    rounds = [
        e["round"]
        async for e in debate_svc.run_debate(_OneReply(), "d-old", "Q", {}, {})
        if e["type"] == "debate_round_start"
    ]
    assert rounds == list(range(MAX_ROUNDS))
