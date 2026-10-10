# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The arithmetic of the hakediş (Turkish progress payment certificate).

One realistic bill for an MEP subcontract, twenty five mechanical and
electrical rows, is certified three times, the third being final. Every
lettered line of every certificate is pinned, the certificates are checked
against each other (what one prints as cumulative the next prints as
previous), and the final one has to land exactly on the contract value.

Every rate in this file is SYNTHETIC. The VAT rate, the withholding fraction,
the income withholding rate and the stamp duty rate below are round numbers
chosen so the arithmetic can be followed by hand; none of them is a Turkish
rate and none may be read as one. The poz-style codes are invented as well.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.core.payment_taxes import Choice, Figure, PaymentTaxInput, PaymentTaxResult, RateRow, compute_payment_taxes
from app.modules.contracts.hakedis import (
    Certificate,
    CertificateInput,
    CertificateParty,
    CertificateWorkLine,
    ManualLine,
    compute_certificate,
    expected_tax_bases,
    lump_sum_line_amounts,
    manual_lines_for,
)
from app.modules.contracts.hakedis_layout import DEFAULT_LAYOUTS, resolve_settings

D = Decimal

# SYNTHETIC rates, illustrative only.
SYNTHETIC_VAT_PCT = D("10")
SYNTHETIC_WITHHOLDING = (1, 2)
SYNTHETIC_INCOME_PCT = D("2")
SYNTHETIC_STAMP_PCT = D("1")
SYNTHETIC_RETENTION_PCT = D("10")
SYNTHETIC_ADVANCE_PCT = D("20")

MECHANICAL = "01 - MEKANİK TESİSAT"
ELECTRICAL = "02 - ELEKTRİK TESİSATI"

# code, description, unit, contract quantity, unit price, quantity of certificates 1, 2 and 3.
# Row 3 is over-measured in the second certificate (900 against 850) and
# corrected by a negative quantity in the third.
BILL: tuple[tuple[str, str, str, str, str, str, str, str, str], ...] = (
    (MECHANICAL, "M-25.101", "Siyah çelik boru DN50, dişli, yangın tesisatı", "m", "1200", "485.75", "400", "500", "300"),
    (MECHANICAL, "M-25.102", "Siyah çelik boru DN100, kaynaklı, yangın tesisatı", "m", "640.5", "1120.40", "200", "240.5", "200"),
    (MECHANICAL, "M-25.210", "Sprinkler başlığı, sarkık tip, 68°C", "adet", "850", "312.00", "300", "600", "-50"),
    (MECHANICAL, "M-25.305", "Yangın dolabı, hortumlu, gömme tip", "adet", "42", "9850.00", "10", "20", "12"),
    (MECHANICAL, "M-26.110", "PPR-C temiz su borusu Ø32", "m", "2100", "96.35", "700", "900", "500"),
    (MECHANICAL, "M-26.115", "PVC pis su borusu Ø110", "m", "980.25", "148.90", "300.25", "400", "280"),
    (MECHANICAL, "M-27.040", "Galvanizli sac hava kanalı, dikdörtgen kesitli", "m²", "3450.75", "742.18", "1000.255", "1500.495", "950"),
    (MECHANICAL, "M-27.120", "Kanal izolasyonu, kauçuk köpüğü, 19 mm", "m²", "2800", "265.44", "800", "1200", "800"),
    (MECHANICAL, "M-27.310", "Fan coil ünitesi, dört borulu, tavan tipi", "adet", "120", "28450.00", "30", "60", "30"),
    (MECHANICAL, "M-27.520", "Klima santrali, 20.000 m³/h, ısı geri kazanımlı", "adet", "4", "1875000.00", "1", "2", "1"),
    (MECHANICAL, "M-28.015", "Soğutma grubu, hava soğutmalı, 750 kW", "adet", "2", "6420000.00", "0", "1", "1"),
    (MECHANICAL, "M-28.140", "Sirkülasyon pompası, frekans konvertörlü", "adet", "16", "184300.50", "4", "8", "4"),
    (MECHANICAL, "M-29.005", "Test, ayar ve dengeleme (TAD) işleri", "takım", "1", "950000.00", "0", "0.4", "0.6"),
    (ELECTRICAL, "E-35.110", "NYY kablo 3x2,5 mm², döşeme dahil", "m", "18500", "64.27", "6000", "8000", "4500"),
    (ELECTRICAL, "E-35.145", "N2XH kablo 4x95 mm², halojensiz", "m", "1250.5", "2315.85", "400", "500.5", "350"),
    (ELECTRICAL, "E-35.300", "Sıcak daldırma galvaniz kablo tavası 300x60 mm", "m", "2200", "418.60", "800", "900", "500"),
    (ELECTRICAL, "E-36.020", "Ana dağıtım panosu (ADP), 4000 A", "adet", "2", "2950000.00", "0", "1", "1"),
    (ELECTRICAL, "E-36.085", "Tali dağıtım panosu, sıva üstü", "adet", "36", "86500.00", "10", "16", "10"),
    (ELECTRICAL, "E-36.210", "Busbar sistemi, 2500 A, alüminyum", "m", "180.4", "31250.75", "60.405", "69.995", "50"),
    (ELECTRICAL, "E-37.010", "LED armatür, 60x60, 40 W, gömme", "adet", "2400", "1485.00", "800", "1000", "600"),
    (ELECTRICAL, "E-37.130", "Acil aydınlatma armatürü, kesintide 3 saat yanan", "adet", "310", "2260.40", "100", "130", "80"),
    (ELECTRICAL, "E-38.050", "Yangın algılama dedektörü, optik duman", "adet", "1150", "978.65", "400", "450", "300"),
    (ELECTRICAL, "E-38.200", "Yangın alarm paneli, adresli, 4 çevrimli", "adet", "3", "412000.00", "1", "1", "1"),
    (ELECTRICAL, "E-39.015", "Topraklama iletkeni, örgülü bakır 50 mm²", "m", "3200.75", "356.19", "1200.755", "1199.995", "800"),
    (ELECTRICAL, "E-39.400", "Dizel jeneratör grubu, 1600 kVA, kabinli", "adet", "2", "9875000.00", "0", "1", "1"),
)  # fmt: skip

