# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The printed G702/G703 has to add up, to itself and to the claim behind it.

Three defects that all showed up as a certificate whose own figures disagreed,
found by an adversarial review of the money math (its scenario ids are kept in
the test names so a finding can be traced back):

* rv-money s09/s09b: every row was rounded to cents on its own and the face
  added the rounded rows up, so line 5 drifted from the claim's retention by a
  cent per row - half a dollar over a hundred lines - and a row could print
  D + E + F and G that did not agree.
* rv-money s13: a claim billed without a schedule of values (cost-plus, T&M)
  had no rows to roll up, so lines 4 and 8 printed zero on a claim that was
  owed its net in full.
* rv-money s01: the continuation sheet's totals row took column C from G702
  line 3 and column H from line 9, two figures of the face that are not those
  columns, so the printed total did not match the rows above it.

All pure: no database, no service, hand-checkable arithmetic.
"""

from __future__ import annotations

import io
import re
import uuid
from decimal import Decimal

from app.modules.contracts.aia import (
    build_cost_of_work_row,
    build_g702_summary,
    build_g703,
)
from app.modules.contracts.aia_pdf import render_aia_application_pdf


class _Line:
    """The two attributes the G703 builders read off an SoV line."""

    def __init__(self, code: str, total: str, description: str = "Work") -> None:
        self.id = uuid.uuid4()
        self.code = code
        self.description = description
        self.total_value = Decimal(total)


class _Billed:
    """A claim line as the generators store one."""

    def __init__(self, period: str, prior: str = "0") -> None:
        self.period_completed_value = Decimal(period)
        self.prior_completed_value = Decimal(prior)
        self.materials_stored_value = None
        self.cumulative_completed_value = None
        self.metadata_ = {}


def _sheet(lines, billed, *, retainage="10"):
    rows = build_g703(lines, billed, retainage_percent=Decimal(retainage))
    scheduled = sum((ln.total_value for ln in lines), Decimal("0"))
    summary = build_g702_summary(rows, original_contract_sum=scheduled, change_orders_net=Decimal("0"))
    return rows, summary


def _column(rows, key) -> Decimal:
    return sum((row[key] for row in rows), Decimal("0"))


# ── Rounding: the column is rounded, not the row ─────────────────────────


def test_retainage_does_not_drift_a_cent_per_row_rv_s09b() -> None:
    """A hundred rows whose retainage is half a cent: line 5 is 10,000.50, not 10,001."""
    lines = [_Line(f"L{i:03d}", "1000.05") for i in range(100)]
    billed = {ln.id: _Billed("1000.05") for ln in lines}
    rows, summary = _sheet(lines, billed)

    # 10% of 1000.05 is 100.005 on every row. Rounding each row up and adding
    # the results gives 10,001.00; the exact column is 10,000.50.
    assert summary["retainage"] == Decimal("10000.50")
    assert _column(rows, "retainage") == summary["retainage"]
    assert summary["total_completed_stored"] == Decimal("100005.00")
    assert summary["total_earned_less_retainage"] == Decimal("90004.50")


def test_the_sheet_adds_up_to_the_face_on_odd_cents_rv_s09() -> None:
    """Three lines of 1000.01 at 60%: line 4 is 1800.02 and the rows say so too."""
    lines = [_Line(code, "1000.01") for code in ("A", "B", "C")]
    # 40% billed before, 20% this period: D 400.004, E 200.002, G 600.006.
    billed = {ln.id: _Billed("200.002", prior="400.004") for ln in lines}
    rows, summary = _sheet(lines, billed)

    assert summary["total_completed_stored"] == Decimal("1800.02")
    assert _column(rows, "total_completed_stored") == summary["total_completed_stored"]
    # Every printed row adds up on its own: the cent the column owes lands in
    # one row's column E rather than sitting between D + E + F and G.
    for row in rows:
        assert (
            row["previous_value"] + row["this_period_value"] + row["materials_stored"]
            == (row["total_completed_stored"])
        )
        assert row["scheduled_value"] - row["total_completed_stored"] == row["balance_to_finish"]


def test_a_line_finished_to_the_cent_prints_no_balance_rv_s09() -> None:
    """At 100% the column has nothing to spread, so no row is pushed past its value."""
    lines = [_Line(code, "1000.01") for code in ("A", "B", "C")]
    billed = {ln.id: _Billed("400.004", prior="600.006") for ln in lines}
    rows, summary = _sheet(lines, billed)

    assert [row["total_completed_stored"] for row in rows] == [Decimal("1000.01")] * 3
    assert [row["balance_to_finish"] for row in rows] == [Decimal("0.00")] * 3
    assert [row["percent_complete"] for row in rows] == [Decimal("100.00")] * 3
    assert summary["total_completed_stored"] == Decimal("3000.03")


def test_a_credit_line_keeps_its_sign_while_the_column_still_foots_rv_s10() -> None:
    """A negative SoV line must not be rounded towards zero or dropped from the spread."""
    work = _Line("A", "60000")
    credit = _Line("D", "-5000")
    billed = {work.id: _Billed("24000"), credit.id: _Billed("-2000")}
    rows, summary = _sheet([work, credit], billed)

    assert rows[1]["total_completed_stored"] == Decimal("-2000.00")
    assert rows[1]["retainage"] == Decimal("-200.00")
    assert rows[1]["balance_to_finish"] == Decimal("-3000.00")
    assert summary["total_completed_stored"] == Decimal("22000.00")
    assert _column(rows, "total_completed_stored") == summary["total_completed_stored"]


def test_an_empty_sheet_rolls_up_to_zero() -> None:
    rows, summary = _sheet([], {})
    assert rows == []
    assert summary["total_completed_stored"] == Decimal("0.00")


# ── A claim billed without a schedule of values ──────────────────────────


def test_cost_of_work_row_carries_the_claims_own_figures_rv_s13() -> None:
    """Cost-plus month two: D is what the earlier claims billed, E this claim's gross."""
    row = build_cost_of_work_row(
        item_number="C-1",
        description="Reimbursable works",
        scheduled=Decimal("100000"),
        previous=Decimal("50000"),
        this_period=Decimal("30000"),
        retainage=Decimal("8000"),
    )
    assert row["previous_value"] == Decimal("50000.00")
    assert row["this_period_value"] == Decimal("30000.00")
    assert row["total_completed_stored"] == Decimal("80000.00")
    assert row["balance_to_finish"] == Decimal("20000.00")
    assert row["percent_complete"] == Decimal("80.00")
    assert row["retainage"] == Decimal("8000.00")

    summary = build_g702_summary(
        [row],
        original_contract_sum=Decimal("100000"),
        change_orders_net=Decimal("0"),
        previous_certificates_total=Decimal("45000"),
    )
    assert summary["total_completed_stored"] == Decimal("80000.00")
    # Line 8 is this period's gross less its retention: 30000 - 3000.
    assert summary["current_payment_due"] == Decimal("27000.00")


