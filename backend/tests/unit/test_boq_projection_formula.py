# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the per-element BOQ quantity *formula* projection (option C).

The projection engine evaluates a formula **per bound element** and then
aggregates (``Σ formula(element_i)``, or max/min/first). These tests drive
``BIMHubService._compute_formula_quantity`` directly with a fake element
repository — no DB, no event bus — so the dimensional/safety contract is
pinned without the integration harness:

* per-element transform then aggregate (sum / max / min / first);
* an element missing a referenced parameter is **ignored and flagged**,
  never an error (mixed-binding tolerance);
* an invalid / unsafe formula yields ``quantity=None`` (manual value left
  untouched — same contract as D-TKC-028);
* ``count`` is reserved to simple mode — a formula aggregation of
  ``count`` is coerced to ``sum``;
* the per-element ``names`` binding exposes quantities (primary),
  properties (secondary, never overriding), and a synthetic ``count = 1``.

Run:
    cd backend
    python -m pytest tests/unit/test_boq_projection_formula.py -v --tb=short
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from app.modules.bim_hub.service import (
    BIMHubService,
    ProjectionSpec,
    _aggregate_decimals,
)

# ── Fakes ────────────────────────────────────────────────────────────────


@dataclass
class _FakeElement:
    stable_id: str
    quantities: dict = field(default_factory=dict)
    properties: dict = field(default_factory=dict)
    name: str | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class _FakeLink:
    bim_element_id: uuid.UUID


class _FakeElementRepo:
    def __init__(self, elements: list[_FakeElement]) -> None:
        self._by_id = {e.id: e for e in elements}

    async def get(self, element_id):
        return self._by_id.get(element_id)


def _service_with_elements(elements: list[_FakeElement]) -> BIMHubService:
    """A ``BIMHubService`` wired with only the fake element repo it needs.

    ``_compute_formula_quantity`` touches nothing but ``self.element_repo``
    and the static ``_element_formula_names`` — so we skip ``__init__`` and
    inject just that collaborator.
    """
    svc = BIMHubService.__new__(BIMHubService)
    svc.element_repo = _FakeElementRepo(elements)
    return svc


def _links_for(elements: list[_FakeElement]) -> list[_FakeLink]:
    return [_FakeLink(bim_element_id=e.id) for e in elements]


async def _compute(elements, *, formula, aggregation="sum", unit="m2"):
    svc = _service_with_elements(elements)
    spec = ProjectionSpec(kind="formula", aggregation=aggregation, formula=formula)
    return await svc._compute_formula_quantity(None, _links_for(elements), unit, spec)


# ── _aggregate_decimals (pure) ───────────────────────────────────────────


def test_aggregate_empty_is_zero() -> None:
    assert _aggregate_decimals([], "sum") == Decimal(0)
    assert _aggregate_decimals([], "max") == Decimal(0)


def test_aggregate_modes() -> None:
    vals = [Decimal("2"), Decimal("5"), Decimal("1")]
    assert _aggregate_decimals(vals, "sum") == Decimal("8")
    assert _aggregate_decimals(vals, "max") == Decimal("5")
    assert _aggregate_decimals(vals, "min") == Decimal("1")
    assert _aggregate_decimals(vals, "first") == Decimal("2")
    # Unknown aggregation falls back to sum.
    assert _aggregate_decimals(vals, "bogus") == Decimal("8")


# ── _element_formula_names (pure / static) ───────────────────────────────


def test_formula_names_quantities_primary_properties_secondary() -> None:
    elem = _FakeElement(
        stable_id="W1",
        quantities={"area_m2": 12.0, "shared": 1.0},
        properties={"thickness_m": 0.2, "shared": 99.0},
    )
    names = BIMHubService._element_formula_names(elem)
    assert names["area_m2"] == 12.0
    assert names["thickness_m"] == 0.2
    # A quantity is never overridden by a property of the same name.
    assert names["shared"] == 1.0
    # Synthetic count for parity with simple count aggregation.
    assert names["count"] == 1.0


def test_formula_names_skips_non_numeric_and_non_finite() -> None:
    elem = _FakeElement(
        stable_id="W1",
        quantities={"area_m2": 3.0, "label": "wall", "inf": float("inf")},
        properties={"nan": float("nan")},
    )
    names = BIMHubService._element_formula_names(elem)
    assert names["area_m2"] == 3.0
    assert "label" not in names
    assert "inf" not in names
    assert "nan" not in names


# ── Per-element transform then aggregate ─────────────────────────────────


