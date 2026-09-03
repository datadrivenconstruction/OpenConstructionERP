# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The takeoff demo seed must draw what it claims and link only what exists.

The old seed had three ways to lie that no gate caught: a measurement's value
contradicted its own polygon (248.50 m2 stored on a 13.44 m2 rectangle), 48
rows on twelve projects carried no document, no points and no scale, and zero
of 56 measurements were linked to a BOQ position, so the traceability chain
the takeoff workspace demonstrates had no seeded example anywhere. Each is
pinned here against a real database:

* every seeded measurement is recomputed from its OWN ``points`` and
  ``scale_pixels_per_unit`` through the same service function the API uses,
  and must agree with the stored value within 1%;
* every ``linked_boq_position_id`` must resolve to a really-seeded position of
  the SAME project (a link to a row that does not exist renders as silently
  empty, which is worse than no link);
* the seed is idempotent per document, and it prunes the legacy document-less
  "boq_derived" rows earlier demo installs left behind.

The revision compare needs a second document to exist at all, so the shoot
project carries both issues of sheet A-2.01. Pinned here as well, because a
pair only works when it pairs: the two sheets must be different files, the
measurements that did not change must keep the tuple the compare matches on,
and the ones that did must move - which is checked by running the real
compare rather than by re-deriving what it should have said.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.modules.boq.models import BOQ, Position
from app.modules.projects.models import Project
from app.modules.takeoff.models import TakeoffDocument, TakeoffMeasurement
from app.modules.takeoff.seed import seed_takeoff_demo
from app.modules.takeoff.service import TakeoffService, recompute_measurement_value
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

_FLAGSHIP_ID = uuid.UUID("f1a95000-0001-4a00-8b00-000000000001")
_FRANKFURT = "Bürogebäude Frankfurt Europaviertel"
_HEILBRONN = "Lebensmittelmarkt Heilbronn"
_HEIDELBERG = "Lebensmittelmarkt Heidelberg"

# Descriptions quoted verbatim from the demo packs (office-frankfurt /
# retail_market_heilbronn), so the link patterns are exercised against the
# exact strings the real install seeds.
_FRANKFURT_POSITIONS = [
    ("02.010", "Bodenplatte WU-Beton C30/37 XC4, d=80cm", "m3"),
    ("09.120", "Trennwand Trockenbau doppelt beplankt CW100", "m2"),
    ("09.480", "Sockelleisten Aluminium", "m"),
    ("08.210", "Dämmung Rohrleitungen EnEV/GEG", "m"),
    ("350.4", "Schwimmender Estrich CT-C30-F5, 65mm", "m2"),
]
_HEILBRONN_POSITIONS = [
    ("04.02.0030", "Bodenplatte C25/30 (RC-Beton), d = 20 cm, inkl. Einbau und Abziehen", "m3"),
    ("04.01.0090", "XPS-Dämmung 120 mm unter Bodenplatte, Heizzone, druckfest", "m2"),
    ("09.02.0040", "Eckschutzschienen und Rammschutz-Sockelleisten Flure", "m"),
    ("09.03.0010", "T30-RS-Türen Technik- und LV-Raum", "St"),
    ("09.01.0010", "Trockenbauwände Sozialtrakt und Büros, doppelt beplankt, MW-Dämmung", "m2"),
    ("09.04.0020", "Innentüren Holz mit Stahl-Umfassungszarge, teils Feuchtraum", "St"),
]


@pytest.fixture(autouse=True)
def _isolated_data_dir(monkeypatch, tmp_path):
    """Route the takeoff documents directory into the test's tmp dir.

    ``_takeoff_documents_dir`` resolves the data root per call from the
    environment, so the seed's PDF copies land here instead of the developer's
    real data directory.
    """
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))
    return tmp_path


async def _make_user(session) -> uuid.UUID:
    user_id = uuid.uuid4()
    session.add(
        User(
            id=user_id,
            email=f"takeoff-{user_id.hex[:8]}@example.test",
            hashed_password="x",
            full_name="Takeoff Seed Owner",
            role="manager",
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    await session.flush()
    return user_id


async def _make_project(session, name: str, owner_id: uuid.UUID, project_id: uuid.UUID | None = None) -> uuid.UUID:
    project_id = project_id or uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name=name,
            description="Takeoff seed fixture",
            currency="EUR",
            status="active",
            owner_id=owner_id,
            metadata_={},
        )
    )
    await session.flush()
    return project_id


