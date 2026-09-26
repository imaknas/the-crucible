# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

The Crucible is a multi-model AI arena: a full-stack app where users can run simultaneous conversations across OpenAI, Anthropic, and Google models, branch the conversation tree from any checkpoint, pit models against each other (Arena Mode), invite a model to critically review a thread (Deliberation), synthesize divergent responses (Consensus Engine), and run autonomous multi-round structured debates between models with configurable stopping conditions (Debate Mode).

## Commands

### Development (both services)
```bash
./start_dev.sh          # starts backend (port 8000) + frontend (port 3000), auto-resolves conflicts
```

### Backend
```bash
cd backend
uv sync                           # install dependencies
uv run python -m app.main         # start FastAPI server (reload enabled)
uv run pytest tests/ -v           # run all tests
uv run pytest tests/test_graph.py -v   # run a single test file
uv run ruff check .               # lint
uv run crucible arena "prompt"    # CLI: run multi-model arena
uv run crucible deliberate "topic" -m gpt-5.4 -m claude-sonnet-5 --rounds 3   # repeat -m per model
```

### Frontend
```bash
cd frontend
npm run dev      # Next.js dev server
npm test         # Jest tests
npm run lint     # ESLint
npm run format   # Prettier
```

### E2E (Playwright)
```bash
npm run test:e2e          # re-seeds the fixture DB, then runs the suite
npm run e2e:seed          # rebuild e2e/.fixtures/e2e.sqlite only
npx playwright test --repeat-each=3   # flake check
npx playwright show-report e2e/.report
E2E_BACKEND_PORT=8124 E2E_FRONTEND_PORT=3124 npm run test:e2e   # if 8123/3123 are taken
```
`e2e/seed_db.py` builds a deterministic fixture by running the **real** LangGraph
workflow with `get_model()` stubbed to a canned-response fake — the checkpoints
have to be genuine because the tree endpoints walk LangGraph's own parent/child
links. Both servers run on ports 8123/3123 against that fixture (and `CHROMA_DIR`
under `e2e/.fixtures/`), so the suite never opens `backend/checkpoints.sqlite`
or `backend/chroma_db`.
- The backend runs with `CRUCIBLE_FAKE_LLM=1`: `get_model()` returns
  `services/fake_llm.ScriptedChatModel` for every registered model. It streams
  "Scripted answer from <id> (<hash>)…" word by word, so `e2e/tests/live.spec.ts`
  can send messages and run whole debates. Prompt hooks: `[[slow]]` holds a
  stream open (10× delay), `[[fail:<model_id>]]` makes that model raise. Never
  set the variable outside tests.
- Live tests write real checkpoints, which is why the suite re-seeds on every run
  and each live test starts from **New Session**.
- With `reuseExistingServer`, Playwright silently tests against *whatever* holds
  the port. A stray `python -m http.server 8123` made every spec fail once; use
  the `E2E_*_PORT` overrides instead of killing processes you don't own.

### Docker (for eval / deployment)
```bash
docker compose up --build   # full stack; SQLite persisted in `crucible_data` volume
```

### Environment
Copy `.env.example` to `backend/.env` and set at least one of: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`. `NEXT_PUBLIC_API_URL` defaults to `http://localhost:8000`.

## Architecture

### Backend (`backend/app/`)

**Entry point — `main.py`**
FastAPI server. On startup, compiles the LangGraph workflow with an `AsyncSqliteSaver` checkpointer. Two core endpoints:
- `POST /chat` — non-streaming, for REST usage
- `WebSocket /ws/{thread_id}` — primary endpoint; spawns each model as a concurrent `asyncio.Task`, streams tokens, then emits `stream_end` with fully formatted messages. A disconnect cancels the in-flight tasks.

