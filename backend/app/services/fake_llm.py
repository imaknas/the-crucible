"""A scripted chat model for end-to-end tests.

Enabled only when CRUCIBLE_FAKE_LLM is set (the Playwright config does this),
in which case get_model() returns it for every registered model. It streams a
deterministic reply word by word, so the UI goes through the same
stream_start / stream_token / stream_end path as with a real provider, without
network access or cost.

Test hooks, written into the prompt:
  [[fail:<model_id>]]  that model raises instead of answering
  [[slow]]             ten times the per-token delay, to hold a stream open

CRUCIBLE_FAKE_LLM_DELAY sets the per-token delay in seconds (default 0.04).
"""

import hashlib
import os
import time
from typing import Any, Iterator, List, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


def enabled() -> bool:
    return os.getenv("CRUCIBLE_FAKE_LLM", "").lower() in ("1", "true", "yes")


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, list):
        return " ".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    return str(content)


class ScriptedChatModel(BaseChatModel):
    model_id: str
    delay: float = 0.04

    @property
    def _llm_type(self) -> str:
        return "crucible-scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _prompt(self, messages: List[BaseMessage]) -> str:
        humans = [m for m in messages if m.type == "human"]
        return _text(humans[-1]) if humans else ""

    def _reply(self, messages: List[BaseMessage]) -> str:
        prompt = self._prompt(messages)
        if f"[[fail:{self.model_id}]]" in prompt:
            raise RuntimeError(f"{self.model_id} failed (scripted by [[fail:{self.model_id}]])")
        digest = hashlib.sha1(prompt.encode()).hexdigest()[:6]
        return (
            f"Scripted answer from {self.model_id} ({digest}). "
            "The point under discussion has two sides worth weighing carefully, "
            "and this reply stands in for a real model so the interface can be tested."
        )

    def _delay(self, messages: List[BaseMessage]) -> float:
        return self.delay * (10 if "[[slow]]" in self._prompt(messages) else 1)

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self._reply(messages)))])

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        reply = self._reply(messages)
        delay = self._delay(messages)
        words = reply.split(" ")
        for i, word in enumerate(words):
            time.sleep(delay)
            token = word if i == len(words) - 1 else word + " "
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=token))
            if run_manager:
                run_manager.on_llm_new_token(token, chunk=chunk)
            yield chunk


def get_fake_model(model_id: str) -> ScriptedChatModel:
    return ScriptedChatModel(
        model_id=model_id,
        delay=float(os.getenv("CRUCIBLE_FAKE_LLM_DELAY", "0.04")),
    )
