# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner-pack demo: Office building Vienna, Quartier Belvedere (Austria)
# Pack: austria-at  ·  OENORM B 1801 cost planning, OENORM B 2061 pricing
# ---------------------------------------------------------------------------
# An Austrian estimate follows the OENORM standards. OENORM B 1801-1 defines
# cost groups for building construction, OENORM B 2061 governs how unit prices
# are built up (K-Blatt), and OENORM A 2063 specifies the electronic exchange
# format for bills of quantities.
#
# Rates are Vienna 2026 market estimates in EUR, net of USt. Austrian
# construction costs are broadly comparable to southern German levels, somewhat
# lower than Munich and notably lower than Zurich.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="office-vienna",
    project_name="Buerogebaeude Quartier Belvedere, Wien Favoriten",
    project_description=(
        "Neubau eines Buero- und Geschaeftshauses im Quartier Belvedere, "
        "10. Bezirk Favoriten, Wien. 8 Obergeschosse + 2 Untergeschosse "
        "Tiefgarage mit 120 Stellplaetzen. BGF ca. 12.800 m2, BRI ca. "
        "51.200 m3, ca. 9.200 m2 Mietflaeche. Tragwerk: Stahlbeton-Skelettbau "
        "mit Flachdecken auf Stuetzenraster 8,10 x 8,10 m, Aussteifung ueber "
        "Treppen-/Aufzugskerne. Gebaeudehulle: Pfosten-Riegel-Fassade "
        "Aluminium/Glas mit aussenliegendem Sonnenschutz, Dreifach-Verglasung. "
        "Energiestandard klimaaktiv Gold, OIB-Richtlinie 6 (Energieeinsparung). "
        "Kostenberechnung gemaess OENORM B 1801, "
        "Baukosten ca. 38 Mio EUR netto. "
        "New-build office and commercial building in Quartier Belvedere, Vienna. "
        "8 above-ground and 2 basement levels with 120 parking spaces. "
        "GFA approx. 12,800 m2. RC frame with flat slabs, curtain-wall facade, "
        "klimaaktiv Gold energy standard. OENORM B 1801 cost estimate, "
        "approx. EUR 38 million net."
    ),
    region="DACH",
    # The registry stores an Austrian or Swiss project under DIN 276, so every
    # line also carries the DIN 276 group its section falls in; without it the
    # Validate button failed every line for a cost group it never carried.
    classification_standard="onorm",
    currency="EUR",
    locale="de",
    address={
        "street": "Arsenalstrasse 11",
        "city": "Vienna",
        "postcode": "1100",
        "country": "Austria",
        "lat": 48.1800,
        "lng": 16.3850,
    },
    validation_rule_sets=["boq_quality"],
    boq_name="Kostenberechnung gemaess OENORM B 1801",
    boq_description=(
        "Kostenberechnung gemaess OENORM B 1801-1, "
        "Gliederung nach OENORM-Kostengruppen. "
        "Preisermittlung nach OENORM B 2061, "
        "Preisbasis Wien 2026."
    ),
    boq_metadata={
        "standard": "OENORM B 1801-1",
        "phase": "Entwurf / Kostenberechnung",
        "base_date": "2026-Q1",
        "price_level": "Wien 2026",
    },
    sections=[
        # ── Baugrube / Erdbau ──────────────────────────────────────
        (
            "01",
            "01 - Baustellengemeinkosten, Baugrube, Erdbau",
            {"onorm": "01", "din276": "310"},
            [
                ("01.1", "Baustelleneinrichtung Grossbaustelle", "lsum", 1, 340000.00, {"onorm": "01", "din276": "310"}),
                ("01.2", "Spundwand Stahl Rammen + Ziehen", "m2", 3600, 195.00, {"onorm": "01", "din276": "310"}),
                ("01.3", "Rueckverankerung temporaer Litzenanker", "pcs", 180, 1280.00, {"onorm": "01", "din276": "310"}),
                ("01.4", "Aushub Baugrube Klasse 3-5", "m3", 64000, 14.50, {"onorm": "01", "din276": "310"}),
                ("01.5", "Bodenabtransport + Deponie", "m3", 60000, 22.00, {"onorm": "01", "din276": "310"}),
                ("01.6", "Grundwasserhaltung offene Wasserhaltung", "month", 14, 16000.00, {"onorm": "01", "din276": "310"}),
                ("01.7", "Planum Baugrubensohle + Verdichtung", "m2", 3200, 5.20, {"onorm": "01", "din276": "310"}),
                ("01.8", "Baustrasse Schottertragschicht", "m2", 1200, 28.00, {"onorm": "01", "din276": "310"}),
            ],
        ),
        # ── Gruendung ──────────────────────────────────────────────
        (
            "02",
            "02 - Gruendung",
            {"onorm": "02", "din276": "320"},
            [
                ("02.1", "Sauberkeitsschicht C12/15", "m2", 3200, 12.00, {"onorm": "02", "din276": "320"}),
                ("02.2", "Bodenplatte WU-Beton C30/37, d=80cm", "m3", 2560, 195.00, {"onorm": "02", "din276": "320"}),
                ("02.3", "Bewehrung Bodenplatte BSt 550", "t", 320, 1480.00, {"onorm": "02", "din276": "320"}),
                ("02.4", "Pfaehle Bohrpfaehle d=900mm, L=18m", "m", 3060, 165.00, {"onorm": "02", "din276": "320"}),
                ("02.5", "Fugenbaender + WU-Abdichtungskonzept", "m", 1600, 34.00, {"onorm": "02", "din276": "320"}),
                ("02.6", "Aufzugsunterfahrten / Pumpensumpf", "pcs", 4, 7500.00, {"onorm": "02", "din276": "320"}),
                ("02.7", "Drainage DN200", "m", 320, 62.00, {"onorm": "02", "din276": "320"}),
            ],
        ),
        # ── Rohbau Aussenwaende ────────────────────────────────────
        (
            "03",
            "03 - Rohbau, Aussenwaende und tragende Konstruktionen",
            {"onorm": "03", "din276": "330"},
            [
                ("03.1", "Kelleraussenwaende WU-Beton C30/37, d=40cm", "m3", 1040, 215.00, {"onorm": "03", "din276": "330"}),
                ("03.2", "Schalung Aussenwaende Rahmenschalung", "m2", 7200, 34.00, {"onorm": "03", "din276": "330"}),
                ("03.3", "Bewehrung Aussenwaende BSt 550", "t", 125, 1480.00, {"onorm": "03", "din276": "330"}),
                ("03.4", "Stahlbetonstuetzen C45/55", "m3", 420, 380.00, {"onorm": "03", "din276": "330"}),
                ("03.5", "Stahlbetonkerne C35/45 Treppen/Aufzug", "m3", 1080, 360.00, {"onorm": "03", "din276": "330"}),
                ("03.6", "Schalung Kerne Kletterschalung", "m2", 6200, 40.00, {"onorm": "03", "din276": "330"}),
                ("03.7", "Bewehrung Kerne BSt 550", "t", 148, 1480.00, {"onorm": "03", "din276": "330"}),
                ("03.8", "Perimeterdaemmung XPS 160mm erdberuehrt", "m2", 3400, 46.00, {"onorm": "03", "din276": "330"}),
                ("03.9", "Bauwerksabdichtung KMB erdberuehrt", "m2", 3400, 40.00, {"onorm": "03", "din276": "330"}),
            ],
        ),
        # ── Rohbau Decken ──────────────────────────────────────────
        (
            "04",
            "04 - Rohbau, Decken und Treppen",
            {"onorm": "04", "din276": "350"},
            [
                ("04.1", "Stahlbeton-Flachdecke C30/37, d=32cm", "m3", 4096, 295.00, {"onorm": "04", "din276": "350"}),
                ("04.2", "Schalung Decken Deckentische", "m2", 12800, 28.00, {"onorm": "04", "din276": "350"}),
                ("04.3", "Bewehrung Decken BSt 550", "t", 480, 1480.00, {"onorm": "04", "din276": "350"}),
                ("04.4", "Durchstanzbewehrung Stuetzenkoepfe", "pcs", 260, 285.00, {"onorm": "04", "din276": "350"}),
                ("04.5", "Fertigteiltreppen Stahlbeton", "pcs", 32, 4600.00, {"onorm": "04", "din276": "350"}),
                ("04.6", "Treppengelaender Edelstahl + Glas", "m", 480, 265.00, {"onorm": "04", "din276": "350"}),
            ],
        ),
        # ── Fassade ────────────────────────────────────────────────
        (
            "05",
            "05 - Fassade, Fenster, Sonnenschutz",
            {"onorm": "05", "din276": "330"},
            [
                (
                    "05.1",
                    "Pfosten-Riegel-Fassade Aluminium 3-fach-Verglasung Uw 0,9",
                    "m2",
                    6400,
                    620.00,
                    {"onorm": "05", "din276": "330"},
                ),
                ("05.2", "Festverglasung Brandschutz EI30 Foyer", "m2", 280, 420.00, {"onorm": "05", "din276": "330"}),
                ("05.3", "Oeffnungsfluegel / Kippfenster motorisiert", "pcs", 240, 1280.00, {"onorm": "05", "din276": "330"}),
                ("05.4", "Aussenliegender Sonnenschutz Raffstore", "m2", 5800, 145.00, {"onorm": "05", "din276": "330"}),
                ("05.5", "Aussentueren Aluminium Eingang automatisch", "pcs", 4, 6200.00, {"onorm": "05", "din276": "330"}),
                ("05.6", "Fassadenbefahranlage Anschlagpunkte", "lsum", 1, 32000.00, {"onorm": "05", "din276": "330"}),
            ],
        ),
        # ── Dach ───────────────────────────────────────────────────
        (
            "06",
            "06 - Dach",
            {"onorm": "06", "din276": "360"},
            [
                ("06.1", "Stahlbeton-Dachdecke C30/37, d=28cm", "m3", 448, 305.00, {"onorm": "06", "din276": "360"}),
                ("06.2", "Gefaelledaemmung PIR 220-300mm", "m2", 1700, 68.00, {"onorm": "06", "din276": "360"}),
                ("06.3", "Dachabdichtung FPO 2-lagig", "m2", 1700, 48.00, {"onorm": "06", "din276": "360"}),
                ("06.4", "Extensivbegrunung Substrat + Vegetation", "m2", 1100, 52.00, {"onorm": "06", "din276": "360"}),
                ("06.5", "Dachrandabschluss Attikaabdeckung Alu", "m", 380, 58.00, {"onorm": "06", "din276": "360"}),
                ("06.6", "Absturzsicherung Sekuranten", "m", 380, 125.00, {"onorm": "06", "din276": "360"}),
                ("06.7", "Lichtkuppeln / RWA Treppenhaeuser", "pcs", 4, 4200.00, {"onorm": "06", "din276": "360"}),
                ("06.8", "PV-Anlage Aufdach 150 kWp", "lsum", 1, 215000.00, {"onorm": "06", "din276": "360"}),
            ],
        ),
        # ── Innenausbau ───────────────────────────────────────────
        (
            "07",
            "07 - Innenausbau, Waende und Tueren",
            {"onorm": "07", "din276": "340"},
            [
                ("07.1", "Trennwand Trockenbau CW100 doppelt beplankt", "m2", 8400, 52.00, {"onorm": "07", "din276": "340"}),
                ("07.2", "Brandwand EI90 Trockenbau", "m2", 2200, 118.00, {"onorm": "07", "din276": "340"}),
                ("07.3", "Systemtrennwand verglast Buero", "m2", 2800, 248.00, {"onorm": "07", "din276": "340"}),
                ("07.4", "Schachtwandverkleidung F90", "m2", 1600, 78.00, {"onorm": "07", "din276": "340"}),
                ("07.5", "Innentueren Holz / Stahlzargen", "pcs", 380, 620.00, {"onorm": "07", "din276": "340"}),
                ("07.6", "Brandschutztueren EI30/EI90", "pcs", 84, 1250.00, {"onorm": "07", "din276": "340"}),
                ("07.7", "WC-Trennwandanlagen HPL", "pcs", 56, 850.00, {"onorm": "07", "din276": "340"}),
            ],
        ),
        # ── Boeden, Decken, Wandbelaege ────────────────────────────
        (
            "08",
            "08 - Boeden, Decken, Wandbelaege",
            {"onorm": "08", "din276": "350"},
            [
                ("08.1", "Hohlraumboden / Doppelboden Bueroflaechen", "m2", 7800, 68.00, {"onorm": "08", "din276": "350"}),
                ("08.2", "Zementestrich CT-C25-F4 Nebenflaechen", "m2", 2800, 24.00, {"onorm": "08", "din276": "350"}),
                ("08.3", "Trittschalldaemmung MW-T 30mm", "m2", 9600, 12.50, {"onorm": "08", "din276": "350"}),
                ("08.4", "Bodenbelag Teppichfliese Buero", "m2", 6800, 36.00, {"onorm": "08", "din276": "350"}),
                ("08.5", "Bodenbelag Naturstein Eingangsfoyer", "m2", 580, 158.00, {"onorm": "08", "din276": "350"}),
                ("08.6", "Bodenbelag Feinsteinzeug Nebenflaechen", "m2", 2200, 58.00, {"onorm": "08", "din276": "350"}),
                ("08.7", "Akustik-Metalldecke Kassetten abgehaengt", "m2", 8000, 76.00, {"onorm": "08", "din276": "350"}),
                ("08.8", "Gipskarton-Unterdecke EI30/EI90", "m2", 3200, 45.00, {"onorm": "08", "din276": "350"}),
                ("08.9", "Wandbeschichtung Dispersion innen", "m2", 19200, 8.20, {"onorm": "08", "din276": "350"}),
                ("08.10", "Wandfliesen Sanitaerbereiche", "m2", 1900, 52.00, {"onorm": "08", "din276": "350"}),
                ("08.11", "Sockelleisten Aluminium", "m", 5600, 9.80, {"onorm": "08", "din276": "350"}),
            ],
        ),
        # ── Heizung, Lueftung, Sanitaer ────────────────────────────
        (
            "09",
            "09 - HKLS (Heizung, Kuehlung, Lueftung, Sanitaer)",
            {"onorm": "09", "din276": "420"},
            [
                ("09.1", "Fernwaermeanschluss Wien Energie 800 kW", "lsum", 1, 82000.00, {"onorm": "09", "din276": "420"}),
                ("09.2", "Luft-Wasser-Waermepumpe 200 kW Kaskade", "lsum", 1, 165000.00, {"onorm": "09", "din276": "420"}),
                ("09.3", "Pufferspeicher 2000 L", "pcs", 2, 5800.00, {"onorm": "09", "din276": "420"}),
                ("09.4", "Heizungsverteiler + Pumpengruppen", "lsum", 1, 68000.00, {"onorm": "09", "din276": "420"}),
                ("09.5", "Betonkernaktivierung BKT", "m2", 7800, 34.00, {"onorm": "09", "din276": "420"}),
                ("09.6", "Statische Heizflaechen / Konvektoren", "pcs", 160, 365.00, {"onorm": "09", "din276": "420"}),
                ("09.7", "RLT-Zentralgeraet mit WRG 52.000 m3/h", "pcs", 3, 82000.00, {"onorm": "09", "din276": "420"}),
                ("09.8", "Luftkanaele verzinkt Hauptverteilung", "m2", 8000, 68.00, {"onorm": "09", "din276": "420"}),
                ("09.9", "Volumenstromregler VVS", "pcs", 360, 420.00, {"onorm": "09", "din276": "420"}),
                ("09.10", "Brandschutzklappen EI90", "pcs", 280, 248.00, {"onorm": "09", "din276": "420"}),
                ("09.11", "Grundleitungen SML/PE DN100-DN200", "m", 1400, 48.00, {"onorm": "09", "din276": "420"}),
                ("09.12", "Trinkwasserinstallation PE-Xc/Edelstahl", "m", 4200, 36.00, {"onorm": "09", "din276": "420"}),
                ("09.13", "Sanitaerobjekte WC/Waschtisch komplett", "pcs", 200, 1080.00, {"onorm": "09", "din276": "420"}),
                ("09.14", "Tiefgaragenentlueftung CO-gesteuert", "lsum", 1, 82000.00, {"onorm": "09", "din276": "420"}),
            ],
        ),
        # ── Elektro ───────────────────────────────────────────────
        (
            "10",
            "10 - Elektroanlagen",
            {"onorm": "10", "din276": "440"},
            [
                ("10.1", "Mittelspannungsuebergabe + Trafostation 2x800 kVA", "lsum", 1, 248000.00, {"onorm": "10", "din276": "440"}),
                ("10.2", "Niederspannungshauptverteilung NSHV", "pcs", 2, 42000.00, {"onorm": "10", "din276": "440"}),
                ("10.3", "Unterverteilungen je Geschoss", "pcs", 20, 5200.00, {"onorm": "10", "din276": "440"}),
                ("10.4", "Netzersatzanlage Diesel-NEA 350 kVA", "pcs", 1, 128000.00, {"onorm": "10", "din276": "440"}),
                ("10.5", "USV-Anlage", "pcs", 2, 34000.00, {"onorm": "10", "din276": "440"}),
                ("10.6", "Kabeltrassen + Verteilung", "m", 5800, 34.00, {"onorm": "10", "din276": "440"}),
                ("10.7", "Installationsleitungen / Verdrahtung", "m", 84000, 3.60, {"onorm": "10", "din276": "440"}),
                ("10.8", "Allgemeinbeleuchtung LED DALI", "m2", 9600, 48.00, {"onorm": "10", "din276": "440"}),
                ("10.9", "Sicherheitsbeleuchtung Zentralbatterie", "lsum", 1, 76000.00, {"onorm": "10", "din276": "440"}),
                ("10.10", "Blitzschutz + Erdung", "lsum", 1, 78000.00, {"onorm": "10", "din276": "440"}),
            ],
        ),
        # ── Kommunikation / Sicherheit ────────────────────────────
        (
            "11",
            "11 - Kommunikations- und Sicherheitsanlagen",
            {"onorm": "11", "din276": "450"},
            [
                ("11.1", "Strukturierte Verkabelung Cat.7 / LWL", "m2", 9600, 28.00, {"onorm": "11", "din276": "450"}),
                ("11.2", "Brandmeldeanlage TRVB 123 S", "m2", 12800, 12.50, {"onorm": "11", "din276": "450"}),
                ("11.3", "Zutrittskontrolle + Schliessanlage", "pcs", 160, 580.00, {"onorm": "11", "din276": "450"}),
                ("11.4", "Videoueberwachung", "pcs", 84, 850.00, {"onorm": "11", "din276": "450"}),
                ("11.5", "Einbruchmeldeanlage", "lsum", 1, 36000.00, {"onorm": "11", "din276": "450"}),
            ],
        ),
        # ── Foerderanlagen ────────────────────────────────────────
        (
            "12",
            "12 - Foerderanlagen",
            {"onorm": "12", "din276": "460"},
            [
                ("12.1", "Personenaufzug 1600 kg / 21 Pers., 10 Haltestellen", "pcs", 4, 148000.00, {"onorm": "12", "din276": "460"}),
                ("12.2", "Lasten-/Feuerwehraufzug 2000 kg", "pcs", 1, 195000.00, {"onorm": "12", "din276": "460"}),
            ],
        ),
        # ── Gebaeudeautomation ────────────────────────────────────
        (
            "13",
            "13 - Gebaeudeautomation (MSR)",
            {"onorm": "13", "din276": "480"},
            [
                ("13.1", "GLT Managementebene + Server", "lsum", 1, 145000.00, {"onorm": "13", "din276": "480"}),
                ("13.2", "DDC-Automationsstationen", "pcs", 42, 3600.00, {"onorm": "13", "din276": "480"}),
                ("13.3", "Feldgeraete / Sensorik / Aktorik", "lsum", 1, 245000.00, {"onorm": "13", "din276": "480"}),
                ("13.4", "Raumautomation Buero KNX", "m2", 8600, 18.50, {"onorm": "13", "din276": "480"}),
                ("13.5", "Inbetriebnahme + GA-Funktionspruefung", "lsum", 1, 76000.00, {"onorm": "13", "din276": "480"}),
            ],
        ),
        # ── Aussenanlagen ─────────────────────────────────────────
        (
            "14",
            "14 - Aussenanlagen und Freiflaechen",
            {"onorm": "14", "din276": "500"},
            [
                ("14.1", "Erdarbeiten Aussenanlagen / Oberboden", "m3", 1800, 18.50, {"onorm": "14", "din276": "500"}),
                ("14.2", "Tiefgaragenrampe Beton + Heizung", "m2", 200, 215.00, {"onorm": "14", "din276": "500"}),
                ("14.3", "Verkehrsflaechen Asphalt + Pflaster", "m2", 2200, 68.00, {"onorm": "14", "din276": "500"}),
                ("14.4", "Naturstein Vorplatz", "m2", 1000, 138.00, {"onorm": "14", "din276": "500"}),
                ("14.5", "Baumpflanzung + Pflanzbeete", "pcs", 36, 1580.00, {"onorm": "14", "din276": "500"}),
                ("14.6", "Aussenbeleuchtung Mastleuchten + Poller", "pcs", 32, 1250.00, {"onorm": "14", "din276": "500"}),
                ("14.7", "Fahrradabstellplaetze ueberdacht", "pcs", 100, 280.00, {"onorm": "14", "din276": "500"}),
                ("14.8", "Versorgungsanschluesse Strom/Wasser/Fernwaerme", "lsum", 1, 142000.00, {"onorm": "14", "din276": "500"}),
            ],
        ),
    ],
    markups=[
        ("Baustellengemeinkosten (BGK)", 8.0, "overhead", "direct_cost"),
        ("Geschaeftsgemeinkosten (GGK)", 6.5, "overhead", "direct_cost"),
        ("Bauwagnis (W)", 2.0, "contingency", "direct_cost"),
        ("Gewinn (G)", 3.5, "profit", "direct_cost"),
        ("Umsatzsteuer (USt)", 20.0, "tax", "cumulative"),
    ],
    total_months=28,
    tender_name="Rohbau",
    tender_companies=[
        ("Berghammer Bau GmbH, Wien", "angebot@berghammer.example", 0.98),
        ("Waidhofen + Thalberg Bau GmbH & Co KG", "vergabe@waidhofen-thalberg.example", 1.03),
        ("Sternfeld Baugesellschaft mbH", "angebot@sternfeld.example", 1.01),
    ],
    project_metadata={
        "address": "Arsenalstrasse 11, 1100 Wien",
        "client": "Quartier Belvedere Immobilien AG",
        "main_contractor": "Berghammer Bau GmbH, Wien",
        "architect": "Koernbach + Leithner Architekten ZT, Wien",
        "structural_engineer": "Thalveld Tragwerksplanung ZT GmbH",
        "mep_engineer": "Weidmann Gebaeudetechnik GmbH",
        "gfa_m2": 12800,
        "rentable_area_m2": 9200,
        "bri_m3": 51200,
        "storeys_above": 8,
        "storeys_below": 2,
        "parking_spaces": 120,
        "structure_system": "Stahlbeton-Skelettbau / RC frame, flat slabs, core-braced",
        "facade_system": "Pfosten-Riegel-Fassade Alu/Glas, Dreifach-Verglasung Uw 0,9",
        "grid_m": "8.10 x 8.10",
        "energy_standard": "klimaaktiv Gold, OIB-Richtlinie 6",
        "design_phase": "Entwurf / Kostenberechnung gemaess OENORM B 1801",
        "applicable_standards": [
            "OENORM B 1801-1 (Kosten im Hoch- und Tiefbau)",
            "OENORM B 2061 (Preisermittlung fuer Bauleistungen)",
            "OENORM A 2063 (Datenaustausch LV)",
            "OENORM B 2110 (Allgemeine Vertragsbestimmungen)",
            "OIB-Richtlinie 6 (Energieeinsparung und Waermeschutz)",
            "klimaaktiv Gebaeudebewertung",
            "Wiener Bauordnung (WBO 2023)",
        ],
        "permit_authority": "MA 37 Baupolizei, Stadt Wien",
        "cost_basis": "OENORM-Richtwerte 2025/26, Regionalfaktor Wien",
    },
    tender_packages=[
        (
            "Rohbau",
            "Baugrube, Gruendung, Stahlbeton-Skelettbau, Kerne, Decken",
            "evaluating",
            [
                ("Berghammer Bau GmbH, Wien", "angebot@berghammer.example", 0.98),
                ("Waidhofen + Thalberg Bau GmbH & Co KG", "vergabe@waidhofen-thalberg.example", 1.03),
                ("Sternfeld Baugesellschaft mbH", "angebot@sternfeld.example", 1.01),
            ],
        ),
        (
            "Fassade",
            "Pfosten-Riegel-Fassade, Sonnenschutz, Dachabdichtung",
            "evaluating",
            [
                ("Glasfassaden Leitwald GmbH", "angebot@leitwald.example", 0.97),
                ("Fassadenbau Greinburg GmbH", "vergabe@greinburg.example", 1.04),
            ],
        ),
        (
            "HKLS",
            "Fernwaerme, Waermepumpe, BKT, Lueftung, Sanitaer",
            "evaluating",
            [
                ("Haustechnik Rosenfeld GmbH", "angebot@rosenfeld.example", 0.99),
                ("Gebaeudeklimatik Tauernfeld GmbH & Co KG", "vergabe@tauernfeld.example", 1.05),
            ],
        ),
        (
            "Elektro / MSR",
            "Trafo, NS-Verteilung, Beleuchtung, Sicherheitstechnik, GLT",
            "evaluating",
            [
                ("Elektrotechnik Hallstatt GmbH", "angebot@hallstatt-et.example", 0.98),
                ("Thalberg Elektro + Automation", "vergabe@thalberg-ea.example", 1.02),
            ],
        ),
        (
            "Innenausbau",
            "Trockenbau, Doppelboden, Akustikdecken, Bodenbelaege, Tueren",
            "draft",
            [
                ("Ausbau Dornbirn GmbH", "angebot@ausbau-dornbirn.example", 0.97),
                ("Graufeld Raumgestaltung GmbH", "vergabe@graufeld.example", 1.03),
            ],
        ),
        (
            "Aussenanlagen",
            "Erdbau, Verkehrsflaechen, Begrunung, Aussenleuchten, Anschluesse",
            "draft",
            [
                ("GaLaBau Wienerwold GmbH", "angebot@wienerwold.example", 0.99),
                ("Gruenraum Marchfeld GmbH", "vergabe@gruenraum-marchfeld.example", 1.04),
            ],
        ),
    ],
)
