# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""DB-backed module tests for the Gap I progress-claim bridge.

Runs against the real embedded PostgreSQL the suite boots, using the canonical
``transactional_session`` isolation primitive (one outer transaction rolled
back per test). Covers the service contract end-to-end:

* populate preview happy path (latest observation per BOQ position drives value);
* no progress in period -> empty preview;
* SoV line without a BOQ link -> skipped + counted;
* claim not draft/submitted -> 422; claim not found -> 404;
* boq_position_ids filter narrows the preview;
* commit happy path writes lines + rolls up gross/retention/net;
* commit idempotency (re-run yields one set of lines, not duplicates);
* commit replaces only the ticked lines and keeps the rest, with their findings;
* commit on a non-editable claim -> 422;
* commit with a foreign contract line -> 404 (no partial write);
* retention + net-due math;
* the ``contracts.claim.populated`` event fires with the right payload;
* multi-period observations -> the latest is used;
* project isolation -> an observation in another project never leaks.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.boq.models import BOQ, Position
from app.modules.contracts.events import CLAIM_POPULATED
from app.modules.contracts.models import Contract, ContractLine, ProgressClaim, ProgressClaimLine
from app.modules.contracts.service import BOQ_POSITION_META_KEY, PERCENT_REGRESSED_META_KEY, ContractsService
from app.modules.progress.models import ProgressEntry
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email="owner@bridge.io", hashed_password="x", full_name="Owner"))
        await s.flush()
        yield s


# ── Seed helpers ───────────────────────────────────────────────────────────


async def _make_project(s, *, currency: str = "USD") -> Project:
    project = Project(
        id=uuid.uuid4(),
        name="Bridge Project",
        owner_id=OWNER_ID,
        currency=currency,
        status="active",
        metadata_={},
    )
    s.add(project)
    await s.flush()
    return project


async def _make_boq_position(s, project: Project) -> Position:
    boq = BOQ(id=uuid.uuid4(), project_id=project.id, name="Main BOQ")
    s.add(boq)
    await s.flush()
    pos = Position(
        id=uuid.uuid4(),
        boq_id=boq.id,
        ordinal="01.001",
        description="Concrete works",
        unit="m3",
        quantity="100",
        unit_rate="50",
        total="5000",
    )
    s.add(pos)
    await s.flush()
    return pos


async def _make_contract(s, project: Project, *, retention_percent: str = "5.00") -> Contract:
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        currency=project.currency,
        retention_percent=Decimal(retention_percent),
        status="active",
    )
    s.add(contract)
    await s.flush()
    return contract


async def _make_line(
    s,
    contract: Contract,
    *,
    total_value: str = "1000",
    quantity: str = "10",
    boq_position_id: uuid.UUID | None = None,
    currency: str | None = None,
    code: str = "L1",
) -> ContractLine:
    meta: dict = {}
    if boq_position_id is not None:
        meta[BOQ_POSITION_META_KEY] = str(boq_position_id)
    if currency is not None:
        meta["currency"] = currency
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code=code,
        description=f"SoV {code}",
        quantity=Decimal(quantity),
        unit_rate=Decimal("0"),
        total_value=Decimal(total_value),
        metadata_=meta,
    )
    s.add(line)
    await s.flush()
    return line


async def _make_entry(
    s,
    project: Project,
    position: Position,
    *,
    pct: str,
    period: str = "2026-W22",
    recorded_at: datetime | None = None,
) -> ProgressEntry:
    entry = ProgressEntry(
        id=uuid.uuid4(),
        project_id=project.id,
        boq_position_id=position.id,
        period_label=period,
        percent_complete=Decimal(pct),
        recorded_at=recorded_at or datetime.now(UTC),
    )
    s.add(entry)
    await s.flush()
    return entry


async def _make_claim(s, contract: Contract, *, status: str = "draft") -> ProgressClaim:
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number=f"PC-{uuid.uuid4().hex[:4]}",
        currency=contract.currency,
        status=status,
    )
    s.add(claim)
    await s.flush()
    return claim


