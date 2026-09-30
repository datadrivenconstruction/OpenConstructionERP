"""Build the ``PartnerPackManifest`` instance for the indonesia-id pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="indonesia-id",
    partner_name="Indonesia Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for the Indonesian construction market: AHSP "
        "unit rate analysis and SNI standards, IDR currency with 11% "
        "PPN, RAB (Rencana Anggaran Biaya) estimating practice."
    ),
    default_locale="id",
    additional_locales={},
    cwicr_regions=["cwicr-id-jakarta", "cwicr-id-national"],
    default_currency="IDR",
    default_tax_template="id_ppn_11",
    default_methodology="indonesia",
    validation_rule_packs=[],
    validation_rule_sets=[
        "masterformat",
    ],
    default_modules=[],
    hidden_modules=[],
    demo_template_ids=["commercial-jakarta", "residential-surabaya"],
    branding=PartnerBranding(
        primary_color="#FF0000",  # red of the Indonesian flag
        accent_color="#FFFFFF",  # white of the Indonesian flag
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path=None,
    metadata={
        "country": "ID",
        "country_name_en": "Indonesia",
        "country_name_id": "Indonesia",
        "classification_standard": "masterformat",
        "measurement_system": "metric",
        "regulator_refs": [
            "AHSP (Analisa Harga Satuan Pekerjaan, unit rate analysis)",
            "SNI (Standar Nasional Indonesia, national standards for construction)",
            "Peraturan Menteri PUPR (Minister of Public Works regulations)",
            "RAB (Rencana Anggaran Biaya, project cost plan)",
            "UU No. 2/2017 tentang Jasa Konstruksi (Construction Services Act)",
            "Perpres 16/2018 tentang Pengadaan Barang/Jasa Pemerintah (Public Procurement)",
        ],
        "vat_standard_rate": 11,
        "support_email": "info@datadrivenconstruction.io",
    },
)
