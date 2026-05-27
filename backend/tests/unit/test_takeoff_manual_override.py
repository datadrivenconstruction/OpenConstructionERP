# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests — manual measurement override behavior.

Covers bullet 8 of the R7 hardening sweep:
  * A user's manual correction overrides the AI suggestion.
  * Manual measurements (TakeoffMeasurement) carry ``confidence=None``
    (the ORM model has no confidence column) — not 0.0.
  * Updating a measurement with new geometry via PATCH re-computes the
    measurement_value server-side from the new points (Audit B8).
  * The ``ai_confidence`` concept: extractedElement AI output carries
    confidence; once a user manually edits a measurement, the persisted
    record has no AI confidence (the field does not exist on the ORM).
  * After update_measurement, the new measurement_value reflects the
    new geometry, not the old client-submitted value.

All tests are pure-Python — no DB, no HTTP, no filesystem.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.takeoff.schemas import PointSchema, TakeoffMeasurementUpdate
from app.modules.takeoff.service import (
    TakeoffService,
    recompute_measurement_value,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MeasurementStub:
    """Minimal TakeoffMeasurement stand-in for update_measurement tests."""

    def __init__(
        self,
        *,
        mtype: str = "distance",
        points: list | None = None,
        scale: float | None = 100.0,
        count_value: int | None = None,
        measurement_value: float | None = None,
    ) -> None:
        self.id = uuid.uuid4()
        self.type = mtype
        self.points = points or [{"x": 0.0, "y": 0.0}, {"x": 300.0, "y": 0.0}]
        self.scale_pixels_per_unit = scale
        self.count_value = count_value
        self.measurement_value = measurement_value
        # Non-geometry fields needed by update_measurement
        self.document_id = None
        self.page = 1
        self.group_name = "General"
        self.group_color = "#3B82F6"
        self.annotation = None
        self.measurement_unit = "m"
        self.depth = None
        self.volume = None
        self.perimeter = None
        self.linked_boq_position_id = None
        self.metadata_ = {}
        self.created_by = ""


def _make_service() -> TakeoffService:
    svc = object.__new__(TakeoffService)
    svc.session = AsyncMock()
    svc.session.refresh = AsyncMock()
    svc.repo = MagicMock()
    svc.measurement_repo = MagicMock()
    svc.measurement_repo.update_fields = AsyncMock()
    return svc


# ---------------------------------------------------------------------------
# Measurement model has NO confidence column
# ---------------------------------------------------------------------------


class TestMeasurementModelHasNoConfidence:
    def test_takeoff_measurement_no_confidence_column(self) -> None:
        """TakeoffMeasurement ORM table must NOT have a confidence column.

        Manual measurements are human-drawn; an AI confidence score has no
        meaning. If a confidence column existed it would default to 0.0
        and misrepresent the item as "AI very unsure" instead of "no AI".
        """
        from app.modules.takeoff.models import TakeoffMeasurement

        columns = {col.key for col in TakeoffMeasurement.__table__.columns}
        assert "confidence" not in columns, (
            "TakeoffMeasurement must not have a confidence column. Manual measurements have no AI score."
        )

    def test_takeoff_measurement_no_ai_confidence_column(self) -> None:
        """Also check for alternative names sometimes used."""
        from app.modules.takeoff.models import TakeoffMeasurement

        columns = {col.key for col in TakeoffMeasurement.__table__.columns}
        for name in ("ai_confidence", "score", "certainty"):
            assert name not in columns, f"TakeoffMeasurement must not have '{name}' column."


# ---------------------------------------------------------------------------
# Manual correction overrides AI suggestion via update_measurement
# ---------------------------------------------------------------------------


class TestManualOverrideUpdatesValue:
    """PATCH measurement with new geometry → server recomputes value."""

    @pytest.mark.asyncio
    async def test_patch_with_new_points_triggers_recompute(self) -> None:
        """Updating points causes measurement_value to be recomputed server-side.

        The client's old value is NOT preserved when geometry changes.
        """
        svc = _make_service()

        # Existing: 300px distance at scale 100 px/m = 3.0 m
        stub = _MeasurementStub(
            mtype="distance",
            points=[{"x": 0.0, "y": 0.0}, {"x": 300.0, "y": 0.0}],
            scale=100.0,
            measurement_value=3.0,
        )

        # PATCH: user manually draws a new 500px segment → 5.0 m
        new_points = [
            PointSchema(x=0.0, y=0.0),
            PointSchema(x=500.0, y=0.0),
        ]
        update = TakeoffMeasurementUpdate(
            points=new_points,
            measurement_value=9999.0,  # client's stale/wrong value — must be ignored
        )

        captured: dict = {}

        async def _capture_update(mid, **fields):
            captured.update(fields)

        svc.measurement_repo.update_fields = _capture_update

        await svc.update_measurement(stub.id, update, existing=stub)

        recomputed = captured.get("measurement_value")
        assert recomputed is not None
        # 500 px / 100 px/m = 5.0 m — client's 9999.0 must be ignored
        assert abs(recomputed - 5.0) < 0.01, f"Expected recomputed value ~5.0 m, got {recomputed}"

    @pytest.mark.asyncio
    async def test_patch_without_geometry_preserves_existing_value(self) -> None:
        """A PATCH that touches only non-geometry fields keeps the existing value."""
        svc = _make_service()

        stub = _MeasurementStub(
            mtype="distance",
            points=[{"x": 0.0, "y": 0.0}, {"x": 200.0, "y": 0.0}],
            scale=100.0,
            measurement_value=2.0,
        )

        # Only update annotation — no geometry change.
        update = TakeoffMeasurementUpdate(annotation="This is a wall segment")

        captured: dict = {}

        async def _capture_update(mid, **fields):
            captured.update(fields)

        svc.measurement_repo.update_fields = _capture_update

        await svc.update_measurement(stub.id, update, existing=stub)

        # measurement_value should NOT be in the captured fields since
        # no geometry trigger was touched.
        assert "measurement_value" not in captured, "Non-geometry PATCH must not recompute measurement_value"


# ---------------------------------------------------------------------------
# AI suggestions carry confidence; manual corrections carry None
# ---------------------------------------------------------------------------


class TestConfidenceOnlyOnAiOutput:
    def test_extracted_element_has_numeric_confidence(self) -> None:
        """ExtractedElement (from AI/table extraction) MUST have a numeric confidence."""
        from app.modules.takeoff.schemas import ExtractedElement

        el = ExtractedElement(
            id="ai_1",
            category="general",
            description="Concrete slab",
            quantity=50.0,
            unit="m2",
            confidence=0.85,
        )
        assert isinstance(el.confidence, float)
        assert 0.0 <= el.confidence <= 1.0

    def test_recompute_measurement_value_ignores_confidence(self) -> None:
        """recompute_measurement_value has no confidence parameter.

        This test ensures the server-side recompute function signature
        does NOT accept a confidence parameter — confidence belongs to AI
        output (ExtractedElement), not to the geometry recomputation.
        """
        import inspect

        sig = inspect.signature(recompute_measurement_value)
        assert "confidence" not in sig.parameters, (
            "recompute_measurement_value must not accept a confidence parameter. "
            "Confidence is an AI-output concern, not a geometry-recompute concern."
        )


# ---------------------------------------------------------------------------
# recompute_measurement_value correctness (sanity, covers the server-side path)
# ---------------------------------------------------------------------------


class TestRecomputeMeasurementValue:
    def test_distance_two_points(self) -> None:
        """300 px distance / 100 px/m = 3.0 m."""
        pts = [PointSchema(x=0.0, y=0.0), PointSchema(x=300.0, y=0.0)]
        result = recompute_measurement_value(
            measurement_type="distance",
            points=pts,
            scale_pixels_per_unit=100.0,
            count_value=None,
            client_value=None,
        )
        assert result == pytest.approx(3.0)

    def test_area_square(self) -> None:
        """A 100×100 px square at 10 px/m = 100 m²."""
        pts = [
            PointSchema(x=0.0, y=0.0),
            PointSchema(x=100.0, y=0.0),
            PointSchema(x=100.0, y=100.0),
            PointSchema(x=0.0, y=100.0),
        ]
        result = recompute_measurement_value(
            measurement_type="area",
            points=pts,
            scale_pixels_per_unit=10.0,
            count_value=None,
            client_value=None,
        )
        assert result == pytest.approx(100.0)

    def test_count_uses_count_value_not_geometry(self) -> None:
        """Count type ignores points and uses count_value."""
        pts = [PointSchema(x=0.0, y=0.0), PointSchema(x=500.0, y=500.0)]
        result = recompute_measurement_value(
            measurement_type="count",
            points=pts,
            scale_pixels_per_unit=100.0,
            count_value=7,
            client_value=None,
        )
        assert result == 7.0

    def test_client_value_used_for_annotation_types(self) -> None:
        """Annotation types (text, cloud, etc.) fall back to client_value."""
        result = recompute_measurement_value(
            measurement_type="text",
            points=[],
            scale_pixels_per_unit=100.0,
            count_value=None,
            client_value=42.0,
        )
        assert result == 42.0

    def test_no_scale_falls_back_to_client_value(self) -> None:
        """Without scale, geometry cannot be converted — echo client_value."""
        pts = [PointSchema(x=0.0, y=0.0), PointSchema(x=300.0, y=0.0)]
        result = recompute_measurement_value(
            measurement_type="distance",
            points=pts,
            scale_pixels_per_unit=None,
            count_value=None,
            client_value=5.5,
        )
        assert result == 5.5
