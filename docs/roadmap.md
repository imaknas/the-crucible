# Roadmap

What comes next, in order. It grew out of a survey (November 2026) of about forty multi-model chat front-ends, comparison and evaluation tools, branching and canvas chats, debate and council projects, and the research on multi-agent debate and context compaction. Two parts of The Crucible had no close equivalent:
- the research layer (automatic query-driven recall, the strict oracle, the goal-change experiments, `scaffold-audit`);
- a debate that maps arguments instead of declaring a winner.

Most of this plan deepens those two. The rest borrows what other tools do well.

Every item that changes what the web UI does to a conversation also lands in the CLI and the MCP server (`tests/test_parity.py`), with tests and a line in `CLAUDE.md`. Paid model calls happen only in Phase 7's Tiers C and D: each starts with `--estimate` and runs only within an agreed budget.

## Phase 1 — Debate grounded in the research, and what each answer costs

Cheap changes that answer published criticism of multi-agent debate, plus the numbers every comparison is missing.

1. **Default to 1–2 debate rounds.** The cap stays at 10, which is a spend limit, not advice. The dialog says why longer debates tend toward conformity. Sources: Wynn et al. 2025, "The Cost of Consensus" 2026, FREE-MAD.
2. **Round 1 next to the argument map.**
   - Show the spread of the independent first-round answers.
   - Show who changed position after round 1, and from what to what.
   - The data is already in `debate_rounds()`. Sources: "Debate or Vote" (NeurIPS 2025), FREE-MAD.
3. **De-bias the judge and the synthesizer.**
   - The agreement judge runs twice with the label order reversed; agreement needs both runs.
   - Judge and synthesizer default to a family that is not debating, with a warning when they are a participant.
   - Sources: self-preference (Panickssery et al.), position bias (Shi et al.), lechmazur/debate.
4. **Per-answer metrics on every compare card.**
   - Each card shows time to first token, total time, input, output and reasoning tokens, and cost; the turn shows a total.
   - `stream_end` carries the numbers, and `PriceBook` already prices a reply's usage.
   - Sources: LiteLLM compare, promptfoo, Microsoft Foundry.

## Phase 2 — Reading and combining answers

5. **Diff two answers or two branches.**
   - A "Compare with…" action: sentence-level for prose, structural for JSON and code.
   - Phase 1's "who changed" and Phase 5's replay reuse it.
   - Evaluation tools have this; no chat or canvas tool found does.
6. **Checklist and Compare synthesis.**
   - New `SynthesisFraming`s. Compare builds a table of where the answers differ. Checklist splits the answers into components; the user ticks which to keep, then they are merged.
   - Source: big-AGI Beam.
7. **Synthesize or question any selection of nodes.**
   - Today synthesis takes one turn's answers. This opens it to any nodes, across branches and debate lanes, and lets the user ask a question about the selection.
   - Sources: Flowith Group Nodes, canvas-chat, NotebookLM mind maps.
8. **Anonymous peer review before synthesis, as evidence.**
   - After Arena's independent answers, each model reviews the others anonymously and cannot change its own answer. The ranking is shown beside the synthesis, never as a verdict.
   - Source: llm-council.

## Phase 3 — Nothing lost, nothing hidden

9. **Resumable streams.**
   - A chat turn or a debate keeps running when the tab reloads or the socket drops, and the client reattaches. This replaces today's rule that a run dies with its socket (`interrupted`).
   - Source: LibreChat.
10. **Visible context.**
    - How much of the model's budget the path uses.
    - A marker where history was summarized.
    - The summary itself, viewable and editable.
    - What recall brought back for a turn.
    - Sources: TypingMind, LobeHub.
11. **Show what a branch inherits.** Branching from a node says which messages the next turn will see, and offers "start fresh from here". Sources: TREEGPT, shapeof.ai's branch patterns.

## Phase 4 — Moving around a big tree

12. **Tree navigation.**
    - Keyboard: parent, child and sibling.
    - Bookmarks and branch names.
    - Collapse or hoist a subtree.
    - Compress a subtree into one summary node, using the existing summarizer.
    - Sources: Loom, Canvas Branch Chat, branching-ai-chat, the CanvasConvo field study.
13. **Branch from a highlighted span.** Select text in a reply and open a branch about exactly that claim. Sources: canvas-chat, treechat.
14. **Add a model to a finished turn, and mark the primary reply.**
    - A "+ model" button asks one more model the same question, without re-asking the others.
    - A "primary" mark says which reply the next message continues.
    - Sources: Chorus, TypingMind.

## Phase 5 — Your own evaluation set

15. **Blind comparison with votes.**
    - Arena cards can show as Answer A/B/C in shuffled order, and the models are revealed after a vote: better, tie or all bad, with an optional reason.
    - Votes build a private win rate by task type.
    - Reuses `services/peers.py`. Sources: LMArena, Open WebUI's arena model.
16. **Save a comparison and replay it on new models.**
    - A turn's prompt, attachments, context and votes become a saved case.
    - `crucible replay` (and an MCP tool) re-runs it on the current catalog and shows old against new, with diff and cost.
    - It fits the habit `scaffold-audit` and `catalog-sync` already have: re-measure when models change.
    - Sources: Braintrust, promptfoo, Langfuse.

