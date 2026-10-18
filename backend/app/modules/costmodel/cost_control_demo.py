# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A fixed demo project for the cost control page: "Bürohaus Lindenhof".

The cost control film series is shot on one invented office building whose
figures are known in advance, so every number on screen can be checked against
the script before a take. This module writes that project from scratch through
the same tables the report reads, and nothing else:

* six DIN 276 cost lines with a budget line each (and an estimate on 410);
* four subcontracts with a schedule of values, the approved change orders
  posted onto them the way the contracts subscriber posts an approval;
* one paid progress claim per contract that has work certified, with the 5 %
  retention held on the claim so "paid" is certified minus retention;
* a submitted change order (N-03) waiting for a decision;
* an issued purchase order (B-2026-014) whose only item sits on no cost line;
* four saved forecasts dated in the past, so the history chart has a story and
  the "no forecast saved" finding stays quiet.

The project carries a ``demo_id`` marker like every other demo installer, so the
demo bookkeeping recognises it and a second install returns the first project
instead of writing a copy. German appears only as data values.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.demo_marker import live_demo_projects, restore_demo_id
from app.modules.costmodel.cost_control import (
    CENT,
    SOURCE_AWARDED,
    SOURCE_BUDGET,
    SOURCE_ESTIMATE,
    SOURCE_FINAL,
    SOURCE_MEASURED,
    SOURCE_PARTLY_AWARDED,
    STAGE_AWARD,
    STAGE_DETAILED_ESTIMATE,
    STAGE_FORECAST,
    variance_pct,
)

#: The marker that identifies this demo project; never change it, idempotency keys on it.
DEMO_ID = "cost-control-lindenhof"

PROJECT_NAME = "Bürohaus Lindenhof"
CURRENCY = "EUR"
RETENTION_PCT = Decimal("5")

D = Decimal
ZERO = D("0")


@dataclass(frozen=True, slots=True)
class _LineSpec:
    code: str
    description: str
    budget: Decimal
    estimate: Decimal = ZERO


#: Table A of the script: cost groups, budgets and the one estimate.
LINES: tuple[_LineSpec, ...] = (
    _LineSpec("310", "Baugrube, Erdbau", D("180000")),
    _LineSpec("320", "Gründung", D("240000")),
    _LineSpec("330", "Außenwände, Fassade", D("520000")),
    _LineSpec("340", "Innenwände, Trockenbau", D("310000")),
    _LineSpec("410", "Abwasser, Wasser, Gas", D("150000"), D("162000")),
    _LineSpec("440", "Starkstromanlagen", D("210000")),
)


@dataclass(frozen=True, slots=True)
class _ChangeSpec:
    code: str
    title: str
    amount: Decimal
    approved_on: date
    reason: str = "client_request"


@dataclass(frozen=True, slots=True)
class _ContractSpec:
    code: str
    title: str
    line_code: str
    line_description: str
    awarded: Decimal
    status: str
    signed_on: date
    #: Cumulative certified value on the original line, then on each change line.
    certified_original: Decimal
    certified_changes: bool
    claim_number: str
    claim_paid_on: date | None
    change: _ChangeSpec | None = None