#: The contract value of the bill: every row's contract quantity at its price, rounded per row.
CONTRACT_VALUE = D("80458595.44")

EMPLOYER = CertificateParty(
    name="Örnek Ana Yüklenici İnşaat A.Ş.",
    tax_number="1234567890",
    tax_office="Büyük Mükellefler",
    address="Çankaya, Ankara",
)
CONTRACTOR = CertificateParty(
    name="Örnek Mekanik ve Elektrik Taahhüt Ltd. Şti.",
    tax_number="9876543210",
    tax_office="Şişli",
    address="Şişli, İstanbul",
)

PERIODS = {
    1: (date(2026, 7, 1), date(2026, 7, 31)),
    2: (date(2026, 8, 1), date(2026, 8, 31)),
    3: (date(2026, 9, 1), date(2026, 9, 30)),
}


def unit_price_lines(number: int) -> list[CertificateWorkLine]:
    """The bill as certificate ``number`` sees it: what came before, and this period."""
    lines = []
    for section, code, description, unit, contract_quantity, price, *periods in BILL:
        measured = [D(q) for q in periods]
        lines.append(
            CertificateWorkLine(
                code=code,
                description=description,
                unit=unit,
                contract_quantity=D(contract_quantity),
                previous_quantity=sum(measured[: number - 1], D(0)),
                period_quantity=measured[number - 1],
                unit_price=D(price),
                contract_amount=None,
                weight_pct=None,
                previous_pct=None,
                period_pct=None,
                section=section,
            )
        )
    return lines


def figure(kind: str, amount: Decimal | None, base: Decimal | None, **changes: Any) -> Figure:
    """A tax figure built by hand, a value unless told otherwise."""
    fields: dict[str, Any] = {
        "kind": kind,
        "status": "value",
        "amount": amount,
        "base": base,
        "rate_pct": None,
        "numerator": None,
        "denominator": None,
        "code": "",
        "legal_reference": "",
        "effective_from": date(2026, 1, 1),
        "review_status": "confirmed",
        "overridden": False,
        "reason_key": "",
        "reason_params": {},
    }
    fields.update(changes)
    return Figure(**fields)


def q(value: Decimal) -> Decimal:
    return value.quantize(D("0.01"), rounding="ROUND_HALF_UP")


def synthetic_taxes(net: Decimal, stamp_base: Decimal) -> PaymentTaxResult:
    """The five figures at the SYNTHETIC rates above, each on the base the layout expects."""
    vat = q(net * SYNTHETIC_VAT_PCT / 100)
    withheld = q(vat * SYNTHETIC_WITHHOLDING[0] / SYNTHETIC_WITHHOLDING[1])
    return PaymentTaxResult(
        vat_computed=figure("vat_computed", vat, net, rate_pct=SYNTHETIC_VAT_PCT),
        vat_withheld=figure(
            "vat_withheld",
            withheld,
            vat,
            numerator=SYNTHETIC_WITHHOLDING[0],
            denominator=SYNTHETIC_WITHHOLDING[1],
            code="SYN-W1",
            legal_reference="Synthetic withholding table, row 1",
        ),
        vat_payable=figure("vat_payable", vat - withheld, vat),
        income_withheld=figure(
            "income_withheld",
            q(net * SYNTHETIC_INCOME_PCT / 100),
            net,
            rate_pct=SYNTHETIC_INCOME_PCT,
            code="SYN-I1",
            legal_reference="Synthetic income withholding, article 1",
        ),
        stamp_duty=figure(
            "stamp_duty",
            q(stamp_base * SYNTHETIC_STAMP_PCT / 100),
            stamp_base,
            rate_pct=SYNTHETIC_STAMP_PCT,
            code="SYN-S1",
            legal_reference="Synthetic stamp duty table, line 1",
        ),
    )


