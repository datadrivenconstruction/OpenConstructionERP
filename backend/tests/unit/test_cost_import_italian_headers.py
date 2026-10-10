# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The headers of a regional Italian price list map without a manual step."""

import pytest

from app.modules.costs.router import _COST_COLUMN_ALIASES, _match_cost_column


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Tariffa", "code"),
        ("Codice", "code"),
        ("Numero d'ordine", "code"),
        ("Descrizione estesa", "description"),
        ("Descrizione dell'articolo", "description"),
        ("U.M.", "unit"),
        ("Unità di misura", "unit"),
        ("Unita' di misura", "unit"),
        ("Prezzo €", "rate"),
        ("Prezzo unitario", "rate"),
    ],
)
def test_italian_price_list_headers_map(header: str, expected: str) -> None:
    assert _match_cost_column(header) == expected


def test_no_alias_names_two_columns() -> None:
    seen: dict[str, str] = {}
    for canonical, aliases in _COST_COLUMN_ALIASES.items():
        for alias in aliases:
            assert seen.setdefault(alias, canonical) == canonical, alias
