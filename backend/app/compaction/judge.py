"""Judge whether one compaction policy retains more detail than another.

Retention data is paired and binary: the same planted fact, probed under
policy A and policy B, recalled or not. Judging uses adaptive-iteration's
DecisionRule layer for a single offline look (no weekly checkpoints), so the
outcome distinguishes "B is better", "practically equivalent" and "not enough
data yet" instead of eyeballing two recall rates.

adaptive-iteration is imported lazily: the policies in this package don't
need it, only judging does.

Rule: WelchIntervalRule in paired mode is a stopgap — a t interval on 0/1
differences is rough at small n and when few pairs disagree. It will be
replaced by a paired-proportion rule (McNemar / Newcombe) once
adaptive-iteration ships one.
"""

from typing import Mapping, Optional


def compare_recall(
    a: Mapping[str, bool],
    b: Mapping[str, bool],
    *,
    min_effect: float = 0.1,
    rule=None,
    label: str = "compaction",
):
    """Paired comparison of recall; keys pair the same probe across A and B.

    Returns adaptive-iteration's RuleResult. `effect` and `interval` are
    oriented so positive means B recalled more; `min_effect` is the smallest
    recall difference (0.1 = 10 points) that matters. Probes present in only
    one arm are left out.
    """
    from adaptive_iteration import MetricSpec, WelchIntervalRule
    from adaptive_iteration.core.decision import DecisionContext, Sample

    keys = sorted(set(a) & set(b))
    sample_a = Sample(values=tuple(float(a[k]) for k in keys), unit_ids=tuple(f"a:{k}" for k in keys), pair_ids=tuple(keys))
    sample_b = Sample(values=tuple(float(b[k]) for k in keys), unit_ids=tuple(f"b:{k}" for k in keys), pair_ids=tuple(keys))
    spec = MetricSpec(name="recall", min_effect=min_effect)
    ctx = DecisionContext(experiment_id=label, paired=True, checkpoint=1, max_checkpoints=1)
    return (rule or WelchIntervalRule()).decide(sample_a, sample_b, spec, ctx)


def recall_rate(results: Mapping[str, bool]) -> Optional[float]:
    return sum(results.values()) / len(results) if results else None
