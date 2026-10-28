# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A revision compare must never present a partial diff as a complete one.

``compare_documents`` used to read each side with ``limit=500`` over a
``created_at DESC`` ordering. Two documents were therefore sliced into two
different windows of the drawing set, so a measurement inside one window and
outside the other came out as added or removed even though nothing about it
changed, and its money delta landed in ``net_cost_impact``. Nothing in the
response said any of this had happened.

These tests pin the replacement contract:

    * both sides are read in full, so a set well past the old cap compares
      clean instead of inventing added / removed rows;
    * when a document really does exceed the memory ceiling, the summary says
      ``truncated`` and carries the true row totals;
    * the draft-variation narrative repeats that warning, because that path
      turns the compare into a money figure a human is asked to confirm.

No database is touched: the measurement repository is replaced with an
in-memory fake that honours the same contract.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

# ``app.modules.takeoff.service`` loads config on import; point DATA_DIR at a
# scratch directory the same way the sibling takeoff unit tests do.
_PREVIOUS_DATA_DIR = os.environ.get("DATA_DIR")
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-takeoff-compare-"))
os.environ["DATA_DIR"] = str(_TMP_DIR)

from app.modules.takeoff import service as takeoff_service  # noqa: E402
from app.modules.takeoff.service import (  # noqa: E402
    MAX_COMPARE_MEASUREMENTS,
    TakeoffService,
    _build_pdf_revision_narrative,
)

# Put it back. DATA_DIR is process wide and only the import above reads it, so
# left set it answers every later module that asks resolve_data_dir() where the
# platform writes, and the failure surfaces in whichever unrelated test asks.
if _PREVIOUS_DATA_DIR is None:
    os.environ.pop("DATA_DIR", None)
else:
    os.environ["DATA_DIR"] = _PREVIOUS_DATA_DIR


pytestmark = pytest.mark.unit


def _measurement(idx: int, *, value: str, document_id: str) -> SimpleNamespace:
    """Minimal ducktype for ``TakeoffMeasurement``.

    Only the attributes the compare reads are present, which keeps the test
    off the ORM mapper and off the database.
    """
    return SimpleNamespace(
        id=uuid.uuid4(),
        document_id=document_id,
        type="area",
        group_name="General",
        page=1 + idx // 50,
        annotation=f"A{idx}",
        measurement_value=Decimal(value),
        volume=None,
        count_value=None,
        measurement_unit="m2",
        linked_boq_position_id=None,
        metadata_={},
    )


class _FakeMeasurementRepo:
    """In-memory stand-in honouring the two methods the compare calls."""

    def __init__(self, by_document: dict[str, list[Any]]) -> None:
        self.by_document = by_document

    async def count_for_document(self, project_id: uuid.UUID, document_id: str) -> int:
        return len(self.by_document.get(document_id, []))

    async def list_all_for_document(
        self,
        project_id: uuid.UUID,
        document_id: str,
        *,
        max_rows: int,
        chunk_size: int = 1000,
    ) -> list[Any]:
        return list(self.by_document.get(document_id, []))[:max_rows]