async def _add_positions(session, project_id: uuid.UUID, rows: list[tuple[str, str, str]]) -> None:
    boq_id = uuid.uuid4()
    session.add(BOQ(id=boq_id, project_id=project_id, name="Fixture LV", description="", status="draft", metadata_={}))
    await session.flush()
    for ordinal, description, unit in rows:
        session.add(
            Position(
                id=uuid.uuid4(),
                boq_id=boq_id,
                ordinal=ordinal,
                reference_code=ordinal,
                description=description,
                unit=unit,
                quantity="100",
                unit_rate="10",
                total="1000",
                metadata_={},
            )
        )
    await session.flush()


async def _add_boq(session, project_id: uuid.UUID, name: str, rows: list[tuple[str, str, str, str]]) -> None:
    """Add one BOQ with fully specified positions: (ordinal, description, unit, unit_rate)."""
    boq_id = uuid.uuid4()
    session.add(BOQ(id=boq_id, project_id=project_id, name=name, description="", status="draft", metadata_={}))
    await session.flush()
    for ordinal, description, unit, unit_rate in rows:
        session.add(
            Position(
                id=uuid.uuid4(),
                boq_id=boq_id,
                ordinal=ordinal,
                reference_code=ordinal,
                description=description,
                unit=unit,
                quantity="100",
                unit_rate=unit_rate,
                total="1000",
                metadata_={},
            )
        )
    await session.flush()


async def _build_stand(session) -> dict[str, uuid.UUID]:
    """Flagship + two German projects with their packs' own BOQ positions."""
    owner_id = await _make_user(session)
    flagship = await _make_project(session, "Residential House - Reference Build", owner_id, _FLAGSHIP_ID)
    frankfurt = await _make_project(session, _FRANKFURT, owner_id)
    heilbronn = await _make_project(session, _HEILBRONN, owner_id)
    await _add_positions(session, frankfurt, _FRANKFURT_POSITIONS)
    await _add_positions(session, heilbronn, _HEILBRONN_POSITIONS)
    # One legacy "boq_derived" row without a document: the shape older demo
    # installs minted 4x per project. The seed must prune it.
    session.add(
        TakeoffMeasurement(
            project_id=frankfurt,
            document_id=None,
            page=1,
            type="area",
            group_name="Baugrube / Erdbau",
            annotation="Kampfmittelsondierung (legacy)",
            points=[],
            measurement_unit="m2",
            created_by=str(owner_id),
            metadata_={"project_id": str(frankfurt), "demo_id": "office-frankfurt", "source": "boq_derived"},
        )
    )
    await session.flush()
    return {"flagship": flagship, "frankfurt": frankfurt, "heilbronn": heilbronn, "owner": owner_id}


async def _measurements(session, project_id: uuid.UUID) -> list[TakeoffMeasurement]:
    return list(
        (await session.execute(select(TakeoffMeasurement).where(TakeoffMeasurement.project_id == project_id)))
        .scalars()
        .all()
    )


def _assert_close(actual: float, expected: float, label: str) -> None:
    assert expected > 0, f"{label}: expected value must be positive, got {expected}"
    rel = abs(actual - expected) / expected
    assert rel <= 0.01, f"{label}: stored {actual} vs recomputed {expected} differ by {rel:.2%}"