# What a person entered on each certificate. The price adjustment is cumulative.
MANUAL: dict[int, dict[str, ManualLine]] = {
    1: {
        "price_adjustment": ManualLine("price_adjustment", "not_applicable", None, "no adjustment clause yet"),
        "social_security": ManualLine("social_security", "value", D("0")),
        "delay_penalty": ManualLine("delay_penalty", "not_applicable", None),
    },
    2: {
        "price_adjustment": ManualLine("price_adjustment", "value", D("125000.00")),
        "social_security": ManualLine("social_security", "value", D("0")),
        "delay_penalty": ManualLine("delay_penalty", "not_applicable", None),
    },
    3: {
        "price_adjustment": ManualLine("price_adjustment", "value", D("200000.00")),
        "social_security": ManualLine("social_security", "value", D("5000.00")),
        "delay_penalty": ManualLine("delay_penalty", "value", D("10000.00")),
    },
}

#: What the contract settles once for every certificate.
CONTRACT_TERMS = {
    "hakedis": {
        "retention": {"source": "fixed", "pct": str(SYNTHETIC_RETENTION_PCT)},
        "advance_recovery_pct": str(SYNTHETIC_ADVANCE_PCT),
        "not_applicable": {
            "employer_plant_rent": "no employer plant on this job",
            "price_adjustment_guarantee": "covered by a letter of guarantee",
            "other_deductions": "none agreed",
        },
    }
}
SETTINGS = resolve_settings("TR", CONTRACT_TERMS)


def certificate_input(number: int, previous_total: Decimal | None, **changes: Any) -> CertificateInput:
    start, end = PERIODS[number]
    fields: dict[str, Any] = {
        "flavour": "unit_price",
        "certificate_number": number,
        "is_final": number == 3,
        "period_start": start,
        "period_end": end,
        "currency": "TRY",
        "country_code": "TR",
        "project_name": "Örnek Veri Merkezi İnşaatı",
        "contract_number": "ALT-2026-014",
        "contract_title": "Mekanik ve Elektrik Tesisat İşleri Alt Yüklenici Sözleşmesi",
        "employer": EMPLOYER,
        "contractor": CONTRACTOR,
        "lines": unit_price_lines(number),
        "previous_certified_total": previous_total,
        "manual_lines": manual_lines_for(SETTINGS, MANUAL[number]),
        "retention_pct": SETTINGS.retention_pct,
        "taxes": None,
        "layout": SETTINGS.layout,
        "signature_roles": SETTINGS.signature_roles,
    }
    fields.update(changes)
    return CertificateInput(**fields)


def certify(number: int, previous_total: Decimal | None, **changes: Any) -> Certificate:
    """Certificate ``number`` with its taxes computed on the bases the layout expects."""
    inp = certificate_input(number, previous_total, **changes)
    if "taxes" not in changes:
        bases = expected_tax_bases(inp)
        assert bases["vat_computed"] is not None and bases["stamp_duty"] is not None
        inp = replace(inp, taxes=synthetic_taxes(bases["vat_computed"], bases["stamp_duty"]))
    return compute_certificate(inp)


def three_certificates() -> list[Certificate]:
    certificates: list[Certificate] = []
    previous = D("0")
    for number in (1, 2, 3):
        cert = certify(number, previous)
        certificates.append(cert)
        previous = cert.line("total").amount
    return certificates


def amounts(cert: Certificate) -> dict[str, Decimal | None]:
    return {(line.letter or line.key): line.amount for line in cert.summary}


# Every lettered line of the three certificates, checked by hand against the
# bill above at the SYNTHETIC rates. None stands for a line that does not apply.
EXPECTED: dict[int, dict[str, Decimal | None]] = {
    1: {
        "A": D("12187793.96"),
        "B": None,
        "C": D("12187793.96"),
        "D": D("0.00"),
        "E": D("12187793.96"),
        "F": D("1218779.40"),
        "G": D("13406573.36"),
        "a": D("243755.88"),
        "b": D("97502.35"),
        "c": D("609389.70"),
        "d": D("0.00"),
        "e": None,
        "f": None,
        "g": D("2437558.79"),
        "h": None,
        "i": D("1218779.40"),
        "j": None,
        "H": D("4606986.12"),
        "payable": D("8799587.24"),
    },
    2: {
        "A": D("49899219.44"),
        "B": D("125000.00"),
        "C": D("50024219.44"),
        "D": D("12187793.96"),
        "E": D("37836425.48"),
        "F": D("3783642.55"),
        "G": D("41620068.03"),
        "a": D("756728.51"),
        "b": D("302691.40"),
        "c": D("1891821.28"),
        "d": D("0.00"),
        "e": None,
        "f": None,
        "g": D("7567285.10"),
        "h": None,
        "i": D("3783642.55"),
        "j": None,
        "H": D("14302168.84"),
        "payable": D("27317899.19"),
    },
    3: {
        "A": D("80458595.44"),
        "B": D("200000.00"),
        "C": D("80658595.44"),
        "D": D("50024219.44"),
        "E": D("30634376.00"),
        "F": D("3063437.60"),
        "G": D("33697813.60"),
        "a": D("612687.52"),
        "b": D("245075.01"),
        "c": D("1531718.80"),
        "d": D("5000.00"),
        "e": None,
        "f": D("10000.00"),
        "g": D("6126875.20"),
        "h": None,
        "i": D("3063437.60"),
        "j": None,
        "H": D("11594794.13"),
        "payable": D("22103019.47"),
    },
}


@pytest.fixture(scope="module")
def certificates() -> list[Certificate]:
    return three_certificates()


