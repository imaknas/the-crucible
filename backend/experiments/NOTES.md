# Compaction experiments — lab notes

Raw results live in `results/` (one JSON per run, every probe included).
Experiment databases (`*.sqlite`) are not committed; runs are reproducible
with the command recorded in each entry.

## 2026-09-26 — Pilot 1: cheap models, synthetic filler

**Command:** `uv run crucible compaction-eval --scenario basic --compaction once --no-oracle --out experiments/results/pilot-cheap-2026-09-26.json`
(the flags reproduce pilot 1's design; the defaults changed with pilot 2).

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

## 2026-09-26 — Pilot 2: dense scenarios, live compaction

**Command:** `uv run crucible compaction-eval -t 8000 -s gemini-3.5-flash -s gemini-3.5-flash-lite --out experiments/results/pilot2-dense-2026-09-26.json`

**Design changes (all five from pilot 1's "Next").**
- `build_dense_scenario`: 140 exchanges (~23k tokens). Every turn states
  specifics about some subsystem (latency, tickets, release, owners…), so the
  24 planted facts per scenario are not the only concrete content. Fact
  attributes never appear in filler and filler values come from disjoint
  pools, so each probe has exactly one right answer.
- Variants: plain; *distractor* (a rejected proposal with another value is
  planted within ±15 exchanges); *update* (an older value is planted 3–30
  exchanges earlier, the fact states the new one). An answer containing a
  rejected or superseded value is scored wrong and counted as `stale`.
- Live compaction (`run_live_grid`): the conversation is replayed turn by
  turn through the graph's summarize step, so it is summarized several times
  as it grows (H3). The replay is shared by all answering models: every model
  sees the identical compacted context.
- Summarizer as a condition: gemini-3.5-flash (the app default) vs
  gemini-3.5-flash-lite, both at a fixed 8,000-token threshold.
- The `oracle` pseudo-model answers from the same branches: it recalls a
  fact iff the value is still in the context it is given, so its recall is
  what the summaries kept (H1). Real model recall below the oracle's is
  information present but not used (H2).
- New per-probe fields: `variant`, `stale`, `compactions` (summaries written
  after the fact was stated).

**Smoke run finding — summary thrash.** At t=2000 on a 40-exchange dense
scenario, summaries grew to ~4k tokens and a new one was written every 5
messages (12 summaries). `ThresholdPolicy` counts the summary itself in
`tokens_since_summary`, so once a summary is larger than the threshold the
policy fires on every eligible turn: each re-summary costs a summarizer call
and re-compresses already compressed text. Summaries also started to blend
filler values ("p95 latency of 305 ms (noted as 140 ms …)").

**Scoring fix (applied before reading results).** Models often answer and
then quote the source: "Litware — stated as '…picked Litware over Margie and
Contoso'". Matching stale values anywhere in the reply marked those wrong
(Haiku scored 0/9 on vendor choice in every condition). Scoring now reads
only the committed answer, the reply's first non-empty line
(`probe.committed_answer`); a reply listing two candidates without choosing
still counts as wrong. The stored answers were rescored
(`compaction_eval.rescore`); 74 of 864 probes changed. Pilot 1 is unchanged
(216/216).

**Result.** Recall, 72 paired probes per cell (3 scenarios × 24 facts):

| answering model | never compact | t8000, flash summaries | t8000, flash-lite summaries |
|---|---|---|---|
| gpt-5.4-nano | 0.875 | **1.000** | 0.458 |
| claude-haiku-4-5 | 0.806 | **0.986** | 0.472 |
| gemini-3.5-flash-lite | 0.833 | **0.972** | 0.444 |
| oracle (value still in context) | 1.000 | 1.000 | 0.486 |

Every model: flash summaries beat never compacting (+12 to +18 points, 95%
intervals exclude 0), flash-lite summaries lose to both (−33 to −54 points).

1. **The ceiling is gone, and without compaction cheap models already miss
   ~15%** of facts in a 23k-token dense conversation. Most misses are
   variant facts: gemini-3.5-flash-lite gave the superseded value on 10 of 18
   updates (stale 11), Haiku on 8. Attention over a long raw history is
   itself lossy (H4), especially for "which value is current".
2. **A good summary is better than the raw history.** gemini-3.5-flash
   summaries kept every fact (oracle 1.00) through 10–29 successive
   summaries, and resolved updates: stale answers dropped to 0. The summary
   is a consolidated state, not only a shorter transcript.
3. **With a weak summarizer the loss is in the summary (H1), not in
   attention (H2).** Models track the oracle (0.44–0.47 vs 0.49): what
   flash-lite dropped is gone, and what it kept is found.
4. **Loss compounds with each summary (H3)** — flash-lite, oracle recall by
   number of summaries a fact went through: 1 → 12/13, 2 → 16/23,
   3 → 6/19, 4 → 0/16.
5. **Repetition protects a fact.** Under flash-lite, plain facts (stated
   once) survived 9/36; distractor and update facts (the subject is
   mentioned twice) 12/18 and 14/18.

**Cost and the thrash.** gemini-3.5-flash wrote 132 summaries (flash-lite:
23). Its summaries grow past the 8,000-token threshold, so ThresholdPolicy
re-summarizes every 5 messages from then on (see the smoke-run note). Those
summaries produced ~1.57M output tokens, mostly thinking, against ~1.26M
input: the summarizer was the largest cost of the run, larger than the
answering models reading raw history (never: 1.4–1.6M input tokens per
model). Measured tokens are in the JSON; prices were not recorded. The run
cost roughly $8–10 at list prices, about twice the planned $5.

**Next.**
- Fix the thrash: measure `tokens_since_summary` without the summary itself,
  or set the threshold relative to the summary size. Then compare flash vs
  flash-lite again at equal summary counts, since part of flash's win may
  be the sheer number of refreshes.
- A summarizer without thinking (or with a thinking budget) — flash's
  retention at a fraction of its cost?
- Larger answering models: is the never-compact deficit (point 1) only a
  small-model effect?

## 2026-09-26 — Fix: re-summarize thrash

`ThresholdPolicy.should_summarize` compared `tokens_since_summary` (summary
included) with the threshold. gemini-3.5-flash summaries grew from 4.1k to
8.3k tokens over a pilot 2 conversation, so once one passed 8,000 the policy
fired on every eligible turn (every 5 messages, including during probing).

Now `ContextSnapshot.summary_tokens` is reported and re-summarizing is due
when `new_tokens > max(threshold − summary_tokens, min_new_fraction ×
threshold)` (default 0.5). While the summary is small this is exactly the old
rule. Replay check with a summarizer whose output grows 480 tokens per call
(60 exchanges, t=2000): 16 summaries before, 8 after. At pilot 2's t=8000
the floor is 4,000 new tokens, so probing (≈50 tokens per probe) no longer
re-summarizes at all.

Not fixed: the summary itself still grows without bound (the prompt asks
for a "detailed" brief and sets no length). A length target is a separate
condition to test — it trades cost against the retention flash showed.

Pilot 2's flash-vs-flash-lite comparison was made under the old rule
(flash: 10–29 summaries per fact, flash-lite: 1–5). Re-run it before
attributing flash's advantage to the model rather than to the refreshes.
