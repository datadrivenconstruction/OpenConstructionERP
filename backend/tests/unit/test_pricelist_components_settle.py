"""Every price-list reader hands over components that add up to the item's rate.

The BOQ editor prices a line added from the cost database as the sum of the
item's components when it has any (``BOQModals.tsx``, and the server states
the same figure as ``buildup_rate``). A reader whose components do not add up
to the list price therefore reprices every line it touches: an XPWE item at
13.63 landed at 5.34, its analysis without general expenses and profit, and
one at 2.25 landed at 3.32. Each reader closes the gap with one balancing
"Spese generali e utile d'impresa" line, and an analysis that claims more than
the price is kept as a record (``metadata.prezzario.analysis``) rather than as
components. This file holds every reader to that, so none can drift again.
"""

from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.costs.buildup import buildup_rate
from app.modules.costs.pricelists.service import cost_item_payload, plan_upload
from tests.fixtures import xpwe_builder

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pricelists"
XPWE_COMPUTO = Path(__file__).resolve().parents[1] / "fixtures" / "xpwe" / "computo_small.xpwe"
TOLERANCE = Decimal("0.000001")


def _dec(value: object) -> Decimal:
    return Decimal(str(value))


def _lands_at(component: dict) -> Decimal:
    """What one resource adds to the line, the way ``catalogComponentAmounts`` reads it.

    The editor takes the ``cost`` and fits the quantity to it when an official
    list rounded the amount (0.02 x 25.96832 stated as 0.51937); only a
    component without a cost is priced as quantity x rate.
    """
    cost = _dec(component.get("cost") or 0)
    if cost:
        return cost
    return _dec(component.get("quantity", 1)) * _dec(component.get("unit_rate") or 0)


def _payloads(data: bytes, name: str) -> list[tuple[object, dict]]:
    plan = plan_upload(io.BytesIO(data), name)
    return [(row, cost_item_payload(row, plan.source)) for row in plan.rows() if row.rate]


def _assert_settles(data: bytes, name: str) -> int:
    """Assert the invariant on every row; return how many rows had components."""
    with_components = 0
    for row, payload in _payloads(data, name):
        components = payload["components"]
        if not components:
            continue
        with_components += 1
        total = sum((_lands_at(c) for c in components), Decimal(0))
        assert abs(total - row.rate) <= TOLERANCE, f"{row.code}: components {total} against rate {row.rate}"
        landing = buildup_rate(components, payload["metadata"])
        assert landing == row.rate.quantize(Decimal("0.01")), f"{row.code}: lands at {landing}, lists {row.rate}"
    return with_components


@pytest.mark.parametrize(
    ("fixture", "name"),
    [
        ("toscana_firenze_2025.xml", "Firenze-2025.xml"),
        ("lombardia_2026.xml", "lom.xml"),
        ("puglia_2026.csv", "2026_prezzario_regione_puglia.csv"),
    ],
)
def test_a_regional_reader_settles_its_components_on_the_rate(fixture: str, name: str) -> None:
    assert _assert_settles((FIXTURES / fixture).read_bytes(), name) > 0


def test_an_xpwe_analysis_short_of_the_price_gets_the_balancing_line() -> None:
    data = XPWE_COMPUTO.read_bytes()
    assert _assert_settles(data, "elenco.xpwe") > 0
    row, payload = next((r, p) for r, p in _payloads(data, "elenco.xpwe") if r.code == "EX26_01.A03.001.001")
    # 0.15 h x 32.17 + 0.02 h x 25.97 = 5.3449 of a 13.63 price.
    assert row.rate == Decimal("13.63")
    assert payload["components"][-1]["name"] == "Spese generali e utile d'impresa"
    assert abs(_dec(payload["components"][-1]["cost"]) - Decimal("8.2851")) <= TOLERANCE


def test_an_xpwe_analysis_over_the_price_is_kept_as_a_record_not_as_components() -> None:
    data = xpwe_builder.price_list(3, analysis_lines=10)
    rows = _payloads(data, "elenco.xpwe")
    assert _assert_settles(data, "elenco.xpwe") >= 0
    over = [(r, p) for r, p in rows if "analysis_exceeds_price" in r.flags]
    assert over, "the builder's first item states 2.25 against an analysis of more than 3"
    for row, payload in over:
        assert payload["components"] == []
        block = payload["metadata"]["prezzario"]
        assert block["analysis"], "the analysis is kept for the estimator to read"
        assert "analysis_exceeds_price" in block["flags"]


def test_every_xpwe_item_of_a_generated_list_settles() -> None:
    assert _assert_settles(xpwe_builder.price_list(40, analysis_lines=2), "elenco.xpwe") > 0
