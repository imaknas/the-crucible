"""Debate controls: inject, pause/resume, stop cancellation, timeout handling."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.services import debate as debate_svc
from app.services.convergence import _compute_sync
from app.services.debate import DebateControl, _build_round_prompts, run_debate

PARTICIPANTS = ["gpt-5.4", "claude-sonnet-5"]


def _session(max_rounds=2):
    return {
        "session_id": "debate-x",
        "parent_thread_id": "t",
        "participants": PARTICIPANTS,
        "thread_ids": {m: f"t::{m}" for m in PARTICIPANTS},
        "current_round": 0,
        "status": "running",
        "termination_policy": {"max_rounds": max_rounds, "convergence_threshold": None, "llm_judge": None, "mode": "all"},
        "auto_synthesize": False,
        "synthesizer_model": None,
    }


class FakeGraph:
    """Records every prompt it receives; optional per-call delay."""

    def __init__(self, delay=0.0, stall_after_draft=False):
        self.prompts: list[str] = []
        self.delay = delay
        self.stall_after_draft = stall_after_draft
        self.cancelled = 0

    async def astream_events(self, state, config, version="v2"):
        self.prompts.append(state["messages"][0][1])
        try:
            await asyncio.sleep(self.delay)
            chunk = MagicMock()
            chunk.content = "answer"
            yield {"event": "on_chat_model_stream", "metadata": {"langgraph_node": "draft"}, "data": {"chunk": chunk}}
            yield {"event": "on_chain_end", "name": "draft", "data": {}}
            if self.stall_after_draft:
                await asyncio.sleep(10)
            yield {"event": "on_chain_end", "name": "LangGraph", "data": {"output": {"messages": []}}}
        except asyncio.CancelledError:
            self.cancelled += 1
            raise

    async def aget_state_history(self, config, filter=None, limit=None):
        if False:
            yield None


async def _collect(gen, on_event=None):
    events = []
    async for e in gen:
        events.append(e)
        if on_event:
            await on_event(e)
    return events


class _PatchedDb:
    """get/update the session in memory; the parent thread already has a title."""

    def __init__(self, max_rounds):
        self._patches = [
            patch.object(debate_svc.db, "get_debate_session", return_value=_session(max_rounds)),
            patch.object(debate_svc.db, "update_debate_session"),
            patch.object(debate_svc.db, "get_thread_title", return_value="titled"),
        ]

    def __enter__(self):
        for p in self._patches:
            p.start()

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()


def _patched_db(max_rounds=2):
    return _PatchedDb(max_rounds)


def test_injected_message_reaches_every_prompt():
    prompts = _build_round_prompts(1, "Q", PARTICIPANTS, {m: "prev" for m in PARTICIPANTS}, injected=["consider cost"])
    assert all("consider cost" in p for p in prompts.values())
    assert "consider cost" not in _build_round_prompts(1, "Q", PARTICIPANTS, {m: "prev" for m in PARTICIPANTS})["gpt-5.4"]


@pytest.mark.asyncio
async def test_inject_during_round_is_used_in_next_round():
    graph = FakeGraph()
    control = DebateControl()

    async def on_event(e):
        # Round 0's prompts are already out once its models start streaming.
        if e["type"] == "stream_start" and e["round"] == 0 and not control.injected:
            control.inject("what about cost?")

    with _patched_db(max_rounds=2):
        await _collect(run_debate(graph, "debate-x", "Q", {}, {}, control=control), on_event)

    round0, round1 = graph.prompts[:2], graph.prompts[2:]
    assert not any("what about cost?" in p for p in round0)
    assert all("what about cost?" in p for p in round1)


@pytest.mark.asyncio
async def test_inject_after_final_round_is_reported_not_dropped():
    control = DebateControl()

    async def on_event(e):
        if e["type"] == "stream_start" and not control.injected:
            control.inject("too late")

    with _patched_db(max_rounds=1):
        events = await _collect(run_debate(FakeGraph(), "debate-x", "Q", {}, {}, control=control), on_event)
    assert any(e["type"] == "error" and "too late" in e["message"] for e in events)


@pytest.mark.asyncio
async def test_pause_holds_before_next_round_until_resumed():
    control = DebateControl()
    graph = FakeGraph()
    seen: list[str] = []

    async def on_event(e):
        seen.append(e.get("status") or e["type"])
        if e["type"] == "debate_round_start" and e["round"] == 0:
            control.pause()
        if e.get("status") == "paused":
            assert len(graph.prompts) == 2  # round 1 has not started
            asyncio.get_running_loop().call_later(0.01, control.resume)

    with _patched_db(max_rounds=2):
        await _collect(run_debate(graph, "debate-x", "Q", {}, {}, control=control), on_event)

    assert seen.index("paused") < seen.index("running") < len(seen)
    assert len(graph.prompts) == 4


@pytest.mark.asyncio
async def test_cancelling_debate_cancels_model_runs():
    graph = FakeGraph(delay=5)
    with _patched_db():
        task = asyncio.create_task(_collect(run_debate(graph, "debate-x", "Q", {}, {})))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert graph.cancelled == len(PARTICIPANTS)


@pytest.mark.asyncio
async def test_timeout_after_draft_keeps_the_answer(monkeypatch):
    monkeypatch.setattr(debate_svc, "MODEL_TIMEOUT_SECONDS", 0.1)
    with _patched_db(max_rounds=1):
        events = await _collect(run_debate(FakeGraph(stall_after_draft=True), "debate-x", "Q", {}, {}))
    ends = [e for e in events if e["type"] == "stream_end"]
    assert {e["model"] for e in ends} == set(PARTICIPANTS)
    assert all(e["content"] == "answer" for e in ends)
    assert not any(e["type"] == "error" for e in events)


def test_all_mode_not_converged_when_a_model_failed():
    embeddings = MagicMock()
    embeddings.embed_query.side_effect = lambda text: [1.0, 0.0]
    with patch("app.services.rag.get_embeddings", return_value=embeddings):
        score, converged = _compute_sync(
            {"a": "x", "b": "y"}, {"a": "x", "b": ""}, mode="all", threshold=0.9
        )
    assert not converged
