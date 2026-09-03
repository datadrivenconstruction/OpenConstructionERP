# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Four demo seeds whose rows are derived from data that already exists.

Validation reports, reconciliation links, project documents and DWG markup are
not registers a seeder may author from imagination. Each one is a statement
about something else in the estate: a report is the engine's verdict on a real
BOQ, a link points at two records in other modules, a document row claims bytes
on disk, an annotation claims a measurement off real geometry. A seeder can
therefore be wrong in a way no exit code shows - it can write rows that look
right and say something false.

So each module is pinned four ways against a real database: rows appear for a
demo project, a second pass does not double them, a project without the demo
marker is left alone, and - the one that matters - the derivation is re-computed
here and compared. The validation report is diffed against a fresh engine run
over the same positions; every persisted link is resolved back to its source
row; every document's recorded size is compared with the file it names; every
measurement is recomputed from the annotation's own coordinates.

The demo-marker test is not a formality. ``enrich_all`` hands every seeder every
project in the database, including a customer's own, so a seeder that gates on
"this project has no rows of my type" would write into live projects.
"""

from __future__ import annotations

import math
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.modules.boq.models import BOQ, Position
from app.modules.changeorders.models import ChangeOrder
from app.modules.correspondence.models import Correspondence
from app.modules.documents.documents_seed import seed_documents_demo
from app.modules.documents.models import Document
from app.modules.dwg_takeoff.models import DwgAnnotation
from app.modules.dwg_takeoff.seed import seed_dwg_takeoff_demo
from app.modules.projects.models import Project
from app.modules.reconciliation.models import RecordLink
from app.modules.reconciliation.seed import seed_reconciliation_demo
from app.modules.users.models import User
from app.modules.validation.models import ValidationReport
from app.modules.validation.seed import seed_validation_demo

pytestmark = pytest.mark.asyncio

_RULE_SETS = ["boq_quality"]

# Positions carrying the three things every BOQ rule reads: a code, a unit and
# priced quantities. Whether they pass is the engine's business, not ours.
_POSITIONS = (
    ("01.10.010", "Excavation to reduced level", "m3", "480", "18.50"),
    ("01.20.020", "Disposal of excavated material", "m3", "480", "22.00"),
    ("03.30.030", "In-situ concrete, ground slab", "m3", "96", "165.00"),
    ("05.40.040", "Structural steel columns", "t", "14", "2450.00"),
)


@pytest.fixture
def quiet_validation_events():
    """Detach the subscribers that open a session of their own.

    ``run_validation`` publishes ``validation.report.created`` and, when the
    engine finds ERROR-severity results, ``validation.results.errors_found``.
    Both are consumed detached: a handler builds its own session from
    ``async_session_factory``, which this lane never binds to the embedded
    cluster. The damage from letting one fire is not confined to this file - the
    half-opened connection outlives the failure and errors every later test - so
    the handlers are lifted for the duration and put back afterwards.
    """
    from app.core.events import event_bus

    names = ("validation.report.created", "validation.results.errors_found")
    saved = {name: list(event_bus._handlers.get(name, [])) for name in names}
    for name, handlers in saved.items():
        for handler in handlers:
            event_bus.unsubscribe(name, handler)
    try:
        yield
    finally:
        for name, handlers in saved.items():
            for handler in handlers:
                event_bus.subscribe(name, handler)


async def _make_project(session, name: str, *, demo: bool) -> uuid.UUID:
    """A project with an owner and a priced BOQ, demo-marked or not.

    ``demo=False`` produces exactly what a customer's own project looks like to
    a seeder: everything present except ``metadata["demo_id"]``.
    """
    owner_id = uuid.uuid4()
    session.add(
        User(
            id=owner_id,
            email=f"{name.lower()}-{uuid.uuid4().hex[:6]}@example.test",
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

    project_id = uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name=name,
            description="Derived-seed fixture",
            currency="EUR",
            status="active",
            owner_id=owner_id,
            # Stated rather than inherited. The measurement system a BOQ run
            # carries is resolved from this column, so a fixture that let the
            # model default supply it would be pinned to that default - and
            # would change what these tests validate if it ever moved.
            country_code="DE",
            validation_rule_sets=list(_RULE_SETS),
            metadata_={"demo_id": f"fixture-{name.lower()}", "is_demo": True} if demo else {},
        )
    )
    await session.flush()

    boq_id = uuid.uuid4()
    session.add(
        BOQ(
            id=boq_id,
            project_id=project_id,
            name=f"{name} estimate",
            description="",
            status="draft",
            metadata_={},
        )
    )
    await session.flush()
    for ordinal, description, unit, quantity, rate in _POSITIONS:
        session.add(
            Position(
                id=uuid.uuid4(),
                boq_id=boq_id,
                ordinal=ordinal,
                reference_code=ordinal,
                description=description,
                unit=unit,
                quantity=quantity,
                unit_rate=rate,
                total=str(Decimal(quantity) * Decimal(rate)),
                metadata_={},
            )
        )
    await session.flush()
    return project_id


# ── validation ────────────────────────────────────────────────────────────


def _outcomes_by_rule(outcomes: Iterable[tuple[str, bool]]) -> dict[str, Counter[str]]:
    """Rule id -> how many of that rule's results passed and how many failed.

    Keyed by name, so a difference between two runs is reported as the rule it
    is about. Counted rather than collapsed to a set, because a rule fires once
    per finding: one that flags three positions on one side and one on the
    other is a real disagreement, and a set would call the two sides equal.

    Args:
        outcomes: ``(rule_id, passed)`` pairs, one per validation result.

    Returns:
        Mapping of rule id to a counter over ``"passed"`` / ``"failed"``.
    """
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for rule_id, passed in outcomes:
        grouped[rule_id]["passed" if passed else "failed"] += 1
    return dict(grouped)


async def _reports(session, project_id: uuid.UUID) -> list[ValidationReport]:
    return list(
        (await session.execute(select(ValidationReport).where(ValidationReport.project_id == project_id)))
        .scalars()
        .all()
    )


async def test_validation_persists_the_engines_own_verdict(pg_session, quiet_validation_events) -> None:
    """The stored report must be what the engine returns, rule for rule.

    A seeder that authored plausible-looking findings would pass a row count and
    a status check. It cannot pass this: the engine is re-run here over the same
    positions and every rule outcome is compared.
    """
    from app.core.validation.engine import validation_engine
    from app.modules.validation.service import ValidationModuleService

    project_id = await _make_project(pg_session, "Quay", demo=True)

    counts = await seed_validation_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["reports"] == 1, f"seeded {counts['reports']} report(s) for one BOQ"
    reports = await _reports(pg_session, project_id)
    assert len(reports) == 1
    report = reports[0]
    assert report.target_type == "boq"
    assert report.total_rules > 0, "a report that checked no rules is not a verdict"

    boq_id = uuid.UUID(report.target_id)
    service = ValidationModuleService(pg_session)
    # The payload comes from the service's own builder rather than being
    # hand-rolled here - the same one the seeder's run went through. A rule
    # reads its inputs from this mapping, and one whose input is missing
    # returns nothing at all rather than failing, so a payload assembled by
    # hand quietly drops that rule from this side of the comparison, and the
    # test then reads as the seeder having invented a verdict it did not
    # invent. Calling the builder rather than reassembling its output keeps
    # that true when the payload grows a key: it used to carry positions
    # alone, and a document-level rule reading the bill's own fields would
    # have been dropped here and nowhere else.
    engine_data = await service._engine_payload(boq_id, project_id)
    # Both sides of the comparison now share that builder, so pin what it
    # contributes: the fixture project declares DE, its regional pack answers,
    # and the measurement system has to be in the payload. Without this the two
    # sides could agree on a smaller rule set and the disagreement this test
    # exists to catch would go quiet.
    assert engine_data.get("project_unit_system") == "metric", (
        f"the engine payload lost the project's measurement system: {sorted(engine_data)}"
    )
    fresh = await validation_engine.validate(
        data=engine_data,
        rule_sets=list(_RULE_SETS),
        target_type="boq",
        target_id=str(boq_id),
        project_id=str(project_id),
    )

    stored = _outcomes_by_rule((row["rule_id"], bool(row["passed"])) for row in report.results)
    expected = _outcomes_by_rule((result.rule_id, bool(result.passed)) for result in fresh.results)
    # Compared rule by rule and named in all three directions. This used to be
    # two sorted lists checked positionally, which reports the first index that
    # differs and identifies nothing: a rule present on one side shifts every
    # element after it, so the failure reads as some unrelated rule disagreeing
    # with itself, and enabling any new rule breaks the comparison rather than
    # the thing it measures.
    assert not set(stored) - set(expected), (
        f"the stored report carries rules a fresh run does not produce: {sorted(set(stored) - set(expected))}"
    )
    assert not set(expected) - set(stored), (
        f"a fresh run produces rules the stored report does not carry: {sorted(set(expected) - set(stored))}"
    )
    # Both sides carry the same rules by here, so what is left is a rule that
    # reached a different verdict - or reached the same verdict on a different
    # number of positions. Reported as the rule it is about, with both counts.
    disagreeing = {
        rule_id: {"stored": dict(stored[rule_id]), "fresh": dict(expected[rule_id])}
        for rule_id in sorted(set(stored) & set(expected))
        if stored[rule_id] != expected[rule_id]
    }
    assert not disagreeing, f"the persisted report disagrees with what the engine returns: {disagreeing}"

    assert report.status == fresh.status.value
    assert report.passed_count == len(fresh.passed_rules)
    assert report.warning_count == len(fresh.warnings)
    assert report.error_count == len(fresh.errors)
    # The rule sets recorded on the report are the ones the project declares -
    # never widened to a standard the project does not claim to follow.
    assert report.rule_set == "+".join(_RULE_SETS)


async def test_validation_second_pass_adds_nothing(pg_session, quiet_validation_events) -> None:
    """Re-running must not validate a BOQ that already has a verdict."""
    project_id = await _make_project(pg_session, "Basin", demo=True)

    await seed_validation_demo(pg_session, [project_id])
    await pg_session.flush()
    after_first = len(await _reports(pg_session, project_id))
    assert after_first > 0

    second = await seed_validation_demo(pg_session, [project_id])
    await pg_session.flush()
    assert second["reports"] == 0, f"the second pass wrote {second['reports']} report(s) again"
    assert len(await _reports(pg_session, project_id)) == after_first


async def test_validation_leaves_a_non_demo_project_alone(pg_session, quiet_validation_events) -> None:
    """A project without the demo marker must not be validated behind its owner's back."""
    project_id = await _make_project(pg_session, "Tenant", demo=False)

    counts = await seed_validation_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["reports"] == 0
    assert await _reports(pg_session, project_id) == []


