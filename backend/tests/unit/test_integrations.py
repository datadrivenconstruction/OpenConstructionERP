"""Unit tests for the integrations module.

Covers:
    - Webhook schemas (create, update, response serialization)
    - Email templates (HTML generation)
    - iCal date formatting helper
    - iCal text escaping helper
    - HMAC signature computation
"""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.modules.integrations.email_service import (
    template_invoice_approved,
    template_meeting_invitation,
    template_safety_alert,
    template_task_assigned,
)
from app.modules.integrations.router import _ical_dt, _ical_escape
from app.modules.integrations.schemas import (
    DeliveryResponse,
    WebhookCreate,
    WebhookResponse,
    WebhookUpdate,
)
from app.modules.integrations.service import _sign_payload

# ---------------------------------------------------------------------------
# Webhook schema tests
# ---------------------------------------------------------------------------


class TestWebhookCreate:
    """WebhookCreate schema validation."""

    def test_valid_create(self):
        data = WebhookCreate(
            name="My Hook",
            url="https://example.com/hook",
            events=["rfi.created", "task.assigned"],
        )
        assert data.name == "My Hook"
        assert data.url == "https://example.com/hook"
        assert data.events == ["rfi.created", "task.assigned"]
        assert data.is_active is True
        assert data.secret is None
        assert data.project_id is None

    def test_events_required_non_empty(self):
        with pytest.raises(ValidationError):
            WebhookCreate(
                name="Empty Events",
                url="https://example.com/hook",
                events=[],  # min_length=1
            )

    def test_name_required(self):
        with pytest.raises(ValidationError):
            WebhookCreate(
                name="",  # min_length=1
                url="https://example.com/hook",
                events=["rfi.created"],
            )

    def test_with_project_and_secret(self):
        pid = uuid.uuid4()
        data = WebhookCreate(
            name="Scoped",
            url="https://example.com/hook",
            events=["*"],
            project_id=pid,
            secret="my-secret",
        )
        assert data.project_id == pid
        assert data.secret == "my-secret"


class TestWebhookUpdate:
    """WebhookUpdate schema validation (partial)."""

    def test_partial_update(self):
        data = WebhookUpdate(name="Renamed")
        assert data.name == "Renamed"
        assert data.url is None
        assert data.events is None

    def test_update_events(self):
        data = WebhookUpdate(events=["task.assigned"])
        assert data.events == ["task.assigned"]

    def test_deactivate(self):
        data = WebhookUpdate(is_active=False)
        assert data.is_active is False


class TestWebhookResponse:
    """WebhookResponse serialization from ORM-like objects."""

    def test_from_dict(self):
        now = datetime.now(UTC)
        resp = WebhookResponse(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            name="Hook",
            url="https://example.com",
            events=["rfi.created"],
            created_at=now,
            updated_at=now,
        )
        assert resp.failure_count == 0
        assert resp.is_active is True


class TestDeliveryResponse:
    """DeliveryResponse serialization."""

    def test_from_dict(self):
        now = datetime.now(UTC)
        resp = DeliveryResponse(
            id=uuid.uuid4(),
            webhook_id=uuid.uuid4(),
            event_type="rfi.created",
            payload={"key": "value"},
            status_code=200,
            duration_ms=42,
            created_at=now,
        )
        assert resp.status_code == 200
        assert resp.duration_ms == 42


# ---------------------------------------------------------------------------
# HMAC signature
# ---------------------------------------------------------------------------


class TestHMACSignature:
    """HMAC-SHA256 payload signing."""

    def test_sign_deterministic(self):
        payload = b'{"event":"test"}'
        sig1 = _sign_payload(payload, "secret")
        sig2 = _sign_payload(payload, "secret")
        assert sig1 == sig2
        assert len(sig1) == 64  # hex digest length

    def test_different_secret_different_sig(self):
        payload = b'{"event":"test"}'
        sig1 = _sign_payload(payload, "secret-a")
        sig2 = _sign_payload(payload, "secret-b")
        assert sig1 != sig2


# ---------------------------------------------------------------------------
# Email templates
# ---------------------------------------------------------------------------


class TestEmailTemplates:
    """HTML email template generation."""

    def test_task_assigned(self):
        subject, html = template_task_assigned(
            task_title="Review drawings",
            assignee_name="Alice",
            project_name="Berlin HQ",
            action_url="https://app.example.com/tasks/1",
        )
        assert "Review drawings" in subject
        assert "Alice" in html
        assert "Berlin HQ" in html
        assert "https://app.example.com/tasks/1" in html
        assert "<!DOCTYPE html>" in html

    def test_invoice_approved(self):
        subject, html = template_invoice_approved(
            invoice_number="INV-2026-042",
            amount="EUR 12,500.00",
            project_name="Office London",
        )
        assert "INV-2026-042" in subject
        assert "EUR 12,500.00" in html
        assert "Office London" in html

    def test_safety_alert(self):
        subject, html = template_safety_alert(
            description="Unprotected edge on level 3",
            reporter_name="Bob",
            project_name="Warehouse Dubai",
        )
        assert "Safety alert" in subject
        assert "high-risk" in html
        assert "Bob" in html

    def test_meeting_invitation(self):
        subject, html = template_meeting_invitation(
            meeting_title="Safety Review",
            meeting_date="2026-04-15",
            location="Conference Room A",
            project_name="School Paris",
            action_url="https://app.example.com/meetings/5",
        )
        assert "Safety Review" in subject
        assert "2026-04-15" in html
        assert "Conference Room A" in html

    def test_meeting_invitation_no_location(self):
        subject, html = template_meeting_invitation(
            meeting_title="Kickoff",
            meeting_date="2026-05-01",
            location=None,
            project_name="Test",
        )
        assert "Location" not in html


# ---------------------------------------------------------------------------
# iCal helpers
# ---------------------------------------------------------------------------


class TestICalEscape:
    """iCalendar text escaping."""

    def test_plain_text(self):
        assert _ical_escape("Hello World") == "Hello World"

    def test_semicolons_and_commas(self):
        assert _ical_escape("a;b,c") == "a\\;b\\,c"

    def test_newlines(self):
        assert _ical_escape("line1\nline2") == "line1\\nline2"

    def test_backslash(self):
        assert _ical_escape("a\\b") == "a\\\\b"


class TestICalDt:
    """iCalendar date/datetime formatting."""

    def test_date_only(self):
        result = _ical_dt("2026-04-15")
        assert result == "20260415T090000Z"

    def test_datetime(self):
        result = _ical_dt("2026-04-15T14:30:00")
        assert result == "20260415T143000Z"

    def test_datetime_with_tz(self):
        result = _ical_dt("2026-04-15T14:30:00+02:00")
        assert result == "20260415T143000Z"

    def test_none(self):
        assert _ical_dt(None) is None

    def test_empty_string(self):
        assert _ical_dt("") is None
