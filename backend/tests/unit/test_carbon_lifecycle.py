# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Stage​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ maths, EPD parsers, E1 aggregation and the life-cycle validation rule."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.carbon import csrd, lifecycle
from app.modules.carbon.validators import CarbonLifecycleRule

ILCD = b"""<?xml version="1.0" encoding="UTF-8"?>
<processDataSet xmlns="http://lca.jrc.it/ILCD/Process" xmlns:common="http://lca.jrc.it/ILCD/Common"
    xmlns:epd="http://www.iai.kit.edu/EPD/2013">
  <processInformation>
    <dataSetInformation>
      <common:UUID>0b1c2d3e-0000-4000-8000-000000000001</common:UUID>
      <name><baseName xml:lang="en">Concrete C30/37</baseName></name>
    </dataSetInformation>
    <time><common:referenceYear>2024</common:referenceYear><common:dataSetValidUntil>2029</common:dataSetValidUntil></time>
  </processInformation>
  <exchanges><exchange><referenceToFlowDataSet><common:shortDescription>Concrete 1 m3</common:shortDescription></referenceToFlowDataSet></exchange></exchanges>
  <LCIAResults>
    <LCIAResult>
      <referenceToLCIAMethodDataSet><common:shortDescription>Global warming potential - biogenic (GWP-biogenic)</common:shortDescription></referenceToLCIAMethodDataSet>
      <common:other><epd:amount epd:module="A1-A3">-5</epd:amount></common:other>
    </LCIAResult>
    <LCIAResult>
      <referenceToLCIAMethodDataSet><common:shortDescription>Climate change - total (GWP-total)</common:shortDescription></referenceToLCIAMethodDataSet>
      <common:other>
        <epd:amount epd:module="A1-A3">310.5</epd:amount>
        <epd:amount epd:module="A4">6.2</epd:amount>
        <epd:amount epd:module="C3">4</epd:amount>
        <epd:amount epd:module="C4">1.5</epd:amount>
        <epd:amount epd:module="D">-8</epd:amount>
        <epd:amount epd:module="A4" epd:scenario="far">99</epd:amount>
      </common:other>
    </LCIAResult>
  </LCIAResults>
</processDataSet>"""


def test_ilcd_parser_reads_gwp_total_per_module() -> None:
    out = lifecycle.parse_ilcd_epd_xml(ILCD)
    assert out["epd_id"] == "0b1c2d3e-0000-4000-8000-000000000001"
    assert out["product_name"] == "Concrete C30/37"
    assert out["gwp_a1a3"] == Decimal("310.5")
    assert out["gwp_a4"] == Decimal("6.2")
    assert out["gwp_c_total"] == Decimal("5.5")
    assert out["gwp_d_credits"] == Decimal("-8")
    assert out["declared_unit"] == "m3"
    assert out["validity_until"] == "2029-12-31"
    assert out["reference_year"] == 2024


@pytest.mark.parametrize("payload", [b"not xml", b"<root/>", b"<processDataSet/>"])
def test_ilcd_parser_rejects_bad_input(payload: bytes) -> None:
    with pytest.raises(ValueError):
        lifecycle.parse_ilcd_epd_xml(payload)


def test_ilcd_parser_refuses_entity_expansion() -> None:
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><processDataSet>&a;</processDataSet>'
    with pytest.raises(ValueError):
        lifecycle.parse_ilcd_epd_xml(bomb)


def test_csv_parser_semicolon_and_errors() -> None:
    text = (
        "epd_id;product_name;declared_unit;gwp_a1a3;gwp_a4;validity_until\n"
        "E1;Steel rebar;kg;1,2;0,05;2028-01-01\n"
        "E2;Bad;kg;abc;;\n"
    )
    rows, errors = lifecycle.parse_epd_csv(text)
    assert len(rows) == 1 and rows[0]["gwp_a1a3"] == Decimal("1.2") and rows[0]["gwp_a4"] == Decimal("0.05")
    assert errors and "line 3" in errors[0]


def test_csv_parser_missing_columns() -> None:
    rows, errors = lifecycle.parse_epd_csv("epd_id,product_name\nx,y\n")
    assert rows == [] and "gwp_a1a3" in errors[0]


def test_a4_transport_tonne_km() -> None:
    assert lifecycle.compute_a4_transport(24000, 100, "road_truck") == Decimal("256.800")
    assert lifecycle.compute_a4_transport(1000, 10, "rail", factor_per_tkm="0.5") == Decimal("5.0")
    with pytest.raises(ValueError):
        lifecycle.compute_a4_transport(-1, 10)
    with pytest.raises(ValueError):
        lifecycle.compute_a4_transport(1, 10, "teleport")