# ── reconciliation ────────────────────────────────────────────────────────


async def _add_correlating_records(session, project_id: uuid.UUID) -> None:
    """Four change orders and four letters that quote their codes.

    A shared tracked reference is the engine's strongest signal and clears the
    threshold on its own, so each letter correlates with exactly one change
    order. Two of the letters also repeat their change order's title, which
    fires the subject signal as well - so the engine returns links at two
    different strengths and the seeder's ranked plan has something to rank.
    """
    titles = (
        "Additional excavation to the north bay",
        "Revised door schedule on the protected corridor",
        "Temporary works to the retaining wall",
        "Relocation of the incoming water main",
    )
    for index, title in enumerate(titles, start=1):
        code = f"CO-{index:03d}"
        session.add(
            ChangeOrder(
                id=uuid.uuid4(),
                project_id=project_id,
                code=code,
                title=title,
                description=f"Instructed work covered by {code}.",
                reason_category="client_request",
                status="submitted",
                submitted_at="2026-05-12T09:00:00+00:00",
                cost_impact=Decimal("0"),
                schedule_impact_days=0,
                metadata_={},
            )
        )
        session.add(
            Correspondence(
                id=uuid.uuid4(),
                project_id=project_id,
                reference_number=code,
                direction="incoming",
                subject=(title if index <= 2 else f"Letter concerning instruction {index}"),
                correspondence_type="letter",
                date_sent="2026-05-13",
                to_contact_ids=[],
                linked_document_ids=[],
                notes=f"Contractor's letter about the works instructed under {code}.",
                metadata_={},
            )
        )
    await session.flush()


