"""When to compact an LLM conversation, and how much detail survives it.

Self-contained on purpose: nothing here imports from `app.*`, so the package
can be lifted out into its own project unchanged (a test enforces this). The
host application supplies model facts (ModelBudget) and token counts; this
package only decides and measures.

- policy.py   CompactionPolicy strategies: when to summarize, when to prune
- probe.py    Detail-retention scenarios: planted facts, filler, probes, scoring
- instructions.py  What the summarizer is asked to write (SummaryInstruction)
- retention.py  What stays verbatim once history is pruned (Retention)
- recall.py     Which pruned messages to bring back for a request (HistoryRecall)
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
from app.compaction.instructions import AllSubjects, DetailedBrief, HandoffBrief, IndexOnly, LengthTarget, StateAndIndex, SummaryInstruction
from app.compaction.recall import EmbeddingRecall, GuidedRecall, HistoryRecall, KeywordRecall
from app.compaction.retention import EarlierMessage, KeepRecent, KeepUserMessages, Retention
from app.compaction.judge import compare_recall, recall_rate
from app.compaction.probe import (
    DEFAULT_FACTS,
    PlantedFact,
    Scenario,
    Turn,
    build_dense_scenario,
    build_scenario,
    build_task_scenario,
    generate_facts,
    is_correct,
    is_stale,
    value_attached,
    as_asides,
    with_reminders,
)

__all__ = [
    "AllSubjects",
    "DetailedBrief",
    "HandoffBrief",
    "StateAndIndex",
    "IndexOnly",
    "GuidedRecall",
    "HistoryRecall",
    "KeywordRecall",
    "EmbeddingRecall",
    "EarlierMessage",
    "KeepRecent",
    "KeepUserMessages",
    "Retention",
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
    "build_task_scenario",
    "generate_facts",
    "is_correct",
    "is_stale",
    "value_attached",
    "with_reminders",
    "as_asides",
    "compare_recall",
    "recall_rate",
]
