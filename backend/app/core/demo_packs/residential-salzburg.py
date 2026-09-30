# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner-pack demo: Residential building Salzburg-Lehen (Austria)
# Pack: austria-at  ·  OENORM B 1801 cost planning, OENORM B 2061 pricing
# ---------------------------------------------------------------------------
# Rates are Salzburg 2026 market estimates in EUR, net of USt. Salzburg
# construction costs are broadly comparable to Innsbruck, somewhat below
# Vienna levels for commercial work but residential costs are comparable
# due to high land prices and tight availability of skilled trades.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-salzburg",
    project_name="Wohnanlage Salzburg-Lehen, Strubergasse",
    project_description=(
        "Neubau einer Wohnanlage mit 54 Wohneinheiten auf 2 Baukoeperper, "
        "5 Obergeschosse + 1 Untergeschoss Tiefgarage mit 62 Stellplaetzen. "
        "BGF ca. 8.600 m2, davon ca. 7.200 m2 oberirdisch und ca. 1.400 m2 "
        "unterirdisch, auf einem Grundstueck von ca. 3.800 m2. "
        "Tragwerk: Stahlbetonbau mit Waenden und Stuetzen, Flachdecken, "
        "Gruendung auf Streifenfundamenten und Bodenplatte. "
        "Gebaeudehulle: Vollwaermeschutz WDVS EPS 200mm, "
        "Holz-Alu-Fenster Dreifach-Verglasung. "
        "Energiestandard klimaaktiv Silber, OIB-Richtlinie 6. "
        "Kostenberechnung gemaess OENORM B 1801, "
        "Baukosten ca. 14,8 Mio EUR netto. "
        "New-build residential complex of 54 apartments in 2 buildings, "
        "5 above-ground storeys + 1 basement level with 62 parking spaces. "
        "GFA approx. 8,600 m2. RC wall/column structure with flat slabs, "
        "ETICS facade, wood-aluminium triple-glazed windows. "
        "klimaaktiv Silver energy standard. OENORM B 1801 cost estimate, "
        "approx. EUR 14.8 million net."
    ),
    region="DACH",
    # The registry stores an Austrian or Swiss project under DIN 276, so every
    # line also carries the DIN 276 group its section falls in; without it the
    # Validate button failed every line for a cost group it never carried.
    classification_standard="onorm",
    currency="EUR",
    locale="de",
    address={
        "street": "Strubergasse 28",
        "city": "Salzburg",
        "postcode": "5020",
        "country": "Austria",
        "lat": 47.8110,
        "lng": 13.0340,
    },
    validation_rule_sets=["boq_quality"],
    boq_name="Kostenberechnung gemaess OENORM B 1801",
    boq_description=(
        "Kostenberechnung gemaess OENORM B 1801-1, "
        "Gliederung nach OENORM-Kostengruppen. "
        "Preisermittlung nach OENORM B 2061, "
        "Preisbasis Salzburg 2026."
    ),
    boq_metadata={
        "standard": "OENORM B 1801-1",
        "phase": "Entwurf / Kostenberechnung",
        "base_date": "2026-Q1",
        "price_level": "Salzburg 2026",
    },
    sections=[
        # ── Baustelleneinrichtung / Erdbau ─────────────────────────
        (
            "01",
            "01 - Baustelleneinrichtung, Erdbau",
            {"onorm": "01", "din276": "310"},
            [
                ("01.1", "Baustelleneinrichtung", "lsum", 1, 185000.00, {"onorm": "01", "din276": "310"}),
                ("01.2", "Aushub Baugrube Klasse 3-5", "m3", 18000, 14.00, {"onorm": "01", "din276": "310"}),
                ("01.3", "Bodenabtransport + Deponie", "m3", 16500, 20.00, {"onorm": "01", "din276": "310"}),
                ("01.4", "Boeschungssicherung Spritzbeton + Anker", "m2", 1200, 145.00, {"onorm": "01", "din276": "310"}),
                ("01.5", "Planum Baugrubensohle + Verdichtung", "m2", 1400, 4.80, {"onorm": "01", "din276": "310"}),
                ("01.6", "Baustrasse Schotter", "m2", 600, 24.00, {"onorm": "01", "din276": "310"}),
            ],
        ),
        # ── Gruendung ──────────────────────────────────────────────
        (
            "02",
            "02 - Gruendung",
            {"onorm": "02", "din276": "320"},
            [
                ("02.1", "Sauberkeitsschicht C12/15", "m2", 1400, 11.50, {"onorm": "02", "din276": "320"}),
                ("02.2", "Bodenplatte WU-Beton C25/30, d=40cm", "m3", 560, 185.00, {"onorm": "02", "din276": "320"}),
                ("02.3", "Bewehrung Bodenplatte BSt 550", "t", 68, 1420.00, {"onorm": "02", "din276": "320"}),
                ("02.4", "Streifenfundamente C25/30", "m3", 240, 175.00, {"onorm": "02", "din276": "320"}),
                ("02.5", "Fugenbaender + WU-Abdichtung", "m", 720, 32.00, {"onorm": "02", "din276": "320"}),
                ("02.6", "Drainage DN150", "m", 240, 52.00, {"onorm": "02", "din276": "320"}),
            ],
        ),
        # ── Rohbau Waende ──────────────────────────────────────────
        (
            "03",
            "03 - Rohbau, Waende und tragende Konstruktionen",
            {"onorm": "03", "din276": "330"},
            [
                ("03.1", "Kelleraussenwaende WU-Beton C25/30, d=30cm", "m3", 420, 205.00, {"onorm": "03", "din276": "330"}),
                ("03.2", "Schalung Kellerwaende Rahmenschalung", "m2", 2800, 32.00, {"onorm": "03", "din276": "330"}),
                ("03.3", "Bewehrung Kellerwaende BSt 550", "t", 52, 1420.00, {"onorm": "03", "din276": "330"}),
                ("03.4", "Ziegelmauerwerk Hochlochziegel d=25cm", "m2", 6800, 68.00, {"onorm": "03", "din276": "330"}),
                ("03.5", "Ziegelmauerwerk Schallschutz d=30cm", "m2", 2400, 82.00, {"onorm": "03", "din276": "330"}),
                ("03.6", "Stahlbetonwaende Treppenhaus/Aufzug C30/37", "m3", 420, 345.00, {"onorm": "03", "din276": "330"}),
                ("03.7", "Bewehrung Waende Treppenhaus BSt 550", "t", 56, 1420.00, {"onorm": "03", "din276": "330"}),
                ("03.8", "Perimeterdaemmung XPS 140mm erdberuehrt", "m2", 1400, 42.00, {"onorm": "03", "din276": "330"}),
                ("03.9", "Bauwerksabdichtung KMB erdberuehrt", "m2", 1400, 36.00, {"onorm": "03", "din276": "330"}),
            ],
        ),
        # ── Rohbau Decken ──────────────────────────────────────────
        (
            "04",
            "04 - Rohbau, Decken und Treppen",
            {"onorm": "04", "din276": "350"},
            [
                ("04.1", "Stahlbeton-Flachdecke C25/30, d=22cm", "m3", 1892, 275.00, {"onorm": "04", "din276": "350"}),
                ("04.2", "Schalung Decken Deckentische", "m2", 8600, 26.00, {"onorm": "04", "din276": "350"}),
                ("04.3", "Bewehrung Decken BSt 550", "t", 215, 1420.00, {"onorm": "04", "din276": "350"}),
                ("04.4", "Fertigteiltreppen Stahlbeton", "pcs", 20, 4200.00, {"onorm": "04", "din276": "350"}),
                ("04.5", "Treppengelaender Stahl pulverbeschichtet", "m", 300, 215.00, {"onorm": "04", "din276": "350"}),
            ],
        ),
        # ── Fassade ────────────────────────────────────────────────
        (
            "05",
            "05 - Fassade, Fenster, Sonnenschutz",
            {"onorm": "05", "din276": "330"},
            [
                ("05.1", "WDVS EPS 200mm Vollwaermeschutz", "m2", 4200, 62.00, {"onorm": "05", "din276": "330"}),
                ("05.2", "Aussenputz mineralisch 2-lagig", "m2", 4200, 38.00, {"onorm": "05", "din276": "330"}),
                ("05.3", "Holz-Alu-Fenster Dreifach-Verglasung Uw 0,9", "m2", 2800, 520.00, {"onorm": "05", "din276": "330"}),
                ("05.4", "Balkonfenstertueren Hebeschiebe", "pcs", 108, 2150.00, {"onorm": "05", "din276": "330"}),
                ("05.5", "Raffstore aussenliegend motorisiert", "pcs", 280, 385.00, {"onorm": "05", "din276": "330"}),
                ("05.6", "Haustueranlage Aluminium", "pcs", 2, 5800.00, {"onorm": "05", "din276": "330"}),
                ("05.7", "Sockelbereich Abdichtung + Verblendung", "m2", 360, 72.00, {"onorm": "05", "din276": "330"}),
                ("05.8", "Balkone Stahlbeton + thermische Trennung", "m2", 1080, 245.00, {"onorm": "05", "din276": "330"}),
                ("05.9", "Balkongelaender Stahl + Glas", "m", 720, 215.00, {"onorm": "05", "din276": "330"}),
            ],
        ),
        # ── Dach ───────────────────────────────────────────────────
        (
            "06",
            "06 - Dach",
            {"onorm": "06", "din276": "360"},
            [
                ("06.1", "Waermedaemmung PIR 200-260mm", "m2", 1500, 62.00, {"onorm": "06", "din276": "360"}),
                ("06.2", "Dachabdichtung FPO 2-lagig", "m2", 1500, 42.00, {"onorm": "06", "din276": "360"}),
                ("06.3", "Extensivbegrunung Substrat + Vegetation", "m2", 1000, 48.00, {"onorm": "06", "din276": "360"}),
                ("06.4", "Dachrandabschluss Attikaabdeckung", "m", 280, 52.00, {"onorm": "06", "din276": "360"}),
                ("06.5", "Lichtkuppeln / RWA Treppenhaeuser", "pcs", 2, 3800.00, {"onorm": "06", "din276": "360"}),
                ("06.6", "PV-Anlage Aufdach 80 kWp", "lsum", 1, 118000.00, {"onorm": "06", "din276": "360"}),
            ],
        ),
        # ── Innenausbau ───────────────────────────────────────────
        (
            "07",
            "07 - Innenausbau, Waende und Tueren",
            {"onorm": "07", "din276": "340"},
            [
                ("07.1", "Trennwaende Trockenbau CW75 doppelt beplankt", "m2", 4800, 48.00, {"onorm": "07", "din276": "340"}),
                ("07.2", "Brandwand EI90 Trockenbau", "m2", 720, 108.00, {"onorm": "07", "din276": "340"}),
                ("07.3", "Wohnungseingangstueren Sicherheitstueren", "pcs", 54, 1380.00, {"onorm": "07", "din276": "340"}),
                ("07.4", "Innentueren Holz / Stahlzargen", "pcs", 270, 520.00, {"onorm": "07", "din276": "340"}),
                ("07.5", "Brandschutztueren EI30", "pcs", 24, 1080.00, {"onorm": "07", "din276": "340"}),
            ],
        ),
        # ── Boeden, Decken, Wandbelaege ────────────────────────────
        (
            "08",
            "08 - Boeden, Decken, Wandbelaege",
            {"onorm": "08", "din276": "350"},
            [
                ("08.1", "Zementestrich CT-C25-F4 schwimmend", "m2", 7200, 22.00, {"onorm": "08", "din276": "350"}),
                ("08.2", "Trittschalldaemmung MW-T 30mm", "m2", 7200, 11.50, {"onorm": "08", "din276": "350"}),
                ("08.3", "Parkett Eiche gebuerstet versiegelt", "m2", 3800, 58.00, {"onorm": "08", "din276": "350"}),
                ("08.4", "Feinsteinzeug Baeder/Kuechen", "m2", 1800, 52.00, {"onorm": "08", "din276": "350"}),
                ("08.5", "Fliesen Treppenhaeuser", "m2", 800, 48.00, {"onorm": "08", "din276": "350"}),
                ("08.6", "Wandfliesen Baeder", "m2", 2400, 48.00, {"onorm": "08", "din276": "350"}),
                ("08.7", "Innenwandanstrich Dispersion 2x", "m2", 18000, 7.20, {"onorm": "08", "din276": "350"}),
                ("08.8", "Sockelleisten MDF lackiert", "m", 5400, 9.50, {"onorm": "08", "din276": "350"}),
            ],
        ),
        # ── Heizung, Lueftung, Sanitaer ────────────────────────────
        (
            "09",
            "09 - HKLS (Heizung, Kuehlung, Lueftung, Sanitaer)",
            {"onorm": "09", "din276": "420"},
            [
                ("09.1", "Luft-Wasser-Waermepumpe 140 kW Kaskade", "lsum", 1, 118000.00, {"onorm": "09", "din276": "420"}),
                ("09.2", "Pufferspeicher 2000 L", "pcs", 2, 5200.00, {"onorm": "09", "din276": "420"}),
                ("09.3", "Heizungsverteiler + Pumpengruppen", "lsum", 1, 42000.00, {"onorm": "09", "din276": "420"}),
                ("09.4", "Fussbodenheizung PE-Xa 20mm", "m2", 5800, 34.00, {"onorm": "09", "din276": "420"}),
                ("09.5", "Handtuchheizkoerper Baeder", "pcs", 72, 365.00, {"onorm": "09", "din276": "420"}),
                ("09.6", "Kontrollierte Wohnungslueftung WRG", "pcs", 54, 3800.00, {"onorm": "09", "din276": "420"}),
                ("09.7", "Tiefgaragenentlueftung CO-gesteuert", "lsum", 1, 52000.00, {"onorm": "09", "din276": "420"}),
                ("09.8", "Grundleitungen SML/PE DN100-DN150", "m", 720, 45.00, {"onorm": "09", "din276": "420"}),
                ("09.9", "Steigleitungen Schmutzwasser/Regenwasser", "m", 1080, 42.00, {"onorm": "09", "din276": "420"}),
                ("09.10", "Trinkwasserinstallation PE-Xc", "m", 3600, 32.00, {"onorm": "09", "din276": "420"}),
                ("09.11", "Sanitaerobjekte WC/Waschtisch/Badewanne", "pcs", 216, 950.00, {"onorm": "09", "din276": "420"}),
                ("09.12", "Kuechen-Wasseranschluss komplett", "pcs", 54, 520.00, {"onorm": "09", "din276": "420"}),
            ],
        ),
        # ── Elektro ───────────────────────────────────────────────
        (
            "10",
            "10 - Elektroanlagen",
            {"onorm": "10", "din276": "440"},
            [
                ("10.1", "Netzanschluss + Hauptverteiler", "lsum", 1, 52000.00, {"onorm": "10", "din276": "440"}),
                ("10.2", "Wohnungsverteiler Kleinverteiler", "pcs", 54, 1850.00, {"onorm": "10", "din276": "440"}),
                ("10.3", "Elektroinstallation Wohnungen pauschal", "m2", 5800, 32.00, {"onorm": "10", "din276": "440"}),
                ("10.4", "Beleuchtung Allgemeineflaechen LED", "m2", 1400, 38.00, {"onorm": "10", "din276": "440"}),
                ("10.5", "Sicherheitsbeleuchtung", "lsum", 1, 28000.00, {"onorm": "10", "din276": "440"}),
                ("10.6", "Blitzschutz + Erdung", "lsum", 1, 32000.00, {"onorm": "10", "din276": "440"}),
                ("10.7", "Sprechanlage + Videoklingel", "pcs", 54, 380.00, {"onorm": "10", "din276": "440"}),
                ("10.8", "E-Ladeinfrastruktur Tiefgarage 11 kW", "pcs", 12, 1850.00, {"onorm": "10", "din276": "440"}),
            ],
        ),
        # ── Foerderanlagen ────────────────────────────────────────
        (
            "11",
            "11 - Foerderanlagen",
            {"onorm": "11", "din276": "460"},
            [
                ("11.1", "Personenaufzug 630 kg / 8 Pers., 6 Haltestellen", "pcs", 2, 98000.00, {"onorm": "11", "din276": "460"}),
            ],
        ),
        # ── Aussenanlagen ─────────────────────────────────────────
        (
            "12",
            "12 - Aussenanlagen und Freiflaechen",
            {"onorm": "12", "din276": "500"},
            [
                ("12.1", "Erdarbeiten Aussenanlagen", "m3", 800, 16.50, {"onorm": "12", "din276": "500"}),
                ("12.2", "Tiefgaragenrampe Beton + Heizung", "m2", 120, 195.00, {"onorm": "12", "din276": "500"}),
                ("12.3", "Gehwege + Zufahrt Pflaster / Asphalt", "m2", 1100, 58.00, {"onorm": "12", "din276": "500"}),
                ("12.4", "Baumpflanzung + Strauchpflanzung", "pcs", 18, 1280.00, {"onorm": "12", "din276": "500"}),
                ("12.5", "Rasenflaechen + Staudenbeete", "m2", 1200, 22.00, {"onorm": "12", "din276": "500"}),
                ("12.6", "Aussenbeleuchtung Poller + Mastleuchten", "pcs", 16, 1080.00, {"onorm": "12", "din276": "500"}),
                ("12.7", "Fahrradabstellplaetze ueberdacht", "pcs", 60, 245.00, {"onorm": "12", "din276": "500"}),
                ("12.8", "Spielplatz Kinder", "lsum", 1, 28000.00, {"onorm": "12", "din276": "500"}),
                ("12.9", "Einfriedung + Tore", "m", 180, 118.00, {"onorm": "12", "din276": "500"}),
            ],
        ),
    ],
    markups=[
        ("Baustellengemeinkosten (BGK)", 7.5, "overhead", "direct_cost"),
        ("Geschaeftsgemeinkosten (GGK)", 6.0, "overhead", "direct_cost"),
        ("Bauwagnis (W)", 2.0, "contingency", "direct_cost"),
        ("Gewinn (G)", 3.5, "profit", "direct_cost"),
        ("Umsatzsteuer (USt)", 20.0, "tax", "cumulative"),
    ],
    total_months=22,
    tender_name="Rohbau",
    tender_companies=[
        ("Salzburger Wohnbau GmbH", "angebot@salzburger-wohnbau.example", 0.98),
        ("Tauernstein Bau GmbH & Co KG", "vergabe@tauernstein.example", 1.04),
        ("Flachgau Baugesellschaft mbH", "angebot@flachgau-bau.example", 1.01),
    ],
    project_metadata={
        "address": "Strubergasse 28, 5020 Salzburg",
        "client": "Salzland Wohnbautraeger GmbH",
        "main_contractor": "Salzburger Wohnbau GmbH",
        "architect": "Gastein + Hallenbach Architekten ZT, Salzburg",
        "structural_engineer": "Tragwerksplanung Lungau ZT GmbH",
        "mep_engineer": "Haustechnik Untersberg GmbH",
        "gfa_m2": 8600,
        "residential_units": 54,
        "bri_m3": 28700,
        "storeys_above": 5,
        "storeys_below": 1,
        "parking_spaces": 62,
        "structure_system": "Stahlbetonbau Waende/Stuetzen, Flachdecken, Streifenfundamente/Bodenplatte",
        "facade_system": "WDVS EPS 200mm, Holz-Alu-Fenster Dreifach-Verglasung Uw 0,9",
        "energy_standard": "klimaaktiv Silber, OIB-Richtlinie 6",
        "design_phase": "Entwurf / Kostenberechnung gemaess OENORM B 1801",
        "applicable_standards": [
            "OENORM B 1801-1 (Kosten im Hoch- und Tiefbau)",
            "OENORM B 2061 (Preisermittlung fuer Bauleistungen)",
            "OENORM A 2063 (Datenaustausch LV)",
            "OENORM B 2110 (Allgemeine Vertragsbestimmungen)",
            "OIB-Richtlinie 6 (Energieeinsparung und Waermeschutz)",
            "klimaaktiv Gebaeudebewertung",
            "Salzburger Raumordnungsgesetz (ROG)",
            "Salzburger Baupolizeigesetz (BauPolG)",
        ],
        "permit_authority": "Baubehoerde Stadt Salzburg (Magistrat, Baurechtsamt)",
        "cost_basis": "OENORM-Richtwerte 2025/26, Regionalfaktor Salzburg",
    },
    tender_packages=[
        (
            "Rohbau",
            "Erdarbeiten, Gruendung, Stahlbetonbau, Mauerwerk",
            "evaluating",
            [
                ("Salzburger Wohnbau GmbH", "angebot@salzburger-wohnbau.example", 0.98),
                ("Tauernstein Bau GmbH & Co KG", "vergabe@tauernstein.example", 1.04),
                ("Flachgau Baugesellschaft mbH", "angebot@flachgau-bau.example", 1.01),
            ],
        ),
        (
            "Fassade / Fenster",
            "WDVS, Putz, Holz-Alu-Fenster, Balkone, Sonnenschutz",
            "evaluating",
            [
                ("Fassadenbau Tennengau GmbH", "angebot@tennengau.example", 0.97),
                ("Fenster Pinzgau GmbH", "vergabe@fenster-pinzgau.example", 1.03),
            ],
        ),
        (
            "HKLS",
            "Waermepumpe, Fussbodenheizung, Wohnungslueftung, Sanitaer",
            "evaluating",
            [
                ("Haustechnik Untersberg GmbH", "angebot@untersberg-ht.example", 0.99),
                ("Gebaeudetechnik Pongau GmbH", "vergabe@pongau-gt.example", 1.05),
            ],
        ),
        (
            "Innenausbau",
            "Trockenbau, Estrich, Parkett, Fliesen, Tueren, Malerarbeiten",
            "draft",
            [
                ("Ausbau Salzland GmbH", "angebot@ausbau-salzland.example", 0.98),
                ("Maler + Boden Hallein GmbH", "vergabe@maler-hallein.example", 1.02),
            ],
        ),
    ],
)