async def _links(session, project_id: uuid.UUID) -> list[RecordLink]:
    return list((await session.execute(select(RecordLink).where(RecordLink.project_id == project_id))).scalars().all())


async def test_reconciliation_links_point_at_records_that_exist(pg_session) -> None:
    """Every persisted endpoint must resolve to a real row in its source module.

    This is the whole risk of the module: a link is two foreign keys wearing a
    string, with no database constraint behind either of them. A seeder that
    minted ids, or that swapped the canonical endpoint order, produces rows that
    read fine and resolve to nothing.
    """
    project_id = await _make_project(pg_session, "Harbour", demo=True)
    await _add_correlating_records(pg_session, project_id)

    counts = await seed_reconciliation_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["links"] > 0, "no decision recorded on any correlation"
    rows = await _links(pg_session, project_id)
    assert len(rows) == counts["links"]

    tables = {"change_order": ChangeOrder, "correspondence": Correspondence}
    for row in rows:
        for record_type, record_id in (
            (row.left_type, row.left_id),
            (row.right_type, row.right_id),
        ):
            model = tables.get(record_type)
            assert model is not None, f"link names an unknown source type {record_type!r}"
            found = await pg_session.get(model, uuid.UUID(record_id))
            assert found is not None, f"{record_type}:{record_id} is named by a link but does not exist"
            assert found.project_id == project_id, "a link reaches into another project"
        assert Decimal("0") < Decimal(str(row.confidence)) <= Decimal("1")
        assert row.relation == "same_event"

    # A register where every link is confirmed does not show what the module is
    # for; the reviewer has to have said no somewhere, and left something open.
    statuses = {row.status for row in rows}
    assert statuses == {"suggested", "confirmed", "rejected"}, f"only saw {sorted(statuses)}"


async def test_reconciliation_second_pass_adds_nothing(pg_session) -> None:
    """Re-running must not double the decision ledger."""
    project_id = await _make_project(pg_session, "Wharfside", demo=True)
    await _add_correlating_records(pg_session, project_id)

    await seed_reconciliation_demo(pg_session, [project_id])
    await pg_session.flush()
    after_first = len(await _links(pg_session, project_id))
    assert after_first > 0

    second = await seed_reconciliation_demo(pg_session, [project_id])
    await pg_session.flush()
    assert second["links"] == 0, f"the second pass wrote {second['links']} link(s) again"
    assert len(await _links(pg_session, project_id)) == after_first


async def test_reconciliation_leaves_a_non_demo_project_alone(pg_session) -> None:
    """A customer's own correspondence must not acquire reviewed decisions."""
    project_id = await _make_project(pg_session, "Client", demo=False)
    await _add_correlating_records(pg_session, project_id)

    counts = await seed_reconciliation_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["links"] == 0
    assert await _links(pg_session, project_id) == []


# ── documents ─────────────────────────────────────────────────────────────


@pytest.fixture
def upload_store(tmp_path, monkeypatch):
    """Point the document store at a temp directory for the duration."""
    from app.modules.documents import service as documents_service

    store = tmp_path / "uploads"
    store.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(documents_service, "UPLOAD_BASE", store)
    return store