def test_a5_site_energy_and_waste() -> None:
    parts = lifecycle.compute_a5_site_energy({"diesel": 100}, 1000, "0.4")
    assert parts["fuel_kg"] == Decimal("266.00") and parts["electricity_kg"] == Decimal("400.0")
    assert parts["total_kg"] == Decimal("666.00")
    waste = lifecycle.compute_a5_waste(1000, 2000, 5, "landfill_inert")
    assert waste == Decimal("50.00") + Decimal("0.05") * 2000 * Decimal("0.0013")
    with pytest.raises(ValueError):
        lifecycle.compute_a5_waste(1, 1, 150)


def test_hotspots_group_by_din276() -> None:
    entries = [
        SimpleNamespace(carbon_kg="600", metadata_={"boq_position_id": "p1"}),
        SimpleNamespace(carbon_kg="300", metadata_={"boq_position_id": "p2"}),
        SimpleNamespace(carbon_kg="100", metadata_={}),
    ]
    cls = {"p1": {"din276": "331.10"}, "p2": {"din276": "331"}}
    rows = lifecycle.hotspots_by_group(entries, cls, "din276")
    assert rows[0] == {"group": "331", "carbon_kg": "900", "share_pct": 90.0}
    assert rows[1]["group"] == "unclassified"


def test_budget_swap_and_ages() -> None:
    b = lifecycle.budget_status(1200, 1000)
    assert b["over_budget"] is True and b["used_pct"] == 120.0 and b["remaining_kg"] == "-200"
    swap = lifecycle.compare_swap(120, 310, 145, 205, 152)
    assert swap["co2_delta_kg"] == "-12600" and swap["cost_delta"] == "840"
    assert lifecycle.is_factor_set_outdated(2015, date(2026, 1, 1)) is True
    assert lifecycle.is_factor_set_outdated(2024, date(2026, 1, 1)) is False
    assert lifecycle.is_epd_expired("2025-12-31", date(2026, 1, 1)) is True


def test_e1_aggregation_and_audit_trail() -> None:
    rows = [
        {
            "scope": 1,
            "co2e_kg": "100000",
            "energy_kwh": "400000",
            "data_quality": "measured",
            "source": "s1",
            "source_id": "a",
        },
        {
            "scope": 2,
            "co2e_kg": "50000",
            "market_co2e_kg": "20000",
            "energy_kwh": "100000",
            "renewable_share_pct": "40",
            "data_quality": "calculated",
            "source": "s2",
            "source_id": "b",
        },
        {"scope": 3, "co2e_kg": "250000", "data_quality": "estimated", "source": "s3", "source_id": "c"},
    ]
    dps, audit = csrd.build_e1_datapoints(rows, net_revenue=10_000_000, targets=[{"id": "t"}])
    assert dps["E1-6_scope1"]["value"] == "100.000"
    assert dps["E1-6_total_location"]["value"] == "400.000"
    assert dps["E1-6_total_market"]["value"] == "370.000"
    assert dps["E1-6_intensity_location"]["value"] == "40.000"
    assert dps["E1-5_energy_renewable"]["value"] == "40.000"
    assert dps["E1-5_energy_fossil"]["value"] == "460.000"
    assert dps["E1-6_scope1"]["data_quality"] == "measured"
    assert dps["E1-6_total_location"]["data_quality"] == "estimated"
    assert audit["E1-6_scope3"][0]["source_id"] == "c"
    csv_text = csrd.to_xbrl_csv({"reporting_year": 2026, "datapoints": dps})
    assert "esrs:GrossScope1GreenhouseGasEmissions" in csv_text


def test_templates_and_limits() -> None:
    dps, _ = csrd.build_e1_datapoints([], template="uk_secr")
    assert "E1-6_scope3" not in dps
    hit = csrd.embodied_limit("fr", "multi_family_housing", "2026-03-01")
    assert hit and hit["limit"] == "650"
    assert csrd.embodied_limit("FI", "any", "2026-01-01") is None


def test_exports_render() -> None:
    dps, audit = csrd.build_e1_datapoints([{"scope": 1, "co2e_kg": "1000", "source": "x", "source_id": "1"}])
    rep = {"reporting_year": 2026, "template": "esrs_e1", "company_name": "Demo", "datapoints": dps, "audit": audit}
    assert csrd.to_xlsx(rep)[:2] == b"PK"
    assert csrd.to_pdf(rep)[:4] == b"%PDF"


async def test_lifecycle_rule_reports_each_issue() -> None:
    rule = CarbonLifecycleRule()
    ctx = ValidationContext(
        data={
            "carbon_checks": {
                "no_factor": ["e1"],
                "unit_mismatch": ["e2"],
                "budget": {"over_budget": True, "used_pct": 130},
            }
        }
    )
    results = await rule.validate(ctx)
    ids = {r.rule_id for r in results}
    assert ids == {
        "carbon.lifecycle_checks.no_factor",
        "carbon.lifecycle_checks.unit_mismatch",
        "carbon.lifecycle_checks.over_budget",
    }
    assert await rule.validate(ValidationContext(data={})) == []
