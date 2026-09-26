"""Convergence detection for debates, as interchangeable strategies.

A debate asks one ConvergenceCheck, after every round from round 1 on, whether
the models have settled. build_convergence_check() turns a session's
termination policy into that check:

  convergence_threshold only  → SimilarityCheck
  llm_judge only              → JudgeCheck
  both                        → CombinedCheck(mode="all" | "any")
  neither                     → None (the debate runs all its rounds)

To add a new kind of check, implement ConvergenceCheck and wire it into
build_convergence_check(); run_debate doesn't change.
"""

import asyncio
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Protocol, Sequence

import numpy as np

Embed = Callable[[str], list[float]]
Responses = Mapping[str, str]


@dataclass(frozen=True)
class Verdict:
    converged: bool
    # How the verdict was reached: "similarity" or "judge".
    method: str
    reason: Optional[str] = None
    # Mean round-over-round similarity, when the check measures one.
    score: Optional[float] = None


class ConvergenceCheck(Protocol):
    async def evaluate(self, previous: Responses, current: Responses) -> Verdict:
        """Compare each model's answer this round with its previous one."""
        ...


# ─── Similarity ──────────────────────────────────────────────────


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a), np.array(b)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def _default_embed() -> Embed:
    from app.services.rag import get_embeddings

    return get_embeddings().embed_query


def _compute_sync(
    prev_responses: Responses,
    curr_responses: Responses,
    mode: str,
    threshold: float,
    embed: Optional[Embed] = None,
) -> tuple[float, bool]:
    """Blocking: returns (mean_similarity, converged). Run it in an executor."""
    embed = embed or _default_embed()
    models = [m for m in curr_responses if m in prev_responses]
    if not models:
        return 0.0, False

    similarities = []
    for model_id in models:
        prev_text = prev_responses[model_id].strip()
        curr_text = curr_responses[model_id].strip()
        if not prev_text or not curr_text:
            continue
        similarities.append(_cosine_similarity(embed(prev_text), embed(curr_text)))

    if not similarities:
        return 0.0, False

    mean_sim = float(np.mean(similarities))
    if mode == "all":
        # A model that errored or timed out this round has no similarity; "all"
        # must not be satisfied by the models that happened to answer.
        converged = len(similarities) == len(models) and all(s >= threshold for s in similarities)
    else:
        converged = any(s >= threshold for s in similarities)
    return mean_sim, converged


class SimilarityCheck:
    """Converged when each model's answer stopped changing (embedding cosine)."""

    def __init__(self, threshold: float, mode: str = "all", embed: Optional[Embed] = None):
        self.threshold = threshold
        self.mode = mode
        self._embed = embed

    async def evaluate(self, previous: Responses, current: Responses) -> Verdict:
        loop = asyncio.get_running_loop()
        score, converged = await loop.run_in_executor(
            None, _compute_sync, previous, current, self.mode, self.threshold, self._embed
        )
        return Verdict(converged=converged, method="similarity", reason=f"similarity={score:.3f}", score=score)


# ─── LLM judge ───────────────────────────────────────────────────


class JudgeCheck:
    """Converged when a judge model says the positions agree."""

    def __init__(self, judge_model: str, factory=None, timeout: float = 30.0):
        self.judge_model = judge_model
        self._factory = factory
        self.timeout = timeout

    def _prompt(self, current: Responses) -> str:
        summaries = "\n\n".join(f"[{model}]:\n{content}" for model, content in current.items())
        return (
            "You are evaluating whether multiple AI models have reached a substantive consensus.\n\n"
            f"Their responses:\n{summaries}\n\n"
            "Have they converged on the same core position? "
            'Reply with exactly: "CONVERGED: yes, <one-line reason>" or "CONVERGED: no, <one-line reason>".'
        )

    async def evaluate(self, previous: Responses, current: Responses) -> Verdict:
        from langchain_core.messages import HumanMessage

        from app.llm import default_model_factory
        from app.utils.helpers import extract_text

        try:
            llm = (self._factory or default_model_factory()).chat(self.judge_model, {})
            loop = asyncio.get_running_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(None, llm.invoke, [HumanMessage(content=self._prompt(current))]),
                timeout=self.timeout,
            )
            text = extract_text(response.content).strip()
            reason = text.split(",", 1)[1].strip() if "," in text else text
            return Verdict(converged=text.upper().startswith("CONVERGED: YES"), method="judge", reason=reason)
        except asyncio.TimeoutError:
            return Verdict(converged=False, method="judge", reason="Judge timed out")
        except Exception as e:
            return Verdict(converged=False, method="judge", reason=f"Judge error: {e}")


# ─── Composition ─────────────────────────────────────────────────


class CombinedCheck:
    """Runs several checks; converged when all (or any) of them agree."""

    def __init__(self, checks: Sequence[ConvergenceCheck], mode: str = "all"):
        self.checks = list(checks)
        self.mode = mode

    async def evaluate(self, previous: Responses, current: Responses) -> Verdict:
        verdicts = await asyncio.gather(*(c.evaluate(previous, current) for c in self.checks))
        combine = all if self.mode == "all" else any
        judge = next((v for v in verdicts if v.method == "judge"), None)
        score = next((v.score for v in verdicts if v.score is not None), None)
        reason = (judge.reason if judge else None) or next((v.reason for v in verdicts if v.reason), None)
        return Verdict(
            converged=combine(v.converged for v in verdicts),
            method="judge" if judge else verdicts[0].method,
            reason=reason,
            score=score,
        )


def build_convergence_check(policy: Mapping, factory=None, embed: Optional[Embed] = None) -> Optional[ConvergenceCheck]:
    """The check a debate's termination policy asks for, or None."""
    mode = policy.get("mode", "all")
    checks: list[ConvergenceCheck] = []
    if policy.get("convergence_threshold") is not None:
        checks.append(SimilarityCheck(policy["convergence_threshold"], mode, embed))
    if policy.get("llm_judge"):
        checks.append(JudgeCheck(policy["llm_judge"], factory))
    if not checks:
        return None
    return checks[0] if len(checks) == 1 else CombinedCheck(checks, mode)
