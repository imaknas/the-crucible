# The Crucible ⚔️

**A multi-model AI arena for non-linear debate, deliberation, and consensus.**

The Crucible is an open-source, full-stack research interface that lets you orchestrate conversations across OpenAI, Anthropic, and Google models — simultaneously. Unlike traditional linear chat apps, every conversation is a **tree**: you can branch, rewind, pit models against each other, and synthesize their best ideas into a unified thesis.

---

## ✨ Features

| Feature | Description |
|---|---|
| **🌳 Conversation Trees** | Every message is a node. Branch off any point, explore alternate timelines, and navigate visually via a React Flow canvas. |
| **⚔️ Arena Mode** | Select multiple models and fire a single prompt. Each model responds in parallel, creating side-by-side branches for instant comparison. |
| **⚖️ Deliberation** | Invite a different model to critically review an existing conversation thread — with full speaker attribution so it knows who said what. |
| **🤝 Consensus Engine** | Select divergent responses and synthesize them into a single, cohesive academic brief. |
| **🧠 Smart Compression** | Automatic context management via `tiktoken`. When token counts approach a model's limit, older history is compressed into a technical brief — with speaker attribution preserved. |
| **📐 LaTeX Math** | Native rendering of `$inline$` and `$$block$$` math expressions via KaTeX. |
| **🕐 Temporal Context** | Models automatically receive the current date, time, and timezone — just like official web clients. |
| **📎 Document Attachments** | Upload PDFs mid-conversation. Documents are parsed and indexed for retrieval. |
| **🔍 RAG (Deep Knowledge Search)** | Enable the RAG toggle to perform semantic search across your uploaded documents. Features self-correcting retrieval grading and inline source citations. |

---

## 🏗️ Architecture

```
the-crucible/
├── backend/           # FastAPI + LangGraph + SQLite
│   ├── app/           # Modular application package
│   │   ├── api/       # FastAPI route modules (threads, history, models, etc.)
│   │   ├── core/      # Database logic, schema, and core config
│   │   ├── services/  # LangGraph, RAG, and tree reconstruction logic
│   │   ├── utils/     # Parsers and helper functions
│   │   └── main.py    # WebSocket server & entry point
│   ├── tests/         # Pytest suite
│   ├── chroma_db/     # Persistent vector storage (git-ignored)
│   └── Dockerfile     # Optimized for Python 3.13 + uv
└── frontend/          # Next.js + MUI + React Flow
    └── src/
        ├── app/
        │   ├── layout.tsx
        │   └── page.tsx    # Main orchestrator (WS, state, routing)
        ├── components/
        │   ├── ChatView.tsx      # Markdown + LaTeX message renderer
        │   ├── TreeCanvas.tsx    # React Flow conversation tree
        │   ├── ControlPanel.tsx  # Model selector + toggles
        │   ├── Sidebar.tsx       # Thread list
        │   ├── LandingView.tsx   # Welcome screen
        │   └── ...
        ├── lib/api.ts    # Centralized API client
        └── theme.ts      # MUI theme configuration
```

### Tech Stack

| Layer | Stack |
|---|---|
| **Frontend** | Next.js 16, React, MUI, React Flow, Framer Motion, react-markdown, KaTeX |
| **Backend** | FastAPI, LangGraph, LangChain, ChromaDB, SQLite, WebSockets, tiktoken |
| **Embeddings** | HuggingFace (local `all-MiniLM-L6-v2`) |
| **AI Providers** | OpenAI, Anthropic, Google (via `langchain-*` SDKs) |

---

## 🚀 Quick Start

### Prerequisites

- **Node.js** 24+
- **Python** 3.12+
- **uv** (recommended) or pip
- At least one API key: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GOOGLE_API_KEY`

### Setup

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/the-crucible.git
cd the-crucible

# 2. Configure environment
cp .env.example backend/.env
# Edit backend/.env and add your API keys

# 3. Backend
cd backend
uv venv && source .venv/bin/activate
uv sync
cd ..

# 4. Frontend
cd frontend
npm install
cd ..

# 5. Launch everything
chmod +x start_dev.sh
./start_dev.sh
```

Open **http://localhost:3000** and step into The Crucible.

> **Tip:** `start_dev.sh` starts both the FastAPI backend (port 8000) and Next.js frontend (port 3000) in a single terminal. Press `Ctrl+C` to shut down both.

### Manual Start (if you prefer)

```bash
# Terminal 1 — Backend
cd backend && uv run python -m app.main

# Terminal 2 — Frontend
cd frontend && npm run dev
```

### 🐳 Run with Docker (Recommended)

The easiest way to run the entire stack is using Docker Compose.

1. **Configure environment**: 
   Ensure `backend/.env` exists with your keys.
2. **Launch**:
   ```bash
   docker compose up --build
   ```
3. **Access**:
   - Frontend: [http://localhost:3000](http://localhost:3000)
   - Backend API: [http://localhost:8000](http://localhost:8000)

> **Note:** The SQLite database is persisted in a Docker volume named `crucible_data`.

---

## 🛠️ Choosing Your Environment

| Method | Recommended For | Perks |
|---|---|---|
| **`./start_dev.sh`** | **Active Development** | Hot reloading, fast startup, easy debugging. |
| **`docker compose`** | **Evaluation & Deployment** | Zero-config env, high stability, exact production parity. |

---

## 🔑 Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | At least one | OpenAI API key |
| `ANTHROPIC_API_KEY` | At least one | Anthropic API key |
| `GOOGLE_API_KEY` | At least one | Google AI API key |
| `NEXT_PUBLIC_API_URL` | No | Backend URL (defaults to `http://localhost:8000`) |

---

## 🧪 Running Tests

```bash
cd backend
uv run pytest tests/ -v
```

---

## 🤝 Contributing

Contributions are welcome! Whether it's adding a new model, improving the tree layout, or fixing a bug, your help is appreciated.

This project follows the [Conventional Commits](https://www.conventionalcommits.org/) specification for commit messages.

1. Clone the repository and create a branch:
   ```bash
   git checkout -b feat/amazing-feature
   ```
2. Commit your changes following the format:
   - `feat:` for new features
   - `fix:` for bug fixes
   - `docs:` for documentation updates
   - `refactor:` for code restructurings
   - `test:` for adding/updating tests
   - *Example: `git commit -m "feat: add support for DeepSeek models"`*
3. Push to your branch and open a Pull Request.

---

## 📝 License

This project is licensed under the [MIT License](LICENSE).