# ── Preview ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_populate_preview_happy_path(session) -> None:
    project = await _make_project(session)
    pos = await _make_boq_position(session, project)
    contract = await _make_contract(session, project, retention_percent="5")
    await _make_line(session, contract, total_value="1000", quantity="10", boq_position_id=pos.id)
    await _make_entry(session, project, pos, pct="40")
    claim = await _make_claim(session, contract)

    svc = ContractsService(session)
    preview = await svc.populate_claim_from_progress(claim.id)

    assert len(preview["items"]) == 1
    item = preview["items"][0]
    assert item["period_completed_value"] == Decimal("400.0000")
    assert item["period_completed_qty"] == Decimal("4.0000")
    assert preview["gross"] == Decimal("400.0000")
    assert preview["retention"] == Decimal("20.0000")  # 5% of 400
    assert preview["net_due"] == Decimal("380.0000")
    assert preview["currency"] == "USD"


@pytest.mark.asyncio
async def test_populate_preview_no_progress_empty(session) -> None:
    project = await _make_project(session)
    pos = await _make_boq_position(session, project)
    contract = await _make_contract(session, project)
    await _make_line(session, contract, boq_position_id=pos.id)
    claim = await _make_claim(session, contract)

    svc = ContractsService(session)
    preview = await svc.populate_claim_from_progress(claim.id)
    assert preview["items"] == []
    assert preview["skipped_no_progress"] == 1
    assert preview["gross"] == Decimal("0")


@pytest.mark.asyncio
async def test_populate_preview_unlinked_line_skipped(session) -> None:
    project = await _make_project(session)
    contract = await _make_contract(session, project)
    await _make_line(session, contract, boq_position_id=None)  # no BOQ link
    claim = await _make_claim(session, contract)

    svc = ContractsService(session)
    preview = await svc.populate_claim_from_progress(claim.id)
    assert preview["items"] == []
    assert preview["skipped_unlinked"] == 1


@pytest.mark.asyncio
async def test_populate_preview_foreign_currency_skipped(session) -> None:
    project = await _make_project(session, currency="USD")
    pos = await _make_boq_position(session, project)
    contract = await _make_contract(session, project)
    await _make_line(session, contract, boq_position_id=pos.id, currency="EUR")
    await _make_entry(session, project, pos, pct="50")
    claim = await _make_claim(session, contract)

    svc = ContractsService(session)
    preview = await svc.populate_claim_from_progress(claim.id)
    assert preview["items"] == []
    assert preview["skipped_foreign_currency"] == 1


