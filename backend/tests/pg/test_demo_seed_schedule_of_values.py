# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A demo contract must arrive with a schedule of values that closes.

Before this, every contract on every demo project carried an agreed value and
nothing behind it: 52 contracts, 0 schedule lines, 0 claim lines. The catalog
in the contracts seeder does write lines, but only into a project holding no
contract at all, and a demo project arrives with an authored head contract, so
that path never ran on a real estate. The line-by-line continuation sheet and
everything reading a contract's own breakdown had no data anywhere in the
product, which is why a case built on it could not be demonstrated.

This gates the outcome rather than the writes. The arithmetic is proven
without a database in ``tests/unit/test_contracts_schedule_of_values.py``;
what needs a real schema is that the seeder puts that arithmetic on real rows,
that a re-seed does not double them, and above all that the two halves of a
payment application agree: the G702 certificate face is a pure roll-up of the
G703 rows, so if the breakdown is wrong the certificate quietly certifies a
different number from the one the register shows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

_DEMO_ID = "sov-gate-demo"


async def _make_demo_project(session) -> uuid.UUID:
    """Stand up a project the way the demo installer does: contracts, no lines.

    A head contract priced as a lump sum and a trade subcontract remeasured
    against what is built, so both schedule shapes are exercised. Neither
    carries a single line, which is exactly the state the estate was found in.
    """
    from app.modules.contracts.models import Contract
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    email = "sov-gate@reference.example"
    owner = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if owner is None:
        owner = User(email=email, hashed_password="not-a-real-hash", full_name="Reference commercial lead")
        session.add(owner)
        await session.flush()

    name = "Schedule of values reference project"
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
    wanted = (
        (f"{_DEMO_ID}-MAIN", "Main construction contract", "lump_sum", "client", Decimal("4800000.00"), "active"),
        (
            f"{_DEMO_ID}-SUB-01",
            "Subcontract - concrete works",
            "remeasurement",
            "subcontractor",
            Decimal("737291.37"),
            "active",
        ),
        (
            f"{_DEMO_ID}-SUB-02",
            "Subcontract - envelope",
            "remeasurement",
            "subcontractor",
            Decimal("412500.00"),
            "draft",
        ),
    )
    for code, title, ctype, party, value, status in wanted:
        found = (await session.execute(select(Contract).where(Contract.code == code))).scalar_one_or_none()
        if found is None:
            session.add(
                Contract(
                    code=code,
                    title=title,
                    contract_type=ctype,
                    counterparty_type=party,
                    project_id=pid,
                    start_date=start.isoformat(),
                    end_date=(start + timedelta(days=540)).isoformat(),
                    total_value=value,
                    currency="EUR",
                    retention_percent=Decimal("5"),
                    status=status,
                )
            )
    await session.flush()
    return pid


async def test_every_demo_contract_gets_a_schedule_that_sums_to_its_value(pg_session) -> None:
    """The gate: an agreed value with nothing behind it is what this ends."""
    from app.modules.contracts.models import Contract, ContractLine
    from app.modules.contracts.seed import seed_contracts_demo

    pid = await _make_demo_project(pg_session)
    report = await seed_contracts_demo(pg_session, [pid])
    await pg_session.flush()

    assert report["lines_backfilled"] > 0, f"the schedule backfill wrote nothing: {report}"

    contracts = (await pg_session.execute(select(Contract).where(Contract.project_id == pid))).scalars().all()
    assert contracts, "the fixture wrote no contracts"

    for contract in contracts:
        lines = (
            (
                await pg_session.execute(
                    select(ContractLine)
                    .where(ContractLine.contract_id == contract.id)
                    .order_by(ContractLine.order_index)
                )
            )
            .scalars()
            .all()
        )
        assert lines, f"{contract.code} still has no schedule of values"
        assert sum(line.total_value for line in lines) == contract.total_value, (
            f"{contract.code}: schedule sums to {sum(line.total_value for line in lines)}, "
            f"contract is worth {contract.total_value}"
        )
        for line in lines:
            assert line.total_value == line.quantity * line.unit_rate, (
                f"{contract.code} line {line.code}: {line.quantity} x {line.unit_rate} != {line.total_value}"
            )
            assert line.description.strip(), f"{contract.code} line {line.code} has no description"


