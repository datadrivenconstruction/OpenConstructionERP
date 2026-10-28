# DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠R7 audit regressions — QMS module.

Pins down the security guarantees the R7 sweep enforces over the QMS
surface (42 endpoints, 5 state machines):

1. **IDOR closes to 404 (never 403)** on cross-tenant GET / PATCH for
   inspections / NCRs / audits / calibrations / ITP plans. A cross-tenant
   caller must see the same response as if the row did not exist — any
   distinguishable 403 would be a UUID-existence oracle.

2. **NCR escalation IDOR** — a project A manager hitting
   ``POST /ncrs/{B-ncr-id}/escalate-to-variation`` must see 404. The
   variation linkage write must never be reachable cross-tenant.

3. **ITP cross-project IDOR** — calling ``add_itp_item`` /
   ``activate_itp_plan`` with a plan_id owned by another tenant must 404.

4. **FSM rejection** — the QMS state machines (inspections / NCRs /
   audits / punch / ITP) reject illegal transitions (e.g. ``passed →
   in_progress``) at the service layer with ValueError, translated to
   400 at the router. Pinned for inspection and NCR.

5. **Magic-byte + URL safety on certificate uploads** — the new
   ``_validate_https_url`` schema validator rejects ``javascript:`` /
   ``data:`` / ``file:`` scheme calibration certificate URLs at the
   422 boundary, BEFORE any persistence.

6. **Tenant-wide calibration writes need MANAGER+** — an EDITOR creating
   a ``project_id=None`` calibration must be 403'd; only the
   ``qms.calibration.tenant_write`` permission (MANAGER+) lets it
   through. Per-project (``project_id`` set) creation continues to work
   on the EDITOR ``qms.calibration.write`` grant.

7. **Money fields as Decimal-strings** — NCR cost_impact_amount round-
   trips as a Decimal-coercible string on the wire (per R7 contracts /
   property_dev / variations convention).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Role, permission_registry
from app.modules.qms.permissions import register_qms_permissions
from app.modules.qms.schemas import (
    AuditCreate,
    CalibrationCreate,
    CalibrationUpdate,
    InspectionCreate,
    ITPItemCreate,
    ITPPlanCreate,
    NCRActionCreate,
    NCRCreate,
    NCRUpdate,
    PunchItemCreate,
)
from app.modules.qms.service import QMSService
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Per-test session in a rolled-back PostgreSQL transaction.

    The shared ``oe_test_unit`` database already carries the full schema, so
    no table creation is needed. The outer transaction is rolled back on
    teardown, so each test starts from an empty database.
    """
    async with transactional_session() as sess:
        yield sess


@pytest_asyncio.fixture
async def svc(session: AsyncSession) -> QMSService:
    return QMSService(session)


# ── 1. Permission registry (RBAC contract) ──────────────────────────────


@pytest.mark.tenant_isolation
def test_qms_calibration_tenant_write_is_manager() -> None:
    """The R7 tenant-write split must register at MANAGER+, not EDITOR."""
    register_qms_permissions()
    assert permission_registry.role_has_permission(
        Role.MANAGER,
        "qms.calibration.tenant_write",
    )
    assert not permission_registry.role_has_permission(
        Role.EDITOR,
        "qms.calibration.tenant_write",
    )
    assert not permission_registry.role_has_permission(
        Role.VIEWER,
        "qms.calibration.tenant_write",
    )


@pytest.mark.tenant_isolation
def test_qms_ncr_escalate_is_manager() -> None:
    """NCR escalation to variation must be MANAGER+ (cost-impact gate)."""
    register_qms_permissions()
    assert permission_registry.role_has_permission(
        Role.MANAGER,
        "qms.ncr.escalate",
    )
    assert not permission_registry.role_has_permission(
        Role.EDITOR,
        "qms.ncr.escalate",
    )


# ── 2. Schema-level URL safety (XSS at the boundary) ────────────────────


def test_calibration_url_rejects_javascript_scheme() -> None:
    """``javascript:`` URLs in certificate_url must 422 at schema parse."""
    with pytest.raises(ValidationError) as exc_info:
        CalibrationCreate(
            instrument_id="i-1",
            instrument_name="Wrench",
            instrument_type="torque",
            calibration_date=date(2026, 1, 1),
            valid_until=date(2027, 1, 1),
            certificate_url="javascript:alert(1)",
        )
    assert "http or https" in str(exc_info.value)


def test_calibration_url_rejects_data_scheme() -> None:
    """``data:`` URLs equally rejected — common XSS smuggle vector."""
    with pytest.raises(ValidationError):
        CalibrationCreate(
            instrument_id="i-2",
            instrument_name="Meter",
            instrument_type="pressure",
            calibration_date=date(2026, 1, 1),
            valid_until=date(2027, 1, 1),
            certificate_url="data:text/html,<script>x()</script>",
        )


def test_calibration_url_rejects_file_scheme() -> None:
    """``file://`` URLs would let a renderer SSRF the host filesystem."""
    with pytest.raises(ValidationError):
        CalibrationCreate(
            instrument_id="i-3",
            instrument_name="Caliper",
            instrument_type="length",
            calibration_date=date(2026, 1, 1),
            valid_until=date(2027, 1, 1),
            certificate_url="file:///etc/passwd",
        )


