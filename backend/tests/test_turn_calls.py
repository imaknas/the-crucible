"""What one chat turn costs in model calls, through the real graph."""

import os
from unittest.mock import patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.checkpoint.memory import MemorySaver

import app.services.graph as graph_mod
from app.llm import CallableModelFactory, use_model_factory
from app.services.runs import final_state_of_run, tag_run, thread_config

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}


@pytest.mark.asyncio
async def test_a_turn_calls_the_answering_model_once():
    calls = []

    def build(model_id, toggles):
        calls.append((model_id, dict(toggles or {})))
        return FakeListChatModel(responses=[f"reply from {model_id}"])

    with use_model_factory(CallableModelFactory(build)), patch.dict(os.environ, KEYS):
        app = graph_mod.workflow.compile(checkpointer=MemorySaver())
        config = thread_config("t-cost")
        run_id = tag_run(config)
        await app.ainvoke(
            {
                "active_peer": "gpt-5.4",
                "messages": [("user", "A question long enough that the old thesis update would run.")],
                "toggles": {"use_web_search": True},
            },
            config,
        )
        final = await final_state_of_run(app, "t-cost", run_id)

    assert calls == [("gpt-5.4", {"use_web_search": True})]
    assert final.values["messages"][-1].content == "reply from gpt-5.4"
    assert not final.values.get("current_thesis")
