# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Heavy exports render in a worker thread, not on the event loop.

One worker serves every user of an install, and an export rendered on its
event loop answers nobody else until it is done. The BIM COBie and BOQ
workbooks grow with the model, the punch list PDF draws a photo per item with
no limit on items, the closeout package renders a COBie workbook and three
PDFs and deflates every bound document, as an in-process job on that same loop,
a bulk regenerate of property sales documents renders up to 500 PDFs in one
request, and a full project bundle hashes and deflates every file the project
holds.

Each test swaps the renderer for a spy that records the thread it ran on and
then calls the real renderer, and asserts that thread is not the loop's own
thread, which is the thread the test coroutine runs on. The queries stay on the
loop with their session, so the fakes here stand in for the repositories.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


def _recording(seen: list[int], real: Callable[..., Any]) -> Callable[..., Any]:
    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(threading.get_ident())
        return real(*args, **kwargs)

    return spy


def _bim_model() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4(), name="Tower A", discipline="Architectural")


def _bim_elements() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            id=uuid.uuid4(),
            stable_id="room-101",
            element_type="IfcSpace",
            name="Office 101",
            storey="Level 1",
            discipline="Architectural",
            asset_info={},
            is_tracked_asset=False,
            quantities={"area": 42.5, "volume": 127.5},
            properties={},
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            stable_id="ahu-01",
            element_type="AirHandlingUnit",
            name="AHU-01",
            storey="Level 1",
            discipline="MEP",
            asset_info={"manufacturer": "Generic", "model": "AH-100", "asset_tag": "AHU-01"},
            is_tracked_asset=True,
            quantities={},
            properties={},
        ),
    ]


def _bim_service(model: SimpleNamespace, elements: list[SimpleNamespace]) -> Any:
    from app.modules.bim_hub.service import BIMHubService

    service = BIMHubService(MagicMock())
    service.model_repo = SimpleNamespace(get=AsyncMock(return_value=model))
    service.element_repo = SimpleNamespace(list_for_model=AsyncMock(return_value=(elements, len(elements))))
    return service


@pytest.mark.asyncio
async def test_bim_cobie_workbook_is_built_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.bim_hub import exporters

    seen: list[int] = []
    monkeypatch.setattr(exporters, "build_cobie_workbook", _recording(seen, exporters.build_cobie_workbook))
    model = _bim_model()

    xlsx, filename = await _bim_service(model, _bim_elements()).export_cobie(model.id)

    assert xlsx[:2] == b"PK"
    assert filename == "COBie_Tower_A.xlsx"
    assert seen, "the COBie builder never ran"
    assert threading.get_ident() not in seen


@pytest.mark.asyncio
async def test_bim_boq_workbook_is_built_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.bim_hub import exporters

    seen: list[int] = []
    monkeypatch.setattr(exporters, "build_boq_workbook", _recording(seen, exporters.build_boq_workbook))
    model = _bim_model()

    xlsx, filename = await _bim_service(model, _bim_elements()).export_boq(model.id)

    assert xlsx[:2] == b"PK"
    assert filename == "BOQ_Tower_A.xlsx"
    assert seen, "the BOQ builder never ran"
    assert threading.get_ident() not in seen


@pytest.mark.asyncio
async def test_punch_list_pdf_is_rendered_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.punchlist import service as punch_service

    seen: list[int] = []
    # Whichever renderer this install has is the one that must leave the loop.
    monkeypatch.setattr(punch_service, "_build_reportlab_pdf", _recording(seen, punch_service._build_reportlab_pdf))
    monkeypatch.setattr(punch_service, "_build_minimal_pdf", _recording(seen, punch_service._build_minimal_pdf))
    item = SimpleNamespace(
        id=uuid.uuid4(),
        title="Touch up paint at door 1.04",
        description="Scuffed frame",
        status="open",
        priority="medium",
        category="finishes",
        trade="painting",
        assigned_to=None,
        due_date=None,
        resolution_notes=None,
        photos=[],
        metadata_={},
        document_id=None,
        page=None,
        location_x=None,
        location_y=None,
        created_at=None,
        updated_at=None,
        verified_at=None,
        verified_by=None,
        closed_at=None,
    )
    service = punch_service.PunchListService(MagicMock())
    service.repo = SimpleNamespace(all_for_project=AsyncMock(return_value=[item]))
    monkeypatch.setattr(service, "resolve_party_names", AsyncMock(return_value={}))

    pdf = await service.export_pdf(uuid.uuid4())

    assert pdf.startswith(b"%PDF")
    assert seen, "no PDF renderer ran"
    assert threading.get_ident() not in seen


@pytest.mark.asyncio
async def test_closeout_package_renders_and_zips_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.closeout import service as closeout_service

    cover_threads: list[int] = []
    zip_threads: list[int] = []
    monkeypatch.setattr(
        closeout_service, "render_cover_pdf", _recording(cover_threads, closeout_service.render_cover_pdf)
    )
    service = closeout_service.CloseoutService(MagicMock())
    monkeypatch.setattr(
        service, "_assemble_zip", _recording(zip_threads, closeout_service.CloseoutService._assemble_zip)
    )
    service.repo = SimpleNamespace(
        list_slots=AsyncMock(return_value=[]),
        list_bindings_for_package=AsyncMock(return_value={}),
    )
    monkeypatch.setattr(service, "_project_name", AsyncMock(return_value="Riverside Block C"))
    monkeypatch.setattr(service, "gaps", AsyncMock(return_value=[]))
    package = SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4(), project_type="residential", title="Handover")

    zip_bytes, summary = await service._build_zip_blob(package)

    assert zip_bytes[:2] == b"PK"
    assert summary["document_count"] == 0
    assert cover_threads and threading.get_ident() not in cover_threads
    assert zip_threads and threading.get_ident() not in zip_threads