# ── The printed totals row ───────────────────────────────────────────────


def _grand_total_numbers(pdf: bytes) -> list[Decimal]:
    """The money figures on the continuation sheet's 'Grand total' row."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        for page in doc.pages:
            words = page.extract_words()
            anchor = [w for w in words if w["text"] == "Grand"]
            if not anchor:
                continue
            top = anchor[0]["top"]
            row = sorted((w for w in words if abs(w["top"] - top) < 4), key=lambda w: w["x0"])
            return [Decimal(w["text"].replace(",", "")) for w in row if re.fullmatch(r"-?[\d,]+\.\d{2}", w["text"])]
    return []


def test_pdf_grand_total_row_totals_the_columns_it_sits_under_rv_s01() -> None:
    """C and H under the totals row are the columns' own totals, not lines 3 and 9."""
    lines = [_Line("A", "60000", "Foundations"), _Line("B", "40000", "Framing")]
    billed = {lines[0].id: _Billed("12000", prior="24000"), lines[1].id: _Billed("8000", prior="16000")}
    rows, summary = _sheet(lines, billed)
    app = {
        "claim_id": uuid.uuid4(),
        "contract_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "application_number": "PC-2",
        "period_start": None,
        "period_end": None,
        "claim_date": None,
        "currency": "USD",
        "claim_status": "draft",
        "retainage_percent": Decimal("10.00"),
        "summary": summary,
        "lines": rows,
        "certification": {},
    }

    numbers = _grand_total_numbers(render_aia_application_pdf(app))

    assert len(numbers) == 4, f"expected C, G, H and I on the totals row, got {numbers}"
    printed_c, printed_g, printed_h, printed_i = numbers
    assert printed_c == _column(rows, "scheduled_value")
    assert printed_g == _column(rows, "total_completed_stored") == summary["total_completed_stored"]
    # Column H is C - G and leaves retainage out; G702 line 9 carries it, so
    # the two are 6,000 apart here and only the column belongs under the column.
    assert printed_h == _column(rows, "balance_to_finish") == Decimal("40000.00")
    assert printed_h != summary["balance_to_finish"]
    assert printed_i == _column(rows, "retainage") == summary["retainage"]
