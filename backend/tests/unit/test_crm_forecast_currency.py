# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠crm: the forecast's currency breakdown survives being stored.

``compute_forecast`` has always returned ``by_currency`` and
``mixed_currency`` alongside its four scalars. They were computed correctly
and then dropped on the way to the ``Forecast`` row, and ``ForecastResponse``
declared defaults - ``[]`` and ``False`` - that filled the gap back in. The
result was not an error anywhere: ``GET /forecasts/{period}`` and
``POST /forecasts/compute`` answered ``mixed_currency: false`` on every call,
for every period, whatever the deals said.

The control is in the same module and gets it right
---------------------------------------------------
``GET /pipeline/metrics`` publishes the same two fields off the same helper
family, and ``PipelineMetricsResponse`` declares the *same* permissive
defaults. It has never been wrong, because it computes and constructs in one
breath with every field passed explicitly, so its defaults are never reached.

Two endpoints do reach them, by different routes. The forecast computes,
stores, and validates back off a row that had nowhere to keep the two fields.
``GET /crm/dashboard`` has no storage hop at all and simply passed seven of ten
arguments, so the remaining three came from the defaults on every call.

So the defaults are not the difference and the computation is not the
difference. Anything standing between the computation and the response is,
whether that is a missing column or a missing argument, and that is what these
tests hold in place: the control's correctness (which must not quietly become
the fix), both carry-throughs, and the refusal to manufacture an answer for a
row that was never checked.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.crm.schemas import ForecastResponse, PipelineMetricsResponse
from app.modules.crm.service import (
    CrmService,
    compute_forecast,
    compute_pipeline_metrics,
)

_PERIOD = "2026-Q2"


def _opp(value: str, currency: str, *, status: str = "open", prob: int = 50) -> SimpleNamespace:
    """One open deal closing inside 2026-Q2, carrying its own ISO currency."""
    return SimpleNamespace(
        status=status,
        estimated_value=Decimal(value),
        weighted_value=Decimal(value) * Decimal(prob) / Decimal(100),
        probability_percent=prob,
        currency=currency,
        expected_close_date="2026-05-15",
        won_at=None,
        lost_at=None,
        stage_id=uuid.uuid4(),
        owner_user_id=None,
    )


# ── The control ──────────────────────────────────────────────────────────


def test_pipeline_metrics_is_the_control_and_its_defaults_are_the_permissive_ones() -> None:
    """Same two fields, same forgiving defaults, no defect - because nothing is stored.

    Both halves are asserted on purpose. That the route answers correctly is
    only interesting once you know its schema would have let it answer
    ``False``; and that the schema is permissive is only interesting once you
    know the route is right anyway. Together they say the storage hop is the
    whole difference between this endpoint and the forecast one.

    If this test ever fails because ``PipelineMetricsResponse`` stopped
    defaulting to ``[]`` / ``False``, nothing is broken - but the control has
    changed, and the reasoning recorded above needs rereading before it is
    quoted again.
    """
    fields = PipelineMetricsResponse.model_fields
    assert fields["mixed_currency"].default is False
    assert fields["by_currency"].default_factory is not None
    assert fields["by_currency"].default_factory() == []

    metrics = compute_pipeline_metrics([_opp("1000", "EUR"), _opp("2000", "USD")])

    # Constructed the way router.py builds it: every field passed explicitly,
    # so not one of the defaults above is ever consulted.
    response = PipelineMetricsResponse(
        open_count=metrics["open_count"],
        weighted_value=metrics["weighted_value"],
        total_value=metrics["total_value"],
        by_stage=metrics["by_stage"],
        win_rate_30d=metrics["win_rate_30d"],
        by_currency=metrics["by_currency"],
        weighted_by_currency=metrics["weighted_by_currency"],
        mixed_currency=metrics["mixed_currency"],
    )
    assert response.mixed_currency is True
    assert {row.currency for row in response.by_currency} == {"EUR", "USD"}


# ── The computation was never the problem ────────────────────────────────


def test_compute_forecast_already_reports_the_blend() -> None:
    """The pure function was right the whole time; only the snapshot lost it."""
    computed = compute_forecast([_opp("1000", "EUR"), _opp("2000", "USD")], _PERIOD)

    assert computed["mixed_currency"] is True
    assert computed["by_currency"] == [
        {"currency": "EUR", "total": Decimal("1000.00")},
        {"currency": "USD", "total": Decimal("2000.00")},
    ]
    # And the scalar it warns about really is the meaningless blend.
    assert computed["pipeline_value"] == Decimal("3000.00")


# ── The carry-through ────────────────────────────────────────────────────


class _CapturingForecastRepo:
    """Returns whatever it was handed, so the assertions read the service's own work.

    Deliberately not a re-implementation of ``ForecastRepository``: the field
    copying inside the real ``upsert`` is a second drop site and is exercised
    against a real session in the PG lane. This one stands in for storage only
    so the object the service *built* can be inspected.
    """

    def __init__(self) -> None:
        self.upserted: list[Any] = []

    async def get_by_period(self, period: str, owner_user_id: uuid.UUID | None = None) -> Any:
        return None

    async def upsert(self, forecast: Any) -> Any:
        self.upserted.append(forecast)
        return forecast


class _StaticOpportunityRepo:
    """A page of rows, whatever filters the caller asks for.

    ``**_filters`` rather than a named signature because three different repos
    are stood in for here and each is called with a different keyword set
    (``owner_user_id``, ``due_before``); the filtering is not what any of these
    tests are about.
    """

    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    async def list_all(self, limit: int = 100, **_filters: Any) -> tuple[list[Any], int]:
        return self.rows, len(self.rows)


