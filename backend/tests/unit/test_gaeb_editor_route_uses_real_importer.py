# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The BOQ editor's GAEB route imports the file instead of skipping all of it.

``POST /boqs/{id}/import/gaeb/`` used to run an inline walker whose text
helpers read only an element's own ``.text``. GAEB DA XML 3.3 keeps an item's
wording in ``Description/CompleteText/DetailTxt/Text/p/span``, so the walker
located ``<Text>``, read the whitespace in front of its ``<p>`` child, found
nothing, fell back to ``<OutlineText>.text`` for the same empty result, and
skipped every Item for having no description. Measured over every GAEB fixture
in this repo it imported 0 of 27 items from the X84, 0 of 27 from the X83 and
0 of 21 from the Frankfurt X83.

The route now runs the registered :class:`GAEBXMLImporter`. These tests drive
the endpoint function itself, so they cover the parse, the persistence and the
response contract in one pass, and they assert against real PostgreSQL rows
rather than against the parser's return value: ``_persist_imported_boq``
creates a row per section as well as per line item, and the two counts differ.

The contract is frozen. The route, the request and the response field names do
not change, ``skipped`` is still reported even though it is now zero, and
``imported`` still counts line items only - the section rows are reported under
``sections`` where this route has always reported them.

Run:
    cd backend
    python -m pytest tests/unit/test_gaeb_editor_route_uses_real_importer.py -v
"""

from __future__ import annotations

import io
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import Response, UploadFile
from sqlalchemy import select

from app.modules.boq.models import BOQ, BOQMarkup, Position
from app.modules.boq.router import import_boq_gaeb
from app.modules.boq.service import BOQService
from app.modules.projects.models import Project
from tests._pg import transactional_session

OWNER_ID = uuid.uuid4()

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gaeb"
_X83 = _FIXTURES / "oce_conformance_x83.x83"
_X84 = _FIXTURES / "oce_conformance_x84.x84"

# Measured against the fixtures, not derived from the parser's own report.
_LINE_ITEMS = 27
_SECTIONS = 12
_ROOT_SECTIONS = 4  # rows with no parent; the other 35 are threaded
_X84_DIRECT_COST = Decimal("1915000.00")
_X84_MARKUP_IT = Decimal("85000.00")
_X83_UNITS = {"lsum": 1, "m": 4, "m2": 7, "m3": 6, "pcs": 8, "t": 1}

# The response keys this route returns: the historic ones plus the additive fidelity report.
# The frontend reads imported, skipped, errors.length, sections.length, source_format and currency.
_RESPONSE_KEYS = {
    "imported",
    "skipped",
    "errors",
    "sections",
    "source_format",
    "currency",
    "validation_report",
    "fidelity",
}


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        from app.modules.users.models import User

        s.add(
            User(
                id=OWNER_ID,
                email=f"gaebroute-{uuid.uuid4().hex[:6]}@test.io",
                hashed_password="x",
                full_name="GAEB Route Tester",
            )
        )
        await s.flush()
        await s.commit()
        yield s


async def _make_boq(session) -> uuid.UUID:
    project_id = uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name=f"GaebRoute {uuid.uuid4().hex[:6]}",
            owner_id=OWNER_ID,
            currency="EUR",
        )
    )
    await session.flush()
    boq = BOQ(id=uuid.uuid4(), project_id=project_id, name="Route BOQ")
    session.add(boq)
    await session.commit()
    return boq.id


async def _import(session, fixture: Path) -> tuple[uuid.UUID, dict, Response]:
    """Drive the real endpoint function the way the editor's upload does."""
    boq_id = await _make_boq(session)
    service = BOQService(session)
    upload = UploadFile(file=io.BytesIO(fixture.read_bytes()), filename=fixture.name)
    response = Response()
    result = await import_boq_gaeb(
        boq_id=boq_id,
        response=response,
        _user_id=str(OWNER_ID),
        payload={},
        session=session,
        file=upload,
        service=service,
    )
    return boq_id, result, response


async def _rows(session, boq_id: uuid.UUID) -> list[Position]:
    return list((await session.execute(select(Position).where(Position.boq_id == boq_id))).scalars().all())


def _line_items(rows: list[Position]) -> list[Position]:
    return [r for r in rows if (r.unit or "") != "section"]


def _sections(rows: list[Position]) -> list[Position]:
    return [r for r in rows if (r.unit or "") == "section"]


