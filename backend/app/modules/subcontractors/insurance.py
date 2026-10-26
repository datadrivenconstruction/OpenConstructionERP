# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Subcontractor insurance compliance​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ - certificate expiry, payment gate, override, dashboard.

The insurance certificates a subcontractor holds are rows of
:class:`~app.modules.subcontractors.models.Certificate`. This module adds the
three things a site or commercial manager needs from them:

* an alert bucket per certificate, at 30, 14 and 0 days before expiry, sent
  once per bucket to the notifications module;
* a payment gate: finance approval and payment of a pay application are refused
  while a certificate marked mandatory has lapsed. The gate is the
  ``subcontractor_insurance`` validation rule set, run through the validation
  engine, so the same rule answers on the compliance dashboard and at the gate;
* a manager override with a recorded reason, kept as an append-only row and in
  the audit log. An override covers the lapses it names and nothing that lapses
  afterwards.

The insurance types are country neutral. A national pack may require more
types (``progress_billing.sub_payment_requirements``); those stay with the pack.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.subcontractors.models import (
    Certificate,
    PaymentApplication,
    PaymentComplianceOverride,
    SubcontractAgreement,
    Subcontractor,
)

logger = logging.getLogger(__name__)

#: Country-neutral insurance certificate types, in the order the UI lists them.
INSURANCE_CERT_TYPES: tuple[str, ...] = (
    "public_liability",
    "employers_liability",
    "professional_indemnity",
    "contractors_all_risk",
    "workers_compensation",
    "motor_vehicle",
    "product_liability",
    "plant_equipment",
    "environmental_liability",
    "cyber_liability",
    "insurance",
)

#: Days before expiry at which an alert is raised; 0 is the expiry day itself.
ALERT_WINDOWS: tuple[int, ...] = (30, 14, 0)

#: Rule set the payment gate runs.
INSURANCE_RULE_SET = "subcontractor_insurance"

#: Key in ``Certificate.metadata_`` recording which alert buckets were already sent.
ALERTS_SENT_KEY = "insurance_alerts_sent"


# ── Pure helpers ──────────────────────────────────────────────────────────


def alert_bucket(valid_until: date | None, as_at: date, *, revoked: bool = False) -> str:
    """Classify a certificate by how close it is to expiry.

    Returns ``revoked``, ``expired`` (valid_until before ``as_at``), ``due_0``
    (expires today), ``due_14``, ``due_30`` or ``valid``. A certificate with no
    expiry date is ``valid``: it never lapses.
    """
    if revoked:
        return "revoked"
    if valid_until is None:
        return "valid"
    days = (valid_until - as_at).days
    if days < 0:
        return "expired"
    for window in sorted(ALERT_WINDOWS):
        if days <= window:
            return f"due_{window}"
    return "valid"


def _covered(certificates: Sequence[Any], cert_type: str, as_at: date) -> bool:
    return any(
        c.cert_type == cert_type
        and not c.revoked
        and (c.valid_until is None or c.valid_until >= as_at)
        and (c.issue_date is None or c.issue_date <= as_at)
        for c in certificates
    )


def lapsed_mandatory_reasons(certificates: Sequence[Any], as_at: date) -> list[str]:
    """Reason codes for every mandatory certificate type that is not covered on ``as_at``.

    A mandatory type passes when any certificate of that type is live on the
    date, so a renewal on file clears a lapsed predecessor. Codes are
    ``expired_mandatory_certificate:<type>:<date>`` or
    ``revoked_mandatory_certificate:<type>``, sorted for a stable answer.
    """
    reasons: set[str] = set()
    for cert in certificates:
        if not getattr(cert, "is_mandatory", False):
            continue
        if _covered(certificates, cert.cert_type, as_at):
            continue
        if cert.revoked:
            reasons.add(f"revoked_mandatory_certificate:{cert.cert_type}")
        elif cert.valid_until is not None and cert.valid_until < as_at:
            reasons.add(f"expired_mandatory_certificate:{cert.cert_type}:{cert.valid_until.isoformat()}")
    return sorted(reasons)