## Phase 6 — Assigned sides

17. **Assigned sides and a devil's advocate.**
    - For contested questions: models argue an assigned side, or one attacks the emerging consensus.
    - This is the setup where debate measurably helps the judge, here the user.
    - It is a feature built on published results and needs no experiment of ours.
    - Sources: Khan et al. (ICML 2024), Kenton et al. (NeurIPS 2024), Quorum's Oxford and Advocate modes.

## Phase 7 — Research, in order of how long the answer lasts

There is no research budget, so money goes first to conclusions that should hold however models change. Results about how one generation of models behaves are worth having only once those are done, and only as re-runnable entries.

**How durable a result is decides when it runs.**

- **Tier A: guaranteed by construction ($0).**
  - A test proves it, not an experiment. Examples: a constraint kept outside the summary can't be summarized away; a judge read in both orders cancels position bias.
  - These ship as mechanisms with tests.
- **Tier B: measured without a language model ($0).**
  - The reader is the availability oracle. Retrieval is keyword or local-embedding recall. Summaries are model-free stand-ins (`first-sentence-summarizer`, `sized-summarizer`) or summaries already in the replay cache and `backend/experiments/*.sqlite`.
  - A conclusion about a mechanism that contains no model can't be overturned by a better model.
- **Tier C: invariance across model generations (cents to a few dollars).**
  - A claim that needs a real summarizer or reader is run on the cheapest model of two or three generations in each family, legacy models included.
  - If the effect holds with no trend across generations, it is likely to keep holding. If it shrinks with each generation, it is perishable, and now we know its direction.
- **Tier D: how today's models behave (only with money left over).**
  - Run as `scaffold-audit` entries, dated, with model ids. They are re-measured when models change instead of quoted as facts.

**Tier A and B ($0)**

18. **Pinned constraints.**
    - A retention that keeps process constraints ("never touch X") verbatim outside the summary.
    - Tested with the oracle on cached and stand-in summaries.
    - Source: "Benchmarks Are Surprisingly Compaction-Friendly", Governance Decay.
19. **What recall brings back, measured with no model in the loop.**
    - For keyword and embedding recall, record the precision of each recall. Also record:
      - the false positives;
      - how often a superseded value comes back.
    - Then test dated or "superseded" notes.
    - Source: Context Rot, NoLiMa.
20. **Harder facts and a relational oracle.**
    - Facts reworded so they share no words with the question (NoLiMa-style). This shows which recall mechanisms depend on shared words, a property of the mechanism, not of any model.
    - An oracle that checks a fact *and* the reason attached to it. This is the model-free part of "remembering a fact is not being able to continue the task" (Compact-Bench).
21. **Recall with a summarizer that isn't a model.**
    - How much of what a stand-in summarizer drops does recall bring back?
    - A lower bound for "with recall, the summary only has to point to the originals" that no model generation can move.
22. **Publish the instrument, not just numbers.**
    - The harness, scenarios, oracles and `scaffold-audit` history, published as a benchmark anyone can re-run on any future model.
    - Includes real long conversations replayed through `run_live_grid`.

**Tier C (an estimate first, then a budget decision)**

23. **The headline findings across generations.**
    - The findings:
      - summaries keep what the current goal needs;
      - announcing the next goal restores the rest;
      - read-time recall rescues what was dropped.
    - Each is re-run with the cheapest summarizer of two or three generations per family, reusing every cached summary.
    - The write-up then says, for each finding, whether it held across generations.
    - Deadline: OpenAI shuts down gpt-5, gpt-5-mini and gpt-5-nano on 2026-12-11. Runs that need them as the older OpenAI generation must happen before then; otherwise use the oldest generation still served.

**Tier D (only with money left over)**

24. **Task continuation with real readers** (Compact-Bench style).
25. **The accuracy cost of irrelevant recalled notes on real readers** (Context Rot).
26. **Vendor compaction as baselines:** Anthropic's compaction, OpenAI's `/responses/compact`, Gemini CLI's snapshot-plus-probe. These products change fastest of all, so their results date fastest.
27. **Blind peers in debates, as an A/B experiment.**
    - A `PeerPresentation` that hides self from peer as well as names.
    - Today's labels hide names, which is the design choice that holds regardless of model. Whether models conform less without the self/peer distinction is a behaviour of current models.
    - The published effect comes from 7–32B open models (Choi et al. 2025, arXiv 2510.07517).

## Phase 8 — Launch

- Re-record the README demo with the new features (`scripts/seed_demo.py --estimate` first).
- Update the README and the research write-up with Phase 7's results.
- From a fresh clone, check that the quick start and `docker compose up` work as written.
- Run the e2e suite until it is stable on a loaded machine.
- Then announce it.

The launch waits for Tiers A–C. Tier D is not a launch requirement.

## Order and parallel work

- **Dependencies:**
  - Phase 1's cost numbers feed Phases 2 and 5.
  - The diff (5) feeds "who changed" (2) and replay (16).
  - Phase 7 depends on nothing else. It can run alongside Phases 2–6 in its own session; Tiers A and B cost nothing, and Tier C needs a budget decision after its estimate.
- **Where the items came from:** the source notes for each are in the survey this plan came from. Items are numbered here in order of work, not in the survey's order.
