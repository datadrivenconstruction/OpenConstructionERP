# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rules for imported rebar schedules.

Nothing in this codebase imports without validation, and a bending schedule is
a case where that matters more than most: the file downstream of this one
drives a bending machine, and a shape that is wrong is steel that is cut and
scrapped rather than a number somebody edits later.

The rules below form the ``bvbs_abs`` rule set. They read the parsed records
produced by :mod:`app.modules.rebar_schedule.abs_format`, so they can be
exercised without a database. Their user-facing text lives in this module's own
``messages/`` bundle rather than in the shared one, so the module stays a
self-contained plugin.

Each rule and what it catches:

``bvbs_abs.checksum_valid``
    The record's own checksum matches its content. The first line of defence
    against a file damaged in transit.
``bvbs_abs.header_field_order``
    Every header field the record's super-group requires is present, and the
    identifiers run in the order the standard fixes. A reader that walks the
    header positionally silently mis-assigns every field after a gap.
``bvbs_abs.geometry_angle_terminated``
    A planar shape's last leg carries an explicit angle. The standard asks for
    ``w0@`` on a bar that ends straight, and without it a machine cannot tell
    "no bend" from "angle not stated".
``bvbs_abs.bend_radius_over_roller``
    A curved leg's radius is larger than half the header's bending-roller
    diameter, which is what makes the curve producible on that roller.
``bvbs_abs.developed_length_matches_header``
    The legs and arcs in the geometry block add up to the total length in the
    header. Where they disagree the geometry wins on the machine, so a
    mismatch means the printed schedule and the cut bar differ.
``bvbs_abs.mesh_coordinates_non_negative``
    A mesh's bar coordinates are non-negative, as the standard requires of the
    mesh coordinate system.
``bvbs_abs.geometry_excludes_spacer``
    A record carries a geometry block or a spacer block, never both.
``bvbs_abs.ascii_only``
    The record is ASCII. Anything else changes the byte the checksum was
    computed over and will not survive the round trip to the bending shop.
``bvbs_abs.record_within_length_budget``
    The record stays inside the standard's 1000-character compactness target.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.core.validation.messages import DEFAULT_LOCALE, MessageBundle
from app.modules.rebar_schedule.abs_format import (
    GEOMETRY,
    HEADER_FIELD_ORDER,
    HEADER_FIELDS_BY_GROUP,
    MAX_RECORD_LENGTH,
    SPACER,
    AbsRecord,
    read_segments,
)

#: Name of the rule set these rules register under.
RULE_SET = "bvbs_abs"

#: This module's own translations, beside the rules they belong to. The
#: validation message layer is built for exactly this - a rules package that
#: carries its own ``messages/`` directory and registers itself without
#: reaching into the shared bundle - which keeps the module droppable and keeps
#: a locale gap here from being a merge conflict in a file every rule set edits.
MESSAGES = MessageBundle(Path(__file__).parent / "messages")


def translate(key: str, locale: str = DEFAULT_LOCALE, **params: Any) -> str:
    """Resolve one of this module's message keys.

    Same semantics as the shared translator: requested locale, then English,
    then the raw key.
    """
    return MESSAGES.translate(key, locale=locale, **params)


#: How far the developed length may sit from the header length before it is
#: reported. An arc contributes ``radius * angle`` in radians, so a shape with
#: bends lands a fraction of a millimetre away from a value the CAD system
#: rounded; 1 mm or 0.1 percent, whichever is larger, absorbs that without
#: hiding a leg that was actually mistyped.
LENGTH_TOLERANCE_MM = Decimal("1.0")
LENGTH_TOLERANCE_RATIO = Decimal("0.001")


def _records(context: ValidationContext) -> list[AbsRecord]:
    """Pull the parsed records out of a validation context."""
    data = context.data
    if isinstance(data, dict):
        found = data.get("records", [])
    else:
        found = data
    if not isinstance(found, list):
        return []
    return [item for item in found if isinstance(item, AbsRecord)]


