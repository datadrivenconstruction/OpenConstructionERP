# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Neutral e-invoice lifecycle: deadlines, cancellation windows and allowed actions.

Nothing here names a country. Every duration, threshold and country rule id is
read from the ``lifecycle`` block of the country's mandate file (pack data under
``app/core/country_data/einvoice_mandates``). The module is pure: no session, no
I/O, the reference time is passed in, so the router, a background job and a
test all get the same answer.

Lifecycle block keys read here:

* ``deadlines``: list of ``{id, action: "submit", within_hours | within_days,
  from: "issued" | "invoice_date", applies_to?, warn?, rule_id?, effective_from?,
  condition?: {setting, gte | lte}}``.
* ``cancel``: ``{allowed?: false, within_hours, from: "validated" | "cleared"}``.
  ``validated`` is the authority's validation, which this model stores as
  ``cleared_at``.
* ``hash_chain``: ``{rule_id, applies_to?}``.
* ``identifier_required``: ``{rule_id, severity, after: [status, ...]}``.
* ``network``: ``{participant_field, rule_id}``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SEV_ERROR = "error"
SEV_WARNING = "warning"
SEV_INFO = "info"

CORE_MISSING_FIELD = "EINV-CORE-001"
CORE_DEADLINE_SOON = "EINV-CORE-003"
CORE_DEADLINE_PASSED = "EINV-CORE-004"
CORE_CANCEL_CLOSED = "EINV-CORE-005"
CORE_EXPORT_ONLY = "EINV-CORE-006"
CORE_OUTSIDE_PERIOD = "EINV-CORE-007"

# A deadline badge turns to warning when this share of the window is left.
WARN_FRACTION_LEFT = Decimal("0.25")

MODE_EXPORT = "export"
MODE_SANDBOX = "sandbox"
MODE_LIVE = "live"
MODES: tuple[str, ...] = (MODE_EXPORT, MODE_SANDBOX, MODE_LIVE)

# Lifecycle states shown to the user. ``queued`` and ``delivered`` are internal
# names the stepper folds into ``sent`` and ``accepted``.
PRE_SUBMIT_STATUSES = frozenset({"draft", "validated", "queued", "rejected"})
SENT_STATUSES = frozenset({"submitted"})
DONE_STATUSES = frozenset({"cleared", "reported", "delivered"})

ACTION_VALIDATE = "validate"
ACTION_SEND = "send"
ACTION_DOWNLOAD = "download"
ACTION_CANCEL = "cancel"
ACTION_CORRECT = "correct"
ACTION_CHECK_STATUS = "check_status"


@dataclass(frozen=True)
class Finding:
    """One lifecycle finding. ``params`` feed the i18n message on the client."""

    rule_id: str
    severity: str
    message: str
    params: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"rule_id": self.rule_id, "severity": self.severity, "message": self.message, "params": self.params}


@dataclass(frozen=True)
class Deadline:
    """A resolved deadline for one document."""

    id: str
    action: str
    starts_at: datetime
    due_at: datetime
    rule_id: str = ""
    warn: bool = True
    message: str = ""

    def state(self, now: datetime) -> str:
        """``ok``, ``warning`` (<= 25 % of the window left) or ``overdue``."""
        if now > self.due_at:
            return "overdue"
        total = (self.due_at - self.starts_at).total_seconds()
        left = (self.due_at - now).total_seconds()
        if total > 0 and Decimal(str(left)) <= WARN_FRACTION_LEFT * Decimal(str(total)):
            return "warning"
        return "ok"

    def as_dict(self, now: datetime) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "starts_at": self.starts_at.isoformat(),
            "due_at": self.due_at.isoformat(),
            "state": self.state(now),
            "seconds_left": int((self.due_at - now).total_seconds()),
        }


