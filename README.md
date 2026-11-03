<h1 align="center">The Crucible ⚔️</h1>

<p align="center">
  <strong>Ask OpenAI, Anthropic, Google and xAI models the same question, branch the conversation anywhere, and watch them argue.</strong>
</p>

<p align="center">
  <a href="#-quick-start">Quick start</a> ·
  <a href="#-features">Features</a> ·
  <a href="docs/cli.md">CLI</a> ·
  <a href="docs/mcp.md">MCP server</a> ·
  <a href="#-research-what-survives-compaction">Research</a> ·
  <a href="docs/development.md">Development</a> ·
  <a href="docs/roadmap.md">Roadmap</a>
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue"></a>
  <img alt="Python 3.13+" src="https://img.shields.io/badge/python-3.13%2B-3776ab">
  <img alt="Node.js 24+" src="https://img.shields.io/badge/node-24%2B-339933">
  <img alt="Next.js 16 · FastAPI · LangGraph" src="https://img.shields.io/badge/Next.js%2016%20%C2%B7%20FastAPI%20%C2%B7%20LangGraph-555">
</p>

![Demo: three models answer one question and each continues its own conversation, shown as a tree and as compare cards; then an anonymous three-model debate, one reply read in full, and the argument map it ends in](docs/demo.webp)

<p align="center"><em>Three models answer one question and each continues its own conversation; the tree shows every branch, and any path reads as side-by-side cards. Then an anonymous three-model debate, one reply read in full, and the argument map it ends in.</em></p>

The Crucible is a self-hosted workbench for comparing language models. Every conversation is a **tree**: put a question to several models at once, branch from any reply, have them debate over several rounds, and merge what they said. It runs as a web app, a CLI and an MCP server, all on the same local database. Bring your own API keys: conversations stay in a local database, and only the providers you call see them.

## ✨ Features

- 🌳 **Conversation trees.** Every message is a checkpoint. Branch from any node, edit a question and re-ask it, and move around the whole tree on a canvas.
- ⚔️ **Arena.** One prompt, several models, answering in parallel. Each keeps its own conversation, and the app adds no system prompt of its own, so you compare models as they ship.
- 🗣️ **Debate, as an argument explorer.** Models argue over rounds as anonymous *Participant A, B…*, so none defers to a brand. It ends in an argument map (positions, evidence, who changed their mind and why, what is unresolved), never a verdict.
- 🤝 **Synthesis and Deliberation.** Merge divergent answers into one, or ask a model to critique the thread so far.
- 📎 **Documents and web search.** Attach PDFs, text, Markdown or CSV; search them with cited passages; let models use their provider's own web search.
- 🧠 **Long conversations that keep their details.** Old history is summarized, never deleted, and the original messages a new question needs are brought back.
- ⌨️ **CLI and 🤖 MCP.** Everything the web UI does to a conversation, from the terminal or from another agent.

[Every feature in detail →](docs/features.md)

## 🚀 Quick start

