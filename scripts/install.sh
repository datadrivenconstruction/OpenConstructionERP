#!/bin/bash
# OpenConstructionERP - One-Line Installer for Linux / macOS
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/datadrivenconstruction/OpenConstructionERP/main/scripts/install.sh | bash
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

# ── Compose secrets ──────────────────────────────────────────────────
# 24 bytes of base64, the recipe docker-compose.quickstart.yml carries in its
# own header and the README repeats. 24 is a multiple of 3, so there is no "="
# padding to reason about, and the base64 alphabet cannot emit "@", which is
# the one character that would break the connection URL the stack builds from
# this password: a URL splits its user info at the first "@", so a literal one
# moves the rest of the password into the host. It can emit "/", roughly four
# times in ten, and that is fine, because the parser splits the authority on
# the last "@" and a slash before it changes nothing.
random_password() {
    if command -v openssl &>/dev/null; then
        openssl rand -base64 24
    else
        random_hex_32
    fi
}

# 32 bytes as hex. The fallback reads /dev/urandom through od, which takes
# exactly the bytes it was asked for and exits, so nothing in the pipeline
# gets a SIGPIPE that `set -o pipefail` would turn into an aborted install.
random_hex_32() {
    if command -v openssl &>/dev/null; then
        openssl rand -hex 32
    else
        od -An -tx1 -N32 /dev/urandom | tr -d ' \n'
    fi
}

# Write the two secrets the quickstart compose file will not start without.
# It reads POSTGRES_PASSWORD and JWT_SECRET with compose's fail-fast form on
# purpose, so that nobody runs a stack whose JWT signing key is shared with
# every other reader of the file. Without a .env beside the compose file,
# `docker compose up` stops on an interpolation error and starts nothing,
# which is what this installer did for everyone who had Docker.
#
# The check is per key, not per file. A .env holding one of the two is a state
# a reader reaches easily, since the recipe in the README is two separate
# lines, and a plain "the file is there, leave it alone" test would keep the
# install broken for them. A key that is already present is never rewritten:
# the password in it is the one PostgreSQL initialised its data directory
# with, and generating a new one would lock the user out of their own data.
write_compose_secrets() {
    [ -f .env ] || : > .env

    # Add-on writes go after the last byte, so a file that does not end in a
    # newline would swallow the first new key onto the tail of its last line.
    if [ -s .env ] && [ "$(tail -c 1 .env | wc -l)" -eq 0 ]; then
        printf '\n' >> .env
    fi

    if ! grep -q '^POSTGRES_PASSWORD=' .env; then
        local password
        password="$(random_password)"
        if [ -z "$password" ]; then
            error "Could not generate a database password: no openssl and no readable /dev/urandom."
            exit 1
        fi
        printf 'POSTGRES_PASSWORD=%s\n' "$password" >> .env
        ok "Generated POSTGRES_PASSWORD in $OE_INSTALL_DIR/.env"
    fi

    if ! grep -q '^JWT_SECRET=' .env; then
        local secret
        secret="$(random_hex_32)"
        if [ -z "$secret" ]; then
            error "Could not generate a JWT secret: no openssl and no readable /dev/urandom."
            exit 1
        fi
        printf 'JWT_SECRET=%s\n' "$secret" >> .env
        ok "Generated JWT_SECRET in $OE_INSTALL_DIR/.env"
    fi

    chmod 600 .env 2>/dev/null || true
}

# Record a pinned version in the .env as well, where the two secrets are.
# Exporting it would only reach this process, and the commands printed at the
# end of the install are typed later in a fresh shell, where an exported
# variable is long gone and ${OE_IMAGE_TAG:-latest} would quietly mean latest.
# The .env is read on every compose invocation in this directory, so the pin
# holds for `pull`, for `up`, and for every start after that.
#
# Unlike the two secrets this key is replaced when a later run asks for a
# different version. Overwriting a version pin loses nothing, where overwriting
# the password would lock the user out of the data PostgreSQL already wrote.
pin_image_tag() {
    if grep -q '^OE_IMAGE_TAG=' .env; then
        grep -v '^OE_IMAGE_TAG=' .env > .env.tmp || true
        mv .env.tmp .env
    fi
    printf 'OE_IMAGE_TAG=%s\n' "$1" >> .env
    chmod 600 .env 2>/dev/null || true
}