def parse_time(value: Any) -> datetime | None:
    """Read a datetime, ISO string or date. Naive values are UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, date):
        stamp = datetime(value.year, value.month, value.day)
    else:
        raw = str(value).strip()
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=UTC)


def _dec(value: Any) -> Decimal | None:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return out if out.is_finite() else None


def condition_holds(condition: dict[str, Any] | None, settings: dict[str, Any]) -> bool:
    """Whether a ``{setting, gte | lte}`` condition holds for the seller's settings.

    A missing setting fails the condition: a threshold rule that cannot be
    decided is not applied, and the rule's own finding says nothing false.
    """
    if not condition:
        return True
    value = _dec(settings.get(str(condition.get("setting") or "")))
    if value is None:
        return False
    if "gte" in condition and value < (_dec(condition["gte"]) or Decimal("0")):
        return False
    return not ("lte" in condition and value > (_dec(condition["lte"]) or Decimal("0")))


def _kind(document: dict[str, Any]) -> str:
    return str(document.get("document_kind") or "standard")


def _applies(rule: dict[str, Any], document: dict[str, Any]) -> bool:
    kinds = rule.get("applies_to")
    return not kinds or _kind(document) in kinds


def issued_at(document: dict[str, Any]) -> datetime | None:
    fields = document.get("country_fields") or {}
    return parse_time(fields.get("issued_at")) or parse_time(document.get("invoice_date"))


def _zone(name: Any) -> ZoneInfo | None:
    try:
        return ZoneInfo(str(name)) if name else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


def resolve_deadlines(
    lifecycle: dict[str, Any], document: dict[str, Any], settings: dict[str, Any] | None = None
) -> list[Deadline]:
    """Every submit deadline that applies to this document, earliest first."""
    settings = settings or {}
    issued = issued_at(document)
    out: list[Deadline] = []
    for rule in lifecycle.get("deadlines") or []:
        if rule.get("action", "submit") != "submit" or not _applies(rule, document):
            continue
        if not condition_holds(rule.get("condition"), settings):
            continue
        start = issued if rule.get("from", "issued") in ("issued", "invoice_date") else None
        if start is None:
            continue
        calendar_days = rule.get("from") == "invoice_date" and rule.get("within_days") is not None
        if rule.get("from") == "invoice_date":
            start = datetime(start.year, start.month, start.day, tzinfo=_zone(rule.get("timezone")) or start.tzinfo)
        effective = parse_time(rule.get("effective_from"))
        if effective is not None and start < effective:
            continue
        if rule.get("within_hours") is not None:
            span = timedelta(hours=float(rule["within_hours"]))
            due = start + span
        elif rule.get("within_days") is not None:
            # Whole calendar days in the jurisdiction's zone: day N stays open until its local midnight ends.
            days = int(rule["within_days"]) + (1 if calendar_days else 0)
            span = None
            due = (start.replace(tzinfo=None) + timedelta(days=days)).replace(tzinfo=start.tzinfo)
        else:
            continue
        out.append(
            Deadline(
                id=str(rule.get("id") or "submit"),
                action="submit",
                starts_at=start,
                due_at=due,
                rule_id=str(rule.get("rule_id") or ""),
                warn=bool(rule.get("warn", True)),
                message=str(rule.get("message") or ""),
            )
        )
    return sorted(out, key=lambda d: d.due_at)


def cancel_deadline(lifecycle: dict[str, Any], document: dict[str, Any]) -> Deadline | None:
    rule = lifecycle.get("cancel") or {}
    if not rule or rule.get("allowed") is False or rule.get("within_hours") is None:
        return None
    start = parse_time(document.get("cleared_at")) or parse_time(document.get("submitted_at"))
    if start is None:
        return None
    return Deadline(
        id="cancel",
        action="cancel",
        starts_at=start,
        due_at=start + timedelta(hours=float(rule["within_hours"])),
        rule_id=CORE_CANCEL_CLOSED,
    )


def _hours(seconds: float) -> str:
    return f"{Decimal(str(seconds / 3600)).quantize(Decimal('0.1'))}".rstrip("0").rstrip(".")


def evaluate(
    regime: dict[str, Any],
    document: dict[str, Any],
    *,
    profile: dict[str, Any] | None = None,
    intent: str = "save",
    now: datetime | None = None,
) -> list[Finding]:
    """All lifecycle findings for a document, against its country's lifecycle block."""
    profile = profile or {}
    lifecycle = regime.get("lifecycle") or {}
    settings = profile.get("settings") or {}
    now = now or datetime.now(UTC)
    status = str(document.get("status") or "draft")
    number = str(document.get("invoice_number") or "")
    platform = str(regime.get("platform") or "")
    found: list[Finding] = []

    if status in PRE_SUBMIT_STATUSES:
        for deadline in resolve_deadlines(lifecycle, document, settings):
            state = deadline.state(now)
            if state == "overdue":
                rule_id = deadline.rule_id or CORE_DEADLINE_PASSED
                found.append(
                    Finding(
                        rule_id,
                        SEV_ERROR,
                        deadline.message
                        or f"Submission deadline passed on {deadline.due_at.date().isoformat()}; issue a correction instead.",
                        {"date": deadline.due_at.isoformat(), "no": number, "deadline": deadline.id},
                    )
                )
            elif state == "warning" and deadline.warn:
                left = _hours((deadline.due_at - now).total_seconds())
                found.append(
                    Finding(
                        CORE_DEADLINE_SOON,
                        SEV_WARNING,
                        f"Submission deadline in {left} h for invoice {number}.",
                        {"n": left, "no": number, "date": deadline.due_at.isoformat()},
                    )
                )

    chain = lifecycle.get("hash_chain") or {}
    if chain and _applies(chain, document) and not str(document.get("previous_hash") or "").strip():
        found.append(
            Finding(
                str(chain.get("rule_id") or CORE_MISSING_FIELD),
                SEV_ERROR,
                "Previous invoice hash missing; the hash chain is broken.",
                {"no": number},
            )
        )

    ident = lifecycle.get("identifier_required") or {}
    if ident and status in set(ident.get("after") or ()) and not str(document.get("authority_identifier") or ""):
        found.append(
            Finding(
                str(ident.get("rule_id") or CORE_MISSING_FIELD),
                str(ident.get("severity") or SEV_WARNING),
                f"{regime.get('identifier_label') or 'Authority identifier'} missing; invoice not legally issued.",
                {"no": number},
            )
        )

    network = lifecycle.get("network") or {}
    # Only a registration that sends over the network itself (sandbox or live)
    # needs the buyer's participant id; legacy and export registrations route elsewhere.
    if network and intent == "submit" and profile.get("mode") in (MODE_SANDBOX, MODE_LIVE):
        field_name = str(network.get("participant_field") or "buyer_endpoint_id")
        if not str((document.get("country_fields") or {}).get(field_name) or "").strip():
            found.append(
                Finding(
                    str(network.get("rule_id") or CORE_MISSING_FIELD),
                    SEV_ERROR,
                    "Buyer has no network participant id; cannot send via network.",
                    {"field": field_name},
                )
            )

    if intent == "cancel":
        cancel = lifecycle.get("cancel") or {}
        correction = str(regime.get("correction_mechanism") or "a correcting document")
        if cancel.get("allowed") is False:
            found.append(
                Finding(
                    CORE_CANCEL_CLOSED,
                    SEV_ERROR,
                    f"Cancellation is not available; use {correction}.",
                    {"date": "", "correction_mechanism": correction},
                )
            )
        else:
            deadline = cancel_deadline(lifecycle, document)
            if deadline is not None and now > deadline.due_at:
                found.append(
                    Finding(
                        CORE_CANCEL_CLOSED,
                        SEV_ERROR,
                        f"Cancellation window closed on {deadline.due_at.isoformat()}; use {correction}.",
                        {"date": deadline.due_at.isoformat(), "correction_mechanism": correction},
                    )
                )

    if profile.get("mode") == MODE_EXPORT:
        found.append(
            Finding(
                CORE_EXPORT_ONLY,
                SEV_INFO,
                f"Adapter mode is export: file ready, not sent to {platform}.",
                {"platform": platform},
            )
        )
    return found


