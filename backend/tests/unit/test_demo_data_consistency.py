"""Berlin and London demo data: standard codes, budget rule, VAT, relative dates."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from app.core.demo_projects import DEMO_TEMPLATES, _demo_anchor
from app.core.demo_vat import demo_vat_rate
from app.modules.plant_register.seed import _ITEMS, _ORDER_VALUE
from app.modules.projects.router import governing_boq_id_set


def _direct_total(template) -> float:
    return sum(float(i[3]) * float(i[4]) for sec in template.sections for i in sec[3])


def test_governing_bill_is_the_final_one_not_the_sum_of_both() -> None:
    project = uuid.uuid4()
    detailed, budget = uuid.uuid4(), uuid.uuid4()
    rows = [
        (detailed, project, "draft", None, "2026-08-01"),
        (budget, project, "final", "2026-08-02", "2026-08-01"),
    ]
    assert governing_boq_id_set(rows) == [budget]


def test_latest_approved_bill_governs_and_archived_never_counts() -> None:
    project = uuid.uuid4()
    old, new, archived, draft = (uuid.uuid4() for _ in range(4))
    rows = [
        (old, project, "final", "2026-05-01", "2026-04-01"),
        (new, project, "final", "2026-09-01", "2026-04-02"),
        (archived, project, "archived", None, "2026-10-01"),
        (draft, project, "draft", None, "2026-10-02"),
    ]
    assert governing_boq_id_set(rows) == [new]


def test_without_an_approved_bill_every_live_bill_counts_per_project() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    a1, a2, b1, gone = (uuid.uuid4() for _ in range(4))
    rows = [
        (a1, a, "draft", None, "2026-01-01"),
        (a2, a, "draft", None, "2026-01-02"),
        (gone, a, "archived", None, "2026-01-03"),
        (b1, b, "final", "2026-02-01", "2026-01-01"),
    ]
    assert set(governing_boq_id_set(rows)) == {a1, a2, b1}


def test_berlin_cost_groups_follow_din_276() -> None:
    sections = {s[0]: s for s in DEMO_TEMPLATES["residential-berlin"].sections}
    assert {"310", "460", "500"} <= set(sections)
    assert not {"300", "540"} & set(sections)
    assert "Baugrube" in sections["310"][1]
    assert "Förderanlagen" in sections["460"][1]
    for ordinal, section in sections.items():
        assert section[2]["din276"] == ordinal
        assert all(item[5]["din276"] == ordinal for item in section[3])
        assert all(item[0].startswith(f"{ordinal}.") for item in section[3])


def test_london_groups_follow_nrm_1_numbering() -> None:
    template = DEMO_TEMPLATES["office-london"]
    titles = {s[0]: s[1] for s in template.sections}
    assert len(titles) == len(template.sections)
    assert "Services" in titles["5"]
    assert "External Works" in titles["8"]
    for ordinal in ("3", "4", "9", "11"):
        assert ordinal in titles
    assert not any(float(i[3]) == 0 for s in template.sections for i in s[3])


def test_london_cost_plan_reconciles_with_the_catalogue_headline() -> None:
    template = DEMO_TEMPLATES["office-london"]
    # Preliminaries are priced items now, so the markups carry no second copy.
    assert not any("Preliminaries" in m[0] for m in template.markups)
    with_markups = _direct_total(template) * 1.05 * 1.05 * 1.03 * 1.03
    assert 44_000_000 <= with_markups <= 46_500_000


def test_vat_follows_the_currency() -> None:
    assert demo_vat_rate("EUR") == Decimal("0.19")
    assert demo_vat_rate("gbp") == Decimal("0.20")
    assert demo_vat_rate("USD") == Decimal("0")


def test_every_plant_order_has_a_value() -> None:
    assert {spec["code"] for spec in _ITEMS} <= set(_ORDER_VALUE)
    assert all(Decimal(v) > 0 for v in _ORDER_VALUE.values())


def test_demo_anchor_is_three_months_back_from_today() -> None:
    assert _demo_anchor(datetime(2026, 11, 14)) == datetime(2026, 8, 1)
    assert _demo_anchor(datetime(2027, 2, 3)) == datetime(2026, 11, 1)
