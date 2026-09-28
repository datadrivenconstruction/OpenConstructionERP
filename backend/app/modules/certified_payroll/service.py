# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Certified payroll business logic.

The one idea worth stating before the code: a draft week owns no rows. Its lines
are derived from ``oe_payroll`` every time they are asked for, so there is never
a second live copy of the same hours drifting away from the first. Certifying
freezes that derivation into :class:`CertifiedPayrollLine` and stamps the
signature, and from then on the week reads back its own frozen rows and never
recomputes them.

Both paths produce the same dict shape, so the validation rules, the form
serialiser and the API response do not know or care which they were handed.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.certified_payroll.certpay_math import (
    governing_classification,
    line_pay,
    split_week_hours,
    week_days,
)
from app.modules.certified_payroll.models import (
    ALL_FRINGE_ELECTIONS,
    CertifiedPayrollLine,
    CertifiedPayrollWeek,
    WageClassification,
    WageDetermination,
    WorkerClassificationAssignment,
)
from app.modules.certified_payroll.repository import (
    AssignmentRepository,
    CertifiedWeekRepository,
    WageClassificationRepository,
    WageDeterminationRepository,
)
from app.modules.certified_payroll.validators import CERTIFIED_PAYROLL_RULE_SET
from app.modules.certified_payroll.wh347 import default_statement_of_compliance, render_form
from app.modules.payroll.models import PayrollBatch, PayrollDeduction, PayrollEntry

logger = logging.getLogger(__name__)

# Default overtime multiplier, matching the platform's payroll arithmetic. It is
# a default the caller overrides per contract, never a rule this module asserts.
_DEFAULT_MULTIPLIER = "1.5"


def _dec(value: Any, fallback: str = "0") -> Decimal:
    """Parse a stored Decimal-as-string, falling back rather than raising."""
    try:
        parsed = Decimal(str(value if value not in (None, "") else fallback).strip())
    except (ArithmeticError, ValueError, TypeError):
        return Decimal(fallback)
    return parsed if parsed.is_finite() else Decimal(fallback)


