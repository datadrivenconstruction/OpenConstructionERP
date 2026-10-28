# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every measurement records where its scale came from, or admits it does not.

A wrong scale is the one takeoff error that multiplies through every quantity
on a sheet. Storing the ratio without its origin means a takeoff found to be
mis-scaled cannot be narrowed to the rows that actually inherited the bad
calibration, so the whole document goes back to be re-checked by hand.

The tests below pin the two halves of that promise. The easy half is that each
creation path stamps the right source. The half that actually protects the
user is that no path ever stamps a source it does not know: an unstated source
stays NULL, a page with no scale yields no source, and a patch that moves the
ratio without saying why clears the old label rather than letting it stand as
a claim that has quietly become false. A wrong provenance is worse than a
missing one, because it is the one a recompute would trust.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.takeoff.schemas import TakeoffMeasurementCreate, TakeoffMeasurementUpdate
from app.modules.takeoff.service import TakeoffService, clear_stale_scale_source

# ---------------------------------------------------------------------------
# The schema contract
# ---------------------------------------------------------------------------


async def _no_row(*_a: Any, **_k: Any) -> None:
    """Session.get stub: the drawing lookup finds no register row."""
    return


@pytest.mark.parametrize(
    "source",
    ["page_text", "recovered_text", "vision_read", "manual_calibration", "preset", "inherited"],
)
def test_every_documented_source_is_accepted(source: str) -> None:
    data = TakeoffMeasurementCreate(project_id=uuid.uuid4(), type="area", scale_source=source)
    assert data.scale_source == source


def test_an_unknown_source_is_refused() -> None:
    """A closed set, not free text.

    This column feeds a "recompute exactly these rows" decision. A field that
    accepts anything is a field nothing can filter on, and a typo would then
    silently exclude rows from the recompute that needed it most.
    """
    with pytest.raises(ValidationError):
        TakeoffMeasurementCreate(project_id=uuid.uuid4(), type="area", scale_source="eyeballed")


def test_the_source_is_optional_and_defaults_to_not_recorded() -> None:
    # An older client sends nothing. NULL is the honest answer for it, and the
    # alternative - defaulting to a plausible-looking source - would put a
    # claim on the row that nobody made.
    data = TakeoffMeasurementCreate(project_id=uuid.uuid4(), type="area")
    assert data.scale_source is None


def test_an_update_that_omits_the_source_does_not_carry_a_value() -> None:
    # The service distinguishes "not sent" from "sent as null" through
    # exclude_unset, so this has to stay out of the dump entirely.
    patch = TakeoffMeasurementUpdate(annotation="hello")
    assert "scale_source" not in patch.model_dump(exclude_unset=True)


# ---------------------------------------------------------------------------
# The hand-drawn path, which is where most measurements come from
# ---------------------------------------------------------------------------


def _service_with_stub_repo() -> tuple[TakeoffService, list[Any]]:
    """A service whose repository records the rows it was asked to persist."""
    saved: list[Any] = []
    svc = object.__new__(TakeoffService)
    svc.session = SimpleNamespace(get=_no_row)

    async def _create(row: Any) -> Any:
        saved.append(row)
        return row

    async def _create_bulk(rows: list[Any]) -> list[Any]:
        saved.extend(rows)
        return rows

    async def _validate(_doc_id: Any, _project_id: Any) -> None:
        return None

    svc.measurement_repo = SimpleNamespace(create=_create, create_bulk=_create_bulk)
    svc._validate_document_id = _validate  # type: ignore[method-assign]
    return svc, saved


@pytest.mark.asyncio
async def test_a_hand_drawn_measurement_keeps_the_source_the_client_stated() -> None:
    """Only the drawing surface knows this.

    Whether the user calibrated the page, picked a preset, or drew on a scale
    somebody else had already set is not visible from the ratio alone, so the
    server records what the client says rather than inferring it.
    """
    svc, saved = _service_with_stub_repo()
    await svc.create_measurement(
        TakeoffMeasurementCreate(
            project_id=uuid.uuid4(),
            type="area",
            scale_pixels_per_unit=120.0,
            scale_source="manual_calibration",
        )
    )
    assert [r.scale_source for r in saved] == ["manual_calibration"]


