# Architecture and development

## Layout

```
the-crucible/
├── backend/                 FastAPI + LangGraph + SQLite
│   ├── app/
│   │   ├── main.py          App assembly only (lifespan, CORS, routers)
│   │   ├── api/             HTTP & WebSocket routes — transport only
│   │   ├── services/        Behaviour: chat turns, arena, debates, synthesis, history, uploads, RAG
│   │   ├── llm/             Model providers and the ModelFactory
│   │   ├── registry.py      Which models the app offers, and the defaults
│   │   ├── catalog/         Model facts and prices from the providers' own sources
│   │   ├── compaction/      When to summarize, what to keep, what to recall (no app imports)
│   │   ├── core/            SQLite persistence, storage locations and the graph state schema
│   │   ├── cli.py           `crucible` command
│   │   └── mcp_server.py    MCP tools
│   ├── tests/               pytest suite
│   └── experiments/         Compaction lab notes, raw results, scaffold-audit history
├── frontend/                Next.js + MUI + React Flow
│   └── src/
│       ├── app/page.tsx     App shell: composes hooks and components
│       ├── hooks/           State and sockets (chat, debate session, tree, threads…)
│       ├── components/      UI (TreeCanvas, ChatView, ControlPanel sections…)
│       └── lib/             API client, pure reducers, shared types
├── e2e/                     Playwright suite and its fixture builder
└── scripts/                 Demo data and the README recording
```

## Design

- **One LangGraph workflow** handles every turn: summarize if needed → optional retrieval and grading → draft (with recalled originals when history was pruned). State lives in SQLite checkpoints, which is what makes branching from any node possible.
- **Every model in a turn is pinned to its own fork point.** By default each continues its own reply in the latest turn, so models that answered side by side keep separate conversations; branching from a node pins them all there. Pinning keeps parallel answers on their own branches instead of reading each other's half-finished turn.
- **Models come from a factory.** Each provider is a small strategy class in `backend/app/llm/providers.py`; nothing else in the code branches on the provider, and tests inject scripted models instead of patching globals.
- **Debates run per model.** Each participant gets its own sub-thread, all stream concurrently each round, and early-stop checks (stability, agreement) and how peers are presented to each other (anonymous or named) are interchangeable strategies.

[`CLAUDE.md`](../CLAUDE.md) is the detailed maintainer guide: design invariants, where each kind of change belongs, and how to test it.

## Adding models

The app offers only models it has verified with a real call. With the provider's key in `backend/.env`:

1. `cd backend && uv run crucible catalog-sync` lists the provider's models from its own API and probes each with a one-token call and a web search (a few cents; `--probe none` only lists). It writes `app/catalog/data/catalog.json`.
2. Add the model's price to `app/catalog/data/prices.json`, from the provider's pricing page.
3. Add an entry to `MODEL_REGISTRY` in `app/registry.py` (`native_search` only if the probe's web search passed).

`tests/test_registry_catalog.py` fails until all three agree. xAI (Grok) is set up this way: its key, provider and catalog source are in place, and its models appear after these three steps.

## Running the servers separately

`./start_dev.sh` starts both; to run them in two terminals instead:

```bash
cd backend && uv run python -m app.main     # terminal 1
cd frontend && npm run dev                  # terminal 2
```

## Tech stack

| Layer | Stack |
|---|---|
| **Frontend** | Next.js 16, React 19, MUI 7, React Flow, Framer Motion, react-markdown, KaTeX |
| **Backend** | FastAPI, LangGraph, LangChain, SQLite, ChromaDB, tiktoken, Typer (CLI), FastMCP |
| **Embeddings** | Local HuggingFace `all-MiniLM-L6-v2` |
| **Providers** | OpenAI, Anthropic, Google (via `langchain-*`) |

## Testing

```bash
(cd backend && uv run pytest tests/ -q -n 4)   # backend unit + integration, on 4 workers
(cd backend && uv run ruff check .)            # backend lint
(cd frontend && npm test)                      # frontend unit (Jest)
(cd frontend && npm run lint)                  # frontend lint

npm install && npx playwright install chromium   # once, at the repo root
npm run test:e2e                                 # end-to-end (Playwright)
```

The end-to-end suite builds its own fixture database (`e2e/seed_db.py`) and starts both servers against it with **scripted models** (`CRUCIBLE_FAKE_LLM=1`): replies stream like a real provider's, so it can send messages and run whole debates without network access or cost, and it never touches your real data. The frontend runs as a production build (`next build` into `frontend/.next-e2e`, so a dev server in the same checkout is untouched); `E2E_DEV=1 npm run test:e2e` runs it against `next dev` instead, for debugging. If ports 8123/3123 are taken, set `E2E_BACKEND_PORT` / `E2E_FRONTEND_PORT`.

## Re-recording the README demo

```bash
uv run --project backend python scripts/seed_demo.py --estimate   # upper bound on the cost, no calls
uv run --project backend python scripts/seed_demo.py --budget 1   # real calls, stops at the budget
cd backend && DATABASE_PATH=../scripts/.demo/demo.sqlite CHROMA_DIR=../scripts/.demo/chroma \
  uv run python -m uvicorn app.main:server --port 8200 --env-file .env &   # keys, or the header says none are set
cd frontend && NEXT_PUBLIC_API_URL=http://127.0.0.1:8200 NEXT_DIST_DIR=.next-demo npx next build \
  && NEXT_DIST_DIR=.next-demo npx next start -p 3200 &
node scripts/record_demo.mjs      # docs/demo.webp (light mode; needs ffmpeg and uv)
```