**Parallel runs — `services/runs.py`**
Any code that runs several graph invocations on one thread at once must go through these helpers:
- **Pin the fork point.** Every model in a turn gets the same `checkpoint_id`. Unpinned concurrent runs resume from the thread head, i.e. from each other's half-written turns (B saw A's prompt; only one reply reached the head). `resolve_fork_point()` returns the head, or seeds an empty root checkpoint for a new thread. The WS handler resolves it once per turn in the receive loop: a message without a parent that arrives while models are still running reuses that turn's parent.
- **Tag the run.** `tag_run(config)` puts a run id in the config's `metadata`, which LangGraph copies into checkpoint metadata; `final_state_of_run()` finds the run's own last checkpoint. Re-reading the pinned config after the run returns the **parent**, which is what `stream_end` used to report.

**Network exposure**
The API has no authentication. The backend binds `127.0.0.1` unless `HOST` is set (the Docker image sets `0.0.0.0` and compose publishes ports on `127.0.0.1`). CORS allows localhost origins on any port plus `CORS_ORIGINS`, never `*`. `/config/keys` additionally rejects non-loopback clients unless `CRUCIBLE_ALLOW_REMOTE_CONFIG` is set, and rejects key values containing quotes, backslashes, whitespace or `$` so a value cannot add lines to `.env`.

**LangGraph workflow — `services/graph.py`**

The graph flow is: `summarize → (route) → [retrieve → grade_retrieval →] draft → metadata → synthesis → END`

