"""Per-answer metrics: time to first token, total time, tokens and cost.

Real LangGraph workflow with a scripted model that reports usage and a fake
clock, so the numbers are exact. The timing is stored on the reply, so the
same metrics come back from the tree and the path after a reload.
"""

import os
from typing import Any, Iterator, List, Optional
from unittest.mock import patch

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.checkpoint.memory import MemorySaver

import app.services.graph as graph_mod
from app.catalog.prices import ModelPrice, Price
from app.llm import CallableModelFactory, use_model_factory
from app.services.chat import stream_turn
from app.services.metrics import CLOCK_KEY, TIMING_KEY, describe, message_metrics, turn_total
from app.services.runs import resolve_fork_point
from app.services.tree import build_history_tree, format_messages
from tests.storage_helpers import point

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
USAGE = {
    "input_tokens": 1000,
    "output_tokens": 500,
    "total_tokens": 1500,
    "input_token_details": {"cache_read": 200},
    "output_token_details": {"reasoning": 120},
}


class FakeClock:
    """Advances only when told to: the model moves it as it streams."""

    def __init__(self):
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class TimedModel(BaseChatModel):
    """Streams an empty opening chunk, then two words, then usage; each step
    moves the clock, so the timer sees known gaps."""

    clock: Any
    usage: Optional[dict] = None

    @property
    def _llm_type(self) -> str:
        return "timed"

    def _generate(self, messages: List[BaseMessage], stop=None, run_manager=None, **kw) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Hello there", usage_metadata=self.usage))])

    def _stream(self, messages: List[BaseMessage], stop=None, run_manager=None, **kw) -> Iterator[ChatGenerationChunk]:
        # Anthropic-style opening event: no text yet, not a first token.
        self.clock.now += 0.5
        yield self._chunk("", run_manager)
        self.clock.now += 0.7
        yield self._chunk("Hello ", run_manager)
        self.clock.now += 2.0
        yield self._chunk("there", run_manager, usage=self.usage)
        self.clock.now += 0.3

    def _chunk(self, text, run_manager, usage=None):
        chunk = ChatGenerationChunk(message=AIMessageChunk(content=text, usage_metadata=usage))
        if run_manager:
            run_manager.on_llm_new_token(text, chunk=chunk)
        return chunk


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def graph_app(tmp_path, monkeypatch, clock):
    point(monkeypatch, db_path=str(tmp_path / "t.sqlite"))
    from app.core import database as db

    db.init_db()
    factory = CallableModelFactory(lambda model_id, _t: TimedModel(clock=clock, usage=USAGE))
    with use_model_factory(factory), patch.dict(os.environ, KEYS):
        yield graph_mod.workflow.compile(checkpointer=MemorySaver())


async def _turn(app, thread, parent, model, text, clock):
    tokens, end = [], None
    async for event in stream_turn(app, thread, parent, message=text, model=model, configurable={CLOCK_KEY: clock}):
        if event["type"] == "token":
            tokens.append(event["token"])
        elif event["type"] == "end":
            end = event
    return tokens, end


async def _states(app, thread):
    return [s async for s in app.aget_state_history({"configurable": {"thread_id": thread, "checkpoint_ns": ""}})]


@pytest.mark.asyncio
async def test_a_turn_reports_time_tokens_and_cost(graph_app, clock):
    root = await resolve_fork_point(graph_app, "m")
    tokens, end = await _turn(graph_app, "m", root, "gpt-5.4", "Q", clock)

    assert "".join(tokens) == "Hello there"  # the timer doesn't take the stream from clients
    m = end["metrics"]
    # First visible text 1.2 s after the call started (the empty chunk doesn't count); done at 3.5 s.
    assert m["ttft_ms"] == 1200
    assert m["total_ms"] == 3500
    assert (m["input_tokens"], m["output_tokens"], m["reasoning_tokens"], m["cached_input_tokens"]) == (1000, 500, 120, 200)
    # Priced from the list on the reply's day: gpt-5.4 is priced, so a cost exists.
    assert m["cost_usd"] is not None and m["cost_usd"] > 0


@pytest.mark.asyncio
async def test_metrics_survive_a_reload(graph_app, clock):
    root = await resolve_fork_point(graph_app, "r")
    _, end = await _turn(graph_app, "r", root, "claude-sonnet-5", "Q", clock)
    states = await _states(graph_app, "r")
    state_map = {s.config["configurable"]["checkpoint_id"]: s for s in states}

    # The path (what GET /history and POST /chat answer) ...
    path = format_messages(end["checkpoint_id"], state_map)
    reply = next(m for m in path if m["role"] == "assistant")
    assert reply["metrics"] == end["metrics"]
    assert next(m for m in path if m["role"] == "user")["metrics"] is None

    # ... and the tree node, which the compare cards read.
    active = next(s for s in states if s.config["configurable"]["checkpoint_id"] == end["checkpoint_id"])
    with patch("app.services.tree.load_node_positions", return_value={}):
        tree = build_history_tree("r", states, active)
    node = next(n for n in tree["nodes"] if n["id"] == end["checkpoint_id"])
    assert node["metadata"]["metrics"] == end["metrics"]
    assert all(n["metadata"]["metrics"] is None for n in tree["nodes"] if n["metadata"]["role"] != "ai")


