# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rules of a drawing revision compare (rule set ``drawing_compare``).

A compare is evidence: it is what an estimator points at when a quantity is
re-measured or a variation is claimed. These rules check that the evidence
holds up and that the review was finished.

* ``drawing_compare.distinct_revisions``      - ERROR.   The two sides are two
  different revisions (or at least two different pages).
* ``drawing_compare.alignment_plausible``     - WARNING. The sheet alignment is
  invertible, keeps scale within 1:2..2:1, an automatic one is confident and a
  manual one rests on two point pairs.
* ``drawing_compare.regions_on_sheet``        - ERROR.   Every changed region has
  a size and lies on the sheet it names.
* ``drawing_compare.changes_triaged``         - WARNING. No change is still open.
* ``drawing_compare.relevant_changes_followed_up`` - WARNING. A change marked
  relevant carries a comment, an RFI, a markup or a re-measure flag.

``context.data`` is ``{"comparison": {...}, "changes": [{...}, ...]}`` as
:meth:`app.modules.drawing_compare.service.DrawingCompareService.validate`
builds it.
"""

from __future__ import annotations

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
from app.modules.drawing_compare.geometry import affine_scale_rotation

__all__ = [
    "DRAWING_COMPARE_RULE_SET",
    "register_drawing_compare_rules",
]

DRAWING_COMPARE_RULE_SET = "drawing_compare"

# Below this an automatic alignment is a guess the reviewer should confirm.
MIN_AUTO_CONFIDENCE = 0.5
# Revisions of one sheet are plotted at the same scale; beyond 2:1 the
# alignment has locked onto the wrong feature.
MIN_SCALE, MAX_SCALE = 0.5, 2.0
# A region may overhang the sheet edge by this share of the sheet (antialiasing).
EDGE_TOLERANCE = 0.01


def _payload(context: ValidationContext) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = context.data if isinstance(context.data, dict) else {}
    comparison = data.get("comparison") if isinstance(data.get("comparison"), dict) else {}
    changes = [c for c in data.get("changes", []) if isinstance(c, dict)]
    return comparison, changes  # type: ignore[return-value]


def _locale(context: ValidationContext) -> str | None:
    meta = getattr(context, "metadata", None) or {}
    return meta.get("locale") or None


def _msg(context: ValidationContext, key: str, **params: Any) -> str:
    return t(f"drawing_compare.rules.{key}", locale=_locale(context), **params)


def _result(
    rule: ValidationRule,
    passed: bool,
    message: str,
    *,
    element_ref: str | None = None,
    details: dict[str, Any] | None = None,
    suggestion: str | None = None,
) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=element_ref,
        details=details or {},
        suggestion=suggestion,
    )


class DistinctRevisions(ValidationRule):
    """The two sides of a compare are not the same sheet."""

    rule_id = "drawing_compare.distinct_revisions"
    name = "Compare two different revisions"
    standard = "drawing_compare"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "A compare of a sheet with itself finds nothing and proves nothing."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        cmp, _ = _payload(context)
        same = cmp.get("old_ref_id") == cmp.get("new_ref_id") and cmp.get("old_page") == cmp.get("new_page")
        key = "distinct_revisions_fail" if same else "distinct_revisions_ok"
        return [
            _result(
                self,
                not same,
                _msg(context, key),
                element_ref=str(cmp.get("id") or ""),
                suggestion=_msg(context, "distinct_revisions_hint") if same else None,
            )
        ]


class AlignmentPlausible(ValidationRule):
    """The old sheet was laid onto the new one in a believable way."""

    rule_id = "drawing_compare.alignment_plausible"
    name = "Sheet alignment is plausible"
    standard = "drawing_compare"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "An alignment that rescales or rotates wildly paints every line as changed."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        cmp, _ = _payload(context)
        ref = str(cmp.get("id") or "")
        if cmp.get("source_kind") != "pdf":
            return [_result(self, True, _msg(context, "alignment_not_needed"), element_ref=ref)]
        alignment = cmp.get("alignment") if isinstance(cmp.get("alignment"), dict) else {}
        assert isinstance(alignment, dict)  # noqa: S101 - narrowed above
        problems: list[str] = []
        matrix = alignment.get("matrix")
        if not isinstance(matrix, list) or len(matrix) != 6:
            problems.append(_msg(context, "alignment_missing_matrix"))
        else:
            try:
                det = float(matrix[0]) * float(matrix[3]) - float(matrix[1]) * float(matrix[2])
                scale, _rot = affine_scale_rotation([float(v) for v in matrix])
            except (TypeError, ValueError):
                det, scale = 0.0, 0.0
            if abs(det) < 1e-9:
                problems.append(_msg(context, "alignment_singular"))
            elif not (MIN_SCALE <= scale <= MAX_SCALE):
                problems.append(_msg(context, "alignment_scale", scale=f"{scale:.2f}"))
        method = alignment.get("method")
        confidence = alignment.get("confidence")
        if method == "auto" and isinstance(confidence, (int, float)) and confidence < MIN_AUTO_CONFIDENCE:
            problems.append(_msg(context, "alignment_low_confidence", confidence=f"{confidence:.2f}"))
        if method == "manual" and (
            len(alignment.get("points_old") or []) < 2 or len(alignment.get("points_new") or []) < 2
        ):
            problems.append(_msg(context, "alignment_manual_points"))
        if not problems:
            return [_result(self, True, _msg(context, "alignment_ok"), element_ref=ref)]
        return [
            _result(
                self,
                False,
                p,
                element_ref=ref,
                details={"method": method},
                suggestion=_msg(context, "alignment_hint"),
            )
            for p in problems
        ]


class RegionsOnSheet(ValidationRule):
    """Every changed region has a size and sits on the sheet."""

    rule_id = "drawing_compare.regions_on_sheet"
    name = "Changed regions lie on the sheet"
    standard = "drawing_compare"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "A region off the sheet or without a size cannot be found, measured or clouded."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        cmp, changes = _payload(context)
        width = cmp.get("page_width")
        height = cmp.get("page_height")
        results: list[RuleResult] = []
        for ch in changes:
            w, h = float(ch.get("w") or 0.0), float(ch.get("h") or 0.0)
            x, y = float(ch.get("x") or 0.0), float(ch.get("y") or 0.0)
            ref = str(ch.get("id") or "")
            seq = ch.get("seq")
            if w <= 0 and h <= 0:
                results.append(_result(self, False, _msg(context, "region_empty", seq=seq), element_ref=ref))
                continue
            if cmp.get("source_kind") == "pdf" and width and height:
                tol_x, tol_y = float(width) * EDGE_TOLERANCE, float(height) * EDGE_TOLERANCE
                off = x < -tol_x or y < -tol_y or x + w > float(width) + tol_x or y + h > float(height) + tol_y
                if off:
                    results.append(
                        _result(
                            self,
                            False,
                            _msg(context, "region_off_sheet", seq=seq),
                            element_ref=ref,
                            details={"x": x, "y": y, "w": w, "h": h},
                        )
                    )
        if not results:
            results.append(_result(self, True, _msg(context, "regions_ok"), element_ref=str(cmp.get("id") or "")))
        return results


class ChangesTriaged(ValidationRule):
    """The reviewer has made a call on every change."""

    rule_id = "drawing_compare.changes_triaged"
    name = "Every change is triaged"
    standard = "drawing_compare"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "An open change is a revision nobody has read yet."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        cmp, changes = _payload(context)
        open_seqs = [c.get("seq") for c in changes if c.get("status", "open") == "open"]
        ref = str(cmp.get("id") or "")
        if not open_seqs:
            return [_result(self, True, _msg(context, "triaged_ok"), element_ref=ref)]
        return [
            _result(
                self,
                False,
                _msg(context, "triaged_open", count=len(open_seqs)),
                element_ref=ref,
                details={"open": open_seqs[:50]},
                suggestion=_msg(context, "triaged_hint"),
            )
        ]


class RelevantChangesFollowedUp(ValidationRule):
    """A relevant change leads somewhere."""

    rule_id = "drawing_compare.relevant_changes_followed_up"
    name = "Relevant changes are followed up"
    standard = "drawing_compare"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A change marked relevant with no comment, RFI, markup or re-measure flag is lost."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        cmp, changes = _payload(context)
        results: list[RuleResult] = []
        for ch in changes:
            if ch.get("status") != "relevant":
                continue
            followed = bool(
                (ch.get("comment") or "").strip() or ch.get("rfi_id") or ch.get("markup_id") or ch.get("flagged_at")
            )
            if not followed:
                results.append(
                    _result(
                        self,
                        False,
                        _msg(context, "followed_up_missing", seq=ch.get("seq")),
                        element_ref=str(ch.get("id") or ""),
                        suggestion=_msg(context, "followed_up_hint"),
                    )
                )
        if not results:
            results.append(_result(self, True, _msg(context, "followed_up_ok"), element_ref=str(cmp.get("id") or "")))
        return results


def register_drawing_compare_rules() -> None:
    """Register the rule set (the registry is keyed by id, so this is idempotent)."""
    for rule in (
        DistinctRevisions(),
        AlignmentPlausible(),
        RegionsOnSheet(),
        ChangesTriaged(),
        RelevantChangesFollowedUp(),
    ):
        rule_registry.register(rule, rule_sets=[DRAWING_COMPARE_RULE_SET])