@pytest.mark.parametrize("number", [1, 2, 3])
def test_every_lettered_line_of_each_certificate(certificates: list[Certificate], number: int) -> None:
    assert amounts(certificates[number - 1]) == EXPECTED[number]


def test_the_bill_adds_up_to_the_contract_value() -> None:
    independent = sum((q(D(row[4]) * D(row[5])) for row in BILL), D(0))
    assert independent == CONTRACT_VALUE


def test_the_final_certificate_lands_exactly_on_the_contract_value(certificates: list[Certificate]) -> None:
    final = certificates[2]
    assert final.inp.is_final
    assert final.line("work_done").amount == CONTRACT_VALUE
    assert final.totals.cumulative_amount == CONTRACT_VALUE
    assert final.totals.contract_amount == CONTRACT_VALUE
    for row in final.work_lines:
        assert row.cumulative_amount == row.contract_amount, row.code
        assert row.cumulative_quantity == row.contract_quantity, row.code


def test_what_one_certificate_prints_as_cumulative_the_next_prints_as_previous(
    certificates: list[Certificate],
) -> None:
    for earlier, later in zip(certificates, certificates[1:], strict=False):
        for before, after in zip(earlier.work_lines, later.work_lines, strict=True):
            assert after.previous_quantity == before.cumulative_quantity, after.code
            assert after.previous_amount == before.cumulative_amount, after.code
        assert later.line("previous_certificates").amount == earlier.line("total").amount
        assert later.totals.previous_amount == earlier.totals.cumulative_amount


def test_the_period_amounts_of_all_certificates_add_up_to_the_last_cumulative(
    certificates: list[Certificate],
) -> None:
    for position in range(len(BILL)):
        periods = sum((cert.work_lines[position].period_amount for cert in certificates), D(0))
        assert periods == certificates[-1].work_lines[position].cumulative_amount
    assert (
        sum((cert.line("this_certificate").amount for cert in certificates), D(0))
        == certificates[-1].line("total").amount
    )


@pytest.mark.parametrize("number", [1, 2, 3])
def test_a_row_and_a_column_both_add_up(certificates: list[Certificate], number: int) -> None:
    cert = certificates[number - 1]
    for row in cert.work_lines:
        assert row.previous_amount + row.period_amount == row.cumulative_amount, row.code
        assert row.cumulative_amount == q(row.cumulative_quantity * row.unit_price), row.code
    totals = cert.totals
    assert totals.cumulative_amount == sum((row.cumulative_amount for row in cert.work_lines), D(0))
    assert totals.previous_amount + totals.period_amount == totals.cumulative_amount
    assert cert.line("work_done").amount == totals.cumulative_amount


def test_the_summary_follows_the_forms_arithmetic(certificates: list[Certificate]) -> None:
    for cert in certificates:
        line = {item.key: item.amount or D(0) for item in cert.summary}
        assert line["total"] == line["work_done"] + line["price_adjustment"]
        assert line["this_certificate"] == line["total"] - line["previous_certificates"]
        assert line["vat"] == q(line["this_certificate"] * SYNTHETIC_VAT_PCT / 100)
        assert line["accrued"] == line["this_certificate"] + line["vat"]
        assert line["advance_recovery"] == q(line["this_certificate"] * SYNTHETIC_ADVANCE_PCT / 100)
        assert line["stamp_duty"] == q(
            (line["this_certificate"] - line["advance_recovery"]) * SYNTHETIC_STAMP_PCT / 100
        )
        assert line["retention"] == q(line["this_certificate"] * SYNTHETIC_RETENTION_PCT / 100)
        deductions = [item.amount or D(0) for item in cert.summary if item.section == "deductions"]
        assert line["deductions_total"] == sum(deductions, D(0))
        assert line["payable"] == line["accrued"] - line["deductions_total"]
        assert cert.payable.amount == line["payable"]
        assert not cert.is_draft


def test_an_over_measured_row_is_flagged_not_blocked(certificates: list[Certificate]) -> None:
    second = {row.code: row for row in certificates[1].work_lines}
    sprinkler = second["M-25.210"]
    assert sprinkler.over_measured
    assert sprinkler.over_by == D("50")
    assert sprinkler.cumulative_amount == D("280800.00")
    assert [row.code for row in certificates[1].work_lines if row.over_measured] == ["M-25.210"]
    assert not any(row.over_measured for row in certificates[0].work_lines)


def test_a_negative_period_quantity_corrects_an_earlier_over_measurement(certificates: list[Certificate]) -> None:
    sprinkler = {row.code: row for row in certificates[2].work_lines}["M-25.210"]
    assert sprinkler.period_quantity == D("-50")
    assert sprinkler.period_amount == D("-15600.00")
    assert sprinkler.cumulative_quantity == D("850")
    assert sprinkler.cumulative_amount == D("265200.00")
    assert not sprinkler.over_measured


