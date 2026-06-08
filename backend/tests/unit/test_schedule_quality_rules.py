"""Tests for the C1 schedule-quality rule pack (DCMA-14-style health checks).

Each of the seven rules (``ScheduleOpenEnds``, ``ScheduleNegativeLag``,
``ScheduleExcessiveLag``, ``ScheduleHardConstraints``, ``ScheduleNegativeFloat``,
``ScheduleHighFloat``, ``ScheduleMissingDuration``) gets at least one passing
and one failing case. Assertions cover:

* the boolean ``passed`` flag,
* the ``severity`` reported (governs ERROR vs WARNING vs INFO handling),
* the ``message`` being resolved from the English bundle (so template
  placeholders fill correctly and no hardcoded string snuck in).

Fixtures mirror the persisted schedule data shape (activities + relationships
from the schedule module) but are plain dicts, so no database is touched -
the same pattern the GAEB rule tests use.
"""

from __future__ import annotations

import pytest

from app.core.validation.engine import (
    RuleRegistry,
    Severity,
    ValidationContext,
    ValidationEngine,
)
from app.core.validation.rules import (
    ScheduleExcessiveLag,
    ScheduleHardConstraints,
    ScheduleHighFloat,
    ScheduleMissingDuration,
    ScheduleNegativeFloat,
    ScheduleNegativeLag,
    ScheduleOpenEnds,
    register_builtin_rules,
)

SCHEDULE_QUALITY_RULE_IDS = {
    "schedule_quality.open_ends",
    "schedule_quality.negative_lag",
    "schedule_quality.excessive_lag",
    "schedule_quality.hard_constraints",
    "schedule_quality.negative_float",
    "schedule_quality.high_float",
    "schedule_quality.missing_duration",
}


def _ctx(
    activities: list[dict] | None = None,
    relationships: list[dict] | None = None,
    locale: str = "en",
    metadata_extra: dict | None = None,
) -> ValidationContext:
    metadata = {"locale": locale}
    if metadata_extra:
        metadata.update(metadata_extra)
    data: dict = {}
    if activities is not None:
        data["activities"] = activities
    if relationships is not None:
        data["relationships"] = relationships
    return ValidationContext(data=data, metadata=metadata)


# ── ScheduleOpenEnds ────────────────────────────────────────────────────────


class TestScheduleOpenEnds:
    @pytest.mark.asyncio
    async def test_pass_when_fully_linked(self) -> None:
        rule = ScheduleOpenEnds()
        activities = [
            {"id": "a", "name": "Start mobilise", "activity_type": "start_milestone"},
            {"id": "b", "name": "Excavate", "duration_days": 5},
            {"id": "c", "name": "Closeout", "activity_type": "finish_milestone"},
        ]
        relationships = [
            {"predecessor_id": "a", "successor_id": "b", "relationship_type": "FS"},
            {"predecessor_id": "b", "successor_id": "c", "relationship_type": "FS"},
        ]
        results = await rule.validate(_ctx(activities, relationships))
        # Only the non-milestone task is judged; milestones are exempt.
        assert len(results) == 1
        assert results[0].element_ref == "b"
        assert results[0].passed
        assert results[0].message == "OK"

    @pytest.mark.asyncio
    async def test_fail_on_dangling_activity(self) -> None:
        rule = ScheduleOpenEnds()
        activities = [{"id": "lonely", "name": "Orphan task", "duration_days": 3}]
        results = await rule.validate(_ctx(activities, relationships=[]))
        assert len(results) == 1
        assert not results[0].passed
        assert results[0].severity == Severity.WARNING
        assert "Orphan task" in results[0].message
        assert results[0].suggestion is not None

    @pytest.mark.asyncio
    async def test_inline_dependency_counts_as_predecessor(self) -> None:
        rule = ScheduleOpenEnds()
        activities = [
            {"id": "x", "name": "Has inline pred", "duration_days": 2, "dependencies": [{"id": "p"}]},
        ]
        relationships = [{"predecessor_id": "x", "successor_id": "y"}]
        results = await rule.validate(_ctx(activities, relationships))
        # x has an inline predecessor and an explicit successor -> passes.
        assert results[0].passed

    @pytest.mark.asyncio
    async def test_empty_schedule_skipped(self) -> None:
        rule = ScheduleOpenEnds()
        results = await rule.validate(_ctx([], []))
        assert results == []


# ── ScheduleNegativeLag ─────────────────────────────────────────────────────


