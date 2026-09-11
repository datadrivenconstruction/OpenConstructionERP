"""Build the ``PartnerPackManifest`` instance for the netherlands-nl pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="netherlands-nl",
    partner_name="Netherlands Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for Dutch contractors, architects and public "
        "clients: NL/SfB classification, EUR currency with 21% BTW, "
        "RAW systematiek for civil engineering, STABU besteksystematiek "
        "for building specifications, Bouwbesluit 2012, Aanbestedingswet "
        "2012 public procurement references, NEN standards and BENG "
        "energy performance requirements. Dutch and English interface."
    ),
    default_locale="nl",
    additional_locales={},
    cwicr_regions=[
        "cwicr-nl-amsterdam",  # resolves to NL_AMSTERDAM
    ],
    default_currency="EUR",
    default_tax_template="nl_btw_21",
    default_methodology="netherlands",
    validation_rule_packs=[],
    # No Dutch-specific engine rule set implemented yet.
    validation_rule_sets=[],
    default_modules=[],  # empty = show all
    hidden_modules=[],
    demo_template_ids=["office-amsterdam"],
    branding=PartnerBranding(
        primary_color="#21468B",  # Dutch blue (flag)
        accent_color="#AE1C28",  # Dutch red (flag)
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,  # use default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "NL",
        "country_name_en": "Netherlands",
        "country_name_nl": "Nederland",
        "classification_standard": "nlsfb",
        "regulator_refs": [
            "Aanbestedingswet 2012 (Public Procurement Act)",
            "Bouwbesluit 2012 (Building Decree)",
            "RAW systematiek (civil engineering specifications)",
            "STABU besteksystematiek (building specifications)",
            "NEN standards (Dutch normalisation institute)",
            "BENG (Bijna Energieneutrale Gebouwen, nearly zero-energy buildings)",
        ],
        "vat_standard_rate": 21,
        "vat_reduced_rate": 9,
        "review_status": (
            "Classification, currency and tax references are drawn from "
            "public sources. Regulatory references are pending review by "
            "a Dutch quantity surveyor before they are relied on for a "
            "tender submission."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
