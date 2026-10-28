# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The weekly form: the pivot, the deduction columns and the statement."""

from typing import Any

from app.modules.certified_payroll import wh347


def _line(**overrides: Any) -> dict[str, Any]:
    line = {
        "worker_name": "R. Alvarez",
        "worker_identifier": "1234",
        "classification_title": "Electrician",
        "classification_code": "ELEC-1",
        "determination_identifier": "WD-2026-0041",
        "determination_authority": "federal",
        "hours_by_day": {
            "2026-08-10": {"straight": "8", "overtime": "0"},
            "2026-08-11": {"straight": "8", "overtime": "2"},
        },
        "straight_hours": "16",
        "overtime_hours": "2",
        "paid_basic_rate": "40",
        "paid_fringe_rate": "10",
        "fringe_election": "cash",
        "overtime_base_rate": "40",
        "overtime_multiplier": "1.5",
        "gross_amount": "940.00",
        "total_deductions": "140.00",
        "net_amount": "800.00",
        "deductions_detail": [
            {"label": "Social security", "type": "social", "amount": "60.00"},
            {"label": "Income tax", "type": "tax", "amount": "50.00"},
            {"label": "Union dues", "type": "other", "amount": "30.00"},
        ],
        "currency": "USD",
    }
    line.update(overrides)
    return line


def _week(**overrides: Any) -> dict[str, Any]:
    week = {
        "week_ending": "2026-08-16",
        "payroll_number": "7",
        "is_final": False,
        "contractor_name": "Northgate Mechanical",
        "project_name": "Riverside Transit Center",
        "currency": "USD",
        "status": "certified",
        "statement_text": "I do hereby state ...",
        "signatory_name": "M. Okafor",
        "signatory_title": "Project Accountant",
        "fringe_election": "cash",
    }
    week.update(overrides)
    return week


# ── The pivot ────────────────────────────────────────────────────────────────


def test_the_form_prints_seven_days_even_when_only_two_were_worked() -> None:
    """A blank day is a column with zeros, not a missing column."""
    form = wh347.render_form(_week(), [_line()])
    assert len(form["days"]) == 7
    per_day = form["rows"][0]["hours_by_day"]
    assert len(per_day) == 7
    assert per_day[0] == {"date": "2026-08-10", "straight": "8", "overtime": "0"}
    assert per_day[-1] == {"date": "2026-08-16", "straight": "0", "overtime": "0"}


def test_the_rate_column_keeps_basic_and_fringe_apart() -> None:
    """One blended rate on the form would lose exactly what it has to show."""
    row = wh347.render_form(_week(), [_line()])["rows"][0]
    assert row["basic_rate"] == "40"
    assert row["fringe_rate"] == "10"
    assert row["fringe_election"] == "cash"
    assert "rate" not in row or row.get("rate") != "50"


def test_totals_add_up_across_the_workers() -> None:
    form = wh347.render_form(_week(), [_line(), _line(worker_name="J. Bell")])
    assert form["totals"]["workers"] == "2"
    assert form["totals"]["total_hours"] == "36"
    assert form["totals"]["gross_amount"] == "1880.00"
    assert form["totals"]["net_amount"] == "1600.00"
    assert form["totals"]["total_deductions"] == "280.00"


def test_the_header_carries_the_payroll_number_and_the_final_marking() -> None:
    """Neither can be derived from payroll data, and the form asks for both."""
    header = wh347.render_form(_week(payroll_number="12", is_final=True), [_line()])["header"]
    assert header["payroll_number"] == "12"
    assert header["is_final"] is True
    assert header["week_start"] == "2026-08-10"


def test_an_unparseable_week_ending_yields_no_days_rather_than_raising() -> None:
    form = wh347.render_form(_week(week_ending="week 33"), [_line()])
    assert form["days"] == []


# ── Deduction columns ────────────────────────────────────────────────────────


def test_the_payroll_buckets_map_onto_the_forms_three_columns() -> None:
    columns = wh347.deduction_columns_for(
        [
            {"label": "Social security", "type": "social", "amount": "60.00"},
            {"label": "Income tax", "type": "tax", "amount": "50.00"},
            {"label": "Union dues", "type": "other", "amount": "30.00"},
        ]
    )
    assert columns["social_security"] == "60.00"
    assert columns["withholding_tax"] == "50.00"
    assert columns["other"] == "30.00"
    assert columns["total"] == "140.00"
    assert columns["other_labels"] == ["Union dues"]