class TestScheduleNegativeLag:
    @pytest.mark.asyncio
    async def test_pass_on_zero_and_positive_lag(self) -> None:
        rule = ScheduleNegativeLag()
        relationships = [
            {"predecessor_id": "a", "successor_id": "b", "lag_days": 0},
            {"predecessor_id": "b", "successor_id": "c", "lag_days": 5},
        ]
        results = await rule.validate(_ctx(relationships=relationships))
        assert len(results) == 2
        assert all(r.passed for r in results)
        assert all(r.message == "OK" for r in results)

    @pytest.mark.asyncio
    async def test_fail_on_negative_lag(self) -> None:
        rule = ScheduleNegativeLag()
        relationships = [{"predecessor_id": "a", "successor_id": "b", "lag_days": -3}]
        results = await rule.validate(_ctx(relationships=relationships))
        assert not results[0].passed
        assert results[0].severity == Severity.ERROR
        assert "-3" in results[0].message
        assert results[0].suggestion is not None

    @pytest.mark.asyncio
    async def test_no_relationships_skipped(self) -> None:
        rule = ScheduleNegativeLag()
        results = await rule.validate(_ctx(relationships=[]))
        assert results == []


# ── ScheduleExcessiveLag ────────────────────────────────────────────────────


class TestScheduleExcessiveLag:
    @pytest.mark.asyncio
    async def test_pass_under_threshold(self) -> None:
        rule = ScheduleExcessiveLag()
        relationships = [{"predecessor_id": "a", "successor_id": "b", "lag_days": 10}]
        results = await rule.validate(_ctx(relationships=relationships))
        assert results[0].passed
        assert results[0].message == "OK"

    @pytest.mark.asyncio
    async def test_fail_over_threshold(self) -> None:
        rule = ScheduleExcessiveLag()
        relationships = [{"predecessor_id": "a", "successor_id": "b", "lag_days": 40}]
        results = await rule.validate(_ctx(relationships=relationships))
        assert not results[0].passed
        assert results[0].severity == Severity.WARNING
        assert "40" in results[0].message
        assert "20" in results[0].message  # default threshold appears

    @pytest.mark.asyncio
    async def test_threshold_override_via_metadata(self) -> None:
        rule = ScheduleExcessiveLag()
        relationships = [{"predecessor_id": "a", "successor_id": "b", "lag_days": 40}]
        ctx = _ctx(
            relationships=relationships,
            metadata_extra={"schedule_quality": {"max_lag_days": 60}},
        )
        results = await rule.validate(ctx)
        # 40 <= 60 override -> passes.
        assert results[0].passed


# ── ScheduleHardConstraints ─────────────────────────────────────────────────


class TestScheduleHardConstraints:
    @pytest.mark.asyncio
    async def test_pass_with_soft_constraint(self) -> None:
        rule = ScheduleHardConstraints()
        activities = [{"id": "a", "name": "Pour slab", "constraint_type": "start_no_earlier"}]
        results = await rule.validate(_ctx(activities))
        assert results[0].passed
        assert results[0].message == "OK"

    @pytest.mark.asyncio
    async def test_pass_with_no_constraint(self) -> None:
        rule = ScheduleHardConstraints()
        activities = [{"id": "a", "name": "Pour slab"}]
        results = await rule.validate(_ctx(activities))
        assert results[0].passed

    @pytest.mark.asyncio
    async def test_fail_on_must_finish_on(self) -> None:
        rule = ScheduleHardConstraints()
        activities = [{"id": "a", "name": "Handover", "constraint_type": "must_finish_on"}]
        results = await rule.validate(_ctx(activities))
        assert not results[0].passed
        assert results[0].severity == Severity.WARNING
        assert "Handover" in results[0].message
        assert "must_finish_on" in results[0].message


# ── ScheduleNegativeFloat ───────────────────────────────────────────────────


class TestScheduleNegativeFloat:
    @pytest.mark.asyncio
    async def test_pass_on_non_negative_float(self) -> None:
        rule = ScheduleNegativeFloat()
        activities = [{"id": "a", "name": "On track", "total_float": 4}]
        results = await rule.validate(_ctx(activities))
        assert results[0].passed
        assert results[0].message == "OK"

    @pytest.mark.asyncio
    async def test_fail_on_negative_float(self) -> None:
        rule = ScheduleNegativeFloat()
        activities = [{"id": "a", "name": "Behind", "total_float": -2}]
        results = await rule.validate(_ctx(activities))
        assert not results[0].passed
        assert results[0].severity == Severity.ERROR
        assert "Behind" in results[0].message
        assert "-2" in results[0].message

    @pytest.mark.asyncio
    async def test_missing_float_skipped(self) -> None:
        """No CPM result yet (total_float None) -> nothing to judge."""
        rule = ScheduleNegativeFloat()
        activities = [{"id": "a", "name": "No pass yet"}]
        results = await rule.validate(_ctx(activities))
        assert results == []


