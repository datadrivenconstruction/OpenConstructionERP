# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan room validation rules (rule set ``plan_room``).

Rules run over a plain dict built by the service, one record under one key::

    {"pin": {"id", "page", "note", "photo_ref", "file_version_id", "target_kind", "target_id", "x", "y", ...}}

Besides the stored fields the service puts the facts it looked up into the dict (``target_found``,
``page_count``, ``bim_element_found``, ``sheet_superseded``, ``target_closed``), because a rule never
touches the database. These rules cover what a site manager dropping a pin on a drawing would trip over.
"""

from __future__ import annotations

import re
import uuid

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, section
from app.core.validation.quality_rules import QualityRule

PLAN_ROOM_RULE_SET = "plan_room"

PIN_FIELDS = (
    "page",
    "note",
    "photo_ref",
    "file_version_id",
    "target_kind",
    "target_id",
    "x",
    "y",
    "document_id",
    "bim_element_id",
    "target_found",
    "page_count",
    "bim_element_found",
    "sheet_superseded",
    "target_closed",
)

_LOCAL_PATH = re.compile(r"^(?:[A-Za-z]:|file:|[/\\])")


class _PlanRoomRule(QualityRule):
    standard = PLAN_ROOM_RULE_SET
    message_section = "plan_room"


class PinPhotoRefRule(_PlanRoomRule):
    """A pin's photo is a stored reference, never a path on someone's machine."""

    rule_id = "plan_room.pin_photo_ref"
    name = "Pin photo reference is a stored reference"
    description = "photo_ref must not be a local, absolute or parent-directory path"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        pin = section(context, "pin")
        ref = str(pin.get("id", ""))
        raw = pin.get("photo_ref")
        if not blank(raw):
            text = str(raw).strip()
            if _LOCAL_PATH.match(text) or ".." in re.split(r"[/\\]", text):
                return [self.fail(context, "photo_ref_path", ref=ref, photo=text)]
        return [self.ok(ref)]


class PinFileVersionRule(_PlanRoomRule):
    """The file version a pin is bound to is a real version id."""

    rule_id = "plan_room.pin_file_version"
    name = "Pin file version is a version id"
    description = "file_version_id, when given, must be a UUID"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        pin = section(context, "pin")
        ref = str(pin.get("id", ""))
        raw = pin.get("file_version_id")
        if not blank(raw):
            try:
                uuid.UUID(str(raw).strip())
            except ValueError:
                return [self.fail(context, "file_version_invalid", ref=ref, version=str(raw).strip())]
        return [self.ok(ref)]


class PinHasContentRule(_PlanRoomRule):
    """A pin says what was found: a note, a photo, or both."""

    rule_id = "plan_room.pin_has_content"
    name = "Pin carries a note or a photo"
    severity = Severity.WARNING
    description = "a pin should have a note or a photo_ref"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        pin = section(context, "pin")
        ref = str(pin.get("id", ""))
        if pin.get("target_kind") not in (None, "", "note"):
            return [self.ok(ref)]
        if blank(pin.get("note")) and blank(pin.get("photo_ref")):
            return [self.fail(context, "pin_bare", ref=ref, page=pin.get("page") or "")]
        return [self.ok(ref)]


def _has_drawing(pin: dict) -> bool:
    return not blank(pin.get("document_id"))


def _has_bim(pin: dict) -> bool:
    return not blank(pin.get("bim_element_id"))


class PinPositionRule(_PlanRoomRule):
    """A drawing pin sits on the sheet: x and y are fractions of its width and height."""

    rule_id = "plan_room.pin_position"
    name = "Pin position is on the sheet"
    description = "x and y must lie within 0..1 of the sheet"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        pin = section(context, "pin")
        ref = str(pin.get("id", ""))
        if _has_drawing(pin):
            for axis in ("x", "y"):
                try:
                    value = float(pin.get(axis))  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    return [self.fail(context, "position_out_of_range", ref=ref, axis=axis, value=str(pin.get(axis)))]
                if not 0.0 <= value <= 1.0:
                    return [self.fail(context, "position_out_of_range", ref=ref, axis=axis, value=str(value))]
        return [self.ok(ref)]


class PinPageRule(_PlanRoomRule):
    """The page exists in the document the pin is dropped on."""

    rule_id = "plan_room.pin_page"
    name = "Pin page exists in the document"
    description = "page must not exceed the number of sheets registered for the document"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        pin = section(context, "pin")
        ref = str(pin.get("id", ""))
        count = pin.get("page_count")
        if _has_drawing(pin) and isinstance(count, int) and count > 0:
            page = pin.get("page") or 1
            if int(page) > count:
                return [self.fail(context, "page_out_of_range", ref=ref, page=page, count=count)]
        return [self.ok(ref)]


class PinTargetRule(_PlanRoomRule):
    """A record pin points at a record of the same project."""

    rule_id = "plan_room.pin_target"
    name = "Pin target exists in the project"
    description = "target_id must name an existing record of the same project"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        pin = section(context, "pin")
        ref = str(pin.get("id", ""))
        kind = pin.get("target_kind") or "note"
        if kind == "note":
            return [self.ok(ref)]
        if blank(pin.get("target_id")):
            return [self.fail(context, "target_missing", ref=ref, kind=kind)]
        if pin.get("target_found") is False:
            return [self.fail(context, "target_not_found", ref=ref, kind=kind, target=str(pin.get("target_id")))]
        return [self.ok(ref)]


class PinOneLocationRule(_PlanRoomRule):
    """A pin is either on a drawing page or on a BIM element, never both and never neither."""

    rule_id = "plan_room.pin_one_location"
    name = "Pin has exactly one location"
    description = "drawing (document and page) XOR BIM element"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        pin = section(context, "pin")
        ref = str(pin.get("id", ""))
        drawing, bim = _has_drawing(pin), _has_bim(pin)
        if drawing and bim:
            return [self.fail(context, "location_ambiguous", ref=ref)]
        if not drawing and not bim:
            return [self.fail(context, "location_missing", ref=ref)]
        return [self.ok(ref)]


class PinBimElementRule(_PlanRoomRule):
    """A model pin sits on an element of a model that belongs to the same project."""

    rule_id = "plan_room.pin_bim_element"
    name = "Pin BIM element is in the project"
    description = "bim_element_id must belong to a model of the same project"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        pin = section(context, "pin")
        ref = str(pin.get("id", ""))
        if _has_bim(pin) and pin.get("bim_element_found") is False:
            return [self.fail(context, "bim_element_not_found", ref=ref, element=str(pin.get("bim_element_id")))]
        return [self.ok(ref)]


class PinSupersededRevisionRule(_PlanRoomRule):
    """A pin on a superseded sheet revision is a pin on a drawing nobody builds from."""

    rule_id = "plan_room.pin_superseded_revision"
    name = "Pin is on the current revision"
    severity = Severity.WARNING
    description = "the sheet the pin sits on has a newer revision"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        pin = section(context, "pin")
        ref = str(pin.get("id", ""))
        if pin.get("sheet_superseded") is True:
            return [self.fail(context, "superseded_revision", ref=ref)]
        return [self.ok(ref)]


class PinClosedRecordRule(_PlanRoomRule):
    """A closed record does not need a live pin on the drawing."""

    rule_id = "plan_room.pin_closed_record"
    name = "Pin record is still open"
    severity = Severity.WARNING
    description = "the record the pin points at is already closed"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        pin = section(context, "pin")
        ref = str(pin.get("id", ""))
        if pin.get("target_closed") is True:
            return [self.fail(context, "record_closed", ref=ref, kind=str(pin.get("target_kind")))]
        return [self.ok(ref)]


PLAN_ROOM_RULES = (
    PinPhotoRefRule,
    PinFileVersionRule,
    PinHasContentRule,
    PinPositionRule,
    PinPageRule,
    PinTargetRule,
    PinOneLocationRule,
    PinBimElementRule,
    PinSupersededRevisionRule,
    PinClosedRecordRule,
)


def register_plan_room_validation_rules() -> None:
    """Register the plan room rules with the platform rule registry."""
    for rule_class in PLAN_ROOM_RULES:
        rule_registry.register(rule_class(), [PLAN_ROOM_RULE_SET])


__all__ = ["PIN_FIELDS", "PLAN_ROOM_RULES", "PLAN_ROOM_RULE_SET", "register_plan_room_validation_rules"]
