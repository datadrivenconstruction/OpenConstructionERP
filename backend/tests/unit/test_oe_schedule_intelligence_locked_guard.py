# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""E5.2 locked-figure guard — negative-injection suite.

The commercial-trust heart of ``oe_schedule_intelligence``: prove that once a
figure is locked, no write can change it, from any flow. These are pure unit
tests — no DB, no session — because the guard core is deliberately
dependency-free (``LockedFigureGuard`` takes explicit entries). That is what
lets this suite be exhaustive and fast.

Covers spec ACs: E5.2-AC2 (every apply flow rejects locked-path writes) and
E4.3-AC4 (post-apply verification that locked figures are byte-identical).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.schedule_intelligence.enums import LockedFigureType
from app.modules.schedule_intelligence.locked_guard import (
    LockedEntry,
    LockedFigureGuard,
    LockedFigureViolation,
    canonical_value,
    value_hash,
)


# ── canonicalisation: type-agnostic, byte-identical comparison ───────────────
@pytest.mark.parametrize(
    "a,b",
    [
        (5, 5.0),
        (5, "5"),
        (Decimal("12.50"), 12.5),
        (Decimal("12.50"), "12.5"),
        (1000, "1000"),
        (0, 0.0),
    ],
)
def test_canonical_value_treats_equal_numbers_as_equal(a, b) -> None:
    assert canonical_value(a) == canonical_value(b)


@pytest.mark.parametrize(
    "a,b",
    [
        (5, 5.01),
        (12.5, 12.51),
        ("42 days", "43 days"),
        (True, 1),  # bool is not the integer 1 here — distinct canonical forms
    ],
)
def test_canonical_value_distinguishes_different_values(a, b) -> None:
    assert canonical_value(a) != canonical_value(b)


def test_canonical_value_is_order_independent_for_dicts() -> None:
    assert canonical_value({"a": 1, "b": 2}) == canonical_value({"b": 2, "a": 1})


def test_value_hash_matches_canonical() -> None:
    assert value_hash(canonical_value(5)) == value_hash("5")


# ── the core guard behaviours ────────────────────────────────────────────────
def test_unlocked_path_is_freely_writable() -> None:
    guard = LockedFigureGuard([LockedEntry.for_value("a.b", 10)])
    guard.assert_writable("some.other.path", 999)  # no lock → no raise


def test_idempotent_rewrite_of_same_value_is_allowed() -> None:
    """Single-store re-renders re-emit the confirmed figure — must not trip."""
    guard = LockedFigureGuard([LockedEntry.for_value("decision.1.impact_days", 42)])
    guard.assert_writable("decision.1.impact_days", 42)
    guard.assert_writable("decision.1.impact_days", 42.0)  # numeric-equivalent
    guard.assert_writable("decision.1.impact_days", "42")


def test_mutating_a_locked_figure_is_rejected() -> None:
    guard = LockedFigureGuard([LockedEntry.for_value("decision.1.impact_days", 42)])
    with pytest.raises(LockedFigureViolation) as exc:
        guard.assert_writable("decision.1.impact_days", 43)
    assert exc.value.path == "decision.1.impact_days"
    assert exc.value.locked_value == "42"
    assert exc.value.attempted_value == "43"


def test_negative_injection_across_every_locked_figure_type() -> None:
    """Lock one figure of each type, then inject a mutated write → all rejected.

    This is the E5.2-AC2 guarantee in one sweep: no figure category has a hole.
    """
    baseline = {
        LockedFigureType.BASELINE_DATE: ("baseline.date", "2026-01-01", "2026-02-01"),
        LockedFigureType.IMPACT_DAYS: ("impact.days", 42, 30),
        LockedFigureType.ENTITLEMENT_DAYS: ("eot.days", 15, 20),
        LockedFigureType.ENTITLEMENT_COST: ("eot.cost", "125000.00", "150000.00"),
        LockedFigureType.LDS_AVOIDED: ("lds.avoided", "90000.00", "0.00"),
        LockedFigureType.PROLONGATION_COST: ("prolong.cost", "60000.00", "61000.00"),
        LockedFigureType.ACCELERATION_COST: ("accel.cost", "80000.00", "40000.00"),
    }
    entries = [
        LockedEntry.for_value(path, locked, figure_type=ftype.value)
        for ftype, (path, locked, _mutated) in baseline.items()
    ]
    guard = LockedFigureGuard(entries)

    for ftype, (path, locked, mutated) in baseline.items():
        # identical re-write allowed
        guard.assert_writable(path, locked)
        # any change rejected
        with pytest.raises(LockedFigureViolation):
            guard.assert_writable(path, mutated)


def test_batch_write_rejects_when_any_path_violates() -> None:
    guard = LockedFigureGuard(
        [
            LockedEntry.for_value("a.impact_days", 42),
            LockedEntry.for_value("b.eot_days", 15),
        ]
    )
    # A payload that leaves both locked figures untouched passes.
    guard.assert_batch_writable({"a.impact_days": 42, "b.eot_days": 15, "c.free": 999})
    # A payload that mutates one locked figure is rejected.
    with pytest.raises(LockedFigureViolation):
        guard.assert_batch_writable({"a.impact_days": 42, "b.eot_days": 99})


# ── post-apply verification (E4.3-AC4) ───────────────────────────────────────
def test_verify_unchanged_passes_when_identical() -> None:
    guard = LockedFigureGuard([LockedEntry.for_value("decision.1.impact_days", 42)])
    guard.verify_unchanged("decision.1.impact_days", 42)


def test_verify_unchanged_raises_on_drift() -> None:
    guard = LockedFigureGuard([LockedEntry.for_value("decision.1.impact_days", 42)])
    with pytest.raises(LockedFigureViolation):
        guard.verify_unchanged("decision.1.impact_days", 41)


def test_verify_unchanged_on_unlocked_path_is_an_error() -> None:
    """You only verify what you locked; an unknown path is a programming error."""
    guard = LockedFigureGuard([])
    with pytest.raises(KeyError):
        guard.verify_unchanged("never.locked", 1)


# ── from_rows adapter: only active locks are enforced ────────────────────────
class _Row:
    def __init__(self, path: str, value: str, active: bool, figure_type: str) -> None:
        self.path = path
        self.value = value
        self.active = active
        self.figure_type = figure_type


def test_from_rows_ignores_inactive_locks() -> None:
    guard = LockedFigureGuard.from_rows(
        [
            _Row("active.path", "42", active=True, figure_type="impact_days"),
            _Row("released.path", "10", active=False, figure_type="impact_days"),
        ]
    )
    assert guard.is_locked("active.path")
    assert not guard.is_locked("released.path")
    # An unlocked (released) path is writable again.
    guard.assert_writable("released.path", 999)
    with pytest.raises(LockedFigureViolation):
        guard.assert_writable("active.path", 999)