@pytest.mark.asyncio
async def test_a_client_that_states_nothing_produces_a_null_not_a_guess() -> None:
    svc, saved = _service_with_stub_repo()
    await svc.create_measurement(
        TakeoffMeasurementCreate(project_id=uuid.uuid4(), type="area", scale_pixels_per_unit=120.0)
    )
    assert saved[0].scale_source is None


@pytest.mark.asyncio
async def test_a_bulk_import_carries_the_source_per_row() -> None:
    """The localStorage import sends a mixed batch.

    Stamping the whole batch from the first row, or from a single request
    field, would relabel rows that were captured differently in the same
    session - which is the failure mode a per-row column exists to avoid.
    """
    svc, saved = _service_with_stub_repo()
    project_id = uuid.uuid4()
    await svc.bulk_create_measurements(
        [
            TakeoffMeasurementCreate(
                project_id=project_id, type="area", scale_pixels_per_unit=120.0, scale_source="preset"
            ),
            TakeoffMeasurementCreate(
                project_id=project_id,
                type="distance",
                scale_pixels_per_unit=120.0,
                scale_source="manual_calibration",
            ),
            TakeoffMeasurementCreate(project_id=project_id, type="count"),
        ]
    )
    assert [r.scale_source for r in saved] == ["preset", "manual_calibration", None]


# ---------------------------------------------------------------------------
# Detector proposals: the scale is inherited from the page, never read
# ---------------------------------------------------------------------------


def _service() -> TakeoffService:
    """A service instance with no session, for the pure builder paths."""
    svc = object.__new__(TakeoffService)
    svc.session = SimpleNamespace(get=_no_row)
    return svc


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("page_scale", "expected"),
    [
        (120.0, "inherited"),
        # No scale on the page means nothing was inherited either. Stamping a
        # source here would claim a provenance for a ratio that does not exist.
        (None, None),
    ],
)
async def test_a_detector_proposal_inherits_the_pages_scale(page_scale: float | None, expected: str | None) -> None:
    """The offline detectors read geometry, never a scale.

    Recognize and similar-symbols measure at whatever calibration the sheet
    already carries, so ``inherited`` is the only honest label for them - and
    it is the one that lets a recalibration find these rows later.
    """
    svc, saved = _service_with_stub_repo()
    doc = SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4())
    await svc._persist_proposals(
        doc,  # type: ignore[arg-type]
        1,
        [{"type": "area", "points": [{"x": 0, "y": 0}, {"x": 10, "y": 0}, {"x": 10, "y": 10}], "confidence": 0.8}],
        detector="recognize",
        scale_pixels_per_unit=page_scale,
        user_id=str(uuid.uuid4()),
    )
    assert [r.scale_source for r in saved] == [expected]


class _Run:
    """Minimal stand-in for ``AiTakeoffRun`` in the proposal builder."""

    def __init__(self, calibrated: float | None) -> None:
        self.id = uuid.uuid4()
        self.project_id = uuid.uuid4()
        self.document_id = str(uuid.uuid4())
        self.page = 1
        self.scale_pixels_per_unit = calibrated


class _Room:
    def __init__(self) -> None:
        self.name = "Office"
        self.confidence = 0.9
        self.polygon = [(0.1, 0.1), (0.4, 0.1), (0.4, 0.4), (0.1, 0.4)]


def _result(rooms: list[Any]) -> Any:
    return SimpleNamespace(rooms=rooms, symbols=[], scale=None)