async def test_a_draft_contract_is_scheduled_too(pg_session) -> None:
    """A schedule of values is what a contract is agreed against, so it exists
    before signature. The claims backfill deliberately skips drafts; this must
    not inherit that rule, or the one contract a reader opens to see the
    lifecycle step before signing would be the empty one."""
    from app.modules.contracts.models import Contract, ContractLine
    from app.modules.contracts.seed import seed_contracts_demo

    pid = await _make_demo_project(pg_session)
    await seed_contracts_demo(pg_session, [pid])
    await pg_session.flush()

    draft = (await pg_session.execute(select(Contract).where(Contract.code == f"{_DEMO_ID}-SUB-02"))).scalar_one()
    assert draft.status == "draft"
    lines = (await pg_session.execute(select(ContractLine).where(ContractLine.contract_id == draft.id))).scalars().all()
    assert lines, "the draft subcontract was left without a schedule"
    assert sum(line.total_value for line in lines) == draft.total_value


async def test_the_certificate_face_agrees_with_the_register(pg_session) -> None:
    """The outcome that makes a payment application demonstrable.

    ``build_g702_summary`` is a pure roll-up of the G703 rows, so it never
    reads the claim's own gross amount. If the breakdown does not reconcile,
    the certificate silently certifies a different figure from the one the
    claim register shows, which is worse than an empty sheet because it looks
    finished.
    """
    from app.modules.contracts.aia import build_g702_summary, build_g703
    from app.modules.contracts.models import Contract, ContractLine, ProgressClaim, ProgressClaimLine
    from app.modules.contracts.seed import seed_contracts_demo

    pid = await _make_demo_project(pg_session)
    report = await seed_contracts_demo(pg_session, [pid])
    await pg_session.flush()
    assert report["claim_lines_backfilled"] > 0, f"no claim was broken down: {report}"
    assert report["claims_over_schedule"] == 0, (
        f"{report['claims_over_schedule']} claims could not be placed inside the schedule"
    )

    contract = (await pg_session.execute(select(Contract).where(Contract.code == f"{_DEMO_ID}-MAIN"))).scalar_one()
    lines = (
        (
            await pg_session.execute(
                select(ContractLine).where(ContractLine.contract_id == contract.id).order_by(ContractLine.order_index)
            )
        )
        .scalars()
        .all()
    )
    claims = (
        (
            await pg_session.execute(
                select(ProgressClaim)
                .where(ProgressClaim.contract_id == contract.id)
                .order_by(ProgressClaim.period_start, ProgressClaim.claim_number)
            )
        )
        .scalars()
        .all()
    )
    assert claims, "the claims backfill left the head contract empty"

    scheduled = {line.id: line.total_value for line in lines}
    running = Decimal("0")
    for claim in claims:
        claim_lines = (
            (await pg_session.execute(select(ProgressClaimLine).where(ProgressClaimLine.progress_claim_id == claim.id)))
            .scalars()
            .all()
        )
        assert claim_lines, f"claim {claim.claim_number} has no breakdown"

        # The claim is apportioned, never restated: what the lines say this
        # period must be what the register says the claim is worth.
        period_total = sum(line.period_completed_value for line in claim_lines)
        assert period_total == claim.gross_amount, (
            f"{claim.claim_number}: lines total {period_total}, claim says {claim.gross_amount}"
        )

        # No line may be billed past what it was scheduled at.
        for line in claim_lines:
            assert line.cumulative_completed_value <= scheduled[line.contract_line_id], (
                f"{claim.claim_number}: line billed to {line.cumulative_completed_value} "
                f"against a scheduled {scheduled[line.contract_line_id]}"
            )

        running += claim.gross_amount

        # And the certificate face, rolled up from the continuation sheet the
        # product would print, has to land on the same number.
        by_line = {line.contract_line_id: line for line in claim_lines}
        rows = build_g703(lines, by_line, retainage_percent=contract.retention_percent or Decimal("0"))
        g702 = build_g702_summary(
            rows,
            original_contract_sum=contract.total_value,
            previous_certificates_total=claim.prior_claims_total or Decimal("0"),
        )
        assert g702["total_completed_stored"] == running.quantize(Decimal("0.01")), (
            f"{claim.claim_number}: the certificate certifies {g702['total_completed_stored']} "
            f"earned to date, the register says {running}"
        )
        assert g702["balance_to_finish"] >= 0, f"{claim.claim_number}: the certificate is overbilled"


