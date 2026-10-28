# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Editing a unit retires the claim that the source file never stated one.

A GAEB import records the source's own ``<QU>`` in
``metadata['gaeb_unit_original']``, writing the empty string when the file
stated nothing. An X84 item cannot carry a unit at all, so on that phase the
key is always empty and the stored unit is the importer's guess.

That key is making two claims at once: what the source said, and whether the
current value is still ours. They agree at import and come apart the moment a
person edits the row. An estimator who corrects an invented ``lsum`` to ``m3``
has stated a unit, and every reader of the provenance claim - the GAEB export
among them - must stop being told that nobody did.

These tests pin the lifecycle: a real change to the unit retires the claim, and
a no-op does not, because a re-submitted identical value is not somebody
stating something and a round-trip re-import must not launder a guess into a
fact.

DB isolation uses the shared PostgreSQL transactional session
(``tests._pg.transactional_session``).

Run:
    cd backend
    python -m pytest tests/unit/test_boq_unit_provenance_lifecycle.py -v --tb=short
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest
import pytest_asyncio

from app.modules.boq.models import BOQ
from app.modules.boq.schemas import PositionCreate, PositionUpdate
from app.modules.boq.service import BOQService
from app.modules.projects.models import Project
from tests._pg import transactional_session

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        from app.modules.users.models import User

        s.add(
            User(
                id=OWNER_ID,
                email=f"prov-{uuid.uuid4().hex[:6]}@test.io",
                hashed_password="x",
                full_name="Provenance Tester",
            )
        )
        await s.flush()
        await s.commit()
        yield s


async def _make_project_boq(session) -> uuid.UUID:
    project_id = uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name=f"ProvProj {uuid.uuid4().hex[:6]}",
            owner_id=OWNER_ID,
            currency="EUR",
        )
    )
    await session.flush()
    boq = BOQ(id=uuid.uuid4(), project_id=project_id, name="Provenance BOQ")
    session.add(boq)
    await session.commit()
    return boq.id


async def _imported_x84_position(service: BOQService, boq_id: uuid.UUID, **over):
    """A position exactly as the GAEB importer leaves an X84 item."""
    payload = {
        "boq_id": boq_id,
        "ordinal": "01.001",
        "description": "Baustelleneinrichtung",
        "unit": "lsum",
        "quantity": "1",
        "unit_rate": "8500.00",
        "source": "gaeb_import",
        "metadata": {"gaeb_unit_original": "", "gaeb_ordinal": "01.001"},
    }
    payload.update(over)
    return await service.add_position(PositionCreate(**payload))


@pytest.mark.asyncio
async def test_a_person_stating_a_unit_retires_the_claim(session) -> None:
    """The case the change exists for.

    The importer guessed ``lsum`` and recorded that the file said nothing. An
    estimator corrects it to ``m3``. The row must stop claiming the unit is
    still ours, or the export drops the correction.
    """
    boq_id = await _make_project_boq(session)
    service = BOQService(session)
    pos = await _imported_x84_position(service, boq_id)
    assert pos.metadata_["gaeb_unit_original"] == ""

    updated = await service.update_position(pos.id, PositionUpdate(unit="m3"))

    assert updated.unit == "m3"
    # Dropped, not rewritten. The claim was that the unit came from our
    # fallback because the file could not state one; once a person states one
    # that is false rather than superseded, and absence is the honest form of
    # having no claim. The export reads an absent key as "not a row we guessed
    # for", which is exactly true, so the correction survives.
    assert "gaeb_unit_original" not in (updated.metadata_ or {})
    # The rest of the import provenance is untouched.
    assert updated.metadata_["gaeb_ordinal"] == "01.001"


@pytest.mark.asyncio
async def test_resubmitting_the_same_unit_states_nothing(session) -> None:
    """A no-op patch must not launder a guess into a fact.

    A grid that echoes every field back, or a round-trip re-import of an
    unedited export, resends the stored unit. Nobody stated anything, so the
    claim stands.
    """
    boq_id = await _make_project_boq(session)
    service = BOQService(session)
    pos = await _imported_x84_position(service, boq_id)

    updated = await service.update_position(pos.id, PositionUpdate(unit="lsum"))

    assert updated.unit == "lsum"
    assert updated.metadata_["gaeb_unit_original"] == ""


@pytest.mark.asyncio
async def test_case_and_whitespace_alone_do_not_count_as_stating(session) -> None:
    """``LSUM`` is the same unit as ``lsum``, so the claim survives.

    The schema normalises units on write, so this is belt and braces, but it
    pins the comparison as case-insensitive rather than literal.
    """
    boq_id = await _make_project_boq(session)
    service = BOQService(session)
    pos = await _imported_x84_position(service, boq_id)

    updated = await service.update_position(pos.id, PositionUpdate(unit="  LSUM  "))

    assert updated.metadata_["gaeb_unit_original"] == ""