@pytest.mark.asyncio
async def test_populate_preview_claim_not_editable_422(session) -> None:
    project = await _make_project(session)
    contract = await _make_contract(session, project)
    claim = await _make_claim(session, contract, status="approved")

    svc = ContractsService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.populate_claim_from_progress(claim.id)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_populate_preview_claim_not_found_404(session) -> None:
    svc = ContractsService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.populate_claim_from_progress(uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_populate_preview_filter_by_position_ids(session) -> None:
    project = await _make_project(session)
    pos_a = await _make_boq_position(session, project)
    pos_b = await _make_boq_position(session, project)
    contract = await _make_contract(session, project)
    await _make_line(session, contract, total_value="1000", boq_position_id=pos_a.id, code="A")
    await _make_line(session, contract, total_value="2000", boq_position_id=pos_b.id, code="B")
    await _make_entry(session, project, pos_a, pct="100")
    await _make_entry(session, project, pos_b, pct="100")
    claim = await _make_claim(session, contract)

    svc = ContractsService(session)
    preview = await svc.populate_claim_from_progress(claim.id, boq_position_ids=[pos_a.id])
    assert len(preview["items"]) == 1
    assert preview["items"][0]["boq_position_id"] == pos_a.id


@pytest.mark.asyncio
async def test_populate_preview_multi_period_latest_wins(session) -> None:
    project = await _make_project(session)
    pos = await _make_boq_position(session, project)
    contract = await _make_contract(session, project)
    await _make_line(session, contract, total_value="1000", boq_position_id=pos.id)
    now = datetime.now(UTC)
    await _make_entry(session, project, pos, pct="30", period="2026-W20", recorded_at=now - timedelta(days=14))
    await _make_entry(session, project, pos, pct="70", period="2026-W22", recorded_at=now)
    claim = await _make_claim(session, contract)

    svc = ContractsService(session)
    preview = await svc.populate_claim_from_progress(claim.id)
    assert preview["items"][0]["observed_pct"] == Decimal("70.0000")
    assert preview["items"][0]["period_completed_value"] == Decimal("700.0000")


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_populate_preview_project_isolation(session) -> None:
    project = await _make_project(session)
    other = await _make_project(session)
    # A position + observation that lives in ANOTHER project.
    other_pos = await _make_boq_position(session, other)
    await _make_entry(session, other, other_pos, pct="99")
    contract = await _make_contract(session, project)
    # Contract line in `project` points at the OTHER project's position id.
    await _make_line(session, contract, boq_position_id=other_pos.id)
    claim = await _make_claim(session, contract)

    svc = ContractsService(session)
    preview = await svc.populate_claim_from_progress(claim.id)
    # The cross-project observation must not leak; line counts as no-progress.
    assert preview["items"] == []
    assert preview["skipped_no_progress"] == 1


# ── Commit ─────────────────────────────────────────────────────────────────


class _CommitLine:
    """Minimal stand-in for the ProgressClaimCommitLine schema object."""

    def __init__(self, contract_line_id, pct, value=None) -> None:
        self.contract_line_id = contract_line_id
        self.period_completed_pct = Decimal(str(pct))
        self.period_completed_value = None if value is None else Decimal(str(value))


@pytest.mark.asyncio
async def test_commit_happy_path_rolls_up_totals(session) -> None:
    project = await _make_project(session)
    pos = await _make_boq_position(session, project)
    contract = await _make_contract(session, project, retention_percent="10")
    line = await _make_line(session, contract, total_value="1000", quantity="10", boq_position_id=pos.id)
    claim = await _make_claim(session, contract)

    svc = ContractsService(session)
    await svc.commit_preview_to_claim(claim.id, [_CommitLine(line.id, "50")])

    lines = await svc.claim_line_repo.list_for_claim(claim.id)
    assert len(lines) == 1
    assert lines[0].period_completed_value == Decimal("500.0000")
    refreshed = await svc.claim_repo.get_by_id(claim.id)
    assert refreshed.gross_amount == Decimal("500.0000")
    assert refreshed.retention_amount == Decimal("50.0000")  # 10% of 500
    assert refreshed.net_due == Decimal("450.0000")


@pytest.mark.asyncio
async def test_commit_idempotent_no_duplicates(session) -> None:
    project = await _make_project(session)
    pos = await _make_boq_position(session, project)
    contract = await _make_contract(session, project)
    line = await _make_line(session, contract, total_value="800", boq_position_id=pos.id)
    claim = await _make_claim(session, contract)

    svc = ContractsService(session)
    await svc.commit_preview_to_claim(claim.id, [_CommitLine(line.id, "25")])
    await svc.commit_preview_to_claim(claim.id, [_CommitLine(line.id, "25")])

    lines = await svc.claim_line_repo.list_for_claim(claim.id)
    assert len(lines) == 1  # not 2


@pytest.mark.asyncio
async def test_commit_leaves_the_lines_it_was_not_given_alone(session) -> None:
    """Unticking a row, or a line never on the preview, must not delete it.

    The commit used to wipe every line on the claim and write back only the
    ticked rows. The preview lists only lines with progress behind them, so a
    line the contractor typed in by hand was deleted by every commit without
    a word, and the claim billed less than it had a minute earlier.
    """
    project = await _make_project(session)
    pos = await _make_boq_position(session, project)
    contract = await _make_contract(session, project, retention_percent="10")
    fed = await _make_line(session, contract, total_value="1000", boq_position_id=pos.id, code="L1")
    by_hand = await _make_line(session, contract, total_value="400", code="L2")
    claim = await _make_claim(session, contract)
    session.add(
        ProgressClaimLine(
            id=uuid.uuid4(),
            progress_claim_id=claim.id,
            contract_line_id=by_hand.id,
            period_completed_value=Decimal("200"),
            period_completed_pct=Decimal("50"),
            cumulative_completed_value=Decimal("200"),
        )
    )
    await session.flush()

    svc = ContractsService(session)
    await svc.commit_preview_to_claim(claim.id, [_CommitLine(fed.id, "50")])
    lines = {ln.contract_line_id: ln for ln in await svc.claim_line_repo.list_for_claim(claim.id)}
    assert set(lines) == {fed.id, by_hand.id}
    assert lines[by_hand.id].period_completed_value == Decimal("200")
    assert lines[fed.id].period_completed_value == Decimal("500.0000")
    refreshed = await svc.claim_repo.get_by_id(claim.id)
    # The totals are the claim's, the kept line included.
    assert refreshed.gross_amount == Decimal("700.0000")
    assert refreshed.retention_amount == Decimal("70.0000")
    assert refreshed.net_due == Decimal("630.0000")

    # Committing the fed line again replaces that line and only that line.
    await svc.commit_preview_to_claim(claim.id, [_CommitLine(fed.id, "60")])
    lines = {ln.contract_line_id: ln for ln in await svc.claim_line_repo.list_for_claim(claim.id)}
    assert len(await svc.claim_line_repo.list_for_claim(claim.id)) == 2
    assert lines[fed.id].period_completed_value == Decimal("600.0000")
    assert lines[by_hand.id].period_completed_value == Decimal("200")

    # An empty commit changes no line.
    await svc.commit_preview_to_claim(claim.id, [])
    assert len(await svc.claim_line_repo.list_for_claim(claim.id)) == 2


@pytest.mark.asyncio
async def test_commit_keeps_the_findings_on_lines_it_did_not_touch(session) -> None:
    """A line left alone keeps its "percent went backwards" finding.

    The finding lives on the claim, not on the line, so a commit that rewrote
    the list from its own rows only would clear a warning about a line it
    never looked at, and the claim would submit without it.
    """
    project = await _make_project(session)
    pos = await _make_boq_position(session, project)
    contract = await _make_contract(session, project)
    fed = await _make_line(session, contract, total_value="1000", boq_position_id=pos.id, code="L1")
    other = await _make_line(session, contract, total_value="400", boq_position_id=pos.id, code="L2")
    claim = await _make_claim(session, contract)
    claim.metadata_ = {
        PERCENT_REGRESSED_META_KEY: [
            {
                "contract_line_id": str(other.id),
                "code": "L2",
                "observed_pct": "30",
                "requested_value": "120",
                "previous_value": "160",
            }
        ]
    }
    await session.flush()

    svc = ContractsService(session)
    await svc.commit_preview_to_claim(claim.id, [_CommitLine(fed.id, "50")])
    refreshed = await svc.claim_repo.get_by_id(claim.id)
    assert [e["contract_line_id"] for e in refreshed.metadata_[PERCENT_REGRESSED_META_KEY]] == [str(other.id)]

    # Committed again on a percent that moves forward, the line's finding goes.
    await svc.commit_preview_to_claim(claim.id, [_CommitLine(other.id, "50")])
    refreshed = await svc.claim_repo.get_by_id(claim.id)
    assert PERCENT_REGRESSED_META_KEY not in (refreshed.metadata_ or {})


@pytest.mark.asyncio
async def test_commit_delete_with_no_lines_no_error(session) -> None:
    project = await _make_project(session)
    contract = await _make_contract(session, project)
    claim = await _make_claim(session, contract)
    svc = ContractsService(session)
    # Committing an empty set on a claim that has no lines must not error.
    await svc.commit_preview_to_claim(claim.id, [])
    lines = await svc.claim_line_repo.list_for_claim(claim.id)
    assert lines == []


@pytest.mark.asyncio
async def test_commit_value_override_clamped(session) -> None:
    project = await _make_project(session)
    pos = await _make_boq_position(session, project)
    contract = await _make_contract(session, project, retention_percent="0")
    line = await _make_line(session, contract, total_value="1000", boq_position_id=pos.id)
    claim = await _make_claim(session, contract)

    svc = ContractsService(session)
    # Override above the line value must be clamped to 1000.
    await svc.commit_preview_to_claim(claim.id, [_CommitLine(line.id, "50", value=99999)])
    lines = await svc.claim_line_repo.list_for_claim(claim.id)
    assert lines[0].period_completed_value == Decimal("1000")


@pytest.mark.asyncio
async def test_commit_claim_not_editable_422(session) -> None:
    project = await _make_project(session)
    contract = await _make_contract(session, project)
    claim = await _make_claim(session, contract, status="certified")
    svc = ContractsService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.commit_preview_to_claim(claim.id, [])
    assert exc.value.status_code == 422


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_commit_foreign_contract_line_404_no_partial_write(session) -> None:
    project = await _make_project(session)
    contract = await _make_contract(session, project)
    claim = await _make_claim(session, contract)
    svc = ContractsService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.commit_preview_to_claim(claim.id, [_CommitLine(uuid.uuid4(), "50")])
    assert exc.value.status_code == 404
    # No lines were written despite the raise (validated before mutation).
    lines = await svc.claim_line_repo.list_for_claim(claim.id)
    assert lines == []


@pytest.mark.asyncio
async def test_commit_emits_event(session, monkeypatch) -> None:
    project = await _make_project(session)
    pos = await _make_boq_position(session, project)
    contract = await _make_contract(session, project)
    line = await _make_line(session, contract, total_value="1000", boq_position_id=pos.id)
    claim = await _make_claim(session, contract)

    captured: list[tuple] = []

    from app.modules.contracts import service as service_mod

    def _capture(name, *, data, source_module):  # noqa: ANN001
        captured.append((name, data, source_module))

    monkeypatch.setattr(service_mod.event_bus, "publish_detached", _capture)

    svc = ContractsService(session)
    await svc.commit_preview_to_claim(claim.id, [_CommitLine(line.id, "50")], actor_id="user-1")

    events = [c for c in captured if c[0] == CLAIM_POPULATED]
    assert len(events) == 1
    payload = events[0][1]
    assert payload["claim_id"] == str(claim.id)
    assert payload["contract_id"] == str(contract.id)
    assert payload["line_count"] == 1
    assert payload["gross"] == "500.0000"
    assert payload["actor"] == "user-1"
    assert events[0][2] == "contracts"


# ── Two billing periods from measured progress ─────────────────────────────


async def _dated_claim(s, contract: Contract, number: str, start: date, end: date) -> ProgressClaim:
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number=number,
        currency=contract.currency,
        status="draft",
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        period_from=start,
        period_to=end,
    )
    s.add(claim)
    await s.flush()
    return claim


