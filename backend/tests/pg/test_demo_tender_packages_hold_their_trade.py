# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: a seeded tender package is what its name says, read by the screens that use it.

The office demo's "Innenausbau" package (drywall, raised floors, acoustic
ceilings, floor finishes, doors) used to cover the roof slab, the roof sealing,
the PV plant, the heating and the electrical distribution, and not the drywall
partition it was named for: the installer cut the bill into money-balanced
contiguous slices and handed them to the packages in order. Its deadline was a
fixed date months in the past, so a fresh demo showed the open package overdue.

This installs the demo into a real database and reads the package back through
the comparison the estimator opens (``compare_bids``), because the scope only
matters where a screen reads it: the budget side of the comparison is the
package's declared scope, and a scope of the wrong trade shows as a bid wildly
off a budget nobody tendered.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.demo_projects import install_demo_project
from app.modules.boq.models import Position
from app.modules.tendering.models import TenderBid, TenderPackage
from app.modules.tendering.service import TenderingService

pytestmark = pytest.mark.asyncio

_DEMO_ID = "office-frankfurt"


async def _installed(session) -> tuple[dict[str, Position], list[TenderPackage]]:
    result = await install_demo_project(session, _DEMO_ID)
    await session.flush()
    project_id = uuid.UUID(str(result["project_id"]))
    packages = (
        (await session.execute(select(TenderPackage).where(TenderPackage.project_id == project_id))).scalars().all()
    )
    boq_id = packages[0].boq_id
    positions = (await session.execute(select(Position).where(Position.boq_id == boq_id))).scalars().all()
    return {p.ordinal: p for p in positions}, list(packages)


async def test_the_fit_out_package_holds_the_drywall_and_not_the_roof(pg_session) -> None:
    by_ordinal, packages = await _installed(pg_session)
    fit_out = next(p for p in packages if p.name == "Innenausbau")
    scope = set(fit_out.metadata_["scope_position_ids"])

    assert str(by_ordinal["340.4"].id) in scope, "the drywall partition is not in the fit-out package"
    assert str(by_ordinal["350.12"].id) in scope, "the plasterboard ceiling is not in the fit-out package"
    for ordinal in ("340.1", "350.1", "360.1", "360.3", "420.1", "440.1"):
        assert str(by_ordinal[ordinal].id) not in scope, f"{ordinal} is not interior fit-out"
    shell = next(p for p in packages if p.name == "Rohbau")
    assert str(by_ordinal["340.1"].id) in set(shell.metadata_["scope_position_ids"])


async def test_the_comparison_budgets_the_package_against_its_own_lines(pg_session) -> None:
    """The consumer: the budget the bids are compared with is the fit-out scope."""
    by_ordinal, packages = await _installed(pg_session)
    fit_out = next(p for p in packages if p.name == "Innenausbau")
    scope = set(fit_out.metadata_["scope_position_ids"])
    scope_value = sum(
        (Decimal(str(p.quantity)) * Decimal(str(p.unit_rate)) for p in by_ordinal.values() if str(p.id) in scope),
        Decimal("0"),
    )

    result = await TenderingService(pg_session).compare_bids(fit_out.id)

    assert Decimal(str(result.budget_total)) == scope_value.quantize(Decimal("0.01"))
    bids = (await pg_session.execute(select(TenderBid).where(TenderBid.package_id == fit_out.id))).scalars().all()
    assert bids
    for bid in bids:
        total = Decimal(str(bid.total_amount))
        # Priced off the package's own scope, so every bid sits within a few
        # per cent of the budget it is compared with, not several times it.
        assert abs(total / scope_value - 1) < Decimal("0.10"), f"{bid.company_name} {total} vs scope {scope_value}"
        lines = sum((Decimal(str(line["total"])) for line in bid.line_items), Decimal("0"))
        assert abs(lines - total) <= Decimal("1.00"), f"{bid.company_name}: lines {lines} vs total {total}"


async def test_an_open_package_has_a_deadline_ahead_and_bids_before_it(pg_session) -> None:
    _by_ordinal, packages = await _installed(pg_session)
    today = datetime.now(UTC).date()
    open_packages = [p for p in packages if p.status in {"draft", "issued", "collecting"}]
    assert open_packages, "a fresh demo shows no package still open for bids"
    for package in packages:
        deadline = date.fromisoformat(package.deadline)
        if package.status in {"draft", "issued", "collecting"}:
            assert deadline > today, f"{package.name} is {package.status} with a deadline already passed"
        else:
            assert deadline <= today, f"{package.name} is {package.status} before its deadline"
        bids = (await pg_session.execute(select(TenderBid).where(TenderBid.package_id == package.id))).scalars().all()
        for bid in bids:
            submitted = datetime.fromisoformat(bid.submitted_at).date()
            assert submitted <= deadline, f"{bid.company_name} submitted after the {package.name} deadline"
            assert submitted <= today, f"{bid.company_name} submitted in the future"


async def test_the_fit_out_package_is_out_with_a_firm_yet_to_quote(pg_session) -> None:
    """The consumer: the recipients list the distribution panel reads, against the bids that came in."""
    _by_ordinal, packages = await _installed(pg_session)
    service = TenderingService(pg_session)
    for package in packages:
        bids = (await pg_session.execute(select(TenderBid).where(TenderBid.package_id == package.id))).scalars().all()
        assert not (bids and package.status == "draft"), f"{package.name} is a draft holding {len(bids)} bids"

    fit_out = next(p for p in packages if p.name == "Innenausbau")
    assert fit_out.status == "collecting"
    recipients = await service.list_recipients(fit_out.id)
    bids = (await pg_session.execute(select(TenderBid).where(TenderBid.package_id == fit_out.id))).scalars().all()
    quoted = {b.contact_email.lower() for b in bids}
    invited = {r.email.lower() for r in recipients}
    assert quoted <= invited, "a firm quoted without being invited"
    waiting = [r for r in recipients if r.email.lower() not in quoted]
    assert waiting, "no invited firm is still to quote on the open package"
    assert all(r.status == "sent" and r.sent_at for r in recipients)
    issued = datetime.fromisoformat(fit_out.metadata_["issued_at"])
    assert all(datetime.fromisoformat(b.submitted_at) > issued for b in bids), "a bid arrived before the invitation"