#: Table A of the script: the subcontracts. "beauftragt" and "in Ausführung" are
#: both ``active``: a contract has no separate "let but not started" state, and a
#: draft binds nobody, so its money would not show as awarded.
CONTRACTS: tuple[_ContractSpec, ...] = (
    _ContractSpec(
        code="SUB-01",
        title="Erdbau, Muster Tiefbau GmbH",
        line_code="310",
        line_description="Baugrube und Erdarbeiten, pauschal",
        awarded=D("172000"),
        status="completed",
        signed_on=date(2026, 3, 2),
        certified_original=D("172000"),
        certified_changes=True,
        claim_number="SR-01",
        claim_paid_on=date(2026, 9, 24),
        change=_ChangeSpec("N-01", "Zusätzlicher Bodenaustausch", D("4500"), date(2026, 7, 21), "unforeseen"),
    ),
    _ContractSpec(
        code="SUB-02",
        title="Gründung, Beispiel Bau AG",
        line_code="320",
        line_description="Bodenplatte und Fundamente, nach Aufmaß",
        awarded=D("251000"),
        status="active",
        signed_on=date(2026, 4, 14),
        certified_original=D("268400"),
        certified_changes=False,
        claim_number="AR-05",
        claim_paid_on=date(2026, 10, 9),
    ),
    _ContractSpec(
        code="SUB-03",
        title="Fassade, Fassadenbau Nord GmbH",
        line_code="330",
        line_description="Vorgehängte Fassade mit Dämmung, pauschal",
        awarded=D("498000"),
        status="active",
        signed_on=date(2026, 6, 22),
        certified_original=D("210000"),
        certified_changes=False,
        claim_number="AR-03",
        claim_paid_on=date(2026, 10, 6),
        change=_ChangeSpec("N-02", "Brandriegel je Geschoss", D("18600"), date(2026, 8, 18), "regulatory"),
    ),
    _ContractSpec(
        code="SUB-04",
        title="Trockenbau Los 1, Innenausbau Süd KG",
        line_code="340",
        line_description="Trockenbauwände Los 1, pauschal",
        awarded=D("96000"),
        status="active",
        signed_on=date(2026, 9, 15),
        certified_original=ZERO,
        certified_changes=False,
        claim_number="",
        claim_paid_on=None,
    ),
)

#: The change order still waiting for a decision (approved live in episode 3).
PENDING_CHANGE = _ChangeSpec("N-03", "Mehrfläche Fassadendämmung", D("9200"), date(2026, 10, 8))
PENDING_CHANGE_CONTRACT = "SUB-03"

#: The order whose money sits on no cost line (assigned live in episode 4).
ORDER_NUMBER = "B-2026-014"
ORDER_ITEM = "Dämmplatten Mineralwolle 160 mm, Lieferung"
ORDER_QUANTITY = D("800")
ORDER_UNIT = "m2"
ORDER_RATE = D("31")
ORDER_ISSUED_ON = date(2026, 10, 1)


@dataclass(frozen=True, slots=True)
class _SnapRow:
    code: str
    source: str
    forecast: Decimal
    awarded: Decimal = ZERO
    changes: Decimal = ZERO
    certified: Decimal = ZERO
    paid: Decimal = ZERO
    estimate: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class _SnapSpec:
    taken_on: date
    stage: str
    label: str
    note: str
    rows: tuple[_SnapRow, ...]


#: Table C of the script. Only the project totals are given there; the rows are
#: a consistent history behind them: the shell let in June, the change orders in
#: July and August, the drywall package in September, measured foundation work
#: running over its award, the services estimate revised up and back down.
SNAPSHOTS: tuple[_SnapSpec, ...] = (
    _SnapSpec(
        date(2026, 3, 15),
        STAGE_DETAILED_ESTIMATE,
        "Kostenberechnung Entwurf",
        "Kostenberechnung zur Entwurfsplanung, alle Kostengruppen auf Budget.",
        (
            _SnapRow("310", SOURCE_BUDGET, D("180000")),
            _SnapRow("320", SOURCE_BUDGET, D("240000")),
            _SnapRow("330", SOURCE_BUDGET, D("520000")),
            _SnapRow("340", SOURCE_BUDGET, D("310000")),
            _SnapRow("410", SOURCE_BUDGET, D("150000")),
            _SnapRow("440", SOURCE_BUDGET, D("210000")),
        ),
    ),
    _SnapSpec(
        date(2026, 6, 30),
        STAGE_AWARD,
        "Vergabe Rohbau und Fassade",
        "Erdbau, Gründung und Fassade vergeben.",
        (
            _SnapRow("310", SOURCE_AWARDED, D("172000"), D("172000"), certified=D("95000"), paid=D("90250")),
            _SnapRow("320", SOURCE_AWARDED, D("251000"), D("251000"), certified=D("40000"), paid=D("38000")),
            _SnapRow("330", SOURCE_AWARDED, D("498000"), D("498000")),
            _SnapRow("340", SOURCE_BUDGET, D("310000")),
            _SnapRow("410", SOURCE_ESTIMATE, D("157000"), estimate=D("157000")),
            _SnapRow("440", SOURCE_BUDGET, D("210000")),
        ),
    ),
    _SnapSpec(
        date(2026, 8, 31),
        STAGE_FORECAST,
        "Kostenbericht August",
        "Gründung nach Aufmaß über Auftrag, Nachträge N-01 und N-02 freigegeben.",
        (
            _SnapRow(
                "310", SOURCE_AWARDED, D("176500"), D("172000"), D("4500"), certified=D("160000"), paid=D("152000")
            ),
            _SnapRow("320", SOURCE_MEASURED, D("256900"), D("251000"), certified=D("256900"), paid=D("244055")),
            _SnapRow(
                "330", SOURCE_AWARDED, D("516600"), D("498000"), D("18600"), certified=D("120000"), paid=D("114000")
            ),
            _SnapRow("340", SOURCE_BUDGET, D("310000")),
            _SnapRow("410", SOURCE_ESTIMATE, D("170000"), estimate=D("170000")),
            _SnapRow("440", SOURCE_BUDGET, D("210000")),
        ),
    ),
    _SnapSpec(
        date(2026, 9, 30),
        STAGE_FORECAST,
        "Kostenbericht September",
        "Erdbau abgerechnet, Trockenbau Los 1 vergeben.",
        (
            _SnapRow("310", SOURCE_FINAL, D("176500"), D("172000"), D("4500"), certified=D("176500"), paid=D("167675")),
            _SnapRow("320", SOURCE_MEASURED, D("268100"), D("251000"), certified=D("268100"), paid=D("254695")),
            _SnapRow(
                "330", SOURCE_AWARDED, D("516600"), D("498000"), D("18600"), certified=D("170000"), paid=D("161500")
            ),
            _SnapRow("340", SOURCE_PARTLY_AWARDED, D("310000"), D("96000")),
            _SnapRow("410", SOURCE_ESTIMATE, D("170000"), estimate=D("170000")),
            _SnapRow("440", SOURCE_BUDGET, D("210000")),
        ),
    ),
)


