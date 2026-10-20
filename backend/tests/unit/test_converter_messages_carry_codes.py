# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Converter and CAD-upload refusals carry a stable code, and the facts agree.

Three things are pinned here:

* every version and format range the screens show comes from
  ``converter_source.PACKAGES``, and no converter row names a path on the disk;
* a refused BIM Hub upload answers with ``{code, message, params}`` so the UI
  can translate it, and a drawing or a corrupt file never leaves a model row;
* on a host without a converter build (Linux, macOS) every path that needs one
  says so with the same code and a next step, instead of offering an install
  that cannot succeed.
"""

from __future__ import annotations

import io
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile
from starlette.datastructures import Headers

from app.core.converter_source import PACKAGES
from app.modules.bim_hub import router as bim_router
from app.modules.boq import cad_import
from app.modules.takeoff import router as takeoff_router

OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 1016
IFC = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"


def _file(name: str, content: bytes) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=name,
        headers=Headers({"content-type": "application/octet-stream"}),
    )


def _service() -> MagicMock:
    service = MagicMock()
    service.session = MagicMock()
    service.create_model = AsyncMock()
    service.update_model = AsyncMock()
    return service


async def _upload_cad(name: str, content: bytes, service: MagicMock):
    return await bim_router.upload_cad_file(
        background_tasks=BackgroundTasks(),
        project_id=str(uuid.uuid4()),
        name="",
        discipline="architecture",
        parent_model_id=None,
        conversion_depth="standard",
        file=_file(name, content),
        user_id=f"user-{uuid.uuid4()}",
        _perm=None,
        service=service,
    )


@pytest.fixture(autouse=True)
def _project_access_granted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bim_router, "_verify_project_access", AsyncMock())


@pytest.fixture
def linux_without_converters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(cad_import, "find_converter", lambda _fmt: None)


def _detail(exc: pytest.ExceptionInfo[HTTPException]) -> dict:
    detail = exc.value.detail
    assert isinstance(detail, dict), f"detail must carry a code, got {detail!r}"
    assert set(detail) >= {"code", "message", "params"}
    return detail


# ── One source for versions and ranges ───────────────────────────────────


def test_every_package_declares_the_range_it_reads() -> None:
    assert PACKAGES["rvt"].format_range == "Revit 2019-2027"
    assert PACKAGES["dwg"].format_range == "DWG R13-2018"
    assert PACKAGES["ifc"].format_range == "IFC2x3, IFC4"
    assert PACKAGES["ifc"].produces_geometry is False
    assert "dgn" not in PACKAGES


@pytest.mark.asyncio
async def test_the_converter_listing_reads_versions_and_ranges_from_the_packages(monkeypatch) -> None:
    monkeypatch.setattr(cad_import, "find_converter", lambda _fmt: None)
    body = await takeoff_router.list_converters(verify=False, user=None)
    rows = {row["id"]: row for row in body["converters"]}

    assert set(rows) == {"rvt", "ifc", "dwg"}
    for fmt, pkg in PACKAGES.items():
        assert rows[fmt]["version"] == pkg.version
        assert rows[fmt]["format_range"] == pkg.format_range
        assert (
            pkg.format_range in rows[fmt]["description"]
            or pkg.format_range.removeprefix("DWG ") in rows[fmt]["description"]
        )
        assert "path" not in rows[fmt], "the exe location must not leave the server"


@pytest.mark.asyncio
async def test_an_installed_converter_row_has_no_path_even_for_a_signed_in_caller(monkeypatch, tmp_path) -> None:
    exe = tmp_path / "RVTconverter.exe"
    monkeypatch.setattr(cad_import, "find_converter", lambda fmt: exe if fmt == "rvt" else None)
    body = await takeoff_router.list_converters(verify=False, user={"sub": "someone"})
    row = next(r for r in body["converters"] if r["id"] == "rvt")
    assert row["installed"] is True
    assert "path" not in row
    assert str(tmp_path) not in repr(body)


# ── BIM Hub upload refusals ──────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["plan.dwg", "plan.dxf"])
async def test_a_drawing_is_refused_before_any_model_row_and_points_to_dwg_takeoff(name: str) -> None:
    service = _service()
    with pytest.raises(HTTPException) as exc:
        await _upload_cad(name, b"AC1027" + b"\x00" * 100, service)

    detail = _detail(exc)
    assert exc.value.status_code == 400
    assert detail["code"] == "drawing_use_dwg_takeoff"
    assert detail["params"]["filename"] == name
    service.create_model.assert_not_awaited()


@pytest.mark.asyncio
async def test_dgn_is_not_an_accepted_cad_upload() -> None:
    assert ".dgn" not in bim_router._ALLOWED_CAD_EXTENSIONS
    assert ".dgn" not in bim_router._NEEDS_CONVERTER_EXTS
    service = _service()
    with pytest.raises(HTTPException) as exc:
        await _upload_cad("bridge.dgn", OLE, service)
    assert _detail(exc)["code"] == "unsupported_cad_file_type"
    service.create_model.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_text_file_gets_a_coded_refusal_with_the_accepted_list_as_a_param() -> None:
    service = _service()
    with pytest.raises(HTTPException) as exc:
        await _upload_cad("notes.txt", b"hello", service)
    detail = _detail(exc)
    assert detail["code"] == "unsupported_cad_file_type"
    assert detail["params"]["ext"] == ".txt"
    assert detail["params"]["accepted"] == ".ifc, .rvt"
    service.create_model.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_mesh_file_is_pointed_to_the_3d_uploader_with_a_code() -> None:
    with pytest.raises(HTTPException) as exc:
        await _upload_cad("thing.fbx", b"Kaydara FBX Binary", _service())
    assert _detail(exc)["code"] == "mesh_use_3d_uploader"


@pytest.mark.asyncio
@pytest.mark.parametrize("converter_present", [True, False])
async def test_a_file_that_is_not_a_cad_container_leaves_no_row_whatever_the_converter_state(
    monkeypatch, converter_present: bool
) -> None:
    """The content check runs before the "converter missing" placeholder is created."""
    monkeypatch.setattr(cad_import, "find_converter", lambda _fmt: "x.exe" if converter_present else None)
    monkeypatch.setattr(cad_import, "converter_supported_here", lambda: True)
    service = _service()
    with pytest.raises(HTTPException) as exc:
        await _upload_cad("fake.rvt", b"this is not a revit file at all", service)

    detail = _detail(exc)
    assert detail["code"] == "file_content_mismatch"
    assert detail["params"]["filename"] == "fake.rvt"
    service.create_model.assert_not_awaited()


# ── Hosts without a converter build ──────────────────────────────────────


@pytest.mark.asyncio
async def test_linux_rvt_upload_in_bim_hub_is_refused_with_the_platform_code(linux_without_converters) -> None:
    service = _service()
    with pytest.raises(HTTPException) as exc:
        await _upload_cad("house.rvt", OLE, service)

    detail = _detail(exc)
    assert detail["code"] == "converter_platform_unsupported"
    assert detail["params"] == {"format": "RVT"}
    assert "Windows" in detail["message"]
    assert "DXF" in detail["message"]
    service.create_model.assert_not_awaited()


def test_ifc_never_waits_for_a_converter_in_bim_hub() -> None:
    """IFC opens with the built-in reader, so it is not gated on a converter build."""
    assert ".ifc" not in bim_router._NEEDS_CONVERTER_EXTS


def test_ensure_converter_on_linux_raises_the_platform_code(linux_without_converters) -> None:
    for fmt in ("rvt", "ifc", "dwg"):
        with pytest.raises(cad_import.ConverterUnavailableError) as exc:
            cad_import.ensure_converter(fmt)
        assert exc.value.code == "converter_platform_unsupported"
        assert exc.value.params == {"format": fmt.upper()}
        assert cad_import.converter_error_detail(exc.value)["code"] == "converter_platform_unsupported"


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "content"), [("house.rvt", OLE), ("model.ifc", IFC), ("plan.dwg", b"AC1027")])
async def test_linux_cad_extract_answers_with_the_platform_code(linux_without_converters, name, content) -> None:
    with pytest.raises(HTTPException) as exc:
        await takeoff_router.cad_extract(file=_file(name, content))
    assert exc.value.status_code == 400
    assert _detail(exc)["code"] == "converter_platform_unsupported"


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "content"), [("house.rvt", OLE), ("model.ifc", IFC), ("plan.dwg", b"AC1027")])
async def test_linux_cad_columns_answers_with_the_platform_code(linux_without_converters, name, content) -> None:
    with pytest.raises(HTTPException) as exc:
        await takeoff_router.cad_columns(file=_file(name, content), session=None, user_id=None)
    assert exc.value.status_code == 400
    assert _detail(exc)["code"] == "converter_platform_unsupported"


@pytest.mark.asyncio
async def test_cad_extract_unsupported_extension_is_coded() -> None:
    with pytest.raises(HTTPException) as exc:
        await takeoff_router.cad_extract(file=_file("bridge.dgn", b"x"))
    detail = _detail(exc)
    assert detail["code"] == "unsupported_cad_extension"
    assert "dgn" not in detail["params"]["accepted"]