def _plain(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


class CertifiedPayrollService:
    """Wage determinations, worker classification, and the weekly certified payroll."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.determination_repo = WageDeterminationRepository(session)
        self.classification_repo = WageClassificationRepository(session)
        self.assignment_repo = AssignmentRepository(session)
        self.week_repo = CertifiedWeekRepository(session)

    # ── Wage determinations ─────────────────────────────────────────────────

    async def create_determination(self, project_id: uuid.UUID, data: Any) -> WageDetermination:
        """Record a wage determination and its craft lines for a project."""
        determination = WageDetermination(
            project_id=project_id,
            authority=data.authority,
            authority_name=data.authority_name,
            jurisdiction=data.jurisdiction,
            locality=data.locality,
            identifier=data.identifier,
            title=data.title,
            determination_method=data.determination_method,
            decision_date=data.decision_date,
            effective_date=data.effective_date,
            expires_on=data.expires_on,
            statute_reference=data.statute_reference,
            source_note=data.source_note,
            currency=data.currency,
        )
        created = await self.determination_repo.create(determination)
        for ordinal, item in enumerate(data.classifications or []):
            await self.classification_repo.create(
                WageClassification(
                    determination_id=created.id,
                    code=item.code,
                    title=item.title,
                    basic_hourly_rate=item.basic_hourly_rate,
                    fringe_rate=item.fringe_rate,
                    note=item.note,
                    ordinal=item.ordinal or ordinal,
                )
            )
        refreshed = await self.determination_repo.get_by_id(created.id)
        return refreshed or created

    async def get_determination(self, determination_id: uuid.UUID) -> WageDetermination:
        determination = await self.determination_repo.get_by_id(determination_id)
        if determination is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wage determination not found")
        return determination

    async def update_determination(self, determination_id: uuid.UUID, data: Any) -> WageDetermination:
        """Edit a determination that no certified week rests on."""
        determination = await self.get_determination(determination_id)
        self._reject_if_locked(determination)
        fields = {key: value for key, value in data.model_dump(exclude_unset=True).items() if value is not None}
        if fields:
            await self.determination_repo.update_fields(determination_id, **fields)
        return await self.get_determination(determination_id)

    async def delete_determination(self, determination_id: uuid.UUID) -> None:
        determination = await self.get_determination(determination_id)
        self._reject_if_locked(determination)
        await self.determination_repo.delete(determination)

    async def add_classification(self, determination_id: uuid.UUID, data: Any) -> WageClassification:
        determination = await self.get_determination(determination_id)
        self._reject_if_locked(determination)
        return await self.classification_repo.create(
            WageClassification(
                determination_id=determination_id,
                code=data.code,
                title=data.title,
                basic_hourly_rate=data.basic_hourly_rate,
                fringe_rate=data.fringe_rate,
                note=data.note,
                ordinal=data.ordinal,
            )
        )

    @staticmethod
    def _reject_if_locked(determination: WageDetermination) -> None:
        """Refuse to change a determination a signed payroll rests on."""
        if determination.locked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Wage determination {determination.identifier} is cited by a certified payroll and can no "
                    "longer be changed. Record the superseding determination as a new one instead."
                ),
            )

    # ── Worker classification ───────────────────────────────────────────────

    async def create_assignment(self, project_id: uuid.UUID, data: Any) -> WorkerClassificationAssignment:
        """Put a worker under a trade classification."""
        classification = await self.classification_repo.get_by_id(data.classification_id)
        if classification is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wage classification not found")
        election = data.fringe_election
        if election is not None and election not in ALL_FRINGE_ELECTIONS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"fringe_election must be one of {', '.join(ALL_FRINGE_ELECTIONS)}",
            )
        return await self.assignment_repo.create(
            WorkerClassificationAssignment(
                project_id=project_id,
                resource_id=data.resource_id,
                worker_name=data.worker_name,
                worker_identifier=data.worker_identifier,
                classification_id=data.classification_id,
                valid_from=data.valid_from,
                valid_to=data.valid_to,
                paid_basic_rate=data.paid_basic_rate,
                paid_fringe_rate=data.paid_fringe_rate,
                fringe_election=election,
                note=data.note,
            )
        )

    async def update_assignment(self, assignment_id: uuid.UUID, data: Any) -> WorkerClassificationAssignment:
        assignment = await self.assignment_repo.get_by_id(assignment_id)
        if assignment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Classification assignment not found")
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.assignment_repo.update_fields(assignment_id, **fields)
        refreshed = await self.assignment_repo.get_by_id(assignment_id)
        return refreshed or assignment

    async def delete_assignment(self, assignment_id: uuid.UUID) -> None:
        assignment = await self.assignment_repo.get_by_id(assignment_id)
        if assignment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Classification assignment not found")
        await self.assignment_repo.delete(assignment)

    # ── Weeks ───────────────────────────────────────────────────────────────

    async def create_week(
        self,
        project_id: uuid.UUID,
        data: Any,
        *,
        user_id: str | None = None,
    ) -> CertifiedPayrollWeek:
        """Open a draft week. Its lines are derived, so none are written here."""
        try:
            week_days(data.week_ending)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"week_ending must be an ISO date (YYYY-MM-DD): {exc}",
            ) from exc

        week = CertifiedPayrollWeek(
            project_id=project_id,
            batch_id=data.batch_id,
            week_ending=data.week_ending,
            payroll_number=data.payroll_number,
            is_final=data.is_final,
            contractor_name=data.contractor_name,
            contractor_address=data.contractor_address,
            is_subcontractor=data.is_subcontractor,
            project_name=data.project_name,
            project_location=data.project_location,
            contract_number=data.contract_number,
            covered_authorities=list(data.covered_authorities or []),
            fringe_election=data.fringe_election,
            fringe_exception_note=data.fringe_exception_note,
            status="draft",
            notes=data.notes,
            created_by=uuid.UUID(user_id) if user_id else None,
            metadata_={
                # The overtime rules in force for this week, kept with the week
                # so a payroll certified last year still says which thresholds
                # produced its split rather than picking up today's settings.
                "daily_overtime_threshold": data.daily_overtime_threshold,
                "weekly_overtime_threshold": data.weekly_overtime_threshold,
                "overtime_multiplier": data.overtime_multiplier or _DEFAULT_MULTIPLIER,
            },
        )
        return await self.week_repo.create(week)

    async def get_week(self, week_id: uuid.UUID) -> CertifiedPayrollWeek:
        week = await self.week_repo.get_by_id(week_id)
        if week is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Certified payroll week not found")
        return week

    async def update_week(self, week_id: uuid.UUID, data: Any) -> CertifiedPayrollWeek:
        week = await self.get_week(week_id)
        self._reject_if_certified(week)
        fields = {key: value for key, value in data.model_dump(exclude_unset=True).items() if value is not None}
        if fields:
            await self.week_repo.update_fields(week_id, **fields)
        return await self.get_week(week_id)

    async def delete_week(self, week_id: uuid.UUID) -> None:
        week = await self.get_week(week_id)
        self._reject_if_certified(week)
        await self.week_repo.delete(week)

    @staticmethod
    def _reject_if_certified(week: CertifiedPayrollWeek) -> None:
        """A signed statement of compliance is not editable."""
        if week.status == "certified":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"The payroll for the week ending {week.week_ending} has been certified and cannot be "
                    "changed. Issue a corrected payroll for the same week with the next payroll number."
                ),
            )

    # ── Deriving a week from payroll ────────────────────────────────────────

    async def _payroll_rows(self, project_id: uuid.UUID, week: CertifiedPayrollWeek) -> list[dict[str, Any]]:
        """Read the payroll entries covering this week, with their deductions.

        Scoped by the week's ``batch_id`` when one was named, so a contractor
        running several batches over one period certifies the batch they mean.
        Otherwise every entry of the project whose ``work_date`` falls inside
        the week is taken, which is what somebody who never thought about
        batches expects.
        """
        try:
            days = week_days(week.week_ending)
        except ValueError:
            return []

        stmt = (
            select(PayrollEntry, PayrollBatch.currency)
            .join(PayrollBatch, PayrollEntry.batch_id == PayrollBatch.id)
            .where(PayrollBatch.project_id == project_id)
            .where(PayrollEntry.work_date.in_(days))
        )
        if week.batch_id is not None:
            stmt = stmt.where(PayrollEntry.batch_id == week.batch_id)
        result = await self.session.execute(stmt)
        pairs = list(result.all())
        if not pairs:
            return []

        entry_ids = [entry.id for entry, _ in pairs]
        deduction_stmt = select(PayrollDeduction).where(PayrollDeduction.entry_id.in_(entry_ids))
        deductions = list((await self.session.execute(deduction_stmt)).scalars().all())
        by_entry: dict[uuid.UUID, list[PayrollDeduction]] = {}
        for deduction in deductions:
            by_entry.setdefault(deduction.entry_id, []).append(deduction)

        rows: list[dict[str, Any]] = []
        for entry, batch_currency in pairs:
            rows.append(
                {
                    "resource_id": entry.resource_id,
                    "worker": entry.worker,
                    "work_date": entry.work_date,
                    "hours": _dec(entry.hours),
                    "rate": _dec(entry.rate),
                    "currency": entry.currency or batch_currency or "",
                    "deductions": [
                        {
                            "label": d.label,
                            "type": d.deduction_type,
                            "amount": d.amount,
                        }
                        for d in by_entry.get(entry.id, [])
                    ],
                }
            )
        return rows

    async def _classification_index(
        self,
        project_id: uuid.UUID,
    ) -> tuple[
        dict[str, WorkerClassificationAssignment],
        dict[uuid.UUID, WageClassification],
        dict[uuid.UUID, WageDetermination],
    ]:
        """Build the worker -> classification -> determination lookup in three queries.

        Keyed on the resource id when there is one and on the lower-cased worker
        name otherwise, which is the same key the payroll aggregation uses, so a
        free-text worker with no resource record can still be classified.
        """
        assignments = await self.assignment_repo.list_all_for_project(project_id)
        by_key: dict[str, WorkerClassificationAssignment] = {}
        for assignment in assignments:
            key = str(assignment.resource_id) if assignment.resource_id else assignment.worker_name.strip().lower()
            if key:
                by_key[key] = assignment

        classification_ids = list({a.classification_id for a in assignments})
        classifications = await self.classification_repo.list_by_ids(classification_ids)
        by_classification = {c.id: c for c in classifications}

        determination_ids = list({c.determination_id for c in classifications})
        determinations: dict[uuid.UUID, WageDetermination] = {}
        if determination_ids:
            stmt = select(WageDetermination).where(WageDetermination.id.in_(determination_ids))
            for determination in (await self.session.execute(stmt)).scalars().all():
                determinations[determination.id] = determination
        return by_key, by_classification, determinations

    async def derive_lines(self, week: CertifiedPayrollWeek) -> list[dict[str, Any]]:
        """Pivot the week's payroll entries into one line per worker.

        The pivot is where the daily rows become the weekly form: hours land in
        a per-day map keyed on ISO dates, and the straight/overtime split is
        applied against whichever thresholds the week recorded when it was
        opened.

        The paid rate is split into basic wage and fringe as follows, and the
        order matters because it decides what the compliance rules compare:

        1. Where the worker's assignment states a paid basic rate and a paid
           fringe rate, those are used. This is real data somebody entered and
           it is always preferred.
        2. Otherwise the split is derived from the payroll rate against the
           determination's basic rate: as much of the paid rate as the
           determination calls basic is treated as basic wage, and anything
           above it as fringe. Where the paid rate does not even reach the
           determination's basic rate, all of it is basic and the fringe is
           zero, which is what makes the underpayment visible instead of hiding
           it inside an invented fringe figure.

        The derivation is recorded on each line under ``rate_split_source`` so a
        reader can tell an entered figure from a derived one.
        """
        rows = await self._payroll_rows(week.project_id, week)
        if not rows:
            return []
        by_key, by_classification, determinations = await self._classification_index(week.project_id)

        meta = week.metadata_ or {}
        daily_threshold = meta.get("daily_overtime_threshold")
        weekly_threshold = meta.get("weekly_overtime_threshold")
        multiplier = meta.get("overtime_multiplier") or _DEFAULT_MULTIPLIER

        # Group the day rows per worker.
        buckets: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = str(row["resource_id"]) if row["resource_id"] else str(row["worker"] or "").strip().lower()
            bucket = buckets.get(key)
            if bucket is None:
                bucket = {
                    "resource_id": row["resource_id"],
                    "worker_name": row["worker"] or key,
                    "hours_by_day": {},
                    "rate": row["rate"],
                    "currency": row["currency"],
                    "deductions": [],
                }
                buckets[key] = bucket
            day = str(row["work_date"] or "")
            if day:
                bucket["hours_by_day"][day] = bucket["hours_by_day"].get(day, Decimal("0")) + row["hours"]
            if bucket["rate"] <= 0 < row["rate"]:
                bucket["rate"] = row["rate"]
            if not bucket["currency"] and row["currency"]:
                bucket["currency"] = row["currency"]
            bucket["deductions"].extend(row["deductions"])

        lines: list[dict[str, Any]] = []
        for ordinal, (key, bucket) in enumerate(sorted(buckets.items(), key=lambda item: str(item[1]["worker_name"]))):
            assignment = by_key.get(key)
            classification = by_classification.get(assignment.classification_id) if assignment else None
            determination = determinations.get(classification.determination_id) if classification else None

            per_day, straight, overtime = split_week_hours(
                bucket["hours_by_day"],
                daily_overtime_threshold=daily_threshold,
                weekly_overtime_threshold=weekly_threshold,
            )

            required_basic = _dec(classification.basic_hourly_rate) if classification else Decimal("0")
            required_fringe = _dec(classification.fringe_rate) if classification else Decimal("0")
            paid_basic, paid_fringe, split_source = self._resolve_paid_split(bucket["rate"], assignment, required_basic)

            pay = line_pay(
                straight,
                overtime,
                paid_basic,
                paid_fringe,
                overtime_multiplier=multiplier,
            )
            deducted = sum((_dec(d.get("amount")) for d in bucket["deductions"]), Decimal("0"))
            gross = _dec(pay["gross_amount"])
            net = gross - deducted
            if net < 0:
                net = Decimal("0")

            lines.append(
                {
                    "resource_id": bucket["resource_id"],
                    "worker_name": str(bucket["worker_name"]),
                    "worker_identifier": assignment.worker_identifier if assignment else "",
                    "classification_id": classification.id if classification else None,
                    "classification_code": classification.code if classification else "",
                    "classification_title": classification.title if classification else "",
                    "determination_id": determination.id if determination else None,
                    "determination_identifier": determination.identifier if determination else "",
                    "determination_authority": determination.authority if determination else "",
                    "determination_effective_date": determination.effective_date if determination else None,
                    "determination_expires_on": determination.expires_on if determination else None,
                    "hours_by_day": per_day,
                    "straight_hours": _plain(straight),
                    "overtime_hours": _plain(overtime),
                    "required_basic_rate": _plain(required_basic),
                    "required_fringe_rate": _plain(required_fringe),
                    "paid_basic_rate": _plain(paid_basic),
                    "paid_fringe_rate": _plain(paid_fringe),
                    "fringe_election": (assignment.fringe_election if assignment else None)
                    or week.fringe_election
                    or "",
                    "overtime_multiplier": pay["overtime_multiplier"],
                    "overtime_base_rate": pay["overtime_base_rate"],
                    "gross_amount": pay["gross_amount"],
                    "total_deductions": str(deducted),
                    "net_amount": str(net),
                    "deductions_detail": bucket["deductions"],
                    "currency": bucket["currency"] or week.currency or "",
                    "ordinal": ordinal,
                    "note": "",
                    "rate_split_source": split_source,
                }
            )
        return lines

    @staticmethod
    def _resolve_paid_split(
        paid_rate: Decimal,
        assignment: WorkerClassificationAssignment | None,
        required_basic: Decimal,
    ) -> tuple[Decimal, Decimal, str]:
        """Split the rate actually paid into basic wage and fringe.

        See :meth:`derive_lines` for the order of preference. Returns the two
        figures plus a short word naming where the split came from, so the line
        can say whether a human stated it or this method worked it out.
        """
        if assignment is not None and assignment.paid_basic_rate not in (None, ""):
            basic = _dec(assignment.paid_basic_rate)
            fringe = _dec(assignment.paid_fringe_rate)
            return basic, fringe, "assignment"
        if required_basic > 0 and paid_rate > required_basic:
            return required_basic, paid_rate - required_basic, "derived_against_determination"
        return paid_rate, Decimal("0"), "derived_all_basic"

    async def week_lines(self, week: CertifiedPayrollWeek) -> tuple[list[dict[str, Any]], bool]:
        """Return the week's lines and whether they were derived or read back.

        A certified week reads its frozen rows; a draft derives them. The second
        element of the tuple is what tells a caller which it got, because the
        two are the same shape by design and would otherwise be indistinguishable.
        """
        if week.status == "certified":
            return [self._frozen_line_to_dict(line) for line in sorted(week.lines, key=lambda ln: ln.ordinal)], False
        return await self.derive_lines(week), True

    @staticmethod
    def _frozen_line_to_dict(line: CertifiedPayrollLine) -> dict[str, Any]:
        """Read a frozen line back into the same shape the derivation produces."""
        return {
            "id": line.id,
            "week_id": line.week_id,
            "resource_id": line.resource_id,
            "worker_name": line.worker_name,
            "worker_identifier": line.worker_identifier,
            "classification_id": line.classification_id,
            "classification_code": line.classification_code,
            "classification_title": line.classification_title,
            "determination_id": line.determination_id,
            "determination_identifier": line.determination_identifier,
            "determination_authority": line.determination_authority,
            "hours_by_day": line.hours_by_day,
            "straight_hours": line.straight_hours,
            "overtime_hours": line.overtime_hours,
            "required_basic_rate": line.required_basic_rate,
            "required_fringe_rate": line.required_fringe_rate,
            "paid_basic_rate": line.paid_basic_rate,
            "paid_fringe_rate": line.paid_fringe_rate,
            "fringe_election": line.fringe_election,
            "overtime_multiplier": line.overtime_multiplier,
            "overtime_base_rate": line.overtime_base_rate,
            "gross_amount": line.gross_amount,
            "total_deductions": line.total_deductions,
            "net_amount": line.net_amount,
            "deductions_detail": line.deductions_detail,
            "currency": line.currency,
            "ordinal": line.ordinal,
            "note": line.note,
        }

    # ── Federal versus state ────────────────────────────────────────────────

    async def resolve_governing(
        self, week: CertifiedPayrollWeek, lines: list[dict[str, Any]]
    ) -> tuple[uuid.UUID | None, str]:
        """Decide which determination governs this week, and say why.

        Where a project holds determinations from more than one authority for
        the same craft, both obligations exist and neither discharges the other,
        so the higher total package governs. The choice and its reason are
        stored on the week rather than recomputed on read, because the record
        has to say which rate it used and on what ground.
        """
        determination_ids = {line["determination_id"] for line in lines if line.get("determination_id")}
        if not determination_ids:
            return None, "No wage determination is cited by any line on this payroll."

        stmt = select(WageDetermination).where(WageDetermination.id.in_(list(determination_ids)))
        determinations = {d.id: d for d in (await self.session.execute(stmt)).scalars().all()}

        candidates: list[dict[str, Any]] = []
        for line in lines:
            determination = determinations.get(line.get("determination_id"))
            if determination is None:
                continue
            candidates.append(
                {
                    "determination_id": determination.id,
                    "authority": determination.authority,
                    "determination_identifier": determination.identifier,
                    "classification_title": line.get("classification_title", ""),
                    "basic_hourly_rate": line.get("required_basic_rate", "0"),
                    "fringe_rate": line.get("required_fringe_rate", "0"),
                }
            )
        if len({c["authority"] for c in candidates}) <= 1:
            only = candidates[0] if candidates else None
            if only is None:
                return None, "No wage determination is cited by any line on this payroll."
            return only["determination_id"], (
                f"One regime covers this work: the {only['authority']} determination "
                f"{only['determination_identifier']}."
            )
        winner, reason = governing_classification(candidates)
        return (winner or {}).get("determination_id"), reason

    # ── Validation ──────────────────────────────────────────────────────────

    async def validate_week(self, week: CertifiedPayrollWeek) -> list[Any]:
        """Run the certified payroll rule set over a week and return the findings."""
        lines, _derived = await self.week_lines(week)
        payload = {
            "week": {
                "id": str(week.id),
                "week_ending": week.week_ending,
                "status": week.status,
                "signatory_name": week.signatory_name,
                "signatory_title": week.signatory_title,
                "signed_at": week.signed_at,
                "statement_text": week.statement_text,
                "fringe_election": week.fringe_election,
            },
            "lines": lines,
        }
        context = ValidationContext(
            data=payload,
            project_id=str(week.project_id),
            region="US",
            standard=CERTIFIED_PAYROLL_RULE_SET,
        )
        results: list[Any] = []
        for rule in rule_registry.get_rules_for_sets([CERTIFIED_PAYROLL_RULE_SET]):
            try:
                results.extend(await rule.validate(context))
            except Exception:  # pragma: no cover - a broken rule must not stop the rest
                logger.exception("Certified payroll rule %s failed on week %s", rule.rule_id, week.id)
        return results

    # ── Certification ───────────────────────────────────────────────────────

    async def certify_week(
        self,
        week_id: uuid.UUID,
        data: Any,
        *,
        user_id: str | None = None,
    ) -> CertifiedPayrollWeek:
        """Sign the statement of compliance and freeze the week.

        Refuses on any ERROR-severity finding. A certified payroll is a legal
        assertion, and signing one this module already knows to be wrong is the
        one thing it must not make easy. Warnings do not block: they are
        judgement calls the person signing is entitled to make.
        """
        week = await self.get_week(week_id)
        self._reject_if_certified(week)

        if data.fringe_election is not None:
            week.fringe_election = data.fringe_election
        if data.fringe_exception_note is not None:
            week.fringe_exception_note = data.fringe_exception_note

        findings = await self.validate_week(week)
        blocking = [f for f in findings if not f.passed and str(f.severity) == "error" and not f.is_engine_error]
        if blocking:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": (
                        f"The payroll for the week ending {week.week_ending} cannot be certified: "
                        f"{len(blocking)} compliance error(s) must be resolved first."
                    ),
                    "errors": [
                        {"rule_id": f.rule_id, "message": f.message, "suggestion": f.suggestion} for f in blocking
                    ],
                },
            )

        lines = await self.derive_lines(week)
        if not lines:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"No payroll was found for the week ending {week.week_ending}, so there is nothing to "
                    "certify. Generate the payroll batch covering this week first."
                ),
            )

        governing_id, reason = await self.resolve_governing(week, lines)
        days = week_days(week.week_ending)
        statement = data.statement_text.strip() or default_statement_of_compliance(
            signatory_name=data.signatory_name,
            signatory_title=data.signatory_title,
            contractor_name=week.contractor_name,
            project_name=week.project_name,
            week_start=days[0],
            week_ending=week.week_ending,
            fringe_election=week.fringe_election,
            exception_note=week.fringe_exception_note,
        )

        frozen = [
            CertifiedPayrollLine(
                week_id=week.id,
                resource_id=line["resource_id"],
                worker_name=line["worker_name"],
                worker_identifier=line["worker_identifier"],
                classification_id=line["classification_id"],
                classification_code=line["classification_code"],
                classification_title=line["classification_title"],
                determination_id=line["determination_id"],
                determination_identifier=line["determination_identifier"],
                determination_authority=line["determination_authority"],
                hours_by_day=line["hours_by_day"],
                straight_hours=line["straight_hours"],
                overtime_hours=line["overtime_hours"],
                required_basic_rate=line["required_basic_rate"],
                required_fringe_rate=line["required_fringe_rate"],
                paid_basic_rate=line["paid_basic_rate"],
                paid_fringe_rate=line["paid_fringe_rate"],
                fringe_election=line["fringe_election"] or week.fringe_election,
                overtime_multiplier=line["overtime_multiplier"],
                overtime_base_rate=line["overtime_base_rate"],
                gross_amount=line["gross_amount"],
                total_deductions=line["total_deductions"],
                net_amount=line["net_amount"],
                deductions_detail=line["deductions_detail"],
                currency=line["currency"],
                ordinal=line["ordinal"],
                note=line["note"],
            )
            for line in lines
        ]
        await self.week_repo.bulk_create_lines(frozen)

        # Lock every determination this payroll now rests on. From here the
        # figures behind a signature cannot be edited out from under it.
        cited = {line["determination_id"] for line in lines if line.get("determination_id")}
        for determination_id in cited:
            await self.determination_repo.update_fields(determination_id, locked=True)

        await self.week_repo.update_fields(
            week.id,
            status="certified",
            signatory_name=data.signatory_name,
            signatory_title=data.signatory_title,
            signed_at=datetime.now(UTC),
            signed_by=uuid.UUID(user_id) if user_id else None,
            statement_text=statement,
            governing_determination_id=governing_id,
            governing_reason=reason,
            fringe_election=week.fringe_election,
            fringe_exception_note=week.fringe_exception_note,
            currency=lines[0]["currency"] if lines else week.currency,
        )
        logger.info("Certified payroll week %s (%s) signed by %s", week.id, week.week_ending, data.signatory_name)
        return await self.get_week(week.id)

    # ── Export ──────────────────────────────────────────────────────────────

    async def render_week_form(self, week: CertifiedPayrollWeek) -> dict[str, Any]:
        """Render the week as the standard weekly payroll form payload."""
        lines, _derived = await self.week_lines(week)
        header = {
            "week_ending": week.week_ending,
            "payroll_number": week.payroll_number,
            "is_final": week.is_final,
            "contractor_name": week.contractor_name,
            "contractor_address": week.contractor_address,
            "is_subcontractor": week.is_subcontractor,
            "project_name": week.project_name,
            "project_location": week.project_location,
            "contract_number": week.contract_number,
            "covered_authorities": week.covered_authorities,
            "governing_reason": week.governing_reason,
            "currency": week.currency,
            "status": week.status,
            "statement_text": week.statement_text,
            "signatory_name": week.signatory_name,
            "signatory_title": week.signatory_title,
            "signed_at": week.signed_at,
            "fringe_election": week.fringe_election,
            "fringe_exception_note": week.fringe_exception_note,
        }
        return render_form(header, lines)
