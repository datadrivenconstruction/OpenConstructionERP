# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The welcome email: one catalogue per language, escaped values, the reset link only on the button.

R12: the reset link expires after ``RESET_TOKEN_LIFETIME_MINUTES``; the email
says so and says how to get a new one.
"""

from __future__ import annotations

import logging
import re
import string

import pytest

from app.core.email import ConsoleEmailBackend, EmailMessage, EmailService
from app.modules.trainer import provisioning
from app.modules.trainer.provisioning import (
    WELCOME_LOCALES,
    welcome_html,
    welcome_locale,
    welcome_subject,
)
from app.modules.users.service import RESET_TOKEN_LIFETIME_MINUTES

RESET_URL = "https://academy.example.com/auth/reset?token=eyJ.SECRET-RESET-TOKEN.sig"
FORGOT_URL = "https://academy.example.com/forgot-password"
ACADEMY_URL = "https://academy.example.com/academy"


def _render(locale: str = "en", *, reset_url: str | None = RESET_URL, queued: bool = False, name: str = "Ada") -> str:
    return welcome_html(
        locale=locale,
        name=name,
        email="ada@example.com",
        course_titles=["Valuations UK"],
        queued=queued,
        reset_url=reset_url,
        forgot_url=FORGOT_URL,
        academy_url=ACADEMY_URL,
    )


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_every_language_has_the_english_keys_and_placeholders() -> None:
    tables = provisioning._TABLES
    english = tables["en"]
    assert len(WELCOME_LOCALES) >= 3
    for locale, table in tables.items():
        assert set(table) == set(english), locale
        for key, text in table.items():
            assert _placeholders(text) == _placeholders(english[key]), (locale, key)


@pytest.mark.parametrize(
    ("given", "expected"), [("de", "de"), ("de-AT", "de"), ("FR", "fr"), ("pt-BR", "en"), (None, "en")]
)
def test_a_regional_or_unknown_locale_reads_its_language_or_english(given: str | None, expected: str) -> None:
    assert welcome_locale(given) == expected


def test_the_subject_is_translated() -> None:
    english = welcome_subject("en", ["Kurs A"], queued=False)
    german = welcome_subject("de-DE", ["Kurs A"], queued=False)
    assert "Kurs A" in english and "Kurs A" in german
    assert english != german
    assert welcome_subject("en", ["Kurs A"], queued=True) != english


def test_a_new_account_gets_the_reset_button_and_the_expiry_explained() -> None:
    body = _render()
    assert f'href="{RESET_URL}"' in body
    assert f"{RESET_TOKEN_LIFETIME_MINUTES} minutes" in body
    assert FORGOT_URL in body
    assert body.count("SECRET-RESET-TOKEN") == 1, "the token belongs on the button only"


def test_an_existing_account_gets_no_reset_link() -> None:
    body = _render(reset_url=None)
    assert "token=" not in body
    assert f'href="{ACADEMY_URL}"' in body
    assert FORGOT_URL in body


@pytest.mark.parametrize("locale", WELCOME_LOCALES)
def test_every_language_explains_the_expiry_with_the_real_lifetime(locale: str) -> None:
    body = _render(locale)
    assert re.search(rf"\b{RESET_TOKEN_LIFETIME_MINUTES}\b", body)
    assert FORGOT_URL in body


def test_the_buyers_name_cannot_inject_markup() -> None:
    body = _render(name="<script>alert(1)</script>")
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


async def test_the_console_log_preview_never_shows_the_reset_token(caplog: pytest.LogCaptureFixture) -> None:
    """The console transport logs the first 500 characters at INFO."""
    caplog.set_level(logging.INFO)
    service = EmailService(ConsoleEmailBackend())
    await service.send(EmailMessage(to="ada@example.com", subject="s", html_body=_render(), tags=["t"]))
    messages = [r.getMessage() for r in caplog.records if "[email:console]" in r.getMessage()]
    assert messages, "the console backend must have logged the send"
    assert all("SECRET-RESET-TOKEN" not in m for m in messages)