@pytest.mark.asyncio
async def test_a_reply_without_usage_still_has_its_timing(tmp_path, monkeypatch):
    point(monkeypatch, db_path=str(tmp_path / "u.sqlite"))
    from app.core import database as db

    db.init_db()
    factory = CallableModelFactory(lambda model_id, _t: FakeListChatModel(responses=["plain"]))
    with use_model_factory(factory), patch.dict(os.environ, KEYS):
        app = graph_mod.workflow.compile(checkpointer=MemorySaver())
        root = await resolve_fork_point(app, "u")
        _, end = await _turn(app, "u", root, "gpt-5.4", "Q", FakeClock())
    m = end["metrics"]
    assert m["ttft_ms"] == 0 and m["total_ms"] == 0
    assert m["input_tokens"] is None and m["cost_usd"] is None


def _reply(model="gpt-5.4", usage=USAGE, timing=None):
    msg = AIMessage(content="x", name=model, usage_metadata=usage)
    if timing is not None:
        msg.additional_kwargs[TIMING_KEY] = timing
    return msg


def test_cost_uses_the_price_of_the_reply_day():
    prices = {
        "gpt-5.4": ModelPrice(
            current=Price(input=2.0, output=10.0, cached_input=0.5),
            source="test",
            until="2026-06-30",
            after=Price(input=4.0, output=20.0, cached_input=1.0),
        )
    }
    before = message_metrics(_reply(), day="2026-06-30", prices=prices)
    after = message_metrics(_reply(), day="2026-07-01", prices=prices)
    # 800 uncached in, 200 cached in, 500 out (reasoning is part of output, never added).
    assert before["cost_usd"] == pytest.approx((800 * 2.0 + 200 * 0.5 + 500 * 10.0) / 1e6)
    assert after["cost_usd"] == pytest.approx(2 * before["cost_usd"])


def test_an_unpriced_model_has_no_cost_rather_than_a_guess():
    m = message_metrics(_reply(model="mystery-model"), day="2026-11-02", prices={})
    assert m["input_tokens"] == 1000 and m["cost_usd"] is None
    assert describe(m).endswith("price unknown")


def test_old_replies_and_non_replies_have_no_metrics():
    assert message_metrics(AIMessage(content="old"), day="2026-01-01") is None
    assert message_metrics(_reply(usage=None, timing=None), day=None) is None
    from langchain_core.messages import HumanMessage

    assert message_metrics(HumanMessage(content="q"), day=None) is None


def test_describe_and_turn_total():
    one = {"ttft_ms": 1200, "total_ms": 8400, "input_tokens": 1234, "output_tokens": 567,
           "reasoning_tokens": 120, "cached_input_tokens": 0, "cost_usd": 0.0123}
    assert describe(one) == "1.2 s to first token · 8.4 s · 1,234 in / 567 out (120 reasoning) · $0.0123"
    two = {**one, "ttft_ms": 300, "total_ms": 9100, "reasoning_tokens": None, "cost_usd": None}
    total = turn_total([one, two, None])
    assert total["answers"] == 2
    assert total["total_ms"] == 9100  # the slowest
    assert total["input_tokens"] == 2468 and total["reasoning_tokens"] == 120
    # A total with an unpriced answer never reads as complete.
    assert total["cost_usd"] == 0.0123 and total["unpriced"] == 1
    assert describe(total).endswith("$0.0123 + 1 price unknown")
    assert turn_total([None]) is None
    assert describe({**one, "cost_usd": 0.00001}).endswith("<$0.0001")


def test_a_routed_reply_is_priced_as_the_model_that_answered():
    """Asked for gemini-3.5-flash, Google answers with gemini-3.6-flash and
    reports it; the reply costs what 3.6 costs."""
    from langchain_core.messages import AIMessage

    from app.services.metrics import message_metrics

    prices = {
        "gemini-3.5-flash": ModelPrice(current=Price(input=1.5, output=9.0, cached_input=0.15), source="test"),
        "gemini-3.6-flash": ModelPrice(current=Price(input=0.75, output=3.75, cached_input=0.075), source="test"),
    }
    usage = {"input_tokens": 1_000_000, "output_tokens": 0, "total_tokens": 1_000_000}
    routed = AIMessage(content="ok", name="gemini-3.5-flash", usage_metadata=usage,
                       response_metadata={"model_name": "gemini-3.6-flash"})
    assert message_metrics(routed, day="2026-11-10", prices=prices)["cost_usd"] == 0.75
    # A reported name the price list doesn't know leaves the requested model's price.
    unknown = AIMessage(content="ok", name="gemini-3.5-flash", usage_metadata=usage,
                        response_metadata={"model_name": "something-new"})
    assert message_metrics(unknown, day="2026-11-10", prices=prices)["cost_usd"] == 1.5
