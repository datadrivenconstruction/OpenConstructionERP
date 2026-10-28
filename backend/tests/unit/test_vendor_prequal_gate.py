"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Vendor prequalification: scoring + procurement PO gate (TOP-30 #20).

Two layers:

* pure-logic tests of the structured prequalification scorer / validator
  (:func:`compute_prequal_score`, :func:`validate_questionnaire`) with
  hand-computed fixtures;
* real-PostgreSQL tests that the procurement PO gate hard-blocks a
  ``is_blocked`` vendor (409) on create + issue, warns (non-blocking) on a
  non-prequalified vendor, and never gates an ad-hoc supplier that is not a
  registered subcontractor.

The vendor master link is the existing ``Subcontractor.contact_id`` column
(the same CRM contact a PO references via ``vendor_contact_id``); these tests
seed a subcontractor with a known ``contact_id`` and create a PO against it.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.procurement.schemas import POCreate, POItemCreate, POUpdate
from app.modules.procurement.service import ProcurementService
from app.modules.subcontractors.service import (
    DEFAULT_PREQUAL_QUESTIONS,
    compute_prequal_score,
    validate_questionnaire,
)
from tests._pg import transactional_session

# ── Structured prequal scoring (pure logic) ───────────────────────────────


def test_score_all_correct_is_100() -> None:
    # Every positive question "yes", every negative question "no" -> 8/8.
    answers = {
        "license_current": "yes",
        "wcb_coverage": "yes",
        "insurance_current": "yes",
        "safety_program": "yes",
        "references_available": "yes",
        "financial_statements": "yes",
        "has_open_incidents": "no",
        "has_unpaid_liens": "no",
    }
    assert compute_prequal_score(answers) == 100


def test_score_six_of_eight_is_75() -> None:
    # Design TC-1: 6 of 8 correct -> 6 / 8 * 100 = 75. Two wrong: an open
    # incident (should be "no") and a missing license (should be "yes").
    answers = {
        "license_current": "no",  # wrong
        "wcb_coverage": "yes",
        "insurance_current": "yes",
        "safety_program": "yes",
        "references_available": "yes",
        "financial_statements": "yes",
        "has_open_incidents": "yes",  # wrong
        "has_unpaid_liens": "no",
    }
    assert compute_prequal_score(answers) == 75


def test_unanswered_counts_as_incorrect_not_smaller_denominator() -> None:
    # Only 4 of 8 answered correctly; the 4 blanks do NOT shrink the
    # denominator, so the score is 4 / 8 * 100 = 50, not 100.
    answers = {
        "license_current": "yes",
        "wcb_coverage": "yes",
        "insurance_current": "yes",
        "safety_program": "yes",
    }
    assert compute_prequal_score(answers) == 50


def test_validate_questionnaire_lists_missing_required() -> None:
    answers = {"license_current": "yes", "wcb_coverage": "yes"}
    missing = validate_questionnaire(answers)
    # Six required questions are still unanswered.
    expected = {q.key for q in DEFAULT_PREQUAL_QUESTIONS if q.required} - {
        "license_current",
        "wcb_coverage",
    }
    assert set(missing) == expected


def test_validate_questionnaire_complete_is_empty() -> None:
    answers = {q.key: ("no" if q.expected == "no" else "yes") for q in DEFAULT_PREQUAL_QUESTIONS}
    assert validate_questionnaire(answers) == []


# ── Procurement PO vendor gate (real PostgreSQL) ──────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _seed_vendor_sub(
    session: AsyncSession,
    *,
    blocked: bool = False,
    prequal: str = "approved",
) -> uuid.UUID:
    """Seed a subcontractor linked to a fresh CRM contact id; return that id."""
    from app.modules.subcontractors.models import Subcontractor

    contact_id = uuid.uuid4()
    sub = Subcontractor(
        legal_name="Acme Trades",
        contact_id=contact_id,
        is_blocked=blocked,
        prequalification_status=prequal,
    )
    session.add(sub)
    await session.flush()
    return contact_id


def _po_create(contact_id: uuid.UUID | None) -> POCreate:
    return POCreate(
        project_id=uuid.uuid4(),
        vendor_contact_id=str(contact_id) if contact_id else None,
        currency_code="CAD",
        status="draft",
        items=[POItemCreate(description="Drywall", quantity="10", unit_rate="5")],
    )


@pytest.mark.asyncio
async def test_create_po_hard_blocks_blocked_vendor(session: AsyncSession) -> None:
    contact_id = await _seed_vendor_sub(session, blocked=True)
    svc = ProcurementService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.create_po(_po_create(contact_id))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "vendor_blocked"


@pytest.mark.asyncio
async def test_create_po_warns_non_prequalified_vendor(session: AsyncSession) -> None:
    # Rejected prequal is non-blocking on procurement: PO is created, warning
    # is surfaced on the transient ``vendor_warnings`` attribute.
    contact_id = await _seed_vendor_sub(session, prequal="rejected")
    svc = ProcurementService(session)
    po = await svc.create_po(_po_create(contact_id))
    assert po.id is not None
    assert po.vendor_warnings == ["prequalification_rejected"]


@pytest.mark.asyncio
async def test_create_po_clean_for_approved_vendor(session: AsyncSession) -> None:
    contact_id = await _seed_vendor_sub(session, prequal="approved")
    svc = ProcurementService(session)
    po = await svc.create_po(_po_create(contact_id))
    assert po.vendor_warnings == []


@pytest.mark.asyncio
async def test_create_po_never_gates_adhoc_supplier(session: AsyncSession) -> None:
    # A vendor_contact_id that is not a registered subcontractor (plain CRM
    # contact) is never gated - no block, no warning.
    svc = ProcurementService(session)
    po = await svc.create_po(_po_create(uuid.uuid4()))
    assert po.vendor_warnings == []


@pytest.mark.asyncio
async def test_create_po_no_vendor_is_clean(session: AsyncSession) -> None:
    svc = ProcurementService(session)
    po = await svc.create_po(_po_create(None))
    assert po.vendor_warnings == []


@pytest.mark.asyncio
async def test_issue_po_hard_blocks_vendor_blocked_after_create(session: AsyncSession) -> None:
    # Vendor is approved at create, then blocked; issuing must be refused.
    from app.modules.subcontractors.models import Subcontractor

    contact_id = await _seed_vendor_sub(session, prequal="approved")
    svc = ProcurementService(session)
    po = await svc.create_po(_po_create(contact_id))
    await svc.approve_po(po.id)

    # Block the vendor after the PO was approved.
    sub = (await session.execute(select(Subcontractor).where(Subcontractor.contact_id == contact_id))).scalar_one()
    sub.is_blocked = True
    session.add(sub)
    await session.flush()

    with pytest.raises(HTTPException) as exc:
        await svc.issue_po(po.id)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "vendor_blocked"


@pytest.mark.asyncio
async def test_update_po_regate_on_vendor_change(session: AsyncSession) -> None:
    # Create against an approved vendor, then PATCH the vendor to a blocked one.
    good = await _seed_vendor_sub(session, prequal="approved")
    bad = await _seed_vendor_sub(session, blocked=True)
    svc = ProcurementService(session)
    po = await svc.create_po(_po_create(good))
    with pytest.raises(HTTPException) as exc:
        await svc.update_po(po.id, POUpdate(vendor_contact_id=str(bad)))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "vendor_blocked"
