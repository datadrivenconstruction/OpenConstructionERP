"""‌⁠‍Notification templates — English fallback strings for every notification.

Notifications are stored with i18n keys (``title_key`` + ``body_key``) so
the frontend can translate them. But translation can fail silently for
several reasons:

* the locale file doesn't have the key (most non-English locales);
* the bell renders in a Suspense fallback before i18n hydration;
* a third-party module emits a key the platform doesn't recognise.

When that happens the user used to see the raw key string
("notifications.rfi.assigned") in the bell — confusing and unprofessional.

This module is the **server-side English source of truth** for every
notification template the platform emits. The schema layer
(``NotificationResponse``) interpolates the matching template with the
notification's ``body_context`` and returns it as ``title_default`` /
``body_default`` so the frontend always has a sane fallback even when
i18n misses.

Adding a new notification:
    1. Pick the i18n key (use ``notifications.<module>.<event>.title`` /
       ``.body`` convention).
    2. Add an entry here with the matching template string.
    3. Wire the i18n key into ``frontend/src/app/locales/en.ts`` and
       any other locale you want to support.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── Template registry ────────────────────────────────────────────────────
#
# Each entry is ``i18n_key → English template`` with ``{name}``-style
# placeholders. The placeholder names must match the keys the event
# subscriber puts into ``body_context``. Mismatch is logged at debug
# but never raises — an empty placeholder is preferable to a 500.
#
# Keep templates short and concrete: bell rows truncate at ~50 chars
# for the title and ~80 chars for the body.

_TEMPLATES: dict[str, str] = {
    # ── BOQ ──────────────────────────────────────────────────────────
    "notifications.boq.created.title": "BOQ created",
    "notifications.boq.created.body": "Your bill of quantities '{boq_name}' was saved.",
    # ── Meetings ─────────────────────────────────────────────────────
    "notifications.meeting.action_assigned.title": "Action item assigned to you",
    "notifications.meeting.action_assigned.body": "From meeting {meeting_number}: {description}",
    # ── CDE ──────────────────────────────────────────────────────────
    "notifications.cde.state_transitioned.title": "Document state changed",
    "notifications.cde.state_transitioned.body": "Container moved to '{new_state}'.",
    # ── RFIs ─────────────────────────────────────────────────────────
    "notifications.rfi.assigned.title": "RFI assigned to you",
    "notifications.rfi.assigned.body": "{code} — {title}",
    "notifications.rfi.responded.title": "RFI answered",
    "notifications.rfi.responded.body": "Your request {code} ({title}) has a response.",
    # ── Risks ────────────────────────────────────────────────────────
    "notifications.risk.assigned.title": "Risk assigned to you",
    "notifications.risk.assigned.body": "{code} — {title}",
    # ── Submittals ───────────────────────────────────────────────────
    "notifications.submittal.submitted.title": "Submittal awaiting review",
    "notifications.submittal.submitted.body": "{code} — {title}",
    "notifications.submittal.approved.title": "Submittal approved",
    "notifications.submittal.approved.body": "{code} — {title}",
    "notifications.submittal.rejected.title": "Submittal rejected",
    "notifications.submittal.rejected.body": "{code} ({title}). Reason: {reason}",
    "notifications.submittal.revise_resubmit.title": "Submittal needs revision",
    "notifications.submittal.revise_resubmit.body": "{code} ({title}). Reason: {reason}",
    # ── Transmittals ─────────────────────────────────────────────────
    "notifications.transmittal.issued.title": "Transmittal issued to you",
    "notifications.transmittal.issued.body": "{code} — {title}",
    "notifications.transmittal.acknowledged.title": "Transmittal acknowledged",
    "notifications.transmittal.acknowledged.body": "Recipient confirmed {code} ({title}).",
    "notifications.transmittal.responded.title": "Transmittal answered",
    "notifications.transmittal.responded.body": "{code} ({title}). {response_summary}",
    # ── Singular-namespace keys (event_handlers.py — Wave 5+) ────────
    # These use the `notification.<event>_(title|body)` convention,
    # distinct from the older `notifications.<module>.<event>.(title|body)`
    # entries above. Keep both naming conventions until the legacy
    # subscribers are migrated.
    "notification.rfi_assigned_title": "RFI assigned to you",
    "notification.rfi_assigned_body": "RFI {rfi_number} — {subject}",
    "notification.task_assigned_title": "New task assigned",
    "notification.task_assigned_body": "{task_title}",
    "notification.invoice_approved_title": "Invoice approved",
    "notification.invoice_approved_body": "Invoice {invoice_number} — {amount_total} {currency_code}",
    "notification.inspection_scheduled_title": "Inspection scheduled",
    "notification.inspection_scheduled_body": "{inspection_number} — {title} on {inspection_date}",
    "notification.submittal_status_changed_title": "Submittal status changed",
    "notification.submittal_status_changed_body": "{submittal_number} ({title}) — {new_status}",
    "notification.meeting_scheduled_title": "Meeting scheduled",
    "notification.meeting_scheduled_body": "{title} on {meeting_date}",
    "notification.ncr_created_title": "Non-conformance raised",
    "notification.ncr_created_body": "NCR {ncr_number} — {title} ({severity})",
    "notification.document_uploaded_title": "Document uploaded",
    "notification.document_uploaded_body": "{document_name}",
    # ── File comments (Epic B / B1) ──────────────────────────────────
    "notifications.file_comments.mention.title": "You were mentioned in a comment",
    "notifications.file_comments.mention.body": '"{excerpt}"',
    # ── Digests (Epic B / B3) ────────────────────────────────────────
    "notifications.digest.title": "Notification digest",
    "notifications.digest.body": "You have {count} new updates on the {channel} channel.",
}


# ── notification_type → frontend icon category map ───────────────────────
#
# The frontend's icon palette only knows seven categories
# (success/error/warning/info/import/validation/system). Each backend
# ``notification_type`` is mapped here so the bell can pick a meaningful
# icon instead of falling back to a generic Info.
#
# This mapping is intentionally on the backend so the frontend doesn't
# need to know about every event type — it just reads ``icon_category``
# off the API response.

_TYPE_TO_ICON: dict[str, str] = {
    # Generic
    "info": "info",
    "system": "system",
    # Assignments — a person now owes something
    "task_assigned": "warning",
    "rfi_assigned": "warning",
    "risk_assigned": "warning",
    "transmittal_issued": "warning",
    "submittal_submitted": "warning",
    # Approvals / acknowledgements — positive
    "submittal_approved": "success",
    "transmittal_acknowledged": "success",
    # Rejections / errors — negative
    "submittal_rejected": "error",
    "submittal_revise_resubmit": "error",
    # Responses — neutral inbound
    "rfi_responded": "info",
    "transmittal_responded": "info",
    # File comment mention (Epic B / B1)
    "file_comment_mention": "info",
}


# ── Public helpers ───────────────────────────────────────────────────────


def render(key: str | None, context: dict[str, Any] | None = None) -> str:
    """‌⁠‍Return the English string for an i18n key with placeholders filled.

    Resolution order:
        1. Template from :data:`_TEMPLATES` interpolated with ``context``.
        2. Template raw (if interpolation fails because a placeholder is
           missing — the user still sees something coherent).
        3. The key itself (so missing entries are visible during dev
           rather than rendering as an empty string in the bell).

    Never raises — notification rendering is a hot path, a malformed
    template must not surface as a 500 to the user.
    """
    if not key:
        return ""
    template = _TEMPLATES.get(key)
    if template is None:
        # Unknown key — log once at debug so a new template gets added,
        # but show the key string so the user has *something* to read.
        logger.debug("notifications.templates: no template for key=%r", key)
        return key
    if not context:
        return template
    try:
        return template.format(**context)
    except (KeyError, IndexError, ValueError) as exc:
        # Placeholder mismatch (event payload changed shape) — surface
        # the un-interpolated template so the user sees readable text
        # instead of a half-substituted string.
        logger.debug(
            "notifications.templates: interpolation failed for key=%r: %s",
            key,
            exc,
        )
        return template


def icon_category_for(notification_type: str | None) -> str:
    """‌⁠‍Map a backend ``notification_type`` to a frontend icon category.

    Returns ``"info"`` for unknown types so the bell never crashes on a
    third-party module that invented its own type.
    """
    if not notification_type:
        return "info"
    return _TYPE_TO_ICON.get(notification_type, "info")


def all_template_keys() -> list[str]:
    """Return every known i18n key — used by tests + the i18n audit."""
    return sorted(_TEMPLATES.keys())