async def test_every_seeded_measurement_recomputes_from_its_own_geometry(pg_session) -> None:
    """Stored values, volumes and perimeters agree with points x scale (1%)."""
    ids = await _build_stand(pg_session)

    counts = await seed_takeoff_demo(pg_session, [ids["flagship"], ids["frankfurt"], ids["heilbronn"]])
    await pg_session.flush()

    # One sheet per project, two on the shoot project (index A and index B).
    assert counts["documents"] == 4, f"expected four documents across three projects, got {counts}"
    assert counts["pruned"] == 1, "the legacy document-less row must be pruned"

    # No document-less rows survive anywhere.
    orphans = (
        await pg_session.execute(
            select(func.count()).select_from(TakeoffMeasurement).where(TakeoffMeasurement.document_id.is_(None))
        )
    ).scalar_one()
    assert orphans == 0

    for key, expected_documents in (("flagship", 1), ("frankfurt", 2), ("heilbronn", 1)):
        project_id = ids[key]
        documents = list(
            (await pg_session.execute(select(TakeoffDocument).where(TakeoffDocument.project_id == project_id)))
            .scalars()
            .all()
        )
        assert len(documents) == expected_documents, f"{key}: expected {expected_documents} takeoff document(s)"
        document_ids = set()
        for document in documents:
            document_ids.add(str(document.id))
            assert document.project_id == project_id
            assert document.file_path, f"{key}: document must be backed by a PDF on disk"
            assert Path(document.file_path).exists(), f"{key}: backing PDF missing at {document.file_path}"
            scales = document.page_scales or {}
            assert scales.get("defaultScale", {}).get("unitLabel") == "m", f"{key}: metric page scale expected"
            assert float(scales["defaultScale"]["pixelsPerUnit"]) > 0
            # The frontend's pageIsCalibrated() looks only at byPage; without a
            # page-1 entry the viewer greets the seeded document with a
            # "Not calibrated" badge right next to its working scale.
            by_page = scales.get("byPage") or {}
            assert "1" in by_page, f"{key}: page 1 must carry its own calibration entry"
            assert float(by_page["1"]["pixelsPerUnit"]) == float(scales["defaultScale"]["pixelsPerUnit"])

        rows = await _measurements(pg_session, project_id)
        assert rows, f"{key}: measurements expected"
        for m in rows:
            label = f"{key}:{m.annotation}"
            assert m.document_id in document_ids, f"{label}: measurement must sit on one of the project's documents"
            assert m.points, f"{label}: points must not be empty"
            assert m.scale_pixels_per_unit and m.scale_pixels_per_unit > 0, f"{label}: scale required"
            recomputed = recompute_measurement_value(
                measurement_type=m.type,
                points=m.points,
                scale_pixels_per_unit=m.scale_pixels_per_unit,
                count_value=m.count_value,
                client_value=None,
            )
            assert recomputed is not None, f"{label}: value must be recomputable from geometry"
            assert m.measurement_value is not None, f"{label}: stored value missing"
            _assert_close(float(m.measurement_value), float(recomputed), label)
            if m.type == "count":
                assert m.count_value == len(m.points), f"{label}: one marker per counted piece expected"
                assert float(m.measurement_value) == float(m.count_value)
            if m.depth is not None:
                assert m.volume is not None, f"{label}: depth without volume"
                _assert_close(float(m.volume), float(m.measurement_value) * float(m.depth), f"{label}:volume")
            if m.type == "area" and m.perimeter is not None:
                ring = 0.0
                for i in range(len(m.points)):
                    a, b = m.points[i], m.points[(i + 1) % len(m.points)]
                    ring += math.hypot(b["x"] - a["x"], b["y"] - a["y"])
                _assert_close(float(m.perimeter), ring / m.scale_pixels_per_unit, f"{label}:perimeter")

    # The German showpiece rows are German and sit on the Grundriss.
    frankfurt_rows = await _measurements(pg_session, ids["frankfurt"])
    annotations = {m.annotation for m in frankfurt_rows}
    assert "Bodenplatte EG gesamt (Achse 1-2 / A-D)" in annotations
    groups = {m.group_name for m in frankfurt_rows}
    assert {"Bodenplatten", "Estriche", "Sockelleisten", "Wände", "Türen"} <= groups


