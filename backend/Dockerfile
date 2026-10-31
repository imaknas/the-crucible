# Use the official uv image with Python 3.13
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# curl for the healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy project files
COPY pyproject.toml uv.lock ./

# Install dependencies (the project itself needs its source, below)
RUN uv sync --frozen --no-dev --no-install-project

# Copy the rest of the source code, then install the project (the `crucible` CLI)
COPY . .
RUN uv sync --frozen --no-dev

# Expose the API port
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DATABASE_PATH=/app/data/checkpoints.sqlite
# Listen on all interfaces inside the container; compose publishes on 127.0.0.1.
ENV HOST=0.0.0.0
# No code reloader in a container: nothing edits the code there.
ENV CRUCIBLE_RELOAD=0

# Create persistent data directories
RUN mkdir -p /app/data /app/uploads /app/chroma_db

# Healthcheck to ensure the API is responsive
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:${PORT:-8000}/models || exit 1

# Run the application. --no-sync: `uv run` would otherwise install the dev
# group (pytest, ruff, mypy, pyright) on every start, from the network.
CMD ["uv", "run", "--no-sync", "python", "-m", "app.main"]
