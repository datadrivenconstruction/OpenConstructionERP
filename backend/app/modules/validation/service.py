# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation module business logic.

Orchestrates validation runs against BOQs, persists reports, and provides
access to available rule sets. This is the bridge between the core validation
engine (app.core.validation.engine) and the API/database layer.
"""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import (
    ValidationReport as EngineReport,
)
from app.core.validation.engine import (
    rule_registry,
    validation_engine,
)
from app.core.validation.project_context import with_project_context
from app.modules.validation import audit as estimate_audit
from app.modules.validation.models import ValidationReport
from app.modules.validation.repository import ValidationReportRepository

logger = logging.getLogger(__name__)


def _build_rule_sets(requested: list[str]) -> list[str]:
    """Expand logical rule-set names into the concrete sets the engine runs.

    Today this only rewrites the one-click ``estimate_audit`` rule set into the
    universal ``boq_quality`` checks it is built on (see
    :func:`app.modules.validation.audit.build_rule_sets`); every already-concrete
    rule-set name passes through unchanged. Centralised here so both the audit
    path and any future alias resolve rule sets the same way.
    """
    return estimate_audit.build_rule_sets(requested)


# ── Rule set descriptions ─────────────────────────────────────────────────

RULE_SET_DESCRIPTIONS: dict[str, str] = {
    "estimate_audit": (
        "One-click estimate audit: runs the finished BOQ through the universal "
        "quality checks (missing quantities, zero or anomalous rates, empty units, "
        "duplicate ordinals, empty sections), groups the findings and proposes a "
        "one-click fix for each."
    ),
    "boq_quality": (
        "Universal BOQ quality checks: missing quantities, zero prices, "
        "duplicate ordinals, unit rate anomalies, and more."
    ),
    "din276": (
        "DIN 276 compliance (DACH region): cost group hierarchy, valid Kostengruppe codes, completeness per level."
    ),
    "gaeb": ("GAEB compliance (DACH region): ordinal format, LV structure rules for German tender documents."),
    "nrm": ("NRM compliance (UK): New Rules of Measurement element codes, hierarchy validation, completeness checks."),
    "masterformat": ("MasterFormat compliance (US): division structure, code format validation, completeness checks."),
    "sinapi": "SINAPI compliance (Brazil): code format and validity.",
    "gesn": "GESN compliance (Russia/CIS): code format and validity.",
    "dpgf": "DPGF compliance (France): lot structure and pricing completeness.",
    "onorm": "ONORM compliance (Austria): position format and description rules.",
    "gbt50500": "GB/T 50500 compliance (China): code format and validity.",
    "cpwd": "CPWD compliance (India): code format and validity.",
    "sheet_completeness": (
        "Sheet completeness: reconciles the drawing index / issue register against the "
        "uploaded sheet set - flags missing sheets (error), extra sheets and revision "
        "mismatches (warning)."
    ),
    "project_completeness": (
        "Project completeness (universal): the project names its country and currency "
        "(errors), has a priced bill whose rows are in that currency, a base date on "
        "every bill, a classification standard, planned start and end dates in order, a "
        "recorded client, and, once past estimating, a contract or tender package."
    ),
}


class ValidationModuleService:
    """Service for running validation, managing reports, and querying rule sets."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ValidationReportRepository(session)

    # ── Run validation ────────────────────────────────────────────────────

    async def run_validation(
        self,
        project_id: uuid.UUID,
        boq_id: uuid.UUID,
        rule_sets: list[str],
        *,
        user_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Run validation rules against a BOQ and persist the report.

        1. Load BOQ positions from database.
        2. Convert to the dict format expected by validation rules.
        3. Run the validation engine with requested rule sets.
        4. Persist the report to oe_validation_report.
        5. Return the structured response.

        Args:
            project_id: Project owning the BOQ.
            boq_id: BOQ to validate.
            rule_sets: Which rule sets to apply (e.g. ["boq_quality", "din276"]).
            user_id: Optional user who triggered the validation.

        Returns:
            Dict with report_id, status, score, counts, results.

        Raises:
            ValueError: If the BOQ is not found or has no positions.
        """
        # 1. Load BOQ and positions (scoped to the authorized project)
        payload = await self._engine_payload(boq_id, project_id)
        if not payload.get("positions"):
            logger.warning("Validation: BOQ %s has no positions", boq_id)

        # 2. Run validation engine. Pass the request locale so rule messages
        #    and suggestions resolve in the user's language (the de/ru bundles
        #    are otherwise unreachable - rules default to "en" when no locale
        #    is in metadata).
        from app.core.i18n import get_locale

        engine_report: EngineReport = await validation_engine.validate(
            data=payload,
            rule_sets=rule_sets,
            target_type="boq",
            target_id=str(boq_id),
            project_id=str(project_id),
            metadata={"locale": get_locale()},
        )

        # 3. Build results list for storage
        results_json = [
            {
                "rule_id": r.rule_id,
                "rule_name": r.rule_name,
                "severity": r.severity.value if hasattr(r.severity, "value") else str(r.severity),
                "status": "pass" if r.passed else r.severity.value,
                "passed": r.passed,
                "message": r.message,
                "element_ref": r.element_ref,
                "details": r.details or {},
                "suggestion": r.suggestion,
                "is_engine_error": r.is_engine_error,
            }
            for r in engine_report.results
        ]

        # 4. Persist report
        db_report = ValidationReport(
            id=uuid.uuid4(),
            project_id=project_id,
            target_type="boq",
            target_id=str(boq_id),
            rule_set="+".join(rule_sets),
            status=engine_report.status.value,
            score=(None if engine_report.score is None else str(round(engine_report.score, 4))),
            total_rules=len(engine_report.results),
            passed_count=len(engine_report.passed_rules),
            warning_count=len(engine_report.warnings),
            error_count=len(engine_report.errors),
            results=results_json,
            created_by=user_id,
            metadata_={
                "duration_ms": engine_report.duration_ms,
                "rule_sets": rule_sets,
                "supported_rule_sets": engine_report.supported_rule_sets,
                "unsupported_rule_sets": engine_report.unsupported_rule_sets,
            },
        )
        await self.repo.create(db_report)

        # Publish a standardized event so the vector indexer (and any
        # future cross-module subscriber) can react.  Best-effort -
        # publish failures must never break a successful validation run.
        try:
            from app.core.events import event_bus

            event_bus.publish_detached(
                "validation.report.created",
                {
                    "report_id": str(db_report.id),
                    "project_id": str(project_id),
                    "target_type": "boq",
                    "target_id": str(boq_id),
                    "status": engine_report.status.value,
                },
                source_module="oe_validation",
            )
        except Exception:
            logger.debug("Failed to publish validation.report.created event", exc_info=True)

        # When the run produced ERROR-severity results, escalate. A blocking
        # validation error is a formal non-conformance, so the NCR module raises
        # (idempotently, per report) an NCR from this event. Kept in its own
        # try so a failure here is visible and never hidden under the
        # report.created handler above. We carry a compact, capped error list so
        # the subscriber needs no DB read.
        try:
            from app.core.events import publish_after_commit

            if engine_report.errors:
                error_digest = [
                    {
                        "rule_id": r.rule_id,
                        "rule_name": r.rule_name,
                        "message": r.message,
                        "element_ref": r.element_ref,
                    }
                    for r in engine_report.errors[:50]
                ]
                # Deferred to the commit: the NCR bridge inserts
                # NCR(project_id=...) from its own session, and a seeder that
                # validates a project it has not committed yet would hand that
                # insert an invisible parent. See publish_after_commit.
                publish_after_commit(
                    self.session,
                    "validation.results.errors_found",
                    {
                        "report_id": str(db_report.id),
                        "project_id": str(project_id),
                        "target_type": "boq",
                        "target_id": str(boq_id),
                        "rule_set": "+".join(rule_sets),
                        "error_count": len(engine_report.errors),
                        "errors": error_digest,
                    },
                    source_module="oe_validation",
                )
        except Exception:
            logger.warning("Failed to publish validation.results.errors_found event", exc_info=True)

        # 5. Build response
        return {
            "report_id": str(db_report.id),
            "status": engine_report.status.value,
            "score": engine_report.score,
            "total_rules": len(engine_report.results),
            "passed_count": len(engine_report.passed_rules),
            "warning_count": len(engine_report.warnings),
            "error_count": len(engine_report.errors),
            "info_count": len(engine_report.infos),
            "rule_sets": rule_sets,
            "supported_rule_sets": engine_report.supported_rule_sets,
            "unsupported_rule_sets": engine_report.unsupported_rule_sets,
            "duration_ms": engine_report.duration_ms,
            "results": [
                {
                    "rule_id": r.rule_id,
                    "rule_name": r.rule_name,
                    "severity": (r.severity.value if hasattr(r.severity, "value") else str(r.severity)),
                    "status": "pass" if r.passed else r.severity.value,
                    "passed": r.passed,
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "details": r.details or {},
                    "suggestion": r.suggestion,
                    "is_engine_error": r.is_engine_error,
                }
                for r in engine_report.results
            ],
            "engine_error_count": len(engine_report.engine_errors),
        }

    # ── Sheet completeness (drawing index reconciliation) ─────────────────

    async def run_sheet_completeness(
        self,
        project_id: uuid.UUID,
        *,
        target_id: str,
        expected: list[dict[str, Any]],
        actual: list[dict[str, Any]],
        source_meta: dict[str, Any],
        user_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Run the ``sheet_completeness`` rule set and persist a document report.

        Generic (non-BOQ) validation path. The caller (documents.SheetService)
        has already parsed the drawing index into ``expected`` and loaded the
        actual ``Sheet`` rows into ``actual``; this runs the rule set over them,
        persists a :class:`ValidationReport` with ``target_type='document'`` and
        the reconciliation snapshot in ``metadata.sheet_completeness``, and
        returns the same summary shape as the BOQ path plus a ``completeness``
        block. Keeping parsing in documents and persistence here mirrors how the
        BOQ path splits position loading from :meth:`run_validation`.

        Args:
            project_id: Project owning the sheets (authorisation scope).
            target_id: 36-char UUID string - the index document id, or the
                project id for pasted-list mode (fits ``target_id String(36)``).
            expected: Parsed expected sheets (``ExpectedSheet.__dict__`` shape).
            actual: Actual ``Sheet`` rows as dicts (sheet_number/revision/...).
            source_meta: Reconciliation snapshot stored under
                ``metadata.sheet_completeness`` and echoed back as
                ``completeness``.
            user_id: Optional user who triggered the run.
        """
        from app.core.i18n import get_locale

        engine_report: EngineReport = await validation_engine.validate(
            data={"expected": expected, "actual": actual},
            rule_sets=["sheet_completeness"],
            target_type="document",
            target_id=target_id,
            project_id=str(project_id),
            metadata={"locale": get_locale()},
        )

        results_json = [
            {
                "rule_id": r.rule_id,
                "rule_name": r.rule_name,
                "severity": r.severity.value if hasattr(r.severity, "value") else str(r.severity),
                "status": "pass" if r.passed else r.severity.value,
                "passed": r.passed,
                "message": r.message,
                "element_ref": r.element_ref,
                "details": r.details or {},
                "suggestion": r.suggestion,
                "is_engine_error": r.is_engine_error,
            }
            for r in engine_report.results
        ]

        db_report = ValidationReport(
            id=uuid.uuid4(),
            project_id=project_id,
            target_type="document",
            target_id=target_id,
            rule_set="sheet_completeness",
            status=engine_report.status.value,
            score=(None if engine_report.score is None else str(round(engine_report.score, 4))),
            total_rules=len(engine_report.results),
            passed_count=len(engine_report.passed_rules),
            warning_count=len(engine_report.warnings),
            error_count=len(engine_report.errors),
            results=results_json,
            created_by=user_id,
            metadata_={
                "duration_ms": engine_report.duration_ms,
                "rule_sets": ["sheet_completeness"],
                "supported_rule_sets": engine_report.supported_rule_sets,
                "unsupported_rule_sets": engine_report.unsupported_rule_sets,
                "sheet_completeness": source_meta,
            },
        )
        await self.repo.create(db_report)

        # Best-effort event so the vector indexer (and any future cross-module
        # subscriber) can react. Only ``validation.report.created`` is emitted -
        # never ``validation.results.errors_found`` - so a missing-sheet ERROR
        # does not fan out into the NCR / escalation surface; sheet completeness
        # is a document reconciliation, not a BOQ non-conformance. A publish
        # failure must never break a successful run.
        try:
            from app.core.events import event_bus

            event_bus.publish_detached(
                "validation.report.created",
                {
                    "report_id": str(db_report.id),
                    "project_id": str(project_id),
                    "target_type": "document",
                    "target_id": target_id,
                    "status": engine_report.status.value,
                },
                source_module="oe_validation",
            )
        except Exception:
            logger.debug("Failed to publish validation.report.created event", exc_info=True)

        return {
            "report_id": str(db_report.id),
            "status": engine_report.status.value,
            "score": engine_report.score,
            "total_rules": len(engine_report.results),
            "passed_count": len(engine_report.passed_rules),
            "warning_count": len(engine_report.warnings),
            "error_count": len(engine_report.errors),
            "info_count": len(engine_report.infos),
            "rule_sets": ["sheet_completeness"],
            "supported_rule_sets": engine_report.supported_rule_sets,
            "unsupported_rule_sets": engine_report.unsupported_rule_sets,
            "duration_ms": engine_report.duration_ms,
            "results": results_json,
            "completeness": source_meta,
        }

    # ── Estimate audit (one-click) ────────────────────────────────────────

    async def run_estimate_audit(
        self,
        project_id: uuid.UUID,
        boq_id: uuid.UUID,
        *,
        user_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Run the one-click estimate audit over a finished BOQ.

        Runs the ``boq_quality`` rule set (resolved from the logical
        ``estimate_audit`` set), groups the failing results into actionable
        findings with concrete one-click fixes, persists a
        :class:`ValidationReport` carrying those findings, and writes each
        finding back onto ``Position.validation_status`` (plus a compact
        ``metadata.audit`` summary) so the estimate grid accents match the
        latest report.

        Args:
            project_id: Project owning the BOQ (authorisation scope).
            boq_id: BOQ to audit.
            user_id: Optional user who triggered the audit.

        Returns:
            Dict with report_id, status, score, counts, grouped findings and
            per-finding fixes.

        Raises:
            ValueError: If the BOQ is not found or belongs to another project.
        """
        from datetime import UTC, datetime

        from app.core.i18n import get_locale

        payload = await self._engine_payload(boq_id, project_id)
        rule_sets = _build_rule_sets([estimate_audit.ESTIMATE_AUDIT_RULE_SET])

        engine_report: EngineReport = await validation_engine.validate(
            data=payload,
            rule_sets=rule_sets,
            target_type="boq",
            target_id=str(boq_id),
            project_id=str(project_id),
            metadata={"locale": get_locale()},
        )

        results_json = [
            {
                "rule_id": r.rule_id,
                "rule_name": r.rule_name,
                "severity": r.severity.value if hasattr(r.severity, "value") else str(r.severity),
                "status": "pass" if r.passed else r.severity.value,
                "passed": r.passed,
                "message": r.message,
                "element_ref": r.element_ref,
                "details": r.details or {},
                "suggestion": r.suggestion,
                "is_engine_error": r.is_engine_error,
            }
            for r in engine_report.results
        ]

        # Group failing results into actionable findings + fixes (pure).
        findings = estimate_audit.build_findings(results_json, payload["positions"])
        groups = estimate_audit.summarize_groups(findings)
        status_map = estimate_audit.build_status_map(results_json)
        finding_meta = estimate_audit.build_position_audit_meta(findings)

        # Persist the report with the ``estimate_audit`` label and the grouped
        # findings in metadata, so a re-open restores the exact panel and the
        # score-delta baseline.
        db_report = ValidationReport(
            id=uuid.uuid4(),
            project_id=project_id,
            target_type="boq",
            target_id=str(boq_id),
            rule_set=estimate_audit.ESTIMATE_AUDIT_RULE_SET,
            status=engine_report.status.value,
            score=(None if engine_report.score is None else str(round(engine_report.score, 4))),
            total_rules=len(engine_report.results),
            passed_count=len(engine_report.passed_rules),
            warning_count=len(engine_report.warnings),
            error_count=len(engine_report.errors),
            results=results_json,
            created_by=user_id,
            metadata_={
                "duration_ms": engine_report.duration_ms,
                "rule_sets": rule_sets,
                "audit": True,
                "findings": findings,
                "groups": groups,
            },
        )
        await self.repo.create(db_report)

        # Write the findings back onto the positions so the BOQ grid accents
        # (and the dashboard error/warning counts) match this report.
        await self._write_back_position_audit(
            boq_id,
            status_map=status_map,
            finding_meta=finding_meta,
            report_id=db_report.id,
            checked_at=datetime.now(UTC).isoformat(),
        )

        # Best-effort event so the vector indexer / cross-module subscribers
        # can react. A publish failure must never fail a successful audit.
        try:
            from app.core.events import event_bus

            event_bus.publish_detached(
                "validation.report.created",
                {
                    "report_id": str(db_report.id),
                    "project_id": str(project_id),
                    "target_type": "boq",
                    "target_id": str(boq_id),
                    "status": engine_report.status.value,
                },
                source_module="oe_validation",
            )
        except Exception:
            logger.debug("Failed to publish validation.report.created event", exc_info=True)

        return {
            "report_id": str(db_report.id),
            "boq_id": str(boq_id),
            "status": engine_report.status.value,
            "score": engine_report.score,
            "total_rules": len(engine_report.results),
            "passed_count": len(engine_report.passed_rules),
            "warning_count": len(engine_report.warnings),
            "error_count": len(engine_report.errors),
            "info_count": len(engine_report.infos),
            "rule_sets": rule_sets,
            "duration_ms": engine_report.duration_ms,
            "findings": findings,
            "groups": groups,
        }

    async def _write_back_position_audit(
        self,
        boq_id: uuid.UUID,
        *,
        status_map: dict[str, str],
        finding_meta: dict[str, dict[str, Any]],
        report_id: uuid.UUID,
        checked_at: str,
    ) -> None:
        """Persist audit results onto each checked BOQ position.

        For every position the audit checked, set ``validation_status`` to the
        rolled-up status and stamp a compact ``metadata.audit`` summary
        (findings groups + count) so the grid can render richer per-row
        markers. Positions that are now clean have any stale ``metadata.audit``
        cleared. A new dict is assigned to ``metadata_`` so the JSON column
        change is detected by SQLAlchemy (in-place mutation is not tracked).

        Positions the audit never checked are left untouched.
        """
        from app.modules.boq.models import Position

        rows = (await self.session.execute(select(Position).where(Position.boq_id == boq_id))).scalars().all()

        for pos in rows:
            pid = str(pos.id)
            new_status = status_map.get(pid)
            if new_status is None:
                # Not part of this audit's checked set - leave as-is.
                continue
            pos.validation_status = new_status

            existing_meta = dict(pos.metadata_ or {})
            meta = finding_meta.get(pid)
            if meta:
                existing_meta["audit"] = {
                    "status": new_status,
                    "groups": meta["groups"],
                    "count": meta["count"],
                    "report_id": str(report_id),
                    "checked_at": checked_at,
                }
            else:
                existing_meta.pop("audit", None)
            pos.metadata_ = existing_meta

        await self.session.flush()

    # ── Rule sets ─────────────────────────────────────────────────────────

    def get_available_rule_sets(self) -> list[dict[str, Any]]:
        """Return all available rule sets with descriptions and rule counts.

        Returns:
            List of dicts with name, description, rule_count, and rules.
        """
        registered = rule_registry.list_rule_sets()
        result: list[dict[str, Any]] = []
        for name, count in sorted(registered.items()):
            result.append(
                {
                    "name": name,
                    "description": RULE_SET_DESCRIPTIONS.get(name, f"{name} validation rules"),
                    "rule_count": count,
                    # Only rule sets that resolve to at least one registered
                    # rule reach this list, so ``implemented`` is always true
                    # here. The flag is explicit so callers never have to infer
                    # "ran for real" from a non-zero count, and so a future
                    # rule set that is described but unimplemented can be marked
                    # honestly rather than advertised as working.
                    "implemented": count > 0,
                    "rules": rule_registry.list_rules(rule_set=name),
                }
            )
        return result

    # ── CRUD for reports ──────────────────────────────────────────────────

    async def list_reports(
        self,
        project_id: uuid.UUID,
        *,
        target_type: str | None = None,
        limit: int = 50,
    ) -> list[ValidationReport]:
        """List validation reports for a project."""
        return await self.repo.list_for_project(project_id, target_type=target_type, limit=limit)

    async def get_report(self, report_id: uuid.UUID) -> ValidationReport | None:
        """Get a single validation report by ID."""
        return await self.repo.get(report_id)

    async def delete_report(self, report_id: uuid.UUID) -> bool:
        """Delete a validation report. Returns True if deleted."""
        deleted = await self.repo.delete(report_id)
        if deleted:
            try:
                from app.core.events import event_bus

                event_bus.publish_detached(
                    "validation.report.deleted",
                    {"report_id": str(report_id)},
                    source_module="oe_validation",
                )
            except Exception:
                logger.debug(
                    "Failed to publish validation.report.deleted event",
                    exc_info=True,
                )
        return deleted

    # ── Internal helpers ──────────────────────────────────────────────────

    async def _load_boq_positions(self, boq_id: uuid.UUID, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """Load BOQ positions and convert to validation-compatible dict format.

        Each position dict contains:
            id, ordinal, description, unit, quantity, unit_rate, total,
            classification, source, parent_id, type (section vs position).
        """
        from app.modules.boq.models import BOQ, Position

        boq = await self.session.get(BOQ, boq_id)
        if boq is None:
            msg = f"BOQ {boq_id} not found"
            raise ValueError(msg)

        # Enforce that the BOQ belongs to the project this validation run is
        # scoped to. Without this a caller authorized on project A could
        # validate (and read the positions of) any BOQ id from project B by
        # passing a foreign boq_id - a cross-project IDOR. Raise the same
        # "not found" message so a mismatch leaks nothing about the foreign BOQ
        # (the router maps ValueError to 404).
        if boq.project_id != project_id:
            msg = f"BOQ {boq_id} not found"
            raise ValueError(msg)

        # Load positions with an explicit awaited query rather than the lazy
        # ``boq.positions`` relationship. Under AsyncSession, touching a lazy
        # collection that is not already populated (e.g. positions inserted by
        # FK during demo seeding, before the relationship is loaded) raises
        # MissingGreenlet. An explicit select is safe in every caller context.
        pos_rows = (await self.session.execute(select(Position).where(Position.boq_id == boq_id))).scalars().all()

        # The CurrencyConsistency rule reads each position's currency. The
        # per-position currency is authoritative in metadata (mirrors
        # boq.service._position_currency); fall back to the BOQ currency so a
        # position without an explicit code inherits the BOQ's. The loader used
        # to drop currency entirely, which left the rule reading "" for every
        # row and silently passing on every BOQ.
        boq_currency = (getattr(boq, "currency", "") or "").strip().upper()

        positions_data: list[dict[str, Any]] = []
        for pos in pos_rows:
            pmeta = pos.metadata_ or {}
            pos_currency = ""
            for ck in ("currency", "position_currency", "project_currency"):
                cv = pmeta.get(ck)
                if isinstance(cv, str) and cv.strip():
                    pos_currency = cv.strip().upper()
                    break
            positions_data.append(
                {
                    "id": str(pos.id),
                    "ordinal": pos.ordinal,
                    "description": pos.description,
                    "unit": pos.unit,
                    "quantity": pos.quantity,
                    "unit_rate": pos.unit_rate,
                    "total": pos.total,
                    "classification": pos.classification or {},
                    "source": pos.source,
                    "parent_id": str(pos.parent_id) if pos.parent_id else None,
                    "currency": pos_currency or boq_currency,
                    "type": pmeta.get("type", "position"),
                    # The whole blob, not just the keys this loader happens to
                    # read. Eleven rule sites call ``_position_metadata`` for
                    # things an importer left here - the GAEB Bedarfsposition
                    # marker, the Hungarian two-price split, the GESN resource
                    # decomposition - and every one of them was reading an
                    # empty dict on this path, so the rule either skipped the
                    # position or reported the data missing. Both readings were
                    # about the loader and neither was about the bill.
                    "metadata": pmeta,
                }
            )
        return positions_data

    async def _load_boq_header(self, boq_id: uuid.UUID, project_id: uuid.UUID) -> dict[str, Any]:
        """Load the bill's own fields, the ones that describe the document.

        Separate from the positions because a document-level rule asks a
        different question: not "is this line measured correctly" but "does
        this estimate say what it is". A cost plan's base date, the standard
        it was measured to and the contract it is priced against live on the
        bill, not on any line of it.
        """
        from app.modules.boq.models import BOQ

        boq = await self.session.get(BOQ, boq_id)
        if boq is None or boq.project_id != project_id:
            # Same message and same shape as the positions loader: a mismatch
            # must not tell the caller whether the foreign bill exists.
            msg = f"BOQ {boq_id} not found"
            raise ValueError(msg)
        return {
            "id": str(boq.id),
            "name": boq.name,
            "description": boq.description,
            "status": boq.status,
            "estimate_type": boq.estimate_type,
            "base_date": boq.base_date,
            "currency": (getattr(boq, "currency", "") or "").strip().upper(),
            "metadata": boq.metadata_ or {},
        }

    async def _load_boq_markups(self, boq_id: uuid.UUID) -> list[dict[str, Any]]:
        """Load the bill's markup stack.

        Private, and called only after :meth:`_load_boq_header` has checked
        that the bill belongs to the project this run is scoped to. Markups
        are addressed by bill id alone, so calling this without that check
        would read another project's margin structure.

        Inactive lines are carried rather than filtered. A rule asking whether
        an estimate prices its preliminaries must be able to tell a line that
        was switched off from one that was never there, and the two are the
        same fact once the filtering has happened here.
        """
        from app.modules.boq.models import BOQMarkup

        rows = (await self.session.execute(select(BOQMarkup).where(BOQMarkup.boq_id == boq_id))).scalars().all()
        return [
            {
                "id": str(markup.id),
                "name": markup.name,
                "markup_type": markup.markup_type,
                "category": markup.category,
                "percentage": markup.percentage,
                "fixed_amount": markup.fixed_amount,
                "apply_to": markup.apply_to,
                "sort_order": markup.sort_order,
                "is_active": markup.is_active,
                "scope_position_id": (str(markup.scope_position_id) if markup.scope_position_id else None),
            }
            for markup in rows
        ]

    async def _engine_payload(self, boq_id: uuid.UUID, project_id: uuid.UUID) -> dict[str, Any]:
        """The mapping the validation engine reads for one bill.

        Every BOQ validation path goes through this one builder. A rule reads
        its inputs from this mapping, and a rule whose input is absent returns
        nothing at all rather than failing, so a path that assembles the
        payload by hand drops rules silently instead of erroring.
        """
        positions = await self._load_boq_positions(boq_id, project_id)
        header = await self._load_boq_header(boq_id, project_id)
        markups = await self._load_boq_markups(boq_id)
        return await with_project_context(
            self.session,
            project_id,
            {"boq": header, "positions": positions, "markups": markups},
        )