async def test_links_point_only_at_really_seeded_positions(pg_session) -> None:
    """Every linked_boq_position_id resolves inside the same project."""
    ids = await _build_stand(pg_session)
    await seed_takeoff_demo(pg_session, [ids["flagship"], ids["frankfurt"], ids["heilbronn"]])
    await pg_session.flush()

    linked_by_project: dict[uuid.UUID, int] = {}
    all_rows = list((await pg_session.execute(select(TakeoffMeasurement))).scalars().all())
    for m in all_rows:
        if m.linked_boq_position_id is None:
            continue
        linked_by_project[m.project_id] = linked_by_project.get(m.project_id, 0) + 1
        position = (
            await pg_session.execute(
                select(Position, BOQ.project_id)
                .join(BOQ, Position.boq_id == BOQ.id)
                .where(Position.id == uuid.UUID(m.linked_boq_position_id))
            )
        ).first()
        assert position is not None, f"{m.annotation}: linked position does not exist"
        assert position[1] == m.project_id, f"{m.annotation}: linked position belongs to another project"
        # The showcase hands its quantity to the money chain: a section
        # heading (empty unit) or an unpriced row must never win the link
        # when a priced position exists (the fixtures price every row).
        assert position[0].unit.strip(), f"{m.annotation}: linked position is a section heading"
        assert Decimal(position[0].unit_rate) > 0, f"{m.annotation}: linked position carries no price"

    # Fixture positions cover, per Frankfurt sheet: slab, 2x screed, 2x
    # skirting, drywall, pipe run - and Frankfurt carries two sheets, so the
    # same seven links are made on each. Heilbronn: slab, XPS, skirting,
    # drywall, T30 doors, interior doors.
    assert linked_by_project.get(ids["frankfurt"], 0) == 14, f"frankfurt links: {linked_by_project}"
    assert linked_by_project.get(ids["heilbronn"], 0) == 6, f"heilbronn links: {linked_by_project}"
    assert linked_by_project.get(ids["flagship"], 0) == 0

    # The slab measurement links to the slab position, not to a lookalike.
    slab = next(m for m in all_rows if m.project_id == ids["frankfurt"] and m.group_name == "Bodenplatten")
    slab_position = (
        await pg_session.execute(select(Position).where(Position.id == uuid.UUID(slab.linked_boq_position_id)))
    ).scalar_one()
    assert slab_position.description.startswith("Bodenplatte WU-Beton")


async def test_unpriced_tender_rows_and_headings_lose_to_priced_positions(pg_session) -> None:
    """The link resolver must pick the priced line item across a project's BOQs.

    A demo project carries several BOQs: the priced works LV plus an unpriced
    tender LV and cost plans whose section headings reuse the same German trade
    vocabulary. ``Position.ordinal`` is a string, so the tender LV's
    "01.03.0020" sorts before the works LV's "320.2" - without the priced
    filter the unpriced tender row (and the heading whose description mentions
    the trade) wins the link and the money chain renders zeros.
    """
    owner_id = await _make_user(pg_session)
    frankfurt = await _make_project(pg_session, _FRANKFURT, owner_id)
    # Both decoys sort FIRST by ordinal; the heading also matches "%Innentüren%".
    await _add_boq(
        pg_session,
        frankfurt,
        "Ausschreibungs-LV Rohbau (unbepreist)",
        [
            ("01.03.0020", "Bodenplatte aus Ortbeton C25/30, Expositionsklasse XC2", "m3", "0"),
            ("09", "LV 09 - Innenausbau: Trockenbau, Bodenbeläge, Innentüren", "", "0"),
        ],
    )
    await _add_boq(
        pg_session,
        frankfurt,
        "Kostenberechnung (bepreist)",
        [
            # Priced lump-sum decoy: matches "%Innentüren%" by text, sorts
            # first by ordinal, carries a unit and a price - only the unit
            # compatibility rule can reject it (a count cannot feed LS).
            ("09.01", "LV 09 - Innenausbau: Trockenbau, Bodenbeläge, Innentüren", "LS", "260000.00"),
            ("320.2", "Bodenplatte WU-Beton C30/37 XC4, d=80cm", "m3", "215.00"),
            ("340.8", "Innentüren Holz / Stahlzargen", "pcs", "720.00"),
        ],
    )

    await seed_takeoff_demo(pg_session, [frankfurt])
    await pg_session.flush()

    rows = await _measurements(pg_session, frankfurt)
    slab = next(m for m in rows if m.group_name == "Bodenplatten")
    doors = next(m for m in rows if m.group_name == "Türen")
    assert slab.linked_boq_position_id, "slab measurement must be linked"
    assert doors.linked_boq_position_id, "doors measurement must be linked"
    slab_position = (
        await pg_session.execute(select(Position).where(Position.id == uuid.UUID(slab.linked_boq_position_id)))
    ).scalar_one()
    doors_position = (
        await pg_session.execute(select(Position).where(Position.id == uuid.UUID(doors.linked_boq_position_id)))
    ).scalar_one()
    assert slab_position.description.startswith("Bodenplatte WU-Beton"), slab_position.description
    assert doors_position.description.startswith("Innentüren Holz"), doors_position.description


