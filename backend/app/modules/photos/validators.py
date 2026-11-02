# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Photo archive validation rules (rule set ``photos``).

The rules read one plain snapshot that the service assembles, so they stay pure::

    {
      "now": iso, "project_start": iso | None, "anchor": {"lat", "lon"} | None,
      "photos": [{"id", "filename", "taken_at", "gps_lat", "gps_lon", "gps_accuracy_m",
                  "sha256", "evidence", "file_reachable", "links": [{"target_kind",
                  "target_id", "target_exists"}]}],
      "suggestions": [{"id", "photo_id", "kind", "status", "created_at", "payload"}],
    }

* ``photos.taken_at_present`` (WARNING): the capture time is known.
* ``photos.taken_at_plausible`` (ERROR): not in the future (+24 h for time zones) and
  not more than a year before the project start.
* ``photos.gps_in_project_area`` (WARNING): within 2 km of the site anchor, fix radius
  at most 50 m.
* ``photos.link_target_exists`` (ERROR): every linked record exists in the same project.
* ``photos.duplicate_sha256`` (INFO): the same file is not archived twice.
* ``photos.evidence_grade`` (INFO, WARNING on punch/inspection evidence): the photo
  carries a located, timed, hashed evidence record.
* ``photos.ai_unreviewed`` (INFO): AI proposals are reviewed within 7 days.
* ``photos.hazard_open`` (WARNING): an accepted hazard has a safety observation.
* ``photos.file_reachable`` (ERROR): the file is still in storage.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from app.core.i18n import t
from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
    validation_engine,
)
from app.modules.photos.logic import (
    AI_REVIEW_DAYS,
    MAX_DISTANCE_FROM_SITE_M,
    MAX_GPS_ACCURACY_M,
    evidence_grade_for,
    haversine_m,
    parse_iso,
    valid_lat_lon,
)

logger = logging.getLogger(__name__)

RULE_SET = "photos"
#: Links whose photo is the proof the work passed; weak evidence there is a warning, not a note.
EVIDENCE_LINK_KINDS = frozenset({"punch_item", "inspection"})


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _photos(context: ValidationContext) -> list[dict[str, Any]]:
    return [p for p in _data(context).get("photos") or [] if isinstance(p, dict)]


def _locale(context: ValidationContext) -> str | None:
    value = (context.metadata or {}).get("locale")
    return str(value) if value else None


def _name(photo: dict[str, Any]) -> str:
    return str(photo.get("filename") or photo.get("id") or "")


def _result(
    rule: ValidationRule,
    passed: bool,
    ref: str,
    message: str,
    *,
    severity: Severity | None = None,
    suggestion: str | None = None,
    details: dict[str, Any] | None = None,
) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=severity or rule.severity,
        category=rule.category,
        passed=passed,
        message="OK" if passed else message,
        element_ref=ref,
        details=details or {},
        suggestion=None if passed else suggestion,
    )


class TakenAtPresent(ValidationRule):
    rule_id = "photos.taken_at_present"
    name = "Capture time is known"
    standard = RULE_SET
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Every photo records when it was taken, so it can serve as dated evidence"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            _result(
                self,
                parse_iso(p.get("taken_at")) is not None,
                str(p.get("id")),
                t("photos.validation.taken_at_missing", loc, name=_name(p)),
                suggestion=t("photos.validation.taken_at_missing_fix", loc),
            )
            for p in _photos(context)
        ]


class TakenAtPlausible(ValidationRule):
    rule_id = "photos.taken_at_plausible"
    name = "Capture time is plausible"
    standard = RULE_SET
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Not in the future and not more than a year before the project starts"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        loc = _locale(context)
        now = parse_iso(data.get("now"))
        start = parse_iso(data.get("project_start"))
        out: list[RuleResult] = []
        for p in _photos(context):
            taken = parse_iso(p.get("taken_at"))
            if taken is None or now is None:
                continue
            future = taken > now + timedelta(hours=24)
            early = start is not None and taken < start - timedelta(days=365)
            key = "photos.validation.taken_at_future" if future else "photos.validation.taken_at_before_project"
            out.append(
                _result(
                    self,
                    not (future or early),
                    str(p.get("id")),
                    t(key, loc, name=_name(p), taken_at=taken.date().isoformat()),
                    suggestion=t("photos.validation.taken_at_fix", loc),
                )
            )
        return out