def test_pension_lands_in_other_and_keeps_its_label() -> None:
    """It is neither statutory column, so the label has to carry the meaning."""
    columns = wh347.deduction_columns_for([{"label": "Pension 5%", "type": "pension", "amount": "25.00"}])
    assert columns["other"] == "25.00"
    assert columns["other_labels"] == ["Pension 5%"]


def test_an_unknown_bucket_falls_into_other_rather_than_vanishing() -> None:
    """A bucket added to the shared payroll enum later must not lose its money."""
    columns = wh347.deduction_columns_for([{"label": "Garnishment", "type": "court_order", "amount": "15.00"}])
    assert columns["other"] == "15.00"
    assert columns["total"] == "15.00"


def test_no_deductions_reads_as_zero_withheld_not_as_blank() -> None:
    """Blank says 'not stated'; zero says 'nothing withheld'. Different claims."""
    columns = wh347.deduction_columns_for([])
    assert columns["social_security"] == "0"
    assert columns["total"] == "0"


# ── Statement of compliance ──────────────────────────────────────────────────


def test_the_statement_fills_every_blank_from_the_week() -> None:
    text = wh347.default_statement_of_compliance(
        signatory_name="M. Okafor",
        signatory_title="Project Accountant",
        contractor_name="Northgate Mechanical",
        project_name="Riverside Transit Center",
        week_start="2026-08-10",
        week_ending="2026-08-16",
        fringe_election="plan",
    )
    assert "M. Okafor" in text
    assert "Project Accountant" in text
    assert "Northgate Mechanical" in text
    assert "Riverside Transit Center" in text
    assert "2026-08-10" in text
    assert "2026-08-16" in text
    # The four numbered assertions are all present.
    for marker in ("(1)", "(2)", "(3)", "(4)"):
        assert marker in text


def test_the_election_changes_the_fourth_assertion() -> None:
    """Plan and cash are different claims and cannot share one wording."""
    common = {
        "signatory_name": "M. Okafor",
        "signatory_title": "Project Accountant",
        "contractor_name": "Northgate Mechanical",
        "project_name": "Riverside Transit Center",
        "week_start": "2026-08-10",
        "week_ending": "2026-08-16",
    }
    to_plan = wh347.default_statement_of_compliance(fringe_election="plan", **common)
    in_cash = wh347.default_statement_of_compliance(fringe_election="cash", **common)
    assert "paid to approved plans" in to_plan
    assert "paid in cash" in in_cash
    assert to_plan != in_cash


def test_an_exception_note_becomes_a_remark() -> None:
    text = wh347.default_statement_of_compliance(
        signatory_name="M. Okafor",
        signatory_title="Project Accountant",
        contractor_name="Northgate Mechanical",
        project_name="Riverside Transit Center",
        week_start="2026-08-10",
        week_ending="2026-08-16",
        fringe_election="mixed",
        exception_note="Apprentice rates apply to two workers.",
    )
    assert "Remarks: Apprentice rates apply to two workers." in text


# ── CSV ──────────────────────────────────────────────────────────────────────


def test_csv_carries_two_columns_per_day_headed_by_the_iso_date() -> None:
    csv_text = wh347.render_csv(wh347.render_form(_week(), [_line()]))
    header, row = csv_text.strip().split("\n")[:2]
    assert "2026-08-10_straight" in header
    assert "2026-08-10_overtime" in header
    assert header.count("_straight") == 7
    assert "R. Alvarez" in row
    assert "Electrician" in row


def test_csv_keeps_the_basic_and_fringe_columns_separate() -> None:
    csv_text = wh347.render_csv(wh347.render_form(_week(), [_line()]))
    header = csv_text.split("\n")[0].split(",")
    assert "basic_rate" in header
    assert "fringe_rate" in header
    assert "social_security" in header
    assert "withholding_tax" in header


def test_csv_of_an_empty_week_is_a_header_and_nothing_else() -> None:
    csv_text = wh347.render_csv(wh347.render_form(_week(), []))
    assert len(csv_text.strip().split("\n")) == 1