@pytest.mark.asyncio
async def test_two_periods_from_measured_progress_bill_the_work_once(session) -> None:
    """March at 40% and April at 60% bill 40,000 and then 20,000, never 60,000 again.

    Every observation is on record before either preview is taken, the way a
    claim is often prepared late: March still reads the site as it stood on
    31 March, and April bills only what the site added over what March billed.
    """
    project = await _make_project(session)
    pos = await _make_boq_position(session, project)
    contract = await _make_contract(session, project, retention_percent="10")
    line = await _make_line(session, contract, total_value="100000", quantity="10", boq_position_id=pos.id)
    await _make_entry(session, project, pos, pct="40", period="2026-03", recorded_at=datetime(2026, 3, 20, tzinfo=UTC))
    await _make_entry(session, project, pos, pct="60", period="2026-04", recorded_at=datetime(2026, 4, 25, tzinfo=UTC))
    # Measured after April closed; no claim here may bill it.
    await _make_entry(session, project, pos, pct="90", period="2026-05", recorded_at=datetime(2026, 5, 10, tzinfo=UTC))
    march = await _dated_claim(session, contract, "PC-1", date(2026, 3, 1), date(2026, 3, 31))
    april = await _dated_claim(session, contract, "PC-2", date(2026, 4, 1), date(2026, 4, 30))
    svc = ContractsService(session)

    [m] = (await svc.populate_claim_from_progress(march.id))["items"]
    assert m["observed_pct"] == Decimal("40.0000")
    assert m["prior_completed_value"] == Decimal("0")
    assert m["period_completed_value"] == Decimal("40000.0000")
    assert m["cumulative_completed_value"] == Decimal("40000.0000")
    await svc.commit_preview_to_claim(march.id, [_CommitLine(line.id, m["observed_pct"])])
    march.status = "submitted"
    await session.flush()

    preview = await svc.populate_claim_from_progress(april.id)
    [a] = preview["items"]
    assert a["observed_pct"] == Decimal("60.0000")
    assert a["prior_completed_value"] == Decimal("40000.0000")
    assert a["period_completed_value"] == Decimal("20000.0000")
    assert a["cumulative_completed_value"] == Decimal("60000.0000")
    # 6 of the 10 units to date, 4 of them billed in March.
    assert a["period_completed_qty"] == Decimal("2.0000")
    assert preview["gross"] == Decimal("20000.0000")

    await svc.commit_preview_to_claim(april.id, [_CommitLine(line.id, a["observed_pct"])])
    [row] = await svc.claim_line_repo.list_for_claim(april.id)
    assert row.period_completed_value == Decimal("20000.0000")
    assert row.prior_completed_value == Decimal("40000.0000")
    assert row.cumulative_completed_value == Decimal("60000.0000")
    # Across both claims the line is billed at its percent to date, once.
    billed = [
        Decimal(str(r.period_completed_value))
        for claim in (march, april)
        for r in await svc.claim_line_repo.list_for_claim(claim.id)
    ]
    assert sum(billed, Decimal("0")) == Decimal("60000")


