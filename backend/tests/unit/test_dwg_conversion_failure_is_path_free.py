# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A failed DWG conversion tells the user what to do, never where the file is.

The converter echoes its input path in its JSON report, and that report used
to be appended to the stored error as ``Details: {"input": "C:\\\\..."}``. The
page showed it verbatim, in English whatever the UI language. The drawing now
carries a stable ``metadata.error_code`` the page translates, and the English
API message holds the next step but no server path.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.modules.boq.ddc_runner import ConverterRun
from app.modules.dwg_takeoff import service as service_mod
from app.modules.dwg_takeoff.service import DwgTakeoffService


class _FakeDrawingRepo:
    def __init__(self) -> None:
        self.row = SimpleNamespace(metadata_={}, status="uploaded", error_message=None)

    async def get_by_id(self, _drawing_id: uuid.UUID) -> Any:
        return self.row

    async def update_fields(self, _drawing_id: uuid.UUID, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self.row, key, value)


def _service() -> tuple[DwgTakeoffService, _FakeDrawingRepo]:
    svc = DwgTakeoffService(AsyncMock())
    repo = _FakeDrawingRepo()
    svc.drawing_repo = repo  # type: ignore[assignment]
    return svc, repo


def _dwg(tmp_path: Path) -> Path:
    path = tmp_path / "3f2a9c1e-uuid.dwg"
    path.write_bytes(b"AC1032" + b"\x00" * 200)
    return path


@pytest.mark.asyncio
async def test_failed_conversion_stores_code_and_no_server_path(tmp_path: Path, monkeypatch) -> None:
    dwg = _dwg(tmp_path)
    report = json.dumps({"input": str(dwg), "status": "FAILED", "exit_code": 3})

    def fake_run(fmt: str, _converter: Path, _src: Path, _work: Path, timeout: int) -> ConverterRun:
        return ConverterRun(fmt=fmt, command=["dwg2excel"], returncode=3, stdout=report, status="FAILED")

    monkeypatch.setattr("app.modules.boq.cad_import.find_converter", lambda _fmt: Path("dwg2excel.exe"))
    monkeypatch.setattr("app.modules.boq.ddc_runner.run_converter", fake_run)

    svc, repo = _service()
    await svc._handle_dwg(uuid.uuid4(), str(dwg))

    assert repo.row.status == "error"
    assert repo.row.metadata_["error_code"] == "convert_failed"
    message = repo.row.error_message
    assert "Details" not in message
    assert str(tmp_path) not in message
    assert "input" not in message
    assert "DXF" in message and "2018" in message


@pytest.mark.asyncio
async def test_parse_failure_hides_the_exception_text(tmp_path: Path, monkeypatch) -> None:
    def boom(path: str, *_a: Any) -> dict[str, Any]:
        raise ValueError(f"Failed to parse DXF file: cannot open {path}")

    monkeypatch.setattr(service_mod, "_process_dxf_sync", boom)
    svc, repo = _service()
    svc.version_repo = AsyncMock()  # type: ignore[assignment]
    secret = str(tmp_path / "dwg_uploads" / "x.dxf")

    await svc._process_drawing(uuid.uuid4(), secret)

    assert repo.row.status == "error"
    assert repo.row.metadata_["error_code"] == "parse_failed"
    assert secret not in repo.row.error_message


@pytest.mark.asyncio
async def test_not_a_dwg_gets_its_own_code(tmp_path: Path) -> None:
    bogus = tmp_path / "renamed.dwg"
    bogus.write_bytes(b"%PDF-1.7 not a drawing")
    svc, repo = _service()

    await svc._handle_dwg(uuid.uuid4(), str(bogus))

    assert repo.row.metadata_["error_code"] == "not_dwg"


@pytest.mark.asyncio
async def test_a_new_revision_clears_the_previous_error_code() -> None:
    svc, repo = _service()
    repo.row.metadata_ = {"error_code": "convert_failed", "keep": 1}

    await svc._set_error_code(uuid.uuid4(), None)

    assert repo.row.metadata_ == {"keep": 1}
