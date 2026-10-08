# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A tax rate marked for local confirmation is not used until someone confirms it.

Some rates ship before anyone on the ground has checked them; the Democratic
Republic of the Congo was the case that raised it. The decision was that the
client's accountant confirms such a rate against the tax authority's own
publication before it takes effect. Until then the resolver answers
``awaiting_confirmation`` with no number, and no other row stands in for it.
Rows without the marker, which is every row shipped before it existed, are
unaffected.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.modules.i18n_foundation.service import _CONFIRMED_FIELDS, _with_fresh_confirmation
from app.modules.i18n_foundation.tax_rules import (
    LOCAL_CONFIRMATION_KEY,
    RESOLVED_STATUSES,
    TaxRateRow,
    is_awaiting_confirmation,
    resolve,
    row_from_orm,
)

AS_OF = "2026-10-08"


def _row(rate: str = "16", *, awaiting: bool = False, subdivision: str | None = None, combination: str = "national"):
    return TaxRateRow(
        country_code="CD",
        tax_code="TVA",
        tax_name="TVA",
        rate_pct=rate,
        tax_type="vat",
        combination=combination,
        subdivision_code=subdivision,
        effective_from="2020-01-01",
        effective_to=None,
        is_default=True,
        awaiting_confirmation=awaiting,
    )


def test_an_unconfirmed_rate_resolves_to_no_number() -> None:
    result = resolve([_row(awaiting=True)], "CD", None, AS_OF)
    assert result.status == "awaiting_confirmation"
    assert result.combined_rate_pct is None
    assert not result.resolved
    assert "awaiting_confirmation" not in RESOLVED_STATUSES


def test_a_confirmed_rate_resolves_as_before() -> None:
    result = resolve([_row()], "CD", None, AS_OF)
    assert result.resolved
    assert result.combined_rate_pct == "16"


def test_a_neighbouring_row_does_not_stand_in_for_the_unconfirmed_one() -> None:
    old = _row("10")._replace(is_default=False)
    result = resolve([old, _row(awaiting=True)], "CD", None, AS_OF)
    assert result.status == "awaiting_confirmation"
    assert result.combined_rate_pct is None


def test_an_unconfirmed_rate_outside_its_window_does_not_block() -> None:
    future = _row(awaiting=True)._replace(effective_from="2030-01-01", is_default=False)
    result = resolve([_row(), future], "CD", None, AS_OF)
    assert result.combined_rate_pct == "16"


def test_the_marker_is_read_from_metadata() -> None:
    assert not is_awaiting_confirmation(None)
    assert not is_awaiting_confirmation({})
    assert not is_awaiting_confirmation({LOCAL_CONFIRMATION_KEY: {"required": False}})
    assert is_awaiting_confirmation({LOCAL_CONFIRMATION_KEY: {"required": True, "status": "pending"}})
    assert is_awaiting_confirmation({LOCAL_CONFIRMATION_KEY: {"required": True}})
    assert not is_awaiting_confirmation({LOCAL_CONFIRMATION_KEY: {"required": True, "status": "confirmed"}})


def test_an_orm_row_carries_the_marker_into_the_resolver() -> None:
    orm = SimpleNamespace(
        country_code="CD",
        tax_code="TVA",
        tax_name="TVA",
        rate_pct="16",
        tax_type="vat",
        combination="national",
        subdivision_code=None,
        effective_from=None,
        effective_to=None,
        is_default=True,
        metadata_={LOCAL_CONFIRMATION_KEY: {"required": True, "status": "pending"}},
    )
    assert row_from_orm(orm).awaiting_confirmation


def test_a_new_row_can_ask_for_confirmation_but_never_arrive_confirmed() -> None:
    sent = {"note": "x", LOCAL_CONFIRMATION_KEY: {"required": True, "status": "confirmed", "accountant_name": "A"}}
    assert _with_fresh_confirmation(sent) == {
        "note": "x",
        LOCAL_CONFIRMATION_KEY: {"required": True, "status": "pending"},
    }
    assert _with_fresh_confirmation({LOCAL_CONFIRMATION_KEY: {"status": "confirmed"}}) == {}
    assert _with_fresh_confirmation(None) == {}


def test_the_rate_and_its_dates_are_what_a_confirmation_vouches_for() -> None:
    assert {"rate_pct", "effective_from", "effective_to"} <= set(_CONFIRMED_FIELDS)
