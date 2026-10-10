# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The shipped Türkiye rows, checked for form and provenance.

These tests hold for a table of any size, including an empty one. They never
state what a rate should be: a test that repeats the number proves only that
the number was typed twice. What they can prove is that every row says where
it came from, cannot be misread, and computes through the real calculator.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlparse

import pytest

from app.core.currency_registry import money_quantum
from app.core.payment_taxes import Choice, PaymentTaxInput, categories, compute_payment_taxes, lookup, rows_for
from app.core.payment_taxes.data_tr import ROWS
from app.core.payment_taxes.tables import KINDS, RateRow, find_overlaps, validate_rows

_OFFICIAL_DOMAINS = ("gib.gov.tr", "mevzuat.gov.tr", "resmigazete.gov.tr", "hmb.gov.tr", "csb.gov.tr")

# Turkish words as they come out of a keyboard without Turkish letters. Each
# of these has a correct spelling with a diacritic, so its presence in a label
# printed on a Turkish document is a typo, not a style.
_TRANSLITERATED = frozenset(
    {
        "yapim",
        "isleri",
        "isler",
        "isi",
        "islerle",
        "muhendislik",
        "mimarlik",
        "etut",
        "danismanlik",
        "bakim",
        "onarim",
        "techizat",
        "demirbas",
        "tasit",
        "tasitlara",
        "isgucu",
        "guvenlik",
        "ozel",
        "yapi",
        "cevre",
        "bahce",
        "tasimaciligi",
        "tasimacilik",
        "yuk",
        "diger",
        "bakir",
        "cinko",
        "aluminyum",
        "kursun",
        "kulce",
        "urunleri",
        "urunlerinin",
        "agac",
        "celik",
        "disi",
        "odeme",
        "odemeleri",
        "odemeler",
        "insaat",
        "yillara",
        "hakedis",
        "sozlesme",
        "kagit",
        "kagitlar",
        "alimi",
        "alim",
        "alici",
        "alicilar",
        "alicilara",
        "mukellefi",
        "mukellefleri",
        "yalnizca",
        "tebligi",
        "teblig",
        "tebligin",
        "bolumunde",
        "islem",
        "islemin",
        "islemlerde",
        "sinir",
        "sinirini",
        "sinirina",
        "asmiyorsa",
        "yilindaki",
        "yili",
        "duzenleme",
        "gore",
        "degil",
        "tamamina",
        "degerlendirilir",
        "ulastiginda",
        "saglanan",
        "disindadir",
        "baslayip",
        "icinde",
        "yapildigi",
        "isverenler",
        "arasindaki",
        "hakedisler",
        "kullanilmaz",
        "dusulmus",
        "tutaridir",
        "odemeyi",
        "yaptigi",
        "uygulanir",
        "yururlukteki",
        "sayili",
        "cumhurbaskani",
        "karari",
        "turkiye",
    }
)


def _words(text: str) -> list[str]:
    # str.lower() turns the dotted capital into "i" plus a combining dot.
    return re.findall(r"[^\W\d_]+", text.replace("İ", "i").replace("I", "ı").lower().replace(chr(0x307), ""))


def _ids(rows: tuple[RateRow, ...]) -> list[str]:
    return [f"{row.kind}/{row.code}/{row.effective_from.isoformat()}" for row in rows]


def test_the_registry_serves_exactly_the_shipped_rows() -> None:
    assert isinstance(ROWS, tuple)
    assert rows_for("TR") is ROWS
    assert all(row.country_code == "TR" for row in ROWS)


def test_the_table_is_well_formed_and_no_two_rows_claim_the_same_day() -> None:
    assert validate_rows(ROWS) == []
    assert find_overlaps(ROWS) == []


def test_no_row_is_a_vat_rate() -> None:
    # The KDV rate has one source elsewhere. The only thing this table may
    # say about VAT is which fraction of it the buyer withholds.
    for row in ROWS:
        assert row.kind in KINDS
        if row.kind == "vat_withholding":
            assert row.rate_pct is None, row.code
            assert row.base == "vat", row.code
        else:
            assert row.base != "vat", row.code
        assert row.code not in {"0015", "KDV", "VAT"}
        assert "katma değer vergisi oranı" not in row.labels.get("tr", "").lower()


