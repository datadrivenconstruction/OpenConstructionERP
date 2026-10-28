# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An escalation that cannot be resolved never reaches the cascade.

The failure this pins used to work like this: a markup line named a cost-index
series, the series had been deleted or was missing one of the two months, the
lookup logged a warning and returned nothing, and the cascade then priced the
line at zero. The bill came out with a grand total that looked finished and was
short by the whole escalation. Nothing on the screen and nothing in the number
said so.

So resolution happens before the cascade and fails there. Where somebody is
committing to a figure it refuses, naming the series and both periods. Where it
cannot refuse, the multi-bill totals rollup and the markups list endpoint, the
unresolved lines are kept out of the stack and the total is flagged as
incomplete. Zero is never the answer.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.boq.models import BOQMarkup
from app.modules.boq.service import (
    BOQService,
    EscalationResolution,
    _calculate_markup_amounts,
    _escalation_unresolved_detail,
    _without_unresolved_escalation,
)

_SERIES = uuid.UUID("00000000-0000-4000-8000-0000000000aa")


def _markup(
    *,
    name: str,
    markup_type: str = "percentage",
    percentage: str = "0",
    apply_to: str = "direct_cost",
    sort_order: int = 0,
    metadata: dict | None = None,
) -> BOQMarkup:
    markup = BOQMarkup(
        name=name,
        markup_type=markup_type,
        category="other",
        percentage=percentage,
        fixed_amount="0",
        apply_to=apply_to,
        sort_order=sort_order,
        is_active=True,
        metadata_=metadata or {},
    )
    markup.id = uuid.uuid4()
    return markup


def test_the_reason_names_the_series_and_both_periods() -> None:
    """A reason a reader cannot act on is not a reason.

    Whether the series was deleted or one month is missing from it decides what
    the estimator does next, and neither is visible from the markup row, so both
    periods and the series identity have to travel with the failure.
    """
    detail = _escalation_unresolved_detail(_SERIES, "2024-01", "2026-06", "period 2026-06 not in series")

    assert str(_SERIES) in detail
    assert "2024-01" in detail
    assert "2026-06" in detail
    assert "period 2026-06 not in series" in detail


def test_an_unresolved_line_is_removed_rather_than_priced_at_nothing() -> None:
    """The rollup path obeys the rule by dropping, not by zeroing."""
    good = _markup(name="Overhead", percentage="10", sort_order=0)
    bad = _markup(
        name="Escalation",
        markup_type="escalation",
        sort_order=1,
        metadata={"escalation": {"series_id": str(_SERIES), "base_period": "2024-01", "target_period": "2026-06"}},
    )
    stack = [good, bad]

    kept = _without_unresolved_escalation(stack, {bad.id: "no such series"})

    assert kept == [good]
    # Nothing unresolved must not allocate a new list; the rollup runs this on
    # every bill it prices and the common case is that everything resolved.
    assert _without_unresolved_escalation(stack, {}) is stack


def test_dropping_the_line_and_zeroing_it_are_the_same_money_and_different_claims() -> None:
    """Why the drop is worth doing even though the total does not move.

    A dropped line and a line priced at zero cost the same. The difference is
    what the stack says afterwards: one never contained an escalation, the other
    contains an escalation that came to nothing, and only the second can be read
    later as a fact about the index.
    """
    overhead = _markup(name="Overhead", percentage="10", sort_order=0)
    escalation = _markup(
        name="Escalation",
        markup_type="escalation",
        sort_order=1,
        metadata={"escalation": {"series_id": str(_SERIES), "base_period": "2024-01", "target_period": "2026-06"}},
    )
    vat = _markup(name="VAT", percentage="20", apply_to="cumulative", sort_order=2)
    direct = Decimal("1000")

    with_zeroed = _calculate_markup_amounts(direct, [overhead, escalation, vat], {})
    with_dropped = _calculate_markup_amounts(direct, [overhead, vat], {})

    assert sum(a for _, a in with_zeroed) == sum(a for _, a in with_dropped) == Decimal("320")
    assert [m.name for m, _ in with_dropped] == ["Overhead", "VAT"]


def test_a_resolved_factor_prices_the_increase_not_the_base_again() -> None:
    """The line IS the increase, so the factor arrives as ``factor - 1``."""
    escalation = _markup(
        name="Escalation",
        markup_type="escalation",
        sort_order=0,
        metadata={"escalation": {"series_id": str(_SERIES), "base_period": "2024-01", "target_period": "2026-06"}},
    )

    results = _calculate_markup_amounts(Decimal("1000"), [escalation], {escalation.id: Decimal("1.075")})

    assert results[0][1] == Decimal("75.000")


@pytest.mark.asyncio
async def test_a_line_that_names_no_series_refuses_instead_of_pricing() -> None:
    """Strict mode is the default, and it refuses before the cascade runs.

    A legacy row saved before the shape validator existed can still name no
    series. It used to be skipped, which priced it at zero inside a total that
    read as final. It now raises, and the body names what is missing.
    """
    orphan = _markup(
        name="Escalation",
        markup_type="escalation",
        sort_order=0,
        metadata={"escalation": {"base_period": "", "target_period": ""}},
    )
    service = BOQService.__new__(BOQService)
    service.session = None  # type: ignore[attr-defined]

    with pytest.raises(HTTPException) as exc:
        await service._resolve_escalation_factors([orphan])

    assert exc.value.status_code == 409
    assert "no series or period pair" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_the_same_line_reports_instead_of_refusing_when_it_must_not_fail() -> None:
    """The rollup and the editor get a reason back, not an exception."""
    orphan = _markup(
        name="Escalation",
        markup_type="escalation",
        sort_order=0,
        metadata={"escalation": {"base_period": "", "target_period": ""}},
    )
    service = BOQService.__new__(BOQService)
    service.session = None  # type: ignore[attr-defined]

    resolution = await service._resolve_escalation_factors([orphan], strict=False)

    assert isinstance(resolution, EscalationResolution)
    assert resolution.factors == {}
    assert list(resolution.unresolved) == [orphan.id]


@pytest.mark.asyncio
async def test_an_inactive_or_ordinary_line_is_not_an_escalation_to_resolve() -> None:
    """Only active escalation rows are looked up, so nothing else can refuse."""
    ordinary = _markup(name="Overhead", percentage="10", sort_order=0)
    disabled = _markup(
        name="Escalation",
        markup_type="escalation",
        sort_order=1,
        metadata={"escalation": {"base_period": "", "target_period": ""}},
    )
    disabled.is_active = False
    service = BOQService.__new__(BOQService)
    service.session = None  # type: ignore[attr-defined]

    resolution = await service._resolve_escalation_factors([ordinary, disabled])

    assert resolution.factors == {}
    assert resolution.unresolved == {}
