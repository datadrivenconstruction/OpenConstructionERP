#!/bin/bash
# OpenConstructionERP — One-Line Installer for Linux / macOS
#
# Usage:
#   curl -sSL https://get.openconstructionerp.com | bash
#
# What it does:
#   1. If Docker is installed → runs via docker compose
#   2. If Python 3.12+ is installed → installs via pip/uv
#   3. Otherwise → installs uv (which manages Python) → installs via uv
#
# Environment variables:
#   OE_VERSION     - Version to install (default: latest)
#   OE_INSTALL_DIR - Installation directory (default: ~/.openconstructionerp)
#   OE_METHOD      - Force method: docker, pip, uv (default: auto-detect)
#   OE_PORT        - Port to run on (default: 8080)

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────
OE_VERSION="${OE_VERSION:-latest}"
OE_INSTALL_DIR="${OE_INSTALL_DIR:-$HOME/.openconstructionerp}"
OE_METHOD="${OE_METHOD:-auto}"
OE_PORT="${OE_PORT:-8080}"
OE_REPO="https://github.com/datadrivenconstruction/OpenConstructionERP"

# ── Colors ───────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── Detection ────────────────────────────────────────────────────────
has_docker() {
    command -v docker &>/dev/null && docker info &>/dev/null 2>&1
}

has_python312() {
    # Version comparison is done inside Python itself — avoids a hard dep
    # on ``bc`` (missing from Git Bash on Windows and from minimal base
    # images). Any modern Python has ``sys.version_info`` so the test
    # covers every supported install method.
    local cmd
    for cmd in python3.12 python3 python; do
        command -v "$cmd" &>/dev/null || continue
        "$cmd" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' &>/dev/null && return 0
    done
    return 1
}

has_uv() {
    command -v uv &>/dev/null
}

# ── Install Methods ──────────────────────────────────────────────────
install_docker() {
    info "Installing via Docker..."

    mkdir -p "$OE_INSTALL_DIR"
    cd "$OE_INSTALL_DIR"

    # Download quickstart compose file
    if [ "$OE_VERSION" = "latest" ]; then
        curl -sSL "$OE_REPO/raw/main/docker-compose.quickstart.yml" -o docker-compose.yml
    else
        curl -sSL "$OE_REPO/raw/v$OE_VERSION/docker-compose.quickstart.yml" -o docker-compose.yml
    fi

    info "Starting OpenEstimate..."
    docker compose up -d

    ok "OpenEstimate is running at http://localhost:${OE_PORT}"
    echo ""
    echo "Commands:"
    echo "  cd $OE_INSTALL_DIR && docker compose logs -f   # View logs"
    echo "  cd $OE_INSTALL_DIR && docker compose down      # Stop"
    echo "  cd $OE_INSTALL_DIR && docker compose up -d     # Start"
}

install_uv() {
    info "Installing via uv..."

    # Install uv if not present
    if ! has_uv; then
        info "Installing uv package manager..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
    fi

    # Install OpenConstructionERP (PyPI package name — see pyproject.toml).
    uv tool install openconstructionerp
    ok "OpenConstructionERP installed!"

    # Create systemd service if on Linux
    if [ "$(uname -s)" = "Linux" ] && command -v systemctl &>/dev/null; then
        create_systemd_service
    fi

    echo ""
    echo "Run: openestimate serve --port $OE_PORT"
    echo "     openestimate serve --port $OE_PORT --open  # Also opens browser"
}

install_pip() {
    info "Installing via pip..."

    local python_cmd="python3"
    if command -v python3.12 &>/dev/null; then
        python_cmd="python3.12"
    fi

    # Create virtual environment
    mkdir -p "$OE_INSTALL_DIR"
    $python_cmd -m venv "$OE_INSTALL_DIR/venv"
    source "$OE_INSTALL_DIR/venv/bin/activate"

    # Install
    pip install --upgrade pip
    pip install openconstructionerp

    ok "OpenConstructionERP installed in $OE_INSTALL_DIR/venv"

    # Create convenience script
    cat > "$OE_INSTALL_DIR/start.sh" << 'SCRIPT'
#!/bin/bash
source "$(dirname "$0")/venv/bin/activate"
openconstructionerp serve "$@"
SCRIPT
    chmod +x "$OE_INSTALL_DIR/start.sh"

    echo ""
    echo "Run: $OE_INSTALL_DIR/start.sh --port $OE_PORT"
    echo " Or: source $OE_INSTALL_DIR/venv/bin/activate && openconstructionerp serve"
}

create_systemd_service() {
    local service_file="$HOME/.config/systemd/user/openestimate.service"
    mkdir -p "$(dirname "$service_file")"

    local oe_bin
    oe_bin="$(which openconstructionerp 2>/dev/null || echo "$HOME/.local/bin/openconstructionerp")"

    cat > "$service_file" << EOF
[Unit]
Description=OpenConstructionERP Server
After=network.target

[Service]
Type=simple
ExecStart=$oe_bin serve --host 0.0.0.0 --port $OE_PORT
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload
    info "Systemd service created. Enable with: systemctl --user enable --now openconstructionerp"
}

# ── Main ─────────────────────────────────────────────────────────────
main() {
    echo ""
    echo "  ╔═══════════════════════════════════════════════╗"
    echo "  ║      OpenConstructionERP Installer            ║"
    echo "  ║      Construction Cost Estimation Platform    ║"
    echo "  ╚═══════════════════════════════════════════════╝"
    echo ""

    case "$OE_METHOD" in
        docker)
            if ! has_docker; then
                error "Docker not found. Install Docker first: https://docs.docker.com/get-docker/"
                exit 1
            fi
            install_docker
            ;;
        uv)
            install_uv
            ;;
        pip)
            if ! has_python312; then
                error "Python 3.12+ not found."
                exit 1
            fi
            install_pip
            ;;
        auto)
            if has_docker; then
                info "Docker detected — using Docker Compose (recommended)"
                install_docker
            elif has_uv; then
                info "uv detected — installing as Python tool"
                install_uv
            elif has_python312; then
                info "Python 3.12+ detected — installing via pip"
                install_pip
            else
                info "No Docker or Python found — installing uv first"
                install_uv
            fi
            ;;
        *)
            error "Unknown method: $OE_METHOD. Use: docker, pip, uv, or auto"
            exit 1
            ;;
    esac

    echo ""
    ok "Installation complete!"
    echo ""
}

main "$@"