async def test_a_second_pass_does_not_double_the_schedule(pg_session) -> None:
    """Re-seeding is how the demo estate is refreshed, so it has to be a no-op."""
    from app.modules.contracts.models import ContractLine, ProgressClaimLine
    from app.modules.contracts.seed import seed_contracts_demo

    pid = await _make_demo_project(pg_session)
    await seed_contracts_demo(pg_session, [pid])
    await pg_session.flush()
    before_lines = len((await pg_session.execute(select(ContractLine))).scalars().all())
    before_claim_lines = len((await pg_session.execute(select(ProgressClaimLine))).scalars().all())

    rerun = await seed_contracts_demo(pg_session, [pid])
    await pg_session.flush()

    assert rerun["lines_backfilled"] == 0, f"the rerun re-scheduled a scheduled contract: {rerun}"
    assert rerun["claim_lines_backfilled"] == 0, f"the rerun re-broke-down a broken-down claim: {rerun}"
    after_lines = len((await pg_session.execute(select(ContractLine))).scalars().all())
    after_claim_lines = len((await pg_session.execute(select(ProgressClaimLine))).scalars().all())
    assert after_lines == before_lines, "a rerun grew the schedule"
    assert after_claim_lines == before_claim_lines, "a rerun grew the claim breakdown"


_DE_DEMO_ID = "office-frankfurt"


async def _make_german_demo_project(session) -> uuid.UUID:
    """Stand up a German-worded project the way the demo installer does.

    The titles are copied from the estate verbatim, company names included.
    "Kessmar Rohbau GmbH" is here on purpose: it holds the external-walls
    package, so a match that read the whole title would give it a Rohbau
    schedule.
    """
    from app.modules.contracts.models import Contract
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    email = "sov-gate-de@reference.example"
    owner = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if owner is None:
        owner = User(email=email, hashed_password="not-a-real-hash", full_name="Reference Bauleiter")
        session.add(owner)
        await session.flush()

    name = "Schedule of values reference project DE"
    project = (await session.execute(select(Project).where(Project.name == name))).scalars().first()
    if project is None:
        project = Project(
            name=name,
            owner_id=owner.id,
            country_code="DE",
            currency="EUR",
            metadata_={"demo_id": _DE_DEMO_ID},
        )
        session.add(project)
        await session.flush()
    pid = uuid.UUID(str(project.id))

    start = datetime.now(UTC).date() - timedelta(days=150)
    wanted = (
        (
            "sov-de-MAIN",
            "Main construction contract - Bürogebäude Frankfurt Europaviertel",
            "lump_sum",
            "client",
            Decimal("6400000.00"),
        ),
        (
            "sov-de-SUB-01",
            "Subcontract - Baugrube / Erdbau (Rahnstett Bau Hessen GmbH)",
            "remeasurement",
            "subcontractor",
            Decimal("842750.00"),
        ),
        (
            "sov-de-SUB-02",
            "Subcontract - Außenwände (Kessmar Rohbau GmbH)",
            "remeasurement",
            "subcontractor",
            Decimal("1137291.37"),
        ),
    )
    for code, title, ctype, party, value in wanted:
        found = (await session.execute(select(Contract).where(Contract.code == code))).scalar_one_or_none()
        if found is None:
            session.add(
                Contract(
                    code=code,
                    title=title,
                    contract_type=ctype,
                    counterparty_type=party,
                    project_id=pid,
                    start_date=start.isoformat(),
                    end_date=(start + timedelta(days=540)).isoformat(),
                    total_value=value,
                    currency="EUR",
                    retention_percent=Decimal("5"),
                    status="active",
                )
            )
    await session.flush()
    return pid