async def _seeded_documents(session, project_id: uuid.UUID) -> list[Document]:
    rows = (await session.execute(select(Document).where(Document.project_id == project_id))).scalars().all()
    return [row for row in rows if (row.metadata_ or {}).get("source") == "documents_demo_seed"]


async def test_documents_recorded_size_matches_the_file_on_disk(pg_session, upload_store) -> None:
    """A document row must name bytes that exist, at the size it claims.

    The file manager prints ``file_size`` when it is non-zero and only falls
    back to stat, so a fabricated size sits next to a download that 404s. Every
    row is therefore checked against the file it names.
    """
    project_id = await _make_project(pg_session, "Depotside", demo=True)

    counts = await seed_documents_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["documents"] > 0, "no document written"
    docs = await _seeded_documents(pg_session, project_id)
    assert len(docs) == counts["documents"]

    for doc in docs:
        path = Path(doc.file_path)
        assert path.is_file(), f"{doc.name} names {doc.file_path}, which is not a file"
        assert doc.file_size == path.stat().st_size, f"{doc.name} claims {doc.file_size} bytes on disk"
        assert doc.file_size > 0
        assert path.is_relative_to(upload_store), "a document was written outside the project store"

    # The register has to span folders: one category is a pile, not a tree. And
    # neither photo nor reality capture may be claimed here - photos are their
    # own file kind, and there is no scan asset behind a capture row.
    categories = {doc.category for doc in docs}
    assert len(categories) >= 4, f"only {sorted(categories)} filed"
    assert not categories & {"photo", "reality_capture"}


async def test_documents_revision_chain_is_internally_consistent(pg_session, upload_store) -> None:
    """A superseded revision must point at a document that exists and be marked stale."""
    from app.modules.cde.suitability import validate_suitability_for_state

    project_id = await _make_project(pg_session, "Yardgate", demo=True)
    await seed_documents_demo(pg_session, [project_id])
    await pg_session.flush()

    docs = await _seeded_documents(pg_session, project_id)
    by_id = {doc.id: doc for doc in docs}

    superseding = [doc for doc in docs if doc.parent_document_id is not None]
    assert superseding, "no revision chain seeded, so the register never shows a re-issue"
    for doc in superseding:
        parent = by_id.get(doc.parent_document_id)
        assert parent is not None, f"{doc.name} supersedes a document that is not in the register"
        assert parent.is_current_revision is False, "the superseded revision is still flagged current"
        assert doc.is_current_revision is True
        assert parent.drawing_number == doc.drawing_number, "a revision changed the drawing number"

    # The suitability code is state-scoped and a direct ORM insert is not
    # checked, so a row could carry a combination the API itself would reject.
    for doc in docs:
        if doc.cde_state and doc.suitability_code:
            ok, reason = validate_suitability_for_state(doc.suitability_code, doc.cde_state)
            assert ok, f"{doc.name}: {reason}"


async def test_documents_revision_chain_shows_two_different_sheets(pg_session, upload_store) -> None:
    """The two issues of the chain must not be the same file filed twice.

    A chain is only evidence of a revision if opening both issues shows a
    difference. The German showcase register therefore carries index A and
    index B of the same drawing, which are rendered from one geometry module
    and really differ - the corridor is wider on index B.
    """
    project_id = await _make_project(pg_session, "Bürogebäude Frankfurt Europaviertel", demo=True)
    await seed_documents_demo(pg_session, [project_id])
    await pg_session.flush()

    docs = await _seeded_documents(pg_session, project_id)
    chain = sorted(
        (doc for doc in docs if doc.drawing_number == "A-2.01"),
        key=lambda doc: doc.revision_code or "",
    )
    assert [doc.revision_code for doc in chain] == ["A", "B"], f"chain: {[d.name for d in chain]}"
    assert chain[1].parent_document_id == chain[0].id, "index B must supersede index A"

    bytes_a = Path(chain[0].file_path).read_bytes()
    bytes_b = Path(chain[1].file_path).read_bytes()
    assert bytes_a != bytes_b, "the archived and the current issue serve the same PDF"

    # Only one chain: the English general-arrangement pair would be a second
    # one, and it is the pair that shares a single asset.
    assert [doc for doc in docs if doc.parent_document_id is not None] == [chain[1]]


async def test_documents_top_up_reaches_a_register_seeded_before_the_chain(pg_session, upload_store) -> None:
    """An install seeded earlier still receives the revision chain, once."""
    project_id = await _make_project(pg_session, "Lebensmittelmarkt Heilbronn", demo=True)
    await seed_documents_demo(pg_session, [project_id])
    await pg_session.flush()

    chain = [doc for doc in await _seeded_documents(pg_session, project_id) if doc.drawing_number == "A-2.01"]
    assert len(chain) == 2
    before = len(await _seeded_documents(pg_session, project_id))
    for doc in chain:
        await pg_session.execute(Document.__table__.delete().where(Document.id == doc.id))
    await pg_session.flush()

    counts = await seed_documents_demo(pg_session, [project_id])
    await pg_session.flush()
    assert counts["documents"] == 2, f"only the chain may be re-filed, got {counts}"
    assert len(await _seeded_documents(pg_session, project_id)) == before

    third = await seed_documents_demo(pg_session, [project_id])
    await pg_session.flush()
    assert third["documents"] == 0, "the chain must not be filed twice"


