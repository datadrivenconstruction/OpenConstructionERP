# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the FX service (PostgreSQL).

The network is stubbed at the transport method (``_fetch_ecb_xml`` /
``_fetch_ppp``) and never above it, so the XML parsing, the upsert, the
provenance columns and the legacy-cache mirror are all genuinely exercised
while no socket is ever opened. Anything that would otherwise probe the feed
passes ``probe_network=False``.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fx import repository as repo
from app.modules.fx.service import (
    ORIGIN_LEGACY_CACHE,
    ORIGIN_RATE_SET,
    ORIGIN_SEED,
    FxService,
    RateSetUnavailableError,
    RevaluationLine,
    UnknownCurrencyError,
)
from tests.modules.fx.conftest import ECB_XML, make_policy, make_rate_set

MARCH_1 = date(2026, 3, 1)
MARCH_15 = date(2026, 3, 15)


def _stub_feed(monkeypatch: pytest.MonkeyPatch, xml: str = ECB_XML) -> None:
    """Answer the ECB fetch with a fixed document, leaving parsing to the code."""

    async def _fake(_self: FxService) -> bytes:
        return xml.encode("utf-8")

    monkeypatch.setattr(FxService, "_fetch_ecb_xml", _fake)


def _stub_feed_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the ECB fetch fail the way an unreachable host does."""

    async def _fake(_self: FxService) -> bytes:
        raise httpx.ConnectError("stubbed: the feed is unreachable")

    monkeypatch.setattr(FxService, "_fetch_ecb_xml", _fake)


# ── Refresh ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_stores_a_rate_set_with_its_provenance(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_feed(monkeypatch)
    service = FxService(session)

    result = await service.refresh()

    assert result["network_ok"] is True
    assert result["updated"] == 3
    assert result["as_of"] == date(2026, 3, 2)

    stored = await repo.latest_rate_set(session)
    assert stored is not None
    assert stored.source == "ecb"
    assert stored.source_ref.endswith("eurofxref-daily.xml")
    assert stored.fetched_at is not None
    assert repo.quotes_as_map(stored)["TRY"] == Decimal("42.5")


@pytest.mark.asyncio
async def test_refresh_also_mirrors_the_legacy_cache(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """The register and the compatibility cache are written together, never apart."""
    _stub_feed(monkeypatch)
    await FxService(session).refresh()

    rows = await repo.list_latest_rates(session)
    assert {row.currency for row in rows} == {"USD", "TRY", "CNY"}
    assert all(row.rate_date == date(2026, 3, 2) for row in rows)


@pytest.mark.asyncio
async def test_refreshing_twice_replaces_rather_than_accumulates(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_feed(monkeypatch)
    service = FxService(session)
    await service.refresh()
    await service.refresh()

    assert await repo.count_rate_sets(session) == 1


@pytest.mark.asyncio
async def test_refresh_offline_seeds_an_empty_register(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_feed_offline(monkeypatch)

    result = await FxService(session).refresh()

    assert result["network_ok"] is False
    assert result["source"] == "seed"
    assert result["updated"] > 0
    stored = await repo.latest_rate_set(session)
    assert stored is not None
    assert stored.source == "seed"


@pytest.mark.asyncio
async def test_refresh_offline_never_overwrites_live_rates(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_feed(monkeypatch)
    service = FxService(session)
    await service.refresh()

    _stub_feed_offline(monkeypatch)
    result = await service.refresh()

    assert result["updated"] == 0
    assert "Kept the existing rates" in str(result["note"])
    latest = await repo.latest_rate_set(session)
    assert latest is not None
    assert latest.source == "ecb"


@pytest.mark.asyncio
async def test_refresh_offline_leaves_a_legacy_only_installation_alone(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An upgraded install has rates only in the legacy cache; seeding would outrank them."""
    await repo.upsert_latest_rates(session, {"USD": Decimal("1.08")}, MARCH_1, source="ecb")
    _stub_feed_offline(monkeypatch)

    result = await FxService(session).refresh()

    assert result["updated"] == 0
    assert await repo.count_rate_sets(session) == 0


