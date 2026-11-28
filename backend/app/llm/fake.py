"""A scripted chat model for end-to-end tests.

Enabled only when CRUCIBLE_FAKE_LLM is set (the Playwright config does this),
in which case default_model_factory() is a ScriptedModelFactory. It streams a
deterministic reply word by word, so the UI goes through the same
stream_start / stream_token / stream_end path as with a real provider, without
network access or cost.

Every reply reports deterministic token usage (``usage``), as the real
providers do, so the per-answer metrics and their cost show in tests.

Test hooks, written into the prompt:
  [[fail:<model_id>]]  that model raises instead of answering
  [[slow]]             ten times the per-token delay, to hold a stream open

CRUCIBLE_FAKE_LLM_DELAY sets the per-token delay in seconds (default 0.04).
"""

import hashlib
import re
import os
import time
from typing import Any, Iterator, List, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


def enabled() -> bool:
    return os.getenv("CRUCIBLE_FAKE_LLM", "").lower() in ("1", "true", "yes")


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, list):
        return " ".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    return str(content)


def usage(messages: List[BaseMessage], reply: str) -> UsageMetadata:
    """Tokens as words: the prompt's in, the reply's out, a quarter of them
    reasoning (part of the output, as providers count it)."""
    input_tokens = sum(len(_text(m).split()) for m in messages)
    output_tokens = len(reply.split())
    return UsageMetadata(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        input_token_details={"cache_read": 0},
        output_token_details={"reasoning": output_tokens // 4},
    )


class ScriptedChatModel(BaseChatModel):
    model_id: str
    delay: float = 0.04
    # The reasoning-effort level the run sent, if any; replies don't change.
    effort: Optional[str] = None

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
        if "Score each answer from 1 to 10" in prompt:
            # A peer review (services/review.py): a score for every letter shown.
            letters = re.findall(r"^\[([A-Z])\]:", prompt, re.M)
            return "\n".join(f"{letter}: 7 — Scripted review from {self.model_id}." for letter in letters)
        if "List every problem, risk, gap or objection" in prompt:
            # An issue list (synthesis.ISSUES), in its numbered form.
            labels = re.findall(r"^\[([^\]]+)\]:", prompt, re.M)
            first, rest = (labels[:1] or ["a reviewer"]), (labels[1:] or labels[:1] or ["a reviewer"])
            return (
                f"1. Scripted problem one from {self.model_id} ({digest}).\n"
                f"   Raised by: {', '.join(first)}\n"
                "   Why: Scripted reason one.\n"
                f"2. Scripted problem two from {self.model_id} ({digest}).\n"
                f"   Raised by: {', '.join(rest)}\n"
                "   Why: Scripted reason two.\n"
                "Where the reviews contradict each other: none."
            )
        if "Check each problem below against" in prompt:
            # A problem-by-problem check (services/checks.py): one verdict
            # each, "holds" for odd problems, "can't tell" for even ones.
            numbers = re.findall(r"^(\d+)\. ", prompt.split("Problems:", 1)[-1], re.M)
            return "\n".join(
                f"{n}: {'holds' if int(n) % 2 else 'can\'t tell'} — Scripted check from {self.model_id}."
                for n in numbers
            )
        if "List the distinct components of these answers" in prompt:
            # A checklist synthesis's first step (synthesis.component_request).
            return (
                f"1. [all answers] Scripted part one from {self.model_id} ({digest}).\n"
                f"2. [all answers] Scripted part two from {self.model_id} ({digest})."
            )
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
        reply = self._reply(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content=reply, usage_metadata=usage(messages, reply), response_metadata={"model_name": self.model_id}))])

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
            last = i == len(words) - 1
            token = word if last else word + " "
            # Usage on the last chunk only: chunks are added together.
            chunk = ChatGenerationChunk(
                message=AIMessageChunk(content=token, usage_metadata=usage(messages, reply) if last else None,
                                       response_metadata={"model_name": self.model_id} if last else {})
            )
            if run_manager:
                run_manager.on_llm_new_token(token, chunk=chunk)
            yield chunk


class ScriptedModelFactory:
    """ModelFactory that answers every registered model with a ScriptedChatModel."""

    def __init__(self, delay: Optional[float] = None):
        self._delay = float(os.getenv("CRUCIBLE_FAKE_LLM_DELAY", "0.04")) if delay is None else delay

    def chat(self, model_id: str, toggles: Any = None, effort: Optional[str] = None) -> ScriptedChatModel:
        from app.llm.factory import normalize_model_id

        return ScriptedChatModel(model_id=normalize_model_id(model_id), delay=self._delay, effort=effort)
