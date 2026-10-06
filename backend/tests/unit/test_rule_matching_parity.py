# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The quantity-rule sandbox and the server apply select the same elements.

The rules page runs a draft rule in the browser ("Test this rule",
``ruleSandbox.ts``) and then on the server (Preview / Apply,
``BIMHubService._rule_matches_element``). When the two disagree the estimator
sees matches in the test and gets nothing from Apply: that is what happened
with comma lists such as ``Wall*, IfcWall*``, which the browser split and the
server fnmatched as one string. Both sides now read the same case table,
``frontend/src/features/bim/__tests__/fixtures/ruleMatchingParity.json``,
and the vitest twin of this file runs it through the sandbox.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.bim_hub.service import BIMHubService

TABLE_PATH = (
    Path(__file__).resolve().parents[3]
    / "frontend"
    / "src"
    / "features"
    / "bim"
    / "__tests__"
    / "fixtures"
    / "ruleMatchingParity.json"
)


def _table() -> dict[str, Any]:
    if not TABLE_PATH.is_file():
        pytest.skip(f"parity table not in this checkout: {TABLE_PATH}")
    return json.loads(TABLE_PATH.read_text(encoding="utf-8"))


def _cases() -> list[dict[str, Any]]:
    if not TABLE_PATH.is_file():
        return []
    return json.loads(TABLE_PATH.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["name"])
def test_server_selects_what_the_sandbox_selects(case: dict[str, Any]) -> None:
    table = _table()
    rule = SimpleNamespace(**case["rule"])
    selected = [
        el["id"]
        for el in table["elements"]
        if BIMHubService._rule_matches_element(
            rule,
            SimpleNamespace(element_type=el["element_type"] or None, properties=el["properties"]),
        )
    ]
    assert selected == case["expected"]


def test_the_table_is_not_empty() -> None:
    assert len(_table()["cases"]) >= 10
    assert len(_table()["quantity_cases"]) >= 10


def _single_cases() -> list[dict[str, Any]]:
    if not TABLE_PATH.is_file():
        return []
    return json.loads(TABLE_PATH.read_text(encoding="utf-8"))["single_cases"]


@pytest.mark.parametrize("case", _single_cases(), ids=lambda c: c["name"])
def test_server_decides_one_element_like_the_sandbox(case: dict[str, Any]) -> None:
    el = case["element"]
    element = SimpleNamespace(element_type=el["element_type"] or None, properties=el["properties"])
    assert BIMHubService._rule_matches_element(SimpleNamespace(**case["rule"]), element) is case["expected"]


def _quantity_cases() -> list[dict[str, Any]]:
    if not TABLE_PATH.is_file():
        return []
    return json.loads(TABLE_PATH.read_text(encoding="utf-8"))["quantity_cases"]


@pytest.mark.parametrize("case", _quantity_cases(), ids=lambda c: c["name"])
def test_server_reads_the_quantity_the_sandbox_reads(case: dict[str, Any]) -> None:
    element = SimpleNamespace(**case["element"])
    qty = BIMHubService._extract_quantity(element, case["source"])
    if case["expected"] is None:
        assert qty is None
    else:
        assert qty is not None
        assert float(qty) == pytest.approx(case["expected"])
