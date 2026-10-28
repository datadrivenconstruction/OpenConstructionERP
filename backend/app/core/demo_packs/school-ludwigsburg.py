# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Demo: four-form-entry all-day primary school with sports hall and Mensa,
# Ludwigsburg (Baden-Württemberg). DIN 276:2018-12 cost calculation,
# public owner (invented town). All names, streets and companies are fictional.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="school-ludwigsburg",
    project_name="Grundschule Ludwigsburg Neckarweihingen, Ganztag",
    project_description=(
        "Neubau einer vierzügigen Grundschule im Ganztagsbetrieb mit Einfeld-Sporthalle und Mensa "
        "für die Stadt Ludwigsburg. 16 Klassenräume plus Fachräume, Betreuungs- und Ganztagsbereiche, "
        "Bibliothek, Verwaltung. Dreigeschossiger Schulbau, Mensa mit Produktionsküche, "
        "Einfeld-Sporthalle 15 x 27 m. BGF ca. 10.500 m2, Grundstück ca. 22.000 m2. "
        "Holzrahmenbau-Fassaden auf Stahlbeton-Skelett, Akustikdecken in allen Unterrichtsräumen, "
        "Lüftung mit Wärmerückgewinnung, Photovoltaik auf den Dächern, Wärmepumpe. "
        "Barrierefrei nach DIN 18040. Schulhof mit Spielbereichen. "
        "Baukosten KG 200-700 ca. 27 Mio EUR netto vor Zuschlägen."
    ),
    region="DACH",
    classification_standard="din276",
    currency="EUR",
    locale="de",
    address={
        "street": "Schulweg am Mühlbach 6",
        "city": "Ludwigsburg",
        "postcode": "71634",
        "country": "Germany",
        "lat": 48.8975,
        "lng": 9.1920,
    },
    project_code="GS-LB-2026",
    subdivision_code="DE-BW",
    validation_rule_sets=["din276", "gaeb", "boq_quality"],
    boq_name="Kostenberechnung nach DIN 276 (HOAI LP3)",
    boq_description=(
        "Kostenberechnung gem. DIN 276:2018-12 für KG 200 bis KG 700, "
        "Schulgebäude, Sporthalle und Mensa. Vergabe in Fachlosen nach VOB/A."
    ),
    boq_metadata={
        "standard": "DIN 276:2018-12",
        "phase": "Kostenberechnung (HOAI LP3)",
        "base_date": "2026-Q4",
        "price_level": "Ludwigsburg/Baden-Württemberg 2026",
    },
    sections=[
        (
            "210",
            "KG 200 - Vorbereitende Maßnahmen, Erschließung",
            {"din276": "200"},
            [
                ("210.1", "Kampfmittelsondierung Grundstück", "m2", 22000, 3.60, {"din276": "211"}),
                ("210.2", "Baumfällung + Ersatzpflanzung", "lsum", 1, 60000.00, {"din276": "212"}),
                ("210.3", "Anschlüsse Wasser, Abwasser, Strom, Glasfaser", "lsum", 1, 420000.00, {"din276": "222"}),
            ],
        ),
        (
            "310",
            "KG 310 - Baugrube / Erdbau",
            {"din276": "310"},
            [
                ("310.1", "Baugrundgutachten", "lsum", 1, 32000.00, {"din276": "311"}),
                ("310.2", "Aushub Klasse 3-5", "m3", 9000, 14.00, {"din276": "313"}),
                ("310.3", "Bodenabtransport + Verwertung", "m3", 6000, 25.00, {"din276": "313"}),
                ("310.4", "Baugrubenverbau", "m2", 600, 210.00, {"din276": "312"}),
            ],
        ),
        (
            "320",
            "KG 320 - Gründung, Unterbau",
            {"din276": "320"},
            [
                ("320.1", "Sauberkeitsschicht C12/15", "m2", 4200, 11.00, {"din276": "322"}),
                ("320.2", "Bodenplatte Stahlbeton C30/37", "m3", 1650, 235.00, {"din276": "324"}),
                ("320.3", "Bewehrung Bodenplatte BSt 500", "t", 150, 1700.00, {"din276": "324"}),
                ("320.4", "Streifenfundamente", "m3", 380, 230.00, {"din276": "322"}),
                ("320.5", "Perimeterdämmung", "m2", 1800, 48.00, {"din276": "335"}),
                ("320.6", "Unterbau Sporthalle Schottertragschicht", "m2", 1600, 55.00, {"din276": "323"}),
            ],
        ),
        (
            "330",
            "KG 330 - Außenwände",
            {"din276": "330"},
            [
                ("330.1", "Holzrahmenbau-Fassadenelemente gedämmt", "m2", 5600, 380.00, {"din276": "331"}),
                ("330.2", "Stahlbeton-Sockel + Untergeschoss", "m3", 700, 260.00, {"din276": "331"}),
                ("330.3", "Fassadenbekleidung Holz / Putz", "m2", 5600, 78.00, {"din276": "335"}),
                ("330.4", "Holz-Alu-Fenster 3-fach-Verglasung", "m2", 1700, 640.00, {"din276": "334"}),
                ("330.5", "Außenliegender Sonnenschutz Raffstore", "m2", 1500, 210.00, {"din276": "338"}),
                ("330.6", "Pfosten-Riegel-Fassade Eingang + Mensa", "m2", 520, 650.00, {"din276": "337"}),
                ("330.7", "Außentüren", "pcs", 14, 5200.00, {"din276": "334"}),
            ],
        ),
        (
            "340",
            "KG 340 - Innenwände",
            {"din276": "340"},
            [
                ("340.1", "Stahlbeton-Wände + Kerne", "m3", 600, 380.00, {"din276": "341"}),
                ("340.2", "Klassentrennwände Trockenbau, erhöhter Schallschutz", "m2", 6200, 105.00, {"din276": "342"}),
                ("340.3", "Innentüren Holz", "pcs", 210, 1020.00, {"din276": "344"}),
                ("340.4", "Brandschutztüren T30/T90", "pcs", 46, 1700.00, {"din276": "344"}),
                ("340.5", "Akustik-Wandbekleidung Unterrichtsräume", "m2", 2200, 86.00, {"din276": "345"}),
                ("340.6", "Innenputz + Anstrich", "m2", 24000, 12.00, {"din276": "345"}),
                ("340.7", "Wandfliesen Sanitär + Küche", "m2", 1400, 66.00, {"din276": "345"}),
                ("340.8", "WC-Trennwandsysteme", "pcs", 38, 980.00, {"din276": "346"}),
            ],
        ),
        (
            "350",
            "KG 350 - Decken",
            {"din276": "350"},
            [
                ("350.1", "Stahlbeton-Decken C30/37, d=28 cm", "m3", 2300, 320.00, {"din276": "351"}),
                ("350.2", "Schalung Decken", "m2", 8100, 30.00, {"din276": "351"}),
                ("350.3", "Bewehrung Decken BSt 500", "t", 230, 1700.00, {"din276": "351"}),
                ("350.4", "Zementestrich schwimmend", "m2", 8100, 38.00, {"din276": "352"}),
                ("350.5", "Linoleum Klassenräume + Flure", "m2", 6200, 58.00, {"din276": "352"}),
                ("350.6", "Akustik-Unterdecken Unterrichtsräume", "m2", 7800, 88.00, {"din276": "353"}),
                ("350.7", "Sporthallenboden punktelastisch, Linierung", "m2", 460, 190.00, {"din276": "352"}),
                ("350.8", "Fertigteiltreppen", "pcs", 12, 6200.00, {"din276": "351"}),
            ],
        ),
        (
            "360",
            "KG 360 - Dächer",
            {"din276": "360"},
            [
                ("360.1", "Brettschichtholz-Dachtragwerk Sporthalle", "m3", 420, 1250.00, {"din276": "361"}),
                ("360.2", "Dachabdichtung + Dämmung", "m2", 4200, 115.00, {"din276": "363"}),
                ("360.3", "Extensivbegrünung", "m2", 3000, 52.00, {"din276": "363"}),
                ("360.4", "Photovoltaikanlage Dach 400 kWp", "lsum", 1, 420000.00, {"din276": "362"}),
                ("360.5", "Lichtkuppeln + Rauch- und Wärmeabzug", "pcs", 24, 2400.00, {"din276": "362"}),
                ("360.6", "Absturzsicherung", "m", 380, 130.00, {"din276": "362"}),
                ("360.7", "Dachentwässerung", "lsum", 1, 60000.00, {"din276": "362"}),
            ],
        ),
        (
            "390",
            "KG 390 - Sonstige Maßnahmen für Baukonstruktionen",
            {"din276": "390"},
            [
                ("390.1", "Baustelleneinrichtung", "lsum", 1, 480000.00, {"din276": "391"}),
                ("390.2", "Turmdrehkran inkl. Vorhaltung", "month", 14, 12500.00, {"din276": "392"}),
                ("390.3", "Gerüst", "m2", 7600, 15.00, {"din276": "392"}),
                ("390.4", "Baureinigung", "m2", 10500, 6.50, {"din276": "395"}),
            ],
        ),
        (
            "410",
            "KG 410 - Abwasser-, Wasser-, Gasanlagen",
            {"din276": "410"},
            [
                ("410.1", "Grundleitungen", "m", 1800, 58.00, {"din276": "411"}),
                ("410.2", "Trinkwasserinstallation", "lsum", 1, 520000.00, {"din276": "412"}),
                ("410.3", "Sanitärobjekte WC + Waschtische", "pcs", 190, 1150.00, {"din276": "412"}),
                ("410.4", "Duschen Sporthalle", "pcs", 24, 1400.00, {"din276": "412"}),
                ("410.5", "Regenwasserrückhaltung", "lsum", 1, 220000.00, {"din276": "419"}),
            ],
        ),
        (
            "420",
            "KG 420 - Wärmeversorgungsanlagen",
            {"din276": "420"},
            [
                ("420.1", "Wärmepumpenanlage 650 kW", "lsum", 1, 380000.00, {"din276": "421"}),
                ("420.2", "Fußbodenheizung", "m2", 7000, 58.00, {"din276": "423"}),
                ("420.3", "Heizkörper", "pcs", 260, 520.00, {"din276": "423"}),
                ("420.4", "Verteilung + Pumpen", "lsum", 1, 280000.00, {"din276": "422"}),
            ],
        ),
        (
            "430",
            "KG 430 - Raumlufttechnische Anlagen",
            {"din276": "430"},
            [
                ("430.1", "RLT-Zentralgeräte mit Wärmerückgewinnung", "pcs", 6, 62000.00, {"din276": "431"}),
                ("430.2", "Dezentrale Klassenraumlüftung", "pcs", 56, 9800.00, {"din276": "431"}),
                ("430.3", "Mensa- und Küchenlüftung", "lsum", 1, 260000.00, {"din276": "431"}),
                ("430.4", "Sporthallenlüftung", "lsum", 1, 110000.00, {"din276": "431"}),
                ("430.5", "Luftkanäle verzinkt", "m2", 4000, 76.00, {"din276": "431"}),
                ("430.6", "Brandschutzklappen", "pcs", 180, 280.00, {"din276": "431"}),
            ],
        ),
        (
            "440",
            "KG 440 - Elektrische Anlagen, Starkstrom",
            {"din276": "440"},
            [
                ("440.1", "Niederspannungshauptverteilung", "pcs", 2, 42000.00, {"din276": "443"}),
                ("440.2", "Unterverteilungen", "pcs", 24, 4800.00, {"din276": "443"}),
                ("440.3", "Elektroinstallation", "m2", 10500, 78.00, {"din276": "444"}),
                ("440.4", "Beleuchtung LED + Tageslichtsteuerung", "m2", 10500, 46.00, {"din276": "445"}),
                ("440.5", "Sicherheitsbeleuchtung", "lsum", 1, 140000.00, {"din276": "445"}),
                ("440.6", "Blitzschutz + Erdung", "lsum", 1, 110000.00, {"din276": "446"}),
                ("440.7", "Ladeinfrastruktur Lehrerparkplatz", "pcs", 12, 2600.00, {"din276": "442"}),
            ],
        ),
        (
            "450",
            "KG 450 - Kommunikations-, sicherheits- u. informationstechn. Anlagen",
            {"din276": "450"},
            [
                ("450.1", "Strukturierte Verkabelung + WLAN", "m2", 10500, 34.00, {"din276": "456"}),
                ("450.2", "Brandmeldeanlage", "m2", 10500, 16.00, {"din276": "454"}),
                ("450.3", "Elektroakustische Alarmierungsanlage", "lsum", 1, 160000.00, {"din276": "454"}),
                ("450.4", "Interaktive Tafeln Klassenräume", "pcs", 56, 6800.00, {"din276": "457"}),
                ("450.5", "Zutrittskontrolle + Schließanlage", "lsum", 1, 120000.00, {"din276": "453"}),
            ],
        ),
        (
            "460",
            "KG 460 - Förderanlagen",
            {"din276": "460"},
            [
                ("460.1", "Personenaufzug barrierefrei", "pcs", 2, 62000.00, {"din276": "461"}),
            ],
        ),
        (
            "470",
            "KG 470 - Nutzungsspezifische Anlagen",
            {"din276": "470"},
            [
                ("470.1", "Produktionsküche Mensa komplett", "lsum", 1, 640000.00, {"din276": "471"}),
                (
                    "470.2",
                    "Sporthallen-Sonderausstattung (Prallwände, Geräteraum)",
                    "lsum",
                    1,
                    180000.00,
                    {"din276": "479"},
                ),
            ],
        ),
        (
            "480",
            "KG 480 - Gebäude- und Anlagenautomation",
            {"din276": "480"},
            [
                ("480.1", "Gebäudeleittechnik + Raumautomation", "lsum", 1, 480000.00, {"din276": "481"}),
            ],
        ),
        (
            "500",
            "KG 500 - Außenanlagen und Freiflächen",
            {"din276": "500"},
            [
                ("500.1", "Schulhof Pflaster- und Asphaltflächen", "m2", 5200, 88.00, {"din276": "520"}),
                ("500.2", "Spielgeräte + Spielbereiche", "lsum", 1, 240000.00, {"din276": "530"}),
                ("500.3", "Baumpflanzungen", "pcs", 48, 1750.00, {"din276": "530"}),
                ("500.4", "Rasen- und Pflanzflächen", "m2", 4000, 32.00, {"din276": "530"}),
                ("500.5", "Fahrradstellplätze überdacht", "pcs", 280, 340.00, {"din276": "560"}),
                ("500.6", "Einfriedung", "m", 380, 130.00, {"din276": "560"}),
                ("500.7", "Außenbeleuchtung", "pcs", 36, 1500.00, {"din276": "550"}),
                ("500.8", "Kleinspielfeld + Laufbahn", "lsum", 1, 220000.00, {"din276": "530"}),
                ("500.9", "Außenentwässerung", "lsum", 1, 140000.00, {"din276": "540"}),
            ],
        ),
        (
            "600",
            "KG 600 - Ausstattung und Kunstwerke",
            {"din276": "600"},
            [
                ("600.1", "Klassenraummöbel", "pcs", 56, 6800.00, {"din276": "610"}),
                (
                    "600.2",
                    "Fachraumausstattung Werken, Kunst, Naturwissenschaft",
                    "lsum",
                    1,
                    340000.00,
                    {"din276": "610"},
                ),
                ("600.3", "Mensa-Möblierung", "lsum", 1, 160000.00, {"din276": "610"}),
                ("600.4", "Turngeräte Sporthalle", "lsum", 1, 120000.00, {"din276": "610"}),
                ("600.5", "Bibliothek + Verwaltung", "lsum", 1, 90000.00, {"din276": "610"}),
            ],
        ),
        (
            "700",
            "KG 700 - Baunebenkosten",
            {"din276": "700"},
            [
                ("700.1", "Objekt- und Fachplanung gem. HOAI (LP 1-8)", "lsum", 1, 2500000.00, {"din276": "730"}),
                ("700.2", "Projektsteuerung", "lsum", 1, 450000.00, {"din276": "710"}),
                ("700.3", "Gutachten: Schall, Brandschutz, Energie", "lsum", 1, 200000.00, {"din276": "740"}),
                ("700.4", "Genehmigungsgebühren + Prüfingenieure", "lsum", 1, 120000.00, {"din276": "770"}),
                ("700.5", "Versicherungen", "lsum", 1, 150000.00, {"din276": "770"}),
            ],
        ),
    ],
    markups=[
        ("Baustellengemeinkosten (BGK)", 9.0, "overhead", "direct_cost"),
        ("Allgemeine Geschäftskosten (AGK)", 7.0, "overhead", "direct_cost"),
        ("Wagnis (W)", 2.0, "contingency", "direct_cost"),
        ("Gewinn (G)", 4.0, "profit", "direct_cost"),
        ("Mehrwertsteuer (MwSt.)", 19.0, "tax", "cumulative"),
    ],
    # One bill, one total: the control budget would repeat the same scope.
    with_budget_boq=False,
    total_months=34,
    tender_name="Rohbau",
    tender_companies=[
        ("Hohenasperg Bau GmbH", "vergabe@hohenasperg-bau.example", 0.98),
        ("Neckartal Hochbau GmbH & Co. KG", "ausschreibung@neckartal-hochbau.example", 1.03),
        ("Strohgäu Bauunternehmung", "angebote@strohgaeu-bau.example", 1.01),
    ],
    project_metadata={
        "address": "Schulweg am Mühlbach 6, 71634 Ludwigsburg",
        "client": "Stadt Ludwigsburg, Hochbauamt",
        "main_contractor": "Hohenasperg Bau GmbH",
        "architect": "Lindenhof Seeger Architekten, Stuttgart",
        "structural_engineer": "Ingenieurbüro Rembold + Auer",
        "mep_engineer": "Technische Planung Enzkreis",
        "gfa_m2": 10500,
        "plot_area_m2": 22000,
        "classes": 16,
        "form_entry": 4,
        "sports_hall": "Einfeld-Sporthalle 15 x 27 m",
        "storeys_above": 3,
        "structure_system": "Stahlbeton-Skelett mit Holzrahmenbau-Fassaden, Sporthalle in Brettschichtholz",
        "energy_standard": "GEG, Wärmepumpe, PV 400 kWp",
        "procurement": "Fachlose nach VOB/A",
        "design_phase": "HOAI LP3 Entwurfsplanung / Kostenberechnung",
        "applicable_standards": [
            "DIN 276:2018-12",
            "VOB/A, VOB/C (DIN 18299 ff.)",
            "GAEB DA XML 3.3 (X83)",
            "HOAI 2021",
            "DIN 18041 Raumakustik",
            "DIN 18040 Barrierefreiheit",
            "DIN 18032 Sporthallen",
        ],
        "permit_authority": "Stadt Ludwigsburg, Baurechtsamt (LBO BW)",
        "fire_concept": "Brandschutzkonzept gem. LBO BW / Schulbaurichtlinie",
        "cost_basis": "Baukosten-Benchmarks Schulbau Neubau 2026, Regionalfaktor Ludwigsburg",
    },
    tender_packages=[
        (
            "Fachlos Erd- und Rohbauarbeiten",
            "Baugrube, Gründung, Stahlbeton-Skelett, Kerne, Decken",
            "evaluating",
            [
                ("Hohenasperg Bau GmbH", "vergabe@hohenasperg-bau.example", 0.98),
                ("Neckartal Hochbau GmbH & Co. KG", "ausschreibung@neckartal-hochbau.example", 1.03),
                ("Strohgäu Bauunternehmung", "angebote@strohgaeu-bau.example", 1.01),
            ],
        ),
        (
            "Fachlos Holzbau und Fassade",
            "Holzrahmenbau-Fassadenelemente, Brettschichtholz-Dachtragwerk Sporthalle, Fassadenbekleidung",
            "evaluating",
            [
                ("Holzbau Schwäbischer Wald GmbH", "vergabe@holzbau-sw.example", 0.99),
                ("Zimmerei Remstal", "angebote@zimmerei-remstal.example", 1.04),
                ("Ingenieurholzbau Oberes Neckartal", "tender@ihb-neckartal.example", 1.02),
            ],
        ),
        (
            "Fachlos Fenster und Sonnenschutz",
            "Holz-Alu-Fenster, Pfosten-Riegel-Fassade, Raffstore",
            "evaluating",
            [
                ("Fensterwerk Murrtal GmbH", "vergabe@fensterwerk-murrtal.example", 1.00),
                ("Fassadentechnik Bietigheim", "angebote@fassadentechnik-bietigheim.example", 1.05),
            ],
        ),
        (
            "Fachlos Dach, Abdichtung und PV",
            "Flachdachabdichtung, Begrünung, Photovoltaik, Spenglerarbeiten",
            "draft",
            [
                ("Dachbau Zabergäu GmbH", "vergabe@dachbau-zabergaeu.example", 0.99),
                ("Solardach Kraichgau", "angebote@solardach-kraichgau.example", 1.03),
            ],
        ),
        (
            "Fachlos Heizung Lüftung Sanitär",
            "Wärmepumpe, Fußbodenheizung, Lüftung mit WRG, Sanitär",
            "evaluating",
            [
                ("Gebäudetechnik Enztal GmbH", "vergabe@gt-enztal.example", 0.99),
                ("Haustechnik Löwenstein", "angebote@haustechnik-loewenstein.example", 1.04),
            ],
        ),
        (
            "Fachlos Elektro und Medientechnik",
            "Starkstrom, Beleuchtung, IT-Verkabelung, Alarmierung, Medientechnik",
            "evaluating",
            [
                ("Elektrotechnik Mühlbach GmbH", "vergabe@et-muehlbach.example", 1.00),
                ("Netzwerk und Strom Asperg", "angebote@netzwerk-strom-asperg.example", 1.05),
            ],
        ),
        (
            "Fachlos Trockenbau und Akustik",
            "Klassentrennwände, Akustikdecken, Wandbekleidungen",
            "draft",
            [
                ("Ausbau Schwieberdingen GmbH", "angebote@ausbau-schwieberdingen.example", 0.98),
                ("Akustikbau Remseck", "vergabe@akustikbau-remseck.example", 1.04),
            ],
        ),
        (
            "Fachlos Bodenbeläge und Sporthallenboden",
            "Linoleum, Fliesen, Schwingboden Sporthalle",
            "draft",
            [
                ("Bodenleger Neckarweihingen", "angebote@bodenleger-nwh.example", 0.99),
                ("Sportbodenbau Südwest GmbH", "vergabe@sportbodenbau-sw.example", 1.03),
            ],
        ),
        (
            "Fachlos Küchentechnik Mensa",
            "Produktionsküche, Ausgabe, Spülbereich",
            "draft",
            [
                ("Großküchen Hohenlohe GmbH", "angebote@grosskuechen-hohenlohe.example", 1.00),
                ("Kücheneinrichtung Marbach", "vergabe@kuechen-marbach.example", 1.04),
            ],
        ),
        (
            "Fachlos Außenanlagen Schulhof",
            "Pflaster, Spielgeräte, Begrünung, Einfriedung",
            "draft",
            [
                ("Garten- und Landschaftsbau Strohgäu", "angebote@galabau-strohgaeu.example", 0.98),
                ("Spielplatzbau Ludwigsburg", "vergabe@spielplatzbau-lb.example", 1.05),
            ],
        ),
    ],
    schedule_activities=[
        ("Bedarfsplanung und Raumprogramm mit Schulleitung", "2026-11-01", "2026-12-31"),
        ("Vorentwurf und Entwurfsplanung (LP 2-3), Gemeinderatsbeschluss", "2026-11-15", "2027-03-31"),
        ("Bauantrag und Baugenehmigung", "2027-03-01", "2027-06-30"),
        ("Ausführungsplanung (LP 5)", "2027-04-01", "2027-09-30"),
        ("Ausschreibung und Vergabe Fachlose nach VOB/A", "2027-07-01", "2027-12-31"),
        ("Baufeldfreimachung, Baugrube und Gründung", "2028-01-01", "2028-03-31"),
        ("Rohbau Schulgebäude", "2028-03-01", "2028-08-31"),
        ("Rohbau und Dachtragwerk Sporthalle und Mensa", "2028-05-01", "2028-10-31"),
        ("Holzbau-Fassade, Fenster und Dach", "2028-07-01", "2028-12-31"),
        ("TGA-Installation", "2028-09-01", "2029-02-28"),
        ("Innenausbau, Akustikdecken und Bodenbeläge", "2028-12-01", "2029-05-31"),
        ("Außenanlagen Schulhof", "2029-04-01", "2029-07-31"),
        ("Abnahmen und Übergabe vor Schuljahresbeginn", "2029-06-01", "2029-08-31"),
    ],
)
