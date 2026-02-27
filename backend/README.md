# The Crucible - Backend 🧠

The backend orchestrates the multi-model arena, managing the conversation state machine via LangGraph and persisting data in SQLite.

## 🚀 Getting Started

### Prerequisites
- Python 3.12+
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

- **`main.py`**: The FastAPI application and WebSocket coordinator.
- **`graph.py`**: Defines the conversation state graph, including drafting, synthesis, and summarization nodes.
- **`history_tree.py`**: Handles graph path reconstruction, checkpoint deduplication, and node layout.
- **`db.py`**: SQLite database layer for thread metadata and node positions.

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