async def _install_seeded_before_the_chain(session, german_name: str) -> uuid.UUID:
    """A German showcase project whose register predates the revision chain.

    Reproduced the way it really happened rather than by hand-writing rows: the
    register is seeded while the project still has a neutral name, which files
    the English general-arrangement pair, and the project becomes a German
    showcase project only afterwards.
    """
    project_id = await _make_project(session, "Rivergate", demo=True)
    await seed_documents_demo(session, [project_id])
    await session.flush()
    await session.execute(Project.__table__.update().where(Project.id == project_id).values(name=german_name))
    await session.flush()
    return project_id


async def _sheets(session, project_id: uuid.UUID, drawing_number: str) -> list[Document]:
    docs = await _seeded_documents(session, project_id)
    return sorted(
        (doc for doc in docs if doc.drawing_number == drawing_number),
        key=lambda doc: doc.revision_code or "",
    )


async def test_documents_top_up_retires_the_english_pair_the_chain_replaces(pg_session, upload_store) -> None:
    """The pair whose two issues serve one file must not survive the top-up.

    That pair is the defect the German chain fixes, so leaving it beside the
    chain would leave the register one click away from a revision that changed
    nothing - on the very projects the chain was written for.
    """
    project_id = await _install_seeded_before_the_chain(pg_session, "Bürogebäude Frankfurt Europaviertel")
    assert len(await _sheets(pg_session, project_id, "A-10-001")) == 2, "fixture filed no English pair"
    before = len(await _seeded_documents(pg_session, project_id))

    counts = await seed_documents_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["documents"] == 2, f"only the chain may be filed, got {counts}"
    assert counts["retired"] == 2, f"the English pair survived the top-up, got {counts}"
    assert await _sheets(pg_session, project_id, "A-10-001") == []
    assert [doc.revision_code for doc in await _sheets(pg_session, project_id, "A-2.01")] == ["A", "B"]

    # Two out, two in: nothing else in the register moved.
    docs = await _seeded_documents(pg_session, project_id)
    assert len(docs) == before
    # And exactly one chain is left, the one whose issues are different sheets.
    linked = [(doc.drawing_number, doc.revision_code) for doc in docs if doc.parent_document_id is not None]
    assert linked == [("A-2.01", "B")], f"expected one chain, saw {linked}"


async def test_documents_retire_runs_once_and_then_changes_nothing(pg_session, upload_store) -> None:
    """The pass after the retire must be a no-op, by its own report."""
    project_id = await _install_seeded_before_the_chain(pg_session, "Lebensmittelmarkt Heilbronn")
    await seed_documents_demo(pg_session, [project_id])
    await pg_session.flush()
    settled = {doc.id for doc in await _seeded_documents(pg_session, project_id)}

    again = await seed_documents_demo(pg_session, [project_id])
    await pg_session.flush()

    # The counts dict, not only the row count: a delete that runs and matches
    # nothing is still a different thing from one that never ran, and this dict
    # is what the seeder reports to the boot log.
    assert again == {"projects": 0, "documents": 0, "bytes": 0, "retired": 0}, f"second pass reported {again}"
    assert {doc.id for doc in await _seeded_documents(pg_session, project_id)} == settled


async def test_documents_retire_spares_a_sheet_the_seed_did_not_write(pg_session, upload_store) -> None:
    """Somebody else's file under the same sheet number is not the seed's to delete."""
    project_id = await _install_seeded_before_the_chain(pg_session, "Lebensmittelmarkt Heidelberg")
    pair = await _sheets(pg_session, project_id, "A-10-001")
    assert len(pair) == 2

    # Same project, same sheet number, no seed marker: exactly the row a filter
    # written on the sheet number alone would eat.
    theirs = pair[0]
    theirs.metadata_ = {"filed_by_hand": True}
    await pg_session.flush()

    counts = await seed_documents_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["retired"] == 1, f"expected only the seeded half to go, got {counts}"
    survivor = await pg_session.get(Document, theirs.id)
    assert survivor is not None, "a document the seed did not write was deleted"
    assert Path(survivor.file_path).exists(), "its bytes went with the row"


async def test_documents_retire_spares_a_sheet_opened_in_takeoff(pg_session, upload_store) -> None:
    """A takeoff document keeps its source id with no foreign key behind it.

    Deleting the register row underneath one would leave that document, and
    every measurement filed against it, pointing at nothing, with no constraint
    anywhere to report it.
    """
    from app.modules.takeoff.models import TakeoffDocument

    project_id = await _install_seeded_before_the_chain(pg_session, "Bürogebäude Frankfurt Europaviertel")
    opened = (await _sheets(pg_session, project_id, "A-10-001"))[0]
    owner_id = (await pg_session.execute(select(Project.owner_id).where(Project.id == project_id))).scalar_one()
    pg_session.add(
        TakeoffDocument(
            id=uuid.uuid4(),
            filename=opened.name,
            project_id=project_id,
            owner_id=owner_id,
            source_document_id=str(opened.id),
            file_path=opened.file_path,
        )
    )
    await pg_session.flush()

    counts = await seed_documents_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["retired"] == 1, f"expected the opened sheet to stay, got {counts}"
    assert await pg_session.get(Document, opened.id) is not None, "deleted a sheet takeoff was working on"


