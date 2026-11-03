# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Validation rules for site survey captures (rule set ``geo_hub_survey``).

* ``geo_hub.survey.captured_on_not_future`` - ERROR. A capture cannot be dated after today.
* ``geo_hub.survey.captured_on_in_project_window`` - WARNING. Date is outside the project dates +/- 30 days.
* ``geo_hub.survey.georeferenced`` - WARNING. An orthophoto without CRS or bounds cannot be placed on the globe.
* ``geo_hub.survey.bbox_intersects_anchor`` - WARNING. The footprint misses the project anchor by over 5 km.
* ``geo_hub.survey.observed_pct_range`` - ERROR. Observed progress must be 0..100.
* ``geo_hub.survey.observation_requires_activity_in_project`` - ERROR. The activity belongs to another project.
* ``geo_hub.survey.gsd_reasonable`` - INFO. Ground sample distance over 10 cm is too coarse for quantity checks.

The rules read ``{"capture": {...}, "observation": {...}}``; either part may be absent.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
    validation_engine,
)
from app.core.validation.messages import translate
from app.modules.geo_hub.survey_logic import (
    ANCHOR_MISS_KM,
    COARSE_GSD_CM,
    bbox_distance_km,
    in_project_window,
)

logger = logging.getLogger(__name__)

RULE_SET = "geo_hub_survey"
_P = "geo_hub_survey"


def _part(context: ValidationContext, key: str) -> dict[str, Any] | None:
    data = context.data if isinstance(context.data, dict) else {}
    part = data.get(key)
    return part if isinstance(part, dict) else None


def _locale(context: ValidationContext) -> str:
    loc = (context.metadata or {}).get("locale")
    return loc.strip() if isinstance(loc, str) and loc.strip() else "en"


class _SurveyRule(ValidationRule):
    standard = RULE_SET
    part = "capture"
    msg_key = ""

    def check(self, part: dict[str, Any]) -> tuple[bool, dict[str, Any]] | None:  # pragma: no cover - abstract
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        part = _part(context, self.part)
        if part is None:
            return []
        outcome = self.check(part)
        if outcome is None:
            return []
        passed, details = outcome
        locale = _locale(context)
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message="OK" if passed else translate(f"{_P}.{self.msg_key}.fail", locale, **details),
                element_ref=str(part.get("id") or "") or None,
                suggestion=None if passed else translate(f"{_P}.{self.msg_key}.suggestion", locale),
                details=details,
            )
        ]


class CapturedOnNotFuture(_SurveyRule):
    rule_id = "geo_hub.survey.captured_on_not_future"
    name = "Capture date is not in the future"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "A survey cannot have been flown after today."
    msg_key = "captured_on_not_future"

    def check(self, part):  # noqa: ANN001, ANN201
        captured, today = part.get("captured_on"), part.get("today") or date.today()
        if not isinstance(captured, date):
            return None
        return captured <= today, {"captured_on": captured.isoformat()}


class CapturedOnInProjectWindow(_SurveyRule):
    rule_id = "geo_hub.survey.captured_on_in_project_window"
    name = "Capture date is within the project dates"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "A capture more than 30 days outside the project start and end is probably mis-dated."
    msg_key = "captured_on_in_project_window"

    def check(self, part):  # noqa: ANN001, ANN201
        captured = part.get("captured_on")
        if not isinstance(captured, date):
            return None
        ok = in_project_window(captured, part.get("project_start"), part.get("project_end"))
        return ok, {"captured_on": captured.isoformat()}


class Georeferenced(_SurveyRule):
    rule_id = "geo_hub.survey.georeferenced"
    name = "Orthophoto is georeferenced"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Without a CRS and bounds the orthophoto cannot be placed on the globe."
    msg_key = "georeferenced"

    def check(self, part):  # noqa: ANN001, ANN201
        if part.get("kind") != "orthophoto":
            return None
        ok = part.get("crs_epsg") is not None and part.get("bbox") is not None
        return ok, {}


class BboxIntersectsAnchor(_SurveyRule):
    rule_id = "geo_hub.survey.bbox_intersects_anchor"
    name = "Footprint is near the project anchor"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "A footprint more than 5 km from the project anchor usually means a wrong CRS."
    msg_key = "bbox_intersects_anchor"

    def check(self, part):  # noqa: ANN001, ANN201
        bbox, anchor = part.get("bbox"), part.get("anchor")
        if not bbox or not anchor:
            return None
        km = bbox_distance_km(tuple(float(v) for v in bbox), float(anchor["lat"]), float(anchor["lon"]))
        return km <= ANCHOR_MISS_KM, {"distance_km": round(km, 1)}


class GsdReasonable(_SurveyRule):
    rule_id = "geo_hub.survey.gsd_reasonable"
    name = "Ground sample distance is fine enough"
    severity = Severity.INFO
    category = RuleCategory.QUALITY
    description = "Over 10 cm per pixel is too coarse to check quantities against."
    msg_key = "gsd_reasonable"

    def check(self, part):  # noqa: ANN001, ANN201
        gsd = part.get("gsd_cm")
        if gsd is None:
            return None
        return float(gsd) <= COARSE_GSD_CM, {"gsd_cm": round(float(gsd), 1)}


class ObservedPctRange(_SurveyRule):
    rule_id = "geo_hub.survey.observed_pct_range"
    name = "Observed progress is between 0 and 100"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "Observed progress is a percentage."
    part = "observation"
    msg_key = "observed_pct_range"

    def check(self, part):  # noqa: ANN001, ANN201
        raw = part.get("observed_pct")
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return False, {"observed_pct": str(raw)}
        return 0.0 <= val <= 100.0, {"observed_pct": str(raw)}


class ObservationRequiresActivityInProject(_SurveyRule):
    rule_id = "geo_hub.survey.observation_requires_activity_in_project"
    name = "Observed activity belongs to the project"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "An observation can only be recorded against a schedule activity of the same project."
    part = "observation"
    msg_key = "observation_requires_activity_in_project"

    def check(self, part):  # noqa: ANN001, ANN201
        return bool(part.get("activity_in_project")), {}


_RULES: list[ValidationRule] = [
    CapturedOnNotFuture(),
    CapturedOnInProjectWindow(),
    Georeferenced(),
    BboxIntersectsAnchor(),
    GsdReasonable(),
    ObservedPctRange(),
    ObservationRequiresActivityInProject(),
]


def register_geo_hub_survey_rules() -> None:
    """Register the rule set; idempotent (the registry overwrites by id)."""
    for rule in _RULES:
        rule_registry.register(rule, [RULE_SET])


async def evaluate(data: dict[str, Any], *, locale: str = "en", target_id: str = "") -> list[RuleResult]:
    """Failed findings for one capture or observation; an engine failure logs and returns none."""
    register_geo_hub_survey_rules()
    try:
        report = await validation_engine.validate(
            data=data,
            rule_sets=[RULE_SET],
            target_type="geo_hub_survey",
            target_id=target_id,
            metadata={"locale": locale},
        )
    except Exception:  # noqa: BLE001 - findings augment a write, a rules failure must not break it
        logger.warning("survey validation failed for %s", target_id, exc_info=True)
        return []
    return [r for r in report.results if not r.passed and not r.is_engine_error]