# ── Resolution order ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolution_prefers_the_register(session: AsyncSession) -> None:
    await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.08"})
    await repo.upsert_latest_rates(session, {"USD": Decimal("9.99")}, MARCH_1, source="ecb")

    resolved = await FxService(session).resolve_rates()
    assert resolved.origin == ORIGIN_RATE_SET
    assert resolved.rates["USD"] == Decimal("1.08")


@pytest.mark.asyncio
async def test_resolution_falls_back_to_the_legacy_cache(session: AsyncSession) -> None:
    await repo.upsert_latest_rates(session, {"USD": Decimal("1.08")}, MARCH_1, source="ecb")

    resolved = await FxService(session).resolve_rates()
    assert resolved.origin == ORIGIN_LEGACY_CACHE
    assert resolved.rates["USD"] == Decimal("1.080000")
    assert resolved.as_of == MARCH_1


@pytest.mark.asyncio
async def test_resolution_falls_back_to_the_bundled_seed(session: AsyncSession) -> None:
    resolved = await FxService(session).resolve_rates()
    assert resolved.origin == ORIGIN_SEED
    assert "VND" in resolved.rates


@pytest.mark.asyncio
async def test_resolution_says_so_when_it_cannot_cover_the_date_asked_for(session: AsyncSession) -> None:
    """Silently applying later rates to an earlier date is the failure mode to avoid."""
    resolved = await FxService(session).resolve_rates(on_date=date(2001, 1, 1))
    assert resolved.covers_requested_date is False
    assert "No rate set is on file for 2001-01-01" in resolved.coverage_note()


@pytest.mark.asyncio
async def test_a_named_rate_set_that_does_not_exist_is_an_error_not_a_fallback(
    session: AsyncSession,
) -> None:
    with pytest.raises(RateSetUnavailableError, match="does not exist"):
        await FxService(session).resolve_rates(rate_set_id=uuid.uuid4())


# ── Point-in-time conversion ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_conversion_uses_the_rates_that_applied_on_the_date(session: AsyncSession) -> None:
    await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7"})
    await make_rate_set(session, rate_date=MARCH_15, rates={"TRY": "44.3"})
    service = FxService(session)

    then = await service.convert("1000", "EUR", "TRY", on_date=date(2026, 3, 10))
    now = await service.convert("1000", "EUR", "TRY")

    assert then["converted"] == Decimal("38700.00")
    assert then["as_of"] == MARCH_1
    assert now["converted"] == Decimal("44300.00")
    assert now["as_of"] == MARCH_15


@pytest.mark.asyncio
async def test_conversion_reports_the_set_it_used(session: AsyncSession) -> None:
    rate_set = await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7"}, source_ref="bank quote 8812")

    result = await FxService(session).convert("1", "EUR", "TRY")
    assert result["rate_set_id"] == str(rate_set.id)
    assert result["source_ref"] == "bank quote 8812"
    assert result["origin"] == ORIGIN_RATE_SET


@pytest.mark.asyncio
async def test_conversion_rejects_a_currency_the_set_cannot_price(session: AsyncSession) -> None:
    await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7"})
    with pytest.raises(UnknownCurrencyError, match="ZWL"):
        await FxService(session).convert("1", "EUR", "ZWL")


@pytest.mark.asyncio
async def test_a_pinned_project_prices_at_its_pinned_set_not_at_todays(session: AsyncSession) -> None:
    """This is what pinning buys: a signed-off estimate reprices identically."""
    pinned = await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7"}, lock=True)
    await make_rate_set(session, rate_date=MARCH_15, rates={"TRY": "44.3"})
    policy = await make_policy(session, rate_mode="pinned", pinned_rate_set_id=pinned.id)

    result = await FxService(session).convert("1000", "EUR", "TRY", project_id=policy.project_id)
    assert result["converted"] == Decimal("38700.00")
    assert result["is_locked"] is True


