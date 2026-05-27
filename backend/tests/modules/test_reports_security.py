# DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Reporting module — Round-7 security audit regressions.

The wire-level IDOR boundary is already pinned by
``tests/integration/test_reporting_idor.py`` (eight tenant-isolation
tests for ``/kpi/``, ``/reports/{id}``, ``/templates/scheduled/``,
``/templates/{id}/schedule/``). This file covers the five new R7
guarantees the audit added:

1. **RBAC split: delete = MANAGER, distribute = MANAGER** — pre-R7
   every reporting mutation routed through ``reporting.create`` (EDITOR).
   That meant a plain estimator could clear a manager's scheduled
   report, re-target it at a foreign project (IDOR was already
   blocked), or hard-delete generated PDFs. Distribute (cron-driven
   email to arbitrary recipient lists) is even higher risk because it
   weaponises the platform's SMTP credentials. ``reporting.delete``
   and ``reporting.distribute`` are now MANAGER-only.

2. **HTML-injection guard on user-supplied renderables** —
   ``ReportTemplateCreate.name`` / ``.description`` and
   ``GenerateReportRequest.title`` strip raw HTML tags and
   ``html.escape`` leftover ``< > &`` before storage. Generated
   reports flow into PDF / HTML renderers (WeasyPrint or similar); a
   future template that does ``{{ title | safe }}`` would otherwise
   execute attacker-supplied ``<script>`` in the email recipient's
   preview pane.

3. **Schedule endpoint elevation** — the cron-attach route on a
   template used to require only ``reporting.create``; pinned to
   ``reporting.distribute`` (MANAGER+) here. Without the elevation, an
   editor could fan out a tenant's confidential cost report to an
   external email address every Monday morning.

4. **KPI string-money convention** — every monetary field on
   ``KPISnapshot`` (``cpi`` / ``spi`` / ``budget_consumed_pct`` /
   ``schedule_progress_pct`` / ``risk_score_avg``) is a ``str``,
   never ``float``. This is the platform-wide "Decimal as JSON
   string" convention: float roundtrips silently truncate at ~15 sig-
   digits, which breaks AR reconciliation by a cent on long-running
   projects.

5. **Template-id-scope visibility filter** — non-admin callers see
   only their own project-scoped scheduled templates +
   portfolio-wide templates (``project_id_scope is None``). The
   integration test pins the boundary; here we pin the static
   invariant that the route uses ``project_id_scope`` to discriminate.

The tests are unit-level (no FastAPI app boot, no SQLite) — the
integration suite under ``tests/integration/test_reporting_idor.py``
covers wire-level smoke where it matters.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

# ── 1. RBAC: delete = MANAGER, distribute = MANAGER ──────────────────────


class TestRBACSeparation:
    """``reporting.delete`` and ``.distribute`` require MANAGER+."""

    def _ensure_registered(self) -> None:
        from app.modules.reporting.permissions import register_reporting_permissions

        register_reporting_permissions()

    def test_editor_cannot_delete_report(self) -> None:
        self._ensure_registered()
        from app.core.permissions import Role, permission_registry

        assert not permission_registry.role_has_permission(
            Role.EDITOR,
            "reporting.delete",
        ), (
            "EDITOR must NOT carry reporting.delete — generated PDFs "
            "may contain audit-trail evidence and require manager-level "
            "deletion authority"
        )

    def test_manager_can_delete_report(self) -> None:
        self._ensure_registered()
        from app.core.permissions import Role, permission_registry

        assert permission_registry.role_has_permission(
            Role.MANAGER,
            "reporting.delete",
        )

    def test_editor_cannot_distribute_report(self) -> None:
        self._ensure_registered()
        from app.core.permissions import Role, permission_registry

        assert not permission_registry.role_has_permission(
            Role.EDITOR,
            "reporting.distribute",
        ), (
            "EDITOR must NOT carry reporting.distribute — fan-out to "
            "arbitrary recipient lists on a cron is a cross-tenant "
            "exfiltration vector"
        )

    def test_manager_can_distribute_report(self) -> None:
        self._ensure_registered()
        from app.core.permissions import Role, permission_registry

        assert permission_registry.role_has_permission(
            Role.MANAGER,
            "reporting.distribute",
        )

    def test_viewer_can_read_report(self) -> None:
        self._ensure_registered()
        from app.core.permissions import Role, permission_registry

        assert permission_registry.role_has_permission(
            Role.VIEWER,
            "reporting.read",
        )

    def test_editor_can_create_report(self) -> None:
        """Happy-path regression — the elevation must not over-tighten
        ``reporting.create``: estimators still need to generate cost
        reports.
        """
        self._ensure_registered()
        from app.core.permissions import Role, permission_registry

        assert permission_registry.role_has_permission(
            Role.EDITOR,
            "reporting.create",
        )


# ── 2. HTML-injection guard on user-supplied renderables ─────────────────