def _service(rows: list[Any]) -> tuple[CrmService, _CapturingForecastRepo]:
    service = CrmService.__new__(CrmService)
    repo = _CapturingForecastRepo()
    service.opportunity_repo = _StaticOpportunityRepo(rows)  # type: ignore[assignment]
    service.forecast_repo = repo  # type: ignore[assignment]
    return service, repo


@pytest.mark.asyncio
async def test_stored_forecast_keeps_the_breakdown_and_the_warning() -> None:
    """Three currencies in, three currencies onto the row, and the flag set."""
    service, repo = _service([_opp("1000", "EUR"), _opp("2000", "USD"), _opp("500", "GBP")])

    stored = await service.compute_and_store_forecast(_PERIOD)

    assert stored.mixed_currency is True
    # Money as a JSON string, per the module convention for JSON columns.
    assert stored.by_currency == [
        {"currency": "EUR", "total": "1000.00"},
        {"currency": "GBP", "total": "500.00"},
        {"currency": "USD", "total": "2000.00"},
    ]
    assert repo.upserted == [stored]


@pytest.mark.asyncio
async def test_the_response_reads_the_warning_off_the_stored_row() -> None:
    """The endpoint's own path: validate the ORM row, do not rebuild from the computation.

    This is the assertion the defect fails. Before the columns existed the
    row could not carry either field, ``model_validate`` fell through to the
    schema defaults, and this came back ``False`` with an empty breakdown
    while the deals underneath were EUR and USD.
    """
    service, _ = _service([_opp("1000", "EUR"), _opp("2000", "USD")])
    stored = await service.compute_and_store_forecast(_PERIOD)
    stored.id = uuid.uuid4()
    stored.created_at = stored.updated_at = datetime.now(UTC)

    response = ForecastResponse.model_validate(stored)

    assert response.mixed_currency is True
    assert [(row.currency, row.total) for row in response.by_currency] == [
        ("EUR", Decimal("1000.00")),
        ("USD", Decimal("2000.00")),
    ]


@pytest.mark.asyncio
async def test_one_currency_is_reported_as_one_currency() -> None:
    """The flag is a warning, not a label - a single-currency period is not mixed.

    Without this the fix could be a constant ``True`` and every other
    assertion here would still pass.
    """
    service, _ = _service([_opp("1000", "EUR"), _opp("2000", "EUR")])

    stored = await service.compute_and_store_forecast(_PERIOD)

    assert stored.mixed_currency is False
    assert stored.by_currency == [{"currency": "EUR", "total": "3000.00"}]


# ── The refusal to manufacture an answer ─────────────────────────────────


def test_a_row_that_predates_the_columns_reads_as_unchecked_not_as_unmixed() -> None:
    """``None`` means nobody looked. ``False`` would mean somebody looked and it was fine.

    Rows written before this change carry NULL in both columns and there is no
    backfill, because recomputing a snapshot dated months ago would run
    today's opportunities into it. So the API has to be able to say "not
    checked", and the only way it can is for the defaults to be absent.
    """
    aged = SimpleNamespace(
        id=uuid.uuid4(),
        period=_PERIOD,
        owner_user_id=None,
        pipeline_value=Decimal("3000.00"),
        weighted_value=Decimal("1500.00"),
        won_value=Decimal("0.00"),
        committed_value=Decimal("0.00"),
        computed_at="2026-04-01T00:00:00+00:00",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        by_currency=None,
        mixed_currency=None,
    )

    response = ForecastResponse.model_validate(aged)

    assert response.mixed_currency is None
    assert response.by_currency is None


@pytest.mark.asyncio
async def test_the_dashboard_publishes_the_breakdown_it_computes() -> None:
    """The same family without the storage hop: three kwargs simply left off.

    ``compute_pipeline_metrics`` has always returned the breakdown and the
    flag, and ``crm_dashboard`` passed seven of the ten fields, so the other
    three came from ``CrmDashboardResponse``'s defaults on every call. The
    Insights tab reads ``by_currency`` and falls back to the blended scalar
    "only when absent", so it took the fallback every time.

    The route is called rather than reconstructed here on purpose. Rebuilding
    the response from the same kwargs the router uses would assert that this
    test can pass ten arguments, which is not the thing that was broken.
    """
    from app.modules.crm.router import crm_dashboard

    service = SimpleNamespace(
        opportunity_repo=_StaticOpportunityRepo([_opp("1000", "EUR"), _opp("2000", "USD")]),
        lead_repo=_StaticOpportunityRepo([]),
        activity_repo=_StaticOpportunityRepo([]),
    )

    dashboard = await crm_dashboard(owner_user_id=None, _perm=None, service=service)

    assert dashboard.mixed_currency is True
    assert [(row.currency, row.total) for row in dashboard.by_currency] == [
        ("EUR", Decimal("1000.00")),
        ("USD", Decimal("2000.00")),
    ]
    assert [row.currency for row in dashboard.weighted_by_currency] == ["EUR", "USD"]
    # And the blended scalar it warns about is still published, still blended.
    assert dashboard.pipeline_value == Decimal("3000.00")


def test_forecast_response_declares_no_default_that_could_answer_for_it() -> None:
    """Pins the mechanism, which every assertion above is blind to.

    Re-adding ``= []`` and ``= False`` here is a one-character-per-field
    convenience that makes ``model_validate`` over an incomplete row keep
    working, and it is exactly how the defect was introduced. Every other test
    in this file would stay green, because they all feed rows that carry real
    values. This is the one that would not.
    """
    fields = ForecastResponse.model_fields
    for name in ("by_currency", "mixed_currency"):
        assert fields[name].default is None, (
            f"ForecastResponse.{name} has a default again. A default here does not "
            "make the API more convenient, it makes it answer for a row nobody checked."
        )
        assert fields[name].default_factory is None
