"""‌⁠‍Validate EAC requirements against a BIM model.

Bridges the EAC schema (entity, attribute, constraint_type,
constraint_value) to the existing ``ValidationReport`` storage so the
Validation dashboard, BIM viewer badges, and SARIF export all work
without per-source forks.

Mapping rules:
* ``entity`` matches an element's ``element_type`` via
  case-insensitive glob (``Walls`` matches ``Walls``;
  ``IfcWall*`` matches ``IfcWallStandardCase``). An entity of ``*`` /
  empty string matches every element.
* ``attribute`` is read first from ``quantities`` (BIM Hub stores
  ``Area``, ``Volume``, ``Length`` etc. there), then from
  ``properties[group][name]`` if a group is supplied via dotted
  notation (``Pset_WallCommon.FireRating``), and finally from a flat
  ``properties[name]`` lookup.

The output report uses ``target_type='bim_model'`` (same shape as
``bim_validation_service``) so the existing UI does not need a
discriminator.
"""

from __future__ import annotations

import logging
import time
import uuid
from fnmatch import fnmatch
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bim_hub.repository import BIMElementRepository, BIMModelRepository
from app.modules.requirements.evaluator import EvalResult, evaluate
from app.modules.requirements.models import Requirement, RequirementSet
from app.modules.validation.models import ValidationReport
from app.modules.validation.repository import ValidationReportRepository

logger = logging.getLogger(__name__)

MAX_RESULTS_PER_REPORT = 5000
# Hard ceiling on elements pulled into memory for one validation pass.
# Combined with up-to-N requirements this drives the worst-case loop:
# 50k × 50 reqs = 2.5M evals — already several seconds of CPU. Beyond
# this we surface a "model too large for synchronous validation" error
# rather than blocking the worker for minutes.
MAX_ELEMENTS_PER_VALIDATION = 50_000


def _split_attribute(attribute: str) -> tuple[str | None, str]:
    """‌⁠‍Split ``Pset_WallCommon.FireRating`` -> ('Pset_WallCommon', 'FireRating').

    Returns ``(None, attribute)`` when no dot is present so callers can
    fall back to flat-property lookup.
    """
    text = (attribute or "").strip()
    if "." in text:
        head, _, tail = text.rpartition(".")
        return head or None, tail.strip()
    return None, text


def _read_attribute(elem: Any, attribute: str) -> object:
    """‌⁠‍Resolve an EAC ``attribute`` against a BIM element."""
    group, name = _split_attribute(attribute)
    if not name:
        return None

    quantities = getattr(elem, "quantities", None) or {}
    if name in quantities:
        return quantities[name]
    # Quantities are sometimes capitalised — normalise both sides.
    for k, v in quantities.items():
        if k.lower() == name.lower():
            return v

    properties = getattr(elem, "properties", None) or {}
    if group:
        bag = properties.get(group)
        if isinstance(bag, dict):
            if name in bag:
                return bag[name]
            for k, v in bag.items():
                if k.lower() == name.lower():
                    return v
    if name in properties:
        return properties[name]
    for k, v in properties.items():
        if k.lower() == name.lower():
            return v

    # Best-effort sweep across nested groups (Pset_*, Common, etc.)
    for value in properties.values():
        if isinstance(value, dict):
            if name in value:
                return value[name]
            for k, v in value.items():
                if k.lower() == name.lower():
                    return v
    return None


def _matches_entity(elem: Any, entity: str) -> bool:
    """True when an element's type satisfies the EAC ``entity`` filter."""
    pattern = (entity or "").strip()
    if not pattern or pattern == "*":
        return True
    etype = (getattr(elem, "element_type", "") or "").strip()
    if not etype:
        return False
    pattern_lower = pattern.lower()
    etype_lower = etype.lower()
    if pattern_lower == etype_lower:
        return True
    # Honour wildcards explicitly (Walls* / IfcWall*)
    if any(ch in pattern for ch in "*?[]"):
        return fnmatch(etype_lower, pattern_lower)
    # Plural/singular tolerance — "Walls" matches "Wall" and vice versa
    if etype_lower.startswith(pattern_lower) or pattern_lower.startswith(etype_lower):
        # Only consider the trailing piece an inflection if it is short
        diff = abs(len(pattern_lower) - len(etype_lower))
        return diff <= 2
    return False


def _severity_from_priority(priority: str) -> str:
    return {
        "must": "error",
        "should": "warning",
        "may": "info",
    }.get(priority, "warning")


