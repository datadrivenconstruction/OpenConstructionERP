"""Berlin and London demo data: standard codes, budget rule, VAT, relative dates."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal

from app.core.demo_projects import DEMO_CATALOG, DEMO_TEMPLATES, _demo_anchor, _generate_module_data
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
    assert demo_vat_rate("USD") == Decimal("0.04125")


def test_vat_is_set_for_every_demo_currency_that_taxes_construction() -> None:
    assert demo_vat_rate("CNY") == Decimal("0.09")
    assert demo_vat_rate("CAD") == Decimal("0.13")
    assert demo_vat_rate("SAR") == Decimal("0.15")
    assert demo_vat_rate("AED") == Decimal("0.05")
    assert demo_vat_rate("GBP") == Decimal("0.20")


def test_london_cost_plan_is_quoted_without_vat() -> None:
    template = DEMO_TEMPLATES["office-london"]
    assert not [m for m in template.markups if m[2] == "tax"]


def _generated(demo_id: str) -> dict:
    return _generate_module_data(DEMO_TEMPLATES[demo_id], uuid.uuid4(), uuid.uuid4(), demo_id, datetime(2026, 8, 1))


def test_generated_change_orders_scale_with_the_project() -> None:
    for demo_id in ("office-shanghai", "residential-berlin", "office-tokyo"):
        template = DEMO_TEMPLATES[demo_id]
        direct = _direct_total(template)
        orders = _generated(demo_id)["change_orders"]
        assert orders
        for order in orders:
            assert 0.003 * direct <= order[5] <= 0.02 * direct, (demo_id, order[0], order[5])


_SHANGHAI_ENGLISH_WORD = re.compile(r"[a-z]{3,}")


def _shanghai_names() -> list[str]:
    t = DEMO_TEMPLATES["office-shanghai"]
    names = [t.project_name, t.boq_name, t.budget_boq_name, t.tender_name, t.project_description, t.boq_description]
    names += [str(v) for v in t.boq_metadata.values()]
    names += [str(v) for v in t.project_metadata.values()]
    for section in t.sections:
        names.append(section[1])
        names += [item[1] for item in section[3]]
    names += [m[0] for m in t.markups]
    names += [c[0] for c in t.tender_companies]
    for package in t.tender_packages:
        names += [package[0], package[1]] + [c[0] for c in package[3]]
    return names


def test_shanghai_demo_carries_no_english_glosses() -> None:
    # Standard codes and designations (GB 50500, LEED, Low-E, C40, kVA) stay; words do not.
    for name in _shanghai_names():
        assert not _SHANGHAI_ENGLISH_WORD.search(name), name


def test_every_plant_order_has_a_value() -> None:
    assert {spec["code"] for spec in _ITEMS} <= set(_ORDER_VALUE)
    assert all(Decimal(v) > 0 for v in _ORDER_VALUE.values())


def test_demo_anchor_is_three_months_back_from_today() -> None:
    assert _demo_anchor(datetime(2026, 11, 14)) == datetime(2026, 8, 1)
    assert _demo_anchor(datetime(2027, 2, 3)) == datetime(2026, 11, 1)


def test_toronto_hst_is_charged_on_the_running_subtotal() -> None:
    for demo_id in ("condo-toronto", "office-toronto"):
        tax = [m for m in DEMO_TEMPLATES[demo_id].markups if m[2] == "tax"]
        assert [(m[1], m[3]) for m in tax] == [(13.0, "cumulative")], demo_id


def _paris():
    return DEMO_TEMPLATES["school-paris"]


def test_paris_markups_are_a_plausible_dpgf_stack_and_the_card_is_the_total_ex_tva() -> None:
    template = _paris()
    stack = {m[0].split("(")[-1].rstrip(")"): m[1] for m in template.markups if m[2] != "tax"}
    assert stack == {"FC": 8.0, "FG": 11.0, "B&A": 5.5}
    assert all(m[3] == "direct_cost" for m in template.markups if m[2] != "tax")
    ex_tva = _direct_total(template) * (1 + sum(stack.values()) / 100)
    card = next(c for c in DEMO_CATALOG if c["demo_id"] == "school-paris")
    assert abs(float(card["budget"].lstrip("\u20ac").rstrip("M")) * 1_000_000 - ex_tva) / ex_tva < 0.02


def test_paris_names_are_french_with_accents_and_no_english_glosses() -> None:
    template = _paris()
    names = [template.tender_name, template.boq_name] + [s[1] for s in template.sections]
    names += [item[1] for s in template.sections for item in s[3]]
    names += [m[0] for m in template.markups]
    names += [p[0] for p in template.tender_packages]
    assert not [n for n in names if re.search(r"\([A-Z][a-z]+(?:[ /+-][A-Za-z]+)*\)$", n) and "(FC)" not in n]
    joined = " ".join(names)
    for unaccented in ("Frais generaux", "Benefice", "Debroussaillage", "Electricite", "exterieure", "beton arme"):
        assert unaccented not in joined, unaccented
    assert "Frais généraux (FG)" in joined and "Bénéfice et aléas (B&A)" in joined
    assert "Gros œuvre" in template.tender_name
    assert "Électricité" in [p[0] for p in template.tender_packages]


def test_berlin_and_paris_hand_written_demo_text_comes_from_the_locale_not_english() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "app" / "core" / "demo_projects.py").read_text(encoding="utf-8")
    for english in (
        "Additional balcony waterproofing",
        "Photovoltaic array expansion",
        "Slab Pour Inspection",
        "Archaeological findings",
        "Foundation drainage detail at elevator pit",
        "CLT panel junction - fire compartmentation detail",
        "Reunion de chantier",
    ):
        assert english not in source, english
    for localized in (
        "Zusätzliche Balkonabdichtung",
        "Extension de la centrale photovoltaïque",
        "Découvertes archéologiques",
        "Fundamententwässerung an der Aufzugsunterfahrt",
        "Réunion de chantier hebdomadaire",
    ):
        assert localized in source, localized


def test_shared_document_register_reads_in_the_project_language() -> None:
    from app.modules.documents.documents_seed import _REGISTER, _in_locale

    for spec in _REGISTER:
        for locale, marker in (("de", "pdf"), ("fr", "pdf")):
            localized = _in_locale(spec, locale)
            assert localized.name != spec.name and localized.name.endswith(marker), (locale, spec.key)
            assert localized.description and localized.tags
        assert _in_locale(spec, "en") is spec
        assert _in_locale(spec, None) is spec
    assert _in_locale(_REGISTER[-1], "fr").name == "Mode opératoire - pose de la façade.pdf"


def test_budget_bill_and_programme_wording_follow_the_template_language() -> None:
    from app.core.demo_projects import _seed_text

    assert _seed_text(DEMO_TEMPLATES["school-paris"], "lump_sum", section="Fondations") == "Fondations - Forfait"
    assert _seed_text(DEMO_TEMPLATES["residential-berlin"], "phases", count=3) == "3 Phasen"
    assert _seed_text(DEMO_TEMPLATES["office-london"], "phases", count=3) == "3 phases"


def test_hand_written_budget_lines_are_tied_to_the_bill_direct_cost() -> None:
    from app.core.demo_projects import _tie_budget_lines

    lines = [
        {
            "original_budget": "700",
            "revised_budget": "700",
            "committed": "350",
            "actual": "70",
            "forecast_final": "700",
        },
        {
            "original_budget": "300",
            "revised_budget": "330",
            "committed": "300",
            "actual": "30",
            "forecast_final": "330",
        },
    ]
    tied = _tie_budget_lines(lines, 1100.0)
    assert sum(Decimal(row["original_budget"]) for row in tied) == Decimal("1100.00")
    assert Decimal(tied[0]["committed"]) == Decimal("385.00")
    # Already tied, or sized to a different scope: untouched.
    assert _tie_budget_lines(lines, 1000.0) is lines
    assert _tie_budget_lines(lines, 5000.0) is lines
