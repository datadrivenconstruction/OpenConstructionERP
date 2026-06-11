# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integrity tests for the Retail Market Heilbronn public showcase demo.

The template (``app/core/demo_packs/retail_market_heilbronn.py``) is the
ninth showcase project and carries a reconciled DIN 276 cost frame as a
FULL LV: 303 positions in 16 sections that map 1:1 to procurement units
(Vergabeeinheiten). Two exactness invariants hold simultaneously, to the
cent, and are pinned here as the money contract:

* every LV section sums EXACTLY to its procurement-unit budget, grand
  total 7,905,000.00 EUR net;
* every DIN 276 cost group (2nd level) sums EXACTLY to the reconciled
  cost plan (KG 200-600 without the KG 220 connection fees), including
  the cross-section groups KG 310/320/330/340/350/360/440.

On top of that, the canonical building geometry drives the quantities
(consistency rules R-01..R-16 of the design dossier); the spot checks at
the bottom pin the rule-derived quantities to their OZ rows. The registry
wiring (DEMO_TEMPLATES / SHOWCASE_DEMO_IDS / catalog) is pinned too.
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

# Reconciled DIN 276 cost plan, 2nd level (net EUR). This is the kg_plan
# of the design dossier minus KG 220 (185,000 EUR public connection fees,
# levied by the utilities and not part of any tendered LV) and minus
# KG 700 (professional fees, not tendered works). Several groups are
# carried by more than one procurement unit (e.g. KG 320 = VE-02 + VE-04
# + VE-06, KG 440 = VE-16 + VE-17), so this is a genuinely independent
# second invariant on top of the per-section budgets.
_KG2_BUDGETS: dict[str, Decimal] = {
    "210": Decimal("35000.00"),
    "230": Decimal("60000.00"),
    "310": Decimal("270000.00"),
    "320": Decimal("900000.00"),
    "330": Decimal("740000.00"),
    "340": Decimal("280000.00"),
    "350": Decimal("110000.00"),
    "360": Decimal("790000.00"),
    "370": Decimal("60000.00"),
    "390": Decimal("150000.00"),
    "410": Decimal("160000.00"),
    "420": Decimal("250000.00"),
    "430": Decimal("220000.00"),
    "440": Decimal("1060000.00"),
    "450": Decimal("100000.00"),
    "470": Decimal("830000.00"),
    "480": Decimal("40000.00"),
    "510": Decimal("240000.00"),
    "520": Decimal("540000.00"),
    "530": Decimal("130000.00"),
    "540": Decimal("140000.00"),
    "550": Decimal("100000.00"),
    "610": Decimal("560000.00"),
    "690": Decimal("140000.00"),
}

# Reconciled DIN 276 cost plan, 1st level, restricted to the LV scope.
# KG 200 appears as 95,000 because the 185,000 KG 220 fees are outside
# the LV (kg_plan KG 200 = 280,000); KG 300-600 match kg_plan exactly.
_KG1_BUDGETS: dict[str, Decimal] = {
    "200": Decimal("95000.00"),
    "300": Decimal("3300000.00"),
    "400": Decimal("2660000.00"),
    "500": Decimal("1150000.00"),
    "600": Decimal("700000.00"),
}

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
    assert row["positions"] >= 300
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


def test_kg_rollups_match_cost_plan_exactly() -> None:
    """Every DIN 276 cost group reproduces the reconciled KG plan.

    The second half of the money contract: independent of how the scope is
    cut into procurement units, the per-cost-group sums across ALL
    sections must equal the kg_plan amounts to the cent, on the 2nd level
    (KG 210..690) and rolled up to the 1st level (KG 200..600). Decimal
    arithmetic only.
    """
    template = _template()
    kg_sums: dict[str, Decimal] = {}
    for _ordinal, _title, _cls, items in template.sections:
        for oz, _desc, _unit, qty, rate, cls in items:
            kg = cls.get("din276")
            assert kg, f"{oz}: missing DIN 276 code"
            kg_sums[kg] = kg_sums.get(kg, Decimal("0")) + Decimal(str(qty)) * Decimal(str(rate))
    assert set(kg_sums) == set(_KG2_BUDGETS), (
        f"cost groups drifted: extra={sorted(set(kg_sums) - set(_KG2_BUDGETS))}, "
        f"missing={sorted(set(_KG2_BUDGETS) - set(kg_sums))}"
    )
    for kg, expected in _KG2_BUDGETS.items():
        assert kg_sums[kg] == expected, f"KG {kg}: {kg_sums[kg]} != cost plan {expected}"
    kg1_sums: dict[str, Decimal] = {}
    for kg, value in kg_sums.items():
        kg1 = kg[0] + "00"
        kg1_sums[kg1] = kg1_sums.get(kg1, Decimal("0")) + value
    assert kg1_sums == _KG1_BUDGETS