async def _no_retire(session, project_id: uuid.UUID) -> int:
    """The build that filed the chain before the retire existed."""
    return 0


async def test_documents_retire_reaches_a_project_whose_chain_landed_earlier(
    pg_session, upload_store, monkeypatch
) -> None:
    """The pair goes even when the chain was filed by an earlier build.

    An install reseeded in between carries both the chain and the pair, and it
    will never take the top-up path again - the sheet is already there. A retire
    that only ran beside the write that files the chain would never reach it.
    """
    from app.modules.documents import documents_seed

    project_id = await _install_seeded_before_the_chain(pg_session, "Bürogebäude Frankfurt Europaviertel")
    real_retire = documents_seed._retire_english_chain
    monkeypatch.setattr(documents_seed, "_retire_english_chain", _no_retire)
    await seed_documents_demo(pg_session, [project_id])
    await pg_session.flush()
    # Restored by hand rather than with undo(): the upload store is redirected
    # through the same monkeypatch, and undoing that would send the next pass
    # at the real one.
    monkeypatch.setattr(documents_seed, "_retire_english_chain", real_retire)
    assert len(await _sheets(pg_session, project_id, "A-2.01")) == 2, "fixture filed no chain"
    assert len(await _sheets(pg_session, project_id, "A-10-001")) == 2, "fixture retired the pair too early"

    counts = await seed_documents_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["retired"] == 2, f"the pair outlived the chain, got {counts}"
    assert counts["documents"] == 0, "the chain must not be filed a second time"
    assert await _sheets(pg_session, project_id, "A-10-001") == []
    assert [doc.revision_code for doc in await _sheets(pg_session, project_id, "A-2.01")] == ["A", "B"]


async def test_documents_retire_waits_until_the_chain_is_really_there(pg_session, upload_store, monkeypatch) -> None:
    """Half a chain must not cost the register the pair it replaces.

    A sheet whose bytes cannot be stored is skipped without failing the seed,
    so a retire that trusted the spec list instead of the rows it actually
    wrote would leave the project with one issue and no pair at all.
    """
    from app.modules.documents import documents_seed

    project_id = await _install_seeded_before_the_chain(pg_session, "Lebensmittelmarkt Heilbronn")
    real_store = documents_seed._store
    monkeypatch.setattr(
        documents_seed,
        "_store",
        lambda project, spec: None if spec.key == "gr-index-b" else real_store(project, spec),
    )

    counts = await seed_documents_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["documents"] == 1, f"fixture should have filed index A alone, got {counts}"
    assert counts["retired"] == 0, "the pair was retired behind an incomplete chain"
    assert len(await _sheets(pg_session, project_id, "A-10-001")) == 2


async def test_documents_second_pass_adds_nothing(pg_session, upload_store) -> None:
    """Re-running must not file the register a second time."""
    project_id = await _make_project(pg_session, "Millrace", demo=True)

    await seed_documents_demo(pg_session, [project_id])
    await pg_session.flush()
    after_first = len(await _seeded_documents(pg_session, project_id))
    assert after_first > 0

    second = await seed_documents_demo(pg_session, [project_id])
    await pg_session.flush()
    assert second["documents"] == 0, f"the second pass wrote {second['documents']} document(s) again"
    assert len(await _seeded_documents(pg_session, project_id)) == after_first


async def test_documents_leave_a_non_demo_project_alone(pg_session, upload_store) -> None:
    """A customer's own file store must not receive demo paperwork."""
    project_id = await _make_project(pg_session, "Ledger", demo=False)

    counts = await seed_documents_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["documents"] == 0
    total = (
        await pg_session.execute(select(func.count()).select_from(Document).where(Document.project_id == project_id))
    ).scalar_one()
    assert total == 0


# ── dwg takeoff ───────────────────────────────────────────────────────────


@pytest.fixture
def dwg_store(tmp_path, monkeypatch):
    """Resolve the DWG blob root to a temp directory for the duration."""
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "dwgdata"))
    return tmp_path / "dwgdata"


async def _seed_drawing(session, project_id: uuid.UUID) -> uuid.UUID:
    """Seed the demo DXF through the product's own drawing seeder."""
    from app.scripts.seed_dwg_drawing import seed_ready_dwg_drawing

    owner_id = (await session.execute(select(Project.owner_id).where(Project.id == project_id))).scalar_one()
    drawing_id = uuid.uuid4()
    await seed_ready_dwg_drawing(
        session,
        drawing_id=drawing_id,
        project_id=project_id,
        owner=str(owner_id),
        name="Level 00 floor plan",
        discipline="architectural",
        source="test_fixture",
    )
    await session.flush()
    return drawing_id


async def _annotations(session, project_id: uuid.UUID) -> list[DwgAnnotation]:
    return list(
        (await session.execute(select(DwgAnnotation).where(DwgAnnotation.project_id == project_id))).scalars().all()
    )


