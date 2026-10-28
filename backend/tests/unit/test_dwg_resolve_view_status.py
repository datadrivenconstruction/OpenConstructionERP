# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for ``DwgTakeoffService.resolve_view_status``.

This pure static method is what stops the fresh-install "perpetual
Converting..." spinner on /dwg-takeoff: a seeded ``.dwg`` row sits at
``status="uploaded"`` with no parsed entities, and with no DDC DwgExporter on
disk nothing ever transitions it. ``resolve_view_status`` must always return a
terminal, actionable answer for the viewer. These tests pin every branch so a
future edit cannot silently bring the spinner back.

The function is pure (no DB, no async); for the ``.dwg`` branches we always
pass ``converter_present`` explicitly so the test never touches the filesystem
probe in ``get_offline_readiness``.
"""

import pytest

from app.modules.dwg_takeoff.service import DwgTakeoffService

resolve = DwgTakeoffService.resolve_view_status


@pytest.mark.parametrize(
    ("status_value", "file_format", "has_entities", "converter_present", "expected"),
    [
        # Parsed entities win regardless of stored status / format / converter.
        ("uploaded", "dwg", True, False, "ready"),
        ("processing", "dxf", True, None, "ready"),
        (None, None, True, None, "ready"),
        # Genuine terminal states pass through untouched (and are lowercased).
        ("ready", "dwg", False, False, "ready"),
        ("empty", "dxf", False, None, "empty"),
        ("error", "dwg", False, True, "error"),
        ("processing", "dwg", False, False, "processing"),
        ("needs_conversion", "dwg", False, True, "needs_conversion"),
        ("READY", "dwg", False, False, "ready"),
        # .dwg + uploaded + no entities: converter present -> mid-flight.
        ("uploaded", "dwg", False, True, "processing"),
        # .dwg + uploaded + no entities: no converter -> actionable terminal.
        ("uploaded", "dwg", False, False, "needs_conversion"),
        # Leading-dot format and a missing status still resolve the .dwg branch.
        ("uploaded", ".dwg", False, False, "needs_conversion"),
        (None, "dwg", False, False, "needs_conversion"),
        # .dxf parses locally -> brief pre-parse window is processing.
        ("uploaded", "dxf", False, False, "processing"),
        ("uploaded", ".dxf", False, True, "processing"),
        # Unknown / missing format with no entities falls back to processing.
        ("uploaded", None, False, False, "processing"),
        ("uploaded", "rvt", False, False, "processing"),
    ],
)
def test_resolve_view_status(
    status_value: str | None,
    file_format: str | None,
    has_entities: bool,
    converter_present: bool | None,
    expected: str,
) -> None:
    assert (
        resolve(
            status_value=status_value,
            file_format=file_format,
            has_entities=has_entities,
            converter_present=converter_present,
        )
        == expected
    )


def test_resolve_view_status_never_returns_uploaded() -> None:
    """The viewer must never be handed a non-terminal ``uploaded`` state."""
    for fmt in ("dwg", "dxf", "rvt", None):
        for present in (True, False):
            out = resolve(
                status_value="uploaded",
                file_format=fmt,
                has_entities=False,
                converter_present=present,
            )
            assert out in {"ready", "empty", "error", "processing", "needs_conversion"}
            assert out != "uploaded"


@pytest.mark.parametrize(
    ("status_value", "file_format", "converter_present", "age_seconds", "expected"),
    [
        # Orphaned conversion: still processing/uploaded with no entities and
        # untouched far past the convert timeout -> terminal error. This is the
        # fix for the "Converting... 2547m" infinite spinner a real user hit
        # after reinstalling (the background task died with the old process).
        ("processing", "dwg", True, 999_999.0, "error"),
        ("uploaded", "dwg", True, 999_999.0, "error"),
        ("processing", "dxf", None, 999_999.0, "error"),
        # Fresh / recent conversions are left alone (genuinely mid-flight).
        ("processing", "dwg", True, 1.0, "processing"),
        ("uploaded", "dwg", True, 1.0, "processing"),
        # No age available -> staleness never triggers (back-compat with callers
        # that do not pass age_seconds, e.g. the existing pure-function tests).
        ("processing", "dwg", True, None, "processing"),
        # A genuinely terminal stored state is never overridden by age.
        ("error", "dwg", False, 999_999.0, "error"),
        ("ready", "dwg", False, 999_999.0, "ready"),
        ("needs_conversion", "dwg", True, 999_999.0, "needs_conversion"),
    ],
)
def test_resolve_view_status_stale_conversion(
    status_value: str,
    file_format: str,
    converter_present: bool | None,
    age_seconds: float | None,
    expected: str,
) -> None:
    """An orphaned conversion resolves to a terminal ``error``, never a spinner."""
    assert (
        resolve(
            status_value=status_value,
            file_format=file_format,
            has_entities=False,
            converter_present=converter_present,
            age_seconds=age_seconds,
        )
        == expected
    )
