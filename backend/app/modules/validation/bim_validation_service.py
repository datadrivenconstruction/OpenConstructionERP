# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Per-element BIM validation service.

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
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import (
    SEVERITY_WEIGHTS,
    compute_quality_score,
    rule_registry,
    validation_engine,
)
from app.modules.bim_hub.repository import BIMElementRepository, BIMModelRepository
from app.modules.validation.models import ValidationReport
from app.modules.validation.repository import ValidationReportRepository
from app.modules.validation.rules.bim_element_rule import (
    BIMElementRule,
    BIMElementRuleResult,
)
from app.modules.validation.rules.bim_model_rule import (
    BIMModelContext,
    get_model_rules_by_ids,
)
from app.modules.validation.rules.bim_universal import get_rules_by_ids

logger = logging.getLogger(__name__)


# Hard cap on how many result rows we persist. Large models (100k elements
# × 8 rules) could produce ~800k failures - JSON-column size, load times,
# and UI legibility all collapse well before that. When the cap is hit we
# truncate and append a single synthetic ``_truncated`` entry so the
# caller can show a "… N more" indicator.
MAX_RESULTS_PER_REPORT = 5000

# Default rule-set name an IDS import registers its project-scoped specs
# under (see validation.router.import_ids). The actual key is namespaced per
# project as ``{IDS_RULE_SET_PREFIX}:{project_id}`` so one tenant's imported
# specs are never resolvable by another.
IDS_RULE_SET_PREFIX = "ids_custom"


def _element_to_canonical(elem: Any) -> dict[str, Any]:
    """Project a ``BIMElement`` ORM row onto the canonical-format dict that
    :class:`IDSValidationRule` expects.

    The IDS rule reads ``elements`` (canonical BIM shape), matching on
    ``ifc_class`` / ``category`` / ``predefined_type`` / ``classification``
    and pulling values from ``properties`` / ``attributes``. The ORM row keeps
    the element kind in ``element_type`` and its IFC/Revit attributes in the
    free-form ``properties`` blob, so we surface ``element_type`` under both
    ``ifc_class`` and ``category`` (the applicability matcher accepts either)
    and pass the JSON blobs through unchanged.
    """
    props: dict[str, Any] = getattr(elem, "properties", None) or {}
    etype = getattr(elem, "element_type", None) or ""
    return {
        "id": str(getattr(elem, "id", "") or getattr(elem, "stable_id", "") or ""),
        "ifc_class": etype,
        "category": etype,
        "predefined_type": props.get("predefined_type") or props.get("PredefinedType"),
        "name": getattr(elem, "name", None),
        "classification": props.get("classification") or {},
        "properties": props,
        "attributes": props.get("attributes") or {},
        "quantities": getattr(elem, "quantities", None) or {},
    }


@dataclass
class _IDSPassTotals:
    """Counters contributed by the scoped IDS pass, folded into the report.

    Mirrors the per-element accounting in :meth:`validate_bim_model` so the
    invariant ``passed_count + failed_checks == total_checks`` survives the
    merge. Engine-error (rule-crash) rows are deliberately excluded from every
    counter and from the score, exactly as the core engine treats them.
    """

    total_checks: int = 0
    passed_count: int = 0
    failed_checks: int = 0
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    passed_weight: float = 0.0
    total_weight: float = 0.0
    truncated: bool = False