#: The reasons written on the snapshots' larger moves, keyed by (snapshot date, cost line code):
#: a comment and the evidence behind it, the way a monthly cost report is documented.
SNAPSHOT_NOTES: dict[tuple[date, str], tuple[str, list[dict[str, str]]]] = {
    (date(2026, 6, 30), "330"): (
        "Vergabe Fassade unter Budget, zweites Angebot nach Aufklärungsgespräch.",
        [{"kind": "document", "ref": "Vergabevermerk Fassade"}, {"kind": "minutes", "ref": "Bietergespräch 3"}],
    ),
    (date(2026, 6, 30), "410"): (
        "Kostenschätzung Haustechnik nach Leitungsplanung fortgeschrieben.",
        [{"kind": "document", "ref": "Kostenschätzung TGA Stand Juni"}],
    ),
    (date(2026, 8, 31), "410"): (
        "Lüftung erweitert, Nutzer wünscht zusätzliche Zone im Erdgeschoss.",
        [{"kind": "minutes", "ref": "Planungsbesprechung 11, Punkt 4"}],
    ),
    (date(2026, 8, 31), "330"): (
        "Nachträge N-01 und N-02 freigegeben.",
        [{"kind": "document", "ref": "Nachtrag N-01"}, {"kind": "document", "ref": "Nachtrag N-02"}],
    ),
    (date(2026, 9, 30), "320"): (
        "Gründung nach Aufmaß über Auftrag, Mehrmengen Bodenaustausch.",
        [{"kind": "document", "ref": "Aufmaß Gründung Blatt 7"}, {"kind": "minutes", "ref": "Baubesprechung 18"}],
    ),
}


def _at(day: date) -> datetime:
    """A fixed time of day on ``day``, so stored timestamps are deterministic."""
    return datetime.combine(day, time(16, 0), tzinfo=UTC)


def _retention(certified: Decimal) -> Decimal:
    return (certified * RETENTION_PCT / D("100")).quantize(CENT)


async def find_cost_control_demo(session: AsyncSession) -> uuid.UUID | None:
    """The installed demo project, or None when it is not installed (or was deleted)."""
    for project_id, demo_id in await live_demo_projects(session):
        if demo_id == DEMO_ID:
            return project_id
    return None


