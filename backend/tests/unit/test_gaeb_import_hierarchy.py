# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The GAEB import must PERSIST the LV hierarchy, not only parse it.

The importer emits ``BoQCtgy`` section rows parent-before-children (proven by
``test_gaeb_frankfurt_fixture.py``), but the persistence step used to drop the
links: ``_prepared_row_to_create`` built every ``PositionCreate`` without a
``parent_id``, so sections landed with zero children and every real item ended
up ungrouped. On camera this read as a filled "Abschnitt" column in the import
preview followed by "0 Abschnitte" in the editor and the export summary.

These tests drive the real import->persist path against a recording fake
service (no database):

* the Frankfurt Rohbau X83 fixture persists its full three-level hierarchy
  (Gewerk -> five sub-sections -> 21 items, no item left unparented);
* explicit ``gaeb_section`` identity wins over document order;
* a flat sheet without any section rows keeps creating top-level positions
  (the same helper serves the Excel / BC3 importers);
* a flat sheet WITH section header rows adopts the rows that follow each
  header, which is how the exported sheet reads.

Run::

    cd backend
    python -m pytest tests/unit/test_gaeb_import_hierarchy.py -v --tb=short
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from app.modules.boq.importers.gaeb_xml import GAEBXMLImporter
from app.modules.boq.router import _apply_boq_roundtrip, _persist_imported_boq
from app.modules.boq.schemas import PositionCreate

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "gaeb" / "frankfurt_rohbau_x83.x83"

_BOQ_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class _CreatedPosition:
    """Attribute stand-in for the ORM ``Position`` returned by ``add_position``."""

    def __init__(self, data: PositionCreate) -> None:
        self.id = uuid.uuid4()
        self.boq_id = data.boq_id
        self.parent_id = data.parent_id
        self.ordinal = data.ordinal
        self.description = data.description
        self.unit = data.unit


class _EmptyBOQ:
    """``get_boq_with_positions`` result for a freshly created, empty BOQ."""

    positions: list[Any] = []


