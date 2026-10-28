# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Punch list validation rules (photo evidence).

* ``punchlist.closure_photo`` (WARNING): an item that is resolved, verified or
  closed carries at least one photo, so the closure can be shown and not only
  asserted.
* ``punchlist.photo_evidence_located`` (INFO): each photo of such an item has a
  full evidence record (located, timed, hashed); older or desktop uploads are
  flagged so the reviewer knows which closures rest on weaker evidence.

The rules read a plain dict context, ``{"items": [{"id", "title", "status",
"photos": [...], "photo_evidence": [... | None]}]}``, the shape the punch list
API already returns, so they stay pure and need no database.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.i18n import t
from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

logger = logging.getLogger(__name__)

#: Statuses at which an item claims the work is done.
CLOSURE_STATUSES = frozenset({"resolved", "verified", "closed"})


def _items(context: ValidationContext) -> list[dict[str, Any]]:
    data = context.data
    raw = data.get("items", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    return [i for i in raw if isinstance(i, dict)]


def _ref(item: dict[str, Any]) -> str:
    return str(item.get("id") or "")


def _locale(context: ValidationContext) -> str | None:
    value = (context.metadata or {}).get("locale")
    return str(value) if value else None


class PunchClosurePhotoRule(ValidationRule):
    """A closed-out punch item should show its closure with a photo."""

    rule_id = "punchlist.closure_photo"
    name = "Closed punch items have a photo"
    standard = "punchlist"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Resolved, verified and closed punch items should carry at least one photo"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for item in _items(context):
            if str(item.get("status") or "").lower() not in CLOSURE_STATUSES:
                continue
            passed = bool(item.get("photos"))
            title = item.get("title") or _ref(item)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK" if passed else t("field_evidence.punch_no_photo", _locale(context), title=title),
                    element_ref=_ref(item),
                    suggestion=None if passed else t("field_evidence.punch_no_photo_fix", _locale(context)),
                )
            )
        return results


class PunchPhotoEvidenceRule(ValidationRule):
    """Closure photos should carry a located, timed, hashed evidence record."""

    rule_id = "punchlist.photo_evidence_located"
    name = "Closure photos carry full evidence"
    standard = "punchlist"
    severity = Severity.INFO
    category = RuleCategory.QUALITY
    description = "Photos on closed-out punch items should record location, capture time and file hash"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for item in _items(context):
            if str(item.get("status") or "").lower() not in CLOSURE_STATUSES:
                continue
            photos = list(item.get("photos") or [])
            if not photos:
                continue
            evidence = list(item.get("photo_evidence") or [])
            weak = 0
            for idx in range(len(photos)):
                record = evidence[idx] if idx < len(evidence) else None
                if not isinstance(record, dict) or record.get("grade") != "full":
                    weak += 1
            passed = weak == 0
            title = item.get("title") or _ref(item)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else t("field_evidence.photo_weak", _locale(context), count=weak, title=title),
                    element_ref=_ref(item),
                    details={"weak_photos": weak, "photos": len(photos)},
                    suggestion=None if passed else t("field_evidence.photo_weak_fix", _locale(context)),
                )
            )
        return results


def register_punchlist_validation_rules() -> None:
    """Register the punch list rules under the ``punchlist`` rule set."""
    rule_registry.register(PunchClosurePhotoRule(), ["punchlist"])
    rule_registry.register(PunchPhotoEvidenceRule(), ["punchlist"])
    logger.debug("punchlist: registered 2 validation rules")