async def test_a_german_contract_gets_a_german_schedule(pg_session) -> None:
    """The gate for the filmed projects.

    These are the ones being demonstrated, and a continuation sheet reading
    "Substructure and foundations" under "Subcontract - Baugrube / Erdbau" is
    the most visible half-translated thing a viewer can see. What is asserted
    is that the German catalogue reached the rows, that it was chosen by the
    trade each contract names, and that the English seeder wrote none of it.
    """
    from app.modules.contracts.models import Contract, ContractLine
    from app.modules.contracts.seed import seed_contracts_demo

    pid = await _make_german_demo_project(pg_session)
    report = await seed_contracts_demo(pg_session, [pid])
    await pg_session.flush()

    # Every line on this project came from the German seeder. If the English
    # one had reached it the totals would differ, so this is the filter's gate
    # rather than a restatement of the count.
    assert report["schedule_lines_de"] > 0, f"the German backfill wrote nothing: {report}"
    assert report["lines_backfilled"] == report["schedule_lines_de"], (
        f"the English catalogue reached a German project: {report}"
    )

    contracts = (await pg_session.execute(select(Contract).where(Contract.project_id == pid))).scalars().all()
    by_code = {contract.code: contract for contract in contracts}
    schedules: dict[str, list[ContractLine]] = {}
    for contract in contracts:
        schedules[contract.code] = (
            (
                await pg_session.execute(
                    select(ContractLine)
                    .where(ContractLine.contract_id == contract.id)
                    .order_by(ContractLine.order_index)
                )
            )
            .scalars()
            .all()
        )

    for code, lines in schedules.items():
        assert lines, f"{code} has no schedule"
        assert sum(line.total_value for line in lines) == by_code[code].total_value
        # Written in German, not transliterated into it.
        assert any(ch in line.description for line in lines for ch in "äöüÄÖÜß"), (
            f"{code} has no German wording in its schedule: {[line.description for line in lines]}"
        )

    # The head contract is costed by DIN 276 cost group, the way this estate's
    # own Kostenberechnung is structured.
    assert [line.code for line in schedules["sov-de-MAIN"][:3]] == ["300", "320", "330"]

    # The earthworks subcontract is broken into earthworks positions.
    erdbau = {line.description for line in schedules["sov-de-SUB-01"]}
    assert any("Aushub Baugrube" in description for description in erdbau), erdbau

    # And the external-walls package let to a firm called Rohbau is broken
    # into external-walls positions, not shell-and-core ones.
    aussenwaende = {line.description for line in schedules["sov-de-SUB-02"]}
    assert any("WDVS" in description for description in aussenwaende), aussenwaende
    assert not any("Industrieboden" in description for description in aussenwaende), aussenwaende


async def test_the_german_claims_are_broken_down_too(pg_session) -> None:
    """The claim breakdown is language agnostic and must serve both catalogues.

    It apportions whatever schedule it finds, so the German projects are not
    passed to it separately. This proves that reading is right rather than
    assumed, because a German contract left with claims and no breakdown would
    certify zero earned exactly as an English one would.
    """
    from app.modules.contracts.models import Contract, ProgressClaim, ProgressClaimLine
    from app.modules.contracts.seed import seed_contracts_demo

    pid = await _make_german_demo_project(pg_session)
    report = await seed_contracts_demo(pg_session, [pid])
    await pg_session.flush()

    assert report["claim_lines_backfilled"] > 0, f"no German claim was broken down: {report}"
    assert report["claims_over_schedule"] == 0, report

    contract = (await pg_session.execute(select(Contract).where(Contract.code == "sov-de-MAIN"))).scalar_one()
    claims = (
        (await pg_session.execute(select(ProgressClaim).where(ProgressClaim.contract_id == contract.id)))
        .scalars()
        .all()
    )
    assert claims, "the German head contract got no claims"
    for claim in claims:
        claim_lines = (
            (await pg_session.execute(select(ProgressClaimLine).where(ProgressClaimLine.progress_claim_id == claim.id)))
            .scalars()
            .all()
        )
        assert claim_lines, f"German claim {claim.claim_number} has no breakdown"
        assert sum(line.period_completed_value for line in claim_lines) == claim.gross_amount
