# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""FA(3) documents are valid against the official schema and say the right things.

The schema files in ``tests/fixtures/ksef/fa3`` are the Ministry of Finance's,
unedited. They import their base types by ``http://crd.gov.pl/...`` URL; a
resolver maps those URLs to the local copies, so nothing here reaches the
network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

etree = pytest.importorskip("lxml.etree")

from app.modules.einvoice_ksef import fa3, ksef_number, split_payment  # noqa: E402
from app.modules.einvoice_ksef.facts import FA2, FA3  # noqa: E402

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ksef" / "fa3"
_BASE_URL = "http://crd.gov.pl/xml/schematy/dziedzinowe/mf/2022/01/05/eD/DefinicjeTypy/"


class _LocalSchemas(etree.Resolver):
    def resolve(self, system_url, public_id, context):
        if system_url and system_url.startswith(_BASE_URL):
            return self.resolve_filename(str(_FIXTURES / "bazowe" / system_url[len(_BASE_URL) :]), context)
        return None


@pytest.fixture(scope="module")
def schema():
    parser = etree.XMLParser(no_network=True)
    parser.resolvers.add(_LocalSchemas())
    doc = etree.parse(str(_FIXTURES / "schemat_FA(3)_v1-0E.xsd"), parser)
    return etree.XMLSchema(doc)


def _assert_valid(schema, text: str) -> etree._Element:
    root = etree.fromstring(text.encode("utf-8"))
    if not schema.validate(root):
        errors = "\n".join(f"{e.line}: {e.message}" for e in schema.error_log)
        raise AssertionError(f"FA(3) document is not valid:\n{errors}\n\n{text}")
    return root


def _find(root, path: str) -> list:
    return root.findall(path, {"f": fa3.NS})


def _text(root, path: str) -> str:
    found = _find(root, path)
    return found[0].text if found else ""


SELLER = fa3.Party(
    name="Firma Budowlana Demo Sp. z o.o.",
    nip="5265877635",
    address_line1="ul. Marszalkowska 10",
    address_line2="00-001 Warszawa",
)
BUYER = fa3.Party(name="Inwestor Demo S.A.", nip="7010001454", address_line1="ul. Prosta 1, 00-850 Warszawa")
GENERATED = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)


def _line(desc: str, qty: str, price: str, code: str = "23", **kw) -> fa3.Line:
    q, p = Decimal(qty), Decimal(price)
    return fa3.Line(
        description=desc,
        quantity=q,
        unit=kw.pop("unit", "m2"),
        unit_net_price=p,
        net_amount=(q * p).quantize(Decimal("0.01")),
        vat_code=code,
        **kw,
    )


def _input(**kw) -> fa3.Fa3Input:
    base = {
        "seller": SELLER,
        "buyer": BUYER,
        "number": "FV/2026/10/001",
        "issue_date": "2026-10-19",
        "currency": "PLN",
        "lines": (_line("Tynkowanie scian", "120", "45.50"),),
        "generated_at": GENERATED,
    }
    base.update(kw)
    return fa3.Fa3Input(**base)


class TestSchemaIdentity:
    def test_fa3_is_current_and_fa2_ended_the_day_before(self):
        assert FA3.namespace == "http://crd.gov.pl/wzor/2025/06/25/13775/"
        assert (FA3.system_code, FA3.schema_version, FA3.variant) == ("FA (3)", "1-0E", "3")
        assert FA3.valid_from == "2026-02-01" and not FA3.valid_to
        assert FA2.valid_to == "2026-01-31"
        from datetime import date

        assert FA3.in_force_on(date(2026, 2, 1)) and not FA3.in_force_on(date(2026, 1, 31))
        assert FA2.in_force_on(date(2026, 1, 31)) and not FA2.in_force_on(date(2026, 2, 1))

    def test_the_fixture_is_the_schema_the_registry_names(self):
        text = (_FIXTURES / "schemat_FA(3)_v1-0E.xsd").read_text(encoding="utf-8")
        assert f'targetNamespace="{FA3.namespace}"' in text
        assert 'fixed="FA (3)"' in text and 'fixed="1-0E"' in text