def test_full_lv_has_no_remainder_rows() -> None:
    """The LV is fully detailed: no budget-balancing placeholder rows.

    The slice-1 scaffold closed undetailed sections with lump rows marked
    'Detaillierung folgt'; the full LV must not contain any.
    """
    template = _template()
    for _ordinal, _title, _cls, items in template.sections:
        for oz, desc, _unit, _qty, _rate, _c in items:
            assert "Detaillierung folgt" not in desc, f"{oz} is still a remainder placeholder"


def test_quantities_derive_from_building_geometry() -> None:
    """Spot-pin the rule-derived quantities to their LV rows.

    Implements the quantity-consistency rules of the design dossier
    (R-01..R-16): the same canonical geometry that parameterizes the
    procedural 3D model must show up as position quantities, so BOQ <->
    BIM quantity checks come back green. Keyed by OZ; a drifted quantity
    or a renumbered row fails loudly.
    """
    template = _template()
    rows: dict[str, tuple[str, float]] = {}
    for _ordinal, _title, _cls, items in template.sections:
        for oz, _desc, unit, qty, _rate, _c in items:
            rows[oz] = (unit, qty)

    footprint_m2 = 2720.0  # 68.0 x 40.0 m
    work_area_m2 = 2774.0  # R-02: footprint x 1.02
    perimeter_m = 216.0  # R-03
    expected: dict[str, tuple[str, float]] = {
        "04.01.0090": ("m3", footprint_m2 * 0.20),  # R-01 slab volume = 544 m3
        "04.01.0020": ("m2", work_area_m2),  # R-02 sub-base
        "04.01.0030": ("m2", work_area_m2),  # R-02 blinding
        "05.01.0010": ("m2", work_area_m2),  # R-03 roof deck = footprint x 1.02
        "05.01.0030": ("m2", work_area_m2),  # R-03 roof insulation
        "05.01.0040": ("m2", work_area_m2),  # R-03 roof membrane
        "05.01.0050": ("m", perimeter_m),  # R-03 parapet capping
        "04.01.0050": ("m", perimeter_m),  # R-03 frost skirt
        "06.01.0010": ("m", perimeter_m),  # R-03 precast socket panels
        "16.02.0090": ("m", perimeter_m),  # R-03 ring earth electrode
        "07.01.0010": ("m2", 1292.0),  # R-04 sandwich facade share
        "08.01.0010": ("m2", 120.0),  # R-04 curtain wall 24.0 x 5.0
        "08.01.0030": ("m2", 42.0),  # R-04 window band 28.0 x 1.5
        "06.02.0010": ("pcs", 36.0),  # R-05 columns = 12 axes x 3 rows
        "06.03.0010": ("pcs", 12.0),  # R-05 main binders 23.8 m
        "06.03.0020": ("pcs", 12.0),  # R-05 side binders 16.2 m
        "06.03.0030": ("pcs", 22.0),  # R-05 edge beams = (12 - 1) x 2
        "04.01.0040": ("pcs", 36.0),  # R-06 pocket foundations = columns
        "06.01.0020": ("pcs", 36.0),  # R-06 one grout joint per column
        "04.01.0060": ("t", 38.0),  # R-07 rebar foundations
        "18.01.0020": ("m2", 4590.0),  # R-08 frost layer = asphalt + pavers
        "18.03.0010": ("m2", 4590.0),  # R-08 geogrid on the same area
        "18.01.0030": ("m2", 3140.0),  # R-08 asphalt = 2,380 lanes + 760 yard
        "18.03.0020": ("m2", 3140.0),  # R-08 binder course on the asphalt area
        "18.01.0040": ("m2", 1450.0),  # R-08/R-09 permeable pavers
        "18.03.0040": ("m2", 220.0),  # R-09 walkways
        "02.01.0020": ("m3", footprint_m2 * 0.25),  # R-10 topsoil building field
        "18.01.0010": ("m3", 2028.0),  # R-10 topsoil external = (9,480 - 2,720) x 0.30
        "05.01.0070": ("pcs", 22.0),  # R-11 roof drains: 11 gullies + 11 overflows
        "14.02.0030": ("pcs", 11.0),  # R-11 one internal downpipe per gully
        "17.01.0010": ("pcs", 660.0),  # R-12 PV modules a 440 Wp = 290.4 kWp
        "16.01.0030": ("m", 539.0),  # R-13 light band = 1,672 m2 VK / 3.1 m grid
        "18.01.0090": ("m", 952.0),  # R-16 marking = 112 stalls x 8.5 m
        "18.03.0090": ("pcs", 24.0),  # special stalls: 6 accessible + 6 parent-child + 12 EV
        "17.03.0010": ("pcs", 2.0),  # 2 DC chargers a 2 points
        "17.03.0020": ("pcs", 4.0),  # 4 AC wallboxes a 2 points -> 12 points total
        "15.02.0010": ("m", 48.0),  # 48 lfm chilled cabinets
        "15.02.0020": ("m", 22.0),  # 22 lfm frozen cabinets
        "15.02.0030": ("m", 6.0),  # 6 lfm serve-over
        "05.01.0060": ("pcs", 8.0),  # 8 NRWG rooflights
        "08.01.0060": ("pcs", 6.0),  # 6 steel doors T30/RC2
        "14.02.0050": ("pcs", 4.0),  # 4 wall hydrants type S
        "18.05.0010": ("pcs", 19.0),  # 19 trees
        "04.03.0010": ("m2", 120.0),  # plant mezzanine 120 m2
        "14.01.0020": ("m2", 1650.0),  # underfloor heating 1,650 m2
        "17.01.0020": ("m2", 1440.0),  # PV-covered roof = 60 % of suitable area
        "20.01.0030": ("pcs", 4.0),  # 4 self-checkouts (+ 2 belt checkouts = 6)
        "20.02.0010": ("pcs", 3.0),  # 3 bake-off ovens a 18 kW
        "21.01.0010": ("pcs", 2.0),  # 2 reverse-vending machines
    }
    for oz, (unit, qty) in expected.items():
        assert oz in rows, f"rule-derived row {oz} missing from the LV"
        got_unit, got_qty = rows[oz]
        assert got_unit == unit, f"{oz}: unit {got_unit!r} != {unit!r}"
        assert got_qty == qty, f"{oz}: quantity {got_qty} != derived {qty}"


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
    assert total_rows >= 300, f"only {total_rows} positions (full-LV bar is 300)"
    assert len(ordinals) == len(set(ordinals)), "duplicate OZ ordinals"


