"""Build the ``PartnerPackManifest`` instance for the greece-gr pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="greece-gr",
    partner_name="Greece Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for Greek contractors, engineers and contracting "
        "authorities: every line priced by the article of the national "
        "unified price lists (ΝΕΤ) and classified against DIN 276, EUR "
        "currency with 24% ΦΠΑ, the public works cascade of Ν. 4412/2016 "
        "(ΓΕ&ΟΕ 18%, απρόβλεπτα), and the building code and permit "
        "references. Greek and English interface."
    ),
    default_locale="el",
    additional_locales={},
    # No region token on purpose. The Greek cost base is registered as
    # GR_NATIONAL, and ``resolve_cwicr_db_id`` matches only the last token of a
    # slug, which ``national`` shares with several other countries' bases.
    cwicr_regions=[],
    default_currency="EUR",
    # Documentation only, as on every pack: the rate a bill is charged comes
    # from the dated tax seed for the project's country, and the methodology
    # template carries the same 24 for the cascade.
    default_tax_template="gr_fpa_24",
    default_methodology="greece",
    validation_rule_packs=[
        "gr_net_timologia",
        "gr_dimosia_erga_4412",
        "gr_adeies_nok",
        "gr_fpa_kataskeves",
    ],
    # The engine identifier. Two rules run under it: every priced line carries
    # its ΝΕΤ article, and the article has the price list's shape and opens a
    # real ΟΙΚ chapter.
    validation_rule_sets=[
        "greece",
        "din276",
    ],
    default_modules=[],  # empty = show all
    hidden_modules=[],
    demo_template_ids=["residential-athens", "school-thessaloniki"],
    branding=PartnerBranding(
        primary_color="#0D5EAF",  # blue of the national flag
        accent_color="#FFFFFF",  # white of the national flag
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "GR",
        "country_name_en": "Greece",
        "country_name_el": "Ελλάδα",
        "classification_standard": "din276",
        "national_classification_key": "net",
        "measurement_system": "metric",
        "regulator_refs": [
            "Υ.Α. ΔΝΣγ/οικ.35577/ΦΝ 466/2017 (ΦΕΚ Β 1746/2017), Νέα Ενιαία Τιμολόγια (ΝΕΤ)",
            (
                "Ν. 4412/2016, Δημόσιες Συμβάσεις Έργων, Προμηθειών και Υπηρεσιών (art. 53 §7θ ΓΕ&ΟΕ, "
                "art. 156 §3α απρόβλεπτα)"
            ),
            "Ν. 4067/2012, Νέος Οικοδομικός Κανονισμός (ΝΟΚ)",
            "Ν. 4495/2017, έλεγχος και προστασία του δομημένου περιβάλλοντος (e-Άδειες)",
            "Ν. 5144/2024, Κώδικας ΦΠΑ: art. 26 (rates), art. 45 §4 (reverse charge on public works)",
            "Κ.Υ.Α. ΔΕΠΕΑ/οικ.178581/2017 (ΦΕΚ Β 2367/2017), ΚΕΝΑΚ",
            "Υ.Α. ΔΙΠΑΔ/οικ.372/2014, Ευρωκώδικες and national annexes",
        ],
        "vat_standard_rate": 24,
        "vat_reduced_rate": 13,
        "review_status": (
            "Currency, tax and regulatory references are drawn from public "
            "sources cited in the README. Pending review by a Greek "
            "engineer who prices public works before they are relied on "
            "for a tender."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
