"""Peru pack: data rows, rule set, UBL export and the two demo templates."""

from __future__ import annotations

import asyncio
import importlib.util
from decimal import Decimal
from pathlib import Path

from app.core.payment_taxes import data_pe
from app.core.validation import rules as rules_pkg
from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.contracts.country_defaults import COUNTRY_CONTRACT_DEFAULTS
from app.modules.contracts.price_adjustment import PRICE_ADJUSTMENT_REGIMES
from app.modules.contracts.public_procurement import PUBLIC_WORKS_PRICE_ADJUSTMENT
from app.modules.einvoice.cii import EInvoice, EInvoiceLine, Party, TaxSubtotal
from app.modules.einvoice.ubl_pe import (
    PeDetraction,
    build_ubl_pe_xml,
    check_pe,
    detraction_amount,
    ruc_is_valid,
)
from app.modules.payment_clock.data import PAYMENT_REGIMES

_ROOT = Path(__file__).resolve().parents[3]


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(f"_pe_{path.stem}".replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _invoice() -> EInvoice:
    seller = Party("Constructora Sol SAC", "PE", "20100070970", line1="Av. Lima 1", city="Lima")
    buyer = Party("Clinica Norte SAC", "PE", "20131312955", city="Lima")
    line = EInvoiceLine("1", "Concrete", Decimal(2), "m3", Decimal(100), Decimal(200), Decimal(18))
    return EInvoice(
        "ubl",
        "F001-00000123",
        "2026-10-22",
        "PEN",
        seller,
        buyer,
        [line],
        [TaxSubtotal("S", Decimal(18), Decimal(200), Decimal(36))],
        Decimal(200),
        Decimal(200),
        Decimal(36),
        Decimal(236),
        Decimal(236),
    )


def test_pe_rows_are_unconfirmed_and_cited() -> None:
    assert data_pe.ROWS
    for row in data_pe.ROWS:
        assert row.review_status == "unconfirmed"
        assert row.legal_reference


def test_contract_defaults_row_pe_holds_ten_percent() -> None:
    row = COUNTRY_CONTRACT_DEFAULTS["PE"]
    assert row["retention_percent"]["value"] == "10"
    assert row["payment_period_days"]["value"] is None


def test_payment_clock_and_price_adjustment_regimes_registered() -> None:
    assert any(r["code"] == "pe_lgcp_art210" for r in PAYMENT_REGIMES)
    assert PUBLIC_WORKS_PRICE_ADJUSTMENT["PE"] in PRICE_ADJUSTMENT_REGIMES


def test_ruc_checksum() -> None:
    assert ruc_is_valid("20100070970")
    assert ruc_is_valid("20604812373")
    assert not ruc_is_valid("20100070971")
    assert not ruc_is_valid("123")
    assert not ruc_is_valid(None)


def test_detraction_is_four_percent_whole_soles() -> None:
    assert detraction_amount(Decimal("236.00"), Decimal("4")) == Decimal("9")


def test_ubl_pe_is_unsigned_and_carries_detraction() -> None:
    inv = _invoice()
    det = PeDetraction(account="00-123")
    assert check_pe(inv, det) == []
    xml = build_ubl_pe_xml(inv, det).decode()
    assert "F001-00000123" in xml
    assert "Unsigned" in xml
    assert "030" in xml


def test_peru_rule_set() -> None:
    rules_pkg.register_builtin_rules()
    found = rule_registry.get_rules_for_sets(["peru"])
    assert {r.rule_id for r in found} == {
        "peru.igv_line_present",
        "peru.igv_rate_18",
        "peru.gastos_generales_utilidad_stated",
        "peru.partida_numbering",
    }
    good = [
        {"name": "Gastos generales", "percentage": "9"},
        {"name": "Utilidad", "percentage": "8"},
        {"name": "IGV (18 %)", "percentage": "18"},
    ]
    bad = [{"name": "IGV", "percentage": "17"}]

    def run(markups: list[dict]) -> list[bool]:
        ctx = ValidationContext(data={"positions": [], "markups": markups}, metadata={"locale": "es"})
        return [x.passed for r in found for x in asyncio.run(r.validate(ctx))]

    assert all(run(good))
    assert not all(run(bad))
    assert run([]) == []


def test_demo_templates_follow_the_peru_stack() -> None:
    for name in ("hospital-lima", "school-arequipa"):
        tpl = _load(_ROOT / "backend/app/core/demo_packs" / f"{name}.py").TEMPLATE
        assert tpl.currency == "PEN"
        assert tpl.region == "PE"
        assert "peru" in tpl.validation_rule_sets
        igv = [m for m in tpl.markups if m[2] == "tax"]
        assert len(igv) == 1 and igv[0][1] == 18.0
        assert tpl.claim_retention == 0.10
        assert tpl.progress_claims