def _count_file_entities(path: str) -> tuple[int, int]:
    """Count the DXF on disk without asking the code under test.

    Returns ``(entities across every layout, INSERTs among them)``. The parser
    counts every entity in every layout plus the contents of each block
    definition some INSERT places; with no INSERT in the file that second term
    is empty and a walk of the layouts is the whole count. The caller asserts
    the premise rather than assuming it, so a plan that later grows a block
    fails loudly here instead of quietly comparing two copies of one number.
    """
    import ezdxf

    doc = ezdxf.readfile(path)
    total = 0
    inserts = 0
    for layout in doc.layouts:
        for entity in layout:
            total += 1
            if entity.dxftype() == "INSERT":
                inserts += 1
    return total, inserts


def _shoelace(points: list[dict]) -> float:
    total = 0.0
    for index, current in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        total += float(current["x"]) * float(nxt["y"]) - float(nxt["x"]) * float(current["y"])
    return abs(total) / 2.0


async def test_dwg_measurements_are_recomputable_from_their_own_geometry(pg_session, dwg_store) -> None:
    """Every measurement must fall out of the coordinates stored beside it.

    An annotation is two claims - where it sits and what it measures - and
    nothing in the schema ties them together. A value typed in by hand renders
    identically to one taken off the drawing, so each is recomputed here from
    the annotation's own points and the unit factor the parse recorded.
    """
    pytest.importorskip("ezdxf", reason="the demo drawing is authored with ezdxf")

    project_id = await _make_project(pg_session, "Plansmith", demo=True)
    drawing_id = await _seed_drawing(pg_session, project_id)

    counts = await seed_dwg_takeoff_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["annotations"] > 0, "the drawing was left unmeasured"
    assert counts["measured"] > 0, "no annotation carries a measurement"

    rows = await _annotations(pg_session, project_id)
    assert len(rows) == counts["annotations"]
    assert {row.annotation_type for row in rows} >= {"area", "distance"}

    # The demo plan is authored in millimetres, so a value in metres is the raw
    # geometry times 0.001 (squared for an area). Read the factor off the
    # version rather than restating it.
    from app.modules.dwg_takeoff.models import DwgDrawingVersion

    units = (
        (await pg_session.execute(select(DwgDrawingVersion.units).where(DwgDrawingVersion.drawing_id == drawing_id)))
        .scalars()
        .first()
    )
    assert units == "mm", f"the demo plan reports units {units!r}; this check assumes millimetres"
    factor = 0.001

    for row in rows:
        points = (row.geometry or {}).get("points") or []
        assert points, f"{row.annotation_type} annotation has no geometry"
        assert row.drawing_id == drawing_id
        assert row.drawing_version_id is not None, "annotation is not tied to the version it was made on"

        if row.annotation_type == "area":
            assert len(points) >= 3
            expected = _shoelace(points) * factor * factor
            assert row.measurement_unit == "m2"
            assert math.isclose(float(row.measurement_value), expected, rel_tol=1e-6), (
                f"area reads {row.measurement_value}, geometry gives {expected}"
            )
        elif row.annotation_type == "distance":
            assert len(points) == 2
            dx = float(points[1]["x"]) - float(points[0]["x"])
            dy = float(points[1]["y"]) - float(points[0]["y"])
            expected = math.hypot(dx, dy) * factor
            assert row.measurement_unit == "m"
            assert math.isclose(float(row.measurement_value), expected, rel_tol=1e-6), (
                f"distance reads {row.measurement_value}, geometry gives {expected}"
            )
        elif row.annotation_type == "text_pin":
            # A pin carries the label it is pinned to, not a measurement.
            assert row.text
            assert row.measurement_value is None


async def test_dwg_pin_text_comes_off_the_drawing(pg_session, dwg_store) -> None:
    """A text pin must repeat a string the drawing actually contains."""
    pytest.importorskip("ezdxf", reason="the demo drawing is authored with ezdxf")

    from app.modules.dwg_takeoff.service import DwgTakeoffService

    project_id = await _make_project(pg_session, "Draughtwell", demo=True)
    drawing_id = await _seed_drawing(pg_session, project_id)
    await seed_dwg_takeoff_demo(pg_session, [project_id])
    await pg_session.flush()

    entities = await DwgTakeoffService(pg_session).get_entities(drawing_id)
    labels = {str(e.get("text") or "").strip() for e in entities if e.get("type") == "TEXT"}
    labels.discard("")

    pins = [row for row in await _annotations(pg_session, project_id) if row.annotation_type == "text_pin"]
    assert pins, "the drawing's labels were not pinned"
    for pin in pins:
        assert pin.text in labels, f"pin reads {pin.text!r}, which is on no entity in the drawing"


async def test_dwg_second_pass_adds_nothing(pg_session, dwg_store) -> None:
    """Re-running must not double the markup."""
    pytest.importorskip("ezdxf", reason="the demo drawing is authored with ezdxf")

    project_id = await _make_project(pg_session, "Setsquare", demo=True)
    await _seed_drawing(pg_session, project_id)

    await seed_dwg_takeoff_demo(pg_session, [project_id])
    await pg_session.flush()
    after_first = len(await _annotations(pg_session, project_id))
    assert after_first > 0

    second = await seed_dwg_takeoff_demo(pg_session, [project_id])
    await pg_session.flush()
    assert second["annotations"] == 0, f"the second pass wrote {second['annotations']} annotation(s) again"
    assert len(await _annotations(pg_session, project_id)) == after_first