async def test_no_compatible_unit_leaves_the_measurement_unlinked(pg_session) -> None:
    """A lump-sum-only pack must not capture a piece count (unit reachability).

    When the only text match carries a unit the measured quantity cannot
    feed (10 doors into an LS position priced at a quarter million), the
    honest outcome is no link at all - the incompatible link would render
    a money figure the takeoff cannot justify.
    """
    owner_id = await _make_user(pg_session)
    frankfurt = await _make_project(pg_session, _FRANKFURT, owner_id)
    await _add_boq(
        pg_session,
        frankfurt,
        "Kostenberechnung (nur Pauschalen)",
        [("09.01", "LV 09 - Innenausbau: Trockenbau, Bodenbeläge, Innentüren", "LS", "260000.00")],
    )

    await seed_takeoff_demo(pg_session, [frankfurt])
    await pg_session.flush()

    rows = await _measurements(pg_session, frankfurt)
    doors = next(m for m in rows if m.group_name == "Türen")
    assert doors.linked_boq_position_id is None, "a count must not link into a lump-sum position"


async def test_wall_length_carries_the_height_that_reaches_the_m2_position(pg_session) -> None:
    """The drywall run stores depth (wall height) so length x height = m2.

    The wall polyline measures metres while the drywall position sells m2;
    without the height the link's quantity is unreachable - the same shape
    as the slab's area x depth = m3, mirrored.
    """
    ids = await _build_stand(pg_session)
    await seed_takeoff_demo(pg_session, [ids["frankfurt"], ids["heilbronn"]])
    await pg_session.flush()

    for key, wall_name in (
        ("frankfurt", "Trennwand Trockenbau Flur, Achse C (Länge)"),
        ("heilbronn", "Trockenbauwand Sozialtrakt, Achse C (Länge)"),
    ):
        rows = await _measurements(pg_session, ids[key])
        wall = next(m for m in rows if m.annotation == wall_name)
        assert wall.depth is not None, f"{key}: wall height missing"
        assert float(wall.depth) == 2.75
        assert wall.volume is not None, f"{key}: face area (length x height) missing"
        assert wall.measurement_value is not None, f"{key}: wall length missing"
        assert abs(float(wall.volume) - float(wall.measurement_value) * 2.75) < 1e-6
        assert wall.linked_boq_position_id, f"{key}: wall must link to the drywall position"
        position = (
            await pg_session.execute(select(Position).where(Position.id == uuid.UUID(wall.linked_boq_position_id)))
        ).scalar_one()
        assert position.unit.lower().replace("²", "2") == "m2", f"{key}: expected an m2 target, got {position.unit}"


async def _frankfurt_sheets(session, project_id: uuid.UUID) -> tuple[TakeoffDocument, TakeoffDocument]:
    """The two issues of sheet A-2.01, index A first."""
    documents = list(
        (await session.execute(select(TakeoffDocument).where(TakeoffDocument.project_id == project_id))).scalars().all()
    )
    by_index = {(d.metadata_ or {}).get("revision_index"): d for d in documents}
    assert set(by_index) == {"A", "B"}, f"expected index A and B, got {[d.filename for d in documents]}"
    return by_index["A"], by_index["B"]


