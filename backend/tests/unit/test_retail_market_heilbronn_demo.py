# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integrity tests for the Retail Market Heilbronn public showcase demo.

The template (``app/core/demo_packs/retail_market_heilbronn.py``) is the
ninth showcase project and carries a reconciled DIN 276 cost frame: 16 LV
sections that map 1:1 to procurement units (Vergabeeinheiten), each section
summing EXACTLY to its VE budget and the LV grand total landing on
7,905,000.00 EUR net to the cent. These tests pin that money contract plus
the registry wiring (DEMO_TEMPLATES / SHOWCASE_DEMO_IDS / catalog), so a
later densification pass (swapping ``_SAMPLE_POSITIONS``) cannot silently
drift the section budgets.
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.core.demo_projects import (
    _PACK_DEMO_TYPE,
    DEMO_CATALOG,
    DEMO_TEMPLATES,
    SHOWCASE_DEMO_IDS,
)

DEMO_ID = "retail-market-heilbronn"

# Reconciled procurement-unit budgets (net EUR, price level Heilbronn 2026),
# keyed by LV section ordinal. Sum = 7,905,000 = KG 200-600 (8,090,000)
# minus the 185,000 KG 220 connection fees that are not tendered works.
_VE_BUDGETS: dict[str, Decimal] = {
    "01": Decimal("150000.00"),
    "02": Decimal("365000.00"),
    "04": Decimal("820000.00"),
    "05": Decimal("580000.00"),
    "06": Decimal("540000.00"),
    "07": Decimal("410000.00"),
    "08": Decimal("250000.00"),
    "09": Decimal("280000.00"),
    "14": Decimal("630000.00"),
    "15": Decimal("830000.00"),
    "16": Decimal("680000.00"),
    "17": Decimal("520000.00"),
    "18": Decimal("1020000.00"),
    "19": Decimal("130000.00"),
    "20": Decimal("560000.00"),
    "21": Decimal("140000.00"),
}

_LV_GRAND_TOTAL = Decimal("7905000.00")

_ALLOWED_UNITS = {"m", "m2", "m3", "t", "pcs", "lsum"}

_OZ_PATTERN = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")


def _template():
    template = DEMO_TEMPLATES.get(DEMO_ID)
    assert template is not None, f"{DEMO_ID} missing from DEMO_TEMPLATES"
    return template


def test_registered_as_ninth_showcase() -> None:
    """The demo is appended as the ninth showcase id, replacing nothing."""
    assert DEMO_ID in DEMO_TEMPLATES
    assert len(SHOWCASE_DEMO_IDS) == 9
    assert SHOWCASE_DEMO_IDS[-1] == DEMO_ID
    # The original eight stay untouched and in order.
    assert SHOWCASE_DEMO_IDS[:8] == (
        "residential-berlin",
        "warehouse-dubai",
        "school-paris",
        "medical-us",
        "office-shanghai",
        "residential-saopaulo",
        "govt-building-delhi",
        "condo-toronto",
    )


def test_catalog_row() -> None:
    """The marketplace catalog row is derived with the right identity."""
    row = next((c for c in DEMO_CATALOG if c["demo_id"] == DEMO_ID), None)
    assert row is not None, f"{DEMO_ID} missing from DEMO_CATALOG"
    assert row["country"] == "DE"
    assert row["currency"] == "EUR"
    assert row["type"] == "Retail"
    assert _PACK_DEMO_TYPE.get(DEMO_ID) == "Retail"
    assert row["sections"] == len(_VE_BUDGETS)
    assert row["positions"] >= 80
    assert str(row.get("budget", "")).strip(), "catalog budget label is empty"


def test_template_identity() -> None:
    """Founder-locked naming, code, locale and classification config."""
    template = _template()
    assert template.project_name == "Lebensmittelmarkt Heilbronn"
    assert template.project_metadata.get("name_en") == "Retail Market Heilbronn"
    assert template.project_code == "LM-HN-2026-01"
    assert template.region == "DACH"
    assert template.classification_standard == "din276"
    assert template.currency == "EUR"
    assert template.locale == "de"
    assert template.validation_rule_sets == ["din276", "gaeb", "boq_quality"]
    # The two fictional legal entities.
    assert template.project_metadata.get("client") == "Sueddeutsche Handelsimmobilien GmbH"
    assert template.project_metadata.get("operator") == "Sueddeutsche Lebensmittelmaerkte GmbH"
    # Structured address with coordinates (offline map + weather).
    address = template.address or {}
    assert address.get("city") == "Heilbronn"
    assert address.get("country") == "Germany"
    assert isinstance(address.get("lat"), float)
    assert isinstance(address.get("lng"), float)


def test_markups_and_5d_overrides() -> None:
    """DIN-style markups and the week-19 finance tuning."""
    template = _template()
    assert [(m[1], m[2], m[3]) for m in template.markups] == [
        (9.0, "overhead", "direct_cost"),
        (19.0, "tax", "cumulative"),
    ]
    assert template.planned_budget == 9_430_000.0
    assert template.actual_spend_ratio == 0.30
    assert template.spi_override == 0.97
    assert template.cpi_override == 1.03


