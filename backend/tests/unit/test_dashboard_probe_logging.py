# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A failed dashboard probe must be visible, not just survivable.

Both the BI KPI registry and the Coordination Hub aggregator are built to
degrade rather than crash: a probe that fails yields a zero and the page
still renders. That part is correct and stays. What was wrong is that the
failure was logged at DEBUG, and production log level sits above DEBUG, so a
broken cost feed reached the user as a confident zero with nothing anywhere
to distinguish it from a genuine zero.

These tests pin the visibility half of the contract:

    * a probe that raises logs at WARNING or above, with a traceback, naming
      the probe;
    * it still returns its fallback value, so one bad probe cannot take a
      dashboard down;
    * the one condition that IS expected, a sibling module that was never
      installed, stays at DEBUG and does not become log noise.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import pytest

from app.modules.bi_dashboards import kpis
from app.modules.coordination_hub import service as coord_service

pytestmark = pytest.mark.unit


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


class _BrokenSession:
    """A session whose every statement fails, the way a dropped table does."""

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("relation does not exist")

    async def get(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("relation does not exist")


def _above_debug(handler: _CaptureHandler) -> list[logging.LogRecord]:
    return [r for r in handler.records if r.levelno >= logging.WARNING]


# ── BI KPI registry ────────────────────────────────────────────────────────


async def test_failing_count_probe_logs_above_debug_with_traceback() -> None:
    """The generic count helper is the most-reused probe in the registry."""
    with _capture(kpis.logger) as handler:
        result = await kpis._safe_count(_BrokenSession(), "SELECT 1")  # noqa: SLF001

    # Graceful degradation is unchanged.
    assert result == 0

    loud = _above_debug(handler)
    assert loud, "a failing KPI probe must not be invisible at production log level"
    assert any("safe_count" in r.getMessage() for r in loud), "the log must name the probe"
    assert any(r.exc_info is not None for r in loud), "the traceback is worth keeping"


async def test_failing_currency_probe_names_itself() -> None:
    """Every probe message has to identify which probe failed."""
    with _capture(kpis.logger) as handler:
        base, fx = await kpis._project_currency_and_fx(_BrokenSession(), uuid.uuid4())  # noqa: SLF001

    assert (base, fx) == ("", {})
    loud = _above_debug(handler)
    assert loud
    assert any("currency" in r.getMessage() for r in loud)


async def test_no_kpi_probe_still_reports_failure_only_at_debug() -> None:
    """Regression guard: the old DEBUG-only shape must not come back."""
    with _capture(kpis.logger) as handler:
        await kpis._safe_count(_BrokenSession(), "SELECT 1")  # noqa: SLF001

    assert handler.records, "the probe must log something"
    assert _above_debug(handler), "the failure has to be reported above DEBUG"
    # A future unrelated DEBUG trace line is fine. What must never come back is
    # a FAILURE, one carrying an exception, reported at DEBUG and nowhere else.
    assert not [record for record in handler.records if record.levelno <= logging.DEBUG and record.exc_info], (
        "a failure must not be reported at DEBUG"
    )


async def test_unknown_kpi_code_is_reported() -> None:
    """A widget bound to a code nothing registers renders a permanent zero."""
    with _capture(kpis.logger) as handler:
        result = await kpis.compute("no_such_kpi_code_at_all", _BrokenSession())

    assert result.value == Decimal("0")
    loud = _above_debug(handler)
    assert loud
    assert any("no_such_kpi_code_at_all" in r.getMessage() for r in loud)


async def test_formula_that_raises_is_reported_and_does_not_escape() -> None:
    """One exploding KPI must not 500 the dashboard, but must be logged."""

    @kpis.register_kpi("probe_logging_exploding_kpi", name="Exploding", unit="count")
    async def _boom(_session: Any, **_kwargs: Any) -> kpis.KPIComputation:
        raise RuntimeError("probe blew up")

    try:
        with _capture(kpis.logger) as handler:
            result = await kpis.compute("probe_logging_exploding_kpi", _BrokenSession())

        assert result.value == Decimal("0")
        loud = _above_debug(handler)
        assert any("probe_logging_exploding_kpi" in r.getMessage() for r in loud)
        assert any(r.exc_info is not None for r in loud)
    finally:
        kpis.KPI_FORMULAS.pop("probe_logging_exploding_kpi", None)
        kpis.SYSTEM_KPI_META.pop("probe_logging_exploding_kpi", None)


# ── Coordination Hub ───────────────────────────────────────────────────────


def test_missing_optional_module_stays_at_debug() -> None:
    """A module that was never installed is expected, not a failure."""
    with _capture(coord_service.logger) as handler:
        coord_service._optional_module_unavailable("clash", ImportError("no module named clash"))  # noqa: SLF001

    assert handler.records
    assert all(r.levelno == logging.DEBUG for r in handler.records), (
        "an uninstalled optional module must not become log noise"
    )


def test_broken_optional_module_is_loud() -> None:
    """A module that IS installed and blew up is a real failure."""
    with _capture(coord_service.logger) as handler:
        try:
            raise RuntimeError("bad config in the clash module")
        except RuntimeError as exc:
            coord_service._optional_module_unavailable("clash", exc)  # noqa: SLF001

    loud = _above_debug(handler)
    assert loud, "an import that failed for a real reason must be visible"
    assert any("clash" in r.getMessage() for r in loud)
    assert any(r.exc_info is not None for r in loud)