class _RecordingService:
    """Minimal ``BOQService`` stand-in recording every created position.

    The import path under test only ever reads the current positions (empty
    BOQ) and creates new ones; update/delete/markup are stubbed so an
    accidental call fails loudly instead of passing silently.
    """

    def __init__(self) -> None:
        self.created: list[_CreatedPosition] = []

    async def get_boq_with_positions(self, boq_id: Any) -> _EmptyBOQ:  # noqa: ARG002
        return _EmptyBOQ()

    async def add_position(self, data: PositionCreate) -> _CreatedPosition:
        pos = _CreatedPosition(data)
        self.created.append(pos)
        return pos

    async def update_position(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("import into an empty BOQ must not update positions")

    async def delete_position(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("import into an empty BOQ must not delete positions")

    async def add_markup(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the Frankfurt fixture carries no markup items")

    async def list_markups(self, boq_id: Any) -> list[Any]:  # noqa: ARG002
        """The empty destination has no earlier imported deduction credit."""
        return []


def _by_ordinal(service: _RecordingService) -> dict[str, _CreatedPosition]:
    return {p.ordinal: p for p in service.created}


@pytest.mark.skipif(not _FIXTURE.exists(), reason="Frankfurt X83 fixture not present")
class TestGAEBImportPersistsHierarchy:
    @pytest.mark.asyncio
    async def test_frankfurt_hierarchy_survives_persistence(self) -> None:
        """Gewerk -> sub-sections -> items, linked exactly as the file nests them."""
        imported = await GAEBXMLImporter.parse(_FIXTURE.read_bytes())
        service = _RecordingService()

        summary = await _persist_imported_boq(
            _BOQ_ID,
            imported,
            file_name="frankfurt_rohbau_x83.x83",
            service=service,  # type: ignore[arg-type]
        )

        assert summary["apply_errors"] == []
        rows = _by_ordinal(service)

        # The six section rows: the Gewerk plus its five sub-sections.
        sections = {p.ordinal for p in service.created if p.unit == "section"}
        assert sections == {"01", "01.01", "01.02", "01.03", "01.04", "01.05"}

        # The Gewerk is top-level; every sub-section nests under it.
        assert rows["01"].parent_id is None
        for sub in ("01.01", "01.02", "01.03", "01.04", "01.05"):
            assert rows[sub].parent_id == rows["01"].id, f"{sub} not nested under the Gewerk"

        # Every one of the 21 items hangs under exactly its own sub-section -
        # nothing is left ungrouped (the on-camera defect).
        items = [p for p in service.created if p.unit != "section"]
        assert len(items) == 21
        for item in items:
            section_oz = item.ordinal.rsplit(".", 1)[0]
            assert item.parent_id == rows[section_oz].id, (
                f"item {item.ordinal} should be parented under section {section_oz}"
            )

    @pytest.mark.asyncio
    async def test_explicit_section_identity_beats_document_order(self) -> None:
        """A row naming its section via ``gaeb_section`` attaches to THAT section."""
        service = _RecordingService()
        prepared = [
            {
                "row_index": 1,
                "position_id": None,
                "ordinal": "01",
                "description": "Erdarbeiten",
                "unit": "section",
                "quantity": 0.0,
                "unit_rate": 0.0,
                "classification": {"gaeb_section": "01"},
                "source": "gaeb_import",
                "metadata": {"gaeb_is_section": True},
                "is_section": True,
            },
            {
                "row_index": 2,
                "position_id": None,
                "ordinal": "02",
                "description": "Betonarbeiten",
                "unit": "section",
                "quantity": 0.0,
                "unit_rate": 0.0,
                "classification": {"gaeb_section": "02"},
                "source": "gaeb_import",
                "metadata": {"gaeb_is_section": True},
                "is_section": True,
            },
            {
                # Document order says "after 02", the explicit identity says 01.
                "row_index": 3,
                "position_id": None,
                "ordinal": "01.0010",
                "description": "Baugrubenaushub",
                "unit": "m3",
                "quantity": 350.5,
                "unit_rate": 0.0,
                "classification": {},
                "source": "gaeb_import",
                "metadata": {"gaeb_section": "01"},
                "is_section": False,
            },
            {
                # Explicitly top-level: the key is present but empty.
                "row_index": 4,
                "position_id": None,
                "ordinal": "0020",
                "description": "Stundenlohnarbeiten",
                "unit": "hr",
                "quantity": 10.0,
                "unit_rate": 0.0,
                "classification": {},
                "source": "gaeb_import",
                "metadata": {"gaeb_section": ""},
                "is_section": False,
            },
        ]

        summary = await _apply_boq_roundtrip(_BOQ_ID, prepared, service=service)  # type: ignore[arg-type]

        assert summary["apply_errors"] == []
        rows = _by_ordinal(service)
        assert rows["01.0010"].parent_id == rows["01"].id
        assert rows["0020"].parent_id is None

    @pytest.mark.asyncio
    async def test_flat_sheet_without_sections_stays_flat(self) -> None:
        """Excel/BC3 rows without any section rows keep parent_id NULL."""
        service = _RecordingService()
        prepared = [
            {
                "row_index": i,
                "position_id": None,
                "ordinal": f"{i:03d}",
                "description": f"Row {i}",
                "unit": "m2",
                "quantity": 1.0,
                "unit_rate": 5.0,
                "classification": {},
                "source": "excel_import",
                "metadata": {"import_source": "sheet.xlsx"},
                "is_section": False,
            }
            for i in (1, 2, 3)
        ]

        summary = await _apply_boq_roundtrip(_BOQ_ID, prepared, service=service)  # type: ignore[arg-type]

        assert summary["apply_errors"] == []
        assert [p.parent_id for p in service.created] == [None, None, None]

    @pytest.mark.asyncio
    async def test_flat_sheet_section_headers_adopt_following_rows(self) -> None:
        """A section header row groups the rows below it (ENH-087 re-import)."""
        service = _RecordingService()
        prepared = [
            {
                "row_index": 1,
                "position_id": None,
                "ordinal": "01",
                "description": "Substructure",
                "unit": "section",
                "quantity": 0.0,
                "unit_rate": 0.0,
                "classification": {},
                "source": "excel_import",
                "metadata": {"section_header": True},
                "is_section": True,
            },
            {
                "row_index": 2,
                "position_id": None,
                "ordinal": "01.001",
                "description": "Excavation",
                "unit": "m3",
                "quantity": 100.0,
                "unit_rate": 12.0,
                "classification": {},
                "source": "excel_import",
                "metadata": {},
                "is_section": False,
            },
            {
                "row_index": 3,
                "position_id": None,
                "ordinal": "02",
                "description": "Superstructure",
                "unit": "section",
                "quantity": 0.0,
                "unit_rate": 0.0,
                "classification": {},
                "source": "excel_import",
                "metadata": {"section_header": True},
                "is_section": True,
            },
            {
                "row_index": 4,
                "position_id": None,
                "ordinal": "02.001",
                "description": "Concrete frame",
                "unit": "m3",
                "quantity": 50.0,
                "unit_rate": 300.0,
                "classification": {},
                "source": "excel_import",
                "metadata": {},
                "is_section": False,
            },
        ]

        summary = await _apply_boq_roundtrip(_BOQ_ID, prepared, service=service)  # type: ignore[arg-type]

        assert summary["apply_errors"] == []
        rows = _by_ordinal(service)
        assert rows["01"].parent_id is None
        assert rows["02"].parent_id is None
        assert rows["01.001"].parent_id == rows["01"].id
        assert rows["02.001"].parent_id == rows["02"].id
