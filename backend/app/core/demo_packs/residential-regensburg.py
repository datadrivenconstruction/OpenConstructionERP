# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Demo: residential quarter with four multi-family buildings, Regensburg
# (Bayern). DIN 276:2018-12 cost calculation, owner-side project.
# All names, streets and companies are fictional.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-regensburg",
    project_name="Wohnquartier Regensburg Donaupark",
    project_description=(
        "Neubau eines Wohnquartiers mit vier Mehrfamilienhäusern und ca. 120 Mietwohnungen "
        "(geförderter und freifinanzierter Wohnungsbau) für ein kommunales Wohnungsunternehmen. "
        "4 bis 5 Geschosse plus Staffelgeschoss, gemeinsame Tiefgarage mit 110 Stellplätzen. "
        "Grundstück ca. 14.000 m2, BGF ca. 16.000 m2 oberirdisch, ca. 11.000 m2 Wohnfläche. "
        "Stahlbeton-Massivbau mit Mauerwerk-Außenwänden und WDVS, Balkone als Fertigteile. "
        "Fernwärmeanschluss, Fußbodenheizung, dezentrale Wohnungslüftung mit Wärmerückgewinnung, "
        "Photovoltaik auf den Dächern. Energiestandard KfW Effizienzhaus 40. "
        "Quartiersplatz mit Spielplatz, Fahrradräume und Ladeinfrastruktur. "
        "Baukosten KG 200-700 ca. 41 Mio EUR netto vor Zuschlägen."
    ),
    region="DACH",
    classification_standard="din276",
    currency="EUR",
    locale="de",
    address={
        "street": "Am Donauknie 18",
        "city": "Regensburg",
        "postcode": "93053",
        "country": "Germany",
        "lat": 48.9964,
        "lng": 12.1190,
    },
    project_code="WQ-RGB-2026",
    subdivision_code="DE-BY",
    validation_rule_sets=["din276", "gaeb", "boq_quality"],
    boq_name="Kostenberechnung nach DIN 276 (HOAI LP3)",
    boq_description=(
        "Kostenberechnung gem. DIN 276:2018-12 für KG 200 bis KG 700, "
        "Schwerpunkt KG 300 Bauwerk-Baukonstruktionen und KG 400 Technische Anlagen "
        "für vier Mehrfamilienhäuser mit gemeinsamer Tiefgarage."
    ),
    boq_metadata={
        "standard": "DIN 276:2018-12",
        "phase": "Kostenberechnung (HOAI LP3)",
        "base_date": "2026-Q4",
        "price_level": "Regensburg/Bayern 2026",
    },
    sections=[
        (
            "210",
            "KG 200 - Vorbereitende Maßnahmen, Erschließung",
            {"din276": "200"},
            [
                ("210.1", "Kampfmittelsondierung Grundstück", "m2", 14000, 3.60, {"din276": "211"}),
                ("210.2", "Abbruch Altbestand + Entsorgung", "lsum", 1, 220000.00, {"din276": "212"}),
                ("210.3", "Anschlüsse Fernwärme, Wasser, Strom, Telekom", "lsum", 1, 780000.00, {"din276": "222"}),
                ("210.4", "Erschließungsstraße + Gehweg", "m", 160, 3200.00, {"din276": "230"}),
            ],
        ),
        (
            "310",
            "KG 310 - Baugrube / Erdbau",
            {"din276": "310"},
            [
                ("310.1", "Baugrundgutachten", "lsum", 1, 38000.00, {"din276": "311"}),
                ("310.2", "Aushub Baugrube Klasse 3-5", "m3", 38000, 15.00, {"din276": "313"}),
                ("310.3", "Bodenabtransport + Deponie Z0/Z1.1", "m3", 30000, 27.00, {"din276": "313"}),
                ("310.4", "Baugrubenverbau Trägerbohlwand", "m2", 1900, 260.00, {"din276": "312"}),
                ("310.5", "Wasserhaltung", "month", 10, 11000.00, {"din276": "314"}),
            ],
        ),
        (
            "320",
            "KG 320 - Gründung, Unterbau",
            {"din276": "320"},
            [
                ("320.1", "Sauberkeitsschicht C12/15", "m2", 7800, 11.00, {"din276": "322"}),
                ("320.2", "Bodenplatte WU-Beton C30/37, d=35 cm", "m3", 5200, 215.00, {"din276": "324"}),
                ("320.3", "Bewehrung Bodenplatte BSt 500", "t", 520, 1700.00, {"din276": "324"}),
                ("320.4", "Streifen- und Einzelfundamente", "m3", 900, 240.00, {"din276": "322"}),
                ("320.5", "Perimeterdämmung XPS", "m2", 2400, 48.00, {"din276": "335"}),
            ],
        ),
        (
            "330",
            "KG 330 - Außenwände",
            {"din276": "330"},
            [
                ("330.1", "Stahlbeton-Außenwände Untergeschoss WU", "m3", 2800, 250.00, {"din276": "331"}),
                ("330.2", "Schalung Außenwände", "m2", 9000, 36.00, {"din276": "331"}),
                ("330.3", "Bewehrung Außenwände BSt 500", "t", 300, 1700.00, {"din276": "331"}),
                ("330.4", "Mauerwerk Außenwand Planziegel d=24 cm", "m2", 11500, 165.00, {"din276": "331"}),
                ("330.5", "Wärmedämmverbundsystem Mineralwolle 20 cm", "m2", 11500, 132.00, {"din276": "335"}),
                ("330.6", "Holz-Alu-Fenster 3-fach-Verglasung", "m2", 2100, 620.00, {"din276": "334"}),
                ("330.7", "Raffstore motorisiert", "pcs", 480, 780.00, {"din276": "338"}),
                ("330.8", "Balkone Stahlbeton-Fertigteile", "pcs", 230, 6800.00, {"din276": "337"}),
                ("330.9", "Haustüren Aluminium", "pcs", 16, 4800.00, {"din276": "334"}),
                ("330.10", "Sockelabdichtung + Spritzwasserschutz", "m2", 3000, 58.00, {"din276": "335"}),
                ("330.11", "Garagentore Tiefgarage", "pcs", 2, 18000.00, {"din276": "334"}),
            ],
        ),
        (
            "340",
            "KG 340 - Innenwände",
            {"din276": "340"},
            [
                ("340.1", "Stahlbeton-Treppenhauskerne C30/37", "m3", 1100, 390.00, {"din276": "341"}),
                ("340.2", "Wohnungstrennwände Kalksandstein d=24 cm", "m2", 12000, 105.00, {"din276": "341"}),
                ("340.3", "Trockenbau-Innenwände CW75", "m2", 15000, 58.00, {"din276": "342"}),
                ("340.4", "Innentüren Holz", "pcs", 640, 720.00, {"din276": "344"}),
                ("340.5", "Wohnungseingangstüren T30", "pcs", 120, 1650.00, {"din276": "344"}),
                ("340.6", "Innenputz + Anstrich", "m2", 54000, 13.00, {"din276": "345"}),
                ("340.7", "Wandfliesen Bäder", "m2", 6500, 68.00, {"din276": "345"}),
            ],
        ),
        (
            "350",
            "KG 350 - Decken",
            {"din276": "350"},
            [
                ("350.1", "Stahlbeton-Decken C30/37, d=22 cm", "m3", 6400, 300.00, {"din276": "351"}),
                ("350.2", "Schalung Decken", "m2", 21000, 30.00, {"din276": "351"}),
                ("350.3", "Bewehrung Decken BSt 500", "t", 620, 1700.00, {"din276": "351"}),
                ("350.4", "Zementestrich schwimmend", "m2", 13500, 36.00, {"din276": "352"}),
                ("350.5", "Trittschalldämmung", "m2", 13500, 14.00, {"din276": "352"}),
                ("350.6", "Parkett Wohnräume", "m2", 11000, 78.00, {"din276": "352"}),
                ("350.7", "Bodenfliesen Bäder + Flure", "m2", 2200, 92.00, {"din276": "352"}),
                ("350.8", "Fertigteiltreppen Treppenhäuser", "pcs", 52, 4800.00, {"din276": "351"}),
            ],
        ),
        (
            "360",
            "KG 360 - Dächer",
            {"din276": "360"},
            [
                ("360.1", "Stahlbeton-Dachdecke C30/37", "m3", 1600, 320.00, {"din276": "361"}),
                ("360.2", "Flachdachabdichtung + Gefälledämmung", "m2", 4200, 118.00, {"din276": "363"}),
                ("360.3", "Extensivbegrünung", "m2", 4200, 55.00, {"din276": "363"}),
                ("360.4", "Attika + Dachrandabschluss", "m", 520, 82.00, {"din276": "362"}),
                ("360.5", "Dachentwässerung", "lsum", 1, 94000.00, {"din276": "362"}),
                ("360.6", "Photovoltaikanlage Dach 280 kWp", "lsum", 1, 330000.00, {"din276": "362"}),
            ],
        ),
        (
            "370",
            "KG 370 - Baukonstruktive Einbauten",
            {"din276": "370"},
            [
                ("370.1", "Müllhaus + Briefkastenanlagen", "lsum", 1, 180000.00, {"din276": "371"}),
                ("370.2", "Fahrradräume Einbauten", "lsum", 1, 120000.00, {"din276": "371"}),
            ],
        ),
        (
            "390",
            "KG 390 - Sonstige Maßnahmen für Baukonstruktionen",
            {"din276": "390"},
            [
                ("390.1", "Baustelleneinrichtung", "lsum", 1, 780000.00, {"din276": "391"}),
                ("390.2", "Turmdrehkrane inkl. Vorhaltung", "month", 22, 14500.00, {"din276": "392"}),
                ("390.3", "Fassadengerüst", "m2", 17000, 14.00, {"din276": "392"}),
                ("390.4", "Baureinigung", "m2", 16000, 6.50, {"din276": "395"}),
            ],
        ),
        (
            "410",
            "KG 410 - Abwasser-, Wasser-, Gasanlagen",
            {"din276": "410"},
            [
                ("410.1", "Grundleitungen", "m", 2400, 58.00, {"din276": "411"}),
                ("410.2", "Entwässerung Steigstränge", "pcs", 120, 3400.00, {"din276": "411"}),
                ("410.3", "Trinkwasserinstallation Wohnungen", "pcs", 120, 4800.00, {"din276": "412"}),
                ("410.4", "Sanitärobjekte Bad + WC", "pcs", 120, 4200.00, {"din276": "412"}),
                ("410.5", "Regenwasserrückhaltung", "lsum", 1, 360000.00, {"din276": "419"}),
            ],
        ),
        (
            "420",
            "KG 420 - Wärmeversorgungsanlagen",
            {"din276": "420"},
            [
                ("420.1", "Fernwärme-Übergabestationen", "pcs", 4, 78000.00, {"din276": "421"}),
                ("420.2", "Fußbodenheizung", "m2", 11000, 62.00, {"din276": "423"}),
                ("420.3", "Verteilung + Steigleitungen", "pcs", 120, 2300.00, {"din276": "422"}),
                ("420.4", "Pumpen, Armaturen, Hydraulik", "lsum", 1, 160000.00, {"din276": "422"}),
                ("420.5", "Badheizkörper", "pcs", 120, 420.00, {"din276": "423"}),
            ],
        ),
        (
            "430",
            "KG 430 - Raumlufttechnische Anlagen",
            {"din276": "430"},
            [
                ("430.1", "Dezentrale Wohnungslüftung mit Wärmerückgewinnung", "pcs", 120, 3900.00, {"din276": "431"}),
                ("430.2", "Tiefgaragenlüftung CO-gesteuert", "lsum", 1, 380000.00, {"din276": "434"}),
                ("430.3", "Rauchabzug Treppenhäuser", "pcs", 8, 14000.00, {"din276": "434"}),
            ],
        ),
        (
            "440",
            "KG 440 - Elektrische Anlagen, Starkstrom",
            {"din276": "440"},
            [
                ("440.1", "Hausanschluss + Niederspannungsverteilung", "pcs", 4, 36000.00, {"din276": "443"}),
                ("440.2", "Zählerschränke Wohnungen", "pcs", 120, 1300.00, {"din276": "443"}),
                ("440.3", "Elektroinstallation Wohnungen", "pcs", 120, 7200.00, {"din276": "444"}),
                ("440.4", "Beleuchtung Tiefgarage LED", "m2", 3800, 48.00, {"din276": "445"}),
                ("440.5", "Allgemeinbeleuchtung Treppenhäuser", "lsum", 1, 140000.00, {"din276": "445"}),
                ("440.6", "Blitzschutz + Erdung", "lsum", 1, 90000.00, {"din276": "446"}),
                ("440.7", "Ladeinfrastruktur Tiefgarage", "pcs", 55, 2600.00, {"din276": "442"}),
            ],
        ),
        (
            "450",
            "KG 450 - Kommunikations-, sicherheits- u. informationstechn. Anlagen",
            {"din276": "450"},
            [
                ("450.1", "Türsprechanlage mit Video", "pcs", 120, 820.00, {"din276": "451"}),
                ("450.2", "Multimedia-Verkabelung Wohnungen", "pcs", 120, 1100.00, {"din276": "456"}),
                ("450.3", "Rauchwarnmelder inkl. Wartung 1. Jahr", "pcs", 480, 42.00, {"din276": "454"}),
            ],
        ),
        (
            "460",
            "KG 460 - Förderanlagen",
            {"din276": "460"},
            [
                ("460.1", "Personenaufzug barrierefrei, Tiefgarage bis Dach", "pcs", 8, 68000.00, {"din276": "461"}),
            ],
        ),
        (
            "500",
            "KG 500 - Außenanlagen und Freiflächen",
            {"din276": "500"},
            [
                ("500.1", "Verkehrsflächen Asphalt + Pflaster", "m2", 3200, 82.00, {"din276": "520"}),
                ("500.2", "Wege + Quartiersplatz Pflasterbelag", "m2", 2800, 92.00, {"din276": "520"}),
                ("500.3", "Spielplatz mit Spielgeräten", "lsum", 1, 210000.00, {"din276": "530"}),
                ("500.4", "Baumpflanzungen", "pcs", 55, 1650.00, {"din276": "530"}),
                ("500.5", "Rasen- und Staudenflächen", "m2", 6000, 32.00, {"din276": "530"}),
                ("500.6", "Außenbeleuchtung + Fahrradbügel", "lsum", 1, 140000.00, {"din276": "550"}),
                ("500.7", "Tiefgaragenrampe mit Heizung", "m2", 180, 260.00, {"din276": "520"}),
            ],
        ),
        (
            "700",
            "KG 700 - Baunebenkosten",
            {"din276": "700"},
            [
                ("700.1", "Objekt- und Fachplanung gem. HOAI (LP 1-8)", "lsum", 1, 3400000.00, {"din276": "730"}),
                ("700.2", "Projektsteuerung", "lsum", 1, 600000.00, {"din276": "710"}),
                ("700.3", "Gutachten: Schall, Brandschutz, Energie", "lsum", 1, 250000.00, {"din276": "740"}),
                ("700.4", "Genehmigungsgebühren + Prüfingenieure", "lsum", 1, 300000.00, {"din276": "770"}),
                ("700.5", "Bauherren-Versicherungen", "lsum", 1, 200000.00, {"din276": "770"}),
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
    total_months=30,
    tender_name="Generalunternehmer Rohbau und Ausbau",
    tender_companies=[
        ("Donaustauf Bau GmbH", "vergabe@donaustauf-bau.example", 0.98),
        ("Oberpfalz Wohnungsbau GmbH & Co. KG", "ausschreibung@oberpfalz-wohnungsbau.example", 1.03),
        ("Walhallabau Regensburg GmbH", "angebote@walhallabau.example", 1.01),
    ],
    project_metadata={
        "address": "Am Donauknie 18, 93053 Regensburg",
        "client": "Wohnungsbaugesellschaft Donauknie mbH",
        "main_contractor": "Donaustauf Bau GmbH",
        "architect": "Moosburger Pieper Architekten, Regensburg",
        "structural_engineer": "Tragwerk Naabtal Ingenieure",
        "mep_engineer": "Haustechnik Planung Schwarzach",
        "gfa_m2": 16000,
        "living_area_m2": 11000,
        "units": 120,
        "buildings": 4,
        "parking_spaces": 110,
        "storeys_above": 5,
        "storeys_below": 1,
        "structure_system": "Stahlbeton-Massivbau, Mauerwerk-Außenwände mit WDVS",
        "energy_standard": "KfW Effizienzhaus 40, Fernwärme, PV",
        "design_phase": "HOAI LP3 Entwurfsplanung / Kostenberechnung",
        "applicable_standards": [
            "DIN 276:2018-12",
            "VOB/C (DIN 18299 ff.)",
            "GAEB DA XML 3.3 (X83)",
            "HOAI 2021",
            "GEG 2024",
            "DIN 4109 Schallschutz",
        ],
        "permit_authority": "Stadt Regensburg, Bauordnungsamt (BayBO)",
        "fire_concept": "Brandschutznachweis gem. BayBO, Gebäudeklasse 4/5",
        "cost_basis": "Baukosten-Benchmarks Wohnungsbau Neubau 2026, Regionalfaktor Regensburg",
    },
    tender_packages=[
        (
            "Generalunternehmer Rohbau und Ausbau",
            "Baugrube, Gründung, Stahlbeton, Mauerwerk, WDVS, Trockenbau, Putz, Estrich, Bodenbeläge",
            "evaluating",
            [
                ("Donaustauf Bau GmbH", "vergabe@donaustauf-bau.example", 0.98),
                ("Oberpfalz Wohnungsbau GmbH & Co. KG", "ausschreibung@oberpfalz-wohnungsbau.example", 1.03),
                ("Walhallabau Regensburg GmbH", "angebote@walhallabau.example", 1.01),
            ],
        ),
        (
            "TGA Heizung Lüftung Sanitär",
            "Fernwärmestationen, Fußbodenheizung, Wohnungslüftung, Sanitär, Tiefgaragenlüftung",
            "evaluating",
            [
                ("Haustechnik Altmühl GmbH", "vergabe@haustechnik-altmuehl.example", 0.99),
                ("Installationswerk Straubing", "angebote@installationswerk-straubing.example", 1.04),
                ("Wärme und Wasser Schwandorf GmbH", "tga@waerme-wasser-schwandorf.example", 1.02),
            ],
        ),
        (
            "TGA Elektro",
            "Verteilungen, Wohnungsinstallation, Beleuchtung, Ladeinfrastruktur, Türkommunikation",
            "evaluating",
            [
                ("Elektro Donautal GmbH", "vergabe@elektro-donautal.example", 1.00),
                ("Stromwerk Regenstauf", "angebote@stromwerk-regenstauf.example", 1.05),
            ],
        ),
        (
            "Aufzüge",
            "Personenaufzüge barrierefrei, Wartungsvertrag",
            "draft",
            [
                ("Liftbau Bayerwald GmbH", "angebote@liftbau-bayerwald.example", 0.99),
                ("Aufzugstechnik Kelheim", "vergabe@aufzugstechnik-kelheim.example", 1.04),
            ],
        ),
        (
            "Außenanlagen",
            "Verkehrsflächen, Quartiersplatz, Spielplatz, Begrünung",
            "draft",
            [
                ("Gartenbau Naabtal GmbH", "angebote@gartenbau-naabtal.example", 0.98),
                ("Landschaftsbau Pfatter", "vergabe@landschaftsbau-pfatter.example", 1.05),
            ],
        ),
    ],
    schedule_activities=[
        ("Grundstückssicherung und Bedarfsplanung", "2026-11-01", "2026-12-31"),
        ("Vorentwurf und Entwurfsplanung (LP 2-3)", "2026-11-15", "2027-02-28"),
        ("Bauantrag und Baugenehmigung", "2027-02-01", "2027-06-30"),
        ("Ausführungsplanung (LP 5)", "2027-04-01", "2027-09-30"),
        ("Ausschreibung und Vergabe Generalunternehmer", "2027-07-01", "2027-10-31"),
        ("Vergabe TGA und Aufzüge", "2027-09-01", "2027-12-31"),
        ("Abbruch, Baugrube und Verbau", "2027-11-01", "2028-01-31"),
        ("Tiefgarage und Gründung", "2028-01-01", "2028-04-30"),
        ("Rohbau Haus 1 bis 4", "2028-04-01", "2028-11-30"),
        ("Fassade, Fenster und Dach", "2028-09-01", "2029-01-31"),
        ("TGA-Installation und Innenausbau", "2028-08-01", "2029-03-31"),
        ("Außenanlagen und Spielplatz", "2029-01-01", "2029-03-31"),
        ("Abnahmen, Mängelbeseitigung und Übergabe", "2029-03-01", "2029-04-30"),
    ],
)
