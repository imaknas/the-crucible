"""Does each piece of context scaffolding still earn its place?

Every mechanism that stands between the conversation and the model (the
compaction itself, the verbatim window, a summary instruction, recall, ...)
exists because it beat a baseline once, on the models of the day. A newer
model may close that gap by itself, and scaffolding that no longer helps can
start to get in its way. So each one declares its baseline and its claim,
and an audit re-measures the pair on the current models:

- claim "improves":      it must still beat the baseline;
- claim "non_inferior":  it must not do worse than the baseline (compaction
                         is kept for cost; it only has to not lose detail).

Verdicts: keep, retire (no longer does what it claims), harmful (does worse
than going without), inconclusive (not enough evidence either way; keep it
and look again). Every audit is appended to a history, so the verdicts form
a curve across model generations rather than a snapshot.
"""

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from app.compaction import (
    GuidedRecall,
    KeepRecent,
    KeepUserMessages,
    KeywordRecall,
    NeverCompact,
    StateAndIndex,
    ThresholdPolicy,
    compare_recall,
    fixed_tokens,
)
from app.services.compaction_eval import Condition, ProbeResult

DEFAULT_HISTORY = Path(__file__).resolve().parents[2] / "experiments" / "audit" / "history.jsonl"

IMPROVES = "improves"
NON_INFERIOR = "non_inferior"


@dataclass(frozen=True)
class Scaffold:
    name: str
    claim: str
    # In the app's default path today, or a measured candidate not adopted.
    active: bool
    baseline: Condition
    treatment: Condition
    why: str


def app_scaffolds(threshold: int, *, rewriter=None) -> list[Scaffold]:
    """The scaffolds the app runs by default, and the candidates it could
    adopt, each against the baseline it has to beat. `rewriter` (a model
    rewrite function) enables the model-guided recall candidate."""
    policy = ThresholdPolicy(fixed_tokens(threshold))
    compacted = Condition(f"t{threshold}", policy)
    scaffolds = [
        Scaffold("compaction", NON_INFERIOR, True, Condition("never", NeverCompact()), compacted,
                 "Summarizing past the threshold must not lose detail against the full history."),
        Scaffold("verbatim-window", IMPROVES, True,
                 Condition(f"t{threshold}-keep0", policy, retention=KeepRecent(0)), compacted,
                 "The newest messages stay verbatim after pruning."),
        Scaffold("state-instruction", IMPROVES, False, compacted,
                 Condition(f"t{threshold}-state", policy, instruction=StateAndIndex()),
                 "Asking for current state and an index keeps more than the detailed brief."),
        Scaffold("keep-user-messages", IMPROVES, False, compacted,
                 Condition(f"t{threshold}-keepuser20k", policy, retention=KeepUserMessages(20_000)),
                 "Everything the user wrote stays verbatim (Codex CLI's rule)."),
        Scaffold("recall-keyword", IMPROVES, False, compacted,
                 Condition(f"t{threshold}-recallkeyword", policy, recall=KeywordRecall()),
                 "Hidden messages matching the request come back."),
    ]
    if rewriter is not None:
        scaffolds.append(Scaffold(
            "recall-guided", IMPROVES, False, compacted,
            Condition(f"t{threshold}-recallguided", policy, recall=GuidedRecall(rewriter)),
            "A model reads the summary and names what to fetch."))
    return scaffolds


def conditions_for(scaffolds: Iterable[Scaffold]) -> list[Condition]:
    """Every condition the scaffolds need, each once."""
    seen: dict[str, Condition] = {}
    for s in scaffolds:
        for c in (s.baseline, s.treatment):
            seen.setdefault(c.name, c)
    return list(seen.values())


def verdict(claim: str, outcome: str) -> str:
    """Map a paired comparison (a = baseline, b = scaffold) to a verdict."""
    if outcome == "a_better":
        return "harmful"
    if claim == IMPROVES:
        return {"b_better": "keep", "equivalent": "retire"}.get(outcome, "inconclusive")
    return {"b_better": "keep", "equivalent": "keep"}.get(outcome, "inconclusive")


def audit(results: Sequence[ProbeResult], scaffolds: Iterable[Scaffold], model_ids: Sequence[str],
          *, min_effect: float = 0.1) -> list[dict[str, Any]]:
    """One record per scaffold and answering model."""
    records = []
    for s in scaffolds:
        for model in model_ids:
            mine = [r for r in results if r.model == model]
            arm = lambda name: {r.key: r.correct for r in mine if r.condition == name}  # noqa: E731
            a, b = arm(s.baseline.name), arm(s.treatment.name)
            if not a or not b:
                continue
            v = compare_recall(a, b, min_effect=min_effect, label=s.name)
            records.append({
                "scaffold": s.name,
                "claim": s.claim,
                "active": s.active,
                "model": model,
                "baseline_recall": round(sum(a.values()) / len(a), 3),
                "scaffold_recall": round(sum(b.values()) / len(b), 3),
                "n": len(set(a) & set(b)),
                "outcome": v.outcome.value,
                "effect": None if v.effect is None else round(v.effect, 3),
                "interval": None if v.interval is None else [round(x, 3) for x in v.interval],
                "verdict": verdict(s.claim, v.outcome.value),
            })
    return records


def _git_sha() -> Optional[str]:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              check=True, cwd=Path(__file__).parent).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def append_history(records: Sequence[dict], context: dict, path: Path = DEFAULT_HISTORY) -> None:
    """Append one line per record, stamped with when, what code and what setup."""
    stamp = {"date": datetime.now(timezone.utc).date().isoformat(), "sha": _git_sha(), **context}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for r in records:
            f.write(json.dumps({**stamp, **r}, ensure_ascii=False) + "\n")


def load_history(path: Path = DEFAULT_HISTORY) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def latest(history: Sequence[dict]) -> dict[tuple[str, str], dict]:
    """The most recent record per (scaffold, model)."""
    out: dict[tuple[str, str], dict] = {}
    for r in history:
        out[(r["scaffold"], r["model"])] = r
    return out


def staleness(history: Sequence[dict], *, summarizer: str, catalog_synced: Optional[str]) -> Optional[str]:
    """Why the last audit no longer describes the app, or None if it still does."""
    if not history:
        return "scaffolding has never been audited"
    last = max(history, key=lambda r: r["date"])
    if last.get("summarizer") != summarizer:
        return f"the default summarizer changed ({last.get('summarizer')} → {summarizer}) since the last audit on {last['date']}"
    if catalog_synced and catalog_synced > last["date"]:
        return f"the model catalog was synced on {catalog_synced}, after the last audit on {last['date']}"
    return None