class BIMValidationService:
    """Run :class:`BIMElementRule` instances against BIM models."""

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
        """Run BIM element rules against every element in a model.

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
        # perf_counter, not monotonic: monotonic steps by about 15.625 ms on
        # Windows, which is coarser than a whole validation pass and reported
        # short runs as a duration of exactly zero.
        started = time.perf_counter()

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

        # 3b. Apply this project's scoped IDS rule set, if one was imported.
        #
        # IDS specs are synthesised into IDSValidationRule instances that run
        # through the core validation_engine over canonical-format elements
        # (keyed "elements"), a different rule shape than the per-element
        # BIMElementRule above. They are registered under a project-namespaced
        # set on import, so we resolve THIS model's project set only - a model
        # whose project never imported an IDS adds nothing and behaves exactly
        # as before. Findings are folded into the same counts/score/results so
        # the single persisted report reflects both rule families.
        scoped_ids_set = f"{IDS_RULE_SET_PREFIX}:{model.project_id}"
        if rule_registry.has_rules(scoped_ids_set):
            ids_added = await self._apply_scoped_ids_rules(
                scoped_ids_set=scoped_ids_set,
                elements=elements,
                project_id=str(model.project_id),
                model_id=model_id,
                results_json=results_json,
                truncated=truncated,
            )
            total_checks += ids_added.total_checks
            passed_count += ids_added.passed_count
            failed_checks += ids_added.failed_checks
            error_count += ids_added.error_count
            warning_count += ids_added.warning_count
            info_count += ids_added.info_count
            passed_weight += ids_added.passed_weight
            total_weight += ids_added.total_weight
            # If the IDS pass is what tipped the result list over the cap (the
            # per-element pass had not), add the "… N more" sentinel now so the
            # UI still shows the truncation indicator.
            if ids_added.truncated and not truncated:
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
                            f"single report - narrow the rule set to see the rest."
                        ),
                        "element_id": None,
                        "element_name": None,
                        "element_type": None,
                        "element_ref": None,
                        "details": {"cap": MAX_RESULTS_PER_REPORT},
                    }
                )
            truncated = truncated or ids_added.truncated

        # 3c. Model-level rules.
        #
        # These see ALL elements at once - duplicate identifiers, expected-
        # category completeness, unit consistency, georeference sanity - which
        # the per-element DSL cannot express. Each APPLICABLE rule is folded in
        # as exactly one check, mirroring the per-element accounting: one rule
        # weight per check (added to the denominator once), per-severity buckets
        # over its findings, and a passing check when it emits nothing. A rule
        # that is not applicable (e.g. unit consistency with no unit information)
        # contributes nothing, exactly like a per-element rule whose filter
        # matched no element - so an empty model still reports "skipped".
        model_context = BIMModelContext.from_model(model)
        model_rules = get_model_rules_by_ids(rule_ids)
        model_pass_pre_trunc = truncated
        for model_rule in model_rules:
            try:
                if not model_rule.applies(elements, model_context):
                    continue
                model_failures = [f for f in model_rule.evaluate(elements, model_context) if not f.passed]
            except Exception:  # noqa: BLE001 - a model-rule crash must never fail the run
                logger.warning(
                    "BIM model rule %s crashed for model %s",
                    getattr(model_rule, "rule_id", "?"),
                    model_id,
                    exc_info=True,
                )
                continue

            rule_weight = SEVERITY_WEIGHTS.get(str(model_rule.severity), 1.0)
            total_checks += 1
            total_weight += rule_weight
            if not model_failures:
                passed_count += 1
                passed_weight += rule_weight
                continue

            failed_checks += 1
            for failure in model_failures:
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
                        "element_ref": failure.element_ref,
                        "details": failure.details,
                    }
                )

        # Add the truncation sentinel if the model-rule pass is what tipped the
        # result list over the cap (mirrors the per-element / IDS handling).
        if truncated and not model_pass_pre_trunc:
            results_json.append(
                {
                    "rule_id": "_truncated",
                    "rule_name": "Results truncated",
                    "severity": "info",
                    "status": "warning",
                    "passed": False,
                    "message": (
                        f"Result list truncated at {MAX_RESULTS_PER_REPORT} entries. "
                        f"The model produced more findings than can be stored in a "
                        f"single report - narrow the rule set to see the rest."
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
        # When nothing was actually checked (empty model, or a rule set whose
        # filters matched no elements) we must NOT report a green "passed /
        # 100%". That is the misleading pass the core engine deliberately
        # avoids: status "skipped" with a null score so the UI renders "not
        # checked" rather than a clean bill of health (NEW-VAL-004).
        score: float | None
        if total_checks == 0:
            status_value = "skipped"
            score = None
        elif error_count > 0:
            status_value = "errors"
            score = compute_quality_score(passed_weight, total_weight, error_count)
        elif warning_count > 0:
            status_value = "warnings"
            score = compute_quality_score(passed_weight, total_weight, error_count)
        elif info_count > 0:
            status_value = "info"
            score = compute_quality_score(passed_weight, total_weight, error_count)
        else:
            status_value = "passed"
            # Same severity-weighted definition + blocking-error cap as the
            # core ValidationReport.score (E-XMOD-015).
            score = compute_quality_score(passed_weight, total_weight, error_count)

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
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

        applied_ids_set = scoped_ids_set if rule_registry.has_rules(scoped_ids_set) else None
        db_report = ValidationReport(
            id=uuid.uuid4(),
            project_id=model.project_id,
            target_type="bim_model",
            target_id=str(model_id),
            rule_set=("bim_universal+bim_model+ids_custom" if applied_ids_set else "bim_universal+bim_model"),
            status=status_value,
            score=(None if score is None else str(round(score, 4))),
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
                # Model-level rules folded in after the per-element pass.
                "model_rule_ids": [r.rule_id for r in model_rules],
                # The scoped IDS set (if any) whose rules were folded in. None
                # when the project never imported an IDS - behaviour unchanged.
                "ids_rule_set": applied_ids_set,
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

    # ── Scoped IDS pass ─────────────────────────────────────────────────

    async def _apply_scoped_ids_rules(
        self,
        *,
        scoped_ids_set: str,
        elements: list[Any],
        project_id: str,
        model_id: uuid.UUID,
        results_json: list[dict[str, Any]],
        truncated: bool,
    ) -> _IDSPassTotals:
        """Run a project's scoped IDS rule set over the model's elements.

        The IDS rules are :class:`IDSValidationRule` instances driven by the
        core ``validation_engine``. They expect canonical-format elements under
        the ``elements`` key, so we project each ORM row with
        :func:`_element_to_canonical` and hand the engine ``{"elements": [...]}``.

        Each non-engine-error :class:`RuleResult` counts as one check, keeping
        the report's ``passed_count + failed_checks == total_checks`` invariant.
        Engine-error rows (a rule that raised) are appended to ``results_json``
        for visibility but, like the core engine, never move the counts or the
        score. Appends respect the same ``MAX_RESULTS_PER_REPORT`` cap.
        """
        totals = _IDSPassTotals(truncated=truncated)
        canonical = [_element_to_canonical(e) for e in elements]
        try:
            engine_report = await validation_engine.validate(
                data={"elements": canonical},
                rule_sets=[scoped_ids_set],
                target_type="bim_model",
                target_id=str(model_id),
                project_id=project_id,
            )
        except Exception:  # noqa: BLE001 - IDS pass is advisory, never fatal
            logger.warning(
                "Scoped IDS validation pass failed for model %s (set=%s)",
                model_id,
                scoped_ids_set,
                exc_info=True,
            )
            return totals

        for r in engine_report.results:
            severity = r.severity.value if hasattr(r.severity, "value") else str(r.severity)
            # Engine-error rows record a rule crash, not a compliance finding:
            # surface them but keep them out of counts and the score.
            if getattr(r, "is_engine_error", False):
                if len(results_json) < MAX_RESULTS_PER_REPORT:
                    results_json.append(
                        {
                            "rule_id": r.rule_id,
                            "rule_name": r.rule_name,
                            "severity": severity,
                            "status": severity,
                            "passed": False,
                            "message": r.message,
                            "element_id": r.element_ref,
                            "element_name": None,
                            "element_type": None,
                            "element_ref": r.element_ref,
                            "details": r.details or {},
                            "is_engine_error": True,
                        }
                    )
                else:
                    totals.truncated = True
                continue

            weight = SEVERITY_WEIGHTS.get(severity, 1.0)
            totals.total_checks += 1
            totals.total_weight += weight
            if r.passed:
                totals.passed_count += 1
                totals.passed_weight += weight
                continue

            totals.failed_checks += 1
            if severity == "error":
                totals.error_count += 1
            elif severity == "warning":
                totals.warning_count += 1
            else:
                totals.info_count += 1

            if len(results_json) >= MAX_RESULTS_PER_REPORT:
                totals.truncated = True
                continue
            results_json.append(
                {
                    "rule_id": r.rule_id,
                    "rule_name": r.rule_name,
                    "severity": severity,
                    "status": severity,
                    "passed": False,
                    "message": r.message,
                    "element_id": r.element_ref,
                    "element_name": None,
                    "element_type": None,
                    "element_ref": r.element_ref,
                    "details": r.details or {},
                }
            )

        return totals