# ── ScheduleHighFloat ───────────────────────────────────────────────────────


class TestScheduleHighFloat:
    @pytest.mark.asyncio
    async def test_pass_under_threshold(self) -> None:
        rule = ScheduleHighFloat()
        activities = [{"id": "a", "name": "Normal", "total_float": 10}]
        results = await rule.validate(_ctx(activities))
        assert results[0].passed
        assert results[0].message == "OK"

    @pytest.mark.asyncio
    async def test_fail_over_threshold(self) -> None:
        rule = ScheduleHighFloat()
        activities = [{"id": "a", "name": "Loose", "total_float": 90}]
        results = await rule.validate(_ctx(activities))
        assert not results[0].passed
        assert results[0].severity == Severity.INFO
        assert "Loose" in results[0].message
        assert "90" in results[0].message

    @pytest.mark.asyncio
    async def test_negative_float_left_to_other_rule(self) -> None:
        """Negative float is owned by ScheduleNegativeFloat; high-float skips it."""
        rule = ScheduleHighFloat()
        activities = [{"id": "a", "name": "Behind", "total_float": -5}]
        results = await rule.validate(_ctx(activities))
        assert results == []


# ── ScheduleMissingDuration ─────────────────────────────────────────────────


class TestScheduleMissingDuration:
    @pytest.mark.asyncio
    async def test_pass_with_positive_duration(self) -> None:
        rule = ScheduleMissingDuration()
        activities = [{"id": "a", "name": "Build wall", "duration_days": 7}]
        results = await rule.validate(_ctx(activities))
        assert results[0].passed
        assert results[0].message == "OK"

    @pytest.mark.asyncio
    async def test_milestone_zero_duration_passes(self) -> None:
        rule = ScheduleMissingDuration()
        activities = [{"id": "m", "name": "Phase gate", "activity_type": "milestone", "duration_days": 0}]
        results = await rule.validate(_ctx(activities))
        assert results[0].passed

    @pytest.mark.asyncio
    async def test_fail_on_zero_duration_task(self) -> None:
        rule = ScheduleMissingDuration()
        activities = [{"id": "a", "name": "Unfinished entry", "duration_days": 0}]
        results = await rule.validate(_ctx(activities))
        assert not results[0].passed
        assert results[0].severity == Severity.WARNING
        assert "Unfinished entry" in results[0].message

    @pytest.mark.asyncio
    async def test_fail_on_missing_duration(self) -> None:
        rule = ScheduleMissingDuration()
        activities = [{"id": "a", "name": "No duration set"}]
        results = await rule.validate(_ctx(activities))
        assert not results[0].passed
        assert results[0].severity == Severity.WARNING


# ── End-to-end: full schedule_quality rule-set run ──────────────────────────


class TestScheduleQualityRuleSetIntegration:
    @pytest.mark.asyncio
    async def test_builtin_registration_wires_up_all_rules(self) -> None:
        """The public ``register_builtin_rules`` entrypoint registers the
        whole schedule_quality pack into the shared registry.

        Registering twice is idempotent by rule_id, so this is safe even when
        earlier tests already called the loader.
        """
        from app.core.validation.engine import rule_registry

        register_builtin_rules()
        assert rule_registry.list_rule_sets().get("schedule_quality", 0) >= 7
        ids = {r["rule_id"] for r in rule_registry.list_rules("schedule_quality")}
        assert SCHEDULE_QUALITY_RULE_IDS.issubset(ids)

    @pytest.mark.asyncio
    async def test_rule_set_produces_localized_output(self) -> None:
        """Running the whole pack in German yields non-English messages."""
        registry = RuleRegistry()
        for rule in (
            ScheduleOpenEnds(),
            ScheduleNegativeLag(),
            ScheduleExcessiveLag(),
            ScheduleHardConstraints(),
            ScheduleNegativeFloat(),
            ScheduleHighFloat(),
            ScheduleMissingDuration(),
        ):
            registry.register(rule)
        engine = ValidationEngine(registry)

        activities = [
            {"id": "a", "name": "Pour", "duration_days": 0, "total_float": -2, "constraint_type": "must_finish_on"},
        ]
        relationships = [{"predecessor_id": "a", "successor_id": "b", "lag_days": -1}]
        report = await engine.validate(
            data={"activities": activities, "relationships": relationships},
            rule_sets=["schedule_quality"],
            metadata={"locale": "de"},
        )
        # Negative float + negative lag are ERROR severity and must fire.
        assert report.has_errors
        # German output: the hard-constraint warning mentions "Vorgang".
        all_messages = "\n".join(r.message for r in report.results if not r.passed)
        assert "Vorgang" in all_messages, f"expected German output, got: {all_messages}"
