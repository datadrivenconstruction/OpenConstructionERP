"""Regional configuration for DACH (Germany, Austria, Switzerland)."""

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
    # ── Standards ────────────────────────────────────────────────────────────
    "standards": [
        {
            "code": "DIN_276",
            "name": "DIN 276 — Kosten im Bauwesen",
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
                    "title": "Bauwerk — Baukonstruktionen",
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
                    "title": "Bauwerk — Technische Anlagen",
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
            "name": "VOB — Vergabe- und Vertragsordnung für Bauleistungen",
            "description": "German procurement and contract regulations for construction",
            "parts": [
                {"code": "VOB_A", "title": "Allgemeine Bestimmungen für die Vergabe"},
                {"code": "VOB_B", "title": "Allgemeine Vertragsbedingungen"},
                {"code": "VOB_C", "title": "Allgemeine Technische Vertragsbedingungen (ATV/DIN)"},
            ],
        },
        {
            "code": "HOAI",
            "name": "HOAI — Honorarordnung für Architekten und Ingenieure",
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
                {"lp": 8, "title": "Objektüberwachung — Bauüberwachung", "fee_share_pct": "32"},
                {"lp": 9, "title": "Objektbetreuung", "fee_share_pct": "2"},
            ],
        },
    ],
    # ── GAEB exchange formats ────────────────────────────────────────────────
    "gaeb_formats": [
        {
            "code": "X83",
            "name": "GAEB XML 3.3 — Angebotsabgabe",
            "description": "Tender submission (priced bill)",
            "supported": True,
        },
        {
            "code": "X84",
            "name": "GAEB XML 3.3 — Nebenangebot",
            "description": "Alternative tender submission",
            "supported": True,
        },
        {
            "code": "X86",
            "name": "GAEB XML 3.3 — Auftragserteilung",
            "description": "Contract award",
            "supported": True,
        },
        {
            "code": "X81",
            "name": "GAEB XML 3.3 — Ausschreibung (Leistungsverzeichnis)",
            "description": "Bill of quantities for tender",
            "supported": True,
        },
        {
            "code": "D81",
            "name": "GAEB DA XML — Ausschreibung (legacy)",
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
            "name": "Mehrwertsteuer — Regelsteuersatz",
            "type": "vat",
            "country": "DE",
            "rate_pct": "19",
        },
        {
            "code": "DE_MWST_REDUCED",
            "name": "Mehrwertsteuer — Ermäßigter Satz",
            "type": "vat",
            "country": "DE",
            "rate_pct": "7",
        },
        {
            "code": "AT_UST_STANDARD",
            "name": "Umsatzsteuer — Normalsteuersatz",
            "type": "vat",
            "country": "AT",
            "rate_pct": "20",
        },
        {
            "code": "AT_UST_REDUCED",
            "name": "Umsatzsteuer — Ermäßigter Satz",
            "type": "vat",
            "country": "AT",
            "rate_pct": "10",
        },
        {
            "code": "CH_MWST_STANDARD",
            "name": "Mehrwertsteuer — Normalsatz",
            "type": "vat",
            "country": "CH",
            "rate_pct": "8.1",
        },
        {
            "code": "CH_MWST_REDUCED",
            "name": "Mehrwertsteuer — Reduzierter Satz",
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
    # ── Units (metric defaults) ──────────────────────────────────────────────
    "default_units": {
        "length": "m",
        "area": "m²",
        "volume": "m³",
        "weight": "kg",
        "temperature": "°C",
    },
}
