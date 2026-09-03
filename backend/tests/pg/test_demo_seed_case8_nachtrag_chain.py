# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The seeded German Nachtrag chain must be linked, dated and provably strong.

The German showcase seeder writes a Mehrkostenanzeige -> Nachtragsangebot ->
beauftragter Nachtrag chain plus the activity trail the claims-evidence
provability engine grades. Before it existed, every demo record scored
"weak" or "moderate" - the showcase could not demonstrate the one feature
the chain exists for. This gates the outcome, not the writes: the engine
itself must grade the hero records "strong", against a real PostgreSQL
schema, and the staged progress-claim backfill must land on the authored
head contract with German claim numbering.

Content is asserted before any equality: a chain whose links all point at
each other but whose rows are empty shells would satisfy a bare score
check only because the score is blind to prose.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

#: The showcase project this test impersonates. Frankfurt is the hero case:
#: it is the only one whose lead notice also cites a change order, so it
#: exercises every provability signal at once.
_DEMO_ID = "office-frankfurt"


async def _make_frankfurt(session) -> uuid.UUID:
    """Create the anchors the showcase seeder keys on, the way the installer does.

    A project flagged with the demo id and ``country_code="DE"``, its authored
    head contract (code ``<demo_id>-MAIN``, active, started in the past) and
    the generated change order ``CO-001`` the lead notice references.
    """
    from app.modules.changeorders.models import ChangeOrder
    from app.modules.contracts.models import Contract
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    email = "bauleitung@reference.example"
    owner = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if owner is None:
        owner = User(email=email, hashed_password="not-a-real-hash", full_name="Reference site lead")
        session.add(owner)
        await session.flush()

    name = "Buerogebaeude Mainufer"
    project = (await session.execute(select(Project).where(Project.name == name))).scalars().first()
    if project is None:
        project = Project(
            name=name,
            owner_id=owner.id,
            country_code="DE",
            currency="EUR",
            metadata_={"demo_id": _DEMO_ID},
        )
        session.add(project)
        await session.flush()
    pid = uuid.UUID(str(project.id))

    start = datetime.now(UTC).date() - timedelta(days=150)
    main = (await session.execute(select(Contract).where(Contract.code == f"{_DEMO_ID}-MAIN"))).scalar_one_or_none()
    if main is None:
        session.add(
            Contract(
                code=f"{_DEMO_ID}-MAIN",
                title="Main construction contract",
                contract_type="lump_sum",
                counterparty_type="client",
                project_id=pid,
                start_date=start.isoformat(),
                end_date=(start + timedelta(days=540)).isoformat(),
                total_value=Decimal("4800000"),
                currency="EUR",
                retention_percent=Decimal("5"),
                status="active",
            )
        )

    co = (await session.execute(select(ChangeOrder).where(ChangeOrder.project_id == pid))).scalars().first()
    if co is None:
        session.add(
            ChangeOrder(
                project_id=pid,
                code="CO-001",
                title="Nachtrag - Baugrube / Erdbau",
                description="Unvorhergesehene Bedingungen: Auswirkung auf Baugrube / Erdbau.",
                reason_category="unforeseen",
                status="approved",
                cost_impact=Decimal("18400"),
                currency="EUR",
            )
        )
    await session.flush()
    return pid


