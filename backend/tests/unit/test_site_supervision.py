# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure site-supervision domain logic and label localization.

Pins the jurisdiction-neutral supervision maths without a DB or a clock:
plan-versus-fact counting and overdue detection, the hidden-works acceptance
register, the reason-required motivated refusal, the change-sheet link filter,
the neutral-keyed structured export, and the plan-coverage closeout gate. Also
checks the /meta label lookups localise with an English fallback and never leak
a raw code. The pure functions accept plain namespaces so no session is needed.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.modules.site_supervision import intl
from app.modules.site_supervision.validators import (
    change_sheet_links,
    export_visit,
    hidden_works_register,
    motivated_refusal,
    plan_vs_fact,
    supervision_plan_coverage,
)

_TODAY = date(2026, 7, 21)


def _visit(**kw):
    base = {
        "id": kw.pop("id", "v1"),
        "project_id": "p1",
        "planned_date": None,
        "actual_date": None,
        "visitor": "",
        "discipline": "general",
        "status": "planned",
        "summary": "",
        "photo_refs": [],
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _entry(**kw):
    base = {
        "id": kw.pop("id", "e1"),
        "visit_id": "v1",
        "project_id": "p1",
        "ordinal": "",
        "observation": "",
        "category": "conformance",
        "structured_fields": {},
        "links_to_change_ref": None,
        "status": "open",
    }
    base.update(kw)
    return SimpleNamespace(**base)


# ── plan_vs_fact ────────────────────────────────────────────────────────────


def test_plan_vs_fact_counts_and_ratio() -> None:
    visits = [
        _visit(id="a", planned_date=date(2026, 7, 1), actual_date=date(2026, 7, 2), status="conducted"),
        _visit(id="b", planned_date=date(2026, 7, 10), actual_date=None, status="planned"),  # overdue
        _visit(id="c", planned_date=date(2026, 8, 1), actual_date=None, status="planned"),  # future, ok
        _visit(id="d", planned_date=None, actual_date=date(2026, 7, 5), status="reported"),  # ad hoc
    ]
    r = plan_vs_fact(visits, today=_TODAY)
    assert r["total"] == 4
    assert r["planned_count"] == 3  # a, b, c have a planned_date
    assert r["conducted_count"] == 2  # a, d have an actual_date
    assert r["reported_count"] == 1  # d
    assert r["overdue_count"] == 1
    assert r["overdue_refs"] == ["b"]
    assert r["defined"] is True
    # conducted_of_planned = only 'a' (planned AND has outcome) -> 1 / 3
    assert r["completion_ratio"] == pytest.approx(1 / 3, abs=1e-4)


def test_plan_vs_fact_undefined_when_nothing_planned() -> None:
    r = plan_vs_fact([_visit(planned_date=None, actual_date=date(2026, 7, 5), status="conducted")], today=_TODAY)
    assert r["planned_count"] == 0
    assert r["defined"] is False
    assert r["completion_ratio"] == 0.0  # no NaN


# ── hidden_works_register ───────────────────────────────────────────────────


def test_hidden_works_register_marks_acceptance() -> None:
    entries = [
        _entry(id="h1", category="hidden_works", status="closed"),
        _entry(id="h2", category="hidden_works", status="open"),
        _entry(id="x", category="conformance", status="closed"),  # excluded
    ]
    reg = hidden_works_register(entries)
    assert len(reg) == 2
    by_ref = {row["ref"]: row for row in reg}
    assert by_ref["h1"]["accepted"] is True
    assert by_ref["h2"]["accepted"] is False


# ── motivated_refusal ───────────────────────────────────────────────────────


def test_motivated_refusal_sets_status_and_reason() -> None:
    entry = _entry(category="deviation", status="open")
    out = motivated_refusal(entry, "  Cover concrete not to spec  ")
    assert out.status == "refused_motivated"
    assert out.structured_fields["refusal_reason"] == "Cover concrete not to spec"


def test_motivated_refusal_rejects_empty_reason() -> None:
    entry = _entry()
    with pytest.raises(ValueError):
        motivated_refusal(entry, "   ")


# ── change_sheet_links ──────────────────────────────────────────────────────


def test_change_sheet_links_filters_category_and_ref() -> None:
    entries = [
        _entry(id="i1", category="instruction", links_to_change_ref="CH-1"),
        _entry(id="d1", category="deviation", links_to_change_ref="CH-2"),
        _entry(id="d2", category="deviation", links_to_change_ref=None),  # no ref -> excluded
        _entry(id="c1", category="conformance", links_to_change_ref="CH-9"),  # wrong category
    ]
    links = change_sheet_links(entries)
    refs = {row["ref"] for row in links}
    assert refs == {"i1", "d1"}


# ── export_visit ────────────────────────────────────────────────────────────


def test_export_visit_uses_neutral_keys() -> None:
    visit = _visit(
        id="v9",
        discipline="structure",
        visitor="A. Inspector",
        planned_date=date(2026, 7, 1),
        actual_date=date(2026, 7, 2),
        status="reported",
        summary="Rebar inspection",
        photo_refs=["ph1"],
    )
    entries = [
        _entry(
            id="e9",
            ordinal="1.1",
            category="hidden_works",
            observation="Rebar placed",
            status="closed",
            structured_fields={
                "element": "Slab S1",
                "location": "Level 2",
                "norm_ref": "EC2",
                "required_action": "Accept",
                "pack_extra": "keep-me",
            },
        )
    ]
    doc = export_visit(visit, entries)
    assert doc["visit"]["discipline"] == "structure"
    assert doc["visit"]["planned_date"] == "2026-07-01"
    e = doc["entries"][0]
    assert e["element"] == "Slab S1"
    assert e["norm_ref"] == "EC2"
    assert e["required_action"] == "Accept"
    assert e["extra"] == {"pack_extra": "keep-me"}


# ── supervision_plan_coverage ───────────────────────────────────────────────


def test_plan_coverage_passes_when_covered() -> None:
    visits = [
        _visit(id="a", planned_date=date(2026, 7, 1), actual_date=date(2026, 7, 1), status="reported"),
        _visit(id="b", planned_date=date(2026, 8, 1), status="planned"),  # future, not due
    ]
    entries = [_entry(id="h1", category="hidden_works", status="closed")]
    r = supervision_plan_coverage(visits, entries, today=_TODAY)
    assert r["passed"] is True
    assert r["checked_visits"] == 1
    assert r["checked_hidden_works"] == 1


def test_plan_coverage_flags_missing_outcome_and_open_hidden_works() -> None:
    visits = [_visit(id="a", planned_date=date(2026, 7, 1), actual_date=None, status="planned")]
    entries = [_entry(id="h1", category="hidden_works", status="open")]
    r = supervision_plan_coverage(visits, entries, today=_TODAY)
    assert r["passed"] is False
    assert r["planned_without_outcome"] == ["a"]
    assert r["hidden_works_not_accepted"] == ["h1"]
    assert len(r["issues"]) == 2


# ── intl labels ─────────────────────────────────────────────────────────────


def test_labels_localise() -> None:
    assert intl.describe_discipline("structure", "de") == "Tragwerk"
    assert intl.describe_category("hidden_works", "ru") == "Скрытые работы"
    assert intl.describe_visit_status("reported", "es") == "Informada"
    assert intl.describe_entry_status("closed", "en") == "Closed"


def test_labels_fall_back_to_english() -> None:
    assert intl.describe_category("deviation", "zz") == "Deviation"
    assert intl.describe_discipline("mep", None) == "MEP"


def test_unknown_code_is_humanised_not_raw() -> None:
    assert intl.describe_category("site_welfare_note", "en") == "Site Welfare Note"