# ── Install Methods ──────────────────────────────────────────────────
install_docker() {
    info "Installing via Docker..."

    mkdir -p "$OE_INSTALL_DIR"
    cd "$OE_INSTALL_DIR"

    # Download quickstart compose file. -f makes curl exit non-zero on
    # HTTP 4xx/5xx (without it, a 404 silently writes the HTML error page
    # to docker-compose.yml and `docker compose up` then dies on a YAML
    # parse error — opaque failure mode for the user).
    #
    # The image override comes down beside it as docker-compose.override.yml,
    # the name compose merges by itself with no -f flags. Two reasons. The base
    # file builds the app from source and there is no source here, only these
    # two files, so on its own it would stop on a Dockerfile that is not there.
    # And because the name is the automatic one, every plain `docker compose`
    # command run in this directory afterwards, including the ones printed
    # below, keeps meaning the stack that was installed.
    local ref="main"
    [ "$OE_VERSION" = "latest" ] || ref="v$OE_VERSION"
    curl -fsSL "$OE_REPO/raw/$ref/docker-compose.quickstart.yml" -o docker-compose.yml
    curl -fsSL "$OE_REPO/raw/$ref/docker-compose.quickstart.image.yml" -o docker-compose.override.yml

    write_compose_secrets
    [ "$OE_VERSION" = "latest" ] || pin_image_tag "$OE_VERSION"

    # Pulling is spelled out rather than left to `up`, the same way the
    # quickstart-image make target does it, so which artefact runs is stated
    # by the command instead of inferred from compose's build-versus-pull
    # rules for a service that carries both an image and a build section.
    info "Pulling the published image..."
    docker compose pull app

    info "Starting OpenConstructionERP..."
    docker compose up -d

    # Wait for the application to answer, rather than announcing that it runs
    # because compose accepted the command. `docker compose up -d` returns once
    # the containers are created, which is well before anything serves, so the
    # success line below was printed unverified: an install that never came up
    # still said it was running, and the person had no reason to look further.
    # The Windows script has polled this endpoint all along; this one did not
    # poll it at all, which is the more embarrassing of the two failure modes
    # because it is the one that never reports a problem.
    #
    # Three outcomes, because the endpoint reports three. Healthy. Degraded,
    # which as of this release includes an enabled module that failed to load,
    # and which is a usable installation. Or no answer, which is the only one
    # of the three that means the install did not work.
    #
    # Read with grep rather than jq, which a stranger's machine need not have.
    info "Waiting for health check..."
    health_attempts=30
    health_delay=2
    health=""
    for _ in $(seq 1 "$health_attempts"); do
        health=$(curl -fsS --max-time 2 "http://localhost:${OE_PORT}/api/health" 2>/dev/null | tr -d ' \n' || true)
        case "$health" in
            *'"status":"healthy"'*|*'"status":"degraded"'*) break ;;
            *) health="" ;;
        esac
        sleep "$health_delay"
    done

    case "$health" in
        *'"status":"healthy"'*)
            ok "OpenConstructionERP is running at http://localhost:${OE_PORT}"
            ;;
        *'"status":"degraded"'*)
            # The same word covers a missing module, where the product works,
            # and a database the process cannot reach, where it does not.
            if printf '%s' "$health" | grep -q '"database":"ok"'; then
                ok "OpenConstructionERP is running at http://localhost:${OE_PORT}"
                warn "Reporting degraded: not every enabled module loaded"
                echo "  The application is usable. A restart usually loads the rest."
                echo "  Which module is missing is in the log: cd ${OE_INSTALL_DIR} && docker compose logs -f"
            else
                warn "OpenConstructionERP started but cannot reach its database"
                echo "  Check logs: cd ${OE_INSTALL_DIR} && docker compose logs -f"
            fi
            ;;
        *)
            warn "Service started but health check did not answer within $((health_attempts * health_delay))s"
            echo "  Check logs: cd ${OE_INSTALL_DIR} && docker compose logs -f"
            ;;
    esac
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
    # Honour OE_VERSION env var (advertised in file header).
    if [ "$OE_VERSION" = "latest" ]; then
        uv tool install openconstructionerp
    else
        uv tool install "openconstructionerp==$OE_VERSION"
    fi
    ok "OpenConstructionERP installed!"

    # Create systemd service if on Linux
    if [ "$(uname -s)" = "Linux" ] && command -v systemctl &>/dev/null; then
        create_systemd_service
    fi

    echo ""
    echo "Run: openconstructionerp serve --port $OE_PORT"
    echo "     openconstructionerp serve --port $OE_PORT --open  # Also opens browser"
}