def test_a_tax_line_carries_what_an_accountant_needs_to_check_it(certificates: list[Certificate]) -> None:
    cert = certificates[0]
    net = cert.line("this_certificate").amount
    withholding = cert.line("vat_withholding").basis
    assert withholding["numerator"] == "1" and withholding["denominator"] == "2"
    assert withholding["code"] == "SYN-W1"
    assert withholding["legal_reference"] == "Synthetic withholding table, row 1"
    assert withholding["review_status"] == "confirmed"
    assert withholding["overridden"] == "false"
    assert Decimal(withholding["base"]) == cert.line("vat").amount
    income = cert.line("income_tax").basis
    assert Decimal(income["base"]) == net and Decimal(income["rate_pct"]) == SYNTHETIC_INCOME_PCT
    retention = cert.line("retention").basis
    assert Decimal(retention["base"]) == net and Decimal(retention["rate_pct"]) == SYNTHETIC_RETENTION_PCT


def test_the_withheld_vat_is_deducted_once_and_the_payable_vat_is_not_a_line(certificates: list[Certificate]) -> None:
    keys = {line.key for line in certificates[0].summary}
    assert "vat" in keys and "vat_withholding" in keys
    assert not any(defn.tax_kind == "vat_payable" for defn in DEFAULT_LAYOUTS["TR"])


# ── The shared calculation, with synthetic rows ───────────────────────────


def synthetic_row(kind: str, code: str, **changes: Any) -> RateRow:
    """A SYNTHETIC rate row. Not a Turkish rate, not law, never shipped."""
    fields: dict[str, Any] = {
        "country_code": "TR",
        "kind": kind,
        "code": code,
        "labels": {"tr": f"Sentetik {code}", "en": f"Synthetic {code}"},
        "base": "net",
        "rate_pct": None,
        "numerator": None,
        "denominator": None,
        "threshold_amount": None,
        "threshold_currency": "",
        "threshold_scope": "",
        "threshold_measure": "",
        "cap_amount": None,
        "effective_from": date(2020, 1, 1),
        "effective_to": None,
        "legal_reference": f"Synthetic rule {code}",
        "source_url": "https://example.invalid/synthetic",
        "read_date": "2026-10-10",
        "review_status": "unconfirmed",
    }
    fields.update(changes)
    return RateRow(**fields)


SYNTHETIC_ROWS = (
    synthetic_row("vat_withholding", "SYN-W1", base="vat", numerator=1, denominator=2),
    synthetic_row("income_withholding", "SYN-I1", rate_pct=SYNTHETIC_INCOME_PCT),
    synthetic_row("stamp_duty", "SYN-S1", rate_pct=SYNTHETIC_STAMP_PCT),
)


def test_figures_from_the_shared_calculation_print_on_the_certificate() -> None:
    # No advance on this contract, so the stamp duty base is line E and one
    # call of the shared calculation serves all four tax lines.
    settings = resolve_settings("TR", {"hakedis": {"retention": {"pct": "10"}, "remove": ["advance_recovery"]}})
    manual = {
        key: ManualLine(key, "not_applicable", None)
        for key in ("price_adjustment", "social_security", "employer_plant_rent", "delay_penalty")
    } | {key: ManualLine(key, "not_applicable", None) for key in ("price_adjustment_guarantee", "other_deductions")}
    inp = certificate_input(
        1, D("0"), manual_lines=manual, layout=settings.layout, retention_pct=settings.retention_pct
    )
    net = expected_tax_bases(inp)["vat_computed"]
    assert net is not None and expected_tax_bases(inp)["stamp_duty"] == net
    taxes = compute_payment_taxes(
        PaymentTaxInput(
            country_code="TR",
            currency="TRY",
            on=inp.period_end,
            net_amount=net,
            vat_rate_pct=SYNTHETIC_VAT_PCT,
            vat_withholding=Choice("selected", "SYN-W1"),
            income_withholding=Choice("selected", "SYN-I1"),
            stamp_duty=Choice("selected", "SYN-S1"),
        ),
        SYNTHETIC_ROWS,
    )
    cert = compute_certificate(replace(inp, taxes=taxes))
    vat = q(net * SYNTHETIC_VAT_PCT / 100)
    assert cert.line("vat").amount == vat
    assert cert.line("vat_withholding").amount == q(vat / 2)
    assert cert.line("income_tax").amount == q(net * SYNTHETIC_INCOME_PCT / 100)
    assert cert.line("stamp_duty").amount == q(net * SYNTHETIC_STAMP_PCT / 100)
    assert cert.payable.status == "value"
    # The synthetic rows are unconfirmed, and that travels to the document.
    assert cert.line("income_tax").basis["review_status"] == "unconfirmed"
    assert cert.is_draft
    assert {note.reason_key for note in cert.notes} == {"unconfirmed_rate"}


# ── Lump sum ──────────────────────────────────────────────────────────────


def lump_sum_input(
    amounts_: list[Decimal], weights: list[Decimal], previous_pct: Decimal, period_pct: Decimal, **changes: Any
) -> CertificateInput:
    lines = [
        CertificateWorkLine(
            code=f"G-{index:02d}",
            description=f"İş grubu {index}",
            unit="",
            contract_quantity=None,
            previous_quantity=None,
            period_quantity=None,
            unit_price=None,
            contract_amount=amount,
            weight_pct=weight,
            previous_pct=previous_pct,
            period_pct=period_pct,
        )
        for index, (amount, weight) in enumerate(zip(amounts_, weights, strict=True), start=1)
    ]
    fields: dict[str, Any] = {"flavour": "lump_sum", "lines": lines, "manual_lines": {}}
    fields.update(changes)
    return certificate_input(1, D("0"), **fields)


