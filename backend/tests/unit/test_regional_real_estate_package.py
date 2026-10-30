# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""GCC real estate package data: modules exist, demo registered, SA profile sourced, Ejar file shape."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from app.core.party_identifiers import sa as sa_ids
from app.core.regional_packages import country_profile, get_regional_package, module_closure
from app.modules.leasing.country_rules import tenant_identifier_schemes
from app.modules.leasing.export_profiles import enrich_row, load_profiles, render_csv, to_hijri

APP = Path(__file__).resolve().parents[2] / "app"


def test_every_package_module_exists_on_disk() -> None:
    for module in module_closure("real_estate_gcc"):
        assert (APP / "modules" / module / "manifest.py").exists(), module


def test_package_demo_is_registered() -> None:
    from app.core import demo_packs  # noqa: F401 - registers pack templates
    from app.core.demo_projects import DEMO_TEMPLATES
    from app.core.demo_real_estate import REAL_ESTATE_DEMOS

    demo_id = get_regional_package("real_estate_gcc")["demo_id"]
    assert demo_id in DEMO_TEMPLATES
    assert DEMO_TEMPLATES[demo_id].currency == "SAR"
    assert REAL_ESTATE_DEMOS[demo_id] == ("real_estate_gcc", "SA")


def test_saudi_profile_names_its_sources() -> None:
    sa = country_profile("real_estate_gcc", "sa")
    assert sa["currency"] == "SAR"
    assert sa["vat"]["standard_rate_percent"] == "15"
    assert sa["offplan_regulator"]["code"] == "REGA"
    assert sa["lease_export_profile"] in load_profiles()
    for part in (sa["vat"], sa["offplan_regulator"]):
        assert part["source_url"].startswith("https://")


def test_saudi_lease_rules_require_a_tenant_identifier_with_a_source() -> None:
    rules = json.loads((APP / "core/country_data/lease_rules.json").read_text(encoding="utf-8"))["countries"]["SA"]
    assert rules["source_url"].startswith("https://")
    assert "deposit_cap_months" not in rules
    assert "national_id" in tenant_identifier_schemes("SA")


def test_saudi_national_id_check() -> None:
    assert sa_ids.check_national_id("1045823110").valid
    assert sa_ids.check_national_id("2045823110").details["holder"] == "resident"
    assert not sa_ids.check_national_id("3045823110").valid
    assert not sa_ids.check_national_id("12345").valid
    assert sa_ids.check_national_id("١٠٤٥٨٢٣١١٠").valid


def test_hijri_conversion() -> None:
    assert to_hijri("2026-01-01") == "1447-07-12"
    assert to_hijri("") == ""
    assert to_hijri("not a date") == ""


def test_ejar_file_carries_tenant_identity_hijri_dates_and_annual_rent() -> None:
    row = {
        "code": "LS-001",
        "unit_ref": "A-G01",
        "unit_label": "Shop G01",
        "start_date": "2026-01-01",
        "end_date": "2028-12-31",
        "term_months": 36,
        "rent_amount": "15000.00",
        "frequency": "quarterly",
        "deposit": "15000.00",
        "currency": "SAR",
        "tax_rate": "15.0000",
        "ext_refs": {"use": "commercial"},
    }
    tenant = {
        "name": "Noura Al Otaibi",
        "phone": "+966 500000000",
        "identifiers": [{"scheme": "national_id", "value": "1045823110"}],
    }
    body, media, ext = render_csv(load_profiles()["ejar"], [enrich_row(row, tenant)])
    assert (media, ext) == ("text/csv", "csv")
    text = body.decode("utf-8-sig")
    out = next(csv.DictReader(io.StringIO(text)))
    assert out["tenant_id_type"] == "national_id"
    assert out["tenant_id_number"] == "1045823110"
    assert out["tenant_type"] == "individual"
    assert out["contract_type"] == "commercial"
    assert out["start_date_hijri"] == "1447-07-12"
    assert out["annual_rent"] == "60000.00"
    assert out["payments_per_year"] == "4"
    assert out["number_of_payments"] == "12"
    assert out["vat_rate_percent"] == "15"