@pytest.mark.parametrize("row", ROWS, ids=_ids(ROWS))
def test_every_row_says_where_it_came_from(row: RateRow) -> None:
    assert row.legal_reference.strip()
    assert date.fromisoformat(row.read_date) >= date(2026, 1, 1)
    assert row.review_status in ("confirmed", "unconfirmed")

    host = (urlparse(row.source_url).hostname or "").lower()
    official = any(host == domain or host.endswith("." + domain) for domain in _OFFICIAL_DOMAINS)
    if row.review_status == "confirmed":
        # Confirmed means read on the authority's own page, so it needs one.
        assert row.source_url.startswith("https://")
        assert official, row.source_url
    elif row.source_url:
        assert row.source_url.startswith("https://")
        assert official, f"an unofficial source cannot be the citation of a statutory row: {row.source_url}"


@pytest.mark.parametrize("row", ROWS, ids=_ids(ROWS))
def test_every_row_is_labelled_in_turkish_and_english(row: RateRow) -> None:
    for texts in (row.labels, row.conditions):
        if not texts:
            continue
        assert set(texts) >= {"tr", "en"}, row.code
        assert texts["tr"].strip()
        assert texts["en"].strip()
        assert texts["tr"] != texts["en"]
        suspicious = set(_words(texts["tr"])) & _TRANSLITERATED
        assert not suspicious, f"{row.code}: Turkish text without its diacritics: {sorted(suspicious)}"
        # No dash characters other than the hyphen in anything that is printed.
        assert not {chr(0x2013), chr(0x2014)} & set(texts["tr"] + texts["en"])


def test_the_transliteration_check_can_fail() -> None:
    # The check above is only worth something if it tells the two spellings apart.
    assert set(_words("Yapim isleri")) & _TRANSLITERATED
    assert not (set(_words("Yapım işleri")) & _TRANSLITERATED)
    assert not (set(_words("YAPIM İŞLERİ")) & _TRANSLITERATED)
    assert set(_words("Diger hizmetler, celik ve agac urunleri")) & _TRANSLITERATED == {
        "diger",
        "celik",
        "agac",
        "urunleri",
    }


@pytest.mark.parametrize("row", ROWS, ids=_ids(ROWS))
def test_fractions_thresholds_and_caps_are_coherent(row: RateRow) -> None:
    if row.kind == "vat_withholding":
        assert row.numerator is not None
        assert row.denominator is not None
        assert 0 < row.numerator <= row.denominator
    parts = (row.threshold_amount is not None, bool(row.threshold_scope), bool(row.threshold_measure))
    assert all(parts) or not any(parts)
    has_amount = row.threshold_amount is not None or row.cap_amount is not None or row.work_value_threshold is not None
    assert bool(row.threshold_currency) == has_amount
    if has_amount:
        assert row.threshold_currency == "TRY"
    assert (row.work_value_threshold is not None) == (row.buyer_scope == "designated_or_work_value")


@pytest.mark.parametrize("row", [r for r in ROWS if r.kind == "vat_withholding"], ids=lambda r: r.code)
def test_a_withholding_row_states_who_withholds_and_uses_an_official_code(row: RateRow) -> None:
    # The e-invoice code list knows partial codes 6xx and full codes 8xx only.
    assert re.fullmatch(r"[68]\d\d", row.code), row.code
    if row.code.startswith("8"):
        assert row.numerator == row.denominator
    # Whether a withholding arises depends on the buyer. A row that leaves
    # the scope empty would compute for everyone, which is an assumption.
    assert row.buyer_scope in ("any", "designated_only", "designated_or_work_value")
    assert row.conditions.get("tr")
    assert row.conditions.get("en")


@pytest.mark.parametrize("row", [r for r in ROWS if r.kind == "stamp_duty"], ids=lambda r: r.code)
def test_a_stamp_duty_row_states_when_it_applies(row: RateRow) -> None:
    # Duty on a payment depends on who pays. A row without that statement
    # would be offered to a private employer as if it were the default.
    assert row.conditions.get("tr")
    assert row.conditions.get("en")
    # And the calculation itself refuses a buyer stated to be an ordinary one,
    # so a private employer who selects the row anyway gets a dash, not a duty.
    assert row.buyer_scope == "designated_only"
    private = compute_payment_taxes(_input(row, buyer_is_designated=False), rows_for("TR")).stamp_duty
    assert (private.status, private.amount, private.reason_key) == ("not_applicable", None, "buyer_not_designated")
    unstated = compute_payment_taxes(_input(row), rows_for("TR")).stamp_duty
    assert (unstated.status, unstated.amount, unstated.reason_key) == ("held", None, "buyer_class_unknown")


def _probe_dates() -> list[date]:
    days = {date(2026, 10, 10)}
    for row in ROWS:
        days.update({row.effective_from, row.effective_from - timedelta(days=1)})
        if row.effective_to is not None:
            days.update({row.effective_to, row.effective_to + timedelta(days=1)})
    return sorted(days)


