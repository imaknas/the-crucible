# CLI

The backend installs a `crucible` command that can do everything the web UI does to a conversation. Run it from `backend/` with `uv run`, repeat list options once per value (`-m a -m b`), and see `uv run crucible <command> --help` for every option.

**Setup**

```bash
uv run crucible models                     # model IDs, which have a key, web search and price (--all adds legacy ones)
uv run crucible keys                       # which provider keys are set (masked)
uv run crucible keys --set OPENAI_API_KEY  # asks for the value without echoing; --unset removes one
uv run crucible catalog-sync --probe none  # refresh the model catalog from the providers' APIs; probing (the default, --probe new) costs a few cents
```

**Turns**

```bash
uv run crucible arena "Is P = NP?" -m gpt-6.2-sol -m claude-sonnet-5-5 -m gemini-4-neon
uv run crucible chat "Follow-up" -m gpt-6.2-sol --thread <thread_id>
echo "question" | uv run crucible chat -m gpt-6.2-sol              # the prompt can come from stdin
uv run crucible arena "Rephrased question" -m gpt-6.2-sol -m claude-sonnet-5-5 --thread <thread_id> --from <checkpoint>
uv run crucible chat --deliberate -m claude-sonnet-5-5 --thread <thread_id>   # critically review the thread so far
uv run crucible arena --join-turn <turn_or_checkpoint> -m grok-4.7 --thread <thread_id>   # add a model to an answered turn
uv run crucible arena "Review this plan." --attach plan.md -m gpt-6.2-astra -m claude-opus-5-5 \
  --angle gpt-6.2-astra=security --angle "claude-opus-5-5=the case against it" --no-synthesize   # each model its own angle
uv run crucible synthesize --thread <thread_id>                    # combine the answers to the latest question
uv run crucible synthesize --thread <thread_id> --mode compare     # a table of where they differ (no winner)
uv run crucible synthesize --thread <thread_id> --mode issues      # every problem the answers raise, with who raised it (for reviews)
uv run crucible synthesize --thread <thread_id> --mode checklist   # list their parts; then --keep "<part>" (repeat) to merge just those
uv run crucible synthesize --thread <thread_id> --mode ask -q "Which is riskier?"   # your question about them
uv run crucible review --thread <thread_id>                        # the models score each other's answers, anonymously; --list shows stored reviews
uv run crucible check <issue_list_cp> --thread <thread_id>         # does each problem of an issue list hold? each reviewer checks it against the source; --list shows stored checks
```

`arena` answers in parallel, each model on its own branch, then the first model (or `--judge`) synthesizes them; `--no-synthesize` skips that. Without `--from`, each model continues its own latest reply; `--from <checkpoint>` branches from any node of `crucible tree` (to edit a message, branch from the checkpoint before it with the new text), and `--after-debate <session>` continues from a finished debate. `chat` and `arena` also take:

- `--attach <file>` to put a file's text in this turn (`.pdf .txt .md .csv`), `--rag` to search the files uploaded to the thread, `-w` for web search;
- `--system "<prompt>"` to send every model a system prompt (none by default; `debate` and `synthesize` take it too);
- `--summarizer <model>` to choose who summarizes long history (default: the first summarizer model with a key);
- `--angle MODEL=ANGLE` (`arena`, repeat it) or `--angle "<angle>"` (`chat`) to have a model answer from an angle, e.g. to review a plan from several sides. The message stays the same for every model; each answer says its angle, the synthesizer gets none, and `synthesize --mode issues` lists every problem raised with who raised it. A turn whose answers had different angles can't be voted on.

`--join-turn` takes a turn id or one of its replies' checkpoints (both in `crucible tree --format json`): the new models answer that turn's own question from where it was asked, as more answers of the same turn, and nobody else is asked again. It takes no prompt, `--deliberate`, `--attach` or synthesis.

Under each answer (and the synthesis) a dim line says what it took: time to first token, total time, input / output tokens (reasoning among the output) and cost in USD, or "price unknown" for a model without a known price; a turn of several models ends with their total. With `--format json` each answer carries the same numbers as `metrics`.

**Votes and saved cases**

