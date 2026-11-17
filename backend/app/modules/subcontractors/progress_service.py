# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Progress statement and agreement documents, as methods of the subcontractor service.

Kept beside :mod:`app.modules.subcontractors.service` rather than inside it:
that file is large and these two features share nothing with it except the
session and the repositories, which :class:`SubcontractorService` hands to the
mixin through ``self``.

* The statement of a pay application is built by the pure
  :func:`~app.modules.subcontractors.progress_billing.build_statement` from the
  agreement's work packages (its schedule of values) and every pay application
  of the agreement; this module only loads the rows and runs the rule set.
* The required-documents policy is one installation row. Without a row the
  default list (:data:`~app.modules.subcontractors.validators.DEFAULT_REQUIRED_DOCUMENTS`)
  applies in warn mode, so nothing blocks until somebody chooses to.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status

from app.core.i18n import get_locale
from app.core.validation.engine import ValidationReport, validation_engine
from app.modules.subcontractors import progress_billing, validators
from app.modules.subcontractors.models import (
    PaymentApplication,
    SubcontractAgreement,
    SubcontractDocument,
    SubcontractDocumentPolicy,
)
from app.modules.subcontractors.schemas import DocumentPolicy, StatementPreviewRequest

PAY_APP_RULE_SET = "subcontract_pay_app"
REQUIRED_DOCUMENTS_RULE_ID = "subcontract.required_documents"


def _iso(value: object | None) -> str | None:
    return value.isoformat() if isinstance(value, date) else (str(value) if value else None)


