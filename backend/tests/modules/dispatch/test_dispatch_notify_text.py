"""The daily-plan notification renders real text in the e-mail, never a raw key."""

from __future__ import annotations

import pytest

from app.modules.notifications.dispatcher import render_email_parts

PAYLOAD = {
    "title_key": "dispatch.notify.plan_title",
    "body_key": "dispatch.notify.plan_body",
    "body_context": {"day": "2026-11-02", "lines": 4},
}


@pytest.mark.parametrize("locale", [None, "en", "de", "tr"])
def test_plan_email_has_no_raw_key(locale: str | None) -> None:
    subject, body = render_email_parts("info", PAYLOAD, locale, None)
    for text in (subject, body):
        assert "dispatch.notify" not in text
        assert "{" not in text
    assert "4" in body
    assert "2026-11-02" in body or "02.11.2026" in body
