"""When to compact an LLM conversation, and how much detail survives it.

Self-contained on purpose: nothing here imports from `app.*`, so the package
can be lifted out into its own project unchanged (a test enforces this). The
host application supplies model facts (ModelBudget) and token counts; this
package only decides and measures.

- policy.py   CompactionPolicy strategies: when to summarize, when to prune
- probe.py    Detail-retention scenarios: planted facts, filler, probes, scoring
- instructions.py  What the summarizer is asked to write (SummaryInstruction)
- judge.py    Paired comparison of two policies (uses Ordal, lazily)
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
from app.compaction.instructions import DetailedBrief, LengthTarget, SummaryInstruction
from app.compaction.judge import compare_recall, recall_rate
from app.compaction.probe import (
    DEFAULT_FACTS,
    PlantedFact,
    Scenario,
    Turn,
    build_dense_scenario,
    build_scenario,
    generate_facts,
    is_correct,
    is_stale,
    value_attached,
)

__all__ = [
    "DetailedBrief",
    "LengthTarget",
    "SummaryInstruction",
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
    "build_dense_scenario",
    "generate_facts",
    "is_correct",
    "is_stale",
    "value_attached",
    "compare_recall",
    "recall_rate",
]
