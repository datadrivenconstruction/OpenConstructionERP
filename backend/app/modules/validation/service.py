"""Validation module business logic.

Orchestrates validation runs against BOQs, persists reports, and provides
access to available rule sets. This is the bridge between the core validation
engine (app.core.validation.engine) and the API/database layer.
"""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import (
    ValidationReport as EngineReport,
)
from app.core.validation.engine import (
    rule_registry,
    validation_engine,
)
from app.modules.validation.models import ValidationReport
from app.modules.validation.repository import ValidationReportRepository

logger = logging.getLogger(__name__)

# ── Rule set descriptions ─────────────────────────────────────────────────

RULE_SET_DESCRIPTIONS: dict[str, str] = {
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
        # 1. Load BOQ and positions
        positions_data = await self._load_boq_positions(boq_id)
        if not positions_data:
            logger.warning("Validation: BOQ %s has no positions", boq_id)

        # 2. Run validation engine
        engine_report: EngineReport = await validation_engine.validate(
            data={"positions": positions_data},
            rule_sets=rule_sets,
            target_type="boq",
            target_id=str(boq_id),
            project_id=str(project_id),
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
            score=str(round(engine_report.score, 4)),
            total_rules=len(engine_report.results),
            passed_count=len(engine_report.passed_rules),
            warning_count=len(engine_report.warnings),
            error_count=len(engine_report.errors),
            results=results_json,
            created_by=user_id,
            metadata_={
                "duration_ms": engine_report.duration_ms,
                "rule_sets": rule_sets,
            },
        )
        await self.repo.create(db_report)

        # Publish a standardized event so the vector indexer (and any
        # future cross-module subscriber) can react.  Best-effort —
        # publish failures must never break a successful validation run.
        try:
            from app.core.events import event_bus

            await event_bus.publish(
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
                }
                for r in engine_report.results
            ],
        }

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

                await event_bus.publish(
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

    async def _load_boq_positions(self, boq_id: uuid.UUID) -> list[dict[str, Any]]:
        """Load BOQ positions and convert to validation-compatible dict format.

        Each position dict contains:
            id, ordinal, description, unit, quantity, unit_rate, total,
            classification, source, parent_id, type (section vs position).
        """
        from app.modules.boq.models import BOQ

        boq = await self.session.get(BOQ, boq_id)
        if boq is None:
            msg = f"BOQ {boq_id} not found"
            raise ValueError(msg)

        positions_data: list[dict[str, Any]] = []
        for pos in boq.positions:
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
                    "type": (pos.metadata_ or {}).get("type", "position"),
                }
            )
        return positions_data
