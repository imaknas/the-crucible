#!/bin/bash

# The Crucible - Modernized Development Startup Script
# This script initializes the environment and launches the full stack.

# ├── Diagnostic Checks ───────────────────────────────────────────
if [ ! -f "backend/.env" ]; then
    echo "⚠️  WARNING: backend/.env not found! AI features may not work."
    echo "   Please copy backend/.env.example to backend/.env and add your keys."
fi

# ├── Cleanup Logic ──────────────────────────────────────────────
cleanup() {
    echo ""
    echo "🛑 Shutting down The Crucible services..."
    # Gracefully kill background processes
    kill $(jobs -p) 2>/dev/null
    exit
}

trap cleanup SIGINT

# ├── Port Coordination ──────────────────────────────────────────
find_free_port() {
    local port=$1
    while lsof -Pi :$port -sTCP:LISTEN -t >/dev/null ; do
        port=$((port + 1))
    done
    echo $port
}

BACKEND_PORT=$(find_free_port 8000)
FRONTEND_PORT=$(find_free_port 3000)

echo "🚀 Starting The Crucible Ecosystem..."
if [ "$BACKEND_PORT" -ne 8000 ] || [ "$FRONTEND_PORT" -ne 3000 ]; then
    echo "⚠️  Port conflict detected! Re-mapping services..."
fi

# ├── 1. Backend Service ──────────────────────────────────────────
echo "📦 [Backend] Starting FastAPI on http://localhost:$BACKEND_PORT..."
(cd backend && PORT=$BACKEND_PORT uv run python -m app.main) &
BACKEND_PID=$!

# ├── 2. Wait for Backend ─────────────────────────────────────────
sleep 1.5

# ├── 3. Agentic Bridge (MCP) ─────────────────────────────────────
echo "🤖 [MCP] Server ready at backend/app/mcp_server.py"
echo "   -> Connect your agent (Claude/Cursor) to: 'uv run python -m app.mcp_server'"

# ├── 4. Frontend Service ─────────────────────────────────────────
echo "💻 [Frontend] Starting Next.js on http://localhost:$FRONTEND_PORT..."
# Pass the correct backend URL to the frontend at runtime
export NEXT_PUBLIC_API_URL="http://localhost:$BACKEND_PORT"
export PORT=$FRONTEND_PORT
(cd frontend && npm run dev)
