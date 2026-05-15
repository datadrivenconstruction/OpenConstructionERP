#!/bin/bash
# OpenConstructionERP — Dev Startup Script
# Starts: PostgreSQL (Docker), Backend (uvicorn), Frontend (vite)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== OpenConstructionERP Dev Startup ==="

# Ensure Docker infra is running
echo "[1/3] Starting PostgreSQL (Docker)..."
docker compose up -d postgres 2>/dev/null || docker compose start postgres 2>/dev/null || echo "  (already running or using external postgres)"

# Kill any existing dev servers
pkill -f "uvicorn app.main:create_app" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true
sleep 1

# Activate venv and start backend
echo "[2/3] Starting Backend (uvicorn)..."
source venv/bin/activate
cd backend
nohup uvicorn app.main:create_app --factory --reload --port 8000 > /tmp/ocerp-backend.log 2>&1 &
BACKEND_PID=$!
cd ..
echo "  Backend PID: $BACKEND_PID (log: /tmp/ocerp-backend.log)"

# Wait for backend to be ready
echo "  Waiting for backend..."
for i in {1..15}; do
    if curl -s -o /dev/null http://localhost:8000 2>/dev/null; then
        echo "  Backend ready!"
        break
    fi
    sleep 1
done

# Start frontend
echo "[3/3] Starting Frontend (vite)..."
cd frontend
nohup npm run dev > /tmp/ocerp-frontend.log 2>&1 &
FRONTEND_PID=$!
echo "  Frontend PID: $FRONTEND_PID (log: /tmp/ocerp-frontend.log)"

# Wait for frontend
echo "  Waiting for frontend..."
for i in {1..15}; do
    if curl -s -o /dev/null http://localhost:5180 2>/dev/null; then
        echo "  Frontend ready!"
        break
    fi
    sleep 1
done

echo ""
echo "=== All services started ==="
echo "  Backend:  http://localhost:8000 (PID $BACKEND_PID)"
echo "  Frontend: http://localhost:5180 (PID $FRONTEND_PID)"
echo "  Logs:     /tmp/ocerp-backend.log, /tmp/ocerp-frontend.log"
echo ""
echo "To stop: pkill -f 'uvicorn app.main:create_app'; pkill -f 'vite'"