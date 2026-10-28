# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure-Python tests for the takeoff push-quantity helpers.

Estimation-cluster deep-improve wave (2026-05-28) introduced an opt-in
``push_quantity`` flag on the link-to-BOQ endpoints (PDF takeoff +
DWG takeoff). When true, the linked measurement's measured value is
copied into the target BOQ position's ``quantity`` field and the
position total is recomputed.

This module verifies the *value-picking* helper without touching the
DB — type dispatch only (volume / count / default measurement_value).
The DB-write side of the helper is covered indirectly by the existing
``link-to-boq`` integration tests once they opt into ``push_quantity``.
"""

from __future__ import annotations

import os
import tempfile
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

# The SQLAlchemy engine is already bound to the conftest-provisioned
# PostgreSQL cluster before this module imports. We never actually hit
# the DB here, but the module imports ``app.modules.takeoff.service``
# which transitively loads config, so point ``DATA_DIR`` at a scratch
# directory.
#
# ``DATA_DIR`` is process-wide state and this module is not the only thing
# in the process. It is set for the duration of one import and put back
# immediately, because nothing below reads it: these tests hand ducktypes
# to a pure helper and never touch storage. Left set, it followed the
# interpreter into every module collected after this one, and any test
# asking ``resolve_data_dir()`` where the platform writes was answered
# with this scratch directory. That is order-dependent by construction:
# it fails or passes according to which shard a splitter drops the two
# modules into, and it reads as a defect in whichever module asked.
_PREVIOUS_DATA_DIR = os.environ.get("DATA_DIR")
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-takeoff-push-"))
os.environ["DATA_DIR"] = str(_TMP_DIR)

from app.modules.takeoff.service import _pick_takeoff_value  # noqa: E402

if _PREVIOUS_DATA_DIR is None:
    os.environ.pop("DATA_DIR", None)
else:
    os.environ["DATA_DIR"] = _PREVIOUS_DATA_DIR


def _measurement(**fields: object) -> SimpleNamespace:
    """Minimal ducktype for ``TakeoffMeasurement`` — only the attrs the
    helper reads. Avoids the ORM mapper bootstrap cost in these
    micro-tests."""
    base: dict[str, object] = {
        "type": "area",
        "measurement_value": None,
        "volume": None,
        "count_value": None,
    }
    base.update(fields)
    return SimpleNamespace(**base)


def test_pick_value_volume_type_prefers_volume_column() -> None:
    """Volume measurements ship the area×depth product in ``volume``."""
    m = _measurement(type="volume", volume=Decimal("12.5"), measurement_value=Decimal("9.0"))
    assert _pick_takeoff_value(m) == 12.5


def test_pick_value_count_type_uses_count_value() -> None:
    """Count measurements expose an integer in ``count_value`` — not the
    geometry-derived ``measurement_value`` (which is undefined for counts)."""
    m = _measurement(type="count", count_value=7, measurement_value=Decimal("0"))
    assert _pick_takeoff_value(m) == 7.0


def test_pick_value_distance_type_uses_measurement_value() -> None:
    """Linear measurements (distance, area, polyline) flow through
    ``measurement_value`` — the canonical scalar column."""
    m = _measurement(type="distance", measurement_value=Decimal("3.45"))
    assert _pick_takeoff_value(m) == 3.45


def test_pick_value_area_type_uses_measurement_value() -> None:
    """Area dispatch — same column as distance/polyline."""
    m = _measurement(type="area", measurement_value=Decimal("37.5"))
    assert _pick_takeoff_value(m) == 37.5


def test_pick_value_returns_none_when_no_value_present() -> None:
    """Empty annotation row -> ``None`` so the caller treats it as a
    no-op rather than zeroing the BOQ quantity."""
    m = _measurement(type="distance")
    assert _pick_takeoff_value(m) is None


def test_pick_value_volume_falls_back_to_measurement_value() -> None:
    """A volume row without a ``volume`` column (legacy data) still
    surfaces ``measurement_value`` rather than silently dropping it."""
    m = _measurement(type="volume", volume=None, measurement_value=Decimal("9.0"))
    assert _pick_takeoff_value(m) == 9.0


def test_pick_value_count_with_zero_is_returned() -> None:
    """Zero is a valid count (e.g. "no doors found on this sheet") and
    must round-trip rather than triggering the ``None`` no-op branch
    in the caller."""
    m = _measurement(type="count", count_value=0)
    assert _pick_takeoff_value(m) == 0.0


def test_pick_value_handles_string_measurement_value() -> None:
    """The ORM column is ``Numeric(18, 6)`` so SQLAlchemy returns
    ``Decimal``, but a sloppy fixture passing strings should also work
    — the float coercion catches it."""
    m = _measurement(type="distance", measurement_value="2.5")
    assert _pick_takeoff_value(m) == 2.5


def test_pick_value_handles_malformed_count() -> None:
    """A garbage ``count_value`` shouldn't crash the link flow — return
    ``None`` so the caller logs and skips the push."""
    m = _measurement(type="count", count_value="not-a-number")
    assert _pick_takeoff_value(m) is None


def test_pick_value_refuses_an_opening_deduction() -> None:
    """A deduction (opening / void) carries a positive gross area but only
    has meaning as a subtraction inside its group's net-area rollup. It must
    never be pushed into a BOQ position as a standalone quantity, or a void
    would overwrite a position with the area of the hole."""
    m = _measurement(type="area", measurement_value=Decimal("2.0"), is_deduction=True)
    assert _pick_takeoff_value(m) is None


def test_pick_value_non_deduction_area_still_pushes() -> None:
    """A normal area (is_deduction False) is unaffected by the deduction guard."""
    m = _measurement(type="area", measurement_value=Decimal("37.5"), is_deduction=False)
    assert _pick_takeoff_value(m) == 37.5