def test_tender_packages_reproduce_net_bids() -> None:
    """The four procurement packages price out to their exact net bids.

    install_demo_project prices multi-package bids as
    ``round((grand_total / n_packages) * factor, 2)``; the factors are
    authored as ``net_bid / (grand_total / 4)`` so every dossier bid (VP-07
    awarded, VP-09/10/11 pending) comes back to the cent. Status reflects the
    week-19 snapshot using the recognised tender statuses.
    """
    template = _template()
    # install_demo_project does the pricing in float, the way the template
    # factors are authored; mirror that here (the bids are whole euros).
    pkg_share = float(_LV_GRAND_TOTAL) / 4
    expected: dict[str, tuple[str, list[Decimal]]] = {
        "VP-07": ("awarded", [Decimal("812400"), Decimal("858900"), Decimal("901200")]),
        "VP-09": ("collecting", [Decimal("981400"), Decimal("1041200"), Decimal("1118900")]),
        "VP-10": ("evaluating", [Decimal("528700"), Decimal("559400")]),
        "VP-11": ("evaluating", [Decimal("497800"), Decimal("534600"), Decimal("562300")]),
    }
    assert len(template.tender_packages) == 4
    for (name, _desc, status, companies), code in zip(template.tender_packages, expected, strict=True):
        assert name.startswith(code), f"package order drifted at {code}: {name!r}"
        want_status, want_bids = expected[code]
        assert status == want_status, f"{code}: status {status!r} != {want_status!r}"
        assert len(companies) == len(want_bids), f"{code}: bid count drifted"
        for (_co, email, factor), bid in zip(companies, want_bids, strict=True):
            assert "@" in email
            priced = Decimal(str(round(pkg_share * factor, 2)))
            assert priced == bid, f"{code} factor {factor} prices to {priced}, expected {bid}"


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
    from app.modules.finance.models import ProjectBudget
    from app.modules.projects.models import Project
    from app.modules.schedule.models import Activity, Schedule
    from app.modules.tendering.models import TenderBid, TenderPackage
    from tests._pg import transactional_session

    async with transactional_session() as session:
        result = await install_demo_project(session, DEMO_ID)
        assert result.get("already_installed") is not True
        assert result["sections"] == len(_VE_BUDGETS)
        assert result["positions"] >= 300
        assert Decimal(str(result["grand_total"])) == _LV_GRAND_TOTAL

        # The hand-authored lifecycle content (slice 4) is seeded in full.
        assert result["contacts"] == 18, "all 18 stakeholders S01..S18"
        assert result["risks"] == 13, "all 13 risks R01..R13"
        assert result["change_orders"] == 4, "all 4 change orders N-01..N-04"
        assert result["documents"] == 31, "all 31 documents D01..D31"
        assert result["punchlist"] == 10, "all 10 punch items M-001..M-010"
        assert result["inspections"] == 4, "all 4 inspections I-01..I-04"
        assert result["ncrs"] == 2, "both NCRs (NCR-01 closed, NCR-02 open)"
        assert result["finance_budgets"] == 7, "7 DIN 276 budget lines + reserve"

        project = (
            await session.execute(select(Project).where(Project.id == uuid.UUID(result["project_id"])))
        ).scalar_one()
        assert project.name == "Lebensmittelmarkt Heilbronn"
        assert project.project_code == "LM-HN-2026-01"
        assert project.currency == "EUR"
        assert project.country_code == "DE"
        assert (project.metadata_ or {}).get("demo_id") == DEMO_ID

        # The two fictional legal entities are among the 18 seeded contacts,
        # and the GC / direct-award firms are present too.
        contacts = (
            (await session.execute(select(Contact).where(Contact.metadata_["demo_id"].as_string() == DEMO_ID)))
            .scalars()
            .all()
        )
        assert len(contacts) == 18
        companies = {c.company_name for c in contacts}
        assert "Sueddeutsche Handelsimmobilien GmbH" in companies
        assert "Sueddeutsche Lebensmittelmaerkte GmbH" in companies
        assert "Trautwein Bau GmbH & Co. KG" in companies
        assert "Stadt Heilbronn, Planungs- und Baurechtsamt" in companies

        # Finance budget lines respect the single-currency EUR frame and the
        # Decimal-string money rule (no float drift): the 7 lines sum to the
        # approved 9,430,000 budget and the committed total matches the story.
        budget_lines = (
            (await session.execute(select(ProjectBudget).where(ProjectBudget.project_id == project.id))).scalars().all()
        )
        assert len(budget_lines) == 7
        assert sum(Decimal(b.original_budget) for b in budget_lines) == Decimal("9430000.00")
        assert sum(Decimal(b.committed) for b in budget_lines) == Decimal("6571400.00")
        assert sum(Decimal(b.actual) for b in budget_lines) == Decimal("2817800.00")

        # Four tender packages with the awarded VP-07 and three pending ones.
        packages = (
            (await session.execute(select(TenderPackage).where(TenderPackage.project_id == project.id))).scalars().all()
        )
        assert len(packages) == 4
        statuses = sorted(p.status for p in packages)
        assert statuses == ["awarded", "collecting", "evaluating", "evaluating"]
        awarded = next(p for p in packages if p.status == "awarded")
        awarded_bids = (
            (await session.execute(select(TenderBid).where(TenderBid.package_id == awarded.id))).scalars().all()
        )
        # VP-07 winning bid prices exactly to its 812,400 EUR net figure.
        assert Decimal("812400.00") in {Decimal(b.total_amount) for b in awarded_bids}

        # 35 schedule activities are seeded on a single active schedule.
        activities = (
            (await session.execute(select(Activity).join(Schedule).where(Schedule.project_id == project.id)))
            .scalars()
            .all()
        )
        assert len(activities) == 35

        # Idempotent re-run (the every-boot backfill path).
        again = await install_demo_project(session, DEMO_ID)
        assert again.get("already_installed") is True
        demo_projects = [
            p
            for p in (await session.execute(select(Project))).scalars().all()
            if (p.metadata_ or {}).get("demo_id") == DEMO_ID
        ]
        assert len(demo_projects) == 1
