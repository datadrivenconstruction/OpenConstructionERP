# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Meetings validation rules.

Ships two first-class rules registered with the platform rule registry so the
meetings module honours the "no module without validation" principle:

* ``MeetingActionOwnershipRule`` (ERROR) - a tracked action item must have an
  owner and a due date, otherwise it cannot be followed up.
* ``MeetingMinutesReadyRule`` (ERROR) - minutes cannot be issued while a
  required agenda item is unaddressed or no attendee is marked present.
* ``MeetingRecordingConsentRule`` (ERROR) - stored audio or live speech capture
  needs the participants' recorded consent.
* ``MeetingAudioRetentionRule`` (WARNING) - audio must not outlive its
  retention window.
* ``MeetingProposalsReviewedRule`` (WARNING) - AI proposals from a recording
  should all be confirmed or rejected before the minutes go out.

The rules run against a plain dict context (no ORM), so they stay pure and are
trivially unit-testable. The service layer enforces the same pure checks
(:mod:`app.modules.meetings.logic`) at the API boundary by raising HTTP 422, so
bad data is blocked, not merely flagged.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.meetings.audio_logic import audio_overdue, consent_required, proposal_counts
from app.modules.meetings.logic import minutes_issue_problems, validate_action_fields

logger = logging.getLogger(__name__)


def _actions(context: ValidationContext) -> list[dict[str, Any]]:
    data = context.data
    if isinstance(data, dict):
        items = data.get("action_items", [])
        return [a for a in items if isinstance(a, dict)]
    if isinstance(data, list):
        return [a for a in data if isinstance(a, dict)]
    return []


def _minutes_content(context: ValidationContext) -> dict[str, Any]:
    data = context.data
    if isinstance(data, dict):
        content = data.get("content")
        if isinstance(content, dict):
            return content
        return data
    return {}


class MeetingActionOwnershipRule(ValidationRule):
    """Every tracked action item must have an owner and a due date."""

    rule_id = "meetings.action_ownership"
    name = "Action item has an owner and a due date"
    standard = "meetings"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "A tracked action item needs an owner and a due date so it can be followed up"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for idx, action in enumerate(_actions(context)):
            problems = validate_action_fields(
                action.get("owner_id"),
                action.get("owner_name"),
                action.get("due_date"),
                action.get("status"),
            )
            passed = not problems
            label = str(action.get("description") or f"action {idx + 1}")[:80]
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK" if passed else f"'{label}': {' '.join(problems)}",
                    element_ref=str(action.get("id") or ""),
                    suggestion=None if passed else "Set an owner and a due date on the action item",
                )
            )
        return results


class MeetingMinutesReadyRule(ValidationRule):
    """Minutes cannot be issued while a required agenda item is unaddressed."""

    rule_id = "meetings.minutes_ready"
    name = "Minutes are ready to issue"
    standard = "meetings"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Every required agenda item must have a discussion or decision before minutes are issued"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        problems = minutes_issue_problems(_minutes_content(context))
        if not problems:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message="OK",
                )
            ]
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message=problem,
                suggestion="Record the discussion or decision, then issue the minutes",
            )
            for problem in problems
        ]


def _recordings(context: ValidationContext) -> list[dict[str, Any]]:
    data = context.data
    if isinstance(data, dict):
        items = data.get("recordings", [])
        return [r for r in items if isinstance(r, dict)] if isinstance(items, list) else []
    return []


def _has_audio(rec: dict[str, Any]) -> bool:
    return bool(rec.get("audio_storage_key") or rec.get("has_audio"))


class _RecordingRule(ValidationRule):
    """Shared result builder for the per-recording rules."""

    def _result(self, rec: dict[str, Any], passed: bool, message: str, suggestion: str | None) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message="OK" if passed else message,
            element_ref=str(rec.get("id") or ""),
            suggestion=None if passed else suggestion,
        )


class MeetingRecordingConsentRule(_RecordingRule):
    """Stored audio and live speech capture need the participants' consent."""

    rule_id = "meetings.recording_consent"
    name = "Recording has the participants' consent"
    standard = "meetings"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "A meeting recording may only exist when the participants were told and agreed"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for rec in _recordings(context):
            needed = consent_required(str(rec.get("source") or ""), _has_audio(rec))
            passed = not needed or bool(rec.get("consent_confirmed_at"))
            results.append(
                self._result(
                    rec,
                    passed,
                    "The recording has no recorded consent of the participants.",
                    "Delete the audio, or record the consent before keeping it",
                )
            )
        return results


class MeetingAudioRetentionRule(_RecordingRule):
    """Audio is deleted once its retention window has passed."""

    rule_id = "meetings.audio_retention"
    name = "Meeting audio is within its retention window"
    standard = "meetings"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Recorded audio should not be kept past the retention period that was set for it"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        now = datetime.now(UTC)
        return [
            self._result(
                rec,
                not audio_overdue(rec, now),
                "The audio is kept past its retention date.",
                "Delete the audio; the transcript and minutes stay",
            )
            for rec in _recordings(context)
        ]


class MeetingProposalsReviewedRule(_RecordingRule):
    """Every AI proposal from a recording is confirmed or rejected."""

    rule_id = "meetings.proposals_reviewed"
    name = "Proposals from the recording are reviewed"
    standard = "meetings"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Summary, decisions and actions proposed from a recording need a person's confirmation"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for rec in _recordings(context):
            pending = proposal_counts(rec.get("proposals") or {}).get("pending", 0)
            results.append(
                self._result(
                    rec,
                    pending == 0,
                    f"{pending} proposal(s) from the recording are not reviewed yet.",
                    "Confirm or reject each proposal before issuing the minutes",
                )
            )
        return results


def register_meetings_validation_rules() -> None:
    """Register the meetings rules with the platform rule registry."""
    rule_registry.register(MeetingActionOwnershipRule(), ["meetings"])
    rule_registry.register(MeetingMinutesReadyRule(), ["meetings"])
    rule_registry.register(MeetingRecordingConsentRule(), ["meetings"])
    rule_registry.register(MeetingAudioRetentionRule(), ["meetings"])
    rule_registry.register(MeetingProposalsReviewedRule(), ["meetings"])
    logger.debug("meetings: registered 5 validation rules")
