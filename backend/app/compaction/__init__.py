"""When to compact an LLM conversation, and how much detail survives it.

Self-contained on purpose: nothing here imports from `app.*`, so the package
can be lifted out into its own project unchanged (a test enforces this). The
host application supplies model facts (ModelBudget) and token counts; this
package only decides and measures.

- policy.py   CompactionPolicy strategies: when to summarize, when to prune
- probe.py    Detail-retention scenarios: planted facts, filler, probes, scoring
- judge.py    Paired comparison of two policies (uses adaptive-iteration, lazily)
"""

from app.compaction.policy import (
    CompactionPolicy,
    ContextSnapshot,
    Decision,
    ModelBudget,
    NeverCompact,
    ThresholdPolicy,
    fixed_tokens,
    fraction_of_limit,
)
from app.compaction.judge import compare_recall, recall_rate
from app.compaction.probe import (
    DEFAULT_FACTS,
    PlantedFact,
    Scenario,
    Turn,
    build_scenario,
    is_correct,
)

__all__ = [
    "CompactionPolicy",
    "ContextSnapshot",
    "Decision",
    "ModelBudget",
    "NeverCompact",
    "ThresholdPolicy",
    "fixed_tokens",
    "fraction_of_limit",
    "DEFAULT_FACTS",
    "PlantedFact",
    "Scenario",
    "Turn",
    "build_scenario",
    "is_correct",
    "compare_recall",
    "recall_rate",
]