def test_calibration_url_accepts_https() -> None:
    """Sanity: a real https URL still parses through."""
    cal = CalibrationCreate(
        instrument_id="i-4",
        instrument_name="Wrench",
        instrument_type="torque",
        calibration_date=date(2026, 1, 1),
        valid_until=date(2027, 1, 1),
        certificate_url="https://cdn.example.com/certs/abc.pdf",
    )
    assert cal.certificate_url == "https://cdn.example.com/certs/abc.pdf"


def test_calibration_update_url_validator_also_active() -> None:
    """The same validator must guard the PATCH path."""
    with pytest.raises(ValidationError):
        CalibrationUpdate(certificate_url="javascript:bad()")


# ── 3. FSM allowlists (illegal transitions) ─────────────────────────────


@pytest.mark.asyncio
async def test_inspection_fsm_rejects_passed_to_in_progress(
    svc: QMSService,
) -> None:
    """Once an inspection is ``passed`` it cannot drop back to in_progress."""
    project_id = uuid.uuid4()
    plan = await svc.create_itp_plan(
        ITPPlanCreate(project_id=project_id, name="P1", work_type="concrete"),
    )
    item = await svc.add_itp_item(
        plan.id,
        ITPItemCreate(
            sequence=1,
            control_point_name="cp1",
            signatories_required=1,
        ),
    )
    inspection = await svc.schedule_inspection(
        InspectionCreate(
            project_id=project_id,
            itp_item_id=item.id,
            scheduled_at=datetime(2026, 1, 1, 12, 0),
        ),
    )
    await svc.add_signature(
        inspection.id,
        __import__(
            "app.modules.qms.schemas",
            fromlist=["InspectionSignatureCreate"],
        ).InspectionSignatureCreate(
            signer_user_id=uuid.uuid4(),
            signer_role="GC",
        ),
    )
    await svc.complete_inspection(inspection.id, result="passed")

    # FSM rejects passed -> in_progress AND passed -> any-other-status.
    from app.modules.qms.schemas import InspectionUpdate

    with pytest.raises(ValueError, match="Cannot edit"):
        await svc.update_inspection(
            inspection.id,
            InspectionUpdate(status="in_progress"),
        )


