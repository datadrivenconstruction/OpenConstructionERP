# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The hakediş layout: the standard order, a contract's changes to it, and the printed words.

The standard Turkish layout has to stay the public form line for line, because
a cost control department recognises the document by it. A contract's own
arrangement is configuration, and a configuration that cannot be evaluated has
to be refused by name where it is written, not discovered on a printed page.
"""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

from app.core.payment_taxes import Choice
from app.core.payment_taxes.calc import REASON_KEYS
from app.modules.contracts.hakedis_layout import (
    DEFAULT_LAYOUTS,
    DEFAULT_SIGNATURE_ROLES,
    HAKEDIS_LABELS,
    LAYOUT_PRESETS,
    WORKS_COLUMNS,
    WORKS_DEFAULT_COLUMNS,
    SummaryLineDef,
    contractor_label_key,
    currency_label,
    evaluation_order,
    has_layout,
    is_foreign_currency,
    label,
    label_filled,
    label_parts,
    line_formula,
    resolve_layout,
    resolve_settings,
    tax_choice,
    tr_lower,
    tr_upper,
    upper_for,
    validate_layout,
)

TR = DEFAULT_LAYOUTS["TR"]


def terms(**hakedis: object) -> dict[str, object]:
    return {"hakedis": hakedis}


# ── The standard form ─────────────────────────────────────────────────────


def test_the_standard_layout_follows_the_public_form_letter_for_letter() -> None:
    printed = [(line.letter, label(f"line.{line.key}", "tr")) for line in TR]
    assert printed == [
        ("A", "Sözleşme Fiyatları İle Yapılan İş"),
        ("B", "Fiyat Farkı Tutarı"),
        ("C", "Toplam Tutar"),
        ("D", "Bir Önceki Hakedişin Toplam Tutarı"),
        ("E", "Bu Hakedişin Tutarı"),
        ("F", "KDV"),
        ("G", "Tahakkuk Tutarı"),
        ("a", "Gelir / Kurumlar Vergisi"),
        ("b", "Damga Vergisi"),
        ("c", "KDV Tevkifatı"),
        ("d", "Sosyal Sigortalar Kurumu Kesintisi"),
        ("e", "İdare Makinesi Kiraları"),
        ("f", "Gecikme Cezası"),
        ("g", "Avans Mahsubu"),
        ("h", "Bu Hakedişle Ödenen Fiyat Farkı Teminat Kesintisi"),
        ("i", "Teminat Kesintisi"),
        ("j", "Diğer Kesintiler"),
        ("H", "Kesintiler ve Mahsuplar Toplamı"),
        ("", "Yükleniciye Ödenecek Tutar"),
    ]


def test_the_standard_formulas_read_as_on_the_form() -> None:
    by_key = {line.key: line for line in TR}

    def formula(key: str, basis: dict[str, str] | None = None, language: str = "tr") -> str:
        return line_formula(by_key[key], TR, basis or {}, language, lambda raw: raw.replace(".", ","))

    assert formula("total") == "( A + B )"
    assert formula("this_certificate") == "( C - D )"
    assert formula("accrued") == "( E + F )"
    assert formula("payable") == "( G - H )"
    assert formula("deductions_total") == ""
    assert formula("work_done") == ""
    # With no rate known yet the form's own dots are printed.
    assert formula("vat") == "( E x %.. )"
    assert formula("vat", {"rate_pct": "12.5"}) == "( E x %12,5 )"
    assert formula("vat", {"rate_pct": "12.5"}, "en") == "( E x 12,5% )"
    assert formula("stamp_duty", {"rate_pct": "0.5"}) == "( E - g x %0,5 )"
    assert formula("vat_withholding", {"numerator": "1", "denominator": "2"}) == "( F x 1/2 )"
    assert formula("retention", {"rate_pct": "10"}) == "( E x %10 )"
    assert formula("advance_recovery") == ""
    assert formula("advance_recovery", {"rate_pct": "20"}) == "( E x %20 )"


def test_the_deductions_total_adds_every_deduction_and_nothing_else() -> None:
    for layout in (TR, LAYOUT_PRESETS["TR_PRIVATE"]):
        by_key = {line.key: line for line in layout}
        deductions = tuple(line.key for line in layout if line.section == "deductions")
        assert by_key["deductions_total"].operands == deductions
        assert all(by_key[key].sign == -1 for key in deductions)


def test_every_preset_is_a_valid_layout() -> None:
    for name, layout in LAYOUT_PRESETS.items():
        validate_layout(layout)
        order = evaluation_order(layout)
        assert set(order) == {line.key for line in layout}, name
        assert order.index("payable") > order.index("deductions_total") > order.index("vat")


def test_the_works_list_columns_carry_the_forms_letters() -> None:
    unit = {column.key: column.letter for column in WORKS_COLUMNS["unit_price"]}
    assert [unit[key] for key in WORKS_DEFAULT_COLUMNS["unit_price"]] == [
        "", "", "", "", "A", "B", "C", "D=B-C", "E=AxB", "F=AxC", "G=E-F",
    ]  # fmt: skip
    lump = {column.key: column.letter for column in WORKS_COLUMNS["lump_sum"]}
    assert [lump[key] for key in WORKS_DEFAULT_COLUMNS["lump_sum"]] == [
        "", "", "", "A", "B", "C=AxB", "D", "E=AxD", "F=B-D", "G=C-E",
    ]  # fmt: skip
    assert [label(f"col.unit_price.{key}", "tr") for key in WORKS_DEFAULT_COLUMNS["unit_price"]] == [
        "Sıra No",
        "Poz No",
        "İşin Tanımı",
        "Birimi",
        "Teklif Birim Fiyat",
        "Toplam İmalat, İhzarat Miktarı",
        "Bir Önceki Hakediş İmalat, İhzarat Miktarı",
        "Bu Hakediş İmalat, İhzarat Miktarı",
        "Toplam İmalat, İhzarat Tutarı",
        "Bir Önceki Hakediş Tutarı",
        "Bu Hakediş Tutarı",
    ]


def test_the_standard_signature_block_is_the_forms() -> None:
    roles = DEFAULT_SIGNATURE_ROLES["TR"]
    assert [upper_for("tr", label(f"role.{role}", "tr")) for role in roles] == [
        "YÜKLENİCİ",
        "DÜZENLEYENLER (YAPI DENETİM ELEMANLARI)",
        "ONAYLAYAN",
    ]


# ── The printed words ─────────────────────────────────────────────────────


def test_both_locales_have_exactly_the_same_keys() -> None:
    assert set(HAKEDIS_LABELS) == {"tr", "en"}
    assert set(HAKEDIS_LABELS["tr"]) == set(HAKEDIS_LABELS["en"])
    assert all(text.strip() for table in HAKEDIS_LABELS.values() for text in table.values())


def test_placeholders_agree_between_the_locales() -> None:
    for key, text in HAKEDIS_LABELS["tr"].items():
        assert set(re.findall(r"\{(\w+)\}", text)) == set(re.findall(r"\{(\w+)\}", HAKEDIS_LABELS["en"][key])), key


def test_every_line_column_and_role_the_documents_print_has_a_label() -> None:
    needed = {f"line.{line.key}" for layout in LAYOUT_PRESETS.values() for line in layout}
    needed |= {f"col.{flavour}.{column.key}" for flavour, columns in WORKS_COLUMNS.items() for column in columns}
    needed |= {f"role.{role}" for roles in DEFAULT_SIGNATURE_ROLES.values() for role in roles}
    needed |= {f"subtitle.{flavour}" for flavour in WORKS_COLUMNS}
    for table in HAKEDIS_LABELS.values():
        assert needed <= set(table)


def test_every_reason_the_tax_calculation_can_give_has_a_label() -> None:
    for key in REASON_KEYS:
        if key:
            assert f"reason.{key}" in HAKEDIS_LABELS["tr"], key


# Turkish words as they look when typed without their diacritics. A label
# containing one of these has been transliterated, which a Turkish reader sees
# at once and which reads as a different word more often than not.
ASCII_SPELLINGS = (
    "hakedis", "sozlesme", "yuklenici", "odenecek", "onceki", "isin", "isler", "tutari", "miktari", "fiyati",
    "farki", "kesintiler toplami", "cezasi", "tevkifati", "kiralari", "kurumlar vergisi kesintisi",
    "isveren", "duzenleme", "duzenleyenler", "donemi", "tanimi", "sira", "gecici", "goturu", "imalat tutari",
    "ihzarat miktari", "yapilan", "yapi", "muhendisi", "santiye", "sefi", "mudur", "teskilati", "aciklamalar",
    "adi soyadi", "olcu", "gerceklesen", "yuzde",
    "degistirilmistir", "kesinlesmemistir", "tutarlarin", "diger", "sagligi", "guvenligi", "is kalemi",
    "calisma", "secim", "gecerli", "sinir", "alici", "ust sinir", "gerekce",
)  # fmt: skip


def test_no_turkish_label_is_ascii_transliterated() -> None:
    for key, text in HAKEDIS_LABELS["tr"].items():
        lowered = tr_lower(text)
        for word in ASCII_SPELLINGS:
            assert not re.search(rf"(?<![a-zçğıöşü]){re.escape(word)}", lowered), (key, text, word)
    everything = "".join(HAKEDIS_LABELS["tr"].values())
    for letter in "çğıİöşüŞÖ":
        assert letter in everything, letter


def test_a_few_labels_spelled_out_with_their_diacritics() -> None:
    assert label("title.report", "tr") == "Hakediş Raporu"
    assert label("title.works_list", "tr") == "Yapılan İşler Listesi"
    assert label("section.deductions", "tr") == "Kesintiler ve Mahsuplar"
    assert label("subtitle.lump_sum", "tr") == "(Anahtar Teslimi Götürü Bedel İş)"
    assert label("header.work_to_date", "tr", date="31.07.2026") == "31.07.2026 tarihine kadar yapılan işin"
    assert label_parts("line.payable", "tr-en") == ("Yükleniciye Ödenecek Tutar", "Amount Payable to the Contractor")


def test_upper_case_is_turkish_aware() -> None:
    # i -> İ and ı -> I. Python's own upper() would print "IŞI" for "işi".
    assert tr_upper("işi") == "İŞİ"
    assert tr_upper("ı") == "I"
    assert tr_upper("i") == "İ"
    assert tr_upper("Hakediş Raporu") == "HAKEDİŞ RAPORU"
    assert tr_upper("Yapılan İşler Listesi") == "YAPILAN İŞLER LİSTESİ"
    assert tr_upper("Kesintiler ve Mahsuplar") == "KESİNTİLER VE MAHSUPLAR"
    assert tr_upper("31.07.2026 tarihine kadar yapılan işin") == "31.07.2026 TARİHİNE KADAR YAPILAN İŞİN"
    assert "işi".upper() != tr_upper("işi")
    assert tr_lower("IŞIK İLİ") == "ışık ili"
    assert upper_for("en", "Work item") == "WORK ITEM"
    assert upper_for("tr", "Yüklenici") == "YÜKLENİCİ"


# ── A contract's own arrangement ──────────────────────────────────────────


def test_no_terms_give_the_country_standard() -> None:
    assert resolve_layout("TR", None) == TR
    assert resolve_layout("tr", {}) == TR
    assert resolve_layout("TR", {"other": 1}) == TR
    settings = resolve_settings("TR", None)
    assert settings.retention_source == "contract" and settings.retention_pct is None
    assert settings.signature_roles == DEFAULT_SIGNATURE_ROLES["TR"]
    assert settings.tax_choices == {}


def test_gating_is_by_layout_not_by_a_list_of_countries() -> None:
    assert has_layout("TR")
    assert not has_layout("DE")
    assert has_layout("DE", terms(preset="TR_PRIVATE"))
    assert resolve_layout("DE", terms(preset="TR_PRIVATE")) == LAYOUT_PRESETS["TR_PRIVATE"]
    with pytest.raises(ValueError, match="no hakedis layout for country 'DE'"):
        resolve_layout("DE", None)


def test_a_private_contract_rearranges_the_deductions_by_configuration() -> None:
    # The arrangement a filled sample prints: the retention moved up to d)
    # under its own name, the rest re-lettered behind it, no plant rent, and a
    # back-charge line of the contract's own.
    settings = resolve_settings(
        "TR",
        terms(
            remove=["employer_plant_rent", "retention", "other_deductions"],
            add=[
                {
                    "key": "provisional_acceptance_retention",
                    "op": "retention",
                    "operands": ["this_certificate"],
                    "after": "vat_withholding",
                },
                {"key": "site_services", "op": "manual"},
            ],
            reletter=True,
            labels={
                "tr": {"line.site_services": "Şantiye Hizmetleri Kesintisi", "role.site_chief": "Saha Şefi"},
                "en": {"line.site_services": "Site Services Charge", "role.site_chief": "Site Chief"},
            },
            retention={"source": "fixed", "pct": "7.5"},
            advance_recovery_pct="15",
            taxes={
                "vat_withholding": {"state": "selected", "code": "SYN-W1"},
                "stamp_duty": {"state": "not_applicable", "reason": "borne by the employer under clause 9"},
            },
            not_applicable={"social_security": "released against a clearance letter"},
            signature_roles=["subcontractor", "site_chief", "project_manager", "employer"],
            columns={"unit_price": ["seq", "code", "description", "unit", "contract_quantity", "unit_price",
                                    "cumulative_quantity", "cumulative_amount", "period_amount"]},
        ),
    )  # fmt: skip
    deductions = [(line.letter, line.key) for line in settings.layout if line.section == "deductions"]
    assert deductions == [
        ("a", "income_tax"),
        ("b", "stamp_duty"),
        ("c", "vat_withholding"),
        ("d", "provisional_acceptance_retention"),
        ("e", "social_security"),
        ("f", "delay_penalty"),
        ("g", "advance_recovery"),
        ("h", "price_adjustment_guarantee"),
        ("i", "site_services"),
    ]
    total = next(line for line in settings.layout if line.key == "deductions_total")
    assert total.operands == tuple(key for _, key in deductions)
    assert settings.retention_source == "fixed" and settings.retention_pct == Decimal("7.5")
    assert settings.advance_recovery_pct == Decimal("15")
    assert settings.tax_choices["vat_withholding"] == Choice("selected", "SYN-W1")
    assert settings.tax_choices["stamp_duty"].state == "not_applicable"
    assert settings.not_applicable == {"social_security": "released against a clearance letter"}
    assert settings.signature_roles == ("subcontractor", "site_chief", "project_manager", "employer")
    assert "contract_quantity" in settings.columns["unit_price"]
    assert settings.columns["lump_sum"] == WORKS_DEFAULT_COLUMNS["lump_sum"]
    assert label("line.site_services", "tr", settings.labels) == "Şantiye Hizmetleri Kesintisi"
    assert label("role.site_chief", "en", settings.labels) == "Site Chief"
    # The stamp duty formula follows the new letter of the advance.
    stamp = next(line for line in settings.layout if line.key == "stamp_duty")
    assert line_formula(stamp, settings.layout, {"rate_pct": "1"}, "tr", str) == "( E - g x %1 )"


def test_removing_the_advance_leaves_the_stamp_duty_on_this_certificates_amount() -> None:
    layout = resolve_layout("TR", terms(remove=["advance_recovery"]))
    stamp = next(line for line in layout if line.key == "stamp_duty")
    assert stamp.operands == ("this_certificate",)


def test_no_retention_removes_the_line_and_a_base_can_be_chosen() -> None:
    layout = resolve_layout("TR", terms(retention={"source": "none"}))
    assert "retention" not in {line.key for line in layout}
    assert "retention" not in next(line for line in layout if line.key == "deductions_total").operands
    layout = resolve_layout("TR", terms(retention={"pct": "5", "base": ["accrued"]}))
    assert next(line for line in layout if line.key == "retention").operands == ("accrued",)


def test_a_whole_line_set_of_the_contracts_own() -> None:
    lines = [
        {"key": "work_done", "letter": "1", "op": "input", "operands": ["work_cumulative"], "section": "work"},
        {"key": "previous_certificates", "letter": "2", "op": "input", "operands": ["previous_certified_total"],
         "section": "work"},
        {"key": "this_certificate", "letter": "3", "op": "difference",
         "operands": ["work_done", "previous_certificates"], "section": "certificate"},
        {"key": "retention", "letter": "4", "op": "retention", "operands": ["this_certificate"]},
        {"key": "payable", "letter": "5", "op": "difference", "operands": ["this_certificate", "retention"],
         "section": "result"},
    ]  # fmt: skip
    layout = resolve_layout("XX", terms(lines=lines))
    assert [line.letter for line in layout] == ["1", "2", "3", "4", "5"]
    assert layout[3].sign == -1 and layout[4].sign == 1


@pytest.mark.parametrize(
    ("hakedis", "message"),
    [
        ({"colour": "blue"}, "unknown key 'colour'"),
        ({"preset": "TR_MOON"}, "unknown layout 'TR_MOON'"),
        ({"remove": ["no_such_line"]}, "'no_such_line'"),
        ({"remove": ["vat"]}, "'vat_withholding' refers to line 'vat', which does not exist"),
        ({"add": [{"key": "x", "op": "sum", "operands": ["ghost"]}], "labels": {}}, "'x' refers to line 'ghost'"),
        ({"add": [{"key": "x", "op": "manual", "after": "ghost"}]}, "'after' names line 'ghost'"),
        ({"add": [{"key": "x", "op": "manual", "colour": 1}]}, "unknown key 'colour'"),
        ({"add": [{"key": "vat", "op": "manual"}]}, "defines line 'vat' twice"),
        ({"add": [{"key": "x", "op": "manual"}]}, "line 'x' has no 'tr' label"),
        ({"add": [{"key": "back_charges", "op": "guess"}]}, "'back_charges' has unknown operation 'guess'"),
        ({"add": [{"key": "back_charges", "op": "tax", "tax_kind": "luxury"}]}, "unknown tax kind 'luxury'"),
        ({"letters": {"retention": "a"}}, "letter 'a' for both 'income_tax' and 'retention'"),
        ({"letters": {"ghost": "z"}}, "'letters' names line 'ghost'"),
        ({"operands": {"total": ["work_done", "payable"]}}, "cycle through 'total'"),
        ({"operands": {"ghost": ["vat"]}}, "'operands' names line 'ghost'"),
        ({"retention": {"source": "fixed"}}, "no 'pct' is given"),
        ({"retention": {"pct": "150"}}, "between 0 and 100"),
        ({"retention": {"pct": "five"}}, "must be a number"),
        ({"retention": {"rate": "5"}}, "unknown key 'rate'"),
        ({"retention": {"source": "bank"}}, "unknown source 'bank'"),
        ({"advance_recovery_pct": "10", "remove": ["advance_recovery"]}, "needs a manual 'advance_recovery' line"),
        ({"taxes": {"luxury": {"state": "unset"}}}, "unknown tax 'luxury'"),
        ({"taxes": {"stamp_duty": {"state": "selected"}}}, "selected without a code"),
        ({"taxes": {"stamp_duty": {"state": "not_applicable"}}}, "not applicable without a reason"),
        ({"taxes": {"stamp_duty": {"state": "maybe"}}}, "unknown state 'maybe'"),
        ({"not_applicable": {"vat": "no"}}, "'vat', which is not a manual line"),
        ({"not_applicable": {"delay_penalty": " "}}, "no reason for line 'delay_penalty'"),
        ({"signature_roles": ["contractor", "astronaut"]}, "role 'astronaut' has no 'tr' label"),
        ({"signature_roles": []}, "non-empty list"),
        ({"columns": {"cost_plus": ["seq"]}}, "unknown flavour 'cost_plus'"),
        ({"columns": {"unit_price": ["seq", "colour"]}}, "unknown column 'colour'"),
        ({"labels": {"de": {}}}, "unknown language 'de'"),
        ({"lines": [{"key": "payable", "op": "input", "operands": ["thin_air"]}]}, "'payable' must read exactly one"),
        ({"lines": [{"key": "work_done", "op": "input", "operands": ["work_cumulative"]}]}, "no 'payable' line"),
    ],
)
def test_a_configuration_that_cannot_be_used_is_refused_by_name(hakedis: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        resolve_settings("TR", {"hakedis": hakedis})


def test_a_cycle_is_reported_with_its_path() -> None:
    layout = (
        SummaryLineDef("a", "A", "sum", ("b",), 1),
        SummaryLineDef("b", "B", "sum", ("payable",), 1),
        SummaryLineDef("payable", "", "difference", ("a",), 1),
    )
    with pytest.raises(ValueError, match=re.escape("a -> b -> payable -> a")):
        validate_layout(layout)


def test_terms_that_are_not_an_object_are_refused() -> None:
    with pytest.raises(ValueError, match="must be an object"):
        resolve_settings("TR", {"hakedis": ["retention"]})


def test_a_tax_the_contract_does_not_settle_is_unset_never_a_shipped_row() -> None:
    for contract_terms in (None, terms(preset="TR_PRIVATE")):
        settings = resolve_settings("TR", contract_terms)
        for tax in ("vat_withholding", "income_withholding", "stamp_duty"):
            assert tax_choice(settings, tax) == Choice("unset"), tax
    chosen = resolve_settings("TR", terms(taxes={"stamp_duty": {"state": "selected", "code": "SYN-S1"}}))
    assert tax_choice(chosen, "stamp_duty") == Choice("selected", "SYN-S1")
    assert tax_choice(chosen, "income_withholding") == Choice("unset")


def test_a_sentence_never_prints_a_brace_for_a_missing_parameter() -> None:
    assert label_filled("reason.not_applicable_by_user", "en", None, {}) == "Marked as not applicable: ..."
    assert label_filled("reason.no_rate_on_date", "tr", None, {"code": "X1"}) == (
        "... tarihinde X1 kodu için yürürlükte bir oran yok."
    )
    # The page counter is a template its caller fills in later.
    assert label("page.of", "tr") == "Sayfa {page} / {pages}"


# ── Words both documents share ────────────────────────────────────────────


def test_the_lira_is_written_tl_in_turkish_and_any_other_currency_by_its_code() -> None:
    assert currency_label("TRY", "tr") == "TL"
    # English keeps the ISO code, like the other printed documents of the set.
    assert currency_label("TRY", "en") == "TRY"
    assert currency_label("EUR", "tr") == "EUR"
    assert currency_label("EUR", "tr", {"tr": {"currency.EUR": "Avro"}}) == "Avro"


def test_the_paid_party_is_named_as_it_signs() -> None:
    assert contractor_label_key(DEFAULT_SIGNATURE_ROLES["TR"]) == "header.contractor"
    assert contractor_label_key(("subcontractor", "employer")) == "role.subcontractor"
    assert label("role.subcontractor", "tr") == "Alt Yüklenici"


def test_only_a_currency_other_than_the_countrys_own_is_foreign() -> None:
    assert not is_foreign_currency("TR", "TRY")
    assert not is_foreign_currency("tr", " try ")
    assert is_foreign_currency("TR", "EUR")
    # A country with no home currency on record makes no claim either way.
    assert not is_foreign_currency("DE", "EUR")
    assert not is_foreign_currency(None, "EUR")


def test_the_lump_sum_labels_say_what_the_columns_hold() -> None:
    assert label("col.lump_sum.contract_amount", "tr") == "İş Grubu Sözleşme Bedeli"
    assert label("col.lump_sum.contract_amount", "en") == "Work Group Contract Amount"
    assert "A sütunu iş grubunun sözleşme bedelindeki payını" in label("works.weight_note", "tr")


def test_a_foreign_currency_certificate_is_told_where_its_lira_equivalent_belongs() -> None:
    text = label("fx.explanation", "tr", None, currency="EUR")
    assert text.startswith("Bu hakediş EUR cinsinden düzenlenmiştir")
    assert "VUK md. 215" in text and "KDV Kanunu md. 26" in text
    assert label("fx.rate_missing", "en") == "TL equivalent: exchange rate not entered."