class TestBasicInvoice:
    def test_a_basic_invoice_validates_and_carries_the_header(self, schema):
        root = _assert_valid(schema, fa3.build_xml(_input()))
        kod = _find(root, "f:Naglowek/f:KodFormularza")[0]
        assert kod.text == "FA" and kod.get("kodSystemowy") == "FA (3)" and kod.get("wersjaSchemy") == "1-0E"
        assert _text(root, "f:Naglowek/f:WariantFormularza") == "3"
        assert _text(root, "f:Fa/f:RodzajFaktury") == "VAT"
        # 120 x 45.50 = 5460.00 net, 23% = 1255.80
        assert _text(root, "f:Fa/f:P_13_1") == "5460.00"
        assert _text(root, "f:Fa/f:P_14_1") == "1255.80"
        assert _text(root, "f:Fa/f:P_15") == "6715.80"
        assert _text(root, "f:Fa/f:Adnotacje/f:P_18A") == "2"
        assert _text(root, "f:Podmiot2/f:JST") == "2" and _text(root, "f:Podmiot2/f:GV") == "2"

    def test_mixed_rates_land_in_their_own_fields_and_add_up(self, schema):
        lines = (
            _line("Roboty budowlane", "10", "1000.00", "23"),
            _line("Budownictwo mieszkaniowe", "5", "800.00", "8"),
            _line("Szkolenie BHP", "1", "500.00", "zw", unit="usl"),
        )
        root = _assert_valid(schema, fa3.build_xml(_input(lines=lines, exemption_basis="art. 43 ust. 1 pkt 29")))
        assert _text(root, "f:Fa/f:P_13_1") == "10000.00" and _text(root, "f:Fa/f:P_14_1") == "2300.00"
        assert _text(root, "f:Fa/f:P_13_2") == "4000.00" and _text(root, "f:Fa/f:P_14_2") == "320.00"
        assert _text(root, "f:Fa/f:P_13_7") == "500.00"
        assert _text(root, "f:Fa/f:P_15") == "17120.00"
        assert _text(root, "f:Fa/f:Adnotacje/f:Zwolnienie/f:P_19") == "1"
        assert len(_find(root, "f:Fa/f:FaWiersz")) == 3

    def test_an_exempt_line_without_its_legal_basis_is_refused(self):
        with pytest.raises(fa3.Fa3BuildError, match="P_19A"):
            fa3.build_xml(_input(lines=(_line("Szkolenie", "1", "100", "zw"),)))

    def test_a_foreign_currency_invoice_states_the_vat_in_pln(self, schema):
        root = _assert_valid(
            schema,
            fa3.build_xml(
                _input(currency="EUR", exchange_rate=Decimal("4.2512"), lines=(_line("Works", "1", "1000"),))
            ),
        )
        assert _text(root, "f:Fa/f:P_14_1") == "230.00"
        assert _text(root, "f:Fa/f:P_14_1W") == "977.78"

    def test_a_foreign_currency_invoice_without_a_rate_is_refused(self):
        with pytest.raises(fa3.Fa3BuildError, match="exchange rate"):
            fa3.build_xml(_input(currency="EUR"))

    def test_reverse_charge_and_contract_and_payment_blocks_validate(self, schema):
        text = fa3.build_xml(
            _input(
                lines=(_line("Podwykonawstwo", "1", "50000", "oo"),),
                reverse_charge=True,
                contracts=(fa3.Contract(number="UM/12/2026", date="2026-03-01"),),
                due_date="2026-11-18",
                bank_account="PL61109010140000071219812874",
            )
        )
        root = _assert_valid(schema, text)
        assert _text(root, "f:Fa/f:P_13_10") == "50000.00"
        assert _text(root, "f:Fa/f:Adnotacje/f:P_18") == "1"
        assert _text(root, "f:Fa/f:WarunkiTransakcji/f:Umowy/f:NrUmowy") == "UM/12/2026"
        assert _text(root, "f:Fa/f:Platnosc/f:FormaPlatnosci") == "6"


