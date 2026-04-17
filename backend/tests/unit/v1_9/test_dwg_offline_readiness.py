"""Unit tests for DWG offline-readiness probe (R3 #9).

Scope:
    - Converter present -> ``ready=True`` with a non-empty message.
    - Converter missing -> ``ready=False`` with an install hint.

The service method is pure (no DB, no I/O beyond ``find_converter``), so
the tests only need to monkeypatch the discovery function.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.boq import cad_import
from app.modules.dwg_takeoff.schemas import DwgOfflineReadinessResponse
from app.modules.dwg_takeoff.service import DwgTakeoffService


def test_offline_readiness_converter_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When ``find_converter('dwg')`` resolves, the probe reports ready=True."""
    fake_exe = tmp_path / "DwgExporter.exe"
    fake_exe.write_bytes(b"\x00" * 2048)  # > the 1 KB size guard in find_converter

    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: fake_exe)

    payload = DwgTakeoffService.get_offline_readiness()

    assert payload["ready"] is True
    assert payload["converter_available"] is True
    assert payload["version"] == "DwgExporter.exe"
    assert payload["message"]
    assert "locally" in payload["message"].lower()

    # Response model accepts the payload shape.
    DwgOfflineReadinessResponse(**payload)


def test_offline_readiness_converter_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no converter is found, the probe returns a clear install hint."""
    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: None)

    payload = DwgTakeoffService.get_offline_readiness()

    assert payload["ready"] is False
    assert payload["converter_available"] is False
    assert payload["version"] is None
    assert "install" in payload["message"].lower()

    DwgOfflineReadinessResponse(**payload)
