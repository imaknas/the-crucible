# CLI

The backend installs a `crucible` command that can do everything the web UI does to a conversation. Run it from `backend/` with `uv run`, repeat list options once per value (`-m a -m b`), and see `uv run crucible <command> --help` for every option.

**Setup**

```bash
uv run crucible models                     # model IDs, which have a key, web search and price (--all adds legacy ones)
uv run crucible keys                       # which provider keys are set (masked)
uv run crucible keys --set OPENAI_API_KEY  # asks for the value without echoing; --unset removes one
```

**Turns**

```bash
uv run crucible arena "Is P = NP?" -m gpt-6.1-sol -m claude-sonnet-5-5 -m gemini-3.1-pro-preview
uv run crucible chat "Follow-up" -m gpt-6.1-sol --thread <thread_id>
echo "question" | uv run crucible chat -m gpt-6.1-sol              # the prompt can come from stdin
uv run crucible arena "Rephrased question" -m gpt-6.1-sol -m claude-sonnet-5-5 --thread <thread_id> --from <checkpoint>
uv run crucible chat --deliberate -m claude-sonnet-5-5 --thread <thread_id>   # critically review the thread so far
uv run crucible synthesize --thread <thread_id>                    # combine the answers to the latest question
```

`arena` answers in parallel, each model on its own branch, then the first model (or `--judge`) synthesizes them; `--no-synthesize` skips that. Without `--from`, each model continues its own latest reply; `--from <checkpoint>` branches from any node of `crucible tree` (to edit a message, branch from the checkpoint before it with the new text), and `--after-debate <session>` continues from a finished debate. `chat` and `arena` also take:

- `--attach <file>` to put a file's text in this turn (`.pdf .txt .md .csv`), `--rag` to search the files uploaded to the thread, `-w` for web search;
- `--system "<prompt>"` to send every model a system prompt (none by default; `debate` and `synthesize` take it too);
- `--summarizer <model>` to choose who summarizes long history (default: the first summarizer model with a key).

**Debates**

```bash
uv run crucible debate "Topic" -m gpt-6.1-sol -m claude-sonnet-5-5 --rounds 3 --threshold 0.92
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
uv run crucible delete-branch <checkpoint> --thread <thread_id>    # a node and everything below it
uv run crucible upload notes.pdf --thread <thread_id>              # for --rag; --list shows what is kept
```

Every command accepts `--format json`: stdout then carries only the JSON document, errors exit 1 with the message on stderr, and option combinations that can't work exit 2 before anything runs. `crucible -v <command>` shows the backend's diagnostics on stderr. Everything the CLI creates appears in the web UI.

## Measuring context management

```bash
uv run crucible compaction-eval --estimate --scenario task -s gemini-3.8-flash --recall none --recall guided
uv run crucible compaction-eval --budget 2 --scenario task -s gemini-3.8-flash --recall none --recall guided
uv run crucible scaffold-audit --estimate          # then --budget N to run; --report for the latest verdicts
```

Every real run needs `--budget` (USD): it calibrates each model with one call, estimates the whole run, refuses to start if the estimate is over budget, and stops starting calls once the budget is spent. `--estimate` only estimates.