def can_cancel(regime: dict[str, Any]) -> bool:
    cancel = (regime.get("lifecycle") or {}).get("cancel") or {}
    if cancel.get("allowed") is False:
        return False
    return bool(cancel) or regime.get("cancellation_window_days") is not None


def allowed_actions(
    regime: dict[str, Any], document: dict[str, Any], profile: dict[str, Any] | None = None
) -> list[str]:
    """The actions the card offers, primary first. Download is always last."""
    profile = profile or {}
    status = str(document.get("status") or "draft")
    mode = str(profile.get("mode") or "")
    actions: list[str] = []
    if status in ("draft", "rejected"):
        actions.append(ACTION_VALIDATE)
    if status in ("validated", "queued") and mode != MODE_EXPORT:
        actions.append(ACTION_SEND)
    if status == "submitted":
        actions.append(ACTION_CHECK_STATUS)
    if status in DONE_STATUSES:
        actions.append(ACTION_CANCEL if can_cancel(regime) else ACTION_CORRECT)
    actions.append(ACTION_DOWNLOAD)
    return actions


def blocking(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == SEV_ERROR]


__all__ = [
    "CORE_CANCEL_CLOSED",
    "CORE_DEADLINE_PASSED",
    "CORE_DEADLINE_SOON",
    "CORE_EXPORT_ONLY",
    "CORE_MISSING_FIELD",
    "CORE_OUTSIDE_PERIOD",
    "MODES",
    "MODE_EXPORT",
    "MODE_LIVE",
    "MODE_SANDBOX",
    "Deadline",
    "Finding",
    "allowed_actions",
    "blocking",
    "cancel_deadline",
    "condition_holds",
    "evaluate",
    "parse_time",
    "resolve_deadlines",
]