async def test_the_shoot_project_carries_both_issues_of_the_sheet(pg_session) -> None:
    """Two documents, two different drawings, in the order they were issued.

    The compare drawer offers the newest document as the target and the next
    distinct one as the baseline, off a list served newest first. Both rows
    are written in one transaction, so without an explicit issue date they
    share a timestamp and the pair can order either way - which would show the
    revision running backwards.
    """
    ids = await _build_stand(pg_session)
    await seed_takeoff_demo(pg_session, [ids["frankfurt"]])
    await pg_session.flush()

    index_a, index_b = await _frankfurt_sheets(pg_session, ids["frankfurt"])

    assert "Index A" in index_a.filename and "Index B" in index_b.filename
    assert index_a.project_id == index_b.project_id == ids["frankfurt"]
    assert index_b.created_at > index_a.created_at, "index B must be the newer sheet"
    assert index_a.owner_id == index_b.owner_id, "the document list is owner-filtered"

    # Different drawings, not the same file filed twice.
    digests = {hashlib.sha256(Path(doc.file_path).read_bytes()).hexdigest() for doc in (index_a, index_b)}
    assert len(digests) == 2, "the two issues must be different PDFs"
    # ... and the newer one says so in its own text layer.
    assert "Index B" in (index_b.extracted_text or "")
    assert "2,50 m" in (index_b.extracted_text or ""), "the index B text must carry its change note"

    for doc in (index_a, index_b):
        assert (doc.page_scales or {}).get("byPage", {}).get("1"), f"{doc.filename}: page 1 calibration missing"
    assert index_a.page_scales["defaultScale"] == index_b.page_scales["defaultScale"], (
        "both issues are drawn at M 1:100, so they must share the scale the compare reads values at"
    )


async def test_the_revision_pair_pairs_up_and_moves_what_it_says(pg_session) -> None:
    """The seeded pair produces a real compare, run through the real service.

    Measurements are matched across documents on (page, type, group_name,
    annotation), so the sheet that did not rename anything must keep those
    tuples identical - otherwise every row reads as one removal plus one
    addition and the compare has nothing to say about cost.
    """
    ids = await _build_stand(pg_session)
    await seed_takeoff_demo(pg_session, [ids["frankfurt"]])
    await pg_session.flush()

    index_a, index_b = await _frankfurt_sheets(pg_session, ids["frankfurt"])
    payload = await TakeoffService(pg_session).compare_documents(ids["frankfurt"], str(index_a.id), str(index_b.id))
    rows = {row["label"]: row for row in payload["measurement_rows"]}
    tally = payload["summary"]["measurements"]

    assert tally["unchanged"] >= 5, f"most of the sheet must survive the reissue: {tally}"
    assert tally["removed"] == 0, f"index B renames nothing, so nothing may read as removed: {tally}"

    # The corridor was widened, so its screed grew and the skirting around the
    # office it took the depth from shrank.
    screed = rows["Estrich Flur 1.11"]
    assert screed["change_type"] == "modified"
    assert screed["new_value"] > screed["old_value"]
    assert abs((screed["new_value"] - screed["old_value"]) - 13.755) < 0.01
    skirting = rows["Sockelleiste Großraumbüro 1.06 (umlaufend)"]
    assert skirting["change_type"] == "modified"
    assert abs((skirting["new_value"] - skirting["old_value"]) + 1.0) < 0.01
    assert rows["Innentüren EG"]["new_value"] == 11.0, "the second meeting room door must be counted"

    # The wall moved without changing length: same quantity, and the compare
    # is right to call that unchanged.
    assert rows["Trennwand Trockenbau Flur, Achse C (Länge)"]["change_type"] == "unchanged"
    assert rows["Bodenplatte EG gesamt (Achse 1-2 / A-D)"]["change_type"] == "unchanged"

    # Taking the old wall down is scope index B brought with it, so it is a
    # new row rather than a changed one.
    demolition = rows["Rückbau Trennwand Flur, Achse C (Lage Index A)"]
    assert demolition["change_type"] == "added"
    assert demolition["old_value"] is None

    # Both changed quantities are priced, so the drawer can offer a variation.
    assert payload["summary"]["net_cost_impact"] is not None
    assert Decimal(payload["summary"]["net_cost_impact"]) > 0
    assert screed["cost_impact"] is not None and Decimal(screed["cost_impact"]) > 0
    assert skirting["cost_impact"] is not None and Decimal(skirting["cost_impact"]) < 0


