# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for notification text helpers (``app.modules.notifications.templates``).

Pure - no DB, no event bus. Focuses on ``combine_title_body``, the shared
one-line folding used by positional-parameter delivery sinks (e.g. a WhatsApp
message template), which previously printed "Title - Title" when an event set
the body equal to the title.
"""

from __future__ import annotations

from app.modules.notifications.templates import combine_title_body, render


def test_combine_distinct_title_and_body():
    assert combine_title_body("New RFI", "RFI-012 Foundation") == "New RFI - RFI-012 Foundation"


def test_combine_dedupes_identical_title_and_body():
    # Several events set body_default == title_default; never print "X - X".
    assert combine_title_body("Approval requested", "Approval requested") == "Approval requested"


def test_combine_handles_empty_body():
    assert combine_title_body("Heads up", "") == "Heads up"
    assert combine_title_body("Heads up", None) == "Heads up"


def test_combine_handles_empty_title():
    assert combine_title_body("", "Body only") == "Body only"
    assert combine_title_body(None, "Body only") == "Body only"


def test_combine_strips_surrounding_whitespace():
    assert combine_title_body("  New  ", "  New  ") == "New"
    assert combine_title_body("  A  ", "  B  ") == "A - B"


def test_portal_notification_templates_render_real_text():
    # Regression for issue #361: the portal notification keys had no
    # server-side template, so channels without frontend i18n (the Telegram
    # bridge) rendered the raw key string as the title and body. render()
    # must interpolate them, never fall back to the key.
    invited = render(
        "notifications.portal.user_invited.body",
        {"portal_user_email": "sam@example.com", "portal_role": "viewer"},
    )
    assert invited == "sam@example.com invited as viewer."

    message = render(
        "notifications.portal.message_received.body",
        {"buyer_name": "A buyer"},
    )
    assert message == "A buyer sent a message."

    for key in (
        "notifications.portal.user_invited.title",
        "notifications.portal.message_received.title",
    ):
        assert render(key) != key
