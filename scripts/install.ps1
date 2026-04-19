# OpenConstructionERP — One-Line Installer for Windows
#
# Usage:
#   irm https://get.openconstructionerp.com/windows | iex
#
# What it does:
#   1. If Docker Desktop is running → runs via docker compose
#   2. If Python 3.12+ is installed → installs via pip
#   3. Otherwise → installs uv → installs via uv

$ErrorActionPreference = "Stop"

$OE_VERSION = if ($env:OE_VERSION) { $env:OE_VERSION } else { "latest" }
$OE_INSTALL_DIR = if ($env:OE_INSTALL_DIR) { $env:OE_INSTALL_DIR } else { "$env:LOCALAPPDATA\OpenConstructionERP" }
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
    # Must treat future major versions (Python 4.x) as satisfying "3.12+":
    # the naive ``$major -ge 3 -and $minor -ge 12`` fails for 4.0-4.11
    # because 4.0 < 3.12 component-wise. Use proper major/minor compare.
    try {
        $ver = & python --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            return ($major -gt 3) -or (($major -eq 3) -and ($minor -ge 12))
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

    Write-Info "Starting OpenConstructionERP..."
    & docker compose up -d
    if ($LASTEXITCODE -ne 0) {
        Write-Err "docker compose up failed (exit code $LASTEXITCODE)"
        exit 1
    }

    # Wait for health check
    Write-Info "Waiting for health check..."
    $healthy = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $resp = Invoke-RestMethod -Uri "http://localhost:$OE_PORT/api/health" -TimeoutSec 2
            if ($resp.status -eq "healthy") {
                $healthy = $true
                break
            }
        } catch {}
        Start-Sleep -Seconds 2
    }

    if ($healthy) {
        Write-Ok "OpenConstructionERP is running at http://localhost:$OE_PORT"
    } else {
        Write-Warn "Service started but health check did not pass within 60s"
        Write-Host "  Check logs: cd $OE_INSTALL_DIR; docker compose logs -f"
    }
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
        # astral's installer drops uv.exe into %USERPROFILE%\.local\bin
        # but does NOT refresh the current session's PATH. Without this
        # the immediate ``& uv tool install`` below can't find uv.exe.
        $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    }

    # Prefer the full path — survives ``$env:Path`` being wiped by a
    # profile script mid-session.
    $uvPath = if (Test-Path "$env:USERPROFILE\.local\bin\uv.exe") {
        "$env:USERPROFILE\.local\bin\uv.exe"
    } else { "uv" }

    & $uvPath tool install openconstructionerp
    if ($LASTEXITCODE -ne 0) {
        Write-Err "uv tool install failed (exit code $LASTEXITCODE)"
        exit 1
    }
    Write-Ok "OpenConstructionERP installed!"
    Write-Host ""
    Write-Host "Run: openconstructionerp serve --port $OE_PORT --open"
}

function Install-Pip {
    Write-Host ""
    Write-Host "  +-------------------------------------------------+"
    Write-Host "  |  Installing OpenConstructionERP (pip mode)      |"
    Write-Host "  +-------------------------------------------------+"
    Write-Host ""

    # 1. Verify Python
    Write-Info "[1/5] Checking Python 3.12+..."
    if (-not (Test-Python312)) {
        Write-Err "Python 3.12+ is required."
        Write-Host "  Install from: https://www.python.org/downloads/"
        exit 1
    }
    $pyVer = & python --version 2>&1
    Write-Ok "[1/5] Found $pyVer"

    # 2. Create venv
    Write-Info "[2/5] Creating virtual environment at $OE_INSTALL_DIR\venv ..."
    New-Item -ItemType Directory -Force -Path $OE_INSTALL_DIR | Out-Null
    if (-not (Test-Path "$OE_INSTALL_DIR\venv\Scripts\python.exe")) {
        & python -m venv "$OE_INSTALL_DIR\venv"
        if ($LASTEXITCODE -ne 0) {
            Write-Err "Failed to create venv (exit $LASTEXITCODE)"
            exit 1
        }
    }
    Write-Ok "[2/5] Virtual environment ready"

    # 3. Install package
    Write-Info "[3/5] Installing openconstructionerp from PyPI..."
    & "$OE_INSTALL_DIR\venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    & "$OE_INSTALL_DIR\venv\Scripts\python.exe" -m pip install --quiet --upgrade openconstructionerp
    if ($LASTEXITCODE -ne 0) {
        Write-Err "pip install failed (exit code $LASTEXITCODE)"
        Write-Host "  Try: $OE_INSTALL_DIR\venv\Scripts\python.exe -m pip install openconstructionerp"
        exit 1
    }
    Write-Ok "[3/5] Package installed"

    # 4. Initialise database
    Write-Info "[4/5] Initialising local database..."
    $cliExe = if (Test-Path "$OE_INSTALL_DIR\venv\Scripts\openconstructionerp.exe") {
        "$OE_INSTALL_DIR\venv\Scripts\openconstructionerp.exe"
    } else {
        "$OE_INSTALL_DIR\venv\Scripts\openestimate.exe"
    }
    & $cliExe init-db 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "init-db reported a non-zero exit code, continuing anyway..."
    } else {
        Write-Ok "[4/5] Database ready"
    }

    # 5. Create launcher script
    Write-Info "[5/5] Creating launcher script..."
    @"
@echo off
REM OpenConstructionERP launcher (auto-generated by install.ps1)
"$cliExe" serve --port $OE_PORT --open %*
"@ | Set-Content "$OE_INSTALL_DIR\start.bat" -Encoding ASCII
    Write-Ok "[5/5] Launcher created at $OE_INSTALL_DIR\start.bat"

    Write-Host ""
    Write-Ok "Installation complete!"
    Write-Host ""
    Write-Host "  Start the server:    $OE_INSTALL_DIR\start.bat"
    Write-Host "  Or directly:         $cliExe serve --open"
    Write-Host "  Diagnose problems:   $cliExe doctor"
    Write-Host ""

    # Offer to start now
    $reply = Read-Host "Start the server now? [Y/n]"
    if ($reply -eq "" -or $reply -eq "y" -or $reply -eq "Y") {
        & "$OE_INSTALL_DIR\start.bat"
    }
}

# ── Main ─────────────────────────────────────────────────────
Write-Host ""
Write-Host "  +===============================================+"
Write-Host "  |      OpenConstructionERP Installer            |"
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
