"""Early-stop strategies (stability, judge), with injected embeddings and judge models (no patching)."""

import pytest
from langchain_core.messages import AIMessage

from app.llm import CallableModelFactory
from app.services.convergence import (
    CombinedCheck,
    JudgeCheck,
    StabilityCheck,
    Verdict,
    build_convergence_check,
)

# Texts map to fixed vectors: "same" answers are identical, "moved" ones orthogonal.
VECTORS = {"a1": [1.0, 0.0], "a2": [1.0, 0.0], "b1": [1.0, 0.0], "b2": [0.0, 1.0]}
embed = VECTORS.__getitem__
PREV = {"a": "a1", "b": "b1"}
CURR = {"a": "a2", "b": "b2"}  # a stayed put, b moved


class _Fixed:
    def __init__(self, converged, method="stability", score=None, reason=None):
        self.verdict = Verdict(converged, method, reason, score)

    async def evaluate(self, previous, current):
        return self.verdict


def _judge_factory(reply):
    return CallableModelFactory(lambda *_: type("M", (), {"invoke": lambda self, _m: AIMessage(content=reply)})())


@pytest.mark.asyncio
async def test_stability_all_requires_every_model():
    v = await StabilityCheck(0.9, "all", embed).evaluate(PREV, CURR)
    assert (v.converged, v.method, v.score) == (False, "stability", 0.5)


@pytest.mark.asyncio
async def test_stability_any_needs_one_model():
    v = await StabilityCheck(0.9, "any", embed).evaluate(PREV, CURR)
    assert v.converged and v.reason == "stability=0.500"


@pytest.mark.asyncio
async def test_stability_is_not_agreement():
    # Each model repeats its own answer while the two answers are opposite:
    # perfectly stable, and nothing here says they agree.
    opposite = {"yes1": [1.0, 0.0], "yes2": [1.0, 0.0], "no1": [0.0, 1.0], "no2": [0.0, 1.0]}
    v = await StabilityCheck(0.9, "all", opposite.__getitem__).evaluate(
        {"a": "yes1", "b": "no1"}, {"a": "yes2", "b": "no2"}
    )
    assert v.converged and v.method == "stability"


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
@pytest.mark.parametrize("mode, expected", [
    # Not stopping: the judge's "no" explains why.
    ("all", (False, "judge", "no")),
    # Stopping on stability alone: reported as stability, not as the
    # agreement the judge just denied.
    ("any", (True, "stability", "stability=0.950")),
])
async def test_combined_reports_why_it_stops(mode, expected):
    check = CombinedCheck([
        _Fixed(True, score=0.95, reason="stability=0.950"),
        _Fixed(False, method="judge", reason="no"),
    ], mode)
    v = await check.evaluate(PREV, CURR)
    assert (v.converged, v.method, v.reason) == expected
    assert v.score == 0.95


@pytest.mark.asyncio
async def test_combined_stops_on_agreement_as_judge():
    check = CombinedCheck([
        _Fixed(True, score=0.95, reason="stability=0.950"),
        _Fixed(True, method="judge", reason="same view"),
    ], "all")
    v = await check.evaluate(PREV, CURR)
    assert (v.converged, v.method, v.reason, v.score) == (True, "judge", "same view", 0.95)


def test_build_from_policy():
    assert build_convergence_check({"convergence_threshold": None, "llm_judge": None}) is None
    assert isinstance(build_convergence_check({"convergence_threshold": 0.9}), StabilityCheck)
    assert isinstance(build_convergence_check({"llm_judge": "gpt-5.4"}), JudgeCheck)
    both = build_convergence_check({"convergence_threshold": 0.9, "llm_judge": "gpt-5.4", "mode": "any"})
    assert isinstance(both, CombinedCheck) and both.mode == "any"
