# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The coordination demo seeds must fill their registers, once, with usable rows.

BCF, Point Cloud and the interface register all shipped routed, permissioned and
empty, so each screen photographed the same on every demo project. The seeders
that fix that share four ways to be wrong which a green exit code cannot show,
and each is pinned here against a real database:

* they write into a project that is not a demo project. The caller hands every
  project in the database to every seeder and re-runs on each upgrade, so an
  emptiness check alone would inject invented rows into a customer's live
  project - the one failure here that is a data incident rather than a
  cosmetic one;
* they double the register on the second boot, because idempotency in this
  codebase is per loop rather than per seeder;
* they write rows that are individually valid and collectively incoherent - an
  interface signed off with actions still open, a topic whose thread predates
  it, a registration whose error figure has nothing to do with the accuracy the
  scan claims;
* they write rows the consumer downstream cannot use. A BCF topic only matters
  if it survives an export, and a scan only matters if the container behind it
  really exists and decodes - a row pointing at a missing blob renders an error
  card where the demo is supposed to show a cloud.

The last one is asserted through the real consumers - the module's own bcfzip
codec and the point decoder the viewer endpoint calls - rather than by
restating what they do.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.modules.bcf import bcf_xml
from app.modules.bcf.models import BCFComment, BCFTopic, BCFViewpoint
from app.modules.bcf.seed import seed_bcf_demo
from app.modules.bim_hub.models import BIMElement, BIMModel
from app.modules.clash.models import ClashResult, ClashRun
from app.modules.interface_management.models import InterfaceAction, InterfaceRecord
from app.modules.interface_management.register import can_be_overdue
from app.modules.interface_management.seed import seed_interface_management_demo
from app.modules.pointcloud.models import ScanDataset, ScanRegistration
from app.modules.pointcloud.seed import _DENSITY_BANDS, seed_pointcloud_demo
from app.modules.pointcloud.validators import rms_within_tier
from app.modules.projects.models import Project
from app.modules.subcontractors.models import Subcontractor
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

# Statuses that mean the handshake is settled, mirroring the register core.
_SETTLED = ("agreed", "closed")


def _overdue_diagnosis(rows, as_of: date) -> str:
    """Why the overdue tile came back empty, in the terms the register decides it on.

    An empty list has the same shape whatever emptied it, so an assertion on
    one tells the next reader only that it was empty. What that reader needs
    is the status census beside the rows that are already past their need-by
    date, because those two disagreeing is what went wrong here: a paused row
    dated into the past reads as overdue in the table and is exempt from the
    tile. Which statuses are exempt is asked of the register rather than
    restated, so this message cannot drift from the rule it is explaining.
    """
    census = dict(sorted(Counter(row.status for row in rows).items()))
    past_due = dict(
        sorted(Counter(row.status for row in rows if row.need_by_date is not None and row.need_by_date < as_of).items())
    )
    exempt = sorted(status for status in past_due if not can_be_overdue(status))
    return (
        f"{len(rows)} row(s) as of {as_of}; statuses {census}; already past their need-by date {past_due}; "
        f"of those, statuses this register never counts as overdue: {exempt}"
    )


def _named(refs) -> str:
    """The interfaces a register reported, named, for an assertion that wanted none."""
    return ", ".join(f"{ref['reference']} ({ref['status']}, due {ref['need_by_date']})" for ref in refs) or "nothing"


