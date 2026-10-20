# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every way the server is started keeps idle connections longer than uvicorn's 5 s default.

Under a busy conversion the event loop can stall for ~5 s; with the default the
keep-alive close then wins the race against a client reusing the connection and
the client sees "server disconnected" (5 of 71 batch uploads).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_the_cli_and_module_entry_points_raise_keep_alive() -> None:
    for rel in ("backend/app/cli.py", "backend/app/__main__.py"):
        assert "timeout_keep_alive=75" in (ROOT / rel).read_text(encoding="utf-8"), rel


def test_the_container_entrypoint_raises_keep_alive() -> None:
    assert "--timeout-keep-alive 75" in (ROOT / "deploy/docker/entrypoint.sh").read_text(encoding="utf-8")
