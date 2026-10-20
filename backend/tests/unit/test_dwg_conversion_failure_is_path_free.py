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


@pytest.mark.asyncio
async def test_parse_runs_after_the_processing_row_is_committed(tmp_path: Path, monkeypatch) -> None:
    # The heartbeat updates the drawing row from another session; an open
    # transaction here would block it for the whole parse and the drawing
    # would read as orphaned while it was still being processed.
    svc, _repo = _service()
    order: list[str] = []
    svc.session.commit = AsyncMock(side_effect=lambda: order.append("commit"))

    def parse(*_a: Any) -> dict[str, Any]:
        order.append("parse")
        raise ValueError("stop here")

    monkeypatch.setattr(service_mod, "_process_dxf_sync", parse)
    await svc._process_drawing(uuid.uuid4(), str(tmp_path / "x.dxf"))

    assert order[:2] == ["commit", "parse"]


def _failed_run(error: dict[str, Any]):
    report = json.dumps({"status": "FAILED", "error": error, "exit_code": 3})

    def fake_run(fmt: str, _converter: Path, _src: Path, _work: Path, timeout: int) -> ConverterRun:
        return ConverterRun(fmt=fmt, command=["dwg2excel"], returncode=3, stdout=report, status="FAILED")

    return fake_run


@pytest.mark.asyncio
async def test_a_converter_stopped_by_its_time_limit_reads_as_a_timeout(tmp_path: Path, monkeypatch) -> None:
    # dwg2excel reports its own --timeout as DWG_DAMAGED with "Cancelled" in the detail.
    error = {"code": "DWG_DAMAGED", "message_en": "The DWG file is damaged.", "detail": "ContainerError: Cancelled"}
    monkeypatch.setattr("app.modules.boq.cad_import.find_converter", lambda _fmt: Path("dwg2excel.exe"))
    monkeypatch.setattr("app.modules.boq.ddc_runner.run_converter", _failed_run(error))

    svc, repo = _service()
    await svc._handle_dwg(uuid.uuid4(), str(_dwg(tmp_path)))

    assert repo.row.metadata_["error_code"] == "convert_timeout"
    assert "damaged" not in repo.row.error_message


@pytest.mark.asyncio
async def test_the_converters_code_is_kept_without_its_detail(tmp_path: Path, monkeypatch) -> None:
    error = {
        "code": "DWG_DAMAGED",
        "message_en": "The DWG file is damaged.",
        "message_ru": "Файл DWG повреждён.",
        "detail": f"ReaderRefusal at {tmp_path}",
    }
    monkeypatch.setattr("app.modules.boq.cad_import.find_converter", lambda _fmt: Path("dwg2excel.exe"))
    monkeypatch.setattr("app.modules.boq.ddc_runner.run_converter", _failed_run(error))

    svc, repo = _service()
    await svc._handle_dwg(uuid.uuid4(), str(_dwg(tmp_path)))

    assert repo.row.metadata_["error_code"] == "convert_failed"
    assert repo.row.metadata_["converter_error"] == {
        "code": "DWG_DAMAGED",
        "message_en": "The DWG file is damaged.",
        "message_ru": "Файл DWG повреждён.",
    }


def test_the_dwg_converter_gets_a_time_limit_below_ours(tmp_path: Path) -> None:
    from app.modules.boq.ddc_runner import build_command

    cmd = build_command("dwg", tmp_path / "dwg2excel.exe", tmp_path / "a.dwg", tmp_path / "out", timeout=900)
    assert cmd[-2:] == ["--timeout", "885"]


@pytest.mark.asyncio
async def test_a_conversion_that_breaks_its_session_is_still_marked_failed(tmp_path: Path, monkeypatch) -> None:
    # A connection dropped mid-conversion (idle-in-transaction timeout) used to leave
    # the row in "processing"; the page then blamed a server restart.
    marked: list[tuple[uuid.UUID, str]] = []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def commit(self):
            return None

        async def rollback(self):
            return None

    async def broken(self, _drawing_id, _path):
        raise RuntimeError("Can't reconnect until invalid transaction is rolled back")

    async def mark(self, drawing_id, code, _message):
        marked.append((drawing_id, code))

    async def no_beat(_drawing_id):
        return None

    monkeypatch.setattr(service_mod, "async_session_factory", _Session)
    monkeypatch.setattr(service_mod, "_beat_while_converting", no_beat)
    monkeypatch.setattr(DwgTakeoffService, "_handle_dwg", broken)
    monkeypatch.setattr(DwgTakeoffService, "_mark_failed", mark)
    drawing_id = uuid.uuid4()

    await service_mod._run_dwg_conversion_in_background(drawing_id, str(tmp_path / "a.dwg"))

    assert marked == [(drawing_id, "convert_failed")]