class GpsInProjectArea(ValidationRule):
    rule_id = "photos.gps_in_project_area"
    name = "Location is on site"
    standard = RULE_SET
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Located photos lie within 2 km of the site anchor and their fix is accurate to 50 m"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        loc = _locale(context)
        anchor = data.get("anchor") or {}
        has_anchor = valid_lat_lon(anchor.get("lat"), anchor.get("lon"))
        out: list[RuleResult] = []
        for p in _photos(context):
            lat, lon = p.get("gps_lat"), p.get("gps_lon")
            if not valid_lat_lon(lat, lon):
                continue
            accuracy = p.get("gps_accuracy_m")
            if accuracy is not None and float(accuracy) > MAX_GPS_ACCURACY_M:
                out.append(
                    _result(
                        self,
                        False,
                        str(p.get("id")),
                        t("photos.validation.gps_inaccurate", loc, name=_name(p), accuracy=round(float(accuracy))),
                        suggestion=t("photos.validation.gps_fix", loc),
                        details={"accuracy_m": accuracy},
                    )
                )
                continue
            if not has_anchor:
                continue
            distance = haversine_m(float(lat), float(lon), float(anchor["lat"]), float(anchor["lon"]))
            out.append(
                _result(
                    self,
                    distance <= MAX_DISTANCE_FROM_SITE_M,
                    str(p.get("id")),
                    t("photos.validation.gps_off_site", loc, name=_name(p), distance_km=round(distance / 1000, 1)),
                    suggestion=t("photos.validation.gps_fix", loc),
                    details={"distance_m": round(distance)},
                )
            )
        return out


class LinkTargetExists(ValidationRule):
    rule_id = "photos.link_target_exists"
    name = "Linked records exist"
    standard = RULE_SET
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Every record a photo is linked to exists in the same project"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        out: list[RuleResult] = []
        for p in _photos(context):
            for link in p.get("links") or []:
                out.append(
                    _result(
                        self,
                        bool(link.get("target_exists")),
                        str(p.get("id")),
                        t("photos.validation.link_missing", loc, name=_name(p), kind=link.get("target_kind")),
                        suggestion=t("photos.validation.link_missing_fix", loc),
                        details={"target_kind": link.get("target_kind"), "target_id": link.get("target_id")},
                    )
                )
        return out


class DuplicateSha256(ValidationRule):
    rule_id = "photos.duplicate_sha256"
    name = "No duplicate files"
    standard = RULE_SET
    severity = Severity.INFO
    category = RuleCategory.QUALITY
    description = "The same image is archived once"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        by_hash: dict[str, list[dict[str, Any]]] = {}
        for p in _photos(context):
            if p.get("sha256"):
                by_hash.setdefault(str(p["sha256"]), []).append(p)
        out: list[RuleResult] = []
        for p in _photos(context):
            if not p.get("sha256"):
                continue
            twins = [q for q in by_hash[str(p["sha256"])] if q is not p]
            out.append(
                _result(
                    self,
                    not twins,
                    str(p.get("id")),
                    t("photos.validation.duplicate", loc, name=_name(p), count=len(twins)),
                    suggestion=t("photos.validation.duplicate_fix", loc),
                    details={"duplicates": [str(q.get("id")) for q in twins]},
                )
            )
        return out


class EvidenceGrade(ValidationRule):
    rule_id = "photos.evidence_grade"
    name = "Photo carries full evidence"
    standard = RULE_SET
    severity = Severity.INFO
    category = RuleCategory.QUALITY
    description = "Location, capture time and file hash are recorded; required on punch and inspection evidence"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        out: list[RuleResult] = []
        for p in _photos(context):
            grade = evidence_grade_for(p.get("evidence"))
            proof = any(link.get("target_kind") in EVIDENCE_LINK_KINDS for link in p.get("links") or [])
            out.append(
                _result(
                    self,
                    grade == "full",
                    str(p.get("id")),
                    t("photos.validation.evidence_weak", loc, name=_name(p), grade=grade),
                    severity=Severity.WARNING if proof and grade == "none" else Severity.INFO,
                    suggestion=t("photos.validation.evidence_weak_fix", loc),
                    details={"grade": grade},
                )
            )
        return out