You need Node.js 24+, Python 3.13+ with [uv](https://docs.astral.sh/uv/), and an API key for at least one of OpenAI, Anthropic, Google or xAI.

```bash
git clone https://github.com/imaknas/the-crucible.git && cd the-crucible
(cd backend && uv sync) && (cd frontend && npm install)
./start_dev.sh
```

Open **http://localhost:3000** and add your keys under **Control Panel → API Keys** (or copy `.env.example` to `backend/.env` first). `start_dev.sh` picks free ports if 8000 or 3000 are taken.

**With Docker:**

```bash
cp .env.example backend/.env    # add keys now or in the app later
docker compose up --build
```

Ports, volumes and every setting are in [docs/configuration.md](docs/configuration.md).

> [!WARNING]
> The API has no authentication. It listens on `127.0.0.1` by default; if you expose it with `HOST=0.0.0.0`, anyone who can reach it can spend your API keys. See [configuration](docs/configuration.md) for how browser access from other sites is blocked.

## ⌨️ From the terminal or another agent

The backend installs a `crucible` command:

```bash
cd backend
uv run crucible arena "Is P = NP?" -m gpt-6.1-sol -m claude-sonnet-5-5 -m gemini-3.1-pro-preview
uv run crucible debate "Monolith or microservices?" -m gpt-6.1-sol -m claude-sonnet-5-5 --rounds 3
uv run crucible tree --thread <thread_id> --open    # see it in the web UI
```

Every command takes `--format json`, and everything it creates appears in the web UI. [Full CLI reference →](docs/cli.md)

The same capabilities are MCP tools (`invoke_arena`, `run_debate`, `get_thread_tree`, `search_thread`, …), so another agent can consult a panel of models and branch their conversations. [MCP setup and tool list →](docs/mcp.md)

## 🔬 Research: what survives compaction?

The Crucible doubles as a testbed for one question: when a long conversation is summarized to fit the context window, which details survive, and why are the rest lost? Facts are planted in long synthetic conversations, the app's real pipeline summarizes them turn by turn, and an *oracle* checks whether each fact is still in the context. Pilot-scale findings so far:

- **Summaries keep what the current goal needs.** After a change of plans, OpenAI and Anthropic summaries had kept only 4–13 of the 32 facts the new goal needed.
- **The cause is not knowing what comes next.** Announcing the next goal in advance restored 30 of 32. Without that knowledge, the only fix at write time is to barely compress.
- **Deciding at read time recovers it.** Keeping the originals and fetching the relevant ones once the question is known brought back 28–32 of 32, and the cheapest model chose what to fetch as well as the strongest.
- **With recall on, a cheap summarizer comes close.** Its summaries plus recall kept 93/96 facts on the detail-heavy scenario and 62/64 after a change of plans, at about 1/25 of the cost per summary. A later fix to the harness weakened this: rescored, the best summarizer stays 2–3 facts ahead, so the cheap one is the app's default on cost, not because it matched.

Read the write-up, [**What Survives Compaction?**](https://www.imaknas.com/writing/what-survives-compaction/), or the lab notes with every number and every mistake in [`backend/experiments/NOTES.md`](backend/experiments/NOTES.md). You can run the same measurements on your own models with `crucible compaction-eval` and `crucible scaffold-audit` ([CLI reference](docs/cli.md#measuring-context-management)); [the benchmark guide](docs/benchmark.md) explains the scenarios, the oracles, the free runs and how long each kind of result lasts.

## ❓ FAQ

<details>
<summary><strong>Do I need keys for every provider?</strong></summary>

No. One of OpenAI, Anthropic, Google or xAI is enough, and you can add the others later in the app. With a fourth provider's key, a debate between the default three gets a referee from outside: Grok writes its argument map. `uv run crucible models` lists every model, whether its provider has a key, and its price.
</details>

<details>
<summary><strong>Why are debate participants anonymous?</strong></summary>

Models defer to majorities and to peers they recognise as strong. Labelling them *Participant A, B…* removes the brand from the argument; the UI still shows you who is who. Use `--peers named` (CLI) or the debate dialog to compare.
</details>

<details>
<summary><strong>Is the debate's conclusion reliable?</strong></summary>

Not by itself: agreement reached by debating is not evidence, which is why a debate ends in an argument map rather than a verdict. For an answer to rely on, use Arena's independent answers and Synthesis.
</details>

<details>
<summary><strong>Where is my data?</strong></summary>

In a local SQLite database (`backend/checkpoints.sqlite`), with uploads in `backend/uploads` and the document index in `backend/chroma_db`; Docker keeps them in volumes. Document search runs on a local embedding model; a model sees a file only when a turn attaches it or quotes passages retrieved from it.
</details>

<details>
<summary><strong>How do I add a model?</strong></summary>

`uv run crucible catalog-sync` checks it with a real call, then add its price and a registry entry; [`CLAUDE.md`](CLAUDE.md#extension-points) has the steps.
</details>

## 🛠️ Development

[docs/development.md](docs/development.md) covers the layout, design, tech stack, the test suites (pytest, Jest, and a Playwright suite that runs against scripted models at no cost) and how the demo above is recorded. [`CLAUDE.md`](CLAUDE.md) is the detailed maintainer guide: design invariants and where each kind of change belongs.

## 🗺️ Roadmap

Next: debates that follow what the research says about rounds, anonymity and judges; the cost and speed of every answer; diffs; synthesizing any set of nodes; resumable streams; a navigable tree; your own blind evaluation set; and a third round of compaction research. [The full plan →](docs/roadmap.md)

## 🤝 Contributing

Contributions are welcome: a new model, a better tree layout, a bug fix. Create a branch, make the change where [`CLAUDE.md`](CLAUDE.md) says it belongs, run the tests, and commit with [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`…) before opening a pull request.

## 📝 License

[MIT](LICENSE)