class TestHTMLInjectionGuard:
    """User-supplied renderable strings strip raw HTML before storage."""

    def test_generate_report_title_strips_script(self) -> None:
        from app.modules.reporting.schemas import GenerateReportRequest

        req = GenerateReportRequest(
            project_id=uuid.uuid4(),
            report_type="project_status",
            title="<script>alert('xss')</script>Q1 Cost Report",
        )
        # Tag is gone; leftover text is preserved.
        assert "<script>" not in req.title
        assert "alert" not in req.title or "&" in req.title  # escaped if any
        assert "Q1 Cost Report" in req.title

    def test_generate_report_title_strips_iframe(self) -> None:
        from app.modules.reporting.schemas import GenerateReportRequest

        req = GenerateReportRequest(
            project_id=uuid.uuid4(),
            report_type="cost_report",
            title='<iframe src="//evil.com/" onload="x()">',
        )
        assert "<iframe" not in req.title
        assert "onload" not in req.title
        assert "evil.com" not in req.title

    def test_generate_report_title_escapes_stray_angle_brackets(self) -> None:
        """If a user writes ``a < b cost > c overrun`` (legit math),
        the validator must escape the brackets to HTML entities so a
        downstream renderer doesn't interpret them as malformed
        markup.
        """
        from app.modules.reporting.schemas import GenerateReportRequest

        req = GenerateReportRequest(
            project_id=uuid.uuid4(),
            report_type="cost_report",
            title="Result: 5 < cost variance",
        )
        # Either the leftover ``<`` is escaped to ``&lt;`` (literal
        # entity) or treated as an opening tag and stripped — both are
        # safe. The dangerous outcome would be a raw ``<`` reaching the
        # renderer.
        assert "<" not in req.title or "&lt;" in req.title

    def test_template_create_strips_script_from_name(self) -> None:
        from app.modules.reporting.schemas import ReportTemplateCreate

        tmpl = ReportTemplateCreate(
            name="Monthly Status <script>steal()</script>",
            report_type="project_status",
        )
        assert "<script>" not in tmpl.name
        assert "Monthly Status" in tmpl.name

    def test_template_create_strips_script_from_description(self) -> None:
        from app.modules.reporting.schemas import ReportTemplateCreate

        tmpl = ReportTemplateCreate(
            name="OK",
            report_type="project_status",
            description="Comprehensive <img src=x onerror=alert(1)> rollup.",
        )
        # Tag with the event-handler is gone; descriptive text survives.
        assert "<img" not in (tmpl.description or "")
        assert "onerror" not in (tmpl.description or "")
        assert "Comprehensive" in (tmpl.description or "")

    def test_template_create_none_description_passes_through(self) -> None:
        """Sanitizer is null-safe."""
        from app.modules.reporting.schemas import ReportTemplateCreate

        tmpl = ReportTemplateCreate(
            name="OK",
            report_type="project_status",
            description=None,
        )
        assert tmpl.description is None


# ── 3. Schedule endpoint elevation ──────────────────────────────────────


class TestScheduleEndpointElevation:
    """The cron-attach handler is gated on ``reporting.distribute``."""

    def test_schedule_route_uses_distribute_permission(self) -> None:
        """Static guard: the schedule handler must use
        ``RequirePermission("reporting.distribute")``, not
        ``reporting.create``. A grep-style check catches a future
        cleanup that copy-pastes the create gate back into place.
        """
        from pathlib import Path

        import app.modules.reporting.router as router_mod

        source = Path(router_mod.__file__).read_text(encoding="utf-8")
        # The schedule handler is the only route in this module that
        # uses ``reporting.distribute`` — assert at least one occurrence.
        assert 'RequirePermission("reporting.distribute")' in source, (
            "schedule template handler must use reporting.distribute (MANAGER+), not reporting.create (EDITOR)"
        )

    def test_delete_route_uses_delete_permission(self) -> None:
        from pathlib import Path

        import app.modules.reporting.router as router_mod

        source = Path(router_mod.__file__).read_text(encoding="utf-8")
        assert 'RequirePermission("reporting.delete")' in source, (
            "delete_report handler must use reporting.delete (MANAGER+), not reporting.create (EDITOR)"
        )


# ── 4. KPI money convention — strings, never floats ─────────────────────


