# Use the official uv image with Python 3.13
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# Install system dependencies for unstructured/pymupdf if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy project files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy the rest of the source code
COPY . .

# Expose the API port
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DATABASE_PATH=/app/data/checkpoints.sqlite

# Create persistent data directories
RUN mkdir -p /app/data /app/uploads /app/chroma_db

# Healthcheck to ensure the API is responsive
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/models || exit 1

# Run the application
CMD ["uv", "run", "python", "-m", "app.main"]
