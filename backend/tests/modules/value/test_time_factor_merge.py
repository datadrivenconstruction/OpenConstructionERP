# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure-engine tests for the hours-saved factor merge (no DB, py3.11-safe).

``merge_factors`` is the deterministic glue that turns a tenant's sparse
overrides into the full effective factor map the aggregation functions take.
These tests pin its semantics: overrides win, unset pairs keep their default,
tenant-only pairs are added, and the base map is never mutated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.modules.value.time_saved import (
    BY_FEATURE,
    DEFAULT_FACTORS,
    ActivityEvent,
    aggregate_hours,
    estimate_saved_minutes,
    merge_factors,
)


def test_override_wins_over_default() -> None:
    """An override replaces just that pair; every other default is untouched."""
    pair = ("rfi", "rfi_answered")
    assert DEFAULT_FACTORS[pair] == Decimal("25")  # guard the seed assumption

    effective = merge_factors({pair: Decimal("40")})

    assert effective[pair] == Decimal("40")
    # A different default pair is carried through unchanged.
    assert effective[("takeoff", "takeoff_parsed")] == DEFAULT_FACTORS[("takeoff", "takeoff_parsed")]
    # Every default key is still present.
    assert set(DEFAULT_FACTORS).issubset(effective)


def test_unset_pair_keeps_default() -> None:
    """With no overrides the effective map equals the defaults exactly."""
    assert merge_factors({}) == dict(DEFAULT_FACTORS)


def test_tenant_only_pair_is_added() -> None:
    """An override for a pair absent from the seed map is added, not dropped."""
    extra = ("safety", "toolbox_talk_logged")
    assert extra not in DEFAULT_FACTORS

    effective = merge_factors({extra: Decimal("12")})

    assert effective[extra] == Decimal("12")
    # Engine credits the new pair from the merged map.
    assert estimate_saved_minutes("toolbox_talk_logged", "safety", 1, effective) == Decimal("12")


def test_base_is_not_mutated() -> None:
    """Merging never writes back into the shared DEFAULT_FACTORS map."""
    before = dict(DEFAULT_FACTORS)
    merge_factors({("rfi", "rfi_answered"): Decimal("99")})
    assert before == DEFAULT_FACTORS


def test_merged_factors_flow_through_aggregation() -> None:
    """A tuned factor changes the aggregated hours the engine reports."""
    events = [ActivityEvent(action="rfi_answered", module="rfi", at=datetime(2026, 6, 1, tzinfo=UTC))]

    default_buckets = aggregate_hours(events, by=BY_FEATURE, factors=DEFAULT_FACTORS)
    # 25 minutes -> 0.42 h
    assert default_buckets[0].minutes == Decimal("25")

    tuned = merge_factors({("rfi", "rfi_answered"): Decimal("60")})
    tuned_buckets = aggregate_hours(events, by=BY_FEATURE, factors=tuned)
    assert tuned_buckets[0].minutes == Decimal("60")
    assert tuned_buckets[0].hours == Decimal("1.00")