def _build(calibrated: float | None, scale_ratio: float | None) -> list[Any]:
    return _service()._build_plan_read_proposals(
        run=_Run(calibrated),
        result=_result([_Room()]),
        page_w_pt=595.0,
        page_h_pt=842.0,
        scale_ratio=scale_ratio,
        user_id=str(uuid.uuid4()),
    )


def test_a_users_calibration_that_survived_is_recorded_as_inherited() -> None:
    """The run carried a calibration and it won the plausibility belt.

    The proposals are measured at a ratio the user set on the page, so that is
    what they inherited - not something the model read.
    """
    rows = _build(calibrated=120.0, scale_ratio=120.0)
    assert rows, "the builder is expected to produce a room proposal"
    assert all(r.scale_source == "inherited" for r in rows)


def test_a_scale_the_model_read_is_recorded_as_vision_read() -> None:
    """No calibration on the run, so the surviving ratio came off the sheet.

    Kept distinct from ``page_text`` deliberately: the same "1:100" carries a
    different weight when it was inferred from pixels rather than parsed from
    the text layer, and that difference is the reason to record a source.
    """
    rows = _build(calibrated=None, scale_ratio=90.0)
    assert all(r.scale_source == "vision_read" for r in rows)


def test_a_dropped_calibration_is_not_reported_as_inherited() -> None:
    """An implausible calibration is discarded and the model's scale used.

    Labelling that "inherited" would credit the user for a ratio their
    calibration lost, which is precisely the misleading provenance this
    column has to avoid.
    """
    rows = _build(calibrated=1_000_000.0, scale_ratio=90.0)
    assert all(r.scale_source == "vision_read" for r in rows)


def test_no_surviving_scale_leaves_the_source_empty() -> None:
    # With no scale the areas are empty too. Naming a source for a number we
    # do not have would be confident fiction.
    rows = _build(calibrated=None, scale_ratio=None)
    assert all(r.scale_source is None for r in rows)


# ---------------------------------------------------------------------------
# A patch that moves the ratio must not leave a stale label behind
# ---------------------------------------------------------------------------


def test_changing_the_scale_without_saying_why_clears_the_old_source() -> None:
    patch = TakeoffMeasurementUpdate(scale_pixels_per_unit=150.0)
    fields = clear_stale_scale_source(patch.model_dump(exclude_unset=True))
    assert fields["scale_source"] is None


def test_changing_the_scale_and_stating_the_source_keeps_what_was_stated() -> None:
    patch = TakeoffMeasurementUpdate(scale_pixels_per_unit=150.0, scale_source="manual_calibration")
    fields = clear_stale_scale_source(patch.model_dump(exclude_unset=True))
    assert fields["scale_source"] == "manual_calibration"


def test_a_patch_that_leaves_the_scale_alone_does_not_touch_the_source() -> None:
    # Renaming a measurement must not erase where its scale came from.
    patch = TakeoffMeasurementUpdate(annotation="Room 12")
    fields = clear_stale_scale_source(patch.model_dump(exclude_unset=True))
    assert "scale_source" not in fields


def test_the_guard_reads_presence_not_truthiness() -> None:
    """Explicitly clearing the ratio is still a change of scale.

    A ``None`` ratio is falsy, so a guard written as ``if fields.get(...)``
    would skip this case and leave the row claiming a source for a scale it no
    longer has.
    """
    patch = TakeoffMeasurementUpdate(scale_pixels_per_unit=None)
    fields = clear_stale_scale_source(patch.model_dump(exclude_unset=True))
    assert fields["scale_source"] is None


def test_the_guard_is_the_one_the_service_runs() -> None:
    """Guards against this test drifting into a copy of the rule it checks.

    The value of the four tests above is that they exercise the function
    ``update_measurement`` actually calls. If that call is ever removed the
    tests would still pass while the behaviour disappears, so pin the wiring.
    """
    import inspect

    from app.modules.takeoff.service import TakeoffService

    body = inspect.getsource(TakeoffService.update_measurement)
    assert "clear_stale_scale_source(fields)" in body
