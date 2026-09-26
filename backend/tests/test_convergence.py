"""Convergence strategies, with injected embeddings and judge models (no patching)."""

import pytest
from langchain_core.messages import AIMessage

from app.llm import CallableModelFactory
from app.services.convergence import (
    CombinedCheck,
    JudgeCheck,
    SimilarityCheck,
    Verdict,
    build_convergence_check,
)

# Texts map to fixed vectors: "same" answers are identical, "moved" ones orthogonal.
VECTORS = {"a1": [1.0, 0.0], "a2": [1.0, 0.0], "b1": [1.0, 0.0], "b2": [0.0, 1.0]}
embed = VECTORS.__getitem__
PREV = {"a": "a1", "b": "b1"}
CURR = {"a": "a2", "b": "b2"}  # a stayed put, b moved


class _Fixed:
    def __init__(self, converged, method="similarity", score=None, reason=None):
        self.verdict = Verdict(converged, method, reason, score)

    async def evaluate(self, previous, current):
        return self.verdict


def _judge_factory(reply):
    return CallableModelFactory(lambda *_: type("M", (), {"invoke": lambda self, _m: AIMessage(content=reply)})())


@pytest.mark.asyncio
async def test_similarity_all_requires_every_model():
    v = await SimilarityCheck(0.9, "all", embed).evaluate(PREV, CURR)
    assert (v.converged, v.method, v.score) == (False, "similarity", 0.5)


@pytest.mark.asyncio
async def test_similarity_any_needs_one_model():
    v = await SimilarityCheck(0.9, "any", embed).evaluate(PREV, CURR)
    assert v.converged and v.reason == "similarity=0.500"


@pytest.mark.asyncio
@pytest.mark.parametrize("reply, converged", [("CONVERGED: yes, same view", True), ("CONVERGED: no, they differ", False)])
async def test_judge_parses_reply(reply, converged):
    v = await JudgeCheck("gpt-5.4", _judge_factory(reply)).evaluate(PREV, CURR)
    assert v.converged is converged and v.method == "judge"
    assert v.reason in ("same view", "they differ")


@pytest.mark.asyncio
async def test_judge_failure_is_not_convergence():
    def boom(*_):
        raise RuntimeError("provider down")

    v = await JudgeCheck("gpt-5.4", CallableModelFactory(boom)).evaluate(PREV, CURR)
    assert not v.converged and "provider down" in v.reason


@pytest.mark.asyncio
@pytest.mark.parametrize("mode, expected", [("all", False), ("any", True)])
async def test_combined_mode(mode, expected):
    check = CombinedCheck([_Fixed(True, score=0.95), _Fixed(False, method="judge", reason="no")], mode)
    v = await check.evaluate(PREV, CURR)
    assert v.converged is expected
    # The judge explains; the similarity supplies the score.
    assert (v.method, v.reason, v.score) == ("judge", "no", 0.95)


def test_build_from_policy():
    assert build_convergence_check({"convergence_threshold": None, "llm_judge": None}) is None
    assert isinstance(build_convergence_check({"convergence_threshold": 0.9}), SimilarityCheck)
    assert isinstance(build_convergence_check({"llm_judge": "gpt-5.4"}), JudgeCheck)
    both = build_convergence_check({"convergence_threshold": 0.9, "llm_judge": "gpt-5.4", "mode": "any"})
    assert isinstance(both, CombinedCheck) and both.mode == "any"
