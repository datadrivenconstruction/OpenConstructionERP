# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""EPD file ingestion: magic-byte validation tests.

The carbon module accepts EPD documents in three formats:
    - PDF  (Environmental Product Declaration document — magic: %PDF)
    - XML  (ILCD+EPD / EN 15804 schema — magic: <?xml or <epd)
    - JSON (EC3 / BuildingTransparency API payload)

Any other binary is rejected with HTTP 415 Unsupported Media Type.

Tests here cover the pure ``validate_epd_file_magic`` helper and the
service-level ``ingest_epd_document`` gate (service stubbed so no DB
needed for the magic-byte checks).
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# ── SQLite isolation (before app imports) ──────────────────────────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-carbon-epd-"))
_TMP_DB = _TMP_DIR / "carbon_epd.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app.modules.carbon.service import (  # noqa: E402
    ALLOWED_EPD_MIME_TYPES,
    EPD_MAGIC_BYTES,
    ingest_epd_document,
    validate_epd_file_magic,
)

# ── Pure magic-byte helper ─────────────────────────────────────────────────


def test_validate_epd_magic_pdf_accepted() -> None:
    """PDF magic bytes (%PDF-) pass validation."""
    buf = b"%PDF-1.4 fake pdf content"
    result = validate_epd_file_magic(buf)
    assert result == "pdf"


def test_validate_epd_magic_xml_with_xml_declaration_accepted() -> None:
    """XML files starting with <?xml pass validation."""
    buf = b"<?xml version='1.0' encoding='utf-8'?><epd:EPD/>"
    result = validate_epd_file_magic(buf)
    assert result == "xml"


def test_validate_epd_magic_xml_bare_tag_accepted() -> None:
    """XML files starting with <EPD or <epd (no XML declaration) accepted."""
    buf = b"<EPD xmlns='urn:test'>"
    result = validate_epd_file_magic(buf)
    assert result == "xml"


def test_validate_epd_magic_xml_ilcd_accepted() -> None:
    """ILCD EPD XML wrapper accepted."""
    buf = b"<processDataSet xmlns='http://lca.jrc.it/ILCD/Process'"
    result = validate_epd_file_magic(buf)
    assert result == "xml"


def test_validate_epd_magic_json_object_accepted() -> None:
    """JSON object payload (EC3 format) accepted."""
    payload = json.dumps(
        {
            "name": "GGBS C30/37",
            "gwp_a1a3": 0.083,
            "declared_unit": "kg",
        }
    ).encode()
    result = validate_epd_file_magic(payload)
    assert result == "json"


def test_validate_epd_magic_json_array_rejected() -> None:
    """JSON arrays are not valid EPD documents — reject."""
    buf = b"[1, 2, 3]"
    with pytest.raises(ValueError, match="415"):
        validate_epd_file_magic(buf)


def test_validate_epd_magic_zip_rejected() -> None:
    """ZIP magic (PK\\x03\\x04) must reject with ValueError."""
    buf = b"PK\x03\x04local file header signature..."
    with pytest.raises(ValueError, match="415"):
        validate_epd_file_magic(buf)


def test_validate_epd_magic_exe_rejected() -> None:
    """DOS/PE executable (MZ header) must reject."""
    buf = b"MZ\x90\x00\x03\x00"
    with pytest.raises(ValueError, match="415"):
        validate_epd_file_magic(buf)


def test_validate_epd_magic_empty_rejected() -> None:
    """Empty file must reject."""
    with pytest.raises(ValueError, match="415"):
        validate_epd_file_magic(b"")


def test_validate_epd_magic_too_short_rejected() -> None:
    """Files shorter than minimum magic length must reject."""
    with pytest.raises(ValueError, match="415"):
        validate_epd_file_magic(b"XY")


def test_validate_epd_magic_png_rejected() -> None:
    """PNG image must reject (common accidental upload)."""
    buf = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    with pytest.raises(ValueError, match="415"):
        validate_epd_file_magic(buf)


# ── Constants exported by service ─────────────────────────────────────────


def test_allowed_mime_types_coverage() -> None:
    """ALLOWED_EPD_MIME_TYPES must include pdf, xml and json variants."""
    expected = {"application/pdf", "text/xml", "application/xml", "application/json"}
    assert expected.issubset(ALLOWED_EPD_MIME_TYPES), f"Missing MIME types: {expected - ALLOWED_EPD_MIME_TYPES}"