class ProgressBillingMixin:
    """Statement, pay application rules and agreement documents. Mixed into the service."""

    # Provided by SubcontractorService.__init__.
    session: Any
    agreements: Any
    work_packages: Any
    payments: Any
    payment_lines: Any
    agreement_documents: Any
    document_policy_repo: Any

    # ── The statement ───────────────────────────────────────────────────

    async def _agreement_or_404(self, agreement_id: uuid.UUID) -> SubcontractAgreement:
        agreement = await self.agreements.get_by_id(agreement_id)
        if agreement is None:
            raise HTTPException(status_code=404, detail="Agreement not found")
        return agreement

    async def _statement_sources(self, agreement: SubcontractAgreement) -> dict[str, Any]:
        packages = list(await self.work_packages.list_for_agreement(agreement.id))
        applications = list(await self.payments.list_for_agreement(agreement.id))
        applications.sort(key=lambda a: (a.submitted_at or a.created_at, a.application_number))
        by_app: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for application in applications:
            by_app[application.id] = [
                {
                    "work_package_id": str(line.work_package_id),
                    "claimed_amount": line.claimed_amount,
                    "approved_amount": line.approved_amount,
                }
                for line in await self.payment_lines.list_for_application(application.id)
            ]
        return {
            "work_packages": [{"id": str(p.id), "name": p.name, "planned_value": p.planned_value} for p in packages],
            "applications": [
                {
                    "id": str(a.id),
                    "number": a.application_number,
                    "status": a.status,
                    "gross_amount": a.gross_amount,
                    "net_amount": a.net_amount,
                    "approved_gross_amount": a.approved_gross_amount,
                    "approved_net_amount": a.approved_net_amount,
                    "lines": by_app.get(a.id, []),
                }
                for a in applications
            ],
            "change_orders_total": await self.agreements.approved_changes_total(agreement.id),
        }

    async def _documents_payload(self, agreement: SubcontractAgreement) -> dict[str, Any]:
        """What the required-documents rule reads: the policy and the files on file."""
        policy = await self.document_policy()
        held = await self.agreement_documents.list_for_agreement(agreement.id)
        return {
            "required_documents": [r.model_dump() for r in policy.required],
            "enforcement": policy.enforcement,
            "documents": [
                {
                    "role": d.doc_role,
                    "title": d.title,
                    "signed_date": _iso(d.signed_date),
                    "valid_until": _iso(d.valid_until),
                }
                for d in held
            ],
        }

    def _statement_payload(
        self,
        agreement: SubcontractAgreement,
        statement: dict[str, Any],
        *,
        number: str,
        gross: Decimal,
        reason: str | None,
        today: date | None,
    ) -> dict[str, Any]:
        summary = statement["summary"]
        return {
            "id": number,
            "application_number": number,
            "title": agreement.title,
            "currency": agreement.currency or "",
            "as_of": (today or datetime.now(UTC).date()).isoformat(),
            "contract_sum_to_date": str(summary["contract_sum_to_date"]),
            "previous_gross_billed": str(summary["previous_gross_billed"]),
            "this_gross": str(gross),
            "override_reason": reason or "",
            "lines": [
                {
                    "name": row["name"],
                    "scheduled_value": str(row["scheduled_value"]),
                    "previous": str(row["previous"]),
                    "this_period": str(row["this_period"]),
                    "total_completed": str(row["total_completed"]),
                }
                for row in statement["lines"]
            ],
        }

    async def _run_pay_app_rules(self, agreement: SubcontractAgreement, payload: dict[str, Any]) -> ValidationReport:
        payload = {**payload, **await self._documents_payload(agreement)}
        return await validation_engine.validate(
            data=payload,
            rule_sets=[PAY_APP_RULE_SET],
            target_type="subcontract_pay_application",
            target_id=str(payload.get("id") or ""),
            project_id=str(agreement.project_id),
            metadata={"locale": get_locale()},
        )

    @staticmethod
    def _findings(report: ValidationReport) -> list[dict[str, Any]]:
        return [
            {
                "rule_id": r.rule_id,
                "severity": r.severity.value,
                "passed": r.passed,
                "message": r.message,
                "element_ref": r.element_ref,
                "suggestion": r.suggestion,
            }
            for r in report.results
        ]

    @staticmethod
    def _statement_response(
        agreement: SubcontractAgreement,
        statement: dict[str, Any],
        findings: list[dict[str, Any]],
        *,
        app: PaymentApplication | None,
        reason: str | None,
    ) -> dict[str, Any]:
        return {
            "payment_application_id": app.id if app is not None else None,
            "agreement_id": agreement.id,
            "application_number": app.application_number if app is not None else "",
            "status": app.status if app is not None else "draft",
            "period_start": app.period_start if app is not None else None,
            "period_end": app.period_end if app is not None else None,
            "currency": (app.currency if app is not None else "") or agreement.currency or "",
            "override_reason": reason or None,
            "lines": statement["lines"],
            "summary": statement["summary"],
            "findings": findings,
        }

    def _build(self, agreement: SubcontractAgreement, sources: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return progress_billing.build_statement(
            contract_sum_to_date=agreement.total_value,
            change_orders_total=sources["change_orders_total"],
            retention_percent=agreement.retention_percent,
            work_packages=sources["work_packages"],
            applications=sources["applications"],
            **kwargs,
        )

    async def pay_app_statement(self, payment_id: uuid.UUID, *, today: date | None = None) -> dict[str, Any]:
        """The progress statement of a saved pay application, with the rules' findings."""
        app = await self.payments.get_by_id(payment_id)
        if app is None:
            raise HTTPException(status_code=404, detail="Payment application not found")
        agreement = await self._agreement_or_404(app.agreement_id)
        sources = await self._statement_sources(agreement)
        statement = self._build(agreement, sources, current_id=str(app.id))
        reason = (app.metadata_ or {}).get("override_reason")
        payload = self._statement_payload(
            agreement,
            statement,
            number=app.application_number,
            gross=Decimal(str(app.gross_amount or 0)),
            reason=reason,
            today=today,
        )
        report = await self._run_pay_app_rules(agreement, payload)
        return self._statement_response(agreement, statement, self._findings(report), app=app, reason=reason)

    def _preview_lines(self, sources: dict[str, Any], request_lines: list[Any]) -> list[dict[str, Any]]:
        """Typed lines as statement lines: a period percentage becomes an amount of the scheduled value."""
        scheduled = {p["id"]: Decimal(str(p["planned_value"] or 0)) for p in sources["work_packages"]}
        resolved: list[dict[str, Any]] = []
        for line in request_lines:
            key = str(line.work_package_id)
            if key not in scheduled:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail={"code": "work_package_not_on_agreement", "work_package_id": key},
                )
            percent = getattr(line, "this_period_percent", None)
            amount = (
                progress_billing.amount_from_percent(scheduled[key], Decimal(str(percent)))
                if percent is not None
                else Decimal(str(line.claimed_amount))
            )
            resolved.append({"work_package_id": key, "claimed_amount": amount, "approved_amount": Decimal("0")})
        return resolved

    async def preview_statement(
        self,
        agreement_id: uuid.UUID,
        data: StatementPreviewRequest,
        *,
        today: date | None = None,
    ) -> dict[str, Any]:
        """The statement a pay application would carry, from typed lines, saving nothing."""
        agreement = await self._agreement_or_404(agreement_id)
        sources = await self._statement_sources(agreement)
        lines = self._preview_lines(sources, data.lines)
        statement = self._build(agreement, sources, current_lines=lines)
        payload = self._statement_payload(
            agreement,
            statement,
            number="",
            gross=statement["summary"]["this_gross"],
            reason=data.overage_reason,
            today=today,
        )
        report = await self._run_pay_app_rules(agreement, payload)
        return self._statement_response(
            agreement, statement, self._findings(report), app=None, reason=data.overage_reason
        )

    async def assert_submission_within_limits(
        self,
        agreement: SubcontractAgreement,
        lines: list[Any],
        *,
        gross: Decimal,
        reason: str | None,
        today: date | None = None,
    ) -> list[dict[str, Any]]:
        """Resolve typed lines and refuse a claim the schedule of values cannot carry.

        Returns the lines with period percentages turned into amounts. Errors of
        the pay application rule set (a negative cumulative, a total above the
        agreement value plus approved variations) refuse with 422 before
        anything is written; warnings (a line over 100 percent) do not.
        The required-documents rule is not part of this gate: documents gate
        approval and activation, not the sub filing its claim.
        """
        sources = await self._statement_sources(agreement)
        resolved = self._preview_lines(sources, lines)
        statement = self._build(agreement, sources, current_lines=resolved)
        payload = self._statement_payload(agreement, statement, number="", gross=gross, reason=reason, today=today)
        payload["required_documents"] = []
        report = await validation_engine.validate(
            data=payload,
            rule_sets=[PAY_APP_RULE_SET],
            target_type="subcontract_pay_application",
            target_id="",
            project_id=str(agreement.project_id),
            metadata={"locale": get_locale()},
        )
        errors = [r for r in report.results if not r.passed and r.severity.value == "error"]
        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "pay_application_over_limit",
                    "findings": [{"rule_id": r.rule_id, "message": r.message} for r in errors],
                },
            )
        return resolved

    # ── Documents ───────────────────────────────────────────────────────

    async def document_policy(self) -> DocumentPolicy:
        """The policy in force: the installation row, or the default list in warn mode."""
        row: SubcontractDocumentPolicy | None = await self.document_policy_repo.get_installation()
        if row is None:
            return DocumentPolicy(required=list(validators.DEFAULT_REQUIRED_DOCUMENTS), enforcement="warn")
        return DocumentPolicy(required=list(row.required or []), enforcement=row.enforcement or "warn")

    async def document_policy_is_default(self) -> bool:
        return await self.document_policy_repo.get_installation() is None

    async def set_document_policy(self, data: DocumentPolicy, user_id: str | None) -> DocumentPolicy:
        roles = [r.role for r in data.required]
        if len(set(roles)) != len(roles):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "duplicate_required_role"},
            )
        row = await self.document_policy_repo.get_installation()
        values = {"required": [r.model_dump() for r in data.required], "enforcement": data.enforcement}
        if row is None:
            await self.document_policy_repo.create(
                SubcontractDocumentPolicy(scope="installation", updated_by=user_id, **values)
            )
        else:
            await self.document_policy_repo.update_fields(row.id, updated_by=user_id, **values)
        return await self.document_policy()

    async def document_presets(self, project_id: uuid.UUID | None) -> list[dict[str, Any]]:
        """Optional presets the project's national pack offers (``document_presets`` of its block)."""
        if project_id is None:
            return []
        try:
            from app.core.regional_packs import resolve_progress_billing  # noqa: PLC0415
            from app.modules.projects.models import Project  # noqa: PLC0415
        except ImportError:
            return []
        project = await self.session.get(Project, project_id)
        if project is None:
            return []
        billing = resolve_progress_billing(
            country_code=getattr(project, "country_code", None),
            region=getattr(project, "region", None),
        )
        block = (billing or {}).get("sub_payment_requirements")
        presets = block.get("document_presets") if isinstance(block, dict) else None
        return [dict(p) for p in presets if isinstance(p, dict)] if isinstance(presets, list) else []

    async def required_document_gaps(
        self, agreement: SubcontractAgreement, *, today: date | None = None
    ) -> list[dict[str, str]]:
        payload = {**await self._documents_payload(agreement), "as_of": (today or datetime.now(UTC).date()).isoformat()}
        return [dict(f.details) for f in validators.check_required_documents(payload)]

    async def required_documents_status(self, agreement_id: uuid.UUID) -> dict[str, Any]:
        agreement = await self._agreement_or_404(agreement_id)
        policy = await self.document_policy()
        return {
            "agreement_id": agreement.id,
            "enforcement": policy.enforcement,
            "required": policy.required,
            "gaps": await self.required_document_gaps(agreement),
        }

    async def enforce_required_documents(
        self, agreement: SubcontractAgreement, *, operation: str, today: date | None = None
    ) -> None:
        """Refuse (409) when the policy blocks and a required document is missing, unsigned or expired.

        In warn mode this does nothing; the same gaps reach the user through
        the ``subcontract.required_documents`` rule on the validation reports.
        """
        policy = await self.document_policy()
        if policy.enforcement != "block":
            return
        gaps = await self.required_document_gaps(agreement, today=today)
        if gaps:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "required_documents_missing", "operation": operation, "gaps": gaps},
            )

    async def create_agreement_document(self, **fields: Any) -> SubcontractDocument:
        return await self.agreement_documents.create(SubcontractDocument(**fields))