@pytest.mark.asyncio
async def test_a_project_on_live_rates_tracks_the_newest_set(session: AsyncSession) -> None:
    await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7"})
    await make_rate_set(session, rate_date=MARCH_15, rates={"TRY": "44.3"})
    policy = await make_policy(session, rate_mode="live")

    result = await FxService(session).convert("1000", "EUR", "TRY", project_id=policy.project_id)
    assert result["converted"] == Decimal("44300.00")


@pytest.mark.asyncio
async def test_a_pin_with_no_set_configured_refuses_to_price(session: AsyncSession) -> None:
    policy = await make_policy(session, rate_mode="pinned", pinned_rate_set_id=None)
    with pytest.raises(RateSetUnavailableError, match="pinned"):
        await FxService(session).convert("1000", "EUR", "TRY", project_id=policy.project_id)


# ── Rate maps ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rates_can_be_rebased_onto_another_currency(session: AsyncSession) -> None:
    await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.10", "TRY": "44.0"})

    result = await FxService(session).get_rates("USD")
    rates = result["rates"]
    assert isinstance(rates, dict)
    # 1 USD buys 40 TRY, and 1 USD is 1/1.10 EUR.
    assert rates["TRY"] == Decimal("40.000000")
    assert rates["EUR"] == Decimal("0.909090909091")
    assert "USD" not in rates


@pytest.mark.asyncio
async def test_rebasing_onto_an_unquoted_currency_is_rejected(session: AsyncSession) -> None:
    await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.10"})
    with pytest.raises(UnknownCurrencyError, match="ZWL"):
        await FxService(session).get_rates("ZWL")


# ── Revaluation ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_revaluation_separates_the_rate_from_the_scope(session: AsyncSession) -> None:
    """The report an estimator is actually asked for: what moved, and why."""
    await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7", "USD": "1.07"})
    await make_rate_set(session, rate_date=MARCH_15, rates={"TRY": "44.3", "USD": "1.09"})

    result = await FxService(session).revalue(
        [
            # A subcontract in lira whose scope never changed.
            RevaluationLine(currency="TRY", baseline_amount=Decimal("1000000"), current_amount=Decimal("1000000")),
            # A dollar package that grew.
            RevaluationLine(currency="USD", baseline_amount=Decimal("500000"), current_amount=Decimal("600000")),
        ],
        reporting_currency="USD",
        baseline_date=MARCH_1,
        current_date=MARCH_15,
    )

    lines = result["lines"]
    assert isinstance(lines, list)
    lira, dollars = lines

    # The lira line lost value purely because the rate moved.
    assert lira["scope_delta"] == Decimal("0.00")
    assert lira["rate_delta"] < 0
    # The dollar line is reported in its own currency, so only scope moved.
    assert dollars["rate_delta"] == Decimal("0.00")
    assert dollars["scope_delta"] == Decimal("100000.00")

    for line in lines:
        assert line["scope_delta"] + line["rate_delta"] + line["joint_delta"] == line["total_delta"]

    assert result["scope_delta"] + result["rate_delta"] + result["joint_delta"] == result["total_delta"]
    assert result["baseline_value"] + result["total_delta"] == result["current_value"]
    assert result["priced_lines"] == 2
    assert result["unpriced_lines"] == 0


@pytest.mark.asyncio
async def test_revaluation_totals_are_the_sum_of_the_rows(session: AsyncSession) -> None:
    await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7", "USD": "1.07"})
    await make_rate_set(session, rate_date=MARCH_15, rates={"TRY": "44.3", "USD": "1.09"})

    result = await FxService(session).revalue(
        [
            RevaluationLine(
                currency="TRY", baseline_amount=Decimal("1234567.89"), current_amount=Decimal("1391011.13")
            ),
            RevaluationLine(currency="TRY", baseline_amount=Decimal("77777.77"), current_amount=Decimal("70000.07")),
            RevaluationLine(currency="USD", baseline_amount=Decimal("999999.99"), current_amount=Decimal("1000000.01")),
        ],
        reporting_currency="USD",
        baseline_date=MARCH_1,
        current_date=MARCH_15,
    )

    lines = result["lines"]
    assert isinstance(lines, list)
    for key in ("baseline_value", "current_value", "total_delta", "scope_delta", "rate_delta", "joint_delta"):
        assert result[key] == sum(line[key] for line in lines)


