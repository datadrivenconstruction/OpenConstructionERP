# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Saudi withholding tax on payments to non-residents, as payment tax rows.

Saudi Arabia withholds income tax only on payments from a Saudi source to a
payee who is not resident and has no permanent establishment in the Kingdom.
There is no resident-to-resident withholding, so a Saudi payee must never meet
one of these rows by default: every row states the non-resident condition.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.payment_taxes.data_sa import ROWS
from app.core.payment_taxes.tables import categories, lookup, rows_for, validate_rows


def _rate(code: str, on: date = date(2026, 10, 19)) -> Decimal | None:
    row = lookup(ROWS, country="SA", kind="income_withholding", code=code, on=on)
    return None if row is None else row.rate_pct


def test_the_shipped_rows_are_sound() -> None:
    assert validate_rows(ROWS) == []
    assert ROWS, "the Saudi table is empty"


def test_the_country_resolves_its_own_rows() -> None:
    assert rows_for("SA") == ROWS
    assert rows_for("sa") == ROWS


def test_the_three_rate_buckets() -> None:
    assert _rate("SA_NR_MANAGEMENT_FEES") == Decimal("20")
    assert _rate("SA_NR_ROYALTIES") == Decimal("15")
    assert _rate("SA_NR_RELATED_PARTY_SERVICES") == Decimal("15")
    assert _rate("SA_NR_TECHNICAL_SERVICES") == Decimal("5")
    assert _rate("SA_NR_RENT") == Decimal("5")
    assert _rate("SA_NR_OTHER") == Decimal("15")


def test_every_row_is_income_withholding_on_the_net_for_a_non_resident() -> None:
    for row in ROWS:
        assert row.kind == "income_withholding", row.code
        assert row.base == "net", row.code
        assert "not resident" in row.conditions["en"], row.code
        assert row.labels.get("ar"), f"{row.code} has no Arabic label"
        assert row.source_url.startswith("https://"), row.code


def test_a_date_before_the_law_is_held() -> None:
    assert _rate("SA_NR_TECHNICAL_SERVICES", on=date(2004, 1, 1)) is None


def test_the_picker_offers_one_row_per_code() -> None:
    picked = categories(ROWS, country="SA", kind="income_withholding", on=date(2026, 10, 19))
    codes = [row.code for row in picked]
    assert len(codes) == len(set(codes)) == len({row.code for row in ROWS})