def test_seven_groups_of_14_2857_share_the_whole_contract_price() -> None:
    weights = [D("14.2857")] * 7
    assert sum(weights) == D("99.9999")
    shares = lump_sum_line_amounts(D("1000000.00"), weights, "TRY")
    assert sum(shares) == D("1000000.00")
    assert sorted(set(shares)) == [D("142857.14"), D("142857.15")]
    assert shares.count(D("142857.15")) == 2


@pytest.mark.parametrize(
    ("contract", "weights"),
    [
        (D("1000000.00"), ["33.33", "33.33", "33.34"]),
        (D("100000.01"), ["33.33", "33.33", "33.34"]),
        (D("1000000.00"), ["14.2857"] * 7),
        (D("987654.32"), ["14.2857"] * 7),
    ],
)
def test_a_lump_sum_contract_lands_exactly_on_its_price_with_no_drift(contract: Decimal, weights: list[str]) -> None:
    group_weights = [D(weight) for weight in weights]
    shares = lump_sum_line_amounts(contract, group_weights, "TRY")
    assert sum(shares) == contract
    # Three certificates of 33.33, 33.33 and 33.34 percent of every group.
    steps = [D("33.33"), D("33.33"), D("33.34")]
    done = D("0")
    period_total = D("0")
    previous_cumulative = D("0")
    for step in steps:
        cert = compute_certificate(lump_sum_input(shares, group_weights, done, step))
        assert cert.totals.previous_amount == previous_cumulative
        for row in cert.work_lines:
            assert row.previous_amount + row.period_amount == row.cumulative_amount
        period_total += cert.totals.period_amount
        previous_cumulative = cert.totals.cumulative_amount
        done += step
    assert done == D("100")
    assert previous_cumulative == contract
    assert period_total == contract
    assert cert.line("work_done").amount == contract
    assert all(row.cumulative_amount == row.contract_amount for row in cert.work_lines)


def test_a_lump_sum_row_prints_its_percentages_and_flags_more_than_a_hundred() -> None:
    cert = compute_certificate(lump_sum_input([D("250000.00")], [D("100")], D("90"), D("15")))
    row = cert.work_lines[0]
    assert (row.previous_pct, row.period_pct, row.cumulative_pct) == (D("90"), D("15"), D("105"))
    assert row.previous_amount == D("225000.00")
    assert row.cumulative_amount == D("262500.00")
    assert row.period_amount == D("37500.00")
    assert row.over_measured and row.over_by == D("5")


def test_weights_that_add_up_to_zero_are_refused() -> None:
    with pytest.raises(ValueError, match="zero"):
        lump_sum_line_amounts(D("100"), [D("0"), D("0")], "TRY")


def test_a_negative_weight_and_a_total_finer_than_the_currency_are_refused() -> None:
    with pytest.raises(ValueError, match="negative"):
        lump_sum_line_amounts(D("100"), [D("1"), D("-2")], "TRY")
    with pytest.raises(ValueError, match="more decimals"):
        lump_sum_line_amounts(D("100.005"), [D("1"), D("2")], "TRY")


# ── Held, not applicable, value ───────────────────────────────────────────


def statuses(cert: Certificate) -> dict[str, str]:
    return {line.key: line.status for line in cert.summary}


def test_without_the_tax_module_every_tax_line_is_held_and_so_is_what_adds_them() -> None:
    cert = certify(1, D("0"), taxes=None)
    status = statuses(cert)
    for key in ("vat", "income_tax", "stamp_duty", "vat_withholding"):
        assert status[key] == "held", key
        assert cert.line(key).amount is None
        assert cert.line(key).basis["reason"] == "module_absent"
    assert status["this_certificate"] == "value"
    assert status["accrued"] == "held"
    assert cert.line("accrued").basis["held_operands"] == "vat"
    assert cert.line("deductions_total").basis["held_operands"] == "income_tax, stamp_duty, vat_withholding"
    assert cert.payable.status == "held" and cert.payable.amount is None
    assert cert.payable.basis["held_operands"] == "accrued, deductions_total"
    assert cert.is_draft
    # One note per root cause; the totals held on their account get none.
    assert [note.line_key for note in cert.notes] == ["vat", "income_tax", "stamp_duty", "vat_withholding"]


def test_an_unknown_previous_total_holds_this_certificate_and_every_tax_on_it() -> None:
    cert = certify(2, None, taxes=synthetic_taxes(D("1000.00"), D("800.00")))
    assert cert.line("previous_certificates").basis["reason"] == "previous_unknown"
    assert cert.line("this_certificate").status == "held"
    assert cert.line("this_certificate").basis["held_operands"] == "previous_certificates"
    # The provider answered, but nobody knows the base its figures belong to.
    for key in ("vat", "income_tax", "stamp_duty"):
        assert cert.line(key).basis["reason"] == "base_held", key
    assert cert.line("retention").basis["reason"] == "base_held"
    assert cert.payable.status == "held"


