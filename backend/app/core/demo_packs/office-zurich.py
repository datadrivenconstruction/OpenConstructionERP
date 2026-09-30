# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner-pack demo: Office building Zurich-West (Switzerland)
# Pack: switzerland-ch  ·  BKP Baukostenplan, SIA 451 cost planning
# ---------------------------------------------------------------------------
# A Swiss estimate is structured by the BKP (Baukostenplan), the CRB
# classification that organises construction costs into main groups 0
# through 9 and three-digit subgroups. SIA 451 defines how these cost
# groups are used across SIA 112 project phases.
#
# Rates are Zurich 2026 market estimates in CHF, net of MWST. Swiss
# construction costs are notably higher than the DACH neighbours
# because of wage levels, material logistics and the regulatory
# environment. A Zurich office building at CHF 5,500-7,000 per m2 BGF
# for KG 2+3+4 is within the normal corridor.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="office-zurich",
    project_name="Buerogebaeude Zurich-West, Pfingstweidstrasse",
    project_description=(
        "Neubau eines Buero- und Dienstleistungsgebaeudes im Entwicklungsgebiet "
        "Zurich-West. 7 Obergeschosse + 2 Untergeschosse Tiefgarage mit 95 "
        "Stellplaetzen. BGF ca. 11.200 m2, GV ca. 44.800 m3, ca. 7.800 m2 "
        "Mietflaeche. Tragwerk: Stahlbeton-Skelettbau mit Flachdecken auf "
        "Stuetzenraster 7,80 x 7,80 m, Aussteifung ueber Kerne. "
        "Fassade: Elementfassade Aluminium/Glas, Dreifach-Isolierverglasung, "
        "aussenliegender Sonnenschutz. Energiestandard Minergie-P, "
        "Zertifizierung SNBS Standard Gold angestrebt. "
        "Kostenvoranschlag SIA 451, Phase 32 Bauprojekt, "
        "Baukosten BKP 2+3+4 ca. CHF 52 Mio. "
        "New-build office and commercial building in the Zurich-West development "
        "area. 7 above-ground and 2 basement levels with 95 parking spaces. "
        "GFA approx. 11,200 m2. RC frame with flat slabs, unitised aluminium/glass "
        "facade, Minergie-P energy standard. SIA 451 cost estimate, phase 32, "
        "approx. CHF 52 million construction cost."
    ),
    region="DACH",
    # The registry stores an Austrian or Swiss project under DIN 276, so every
    # line also carries the DIN 276 group its section falls in; without it the
    # Validate button failed every line for a cost group it never carried.
    classification_standard="bkp",
    currency="CHF",
    locale="de",
    address={
        "street": "Pfingstweidstrasse 60",
        "city": "Zurich",
        "postcode": "8005",
        "country": "Switzerland",
        "lat": 47.3908,
        "lng": 8.5095,
    },
    validation_rule_sets=["boq_quality"],
    boq_name="Kostenvoranschlag BKP (SIA 451, Phase 32 Bauprojekt)",
    boq_description=(
        "Kostenvoranschlag gemaess SIA 451, BKP-Gliederung, "
        "Phase 32 Bauprojekt. Schwerpunkt BKP 2 Gebaeudekosten und "
        "BKP 3 Betriebseinrichtungen. Preisbasis Zurich 2026."
    ),
    boq_metadata={
        "standard": "BKP (CRB) / SIA 451",
        "phase": "SIA 112 Phase 32, Bauprojekt",
        "base_date": "2026-Q1",
        "price_level": "Zurich 2026",
    },
    sections=[
        # ── BKP 211 Baugrubenabschluesse ────────────────────────────
        (
            "211",
            "BKP 211 - Baugrubenabschluesse",
            {"bkp": "211", "din276": "330"},
            [
                ("211.1", "Spundwand Stahl, Profil HZ 680M, Rammen + Ziehen", "m2", 3200, 285.00, {"bkp": "211", "din276": "330"}),
                ("211.2", "Rueckverankerung temporaer Litzenanker", "pcs", 160, 1680.00, {"bkp": "211", "din276": "330"}),
                ("211.3", "Jet-Grouting Sohlabdichtung", "m", 4800, 185.00, {"bkp": "211", "din276": "330"}),
                (
                    "211.4",
                    "Baugrubenueberwachung Inklinometer + Setzungsmessungen",
                    "month",
                    14,
                    8500.00,
                    {"bkp": "211", "din276": "330"},
                ),
            ],
        ),
        # ── BKP 212 Aushub ─────────────────────────────────────────
        (
            "212",
            "BKP 212 - Aushub, Erdbewegungen",
            {"bkp": "212", "din276": "330"},
            [
                ("212.1", "Aushub Baugrube, Boden Klasse 3-5", "m3", 52000, 28.00, {"bkp": "212", "din276": "330"}),
                ("212.2", "Abtransport + Entsorgung belasteter Boden Klasse U", "m3", 8400, 68.00, {"bkp": "212", "din276": "330"}),
                ("212.3", "Grundwasserhaltung offene Wasserhaltung", "month", 12, 22000.00, {"bkp": "212", "din276": "330"}),
                ("212.4", "Planum Baugrubensohle + Verdichtung", "m2", 2800, 8.50, {"bkp": "212", "din276": "330"}),
                ("212.5", "Baustrasse Kieskoffer", "m2", 1100, 42.00, {"bkp": "212", "din276": "330"}),
            ],
        ),
        # ── BKP 213 Fundation ──────────────────────────────────────
        (
            "213",
            "BKP 213 - Fundation, Gruendung",
            {"bkp": "213", "din276": "330"},
            [
                ("213.1", "Sauberkeitsschicht C12/15", "m2", 2800, 18.50, {"bkp": "213", "din276": "330"}),
                ("213.2", "Bodenplatte WU-Beton C30/37, d=80cm", "m3", 2240, 285.00, {"bkp": "213", "din276": "330"}),
                ("213.3", "Bewehrung Bodenplatte BSt 500", "t", 280, 2150.00, {"bkp": "213", "din276": "330"}),
                ("213.4", "Pfaehle Bohrpfaehle d=900mm, L=16m", "m", 2880, 245.00, {"bkp": "213", "din276": "330"}),
                ("213.5", "Fugenbaender + WU-Abdichtungskonzept", "m", 1400, 52.00, {"bkp": "213", "din276": "330"}),
                ("213.6", "Aufzugsunterfahrten / Pumpensumpf", "pcs", 3, 12000.00, {"bkp": "213", "din276": "330"}),
            ],
        ),
        # ── BKP 214 Rohbau 1 (Aussenwaende, Stuetzen) ─────────────
        (
            "214",
            "BKP 214 - Rohbau 1, Aussenwaende und tragende Bauteile",
            {"bkp": "214", "din276": "330"},
            [
                ("214.1", "Kelleraussenwaende WU-Beton C30/37, d=40cm", "m3", 920, 320.00, {"bkp": "214", "din276": "330"}),
                ("214.2", "Schalung Aussenwaende Grossflaechenschalung", "m2", 6400, 48.00, {"bkp": "214", "din276": "330"}),
                ("214.3", "Bewehrung Aussenwaende BSt 500", "t", 112, 2150.00, {"bkp": "214", "din276": "330"}),
                ("214.4", "Stahlbetonstuetzen C45/55, Rundstuetzen d=45cm", "m3", 340, 520.00, {"bkp": "214", "din276": "330"}),
                ("214.5", "Stahlbetonkerne C35/45 Treppen-/Aufzugskerne", "m3", 960, 485.00, {"bkp": "214", "din276": "330"}),
                ("214.6", "Schalung Kerne Kletterschalung", "m2", 5600, 56.00, {"bkp": "214", "din276": "330"}),
                ("214.7", "Bewehrung Kerne BSt 500", "t", 130, 2150.00, {"bkp": "214", "din276": "330"}),
                ("214.8", "Perimeterdaemmung XPS 200mm erdberuehrt", "m2", 2900, 68.00, {"bkp": "214", "din276": "330"}),
                ("214.9", "Bauwerksabdichtung KMB erdberuehrt", "m2", 2900, 58.00, {"bkp": "214", "din276": "330"}),
            ],
        ),
        # ── BKP 215 Rohbau 2 (Decken, Treppen) ────────────────────
        (
            "215",
            "BKP 215 - Rohbau 2, Decken und Treppen",
            {"bkp": "215", "din276": "330"},
            [
                ("215.1", "Stahlbeton-Flachdecke C30/37, d=30cm", "m3", 3360, 420.00, {"bkp": "215", "din276": "330"}),
                ("215.2", "Schalung Decken Deckentische", "m2", 11200, 42.00, {"bkp": "215", "din276": "330"}),
                ("215.3", "Bewehrung Decken BSt 500", "t", 395, 2150.00, {"bkp": "215", "din276": "330"}),
                ("215.4", "Durchstanzbewehrung Stuetzenkoepfe", "pcs", 210, 420.00, {"bkp": "215", "din276": "330"}),
                ("215.5", "Fertigteiltreppen Stahlbeton", "pcs", 28, 6800.00, {"bkp": "215", "din276": "330"}),
                ("215.6", "Treppengelaender Edelstahl + Glas", "m", 420, 385.00, {"bkp": "215", "din276": "330"}),
            ],
        ),
        # ── BKP 221 Fenster, Aussentueren ─────────────────────────
        (
            "221",
            "BKP 221 - Fenster, Aussentueren, Fassade",
            {"bkp": "221", "din276": "330"},
            [
                ("221.1", "Elementfassade Aluminium 3-fach-Verglasung Uw 0,85", "m2", 5600, 920.00, {"bkp": "221", "din276": "330"}),
                ("221.2", "Pfosten-Riegel-Fassade Eingangsbereich", "m2", 480, 780.00, {"bkp": "221", "din276": "330"}),
                ("221.3", "Oeffnungsfluegel / Kippfenster motorisiert", "pcs", 210, 1850.00, {"bkp": "221", "din276": "330"}),
                ("221.4", "Aussenliegender Sonnenschutz Raffstore", "m2", 5200, 215.00, {"bkp": "221", "din276": "330"}),
                ("221.5", "Festverglasung Brandschutz EI30 Atrium", "m2", 240, 620.00, {"bkp": "221", "din276": "330"}),
                ("221.6", "Aussentueren Aluminium Eingang automatisch", "pcs", 4, 9500.00, {"bkp": "221", "din276": "330"}),
            ],
        ),
        # ── BKP 224 Dach ───────────────────────────────────────────
        (
            "224",
            "BKP 224 - Dach",
            {"bkp": "224", "din276": "330"},
            [
                ("224.1", "Gefaelledaemmung PIR 240-320mm", "m2", 1600, 98.00, {"bkp": "224", "din276": "330"}),
                ("224.2", "Dachabdichtung FPO 2-lagig", "m2", 1600, 72.00, {"bkp": "224", "din276": "330"}),
                ("224.3", "Extensivbegrunung Substrat + Vegetation", "m2", 1200, 78.00, {"bkp": "224", "din276": "330"}),
                ("224.4", "Dachrandabschluss Attikaabdeckung Aluminium", "m", 320, 88.00, {"bkp": "224", "din276": "330"}),
                ("224.5", "Absturzsicherung Sekuranten", "m", 320, 185.00, {"bkp": "224", "din276": "330"}),
                ("224.6", "Lichtkuppeln / RWA Treppenhaeuser", "pcs", 4, 6200.00, {"bkp": "224", "din276": "330"}),
                ("224.7", "PV-Anlage Aufdach 160 kWp", "lsum", 1, 320000.00, {"bkp": "224", "din276": "330"}),
            ],
        ),
        # ── BKP 225 Ausbau 1 (Innenwaende, Tueren) ────────────────
        (
            "225",
            "BKP 225 - Ausbau 1, Innenwaende und Tueren",
            {"bkp": "225", "din276": "330"},
            [
                ("225.1", "Trennwand Trockenbau CW100 doppelt beplankt", "m2", 7200, 78.00, {"bkp": "225", "din276": "330"}),
                ("225.2", "Brandwand EI90 Trockenbau", "m2", 1800, 175.00, {"bkp": "225", "din276": "330"}),
                ("225.3", "Systemtrennwand verglast Buero", "m2", 2400, 380.00, {"bkp": "225", "din276": "330"}),
                ("225.4", "Innentueren Holz / Stahlzargen", "pcs", 320, 920.00, {"bkp": "225", "din276": "330"}),
                ("225.5", "Brandschutztueren EI30/EI90", "pcs", 72, 1850.00, {"bkp": "225", "din276": "330"}),
                ("225.6", "WC-Trennwandanlagen HPL", "pcs", 48, 1280.00, {"bkp": "225", "din276": "330"}),
            ],
        ),
        # ── BKP 226 Ausbau 2 (Boeden, Decken, Waende) ─────────────
        (
            "226",
            "BKP 226 - Ausbau 2, Boeden, Decken, Wandbelaege",
            {"bkp": "226", "din276": "330"},
            [
                ("226.1", "Hohlraumboden / Doppelboden Bueroflaechen", "m2", 6800, 105.00, {"bkp": "226", "din276": "330"}),
                ("226.2", "Zementestrich CT-C25-F4 Nebenflaechen", "m2", 2400, 38.00, {"bkp": "226", "din276": "330"}),
                ("226.3", "Trittschalldaemmung MW-T 30mm", "m2", 8400, 19.50, {"bkp": "226", "din276": "330"}),
                ("226.4", "Bodenbelag Teppichfliese Buero", "m2", 5800, 56.00, {"bkp": "226", "din276": "330"}),
                ("226.5", "Bodenbelag Naturstein Eingangshalle", "m2", 520, 245.00, {"bkp": "226", "din276": "330"}),
                ("226.6", "Bodenbelag Feinsteinzeug Nebenflaechen", "m2", 1800, 88.00, {"bkp": "226", "din276": "330"}),
                ("226.7", "Akustik-Metalldecke Kassetten abgehaengt", "m2", 7000, 115.00, {"bkp": "226", "din276": "330"}),
                ("226.8", "Gipskarton-Unterdecke EI30/EI90", "m2", 2800, 68.00, {"bkp": "226", "din276": "330"}),
                ("226.9", "Wandbeschichtung Dispersion innen", "m2", 16800, 12.50, {"bkp": "226", "din276": "330"}),
                ("226.10", "Wandfliesen Sanitaerbereiche", "m2", 1600, 82.00, {"bkp": "226", "din276": "330"}),
            ],
        ),
        # ── BKP 230 Elektroanlagen ─────────────────────────────────
        (
            "230",
            "BKP 230 - Elektroanlagen",
            {"bkp": "230", "din276": "440"},
            [
                ("230.1", "Trafostation Oel-/Giessharztransformator 2x630 kVA", "lsum", 1, 245000.00, {"bkp": "230", "din276": "440"}),
                ("230.2", "Niederspannungshauptverteilung NSHV", "pcs", 2, 58000.00, {"bkp": "230", "din276": "440"}),
                ("230.3", "Unterverteilungen je Geschoss", "pcs", 18, 7800.00, {"bkp": "230", "din276": "440"}),
                ("230.4", "Netzersatzanlage Diesel 350 kVA", "pcs", 1, 185000.00, {"bkp": "230", "din276": "440"}),
                ("230.5", "USV-Anlage", "pcs", 2, 48000.00, {"bkp": "230", "din276": "440"}),
                ("230.6", "Kabeltrassen + Installationsverteilung", "m", 5200, 48.00, {"bkp": "230", "din276": "440"}),
                ("230.7", "Installationsleitungen / Verdrahtung", "m", 72000, 5.80, {"bkp": "230", "din276": "440"}),
                ("230.8", "Allgemeinbeleuchtung LED DALI", "m2", 8400, 75.00, {"bkp": "230", "din276": "440"}),
                ("230.9", "Sicherheitsbeleuchtung Zentralbatterie", "lsum", 1, 115000.00, {"bkp": "230", "din276": "440"}),
                ("230.10", "Blitzschutz + Erdung", "lsum", 1, 118000.00, {"bkp": "230", "din276": "440"}),
            ],
        ),
        # ── BKP 232 Telekommunikation / Sicherheit ─────────────────
        (
            "232",
            "BKP 232 - Telekommunikations- und Sicherheitsanlagen",
            {"bkp": "232", "din276": "440"},
            [
                ("232.1", "Strukturierte Verkabelung Cat.7 / LWL", "m2", 8400, 42.00, {"bkp": "232", "din276": "440"}),
                ("232.2", "Brandmeldeanlage VKF-anerkannt", "m2", 11200, 18.50, {"bkp": "232", "din276": "440"}),
                ("232.3", "Zutrittskontrolle + Schliessanlage", "pcs", 140, 880.00, {"bkp": "232", "din276": "440"}),
                ("232.4", "Videoueberwachung", "pcs", 72, 1250.00, {"bkp": "232", "din276": "440"}),
            ],
        ),
        # ── BKP 240 Heizung ────────────────────────────────────────
        (
            "240",
            "BKP 240 - Heizungsanlagen",
            {"bkp": "240", "din276": "420"},
            [
                ("240.1", "Fernwaermeanschluss + Uebergabestation 600 kW", "lsum", 1, 125000.00, {"bkp": "240", "din276": "420"}),
                ("240.2", "Waermepumpe Luft/Wasser 180 kW Kaskade", "lsum", 1, 225000.00, {"bkp": "240", "din276": "420"}),
                ("240.3", "Pufferspeicher 2000 L", "pcs", 2, 8800.00, {"bkp": "240", "din276": "420"}),
                ("240.4", "Heizungsverteiler + Pumpengruppen", "lsum", 1, 98000.00, {"bkp": "240", "din276": "420"}),
                ("240.5", "Betonkernaktivierung BKT Rohrregister", "m2", 6800, 48.00, {"bkp": "240", "din276": "420"}),
                ("240.6", "Statische Heizflaechen / Konvektoren", "pcs", 140, 540.00, {"bkp": "240", "din276": "420"}),
            ],
        ),
        # ── BKP 241 Lueftung / Klima ──────────────────────────────
        (
            "241",
            "BKP 241 - Lueftungsanlagen",
            {"bkp": "241", "din276": "420"},
            [
                ("241.1", "RLT-Zentralgeraet mit WRG 48.000 m3/h", "pcs", 3, 118000.00, {"bkp": "241", "din276": "420"}),
                ("241.2", "Luftkanaele verzinkt Hauptverteilung", "m2", 7200, 98.00, {"bkp": "241", "din276": "420"}),
                ("241.3", "Volumenstromregler VVS", "pcs", 320, 620.00, {"bkp": "241", "din276": "420"}),
                ("241.4", "Brandschutzklappen EI90", "pcs", 240, 365.00, {"bkp": "241", "din276": "420"}),
                ("241.5", "Luftauslaesse Drall-/Schlitzauslaesse", "pcs", 1200, 125.00, {"bkp": "241", "din276": "420"}),
                ("241.6", "Tiefgaragenentlueftung CO-gesteuert", "lsum", 1, 120000.00, {"bkp": "241", "din276": "420"}),
            ],
        ),
        # ── BKP 242 Sanitaer ──────────────────────────────────────
        (
            "242",
            "BKP 242 - Sanitaeranlagen",
            {"bkp": "242", "din276": "420"},
            [
                ("242.1", "Grundleitungen SML/PE DN100-DN200", "m", 1200, 75.00, {"bkp": "242", "din276": "420"}),
                ("242.2", "Schmutz-/Regenwasserleitung Steigstraenge", "m", 1800, 58.00, {"bkp": "242", "din276": "420"}),
                ("242.3", "Trinkwasserinstallation Edelstahl/PE-Xc", "m", 3600, 55.00, {"bkp": "242", "din276": "420"}),
                ("242.4", "Sanitaerobjekte WC/Waschtisch komplett", "pcs", 160, 1580.00, {"bkp": "242", "din276": "420"}),
                ("242.5", "Regenwassernutzung Retentionsbecken", "lsum", 1, 48000.00, {"bkp": "242", "din276": "420"}),
                ("242.6", "Daemmung Rohrleitungen MuKEn", "m", 3600, 18.50, {"bkp": "242", "din276": "420"}),
            ],
        ),
        # ── BKP 250 Aufzuege ──────────────────────────────────────
        (
            "250",
            "BKP 250 - Transportanlagen",
            {"bkp": "250", "din276": "410"},
            [
                ("250.1", "Personenaufzug 1600 kg / 21 Pers., 9 Haltestellen", "pcs", 3, 215000.00, {"bkp": "250", "din276": "410"}),
                ("250.2", "Lasten-/Feuerwehraufzug 2000 kg", "pcs", 1, 285000.00, {"bkp": "250", "din276": "410"}),
            ],
        ),
        # ── BKP 260 Gebaeudeautomation ────────────────────────────
        (
            "260",
            "BKP 260 - Gebaeudeautomation",
            {"bkp": "260", "din276": "460"},
            [
                ("260.1", "GLT Managementebene + Server", "lsum", 1, 195000.00, {"bkp": "260", "din276": "460"}),
                ("260.2", "DDC-Automationsstationen", "pcs", 36, 5400.00, {"bkp": "260", "din276": "460"}),
                ("260.3", "Feldgeraete / Sensorik / Aktorik", "lsum", 1, 345000.00, {"bkp": "260", "din276": "460"}),
                ("260.4", "Raumautomation Buero KNX", "m2", 7800, 28.00, {"bkp": "260", "din276": "460"}),
                ("260.5", "Inbetriebnahme + GA-Funktionspruefung", "lsum", 1, 108000.00, {"bkp": "260", "din276": "460"}),
            ],
        ),
        # ── BKP 280 Baunebenkosten ────────────────────────────────
        (
            "280",
            "BKP 280 - Baunebenkosten, Honorare",
            {"bkp": "280", "din276": "350"},
            [
                ("280.1", "Architektenhonorar SIA 102", "lsum", 1, 2850000.00, {"bkp": "280", "din276": "350"}),
                ("280.2", "Bauingenieurhonorar SIA 108", "lsum", 1, 1250000.00, {"bkp": "280", "din276": "350"}),
                ("280.3", "HLKS-Ingenieurhonorar SIA 108", "lsum", 1, 980000.00, {"bkp": "280", "din276": "350"}),
                ("280.4", "Elektroingenieurhonorar SIA 108", "lsum", 1, 680000.00, {"bkp": "280", "din276": "350"}),
                ("280.5", "Bauherrenberatung / Projektmanagement", "lsum", 1, 420000.00, {"bkp": "280", "din276": "350"}),
            ],
        ),
        # ── BKP 420 Umgebung ──────────────────────────────────────
        (
            "420",
            "BKP 420 - Umgebung",
            {"bkp": "420", "din276": "500"},
            [
                ("420.1", "Erdarbeiten Umgebung / Oberboden", "m3", 1600, 32.00, {"bkp": "420", "din276": "500"}),
                ("420.2", "Tiefgaragenrampe Beton + Heizung", "m2", 180, 320.00, {"bkp": "420", "din276": "500"}),
                ("420.3", "Verkehrsflaechen Asphalt + Pflaster", "m2", 1800, 98.00, {"bkp": "420", "din276": "500"}),
                ("420.4", "Baumpflanzung + Pflanzbeete", "pcs", 32, 2400.00, {"bkp": "420", "din276": "500"}),
                ("420.5", "Aussenbeleuchtung Mastleuchten + Poller", "pcs", 28, 1850.00, {"bkp": "420", "din276": "500"}),
                ("420.6", "Veloabstellplaetze ueberdacht", "pcs", 80, 420.00, {"bkp": "420", "din276": "500"}),
            ],
        ),
    ],
    markups=[
        ("Baustellengemeinkosten (BGK)", 10.0, "overhead", "direct_cost"),
        ("Allgemeine Geschaeftskosten (AGK)", 8.0, "overhead", "direct_cost"),
        ("Risiko (R)", 3.0, "contingency", "direct_cost"),
        ("Gewinn (G)", 5.0, "profit", "direct_cost"),
        ("Mehrwertsteuer (MWST)", 8.1, "tax", "cumulative"),
    ],
    total_months=26,
    tender_name="Rohbau",
    tender_companies=[
        ("Tobelmann Bau AG, Zurich", "offerte@tobelmann.example", 0.98),
        ("Grauholz + Sennhof AG", "submission@grauholz.example", 1.03),
        ("Werkhof Bernhardt AG", "offerte@werkhof-bernhardt.example", 1.01),
    ],
    project_metadata={
        "address": "Pfingstweidstrasse 60, 8005 Zurich",
        "client": "Hafenfeld Immobilien AG, Zurich",
        "main_contractor": "Tobelmann Bau AG, Zurich",
        "architect": "Steinvoss + Koerner Architekten BSA, Zurich",
        "structural_engineer": "Thalberg Bauingenieure AG",
        "mep_engineer": "Grabenfeld Haustechnik AG",
        "gfa_m2": 11200,
        "rentable_area_m2": 7800,
        "gv_m3": 44800,
        "storeys_above": 7,
        "storeys_below": 2,
        "parking_spaces": 95,
        "structure_system": "Stahlbeton-Skelettbau / RC frame, flat slabs, core-braced",
        "facade_system": "Elementfassade Aluminium/Glas, Dreifach-Verglasung Uw 0,85",
        "grid_m": "7.80 x 7.80",
        "energy_standard": "Minergie-P",
        "sustainability_target": "SNBS Standard Gold",
        "design_phase": "SIA 112 Phase 32 Bauprojekt / Kostenvoranschlag",
        "applicable_standards": [
            "SIA 451 (Kostenplanung im Hochbau)",
            "BKP Baukostenplan (CRB)",
            "SIA 118:2013 (Allgemeine Bedingungen fuer Bauarbeiten)",
            "SIA 102:2020 (Leistungen und Honorare der Architekten)",
            "SIA 112:2014 (Modell Bauplanung)",
            "Minergie-P Standard",
            "SNBS Standard Hochbau 2.1",
        ],
        "permit_authority": "Bauamt Stadt Zurich (PBG / BZO)",
        "cost_basis": "CRB-Baukostenbenchmarks 2025/26, Regionalfaktor Zurich",
    },
    tender_packages=[
        (
            "Rohbau",
            "Baugrube, Gruendung, Stahlbeton-Skelettbau, Kerne, Decken",
            "evaluating",
            [
                ("Tobelmann Bau AG, Zurich", "offerte@tobelmann.example", 0.98),
                ("Grauholz + Sennhof AG", "submission@grauholz.example", 1.03),
                ("Werkhof Bernhardt AG", "offerte@werkhof-bernhardt.example", 1.01),
            ],
        ),
        (
            "Fassade",
            "Elementfassade, Pfosten-Riegel, Sonnenschutz, Dachabdichtung",
            "evaluating",
            [
                ("Riedfeld Fassadenbau AG", "offerte@riedfeld.example", 0.97),
                ("Glashaus Bernhardt + Partner", "submission@glashaus.example", 1.04),
            ],
        ),
        (
            "HLKS (Heizung/Lueftung/Klima/Sanitaer)",
            "Fernwaerme, Waermepumpen, BKT, Lueftung, Sanitaer",
            "evaluating",
            [
                ("Haustechnik Grimmwald AG", "offerte@grimmwald.example", 0.99),
                ("Sennhof Gebaeudetechnik AG", "angebot@sennhof-gbt.example", 1.05),
            ],
        ),
        (
            "Elektro / GA",
            "Trafo, NS-Verteilung, Beleuchtung, Sicherheitstechnik, GLT",
            "evaluating",
            [
                ("Elektro Haldenfeld AG", "offerte@haldenfeld.example", 0.98),
                ("Amstein + Walthert Elektro", "submission@amstein-walthert.example", 1.02),
            ],
        ),
        (
            "Innenausbau",
            "Trockenbau, Doppelboden, Akustikdecken, Bodenbelaege, Tueren",
            "draft",
            [
                ("Ausbau Steinberg AG", "offerte@steinberg-ausbau.example", 0.97),
                ("Thalmann Innenausbau GmbH", "angebot@thalmann.example", 1.03),
            ],
        ),
    ],
)
