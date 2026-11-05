"""CWICR resource typing must not depend on the language of a regional base."""

from __future__ import annotations

import pandas as pd

from app.modules.costs.router import _cwicr_resource_types

HOURS = {"hrs", "h", "person-hour", "person-hours", "man-hours"}


def _frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["_unit"] = df["resource_unit"].astype(str)
    df["_code"] = df["resource_code"].astype(str)
    return df


def test_a_german_base_types_labour_concrete_and_machines() -> None:
    """DE_BERLIN: is_labor is never set and row_type text is German."""
    base = {"is_machine": False, "is_material": False, "is_labor": False, "is_abstract": False}
    df = _frame(
        [
            {
                **base,
                "row_type": "Ressource",
                "is_material": True,
                "resource_unit": "Std.",
                "resource_code": "ME_MEKAKA_TOVO",
            },
            {
                **base,
                "row_type": "Ressource",
                "is_material": True,
                "resource_unit": "Personen",
                "resource_code": "TO_TOKAKA_RIME",
            },
            {
                **base,
                "row_type": "Abstrakte Ressource",
                "is_abstract": True,
                "resource_unit": "m3",
                "resource_code": "KAME-LI-MESA-KATO_KAKAPURI",
            },
            {
                **base,
                "row_type": "Ressource",
                "is_material": True,
                "resource_unit": "kg",
                "resource_code": "KARI-RI-KASA-KAPU_RIKADXKA",
            },
            {
                **base,
                "row_type": "Maschinist",
                "is_machine": True,
                "resource_unit": "Masch.-Std.",
                "resource_code": "PU_PUKAKA_TOVO",
            },
            {
                **base,
                "row_type": "Elektrizität",
                "is_machine": True,
                "resource_unit": "kWh",
                "resource_code": "DX_DXDXDX_DXDX",
            },
        ]
    )
    assert list(_cwicr_resource_types(df, HOURS)) == [
        "labor",
        "labor",
        "material",
        "material",
        "equipment",
        "equipment",
    ]


def test_an_english_base_keeps_its_types() -> None:
    base = {"is_machine": False, "is_material": False, "is_labor": False}
    df = _frame(
        [
            {**base, "row_type": "Labour", "is_labor": True, "resource_unit": "hrs", "resource_code": "ME_MEKAKA_TOVO"},
            {**base, "row_type": "Abstract resource", "resource_unit": "m3", "resource_code": "A-B"},
            {
                **base,
                "row_type": "Plant Operator",
                "is_machine": True,
                "resource_unit": "hrs",
                "resource_code": "PU_PUKAKA_TOVO",
            },
            {**base, "row_type": "Material", "is_material": True, "resource_unit": "t", "resource_code": "C-D"},
        ]
    )
    assert list(_cwicr_resource_types(df, HOURS)) == ["labor", "material", "equipment", "material"]