@pytest.mark.asyncio
async def test_one_exotic_currency_does_not_cost_the_estimator_the_other_lines(
    session: AsyncSession,
) -> None:
    await make_rate_set(session, rate_date=MARCH_1, rates={"USD": "1.07"})
    await make_rate_set(session, rate_date=MARCH_15, rates={"USD": "1.09"})

    result = await FxService(session).revalue(
        [
            RevaluationLine(currency="USD", baseline_amount=Decimal("1000"), current_amount=Decimal("1200"), ref="A"),
            RevaluationLine(currency="ZWL", baseline_amount=Decimal("1000"), current_amount=Decimal("1200"), ref="B"),
        ],
        reporting_currency="USD",
        baseline_date=MARCH_1,
        current_date=MARCH_15,
    )

    lines = result["lines"]
    assert isinstance(lines, list)
    assert result["priced_lines"] == 1
    assert result["unpriced_lines"] == 1
    assert lines[1]["available"] is False
    assert "ZWL" in str(lines[1]["note"])
    assert result["total_delta"] == Decimal("200.00")


# ── Policy ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_saving_a_pinned_policy_checks_the_set_exists(session: AsyncSession) -> None:
    with pytest.raises(RateSetUnavailableError):
        await FxService(session).save_policy(
            uuid.uuid4(),
            estimating_currency="EUR",
            procurement_currency="TRY",
            reporting_currency="USD",
            rate_mode="pinned",
            pinned_rate_set_id=uuid.uuid4(),
        )


@pytest.mark.asyncio
async def test_saving_a_pinned_policy_with_no_set_is_refused(session: AsyncSession) -> None:
    with pytest.raises(RateSetUnavailableError, match="must name"):
        await FxService(session).save_policy(
            uuid.uuid4(),
            estimating_currency="EUR",
            procurement_currency="TRY",
            reporting_currency="USD",
            rate_mode="pinned",
        )


@pytest.mark.asyncio
async def test_saving_a_policy_returns_the_pinned_set_summary(session: AsyncSession) -> None:
    rate_set = await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7"}, lock=True)
    project_id = uuid.uuid4()

    stored = await FxService(session).save_policy(
        project_id,
        estimating_currency="eur",
        procurement_currency="try",
        reporting_currency="usd",
        rate_mode="pinned",
        pinned_rate_set_id=rate_set.id,
    )

    assert stored["estimating_currency"] == "EUR"
    pinned = stored["pinned_rate_set"]
    assert isinstance(pinned, dict)
    assert pinned["is_locked"] is True
    assert pinned["quote_count"] == 1


@pytest.mark.asyncio
async def test_an_unknown_rate_mode_is_refused(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="Unknown rate mode"):
        await FxService(session).save_policy(
            uuid.uuid4(),
            estimating_currency="EUR",
            procurement_currency="EUR",
            reporting_currency="EUR",
            rate_mode="whenever",
        )


# ── Validation over real rows ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validation_flags_a_project_its_rates_cannot_price(session: AsyncSession) -> None:
    await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7"})
    policy = await make_policy(session, reporting_currency="USD", max_rate_age_days=3650)

    report = await FxService(session).validate_project(policy.project_id, on_date=date(2026, 3, 10))

    assert [row.rule_id for row in report.errors] == ["fx.policy_currency_coverage"]
    assert report.status.value == "errors"


@pytest.mark.asyncio
async def test_validation_is_clean_for_a_well_configured_project(session: AsyncSession) -> None:
    await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7", "USD": "1.07"})
    policy = await make_policy(session, reporting_currency="USD", max_rate_age_days=30)

    report = await FxService(session).validate_project(policy.project_id, on_date=date(2026, 3, 10))

    assert report.errors == []
    assert report.warnings == []


