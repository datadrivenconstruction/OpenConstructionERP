# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Service-level resolution of formula-mode quantity links (Issue #347).

Exercises the real ``BOQService._compute_link_quantity`` - the method the
refresh/apply endpoints call - with the element repository monkeypatched to
return in-memory elements. That keeps the test DB-free (no app boot, no
PostgreSQL) while still driving the production per-element projection: build
each element's variables, evaluate the formula against them, drop an element
that lacks a needed variable (or hits a math error) as ``missing``, then
aggregate the survivors exactly like field mode.

The HTTP contract (create -> refresh -> apply, 422 validation) is covered end
to end in ``tests/integration/test_quantity_link_formula.py``; this file pins
the pure resolution maths that sits underneath it.
"""

from __future__ import annotations

import types
import uuid
from decimal import Decimal

import pytest

import app.modules.bim_hub.repository as repo_mod
from app.modules.boq.service import BOQService


def _elem(stable_id: str, quantities: dict | None = None, properties: dict | None = None) -> types.SimpleNamespace:
    """A minimal stand-in for a ``BIMElement`` row (only the read fields)."""
    return types.SimpleNamespace(
        stable_id=stable_id,
        quantities=quantities or {},
        properties=properties or {},
    )


@pytest.fixture
def service_with_elements(monkeypatch):
    """A ``BOQService`` whose element repository serves an in-memory store.

    Returns ``(service, store)``; put ``_elem(...)`` objects into ``store``
    keyed by stable_id, then call ``service._compute_link_quantity(...)``.
    """
    store: dict[str, types.SimpleNamespace] = {}

    async def _fake_list_by_stable_ids(self, model_id, stable_ids):  # noqa: ANN001, ARG001
        return [store[s] for s in stable_ids if s in store]

    monkeypatch.setattr(repo_mod.BIMElementRepository, "list_by_stable_ids", _fake_list_by_stable_ids)
    service = BOQService(session=types.SimpleNamespace())
    return service, store


async def _resolve(service: BOQService, stable_ids: list[str], **kw):
    return await service._compute_link_quantity(
        model_id=uuid.uuid4(),
        stable_ids=stable_ids,
        quantity_field=kw.pop("quantity_field", ""),
        aggregation=kw.pop("aggregation", "sum"),
        projection_mode=kw.pop("projection_mode", "formula"),
        formula=kw.pop("formula", None),
    )


@pytest.mark.asyncio
async def test_formula_sum_evaluates_per_element_then_aggregates(service_with_elements) -> None:
    service, store = service_with_elements
    store["S1"] = _elem("S1", {"area_m2": 10})
    store["S2"] = _elem("S2", {"area_m2": 20})

    agg, contributing, missing = await _resolve(service, ["S1", "S2"], formula="area_m2 * 0.5", aggregation="sum")
    # 10*0.5 + 20*0.5 = 15, and Decimal not float.
    assert agg == Decimal("15.0")
    assert contributing == ["S1", "S2"]
    assert missing == []


@pytest.mark.asyncio
async def test_formula_uses_both_quantities_and_properties(service_with_elements) -> None:
    service, store = service_with_elements
    # length_m is a quantity, unit_weight lives in properties; a formula can
    # combine both because build_element_vars merges the two namespaces.
    store["B1"] = _elem("B1", {"length_m": 4}, {"unit_weight": 2.5})

    agg, contributing, missing = await _resolve(service, ["B1"], formula="length_m * unit_weight")
    assert agg == Decimal("10.0")
    assert contributing == ["B1"]
    assert missing == []


@pytest.mark.asyncio
async def test_element_missing_variable_is_reported_not_zeroed(service_with_elements) -> None:
    service, store = service_with_elements
    store["A"] = _elem("A", {"area_m2": 8})
    store["B"] = _elem("B", {"volume_m3": 3})  # no area_m2

    agg, contributing, missing = await _resolve(service, ["A", "B"], formula="area_m2 * 2")
    # Only A resolves (16); B is surfaced as missing, never a silent zero that
    # would drag a sum/min down or inflate a count.
    assert agg == Decimal("16")
    assert contributing == ["A"]
    assert missing == ["B"]


@pytest.mark.asyncio
async def test_per_element_division_by_zero_is_missing(service_with_elements) -> None:
    service, store = service_with_elements
    store["OK"] = _elem("OK", {"area_m2": 12, "count": 3})
    store["BAD"] = _elem("BAD", {"area_m2": 9, "count": 0})  # divide by zero

    agg, contributing, missing = await _resolve(service, ["OK", "BAD"], formula="area_m2 / count")
    assert agg == Decimal("4")
    assert contributing == ["OK"]
    assert missing == ["BAD"]


@pytest.mark.asyncio
async def test_absent_element_is_missing(service_with_elements) -> None:
    service, store = service_with_elements
    store["P"] = _elem("P", {"area_m2": 5})
    # "GONE" was revised out of the model - not in the store.

    agg, contributing, missing = await _resolve(service, ["P", "GONE"], formula="area_m2 * 1")
    assert agg == Decimal("5")
    assert contributing == ["P"]
    assert missing == ["GONE"]


@pytest.mark.asyncio
async def test_formula_max_and_min_aggregation(service_with_elements) -> None:
    service, store = service_with_elements
    store["a"] = _elem("a", {"h": 2, "w": 3})  # 6
    store["b"] = _elem("b", {"h": 5, "w": 4})  # 20
    store["c"] = _elem("c", {"h": 1, "w": 1})  # 1

    agg_max, *_ = await _resolve(service, ["a", "b", "c"], formula="h * w", aggregation="max")
    agg_min, *_ = await _resolve(service, ["a", "b", "c"], formula="h * w", aggregation="min")
    assert agg_max == Decimal("20")
    assert agg_min == Decimal("1")


@pytest.mark.asyncio
async def test_count_aggregation_ignores_formula(service_with_elements) -> None:
    service, store = service_with_elements
    store["d1"] = _elem("d1", {"area_m2": 999})
    store["d2"] = _elem("d2", {})  # would fail the formula, but count ignores it

    # count = number of RESOLVED elements, independent of the projection.
    agg, contributing, missing = await _resolve(service, ["d1", "d2", "d3"], formula="area_m2 * 2", aggregation="count")
    assert agg == Decimal("2")
    assert contributing == ["d1", "d2"]
    assert missing == ["d3"]


@pytest.mark.asyncio
async def test_field_mode_still_reads_quantity_field(service_with_elements) -> None:
    """Regression guard: the default 'field' projection is unchanged."""
    service, store = service_with_elements
    store["F1"] = _elem("F1", {"area_m2": 7})
    store["F2"] = _elem("F2", {"area_m2": 8})

    agg, contributing, missing = await _resolve(
        service, ["F1", "F2"], projection_mode="field", quantity_field="area_m2", formula=None
    )
    assert agg == Decimal("15")
    assert contributing == ["F1", "F2"]
    assert missing == []
