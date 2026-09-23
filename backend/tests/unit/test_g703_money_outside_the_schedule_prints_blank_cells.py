# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The G703 row carrying money no schedule line carries leaves C, % and H empty.

That row exists because earlier claims billed work that no schedule of values
line holds, either a month billed from cost on a contract that can bill both
ways, or a claim whose gross outran its lines. The money is real and sits in
column G. It has no scheduled value, so there is nothing to measure a percent
or a balance to finish against.

The row used to print a zero in column C, which made the percent read 0 against
a non-zero G and column H read minus G. Those three cells are now empty: an
empty cell says there is no answer, a zero says the answer is zero. Everything
else on the row, and every figure on the G702 face, stays exactly as it was.

The totals row adds up the cells that have an answer. Column C's total does not
move, because the row used to contribute a zero to it. Column H's total rises by
the row's G, because the minus G the placeholder put there is gone, so on a
sheet carrying this row the H total no longer equals the C total less the G
total; the gap is that row's G, the same caveat that already kept column C from
tying to line 3 on such a contract.

Figures, all hand-checkable. Two schedule lines, A at 60,000 and B at 40,000,
each 40% billed before and 20% this period. Earlier claims also billed 10,000
with no schedule line behind it. Retainage 10%.
"""

from __future__ import annotations

import io
import re
import uuid
from decimal import Decimal

from app.modules.contracts.aia import build_g702_summary, build_g703
from app.modules.contracts.aia_pdf import render_aia_application_pdf
from app.modules.contracts.schemas import AIAApplicationResponse, AIAG703Line

OUTSIDE = Decimal("10000")
LABEL = "Offschedule"


class _Line:
    """The attributes the G703 builders read off a schedule of values line."""

    def __init__(self, code: str, total: str, description: str) -> None:
        self.id = uuid.uuid4()
        self.code = code
        self.description = description
        self.total_value = Decimal(total)


class _Billed:
    """A claim line as the generators store one."""

    def __init__(self, period: str, prior: str) -> None:
        self.period_completed_value = Decimal(period)
        self.prior_completed_value = Decimal(prior)
        self.materials_stored_value = None
        self.cumulative_completed_value = None
        self.metadata_ = {}


def _schedule():
    lines = [_Line("A", "60000", "Foundations"), _Line("B", "40000", "Framing")]
    billed = {lines[0].id: _Billed("12000", prior="24000"), lines[1].id: _Billed("8000", prior="16000")}
    return lines, billed


def _mixed_sheet():
    lines, billed = _schedule()
    rows = build_g703(
        lines,
        billed,
        retainage_percent=Decimal("10"),
        prior_without_schedule=OUTSIDE,
        out_of_schedule_label=LABEL,
    )
    # Line 7: the cost month certified 10,000 less 1,000 retained, the earlier
    # schedule claim 40,000 less 4,000.
    summary = build_g702_summary(
        rows,
        original_contract_sum=Decimal("100000"),
        change_orders_net=Decimal("0"),
        previous_certificates_total=Decimal("45000"),
    )
    return rows, summary


def _application(rows, summary) -> dict:
    return {
        "claim_id": uuid.uuid4(),
        "contract_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "application_number": "PC-3",
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


# ── The builder ───────────────────────────────────────────────────────────


def test_the_out_of_schedule_row_has_no_scheduled_value_percent_or_balance() -> None:
    rows, _ = _mixed_sheet()
    outside = rows[-1]

    assert outside["description"] == LABEL
    assert outside["scheduled_value"] is None
    assert outside["percent_complete"] is None
    assert outside["balance_to_finish"] is None


def test_the_out_of_schedule_row_still_carries_its_money() -> None:
    rows, _ = _mixed_sheet()
    outside = rows[-1]

    assert outside["item_number"] == ""
    assert outside["previous_value"] == Decimal("10000.00")
    assert outside["this_period_value"] == Decimal("0.00")
    assert outside["materials_stored"] == Decimal("0.00")
    assert outside["total_completed_stored"] == Decimal("10000.00")
    assert outside["retainage"] == Decimal("1000.00")
    assert outside["retainage_completed_work"] == Decimal("1000.00")
    assert outside["retainage_stored_materials"] == Decimal("0.00")


def test_the_schedule_rows_are_what_they_are_without_the_extra_row() -> None:
    lines, billed = _schedule()
    alone = build_g703(lines, billed, retainage_percent=Decimal("10"))
    rows, _ = _mixed_sheet()

    assert rows[:2] == alone
    assert [row["scheduled_value"] for row in rows[:2]] == [Decimal("60000.00"), Decimal("40000.00")]
    assert [row["percent_complete"] for row in rows[:2]] == [Decimal("60.00"), Decimal("60.00")]
    assert [row["balance_to_finish"] for row in rows[:2]] == [Decimal("24000.00"), Decimal("16000.00")]


def test_the_face_reads_lines_three_to_nine_as_before() -> None:
    """None of lines 1 to 9 reads column C, H or the percent, so none of them moves."""
    _, summary = _mixed_sheet()

    assert summary["contract_sum_to_date"] == Decimal("100000.00")
    assert summary["total_completed_stored"] == Decimal("70000.00")
    assert summary["retainage"] == Decimal("7000.00")
    assert summary["retainage_completed_work"] == Decimal("7000.00")
    assert summary["retainage_stored_materials"] == Decimal("0.00")
    assert summary["total_earned_less_retainage"] == Decimal("63000.00")
    assert summary["previous_certificates_total"] == Decimal("45000.00")
    # This period's 20,000 less its 2,000 retention.
    assert summary["current_payment_due"] == Decimal("18000.00")
    assert summary["balance_to_finish"] == Decimal("37000.00")


# ── The response the endpoint validates ──────────────────────────────────


def test_the_response_schema_carries_the_empty_cells_as_null() -> None:
    """The endpoint validates its payload through this model, so a None it refused would be a 500."""
    rows, summary = _mixed_sheet()

    response = AIAApplicationResponse.model_validate(_application(rows, summary))
    dumped = response.model_dump(mode="json")["lines"][-1]

    assert dumped["scheduled_value"] is None
    assert dumped["percent_complete"] is None
    assert dumped["balance_to_finish"] is None
    assert Decimal(dumped["total_completed_stored"]) == Decimal("10000.00")


def test_a_schedule_row_still_serialises_its_figures() -> None:
    rows, _ = _mixed_sheet()
    dumped = AIAG703Line.model_validate(rows[0]).model_dump(mode="json")

    assert Decimal(dumped["scheduled_value"]) == Decimal("60000.00")
    assert Decimal(dumped["percent_complete"]) == Decimal("60.00")
    assert Decimal(dumped["balance_to_finish"]) == Decimal("24000.00")


# ── The printed sheet ────────────────────────────────────────────────────


def _row_words(pdf: bytes, anchor: str) -> list[str]:
    """Every word on the continuation sheet row whose first word is ``anchor``."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        for page in doc.pages:
            words = page.extract_words()
            hits = [w for w in words if w["text"] == anchor]
            if not hits:
                continue
            top = hits[-1]["top"]
            return [w["text"] for w in sorted((w for w in words if abs(w["top"] - top) < 4), key=lambda w: w["x0"])]
    return []