install_pip() {
    info "Installing via pip..."

    # Mirror has_python312()'s fallback: pick the first interpreter that is
    # actually >=3.12. Picking `python3` blindly used to install into a
    # 3.10 venv when the system shipped python3.12 only via the versioned
    # binary, then fail at first import with cryptic syntax errors.
    local python_cmd=""
    for cmd in python3.12 python3 python; do
        if command -v "$cmd" &>/dev/null; then
            if "$cmd" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' &>/dev/null; then
                python_cmd="$cmd"
                break
            fi
        fi
    done
    if [ -z "$python_cmd" ]; then
        error "No Python 3.12+ interpreter found on PATH."
        exit 1
    fi
    info "Using $python_cmd ($("$python_cmd" --version 2>&1))"

    # Create virtual environment
    mkdir -p "$OE_INSTALL_DIR"
    $python_cmd -m venv "$OE_INSTALL_DIR/venv"
    source "$OE_INSTALL_DIR/venv/bin/activate"

    # Install. --upgrade so re-running picks up new releases; OE_VERSION
    # pin honours the env var advertised in the file header.
    pip install --upgrade pip
    if [ "$OE_VERSION" = "latest" ]; then
        pip install --upgrade openconstructionerp
    else
        pip install --upgrade "openconstructionerp==$OE_VERSION"
    fi

    ok "OpenConstructionERP installed in $OE_INSTALL_DIR/venv"

    # Convenience launcher.
    cat > "$OE_INSTALL_DIR/start.sh" << 'SCRIPT'
#!/bin/bash
source "$(dirname "$0")/venv/bin/activate"
openconstructionerp serve "$@"
SCRIPT
    chmod +x "$OE_INSTALL_DIR/start.sh"

    # Put the command on PATH via ~/.local/bin, which is on PATH for most
    # shells. This makes a bare `openconstructionerp` work in a new terminal.
    mkdir -p "$HOME/.local/bin"
    ln -sf "$OE_INSTALL_DIR/venv/bin/openconstructionerp" "$HOME/.local/bin/openconstructionerp"

    echo ""
    echo "  +-------------------------------------------------+"
    echo "  |  OpenConstructionERP is installed               |"
    echo "  +-------------------------------------------------+"
    echo ""
    if echo "$PATH" | tr ':' '\n' | grep -qx "$HOME/.local/bin"; then
        echo "  Open a new terminal and run:"
        echo "     openconstructionerp"
    else
        echo "  Add ~/.local/bin to your PATH once:"
        echo "     echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
        echo "  then run:"
        echo "     openconstructionerp"
    fi
    echo ""
    echo "  That starts the server and serves http://localhost:$OE_PORT"
    echo "  Sign in with:  demo@openconstructionerp.com  /  DemoPass1234!"
    echo ""
    echo "  Or start it right now:  $OE_INSTALL_DIR/start.sh --open"
}

create_systemd_service() {
    local service_file="$HOME/.config/systemd/user/openconstructionerp.service"
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
                info "Docker detected, using Docker Compose (recommended)"
                install_docker
            elif has_uv; then
                info "uv detected, installing as Python tool"
                install_uv
            elif has_python312; then
                info "Python 3.12+ detected, installing via pip"
                install_pip
            else
                info "No Docker or Python found, installing uv first"
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
