"""Unit tests for structured error logging in the reporting service (v2.4.0).

Before v2.4.0 :meth:`ReportingService.auto_recalculate_kpis` caught every
sub-module failure with ``logger.debug(..., exc_info=True)`` — below the
default production log level, which meant a broken finance dashboard or
an offline safety module produced zero signal in the log while KPI
snapshots silently filled with ``None`` everywhere.

These tests assert the new behaviour: each sub-query failure emits a
``WARNING`` line that mentions the operation (so the oncall knows
*which* module's data is missing) and the project id (so the incident
can be correlated to a tenant).  The KPI recalc still succeeds — we are
hardening observability, not changing semantics.

Pattern mirrors :mod:`tests.unit.test_cache_logging` which established
the ``caplog`` + structured-field style for this codebase.
"""

from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.reporting.service import ReportingService

# ---------------------------------------------------------------------------
# Light-weight stubs — no real DB, so we can inject sub-module failures freely
# ---------------------------------------------------------------------------


class _StubSession:
    """Session stub that returns a single fake project on the first
    ``Project`` query and fails (``RuntimeError``) on every other call.

    Making every downstream query fail is exactly what we want here —
    the WHOLE point of the tests is that these per-sub-module failures
    land in the log at WARNING with the project id attached.
    """

    def __init__(self, project_id: uuid.UUID) -> None:
        self._project_id = project_id
        self._calls = 0

    async def execute(self, _stmt):
        self._calls += 1
        # First call is the ``select(Project).where(status==active)``
        # — return one fake project.  Every subsequent call (submittals
        # count, schedule progress, risk average, upsert existing
        # snapshot) raises, which is exactly the observability scenario
        # we want the new logging to cover.
        if self._calls == 1:
            fake_project = SimpleNamespace(id=self._project_id)
            fake_scalars = MagicMock()
            fake_scalars.all = MagicMock(return_value=[fake_project])
            fake_result = MagicMock()
            fake_result.scalars = MagicMock(return_value=fake_scalars)
            return fake_result
        raise RuntimeError(f"stub-db: no table for call #{self._calls}")

    async def flush(self):
        return None

    def add(self, _obj):  # pragma: no cover - not exercised by these tests
        return None


@pytest.fixture
def stub_session() -> _StubSession:
    return _StubSession(project_id=uuid.UUID("11111111-2222-3333-4444-555555555555"))


@pytest.fixture
def reporting_service(stub_session: _StubSession) -> ReportingService:
    # ``ReportingService.__init__`` wires repositories off the session.
    # The sub-module failure paths never touch those repositories, so
    # the ``_StubSession`` is sufficient.  We build ``ReportingService``
    # via ``object.__new__`` to skip the repository constructors —
    # they inspect the session in ways a stub cannot satisfy.
    svc = object.__new__(ReportingService)
    svc.session = stub_session
    svc.kpi_repo = MagicMock()
    svc.template_repo = MagicMock()
    svc.report_repo = MagicMock()
    return svc


# ---------------------------------------------------------------------------
# Individual sub-module failure paths
# ---------------------------------------------------------------------------


