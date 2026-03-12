# The Crucible - Backend 🧠

The backend orchestrates the multi-model arena, managing the conversation state machine via LangGraph and persisting data in SQLite.

## 🚀 Getting Started

### Prerequisites
- Python 3.13+
- Node.js 24+ (for development tools)
- [uv](https://github.com/astral-sh/uv) (recommended)

### Installation
```bash
uv sync
```

### Environment Setup
Create a `.env` file based on `.env.example`:
```bash
cp .env.example .env
```
Ensure at least one and preferably multiple API keys are set (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`).

## 🛠️ Key Components

- **`app/main.py`**: The FastAPI application and WebSocket coordinator.
- **`app/services/graph.py`**: Defines the conversation state graph, including drafting, retrieval, grading, synthesis, and summarization nodes.
- **`app/services/rag.py`**: Manages local vector storage using ChromaDB, semantic chunking, and HuggingFace embeddings (`all-MiniLM-L6-v2`).
- **`app/services/tree.py`**: Handles graph path reconstruction, checkpoint deduplication, and node layout.
- **`app/core/database.py`**: SQLite database layer for thread metadata and node positions.
- **`app/core/schema.py`**: CrucibleState TypedDict and state definitions.
- **`app/api/`**: Modular FastAPI routers for threads, history, models, and uploads.
- **`chroma_db/`**: Persistent storage directory for the vector database (automatically created on first upload).

## 🧪 Testing

We use `pytest` for logic and integration testing.

```bash
# Run all tests
uv run pytest tests/ -v

# Run specific integration tests
uv run pytest tests/test_routers.py
```

## 🐳 Docker

The backend is containerized for easy deployment. See the root `docker-compose.yml` for orchestration details.
