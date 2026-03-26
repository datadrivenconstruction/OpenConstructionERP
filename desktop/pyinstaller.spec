# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for OpenEstimate backend sidecar.

Builds the FastAPI backend into a single executable that Tauri
launches as a sidecar process.

Usage:
    cd desktop
    pyinstaller pyinstaller.spec
"""

import sys
from pathlib import Path

block_cipher = None

# Paths
ROOT = Path(SPECPATH).parent
BACKEND = ROOT / "backend"
FRONTEND_DIST = ROOT / "frontend" / "dist"
DATA_CATALOG = ROOT / "data" / "catalog"

# Collect all backend module packages for hidden imports
modules_dir = BACKEND / "app" / "modules"
hidden_imports = [
    "aiosqlite",
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "app.cli",
    "app.cli_static",
    "app.main",
    "app.config",
    "app.database",
    "app.core",
    "app.core.module_loader",
    "app.core.i18n",
    "app.core.i18n_router",
    "app.core.permissions",
    "app.core.validation",
    "app.core.validation.engine",
    "app.core.validation.rules",
    "app.core.vector",
    "app.core.hooks",
    "app.core.events",
    "app.core.demo_projects",
    "app.core.marketplace",
]

# Auto-discover modules
if modules_dir.is_dir():
    for mod_dir in sorted(modules_dir.iterdir()):
        if mod_dir.is_dir() and (mod_dir / "__init__.py").exists():
            mod_name = mod_dir.name
            hidden_imports.extend([
                f"app.modules.{mod_name}",
                f"app.modules.{mod_name}.models",
                f"app.modules.{mod_name}.schemas",
                f"app.modules.{mod_name}.router",
                f"app.modules.{mod_name}.service",
                f"app.modules.{mod_name}.repository",
                f"app.modules.{mod_name}.manifest",
            ])

# Data files to include
datas = []

# Frontend dist
if FRONTEND_DIST.is_dir():
    datas.append((str(FRONTEND_DIST), "app/_frontend_dist"))

# Translation files, validation rules, etc. from backend
datas.append((str(BACKEND / "app"), "app"))

a = Analysis(
    [str(BACKEND / "app" / "cli.py")],
    pathex=[str(BACKEND)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "scipy",
        "pandas",
        "torch",
        "tensorflow",
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="openestimate-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Keep console for server logging
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="openestimate-server",
)