def _locale(context: ValidationContext) -> str:
    """Read the caller's locale, defaulting to English."""
    return str(context.metadata.get("locale") or DEFAULT_LOCALE)


def _ref(record: AbsRecord) -> str:
    """A human-readable reference for a record, used as ``element_ref``."""
    position = record.header_value("p") or "?"
    drawing = record.header_value("r") or "?"
    return f"{record.group}:{drawing}:{position}@{record.line_no}"


def _result(
    rule: ValidationRule,
    record: AbsRecord,
    *,
    passed: bool,
    locale: str,
    message_key: str = "",
    details: dict[str, Any] | None = None,
    **params: Any,
) -> RuleResult:
    """Build a :class:`RuleResult` with i18n message and suggestion."""
    if passed:
        message = translate("common.ok", locale=locale)
        suggestion = None
    else:
        message = translate(f"{message_key}.fail", locale=locale, **params)
        suggestion = translate(f"{message_key}.suggestion", locale=locale)
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=_ref(record),
        details=details or {},
        suggestion=suggestion,
    )


# ── Structure ───────────────────────────────────────────────────────────────


class AbsChecksumValid(ValidationRule):
    """Checks that each record's declared checksum matches its content."""

    rule_id = "bvbs_abs.checksum_valid"
    name = "ABS Record Checksum"
    standard = RULE_SET
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "Every ABS record must carry a checksum block whose value matches the record's characters"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _locale(context)
        results = []
        for record in _records(context):
            declared = record.declared_checksum
            passed = record.checksum_ok
            results.append(
                _result(
                    self,
                    record,
                    passed=passed,
                    locale=locale,
                    message_key="bvbs_abs.checksum_valid",
                    details={"declared": declared},
                    line=record.line_no,
                    declared="-" if declared is None else declared,
                )
            )
        return results


class AbsHeaderFieldOrder(ValidationRule):
    """Checks the header carries the required fields, in the fixed order."""

    rule_id = "bvbs_abs.header_field_order"
    name = "ABS Header Field Order"
    standard = RULE_SET
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Header fields must all be present for the super-group and appear in the order the standard fixes"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _locale(context)
        results = []
        for record in _records(context):
            header = record.header
            if header is None:
                results.append(
                    _result(
                        self,
                        record,
                        passed=False,
                        locale=locale,
                        message_key="bvbs_abs.header_field_order",
                        line=record.line_no,
                        problem=translate("bvbs_abs.header_field_order.missing_block", locale=locale),
                    )
                )
                continue
            present = [item.key for item in header.fields]
            required = HEADER_FIELDS_BY_GROUP.get(record.group, ())
            missing = [key for key in required if key not in present]
            ranked = [HEADER_FIELD_ORDER.index(key) for key in present if key in HEADER_FIELD_ORDER]
            out_of_order = ranked != sorted(ranked)
            unknown = [key for key in present if key not in HEADER_FIELD_ORDER]
            problems = []
            if missing:
                problems.append(
                    translate("bvbs_abs.header_field_order.missing", locale=locale, fields=", ".join(missing))
                )
            if out_of_order:
                problems.append(translate("bvbs_abs.header_field_order.order", locale=locale))
            if unknown:
                problems.append(
                    translate("bvbs_abs.header_field_order.unknown", locale=locale, fields=", ".join(unknown))
                )
            results.append(
                _result(
                    self,
                    record,
                    passed=not problems,
                    locale=locale,
                    message_key="bvbs_abs.header_field_order",
                    details={"missing": missing, "unknown": unknown, "out_of_order": out_of_order},
                    line=record.line_no,
                    problem="; ".join(problems),
                )
            )
        return results