async def post_change_order_to_contract(
    session: AsyncSession, contract: object, order: object, *, approved_on: date
) -> None:
    """Put an approved change order's money on its contract, as the approval subscriber does.

    In the running app ``changeorder.approved`` reaches
    ``_on_changeorder_approved_contract`` in its own session: it records the
    order on the contract, raises the contract sum and posts the amount to the
    schedule of values. A seeder and a rolled-back test session cannot wait for
    that, so this does the same writes in the caller's session.
    """
    from app.modules.contracts.sov_posting import post_source_to_sov, source_key

    amount = D(str(order.cost_impact))  # type: ignore[attr-defined]
    key = source_key("change_order", order.id)  # type: ignore[attr-defined]
    md = dict(contract.metadata_ or {})  # type: ignore[attr-defined]
    md["change_order_ids"] = [*(md.get("change_order_ids") or []), str(order.id)]  # type: ignore[attr-defined]
    md["change_order_total"] = str(D(str(md.get("change_order_total") or 0)) + amount)
    md["posted_sources"] = [*(md.get("posted_sources") or []), key]
    contract.metadata_ = md  # type: ignore[attr-defined]
    contract.total_value = D(str(contract.total_value or 0)) + amount  # type: ignore[attr-defined]
    await session.flush()
    await post_source_to_sov(
        session,
        contract,  # type: ignore[arg-type]
        key=key,
        kind="change_order",
        source_id=order.id,  # type: ignore[attr-defined]
        code=order.code,  # type: ignore[attr-defined]
        title=order.code,  # type: ignore[attr-defined]
        amount=amount,
        currency=contract.currency,  # type: ignore[attr-defined]
        approved_on=approved_on,
    )


