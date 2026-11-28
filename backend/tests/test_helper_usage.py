"""What the calls before a reply took (summary, document grading, recall).

Real LangGraph workflow, one turn that summarizes, grades a retrieved
document and recalls, each call reporting usage: every helper call is
counted once, kept on the reply, priced when read, and summed into the
turn's total.
"""

import os
from typing import List
from unittest.mock import patch

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import MemorySaver

import app.services.graph as graph_mod
from app.compaction import GuidedRecall, ThresholdPolicy, fixed_tokens
from app.llm import CallableModelFactory, use_model_factory
from app.services.chat import stream_turn
from app.services.metrics import HELPERS_KEY, turn_total, usage_summary
from app.services.recall import ModelRewriter
from app.services.runs import seed_thread
from app.utils.helpers import extract_text
from tests.storage_helpers import point

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
USAGE = {"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100}


class UsageModel(BaseChatModel):
    """Answers each kind of call in its own way; every call reports USAGE
    and the model that served it, as providers do."""

    model_id: str

    @property
    def _llm_type(self) -> str:
        return "usage"

    def _generate(self, messages: List[BaseMessage], stop=None, run_manager=None, **kw) -> ChatResult:
        prompt = extract_text(messages[-1].content)
        if "relevant" in prompt.lower() and "yes" in prompt.lower():
            reply = "yes"
        elif "Which topics" in prompt:
            reply = "harbor crane"
        elif "summar" in prompt.lower():
            reply = "Summary: notes on the harbor crane."
        else:
            reply = "The answer."
        message = AIMessage(content=reply, usage_metadata=USAGE, response_metadata={"model_name": self.model_id})
        return ChatResult(generations=[ChatGeneration(message=message)])


class Doc:
    page_content = "The crane runs at dawn."
    metadata = {"filename": "notes.txt"}


@pytest.fixture
def graph_app(tmp_path, monkeypatch):
    point(monkeypatch, db_path=str(tmp_path / "t.sqlite"))
    from app.core import database as db

    db.init_db()
    factory = CallableModelFactory(lambda model_id, _t: UsageModel(model_id=model_id))
    with use_model_factory(factory), patch.dict(os.environ, KEYS):
        yield graph_mod.workflow.compile(checkpointer=MemorySaver()), factory


@pytest.mark.asyncio
async def test_the_calls_before_a_reply_are_kept_with_it(graph_app):
    app, factory = graph_app
    history = []
    for i in range(6):
        history += [HumanMessage(content=f"Notes {i} on the harbor crane schedule. " * 20),
                    AIMessage(content=f"Thanks for notes {i}. " * 20, name="gpt-5.4")]
    parent = await seed_thread(app, "h", {"messages": history})
    configurable = {
        graph_mod.POLICY_CONFIG_KEY: ThresholdPolicy(fixed_tokens(300)),
        graph_mod.SUMMARIZER_CONFIG_KEY: "gpt-5.4",
        graph_mod.GRADER_CONFIG_KEY: "gpt-5.4",
        graph_mod.RECALL_CONFIG_KEY: GuidedRecall(ModelRewriter("gpt-5.4", factory)),
        "retriever": lambda query, thread: [Doc()],
    }
    end = None
    async for event in stream_turn(app, "h", parent, message="When does the harbor crane run?", model="gpt-5.4",
                                   toggles={"use_rag": True}, configurable=configurable):
        if event["type"] == "end":
            end = event

    assert end["retrieved"] == ["notes.txt"]  # searched on the turn a summary was written
    m = end["metrics"]
    # The reply's own numbers are the answering call alone ...
    assert (m["input_tokens"], m["output_tokens"]) == (1000, 100)
    # ... and the calls made for it, each once: the summary, the grading of
    # the one retrieved document and recall's rewrite.
    helpers = m["helpers"]
    assert helpers["calls"] == 3
    assert helpers["kinds"] == ["document grading", "recall", "summary"]
    assert (helpers["input_tokens"], helpers["output_tokens"]) == (3000, 300)
    assert helpers["cost_usd"] == pytest.approx(3 * m["cost_usd"]) and helpers["unpriced"] == 0

    # Kept on the reply as raw usage, so a reload prices it the same way.
    final = await app.aget_state({"configurable": {"thread_id": "h", "checkpoint_id": end["checkpoint_id"]}})
    reply = final.values["messages"][-1]
    assert [c["kind"] for c in reply.additional_kwargs[HELPERS_KEY]] == ["summary", "document grading", "recall"]

    total = turn_total([m])
    assert total["input_tokens"] == 4000 and total["cost_usd"] == pytest.approx(4 * m["cost_usd"])
    assert total["helpers"]["calls"] == 3


@pytest.mark.asyncio
async def test_a_plain_turn_has_no_helpers(graph_app):
    app, _ = graph_app
    parent = await seed_thread(app, "p", {"messages": []})
    end = None
    async for event in stream_turn(app, "p", parent, message="Hi", model="gpt-5.4"):
        if event["type"] == "end":
            end = event
    assert end["metrics"]["helpers"] is None
    assert turn_total([end["metrics"]])["helpers"] is None


def test_an_unpriced_helper_call_is_counted_not_free():
    calls = [{"model": "gpt-5.4", "kind": "summary", "usage": USAGE},
             {"model": "mystery-model", "kind": "recall", "usage": USAGE},
             {"model": None, "kind": "helper", "usage": USAGE}]
    s = usage_summary(calls, day="2026-11-29")
    assert s["calls"] == 3 and s["unpriced"] == 2 and s["input_tokens"] == 3000
    assert s["cost_usd"] == pytest.approx(usage_summary(calls[:1], day="2026-11-29")["cost_usd"])
    assert usage_summary([], day=None) is None


def test_describe_names_the_other_calls():
    from app.services.metrics import describe

    reply = {"ttft_ms": None, "total_ms": None, "input_tokens": 10, "output_tokens": 5, "reasoning_tokens": None,
             "cached_input_tokens": 0, "cost_usd": 0.01,
             "helpers": {"calls": 2, "kinds": ["recall", "summary"], "input_tokens": 4, "output_tokens": 2,
                         "reasoning_tokens": 0, "cached_input_tokens": 0, "cost_usd": 0.002, "unpriced": 0}}
    assert describe(reply).endswith("$0.0100 · + $0.0020 for 2 other calls (recall, summary)")
    assert describe(turn_total([reply])).endswith("$0.0120 · incl. $0.0020 for 2 other calls (recall, summary)")