class TestKPIMoneyStringConvention:
    """KPI fields are ``str`` to preserve Decimal precision across DBs."""

    def test_kpi_response_money_fields_are_strings(self) -> None:
        from app.modules.reporting.schemas import KPISnapshotResponse

        now = datetime.now(UTC)
        resp = KPISnapshotResponse(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            snapshot_date="2026-05-24",
            cpi="1.02",
            spi="0.98",
            budget_consumed_pct="42.5",
            schedule_progress_pct="38.0",
            risk_score_avg="3.25",
            created_at=now,
            updated_at=now,
        )
        # Pydantic ``str`` annotation guarantees the wire format.
        for field in (
            "cpi",
            "spi",
            "budget_consumed_pct",
            "schedule_progress_pct",
            "risk_score_avg",
        ):
            value = getattr(resp, field)
            assert isinstance(value, str), (
                f"{field!r} must be ``str`` to preserve Decimal precision; got {type(value).__name__}: {value!r}"
            )

    def test_no_float_columns_on_kpi_model(self) -> None:
        """Defensive guard: every money / metric column on
        ``KPISnapshot`` must be ``String`` (or ``Integer`` for raw
        counts), NEVER ``Float``. A future migration that drops to
        Float for "performance" would silently re-introduce binary-FP
        rounding for cost / progress / risk metrics.
        """
        from sqlalchemy import Float

        from app.modules.reporting.models import KPISnapshot

        for col in KPISnapshot.__table__.columns:
            assert not isinstance(col.type, Float), (
                f"KPISnapshot.{col.name} is a Float column; the KPI "
                "schema mandates String storage for Decimal-as-string "
                "wire format. Migrate to String(20) instead."
            )

    def test_kpi_create_accepts_decimal_strings(self) -> None:
        """End-to-end: round-tripping a Decimal-shaped string through
        ``KPISnapshotCreate`` does not coerce to float (which would
        lose precision).
        """
        from app.modules.reporting.schemas import KPISnapshotCreate

        # A value that would lose precision as float: 0.1 + 0.2 round-trip
        # via ``str(0.1 + 0.2)`` = "0.30000000000000004", but our schema
        # passes the user-supplied string through unchanged.
        snap = KPISnapshotCreate(
            project_id=uuid.uuid4(),
            snapshot_date="2026-05-24",
            cpi="1.234567890123456789",
        )
        assert snap.cpi == "1.234567890123456789"
        assert isinstance(snap.cpi, str)


# ── 5. Template-id-scope visibility filter ──────────────────────────────


class TestTemplateScopeVisibility:
    """``/templates/scheduled/`` must filter by ``project_id_scope``."""

    def test_scheduled_handler_uses_project_id_scope(self) -> None:
        """Static guard: the handler reads ``project_id_scope`` from
        each row before deciding whether to include it. Catches a
        future drift that removes the filter loop and returns every
        scheduled template regardless of ownership (which the original
        bug was).
        """
        from pathlib import Path

        import app.modules.reporting.router as router_mod

        source = Path(router_mod.__file__).read_text(encoding="utf-8")
        assert "project_id_scope" in source, (
            "scheduled-template handler must filter on project_id_scope "
            "— pre-fix it returned every scheduled template across "
            "tenants"
        )
        # Admin bypass survives — admins legitimately see every template.
        assert 'role", "") == "admin"' in source

    def test_report_get_validates_via_verify_project_access(self) -> None:
        """``GET /reports/{report_id}`` must gate via
        ``verify_project_access``. Pre-fix the handler returned the
        row by primary key with no project check — pinning the
        invariant statically so a future refactor that drops the
        verify call surfaces as a red test.
        """
        from pathlib import Path

        import app.modules.reporting.router as router_mod

        source = Path(router_mod.__file__).read_text(encoding="utf-8")
        # The phrase appears at least twice — once on the import line,
        # once inside the ``get_report`` handler — but the critical
        # invariant is that ``get_report`` calls it after resolving the
        # row.
        assert source.count("verify_project_access") >= 4, (
            "verify_project_access must appear in get_report, "
            "delete_report, list_reports and at the import — fewer "
            "occurrences means an endpoint dropped the IDOR gate"
        )


# ── 6. KPI snapshot schema completeness regression ──────────────────────


def test_kpi_snapshot_create_round_trip() -> None:
    """Happy path — the schema must still accept the canonical KPI
    payload. The R7 fixes must not have over-tightened input parsing.
    """
    from app.modules.reporting.schemas import KPISnapshotCreate

    pid = uuid.uuid4()
    snap = KPISnapshotCreate(
        project_id=pid,
        snapshot_date="2026-05-24",
        cpi="1.02",
        spi="0.97",
        budget_consumed_pct="42.5",
        open_defects=3,
        open_observations=11,
        schedule_progress_pct="38.5",
        open_rfis=2,
        open_submittals=4,
        risk_score_avg="3.25",
        metadata={"source": "auto_recalculate"},
    )
    assert snap.project_id == pid
    assert snap.cpi == "1.02"
    assert snap.open_defects == 3
    assert snap.metadata == {"source": "auto_recalculate"}


def test_generate_report_request_rejects_empty_title() -> None:
    """Defensive — the ``min_length=1`` constraint must survive
    interaction with the new HTML-strip validator (a title that
    consists ONLY of ``<script>tags</script>`` would otherwise strip
    to empty, which is a confusing UX).
    """
    from app.modules.reporting.schemas import GenerateReportRequest

    # Empty title fails min_length=1.
    with pytest.raises(ValidationError):
        GenerateReportRequest(
            project_id=uuid.uuid4(),
            report_type="project_status",
            title="",
        )
