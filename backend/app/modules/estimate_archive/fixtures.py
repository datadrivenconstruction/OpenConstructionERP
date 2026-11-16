# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The worked examples of the sealed-estimate spec as payloads.

Shared by the tests and the demo seed, so the numbers a visitor sees on the
demo projects are the numbers the tests prove.
"""

from __future__ import annotations

from typing import Any

from app.modules.estimate_archive import engine


def _res(kind: str, code: str, description: str, unit: str, qty: str, rate: str, **extra: str) -> dict[str, Any]:
    return {"type": kind, "code": code, "name": description, "unit": unit, "quantity": qty, "unit_rate": rate, **extra}


def _mk(mid: str, name: str, pct: str, apply_to: str, order: int, category: str = "overhead") -> dict[str, Any]:
    return {
        "id": mid,
        "name": name,
        "category": category,
        "markup_type": "percentage",
        "percentage": pct,
        "fixed_amount": "0",
        "apply_to": apply_to,
        "sort_order": order,
        "is_active": True,
    }


def example_de_trench() -> dict[str, Any]:
    """Example 1: water main, VOB/B unit-price contract, pos. 02.03.0040."""
    return engine.build_payload(
        estimate={
            "name": "Kostenberechnung Wasserleitung",
            "currency": "EUR",
            "base_date": "2026-03-01",
            "classification_standard": "din276",
        },
        positions=[
            {"ordinal": "02", "description": "Erdarbeiten", "unit": "section", "quantity": "0", "unit_rate": "0"},
            {
                "ordinal": "02.03",
                "parent_ordinal": "02",
                "description": "Rohrgraben",
                "unit": "section",
                "quantity": "0",
                "unit_rate": "0",
            },
            {
                "ordinal": "02.03.0040",
                "parent_ordinal": "02.03",
                "unit": "m3",
                "quantity": "1250",
                "unit_rate": "36.16",
                "description": "Rohrgraben ausheben, Tiefe bis 1,75 m",
                "classification": {"din276": "311"},
                "resources": [
                    _res("labor", "L-TRENCH", "Facharbeiter Tiefbau", "h", "0.45", "52.80", price_date="2026-03-01"),
                    _res("equipment", "P-EXC", "Mobilbagger 14 t", "h", "0.08", "64.00", price_date="2026-03-01"),
                ],
            },
            {
                "ordinal": "02.03.0050",
                "parent_ordinal": "02.03",
                "unit": "m3",
                "quantity": "420",
                "unit_rate": "41.19",
                "description": "Rohrbettung Sand 0/2",
                "resources": [
                    _res("labor", "L-TRENCH", "Facharbeiter Tiefbau", "h", "0.20", "52.80"),
                    _res("material", "M-SAND", "Sand 0/2", "t", "1.8", "12.60", quote_ref="Q-102"),
                ],
            },
            {
                "ordinal": "02.03.0060",
                "parent_ordinal": "02.03",
                "unit": "m3",
                "quantity": "980",
                "unit_rate": "14.90",
                "description": "Verfuellen und verdichten",
            },
        ],
        markups=[
            _mk("bgk", "BGK", "9.5", "direct_cost", 10),
            _mk("agk", "AGK", "11.0", "cumulative", 20),
            _mk("wug", "WuG", "3.0", "cumulative", 30, category="profit"),
        ],
        attachments=[{"name": "EFB 221.pdf", "sha256": "5f1c" + "0" * 60}],
    )


def example_uk_trench() -> dict[str, Any]:
    """Example 2: JCT SBC priced bill, trench excavation in clay n.e. 2 m."""
    return engine.build_payload(
        estimate={
            "name": "Contract bills, drainage",
            "currency": "GBP",
            "base_date": "2026-02-01",
            "classification_standard": "nrm2",
        },
        positions=[
            {
                "ordinal": "D20",
                "description": "Excavating and filling",
                "unit": "section",
                "quantity": "0",
                "unit_rate": "0",
            },
            {
                "ordinal": "D20.1",
                "parent_ordinal": "D20",
                "unit": "m3",
                "quantity": "640",
                "unit_rate": "42.62",
                "description": "Trench excavation in clay, n.e. 2 m deep",
                "resources": [
                    _res("labor", "LAB", "Groundworker", "h", "0.35", "32.00"),
                    _res("equipment", "EXC", "13 t excavator", "h", "0.06", "58.00"),
                    _res("material", "DISP", "Disposal off site", "t", "1.6", "14.50"),
                ],
            },
            {
                "ordinal": "D20.2",
                "parent_ordinal": "D20",
                "unit": "m3",
                "quantity": "210",
                "unit_rate": "28.40",
                "description": "Granular backfill type 1",
            },
        ],
        markups=[_mk("ohp", "OH&P", "12.5", "direct_cost", 10, category="profit")],
    )


def example_fidic_pipe_surround() -> dict[str, Any]:
    """Example 3: FIDIC 2017 Red Book, USD, item 4.07 concrete pipe surround."""
    return engine.build_payload(
        estimate={
            "name": "Rate build-up, utilities",
            "currency": "USD",
            "base_date": "2026-01-15",
            "classification_standard": "masterformat",
        },
        positions=[
            {"ordinal": "4", "description": "Pipework", "unit": "section", "quantity": "0", "unit_rate": "0"},
            {
                "ordinal": "4.07",
                "parent_ordinal": "4",
                "unit": "m3",
                "quantity": "310",
                "unit_rate": "188.02",
                "description": "Concrete pipe surround",
                "resources": [
                    _res("labor", "LAB", "Concrete gang", "h", "1.2", "46.00"),
                    _res("equipment", "PLANT", "Plant allowance", "m3", "1", "9.80"),
                    _res("material", "CONC", "Ready-mix concrete", "m3", "1.05", "96.00", price_date="2026-01-10"),
                ],
            },
        ],
        markups=[
            _mk("oh", "Overhead", "8", "direct_cost", 10),
            _mk("pr", "Profit", "5", "cumulative", 20, category="profit"),
        ],
    )