async def test_an_install_seeded_before_index_b_is_topped_up(pg_session) -> None:
    """An older install gains index B, and its index A row is not duplicated.

    The stand this ships to already holds the unindexed sheet the first seed
    wrote. Keying idempotency on the file name would have missed it under its
    new name and filed a third document; the seed key recognises it, renames
    it and re-serves it from the current fixture.
    """
    ids = await _build_stand(pg_session)
    await seed_takeoff_demo(pg_session, [ids["frankfurt"]])
    await pg_session.flush()

    # Roll the project back to what an older install looks like: one sheet,
    # no seed key, the file name that predates the revision index.
    index_a, index_b = await _frankfurt_sheets(pg_session, ids["frankfurt"])
    legacy_path = Path(index_a.file_path)
    legacy_path.write_bytes(b"%PDF-1.4 stale fixture\n")
    await pg_session.execute(
        TakeoffMeasurement.__table__.delete().where(TakeoffMeasurement.document_id == str(index_b.id))
    )
    await pg_session.execute(TakeoffDocument.__table__.delete().where(TakeoffDocument.id == index_b.id))
    index_a.filename = "A-2.01 Grundriss Erdgeschoss.pdf"
    index_a.metadata_ = {"seed": True, "demo": True, "scale": "1:100"}
    await pg_session.flush()

    counts = await seed_takeoff_demo(pg_session, [ids["frankfurt"]])
    await pg_session.flush()
    assert counts["documents"] == 1, f"only the missing sheet may be written: {counts}"
    assert counts["adopted"] == 1, f"the legacy row must be adopted, not duplicated: {counts}"

    adopted, _new_b = await _frankfurt_sheets(pg_session, ids["frankfurt"])
    assert adopted.id == index_a.id, "the legacy row itself must become index A"
    assert adopted.filename == "A-2.01 Grundriss Erdgeschoss (Index A).pdf"
    assert legacy_path.read_bytes().startswith(b"%PDF"), "the sheet must be re-served from the fixture"
    assert len(legacy_path.read_bytes()) > 1000, "the stale placeholder must have been replaced"

    again = await seed_takeoff_demo(pg_session, [ids["frankfurt"]])
    await pg_session.flush()
    assert again == {}, f"a second re-run must be a no-op, got {again}"


async def test_a_document_the_seed_did_not_write_leaves_the_project_alone(pg_session) -> None:
    """A user upload owns its project: no sheet is added next to it."""
    ids = await _build_stand(pg_session)
    pg_session.add(
        TakeoffDocument(
            filename="Eigener Plan.pdf",
            pages=1,
            size_bytes=10,
            content_type="application/pdf",
            status="analyzed",
            project_id=ids["frankfurt"],
            owner_id=ids["owner"],
            file_path="",
            metadata_={},
        )
    )
    await pg_session.flush()

    counts = await seed_takeoff_demo(pg_session, [ids["frankfurt"]])
    await pg_session.flush()

    assert counts.get("documents", 0) == 0, f"a user's project must not be seeded onto: {counts}"
    total = (
        await pg_session.execute(
            select(func.count()).select_from(TakeoffDocument).where(TakeoffDocument.project_id == ids["frankfurt"])
        )
    ).scalar_one()
    assert total == 1


async def test_seed_is_idempotent_per_project(pg_session) -> None:
    """A re-run changes nothing; a later new project still gets seeded."""
    ids = await _build_stand(pg_session)
    first = await seed_takeoff_demo(pg_session, [ids["flagship"], ids["frankfurt"], ids["heilbronn"]])
    await pg_session.flush()
    assert first["documents"] == 4

    async def _totals() -> tuple[int, int]:
        docs = (await pg_session.execute(select(func.count()).select_from(TakeoffDocument))).scalar_one()
        rows = (await pg_session.execute(select(func.count()).select_from(TakeoffMeasurement))).scalar_one()
        return docs, rows

    before = await _totals()
    second = await seed_takeoff_demo(pg_session, [ids["flagship"], ids["frankfurt"], ids["heilbronn"]])
    await pg_session.flush()
    assert second == {}, f"re-run must be a no-op, got {second}"
    assert await _totals() == before

    # A project that appears later is seeded without re-touching the others.
    heidelberg = await _make_project(pg_session, _HEIDELBERG, ids["owner"])
    third = await seed_takeoff_demo(pg_session, [ids["flagship"], ids["frankfurt"], ids["heilbronn"], heidelberg])
    await pg_session.flush()
    assert third["documents"] == 1, f"only the new project gets a document, got {third}"
    docs_after, rows_after = await _totals()
    assert docs_after == before[0] + 1
    assert rows_after > before[1]
    heidelberg_rows = await _measurements(pg_session, heidelberg)
    assert heidelberg_rows and all(m.document_id for m in heidelberg_rows)