class AIUnreviewed(ValidationRule):
    rule_id = "photos.ai_unreviewed"
    name = "AI proposals are reviewed"
    standard = RULE_SET
    severity = Severity.INFO
    category = RuleCategory.COMPLETENESS
    description = f"AI proposals are accepted or rejected within {AI_REVIEW_DAYS} days"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        loc = _locale(context)
        now = parse_iso(data.get("now"))
        out: list[RuleResult] = []
        for s in data.get("suggestions") or []:
            if not isinstance(s, dict) or s.get("status") != "pending" or now is None:
                continue
            created = parse_iso(s.get("created_at"))
            stale = created is not None and now - created > timedelta(days=AI_REVIEW_DAYS)
            out.append(
                _result(
                    self,
                    not stale,
                    str(s.get("photo_id")),
                    t("photos.validation.ai_unreviewed", loc, kind=s.get("kind"), days=AI_REVIEW_DAYS),
                    suggestion=t("photos.validation.ai_unreviewed_fix", loc),
                    details={"suggestion_id": str(s.get("id"))},
                )
            )
        return out


class HazardOpen(ValidationRule):
    rule_id = "photos.hazard_open"
    name = "Accepted hazards are followed up"
    standard = RULE_SET
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "A hazard confirmed on a photo is linked to a safety observation"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        loc = _locale(context)
        observed = {
            str(p.get("id"))
            for p in _photos(context)
            if any(link.get("target_kind") == "safety_obs" for link in p.get("links") or [])
        }
        out: list[RuleResult] = []
        for s in data.get("suggestions") or []:
            if not isinstance(s, dict) or s.get("kind") != "hazard" or s.get("status") not in ("accepted", "edited"):
                continue
            hazard = (s.get("payload") or {}).get("hazard") or ""
            out.append(
                _result(
                    self,
                    str(s.get("photo_id")) in observed,
                    str(s.get("photo_id")),
                    t("photos.validation.hazard_open", loc, hazard=hazard),
                    suggestion=t("photos.validation.hazard_open_fix", loc),
                    details={"suggestion_id": str(s.get("id"))},
                )
            )
        return out


class FileReachable(ValidationRule):
    rule_id = "photos.file_reachable"
    name = "File is in storage"
    standard = RULE_SET
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "The archived file can still be read from storage"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            _result(
                self,
                bool(p.get("file_reachable")),
                str(p.get("id")),
                t("photos.validation.file_missing", loc, name=_name(p)),
                suggestion=t("photos.validation.file_missing_fix", loc),
            )
            for p in _photos(context)
            if "file_reachable" in p
        ]


RULES: tuple[ValidationRule, ...] = (
    TakenAtPresent(),
    TakenAtPlausible(),
    GpsInProjectArea(),
    LinkTargetExists(),
    DuplicateSha256(),
    EvidenceGrade(),
    AIUnreviewed(),
    HazardOpen(),
    FileReachable(),
)
RULE_IDS: tuple[str, ...] = tuple(r.rule_id for r in RULES)


def register_photos_rules() -> None:
    """Register the photo rules under the ``photos`` rule set."""
    for rule in RULES:
        rule_registry.register(rule, [RULE_SET])
    logger.debug("photos: registered %d validation rules", len(RULES))


async def evaluate(snapshot: dict[str, Any], *, target_id: str = "", locale: str | None = None) -> dict[str, Any]:
    """Run the rule set and return a traffic-light summary plus the failed findings."""
    try:
        report = await validation_engine.validate(
            data=snapshot,
            rule_sets=[RULE_SET],
            target_type="photos",
            target_id=target_id,
            metadata={"locale": locale} if locale else None,
        )
    except Exception:  # noqa: BLE001 - findings augment a read, never break it
        logger.warning("photo validation failed for %s", target_id, exc_info=True)
        return {"status": "unknown", "score": None, "findings": []}
    findings = [
        {
            "rule_id": r.rule_id,
            "severity": str(r.severity.value if hasattr(r.severity, "value") else r.severity),
            "message": r.message,
            "element_ref": r.element_ref,
            "suggestion": r.suggestion,
            "details": r.details,
        }
        for r in report.results
        if not r.passed and not r.is_engine_error
    ]
    status = report.status
    return {
        "status": str(status.value if hasattr(status, "value") else status),
        "score": report.score,
        "findings": findings,
    }