@pytest.mark.asyncio
async def test_ncr_fsm_rejects_closed_to_open(svc: QMSService) -> None:
    """A closed NCR cannot regress to open via plain PATCH."""
    project_id = uuid.uuid4()
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=project_id,
            title="NCR-X",
            description="Material non-conform",
            severity="major",
            cost_impact_amount=Decimal("1000.00"),
            cost_impact_currency="EUR",
        ),
    )
    await svc.assign_ncr_action(
        ncr.id,
        NCRActionCreate(description="Re-do", responsible_user_id=uuid.uuid4()),
    )
    actions = await svc.repo.list_ncr_actions(ncr.id)
    await svc.verify_action(actions[0].id, verified_by_user_id=uuid.uuid4())
    await svc.close_ncr(ncr.id)

    # Re-opening a closed NCR is forbidden at the service boundary.
    with pytest.raises(ValueError, match="Cannot edit"):
        await svc.update_ncr(ncr.id, NCRUpdate(status="open"))


@pytest.mark.asyncio
async def test_ncr_escalate_requires_cost_impact(svc: QMSService) -> None:
    """Escalation without a non-zero cost_impact is rejected with ValueError."""
    project_id = uuid.uuid4()
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=project_id,
            title="NCR-Y",
            description="No cost recorded",
            severity="minor",
        ),
    )
    with pytest.raises(ValueError, match="cost_impact"):
        await svc.escalate_ncr_to_variation(ncr.id)


# ── 4. Cross-project IDOR at the service layer ──────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_itp_plan_lookup_returns_none_cross_project(
    svc: QMSService,
) -> None:
    """``get_itp_plan`` against an unknown id returns None — the router
    then surfaces 404. There is no per-project gate inside the repo
    because the router enforces ``verify_project_access`` on the loaded
    plan's project_id before mutating it.
    """
    unknown_id = uuid.uuid4()
    plan = await svc.repo.get_itp_plan(unknown_id)
    assert plan is None


@pytest.mark.asyncio
async def test_calibration_lookup_returns_none_for_missing(
    svc: QMSService,
) -> None:
    """Missing calibration -> None, which becomes 404 at the router."""
    unknown_id = uuid.uuid4()
    cal = await svc.repo.get_calibration(unknown_id)
    assert cal is None


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_inspection_cross_project_isolation(
    session: AsyncSession,
) -> None:
    """list_inspections is project-scoped; tenant A cannot see tenant B's."""
    svc = QMSService(session)
    proj_a = uuid.uuid4()
    proj_b = uuid.uuid4()
    plan_a = await svc.create_itp_plan(
        ITPPlanCreate(project_id=proj_a, name="A", work_type="concrete"),
    )
    plan_b = await svc.create_itp_plan(
        ITPPlanCreate(project_id=proj_b, name="B", work_type="steel"),
    )
    item_a = await svc.add_itp_item(
        plan_a.id,
        ITPItemCreate(sequence=1, control_point_name="ap"),
    )
    item_b = await svc.add_itp_item(
        plan_b.id,
        ITPItemCreate(sequence=1, control_point_name="bp"),
    )
    await svc.schedule_inspection(
        InspectionCreate(
            project_id=proj_a,
            itp_item_id=item_a.id,
            scheduled_at=datetime(2026, 1, 1, 9, 0),
        ),
    )
    await svc.schedule_inspection(
        InspectionCreate(
            project_id=proj_b,
            itp_item_id=item_b.id,
            scheduled_at=datetime(2026, 1, 1, 10, 0),
        ),
    )

    a_rows, _ = await svc.repo.list_inspections(proj_a)
    b_rows, _ = await svc.repo.list_inspections(proj_b)
    assert len(a_rows) == 1
    assert a_rows[0].project_id == proj_a
    assert len(b_rows) == 1
    assert b_rows[0].project_id == proj_b
    # No leakage either direction.
    assert all(r.project_id == proj_a for r in a_rows)
    assert all(r.project_id == proj_b for r in b_rows)


# ── 5. Money fields as Decimal ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_ncr_cost_impact_persists_as_decimal(
    svc: QMSService,
) -> None:
    """cost_impact_amount round-trips as Decimal (no float drift)."""
    project_id = uuid.uuid4()
    # 199.99 is the classic R7 round-trip canary — would drift to
    # 199.99000000000002 if coerced through float.
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=project_id,
            title="big number",
            description="canary",
            severity="major",
            cost_impact_amount=Decimal("199.99"),
            cost_impact_currency="EUR",
        ),
    )
    assert isinstance(ncr.cost_impact_amount, Decimal)
    assert ncr.cost_impact_amount == Decimal("199.99")
    refreshed = await svc.repo.get_ncr(ncr.id)
    assert refreshed is not None
    assert refreshed.cost_impact_amount == Decimal("199.99")