class AbsGeometryExcludesSpacer(ValidationRule):
    """Checks that a record does not carry both a geometry and a spacer block."""

    rule_id = "bvbs_abs.geometry_excludes_spacer"
    name = "ABS Geometry And Spacer Blocks Are Exclusive"
    standard = RULE_SET
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "A record carries either a geometry block or a spacer block, never both"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _locale(context)
        results = []
        for record in _records(context):
            kinds = {block.kind for block in record.blocks}
            passed = not (GEOMETRY in kinds and SPACER in kinds)
            results.append(
                _result(
                    self,
                    record,
                    passed=passed,
                    locale=locale,
                    message_key="bvbs_abs.geometry_excludes_spacer",
                    line=record.line_no,
                )
            )
        return results


class AbsAsciiOnly(ValidationRule):
    """Checks that every record is pure ASCII, as the standard requires."""

    rule_id = "bvbs_abs.ascii_only"
    name = "ABS Records Are ASCII"
    standard = RULE_SET
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "ABS is an ASCII format; any other byte breaks the checksum and the round trip to the bending shop"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _locale(context)
        results = []
        for record in _records(context):
            offenders = sorted({char for char in record.raw if not char.isascii()})
            results.append(
                _result(
                    self,
                    record,
                    passed=not offenders,
                    locale=locale,
                    message_key="bvbs_abs.ascii_only",
                    details={"characters": offenders},
                    line=record.line_no,
                    characters=" ".join(offenders),
                )
            )
        return results


class AbsRecordLengthBudget(ValidationRule):
    """Checks the record stays inside the standard's compactness target."""

    rule_id = "bvbs_abs.record_within_length_budget"
    name = "ABS Record Length Budget"
    standard = RULE_SET
    severity = Severity.INFO
    category = RuleCategory.QUALITY
    description = "The standard asks for no more than 1000 characters per bending shape"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _locale(context)
        results = []
        for record in _records(context):
            size = len(record.raw)
            results.append(
                _result(
                    self,
                    record,
                    passed=size <= MAX_RECORD_LENGTH,
                    locale=locale,
                    message_key="bvbs_abs.record_within_length_budget",
                    details={"length": size},
                    line=record.line_no,
                    length=size,
                    budget=MAX_RECORD_LENGTH,
                )
            )
        return results


# ── Geometry ────────────────────────────────────────────────────────────────


class AbsGeometryAngleTerminated(ValidationRule):
    """Checks that every leg of a planar shape carries its bend angle."""

    rule_id = "bvbs_abs.geometry_angle_terminated"
    name = "ABS Geometry Legs Carry An Angle"
    standard = RULE_SET
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Every leg must be followed by an angle; a bar that ends straight must still carry an explicit w0"

    _GROUPS = ("BF2D", "BFWE", "BFMA")

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _locale(context)
        results = []
        for record in _records(context):
            if record.group not in self._GROUPS:
                continue
            geometry = record.geometry
            if geometry is None:
                continue
            segments = read_segments(geometry)
            if not segments:
                continue
            unangled = [index + 1 for index, seg in enumerate(segments) if seg.angle_deg is None]
            results.append(
                _result(
                    self,
                    record,
                    passed=not unangled,
                    locale=locale,
                    message_key="bvbs_abs.geometry_angle_terminated",
                    details={"legs": unangled},
                    line=record.line_no,
                    legs=", ".join(str(index) for index in unangled),
                )
            )
        return results


class AbsBendRadiusOverRoller(ValidationRule):
    """Checks a curved leg's radius against the header's bending roller."""

    rule_id = "bvbs_abs.bend_radius_over_roller"
    name = "ABS Bend Radius Exceeds Half The Roller"
    standard = RULE_SET
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "A curved leg's radius must be larger than half the bending-roller diameter given in the header"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _locale(context)
        results = []
        for record in _records(context):
            geometry = record.geometry
            roller = record.header_number("s")
            if geometry is None or roller is None or roller <= 0:
                continue
            limit = roller / 2
            offenders = [
                (index + 1, seg.radius_mm)
                for index, seg in enumerate(read_segments(geometry))
                if seg.radius_mm is not None and seg.radius_mm <= limit
            ]
            results.append(
                _result(
                    self,
                    record,
                    passed=not offenders,
                    locale=locale,
                    message_key="bvbs_abs.bend_radius_over_roller",
                    details={"legs": [index for index, _ in offenders], "limit_mm": str(limit)},
                    line=record.line_no,
                    legs=", ".join(f"{index} (r={radius})" for index, radius in offenders),
                    limit=limit,
                )
            )
        return results


