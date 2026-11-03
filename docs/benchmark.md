# What survives compaction: a benchmark you can re-run

When a conversation outgrows a model's context, something has to give: older turns are summarized, pruned, or both. This benchmark measures what a compaction setup loses, fact by fact, so you can check a summarizer, a summary instruction, a retention rule or a recall mechanism on today's models and again on whatever comes next.

It is the instrument behind the research in [`backend/experiments/NOTES.md`](../backend/experiments/NOTES.md). The numbers there are dated and tied to the models of their day; the harness, the scenarios and the oracles are what this page is about. Everything runs from `backend/` through the `crucible` command, against a separate database, never the app's own.

- [What it measures](#what-it-measures)
- [The pieces](#the-pieces)
- [Running it](#running-it)
- [What a results file holds](#what-a-results-file-holds)
- [How long a result lasts](#how-long-a-result-lasts)
- [What has been found so far](#what-has-been-found-so-far)
- [Limits](#limits)
- [Your own conversations](#your-own-conversations)
- [Coming next](#coming-next)

## What it measures

Facts are planted in a long synthetic conversation: a budget cap, an on-call reviewer, a port, a key label, a date, a vendor choice, something the team agreed *not* to use. The conversation is run through the app's own summarize-and-prune step, then each fact is asked about. A fact counts as kept if the answer is right.

Two sides of compaction are measured:

- **The write side: what a summary keeps.** Which facts survive one summary, and several in a row; whether the summarizer, its instruction or the summary's length decide it; whether a value that was later changed comes back as the old one.
- **The read side: what recall brings back.** Once history is pruned, the originals still exist. A recall step can show the relevant ones again for the current question. Then the question is who decides what is relevant (word overlap, an embedding, a small model), and whether that works when the question doesn't use the fact's words.

One principle ties the results so far together (from the notes): every loss measured was information whose only copy was a summary. The benchmark is built to find where that happens and what prevents it.

## The pieces

The design lives in [`backend/app/compaction/`](../backend/app/compaction), which imports nothing from the rest of the app (a test enforces it), so it can be lifted out whole. The host side, which runs the scenarios through the app's real LangGraph workflow, is [`backend/app/services/compaction_eval.py`](../backend/app/services/compaction_eval.py).

### Scenarios

Every scenario is generated from code and a seed: the same seed gives the same conversation, facts and positions on any machine. There is no data file to download; the published set is the generator plus the seeds a run records.

**`--scenario dense`** (`build_dense_scenario`, the default). About 140 exchanges (~23k tokens) about the subsystems of a fictional product. Every turn carries specifics of the same shape as the facts (other numbers, names, ids), so the planted facts are not the only concrete content. By default 24 facts per conversation, cycling through eight kinds (number, name, identifier, negation, date, port, quote, choice), planted between 8% and 88% of the way through, buried mid-message (summaries tend to keep openings). Fact attributes never appear in the filler, and filler values come from separate pools, so every question has exactly one right answer. Variants:

- *plain*: the fact is stated once.
- *distractor*: a rejected proposal with another value is planted nearby ("Someone proposed capping the budget … at 41,800 euros, but that was turned down").
- *update*: an older value is planted earlier and the fact states the new one. An answer that gives a rejected or superseded value is scored wrong and counted as `stale`.

Options that change only one thing, so a run with and without them pairs fact by fact:

- `--assistant-facts 0.5`: half the facts are stated by the assistant instead of the user (needed whenever a condition keeps user messages verbatim, or that condition wins by construction).
- `--questions indirect`: ask by what a subject does instead of its name ("the task that clears cached files at the edge" instead of "the CDN purge job"); no subject word appears in an indirect question. This is what separates a retriever that matches words from one that understands the question.
- `--asides`: state each fact as a throwaway remark ("Side note, probably irrelevant: …").
- `--repeat-facts`: restate each fact once more later, same value.
- `--fact-variants plain`: plain facts only.

**`--scenario task`** (`build_task_scenario`). One stated goal, eight facts about it and eight about a subject nobody is working on yet (stated plainly, mentioned nowhere else), then a change of plans to that subject. Relevance is set by the task, not by wording: an off-goal fact reads exactly like an on-goal one when it is stated. Facts carry the variant `on-goal` or `off-goal`. `--later-subject` sets what the goal reminders say about the subject the conversation will switch to: `unknown` (nothing), `announced` (it is the next priority, and the switch arrives as planned) or `mentioned` (named as often, but as out of scope, and the switch is a surprise). Facts, filler and positions are identical across the three for a seed, so they pair. `--questions indirect` and `--assistant-facts` work here too.

**`--scenario basic`** (`build_scenario`). Pilot 1's generic filler around eight hand-written facts. Kept for reproducing it; the planted facts are the only specific content, so any competent summarizer keeps them all (it hit a ceiling).

Answers are scored on the committed answer, the reply's first non-empty line: models often answer and then quote the source, and the quote may name the rejected values.

### Oracles

Two pseudo-models answer every probe alongside the real ones, at no cost:

- **`oracle`** answers correctly if and only if the right value is anywhere in the context it was given.
- **`oracle-strict`** also requires the value to be attached to its subject (`probe.value_attached`): on a line that mentions the subject, or with this subject as the nearest one mentioned before it (inside that subject's section, however long). A summary can keep "5592" and lose that it was the CDN purge job's port; the strict oracle catches that.

The oracles measure what compaction *removed*, independently of whether a reader would notice what is left. A real model scoring below the oracle missed something that was still there (attention); the oracle scoring low means the summary dropped it. That is why most results below are oracle results: they don't depend on a particular reader's attention, only on what the summarizer and the recall step did. The oracle learns which fact a probe asks from the run's metadata, not from the request text (see [one settled checkpoint](#every-probe-forks-from-one-settled-checkpoint)).

### Conditions

A condition is one way of compacting, and every condition answers the same probes on the same conversation, so conditions pair fact by fact:

| Part | Options | Default |
|---|---|---|
| When to summarize | `-t` threshold in tokens (repeat for several); `--baseline` adds "never compact" | 6000 (dense and task; the pilots from 2 on used `-t 8000`, except the horizon runs at 4,000); baseline on |
| Who summarizes | `-s <model>` (repeat); a Gemini model takes a thinking level, e.g. `gemini-3.5-flash@minimal` | the app's default summarizer |
| What it is asked | `--instruction brief` (the app's), `handoff` (Codex CLI's compaction prompt), `state` (current state plus an index), `index` (topics only), `allsubjects` (brief plus "priorities may change, keep every subject"); `-l <tokens>` adds a length target | brief, no length limit |
| What stays verbatim | `--keep recent` (the last 5 messages), `--keep user` (also every user message within `--user-budget`, as Codex CLI does) | recent |
| What comes back | `--recall none`, `keyword` (word overlap), `embedding` (a local embedding model), `guided` (a model reads the summary and the question and names what to search for; `--rewriter <model>`); `--excerpt message` or `sentences` | none |

The summarize threshold is a *re-summarize* rule too: a new summary waits until enough new material has arrived (at least half the threshold), so a summary larger than the threshold does not trigger itself on every turn.

### Live or once

- **`--compaction live`** (the default, `run_live_grid`): the conversation is replayed turn by turn through the graph's own summarize step, so it is summarized several times as it grows, the way the app does it. This is the setting where loss compounds. The replay is computed once per scenario and condition and shared by every answering model, so all readers see the very same summaries. Thresholds are evaluated against the first model's budget, so use fixed `-t` values.
- **`--compaction once`** (`run_grid`): the whole conversation is written at once and gets a single summary when probing starts.

Real replays are cached on disk (`experiments/.replay-cache/`, not committed), keyed by everything that shapes the summaries: the conversation, the policy, the summarizer and its catalog identity (release date and the date the catalog was last synced), and the instruction. Question wording, recall and retention act only at answer time, so runs that vary them reuse the same summaries.

### Every probe forks from one settled checkpoint

Before probing, each branch is *settled*: the summarize step runs once more, as the app would when the first question arrives (a fixed-length placeholder stands in for the question; only its length decides whether a summary is due). Then every probe forks from that one checkpoint, on its own branch, under a policy that prunes as the condition says but never summarizes. A probe that writes a summary is an error.

This rule exists because the harness used to get it wrong ([Harness bias, 2026-10-25](../backend/experiments/NOTES.md#2026-10-25--harness-bias-chained-probes-and-the-oracles-question-matching)). Probes were asked in a chain on one branch, so earlier questions and answers became history. A verbose reader's answers pushed the branch past the threshold again, so summaries were written *while probing* (9–16 per cell for Claude Haiku 5.5, 0–2 for the oracles), and recall then brought an earlier probe of the same kind back into the request. Worse, the oracle chose which fact was asked by matching question text in the latest message, which now carried that recalled earlier probe, so it answered the earlier fact's value. The fix forks every probe from the settled checkpoint and gives the oracle the fact from run metadata. Every run before that fix chained its probes; recall conditions and verbose readers are biased in a direction that depends on the condition, and `--rescore` bounds how much (below).

### Judging

Two conditions are compared per answering model with a paired test on the same facts (Ordal's `PairedProportionRule`: Newcombe's paired score interval for the difference). `--min-effect` (default 0.1, ten points) is the smallest difference that matters. Outcomes: `b_better`, `a_better`, `equivalent` (the interval lies inside ±min-effect) or `no_detectable_diff`.

## Running it

```bash
cd backend
uv sync
```

### Free: no model calls

**A dry run** answers with the oracles only and summarizes with `first-sentence-summarizer`, a deterministic stand-in that keeps the first sentence of every message. Facts are buried mid-message, so it drops nearly all of them: it is a lossy summarizer by design, for checking the pipeline and for measuring recall mechanisms that contain no model.

```bash
uv run crucible compaction-eval --dry-run --seeds 1 -t 8000
uv run crucible compaction-eval --dry-run --seeds 1 -t 8000 --no-baseline --recall none --recall keyword --recall embedding
uv run crucible compaction-eval --dry-run --scenario task --seeds 2 -t 8000 --no-baseline --recall none --recall keyword --questions indirect --out dry-task.json
```

With seed 0 the second command gives, for both oracles: 2 of 24 facts with no recall, 22 of 24 with keyword recall, 12 of 24 with embedding recall. That is a sanity check of the stand-in (it should lose almost everything, and recall over the kept originals should bring most of it back), not a finding. `--recall embedding` runs the app's local embedding model (all-MiniLM-L6-v2, downloaded from Hugging Face on first use). Leave `--recall guided` out of dry runs: its rewriter is a model, which the dry run replaces with the same first-sentence stand-in, so its numbers there mean nothing.

The other stand-in, `sized-summarizer`, writes a summary of a fixed size; `--estimate` uses it to count what each probe will read and how many summaries a run will write. It is not selectable as a summarizer.

**Rescoring stored results** reads a results file or a recorded audit and reports each cell as recorded and within bounds for the [harness bias](#every-probe-forks-from-one-settled-checkpoint): a wrong answer that gives another fact's value from the same scenario is flagged, then left out (lower bound) or counted correct (upper bound); "unaffected" keeps only probes answered before any summary was written while probing. Files are read, never changed.

```bash
uv run crucible compaction-eval --rescore experiments/results/pilot22b-summarizers-task-2026-09-28.json
uv run crucible scaffold-audit --rescore experiments/audit/runs/scaffold-audit-20261025T053017.json
uv run crucible scaffold-audit --report    # the latest recorded verdict per scaffold and reader, and whether it is stale
```

`--rescore` works on the result files from pilot 2 on; pilot 1's file predates the recorded scenario option. `--report` decides staleness against the summarizer and recall model *your* keys select, so without keys it says the recall model changed.

### Paid: estimate first, then a budget

A real run calls models. Every real run needs `--budget` in USD; `--estimate` only estimates. The estimate calibrates each model with one or two real calls (a few cents, cached for the day), dry-runs every condition with a stand-in summary of the calibrated size to count exactly what each probe reads and how many summaries are written, and multiplies by a planning margin learned from past result files in `experiments/results/` (the 90th percentile of actual over estimated cost, never below 1.35). A run refuses to start if the estimate with margin exceeds the budget, runs conditions one at a time, cheapest first, starts a condition only if the budget left covers it, saves `--out` after each, and stops starting calls once the budget is spent. A failed model call stops the run, and the request is saved under `experiments/.failures/` (not committed) for you to read rather than resend.

```bash
uv run crucible compaction-eval --estimate --scenario task --questions indirect --seeds 4 -t 8000 \
  -s gpt-6-luna --recall none --recall guided -m oracle-strict
uv run crucible compaction-eval --budget 2 --scenario task --questions indirect --seeds 4 -t 8000 \
  -s gpt-6-luna --recall none --recall guided -m oracle-strict \
  --out experiments/results/my-task-run.json
```

The answering models default to the cheapest offered model of each provider, so with keys for fewer than all four providers name your readers with `-m`, or answer with the oracles only (`-m oracle-strict`; both oracles are added unless `--no-oracle`). Every model named, the summarizer, and the guided-recall rewriter (`--rewriter`, default GPT-6 Luna) needs its provider's key.

### `scaffold-audit`: does each mechanism still earn its place?

Every mechanism between the conversation and the model declares the baseline it has to beat and its claim, and the audit re-measures each pair on current models (dense scenario, half the facts stated by the assistant, 24 facts, `--seeds 2` conversations, `-t 8000` by default):

| Scaffold | Baseline | Claim |
|---|---|---|
| `compaction` | never compact | `non_inferior`: kept for cost, it only must not lose detail |
| `verbatim-window` | no recent messages kept | `improves` |
| `recall` (only when a key allows the app's recall model) | no recall | `improves` |
| `state-instruction` (candidate) | the app's path | `improves` |
| `keep-user-messages` (candidate) | the app's path | `improves` |
| `recall-keyword` (candidate) | the app's path | `non_inferior` with a recall model (a cheaper replacement), else `improves` |
| `summarizer-<model>` (candidate, one per other summarizer with a key) | the default summarizer | `improves`: it has to justify its cost |

Verdicts:

- **keep**: it does what it claims (beats the baseline, or for `non_inferior`, is shown no worse).
- **retire**: an `improves` scaffold measured equivalent to going without; it no longer does what it claims.
- **harmful**: the baseline is detectably better. Reported at any recall level.
- **inconclusive**: not enough evidence either way; keep it and look again.
- **no_headroom**: the probes can't tell: both arms at 0.95 or above, or an `improves` scaffold whose baseline is already there. Equal recall at 1.00 is evidence neither for keep nor for retire.

```bash
uv run crucible scaffold-audit --estimate -m gpt-6-luna
uv run crucible scaffold-audit --budget 3 -m gpt-6-luna
uv run crucible scaffold-audit --budget 1 -m gpt-6-luna --scaffold recall --scaffold compaction
```

Readers (`-m`) default to the cheapest offered model of each provider, and the strict oracle always answers too. A real audit writes every probe to `experiments/audit/runs/<run>.json` and appends one line per scaffold and reader to [`experiments/audit/history.jsonl`](../backend/experiments/audit/history.jsonl), stamped with the date, the commit, the summarizer, the recall model, the threshold, the seeds and the cost, so the verdicts form a curve across model generations. When `uv run crucible catalog-sync` finds models added or changed, it prompts a re-audit. Re-running the audit in your own clone appends your verdicts to that same committed file. The audit only protects what the probes measure (detail recall), not tone, refusals or latency.

## What a results file holds

`--out` writes one JSON file: the run id, the models, every option (so `--rescore` can rebuild the scenarios), the recall per condition and model, every pairwise comparison, token usage, the spend against the budget, and every probe:

- `condition`, `model`, `scenario` (the seed), `fact`, `kind`, `variant`, `stated_by`, `planted_turn`;
- `correct`, `stale`, `answer` (its first 200 characters);
- `pruned` (the call saw summary-jumped history), `summarized`, `compactions` (summaries written after the fact was stated), `summary_tokens`;
- `usage` per model call and `setup_usage` (the replay's summaries, on the first probe of a branch), as raw token counts, so cost can be recomputed with whatever prices apply.

The committed files are in [`backend/experiments/results/`](../backend/experiments/results), one per pilot. The experiment databases and the replay cache, which hold the summaries themselves, are not committed: re-running a pilot pays for its summaries again.

## How long a result lasts

Results differ in how long they stay true, and that decides when they are worth paying for:

- **Tier A, by construction.** A test proves it; no experiment needed. In this benchmark: every probe reads the same settled branch, a probe that summarizes is an error, the oracle answers the fact it is asked and not one quoted in the request, replay keys change with the summarizer's identity, the compaction package imports nothing from the app. In the app: a summary larger than the threshold does not trigger itself, the verbatim window is folded into the next summary, and keeping user messages verbatim keeps every user-stated fact within its token budget through any summary (`backend/tests/test_compaction.py`).
- **Tier B, measured without a language model.** The reader is an oracle, recall is keyword or a local embedding, summaries are stand-ins. No better model can overturn a result about a mechanism that contains no model. So far exactly one finding is in this tier: the offline retrieval check of 2026-09-28 (is the message that stated a fact among the top 4 for its question, over the full conversation?): keyword retrieval found 66 of 72 with direct questions and 24 of 72 with indirect ones; the small embedding model 27 and 22. No command reproduces it yet (see [Coming next](#coming-next)). The dry run is the Tier B instrument.
- **Tier C, invariance across model generations.** A claim that needs a real summarizer or reader, run on the cheapest model of two or three generations in each family: if the effect holds with no trend, it is likely to keep holding; if it shrinks each generation, it is perishable and now its direction is known. **No result is in this tier yet.** Re-running the headline findings this way is roadmap item 23. The cross-family runs below (pilots 14 and 18) span families and tiers, not generations.
- **Tier D, how today's models behave.** Every other number on this page: each pilot and each audit verdict names its models and date and should be re-measured when models change, not quoted as a fact. All of them before 2026-10-25 ran on the harness with chained probes.

## What has been found so far

From the notes' "Conclusions so far" (written 2026-09-28, with later corrections), at pilot scale: synthetic conversations, 2–4 conversations per cell, mostly small and mid-size models, one threshold (8,000 tokens). The labels are the notes' own. Model names are as of each run. All Tier D.

**Solid** (large effects, replicated across runs):

1. With a cheap summarizer, loss compounds with each pass: a fact that went through one summary survived every time, after four summaries none did. ([pilot 2](../backend/experiments/results/pilot2-dense-2026-09-26.json), [2b](../backend/experiments/results/pilot2b-no-thrash-2026-09-26.json), [6a live](../backend/experiments/results/pilot6a-live.json))
2. Bringing hidden originals back with keyword recall rescues lossy summaries: Gemini 3.5 Flash-Lite handoffs went from 9/72 to 66/72, each later call reading 2.8k tokens. ([pilot 7b](../backend/experiments/results/pilot7b-recall-2026-09-27.json))
3. Gemini 3.8 Flash summarizes as well as Gemini 3.5 Flash at about 1/6 of the cost per summary. ([pilot 4](../backend/experiments/results/pilot4-flash38-2026-09-27.json))
4. Keeping user messages verbatim (Codex CLI's rule) rescues exactly the user-stated facts and nothing else, at 2.3× the context per call. ([pilot 5](../backend/experiments/results/pilot5-codex-style-2026-09-27.json))

**Likely** (clear effects, small scale):

5. Most loss is in the summary, not in the reader's attention; with a weak summarizer, readers also missed about 14% of facts that did survive. (pilot 2b, strict rescore)
6. For small models a good summary beats the raw history: in a 23k-token transcript they often gave superseded values, which the summary resolved. (pilot 2)
7. What the summarizer is asked to keep matters as much as which model it is: a state-and-index instruction took Gemini 3.5 Flash-Lite from 31 to 70 of 72. ([pilot 7a](../backend/experiments/results/pilot7a-state-2026-09-27.json))

**Tentative** (direction visible, not settled):

8. Old facts are lost to repeated passes rather than lack of room, but the overall paired test was not decisive, and one big pass detaches values from their subjects. ([pilot 6a once](../backend/experiments/results/pilot6a-once.json))
9. A restatement adds 25 points, partly because the restatement is newer and went through fewer passes. ([6b plain](../backend/experiments/results/pilot6b-plain.json), [6b repeated](../backend/experiments/results/pilot6b-repeated.json))

**The read side** (pilots 8–22):

10. With the facts in view, a model answers indirect questions as well as direct ones (68–72/72); keyword recall drops from 66/72 to 28/72 with indirect questions, because the retriever, not the model, now judges relevance. ([8a](../backend/experiments/results/pilot8a-indirect-2026-09-28.json), [8a2](../backend/experiments/results/pilot8a2-indirect-recall-2026-09-28.json), [8b](../backend/experiments/results/pilot8b-indirect-state-2026-09-28.json), [8c](../backend/experiments/results/pilot8c-direct-embedding-2026-09-28.json))
11. Letting a model choose the search terms from the summary recovers most of it (index + guided recall 19 → 49/72; handoff 28 → 54/72), not all. ([pilot 9](../backend/experiments/results/pilot9-guided-2026-09-28.json))
12. Summaries drop what the current task doesn't need, across families, and recall brings it back: after a change of goal, OpenAI and Anthropic summarizers kept 4–13 of 32 off-goal facts (Gemini kept most); recall restored 32/32 for both GPT-6 Sol and Claude Haiku 4.5 summaries. "Not “stronger drops more” — the family's style decides how much." ([11](../backend/experiments/results/pilot11-task-2026-09-28.json), [14](../backend/experiments/results/pilot14-crossfamily-2026-09-28.json), [15](../backend/experiments/results/pilot15-rescue-2026-09-28.json), [16](../backend/experiments/results/pilot16-rescue-xfam-2026-09-28.json)). Pilot 16's probes name their subject, which keyword recall is kind to.
13. Tentative, and a failed prediction: stating facts as throwaway remarks did *not* make summaries drop them. Surface wording is not low salience. ([10a](../backend/experiments/results/pilot10a-asides-lite-2026-09-28.json)–[10d](../backend/experiments/results/pilot10d-plain-strong-2026-09-28.json))
14. Deciding what to fetch does not need a strong model: with indirect questions, guided recall restored 25–31 of 32 off-goal facts whichever of six models chose the terms, against 16/32 for keyword recall; the cheapest matched the most expensive. ([17](../backend/experiments/results/pilot17-rescue-indirect-2026-09-28.json), [18](../backend/experiments/results/pilot18-rewriter-2026-09-28.json)) The notes call the part about *when* the decision is made durable and the part about *which* cheap model suffices perishable; one summarizer, one threshold.
15. Why the summary drops them: it can't know what comes next. With the next goal announced in advance, GPT-6 Sol's summaries kept 30 of 32 off-goal facts instead of 4, at +30% length; naming the subject as often but as out of scope kept 6. Without that knowledge the only fix was to stop compressing (a generic hedge kept 32/32 with summaries 9× longer). A weaker summarizer adds a separate fidelity loss. ([19a](../backend/experiments/results/pilot19a-unknown-future-2026-09-28.json), [19b](../backend/experiments/results/pilot19b-foreshadowed-2026-09-28.json), [20a](../backend/experiments/results/pilot20a-mentioned-brief-2026-09-28.json), [20b](../backend/experiments/results/pilot20b-mentioned-haiku-allsubjects-2026-09-28.json))
16. With recall on, the cheapest summarizer is enough: GPT-6 Luna summaries plus guided recall kept 93/96 (dense) and 62/64 (goal switch) at about 1/25 of Gemini 3.8 Flash's cost per summary. **Weakened on 2026-10-25** (below). ([22a](../backend/experiments/results/pilot22a-summarizers-dense-2026-09-28.json), [22b](../backend/experiments/results/pilot22b-summarizers-task-2026-09-28.json))

### The 2026-10-25 correction

Rescoring every stored probe for the harness bias, with no model call, changed these:

- **Retracted:** Claude Haiku 4.5's summaries being "harmful" (both audits); Gemini 3.8 Flash's path ending below GPT-6 Luna's on the strict oracle, and the "unexplained gap" behind it (pilot 22, second audit); recall or the alternative summarizers lowering Gemini 3.1 Flash-Lite as a reader; Claude Haiku 5.5 reading compacted context poorly, and GPT-6 Luna's summaries being the worst for it.
- **Stands:** recall is essential (keep in every run and every bound); compaction is never shown harmful outside the confounded reader; Claude Haiku 5.5 as the Anthropic-only summarizer, now on price alone.
- **Weakened:** GPT-6 Luna as the default summarizer. Within the rescored bounds Gemini 3.8 Flash is best on both scenarios, and Luna misses equivalence on the goal switch by 0.01–0.02 of the ±0.1 margin, 2 facts in 64. Read literally, pilot 22's pre-registered rule now picks Gemini 3.8 Flash. Luna stays the default on cost, not on the rule; on 2026-11-01 that was decided without a re-test (a re-test could at best show Gemini 3.8 Flash a few facts ahead, at 17–30× the price per summary).
- Pilots 8a, 15 and 17 also had earlier-sibling answers, all in recall conditions: they understated recall, so their conclusions only get stronger.

The verdicts in `history.jsonl` are left as they were run; `--rescore` reproduces the corrected tables.

### Audits so far

Four runs, all on dense seeds 0 and 1 at 8,000 tokens, recorded in [`history.jsonl`](../backend/experiments/audit/history.jsonl) with their per-probe files in [`audit/runs/`](../backend/experiments/audit/runs) (the first audit kept none). Since GPT-6 Luna became the summarizer (the last three runs), recall is **keep** for every reader, as recorded and within the rescored bounds: without it the app's path kept 0.31–0.46 of the facts, with it 0.75–1.00 as recorded. In the first audit, with Gemini 3.8 Flash summaries that already kept most facts, it was keep for GPT-6 Luna as the reader and inconclusive for the others. Most other rows are two arms at 0.98–1.00, which the current rules call no_headroom: the probes were too easy for the readers that matter. Every Claude Haiku 5.5 reader verdict is confounded (9–16 summaries written while probing each of its cells) and describes neither direction.

## Limits

From the notes, and still true of the harness:

- **Synthetic conversations only**, and 24 (dense) or 16 (task) facts per conversation, 2–4 conversations per cell.
- **Probes are clustered.** The facts of one conversation share one chain of summaries, but the paired interval treats every probe as independent, so the intervals are too narrow; the effective sample is closer to the number of conversations. Pilot 22's knife-edge is inside that error.
- **The same two seeds every audit.** Audits are not independent replications: a quirk of one conversation repeats in every audit and reads as a stable result.
- **No multiple-comparison correction.** An audit judges 18–24 scaffold × reader pairs; at a 95% level about one verdict per audit is expected by chance.
- **An 8,000-token threshold against real soft limits of 70K–800K.** At 8K a summary covers a few dozen turns; in the app it covers hundreds. With most arms at 0.98–1.00 on the dense scenario, the probes are too easy for strong readers.
- **Direct probes name their subject**, which favours keyword recall.
- **Reader results across 2026-10-25 are not comparable.** Until then every answering call carried the app's old system prompt (a research-assistant persona and a request for a self-assessed confidence); readers no longer get it. Compare arms within one run, or re-run the baseline. Replays are unaffected.

The notes' next steps for the harness (more conversations per cell with seeds rotated between audits, cluster-bootstrap intervals over conversations, Holm correction within an audit, a threshold near a real soft limit, the goal switch with indirect questions in the audit) are not in the code yet. No paid run should be based on code from before the 2026-10-25 fix.

## Your own conversations

The roadmap's plan for this benchmark includes real long conversations replayed through `run_live_grid`. A person's own conversations are personal data, so none are published: **the published set is the synthetic scenarios**, regenerated from their seeds.

Replaying your own thread locally is possible from Python, not from a command. `run_live_grid` takes a `Scenario`, and a real thread has no planted facts to ask about, so it takes two things no command provides today:

1. **Your thread as a `Scenario`**: its turns, in order (`crucible messages --thread <id> --format json` prints the path you see in the chat view).
2. **Your probes**: for each detail you want to check, a `PlantedFact` with the question, the accepted answers, any values that were superseded (`stale`), its subject for the strict oracle, and the statement as it appears in a turn, with its position in `Scenario.positions`.

With those, the oracles, every condition and the paired comparisons work as on the synthetic scenarios. Keep everything local: the experiment database, the replay cache and the results file all hold your conversation's text, and only the first two are kept out of git by default. A real run sends your conversation to the summarizer's and readers' providers, as the app does.

## Coming next

Four pieces are being added for Tiers A and B (roadmap items 18–21). Until they land, this section is a placeholder; the commands and options will be documented here.

> **Pinned constraints (item 18).** *Not yet in the code.* A retention that keeps process constraints ("never touch X") verbatim outside the summary, tested with the oracle on cached and stand-in summaries.

> **What recall brings back, with no model in the loop (items 19 and 20).** *Not yet in the code.* For keyword and embedding recall: the precision of each recall, its false positives, and how often a superseded value comes back; then dated or "superseded" notes. Harder facts, reworded so they share no words with the question, to show which recall mechanisms depend on shared words. An oracle that checks a fact *and* the reason attached to it.

> **Recall with a summarizer that isn't a model (item 21).** *Not yet in the code.* How much of what a stand-in summarizer drops does recall bring back: a lower bound for "with recall, the summary only has to point to the originals" that no model generation can move.