def test_an_unknown_retention_percent_holds_the_retention_line() -> None:
    cert = certify(1, D("0"), retention_pct=None)
    assert cert.line("retention").status == "held"
    assert cert.line("retention").basis["reason"] == "retention_unknown"
    assert cert.line("accrued").status == "value"
    assert cert.line("deductions_total").basis["held_operands"] == "retention"
    assert cert.payable.status == "held"


def test_a_manual_line_nobody_entered_is_held_not_zero() -> None:
    manual = dict(manual_lines_for(SETTINGS, MANUAL[1]))
    del manual["social_security"]
    cert = certify(1, D("0"), manual_lines=manual)
    assert cert.line("social_security").status == "held"
    assert cert.line("social_security").basis["reason"] == "not_entered"
    assert cert.payable.status == "held"


def test_a_manual_line_put_on_hold_is_held_with_its_note() -> None:
    manual = dict(manual_lines_for(SETTINGS, MANUAL[1]))
    manual["delay_penalty"] = ManualLine("delay_penalty", "held", None, "under discussion")
    cert = certify(1, D("0"), manual_lines=manual)
    assert cert.line("delay_penalty").basis == {"note": "under discussion", "reason": "manual_held"}
    assert cert.line("deductions_total").status == "held"


def test_a_work_row_with_a_missing_figure_holds_line_a() -> None:
    lines = unit_price_lines(1)
    lines[4] = replace(lines[4], unit_price=None)
    cert = certify(1, D("0"), lines=lines, taxes=None)
    row = cert.work_lines[4]
    assert row.status == "held" and row.reason == "unit_price" and row.cumulative_amount is None
    work = cert.line("work_done")
    assert work.status == "held"
    assert work.basis["reason"] == "work_line_incomplete"
    assert work.basis["reason.lines"] == "M-26.110"
    assert cert.line("total").basis["held_operands"] == "work_done"


def test_a_held_figure_from_the_calculation_keeps_its_reason() -> None:
    inp = certificate_input(1, D("0"))
    bases = expected_tax_bases(inp)
    taxes = synthetic_taxes(bases["vat_computed"], bases["stamp_duty"])
    taxes = replace(
        taxes,
        income_withheld=figure("income_withheld", None, None, status="held", reason_key="not_chosen", review_status=""),
    )
    cert = compute_certificate(replace(inp, taxes=taxes))
    assert cert.line("income_tax").status == "held"
    assert cert.line("income_tax").basis["reason"] == "not_chosen"
    assert cert.line("vat").status == "value"
    assert cert.payable.status == "held"
    assert [(note.line_key, note.reason_key) for note in cert.notes] == [("income_tax", "not_chosen")]


def test_a_tax_computed_on_another_base_is_held() -> None:
    inp = certificate_input(1, D("0"))
    bases = expected_tax_bases(inp)
    # The stamp duty arrives computed on line E, where the layout expects E - g.
    taxes = synthetic_taxes(bases["vat_computed"], bases["vat_computed"])
    cert = compute_certificate(replace(inp, taxes=taxes))
    stamp = cert.line("stamp_duty")
    assert stamp.status == "held"
    assert stamp.basis["reason"] == "tax_base_mismatch"
    assert Decimal(stamp.basis["reason.base"]) == bases["vat_computed"]
    assert Decimal(stamp.basis["reason.expected"]) == bases["stamp_duty"]
    assert cert.line("income_tax").status == "value"


def test_a_tax_that_does_not_apply_prints_no_amount_and_adds_nothing() -> None:
    inp = certificate_input(1, D("0"))
    bases = expected_tax_bases(inp)
    taxes = synthetic_taxes(bases["vat_computed"], bases["stamp_duty"])
    with_stamp = compute_certificate(replace(inp, taxes=taxes))
    taxes = replace(
        taxes,
        stamp_duty=figure(
            "stamp_duty", None, None, status="not_applicable", reason_key="not_applicable_by_user", review_status=""
        ),
    )
    cert = compute_certificate(replace(inp, taxes=taxes))
    assert cert.line("stamp_duty").status == "not_applicable"
    assert cert.line("stamp_duty").amount is None
    assert cert.payable.status == "value"
    assert cert.payable.amount == with_stamp.payable.amount + with_stamp.line("stamp_duty").amount
    assert not cert.is_draft


def test_a_real_zero_is_a_value_not_a_dash() -> None:
    cert = certify(1, D("0"))
    assert cert.line("social_security").status == "value"
    assert cert.line("social_security").amount == D("0.00")
    assert cert.line("employer_plant_rent").status == "not_applicable"


@pytest.mark.parametrize(
    ("change", "reason"),
    [({"review_status": "unconfirmed"}, "unconfirmed_rate"), ({"overridden": True}, "overridden")],
)
def test_an_unconfirmed_or_overridden_figure_keeps_its_amount_and_makes_a_draft(
    change: dict[str, Any], reason: str
) -> None:
    inp = certificate_input(1, D("0"))
    bases = expected_tax_bases(inp)
    taxes = synthetic_taxes(bases["vat_computed"], bases["stamp_duty"])
    income = replace(taxes.income_withheld, **change)
    cert = compute_certificate(replace(inp, taxes=replace(taxes, income_withheld=income)))
    assert cert.line("income_tax").status == "value"
    assert cert.payable.status == "value"
    assert cert.is_draft
    assert [(note.line_key, note.reason_key) for note in cert.notes] == [("income_tax", reason)]


