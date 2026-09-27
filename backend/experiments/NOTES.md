# Compaction experiments — lab notes

Raw results live in `results/` (one JSON per run, every probe included).
Experiment databases (`*.sqlite`) are not committed; runs are reproducible
with the command recorded in each entry.

## Conclusions so far (as of 2026-09-28)

One principle ties them together: every loss measured here was information
whose only copy was a summary. Keeping the original reachable, or asking the
summary for the current state, is what prevented it. Details and numbers are
in the dated entries below.

**Solid** (large effects, replicated across runs):

1. With a cheap summarizer, loss compounds with each pass: a fact that went
   through 1 summary survived 100% of the time, after 4 summaries 0%
   (pilots 2, 2b, 6a).
2. Bringing hidden originals back (keyword recall) rescues lossy summaries:
   flash-lite handoffs went from 9/72 to 66/72, with each later call reading
   2.8k tokens (pilot 7b).
3. gemini-3.8-flash summarizes as well as gemini-3.5-flash at about 1/6 of
   the cost per summary (pilot 4).
4. Keeping user messages verbatim (Codex CLI's rule) rescues exactly the
   user-stated facts and nothing else, at 2.3× the context per call
   (pilot 5).

**Likely** (clear effects, small scale):

5. Most loss is in the summary, not in the answering model's attention; with
   a weak summarizer, models also missed ~14% of facts that did survive
   (pilot 2b, strict re-score).
6. For small models a good summary beats the raw history: in a 23k-token
   transcript they often gave superseded values, which the summary resolved
   (pilot 2).
7. What the summarizer is asked to keep matters as much as which model it
   is: state-and-index took flash-lite from 31 to 70 of 72, about the same
   gain as switching to gemini-3.8-flash (31 → 72) (pilots 5, 7a).

**Tentative** (direction visible, not settled):

8. Old facts are lost to repeated passes rather than lack of room: one
   summary of everything kept 19/24 early facts vs 8/24 incrementally, but
   the overall paired test was not decisive, and one big pass detaches
   values from their subjects (pilot 6a).
9. A restatement adds 25 points, partly because the restatement is newer and
   went through fewer passes (pilot 6b).

**Changed in the app:** the re-summarize thrash fix; `SUMMARIZER_MODELS`
now leads with gemini-3.8-flash; the price list, cost estimate and
`--budget` hard cap. **Measured, not adopted:** `StateAndIndex`,
`KeywordRecall`, `KeepUserMessages` — candidates, not defaults.

**Limitations:** synthetic conversations only; 3 conversations × 24 facts
per cell; small and mid-size models; one threshold (8,000 tokens); no
multiple-comparison correction; keyword recall is favoured by probes that
name their subject. Total spend about $55, about $41 of it before the
budget guard existed.

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

## 2026-09-27 — Pilot 2b: flash vs flash-lite without the thrash

**Command:** `uv run crucible compaction-eval --no-baseline -t 8000 -s gemini-3.5-flash -s gemini-3.5-flash-lite --out experiments/results/pilot2b-no-thrash-2026-09-26.json`
(same scenarios, models and threshold as pilot 2; the never-compact
baseline is not affected by the fix and was not re-run.)

**Summaries.** flash 23 (pilot 2: 132), flash-lite 17 (23). Facts now pass
through 1–5 summaries under both summarizers, so the comparison is at equal
refresh counts. flash's summarizer output fell from ~1.57M to ~0.50M tokens;
each summary now covers more new text and thinks more (~20k output tokens
per summary vs ~12k).

| answering model | flash summaries | flash-lite summaries | pilot 2 (flash / lite) |
|---|---|---|---|
| gpt-5.4-nano | 0.986 | 0.500 | 1.000 / 0.458 |
| claude-haiku-4-5 | 1.000 | 0.417 | 0.986 / 0.472 |
| gemini-3.5-flash-lite | 1.000 | 0.278 | 0.972 / 0.444 |
| oracle | 1.000 | 0.542 | 1.000 / 0.486 |

flash beats flash-lite for every model (−46 to −72 points, intervals far
from 0). **flash's advantage is the summarizer, not the refreshes**: it
holds with a similar number of summaries per fact. flash-lite's
cumulative loss repeats (oracle by summaries survived: 1 → 10/10,
2 → 16/18, 3 → 13/20, 4 → 0/24).

**Model vs oracle under flash-lite summaries** (facts whose value the
oracle still found): nano missed 3/39, Haiku 9/39 ("I cannot find … about
the billing export"), gemini-3.5-flash-lite 19/39 (empty or invented
answers: "€15,000 … based on standard IT operations"). Caveat: the oracle
checks that the value string is somewhere in context, not that it is
still attached to its subject, so part of this gap is association lost in
the summary rather than attention. Next oracle version: require the
subject and the value in the same sentence.

**Cost** roughly $3–4 (Haiku reading the compacted context ~$2, flash
summaries ~$1.3).

## 2026-09-27 — Pilot 2c: summarizer thinking level

**Command:** `uv run crucible compaction-eval --no-baseline -t 8000 -s gemini-3.5-flash@minimal -s gemini-3.5-flash@medium --out experiments/results/pilot2c-thinking-2026-09-27.json`
Reference: the default-thinking flash condition of pilot 2b (same scenarios,
models, threshold and policy), merged by probe key for the comparisons.
`model@level` binds Gemini's `thinking_level` per call (experiments only).

One summary of 60 exchanges, measured directly: default 11.4k reasoning /
15.0k output tokens (the default behaves like `high`: 14.2k / 18.2k);
`medium` 6.7k / 9.6k; `low` and `minimal` no reasoning, ~3k output.

| answering model | high (default, 2b) | medium | minimal |
|---|---|---|---|
| gpt-5.4-nano | 0.986 | 0.972 | 0.806 |
| claude-haiku-4-5 | 1.000 | 0.986 | 0.819 |
| gemini-3.5-flash-lite | 1.000 | 0.986 | 0.819 |
| oracle | 1.000 | 1.000 | 0.861 |

| summarizer | summaries | median summary size | output tokens per summary |
|---|---|---|---|
| flash high (default) | 23 | 12.8k | ~21.6k |
| flash medium | 22 | 8.8k | ~18.1k |
| flash minimal | 20 | 6.6k | ~5.9k |
| flash-lite (pilot 2) | — | ~3k | — |

- **medium ≈ high** for every model ("equivalent" within ±0.1, intervals
  within [−0.09, +0.05]) at ~16% less summarizer output.
- **minimal loses ~18 points** (all three models, intervals exclude 0) but
  costs ~¼ of high per summary. The loss is in the summaries (oracle 0.86)
  and concentrated in plain facts (27/36) and facts through 4 summaries
  (15/24); distractor/update facts survived (35/36).

**The confound this exposes: summary size.** flash's default summaries are
~12.8k tokens of a ~23k-token conversation — barely compression, and larger
than the 8,000-token threshold itself. Haiku read 1.40M input tokens under
flash summaries vs 1.61M never compacting (−13%); under minimal 0.80M,
under flash-lite 0.53M. Retention so far tracks summary size (12.8k → 1.00,
8.8k → 1.00, 6.6k → 0.86, ~3k → ~0.5), so "flash is a better summarizer"
and "flash writes longer summaries" are not yet separated. Pilot 2's
"a good summary beats the raw history" still holds (consolidation removes
stale values), but most of flash's retention is bought with size.

**Next.** A length target in the summary prompt (e.g. 1.5k / 3k / 6k
tokens) for flash and flash-lite: recall per summary token, which is the
number a policy needs. With several conditions on the same probe set, apply
Ordal's winner's-curse correction (`ordal.shrinkage.estimate_prior`;
Ordal is adaptive-iteration renamed) before reporting the best one.

**Cost** roughly $3–4 (Haiku ~$2, flash summaries ~$1.3).

## 2026-09-27 — Strict oracle: kept values stay attached

A summary can keep "5592" while losing that it was the CDN purge job's port,
so the plain oracle (value anywhere in context) could overstate what
survived. `probe.value_attached` requires the value to be attached to its
subject: on a line mentioning the subject, or with this subject as the
nearest subject mentioned before it (its section, however long). A first
version (value within 200 characters of the subject) was wrong: flash writes
per-subsystem sections with long bullet lists, and it marked 21% of facts
"detached" that every model answered correctly.

Re-scored offline for pilots 2b and 2c, from the stored oracle branches,
pruned exactly as the drafting node prunes (the loose re-score reproduces the
recorded oracle recall exactly):

| summaries | oracle | oracle-strict | models missed a fact that was attached |
|---|---|---|---|
| flash (default thinking) | 1.000 | 1.000 | 1 / 216 |
| flash@medium | 1.000 | 1.000 | 4 / 216 |
| flash@minimal | 0.861 | 0.861 | 10 / 216 |
| flash-lite | 0.542 | 0.542 | 31 / 216 |

No model ever answered correctly when the value was detached. Two findings:

- Summaries in these runs never kept a value while losing its subject:
  loss is all-or-nothing per fact (H1).
- The pilot 2b gap between models and the oracle under flash-lite summaries
  is therefore attention, not lost association (H2): models miss ~14% of the
  facts a terse summary did keep, against ~0.5% under flash's long summaries.

## 2026-09-27 — What these runs cost, and budget control

The earlier "cost" lines in these notes used guessed prices and were far too
low (gemini-3.5-flash was assumed $2.50/1M output; it is $9.00). At official
prices (`app/catalog/data/prices.json`, checked 2026-09-27), from each run's
recorded usage:

| run | cost | of which gemini-3.5-flash (summarizer) | Haiku |
|---|---|---|---|
| pilot 1 | $1.90 | $1.22 | $0.53 |
| pilot 2 | $22.61 | $15.98 | $4.50 |
| pilot 2b | $7.81 | $4.88 | $2.00 |
| pilot 2c | $8.28 | $5.27 | $2.18 |

About $41 in total, plus the unrecorded smoke/calibration calls and the
length-target run stopped at 27 of 1,080 probes (61 summaries written). The
summarizer's reasoning tokens at $9/1M are most of it.

Price facts that change experiment defaults: gpt-6-luna ($0.10/$0.50) is half
of gpt-5.4-nano ($0.20/$1.25); gemini-3.8-flash ($0.75/$3.75 until
2026-12-31, then $1.50/$7.50) is cheaper than gemini-3.5-flash ($1.50/$9.00)
and, in one measured summary, reasoned half as much ($0.025 vs $0.088 per
summary, both keeping 5/5 planted facts); gemini-3.1-flash-lite
($0.25/$1.50) undercuts 3.5-flash-lite.

`compaction-eval` now requires `--budget`: calibration calls, a dry-run
estimate, refusal above budget, and a hard stop. Back-test on pilot 2c's
settings: estimate $6.27, actual $8.28 — the planning figure is the
estimate × 1.35.

## 2026-09-27 — Pilot 4: gemini-3.8-flash as the summarizer

**Command:** `uv run crucible compaction-eval --budget 1.5 --no-baseline -t 8000 -s gemini-3.8-flash -m gpt-6-luna -m gemini-3.1-flash-lite --out experiments/results/pilot4-flash38-2026-09-27.json`
Same scenarios, threshold and policy as pilot 2b; the gemini-3.5-flash
reference is 2b's (oracle probes pair by scenario and fact across runs).

**Cost.** Estimated $1.02 (a separate `--estimate` run said $0.73: the
calibration call varies), spent $0.82 + $0.03 calibration, cap $1.50.

| summarizer | oracle recall | summaries | median size | cost per summary |
|---|---|---|---|---|
| gemini-3.5-flash (2b) | 1.000 | 23 | 12.8k | ~$0.21 |
| **gemini-3.8-flash** | **0.972** | 17 | 6.4k | **~$0.032** |
| gemini-3.5-flash-lite (2b) | 0.542 | 17 | ~3k | ~$0.01 |

- 3.8-flash vs 3.5-flash (oracle, 72 paired probes): **equivalent**,
  −2.8 points, 95% interval [−9.6, +2.7] inside ±10. It lost 2 plain facts
  (a quote, a port), both after 4 summaries; stale answers 0.
- gpt-6-luna and gemini-3.1-flash-lite answered exactly as well as the
  oracle (0.972 each): nothing the summaries kept was missed.
- Its summaries are half the size of 3.5-flash's, so answering reads less
  too. At the price from 2027-01-01 ($1.50/$7.50) a summary would cost
  ~$0.06, still ~3.5× cheaper than 3.5-flash.

**For the app:** gemini-3.8-flash is the better default summarizer
(`SUMMARIZER_MODELS`), at the same retention for ~1/6 of the cost.

## 2026-09-27 — Pilot 5: Codex CLI's compaction as conditions

**Command:** `uv run crucible compaction-eval --budget 3.2 --no-baseline -t 8000 -s gemini-3.5-flash-lite -s gemini-3.8-flash --keep recent --keep user --instruction brief --instruction handoff --assistant-facts 0.5 -m gpt-6-luna --out experiments/results/pilot5-codex-style-2026-09-27.json`
New scenarios: half of the 24 facts per conversation are stated by the
assistant. Estimated $2.06 (+$0.08 calibration), spent $2.47, cap $3.20.

How the tools compact (read 2026-09-27): **Codex CLI** (open source,
openai/codex 9db8162d65) auto-compacts at 90% of the context window; the
working model writes a "handoff summary for another LLM that will resume the
task" (`HandoffBrief`); the new history is **every user message verbatim,
newest first, up to 20,000 tokens**, plus the summary; assistant turns and
tool output are dropped; after compacting it warns that multiple compactions
make the model less accurate. **Claude Code** (docs only): clears old tool
output first, then summarizes; "your requests and key code snippets are
preserved"; CLAUDE.md is reloaded; a "Compact Instructions" section or
`/compact <focus>` steers it; threshold not documented.

Oracle recall (72 probes per cell; 36 user-stated, 36 assistant-stated):

| summarizer | keep | instruction | user-stated | assistant-stated | summary | read per probe |
|---|---|---|---|---|---|---|
| flash-lite | recent | brief | 17/36 | 14/36 | 5.6k | 5.8k |
| flash-lite | recent | handoff | 7/36 | 3/36 | 0.9k | 2.1k |
| flash-lite | **user** | brief | **36/36** | 16/36 | 3.2k | 13.1k |
| flash-lite | user | handoff | 36/36 | 2/36 | 0.8k | 9.7k |
| 3.8-flash | recent | brief | 36/36 | 36/36 | 7.8k | 9.5k |
| 3.8-flash | recent | **handoff** | 36/36 | **34/36** | **1.3k** | **3.7k** |
| 3.8-flash | user | brief | 36/36 | 35/36 | 6.9k | 16.4k |
| 3.8-flash | user | handoff | 36/36 | 36/36 | 1.8k | 10.8k |

(gpt-6-luna matched the oracle except under flash-lite/recent/brief: 0.375
vs 0.431.)

1. **Keeping user messages rescues exactly what the user said** (flash-lite:
   17 → 36 of 36, +53 points, interval [+34, +68]) and nothing else
   (assistant-stated 14 → 16, no detectable difference), at 2.3× the context
   per call.
2. **Codex's handoff prompt writes summaries ~1/6 the size.** With a weak
   summarizer that is ruinous for anything not kept verbatim (assistant-stated
   14 → 3 of 36, −31 points). With gemini-3.8-flash it is nearly free
   (36 → 34, no detectable difference) and cuts what every later call reads
   from 9.5k to 3.7k tokens.
3. **Why Codex can afford a short handoff:** what the user said is kept
   verbatim, and what the agent learned lives in the repository and can be
   re-read — the summary only has to carry state and next steps. In a
   conversation whose details exist only in the chat (The Crucible's case),
   the same design depends entirely on a strong summarizer.
4. **This refines "retention tracks summary size" (pilot 2c).** gemini-3.8-flash
   kept 34/36 assistant facts in 1.3k-token handoffs while flash-lite lost
   most of them in 5.6k-token briefs: for a capable summarizer the limit is
   what it chooses to keep, not the room it has. Size mattered earlier because
   it was confounded with the summarizer's ability (flash thinking levels).

## 2026-09-27 — Pilot 6: why detail is lost (oracle only, flash-lite)

Four runs, gemini-3.5-flash-lite summaries, oracles only, t=8000, same seeds.
$0.52 in total (each capped at $0.50).

**6a. Passes or capacity?** The same conversations summarized *live* (as they
grow: facts pass through 1–4 summaries) or *once* (a single summary of
everything at probe time). If loss comes from each pass, "once" keeps old
facts; if the summary simply has no room, it loses them too.

| | early facts | mid | late | all |
|---|---|---|---|---|
| live, value present | 8/24 | 20/30 | 18/18 | 0.639 |
| once, value present | 22/24 | 28/30 | 16/18 | 0.917 |
| live, value attached to its subject | 8/24 | 20/30 | 17/18 | 0.625 |
| once, value attached | 19/24 | 22/30 | 13/18 | 0.750 |

- **Old facts are lost to repeated passes, not to lack of room**: a single
  pass over the whole conversation kept 19–22 of the 24 early facts that
  incremental summarizing lost (8/24). Live recall by summaries survived:
  1 → 17/18, 2 → 13/17, 3 → 7/20, 4 → 8/16.
- **One big pass has its own cost**: it keeps values but detaches them
  (92% present vs 75% attached — the only run where the two oracles differ
  much), and it loses more late facts (13/18 vs 17/18). Overall (strict)
  once vs live: +12.5 points, interval [−3.5, +27.7], not decisive.
- So both mechanisms exist, at different ages: each summary pass drops some
  of what the previous one kept (compounding for old facts), and a summary of
  a lot of material at once blurs which value belongs to what.

**6b. Does repetition itself protect a fact?** Plain facts only, with and
without a later restatement ("To repeat what was said earlier: …", 5–30
exchanges after). The facts, values, positions and filler are identical;
only the 24 restatements differ.

- 23/72 → 41/72 kept: **+25 points, interval [+11.7, +36.9]**. By summaries
  since the first mention: 3 → 0/20 vs 10/19, 4 → 0/16 vs 3/24.
- Caveat: the restatement is also a *later* copy, so part of the gain is that
  the latest mention went through fewer passes. Separating the two needs the
  restatement in the same summary window as the original.

## 2026-09-27 — Pilot 7a: a state-and-index instruction

**Command:** `uv run crucible compaction-eval --budget 1.4 --no-baseline -t 8000 -s gemini-3.5-flash-lite -s gemini-3.8-flash --assistant-facts 0.5 -m gpt-6-luna --instruction state --recall none --out experiments/results/pilot7a-state-2026-09-27.json`
Same scenarios as pilot 5 (half the facts stated by the assistant); brief
and handoff rows are pilot 5's. Spent $1.03 against an in-run estimate of
$0.58 — beyond the ×1.35 planning factor; a separate estimate an hour
earlier had said $0.97. One calibration call per condition is too noisy for
the estimate; the hard cap is what bounds a run.

`StateAndIndex` asks for what cannot be recovered otherwise: every decision,
agreed value, constraint and open item with who stated it, only the latest
value of anything changed, and a one-line index of topics.

| summarizer | instruction | user-stated | assistant-stated | gpt-6-luna | summary | read per probe |
|---|---|---|---|---|---|---|
| flash-lite | brief | 17/36 | 14/36 | 27/72 | 5.6k | 5.8k |
| flash-lite | handoff | 7/36 | 2/36 | 9/72 | 0.9k | 2.1k |
| flash-lite | **state** | **35/36** | **35/36** | **69/72** | 10.2k | 10.9k |
| 3.8-flash | brief | 36/36 | 36/36 | 72/72 | 7.8k | 9.5k |
| 3.8-flash | handoff | 36/36 | 34/36 | 70/72 | 1.3k | 3.7k |
| 3.8-flash | **state** | 36/36 | 36/36 | 72/72 | **5.7k** | **7.7k** |

(strict oracle)

- **The instruction decides what a weak summarizer keeps.** Asked for "a
  concise, detailed technical brief", flash-lite kept 31/72; asked for every
  decision and current value, 70/72. It did so by writing twice as much:
  the gain costs context on every later call (10.9k vs 5.8k per probe).
- With gemini-3.8-flash the state instruction keeps everything with smaller
  summaries than the brief (5.7k vs 7.8k): the best retention per token read
  in these runs apart from the handoff, which loses a little.
- Combined with pilot 6: loss comes from what each pass chooses to drop, and
  telling the summarizer *what kind* of thing must survive (values,
  decisions, who said them) changes that choice far more than the choice of
  a cheap model does.

## 2026-09-27 — Pilot 7b: bringing hidden messages back (recall)

**Command:** `uv run crucible compaction-eval --budget 3.2 --no-baseline -t 8000 -s gemini-3.5-flash-lite -s gemini-3.8-flash --assistant-facts 0.5 -m gpt-6-luna --instruction brief --instruction handoff --instruction state --recall keyword --out experiments/results/pilot7b-recall-2026-09-27.json`
(A first attempt with a $2.60 cap was refused by the budget check: the
re-calibrated estimate plus margin was $3.01.) Estimated $2.07 + $0.10
calibration, spent $2.18. Rows without recall are pilots 5 and 7a.

`KeywordRecall`: before each call, the up to 4 hidden messages (pruned, not
in the retained window) sharing the most distinctive words with the latest
user message come back as a quoted excerpt, oldest first.

| summarizer | instruction | recall | strict oracle | gpt-6-luna | read per probe |
|---|---|---|---|---|---|
| flash-lite | brief | – | 31/72 | 27/72 | 5.8k |
| flash-lite | brief | keyword | **67/72** | **67/72** | 5.3k |
| flash-lite | handoff | – | 9/72 | 9/72 | 2.1k |
| flash-lite | handoff | keyword | **66/72** | **66/72** | **2.8k** |
| flash-lite | state | – | 70/72 | 69/72 | 10.9k |
| flash-lite | state | keyword | 72/72 | 72/72 | 11.7k |
| 3.8-flash | brief / handoff / state | – | 72 / 70 / 72 | 72 / 70 / 72 | 9.5k / 3.7k / 7.7k |
| 3.8-flash | brief / handoff / state | keyword | 72 / 72 / 72 | 72 / 72 / 72 | 7.9k / 3.7k / 7.8k |

- **Recall rescues lossy summaries**: flash-lite brief +50 points
  ([+36, +61]), handoff +79 points ([+66, +86]). Where the summary already
  kept everything, recall changes nothing (equivalent within ±0.1).
- **The cheapest configuration that keeps ~all detail**: flash-lite writing
  1k-token handoffs plus recall — 66/72 while every later call reads 2.8k
  tokens, a third of what a detailed brief costs to carry.
- This is the "never let the summary be the only copy" principle measured:
  once the original is reachable, the summary only has to be good enough to
  continue from, not a complete record.
- Caveat: probes name their subject, which is kind to keyword search; real
  follow-up questions are vaguer. Embedding search or a model-driven lookup
  (using the summary's index) is the next test, as are real conversations.

## 2026-09-28 — Toward the read side: indirect questions (retrieval, offline)

The research question moves from *how well* a summary keeps detail (a
capability question, redone for every model) to *when* the relevance
decision is made. Compaction decides what matters before the question
exists; recall decides at read time, but then has to know what to fetch.

`--questions indirect` asks by what a subject does instead of its name
("Which network port should the firewall allow for the task that clears
cached files at the edge?" instead of "Which port does the CDN purge job
listen on?"). No subject word appears in any indirect question
(`probe.SUBJECT_DESCRIPTIONS`). `EmbeddingRecall` ranks hidden messages by
cosine similarity with the app's local embedding model (all-MiniLM-L6-v2).

Retrieval alone, no model calls: over each full conversation (280 messages,
half the facts stated by the assistant), is the message that stated the fact
among the top 4 for its question?

| | direct question | indirect question |
|---|---|---|
| KeywordRecall | 66/72 | **24/72** |
| EmbeddingRecall (MiniLM) | 27/72 | 22/72 |

- Taking away the subject's name cuts keyword retrieval to a third.
- The small embedding model is weak even for direct questions: every
  message in these conversations has the same shape (subsystem + metric), so
  sentence embeddings barely separate them. Retrieval quality, not storage,
  becomes the bottleneck once originals are kept.
- Pilot 8 (below) measures how this turns into lost answers.

## 2026-09-28 — Pilot 8: who has to understand the question

Same scenarios as pilots 5/7 (half the facts assistant-stated), t=8000,
gpt-6-luna answering (gemini-3.8-flash also answered the first run). Runs:
`pilot8a` (indirect: full history + flash-lite handoff with keyword or
embedding recall, luna and 3.8-flash; stopped at its $3.00 cap after $3.04,
recall conditions incomplete), `pilot8a2` (indirect recall conditions again,
luna only), `pilot8b` (indirect, 3.8-flash state summaries), `pilot8c`
(direct, embedding recall). Direct keyword and direct state rows are pilots
7b/7a. About $4.2 in total (cap $10). The first run's estimate was $1.81:
gemini-3.8-flash as an answering model reasons a very variable amount per
call, which the one-call calibration cannot see.

| gpt-6-luna recall (strict oracle in brackets) | direct | indirect |
|---|---|---|
| Full history, no compaction | – | 68/72 (72/72); gemini-3.8-flash 62/62 |
| flash-lite handoff + keyword recall | 66/72 (66) | **28/72** (29) |
| flash-lite handoff + embedding recall | 27/72 (29) | 32/72 (33) |
| gemini-3.8-flash state summary, no recall | 72/72 (72) | **72/72** (72) |

- Keyword recall: direct → indirect −53 points ([−64, −39]). Embedding
  (MiniLM) recall is poor either way (no detectable difference).
- With indirect questions, a strong state summary beats summary + keyword
  recall by 61 points ([+49, +72]).
- **When the model sees the facts, wording doesn't matter**: with the full
  history or a complete summary, luna maps "the task that clears cached files
  at the edge" to the CDN purge job almost every time. The model can make the
  relevance decision at read time.
- **Recall moves that decision to the retriever**, and a lexical or small
  embedding retriever is far weaker at it than the model. Lazy recall only
  beats eager summarizing if whoever chooses what to fetch understands the
  question as well as the model does.
- So both families fail by capability, in different places: an eager summary
  by the summarizer (compounding per pass), lazy recall by the retriever.
  The structural part — facts that are unremarkable when stated and needed
  later — is still untested: every fact here is salient, which is why a
  complete summary kept them all.

Next: model-driven lookup (the answering model sees the summary's index and
names what to fetch) against keyword/embedding recall, and "sleeper" facts
that read like filler when stated.

## 2026-09-28 — Pilot 9: let a model decide what to fetch

**Command:** `uv run crucible compaction-eval --budget 1.0 -m gpt-6-luna --assistant-facts 0.5 -t 8000 --questions indirect --no-baseline -s gemini-3.5-flash-lite --instruction index --instruction handoff --recall keyword --recall guided --out experiments/results/pilot9-guided-2026-09-28.json`
Estimated $0.24, spent $0.32.

`GuidedRecall`: before each call, gpt-6-luna reads the visible summary and
the question and names what to search for; keyword recall then uses those
terms. `IndexOnly` summaries only list the topics that came up.

| indirect questions (gpt-6-luna; strict oracle) | keyword recall | guided recall |
|---|---|---|
| flash-lite index-only summary (median 168 tokens) | 19/72 (16) | **49/72 (51)** |
| flash-lite handoff (median ~1k tokens) | 28/72 (28) | **54/72 (55)** |
| reference: direct questions, handoff + keyword (pilot 7b) | 66/72 | – |

- Handing the relevance decision back to a model recovers most of what
  indirect wording cost: +42 points ([+28, +53]) with an index, +36
  ([+23, +47]) with a handoff. It does not fully close the gap to direct
  questions (55 vs 66).
- flash-lite's "index" was tiny (168 tokens for ~40 subjects), so it likely
  left subjects out; the rewriter cannot name what the index never
  mentioned. A complete index is the obvious next check.
- Cost stays low: the rewrite call reads the summary and the question
  (luna input per probe 3.7k–6.1k tokens, rewrite included).

## 2026-09-28 — Pilot 10: facts stated as throwaway remarks ("sleeper" test)

**Commands:** `pilot10a/b` with `--asides --fact-variants plain`, `pilot10c/d`
the same without `--asides` (10c/10d on their own databases, run in
parallel); gpt-6-luna answering, half the facts assistant-stated, t=8000.
Spent $0.62 + $0.50 + $0.72 + $0.51. A first 10c attempt hit the Google
project's monthly spending cap: every summary failed with 429, the app
carried on without summaries, and the run was discarded. Experiments now
halt on any failed model call (`Spend.errors`).

`as_asides` restates each fact as a throwaway remark ("(Side note, probably
irrelevant: the staging database listens on port 6543.)"); values, subjects,
positions and filler are identical, so plain and aside runs pair by fact.

| strict oracle | plain | aside | paired plain → aside |
|---|---|---|---|
| full history | 72/72 | 72/72 | equivalent |
| flash-lite brief | 16/72 | 23/72 | no detectable difference (luna: +14 [+5, +23]) |
| flash-lite handoff | 1/72 | 18/72 | **+24 [+13, +35]** |
| flash-lite brief + keyword recall | 68/72 | 67/72 | equivalent |
| flash-lite handoff + keyword recall | 69/72 | 67/72 | equivalent |
| 3.8-flash state-and-index | 72/72 | 72/72 | equivalent |

- **The prediction failed.** Sounding unimportant did not make a fact more
  likely to be dropped; with a lossy summarizer, asides survived *more*
  often. The strong summarizer and recall kept everything either way.
- Likely reason: in filler where every sentence has the same shape, an aside
  ("Side note, probably irrelevant: …") is *more* distinctive, not less.
  Surface hedging is not low salience for an LLM. This manipulation did not
  produce sleeper facts, so the structural question is still open.
- A better sleeper design ties salience to the *task* rather than to wording:
  give the conversation a goal, plant facts that are off-goal when stated,
  and later make them matter. A task-focused summary (e.g. Codex's handoff)
  should drop exactly those.
- Aside: flash-lite handoffs keep almost no plain details (1/72), fewer than
  with mixed variants (9/72 in pilot 5): a handoff summary is a pointer, not
  a record, and needs recall behind it.

## 2026-09-28 — Cost: prompt caching was defeated by a timestamp

Recorded experiment spend at official prices: Google $40.2, Anthropic $9.2,
OpenAI $3.3 (plus ~$5–7 of unrecorded Gemini calls: the stopped length run,
calibrations, one-off checks) — consistent with the Google bill of about
NT$1,500. Roughly $20 of the Gemini spend was avoidable (the re-summarize
thrash and the $9/1M-output gemini-3.5-flash at full thinking).

Cache hits across pilots 5–10 were ~1%: every drafting call began its system
prompt with the current time to the second, so no two calls shared a prefix.
The time (and recalled excerpts) now ride with the latest user message
(`graph._with_request_notes`), and a test keeps the prefix stable.

One conversation, no compaction, before → after:

| model | cache hits before | after |
|---|---|---|
| gemini-3.5-flash-lite | 0% | **76%** (billed at 1/10) |
| gpt-6-luna | 0% | 0% |

gpt-6-luna is provider behaviour, checked directly: a long *single* system
message is cached on the second call (7,722 of 7,732 tokens), but the same
text as a ~120-message conversation is never read from cache (cache writes
reported every time, 0 cached, with gaps of 3–15 s). Not something the app
can fix without flattening history into one message.

## 2026-09-28 — Prompt caching per provider (verified)

Each provider caches a different way; one message layout does not suit all.

- **OpenAI, GPT-5.6+ (gpt-6-luna)** — official docs: in the default
  implicit mode the API places a cache breakpoint at the end of the latest
  user message (and after the initial developer block); cache writes cost
  1.25× input. Growing three-turn conversation, ~7k-token prefix:

  | per-request context (time, excerpts) | turns 2–3 |
  |---|---|
  | none | 7,041 / 7,067 tokens read from cache |
  | inside the user message | **0 read, full prefix re-written every turn (1.25×)** |
  | its own trailing system message | 7,075 / 7,118 read |

  So with the context inside the user message, OpenAI calls cost *more* than
  with no caching. `CachingChatOpenAI` moves the per-request block into a
  trailing system message (not a breakpoint position); through the app's
  own assembly: 0 → 6,989 → 7,028 tokens read.
- **Anthropic** — no caching without a `cache_control` marker.
  `CachingChatAnthropic` marks the last block the next turn will repeat (the
  question, not the per-request block after it); claude-haiku-4-5 reads
  7,403 → 7,442 tokens per turn and writes only the ~40 new ones. A marker
  on the per-request block wrote every turn and never read.
- **Gemini** — implicit prefix caching, no markers; hits are probabilistic
  (76% over 24 consecutive probes, 0 over three quick calls).
