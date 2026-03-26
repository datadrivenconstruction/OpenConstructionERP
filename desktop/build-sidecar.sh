#!/bin/bash
# Build the PyInstaller sidecar binary for Tauri.
#
# Usage: ./desktop/build-sidecar.sh [target-triple]
#
# The output binary is placed in desktop/src-tauri/binaries/
# with the Tauri-required naming: openestimate-server-{target-triple}
#
# Target triples:
#   x86_64-pc-windows-msvc    (Windows)
#   x86_64-apple-darwin       (macOS Intel)
#   aarch64-apple-darwin       (macOS Apple Silicon)
#   x86_64-unknown-linux-gnu  (Linux)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Detect target triple
detect_target() {
    local os arch
    os="$(uname -s)"
    arch="$(uname -m)"

    case "$os" in
        Darwin)
            case "$arch" in
                arm64) echo "aarch64-apple-darwin" ;;
                *)     echo "x86_64-apple-darwin" ;;
            esac
            ;;
        Linux)
            echo "x86_64-unknown-linux-gnu"
            ;;
        MINGW*|MSYS*|CYGWIN*)
            echo "x86_64-pc-windows-msvc"
            ;;
        *)
            echo "unknown-unknown-unknown"
            ;;
    esac
}

TARGET="${1:-$(detect_target)}"
echo "=== Building OpenEstimate sidecar for $TARGET ==="

# Step 1: Build frontend
echo "[1/3] Building frontend..."
cd "$ROOT_DIR/frontend"
[ -d "node_modules" ] || npm ci
npm run build

# Step 2: Build sidecar with PyInstaller
echo "[2/3] Building sidecar binary..."
cd "$ROOT_DIR"
pip install pyinstaller --quiet
pyinstaller desktop/pyinstaller.spec --distpath desktop/dist --workpath desktop/build --noconfirm

# Step 3: Copy to Tauri binaries directory
echo "[3/3] Copying to Tauri binaries..."
BINARIES_DIR="$SCRIPT_DIR/src-tauri/binaries"
mkdir -p "$BINARIES_DIR"

# Determine the binary name and extension
EXT=""
if [[ "$TARGET" == *"windows"* ]]; then
    EXT=".exe"
fi

SRC="$SCRIPT_DIR/dist/openestimate-server/openestimate-server${EXT}"
DST="$BINARIES_DIR/openestimate-server-${TARGET}${EXT}"

if [ -f "$SRC" ]; then
    cp "$SRC" "$DST"
    chmod +x "$DST"
    echo ""
    echo "Sidecar built: $DST"
    echo "Size: $(du -sh "$DST" | cut -f1)"
else
    echo "ERROR: Binary not found at $SRC"
    ls -la "$SCRIPT_DIR/dist/openestimate-server/" 2>/dev/null || true
    exit 1
fi

echo ""
echo "Next step: cd desktop && cargo tauri build"
