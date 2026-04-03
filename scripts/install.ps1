# OpenEstimate — One-Line Installer for Windows
#
# Usage:
#   irm https://get.openestimate.io/windows | iex
#
# What it does:
#   1. If Docker Desktop is running → runs via docker compose
#   2. If Python 3.12+ is installed → installs via pip
#   3. Otherwise → installs uv → installs via uv

$ErrorActionPreference = "Stop"

$OE_VERSION = if ($env:OE_VERSION) { $env:OE_VERSION } else { "latest" }
$OE_INSTALL_DIR = if ($env:OE_INSTALL_DIR) { $env:OE_INSTALL_DIR } else { "$env:LOCALAPPDATA\OpenEstimate" }
$OE_PORT = if ($env:OE_PORT) { $env:OE_PORT } else { "8080" }
$OE_REPO = "https://github.com/datadrivenconstruction/OpenConstructionERP"

function Write-Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Blue }
function Write-Ok($msg)   { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "[ERROR] $msg" -ForegroundColor Red }

function Test-Docker {
    try {
        $null = & docker info 2>&1
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Test-Python312 {
    try {
        $ver = & python --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            return ($major -ge 3 -and $minor -ge 12)
        }
        return $false
    } catch {
        return $false
    }
}

function Test-Uv {
    try {
        $null = & uv --version 2>&1
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Install-Docker {
    Write-Info "Installing via Docker..."
    New-Item -ItemType Directory -Force -Path $OE_INSTALL_DIR | Out-Null
    Set-Location $OE_INSTALL_DIR

    $url = "$OE_REPO/raw/main/docker-compose.quickstart.yml"
    Invoke-WebRequest -Uri $url -OutFile "docker-compose.yml"

    Write-Info "Starting OpenEstimate..."
    & docker compose up -d

    Write-Ok "OpenEstimate is running at http://localhost:$OE_PORT"
    Write-Host ""
    Write-Host "Commands:"
    Write-Host "  cd $OE_INSTALL_DIR; docker compose logs -f   # View logs"
    Write-Host "  cd $OE_INSTALL_DIR; docker compose down      # Stop"
}

function Install-Uv {
    Write-Info "Installing via uv..."

    if (-not (Test-Uv)) {
        Write-Info "Installing uv package manager..."
        irm https://astral.sh/uv/install.ps1 | iex
    }

    & uv tool install openestimate
    Write-Ok "OpenEstimate installed!"
    Write-Host ""
    Write-Host "Run: openestimate serve --port $OE_PORT --open"
}

function Install-Pip {
    Write-Info "Installing via pip..."
    New-Item -ItemType Directory -Force -Path $OE_INSTALL_DIR | Out-Null

    & python -m venv "$OE_INSTALL_DIR\venv"
    & "$OE_INSTALL_DIR\venv\Scripts\Activate.ps1"
    & pip install --upgrade pip
    & pip install openestimate

    Write-Ok "OpenEstimate installed in $OE_INSTALL_DIR\venv"

    # Create start script
    @"
@echo off
call "$OE_INSTALL_DIR\venv\Scripts\activate.bat"
openestimate serve %*
"@ | Set-Content "$OE_INSTALL_DIR\start.bat"

    Write-Host ""
    Write-Host "Run: $OE_INSTALL_DIR\start.bat --port $OE_PORT"
}

# ── Main ─────────────────────────────────────────────────────
Write-Host ""
Write-Host "  +===============================================+"
Write-Host "  |      OpenEstimate Installer                   |"
Write-Host "  |      Construction Cost Estimation Platform    |"
Write-Host "  +===============================================+"
Write-Host ""

if (Test-Docker) {
    Write-Info "Docker detected — using Docker Compose (recommended)"
    Install-Docker
} elseif (Test-Uv) {
    Write-Info "uv detected — installing as Python tool"
    Install-Uv
} elseif (Test-Python312) {
    Write-Info "Python 3.12+ detected — installing via pip"
    Install-Pip
} else {
    Write-Info "No Docker or Python found — installing uv first"
    Install-Uv
}

Write-Host ""
Write-Ok "Installation complete!"
Write-Host ""
