# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The past windows ``tax_history_backfill`` may deliver, pinned against the seed file.

Every entry has to be a window the file really ships, closed, and in front of
a later window on the same line: that is the only shape the repair exists for,
and an entry of any other shape would either deliver nothing or overlap a rate
an install already holds.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.i18n_foundation.seed import load_tax_seed_rows
from app.modules.i18n_foundation.tax_history_backfill import (
    WINDOW_FIRST_SHIPPED,
    delivery_key,
    shipped_windows,
)
from app.modules.i18n_foundation.tax_seed_reconcile import LINE_FIRST_SHIPPED, REPAIRED_ELSEWHERE


def test_the_backfill_population_is_switzerland_s_three_past_windows() -> None:
    assert set(WINDOW_FIRST_SHIPPED) == {
        ("CH", "VAT", "2018-01-01"),
        ("CH", "VAT_REDUCED", "2018-01-01"),
        ("CH", "VAT_SPECIAL", "2018-01-01"),
    }


def test_every_window_ships_closed_and_before_a_later_window_on_its_line() -> None:
    shipped = shipped_windows()
    assert set(shipped) == set(WINDOW_FIRST_SHIPPED), "a declared window is not in the seed file"
    rows = load_tax_seed_rows()
    for (country, tax_code, starts), row in shipped.items():
        assert row["effective_to"] is not None, f"{delivery_key((country, tax_code, starts))} is open"
        later = [
            other
            for other in rows
            if other["country_code"] == country
            and other["tax_code"] == tax_code
            and (other.get("effective_from") or "") > row["effective_to"]
        ]
        assert later, f"{delivery_key((country, tax_code, starts))} has no later window to sit in front of"


def test_no_window_belongs_to_a_line_another_repair_delivers_or_owns() -> None:
    """A whole line the reconciler delivers already carries its history with it."""
    lines = {(country, tax_code) for country, tax_code, _ in WINDOW_FIRST_SHIPPED}
    assert not lines & set(LINE_FIRST_SHIPPED)
    assert not lines & REPAIRED_ELSEWHERE


def test_every_ship_date_is_a_past_date() -> None:
    """A date in the future would withhold the window from every install for ever."""
    now = datetime.now(UTC)
    for window, iso in WINDOW_FIRST_SHIPPED.items():
        assert datetime.fromisoformat(iso).replace(tzinfo=UTC) < now, f"{delivery_key(window)} ships at {iso}"


def test_a_window_key_cannot_be_read_as_a_line_key() -> None:
    assert delivery_key(("CH", "VAT", "2018-01-01")) == "CH/VAT@2018-01-01"