def _amounts(words: list[str]) -> list[Decimal]:
    return [Decimal(w.replace(",", "")) for w in words if re.fullmatch(r"-?[\d,]+\.\d{2}", w)]


def test_the_printed_row_leaves_c_percent_and_h_empty() -> None:
    rows, summary = _mixed_sheet()
    words = _row_words(render_aia_application_pdf(_application(rows, summary)), LABEL)

    assert words, "the out-of-schedule row is not on the sheet"
    # D, E, F, G and I only: no scheduled value, no balance, no percent.
    assert _amounts(words) == [
        Decimal("10000.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("10000.00"),
        Decimal("1000.00"),
    ]
    assert not [w for w in words if w.endswith("%")]


def test_a_printed_schedule_row_is_unchanged() -> None:
    rows, summary = _mixed_sheet()
    words = _row_words(render_aia_application_pdf(_application(rows, summary)), "Foundations")

    assert _amounts(words) == [
        Decimal("60000.00"),
        Decimal("24000.00"),
        Decimal("12000.00"),
        Decimal("0.00"),
        Decimal("36000.00"),
        Decimal("24000.00"),
        Decimal("3600.00"),
    ]
    assert "60.00%" in words


def test_the_totals_row_adds_up_the_cells_that_have_an_answer() -> None:
    """C totals the schedule, as it did; H totals the schedule's balances, which the placeholder had pulled down."""
    rows, summary = _mixed_sheet()
    printed_c, printed_g, printed_h, printed_i = _amounts(
        _row_words(render_aia_application_pdf(_application(rows, summary)), "Grand")
    )

    assert printed_c == Decimal("100000.00")
    assert printed_g == summary["total_completed_stored"] == Decimal("70000.00")
    assert printed_h == Decimal("40000.00")
    assert printed_i == summary["retainage"] == Decimal("7000.00")
    # The row's G has no balance of its own, so H no longer equals C less G.
    assert printed_c - printed_g == printed_h - OUTSIDE