class _CaptureHandler(logging.Handler):
    """Collect records straight off one logger.

    Attached to the module logger directly rather than going through
    ``caplog``, so the assertions hold regardless of how the app configures
    propagation and root handlers.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _capture(logger: logging.Logger) -> Iterator[_CaptureHandler]:
    """Capture every record ``logger`` emits inside the block."""
    handler = _CaptureHandler()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def _service(by_document: dict[str, list[Any]]) -> TakeoffService:
    svc = TakeoffService(None)  # type: ignore[arg-type]
    svc.measurement_repo = _FakeMeasurementRepo(by_document)  # type: ignore[assignment]
    return svc


async def test_compare_reads_past_the_old_500_row_window() -> None:
    """A 600-row set on both sides compares clean, with no invented rows.

    Under the old windowed read this is exactly the shape that produced
    phantom added / removed rows. Every measurement is identical across the
    two documents, so the only honest tally is 600 unchanged.
    """
    rows = 600
    docs = {
        "rev-a": [_measurement(i, value="10.0", document_id="rev-a") for i in range(rows)],
        "rev-b": [_measurement(i, value="10.0", document_id="rev-b") for i in range(rows)],
    }
    result = await _service(docs).compare_documents(uuid.uuid4(), "rev-a", "rev-b")

    summary = result["summary"]
    assert summary["measurements"]["unchanged"] == rows
    assert summary["measurements"]["added"] == 0
    assert summary["measurements"]["removed"] == 0
    assert summary["from_measurement_count"] == rows
    assert summary["to_measurement_count"] == rows
    assert summary["truncated"] is False
    assert summary["truncation_limit"] is None


async def test_compare_reports_real_totals_when_not_truncated() -> None:
    """The totals are always present, so a client never has to infer them."""
    docs = {
        "rev-a": [_measurement(i, value="1.0", document_id="rev-a") for i in range(3)],
        "rev-b": [_measurement(i, value="2.0", document_id="rev-b") for i in range(5)],
    }
    summary = (await _service(docs).compare_documents(uuid.uuid4(), "rev-a", "rev-b"))["summary"]

    assert summary["from_measurement_total"] == 3
    assert summary["to_measurement_total"] == 5
    assert summary["truncated"] is False


async def test_compare_over_the_cap_reports_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A set larger than the ceiling is flagged, never served as complete."""
    monkeypatch.setattr(takeoff_service, "MAX_COMPARE_MEASUREMENTS", 5)
    docs = {
        "rev-a": [_measurement(i, value="1.0", document_id="rev-a") for i in range(12)],
        "rev-b": [_measurement(i, value="1.0", document_id="rev-b") for i in range(9)],
    }

    with _capture(takeoff_service.logger) as handler:
        summary = (await _service(docs).compare_documents(uuid.uuid4(), "rev-a", "rev-b"))["summary"]

    assert summary["truncated"] is True
    assert summary["truncation_limit"] == 5
    # What was compared, versus what is really there.
    assert summary["from_measurement_count"] == 5
    assert summary["to_measurement_count"] == 5
    assert summary["from_measurement_total"] == 12
    assert summary["to_measurement_total"] == 9
    warnings = [r for r in handler.records if r.levelno >= logging.WARNING]
    assert warnings, "a truncated compare must log above DEBUG"
    assert any("truncated" in r.getMessage() for r in warnings)


async def test_compare_counts_collapsed_duplicate_keys() -> None:
    """Measurements sharing a compare key collapse by design, and are counted."""
    dupes = [_measurement(0, value="1.0", document_id="rev-a") for _ in range(3)]
    docs = {"rev-a": dupes, "rev-b": []}
    summary = (await _service(docs).compare_documents(uuid.uuid4(), "rev-a", "rev-b"))["summary"]

    assert summary["from_measurement_count"] == 3
    assert summary["measurements"]["removed"] == 1
    assert summary["collapsed_duplicate_keys"] == 2


def test_default_cap_is_far_above_the_old_window() -> None:
    """The ceiling is a memory guard, not a page size."""
    assert MAX_COMPARE_MEASUREMENTS >= 20000


def test_variation_narrative_repeats_the_truncation_warning() -> None:
    """A draft variation must state that its money figure is partial."""
    note = "WARNING: the source compare was truncated at 20000 measurements per document. "
    text = _build_pdf_revision_narrative(
        measurement_tally={"added": 1, "removed": 0, "modified": 2, "unchanged": 3},
        changed_linked_count=2,
        truncation_note=note,
    )
    assert note in text
    assert "Review and confirm" in text


def test_variation_narrative_is_unchanged_without_truncation() -> None:
    """The normal path reads exactly as it did before."""
    text = _build_pdf_revision_narrative(
        measurement_tally={"added": 1, "removed": 0, "modified": 2, "unchanged": 3},
        changed_linked_count=2,
    )
    assert "WARNING" not in text
