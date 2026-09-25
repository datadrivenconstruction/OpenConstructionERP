# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""G702 line 5 is the claim's own retention to the cent.

The certificate used to round retention on each G703 row and add the rounded
rows up, so on a schedule of odd-cent lines line 5 came out a cent or more
away from the retention the claim itself stored, and the two documents a
payer compares disagreed. Column I is now rounded once over the whole column
(``_allocate_to_cents``), and on a claim the retention engine has worked out
it carries the engine's stored per-line figures (``apply_retention_snapshot``).
Both paths are pinned here against the claim's figure.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace

from app.modules.contracts.aia import apply_retention_snapshot, build_g702_summary, build_g703

CENT = Decimal("0.01")


def _schedule(n: int, value: str) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(id=uuid.uuid4(), code=f"{i:02d}", description=f"Line {i}", total_value=Decimal(value))
        for i in range(1, n + 1)
    ]


def _billed(lines: list[SimpleNamespace], **extra: Decimal) -> dict:
    return {
        ln.id: SimpleNamespace(
            period_completed_value=ln.total_value,
            prior_completed_value=Decimal("0"),
            cumulative_completed_value=ln.total_value,
            materials_stored_value=Decimal("0"),
            metadata_={},
            **extra,
        )
        for ln in lines
    }


def test_a_flat_rate_line_5_is_the_rounded_retention_on_the_gross() -> None:
    # Ten per cent of 1000.05 is 100.005 on every row: rounded row by row and
    # added up, a hundred rows print 10,001.00 against a claim of 10,000.50.
    lines = _schedule(100, "1000.05")
    rows = build_g703(lines, _billed(lines), retainage_percent=Decimal("10"))
    summary = build_g702_summary(rows, original_contract_sum=Decimal("100005"))

    gross = sum((ln.total_value for ln in lines), Decimal("0"))
    claim_retention = (gross * Decimal("10") / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)
    assert summary["retainage"] == claim_retention == Decimal("10000.50")


def test_an_engine_worked_claim_prints_the_stored_per_line_retention() -> None:
    lines = _schedule(3, "333.33")
    stored = [Decimal("33.33"), Decimal("33.34"), Decimal("33.33")]
    by_line = _billed(lines)
    for ln, held in zip(lines, stored, strict=True):
        by_line[ln.id].retention_to_date = held
        by_line[ln.id].retention_stored_to_date = Decimal("0")
    rows = build_g703(lines, by_line, retainage_percent=Decimal("10"))

    apply_retention_snapshot(rows, lines, by_line, held=sum(stored, Decimal("0")))
    summary = build_g702_summary(rows, original_contract_sum=Decimal("999.99"))

    assert [row["retainage"] for row in rows] == stored
    assert summary["retainage"] == Decimal("100.00")