def certificate_payload(cert: Any, as_at: date) -> dict[str, Any]:
    """One certificate as the rule payload and the dashboard read it."""
    return {
        "id": str(cert.id),
        "subcontractor_id": str(cert.subcontractor_id),
        "cert_type": cert.cert_type,
        "is_mandatory": bool(getattr(cert, "is_mandatory", False)),
        "valid_until": cert.valid_until.isoformat() if cert.valid_until else None,
        "issue_date": cert.issue_date.isoformat() if cert.issue_date else None,
        "revoked": bool(cert.revoked),
        "policy_number": getattr(cert, "policy_number", None),
        "coverage_amount": str(cert.coverage_amount) if getattr(cert, "coverage_amount", None) is not None else None,
        "coverage_currency": getattr(cert, "coverage_currency", None),
        "issued_by": cert.issued_by,
        "bucket": alert_bucket(cert.valid_until, as_at, revoked=bool(cert.revoked)),
        "days_to_expiry": (cert.valid_until - as_at).days if cert.valid_until else None,
    }


def overall_status(certs: Sequence[dict[str, Any]], blocked: bool) -> str:
    """``non_compliant`` when payment is blocked, ``expiring`` when any cert is due, else ``compliant``."""
    if blocked:
        return "non_compliant"
    if any(c["bucket"].startswith("due_") or c["bucket"] in ("expired", "revoked") for c in certs):
        return "expiring"
    return "compliant"


def override_covers(override_reasons: Sequence[str], current: Sequence[str]) -> bool:
    """An override covers the gate when every current reason was named in it."""
    return bool(current) and set(current) <= set(override_reasons)


# ── Service ──────────────────────────────────────────────────────────────


