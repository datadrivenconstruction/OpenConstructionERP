"""Regulatory-immutability tests for completed HSE investigations.

RIDDOR (UK Reporting of Injuries, Diseases and Dangerous Occurrences
Regulations) and OSHA 1904.33 (US 5-year retention rule) both treat the
formal investigation record as the regulator's submission artefact —
silently editing findings or root cause after the case has been closed
would falsify the record.

The service-layer guard added in ``update_investigation`` rejects any
content-only edit of a ``completed`` or ``abandoned`` investigation
while still allowing a pure ``status`` transition (so a mis-closed
probe can be re-opened explicitly, which is itself audit-logged).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.modules.hse_advanced.models import HSEIncidentInvestigation
from app.modules.hse_advanced.schemas import InvestigationUpdate
from tests.unit.test_hse_advanced import _make_service  # type: ignore[import-not-found]

PROJECT_ID = uuid.uuid4()
USER_ID = str(uuid.uuid4())


def _make_completed_investigation() -> HSEIncidentInvestigation:
    inv = HSEIncidentInvestigation(
        incident_ref=uuid.uuid4(),
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        method="5_whys",
        findings="Original RCA: faulty isolation",
        recommendations="Re-train, replace isolation switch",
        status="completed",
        report_url="https://cdn.example.com/report.pdf",
    )
    inv.id = uuid.uuid4()
    return inv


def _make_in_progress_investigation() -> HSEIncidentInvestigation:
    inv = HSEIncidentInvestigation(
        incident_ref=uuid.uuid4(),
        started_at=datetime.now(UTC),
        method="5_whys",
        status="in_progress",
    )
    inv.id = uuid.uuid4()
    return inv


# ── Hard cases: content edits on terminal investigations must 409 ─────────


@pytest.mark.asyncio
async def test_update_completed_investigation_findings_is_rejected() -> None:
    """Editing ``findings`` on a completed investigation must 409."""
    svc = _make_service()
    inv = _make_completed_investigation()
    svc.investigation_repo.rows[inv.id] = inv

    with pytest.raises(HTTPException) as exc:
        await svc.update_investigation(
            inv.id,
            InvestigationUpdate(findings="Falsified findings"),
        )
    assert exc.value.status_code == 409
    assert "immutable" in str(exc.value.detail).lower() or "completed" in str(exc.value.detail).lower()
    # Stored copy is untouched.
    assert inv.findings == "Original RCA: faulty isolation"


@pytest.mark.asyncio
async def test_update_completed_investigation_recommendations_is_rejected() -> None:
    """Recommendation edits are equally regulatory-sensitive."""
    svc = _make_service()
    inv = _make_completed_investigation()
    svc.investigation_repo.rows[inv.id] = inv

    with pytest.raises(HTTPException) as exc:
        await svc.update_investigation(
            inv.id,
            InvestigationUpdate(recommendations="Drop training requirement"),
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_abandoned_investigation_is_rejected() -> None:
    """``abandoned`` is terminal too — content edits must 409."""
    svc = _make_service()
    inv = _make_completed_investigation()
    inv.status = "abandoned"
    svc.investigation_repo.rows[inv.id] = inv

    with pytest.raises(HTTPException) as exc:
        await svc.update_investigation(
            inv.id,
            InvestigationUpdate(findings="Re-write history"),
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_completed_investigation_method_is_rejected() -> None:
    """Even the analysis ``method`` (5-Whys vs fishbone) is locked."""
    svc = _make_service()
    inv = _make_completed_investigation()
    svc.investigation_repo.rows[inv.id] = inv

    with pytest.raises(HTTPException) as exc:
        await svc.update_investigation(
            inv.id,
            InvestigationUpdate(method="fishbone"),
        )
    assert exc.value.status_code == 409


# ── Allowed transitions on terminal investigations ────────────────────────


@pytest.mark.asyncio
async def test_status_only_update_on_completed_investigation_is_allowed() -> None:
    """A pure ``status`` transition (re-open) is still permitted.

    A mis-closed investigation needs an explicit re-open path so the
    audit log captures who re-opened it; rejecting status edits would
    leave the record permanently incorrect.
    """
    svc = _make_service()
    inv = _make_completed_investigation()
    svc.investigation_repo.rows[inv.id] = inv

    # The schema only validates the in_progress|completed|abandoned set,
    # so re-opening means flipping back to in_progress.
    result = await svc.update_investigation(
        inv.id,
        InvestigationUpdate(status="in_progress"),
    )
    assert result.status == "in_progress"


@pytest.mark.asyncio
async def test_update_in_progress_investigation_findings_is_allowed() -> None:
    """While the case is open, content edits are normal investigator work."""
    svc = _make_service()
    inv = _make_in_progress_investigation()
    svc.investigation_repo.rows[inv.id] = inv

    result = await svc.update_investigation(
        inv.id,
        InvestigationUpdate(findings="Updated RCA narrative"),
    )
    assert result.findings == "Updated RCA narrative"


@pytest.mark.asyncio
async def test_no_op_update_on_completed_investigation_does_not_raise() -> None:
    """An empty payload must not falsely trip the lock."""
    svc = _make_service()
    inv = _make_completed_investigation()
    svc.investigation_repo.rows[inv.id] = inv

    # `InvestigationUpdate()` has every field as None, so model_dump
    # with exclude_unset=True yields {} — guard must short-circuit.
    result = await svc.update_investigation(inv.id, InvestigationUpdate())
    assert result.status == "completed"
