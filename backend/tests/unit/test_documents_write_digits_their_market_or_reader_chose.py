# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A document writes digits the way its market does, unless the reader chose.

The separators of a number belong to the market and were already decided by
the country row. Which digit shapes print is a second, independent question:
Egyptian business documents are commonly printed with Western digits while
Arabic-Indic digits are the CLDR default for Arabic, and a Persian reader
writes yet another set. The country row may name a digit system, and a request
may override it through ``X-Digit-System`` or ``?digits=``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core import regional_format as rf
from app.core.i18n_data import COUNTRY_DEFAULTS
from app.middleware.accept_language import AcceptLanguageMiddleware

AMOUNT = Decimal("1234567.89")


def test_egypt_has_a_country_row_that_prints_western_digits() -> None:
    row = COUNTRY_DEFAULTS["EG"]
    assert row["currency"] == "EGP"
    assert row["locale"] == "ar"
    assert row["digit_system"] == "latn"
    assert rf.format_number(AMOUNT, 2, rf.number_style("EG", "EGP")) == "1,234,567.89"


def test_arabic_indic_digits_bring_their_own_separators() -> None:
    style = rf.number_style("EG", "EGP", digits="arab")
    assert rf.format_number(AMOUNT, 2, style) == "١٬٢٣٤٬٥٦٧٫٨٩"


def test_a_continental_market_asked_for_arabic_digits_does_not_keep_latin_separators() -> None:
    # A German grouping dot between Arabic-Indic digits reads as nothing in
    # either script; the digit system brings the separators that go with it.
    style = rf.number_style("DE", "EUR", digits="arab")
    assert rf.format_number(AMOUNT, 2, style) == "١٬٢٣٤٬٥٦٧٫٨٩"


def test_persian_digits_are_the_extended_set() -> None:
    style = rf.number_style("EG", "EGP", digits="arabext")
    assert rf.format_number(Decimal("1234.5"), 2, style) == "۱٬۲۳۴٫۵۰"


def test_asking_for_latin_digits_keeps_the_markets_separators() -> None:
    assert rf.format_number(AMOUNT, 2, rf.number_style("DE", "EUR", digits="latn")) == "1.234.567,89"


def test_a_country_without_a_digit_system_is_unchanged() -> None:
    assert "digit_system" not in COUNTRY_DEFAULTS["DE"]
    assert rf.number_style("DE", "EUR") == rf.CONTINENTAL
    assert rf.number_style(None, "INR") == rf.INDIAN


def test_an_unknown_digit_system_is_ignored_rather_than_guessed() -> None:
    assert rf.number_style("EG", "EGP", digits="klingon") == rf.number_style("EG", "EGP")


def test_negative_amounts_keep_their_sign_in_any_script() -> None:
    style = rf.number_style("EG", "EGP", digits="arab")
    assert rf.format_number(Decimal("-12.5"), 2, style) == "-١٢٫٥٠"


def test_dates_follow_the_digit_system() -> None:
    day = date(2026, 10, 19)
    assert rf.format_date(day, "EG") == "19/10/2026"
    assert rf.format_date(day, "EG", digits="arab") == "١٩/١٠/٢٠٢٦"


def test_the_request_choice_reaches_number_style_without_an_argument() -> None:
    token = rf.set_document_digits("arab")
    try:
        assert rf.format_number(AMOUNT, 2, rf.number_style("EG", "EGP")) == "١٬٢٣٤٬٥٦٧٫٨٩"
        assert rf.format_date(date(2026, 1, 2), "EG") == "٠٢/٠١/٢٠٢٦"
    finally:
        rf.reset_document_digits(token)
    assert rf.format_number(AMOUNT, 2, rf.number_style("EG", "EGP")) == "1,234,567.89"


def test_an_explicit_argument_beats_the_request_choice() -> None:
    token = rf.set_document_digits("arab")
    try:
        assert rf.format_number(AMOUNT, 2, rf.number_style("EG", "EGP", digits="latn")) == "1,234,567.89"
    finally:
        rf.reset_document_digits(token)


def _echo(request: Request) -> PlainTextResponse:
    return PlainTextResponse(rf.format_number(AMOUNT, 2, rf.number_style("EG", "EGP")))


@pytest.fixture
def client() -> TestClient:
    app = Starlette(routes=[Route("/n", _echo)])
    app.add_middleware(AcceptLanguageMiddleware)
    return TestClient(app)


def test_the_header_sets_the_digits_for_one_request_only(client: TestClient) -> None:
    assert client.get("/n", headers={"X-Digit-System": "arab"}).text == "١٬٢٣٤٬٥٦٧٫٨٩"
    assert client.get("/n").text == "1,234,567.89"


def test_the_query_parameter_wins_over_the_header(client: TestClient) -> None:
    assert client.get("/n?digits=latn", headers={"X-Digit-System": "arab"}).text == "1,234,567.89"


def test_a_garbage_header_changes_nothing(client: TestClient) -> None:
    assert client.get("/n", headers={"X-Digit-System": "<script>"}).text == "1,234,567.89"