class TestSplitPayment:
    def test_annex_15_above_the_threshold_sets_p18a(self, schema):
        line = _line("Roboty instalacyjne", "1", "12195.13", annex_15=True, pkwiu="43.21.10.0")
        decision = split_payment.decide(gross=Decimal("15000.01"), currency="PLN", annex_15_lines=1)
        assert decision.required
        root = _assert_valid(schema, fa3.build_xml(_input(lines=(line,), split_payment=decision.required)))
        assert _text(root, "f:Fa/f:Adnotacje/f:P_18A") == "1"
        assert _text(root, "f:Fa/f:FaWiersz/f:P_12_Zal_15") == "1"

    def test_exactly_the_threshold_is_not_above_it(self):
        assert not split_payment.decide(gross=Decimal("15000.00"), currency="PLN", annex_15_lines=1).required

    def test_above_the_threshold_without_annex_15_is_not_split_payment(self):
        decision = split_payment.decide(gross=Decimal("90000"), currency="PLN", annex_15_lines=0)
        assert decision.verdict == split_payment.DECIDED_NO

    def test_a_foreign_currency_invoice_without_a_rate_cannot_be_decided(self):
        decision = split_payment.decide(gross=Decimal("5000"), currency="EUR", annex_15_lines=1)
        assert decision.verdict == split_payment.UNDECIDABLE

    def test_a_foreign_currency_invoice_is_decided_on_its_pln_equivalent(self):
        assert split_payment.decide(
            gross=Decimal("5000"), currency="EUR", annex_15_lines=1, exchange_rate=Decimal("4.25")
        ).required
        assert not split_payment.decide(
            gross=Decimal("3000"), currency="EUR", annex_15_lines=1, exchange_rate=Decimal("4.25")
        ).required


class TestCorrections:
    def test_a_correction_of_a_ksef_invoice_names_its_ksef_number(self, schema):
        correction = fa3.Correction(
            reason="Blad w ilosci",
            type=2,
            corrected=(fa3.CorrectedInvoice("FV/2026/09/014", "2026-09-30", "5265877635-20250826-0100001AF629-AF"),),
        )
        lines = (
            _line("Tynkowanie scian", "120", "45.50", state_before=True),
            _line("Tynkowanie scian", "100", "45.50"),
        )
        root = _assert_valid(schema, fa3.build_xml(_input(kind=fa3.KIND_KOR, correction=correction, lines=lines)))
        assert _text(root, "f:Fa/f:DaneFaKorygowanej/f:NrKSeF") == "1"
        assert _text(root, "f:Fa/f:DaneFaKorygowanej/f:NrKSeFFaKorygowanej") == "5265877635-20250826-0100001AF629-AF"
        assert not _find(root, "f:Fa/f:DaneFaKorygowanej/f:NrKSeFN")
        # The difference: 20 m2 fewer, 910.00 net and 209.30 VAT less.
        assert _text(root, "f:Fa/f:P_13_1") == "-910.00"
        assert _text(root, "f:Fa/f:P_14_1") == "-209.30"
        assert _text(root, "f:Fa/f:P_15") == "-1119.30"
        assert _text(root, "f:Fa/f:FaWiersz/f:StanPrzed") == "1"

    def test_a_correction_of_an_invoice_outside_ksef_says_so_instead(self, schema):
        correction = fa3.Correction(
            reason="Rabat", type=1, corrected=(fa3.CorrectedInvoice("FV/2025/12/090", "2025-12-15"),)
        )
        root = _assert_valid(
            schema,
            fa3.build_xml(_input(kind=fa3.KIND_KOR, correction=correction, lines=(_line("Rabat", "1", "-100"),))),
        )
        assert _text(root, "f:Fa/f:DaneFaKorygowanej/f:NrKSeFN") == "1"
        assert not _find(root, "f:Fa/f:DaneFaKorygowanej/f:NrKSeFFaKorygowanej")

    def test_a_correction_without_the_corrected_invoice_is_refused(self):
        with pytest.raises(fa3.Fa3BuildError, match="corrects"):
            fa3.build_xml(_input(kind=fa3.KIND_KOR))


