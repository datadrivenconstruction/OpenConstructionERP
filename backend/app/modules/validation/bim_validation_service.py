"""‌⁠‍Per-element BIM validation service.

Runs :class:`BIMElementRule` instances against every ``BIMElement`` in a
model and writes the resulting per-element outcomes into a
:class:`ValidationReport` row (``target_type='bim_model'``).

The service is deliberately separate from
:class:`ValidationModuleService` because BIM element validation operates
on ORM rows (not the flat positions dict consumed by the core
``validation_engine``) and stores results with a different shape - each
result entry carries an ``element_id`` so the BIM element UI can paint
traffic-light badges.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import SEVERITY_WEIGHTS, compute_quality_score
from app.modules.bim_hub.repository import BIMElementRepository, BIMModelRepository
from app.modules.validation.models import ValidationReport
from app.modules.validation.repository import ValidationReportRepository
from app.modules.validation.rules.bim_element_rule import (
    BIMElementRule,
    BIMElementRuleResult,
)
from app.modules.validation.rules.bim_universal import get_rules_by_ids

logger = logging.getLogger(__name__)


# Hard cap on how many result rows we persist. Large models (100k elements
# × 8 rules) could produce ~800k failures - JSON-column size, load times,
# and UI legibility all collapse well before that. When the cap is hit we
# truncate and append a single synthetic ``_truncated`` entry so the
# caller can show a "… N more" indicator.
MAX_RESULTS_PER_REPORT = 5000


class BIMValidationService:
    """‌⁠‍Run :class:`BIMElementRule` instances against BIM models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.model_repo = BIMModelRepository(session)
        self.element_repo = BIMElementRepository(session)
        self.report_repo = ValidationReportRepository(session)

    # ── Public API ──────────────────────────────────────────────────────

    async def validate_bim_model(
        self,
        model_id: uuid.UUID,
        rule_ids: list[str] | None = None,
        *,
        user_id: str | None = None,
    ) -> ValidationReport:
        """‌⁠‍Run BIM element rules against every element in a model.

        Args:
            model_id: Target BIM model UUID.
            rule_ids: Optional subset of rule ids to run. ``None`` / empty
                runs the full enabled universal rule set.
            user_id: Optional UUID string of the user triggering the run;
                stored on the resulting report.

        Returns:
            The newly persisted :class:`ValidationReport` row.

        Raises:
            ValueError: If the referenced BIM model does not exist.
        """
        started = time.monotonic()

        # 1. Load model + all elements
        model = await self.model_repo.get(model_id)
        if model is None:
            msg = f"BIM model {model_id} not found"
            raise ValueError(msg)

        elements, total = await self.element_repo.list_for_model(model_id, offset=0, limit=1_000_000)

        # 2. Resolve active rules
        rules: list[BIMElementRule] = get_rules_by_ids(rule_ids)
        if not rules:
            logger.warning(
                "BIM validation: no rules matched rule_ids=%s for model %s",
                rule_ids,
                model_id,
            )

        # 3. Run each rule against every in-scope element
        #
        # Counting semantics (kept internally consistent, see step 5):
        #   total_checks    -> number of (rule, element) checks executed.
        #   passed_count    -> checks that produced zero failures.
        #   failed_checks   -> checks that produced at least one failure.
        #   error/warning/info_count -> number of FAILURES by severity. A
        #     single failing check can emit several failures, so these can
        #     sum to more than failed_checks. The invariant we persist is
        #     passed_count + failed_checks == total_checks (== total_rules).
        passed_count = 0
        failed_checks = 0
        warning_count = 0
        error_count = 0
        info_count = 0
        total_checks = 0
        # Severity-weighted accumulators so the BIM-model score uses the
        # SAME formula as the core BOQ ValidationReport.score - otherwise the
        # two "quality scores" are not comparable in the unified dashboard
        # (E-XMOD-015). A passing (rule, element) pair contributes the rule's
        # severity weight to both numerator and denominator (mirrors the core
        # engine, where a passing ERROR-rule result carries ERROR weight); a
        # failed check contributes the rule weight to the denominator exactly
        # once, even when the check emits several sub-failures, so the
        # denominator scales with the check count, not the failure count.
        passed_weight = 0.0
        total_weight = 0.0
        results_json: list[dict[str, Any]] = []
        truncated = False

        for rule in rules:
            rule_weight = SEVERITY_WEIGHTS.get(str(rule.severity), 1.0)
            for elem in elements:
                if not rule.matches(elem):
                    continue
                total_checks += 1
                failures: list[BIMElementRuleResult] = rule.evaluate(elem)
                if not failures:
                    passed_count += 1
                    passed_weight += rule_weight
                    total_weight += rule_weight
                    continue

                failed_checks += 1
                # One weight per check, like the core engine: a failed
                # (rule, element) check contributes the rule weight to the
                # denominator exactly once, regardless of how many sub-failures
                # it emits. Per-severity counts still iterate every failure.
                total_weight += rule_weight
                for failure in failures:
                    if failure.severity == "error":
                        error_count += 1
                    elif failure.severity == "warning":
                        warning_count += 1
                    else:
                        info_count += 1

                    if len(results_json) >= MAX_RESULTS_PER_REPORT:
                        truncated = True
                        continue

                    results_json.append(
                        {
                            "rule_id": failure.rule_id,
                            "rule_name": failure.rule_name,
                            "severity": failure.severity,
                            "status": failure.severity,
                            "passed": False,
                            "message": failure.message,
                            "element_id": failure.element_id,
                            "element_name": failure.element_name,
                            "element_type": failure.element_type,
                            "element_ref": failure.element_id,
                            "details": failure.details,
                        }
                    )

        if truncated:
            results_json.append(
                {
                    "rule_id": "_truncated",
                    "rule_name": "Results truncated",
                    "severity": "info",
                    "status": "warning",
                    "passed": False,
                    "message": (
                        f"Result list truncated at {MAX_RESULTS_PER_REPORT} entries. "
                        f"The model produced more failures than can be stored in a "
                        f"single report - narrow the rule_ids filter to see the rest."
                    ),
                    "element_id": None,
                    "element_name": None,
                    "element_type": None,
                    "element_ref": None,
                    "details": {"cap": MAX_RESULTS_PER_REPORT},
                }
            )

        # 4. Derive overall status + score
        #
        # info findings used to be swallowed: a model with only info-level
        # failures was reported as a clean "passed". They are real unresolved
        # findings, so surface them with an "info" status rather than hiding
        # them. errors/warnings still take precedence.
        if error_count > 0:
            status_value = "errors"
        elif warning_count > 0:
            status_value = "warnings"
        elif info_count > 0:
            status_value = "info"
        else:
            status_value = "passed"

        # Same severity-weighted definition + blocking-error cap as the core
        # ValidationReport.score (E-XMOD-015). Replaces the old raw
        # passed_count / total_checks ratio which ignored severity entirely.
        if total_checks == 0:
            score = 1.0
        else:
            score = compute_quality_score(passed_weight, total_weight, error_count)

        duration_ms = round((time.monotonic() - started) * 1000, 2)
        logger.info(
            "BIM validation done: model=%s elements=%d rules=%d checks=%d passed=%d failed=%d warn=%d err=%d info=%d duration=%.1fms",
            model_id,
            total,
            len(rules),
            total_checks,
            passed_count,
            failed_checks,
            warning_count,
            error_count,
            info_count,
            duration_ms,
        )

        # 5. Persist report
        user_uuid: uuid.UUID | None = None
        if user_id:
            try:
                user_uuid = uuid.UUID(str(user_id))
            except (ValueError, TypeError):
                user_uuid = None

        db_report = ValidationReport(
            id=uuid.uuid4(),
            project_id=model.project_id,
            target_type="bim_model",
            target_id=str(model_id),
            rule_set="bim_universal",
            status=status_value,
            score=str(round(score, 4)),
            total_rules=total_checks,
            passed_count=passed_count,
            warning_count=warning_count,
            error_count=error_count,
            results=results_json,
            created_by=user_uuid,
            metadata_={
                "duration_ms": duration_ms,
                "model_id": str(model_id),
                "model_name": model.name,
                "element_count": total,
                "rule_ids": [r.rule_id for r in rules],
                "truncated": truncated,
                "info_count": info_count,
                # total_rules counts checks; passed_count + failed_check_count
                # == total_rules. The severity *_count fields above count
                # failures, which can exceed failed_check_count when one check
                # emits several failures.
                "failed_check_count": failed_checks,
            },
        )
        await self.report_repo.create(db_report)
        return db_report