def test_epd_magic_bytes_keys_present() -> None:
    """EPD_MAGIC_BYTES dict must cover pdf, xml, json signatures."""
    assert "pdf" in EPD_MAGIC_BYTES
    assert "xml" in EPD_MAGIC_BYTES
    assert "json" in EPD_MAGIC_BYTES


# ── Service-level: ingest_epd_document gate ───────────────────────────────


@pytest.mark.asyncio
async def test_ingest_epd_document_pdf_accepted() -> None:
    """Valid PDF binary triggers EPD record creation, returns record."""
    mock_service = MagicMock()
    mock_service.ingest_epd_by_identifier = AsyncMock(
        return_value=MagicMock(
            id=uuid.uuid4(),
            epd_id="test:123",
            source="custom",
            material_class="concrete",
            gwp_a1a3=Decimal("0.13"),
        )
    )
    buf = b"%PDF-1.4 fake content"
    record = await ingest_epd_document(
        service=mock_service,
        file_bytes=buf,
        identifier="custom:test-123",
        gwp_a1a3=Decimal("0.13"),
        product_name="Test EPD",
        material_class="concrete",
    )
    mock_service.ingest_epd_by_identifier.assert_called_once()
    assert record is not None


@pytest.mark.asyncio
async def test_ingest_epd_document_xml_accepted() -> None:
    """Valid XML binary triggers EPD record creation."""
    mock_service = MagicMock()
    mock_service.ingest_epd_by_identifier = AsyncMock(
        return_value=MagicMock(
            id=uuid.uuid4(),
            epd_id="oekobaudat:test",
            source="oekobaudat",
            material_class="concrete",
            gwp_a1a3=Decimal("0.09"),
        )
    )
    buf = b"<?xml version='1.0'?><EPD/>"
    record = await ingest_epd_document(
        service=mock_service,
        file_bytes=buf,
        identifier="oekobaudat:1.4.01.04",
        gwp_a1a3=Decimal("0.09"),
        product_name="GGBS Blended Cement",
        material_class="concrete",
    )
    mock_service.ingest_epd_by_identifier.assert_called_once()
    assert record is not None


@pytest.mark.asyncio
async def test_ingest_epd_document_unknown_type_raises_415() -> None:
    """Non-PDF/XML/JSON binary must raise HTTPException 415."""
    mock_service = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await ingest_epd_document(
            service=mock_service,
            file_bytes=b"PK\x03\x04 this is a zip file",
            identifier="custom:bad",
            gwp_a1a3=Decimal("0.13"),
            product_name="Bad upload",
            material_class="unknown",
        )
    assert exc.value.status_code == 415
    mock_service.ingest_epd_by_identifier.assert_not_called()


@pytest.mark.asyncio
async def test_ingest_epd_document_empty_raises_415() -> None:
    """Empty upload must raise 415, not 500."""
    mock_service = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await ingest_epd_document(
            service=mock_service,
            file_bytes=b"",
            identifier="custom:empty",
            gwp_a1a3=Decimal("0.13"),
            product_name="Empty",
            material_class="concrete",
        )
    assert exc.value.status_code == 415


@pytest.mark.asyncio
async def test_ingest_epd_document_json_payload_accepted() -> None:
    """JSON EPD payload (EC3 format) is accepted and forwarded."""
    mock_service = MagicMock()
    mock_service.ingest_epd_by_identifier = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
    payload = json.dumps({"name": "GGBS", "gwp_a1a3": 0.083}).encode()
    record = await ingest_epd_document(
        service=mock_service,
        file_bytes=payload,
        identifier="ec3:ggbs-001",
        gwp_a1a3=Decimal("0.083"),
        product_name="GGBS",
        material_class="cement_supplement",
    )
    mock_service.ingest_epd_by_identifier.assert_called_once()


# ── Formats handled (informational, not a gate) ───────────────────────────

_HANDLED_FORMATS = ("PDF", "XML (ILCD+EPD / EN 15804)", "JSON (EC3 / BuildingTransparency)")


def test_handled_epd_formats_documented() -> None:
    """Smoke-test that the handled-format tuple is present and non-empty."""
    assert len(_HANDLED_FORMATS) >= 3
