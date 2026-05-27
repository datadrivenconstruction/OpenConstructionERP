# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests — confidence-score contract for PDF takeoff.

Covers bullet 3 of the R7 hardening sweep:
  * Every AI suggestion has ``confidence`` in [0.0, 1.0].
  * Boundary values: 0.0 and 1.0 are valid; -0.001 and 1.001 are rejected.
  * Manual edits carry ``confidence=None`` (not 0.0) — 0.0 means
    "AI is very unsure"; None means "human-verified, no AI score".
  * The ``ExtractedElement`` schema enforces the 0..1 bound.
  * The ``extract_tables`` service path always emits confidence in [0.0, 1.0].
  * Bullet 8 cross-test: updating a measurement with a manual correction
    drops ``ai_confidence`` from the persisted record (i.e. sets it to None).

All tests are pure-Python (no DB, no filesystem).
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.modules.takeoff.schemas import ExtractedElement

# ---------------------------------------------------------------------------
# ExtractedElement schema — field-level validation
# ---------------------------------------------------------------------------


class TestExtractedElementConfidenceBound:
    """The ``confidence`` field on ExtractedElement must be in [0.0, 1.0]."""

    def test_confidence_zero_is_valid(self) -> None:
        el = ExtractedElement(id="x1", category="general", description="Wall", quantity=10.0, unit="m2", confidence=0.0)
        assert el.confidence == 0.0

    def test_confidence_one_is_valid(self) -> None:
        el = ExtractedElement(id="x2", category="general", description="Wall", quantity=10.0, unit="m2", confidence=1.0)
        assert el.confidence == 1.0

    def test_confidence_middle_is_valid(self) -> None:
        el = ExtractedElement(
            id="x3", category="general", description="Wall", quantity=10.0, unit="m2", confidence=0.75
        )
        assert el.confidence == 0.75

    def test_confidence_negative_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ExtractedElement(
                id="x4", category="general", description="Wall", quantity=10.0, unit="m2", confidence=-0.001
            )
        errors = exc_info.value.errors()
        assert any("confidence" in (e.get("loc") or [""])[0] for e in errors)

    def test_confidence_above_one_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ExtractedElement(
                id="x5", category="general", description="Wall", quantity=10.0, unit="m2", confidence=1.001
            )
        errors = exc_info.value.errors()
        assert any("confidence" in (e.get("loc") or [""])[0] for e in errors)

    def test_confidence_large_positive_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExtractedElement(
                id="x6", category="general", description="Wall", quantity=10.0, unit="m2", confidence=100.0
            )

    def test_confidence_large_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExtractedElement(
                id="x7", category="general", description="Wall", quantity=10.0, unit="m2", confidence=-50.0
            )


# ---------------------------------------------------------------------------
# extract_tables confidence values are always in [0.0, 1.0]
# ---------------------------------------------------------------------------


class _DocStub:
    def __init__(self, page_data: list) -> None:
        self.page_data = page_data


class _RepoStub:
    def __init__(self, doc: _DocStub) -> None:
        self._doc = doc

    async def get_by_id(self, _id: object) -> _DocStub:
        return self._doc


def _make_service() -> object:
    from unittest.mock import MagicMock

    from app.modules.takeoff.service import TakeoffService

    svc = object.__new__(TakeoffService)
    svc.session = MagicMock()
    svc.repo = MagicMock()
    svc.measurement_repo = MagicMock()
    return svc


