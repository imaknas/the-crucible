# Compaction experiments — lab notes

Raw results live in `results/` (one JSON per run, every probe included).
Experiment databases (`*.sqlite`) are not committed; runs are reproducible
with the command recorded in each entry.

## 2026-09-26 — Pilot 1: cheap models, synthetic filler

**Command:** `uv run crucible compaction-eval --out experiments/results/pilot-cheap-2026-09-26.json`

**Setup.** 3 scenarios (seeds 0–2) × 40 exchanges (~6.9k tokens) × 8 planted
facts (number, name, 2 identifiers, negation, date, quote, choice), buried
mid-message. Answering models: gpt-5.4-nano, claude-haiku-4-5, gemini-3.5-flash-lite.
Summarizer: gemini-3.5-flash (app default). Conditions: never compact vs.
compact at 2,000 and 4,000 tokens. 24 paired probes per model and condition.

**Result.** Recall 1.00 in every cell (216/216). Compaction did happen: all
48 compacted probes per model saw pruned, summarized history. Judged with
`PairedProportionRule`: no detectable difference (24 concordant pairs,
95% CI for the difference ±0.14).

**Why — a ceiling effect, not evidence that compaction is safe.** The
~1.7k-token summary (≈4× compression) kept all 8 facts verbatim. The filler is
generic and repetitive, so the planted facts are the only distinctive content
in the conversation; any competent summarizer keeps them. The pilot validates
the pipeline (seeding, branching, pruning, usage capture, judging), not the
hypothesis.

**Cost signal.** The summarizer produced ~112k output tokens for 18 summaries
(~6k each, mostly thinking tokens) against ~1.7k tokens of summary text:
with a thinking summarizer, compaction's cost is dominated by the summarizer's
reasoning, not by what it writes.

**Next — make detail compete.**
1. Information-dense filler: every turn carries plausible specifics (other
   numbers, names, ids), so planted facts are no longer the only signal.
2. Distractors and updates: near-miss values ("the cap for phase 2 is
   52,000") and corrections ("the freeze moved to 21 March") — does the
   summary keep the latest value?
3. Fact load: 20–40 facts per conversation instead of 8.
4. Length: long enough to trigger 2–3 successive summaries (H3, cumulative decay).
5. A non-thinking or smaller summarizer as a condition (cost vs. retention).