class AbsDevelopedLengthMatchesHeader(ValidationRule):
    """Checks the geometry's developed length against the header's total."""

    rule_id = "bvbs_abs.developed_length_matches_header"
    name = "ABS Developed Length Matches The Header"
    standard = RULE_SET
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "The legs and arcs of a planar shape must add up to the total length stated in the header"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _locale(context)
        results = []
        for record in _records(context):
            if record.group != "BF2D":
                continue
            geometry = record.geometry
            stated = record.header_number("l")
            if geometry is None or stated is None or stated <= 0:
                continue
            segments = read_segments(geometry)
            if not segments:
                continue
            developed = sum((seg.developed_length_mm for seg in segments), start=Decimal(0))
            allowed = max(LENGTH_TOLERANCE_MM, stated * LENGTH_TOLERANCE_RATIO)
            gap = abs(developed - stated)
            results.append(
                _result(
                    self,
                    record,
                    passed=gap <= allowed,
                    locale=locale,
                    message_key="bvbs_abs.developed_length_matches_header",
                    details={"developed_mm": str(developed), "stated_mm": str(stated)},
                    line=record.line_no,
                    developed=f"{developed:.1f}",
                    stated=f"{stated:.1f}",
                    gap=f"{gap:.1f}",
                )
            )
        return results


class AbsMeshCoordinatesNonNegative(ValidationRule):
    """Checks a mesh's bar coordinates sit in the non-negative quadrant."""

    rule_id = "bvbs_abs.mesh_coordinates_non_negative"
    name = "ABS Mesh Coordinates Are Non-Negative"
    standard = RULE_SET
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "A mesh lies in the X-Y plane with no negative bar coordinates"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _locale(context)
        results = []
        for record in _records(context):
            if record.group != "BFMA":
                continue
            offenders: list[str] = []
            for block in record.bar_blocks:
                for item in block.fields:
                    if item.key not in ("x", "y"):
                        continue
                    # A double bar carries its two values separated by a
                    # semicolon; both belong to the same bar and both count.
                    for part in item.value.split(";"):
                        text = part.strip()
                        if text.startswith("-"):
                            offenders.append(f"{block.kind}{item.key}={text}")
            results.append(
                _result(
                    self,
                    record,
                    passed=not offenders,
                    locale=locale,
                    message_key="bvbs_abs.mesh_coordinates_non_negative",
                    details={"coordinates": offenders},
                    line=record.line_no,
                    coordinates=", ".join(offenders),
                )
            )
        return results


# ── Registration ────────────────────────────────────────────────────────────

RULES: tuple[type[ValidationRule], ...] = (
    AbsChecksumValid,
    AbsHeaderFieldOrder,
    AbsGeometryExcludesSpacer,
    AbsAsciiOnly,
    AbsRecordLengthBudget,
    AbsGeometryAngleTerminated,
    AbsBendRadiusOverRoller,
    AbsDevelopedLengthMatchesHeader,
    AbsMeshCoordinatesNonNegative,
)


def register_rules() -> None:
    """Register the ``bvbs_abs`` rule set.

    Called from the module's startup hook rather than at import time, so
    importing the codec for a unit test does not mutate the process-global
    registry - a registry that grows on import answers differently depending
    on what a test session happened to import first.
    """
    for rule_class in RULES:
        rule_registry.register(rule_class(), rule_sets=[RULE_SET])


__all__ = [
    "LENGTH_TOLERANCE_MM",
    "LENGTH_TOLERANCE_RATIO",
    "RULES",
    "RULE_SET",
    "register_rules",
]
