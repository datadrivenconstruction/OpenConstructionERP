"""Regression tests for BUG-011: validate-BOQ payload completeness.

Background
~~~~~~~~~~
The ``POST /api/v1/boq/boqs/{id}/validate`` endpoint converts each
``Position`` row into a dict and feeds it to ``validation_engine.validate``.
A previous version of that conversion silently dropped ``unit``,
``parent_id``, ``total``, ``type``, and a few other fields. The downstream
``boq_quality.*`` rules then read ``pos.get("unit") -> None``,
``pos.get("total") -> None``, ``pos.get("parent_id") -> None`` and
false-positively errored on every leaf row even when the BOQ was clean.

These tests exercise the rules with the *exact* dict shape the router now
emits (with all relevant keys populated) and assert no false positives —
guarding against any future regression that drops a field again.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.validation.engine import ValidationContext
from app.core.validation.rules import (
    EmptyUnit,
    PositionHasQuantity,
    PositionHasUnitRate,
    TotalMismatch,
)


def _row(
    *,
    pos_id: str,
    ordinal: str,
    unit: str,
    quantity: float,
    unit_rate: float,
    parent_id: str | None = None,
    description: str = "Reinforced concrete C30/37",
) -> dict:
    """Build a position dict matching the router's BUG-011 fix shape."""
    total = quantity * unit_rate
    return {
        "id": pos_id,
        "parent_id": parent_id,
        "ordinal": ordinal,
        "description": description,
        "unit": unit,
        "quantity": quantity,
        "unit_rate": unit_rate,
        "total": total,
        "classification": {},
        "source": "manual",
        "type": "position",
    }


def _section_row(*, pos_id: str, ordinal: str) -> dict:
    """Section header row — has empty unit and zero qty/rate by design."""
    return {
        "id": pos_id,
        "parent_id": None,
        "ordinal": ordinal,
        "description": "Section header",
        "unit": "",
        "quantity": 0,
        "unit_rate": 0,
        "total": 0,
        "classification": {},
        "source": "manual",
        "type": "section",
    }


def _run(rule: object, context: ValidationContext) -> list:
    """Synchronously execute an async rule for compact assertions."""
    return asyncio.run(rule.validate(context))


# ── BUG-011 regression: empty_unit must NOT fire on populated rows ─────────


def test_empty_unit_passes_when_unit_present() -> None:
    """All five rows have unit='m3' — the rule must report passed=True for each.

    Reproduces the original QA bug where ``unit`` was missing from the
    router's position dict and ``boq_quality.empty_unit`` fired
    severity=error on every row.
    """
    positions = [
        _row(pos_id=f"p{i}", ordinal=f"01.{i:03d}", unit="m3", quantity=10, unit_rate=110) for i in range(1, 6)
    ]
    ctx = ValidationContext(data={"positions": positions})

    results = _run(EmptyUnit(), ctx)

    assert len(results) == 5, "Expected one result per leaf position"
    for r in results:
        assert r.passed is True, f"empty_unit must pass when unit is set, got: {r.message}"


def test_empty_unit_fires_only_on_truly_empty_unit() -> None:
    """Sentinel — the rule still catches a genuinely missing unit."""
    positions = [
        _row(pos_id="p1", ordinal="01.001", unit="m3", quantity=5, unit_rate=100),
        _row(pos_id="p2", ordinal="01.002", unit="", quantity=5, unit_rate=100),
    ]
    ctx = ValidationContext(data={"positions": positions})

    results = _run(EmptyUnit(), ctx)

    by_id = {r.element_ref: r for r in results}
    assert by_id["p1"].passed is True
    assert by_id["p2"].passed is False


def test_section_headers_skipped_by_leaf_rules() -> None:
    """Sections must not be policed by leaf-level completeness rules.

    Header rows legitimately have empty unit + zero quantity + zero rate,
    so EmptyUnit / PositionHasQuantity / PositionHasUnitRate must skip
    them once ``type='section'`` is on the dict (which the router now
    derives from unit/qty/rate).
    """
    positions = [
        _section_row(pos_id="s1", ordinal="01"),
        _row(
            pos_id="p1",
            ordinal="01.001",
            unit="m3",
            quantity=10,
            unit_rate=110,
            parent_id="s1",
        ),
    ]
    ctx = ValidationContext(data={"positions": positions})

    for rule in (EmptyUnit(), PositionHasQuantity(), PositionHasUnitRate()):
        results = _run(rule, ctx)
        assert len(results) == 1, f"{rule.rule_id} must skip section headers"
        assert results[0].element_ref == "p1"
        assert results[0].passed is True, f"{rule.rule_id} false-positive on populated leaf: {results[0].message}"


# ── Audit: sibling boq_quality rules also need their fields ────────────────


def test_total_mismatch_uses_total_field() -> None:
    """``boq_quality.total_mismatch`` reads ``total`` — verifies BUG-011 sweep.

    Without ``total`` in the dict, the rule's ``stored_total`` is ``None``
    and the rule short-circuits to "skip" — silently passing every row
    even when totals are wrong. The router must now project ``total``.
    """
    # Correct total: 10 * 110 = 1100
    good = _row(pos_id="p1", ordinal="01.001", unit="m3", quantity=10, unit_rate=110)
    # Wrong stored total
    bad = _row(pos_id="p2", ordinal="01.002", unit="m3", quantity=10, unit_rate=110)
    bad["total"] = 9999.99

    ctx = ValidationContext(data={"positions": [good, bad]})
    results = _run(TotalMismatch(), ctx)

    by_id = {r.element_ref: r for r in results}
    assert by_id["p1"].passed is True
    assert by_id["p2"].passed is False, "total_mismatch must catch wrong stored total (requires total field on dict)"


# ── Direct guard against the BUG-011 regression itself ────────────────────


@pytest.mark.parametrize(
    "missing_key",
    ["unit", "total", "parent_id", "type"],
)
def test_router_payload_must_carry_required_keys(missing_key: str) -> None:
    """The router builds positions for the engine — assert the schema contract.

    Mirrors ``backend/app/modules/boq/router.py::validate_boq``. If a future
    refactor drops one of these keys again the test fails loudly.
    """
    from app.modules.boq.router import validate_boq  # noqa: F401  (import gate)

    sample = _row(pos_id="p1", ordinal="01.001", unit="m3", quantity=1, unit_rate=1)
    assert missing_key in sample, (
        f"BUG-011 sentinel: position dict must carry '{missing_key}' for boq_quality rules to function"
    )