def test_a_picker_can_be_built_for_every_boundary_date() -> None:
    for on in _probe_dates():
        for kind in KINDS:
            found = categories(ROWS, country="TR", kind=kind, on=on)
            assert len({row.code for row in found}) == len(found)
            for row in found:
                assert lookup(ROWS, country="TR", kind=kind, code=row.code, on=on) is row


def test_a_row_is_not_found_before_it_starts() -> None:
    for row in ROWS:
        before = row.effective_from - timedelta(days=1)
        earlier = lookup(ROWS, country="TR", kind=row.kind, code=row.code, on=before)
        assert earlier is None or earlier is not row


_CHOICE_FIELD = {
    "vat_withholding": ("vat_withholding", "vat_withheld"),
    "income_withholding": ("income_withholding", "income_withheld"),
    "stamp_duty": ("stamp_duty", "stamp_duty"),
}


def _input(row: RateRow, **changes: object) -> PaymentTaxInput:
    not_applicable = Choice("not_applicable", reason="Not the subject of this test")
    choices = {field: not_applicable for field, _ in _CHOICE_FIELD.values()}
    choices[_CHOICE_FIELD[row.kind][0]] = Choice("selected", row.code)
    values: dict[str, object] = {
        "country_code": "TR",
        "currency": "TRY",
        "on": row.effective_from,
        "net_amount": Decimal("123456.78"),
        "vat_rate_pct": Decimal("10"),  # an arbitrary test rate, not a statement about any tax
        **choices,
    }
    values.update(changes)
    return PaymentTaxInput(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("row", ROWS, ids=_ids(ROWS))
def test_every_row_computes_through_the_calculator(row: RateRow) -> None:
    quantum = money_quantum("TRY")
    result = compute_payment_taxes(
        _input(row, buyer_is_designated=True, work_value_incl_vat=Decimal("1")), rows_for("TR")
    )
    figure = getattr(result, _CHOICE_FIELD[row.kind][1])

    assert figure.status == "value", figure
    assert (figure.code, figure.legal_reference) == (row.code, row.legal_reference)
    assert figure.review_status == row.review_status
    assert figure.effective_from == row.effective_from
    # The expected amount is derived from the row itself, never restated here.
    if row.kind == "vat_withholding":
        vat = result.vat_computed.amount
        expected = (vat * row.numerator / row.denominator).quantize(quantum, rounding=ROUND_HALF_UP)
        assert result.vat_computed.amount == result.vat_withheld.amount + result.vat_payable.amount
    else:
        expected = (figure.base * row.rate_pct / 100).quantize(quantum, rounding=ROUND_HALF_UP)
    if row.cap_amount is not None and expected > row.cap_amount:
        expected = row.cap_amount
    assert figure.amount == expected


@pytest.mark.parametrize(
    "row", [r for r in ROWS if r.buyer_scope in ("designated_only", "designated_or_work_value")], ids=lambda r: r.code
)
def test_a_buyer_condition_is_never_assumed_for_a_shipped_row(row: RateRow) -> None:
    figure_of = _CHOICE_FIELD[row.kind][1]
    unknown = getattr(compute_payment_taxes(_input(row), rows_for("TR")), figure_of)
    assert (unknown.status, unknown.amount, unknown.reason_key) == ("held", None, "buyer_class_unknown")

    ordinary = getattr(compute_payment_taxes(_input(row, buyer_is_designated=False), rows_for("TR")), figure_of)
    assert ordinary.amount is None
    if row.buyer_scope == "designated_only":
        assert (ordinary.status, ordinary.reason_key) == ("not_applicable", "buyer_not_designated")
    else:
        assert (ordinary.status, ordinary.reason_key) == ("held", "work_value_unknown")
        at_limit = _input(row, buyer_is_designated=False, work_value_incl_vat=row.work_value_threshold)
        assert compute_payment_taxes(at_limit, rows_for("TR")).vat_withheld.status == "value"
        under = _input(row, buyer_is_designated=False, work_value_incl_vat=row.work_value_threshold - 1)
        assert compute_payment_taxes(under, rows_for("TR")).vat_withheld.reason_key == "below_work_value"


def test_a_document_in_another_currency_is_held_rather_than_capped_in_lira() -> None:
    for row in ROWS:
        if row.cap_amount is None:
            continue
        # The buyer is stated, so the cap is the only thing left to stop on.
        result = compute_payment_taxes(_input(row, currency="EUR", buyer_is_designated=True), rows_for("TR"))
        figure = getattr(result, _CHOICE_FIELD[row.kind][1])
        assert (figure.status, figure.reason_key) == ("held", "cap_currency_mismatch")