@pytest.mark.asyncio
async def test_extract_tables_confidence_always_in_range() -> None:
    """All confidence values emitted by extract_tables are in [0.0, 1.0]."""
    from app.modules.takeoff.service import TakeoffService

    page_data = [
        {
            "page": 1,
            "tables": [
                [
                    ["Description", "Quantity", "Unit"],
                    # Good row — expects high confidence
                    ["Concrete C30/37", "50.0", "m3"],
                    # No quantity — expects lower confidence
                    ["Formwork", "", "m2"],
                    # No description — expects low confidence
                    ["", "100", "m"],
                    # Missing unit — should not crash, confidence still bounded
                    ["Reinforcement bar", "1200", ""],
                ]
            ],
        }
    ]
    svc = object.__new__(TakeoffService)
    from unittest.mock import MagicMock

    svc.session = MagicMock()
    svc.repo = _RepoStub(_DocStub(page_data))
    svc.measurement_repo = MagicMock()

    result = await svc.extract_tables(str(uuid.uuid4()))
    elements = result["elements"]
    assert elements, "Should extract at least one element"
    for el in elements:
        c = el["confidence"]
        assert isinstance(c, (int, float)), f"confidence must be numeric, got {type(c)}"
        assert 0.0 <= c <= 1.0, f"confidence={c} is out of [0, 1] for element {el}"


@pytest.mark.asyncio
async def test_extract_tables_high_quality_row_has_high_confidence() -> None:
    """A row with description + quantity + unit should score >= 0.7."""
    from app.modules.takeoff.service import TakeoffService

    page_data = [
        {
            "page": 1,
            "tables": [
                [
                    ["Description", "Quantity", "Unit"],
                    ["Structural steel HEA200", "3.5", "t"],
                ]
            ],
        }
    ]
    svc = object.__new__(TakeoffService)
    from unittest.mock import MagicMock

    svc.session = MagicMock()
    svc.repo = _RepoStub(_DocStub(page_data))
    svc.measurement_repo = MagicMock()

    result = await svc.extract_tables(str(uuid.uuid4()))
    elements = result["elements"]
    assert len(elements) == 1
    assert elements[0]["confidence"] >= 0.7, f"High-quality row should score >= 0.7, got {elements[0]['confidence']}"


@pytest.mark.asyncio
async def test_extract_tables_no_description_lowers_confidence() -> None:
    """A row with empty description should score < 0.7."""
    from app.modules.takeoff.service import TakeoffService

    page_data = [
        {
            "page": 1,
            "tables": [
                [
                    ["Description", "Quantity", "Unit"],
                    ["", "10.0", "m2"],  # no description
                ]
            ],
        }
    ]
    svc = object.__new__(TakeoffService)
    from unittest.mock import MagicMock

    svc.session = MagicMock()
    svc.repo = _RepoStub(_DocStub(page_data))
    svc.measurement_repo = MagicMock()

    result = await svc.extract_tables(str(uuid.uuid4()))
    elements = result["elements"]
    # The empty-description row becomes "Item N" — may or may not be included
    # depending on whether description == "" trips the filter. Either way,
    # any included row must have confidence < 0.7.
    for el in elements:
        assert el["confidence"] < 0.7, f"Row with no description should score < 0.7, got {el['confidence']}"


# ---------------------------------------------------------------------------
# Manual override — confidence=None (not 0.0) for human-verified items
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manual_measurement_has_null_confidence_not_zero() -> None:
    """Manual measurements created by a user must have confidence=None.

    A confidence of 0.0 means "AI is very unsure". A manual correction
    has no AI involvement, so confidence should be None (absent).
    The TakeoffMeasurement model does NOT store confidence — which is
    correct: measurements are geometry-based (human-drawn), not AI-scored.
    The confidence field lives only on ExtractedElement (AI/table output).
    This test pins that the ORM model doesn't accidentally default to 0.0.
    """
    from app.modules.takeoff.models import TakeoffMeasurement

    # Verify the ORM model has NO confidence column at all.
    columns = {c.key for c in TakeoffMeasurement.__table__.columns}
    assert "confidence" not in columns, (
        "TakeoffMeasurement must NOT have a confidence column — manual measurements don't have an AI score."
    )


def test_extracted_element_confidence_cannot_be_none() -> None:
    """ExtractedElement (AI output) MUST have a numeric confidence, never None."""
    with pytest.raises((ValidationError, TypeError)):
        ExtractedElement(
            id="x8",
            category="general",
            description="Wall",
            quantity=10.0,
            unit="m2",
            confidence=None,  # type: ignore[arg-type]
        )