class TestKpiRecalcLogging:
    @pytest.mark.asyncio
    async def test_finance_failure_is_logged_at_warning(self, reporting_service, stub_session, caplog):
        fake_fin_service = MagicMock()
        fake_fin_service.get_dashboard = AsyncMock(side_effect=RuntimeError("finance-db-down"))

        with (
            caplog.at_level(logging.WARNING, logger="app.modules.reporting.service"),
            patch(
                "app.modules.finance.service.FinanceService",
                return_value=fake_fin_service,
            ),
        ):
            await reporting_service.auto_recalculate_kpis()

        finance_records = [
            rec
            for rec in caplog.records
            if "reporting.kpi_recalc" in rec.getMessage() and "finance.get_dashboard" in rec.getMessage()
        ]
        assert finance_records, "finance failure was not logged"
        msg = finance_records[0].getMessage()
        assert str(stub_session._project_id) in msg
        assert finance_records[0].levelno == logging.WARNING

    @pytest.mark.asyncio
    async def test_costmodel_failure_is_logged_at_warning(self, reporting_service, stub_session, caplog):
        fake_cm_service = MagicMock()
        fake_cm_service.get_dashboard = AsyncMock(side_effect=ConnectionError("qdrant refused"))

        with (
            caplog.at_level(logging.WARNING, logger="app.modules.reporting.service"),
            patch(
                "app.modules.costmodel.service.CostModelService",
                return_value=fake_cm_service,
            ),
        ):
            await reporting_service.auto_recalculate_kpis()

        records = [rec for rec in caplog.records if "costmodel.get_dashboard" in rec.getMessage()]
        assert records, "costmodel failure was not logged"
        assert str(stub_session._project_id) in records[0].getMessage()
        assert records[0].levelno == logging.WARNING

    @pytest.mark.asyncio
    async def test_safety_failure_is_logged_at_warning(self, reporting_service, stub_session, caplog):
        fake_safety = MagicMock()
        fake_safety.get_stats = AsyncMock(side_effect=RuntimeError("safety-broken"))

        with (
            caplog.at_level(logging.WARNING, logger="app.modules.reporting.service"),
            patch(
                "app.modules.safety.service.SafetyService",
                return_value=fake_safety,
            ),
        ):
            await reporting_service.auto_recalculate_kpis()

        records = [rec for rec in caplog.records if "safety.get_stats" in rec.getMessage()]
        assert records, "safety failure was not logged"
        assert str(stub_session._project_id) in records[0].getMessage()
        assert records[0].levelno == logging.WARNING

    @pytest.mark.asyncio
    async def test_rfi_failure_is_logged_at_warning(self, reporting_service, stub_session, caplog):
        fake_rfi = MagicMock()
        fake_rfi.get_stats = AsyncMock(side_effect=RuntimeError("rfi-broken"))

        with (
            caplog.at_level(logging.WARNING, logger="app.modules.reporting.service"),
            patch(
                "app.modules.rfi.service.RFIService",
                return_value=fake_rfi,
            ),
        ):
            await reporting_service.auto_recalculate_kpis()

        records = [rec for rec in caplog.records if "rfi.get_stats" in rec.getMessage()]
        assert records, "rfi failure was not logged"
        assert str(stub_session._project_id) in records[0].getMessage()

    @pytest.mark.asyncio
    async def test_submittals_schedule_risk_failures_surface_per_module(self, reporting_service, stub_session, caplog):
        """DB-level failures for submittals/schedule/risk each get their
        own WARNING line carrying the project id — exactly what the
        audit finding was about."""
        with caplog.at_level(logging.WARNING, logger="app.modules.reporting.service"):
            await reporting_service.auto_recalculate_kpis()

        messages = [rec.getMessage() for rec in caplog.records]

        # Each of the three DB paths must produce its own line.
        assert any("submittals count" in m for m in messages), "expected reporting.kpi_recalc submittals count WARNING"
        assert any("schedule.avg_progress" in m for m in messages), (
            "expected reporting.kpi_recalc schedule.avg_progress WARNING"
        )
        assert any("risk.avg_score" in m for m in messages), "expected reporting.kpi_recalc risk.avg_score WARNING"

        # And every reporting.kpi_recalc warning we emit must carry the
        # project id — that's the whole value proposition of the new
        # logging.
        kpi_records = [rec for rec in caplog.records if "reporting.kpi_recalc" in rec.getMessage()]
        assert all(str(stub_session._project_id) in rec.getMessage() for rec in kpi_records)
        assert all(rec.levelno >= logging.WARNING for rec in kpi_records)

    @pytest.mark.asyncio
    async def test_no_warnings_when_submodules_happy(self, reporting_service, caplog):
        """If every sub-module returns valid data, none of the
        reporting.kpi_recalc WARNING lines should fire.

        Note: the downstream raw-SQL queries (submittals / schedule /
        risk) still fail against our _StubSession — that's fine, we
        only assert that the module-service paths (finance / costmodel
        / safety / rfi) are quiet when their services work.
        """
        happy_fin = MagicMock()
        happy_fin.get_dashboard = AsyncMock(return_value={"total_budget": "100", "total_actual": "75"})
        happy_cm = MagicMock()
        happy_cm.get_dashboard = AsyncMock(return_value={"cpi": 1.0, "spi": 0.95})
        happy_safety = MagicMock()
        happy_safety.get_stats = AsyncMock(
            return_value=SimpleNamespace(total_observations=5, closed_observations=3, total_incidents=1)
        )
        happy_rfi = MagicMock()
        happy_rfi.get_stats = AsyncMock(return_value=SimpleNamespace(open=4))

        with (
            caplog.at_level(logging.WARNING, logger="app.modules.reporting.service"),
            patch(
                "app.modules.finance.service.FinanceService",
                return_value=happy_fin,
            ),
            patch(
                "app.modules.costmodel.service.CostModelService",
                return_value=happy_cm,
            ),
            patch(
                "app.modules.safety.service.SafetyService",
                return_value=happy_safety,
            ),
            patch(
                "app.modules.rfi.service.RFIService",
                return_value=happy_rfi,
            ),
        ):
            await reporting_service.auto_recalculate_kpis()

        messages = [rec.getMessage() for rec in caplog.records]
        assert not any("finance.get_dashboard" in m for m in messages)
        assert not any("costmodel.get_dashboard" in m for m in messages)
        assert not any("safety.get_stats" in m for m in messages)
        assert not any("rfi.get_stats" in m for m in messages)


# ---------------------------------------------------------------------------
# Sanity: logger name matches module path
# ---------------------------------------------------------------------------


def test_logger_namespace():
    """Confirm the logger name we assert on actually matches the module."""
    from app.modules.reporting import service as svc_mod

    assert svc_mod.logger.name == "app.modules.reporting.service"
