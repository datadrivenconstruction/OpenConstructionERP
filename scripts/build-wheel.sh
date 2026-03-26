#!/bin/bash
# Build OpenEstimate Python wheel with bundled frontend.
#
# Usage: ./scripts/build-wheel.sh
# Output: backend/dist/openestimate-*.whl
#
# The wheel includes:
#   - FastAPI backend (app/)
#   - Pre-built React frontend (app/_frontend_dist/)
#   - CLI entry point: `openestimate serve`

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== OpenEstimate Wheel Builder ==="
echo ""

# Step 1: Build frontend
echo "[1/3] Building frontend..."
cd "$ROOT_DIR/frontend"
if [ ! -d "node_modules" ]; then
    npm ci
fi
npm run build
echo "  Frontend built: $(du -sh dist | cut -f1)"

# Step 2: Build Python wheel
echo "[2/3] Building Python wheel..."
cd "$ROOT_DIR/backend"
pip install --quiet build
python -m build --wheel

# Step 3: Show result
echo "[3/3] Done!"
echo ""
WHEEL=$(ls -t "$ROOT_DIR/backend/dist/"*.whl 2>/dev/null | head -1)
if [ -n "$WHEEL" ]; then
    echo "  Wheel: $WHEEL"
    echo "  Size:  $(du -sh "$WHEEL" | cut -f1)"
    echo ""
    echo "Install with:"
    echo "  pip install $WHEEL"
    echo ""
    echo "Run with:"
    echo "  openestimate serve"
else
    echo "ERROR: No wheel file found!"
    exit 1
fi