async def _make_project(
    session,
    name: str,
    *,
    demo: bool = True,
    project_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """A project with an owner - the minimum every one of these seeders needs.

    ``demo`` controls the ``demo_id`` marker the seeders gate on. Both demo
    installers stamp it and nothing else does, so ``demo=False`` is what a real
    customer project looks like to these seeders. ``project_id`` pins the id,
    which matters to any seeder that draws from it: the interface register does,
    so a test that has to reproduce one particular register asks for its id.
    """
    owner_id = uuid.uuid4()
    session.add(
        User(
            id=owner_id,
            email=f"{name.lower()}@example.test",
            hashed_password="x",
            full_name=f"{name} Owner",
            role="manager",
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    # Flushed on its own: the project's owner FK has no ORM relationship behind
    # it, so nothing orders the two inserts for us.
    await session.flush()
    project_id = project_id or uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name=name,
            description="Coordination seed fixture",
            currency="EUR",
            status="active",
            owner_id=owner_id,
            metadata_={"demo_id": f"fixture-{name.lower()}"} if demo else {},
        )
    )
    await session.flush()
    return project_id


async def _make_parties(session, count: int = 6) -> None:
    """Register the firms the interface register puts on the two sides."""
    trades = ("concrete", "hvac", "electrical", "facade", "plumbing", "steel_erection")
    for index in range(count):
        session.add(
            Subcontractor(
                id=uuid.uuid4(),
                legal_name=f"Fixture Trades {index:02d}",
                trade_name=f"FT{index:02d}",
                trade_categories=[trades[index % len(trades)]],
                prequalification_status="approved",
                rating_score=Decimal("80"),
                country="DE",
                is_active=True,
            )
        )
    await session.flush()


async def _make_model(session, project_id: uuid.UUID, elements: int = 12) -> uuid.UUID:
    """A BIM model with elements that carry a real bounding box.

    The BCF seeder only aims a camera at geometry that exists, so a model with
    no boxed elements produces topics without viewpoints.
    """
    model_id = uuid.uuid4()
    session.add(
        BIMModel(
            id=model_id,
            project_id=project_id,
            name="Fixture Structural Model",
            discipline="Structural",
            model_format="ifc",
            version="1",
            status="ready",
            element_count=elements,
            storey_count=3,
            metadata_={},
        )
    )
    await session.flush()
    for index in range(elements):
        session.add(
            BIMElement(
                id=uuid.uuid4(),
                model_id=model_id,
                stable_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{model_id}:{index}")),
                element_type="Beam" if index % 2 else "Wall",
                name=f"Element {index}",
                storey=f"Level {index % 3:02d}",
                discipline="Structural",
                properties={},
                quantities={},
                bounding_box={
                    "min_x": float(index),
                    "min_y": 0.0,
                    "min_z": float(index % 3) * 3.2,
                    "max_x": float(index) + 0.4,
                    "max_y": 6.0,
                    "max_z": float(index % 3) * 3.2 + 3.0,
                },
                metadata_={},
            )
        )
    await session.flush()
    return model_id


async def _make_clashes(session, project_id: uuid.UUID, model_id: uuid.UUID, count: int = 3) -> None:
    """A clash run with results, so the clash-derived BCF topics get exercised."""
    run_id = uuid.uuid4()
    owner_id = (await session.execute(select(Project.owner_id).where(Project.id == project_id))).scalars().one()
    session.add(
        ClashRun(
            id=run_id,
            project_id=project_id,
            name="Fixture clash run",
            model_ids=[str(model_id)],
            created_by=str(owner_id),
        )
    )
    await session.flush()
    for index in range(count):
        session.add(
            ClashResult(
                id=uuid.uuid4(),
                run_id=run_id,
                a_element_id=uuid.uuid4(),
                b_element_id=uuid.uuid4(),
                a_stable_id=f"a-{index}",
                b_stable_id=f"b-{index}",
                a_name=f"Duct {index}",
                b_name=f"Beam {index}",
                a_discipline="Mechanical",
                b_discipline="Structural",
                a_model_id=model_id,
                b_model_id=model_id,
                clash_type="hard",
                severity="high",
                status="active",
                cx=float(index) + 1.0,
                cy=2.5,
                cz=3.2,
                signature=f"{index:016x}",
            )
        )
    await session.flush()


@pytest.fixture
def scan_storage(tmp_path, monkeypatch):
    """Point the point-cloud seeder's storage at a temp dir, not the data dir.

    The seeder writes real containers. Without this the test would drop them
    into whatever data directory the developer's settings resolve to.
    """
    from app.core.storage import LocalStorageBackend

    backend = LocalStorageBackend(Path(tmp_path))
    monkeypatch.setattr(
        "app.modules.pointcloud.service.get_storage_backend",
        lambda: backend,
    )
    return backend


# ── Interface register ─────────────────────────────────────────────────────


async def test_the_interface_register_is_populated_and_reads_as_a_live_register(pg_session) -> None:
    """A seeded project shows a register with work in flight, not one uniform state."""
    project_id = await _make_project(pg_session, "Bridge")
    await _make_parties(pg_session)

    counts = await seed_interface_management_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["interfaces"] >= 8, f"only {counts['interfaces']} interface(s) seeded"
    assert counts["actions"] >= counts["interfaces"], "interfaces were seeded with no actions to close them"

    rows = (
        (await pg_session.execute(select(InterfaceRecord).where(InterfaceRecord.project_id == project_id)))
        .scalars()
        .all()
    )
    statuses = {row.status for row in rows}
    assert len(statuses) >= 4, f"the whole register sits in {sorted(statuses)}"
    assert {row.interface_type for row in rows} - {None} != set(), "no interface carries a type"

    # Both sides are real firms on file, and they are two different firms.
    party_names = {name for (name,) in (await pg_session.execute(select(Subcontractor.legal_name))).all()}
    for row in rows:
        assert row.owner_party in party_names, f"owner {row.owner_party!r} is not a firm on file"
        assert row.accepter_party in party_names, f"accepter {row.accepter_party!r} is not a firm on file"
        assert row.owner_party != row.accepter_party, "an interface has the same party on both sides"


async def test_a_settled_interface_carries_its_dates_and_leaves_nothing_open(pg_session) -> None:
    """The coherence rule the derived register depends on.

    An interface is agreed before it is closed, and an interface signed off with
    somebody still owing an action is exactly the state this register exists to
    prevent - so a settled row must carry its dates in order and hold no open
    action. Read back through the module's own register core so a change to
    what counts as settled fails here.
    """
    from app.modules.interface_management.service import InterfaceManagementService

    project_id = await _make_project(pg_session, "Terminal")
    await _make_parties(pg_session)
    await seed_interface_management_demo(pg_session, [project_id])
    await pg_session.flush()

    rows = (
        (await pg_session.execute(select(InterfaceRecord).where(InterfaceRecord.project_id == project_id)))
        .scalars()
        .all()
    )
    open_by_interface: dict[uuid.UUID, int] = {}
    for interface_id, open_count in (
        await pg_session.execute(
            select(InterfaceAction.interface_id, func.count())
            .where(
                InterfaceAction.project_id == project_id,
                InterfaceAction.status == "open",
            )
            .group_by(InterfaceAction.interface_id)
        )
    ).all():
        open_by_interface[interface_id] = int(open_count)

    settled = 0
    for row in rows:
        if row.status == "closed":
            settled += 1
            assert row.agreed_date is not None and row.closed_date is not None, f"{row.reference} closed with no dates"
            assert row.agreed_date <= row.closed_date, f"{row.reference} was closed before it was agreed"
        elif row.status == "agreed":
            settled += 1
            assert row.agreed_date is not None, f"{row.reference} is agreed with no agreed date"
            assert row.closed_date is None, f"{row.reference} is agreed yet carries a closing date"
        else:
            assert row.agreed_date is None and row.closed_date is None, (
                f"{row.reference} is {row.status} yet carries a settlement date"
            )
        if row.status in _SETTLED:
            assert open_by_interface.get(row.id, 0) == 0, f"{row.reference} is {row.status} with an action still open"
    assert settled, "nothing in the register was ever settled"

    report = await InterfaceManagementService(pg_session).build_register(project_id)
    assert report["total"] == len(rows)
    assert report["agreed_pct"] is not None, "the agreed percentage is undefined on a populated register"
    assert report["overdue"], (
        "no interface is overdue, so the overdue tile photographs as a zero: "
        f"{_overdue_diagnosis(rows, date.fromisoformat(report['as_of']))}"
    )


async def test_a_second_interface_pass_adds_no_rows(pg_session) -> None:
    """Running the seed twice must not double the register."""
    project_id = await _make_project(pg_session, "Depot")
    await _make_parties(pg_session)

    await seed_interface_management_demo(pg_session, [project_id])
    await pg_session.flush()
    after_first = (
        await pg_session.execute(
            select(func.count()).select_from(InterfaceRecord).where(InterfaceRecord.project_id == project_id)
        )
    ).scalar_one()
    assert after_first > 0

    second = await seed_interface_management_demo(pg_session, [project_id])
    await pg_session.flush()
    assert second["interfaces"] == 0, f"the second pass wrote {second['interfaces']} interface(s) again"
    assert (
        await pg_session.execute(
            select(func.count()).select_from(InterfaceRecord).where(InterfaceRecord.project_id == project_id)
        )
    ).scalar_one() == after_first


# Project ids whose register seeded with nothing overdue under the rule this
# module used before. The seeder draws its register from the project id, so a
# register that loses the draw is reproducible rather than a one-off: on each
# of these the position meant to carry the overdue row drew a status the report
# exempts, or every candidate position drew a settled one. Ordinary random ids,
# kept because they turn a failure that showed up on roughly one register in
# eighty into one that shows up every run.
_ZERO_OVERDUE_WITNESSES = (
    "9bbd750d-1e70-7c52-30c1-fb6a19086515",
    "16408169-a38d-8afc-fdd2-ed7af97ccc57",
    "6af79ad2-993e-c8c6-e6b1-06e289110af0",
    "bad3116b-63b8-a897-7df0-fe6bce8d75f2",
    "cfdef303-0679-2b47-a283-453695decd6e",
)


async def test_every_seeded_register_opens_on_tiles_that_have_something_to_show(pg_session) -> None:
    """The demo figures are structural rather than a lucky draw.

    Each of these tiles is what a demo project is opened to show, and each was
    a lottery the weighted status draw lost every so often: a register with
    nothing overdue photographs that tile as a zero, one with nothing settled
    has no agreed percentage behind it, and one sitting in three statuses has
    no breakdown to show. One project cannot see a failure that lands on about
    one register in eighty, so this walks a population, and it walks the ids
    that reproduced the empty overdue tile before this was made structural.
    """
    from app.modules.interface_management.service import InterfaceManagementService

    await _make_parties(pg_session)
    service = InterfaceManagementService(pg_session)
    project_ids = [uuid.UUID(witness) for witness in _ZERO_OVERDUE_WITNESSES]
    project_ids += [uuid.UUID(int=0xDEC0DE00 + index) for index in range(7)]

    for index, project_id in enumerate(project_ids):
        await _make_project(pg_session, f"Register{index}", project_id=project_id)
        # One project per call, so every register is drawn at the same ordinal
        # the single-project tests use rather than at a larger one that would
        # carry more rows and hide a thin draw.
        await seed_interface_management_demo(pg_session, [project_id])
        await pg_session.flush()

        rows = (
            (await pg_session.execute(select(InterfaceRecord).where(InterfaceRecord.project_id == project_id)))
            .scalars()
            .all()
        )
        statuses = [row.status for row in rows]
        report = await service.build_register(project_id)
        as_of = date.fromisoformat(report["as_of"])

        assert report["total"] == len(statuses) > 0, f"{project_id} seeded no register to report on"
        assert report["overdue"], (
            f"{project_id} seeded a register with nothing overdue: {_overdue_diagnosis(rows, as_of)}"
        )
        assert [s for s in statuses if s in _SETTLED], (
            f"{project_id} seeded a register with nothing settled: {_overdue_diagnosis(rows, as_of)}"
        )
        assert len(set(statuses)) >= 4, f"{project_id} seeded a register sitting in {sorted(set(statuses))}"


async def test_an_empty_overdue_tile_is_visible_to_that_guard(pg_session) -> None:
    """The other polarity: the guard above has to be able to fail.

    An assertion on a derived list passes for one reason and fails for two, so
    both ways of emptying that list are produced here on purpose - a project
    that was never seeded, and a seeded register whose rows have all been dated
    forward. Neither may read as a register with something on its overdue tile,
    and the second is the one that matters: it is a full register, so a guard
    that only proves rows exist would still call it good.
    """
    from app.modules.interface_management.service import InterfaceManagementService

    await _make_parties(pg_session)
    service = InterfaceManagementService(pg_session)

    unseeded = await _make_project(pg_session, "Unseeded")
    empty = await service.build_register(unseeded)
    assert empty["total"] == 0, f"a project nothing seeded came back carrying {empty['total']} row(s)"
    assert not empty["overdue"], f"a project nothing seeded came back overdue on {_named(empty['overdue'])}"

    project_id = await _make_project(pg_session, "Dated")
    await seed_interface_management_demo(pg_session, [project_id])
    await pg_session.flush()
    rows = (
        (await pg_session.execute(select(InterfaceRecord).where(InterfaceRecord.project_id == project_id)))
        .scalars()
        .all()
    )
    seeded = await service.build_register(project_id)
    assert seeded["overdue"], (
        "the seeded register under test has nothing overdue to take away: "
        f"{_overdue_diagnosis(rows, date.fromisoformat(seeded['as_of']))}"
    )

    ahead = datetime.now(UTC).date() + timedelta(days=90)
    for row in rows:
        row.need_by_date = ahead
    await pg_session.flush()

    dated_forward = await service.build_register(project_id)
    assert dated_forward["total"] == seeded["total"], "dating the register forward changed how many rows it has"
    assert not dated_forward["overdue"], (
        f"a register dated wholly into the future still reports {_named(dated_forward['overdue'])} as overdue"
    )


# ── BCF ────────────────────────────────────────────────────────────────────


async def test_bcf_topics_survive_a_real_bcfzip_export(pg_session) -> None:
    """The register has to be a BCF register, not a table that looks like one.

    Exported through the module's own codec and parsed back, so a viewpoint
    with a camera the format cannot carry fails here rather than at the first
    customer who exports the demo.
    """
    from app.modules.bcf.service import BCFService

    project_id = await _make_project(pg_session, "Campus")
    model_id = await _make_model(pg_session, project_id)
    await _make_clashes(pg_session, project_id, model_id)

    counts = await seed_bcf_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["topics"] >= 8, f"only {counts['topics']} topic(s) seeded"
    assert counts["comments"] >= counts["topics"], "topics were seeded with no discussion on them"
    assert counts["viewpoints"] >= 1, "not one topic carries a viewpoint"

    archive, exported = await BCFService(pg_session).export_bcfzip(project_id, "Campus", "3.0")
    assert exported == counts["topics"]

    parsed = bcf_xml.parse_bcfzip(archive)
    assert not parsed.has_errors, f"the export does not parse: {[i.message for i in parsed.issues]}"
    assert parsed.detected_version == "3.0"
    assert len(parsed.topics) == counts["topics"]

    viewpoints = [vp for topic in parsed.topics for vp in topic.viewpoints]
    assert len(viewpoints) == counts["viewpoints"], "a viewpoint was lost on the way through the format"
    for vp in viewpoints:
        # Exactly one camera, and the fields that belong to it.
        assert vp.camera_type == "perspective", f"viewpoint {vp.guid} exported as {vp.camera_type!r}"
        assert vp.field_of_view, "a perspective viewpoint came back with no field of view"
        assert vp.view_to_world_scale in (None, 0.0), "a perspective camera carries an orthogonal camera's scale"
        direction = vp.camera["camera_direction"]
        up_vector = vp.camera["camera_up_vector"]
        length = sum(float(direction[axis]) ** 2 for axis in "xyz") ** 0.5
        assert abs(length - 1.0) < 1e-6, f"camera direction is not a unit vector ({length})"
        dot = sum(float(direction[axis]) * float(up_vector[axis]) for axis in "xyz")
        assert abs(dot) < 1e-6, f"camera up vector is not perpendicular to the direction ({dot})"

    for topic in parsed.topics:
        assert topic.topic_status in ("Open", "In Progress", "Closed", "ReOpened"), (
            f"topic status {topic.topic_status!r} is outside the BCF enumeration"
        )
        assert topic.topic_type in ("Issue", "Information", "Clash", "Inquiry", "Solution"), (
            f"topic type {topic.topic_type!r} is outside the BCF enumeration"
        )
        assert topic.priority in ("Critical", "Major", "Normal", "Minor"), (
            f"priority {topic.priority!r} is outside the BCF enumeration"
        )

    assert any(topic.topic_type == "Clash" for topic in parsed.topics), (
        "the project has clash results and not one topic was raised from them"
    )


async def test_a_bcf_thread_runs_forward_from_the_topic(pg_session) -> None:
    """The coherence rule: a topic is opened, then discussed, then modified.

    A register whose comments predate the topic they hang off reads as noise the
    moment anybody sorts by date.
    """
    project_id = await _make_project(pg_session, "Viaduct")
    await _make_model(pg_session, project_id)
    await seed_bcf_demo(pg_session, [project_id])
    await pg_session.flush()

    topics = (await pg_session.execute(select(BCFTopic).where(BCFTopic.project_id == project_id))).scalars().all()
    assert topics
    for topic in topics:
        assert topic.creation_date is not None and topic.modified_date is not None
        assert topic.modified_date >= topic.creation_date, f"{topic.guid} was modified before it existed"
        if topic.due_date is not None:
            assert topic.due_date > topic.creation_date, f"{topic.guid} was due before it was raised"
        comments = (
            (
                await pg_session.execute(
                    select(BCFComment).where(BCFComment.topic_id == topic.id).order_by(BCFComment.date)
                )
            )
            .scalars()
            .all()
        )
        assert comments, f"{topic.guid} has no discussion on it"
        for comment in comments:
            assert comment.date >= topic.creation_date, "a comment predates the topic it hangs off"
            assert comment.date <= topic.modified_date, "a comment is newer than the topic's own modified date"
        # A closed topic was closed by somebody saying so, not silently.
        if topic.topic_status == "Closed":
            assert "clos" in comments[-1].comment_text.lower(), f"{topic.guid} is closed with no closing comment"

    # No snapshot is claimed, because no PNG was written for one.
    viewpoints = (
        (
            await pg_session.execute(
                select(BCFViewpoint)
                .join(BCFTopic, BCFViewpoint.topic_id == BCFTopic.id)
                .where(BCFTopic.project_id == project_id)
            )
        )
        .scalars()
        .all()
    )
    assert viewpoints
    for viewpoint in viewpoints:
        assert viewpoint.snapshot_key is None, "a viewpoint claims a snapshot blob that was never written"
        assert viewpoint.element_stable_ids, "a viewpoint highlights nothing at all"


async def test_a_second_bcf_pass_adds_no_topics(pg_session) -> None:
    """Running the seed twice must not double the register."""
    project_id = await _make_project(pg_session, "Harbour")
    await _make_model(pg_session, project_id)

    await seed_bcf_demo(pg_session, [project_id])
    await pg_session.flush()
    after_first = (
        await pg_session.execute(select(func.count()).select_from(BCFTopic).where(BCFTopic.project_id == project_id))
    ).scalar_one()
    assert after_first > 0

    second = await seed_bcf_demo(pg_session, [project_id])
    await pg_session.flush()
    assert second["topics"] == 0, f"the second pass wrote {second['topics']} topic(s) again"
    assert (
        await pg_session.execute(select(func.count()).select_from(BCFTopic).where(BCFTopic.project_id == project_id))
    ).scalar_one() == after_first


# ── Point cloud ────────────────────────────────────────────────────────────


async def test_the_scan_register_is_populated_and_its_containers_really_decode(pg_session, scan_storage) -> None:
    """Every scan that says it is ready must have a cloud the viewer can open.

    Decoded through the same function the points endpoint calls, because a row
    pointing at a missing or unreadable blob renders an error card exactly where
    the demo is supposed to show a cloud.
    """
    from app.modules.pointcloud.decode import decode_points

    project_id = await _make_project(pg_session, "Quarry")
    counts = await seed_pointcloud_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["scans"] >= 8, f"only {counts['scans']} scan(s) seeded"
    assert counts["registrations"] >= 1, "not one scan was ever aligned to anything"

    scans = (await pg_session.execute(select(ScanDataset).where(ScanDataset.project_id == project_id))).scalars().all()
    ready = [scan for scan in scans if scan.status == "ready"]
    assert len(ready) >= 7, "the register is mostly unfinished uploads"

    for scan in ready:
        assert await scan_storage.exists(scan.upload_key), f"scan {scan.id} is ready with no container behind it"
        assert int(scan.point_count) > 0, "a ready scan reports no points"
        assert scan.bbox_json.get("min") and scan.bbox_json.get("max"), "a ready scan reports no extents"
        assert scan.scan_metadata.get("status") == "ok", (
            f"the header of scan {scan.id} did not read back: {scan.scan_metadata.get('status')}"
        )
        # These clouds are modelled in local metres around the origin, and the
        # page prints "EPSG:x" for any scan carrying one. The finalise path runs
        # a bbox heuristic over the header, and a small metric footprint is also
        # a plausible lat/lon box, so a widened region table in the CAD detector
        # would start stamping a coordinate system these scans are not in. Pin
        # it here: an invented EPSG on a photographed screen is worse than the
        # empty state this seeder replaces.
        assert scan.crs_epsg is None, f"scan {scan.id} was stamped EPSG:{scan.crs_epsg} from a local-coordinate bbox"
        # Colour is a property of the capture method, not decoration.
        assert scan.scan_metadata["scalar_fields"]["rgb"] is (scan.source_type == "photogrammetry"), (
            f"{scan.source_type} scan reports rgb={scan.scan_metadata['scalar_fields']['rgb']}"
        )

    # One container all the way through the decoder the viewer endpoint uses.
    sample = ready[0]
    decoded = decode_points(
        Path(scan_storage._path_for(sample.upload_key)),
        sample.original_format,
        max_points=5000,
        max_total_points=10_000_000,
    )
    assert decoded.total_count == int(sample.point_count), "the stored count disagrees with the container"
    assert decoded.returned_count > 0

    failed = [scan for scan in scans if scan.status == "failed"]
    assert failed, "no upload in the register ever failed, which is not what a real one looks like"
    for scan in failed:
        assert int(scan.point_count) == 0 and not scan.bbox_json, "a failed upload reports extents it never had"


async def test_the_registration_error_agrees_with_the_scans_accuracy_tier(pg_session, scan_storage) -> None:
    """The coherence rule: what a scan claims and what it measured must agree.

    A scan that says ``registered`` has to be inside its USIBD tier tolerance
    and one that says ``failed`` has to be outside it - asserted through the
    module's own ``rms_within_tier`` rather than by restating the inequality -
    and the occlusion area has to follow from the coverage figure printed next
    to it instead of being a second, unrelated number.
    """
    project_id = await _make_project(pg_session, "Cutting")
    await seed_pointcloud_demo(pg_session, [project_id])
    await pg_session.flush()

    rows = (
        await pg_session.execute(
            select(ScanRegistration, ScanDataset)
            .join(ScanDataset, ScanRegistration.scan_id == ScanDataset.id)
            .where(ScanDataset.project_id == project_id)
        )
    ).all()
    assert rows, "no registration was seeded at all"

    seen_states = set()
    for registration, scan in rows:
        seen_states.add(scan.registration_status)
        within = rms_within_tier(registration.rms_error, scan.accuracy_tier)
        assert within is (scan.registration_status == "registered"), (
            f"scan says {scan.registration_status} but {registration.rms_error} mm against the "
            f"{scan.accuracy_tier} tier is within={within}"
        )
        assert Decimal("0") < registration.coverage_pct <= Decimal("100")
        assert registration.hole_area > Decimal("0"), "a scan covering less than everything reports no occlusion"
        assert int(registration.out_of_tolerance_count) < int(scan.point_count), (
            "more points are out of tolerance than the scan has"
        )
        assert len(registration.transform_matrix) == 16, "the alignment transform is not a 4x4 matrix"
        assert registration.target_ref, "a registration was aligned to nothing"
    assert seen_states == {"registered", "failed"}, f"the register only shows {sorted(seen_states)}"

    # The density a capture method really delivers, measured off the stored
    # extents rather than off anything the seeder declared.
    scans = (
        (
            await pg_session.execute(
                select(ScanDataset).where(ScanDataset.project_id == project_id, ScanDataset.status == "ready")
            )
        )
        .scalars()
        .all()
    )
    for scan in scans:
        low, high = scan.bbox_json["min"], scan.bbox_json["max"]
        area = (high[0] - low[0]) * (high[1] - low[1])
        assert area > 0
        density = int(scan.point_count) / area
        band_low, band_high = _DENSITY_BANDS[scan.source_type]
        assert band_low <= density <= band_high, (
            f"a {scan.source_type} scan at {density:.0f} points/m2 is outside the {band_low}-{band_high} band "
            "that capture method produces"
        )


async def test_a_second_pointcloud_pass_adds_no_scans(pg_session, scan_storage) -> None:
    """Running the seed twice must not double the register."""
    project_id = await _make_project(pg_session, "Basin")

    await seed_pointcloud_demo(pg_session, [project_id])
    await pg_session.flush()
    after_first = (
        await pg_session.execute(
            select(func.count()).select_from(ScanDataset).where(ScanDataset.project_id == project_id)
        )
    ).scalar_one()
    assert after_first > 0

    second = await seed_pointcloud_demo(pg_session, [project_id])
    await pg_session.flush()
    assert second["scans"] == 0, f"the second pass wrote {second['scans']} scan(s) again"
    assert second["bytes_written"] == 0, "the second pass rewrote the containers"
    assert (
        await pg_session.execute(
            select(func.count()).select_from(ScanDataset).where(ScanDataset.project_id == project_id)
        )
    ).scalar_one() == after_first


async def test_a_project_that_is_not_a_demo_is_left_completely_alone(pg_session, scan_storage) -> None:
    """No seeder may write into a real project, however empty it looks.

    ``enrich_all`` selects every project in the database and hands them all to
    every seeder, and the backfill around it re-runs once per app version, so it
    fires again on each upgrade. Emptiness therefore cannot be the gate: a
    customer project that has recorded no coordination issues, commissioned no
    survey and logged no interface is empty in exactly the way a fresh demo
    project is, and would receive invented defects, invented handshakes between
    firms and megabytes of synthetic point cloud on their next upgrade. That is
    a data incident rather than a cosmetic one, which is why it is pinned per
    seeder rather than assumed from the shared shape of the three.

    The real project here is given everything that would make it attractive to
    seed - an owner, a BIM model with geometry, clash results, parties on file -
    so that the only thing standing between it and a register full of fiction is
    the demo marker.
    """
    real_id = await _make_project(pg_session, "Livewell", demo=False)
    demo_id = await _make_project(pg_session, "Showcase")
    await _make_parties(pg_session)
    for project_id in (real_id, demo_id):
        model_id = await _make_model(pg_session, project_id)
        await _make_clashes(pg_session, project_id, model_id)

    async def _count(model, project_id: uuid.UUID) -> int:
        return (
            await pg_session.execute(select(func.count()).select_from(model).where(model.project_id == project_id))
        ).scalar_one()

    counts = {
        "bcf": await seed_bcf_demo(pg_session, [real_id, demo_id]),
        "interface_management": await seed_interface_management_demo(pg_session, [real_id, demo_id]),
        "pointcloud": await seed_pointcloud_demo(pg_session, [real_id, demo_id]),
    }
    await pg_session.flush()

    for module, result in counts.items():
        assert result["projects"] == 1, f"{module} seeded {result['projects']} project(s), not the one demo project"

    for model in (BCFTopic, InterfaceRecord, ScanDataset):
        assert await _count(model, real_id) == 0, (
            f"{model.__name__} rows were written into a project that is not a demo project"
        )
        assert await _count(model, demo_id) > 0, (
            f"{model.__name__} wrote nothing to the demo project, so this test would pass on a seeder that "
            "does nothing at all"
        )

    # Not one byte of synthetic cloud may be written for the real project
    # either. The containers land before the rows, so a gate applied too late
    # would still leave blobs in the customer's storage - with no row to show
    # for them, which is worse than the rows. Walk the storage tree rather than
    # ask the row where its blob is, because the row is exactly what is absent.
    written = [p for p in scan_storage.base_dir.rglob("*") if p.is_file()]
    assert written, "no container was written at all, so this check proves nothing"
    for path in written:
        assert str(real_id) not in path.as_posix(), f"a point cloud container was written for a real project: {path}"
