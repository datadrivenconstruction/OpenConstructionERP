"""Unit tests for the region → currency fallback warning path.

Audit fix #1 (2026-05-21): ``_resolve_currency`` previously fell through
silently to ``EUR`` on unknown/malformed regions, and the ``PT_SAOPAULO``
key was a mislabel (São Paulo is Brazil → ``BR_SAOPAULO``). These tests
lock in the new behaviour:

    1. Malformed regions log a warning and append the message to the
       caller-supplied ``warnings`` list (then fall back to EUR).
    2. Unknown but well-formed regions log a warning AND fall back.
    3. The bogus ``PT_SAOPAULO`` key is no longer in the registry —
       canonical ``BR_SAOPAULO`` is.
    4. The well-known regions (PT_LISBON, DE_BERLIN, ...) still resolve
       correctly and emit NO warning.
    5. Duplicate warnings are de-duplicated within a single request.
"""

from __future__ import annotations

import logging

import pytest

from app.modules.costs.router import (
    _REGION_CURRENCY,
    _is_valid_region_format,
    _resolve_currency,
)


def test_resolve_currency_well_known_region_no_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Happy path: a known region resolves to its currency and emits no
    warning. The caller-supplied ``warnings`` list stays empty."""
    warnings: list[str] = []
    with caplog.at_level(logging.WARNING, logger="app.modules.costs.router"):
        assert _resolve_currency(None, "DE_BERLIN", warnings=warnings) == "EUR"
        assert _resolve_currency(None, "GB_LONDON", warnings=warnings) == "GBP"
        assert _resolve_currency(None, "BR_SAOPAULO", warnings=warnings) == "BRL"
    assert warnings == []
    assert not any(r.levelno == logging.WARNING for r in caplog.records)


def test_resolve_currency_pt_saopaulo_is_no_longer_in_registry() -> None:
    """The pre-fix registry shipped ``PT_SAOPAULO=BRL`` — a mislabel.
    Canonical key is ``BR_SAOPAULO``. We assert the bogus key is gone so
    the warning path will fire on legacy rows that still carry the typo."""
    assert "PT_SAOPAULO" not in _REGION_CURRENCY
    assert _REGION_CURRENCY["BR_SAOPAULO"] == "BRL"


def test_resolve_currency_malformed_region_logs_warning_and_appends(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Garbage like ``"!@#$"`` or ``"berlin"`` (lowercase) doesn't match
    ``XX_CITY`` — flag it as non-canonical, log a warning, and append the
    message to the caller's warnings list so the FE can show a toast."""
    warnings: list[str] = []
    with caplog.at_level(logging.WARNING, logger="app.modules.costs.router"):
        result = _resolve_currency(None, "!@#$", warnings=warnings)
    assert result == "EUR"  # fallback
    assert len(warnings) == 1
    assert "non-canonical" in warnings[0]
    assert any(r.levelno == logging.WARNING and "non-canonical" in r.getMessage() for r in caplog.records)


def test_resolve_currency_unknown_but_valid_format_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A well-formed but unregistered region (``DK_COPENHAGEN``) is the
    most likely real-world miss — log a warning identifying the missing
    entry so ops can extend the registry."""
    warnings: list[str] = []
    with caplog.at_level(logging.WARNING, logger="app.modules.costs.router"):
        result = _resolve_currency(None, "DK_COPENHAGEN", warnings=warnings)
    assert result == "EUR"
    assert len(warnings) == 1
    assert "Unknown region" in warnings[0]
    assert "DK_COPENHAGEN" in warnings[0]


def test_resolve_currency_duplicate_warnings_collapsed() -> None:
    """When the same bad region appears on many rows, the warnings list
    must not blow up — the helper de-duplicates so the FE shows one toast
    per distinct issue."""
    warnings: list[str] = []
    for _ in range(10):
        _resolve_currency(None, "ZZ_MARS", warnings=warnings)
    assert len(warnings) == 1


def test_resolve_currency_explicit_currency_short_circuits(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A row that carries a non-empty currency bypasses the region lookup
    entirely — even if the region is malformed. No warning emitted."""
    warnings: list[str] = []
    with caplog.at_level(logging.WARNING, logger="app.modules.costs.router"):
        result = _resolve_currency("CHF", "not-a-region", warnings=warnings)
    assert result == "CHF"
    assert warnings == []


def test_is_valid_region_format() -> None:
    """Sanity check for the regex guard used by ``_resolve_currency``."""
    # Valid shapes (2-3 letter country + underscore + uppercase city).
    assert _is_valid_region_format("DE_BERLIN")
    assert _is_valid_region_format("USA_NEWYORK")
    assert _is_valid_region_format("RU_ST_PETERSBURG") is False  # extra _
    # Wait — actually RU_STPETERSBURG is valid (no second underscore).
    assert _is_valid_region_format("RU_STPETERSBURG")
    # Invalid shapes.
    assert not _is_valid_region_format("")
    assert not _is_valid_region_format("berlin")
    assert not _is_valid_region_format("DE-BERLIN")
    assert not _is_valid_region_format("!@#$")
    assert not _is_valid_region_format("DE_")