async def test_the_hero_nachtrag_chain_is_linked_and_grades_strong(pg_session) -> None:
    """VN-101 -> VR-101 -> VO-101 must be one linked story the engine calls strong.

    The band is read from the real provability service - the same code path
    the evidence-pack endpoint uses - not recomputed here from the weights,
    so a change in either the seeder or the engine that breaks the showcase
    claim goes red.
    """
    from app.modules.claims_evidence.provability_service import (
        KIND_VARIATION_NOTICE,
        KIND_VARIATION_ORDER,
        KIND_VARIATION_REQUEST,
        score_subject_provability,
    )
    from app.modules.variations.models import Notice, VariationCostImpact, VariationOrder, VariationRequest
    from app.modules.variations.seed import seed_variations_showcase_de

    pid = await _make_frankfurt(pg_session)
    report = await seed_variations_showcase_de(pg_session, [pid])
    await pg_session.flush()
    assert report["projects"] == 1, f"the showcase seeder skipped its own project: {report}"

    async def one(model, code):
        row = (
            await pg_session.execute(select(model).where(model.project_id == pid).where(model.code == code))
        ).scalar_one_or_none()
        assert row is not None, f"{model.__name__} {code} was not seeded"
        return row

    vn = await one(Notice, "VN-101")
    vr = await one(VariationRequest, "VR-101")
    vo = await one(VariationOrder, "VO-101")

    # ── Content first: the chain must be a story, not a graph of stubs ────
    assert vn.status == "responded"
    assert vn.response_received_at, "the answered notice must carry the owner's response date"
    assert vn.reference_change_order_id is not None, "the lead notice must cite the change order"
    assert "Seed" not in (vn.title or ""), f"filler wording survived: {vn.title!r}"

    assert vr.notice_id == vn.id, "the Nachtragsangebot must cite its Mehrkostenanzeige"
    assert vr.status == "converted_to_vo"
    assert vr.contract_standard == "VOB_B"
    assert "VOB/B" in (vr.contract_clause_ref or ""), f"clause ref is not contractual: {vr.contract_clause_ref!r}"

    assert vo.variation_request_id == vr.id, "the beauftragter Nachtrag must cite its request"
    assert vo.status == "completed"
    assert vo.response_due_date, "an agreed order without a due date caps below the strong band"

    lines = (
        (await pg_session.execute(select(VariationCostImpact).where(VariationCostImpact.variation_order_id == vo.id)))
        .scalars()
        .all()
    )
    assert len(lines) >= 3, "the hero order needs a cost build-up, not a single lump line"
    for line in lines:
        assert line.description.strip(), "a cost line without wording reads as filler"
        assert line.total > 0
    # Equality only after the content above: the build-up must re-add to the
    # order's own agreed figure, so the paper a user prints is arithmetically
    # closed.
    assert sum((line.total for line in lines), Decimal("0")) == vo.final_cost_impact
    assert vo.final_cost_impact > 0

    # ── Then the outcome: all three hero records grade strong ─────────────
    graded = {}
    for kind, subject in (
        (KIND_VARIATION_NOTICE, vn),
        (KIND_VARIATION_REQUEST, vr),
        (KIND_VARIATION_ORDER, vo),
    ):
        result = await score_subject_provability(pg_session, project_id=pid, subject_kind=kind, subject_id=subject.id)
        graded[subject.code] = (result.score.band, result.score.score)

    not_strong = {code: got for code, got in graded.items() if got[0] != "strong"}
    assert not not_strong, f"hero records below the strong band: {not_strong} (all: {graded})"

    # ── And the guard: a second pass must be a no-op, not a second estate ──
    before = (await pg_session.execute(select(Notice).where(Notice.project_id == pid))).scalars().all()
    rerun = await seed_variations_showcase_de(pg_session, [pid])
    await pg_session.flush()
    after = (await pg_session.execute(select(Notice).where(Notice.project_id == pid))).scalars().all()
    assert rerun["projects"] == 0, f"the rerun re-seeded a guarded project: {rerun}"
    assert len(after) == len(before), "a rerun grew the notice register"


async def test_the_claims_backfill_writes_a_german_staged_ladder(pg_session) -> None:
    """The head contract must gain AZ-numbered claims that read as a payment run.

    One claim per elapsed month, the oldest paid and the newest still moving,
    with the cumulative prior-claims figure re-adding exactly. Asserted from
    the rows, not from the seeder's report, because a report can count rows
    the reader would not recognise as a ladder.
    """
    from app.modules.contracts.models import Contract, ProgressClaim
    from app.modules.contracts.seed import seed_contracts_demo

    pid = await _make_frankfurt(pg_session)
    report = await seed_contracts_demo(pg_session, [pid])
    await pg_session.flush()
    assert report["claims_backfilled"] > 0, f"the backfill wrote nothing: {report}"

    main = (await pg_session.execute(select(Contract).where(Contract.code == f"{_DEMO_ID}-MAIN"))).scalar_one()
    claims = (
        (
            await pg_session.execute(
                select(ProgressClaim).where(ProgressClaim.contract_id == main.id).order_by(ProgressClaim.claim_number)
            )
        )
        .scalars()
        .all()
    )
    assert len(claims) >= 3, "150 elapsed days must yield a multi-period run"

    now = datetime.now(UTC)
    prior = Decimal("0")
    for claim in claims:
        # German market numbering: Abschlagszahlung, not PC.
        assert claim.claim_number.startswith("AZ-"), claim.claim_number
        assert claim.gross_amount > 0
        # The contract holds 5% retention, so every claim must too.
        assert claim.retention_amount == (claim.gross_amount * Decimal("0.05")).quantize(Decimal("0.01"))
        assert claim.prior_claims_total == prior, "the cumulative prior-claims figure does not re-add"
        prior += claim.gross_amount
        if claim.submitted_at:
            assert datetime.fromisoformat(claim.submitted_at) <= now, "a claim was submitted in the future"

    statuses = [claim.status for claim in claims]
    assert statuses[-1] in ("draft", "submitted"), f"the running period is not still moving: {statuses}"
    assert statuses[0] == "paid", f"the oldest period is not settled: {statuses}"
    assert all(status == "paid" for status in statuses[:-3]), f"history behind the ladder must be paid: {statuses}"

    # The backfill must self-guard: a second pass adds nothing to a contract
    # that already has claims (this is what keeps re-seeding an estate safe).
    rerun = await seed_contracts_demo(pg_session, [pid])
    await pg_session.flush()
    assert rerun["claims_backfilled"] == 0, f"the rerun backfilled again: {rerun}"
    recount = (
        (await pg_session.execute(select(ProgressClaim).where(ProgressClaim.contract_id == main.id))).scalars().all()
    )
    assert len(recount) == len(claims), "a rerun grew the claims register"