- `summarize_history`: compresses history using a fast model (Gemini Flash / Haiku fallback) when token count exceeds the active model's limit; non-destructive (appends a `PREVIOUS CONTEXT SUMMARY:` system message rather than removing messages, letting large-context models use full history)
- `retrieve_node` / `grade_retrieval_node`: RAG path, only active when `use_rag` toggle is on; retrieves from ChromaDB then LLM-grades each chunk for relevance
- `drafting_node`: the core generation node. Handles Deliberation mode (wraps all history with `[Model]: ...` attribution), RAG context injection, attached documents, native web search via `bind_tools` (the only toggles the backend reads are `use_rag` and `use_web_search`), and `sanitize_messages` for context pruning
- `synthesis_node`: updates a rolling `current_thesis` using the last 5 messages
- `metadata_node`: a pass-through kept so existing checkpoints still replay. Its old write to `node_metadata` never ran (a node's config has no `checkpoint_id`); confidence shown in the UI is parsed from the reply's `<metadata>` block in `api/graph.py`

**Model registry — `api/models.py`**
`MODEL_REGISTRY` dict (keyed by lowercase model ID) is the single source of truth for supported models, their family, token limits, and native search support. `get_model()` in `graph.py` looks up this registry to construct the correct LangChain LLM instance.

- **Verify any ID before adding it.** Presence in a provider's `/models` listing is not sufficient — some listed IDs are not chat models. `gpt-5.4-pro`, `gpt-5.5-pro` and `gpt-5-pro` 404 on `v1/chat/completions`, and `gemini-3-flash-lite-preview` no longer exists; all shipped in the registry as broken entries. Confirm with a real one-token completion.
- `limit` is a **soft** threshold that triggers summarisation in `get_token_limit()`, not the hard API window. Anthropic values are 70% of `max_input_tokens` from `GET /v1/models/{id}`.
- `DEFAULT_MODEL`, `DEFAULT_ARENA_MODELS` and `SUMMARIZER_MODELS` live here and are the only copies. `GET /models` returns `default_model`/`default_arena_models` so the frontend does not hardcode one — the previous hardcoded default in `page.tsx` is how it drifted onto a legacy model.
- Entries marked `"desc": "Legacy"` are retained because existing checkpoints reference them; removing one breaks replay of those threads.

**Message sanitizer — `graph.py:sanitize_messages()`**
Critical function called before every LLM invocation. Ensures non-empty content, merges consecutive same-role messages, enforces alternating human/AI turns (Anthropic requirement), handles the summary-jump pruning, and caps total chars at 1.2M.

**State schema — `core/schema.py`**
`CrucibleState` TypedDict: `messages`, `current_thesis`, `active_peer`, `toggles`, `parent_id`, `branch_name`, `is_deliberation`, `retrieved_chunks`, `documents`.

**Persistence — `core/database.py`**
SQLite at `backend/checkpoints.sqlite` (path overridable via `DATABASE_PATH` env var). Stores `thread_metadata` (title), `node_positions` (x/y for React Flow canvas), and `node_metadata` (confidence, conflict). LangGraph uses the same SQLite file for its own checkpoint tables via `AsyncSqliteSaver`.
- Deletes cascade: `delete_thread_data()` also removes every `{thread_id}::*` debate sub-thread and the `debate_sessions` rows; `delete_debate_session()` removes the participant and synthesis sub-threads. Sub-threads are matched by `substr(thread_id, 1, ?)`, not `LIKE`, because thread ids contain `_`.
- `debate_sessions.round_scores` is a JSON object of `{round: score}`, written by `record_round_score()` so convergence survives a page reload. Added by migration in `init_db()`.

**RAG — `services/rag.py`**
ChromaDB persistent vector store at `backend/chroma_db/`. Local HuggingFace embeddings (`all-MiniLM-L6-v2`). Documents are indexed per `thread_id`.
- `get_vector_store()` / `get_embeddings()` are lazy singletons behind a lock. Graph nodes are sync and run on executor threads, so parallel models hit them together; two concurrent `PersistentClient` inits fail with "Could not connect to tenant default_tenant". The directory is overridable with `CHROMA_DIR`.

**Tree reconstruction — `services/tree.py`**
Walks LangGraph checkpoint parent-child links to build a deduplicated conversation tree for the React Flow canvas.
- `load_thread_states()` pulls every checkpoint state for a thread in a single `aget_state_history` pass (with a per-checkpoint fallback for branches outside the main lineage). Use it instead of looping `aget_state` — LangGraph writes 4-6 checkpoints per turn, so the loop was hundreds of round trips per tree fetch.
- `build_significant_forest()` collapses pass-through checkpoints (synthesis prompts, summarisation) so each significant node is re-parented onto its nearest significant ancestor.
- `tidy_tree_layout()` is a Reingold-Tilford style layout: one column per leaf, each parent centred over its children, computed iteratively so deep threads can't blow the stack. Positions saved via `node_positions` override it per node without shifting siblings.

**CLI and MCP share `services/arena.py`**
Everything that drives the graph outside the web UI goes through it: `open_graph()` (compiled graph on the SQLite checkpointer, as a context manager), `resolve_models()` (validation + key check, raises `ValueError` with a caller-facing message), `run_arena()` (parallel answers forked from one checkpoint, then an **explicit** synthesis call as another branch — the per-model rolling `current_thesis` is not a cross-model synthesis and must not be presented as one), `synthesize_thread()` / `latest_branch_answers()`, `thread_messages()`. Debates go through `services/debate.py` (`run_debate`, `synthesize_session`), the same engine the WebSocket uses. Do not reintroduce separate orchestrators in `graph.py`.
- The graph nodes log with `print()`. Wrap anything whose stdout is machine-read in `stdout_to_stderr()`: CLI `--format json` and every MCP tool (the stdio transport **is** stdout).

**CLI — `app/cli.py`**
Typer CLI installed as `crucible`. Commands: `arena`, `deliberate`, `synthesize` (`--thread` or `--debate`), `chat`, `threads`, `tree` (`--open` uses `?thread=`, honoured by `useThreads`), `models`. List options repeat the flag (`-m a -m b`). `--format json` puts only the JSON document on stdout; errors exit 1 with the message on stderr. `deliberate` marks its session `interrupted` if it doesn't finish.

**MCP server — `app/mcp_server.py`**
FastMCP tools returning dicts: `list_models`, `invoke_arena`, `run_debate`, `list_threads`, `get_thread_messages`, `get_branch_answers`, `get_thread_summary`, `get_thread_status`. Failures raise `ToolError` (never an `"Error: ..."` string). Graph topology is a REST endpoint (`GET /graph/{thread_id}/topology`), not an MCP tool.
- CLI and MCP are tested against the real graph with a fake LLM in `tests/test_cli_mcp.py`. Don't go back to mocking `open_graph`: the old mocked tests hid a crash in every command's cleanup.

**Debate system — `services/debate.py`, `services/convergence.py`, `api/debate.py`**
Multi-round structured debate between ≥2 models. Key design points:
- Each model gets its own LangGraph sub-thread: `{parent_thread_id}::{model_id}`; synthesis uses `{parent_thread_id}::synthesis`
- All models stream concurrently per round via `asyncio.Queue` in `_stream_round`
- Cross-examination (round ≥1): each model receives all peers' previous responses as a single HumanMessage (not raw AIMessages — this is intentional to avoid `sanitize_messages` breaking alternating-turn invariants)
- Convergence detection: cosine similarity via `run_in_executor` (reuses `rag.get_embeddings()`), optional LLM judge, configurable `mode: "any"|"all"`
- `api/debate.py` uses a module-level `set_graph_app` / `_get_graph_app` pattern because FastAPI routers can't access `server.state` directly
- REST: `POST /debate/sessions`, `GET /debate/sessions/{id}`, `GET /debate/sessions/{id}/tree`, `DELETE /debate/sessions/{id}`
- WebSocket: `WS /debate/ws/{session_id}` — handles `debate_start`, `debate_inject`, `debate_redirect`, `debate_control` (`stop`/`pause`/`resume`), `debate_synthesize`
- Live controls are a per-connection `DebateControl`: pause takes effect **between rounds** (the handler acks `pausing`, `run_debate` reports `paused` then `running`), and injected messages are appended to the next round's prompts; one that arrives after the final round is reported as an `error`, not dropped. Synthesize and redirect cancel a running debate first. A debate cannot outlive its socket: disconnect cancels it and sets `status="interrupted"`, so a restored session is never shown as running.
- `MODEL_TIMEOUT_SECONDS` bounds each model's whole graph run per round, but a reply whose `draft` node already finished is kept if later nodes run long. Convergence `mode="all"` is never satisfied while any participant failed that round.
- `database.py` stores debate sessions in a `debate_sessions` table; `tree.py` has `build_debate_tree` which computes deterministic lane layout (no dagre): `x = lane_index × 300`, `y = round_num × 160`
- Debate lanes render **AI responses only**. Each round also writes a human checkpoint (the generated cross-examination prompt); rendering those duplicated the question in every lane and made `round_num` count checkpoint depth instead of debate rounds. The original question is emitted once as a shared `debate::prompt` node above all lanes, with edges fanning out to each lane's round 0.
- `LANE_WIDTH` / `ROUND_HEIGHT` are mirrored in `frontend/src/hooks/useDebateTree.ts` so optimistic pending nodes land exactly where the real node will appear. Change both together.

### Frontend (`frontend/src/`)

**State orchestrator — `app/page.tsx`**
Single large component that owns all cross-cutting state (selected models, toggles, active thread/checkpoint, documents). Wires together all custom hooks and renders the layout (Sidebar + TreeCanvas | ChatView + ControlPanel).

**Custom hooks**
- `useChatWebSocket.ts`: manages the WebSocket connection per thread, dispatches parallel model requests (one per selected model), buffers streaming tokens via `requestAnimationFrame` for smooth rendering, and handles `stream_start` / `stream_token` / `stream_end` / `title_update` / `error` messages
- `useHistoryTree.ts`: fetches checkpoint tree from `GET /history/{thread_id}` (optional `?checkpoint_id=`) for TreeCanvas
- `useThreads.ts`: manages thread list CRUD
- `useDebateTree.ts`: manages debate tree state; fetches from `GET /debate/sessions/{id}/tree`; handles optimistic pending nodes during streaming rounds

**Key components**
- `ChatView.tsx`: renders messages with `react-markdown` + KaTeX for LaTeX, syntax highlighting, thinking-block collapsing, and source citations; when `debateState` prop is set, shows a debate status banner (round, convergence score, stop/synthesize controls)
- `TreeCanvas.tsx`: React Flow canvas showing the conversation tree; node click sets `activeCheckpoint` for branching; `debateMode` prop switches to lane layout with `DebateLaneHeaders` overlay and disables dagre auto-layout (debate nodes start at x=0 which would otherwise falsely trigger dagre)
- `ControlPanel.tsx`: model selector (multi-select for Arena), toggle switches, document upload, debate defaults (max rounds, convergence, auto-synthesize)
- `DebateConfigDialog.tsx`: per-session debate config overlay (overrides ControlPanel defaults for a single run)
- `SynthesisTreeNode.tsx`: purple gradient React Flow node for synthesis checkpoints
- `LandingView.tsx`: initial welcome screen before any thread is active

**Branching / Arena flow**
Multi-model Arena: `useChatWebSocket` sends one WS message per selected model simultaneously. Branching: `activeCheckpoint` (a LangGraph checkpoint ID) is passed as `parent_checkpoint_id` in every WS request, telling the backend which node to branch from.

**Debate flow**
User selects ≥2 models → types prompt → clicks Swords button in ChatInput → `DebateConfigDialog` opens → on Start: `POST /debate/sessions` creates session, WS connects to `/debate/ws/{session_id}`, `debate_start` frame is sent. `page.tsx` owns the debate WS lifecycle: `debateMessages` state (RAF-buffered streaming), `debateRound`/`debateStatus`/`debateConvergenceScore` state, `useDebateTree` for the tree canvas. TreeCanvas switches to debate mode when `activeDebateSession` is set.

## Key Conventions

- All model IDs must be registered in `MODEL_REGISTRY` in `backend/app/api/models.py` before use.
- The `langchain_anthropic` monkeypatch in `main.py` is intentional — it fixes a streaming bug in `langchain_anthropic 1.3.2` related to web-search beta events.
- Backend uses `uv` for package management; never use `pip` directly.
- Commits follow Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`.

## Known Gaps

### Frontend visualization invariants (don't regress these)

These were bugs; the fixes are load-bearing.

- **TreeCanvas node sync** (`TreeCanvas.tsx`): the sync effect must apply restyles, not only structural changes. Theme swaps and label updates produce a new `processedNodes` with an identical ID set; skipping them left the tree painted in the old theme. `CustomTreeNode`'s memo comparator must therefore include `data.styling` and `data.metadata`.
- **fitView gating**: `fitView` reads React Flow's own store, so it is a silent no-op until the store holds *and has measured* the current node set. Gate on `storeNodeCount === externalNodes.length && storeNodesMeasured` (from the `useStore` selector). `useNodesInitialized()` does **not** flip true for these nodes — do not use it. Fit once per structural change, keyed on the node ID set.
- **dagre**: build a fresh `dagre.graphlib.Graph()` per layout call. A module-level singleton accumulates every node from every thread and dagre spreads disconnected components side by side.
- **`@keyframes pulse`** lives in TreeCanvas's `<style jsx global>`. An MUI `sx` definition generates a scoped emotion name and will not resolve for pending nodes.
- **Model colours**: `FAMILY_META` in `api/models.py` is the source of truth; the backend ships the resolved colour as `metadata.model_color`. `frontend/src/lib/colors.ts` mirrors it for the pre-fetch fallback. Don't add a fourth palette.
- **Absolutely-positioned overlay rows need an explicit `height`** (`DebateLaneHeaders`, `DebateRoundBands`) — otherwise the row collapses to zero height and `overflow` clips every child away.
- **Level of detail** (`CustomTreeNode.tsx`): below `LOD_THRESHOLD` (0.6) a node renders as a chip — colour bar, model name, word count — because a 40-char preview at 12px is unreadable once auto-fit drops the canvas to ~0.35. The chip is counter-scaled to stay legible, and that boost **must** stay capped (`LOD_MAX_BOOST` 1.35 against `LOD_CHIP_WIDTH` 190) or chips overlap the next column: the tightest layout pitch is `NODE_SPACING_X` 260. This applies to the selected node too — exempting it made the node you care about the least readable at that scale; its active styling still marks it.
- **Never print a raw model ID in UI a person reads.** The backend ships `metadata.model_name` on every node and `label` on every debate lane, from `display_name()` in `api/models.py`; `lib/modelNames.ts` covers frontend-created optimistic nodes. The exact ID belongs in a `title` tooltip.
- **The view never switches itself.** `handleSendMessage` / `handleDeliberate` deliberately do not call `setShowTree`; sending used to yank you out of the tree. The one legitimate exception is `editAndRebranch`, where moving to the composer is the point of the action.
- **Canvas assertions must wait for idle.** Auto-fit animates the viewport for 500ms and Playwright refuses to click a moving element; use `waitForCanvasIdle()`. Auto-fit on the debate fixture also lands within rounding distance of `LOD_THRESHOLD`, so anything asserting on node *text* must call `ensureDetailZoom()` first or it will flip on layout noise.
- **Utility labels say what they do.** The themed vocabulary ("Quantum Nexus Online", "Council", "Deep Knowledge Search") was replaced with plain labels and a real connection/key status. "The Crucible", "Arena", "Deliberation" and "Synthesis" are kept — they name real mechanics.
- **Persisted debate session** (`crucible_active_debate`): only restore it once a thread is open and only if `parent_thread_id` matches, or a stale session hijacks the tree view of an unrelated thread. `listDebateSessions` returns **newest-first** — index 0, not `length - 1`.
- **Debate socket lifecycle** (`page.tsx`): anything that puts a different debate on screen (sidebar switch, new start, thread switch) calls `closeDebateSocket()` first, which detaches and closes the old socket and stops polling; otherwise the old stream keeps appending bubbles and its poll overwrites the new tree. A socket's `onclose` only clears `debateWsRef` if it is still the current socket. Code that loads a session itself sets `restoredDebateRef.current` so the restore effect does not replace a live stream with a server snapshot. `useDebateTree` drops responses for any session other than the last one fetched, and `resolvePendingNode` removes one round's placeholder by id, not every placeholder for the model.
- **Debate model errors** arrive as `{type:"error", model, round}` with no `stream_end`; the handler must close that bubble and resolve its pending node itself.
- **The persisted-debate write skips its mount run.** During hydration `activeDebateSession` is still null; writing it erased the stored session before it could be adopted.
- **Theme state has one owner**: `ThemeRegistry.tsx`, exposed via `useThemeMode()`. Do not reintroduce a second `isDark` in `page.tsx`.
- **localStorage hydration** goes through `hooks/useStoredValue.ts` (`useSyncExternalStore`). A `useState` + mount effect trips `react-hooks/set-state-in-effect`; a lazy `useState` initializer mismatches SSR.
- `LANE_WIDTH` (300) and `ROUND_HEIGHT` (160) are duplicated in `services/tree.py`, `useDebateTree.ts` and `TreeCanvas.tsx`. Change all three together or optimistic pending nodes land on top of real ones.

### Still open

- **No unit tests for `TreeCanvas` / `CustomTreeNode`.** They are covered end-to-end by `e2e/tests/tree.spec.ts` (auto-fit, tidy-tree centring, the LOD threshold, the anti-overlap cap, theme repaint) but not in isolation. `useDebateTree` has unit tests for the pending-node race and stale-session responses.
- **The debate REST endpoints are untested**; the WebSocket controls are covered by `tests/test_debate_ws.py`, and the full debate lifecycle end to end by `e2e/tests/live.spec.ts`.
- **Frontend unit coverage is ~28%** (Jest counts every file via `collectCoverageFrom`). `page.tsx`, `TreeCanvas`, `ControlPanel` and `DebateConfigDialog` have no unit tests; they are exercised by the Playwright suite instead.
- **First paint is slow in dev.** The app needs several seconds before `threadId` resolves and the tree mounts; the canvas shows its empty state until then.
- **Debate node selection is display-only.** Clicking expands the node's excerpt in place but there is no way to open the full response.
- **The debate `stream_end.checkpoint_id` is not read by the frontend** (the chat `stream_end` one is).
- **Sidebar thread names truncate at ~12 characters** in a 288px rail, and untitled threads still show their raw `thread_xxxxxxx` id.
