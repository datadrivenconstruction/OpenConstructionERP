"""CRM PII-redaction unit tests (R7 audit).

Covers the response-boundary redaction layer that hides ``contact_email``
/ ``contact_phone`` from non-owner viewers:

  * owners (lead.assigned_to == viewer_id) → full email + full phone
  * admins / managers                       → full email + full phone
  * editors / viewers other than the owner  → ``j***@example.com`` / ``+49…567``
  * missing email / phone                   → ``None`` (NOT the log label
    ``<no-email>`` — that string must never leak into JSON responses).

The redaction layer is pure (no DB), so these tests run as unit tests.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.modules.crm.service import (
    _redact_email,
    _redact_email_response,
    _redact_phone,
    _redact_phone_response,
    _safe_lead_label,
    redact_lead_pii,
    viewer_can_see_lead_pii,
)

# ── Helpers ───────────────────────────────────────────────────────────────


def _make_lead(
    *,
    assigned_to: uuid.UUID | None = None,
    email: str | None = "alice@example.com",
    phone: str | None = "+491701234567",
    name: str = "Alice Beispiel",
) -> SimpleNamespace:
    """Build a stub lead that quacks like the SQLAlchemy row."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        contact_name=name,
        contact_email=email,
        contact_phone=phone,
        assigned_to=assigned_to,
        status="new",
    )


# ── Log-boundary redaction (kept for audit-trail use) ─────────────────────


def test_log_email_redact_keeps_first_initial_and_domain():
    assert _redact_email("alice@example.com") == "a***@example.com"


def test_log_email_redact_short_local_part():
    assert _redact_email("a@x.io") == "a***@x.io"


def test_log_email_redact_handles_missing():
    assert _redact_email(None) == "<no-email>"
    assert _redact_email("") == "<no-email>"


def test_log_email_redact_handles_garbage():
    assert _redact_email("not-an-email") == "<redacted>"


def test_log_phone_redact_e164():
    # +49 1701234567 → +49…567 (dial-code + last 3 digits)
    assert _redact_phone("+491701234567") == "+49…567"


def test_log_phone_redact_local():
    assert _redact_phone("01701234567") == "01…567"


def test_log_phone_redact_handles_missing():
    assert _redact_phone(None) == "<no-phone>"
    assert _redact_phone("") == "<no-phone>"


def test_log_phone_redact_too_short():
    assert _redact_phone("123") == "<redacted>"


# ── Response-safe redaction (never returns a placeholder label) ──────────


def test_response_email_redact_returns_none_on_missing():
    """The response variant must NOT echo ``<no-email>`` into JSON."""
    assert _redact_email_response(None) is None
    assert _redact_email_response("") is None
    assert _redact_email_response("garbage-no-at-sign") is None


def test_response_email_redact_masks_local_part():
    assert _redact_email_response("alice@example.com") == "a***@example.com"


def test_response_phone_redact_returns_none_on_missing():
    assert _redact_phone_response(None) is None
    assert _redact_phone_response("") is None
    assert _redact_phone_response("12") is None  # too short


def test_response_phone_redact_keeps_dialcode_and_tail():
    assert _redact_phone_response("+491701234567") == "+49…567"


# ── Viewer-aware ownership check ──────────────────────────────────────────


def test_viewer_is_owner_sees_full_pii():
    owner = uuid.uuid4()
    lead = _make_lead(assigned_to=owner)
    assert (
        viewer_can_see_lead_pii(
            lead,
            viewer_id=str(owner),
            viewer_role="editor",
        )
        is True
    )


def test_admin_sees_full_pii_regardless_of_owner():
    lead = _make_lead(assigned_to=uuid.uuid4())
    assert (
        viewer_can_see_lead_pii(
            lead,
            viewer_id=str(uuid.uuid4()),
            viewer_role="admin",
        )
        is True
    )


def test_manager_sees_full_pii_regardless_of_owner():
    lead = _make_lead(assigned_to=uuid.uuid4())
    assert (
        viewer_can_see_lead_pii(
            lead,
            viewer_id=str(uuid.uuid4()),
            viewer_role="manager",
        )
        is True
    )


def test_editor_who_is_not_owner_cannot_see_pii():
    lead = _make_lead(assigned_to=uuid.uuid4())
    assert (
        viewer_can_see_lead_pii(
            lead,
            viewer_id=str(uuid.uuid4()),
            viewer_role="editor",
        )
        is False
    )


def test_unassigned_lead_hides_pii_from_non_admin():
    lead = _make_lead(assigned_to=None)
    assert (
        viewer_can_see_lead_pii(
            lead,
            viewer_id=str(uuid.uuid4()),
            viewer_role="viewer",
        )
        is False
    )


# ── End-to-end response redaction ─────────────────────────────────────────


def test_redact_lead_pii_owner_round_trip():
    owner = uuid.uuid4()
    lead = _make_lead(assigned_to=owner)
    email, phone = redact_lead_pii(
        lead,
        viewer_id=str(owner),
        viewer_role="editor",
    )
    assert email == "alice@example.com"
    assert phone == "+491701234567"


def test_redact_lead_pii_non_owner_redacts_both_fields():
    lead = _make_lead(assigned_to=uuid.uuid4())
    email, phone = redact_lead_pii(
        lead,
        viewer_id=str(uuid.uuid4()),
        viewer_role="editor",
    )
    assert email == "a***@example.com"
    assert phone == "+49…567"


def test_redact_lead_pii_non_owner_with_missing_fields_returns_none():
    """Non-owner viewing a lead with no PII gets None, not ``<no-email>``."""
    lead = _make_lead(
        assigned_to=uuid.uuid4(),
        email=None,
        phone=None,
    )
    email, phone = redact_lead_pii(
        lead,
        viewer_id=str(uuid.uuid4()),
        viewer_role="viewer",
    )
    assert email is None
    assert phone is None


def test_redact_lead_pii_anonymous_viewer():
    """No JWT → no PII. Belt-and-braces: this path is also gated by auth."""
    lead = _make_lead(assigned_to=uuid.uuid4())
    email, phone = redact_lead_pii(
        lead,
        viewer_id=None,
        viewer_role=None,
    )
    assert email == "a***@example.com"
    assert phone == "+49…567"


# ── Log-label helper (used by GDPR forget audit-trail) ────────────────────


def test_safe_lead_label_first_name_last_initial():
    lead = _make_lead(name="Alice Beispiel")
    assert _safe_lead_label(lead) == "<lead:Alice B>"


def test_safe_lead_label_single_name():
    lead = _make_lead(name="Mononym")
    assert _safe_lead_label(lead) == "<lead:M>"


def test_safe_lead_label_empty_name():
    lead = _make_lead(name="")
    assert _safe_lead_label(lead) == "<lead:?>"