@pytest.mark.asyncio
async def test_a_percent_edited_in_the_preview_is_billed_over_what_came_before(session) -> None:
    """The person corrects April to 55%: the claim bills 15,000 over March's 40,000."""
    project = await _make_project(session)
    pos = await _make_boq_position(session, project)
    contract = await _make_contract(session, project, retention_percent="10")
    line = await _make_line(session, contract, total_value="100000", quantity="10", boq_position_id=pos.id)
    march = await _dated_claim(session, contract, "PC-1", date(2026, 3, 1), date(2026, 3, 31))
    april = await _dated_claim(session, contract, "PC-2", date(2026, 4, 1), date(2026, 4, 30))
    svc = ContractsService(session)
    await svc.commit_preview_to_claim(march.id, [_CommitLine(line.id, "40")])
    march.status = "submitted"
    await session.flush()

    april = await svc.commit_preview_to_claim(april.id, [_CommitLine(line.id, "55")])
    [row] = await svc.claim_line_repo.list_for_claim(april.id)
    assert row.period_completed_pct == Decimal("55.0000")
    assert row.period_completed_value == Decimal("15000.0000")
    assert april.gross_amount == Decimal("15000.0000")

    # Corrected below March, the line bills nothing and the claim says why.
    april = await svc.commit_preview_to_claim(april.id, [_CommitLine(line.id, "30")])
    [row] = await svc.claim_line_repo.list_for_claim(april.id)
    assert row.period_completed_value == Decimal("0")
    assert [e["contract_line_id"] for e in (april.metadata_ or {})[PERCENT_REGRESSED_META_KEY]] == [str(line.id)]
