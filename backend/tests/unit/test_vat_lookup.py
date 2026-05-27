# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for app.core.tax — unified VAT/GST rate lookup (Wave 25 / task #168)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.tax import VATNotApplicable, get_vat_rate, list_covered_countries


class TestGetVatRateDACH:
    """DACH rates — primary audit target (previously assumed 19 % DE, no explicit data)."""

    def test_de_standard(self) -> None:
        assert get_vat_rate("DE", "standard") == Decimal("0.19")

    def test_de_reduced(self) -> None:
        assert get_vat_rate("DE", "reduced") == Decimal("0.07")

    def test_de_zero(self) -> None:
        assert get_vat_rate("DE", "zero") == Decimal("0.00")

    def test_de_default_kind_is_standard(self) -> None:
        # get_vat_rate with no kind argument must default to 'standard'
        assert get_vat_rate("DE") == Decimal("0.19")

    def test_at_standard(self) -> None:
        assert get_vat_rate("AT", "standard") == Decimal("0.20")

    def test_at_reduced(self) -> None:
        assert get_vat_rate("AT", "reduced") == Decimal("0.10")

    def test_ch_standard(self) -> None:
        # Swiss rate effective 2024-01-01 (ESTV / MWSTG Art. 25)
        assert get_vat_rate("CH", "standard") == Decimal("0.081")

    def test_ch_reduced(self) -> None:
        assert get_vat_rate("CH", "reduced") == Decimal("0.026")

    def test_lowercase_country_code(self) -> None:
        # Country codes must be case-insensitive
        assert get_vat_rate("de", "standard") == Decimal("0.19")
        assert get_vat_rate("De", "reduced") == Decimal("0.07")


class TestGetVatRateUK:
    """UK rates — HMRC VAT Notice 700."""

    def test_gb_standard(self) -> None:
        assert get_vat_rate("GB", "standard") == Decimal("0.20")

    def test_gb_reduced(self) -> None:
        assert get_vat_rate("GB", "reduced") == Decimal("0.05")

    def test_gb_zero(self) -> None:
        assert get_vat_rate("GB", "zero") == Decimal("0.00")


class TestGetVatRateAPAC:
    """Asia-Pacific rates."""

    def test_au_standard(self) -> None:
        assert get_vat_rate("AU", "standard") == Decimal("0.10")

    def test_nz_standard(self) -> None:
        assert get_vat_rate("NZ", "standard") == Decimal("0.15")

    def test_jp_standard(self) -> None:
        assert get_vat_rate("JP", "standard") == Decimal("0.10")

    def test_jp_reduced(self) -> None:
        assert get_vat_rate("JP", "reduced") == Decimal("0.08")

    def test_sg_standard(self) -> None:
        # Singapore raised to 9 % effective 2024-01-01
        assert get_vat_rate("SG", "standard") == Decimal("0.09")


class TestGetVatRateMiddleEast:
    """Middle East / GCC rates."""

    def test_ae_standard(self) -> None:
        assert get_vat_rate("AE", "standard") == Decimal("0.05")

    def test_sa_standard(self) -> None:
        # KSA raised to 15 % effective 2020-07-01
        assert get_vat_rate("SA", "standard") == Decimal("0.15")

    def test_bh_standard(self) -> None:
        assert get_vat_rate("BH", "standard") == Decimal("0.10")

    def test_om_standard(self) -> None:
        assert get_vat_rate("OM", "standard") == Decimal("0.05")


class TestGetVatRateLatAm:
    """Latin America rates."""

    def test_mx_standard(self) -> None:
        assert get_vat_rate("MX", "standard") == Decimal("0.16")

    def test_mx_reduced_border(self) -> None:
        assert get_vat_rate("MX", "reduced") == Decimal("0.08")

    def test_ar_standard(self) -> None:
        assert get_vat_rate("AR", "standard") == Decimal("0.21")

    def test_ar_reduced(self) -> None:
        assert get_vat_rate("AR", "reduced") == Decimal("0.105")

    def test_cl_standard(self) -> None:
        assert get_vat_rate("CL", "standard") == Decimal("0.19")

    def test_co_standard(self) -> None:
        assert get_vat_rate("CO", "standard") == Decimal("0.19")

    def test_pe_standard(self) -> None:
        assert get_vat_rate("PE", "standard") == Decimal("0.18")


class TestGetVatRateRussia:
    """Russia NDS rates."""

    def test_ru_standard(self) -> None:
        assert get_vat_rate("RU", "standard") == Decimal("0.20")

    def test_ru_reduced(self) -> None:
        assert get_vat_rate("RU", "reduced") == Decimal("0.10")

    def test_ru_zero(self) -> None:
        assert get_vat_rate("RU", "zero") == Decimal("0.00")


class TestGetVatRateNotApplicable:
    """Countries with no federal VAT or not covered."""

    def test_us_standard_raises(self) -> None:
        """US has no federal VAT — must raise VATNotApplicable."""
        with pytest.raises(VATNotApplicable) as exc_info:
            get_vat_rate("US", "standard")
        assert exc_info.value.country_code == "US"
        assert exc_info.value.kind == "standard"

    def test_us_reduced_raises(self) -> None:
        with pytest.raises(VATNotApplicable):
            get_vat_rate("US", "reduced")

    def test_unknown_country_raises(self) -> None:
        with pytest.raises(VATNotApplicable):
            get_vat_rate("XX", "standard")

    def test_unknown_kind_raises(self) -> None:
        """Requesting a kind that doesn't exist for a known country."""
        # AU has no 'reduced' kind
        with pytest.raises(VATNotApplicable):
            get_vat_rate("AU", "reduced")

    def test_vat_not_applicable_message(self) -> None:
        exc = VATNotApplicable("US", "standard")
        assert "US" in str(exc)
        assert "standard" in str(exc)


class TestReturnTypes:
    """get_vat_rate must always return Decimal, never float."""

    def test_de_return_type_is_decimal(self) -> None:
        result = get_vat_rate("DE")
        assert isinstance(result, Decimal)

    def test_gb_return_type_is_decimal(self) -> None:
        result = get_vat_rate("GB", "reduced")
        assert isinstance(result, Decimal)

    def test_ru_return_type_is_decimal(self) -> None:
        result = get_vat_rate("RU", "zero")
        assert isinstance(result, Decimal)


class TestListCoveredCountries:
    """list_covered_countries should include all pack countries with rates."""

    def test_includes_dach(self) -> None:
        covered = list_covered_countries()
        assert "DE" in covered
        assert "AT" in covered
        assert "CH" in covered

    def test_includes_gb(self) -> None:
        assert "GB" in list_covered_countries()

    def test_excludes_us(self) -> None:
        # US is intentionally absent — no federal VAT
        assert "US" not in list_covered_countries()

    def test_is_sorted(self) -> None:
        covered = list_covered_countries()
        assert covered == sorted(covered)