def test_sections_sum_exactly_to_ve_budgets() -> None:
    """Every LV section sums to its procurement-unit budget to the cent.

    This is the core money contract: detailed sample rows plus the lump-sum
    remainder row must reproduce the reconciled VE budget exactly, and the
    grand total must land on 7,905,000.00 EUR net. All arithmetic in Decimal,
    never float (house rule for money).
    """
    template = _template()
    seen = {}
    for ordinal, _title, _cls, items in template.sections:
        section_sum = sum(
            (Decimal(str(qty)) * Decimal(str(rate)) for _oz, _desc, _unit, qty, rate, _c in items),
            Decimal("0"),
        )
        seen[ordinal] = section_sum
    assert set(seen) == set(_VE_BUDGETS), f"section ordinals drifted: {sorted(seen)}"
    for ordinal, expected in _VE_BUDGETS.items():
        assert seen[ordinal] == expected, f"LV {ordinal}: {seen[ordinal]} != budget {expected}"
    assert sum(seen.values(), Decimal("0")) == _LV_GRAND_TOTAL


def test_positions_are_structurally_sound() -> None:
    """OZ scheme, units, money precision and uniqueness across all rows."""
    template = _template()
    ordinals: list[str] = []
    total_rows = 0
    for sec_ordinal, title, sec_cls, items in template.sections:
        assert sec_cls.get("din276"), f"LV {sec_ordinal} has no DIN 276 code"
        assert title.strip(), f"LV {sec_ordinal} has an empty title"
        # Section titles feed BudgetLine.category, a String(100) column; a
        # longer title used to abort the whole install transaction on PG.
        assert len(title) <= 100, f"LV {sec_ordinal} title is {len(title)} chars (> 100)"
        assert items, f"LV {sec_ordinal} has no positions"
        for oz, desc, unit, qty, rate, cls in items:
            total_rows += 1
            ordinals.append(oz)
            assert _OZ_PATTERN.match(oz), f"bad OZ {oz!r}"
            assert oz.startswith(f"{sec_ordinal}."), f"OZ {oz} outside section {sec_ordinal}"
            assert desc.strip(), f"{oz}: empty description"
            assert unit in _ALLOWED_UNITS, f"{oz}: unexpected unit {unit!r}"
            assert qty > 0, f"{oz}: non-positive quantity"
            assert rate > 0, f"{oz}: non-positive rate"
            assert cls.get("din276"), f"{oz}: missing DIN 276 code"
            # Money stays exact: rates carry max 2 decimals and qty * rate
            # produces no sub-cent dust that stringification would round.
            rate_dec = Decimal(str(rate))
            assert -rate_dec.as_tuple().exponent <= 2, f"{oz}: rate {rate} has sub-cent digits"
            row_total = Decimal(str(qty)) * rate_dec
            assert row_total == row_total.quantize(Decimal("0.01")), f"{oz}: total {row_total} not exact to the cent"
    assert total_rows >= 80, f"only {total_rows} positions (pack bar is 80)"
    assert len(ordinals) == len(set(ordinals)), "duplicate OZ ordinals"


def test_tender_factors_reproduce_net_bids() -> None:
    """The owner direct-award bids price out to their net figures.

    install_demo_project prices single-package bids as
    ``round(grand_total * factor, 2)``; the factors are authored as
    ``bid / grand_total`` so the three VP-07 bids come back exactly.
    """
    template = _template()
    expected = [Decimal("812400"), Decimal("858900"), Decimal("901200")]
    assert len(template.tender_companies) == len(expected)
    for (_co, email, factor), bid in zip(template.tender_companies, expected, strict=True):
        assert "@" in email
        priced = Decimal(str(round(float(_LV_GRAND_TOTAL) * factor, 2)))
        assert priced == bid, f"factor {factor} prices to {priced}, expected {bid}"


async def test_install_is_end_to_end_and_idempotent() -> None:
    """A fresh install seeds the full project; a re-run never duplicates.

    Mirrors the every-boot backfill in main.py: the first call creates the
    project (BOQ summing to the LV grand total, project code, demo metadata,
    the two legal-entity contacts), the second call short-circuits on the
    ``metadata_["demo_id"]`` dedupe and leaves exactly one project behind.
    """
    import uuid

    from sqlalchemy import select

    from app.core.demo_projects import install_demo_project
    from app.modules.contacts.models import Contact
    from app.modules.projects.models import Project
    from tests._pg import transactional_session

    async with transactional_session() as session:
        result = await install_demo_project(session, DEMO_ID)
        assert result.get("already_installed") is not True
        assert result["sections"] == len(_VE_BUDGETS)
        assert result["positions"] >= 80
        assert Decimal(str(result["grand_total"])) == _LV_GRAND_TOTAL

        project = (
            await session.execute(select(Project).where(Project.id == uuid.UUID(result["project_id"])))
        ).scalar_one()
        assert project.name == "Lebensmittelmarkt Heilbronn"
        assert project.project_code == "LM-HN-2026-01"
        assert project.currency == "EUR"
        assert project.country_code == "DE"
        assert (project.metadata_ or {}).get("demo_id") == DEMO_ID

        # The two fictional legal entities arrive as contacts.
        contacts = (
            (await session.execute(select(Contact).where(Contact.metadata_["demo_id"].as_string() == DEMO_ID)))
            .scalars()
            .all()
        )
        companies = {c.company_name for c in contacts}
        assert "Sueddeutsche Handelsimmobilien GmbH" in companies
        assert "Sueddeutsche Lebensmittelmaerkte GmbH" in companies

        # Idempotent re-run (the every-boot backfill path).
        again = await install_demo_project(session, DEMO_ID)
        assert again.get("already_installed") is True
        demo_projects = [
            p
            for p in (await session.execute(select(Project))).scalars().all()
            if (p.metadata_ or {}).get("demo_id") == DEMO_ID
        ]
        assert len(demo_projects) == 1