@pytest.mark.asyncio
async def test_a_row_that_never_came_from_gaeb_gains_no_claim(session) -> None:
    """Editing a manual row must not invent a provenance key.

    The export reads a present key as "this came from a GAEB import". Stamping
    one onto a hand-built row would put it under a rule that was never meant
    for it.
    """
    boq_id = await _make_project_boq(session)
    service = BOQService(session)
    pos = await service.add_position(
        PositionCreate(
            boq_id=boq_id,
            ordinal="02.001",
            description="Hand-entered line",
            unit="pcs",
            quantity="3",
            unit_rate="10.00",
            source="manual",
            metadata={},
        )
    )

    updated = await service.update_position(pos.id, PositionUpdate(unit="m2"))

    assert updated.unit == "m2"
    assert "gaeb_unit_original" not in (updated.metadata_ or {})


@pytest.mark.asyncio
async def test_a_stated_original_is_dropped_too_once_overridden(session) -> None:
    """An X83 row whose file DID state a unit still loses the claim on edit.

    The key describes where the CURRENT value came from. Once a person
    overrides a stated m2 with m3, the file's m2 is no longer the provenance of
    anything the row holds, so keeping it would leave a stale fact behind a
    live-looking name.
    """
    boq_id = await _make_project_boq(session)
    service = BOQService(session)
    pos = await _imported_x84_position(
        service, boq_id, ordinal="03.001", unit="m2", metadata={"gaeb_unit_original": "m2"}
    )

    updated = await service.update_position(pos.id, PositionUpdate(unit="m3"))

    assert "gaeb_unit_original" not in (updated.metadata_ or {})


@pytest.mark.asyncio
async def test_editing_something_else_leaves_the_claim_alone(session) -> None:
    """Only a unit change touches the unit's provenance."""
    boq_id = await _make_project_boq(session)
    service = BOQService(session)
    pos = await _imported_x84_position(service, boq_id)

    updated = await service.update_position(pos.id, PositionUpdate(description="Renamed"))

    assert updated.description == "Renamed"
    assert updated.metadata_["gaeb_unit_original"] == ""


@pytest.mark.asyncio
async def test_a_patch_carrying_its_own_metadata_still_retires_the_claim(session) -> None:
    """The unit rule must survive a patch that also rewrites metadata.

    The frontend grid sends the whole metadata blob back on an edit. If the
    rule only handled the stored-metadata case, the client's copy - which
    still carries the empty original - would win and the correction would be
    lost exactly where it is most likely to happen.
    """
    boq_id = await _make_project_boq(session)
    service = BOQService(session)
    pos = await _imported_x84_position(service, boq_id)

    updated = await service.update_position(
        pos.id,
        PositionUpdate(unit="m3", metadata={"gaeb_unit_original": "", "gaeb_ordinal": "01.001"}),
    )

    assert updated.unit == "m3"
    assert "gaeb_unit_original" not in (updated.metadata_ or {})


@pytest.mark.asyncio
async def test_the_estimators_correction_reaches_the_exported_file(session) -> None:
    """End to end, the case the fourth state broke.

    Import an X84 (no unit anywhere in the file), correct one position by hand,
    export X83. The corrected position must carry the unit the estimator
    stated, and its untouched neighbour must still carry none. Without the
    lifecycle rule the export reads the stale empty claim and drops the
    correction, silently, on the one row somebody fixed.
    """
    from types import SimpleNamespace

    from app.modules.boq.router import build_gaeb_xml

    boq_id = await _make_project_boq(session)
    service = BOQService(session)
    edited = await _imported_x84_position(service, boq_id, ordinal="01.001")
    untouched = await _imported_x84_position(service, boq_id, ordinal="01.002")

    edited = await service.update_position(edited.id, PositionUpdate(unit="m3"))

    rows = [
        SimpleNamespace(
            ordinal=p.ordinal,
            description=p.description,
            unit=p.unit,
            quantity=Decimal(str(p.quantity)),
            unit_rate=Decimal(str(p.unit_rate)),
            total=Decimal(str(p.total)),
            metadata=dict(p.metadata_ or {}),
        )
        for p in (edited, untouched)
    ]
    xml = build_gaeb_xml(
        SimpleNamespace(
            name="LV",
            sections=[SimpleNamespace(ordinal="01", description="Abschnitt", positions=rows)],
            positions=[],
            markups=[],
            direct_cost=Decimal("0"),
            net_total=Decimal("0"),
            grand_total=Decimal("0"),
        ),
        project_name="P",
        project_currency="EUR",
        gaeb_format="x83",
    )

    got: dict[str, str | None] = {}
    for el in ET.fromstring(xml).iter():
        if el.tag.split("}", 1)[-1] != "Item":
            continue
        qu = next((c for c in el if c.tag.split("}", 1)[-1] == "QU"), None)
        got[el.get("RNoPart") or ""] = None if qu is None else (qu.text or "")

    assert got["001"] == "m3", "the estimator's stated unit must reach the file"
    assert got["002"] is None, "an untouched guess must still not be stated"
