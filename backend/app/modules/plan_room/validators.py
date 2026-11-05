# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan room validation rules (rule set ``plan_room``).

Rules run over a plain dict built by the service, one record under one key::

    {"pin": {"id", "page", "note", "photo_ref", "file_version_id"}}

Page and position bounds are already enforced by the request schema; these rules cover what a
site manager dropping a pin on a drawing would trip over.
"""

from __future__ import annotations

import re
import uuid

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, section
from app.core.validation.quality_rules import QualityRule

PLAN_ROOM_RULE_SET = "plan_room"

PIN_FIELDS = ("page", "note", "photo_ref", "file_version_id")

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
        if blank(pin.get("note")) and blank(pin.get("photo_ref")):
            return [self.fail(context, "pin_bare", ref=ref, page=pin.get("page") or "")]
        return [self.ok(ref)]


PLAN_ROOM_RULES = (PinPhotoRefRule, PinFileVersionRule, PinHasContentRule)


def register_plan_room_validation_rules() -> None:
    """Register the plan room rules with the platform rule registry."""
    for rule_class in PLAN_ROOM_RULES:
        rule_registry.register(rule_class(), [PLAN_ROOM_RULE_SET])


__all__ = ["PIN_FIELDS", "PLAN_ROOM_RULES", "PLAN_ROOM_RULE_SET", "register_plan_room_validation_rules"]