class TestAdvances:
    def test_an_advance_invoice_carries_the_order_and_no_lines(self, schema):
        advance = _line("Zaliczka 30% na umowe UM/12/2026", "1", "30000")
        order = (
            fa3.OrderLine(
                description="Stan surowy budynku",
                quantity=Decimal("1"),
                unit="kpl",
                unit_net_price=Decimal("100000"),
                net_amount=Decimal("100000"),
                vat_amount=Decimal("23000"),
                vat_code="23",
                annex_15=True,
            ),
        )
        root = _assert_valid(
            schema,
            fa3.build_xml(
                _input(
                    kind=fa3.KIND_ZAL,
                    lines=(advance,),
                    order_value_gross=Decimal("123000"),
                    order_lines=order,
                    delivery_date="2026-10-15",
                    split_payment=True,
                    contracts=(fa3.Contract("UM/12/2026", "2026-03-01"),),
                )
            ),
        )
        assert _text(root, "f:Fa/f:RodzajFaktury") == "ZAL"
        assert _text(root, "f:Fa/f:P_13_1") == "30000.00" and _text(root, "f:Fa/f:P_15") == "36900.00"
        assert _text(root, "f:Fa/f:Zamowienie/f:WartoscZamowienia") == "123000.00"
        assert _text(root, "f:Fa/f:Zamowienie/f:ZamowienieWiersz/f:P_12Z_Zal_15") == "1"
        assert not _find(root, "f:Fa/f:FaWiersz")
        assert (
            fa3.read_summary(
                fa3.build_xml(
                    _input(kind=fa3.KIND_ZAL, lines=(advance,), order_value_gross=Decimal("123000"), order_lines=order)
                )
            ).annex_15_lines
            == 1
        )

    def test_an_advance_invoice_without_the_order_value_is_refused(self):
        with pytest.raises(fa3.Fa3BuildError, match="order"):
            fa3.build_xml(_input(kind=fa3.KIND_ZAL))

    def test_a_settlement_invoice_lists_the_advances_by_ksef_number_or_own_number(self, schema):
        root = _assert_valid(
            schema,
            fa3.build_xml(
                _input(
                    kind=fa3.KIND_ROZ,
                    lines=(_line("Stan surowy budynku - rozliczenie", "1", "70000"),),
                    advance_invoices=(
                        fa3.AdvanceInvoiceRef("FZ/2026/10/001", "5265877635-20250916-0200A0D6723E-C2"),
                        fa3.AdvanceInvoiceRef("FZ/2025/12/007"),
                    ),
                )
            ),
        )
        refs = _find(root, "f:Fa/f:FakturaZaliczkowa")
        assert len(refs) == 2
        assert refs[0].find("f:NrKSeFFaZaliczkowej", {"f": fa3.NS}).text == "5265877635-20250916-0200A0D6723E-C2"
        assert refs[1].find("f:NrKSeFZN", {"f": fa3.NS}).text == "1"
        assert refs[1].find("f:NrFaZaliczkowej", {"f": fa3.NS}).text == "FZ/2025/12/007"


class TestReader:
    def test_the_reader_reads_back_what_the_writer_wrote(self):
        line = _line("Instalacje", "1", "20000", annex_15=True)
        summary = fa3.read_summary(fa3.build_xml(_input(lines=(line,), split_payment=True)))
        assert summary.namespace == FA3.namespace and summary.system_code == "FA (3)"
        assert summary.issue_date == "2026-10-19" and summary.seller_nip == "5265877635"
        assert summary.gross == Decimal("24600.00") and summary.split_payment and summary.annex_15_lines == 1

    def test_unreadable_xml_is_a_build_error(self):
        with pytest.raises(fa3.Fa3BuildError):
            fa3.read_summary("<Faktura")


class TestKsefNumber:
    def test_the_ministry_examples_pass(self):
        assert ksef_number.is_valid("5265877635-20250826-0100001AF629-AF")
        assert ksef_number.is_valid("5265877635-20250916-0200A0D6723E-C2")

    def test_a_wrong_checksum_fails(self):
        # The brochure's illustrative number is shaped right and checksummed wrong.
        assert ksef_number.problems("9999999999-20260714-D5FB0C9ED490-9A")
        assert not ksef_number.is_valid("5265877635-20250826-0100001AF629-AE")

    def test_a_processing_handle_is_never_a_number(self):
        handle = ksef_number.pending_handle("20261019-SO-1", "20261019-EE-2")
        assert not ksef_number.is_valid(handle)
        assert ksef_number.parse_pending_handle(handle) == ("20261019-SO-1", "20261019-EE-2")
        assert ksef_number.parse_pending_handle("5265877635-20250826-0100001AF629-AF") is None

    def test_an_impossible_date_fails(self):
        data = "5265877635-20250231-0100001AF629"
        assert ksef_number.problems(f"{data}-{ksef_number.checksum(data)}")


class TestTheOracleBites:
    def test_the_schema_rejects_a_document_without_the_split_payment_annotation(self, schema):
        # Proves the validation above can fail: P_18A is mandatory in FA(3).
        text = fa3.build_xml(_input()).replace("<P_18A>2</P_18A>", "")
        assert not schema.validate(etree.fromstring(text.encode("utf-8")))

    def test_the_schema_rejects_an_fa2_form_code(self, schema):
        text = fa3.build_xml(_input()).replace('kodSystemowy="FA (3)"', 'kodSystemowy="FA (2)"')
        assert not schema.validate(etree.fromstring(text.encode("utf-8")))