class InsuranceComplianceService:
    """Insurance gate, override and dashboards for subcontractors."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _certs(self, subcontractor_id: uuid.UUID) -> list[Certificate]:
        rows = await self.session.execute(select(Certificate).where(Certificate.subcontractor_id == subcontractor_id))
        return list(rows.scalars().all())

    async def _payment(self, payment_id: uuid.UUID) -> tuple[PaymentApplication, SubcontractAgreement]:
        pay = await self.session.get(PaymentApplication, payment_id)
        if pay is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment application not found")
        agreement = await self.session.get(SubcontractAgreement, pay.agreement_id)
        if agreement is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agreement not found")
        return pay, agreement

    async def latest_override(self, payment_id: uuid.UUID) -> PaymentComplianceOverride | None:
        """The most recent override on a pay application, or ``None``."""
        rows = await self.session.execute(
            select(PaymentComplianceOverride)
            .where(PaymentComplianceOverride.payment_application_id == payment_id)
            .order_by(PaymentComplianceOverride.overridden_at.desc())
            .limit(1)
        )
        return rows.scalars().first()

    async def validate_subcontractor(self, subcontractor_id: uuid.UUID, as_at: date) -> dict[str, Any]:
        """Run the ``subcontractor_insurance`` rule set over one subcontractor's certificates."""
        from app.core.validation.engine import validation_engine  # noqa: PLC0415
        from app.modules.subcontractors.insurance_rules import register_insurance_rules  # noqa: PLC0415

        register_insurance_rules()
        certs = await self._certs(subcontractor_id)
        payload = {
            "as_of": as_at.isoformat(),
            "subcontractor_id": str(subcontractor_id),
            "certificates": [certificate_payload(c, as_at) for c in certs],
        }
        report = await validation_engine.validate(
            payload,
            rule_sets=[INSURANCE_RULE_SET],
            target_type="subcontractor_insurance",
            target_id=str(subcontractor_id),
        )
        return {
            "certificates": payload["certificates"],
            "errors": [r for r in report.results if not r.passed and r.severity.value == "error"],
            "warnings": [r for r in report.results if not r.passed and r.severity.value == "warning"],
            "results": report.results,
            "reasons": lapsed_mandatory_reasons(certs, as_at),
        }

    async def payment_status(self, payment_id: uuid.UUID, *, as_at: date | None = None) -> dict[str, Any]:
        """Whether insurance blocks this pay application, and whether an override covers it."""
        ref = as_at or date.today()
        pay, agreement = await self._payment(payment_id)
        verdict = await self.validate_subcontractor(agreement.subcontractor_id, ref)
        reasons = verdict["reasons"] if verdict["errors"] else []
        override = await self.latest_override(payment_id)
        overridden = override is not None and override_covers(override.covered_reasons or [], reasons)
        return {
            "payment_application_id": pay.id,
            "subcontractor_id": agreement.subcontractor_id,
            "blocked": bool(reasons) and not overridden,
            "reasons": reasons,
            "overridden": overridden,
            "override": _override_dict(override) if override is not None else None,
            "certificates": verdict["certificates"],
        }

    async def assert_payment_allowed(self, payment_id: uuid.UUID, *, as_at: date | None = None) -> None:
        """Raise 409 ``insurance_compliance_blocked`` while a mandatory certificate has lapsed."""
        verdict = await self.payment_status(payment_id, as_at=as_at)
        if verdict["blocked"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "insurance_compliance_blocked",
                    "message": (
                        "Payment is blocked because a mandatory insurance certificate of this "
                        "subcontractor has lapsed. Record the renewed certificate, or a manager "
                        "can override with a reason."
                    ),
                    "reasons": verdict["reasons"],
                },
            )

    async def override(
        self,
        payment_id: uuid.UUID,
        *,
        reason: str,
        user_id: str | None,
        as_at: date | None = None,
    ) -> PaymentComplianceOverride:
        """Record a manager's override of the insurance gate for one pay application."""
        verdict = await self.payment_status(payment_id, as_at=as_at)
        if not verdict["reasons"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "nothing_to_override", "message": "Insurance does not block this payment."},
            )
        row = PaymentComplianceOverride(
            payment_application_id=payment_id,
            subcontractor_id=verdict["subcontractor_id"],
            reason=reason,
            covered_reasons=list(verdict["reasons"]),
            overridden_by=str(user_id) if user_id else None,
            overridden_at=datetime.now(UTC),
        )
        self.session.add(row)
        await self.session.flush()

        from app.core.audit import audit_log  # noqa: PLC0415

        await audit_log(
            self.session,
            action="override",
            entity_type="subcontractor_payment_application",
            entity_id=str(payment_id),
            user_id=str(user_id) if user_id else None,
            details={"gate": INSURANCE_RULE_SET, "reason": reason, "covered_reasons": row.covered_reasons},
        )
        event_bus.publish_detached(
            "subcontractors.payment.insurance_overridden",
            {
                "payment_application_id": str(payment_id),
                "subcontractor_id": str(verdict["subcontractor_id"]),
                "reasons": row.covered_reasons,
                "user_id": str(user_id) if user_id else None,
            },
            source_module="subcontractors",
        )
        return row

    async def subcontractor_status(self, subcontractor_id: uuid.UUID, *, as_at: date | None = None) -> dict[str, Any]:
        """Insurance status for the subcontractor card and bidder prequalification."""
        ref = as_at or date.today()
        verdict = await self.validate_subcontractor(subcontractor_id, ref)
        blocked = bool(verdict["errors"])
        return {
            "subcontractor_id": subcontractor_id,
            "as_of": ref,
            "status": overall_status(verdict["certificates"], blocked),
            "payment_blocked": blocked,
            "reasons": verdict["reasons"] if blocked else [],
            "certificates": verdict["certificates"],
            "findings": [_result_dict(r) for r in verdict["results"] if not r.passed],
        }

    async def project_dashboard(self, project_id: uuid.UUID, *, as_at: date | None = None) -> dict[str, Any]:
        """Per-project insurance compliance: every subcontractor on the project and its payments."""
        ref = as_at or date.today()
        agreements = list(
            (
                await self.session.execute(
                    select(SubcontractAgreement).where(SubcontractAgreement.project_id == project_id)
                )
            )
            .scalars()
            .all()
        )
        sub_ids = sorted({a.subcontractor_id for a in agreements}, key=str)
        subs = (
            {
                s.id: s
                for s in (await self.session.execute(select(Subcontractor).where(Subcontractor.id.in_(sub_ids))))
                .scalars()
                .all()
            }
            if sub_ids
            else {}
        )
        counts = {"compliant": 0, "expiring": 0, "non_compliant": 0}
        buckets = {"valid": 0, "due_30": 0, "due_14": 0, "due_0": 0, "expired": 0, "revoked": 0}
        rows: list[dict[str, Any]] = []
        for sid in sub_ids:
            st = await self.subcontractor_status(sid, as_at=ref)
            counts[st["status"]] += 1
            for c in st["certificates"]:
                buckets[c["bucket"]] = buckets.get(c["bucket"], 0) + 1
            sub = subs.get(sid)
            rows.append(
                {
                    "subcontractor_id": sid,
                    "name": (sub.trade_name or sub.legal_name) if sub else str(sid),
                    "status": st["status"],
                    "payment_blocked": st["payment_blocked"],
                    "reasons": st["reasons"],
                    "certificates": st["certificates"],
                }
            )
        agreement_ids = [a.id for a in agreements]
        pays = (
            list(
                (
                    await self.session.execute(
                        select(PaymentApplication).where(
                            PaymentApplication.agreement_id.in_(agreement_ids),
                            PaymentApplication.status.in_(("submitted", "foreman_approved", "finance_approved")),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if agreement_ids
            else []
        )
        payments: list[dict[str, Any]] = []
        for pay in pays:
            ps = await self.payment_status(pay.id, as_at=ref)
            if ps["reasons"]:
                payments.append(
                    {
                        "payment_application_id": pay.id,
                        "application_number": pay.application_number,
                        "subcontractor_id": ps["subcontractor_id"],
                        "status": pay.status,
                        "net_amount": str(pay.net_amount),
                        "currency": pay.currency,
                        "blocked": ps["blocked"],
                        "overridden": ps["overridden"],
                        "reasons": ps["reasons"],
                        "override": ps["override"],
                    }
                )
        return {
            "project_id": project_id,
            "as_of": ref,
            "counts": counts,
            "certificate_buckets": buckets,
            "subcontractors": rows,
            "gated_payments": payments,
        }

    async def run_expiry_alerts(self, *, as_at: date | None = None) -> int:
        """Send one notification per certificate per alert bucket (30 / 14 / 0 days, and expired).

        Recipients are the owners of the projects the subcontractor works on and
        the user who registered the subcontractor. A bucket already sent is
        recorded on the certificate, so a rerun sends nothing twice.
        """
        from app.modules.notifications.service import NotificationService  # noqa: PLC0415
        from app.modules.projects.models import Project  # noqa: PLC0415

        ref = as_at or date.today()
        certs = list((await self.session.execute(select(Certificate).where(Certificate.revoked.is_(False)))).scalars())
        notifier = NotificationService(self.session)
        sent = 0
        for cert in certs:
            bucket = alert_bucket(cert.valid_until, ref)
            if bucket == "valid":
                continue
            meta = dict(cert.metadata_ or {})
            done = list(meta.get(ALERTS_SENT_KEY) or [])
            if bucket in done:
                continue
            sub = await self.session.get(Subcontractor, cert.subcontractor_id)
            project_rows = (
                await self.session.execute(
                    select(Project.id, Project.owner_id)
                    .join(SubcontractAgreement, SubcontractAgreement.project_id == Project.id)
                    .where(SubcontractAgreement.subcontractor_id == cert.subcontractor_id)
                )
            ).all()
            recipients: set[str] = {str(owner) for _pid, owner in project_rows if owner}
            if sub is not None and sub.created_by:
                recipients.add(str(sub.created_by))
            context = {
                "subcontractor": (sub.trade_name or sub.legal_name) if sub else "",
                "cert_type": cert.cert_type,
                "valid_until": cert.valid_until.isoformat() if cert.valid_until else "",
                "days": (cert.valid_until - ref).days if cert.valid_until else 0,
            }
            for uid in sorted(recipients):
                try:
                    await notifier.create(
                        uid,
                        "insurance_expiry",
                        f"notifications.subcontractor_insurance.{bucket}_title",
                        entity_type="subcontractor_certificate",
                        entity_id=str(cert.id),
                        body_key=f"notifications.subcontractor_insurance.{bucket}_body",
                        body_context=context,
                        action_url=f"/subcontractors?sub={cert.subcontractor_id}",
                    )
                    sent += 1
                except (ValueError, TypeError):
                    logger.debug("insurance alert: bad recipient %s", uid, exc_info=True)
            meta[ALERTS_SENT_KEY] = [*done, bucket]
            cert.metadata_ = meta
            event_bus.publish_detached(
                "subcontractors.insurance.certificate_alert",
                {"certificate_id": str(cert.id), "subcontractor_id": str(cert.subcontractor_id), "bucket": bucket},
                source_module="subcontractors",
            )
        await self.session.flush()
        return sent


def _override_dict(row: PaymentComplianceOverride) -> dict[str, Any]:
    return {
        "id": row.id,
        "reason": row.reason,
        "covered_reasons": list(row.covered_reasons or []),
        "overridden_by": row.overridden_by,
        "overridden_at": row.overridden_at,
    }


def _result_dict(r: Any) -> dict[str, Any]:
    return {
        "rule_id": r.rule_id,
        "severity": r.severity.value,
        "message": r.message,
        "element_ref": r.element_ref,
    }
