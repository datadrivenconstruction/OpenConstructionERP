# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure unit tests for the CDE readiness-level ranking helpers.

These back the go-live gate: a project may only open its CDE to the whole team
once its readiness level meets a configured minimum. The ranking must be total
and safe (an unknown level can never slip past a gate).
"""

from __future__ import annotations

from app.modules.cde.readiness import (
    READINESS_LEVELS,
    level_rank,
    meets_level,
    readiness_level,
)


class TestLevelOrder:
    def test_levels_are_ordered_ascending(self) -> None:
        assert READINESS_LEVELS == ("not_started", "forming", "operational", "mature")

    def test_rank_matches_index(self) -> None:
        assert level_rank("not_started") == 0
        assert level_rank("forming") == 1
        assert level_rank("operational") == 2
        assert level_rank("mature") == 3

    def test_unknown_level_ranks_lowest(self) -> None:
        # A typo must never grant more authority than "not_started".
        assert level_rank("bogus") == 0
        assert level_rank("") == 0


class TestMeetsLevel:
    def test_exact_level_meets(self) -> None:
        assert meets_level("operational", "operational") is True

    def test_higher_level_meets(self) -> None:
        assert meets_level("mature", "operational") is True

    def test_lower_level_does_not_meet(self) -> None:
        assert meets_level("forming", "operational") is False
        assert meets_level("not_started", "forming") is False

    def test_unknown_achieved_never_meets_real_requirement(self) -> None:
        assert meets_level("bogus", "operational") is False

    def test_unknown_requirement_is_met_by_anything(self) -> None:
        # An unknown requirement ranks 0, so any real level clears it - the gate
        # fails open only when misconfigured with a bad required level, which is
        # caught by schema validation before it can be stored.
        assert meets_level("not_started", "bogus") is True


class TestReadinessLevelBands:
    def test_bands_map_to_known_levels(self) -> None:
        for score in (0, 10, 49, 50, 84, 85, 100):
            assert readiness_level(score) in READINESS_LEVELS

    def test_operational_starts_at_50(self) -> None:
        assert readiness_level(49) == "forming"
        assert readiness_level(50) == "operational"
        assert readiness_level(84) == "operational"
        assert readiness_level(85) == "mature"
