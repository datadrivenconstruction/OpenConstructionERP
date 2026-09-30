"""Build the ``PartnerPackManifest`` instance for the austria-at pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="austria-at",
    partner_name="Austria Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for Austrian developers, contractors and "
        "public clients: OENORM B 2061 tendering, "
        "OENORM B 1801 cost planning, OENORM A 2063 data exchange, "
        "OENORM classification, EUR with 20 percent USt."
    ),
    default_locale="de",
    additional_locales={},
    cwicr_regions=[],
    default_currency="EUR",
    default_tax_template="at_ust_20",
    default_methodology="austria",
    validation_rule_packs=[
        "oenorm_b2061",
        "oenorm_b1801",
        "oenorm_a2063",
    ],
    validation_rule_sets=[],
    default_modules=[],
    hidden_modules=[],
    demo_template_ids=[
        "office-vienna",
        "residential-salzburg",
    ],
    branding=PartnerBranding(
        primary_color="#ED2939",  # Austrian red (flag)
        accent_color="#FFFFFF",  # Austrian white (flag)
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "AT",
        "country_name_en": "Austria",
        "country_name_de": "Oesterreich",
        "classification_standard": "onorm",
        "measurement_system": "metric",
        "regulator_refs": [
            "OENORM B 2061 (Preisermittlung fuer Bauleistungen / tendering and pricing)",
            "OENORM B 1801-1 (Kosten im Hoch- und Tiefbau / cost planning)",
            "OENORM A 2063 (Datenaustausch / electronic data exchange for tendering)",
            "OENORM B 2110 (Allgemeine Vertragsbestimmungen fuer Bauleistungen / general contract conditions)",
            "OENORM B 2118 (Allgemeine Vertragsbestimmungen fuer Bauleistungen unter Anwendung des BVergG)",
            "Bundesvergabegesetz BVergG 2018 (Federal Procurement Act)",
            "Austrian Standards International (ASI)",
        ],
        "vat_standard_rate": 20,
        "vat_reduced_rate": 10,
        "currency_decimals": 2,
        "review_status": (
            "Regulatory references are drawn from public sources and are "
            "pending review by an Austrian Baukalkulator or Ziviltechniker "
            "before they are relied on for a public submission."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
