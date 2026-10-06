# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site-phase refusals reach the UI as codes, not English parser strings."""
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile

from app.modules.boq import gaeb_exchange_router as routes
from app.modules.boq.gaeb_x31 import parse_x31
from app.modules.boq.gaeb_x89 import parse_x89
from app.modules.boq.importers._base import ImporterParseError


@pytest.mark.parametrize("reader", [parse_x31, parse_x89])
@pytest.mark.parametrize("content,code", [
    (b"", "gaeb_empty_file"),
    (b"<GAEB>\n<broken>", "gaeb_not_well_formed"),
    (b'<!DOCTYPE GAEB [<!ENTITY x "unsafe">]><GAEB>&x;</GAEB>', "gaeb_refused"),
    (b"<different/>", "gaeb_wrong_root"),
])
def test_shared_parse_failures_name_the_reason(reader, content, code):
    with pytest.raises(ImporterParseError) as caught:
        reader(content)
    detail = caught.value.as_detail()
    assert detail["code"] == code
    assert detail["message"]
    if code == "gaeb_not_well_formed":
        assert detail["params"] == {"line": 2, "column": 8}
    if code == "gaeb_wrong_root":
        assert detail["params"] == {"root": "different"}


@pytest.mark.parametrize("reader", [parse_x31, parse_x89])
@pytest.mark.parametrize("encoding", ["madeup", "utf-32"])
def test_unsupported_encoding_is_not_misreported_as_an_entity_attack(reader, encoding):
    content = f'<?xml version="1.0" encoding="{encoding}"?><GAEB/>'.encode()
    with pytest.raises(ImporterParseError) as caught:
        reader(content)
    assert caught.value.code == "import_parse_failed"
    assert "encoding" in str(caught.value)
    assert "security" not in str(caught.value)


@pytest.mark.parametrize("reader,expected", [(parse_x31, "X31"), (parse_x89, "X89")])
def test_wrong_phase_names_both_phases(reader, expected):
    with pytest.raises(ImporterParseError) as caught:
        reader(b'<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.3"><Award/></GAEB>')
    assert caught.value.code == "gaeb_wrong_phase"
    assert caught.value.params == {"phase": "X83", "expected": expected}


@pytest.mark.parametrize("reader,content,element,format_name", [
    (parse_x31, b"<GAEB/>", "QtyDeterm", "GAEB X31"),
    (parse_x31, b"<GAEB><QtyDeterm/></GAEB>", "BoQ", "GAEB X31"),
    (parse_x89, b"<GAEB/>", "Invoice", "GAEB X89"),
])
def test_missing_structure_is_specific(reader, content, element, format_name):
    with pytest.raises(ImporterParseError) as caught:
        reader(content)
    assert caught.value.code == "gaeb_missing_element"
    assert caught.value.params == {"element": element, "format": format_name}


@pytest.mark.parametrize("route,extension,format_name", [
    (routes.preview_boq_gaeb_x31, ".x31", "GAEB X31"),
    (routes.check_boq_gaeb_x89, ".x89", "GAEB X89"),
])
@pytest.mark.parametrize("filename,content,code", [
    ("input.pdf", b"file", "gaeb_file_type"),
    ("input.xml", b"", "gaeb_empty_file"),
    ("input.xml", b"<GAEB>", "gaeb_not_well_formed"),
    ("input.xml", b"<wrong/>", "gaeb_wrong_root"),
    ("input.xml", b"<GAEB/>", "gaeb_missing_element"),
])
async def test_both_upload_routes_keep_structured_errors(
    monkeypatch, route, extension, format_name, filename, content, code,
):
    access = AsyncMock()
    monkeypatch.setattr(routes, "_verify_boq", access)
    file = UploadFile(filename=filename, file=BytesIO(content))
    with pytest.raises(HTTPException) as caught:
        await route(uuid4(), "user", {"role": "editor"}, None, file)
    access.assert_awaited_once()
    assert caught.value.status_code == 400
    assert caught.value.detail["code"] == code
    if code == "gaeb_file_type":
        assert caught.value.detail["params"] == {"format": format_name, "extensions": f"{extension}, .xml"}


@pytest.mark.parametrize("route", [routes.preview_boq_gaeb_x31, routes.check_boq_gaeb_x89])
async def test_access_is_checked_before_reading_any_file(monkeypatch, route):
    monkeypatch.setattr(routes, "_verify_boq", AsyncMock(side_effect=HTTPException(404, "not found")))
    upload = AsyncMock()
    with pytest.raises(HTTPException) as caught:
        await route(uuid4(), "stranger", {"role": "editor"}, None, upload)
    assert caught.value.status_code == 404
    upload.read.assert_not_awaited()


@pytest.mark.parametrize("basis,code", [
    ("measured", "gaeb_no_measured_quantities"),
    ("quantity", "gaeb_no_quantities"),
])
async def test_empty_export_does_not_misdescribe_its_basis(monkeypatch, basis, code):
    monkeypatch.setattr(routes, "_verify_boq", AsyncMock())
    service = SimpleNamespace(
        boq_repo=SimpleNamespace(get_by_id=AsyncMock(return_value=SimpleNamespace())),
        position_repo=SimpleNamespace(list_all_for_boq=AsyncMock(return_value=[])),
    )
    monkeypatch.setattr(routes, "_boq_service", lambda _session: service)
    with pytest.raises(HTTPException) as caught:
        await routes.export_boq_gaeb_x31(uuid4(), "user", {"role": "editor"}, None, basis=basis)
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == code