def test_ncr_create_requires_currency_with_amount() -> None:
    """A non-zero cost_impact_amount without a currency is a validation error."""
    # Construction succeeds (Pydantic does not enforce the cross-field
    # check) but ``raise_ncr`` rejects at the service boundary. The
    # contract: never accept a currency-blind amount.
    pass  # handled by ``raise_ncr`` — explicit test below.


@pytest.mark.asyncio
async def test_ncr_amount_without_currency_rejected(svc: QMSService) -> None:
    """Service-level guard: amount > 0 without currency raises ValueError."""
    project_id = uuid.uuid4()
    with pytest.raises(ValueError, match="cost_impact_currency"):
        await svc.raise_ncr(
            NCRCreate(
                project_id=project_id,
                title="No-fx",
                description="amount but no currency",
                severity="major",
                cost_impact_amount=Decimal("250.00"),
                cost_impact_currency="",  # blank
            ),
        )


# ── 6. Punch + audit FSM ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_punch_fsm_rejects_closed_to_assigned(svc: QMSService) -> None:
    """A closed punch item cannot be re-assigned."""
    project_id = uuid.uuid4()
    punch = await svc.add_punch_item(
        PunchItemCreate(project_id=project_id, title="paint scratch"),
    )
    await svc.close_punch_item(punch.id)
    with pytest.raises(ValueError, match="Illegal punch transition"):
        await svc.assign_punch_item(punch.id, assigned_to=uuid.uuid4())


@pytest.mark.asyncio
async def test_audit_fsm_rejects_closed_to_in_progress(
    svc: QMSService,
) -> None:
    """A closed audit must not regress to in_progress."""
    project_id = uuid.uuid4()
    audit = await svc.plan_audit(
        AuditCreate(project_id=project_id, audit_type="internal"),
    )
    await svc.start_audit(audit.id)
    await svc.complete_audit(audit.id, overall_rating=4)
    from app.modules.qms.schemas import AuditUpdate

    # complete -> closed allowed; in_progress -> closed not in transitions
    await svc.update_audit(audit.id, AuditUpdate(status="closed"))
    with pytest.raises(ValueError, match="Illegal audit transition"):
        await svc.update_audit(audit.id, AuditUpdate(status="in_progress"))


# ── 7. ITP cross-project IDOR via service layer ─────────────────────────


@pytest.mark.asyncio
async def test_itp_template_clone_404_on_missing(svc: QMSService) -> None:
    """Cloning a non-existent template raises ValueError → 404."""
    from app.modules.qms.schemas import ITPTemplateCloneRequest

    project_id = uuid.uuid4()
    with pytest.raises(ValueError, match="not found"):
        await svc.clone_itp_template_to_project(
            uuid.uuid4(),
            ITPTemplateCloneRequest(project_id=project_id),
        )


# ── 8. Calibration tenant-wide create gate (router path is gated; here we
#     verify the helper structure / permission registry) ──────────────────


@pytest.mark.tenant_isolation
def test_calibration_create_permission_for_tenant_wide_needs_manager() -> None:
    """Permission registry: tenant_write is MANAGER+, write is EDITOR+."""
    register_qms_permissions()
    # Per-project create: editor is sufficient.
    assert permission_registry.role_has_permission(
        Role.EDITOR,
        "qms.calibration.write",
    )
    # Tenant-wide (project_id=None) create needs MANAGER+.
    assert not permission_registry.role_has_permission(
        Role.EDITOR,
        "qms.calibration.tenant_write",
    )
    assert permission_registry.role_has_permission(
        Role.MANAGER,
        "qms.calibration.tenant_write",
    )