def _snapshot_payload(spec: _SnapSpec, line_ids: dict[str, uuid.UUID]) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Totals and rows in the shape ``CostControlService.create_snapshot`` stores."""
    descriptions = {s.code: s.description for s in LINES}
    budgets = {s.code: s.budget for s in LINES}
    rows: list[dict[str, str]] = []
    sums = dict.fromkeys(
        ("budget", "estimate", "planned", "awarded", "changes", "committed", "certified", "paid", "forecast"), ZERO
    )
    for r in spec.rows:
        planned = budgets[r.code]
        committed = r.awarded + r.changes
        figures = {
            "planned": planned,
            "awarded": r.awarded,
            "changes": r.changes,
            "committed": committed,
            "certified": r.certified,
            "paid": r.paid,
            "forecast": r.forecast,
        }
        rows.append(
            {
                "key": str(line_ids[r.code]),
                "kind": "cost_line",
                "code": r.code,
                "description": descriptions[r.code],
                "source": r.source,
                **{name: str(value.quantize(CENT)) for name, value in figures.items()},
            }
        )
        sums["budget"] += planned
        sums["estimate"] += r.estimate
        for name, value in figures.items():
            sums[name] += value
    totals = {name: str(value) for name, value in sums.items()}
    totals["variance"] = str(sums["forecast"] - sums["planned"])
    pct = variance_pct(sums["forecast"], sums["planned"])
    totals["variance_pct"] = "" if pct is None else str(pct)
    totals["pending_changes"] = "0"
    totals["pending_count"] = "0"
    totals["forecast_with_pending"] = str(sums["forecast"])
    return totals, rows


async def install_cost_control_demo(
    session: AsyncSession, owner_id: uuid.UUID, *, today: date | None = None
) -> uuid.UUID:
    """Install the "Bürohaus Lindenhof" cost control demo and return its project id.

    Idempotent: when a live project with this demo's marker exists, its id is
    returned and nothing is written. Flushes but does not commit.

    Args:
        session: Session to write through; the caller commits.
        owner_id: The user who owns the project.
        today: The shooting day. Dates of the documents are fixed by the
            script; this only stamps the project's creation time. Defaults to
            today. The saved forecasts end on 30.09.2026, so the "no forecast
            saved for more than a month" finding appears after 04.11.2026.

    Returns:
        The id of the demo project.
    """
    from app.modules.changeorders.models import ChangeOrder
    from app.modules.contracts.models import Contract, ContractLine, ProgressClaim, ProgressClaimLine
    from app.modules.costmodel.models import BudgetLine, CostForecastSnapshot, CostForecastSnapshotNote, CostLine
    from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem
    from app.modules.projects.models import Project

    existing = await find_cost_control_demo(session)
    if existing is not None:
        return existing
    # An explicit install brings back a demo the user removed earlier.
    await restore_demo_id(session, DEMO_ID)

    day = today or datetime.now(UTC).date()
    owner = str(owner_id)
    project = Project(
        id=uuid.uuid4(),
        name=PROJECT_NAME,
        description="Demoprojekt für die Filmreihe Kostenkontrolle. Alle Firmen und Zahlen sind erfunden.",
        region="DE",
        country_code="DE",
        classification_standard="din276",
        currency=CURRENCY,
        locale="de",
        status="active",
        owner_id=owner_id,
        project_code="BL-2026",
        project_type="office",
        address={"street": "Lindenallee 12", "postcode": "12345", "city": "Musterstadt", "country": "Germany"},
        budget_estimate=str(sum((s.budget for s in LINES), ZERO)),
        planned_start_date="2026-03-01",
        planned_end_date="2027-09-30",
        metadata_={"demo_id": DEMO_ID, "is_demo": True},
    )
    project.created_at = _at(day)
    session.add(project)
    await session.flush()
    pid = project.id

    # ── Cost lines and their budgets ──────────────────────────────────────
    lines: dict[str, CostLine] = {}
    for spec in LINES:
        line = CostLine(
            project_id=pid,
            code=spec.code,
            description=spec.description,
            source="manual",
            estimate_amount=str(spec.estimate),
            currency=CURRENCY,
            metadata_={"demo_id": DEMO_ID},
        )
        session.add(line)
        lines[spec.code] = line
    await session.flush()
    for spec in LINES:
        session.add(
            BudgetLine(
                project_id=pid,
                cost_line_id=lines[spec.code].id,
                category="subcontractor",
                description=f"KG {spec.code} {spec.description}",
                planned_amount=str(spec.budget),
                currency=CURRENCY,
            )
        )
    await session.flush()

    # ── Subcontracts, approved changes and paid claims ────────────────────
    contracts: dict[str, Contract] = {}
    for spec in CONTRACTS:
        contract = Contract(
            project_id=pid,
            code=spec.code,
            title=spec.title,
            contract_type="lump_sum",
            counterparty_type="subcontractor",
            total_value=spec.awarded,
            original_contract_value=spec.awarded,
            currency=CURRENCY,
            retention_percent=RETENTION_PCT,
            # Posting a change needs a live contract; a completed one is closed after its changes.
            status="active",
            signed_at=spec.signed_on.isoformat(),
            start_date=spec.signed_on.isoformat(),
            created_by=owner,
            metadata_={"demo_id": DEMO_ID},
        )
        session.add(contract)
        await session.flush()
        contracts[spec.code] = contract
        original = ContractLine(
            contract_id=contract.id,
            code="01",
            description=spec.line_description,
            quantity=D("1"),
            unit_rate=spec.awarded,
            total_value=spec.awarded,
            original_value=spec.awarded,
            origin="original",
            cost_line_id=lines[spec.line_code].id,
        )
        session.add(original)
        await session.flush()

        claim_lines: list[tuple[uuid.UUID, Decimal]] = []
        if spec.certified_original > ZERO:
            claim_lines.append((original.id, spec.certified_original))

        if spec.change is not None:
            order = ChangeOrder(
                project_id=pid,
                code=spec.change.code,
                title=spec.change.title,
                description="",
                reason_category=spec.change.reason,
                status="approved",
                cost_impact=spec.change.amount,
                contractor_amount=spec.change.amount,
                approved_amount=spec.change.amount,
                currency=CURRENCY,
                approved_by=owner,
                approved_at=_at(spec.change.approved_on).isoformat()[:19],
                metadata_={"contract_id": str(contract.id), "demo_id": DEMO_ID},
            )
            session.add(order)
            await session.flush()
            await post_change_order_to_contract(session, contract, order, approved_on=spec.change.approved_on)
            if spec.certified_changes:
                change_line_ids = (
                    (
                        await session.execute(
                            select(ContractLine.id, ContractLine.total_value).where(
                                ContractLine.contract_id == contract.id, ContractLine.origin != "original"
                            )
                        )
                    )
                    .tuples()
                    .all()
                )
                claim_lines.extend((cl_id, D(str(value))) for cl_id, value in change_line_ids)

        if claim_lines and spec.claim_paid_on is not None:
            certified = sum((value for _, value in claim_lines), ZERO)
            held = _retention(certified)
            claim = ProgressClaim(
                contract_id=contract.id,
                claim_number=spec.claim_number,
                status="paid",
                currency=CURRENCY,
                claim_date=spec.claim_paid_on.isoformat(),
                paid_at=_at(spec.claim_paid_on).isoformat()[:19],
                gross_amount=certified,
                retention_amount=held,
                net_due=certified - held,
                completed_stored_to_date=certified,
                retention_held_to_date=held,
                application_date=spec.claim_paid_on,
                period_to=spec.claim_paid_on,
                metadata_={"demo_id": DEMO_ID},
            )
            session.add(claim)
            await session.flush()
            for contract_line_id, value in claim_lines:
                session.add(
                    ProgressClaimLine(
                        progress_claim_id=claim.id,
                        contract_line_id=contract_line_id,
                        cumulative_completed_value=value,
                    )
                )
            await session.flush()

        if spec.status != "active":
            contract.status = spec.status
            await session.flush()

    # ── The change order waiting for a decision ───────────────────────────
    # No submitter is recorded, so whoever films the approval is not refused by
    # the four-eyes check.
    session.add(
        ChangeOrder(
            project_id=pid,
            code=PENDING_CHANGE.code,
            title=PENDING_CHANGE.title,
            description="",
            reason_category=PENDING_CHANGE.reason,
            status="submitted",
            cost_impact=PENDING_CHANGE.amount,
            contractor_amount=PENDING_CHANGE.amount,
            currency=CURRENCY,
            submitted_at=_at(PENDING_CHANGE.approved_on).isoformat()[:19],
            contractor_submission_date=PENDING_CHANGE.approved_on.isoformat(),
            metadata_={"contract_id": str(contracts[PENDING_CHANGE_CONTRACT].id), "demo_id": DEMO_ID},
        )
    )
    await session.flush()

    # ── The issued order on no cost line ──────────────────────────────────
    amount = ORDER_QUANTITY * ORDER_RATE
    po = PurchaseOrder(
        project_id=pid,
        po_number=ORDER_NUMBER,
        po_type="standard",
        status="issued",
        issue_date=ORDER_ISSUED_ON.isoformat(),
        currency_code=CURRENCY,
        amount_subtotal=str(amount),
        amount_total=str(amount),
        created_by=owner_id,
    )
    po.metadata_ = {"demo_id": DEMO_ID}
    session.add(po)
    await session.flush()
    session.add(
        PurchaseOrderItem(
            po_id=po.id,
            description=ORDER_ITEM,
            quantity=str(ORDER_QUANTITY),
            unit=ORDER_UNIT,
            unit_rate=str(ORDER_RATE),
            amount=str(amount),
            cost_line_id=None,
        )
    )
    await session.flush()

    # ── Saved forecasts on past dates ─────────────────────────────────────
    # Each one is written as a draft with the reasons behind its moves, then frozen, the way a
    # month is closed in the product: a frozen snapshot takes no notes any more.
    line_ids = {code: line.id for code, line in lines.items()}
    previous_id: uuid.UUID | None = None
    for spec in SNAPSHOTS:
        totals, rows = _snapshot_payload(spec, line_ids)
        snap = CostForecastSnapshot(
            id=uuid.uuid4(),
            project_id=pid,
            taken_on=spec.taken_on.isoformat(),
            stage=spec.stage,
            label=spec.label,
            note=spec.note,
            currency=CURRENCY,
            totals=totals,
            rows=rows,
            created_by=owner,
            status="draft",
            previous_snapshot_id=previous_id,
            meta={"forecast_method": "best_available", "threshold_amount": "0", "threshold_pct": "10"},
        )
        snap.created_at = _at(spec.taken_on)
        session.add(snap)
        await session.flush()
        for (day, code), (comment, evidence) in SNAPSHOT_NOTES.items():
            if day == spec.taken_on:
                session.add(
                    CostForecastSnapshotNote(
                        snapshot_id=snap.id,
                        row_key=str(line_ids[code]),
                        comment=comment,
                        evidence=evidence,
                        updated_by=owner,
                    )
                )
        await session.flush()
        snap.status = "frozen"
        snap.frozen_at = _at(spec.taken_on)
        snap.frozen_by = owner
        await session.flush()
        previous_id = snap.id
    return pid