@pytest.mark.asyncio
async def test_property_documents_render_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    # The single-document endpoints and the bulk regenerate (up to 500
    # renders in one request) all go through ``generate_document``.
    from app.modules.property_dev import document_templates
    from app.modules.property_dev.service import PropertyDevService

    seen: list[int] = []

    def fake_render(*args: Any, **kwargs: Any) -> bytes:
        seen.append(threading.get_ident())
        return b"%PDF-1.4 stub"

    monkeypatch.setattr(document_templates, "render_no_objection_certificate_pdf", fake_render)
    contract = SimpleNamespace(id=uuid.uuid4(), plot_id=uuid.uuid4())
    plot = SimpleNamespace(id=contract.plot_id, development_id=uuid.uuid4())
    svc = SimpleNamespace(
        sales_contracts=SimpleNamespace(get_by_id=AsyncMock(return_value=contract)),
        plots=SimpleNamespace(get_by_id=AsyncMock(return_value=plot)),
        developments=SimpleNamespace(get_by_id=AsyncMock(return_value=SimpleNamespace(id=plot.development_id))),
    )

    pdf = await PropertyDevService.generate_document(svc, doc_type="noc", contract_id=contract.id)  # type: ignore[attr-defined]

    assert pdf.startswith(b"%PDF")
    assert seen and threading.get_ident() not in seen


@pytest.mark.asyncio
async def test_project_bundle_is_packed_off_the_loop(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    # A full-scope bundle hashes and deflates every document, photo, drawing
    # and model of the project. The storage read stays on the loop; the
    # encoding, hashing and deflating of every member must not.
    import io
    import json
    import zipfile

    from app.modules.projects import bundle_export
    from app.modules.projects.file_manager_schemas import ExportOptions

    seen: dict[str, list[int]] = {"table": [], "file": [], "bytes": []}
    monkeypatch.setattr(bundle_export, "_write_table", _recording(seen["table"], bundle_export._write_table))
    monkeypatch.setattr(bundle_export, "_pack_file", _recording(seen["file"], bundle_export._pack_file))
    monkeypatch.setattr(bundle_export, "_pack_bytes", _recording(seen["bytes"], bundle_export._pack_bytes))

    async def rows_for_table(_session: Any, project_id: str, key: str, *_: Any) -> list[dict[str, Any]]:
        return [{"id": project_id, "name": "Riverside Block C"}] if key == "projects" else []

    drawing = tmp_path / "site-plan.pdf"
    drawing.write_bytes(b"%PDF-1.4 site plan")
    attachments = [
        ("attachments/documents/d1/site-plan.pdf", "fs", str(drawing)),
        ("attachments/documents/d2/gone.pdf", "fs", str(tmp_path / "gone.pdf")),
        ("attachments/bim/m1/geometry.glb", "key", "bim/p1/m1/geometry.glb"),
    ]
    monkeypatch.setattr(bundle_export, "_rows_for_table", rows_for_table)
    monkeypatch.setattr(bundle_export, "_collect_attachment_paths", AsyncMock(return_value=attachments))
    monkeypatch.setattr(bundle_export, "_read_storage_key", AsyncMock(return_value=b"GLB\x00geometry"))

    raw = await bundle_export.export_bundle(
        MagicMock(), "p1", "Riverside Block C", "EUR", None, ExportOptions(scope="full")
    )

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        assert zf.testzip() is None
        assert zf.read("attachments/documents/d1/site-plan.pdf") == b"%PDF-1.4 site plan"
        assert zf.read("attachments/bim/m1/geometry.glb") == b"GLB\x00geometry"
        assert json.loads(zf.read("tables/projects.json"))[0]["name"] == "Riverside Block C"
        index = {entry["path"]: entry for entry in json.loads(zf.read("attachments/index.json"))}
    assert index["attachments/documents/d2/gone.pdf"]["missing"] is True
    assert index["attachments/documents/d1/site-plan.pdf"]["size_bytes"] == len(b"%PDF-1.4 site plan")
    for name, threads in seen.items():
        assert threads, f"{name} packing never ran"
        assert threading.get_ident() not in threads, f"{name} packing ran on the event loop"


@pytest.mark.asyncio
async def test_closeout_cobie_is_built_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.bim_hub.exporters import cobie
    from app.modules.closeout.service import CloseoutService

    seen: list[int] = []
    monkeypatch.setattr(cobie, "build_cobie_workbook", _recording(seen, cobie.build_cobie_workbook))
    model_result = MagicMock()
    model_result.scalars.return_value.first.return_value = _bim_model()
    elements_result = MagicMock()
    elements_result.scalars.return_value.all.return_value = _bim_elements()
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[model_result, elements_result])
    notes: list[str] = []

    blob = await CloseoutService(session)._render_cobie(uuid.uuid4(), notes)

    assert blob is not None and blob[:2] == b"PK", notes
    assert seen and threading.get_ident() not in seen
