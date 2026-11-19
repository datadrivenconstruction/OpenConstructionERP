# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Survey register validation rules (rule set ``survey_core``).

Rules run over a plain dict context built by the service::

    {
        "crs": {"horizontal_epsg", "is_local_grid", "source", "detected_confidence", "confirmed"},
        "point_sets": [{"id", "name", "stored_epsg"}],
        "points": [{"point_id", "e", "n", "z", "set_id"}],
        "traverses": [{"id", "name", "kind", "ratio", "profile_ratio", "misclosure_mm", "allowed_mm", "k_mm"}],
        "control_checks": [{"point_id", "d2d_mm", "tol_mm"}],
    }

SRV-001 error: a point set with no coordinate system.
SRV-002 warning: a detected project CRS nobody confirmed.
SRV-003 error: one point id with two different positions.
SRV-010 error: a traverse closes worse than the profile's 1:x.
SRV-011 warning: a level run misses by more than k * sqrt(km).
SRV-012 warning: a control check shot is off by more than the profile tolerance.
Both thresholds come from a survey profile (pack, demo or the user's own);
there is no core default, so without a profile neither rule fires.

Geodesy (context keys ``crs`` extras, ``local_grid``, ``scale``, ``import_problems``, ``export``):
SRV-020 warning: a height system whose geoid grid is not installed.
SRV-021 info: the project grid is a legacy system in a country.
SRV-022 error / SRV-023 warning / SRV-024 warning: local grid points, residuals, scale.
SRV-025 warning: ground/grid difference over the reference distance.
SRV-030 / SRV-031 errors, SRV-032 warning: instrument file units and raw observations.
SRV-110 warning: export in another CRS than the project's.
"""

from __future__ import annotations

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, rows, section
from app.modules.survey_core.survey_math import same_position

SURVEY_RULE_SET = "survey_core"


class _SurveyRule(MoneyRule):
    standard = SURVEY_RULE_SET
    message_section = "survey"
    category = RuleCategory.CONSISTENCY


def _f(value: object) -> float | None:
    try:
        return None if value is None or value == "" else float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class PointSetHasCrsRule(_SurveyRule):
    """SRV-001: every point set says which coordinate system it is in."""

    rule_id = "SRV-001"
    name = "Point sets have a coordinate system"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "A point set without a CRS cannot feed volumes or parcels"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        crs = section(context, "crs")
        local = bool(crs.get("is_local_grid"))
        out = [
            self.fail(context, "no_crs", ref=str(s.get("id") or ""), name=str(s.get("name") or ""))
            for s in rows(context, "point_sets")
            if not s.get("stored_epsg") and not local
        ]
        return out or [self.ok()]


class CrsConfirmedRule(_SurveyRule):
    """SRV-002: a detected CRS is a suggestion until a person confirms it."""

    rule_id = "SRV-002"
    name = "Detected CRS confirmed"
    severity = Severity.WARNING
    description = "An auto-detected CRS is never applied without confirmation"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        crs = section(context, "crs")
        if crs.get("source") != "detected" or crs.get("confirmed"):
            return [self.ok()]
        conf = _f(crs.get("detected_confidence"))
        return [
            self.fail(
                context,
                "crs_unconfirmed",
                ref=str(crs.get("horizontal_epsg") or ""),
                confidence=f"{conf:.2f}" if conf is not None else "?",
            )
        ]


class DuplicatePointRule(_SurveyRule):
    """SRV-003: one point id names one position."""

    rule_id = "SRV-003"
    name = "No point id with two positions"
    severity = Severity.ERROR
    description = "The same point id with coordinates more than 1 mm apart"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        first: dict[str, tuple[float, float, float | None]] = {}
        flagged: list[str] = []
        for p in rows(context, "points"):
            pid = str(p.get("point_id") or "").strip()
            e, n = _f(p.get("e")), _f(p.get("n"))
            if not pid or e is None or n is None:
                continue
            pos = (e, n, _f(p.get("z")))
            seen = first.get(pid)
            if seen is None:
                first[pid] = pos
            elif pid not in flagged and not same_position(seen, pos):
                flagged.append(pid)
        out = [self.fail(context, "duplicate_point", ref=pid, point_id=pid) for pid in flagged]
        return out or [self.ok()]


class TraverseClosureRule(_SurveyRule):
    """SRV-010: a closed traverse meets the profile's minimum ratio."""

    rule_id = "SRV-010"
    name = "Traverse closes within profile"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Linear misclosure ratio 1:x against the profile's minimum"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for t in rows(context, "traverses"):
            if t.get("kind", "traverse") != "traverse":
                continue
            ratio, minimum = _f(t.get("ratio")), _f(t.get("profile_ratio"))
            if ratio is None or not minimum or ratio >= minimum:
                continue
            out.append(
                self.fail(
                    context,
                    "traverse_misclosure",
                    ref=str(t.get("id") or ""),
                    name=str(t.get("name") or ""),
                    r=f"{int(ratio):,}",
                    min=f"{int(minimum):,}",
                )
            )
        return out or [self.ok()]


class LevelRunRule(_SurveyRule):
    """SRV-011: a level run stays within k * sqrt(km)."""

    rule_id = "SRV-011"
    name = "Level run within allowance"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Level misclosure against k * sqrt(distance in km)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for t in rows(context, "traverses"):
            if t.get("kind") != "level":
                continue
            f, allowed, k = _f(t.get("misclosure_mm")), _f(t.get("allowed_mm")), _f(t.get("k_mm"))
            if f is None or allowed is None or not k or abs(f) <= allowed:
                continue
            out.append(self.fail(context, "level_misclosure", ref=str(t.get("id") or ""), f=f"{f:.1f}", k=f"{k:g}"))
        return out or [self.ok()]


class GeoidInstalledRule(_SurveyRule):
    """SRV-020: a named height system whose geoid grid is not installed keeps heights as measured."""

    rule_id = "SRV-020"
    name = "Geoid grid installed for the height system"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Heights in a vertical datum need its geoid grid; none are shipped and PROJ never downloads"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        crs = section(context, "crs")
        if not crs.get("vertical_epsg") or crs.get("geoid_available", True):
            return [self.ok()]
        grid = str(crs.get("geoid_grid") or "") or ", ".join(crs.get("missing_grids") or []) or "?"
        return [self.fail(context, "geoid_missing", ref=str(crs["vertical_epsg"]), v=crs["vertical_epsg"], g=grid)]


class LegacyGridRule(_SurveyRule):
    """SRV-021: the project grid is a legacy system where the country has a primary one."""

    rule_id = "SRV-021"
    name = "Project grid is the country's primary system"
    severity = Severity.INFO
    description = "A legacy national grid is allowed, and named as such"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        legacy = section(context, "crs").get("legacy")
        if not isinstance(legacy, dict) or not legacy.get("epsg"):
            return [self.ok()]
        return [
            self.fail(
                context,
                "legacy_grid",
                ref=str(legacy["epsg"]),
                epsg=legacy["epsg"],
                country=legacy.get("country", ""),
                p=legacy.get("primary", ""),
            )
        ]


class LocalGridPointsRule(_SurveyRule):
    """SRV-022: a local grid tie needs two common points."""

    rule_id = "SRV-022"
    name = "Local grid has two common points"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "A similarity transform is fixed by two points; fewer leave it undefined"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        grid = section(context, "local_grid")
        if not grid or int(grid.get("fitted") or 0) >= 2:
            return [self.ok()]
        return [self.fail(context, "local_grid_points", n=int(grid.get("fitted") or 0))]


class LocalGridResidualRule(_SurveyRule):
    """SRV-023: each common point's residual against the configured tolerance."""

    rule_id = "SRV-023"
    name = "Local grid residuals within tolerance"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Residual on a common point above the project's tolerance (config, no core default)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        grid = section(context, "local_grid")
        tol = _f(grid.get("residual_tol_mm"))
        if tol is None:
            return [self.ok()]
        out = []
        for r in grid.get("residuals") or []:
            value = _f(r.get("r_mm"))
            if value is not None and value > tol:
                pid = str(r.get("point_id") or "")
                out.append(self.fail(context, "local_grid_residual", ref=pid, r=f"{value:.1f}", id=pid, t=f"{tol:g}"))
        return out or [self.ok()]


class LocalGridScaleRule(_SurveyRule):
    """SRV-024: a solved scale far from 1 usually means feet read as metres."""

    rule_id = "SRV-024"
    name = "Local grid scale close to 1"
    severity = Severity.WARNING
    description = "Scale off by more than the configured ppm, or by a metre/foot ratio"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        from app.modules.survey_core.geodesy import unit_mixup  # noqa: PLC0415

        grid = section(context, "local_grid")
        scale = _f(grid.get("scale"))
        if scale is None:
            return [self.ok()]
        ppm = (scale - 1.0) * 1e6
        tol = _f(grid.get("scale_tol_ppm"))
        over = tol is not None and abs(ppm) > tol
        if not over and not unit_mixup(scale):
            return [self.ok()]
        t = f"{tol:g}" if tol is not None else "-"
        return [self.fail(context, "local_grid_scale", s=f"{ppm:.1f}", t=t)]


class GroundGridRule(_SurveyRule):
    """SRV-025: stake sheet distances are grid; say how far they differ from the tape."""

    rule_id = "SRV-025"
    name = "Ground/grid difference stated"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Combined scale factor applied to a reference distance, shown when it reaches 1 mm"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        scale = section(context, "scale")
        diff, dist = _f(scale.get("diff_mm")), _f(scale.get("distance_m"))
        # Stake sheets print millimetres: a difference that rounds to 0 mm is not worth a warning.
        if diff is None or dist is None or abs(diff) < 0.5:
            return [self.ok()]
        return [self.fail(context, "ground_grid", d=f"{dist:g}", mm=f"{diff:.0f}")]


class _ImportProblemRule(_SurveyRule):
    """Base for the import-time rules: the service lists the problems, the rule words them."""

    key = ""

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = [
            self.fail(context, self.key, ref=str(p.get("point_id") or ""), **(p.get("params") or {}))
            for p in rows(context, "import_problems")
            if p.get("rule_id") == self.rule_id
        ]
        return out or [self.ok()]


class GsiUnitRule(_ImportProblemRule):
    """SRV-030: a GSI word with a unit code the format does not define."""

    rule_id = "SRV-030"
    name = "GSI unit code known"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Unit digit of a GSI coordinate word outside 0, 1, 6, 7, 8"
    key = "gsi_unit"


class FootDefinitionRule(_ImportProblemRule):
    """SRV-031: feet in the file, metres in the project, and no foot chosen."""

    rule_id = "SRV-031"
    name = "Foot definition chosen"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "International and US survey feet differ by 2 ppm; the project chooses, never guesses"
    key = "foot_definition"


class RawObservationsRule(_ImportProblemRule):
    """SRV-032: raw observations without reduced coordinates are skipped."""

    rule_id = "SRV-032"
    name = "Raw observations reduced"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Angles and distances without coordinates are not imported"
    key = "raw_skipped"


class ExportCrsRule(_SurveyRule):
    """SRV-110: an export in another system than the project's says so."""

    rule_id = "SRV-110"
    name = "Export CRS stated"
    severity = Severity.WARNING
    description = "Coordinates written in another system are transformed, never relabelled"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        exp = section(context, "export")
        a, b = exp.get("epsg"), exp.get("project_epsg")
        if not a or not b or int(a) == int(b):
            return [self.ok()]
        return [self.fail(context, "export_crs", a=a, b=b)]


class ControlCheckRule(_SurveyRule):
    """SRV-012: the latest check shot on a control point is within the profile tolerance."""

    rule_id = "SRV-012"
    name = "Control check within tolerance"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "A control point that moved, or was set out wrong, shifts everything staked from it"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for c in rows(context, "control_checks"):
            r, tol = _f(c.get("d2d_mm")), _f(c.get("tol_mm"))
            if r is None or not tol or r <= tol:
                continue
            out.append(
                self.fail(
                    context,
                    "control_check",
                    ref=str(c.get("point_id") or ""),
                    id=str(c.get("point_id") or ""),
                    r=f"{r:.1f}",
                    t=f"{tol:g}",
                )
            )
        return out or [self.ok()]


SURVEY_RULES = (
    PointSetHasCrsRule,
    CrsConfirmedRule,
    DuplicatePointRule,
    TraverseClosureRule,
    LevelRunRule,
    GeoidInstalledRule,
    LegacyGridRule,
    LocalGridPointsRule,
    LocalGridResidualRule,
    LocalGridScaleRule,
    GroundGridRule,
    GsiUnitRule,
    FootDefinitionRule,
    RawObservationsRule,
    ExportCrsRule,
    ControlCheckRule,
)

#: Import-time rule id -> message key, for the import preview's problem texts.
IMPORT_MESSAGE_KEYS = {"SRV-030": "gsi_unit", "SRV-031": "foot_definition", "SRV-032": "raw_skipped"}


def register_survey_validation_rules() -> None:
    """Register the survey register rules with the platform rule registry."""
    for rule_class in SURVEY_RULES:
        rule_registry.register(rule_class(), [SURVEY_RULE_SET])


__all__ = ["IMPORT_MESSAGE_KEYS", "SURVEY_RULES", "SURVEY_RULE_SET", "register_survey_validation_rules"]


# Registered at import so a process that only loads this module still knows the rule set.
register_survey_validation_rules()
