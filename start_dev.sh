#!/bin/bash

# The Crucible - Development Startup Script
# This script starts both the FastAPI backend and the Next.js frontend.

# Function to handle shutdown
cleanup() {
    echo ""
    echo "Shutting down The Crucible..."
    # Kill all background processes started by this script
    kill $(jobs -p)
    exit
}

# Trap SIGINT (Ctrl+C) and call cleanup
trap cleanup SIGINT

echo "🚀 Starting The Crucible Development Environment..."

# 1. Start Backend
echo "📦 Starting Backend (FastAPI on http://localhost:8000)..."
cd backend
uv run python main.py &
BACKEND_PID=$!
cd ..

# 2. Wait a moment for backend to initialize
sleep 2

# 3. Start Frontend
echo "💻 Starting Frontend (Next.js on http://localhost:3000)..."
cd frontend
npm run dev