@pytest.mark.asyncio
async def test_per_element_sum() -> None:
    """``area_m2 * 2`` evaluated per wall then summed (enduit use-case)."""
    elements = [
        _FakeElement(stable_id="W1", quantities={"area_m2": 6.0}),
        _FakeElement(stable_id="W2", quantities={"area_m2": 4.0}),
    ]
    result = await _compute(elements, formula="area_m2 * 2", aggregation="sum")
    # (6*2) + (4*2) = 20.
    assert result.quantity == Decimal("20")
    assert result.projection_kind == "formula"
    assert sorted(result.contributing_elements) == ["W1", "W2"]
    assert result.missing_element_ids == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("aggregation", "expected"),
    [("sum", "20"), ("max", "12"), ("min", "8"), ("first", "12")],
)
async def test_aggregations(aggregation: str, expected: str) -> None:
    elements = [
        _FakeElement(stable_id="W1", quantities={"area_m2": 6.0}),  # 12
        _FakeElement(stable_id="W2", quantities={"area_m2": 4.0}),  # 8
    ]
    result = await _compute(elements, formula="area_m2 * 2", aggregation=aggregation)
    assert result.quantity == Decimal(expected)


@pytest.mark.asyncio
async def test_count_aggregation_coerced_to_sum() -> None:
    """``count`` is reserved to simple mode; a formula coerces it to sum."""
    elements = [
        _FakeElement(stable_id="W1", quantities={"area_m2": 6.0}),
        _FakeElement(stable_id="W2", quantities={"area_m2": 4.0}),
    ]
    result = await _compute(elements, formula="area_m2", aggregation="count")
    assert result.aggregation == "sum"
    assert result.quantity == Decimal("10")


# ── Mixed-binding tolerance ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_param_element_ignored_and_flagged() -> None:
    """An element lacking a referenced param is skipped, not an error."""
    elements = [
        _FakeElement(stable_id="W1", quantities={"area_m2": 6.0}),
        _FakeElement(stable_id="W2", quantities={"volume_m3": 1.0}),  # no area_m2
    ]
    result = await _compute(elements, formula="area_m2 * 2", aggregation="sum")
    assert result.quantity == Decimal("12")  # only W1
    assert result.contributing_elements == ["W1"]
    assert result.missing_element_ids == ["W2"]


@pytest.mark.asyncio
async def test_all_elements_missing_param_yields_zero_not_none() -> None:
    """A valid formula whose elements all lack the param → Decimal(0)."""
    elements = [_FakeElement(stable_id="W1", quantities={"volume_m3": 1.0})]
    result = await _compute(elements, formula="area_m2 * 2")
    assert result.quantity == Decimal(0)
    assert result.contributing_elements == []
    assert result.missing_element_ids == ["W1"]


@pytest.mark.asyncio
async def test_missing_element_row_flagged() -> None:
    """A link whose element no longer exists is flagged, not fatal."""
    present = _FakeElement(stable_id="W1", quantities={"area_m2": 5.0})
    svc = _service_with_elements([present])
    ghost = _FakeLink(bim_element_id=uuid.uuid4())  # not in repo
    spec = ProjectionSpec(kind="formula", aggregation="sum", formula="area_m2")
    result = await svc._compute_formula_quantity(None, [_FakeLink(present.id), ghost], "m2", spec)
    assert result.quantity == Decimal("5")
    assert result.contributing_elements == ["W1"]
    assert str(ghost.bim_element_id) in result.missing_element_ids


# ── Invalid / unsafe formula → quantity None ─────────────────────────────


@pytest.mark.asyncio
async def test_empty_formula_yields_none() -> None:
    elements = [_FakeElement(stable_id="W1", quantities={"area_m2": 6.0})]
    result = await _compute(elements, formula="   ")
    assert result.quantity is None


@pytest.mark.asyncio
async def test_syntax_error_formula_yields_none() -> None:
    elements = [_FakeElement(stable_id="W1", quantities={"area_m2": 6.0})]
    result = await _compute(elements, formula="area_m2 *")
    assert result.quantity is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "evil",
    [
        "area_m2.__class__",
        "__import__('os')",
        "(lambda: 1)()",
        "[x for x in range(3)]",
    ],
)
async def test_unsafe_formula_yields_none(evil: str) -> None:
    """Dunder access / import / lambda / comprehension are rejected."""
    elements = [_FakeElement(stable_id="W1", quantities={"area_m2": 6.0})]
    result = await _compute(elements, formula=evil)
    assert result.quantity is None


@pytest.mark.asyncio
async def test_formula_can_reference_synthetic_count() -> None:
    """A formula may reference ``count`` (=1 per element) for parity."""
    elements = [
        _FakeElement(stable_id="W1", quantities={"area_m2": 6.0}),
        _FakeElement(stable_id="W2", quantities={"area_m2": 4.0}),
    ]
    result = await _compute(elements, formula="count", aggregation="sum")
    assert result.quantity == Decimal("2")
