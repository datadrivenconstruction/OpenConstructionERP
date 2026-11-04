# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid outcome ledger: price gap, hit rate by group and the bid_outcome rules."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.validation.engine import ValidationEngine, rule_registry
from app.core.validation.messages import is_key_present, translate
from app.core.validation.rules import register_builtin_rules
from app.modules.win_loss import validators as checks
from app.modules.win_loss.analytics import dominant_currency, price_gap, size_band, summarize
from app.modules.win_loss.schemas import BidOutcomeCreate


def _row(outcome: str, ours: str, **kw: object) -> SimpleNamespace:
    base = {
        "outcome": outcome,
        "our_price": Decimal(ours),
        "winning_price": None,
        "second_price": None,
        "competitor_count": None,
        "client_name": "Acme",
        "trade": "concrete",
        "currency": "EUR",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_a_won_bid_leaves_money_when_the_second_price_is_higher() -> None:
    gap = price_gap(_row("won", "900000", second_price=Decimal("990000")))
    assert (gap["left_on_table"], gap["left_on_table_pct"]) == (Decimal("90000.00"), Decimal("10.0"))
    assert gap["gap_to_winner"] is None


def test_a_lost_bid_measures_the_gap_to_the_winner() -> None:
    gap = price_gap(_row("lost", "1100", winning_price=Decimal("1000")))
    assert (gap["gap_to_winner"], gap["gap_to_winner_pct"]) == (Decimal("100.00"), Decimal("10.0"))
    assert gap["left_on_table"] is None


def test_no_gap_without_the_other_price() -> None:
    assert price_gap(_row("won", "100")) == price_gap(_row("pending", "100"))
    assert price_gap(_row("lost", "100"))["gap_to_winner"] is None


def test_size_bands_follow_the_own_price() -> None:
    assert [size_band(x) for x in ("99999", "100000", "999999", "10000000")] == [
        "small",
        "medium",
        "medium",
        "major",
    ]


def test_hit_rate_counts_decided_bids_only() -> None:
    rows = [
        _row("won", "100", second_price=Decimal("110"), competitor_count=3),
        _row("lost", "200", winning_price=Decimal("180"), competitor_count=5),
        _row("lost", "300", winning_price=Decimal("270"), client_name="Beta", trade="steel"),
        _row("pending", "400"),
        _row("withdrawn", "500"),
    ]
    s = summarize(rows)
    assert (s["submitted"], s["won"], s["lost"], s["open"]) == (5, 1, 2, 1)
    assert s["hit_rate_pct"] == Decimal("33.3")
    assert s["left_on_table"] == Decimal("10.00")
    assert s["avg_competitors"] == Decimal("4.0")
    assert s["avg_gap_to_winner_pct"] == Decimal("11.1")
    acme = next(g for g in s["by_client"] if g["key"] == "Acme")
    assert (acme["submitted"], acme["hit_rate_pct"]) == (4, Decimal("50.0"))
    beta = next(g for g in s["by_trade"] if g["key"] == "steel")
    assert beta["hit_rate_pct"] == Decimal("0.0")
    pending_only = next(g for g in summarize([_row("pending", "1")])["by_client"])
    assert pending_only["hit_rate_pct"] is None


def test_the_summary_currency_is_the_most_used() -> None:
    rows = [_row("won", "1", currency="USD"), _row("won", "1"), _row("won", "1")]
    assert dominant_currency(rows) == "EUR"
    assert dominant_currency([]) == ""


def test_schema_rejects_a_zero_winning_price_and_unknown_outcome() -> None:
    with pytest.raises(ValueError):
        BidOutcomeCreate(title="T", our_price=Decimal("1"), winning_price=Decimal("0"))
    with pytest.raises(ValueError):
        BidOutcomeCreate(title="T", our_price=Decimal("1"), outcome="maybe")


def test_each_check_fires_on_its_case_and_stays_quiet_otherwise() -> None:
    lost = {"title": "T", "outcome": "lost", "currency": "EUR", "our_price": "100"}
    assert checks.check_winner_recorded(lost)
    assert not checks.check_winner_recorded({**lost, "winning_price": "90"})
    assert checks.check_lost_reason_recorded(lost)
    assert not checks.check_lost_reason_recorded({**lost, "lost_reason": "price"})
    assert checks.check_competitors_recorded(lost)
    assert not checks.check_competitors_recorded({**lost, "competitor_count": 4})
    assert not checks.check_competitors_recorded({**lost, "outcome": "pending"})
    won = {"title": "T", "outcome": "won", "currency": "EUR", "our_price": "100", "winning_price": "95"}
    assert checks.check_won_matches_price(won)
    assert not checks.check_won_matches_price({**won, "winning_price": "100.00"})
    both = {**won, "winning_price": "100", "second_price": "90"}
    assert checks.check_second_not_below_winner(both)
    assert not checks.check_second_not_below_winner({**both, "second_price": "100"})


@pytest.mark.parametrize("lang", ["en", "de", "ru"])
def test_every_rule_has_a_message_in_each_shipped_language(lang: str) -> None:
    for key in (
        "winner_recorded",
        "won_matches_price",
        "second_above_winner",
        "competitors_recorded",
        "lost_reason_recorded",
    ):
        assert is_key_present(f"bid_outcome.{key}.fail", lang)
        assert is_key_present(f"bid_outcome.{key}.suggestion", lang)


@pytest.mark.asyncio
async def test_the_rule_set_reports_in_the_requested_language() -> None:
    register_builtin_rules()
    assert rule_registry.get_rules_for_sets(["bid_outcome"])
    engine = ValidationEngine(rule_registry)
    payload = {"title": "Hall", "outcome": "lost", "currency": "EUR", "our_price": "100"}
    report = await engine.validate(
        data=payload, rule_sets=["bid_outcome"], target_type="bid_outcome", metadata={"locale": "de"}
    )
    failed = {r.rule_id: r.message for r in report.results if not r.passed}
    assert set(failed) == {
        "bid_outcome.winner_recorded",
        "bid_outcome.competitors_recorded",
        "bid_outcome.lost_reason_recorded",
    }
    assert failed["bid_outcome.winner_recorded"] == translate("bid_outcome.winner_recorded.fail", "de", bid="Hall")
    clean = {**payload, "winning_price": "90", "competitor_count": 3, "lost_reason": "price"}
    ok = await engine.validate(data=clean, rule_sets=["bid_outcome"], target_type="bid_outcome")
    assert all(r.passed for r in ok.results)


def test_currency_is_normalised_to_upper_case() -> None:
    entry = BidOutcomeCreate(title="T", our_price=Decimal("1"), currency=" eur ")
    assert entry.currency == "EUR"


@pytest.mark.asyncio
async def test_listing_hides_entries_of_projects_the_caller_cannot_reach() -> None:
    import uuid

    from app.modules.win_loss.repository import BidOutcomeRepository

    seen: list[str] = []

    class _Result:
        def scalars(self) -> _Result:
            return self

        def all(self) -> list:
            return []

    class _Session:
        async def execute(self, stmt: object) -> _Result:
            seen.append(str(stmt))
            return _Result()

    repo = BidOutcomeRepository(_Session())  # type: ignore[arg-type]
    await repo.list_all(project_ids={uuid.uuid4()})
    await repo.list_all(project_ids=None)
    scoped, open_ = seen
    assert "project_id IS NULL OR" in scoped and "project_id IN" in scoped
    assert "project_id IN" not in open_


def _service_with_entry(version: int, *, update_error: Exception | None = None):
    import uuid
    from contextlib import asynccontextmanager

    from app.modules.win_loss.service import WinLossService

    entry = SimpleNamespace(id=uuid.uuid4(), project_id=None, version=version)
    calls: list[dict] = []

    class _Repo:
        session = None

        async def get_by_id(self, entry_id: object) -> SimpleNamespace:
            return entry

        async def update_fields(self, entry_id: object, **fields: object) -> None:
            if update_error is not None:
                raise update_error
            calls.append(fields)

    class _Session:
        @asynccontextmanager
        async def begin_nested(self):
            yield

        async def refresh(self, obj: object) -> None:
            return None

    service = WinLossService.__new__(WinLossService)
    service.repo = _Repo()  # type: ignore[assignment]
    service.repo.session = _Session()
    service.session = service.repo.session  # type: ignore[assignment]
    return service, entry, calls


@pytest.mark.asyncio
async def test_update_with_a_stale_version_answers_409_and_writes_nothing() -> None:
    from fastapi import HTTPException

    from app.modules.win_loss.schemas import BidOutcomeUpdate

    service, entry, calls = _service_with_entry(version=3)
    with pytest.raises(HTTPException) as caught:
        await service.update(
            entry.id, BidOutcomeUpdate(version=2, title="Renamed"), "00000000-0000-0000-0000-000000000001"
        )
    assert caught.value.status_code == 409
    assert calls == []


@pytest.mark.asyncio
async def test_update_with_the_current_version_bumps_it() -> None:
    from app.modules.win_loss.schemas import BidOutcomeUpdate

    service, entry, calls = _service_with_entry(version=3)
    await service.update(entry.id, BidOutcomeUpdate(version=3, title="Renamed"), "00000000-0000-0000-0000-000000000001")
    assert calls == [{"title": "Renamed", "version": 4}]


@pytest.mark.asyncio
async def test_patching_a_tender_that_already_has_a_record_answers_409() -> None:
    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError

    from app.modules.win_loss.schemas import BidOutcomeUpdate

    service, entry, _ = _service_with_entry(version=1, update_error=IntegrityError("stmt", {}, Exception("uq")))
    with pytest.raises(HTTPException) as caught:
        await service.update(
            entry.id, BidOutcomeUpdate(version=1, title="Renamed"), "00000000-0000-0000-0000-000000000001"
        )
    assert caught.value.status_code == 409
