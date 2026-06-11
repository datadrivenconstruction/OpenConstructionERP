"""Regression tests for standards code-range conformance (full audit 2026-06).

Covers three findings:

- FA-STD-001: ``din276.valid_cost_group`` rejected the entire KG 8xx range
  although DIN 276:2018-12 defines Kostengruppe 800 (Finanzierung) and the
  platform's own dach_pack tree offers 810.
- FA-STD-012: ``nrm.valid_element`` rejected NRM 1 group elements 0
  (Facilitating works) and 14 (Inflation), failing the London demo's own
  0.x codes under the rule set it declares.
- FA-STD-013: the uk_pack config served an invented 34-entry "NRM2
  measurement_groups" list; NRM 2 Part 3 defines 41 fixed work sections.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.validation.engine import ValidationContext
from app.core.validation.rules import DIN276ValidCostGroup, NRMValidElement
from app.modules.uk_pack.config import PACK_CONFIG


def _positions(standard: str, codes: list[str]) -> list[dict]:
    return [
        {
            "id": f"p{i}",
            "ordinal": f"01.{i:03d}",
            "description": "Test position",
            "classification": {standard: code},
        }
        for i, code in enumerate(codes, start=1)
    ]


def _run(rule: object, positions: list[dict]) -> dict[str, bool]:
    """Execute an async rule and map element_ref -> passed."""
    ctx = ValidationContext(data={"positions": positions})
    results = asyncio.run(rule.validate(ctx))
    return {r.element_ref: r.passed for r in results}


# ── FA-STD-001: DIN 276 valid cost groups include KG 800 ───────────────────


@pytest.mark.parametrize(
    "code",
    ["100", "210", "330", "440", "550", "630", "760", "800", "810", "890"],
)
def test_din276_accepts_all_2018_top_groups(code: str) -> None:
    """Every KG 100-800 first-level family must pass, including 8xx."""
    by_id = _run(DIN276ValidCostGroup(), _positions("din276", [code]))
    assert by_id["p1"] is True, f"DIN 276 code {code} is valid in 2018-12 and must pass"


@pytest.mark.parametrize("code", ["000", "030", "900", "910", "33", "3300", "ABC", "8A0"])
def test_din276_still_rejects_invalid_codes(code: str) -> None:
    """Truly invalid codes (KG 0xx/9xx, wrong length, non-digits) keep failing."""
    by_id = _run(DIN276ValidCostGroup(), _positions("din276", [code]))
    assert by_id["p1"] is False, f"DIN 276 code {code} is invalid and must fail"


# ── FA-STD-012: NRM 1 group elements 0-14 are all valid ────────────────────


@pytest.mark.parametrize(
    "code",
    ["0.1", "0.5", "1.1", "2.6.1", "9.2", "13.2", "14", "14.1"],
)
def test_nrm_accepts_groups_0_through_14(code: str) -> None:
    """NRM 1 (3rd ed.) defines group elements 0-14; 0.x and 14.x must pass."""
    by_id = _run(NRMValidElement(), _positions("nrm", [code]))
    assert by_id["p1"] is True, f"NRM code {code} is valid (groups 0-14) and must pass"


@pytest.mark.parametrize("code", ["15", "15.1", "99.9", "00.1", "2.x", "abc"])
def test_nrm_still_rejects_invalid_codes(code: str) -> None:
    """Codes outside groups 0-14 or with a non-numeric shape keep failing."""
    by_id = _run(NRMValidElement(), _positions("nrm", [code]))
    assert by_id["p1"] is False, f"NRM code {code} is invalid and must fail"


def test_nrm_london_demo_facilitating_works_codes_pass() -> None:
    """The London demo classifies rows 0.1-0.7 - none may error under nrm."""
    codes = [f"0.{n}" for n in range(1, 8)]
    by_id = _run(NRMValidElement(), _positions("nrm", codes))
    assert all(by_id.values()), f"Group 0 sub-codes must all pass, got {by_id}"


# ── FA-STD-013: uk_pack serves the real NRM 2 work-section table ───────────


def _nrm2_groups() -> list[dict]:
    for standard in PACK_CONFIG["standards"]:
        if standard["code"] == "NRM2":
            return standard["measurement_groups"]
    raise AssertionError("NRM2 standard missing from uk_pack config")


def test_nrm2_work_sections_are_the_41_official_sections() -> None:
    groups = _nrm2_groups()
    assert len(groups) == 41, "NRM 2 Part 3 defines exactly 41 work sections"
    assert [g["number"] for g in groups] == [str(n) for n in range(1, 42)]


@pytest.mark.parametrize(
    ("number", "title"),
    [
        ("1", "Preliminaries"),
        ("5", "Excavating and filling"),
        ("11", "In-situ concrete works"),
        ("14", "Masonry"),
        ("24", "Doors, shutters and hatches"),
        ("34", "Drainage below ground"),
        (
            "41",
            "Builder's work in connection with mechanical, electrical and transportation installations",
        ),
    ],
)
def test_nrm2_work_section_titles_match_rics_table(number: str, title: str) -> None:
    by_number = {g["number"]: g["title"] for g in _nrm2_groups()}
    assert by_number[number] == title