async def test_dwg_leaves_a_non_demo_project_alone(pg_session, dwg_store) -> None:
    """A customer's own drawing must not acquire markup nobody drew."""
    pytest.importorskip("ezdxf", reason="the demo drawing is authored with ezdxf")

    project_id = await _make_project(pg_session, "Surveyor", demo=False)
    await _seed_drawing(pg_session, project_id)

    counts = await seed_dwg_takeoff_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["annotations"] == 0
    assert await _annotations(pg_session, project_id) == []


async def test_dwg_element_count_is_a_count_of_its_own_file(pg_session, dwg_store) -> None:
    """The count the drawing states must be a count of the drawing.

    Both seeders used to pass one in, and both passed the element count of the
    converted CAD model carrying the same format in the demo spec - a different
    and far larger file. The drawing then advertised thousands of elements over
    a plan that serves eight, and one click into the viewer showed the eight.

    Stated as a predicate, not as eight: the plan may gain a wall, and a count
    that follows the file survives that while a literal does not.
    """
    pytest.importorskip("ezdxf", reason="the demo drawing is authored with ezdxf")

    from app.modules.dwg_takeoff.models import DwgDrawing, DwgDrawingVersion

    project_id = await _make_project(pg_session, "Rulewright", demo=True)
    drawing_id = await _seed_drawing(pg_session, project_id)

    drawing = await pg_session.get(DwgDrawing, drawing_id)
    assert drawing is not None
    assert drawing.status == "ready", f"the drawing seeded as {drawing.status!r}, so no count was parsed"

    in_file, inserts = _count_file_entities(drawing.file_path)
    assert inserts == 0, (
        "the plan has grown a block reference, so the file's own count is no longer "
        "a walk of its layouts - widen the derivation before trusting the comparison"
    )
    assert in_file > 0

    stated = (drawing.metadata_ or {}).get("element_count")
    assert stated == in_file, f"the drawing states {stated} element(s); the DXF it names holds {in_file}"

    version = (
        (await pg_session.execute(select(DwgDrawingVersion).where(DwgDrawingVersion.drawing_id == drawing_id)))
        .scalars()
        .first()
    )
    assert version is not None, "a ready drawing with no parsed version"
    assert version.entity_count == in_file, (
        f"the version counted {version.entity_count} entities in a file holding {in_file}"
    )


async def test_dwg_room_labels_read_as_a_german_plan(pg_session, dwg_store) -> None:
    """The demo plan is presented as a Grundriss, so it has to read as one.

    The labels used to say ``LIVING 6.0 x 4.0`` and ``BED 2.4 x 4.0`` on a plan
    a German estimator opens first. Two things are pinned here: the wording, and
    the notation a German plan uses for a dimension - a decimal comma, and width
    over depth.

    The third assertion is the one that makes the numbers more than decoration.
    Each label states the room it sits in, so the labelled widths have to add up
    to the width of the envelope they divide. The old living-room label failed
    that: it repeated the full 6.0 m of the outer wall while sitting in the
    3.6 m room the partition leaves.
    """
    pytest.importorskip("ezdxf", reason="the demo drawing is authored with ezdxf")

    from app.modules.dwg_takeoff.models import DwgDrawingVersion
    from app.modules.dwg_takeoff.service import DwgTakeoffService

    project_id = await _make_project(pg_session, "Reissbrett", demo=True)
    drawing_id = await _seed_drawing(pg_session, project_id)

    entities = await DwgTakeoffService(pg_session).get_entities(drawing_id)
    texts = [str(e.get("text") or "").strip() for e in entities if e.get("type") == "TEXT"]
    labels = [text for text in texts if text]
    assert labels, "the plan carries no text at all"

    rooms: dict[str, tuple[float, float]] = {}
    for label in labels:
        assert "." not in label, f"{label!r} writes a decimal point where a German plan writes a comma"
        name, _, dims = label.partition(" ")
        width, _, depth = dims.partition("/")
        assert width and depth, f"{label!r} states no width over depth"
        rooms[name] = (float(width.replace(",", ".")), float(depth.replace(",", ".")))

    assert set(rooms) == {"Wohnen", "Schlafen"}, f"the plan names its rooms {sorted(rooms)}"

    version = (
        (await pg_session.execute(select(DwgDrawingVersion).where(DwgDrawingVersion.drawing_id == drawing_id)))
        .scalars()
        .first()
    )
    assert version is not None
    assert version.units == "mm", f"the demo plan reports units {version.units!r}; this check assumes millimetres"
    extents = version.extents or {}
    envelope_width = (float(extents["max_x"]) - float(extents["min_x"])) * 0.001
    envelope_depth = (float(extents["max_y"]) - float(extents["min_y"])) * 0.001

    assert math.isclose(sum(width for width, _ in rooms.values()), envelope_width, rel_tol=1e-6), (
        f"the labelled rooms are {sum(w for w, _ in rooms.values())} m wide across an envelope of {envelope_width} m"
    )
    for name, (_, depth) in rooms.items():
        assert math.isclose(depth, envelope_depth, rel_tol=1e-6), (
            f"{name} is labelled {depth} m deep in an envelope {envelope_depth} m deep"
        )
