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

echo "🚀 Starting The Crucible Ecosystem..."

# ├── 1. Backend Service ──────────────────────────────────────────
echo "📦 [Backend] Starting FastAPI on http://localhost:8000..."
(cd backend && uv run python -m app.main) &
BACKEND_PID=$!

# ├── 2. Wait for Backend ─────────────────────────────────────────
sleep 1.5

# ├── 3. Agentic Bridge (MCP) ─────────────────────────────────────
echo "🤖 [MCP] Server ready at backend/app/mcp_server.py"
echo "   -> Connect your agent (Claude/Cursor) to: 'uv run python -m app.mcp_server'"

# ├── 4. Frontend Service ─────────────────────────────────────────
echo "💻 [Frontend] Starting Next.js on http://localhost:3000..."
(cd frontend && npm run dev)
