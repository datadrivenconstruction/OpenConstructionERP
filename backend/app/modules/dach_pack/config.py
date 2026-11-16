# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Regional configuration for DACH (Germany, Austria, Switzerland)."""

from decimal import Decimal
from typing import Any

PACK_CONFIG: dict[str, Any] = {
    # ── Identity ─────────────────────────────────────────────────────────────
    "region_code": "DACH",
    "countries": ["DE", "AT", "CH"],
    "default_currency": "EUR",
    "default_locale": "de",
    "measurement_system": "metric",
    "paper_size": "A4",
    "date_format": "DD.MM.YYYY",
    "number_format": "1.234,56",
    # ── Exchange layouts: column names only, never rates, codes or values ────
    "equipment_rate_layout": {
        "label_key": "packs.dach.equipment_layout",
        "interest_convention": "average_value",
        "decimal_comma": True,
        "mapping": {
            "code": "Nr",
            "name": "Bezeichnung",
            "category": "Gruppe",
            "size_key": "Groesse",
            "value": "Neuwert",
            "residual": "Restwert",
            "life_years": "Nutzungsdauer",
            "months_per_year": "Monate",
            "interest": "Zinssatz",
            "repair": "Reparatur",
            "hours_per_month": "Stunden",
        },
    },
    "payroll_profile": {
        "label_key": "packs.dach.payroll_profile",
        "name": "Payroll DE",
        "delimiter": ";",
        "decimal": ",",
        "date_format": "DD.MM.YYYY",
        "encoding": "utf-8",
        "grouping": "day",
        "columns": [
            {"header": "Personalnummer", "source": "worker_ref"},
            {"header": "Datum", "source": "date"},
            {"header": "Projekt", "source": "project_code"},
            {"header": "Kostenstelle", "source": "cost_code"},
            {"header": "Lohnart", "source": "pay_code"},
            {"header": "Stunden", "source": "hours"},
        ],
    },
    # ── Standards ────────────────────────────────────────────────────────────
    "standards": [
        {
            "code": "DIN_276",
            "name": "DIN 276 - Kosten im Bauwesen",
            "description": "Cost classification for building construction (2018 edition)",
            "cost_groups": [
                {
                    "kg": "100",
                    "title": "Grundstück",
                    "children": [
                        {"kg": "110", "title": "Grundstückswert"},
                        {"kg": "120", "title": "Grundstücksnebenkosten"},
                        {"kg": "130", "title": "Freimachen"},
                    ],
                },
                {
                    "kg": "200",
                    "title": "Vorbereitende Maßnahmen",
                    "children": [
                        {"kg": "210", "title": "Herrichten"},
                        {"kg": "220", "title": "Öffentliche Erschließung"},
                        {"kg": "230", "title": "Nichtöffentliche Erschließung"},
                        {"kg": "240", "title": "Kompensationsmaßnahmen"},
                    ],
                },
                {
                    "kg": "300",
                    "title": "Bauwerk - Baukonstruktionen",
                    "children": [
                        {"kg": "310", "title": "Baugrube/Erdbau"},
                        {"kg": "320", "title": "Gründung, Unterbau"},
                        {"kg": "330", "title": "Außenwände/Vertikale Baukonstruktionen, außen"},
                        {"kg": "340", "title": "Innenwände/Vertikale Baukonstruktionen, innen"},
                        {"kg": "350", "title": "Decken/Horizontale Baukonstruktionen"},
                        {"kg": "360", "title": "Dächer"},
                        {"kg": "370", "title": "Infrastrukturelle Baukonstruktionen"},
                        {"kg": "390", "title": "Sonstige Maßnahmen für Baukonstruktionen"},
                    ],
                },
                {
                    "kg": "400",
                    "title": "Bauwerk - Technische Anlagen",
                    "children": [
                        {"kg": "410", "title": "Abwasser-, Wasser-, Gasanlagen"},
                        {"kg": "420", "title": "Wärmeversorgungsanlagen"},
                        {"kg": "430", "title": "Raumlufttechnische Anlagen"},
                        {"kg": "440", "title": "Elektrische Anlagen"},
                        {"kg": "450", "title": "Kommunikations-, sicherheits-, IT-Anlagen"},
                        {"kg": "460", "title": "Förderanlagen"},
                        {"kg": "470", "title": "Nutzungsspezifische und verfahrenstechn. Anlagen"},
                        {"kg": "480", "title": "Gebäude- und Anlagenautomation"},
                        {"kg": "490", "title": "Sonstige Maßnahmen für Technische Anlagen"},
                    ],
                },
                {
                    "kg": "500",
                    "title": "Außenanlagen und Freiflächen",
                    "children": [
                        {"kg": "510", "title": "Erdbau"},
                        {"kg": "520", "title": "Gründung, Unterbau"},
                        {"kg": "530", "title": "Oberbau, Deckschichten"},
                        {"kg": "540", "title": "Baukonstruktionen"},
                        {"kg": "550", "title": "Technische Anlagen"},
                        {"kg": "560", "title": "Einbauten in Außenanlagen"},
                        {"kg": "570", "title": "Vegetationsflächen"},
                        {"kg": "590", "title": "Sonstige Außenanlagen"},
                    ],
                },
                {
                    "kg": "600",
                    "title": "Ausstattung und Kunstwerke",
                    "children": [
                        {"kg": "610", "title": "Ausstattung"},
                        {"kg": "620", "title": "Kunstwerke"},
                    ],
                },
                {
                    "kg": "700",
                    "title": "Baunebenkosten",
                    "children": [
                        {"kg": "710", "title": "Bauherrenaufgaben"},
                        {"kg": "720", "title": "Vorbereitung der Objektplanung"},
                        {"kg": "730", "title": "Architekten- und Ingenieurleistungen"},
                        {"kg": "740", "title": "Gutachten und Beratung"},
                        {"kg": "750", "title": "Künstlerische Leistungen"},
                        {"kg": "760", "title": "Finanzierung"},
                        {"kg": "770", "title": "Allgemeine Baunebenkosten"},
                        {"kg": "790", "title": "Sonstige Baunebenkosten"},
                    ],
                },
                {
                    "kg": "800",
                    "title": "Finanzierung",
                    "children": [],
                },
            ],
        },
        {
            "code": "VOB",
            "name": "VOB - Vergabe- und Vertragsordnung für Bauleistungen",
            "description": "German procurement and contract regulations for construction",
            "parts": [
                {"code": "VOB_A", "title": "Allgemeine Bestimmungen für die Vergabe"},
                {"code": "VOB_B", "title": "Allgemeine Vertragsbedingungen"},
                {"code": "VOB_C", "title": "Allgemeine Technische Vertragsbedingungen (ATV/DIN)"},
            ],
        },
        {
            "code": "HOAI",
            "name": "HOAI - Honorarordnung für Architekten und Ingenieure",
            "description": "Fee schedule for architects and engineers (2021 edition)",
            "note": "Since 2021: fee tables are non-binding orientation values",
            "service_phases": [
                {"lp": 1, "title": "Grundlagenermittlung", "fee_share_pct": "2"},
                {"lp": 2, "title": "Vorplanung", "fee_share_pct": "7"},
                {"lp": 3, "title": "Entwurfsplanung", "fee_share_pct": "15"},
                {"lp": 4, "title": "Genehmigungsplanung", "fee_share_pct": "3"},
                {"lp": 5, "title": "Ausführungsplanung", "fee_share_pct": "25"},
                {"lp": 6, "title": "Vorbereitung der Vergabe", "fee_share_pct": "10"},
                {"lp": 7, "title": "Mitwirkung bei der Vergabe", "fee_share_pct": "4"},
                {"lp": 8, "title": "Objektüberwachung - Bauüberwachung", "fee_share_pct": "32"},
                {"lp": 9, "title": "Objektbetreuung", "fee_share_pct": "2"},
            ],
        },
    ],
    # ── GAEB exchange formats ────────────────────────────────────────────────
    "gaeb_formats": [
        {
            "code": "X83",
            "name": "GAEB XML 3.3 - Angebotsaufforderung",
            "description": "Call for bids (tender request, unpriced)",
            "supported": True,
        },
        {
            "code": "X84",
            "name": "GAEB XML 3.3 - Angebotsabgabe",
            "description": "Priced bid submission",
            "supported": True,
        },
        {
            "code": "X86",
            "name": "GAEB XML 3.3 - Auftragserteilung",
            "description": "Contract award",
            "supported": True,
        },
        {
            "code": "X81",
            "name": "GAEB XML 3.3 - Ausschreibung (Leistungsverzeichnis)",
            "description": "Bill of quantities for tender",
            "supported": True,
        },
        {
            "code": "D81",
            "name": "GAEB DA XML - Ausschreibung (legacy)",
            "description": "Legacy GAEB DA 2000 format",
            "supported": False,
        },
    ],
    # ── Contract types ───────────────────────────────────────────────────────
    "contract_types": [
        {
            "code": "VOB_B_EINHEITSPREIS",
            "name": "VOB/B Einheitspreisvertrag",
            "description": "Unit-price contract per VOB/B",
        },
        {
            "code": "VOB_B_PAUSCHAL",
            "name": "VOB/B Pauschalvertrag",
            "description": "Lump-sum contract per VOB/B",
        },
        {
            "code": "VOB_B_STUNDENLOHN",
            "name": "VOB/B Stundenlohnvertrag",
            "description": "Time-and-materials contract per VOB/B",
        },
        {
            "code": "BGB_WERKVERTRAG",
            "name": "BGB Werkvertrag §§ 631 ff.",
            "description": "Contract for work under German Civil Code",
        },
    ],
    # ── Tax rules ────────────────────────────────────────────────────────────
    "tax_rules": [
        {
            "code": "DE_MWST_STANDARD",
            "name": "Mehrwertsteuer - Regelsteuersatz",
            "type": "vat",
            "country": "DE",
            "rate_pct": "19",
        },
        {
            "code": "DE_MWST_REDUCED",
            "name": "Mehrwertsteuer - Ermäßigter Satz",
            "type": "vat",
            "country": "DE",
            "rate_pct": "7",
        },
        {
            "code": "AT_UST_STANDARD",
            "name": "Umsatzsteuer - Normalsteuersatz",
            "type": "vat",
            "country": "AT",
            "rate_pct": "20",
        },
        {
            "code": "AT_UST_REDUCED",
            "name": "Umsatzsteuer - Ermäßigter Satz",
            "type": "vat",
            "country": "AT",
            "rate_pct": "10",
        },
        {
            "code": "CH_MWST_STANDARD",
            "name": "Mehrwertsteuer - Normalsatz",
            "type": "vat",
            "country": "CH",
            "rate_pct": "8.1",
        },
        {
            "code": "CH_MWST_REDUCED",
            "name": "Mehrwertsteuer - Reduzierter Satz",
            "type": "vat",
            "country": "CH",
            "rate_pct": "2.6",
        },
    ],
    # ── Payment templates ────────────────────────────────────────────────────
    "payment_templates": [
        {
            "code": "ABSCHLAGSRECHNUNG",
            "name": "Abschlagsrechnung",
            "description": "Interim payment invoice per § 632a BGB / § 16 VOB/B",
            "fields": [
                "invoice_number",
                "period",
                "contract_sum",
                "nachtrag_sum",
                "adjusted_contract_sum",
                "cumulative_work_done",
                "previous_payments",
                "current_claim",
                "retainage_pct",
                "retainage_amount",
                "net_payment",
                "mwst",
                "gross_payment",
            ],
        },
        {
            "code": "SCHLUSSRECHNUNG",
            "name": "Schlussrechnung",
            "description": "Final invoice per § 16 VOB/B",
        },
    ],
    # ── Progress billing ─────────────────────────────────────────────────────
    # Read through ``app.core.regional_packs.resolve_progress_billing``. Keyed
    # per country on purpose: this pack also claims AT and CH, and a German
    # figure must never answer for them (Austria once got Germany's VAT that
    # way). Only DE is written; AT and CH resolve to None until someone sources
    # them. Every number sits under a dict that carries ``statute_reference``
    # or ``source`` plus ``effective_date`` (``None`` = commencement not
    # established). VOB/B applies by agreement; VOB/A binds public awarding
    # authorities, so its ceilings are guidance for everyone else.
    "progress_billing": {
        "DE": {
            "retention_policy": {
                "tiers": [{"from_percent_complete": "0", "rate": "10"}],
                "rate_is_maximum": True,
                "tier_mode": "prospective",
                "stored_materials_rate": None,
                "statute_reference": "§ 17 Abs. 6 Nr. 1 Satz 1 VOB/B",
                "effective_date": None,
                "note": (
                    "Where the parties agreed that the security is kept back from payments, the client may cut "
                    "each payment by at most 10 percent until the agreed security sum is reached. Delivered and "
                    "specially made materials count as work in the payment (§ 16 Abs. 1 Nr. 1 VOB/B), so they "
                    "are retained at the same rate and no separate stored-materials rate is set. VOB/B caps "
                    "nothing itself: the cut stops at the agreed security sum, which each contract states, so "
                    "the cap is left to the contract."
                ),
                "cap": None,
                "public_client_cap": {
                    "percent_of_contract_sum": "5",
                    "statute_reference": "§ 9c Abs. 2 Satz 1 VOB/A",
                    "effective_date": None,
                    "note": (
                        "For a public awarding authority the performance security should not exceed 5 percent of "
                        "the contract sum. It binds public clients only; a private contract agrees its own figure."
                    ),
                },
                "public_client_waiver": {
                    "below_contract_sum_net_eur": "250000",
                    "statute_reference": "§ 9c Abs. 1 Satz 2 VOB/A",
                    "effective_date": None,
                    "note": (
                        "A public awarding authority waives the performance security, and as a rule the "
                        "defects security, where the contract sum is below 250,000 euros net of VAT."
                    ),
                },
                "escrow": {
                    "required": True,
                    "deposit_within_working_days": "18",
                    "public_client_own_custody_account": True,
                    "deferred_deposit_for_small_or_short_contracts": True,
                    "statute_reference": "§ 17 Abs. 6 Nr. 1 Satz 3, Nr. 2 and Nr. 4 VOB/B",
                    "effective_date": None,
                    "note": (
                        "The client tells the contractor each amount kept back and pays it into a blocked "
                        "account (Sperrkonto) within 18 working days of that notice. For small or short "
                        "contracts it may pay in only at final payment; public clients may keep it on their own "
                        "custody account without interest."
                    ),
                },
            },
            "release_events": {
                "events": [
                    {
                        "event": "substantial_completion",
                        "release_percent_of_held": "100",
                        "required_documents": ["acceptance_protocol"],
                        "requires_defects_security": True,
                        "statute_reference": "§ 12 VOB/B, formal acceptance record § 12 Abs. 4 Nr. 1; § 17 Abs. 8 Nr. 1 VOB/B",
                        "effective_date": None,
                        "note": (
                            "Acceptance (Abnahme) releases the unused performance security at the agreed time, "
                            "at the latest once the work is accepted and the security for defect claims is "
                            "provided. The client may keep back a matching part for contract claims the defects "
                            "security does not cover. The protocol is the written record of a formal acceptance."
                        ),
                        "starts_security": {
                            "kind": "defects_liability",
                            "percent_of_final_account": None,
                            "source": "contractual",
                            "effective_date": None,
                            "public_client_ceiling": {
                                "percent_of_final_account": "3",
                                "statute_reference": "§ 9c Abs. 2 Satz 2 VOB/A",
                                "effective_date": None,
                                "note": (
                                    "For a public awarding authority the security for defect claims should not "
                                    "exceed 3 percent of the final account sum; a private contract agrees its own."
                                ),
                            },
                        },
                    },
                    {
                        "event": "defects_period_end",
                        "release_percent_of_held": "100",
                        "period_years": "2",
                        "period_starts_at": "substantial_completion",
                        "required_documents": [],
                        "statute_reference": "§ 17 Abs. 8 Nr. 2 VOB/B",
                        "effective_date": None,
                        "note": (
                            "The unused security for defect claims is returned two years after acceptance unless "
                            "another date was agreed. The client may keep back a matching part for defect claims "
                            "it has raised and that are still open."
                        ),
                    },
                    {
                        "event": "security_substituted",
                        "release_percent_of_held": "100",
                        "requires_security_type": "retention_bond",
                        "required_documents": [],
                        "statute_reference": "§ 17 Abs. 3 VOB/B",
                        "effective_date": None,
                        "note": "The contractor chooses the kind of security and may replace one with another.",
                    },
                ],
            },
            "stored_materials": {
                "billable": True,
                "requirements_by_location_kind": {
                    "on_site": {
                        "any_of": [["title_transferred"], ["security"]],
                        "statute_reference": "§ 16 Abs. 1 Nr. 1 Satz 3 VOB/B; § 632a Abs. 1 Satz 6 BGB",
                        "effective_date": None,
                    },
                    "off_site": {
                        "any_of": [["title_transferred"], ["security"]],
                        "eligible_items": "specially_fabricated_components",
                        "statute_reference": "§ 16 Abs. 1 Nr. 1 Satz 3 VOB/B; § 632a Abs. 1 Satz 6 BGB",
                        "effective_date": None,
                    },
                    "bonded_warehouse": {
                        "any_of": [["title_transferred"], ["security"]],
                        "eligible_items": "specially_fabricated_components",
                        "statute_reference": "§ 16 Abs. 1 Nr. 1 Satz 3 VOB/B; § 632a Abs. 1 Satz 6 BGB",
                        "effective_date": None,
                    },
                    "supplier_premises": {
                        "any_of": [["title_transferred"], ["security"]],
                        "eligible_items": "specially_fabricated_components",
                        "statute_reference": "§ 16 Abs. 1 Nr. 1 Satz 3 VOB/B; § 632a Abs. 1 Satz 6 BGB",
                        "effective_date": None,
                    },
                },
                "statute_reference": "§ 16 Abs. 1 Nr. 1 Satz 3 VOB/B; § 632a Abs. 1 Satz 6 BGB",
                "effective_date": None,
                "bgb_effective_date": "2018-01-01",
                "note": (
                    "Materials delivered to site, and components made specially for the work and held ready, "
                    "count as work in an interim payment if the client, at its choice, has been given ownership "
                    "of them or equivalent security. Away from the site only the specially made components "
                    "qualify. The BGB wording applies to contracts concluded from 1 January 2018."
                ),
            },
            "sub_payment_requirements": {
                # Summary the subcontractor rollup reads; ``requirements`` below
                # is the detail, and a test holds the two to the same names.
                # No lien waiver: neither VOB/B nor the BGB asks for one with a
                # payment, so the flag stays False rather than borrowing the US rule.
                "certificate_types": [
                    "construction_tax_exemption",
                    "social_security_clearance",
                    "employers_liability_clearance",
                ],
                "lien_waiver_required": False,
                "statute_reference": "§ 48 Abs. 2 and § 48b EStG; § 28e Abs. 3a to 3f SGB IV; § 150 Abs. 3 SGB VII",
                "effective_date": None,
                "requirements": [
                    {
                        "code": "construction_tax_exemption",
                        "evidence": "certificate",
                        "cert_type": "construction_tax_exemption",
                        "valid_at": "payment_date",
                        "effect_if_missing": "tax_withholding",
                        "withholding_scheme": "DE_BAUABZUGSTEUER",
                        "statute_reference": "§ 48 Abs. 2 Satz 1 EStG; § 48b Abs. 1 EStG",
                        "effective_date": "2002-01-01",
                        "note": (
                            "Without an exemption certificate (Freistellungsbescheinigung) that is valid when "
                            "the payment is made, the client must withhold the construction withholding tax; "
                            "the rate and the small-amount limit live in the tax withholding scheme."
                        ),
                    },
                    {
                        "code": "social_security_clearance",
                        "evidence": "certificate",
                        "cert_type": "social_security_clearance",
                        "valid_at": "period_end",
                        "coverage": "contract_duration_without_gaps",
                        "alternative": "prequalification",
                        "effect_if_missing": "contractor_liability",
                        "applies_from_total_construction_value_eur": "275000",
                        "statute_reference": "§ 28e Abs. 3a, 3b, 3d and 3f SGB IV; § 14 AEntG",
                        "effective_date": None,
                        "note": (
                            "A main contractor is liable like a guarantor for its subcontractor's social security "
                            "contributions once the construction work commissioned for the building reaches "
                            "275,000 euros. Prequalification or clearance certificates from the collecting "
                            "agencies covering the whole contract period without a gap discharge it. The "
                            "posted-workers act adds the same liability for contributions to the joint "
                            "institutions of the collective agreement, such as the construction industry fund "
                            "(SOKA-BAU), which issues its own clearance."
                        ),
                    },
                    {
                        "code": "employers_liability_clearance",
                        "evidence": "certificate",
                        "cert_type": "employers_liability_clearance",
                        "valid_at": "period_end",
                        "coverage": "contract_duration_without_gaps",
                        "effect_if_missing": "contractor_liability",
                        "statute_reference": "§ 150 Abs. 3 SGB VII with § 28e Abs. 3a to 3f SGB IV",
                        "effective_date": None,
                        "note": (
                            "The same liability covers the statutory accident insurance contributions; the "
                            "subcontractor proves payment with a qualified clearance certificate from its "
                            "accident insurance carrier (Berufsgenossenschaft)."
                        ),
                    },
                ],
            },
            "billing_cycle": {
                "frequency": "monthly",
                "period_end": "month_end",
                "source": "industry_practice",
                "effective_date": None,
                "note": (
                    "VOB/B names no interval; monthly is the usual agreed rhythm, and three to four weeks is "
                    "what commentary treats as reasonable where nothing was agreed."
                ),
                "interval_rule": {
                    "text": "in möglichst kurzen Zeitabständen oder zu den vereinbarten Zeitpunkten",
                    "statute_reference": "§ 16 Abs. 1 Nr. 1 Satz 1 VOB/B",
                    "effective_date": None,
                },
                "payment_clock_regimes": {
                    "vob_b_interim": "de_vob_b_abschlag",
                    "vob_b_final": "de_vob_b_schluss",
                    "bgb_interim": "de_bgb_632a",
                },
            },
            "change_line_code_format": {
                "format": "N{source_code}",
                "placeholders": ["source_code"],
                "source": "platform_convention",
                "effective_date": None,
                "note": "Additional-work items (Nachtragspositionen) are listed apart from the original bill of quantities.",
            },
        },
    },
    # ── Units (metric defaults) ──────────────────────────────────────────────
    "default_units": {
        "length": "m",
        "area": "m²",
        "volume": "m³",
        "weight": "kg",
        "temperature": "°C",
    },
    # ── VAT rates (Wave 25) ──────────────────────────────────────────────────
    # ISO-2 country code → kind → Decimal rate (0.19 = 19 %).
    # Mirrored into ``app.core.tax._RAW`` for centralised lookup.
    "vat_rates": {
        "DE": {
            "standard": Decimal("0.19"),
            "reduced": Decimal("0.07"),
            "zero": Decimal("0.00"),
        },
        "AT": {
            "standard": Decimal("0.20"),
            "reduced": Decimal("0.10"),
            "zero": Decimal("0.00"),
        },
        "CH": {
            "standard": Decimal("0.081"),
            "reduced": Decimal("0.026"),
            "zero": Decimal("0.00"),
        },
    },
}