async def validate_requirement_set_against_model(
    session: AsyncSession,
    *,
    req_set: RequirementSet,
    requirements: list[Requirement],
    model_id: uuid.UUID,
    user_id: str | None = None,
) -> ValidationReport:
    """Run every requirement in a set against every element of a BIM model.

    Persists and returns a ``ValidationReport`` row.

    Raises ``ValueError`` if the model does not exist.
    """
    started = time.monotonic()

    model_repo = BIMModelRepository(session)
    elem_repo = BIMElementRepository(session)
    report_repo = ValidationReportRepository(session)

    model = await model_repo.get(model_id)
    if model is None:
        msg = f"BIM model {model_id} not found"
        raise ValueError(msg)

    elements, total_elements = await elem_repo.list_for_model(
        model_id,
        offset=0,
        limit=MAX_ELEMENTS_PER_VALIDATION + 1,
    )
    elements_truncated = False
    if total_elements > MAX_ELEMENTS_PER_VALIDATION:
        # We still validate, but only against the first N elements; the
        # report flags this so the user knows the scope is partial.
        elements = elements[:MAX_ELEMENTS_PER_VALIDATION]
        elements_truncated = True
        logger.warning(
            "validate_requirement_set: model %s has %d elements; capping at %d",
            model_id,
            total_elements,
            MAX_ELEMENTS_PER_VALIDATION,
        )

    passed_count = 0
    warning_count = 0
    error_count = 0
    info_count = 0
    total_checks = 0
    results_json: list[dict[str, Any]] = []
    truncated = False
    not_applicable = 0

    for req in requirements:
        if not req.entity or not req.attribute:
            not_applicable += 1
            continue

        severity_default = _severity_from_priority(req.priority or "must")
        rule_id = f"req:{req.id}"
        rule_name = (
            f"{req.entity}.{req.attribute} {req.constraint_type or 'equals'} {req.constraint_value or ''}".strip()
        )

        matched = [e for e in elements if _matches_entity(e, req.entity)]
        if not matched:
            not_applicable += 1
            if len(results_json) < MAX_RESULTS_PER_REPORT:
                results_json.append(
                    {
                        "rule_id": rule_id,
                        "rule_name": rule_name,
                        "severity": "info",
                        "status": "info",
                        "passed": True,
                        "message": (
                            f"Requirement '{req.entity}.{req.attribute}' matched no elements in this model — skipped."
                        ),
                        "element_id": None,
                        "element_name": None,
                        "element_type": None,
                        "element_ref": None,
                        "details": {
                            "requirement_id": str(req.id),
                            "priority": req.priority,
                            "category": req.category,
                            "skipped": True,
                        },
                    }
                )
            info_count += 1
            continue

        for elem in matched:
            total_checks += 1
            actual = _read_attribute(elem, req.attribute)
            outcome: EvalResult = evaluate(
                req.constraint_type or "equals",
                req.constraint_value or "",
                actual,
            )
            if outcome.passed:
                passed_count += 1
                continue

            severity = severity_default
            if severity == "error":
                error_count += 1
            elif severity == "warning":
                warning_count += 1
            else:
                info_count += 1

            if len(results_json) >= MAX_RESULTS_PER_REPORT:
                truncated = True
                continue

            results_json.append(
                {
                    "rule_id": rule_id,
                    "rule_name": rule_name,
                    "severity": severity,
                    "status": severity,
                    "passed": False,
                    "message": outcome.reason or f"{rule_name} failed",
                    "element_id": str(getattr(elem, "id", "")),
                    "element_name": getattr(elem, "name", None),
                    "element_type": getattr(elem, "element_type", None),
                    "element_ref": str(getattr(elem, "id", "")),
                    "details": {
                        "requirement_id": str(req.id),
                        "priority": req.priority,
                        "category": req.category,
                        "expected": req.constraint_value,
                        "operator": req.constraint_type,
                        "actual": None if actual is None else str(actual),
                        "unit": req.unit or "",
                    },
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
                    f"Result list truncated at {MAX_RESULTS_PER_REPORT} "
                    f"entries — narrow the requirement set or pre-filter "
                    f"the model before re-running."
                ),
                "element_id": None,
                "element_name": None,
                "element_type": None,
                "element_ref": None,
                "details": {"cap": MAX_RESULTS_PER_REPORT},
            }
        )

    if error_count > 0:
        status_value = "errors"
    elif warning_count > 0:
        status_value = "warnings"
    else:
        status_value = "passed"
    score = (passed_count / total_checks) if total_checks else 1.0
    duration_ms = round((time.monotonic() - started) * 1000, 2)

    user_uuid: uuid.UUID | None = None
    if user_id:
        try:
            user_uuid = uuid.UUID(str(user_id))
        except (ValueError, TypeError):
            user_uuid = None

    db_report = ValidationReport(
        id=uuid.uuid4(),
        project_id=req_set.project_id,
        target_type="bim_model",
        target_id=str(model_id),
        rule_set=f"requirements:{req_set.name}",
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
            "element_count": total_elements,
            "requirement_set_id": str(req_set.id),
            "requirement_set_name": req_set.name,
            "requirements_total": len(requirements),
            "requirements_skipped": not_applicable,
            "info_count": info_count,
            "truncated": truncated,
            "elements_truncated": elements_truncated,
            "elements_validated": len(elements),
            "elements_cap": MAX_ELEMENTS_PER_VALIDATION,
        },
    )
    await report_repo.create(db_report)

    logger.info(
        "Requirements validation done: set=%s model=%s reqs=%d elements=%d "
        "checks=%d passed=%d warn=%d err=%d duration=%.1fms",
        req_set.id,
        model_id,
        len(requirements),
        total_elements,
        total_checks,
        passed_count,
        warning_count,
        error_count,
        duration_ms,
    )
    return db_report