@pytest.mark.skipif(not _X84.exists() or not _X83.exists(), reason="GAEB fixtures not present")
class TestEditorRouteImportsTheFile:
    @pytest.mark.asyncio
    async def test_x84_line_items_reach_the_database(self, session) -> None:
        """The phase that used to import nothing now imports every item."""
        boq_id, result, _ = await _import(session, _X84)
        rows = await _rows(session, boq_id)

        assert len(_line_items(rows)) == _LINE_ITEMS
        assert result["imported"] == _LINE_ITEMS
        assert result["skipped"] == 0

    @pytest.mark.asyncio
    async def test_x83_line_items_reach_the_database(self, session) -> None:
        boq_id, result, _ = await _import(session, _X83)
        rows = await _rows(session, boq_id)

        assert len(_line_items(rows)) == _LINE_ITEMS
        assert result["imported"] == _LINE_ITEMS
        assert result["skipped"] == 0

    @pytest.mark.asyncio
    async def test_sections_become_threaded_parent_rows(self, session) -> None:
        """A BoQCtgy is a row with children, not a label in a response list."""
        boq_id, result, _ = await _import(session, _X83)
        rows = await _rows(session, boq_id)

        assert len(_sections(rows)) == _SECTIONS
        assert len(result["sections"]) == _SECTIONS
        # Everything except the top-level categories hangs off a parent.
        assert len([r for r in rows if r.parent_id is None]) == _ROOT_SECTIONS
        assert len([r for r in rows if r.parent_id is not None]) == len(rows) - _ROOT_SECTIONS

    @pytest.mark.asyncio
    async def test_the_ordinal_is_the_oz_and_never_the_opaque_id(self, session) -> None:
        """The regression guard.

        The walker stored ``Item/@ID`` - ``oceI0001`` where the LV says
        ``001.001.0010``. Our own profile schema documents @ID as an opaque
        handle that is never the OZ, and a wrong OZ is worse than a missing one
        because the OZ is how a position is named in a Nachtrag or a dispute.
        It regresses silently because ``oceI0001`` has the shape of data.
        """
        boq_id, _, _ = await _import(session, _X83)
        rows = await _rows(session, boq_id)
        ordinals = {r.ordinal for r in rows}

        assert "001.001.0010" in ordinals
        assert "001.001" in ordinals
        assert not [o for o in ordinals if o and o.lower().startswith("ocei")]

    @pytest.mark.asyncio
    async def test_x84_money_survives_the_route(self, session) -> None:
        """An X84 carries UP and IT but no Qty; quantity is reconstructed."""
        boq_id, _, _ = await _import(session, _X84)
        rows = await _rows(session, boq_id)

        direct = sum(
            (Decimal(str(r.quantity or 0)) * Decimal(str(r.unit_rate or 0)) for r in _line_items(rows)),
            Decimal("0"),
        )
        assert direct == _X84_DIRECT_COST

    @pytest.mark.asyncio
    async def test_the_markup_lands_as_a_native_markup_row(self, session) -> None:
        """The Zuschlagsposition is a BOQMarkup, not a note in metadata."""
        boq_id, _, _ = await _import(session, _X84)
        markups = list((await session.execute(select(BOQMarkup).where(BOQMarkup.boq_id == boq_id))).scalars().all())

        assert len(markups) == 1
        assert markups[0].markup_type == "fixed"
        assert Decimal(str(markups[0].fixed_amount)) == _X84_MARKUP_IT

    @pytest.mark.asyncio
    async def test_units_come_from_the_file_on_a_phase_that_states_them(self, session) -> None:
        boq_id, _, _ = await _import(session, _X83)
        rows = await _rows(session, boq_id)

        counts: dict[str, int] = {}
        for r in _line_items(rows):
            counts[r.unit or "<empty>"] = counts.get(r.unit or "<empty>", 0) + 1
        assert counts == _X83_UNITS


@pytest.mark.skipif(not _X83.exists(), reason="GAEB fixture not present")
class TestTheContractDidNotMove:
    @pytest.mark.asyncio
    async def test_the_response_carries_exactly_the_historic_keys(self, session) -> None:
        _, result, _ = await _import(session, _X83)
        assert set(result) == _RESPONSE_KEYS

    @pytest.mark.asyncio
    async def test_skipped_is_reported_even_though_it_is_now_zero(self, session) -> None:
        """The field stays because a client reads it, not because it is useful."""
        _, result, _ = await _import(session, _X83)
        assert "skipped" in result
        assert result["skipped"] == 0

    @pytest.mark.asyncio
    async def test_sections_entries_keep_their_ordinal_and_label_shape(self, session) -> None:
        _, result, _ = await _import(session, _X83)
        assert all(set(s) == {"ordinal", "label"} for s in result["sections"])
        assert {"ordinal": "001", "label": "Rohbauarbeiten"} in result["sections"]

    @pytest.mark.asyncio
    async def test_imported_counts_line_items_and_not_the_section_rows(self, session) -> None:
        """39 rows are created; the field that says 27 must keep saying 27.

        ``_persist_imported_boq`` reports every created row, sections included.
        Passing that straight through would leave the field name intact and
        quietly change what it counts, which is what a client reading
        "N imported" would then get wrong.
        """
        boq_id, result, _ = await _import(session, _X83)
        rows = await _rows(session, boq_id)

        assert len(rows) == _LINE_ITEMS + _SECTIONS
        assert result["imported"] == _LINE_ITEMS
        assert result["imported"] != len(rows)

    @pytest.mark.asyncio
    async def test_errors_entries_keep_the_ordinal_and_error_shape(self, session) -> None:
        _, result, _ = await _import(session, _X83)
        assert isinstance(result["errors"], list)
        assert all(set(e) >= {"ordinal", "error"} for e in result["errors"])

    @pytest.mark.asyncio
    async def test_the_deprecation_headers_still_point_at_the_successor(self, session) -> None:
        _, _, response = await _import(session, _X83)
        assert response.headers["Deprecation"] == "true"
        assert "successor-version" in response.headers["Link"]
        assert response.headers["Sunset"]

    @pytest.mark.asyncio
    async def test_source_format_and_currency_still_describe_the_file(self, session) -> None:
        _, result, _ = await _import(session, _X83)
        assert result["source_format"] == "gaeb"
        assert result["currency"] == "EUR"