def test_an_advance_entered_as_an_amount_wins_over_the_contract_percent() -> None:
    manual = manual_lines_for(
        SETTINGS, MANUAL[1] | {"advance_recovery": ManualLine("advance_recovery", "value", D("1234.56"))}
    )
    inp = certificate_input(1, D("0"), manual_lines=manual)
    assert compute_certificate(inp).line("advance_recovery").amount == D("1234.56")
    assert expected_tax_bases(inp)["stamp_duty"] == expected_tax_bases(inp)["vat_computed"] - D("1234.56")


def test_a_currency_without_a_subunit_rounds_to_whole_units() -> None:
    lines = [CertificateWorkLine("X-1", "Kablo", "m", D("10"), D("0"), D("3.333"), D("100.5"), None, None, None, None)]
    cert = compute_certificate(certificate_input(1, D("0"), currency="JPY", lines=lines, taxes=None))
    assert cert.work_lines[0].cumulative_amount == D("335")


def test_an_unknown_flavour_and_a_broken_layout_are_refused() -> None:
    with pytest.raises(ValueError, match="flavour"):
        compute_certificate(certificate_input(1, D("0"), flavour="cost_plus"))
    with pytest.raises(ValueError, match="payable"):
        compute_certificate(certificate_input(1, D("0"), layout=DEFAULT_LAYOUTS["TR"][:-1]))


# ── Taxes computed on different bases ─────────────────────────────────────


def test_the_stamp_duty_comes_from_its_own_run_of_the_shared_calculation() -> None:
    # One run of the shared calculation has one net amount. On the standard
    # form the stamp duty is charged on line E less the advance recovered, so
    # it is a second run, handed over under the key of the line that prints it.
    inp = certificate_input(1, D("0"))
    bases = expected_tax_bases(inp)
    net, stamp_base = bases["vat_computed"], bases["stamp_duty"]
    assert net is not None and stamp_base is not None and stamp_base < net

    def run(amount: Decimal) -> PaymentTaxResult:
        return compute_payment_taxes(
            PaymentTaxInput(
                country_code="TR",
                currency="TRY",
                on=inp.period_end,
                net_amount=amount,
                vat_rate_pct=SYNTHETIC_VAT_PCT,
                vat_withholding=Choice("selected", "SYN-W1"),
                income_withholding=Choice("selected", "SYN-I1"),
                stamp_duty=Choice("selected", "SYN-S1"),
            ),
            SYNTHETIC_ROWS,
        )

    one_run = compute_certificate(replace(inp, taxes=run(net)))
    assert one_run.line("stamp_duty").basis["reason"] == "tax_base_mismatch"

    cert = compute_certificate(replace(inp, taxes=run(net), taxes_by_line={"stamp_duty": run(stamp_base)}))
    assert cert.line("stamp_duty").amount == EXPECTED[1]["b"]
    assert Decimal(cert.line("stamp_duty").basis["base"]) == stamp_base
    assert amounts(cert) == EXPECTED[1]
    # The bases a caller is told to compute on do not move once the taxes are in.
    assert expected_tax_bases(replace(inp, taxes=run(net), taxes_by_line={"stamp_duty": run(net)})) == bases


def test_a_line_with_its_own_run_does_not_need_the_main_one() -> None:
    inp = certificate_input(1, D("0"))
    bases = expected_tax_bases(inp)
    own = synthetic_taxes(bases["vat_computed"], bases["stamp_duty"])
    cert = compute_certificate(replace(inp, taxes=None, taxes_by_line={"stamp_duty": own}))
    assert cert.line("stamp_duty").amount == EXPECTED[1]["b"]
    assert cert.line("vat").basis["reason"] == "module_absent"


def test_no_stamp_duty_or_withholding_row_is_preselected_by_the_standard_layout() -> None:
    # Which row applies depends on who pays (the shipped stamp duty row is for
    # payments by public bodies). Nothing is chosen for the user: the line
    # stays held and visible until a person picks.
    assert resolve_settings("TR", None).tax_choices == {}
    assert resolve_settings("TR", {"hakedis": {"preset": "TR_PRIVATE"}}).tax_choices == {}
    inp = certificate_input(1, D("0"))
    net = expected_tax_bases(inp)["vat_computed"]
    unset = compute_payment_taxes(
        PaymentTaxInput(
            country_code="TR",
            currency="TRY",
            on=inp.period_end,
            net_amount=net,
            vat_rate_pct=SYNTHETIC_VAT_PCT,
            vat_withholding=Choice("unset"),
            income_withholding=Choice("unset"),
            stamp_duty=Choice("unset"),
        ),
        SYNTHETIC_ROWS,
    )
    cert = compute_certificate(replace(inp, taxes=unset))
    for key in ("stamp_duty", "income_tax", "vat_withholding"):
        assert cert.line(key).status == "held", key
        assert cert.line(key).basis["reason"] == "not_chosen", key
    assert cert.payable.status == "held" and cert.is_draft
