"""Build the ``PartnerPackManifest`` instance for the peru-pe pack."""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="peru-pe",
    partner_name="Peru Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for contractors working in Peru, private and public: the presupuesto de obra "
        "with gastos generales, utilidad and IGV at 18 percent, the detraccion on construction invoices, "
        "monthly valorizaciones with the 10 percent retention, the public works payment clock and "
        "formula polinomica price adjustment, the SUNAT UBL 2.1 invoice for an OSE or PSE, Peruvian sol."
    ),
    default_locale="es",
    additional_locales={},
    # No Peruvian cost base is shipped: rates come from the tenant's own library.
    cwicr_regions=[],
    default_currency="PEN",
    default_tax_template=None,
    default_methodology="peru",
    validation_rule_packs=[
        "peru_tributario",
        "ley_contrataciones",
    ],
    validation_rule_sets=["peru", "masterformat"],
    default_modules=[],
    hidden_modules=[],
    demo_template_ids=["hospital-lima", "school-arequipa"],
    branding=PartnerBranding(
        primary_color="#D91023",  # Peruvian red (flag)
        accent_color="#FFFFFF",
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "PE",
        "country_name_en": "Peru",
        "country_name_es": "Peru",
        "classification_standard": "masterformat",
        "regulator_refs": [
            "Decreto Legislativo 940 and Resolucion de Superintendencia 183-2004/SUNAT (detracciones)",
            "Resolucion de Superintendencia 037-2002/SUNAT (retencion del IGV)",
            "Ley 32069, Ley General de Contrataciones Publicas, and its Reglamento (D.S. 009-2025-EF)",
            "Resolucion de Superintendencia 097-2012/SUNAT (electronic invoice, UBL 2.1)",
        ],
        "vat_standard_rate": 18,
        "currency_decimals": 2,
        "detraction_construction_percent": 4,
        "retention_percent": 10,
        "review_status": (
            "Drawn from the published legislation and an OECE opinion. Every figure is flagged "
            "unconfirmed in the data tables. Pending review by a Peruvian quantity surveyor and "
            "a Peruvian accountant: do not rely on it for a tender or a tax filing before that review."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
