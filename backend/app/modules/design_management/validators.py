# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rule set ``design_management`` (SPEC section 7).

The rules read one payload, built by ``DesignService.validation_payload``
(scheme, WBS, unresolved references, drawings, releases, deliverables, reports,
permits, approval points). Most are enforced at write time too; they exist as
rules because the data also moves without a write here: a scheme is changed,
someone types a code in CDE, a module writes a WBS reference, a revision is
added after a permit was submitted.
"""

from __future__ import annotations

from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.design_management import numbering as nb
from app.modules.design_management import rules as dr
from app.modules.design_management import wbs as wr
from app.modules.design_management.catalogue import DrawingNumbering
from app.modules.design_management.messages import is_key_present, translate

DESIGN_RULE_SET = "design_management"


def _locale(context: ValidationContext) -> str:
    meta = getattr(context, "metadata", None) or {}
    return str(meta.get("locale") or "en")


def _label(group: str, code: Any, locale: str) -> str:
    """The localized name of a module or phase code; a code the bundle does not know is shown as written."""
    text = str(code or "").strip()
    key = f"design.common.{group}.{text}"
    return translate(key, locale=locale) if text and is_key_present(key, locale) else (text or "-")


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _rows(context: ValidationContext, key: str) -> list[dict[str, Any]]:
    raw = _data(context).get(key) or []
    return [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []


def _scheme(context: ValidationContext) -> DrawingNumbering | None:
    body = _data(context).get("scheme")
    try:
        return DrawingNumbering.model_validate(body) if isinstance(body, dict) else None
    except Exception:
        return None


class _DesignRule(ValidationRule):
    standard = "design"
    category = RuleCategory.CONSISTENCY
    severity = Severity.ERROR
    key = ""

    def _result(self, locale: str, passed: bool, ref: str, **params: Any) -> RuleResult:
        base = f"design.rules.{self.key}"
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message=translate("design.common.ok", locale=locale)
            if passed
            else translate(f"{base}.fail", locale=locale, **params),
            element_ref=ref,
            suggestion=None if passed else translate(f"{base}.suggestion", locale=locale),
        )


class WbsCodeUnique(_DesignRule):
    key = "wbs_code_unique"
    rule_id = "design_management.wbs_code_unique"
    name = "WBS Code Unique"
    description = "Every WBS code is used once per project (rule 1)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        import uuid

        loc = _locale(context)
        nodes = [wr.Node(uuid.UUID(n["id"]), None, n["code"]) for n in _rows(context, "wbs")]
        dups = wr.duplicate_codes(nodes)
        return [self._result(loc, code not in dups, code, code=code) for code in sorted({n.code for n in nodes})]


class WbsReferenceResolves(_DesignRule):
    key = "wbs_reference_resolves"
    rule_id = "design_management.wbs_reference_resolves"
    name = "WBS Reference Resolves"
    severity = Severity.WARNING
    description = "A WBS id or code in another module matches a node of the project (rule 4)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        out = [
            self._result(
                loc, False, f"{u['module']}:{u['row_id']}", module=_label("module", u["module"], loc), value=u["value"]
            )
            for u in _rows(context, "unresolved")
        ]
        return out or [self._result(loc, True, "wbs")]


class DrawingNumberMatchesScheme(_DesignRule):
    key = "drawing_number_matches_scheme"
    rule_id = "design_management.drawing_number_matches_scheme"
    name = "Drawing Number Matches Scheme"
    description = "Every register number matches the pinned numbering scheme (rule 6); legacy numbers are warnings."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc, scheme = _locale(context), _scheme(context)
        if scheme is None:
            return []
        out = []
        for d in _rows(context, "drawings"):
            result = nb.validate(scheme, d["number"])
            fields = ", ".join(sorted({i.field or i.code for i in result.issues}))
            r = self._result(loc, result.valid, d["number"], number=d["number"], fields=fields)
            if not result.valid and d.get("legacy_scheme"):
                r.severity = Severity.WARNING
            out.append(r)
        return out


class DrawingNumberPartsConsistent(_DesignRule):
    key = "drawing_number_parts_consistent"
    rule_id = "design_management.drawing_number_parts_consistent"
    name = "Drawing Number Parts Consistent"
    description = "The stored ISO parts of a container equal what its code parses into (rule 7)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc, scheme = _locale(context), _scheme(context)
        if scheme is None:
            return []
        out = []
        for d in _rows(context, "drawings"):
            if not nb.validate(scheme, d["number"]).valid:
                continue
            bad = nb.parts_mismatch(scheme, d["number"], d.get("parts") or {})
            out.append(self._result(loc, not bad, d["number"], number=d["number"], fields=", ".join(bad)))
        return out


class DrawingOriginatorKnown(_DesignRule):
    key = "drawing_originator_known"
    rule_id = "design_management.drawing_originator_known"
    name = "Drawing Originator Known"
    description = "A drawing's originator belongs to an active design role (rule 21)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        known = {o.upper() for o in _data(context).get("originators") or []}
        if not known:
            return []
        return [
            self._result(loc, d["originator"].upper() in known, d["number"], number=d["number"], value=d["originator"])
            for d in _rows(context, "drawings")
            if d.get("originator")
        ]


class TitleBlockMatchesNumber(_DesignRule):
    key = "title_block_matches_number"
    rule_id = "design_management.title_block_matches_number"
    name = "Title Block Matches Number"
    severity = Severity.WARNING
    description = "The sheet number read from the title block equals the container code (rule 11)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(
                loc,
                d["title_block_number"].strip() == d["number"],
                d["number"],
                number=d["number"],
                value=d["title_block_number"],
            )
            for d in _rows(context, "drawings")
            if d.get("title_block_number")
        ]


class ReleaseRevisionsSuitable(_DesignRule):
    key = "release_revisions_suitable"
    rule_id = "design_management.release_revisions_suitable"
    name = "Release Revisions Suitable"
    description = "No work-in-progress revision in a release; construction issues are published (rule 13)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        import uuid

        loc = _locale(context)
        out = []
        for rel in _rows(context, "releases"):
            views = [
                dr.RevisionView(uuid.UUID(r["id"]), uuid.uuid4(), r.get("suitability"))
                for r in rel.get("revisions") or []
            ]
            errors = dr.release_content_errors(views, rel.get("purpose") or "")
            out.append(self._result(loc, not errors, rel["code"], release=rel["code"], count=len(errors)))
        return out


class DeliverableCompleteForPhase(_DesignRule):
    key = "deliverable_complete_for_phase"
    rule_id = "design_management.deliverable_complete_for_phase"
    name = "Deliverable Complete For Phase"
    severity = Severity.WARNING
    description = "A required design schedule line is accepted or waived (rule 15)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(
                loc,
                d["status"] in ("accepted", "waived"),
                d["code"],
                code=d["code"],
                phase=_label("phase", d.get("phase_code"), loc),
            )
            for d in _rows(context, "deliverables")
            if d.get("required")
        ]


class ReportIndependentCheck(_DesignRule):
    key = "report_independent_check"
    rule_id = "design_management.report_independent_check"
    name = "Report Independent Check"
    description = "An accepted report that needs an independent check was checked by another party (rule 17)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        out = []
        for r in _rows(context, "reports"):
            if r.get("status") != "accepted" or r.get("independent_check") != "required_by_rule":
                continue
            error = dr.report_acceptance_error(
                independent_check=r["independent_check"],
                author_party=r.get("author_party"),
                checker_party=r.get("checker_party"),
                external=bool(r.get("external")),
                cycle_state=r.get("cycle_state"),
            )
            out.append(self._result(loc, error is None, r["code"], code=r["code"]))
        return out


class NotRequiredHasRationale(_DesignRule):
    key = "not_required_has_rationale"
    rule_id = "design_management.not_required_has_rationale"
    name = "Not Required Has Rationale"
    description = "A report set not required, or a catalogue hint overridden, carries a rationale (rule 18)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(loc, dr.rationale_error(r.get("rationale")) is None, r["code"], code=r["code"])
            for r in _rows(context, "reports")
            if r.get("status") == "not_required" or r.get("hint_overridden")
        ]


class PermitPackageComplete(_DesignRule):
    key = "permit_package_complete"
    rule_id = "design_management.permit_package_complete"
    name = "Permit Package Complete"
    description = "Every required item of a permit package is present with a shared or published revision (rule 19)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(loc, not p.get("missing"), p["code"], code=p["code"], count=p.get("missing", 0))
            for p in _rows(context, "permits")
            if p.get("status") not in ("withdrawn", "refused")
        ]


class PermitContentCurrent(_DesignRule):
    key = "permit_content_current"
    rule_id = "design_management.permit_content_current"
    name = "Permit Content Current"
    severity = Severity.WARNING
    description = "No pinned revision of a submitted package was superseded since (rule 19)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(loc, not p.get("superseded_content"), p["code"], code=p["code"])
            for p in _rows(context, "permits")
            if p.get("status") not in ("assembling", "ready")
        ]


class ApprovalByEntitledUser(_DesignRule):
    key = "approval_by_entitled_user"
    rule_id = "design_management.approval_by_entitled_user"
    name = "Approval By Entitled User"
    description = (
        "An approved point was decided through its route and, under four-eyes, not by its submitter (rule 22)."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        four_eyes = bool(_data(context).get("four_eyes", True))
        out = []
        for a in _rows(context, "approval_points"):
            if a.get("status") != "approved":
                continue
            ok = bool(a.get("decided_by")) and not (four_eyes and a.get("decided_by") == a.get("submitted_by"))
            out.append(self._result(loc, ok, a["code"], code=a["code"]))
        return out


DESIGN_RULES: tuple[type[ValidationRule], ...] = (
    WbsCodeUnique,
    WbsReferenceResolves,
    DrawingNumberMatchesScheme,
    DrawingNumberPartsConsistent,
    DrawingOriginatorKnown,
    TitleBlockMatchesNumber,
    ReleaseRevisionsSuitable,
    DeliverableCompleteForPhase,
    ReportIndependentCheck,
    NotRequiredHasRationale,
    PermitPackageComplete,
    PermitContentCurrent,
    ApprovalByEntitledUser,
)


def register_design_rules() -> None:
    """Idempotently register the design management rules."""
    for rule in DESIGN_RULES:
        rule_registry.register(rule(), rule_sets=[DESIGN_RULE_SET])


# Registered on import as well, like the platform rule modules: whoever imports the rules sees them,
# not only an app that ran the startup hook. Registration is idempotent.
register_design_rules()