@pytest.mark.asyncio
async def test_validation_flags_a_pin_left_unlocked(session: AsyncSession) -> None:
    rate_set = await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7", "USD": "1.07"}, lock=False)
    policy = await make_policy(session, rate_mode="pinned", pinned_rate_set_id=rate_set.id)

    report = await FxService(session).validate_project(policy.project_id, on_date=date(2026, 3, 10))

    assert [row.rule_id for row in report.errors] == ["fx.pinned_set_resolvable"]


@pytest.mark.asyncio
async def test_validation_examines_the_rates_a_non_eur_project_is_priced_with(session: AsyncSession) -> None:
    """A project estimating outside EUR is checked, not quietly skipped.

    Every set in the register is quoted against EUR, so looking rates up by the
    project's own estimating currency would find nothing at all: each rule would
    take its "nothing to check" branch, the report would come back empty and the
    traffic light would go green on checks that never ran. Building the context
    from the same resolution pricing uses is what stops that.
    """
    await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7", "USD": "1.07"})
    policy = await make_policy(
        session,
        estimating_currency="TRY",
        procurement_currency="TRY",
        reporting_currency="GBP",
        max_rate_age_days=3650,
    )

    report = await FxService(session).validate_project(policy.project_id, on_date=date(2026, 3, 10))

    # Empty results are the failure this test exists for: SKIPPED, not PASSED.
    assert report.results != []
    assert report.status.value == "errors"
    coverage = [row for row in report.errors if row.rule_id == "fx.policy_currency_coverage"]
    assert [row.details["currency"] for row in coverage] == ["GBP"]


@pytest.mark.asyncio
async def test_validation_still_runs_before_the_register_is_ever_populated(session: AsyncSession) -> None:
    """With no set on file the seed prices the project, so the seed gets judged.

    A fresh installation converts against the bundled seed until someone
    refreshes. Those are real figures on real reports, and the age of them is
    exactly what an estimator needs told.
    """
    policy = await make_policy(session, reporting_currency="USD", max_rate_age_days=30)

    report = await FxService(session).validate_project(policy.project_id, on_date=date(2030, 1, 1))

    assert report.results != []
    assert [row.rule_id for row in report.warnings] == ["fx.rate_freshness"]
    assert report.errors == []


# ── Status ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_reports_the_register_without_touching_the_network(session: AsyncSession) -> None:
    await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7", "USD": "1.07"})
    await repo.upsert_latest_rates(session, {"TRY": Decimal("38.7")}, MARCH_1, source="ecb")

    status = await FxService(session).status(probe_network=False)

    assert status["network_ok"] is False
    assert status["rate_sets"] == 1
    assert status["cached_currencies"] == 1
    assert status["origin"] == ORIGIN_RATE_SET
    assert status["currencies"] == ["EUR", "TRY", "USD"]


# ── PPP ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ppp_conversion_caches_the_factor_with_its_currency(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def _fake_ppp(_self: FxService, iso3: str) -> tuple[Decimal, int] | None:
        calls.append(iso3)
        return {"DEU": (Decimal("0.75"), 2024), "TUR": (Decimal("12.5"), 2024)}.get(iso3)

    monkeypatch.setattr(FxService, "_fetch_ppp", _fake_ppp)
    service = FxService(session)

    result = await service.ppp_convert("100", "EUR", "TRY")

    assert result["available"] is True
    assert result["rate"] == Decimal("16.666667")
    assert result["converted"] == Decimal("1666.67")

    stored = await repo.get_ppp_factor(session, "TUR")
    assert stored is not None
    assert stored.currency == "TRY"

    # A second conversion answers from the cache rather than fetching again.
    await service.ppp_convert("100", "EUR", "TRY")
    assert calls == ["DEU", "TUR"]


@pytest.mark.asyncio
async def test_ppp_is_unavailable_rather_than_failing_for_an_unmapped_currency(
    session: AsyncSession,
) -> None:
    result = await FxService(session).convert("100", "EUR", "ZWL", mode="ppp")
    assert result["available"] is False
    assert "ZWL" in str(result["note"])
    assert result["converted"] is None