```bash
uv run crucible vote --thread <thread_id> --show                   # the latest turn's answers, blind (A/B/C)
uv run crucible vote --thread <thread_id> --best B --task coding --reason "Handles the edge case"   # or --tie, --all-bad; --delete removes it
uv run crucible votes                                              # win rates per model; --task <kind>, --list for the votes
uv run crucible cases save <turn_or_checkpoint> --thread <thread_id>   # copy a turn whole, so it outlives the thread
uv run crucible cases list                                         # also: cases show <case_id>, cases delete <case_id>
uv run crucible replay <case_id> -m gpt-6.2-sol -m claude-sonnet-5-5   # ask today's models again; asks first unless --yes, --diff for full diffs
```

A vote is one per turn (voting again replaces it) and names the letter `--show` printed, so it can be given blind. Win rates are pairwise: a best answer wins over each other answer of its turn, a tie is a tie for every pair, and "all bad" is counted apart. A case copies the turn's question, the conversation before it, its documents, settings, answers and vote; `replay` runs it in a new thread and compares each new answer with the same model's old one, or the one voted best.

**Debates**

```bash
uv run crucible debate "Topic" -m gpt-6.2-sol -m claude-sonnet-5-5 --rounds 3 --threshold 0.92
uv run crucible debates list                                       # newest first; --thread <id> for one thread
uv run crucible debates show <session_id>                          # every round of every participant, and the argument map
uv run crucible debates continue <session_id> --rounds 1 --inject "Consider the cost too"
uv run crucible debates redirect <session_id> "A new question"
uv run crucible synthesize --debate <session_id>                   # (re)write the argument map
uv run crucible debates delete <session_id>
```

Participants see each other as *Participant A, B…*; `--peers named` shows them model ids instead. `--threshold` stops once answers stop changing, `--convergence-judge <model>` once a judge finds the models agree (`--mode all|any` combines both). `--thread` and `--from` start a debate from an existing conversation. Ctrl-C stops a debate; to pause, run fewer rounds and `debates continue` later.

**Threads and history**

```bash
uv run crucible threads                                            # --rename <id> --title "…", --delete <id>
uv run crucible tree --thread <thread_id>                          # each node's checkpoint id; --open shows it in the web UI
uv run crucible messages --thread <thread_id> --at <checkpoint>    # one path, as the chat view shows it
uv run crucible search "keyword" --thread <thread_id>              # every branch
uv run crucible diff <checkpoint_a> <checkpoint_b> --thread <thread_id>   # what differs between two answers
uv run crucible context --thread <thread_id> -m gpt-6.2-sol       # what the next turn would send each model, and whether from a summary
uv run crucible node <checkpoint> --thread <thread_id> --name "Cheaper option" --bookmark   # name a branch, bookmark a node
uv run crucible summarize-branch <checkpoint> --thread <thread_id> # summarize a subtree onto its node (--clear forgets it); the thread is unchanged
uv run crucible delete-branch <checkpoint> --thread <thread_id>    # a node and everything below it
uv run crucible upload notes.pdf --thread <thread_id>              # for --rag; --list shows what is kept
```

`diff` compares two replies sentence by sentence and, inside a changed sentence, word by word; code and JSON line by line (JSON with sorted keys, so key order and whitespace don't count). Markdown formatting is ignored. A's lines start with `−`, B's with `+`; removed words are struck through and added ones underlined. It prints a summary ("12 sentences the same, 3 changed, 2 only in A, 1 only in B") and counts the sentences both share (`--unchanged` prints them). `--format json` gives the rows, the counts and `summary_text`.

Every command accepts `--format json`: stdout then carries only the JSON document, errors exit 1 with the message on stderr, and option combinations that can't work exit 2 before anything runs. `crucible -v <command>` shows the backend's diagnostics on stderr. Everything the CLI creates appears in the web UI.

## Measuring context management

```bash
uv run crucible compaction-eval --estimate --scenario task -s gemini-3.8-flash --recall none --recall guided
uv run crucible compaction-eval --budget 2 --scenario task -s gemini-3.8-flash --recall none --recall guided
uv run crucible scaffold-audit --estimate          # then --budget N to run; --report for the latest verdicts
uv run crucible recall-eval                         # free: what keyword and embedding recall bring back, no model
uv run crucible constraint-eval                     # free: what the constraint detector behind --keep constraints finds
```

Every real run needs `--budget` (USD): it calibrates each model with one call, estimates the whole run, refuses to start if the estimate is over budget, and stops starting calls once the budget is spent. `--estimate` only estimates.

What these measure, the runs that cost nothing (`--dry-run`, `--rescore`, `--report`) and what the results so far are worth: [the benchmark guide](benchmark.md).
