# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner-pack demo: BIM-coordinated office building Frankfurt am Main (Hessen)
# Pack: bimhessen-de  ·  DIN 276:2018-12 cost calculation (HOAI LP3)
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="office-frankfurt",
    project_name="Bürogebäude Frankfurt Europaviertel",
    project_description=(
        "Neubau eines BIM-koordinierten Büro- und Geschäftshauses im "
        "Europaviertel Frankfurt am Main. 8 Obergeschosse + Staffelgeschoss, "
        "2 Untergeschosse Tiefgarage mit 140 Stellplätzen. "
        "BGF ca. 14.000 m2, BRI ca. 56.000 m3, ca. 9.800 m2 Mietfläche (MF/G). "
        "Tragwerk: Stahlbeton-Skelettbau (RC frame) mit Flachdecken auf Stützenraster "
        "8,10 x 8,10 m, Aussteifung über Treppen-/Aufzugskerne. "
        "Gebäudehülle: Elementfassade / Pfosten-Riegel-Vorhangfassade (curtain wall) "
        "mit Dreifach-Isolierverglasung und außenliegendem Sonnenschutz. "
        "Energiestandard GEG / KfW Effizienzgebäude 40 (NWG), DGNB Gold angestrebt. "
        "Planung und Ausführung als BIM-Projekt nach ISO 19650 (BAP/AIA). "
        "Baukosten KG 300+400 ca. 44 Mio EUR (Kostenberechnung HOAI LP3)."
    ),
    region="DACH",
    classification_standard="din276",
    currency="EUR",
    locale="de",
    address={
        "street": "Europa-Allee 90",
        "city": "Frankfurt am Main",
        "postcode": "60486",
        "country": "Germany",
        "lat": 50.1075,
        "lng": 8.6385,
    },
    validation_rule_sets=["din276", "gaeb", "boq_quality"],
    boq_name="Kostenberechnung nach DIN 276 (HOAI LP3)",
    boq_description=(
        "Detaillierte Kostenberechnung gem. DIN 276:2018-12, "
        "Schwerpunkt KG 300 Bauwerk-Baukonstruktionen und KG 400 "
        "Bauwerk-Technische Anlagen, zzgl. KG 500 Außenanlagen. "
        "Mengenermittlung modellbasiert aus BIM-Koordinationsmodell (ISO 19650)."
    ),
    boq_metadata={
        "standard": "DIN 276:2018-12",
        "phase": "Kostenberechnung (HOAI LP3)",
        "base_date": "2026-Q1",
        "price_level": "Frankfurt/Hessen 2026",
    },
    sections=[
        # ── KG 310 Baugrube / Erdbau ─────────────────────────────────
        (
            "310",
            "KG 310 - Baugrube / Erdbau",
            {"din276": "310"},
            [
                ("310.1", "Baugrundgutachten + Baugrunderkundung", "lsum", 1, 42000.00, {"din276": "311"}),
                ("310.2", "Kampfmittelsondierung Grundstück", "m2", 4200, 4.20, {"din276": "311"}),
                ("310.3", "Bohrpfahlwand verankert d=900mm", "m2", 4800, 215.00, {"din276": "312"}),
                ("310.4", "Verpressanker temporär", "pcs", 220, 1450.00, {"din276": "312"}),
                ("310.5", "Aushub Baugrube Klasse 3-5", "m3", 78000, 16.50, {"din276": "313"}),
                ("310.6", "Bodenabtransport + Deponie Z1.1/Z2", "m3", 72000, 28.00, {"din276": "313"}),
                ("310.7", "Grundwasserhaltung offene Wasserhaltung", "month", 14, 18500.00, {"din276": "314"}),
                ("310.8", "Sohlabdichtung Unterwasserbeton", "m3", 1200, 165.00, {"din276": "314"}),
                ("310.9", "Verdichtung + Planum Baugrubensohle", "m2", 3600, 5.80, {"din276": "313"}),
                ("310.10", "Baustraße + Andienung Schottertragschicht", "m2", 1400, 32.00, {"din276": "319"}),
            ],
        ),
        # ── KG 320 Gruendung, Unterbau ───────────────────────────────
        (
            "320",
            "KG 320 - Gründung, Unterbau",
            {"din276": "320"},
            [
                ("320.1", "Sauberkeitsschicht C12/15", "m2", 3600, 13.50, {"din276": "322"}),
                ("320.2", "Bodenplatte WU-Beton C30/37 XC4, d=80cm", "m3", 2880, 215.00, {"din276": "324"}),
                ("320.3", "Bewehrung Bodenplatte BSt 500", "t", 360, 1620.00, {"din276": "324"}),
                ("320.4", "Pfahlgründung Bohrpfähle d=900mm, L=18m", "m", 3240, 185.00, {"din276": "322"}),
                ("320.5", "Fugenbleche + Quellband WU-Konzept", "m", 1800, 38.00, {"din276": "324"}),
                ("320.6", "Aufzugsunterfahrt / Pumpensumpf", "pcs", 4, 8500.00, {"din276": "324"}),
                ("320.7", "Drainage + Ringdrainage DN200", "m", 360, 72.00, {"din276": "326"}),
                ("320.8", "Bodenplatten-Beschichtung Tiefgarage OS8", "m2", 6400, 28.00, {"din276": "325"}),
            ],
        ),
        # ── KG 330 Aussenwaende / Vertikale Baukonstruktionen ────────
        (
            "330",
            "KG 330 - Außenwände / vertikale Baukonstruktionen, außen",
            {"din276": "330"},
            [
                ("330.1", "Kelleraußenwand WU-Beton C30/37, d=40cm", "m3", 1180, 245.00, {"din276": "331"}),
                ("330.2", "Schalung Außenwände Rahmenschalung", "m2", 8400, 38.00, {"din276": "331"}),
                ("330.3", "Bewehrung Außenwände BSt 500", "t", 142, 1680.00, {"din276": "331"}),
                ("330.4", "Stahlbetonstützen C45/55, Rundstützen", "m3", 460, 420.00, {"din276": "331"}),
                ("330.5", "Perimeterdämmung XPS 160mm erdberührt", "m2", 3800, 52.00, {"din276": "335"}),
                ("330.6", "Bauwerksabdichtung KMB erdberührt", "m2", 3800, 46.00, {"din276": "335"}),
                ("330.7", "Elementfassade Aluminium 3-fach-Verglasung Uw 0,9", "m2", 7200, 720.00, {"din276": "337"}),
                ("330.8", "Pfosten-Riegel-Fassade Eingangshalle", "m2", 640, 580.00, {"din276": "337"}),
                ("330.9", "Außenliegender Sonnenschutz Raffstore motorisiert", "m2", 6800, 165.00, {"din276": "338"}),
                ("330.10", "Öffnungsflügel / Parallelausstellfenster", "pcs", 280, 1450.00, {"din276": "337"}),
                ("330.11", "Festverglasung Brandschutz F30 Atrium", "m2", 320, 480.00, {"din276": "337"}),
                ("330.12", "Außentüren Aluminium Eingang", "pcs", 6, 6800.00, {"din276": "334"}),
                ("330.13", "Fassadenbefahranlage Anschlagpunkte", "lsum", 1, 38000.00, {"din276": "338"}),
            ],
        ),
        # ── KG 340 Innenwaende / Vertikale Baukonstruktionen, innen ──
        (
            "340",
            "KG 340 - Innenwände / vertikale Baukonstruktionen, innen",
            {"din276": "340"},
            [
                ("340.1", "Stahlbetonkerne C35/45 Treppen/Aufzug", "m3", 1240, 395.00, {"din276": "341"}),
                ("340.2", "Schalung Kerne Kletterschalung", "m2", 7200, 44.00, {"din276": "341"}),
                ("340.3", "Bewehrung Kerne BSt 500", "t", 168, 1680.00, {"din276": "341"}),
                ("340.4", "Trennwand Trockenbau doppelt beplankt CW100", "m2", 9600, 58.00, {"din276": "342"}),
                ("340.5", "Brandwand F90 Trockenbau", "m2", 2400, 135.00, {"din276": "342"}),
                ("340.6", "Systemtrennwand verglast Büro", "m2", 3200, 285.00, {"din276": "342"}),
                ("340.7", "Schachtwände Installationsschächte F90", "m2", 1800, 92.00, {"din276": "342"}),
                ("340.8", "Innentüren Holz / Stahlzargen", "pcs", 420, 720.00, {"din276": "344"}),
                ("340.9", "Brandschutztüren T30/T90", "pcs", 96, 1450.00, {"din276": "344"}),
                ("340.10", "WC-Trennwandsysteme HPL", "pcs", 64, 980.00, {"din276": "346"}),
                ("340.11", "Wandbeschichtung / Dispersion innen", "m2", 22000, 9.50, {"din276": "345"}),
                ("340.12", "Wandfliesen Sanitärbereiche", "m2", 2200, 62.00, {"din276": "345"}),
            ],
        ),
        # ── KG 350 Decken / Horizontale Baukonstruktionen ────────────
        (
            "350",
            "KG 350 - Decken / horizontale Baukonstruktionen",
            {"din276": "350"},
            [
                ("350.1", "Stahlbeton-Flachdecke C30/37, d=32cm", "m3", 4480, 335.00, {"din276": "351"}),
                ("350.2", "Schalung Decken Deckentische", "m2", 14000, 32.00, {"din276": "351"}),
                ("350.3", "Bewehrung Decken BSt 500", "t", 520, 1680.00, {"din276": "351"}),
                ("350.4", "Durchstanzbewehrung Stützenkopf", "pcs", 280, 320.00, {"din276": "351"}),
                ("350.5", "Hohlraumboden / Doppelboden Büroflächen", "m2", 8800, 78.00, {"din276": "352"}),
                ("350.6", "Zementestrich CT-C25-F4 Nebenflächen", "m2", 3200, 28.00, {"din276": "352"}),
                ("350.7", "Trittschalldämmung MW-T 30mm", "m2", 11000, 14.50, {"din276": "352"}),
                ("350.8", "Bodenbelag Teppichfliese Büro", "m2", 7600, 42.00, {"din276": "352"}),
                ("350.9", "Bodenbelag Naturwerkstein Eingangshalle", "m2", 680, 185.00, {"din276": "352"}),
                ("350.10", "Bodenbelag Feinsteinzeug Nebenflächen", "m2", 2400, 68.00, {"din276": "352"}),
                ("350.11", "Akustik-Metalldecke Kassetten abgehängt", "m2", 9200, 88.00, {"din276": "353"}),
                ("350.12", "Gipskarton-Unterdecke F30/F90", "m2", 3600, 52.00, {"din276": "353"}),
                ("350.13", "Sockelleisten Aluminium", "m", 6400, 11.50, {"din276": "352"}),
            ],
        ),
        # ── KG 360 Daecher ───────────────────────────────────────────
        (
            "360",
            "KG 360 - Dächer",
            {"din276": "360"},
            [
                ("360.1", "Stahlbeton-Dachdecke C30/37, d=30cm", "m3", 540, 345.00, {"din276": "361"}),
                ("360.2", "Gefälledämmung PIR 220-300mm", "m2", 1900, 78.00, {"din276": "363"}),
                ("360.3", "Dachabdichtung FPO/TPO 2-lagig", "m2", 1900, 56.00, {"din276": "363"}),
                ("360.4", "Extensivbegrünung Substrat + Vegetation", "m2", 1100, 62.00, {"din276": "363"}),
                ("360.5", "Dachrandabschluss / Attikaabdeckung Alu", "m", 420, 68.00, {"din276": "362"}),
                ("360.6", "Absturzsicherung Sekuranten + Geländer", "m", 420, 145.00, {"din276": "362"}),
                ("360.7", "Lichtkuppeln / RWA Treppenhäuser", "pcs", 6, 4800.00, {"din276": "362"}),
                ("360.8", "Dachdurchführungen + Entlüftung", "pcs", 48, 320.00, {"din276": "362"}),
                ("360.9", "PV-Anlage Aufdach 180 kWp", "lsum", 1, 245000.00, {"din276": "362"}),
            ],
        ),
        # ── KG 370 Infrastrukturanlagen / sonst. Baukonstruktionen ───
        (
            "370",
            "KG 370 - Baukonstruktive Einbauten",
            {"din276": "370"},
            [
                ("370.1", "Stahlbeton-Fertigteiltreppen", "pcs", 36, 5200.00, {"din276": "379"}),
                ("370.2", "Treppengeländer Edelstahl + Glas", "m", 540, 295.00, {"din276": "379"}),
                ("370.3", "Empfangstresen / Lobby-Einbau", "lsum", 1, 68000.00, {"din276": "371"}),
                ("370.4", "Teeküchen / Pantry-Module je Geschoss", "pcs", 18, 8500.00, {"din276": "371"}),
                ("370.5", "Sanitär-Trennwandanlagen + Spiegel", "lsum", 1, 42000.00, {"din276": "371"}),
                ("370.6", "Beschilderung / Leitsystem", "lsum", 1, 38000.00, {"din276": "374"}),
            ],
        ),
        # ── KG 390 Sonstige Massnahmen Baukonstruktionen ─────────────
        (
            "390",
            "KG 390 - Sonstige Massnahmen für Baukonstruktionen",
            {"din276": "390"},
            [
                ("390.1", "Baustelleneinrichtung Großbaustelle", "lsum", 1, 420000.00, {"din276": "391"}),
                ("390.2", "Turmdrehkran inkl. Vorhaltung", "month", 16, 16500.00, {"din276": "392"}),
                ("390.3", "Gerüst Fassade Standgerüst", "m2", 9800, 18.50, {"din276": "392"}),
                ("390.4", "Baureinigung + Schlussreinigung", "m2", 14000, 6.50, {"din276": "395"}),
                ("390.5", "Winterbaumassnahmen", "lsum", 1, 65000.00, {"din276": "394"}),
            ],
        ),
        # ── KG 410 Abwasser, Wasser, Gas ─────────────────────────────
        (
            "410",
            "KG 410 - Abwasser-, Wasser-, Gasanlagen",
            {"din276": "410"},
            [
                ("410.1", "Grundleitungen SML/PE DN100-DN200", "m", 1600, 58.00, {"din276": "411"}),
                ("410.2", "Schmutz-/Regenwasserleitung Steigstränge", "m", 2400, 46.00, {"din276": "411"}),
                ("410.3", "Hebeanlage Tiefgarage", "pcs", 4, 8800.00, {"din276": "411"}),
                ("410.4", "Trinkwasserinstallation PE-Xc/Edelstahl", "m", 4800, 42.00, {"din276": "412"}),
                ("410.5", "Trinkwassererwärmung Frischwasserstation", "pcs", 9, 6800.00, {"din276": "412"}),
                ("410.6", "Sanitärobjekte WC/Waschtisch komplett", "pcs", 220, 1250.00, {"din276": "412"}),
                ("410.7", "Regenwassernutzung Zisterne + Pumpe", "lsum", 1, 38000.00, {"din276": "419"}),
                ("410.8", "Dämmung Rohrleitungen EnEV/GEG", "m", 4800, 14.50, {"din276": "419"}),
            ],
        ),
        # ── KG 420 Waermeversorgungsanlagen ──────────────────────────
        (
            "420",
            "KG 420 - Wärmeversorgungsanlagen",
            {"din276": "420"},
            [
                ("420.1", "Fernwärme-Übergabestation 900 kW", "pcs", 1, 92000.00, {"din276": "421"}),
                ("420.2", "Luft-Wasser-Wärmepumpe Kaskade 240 kW", "lsum", 1, 185000.00, {"din276": "421"}),
                ("420.3", "Pufferspeicher 2000 L", "pcs", 3, 6800.00, {"din276": "421"}),
                ("420.4", "Heizungsverteiler + Pumpengruppen", "lsum", 1, 78000.00, {"din276": "422"}),
                ("420.5", "Heizungssteigleitungen Stahl gedämmt", "m", 3200, 38.00, {"din276": "422"}),
                ("420.6", "Statische Heizflächen / Konvektoren", "pcs", 180, 420.00, {"din276": "423"}),
                ("420.7", "Betonkernaktivierung BKT Rohrregister", "m2", 8800, 38.00, {"din276": "423"}),
            ],
        ),
        # ── KG 430 Raumlufttechnische Anlagen ────────────────────────
        (
            "430",
            "KG 430 - Raumlufttechnische Anlagen",
            {"din276": "430"},
            [
                ("430.1", "RLT-Zentralgerät mit WRG 60.000 m3/h", "pcs", 4, 92000.00, {"din276": "431"}),
                ("430.2", "Luftkanäle verzinkt Hauptverteilung", "m2", 9200, 78.00, {"din276": "431"}),
                ("430.3", "Volumenstromregler VVS", "pcs", 420, 480.00, {"din276": "431"}),
                ("430.4", "Brandschutzklappen EI90", "pcs", 320, 285.00, {"din276": "431"}),
                ("430.5", "Luftauslässe Drall-/Schlitzauslässe", "pcs", 1600, 95.00, {"din276": "431"}),
                ("430.6", "Schalldämpfer Kulissenschalldämpfer", "pcs", 160, 320.00, {"din276": "431"}),
                ("430.7", "Tiefgaragenentlüftung CO-gesteuert", "lsum", 1, 95000.00, {"din276": "434"}),
                ("430.8", "Küche-/Sonderabluft Edelstahl", "lsum", 1, 42000.00, {"din276": "434"}),
            ],
        ),
        # ── KG 440 Elektrische Anlagen ───────────────────────────────
        (
            "440",
            "KG 440 - Elektrische Anlagen, Starkstrom",
            {"din276": "440"},
            [
                ("440.1", "Mittelspannungsübergabe + Trafostation 2x1000 kVA", "lsum", 1, 285000.00, {"din276": "441"}),
                ("440.2", "Niederspannungshauptverteilung NSHV", "pcs", 2, 48000.00, {"din276": "443"}),
                ("440.3", "Unterverteilungen je Geschoss", "pcs", 22, 5800.00, {"din276": "443"}),
                ("440.4", "Netzersatzanlage Diesel-NEA 400 kVA", "pcs", 1, 145000.00, {"din276": "442"}),
                ("440.5", "USV-Anlage Sicherheitsverbraucher", "pcs", 2, 38000.00, {"din276": "442"}),
                ("440.6", "Kabeltrassen + Bus-Schienen Verteilung", "m", 6800, 38.00, {"din276": "444"}),
                ("440.7", "Installationsleitungen NYM/Funktionserhalt", "m", 96000, 4.20, {"din276": "444"}),
                ("440.8", "Allgemeinbeleuchtung LED DALI", "m2", 11000, 58.00, {"din276": "445"}),
                ("440.9", "Sicherheitsbeleuchtung Zentralbatterie", "lsum", 1, 88000.00, {"din276": "445"}),
                ("440.10", "Blitzschutz + Erdung äußerer/innerer", "lsum", 1, 92000.00, {"din276": "446"}),
                ("440.11", "E-Ladeinfrastruktur Tiefgarage 11/22 kW", "pcs", 70, 2400.00, {"din276": "442"}),
            ],
        ),
        # ── KG 450 Kommunikations-/sicherheitstechnische Anlagen ─────
        (
            "450",
            "KG 450 - Kommunikations-, sicherheits- u. informationstechn. Anlagen",
            {"din276": "450"},
            [
                ("450.1", "Strukturierte Verkabelung Cat.7 / LWL", "m2", 11000, 32.00, {"din276": "456"}),
                ("450.2", "Brandmeldeanlage BMA VdS Kat. 1", "m2", 14000, 14.50, {"din276": "454"}),
                ("450.3", "Sprachalarmierung SAA / ELA", "lsum", 1, 78000.00, {"din276": "454"}),
                ("450.4", "Zutrittskontrolle + Schließanlage", "pcs", 180, 680.00, {"din276": "453"}),
                ("450.5", "Videoüberwachung VSS / CCTV", "pcs", 96, 980.00, {"din276": "452"}),
                ("450.6", "Einbruchmeldeanlage EMA", "lsum", 1, 42000.00, {"din276": "452"}),
            ],
        ),
        # ── KG 460 Foerderanlagen ────────────────────────────────────
        (
            "460",
            "KG 460 - Förderanlagen",
            {"din276": "460"},
            [
                ("460.1", "Personenaufzug 1600 kg / 21 Pers., 11 Haltestellen", "pcs", 4, 165000.00, {"din276": "461"}),
                ("460.2", "Lasten-/Feuerwehraufzug 2000 kg", "pcs", 2, 215000.00, {"din276": "461"}),
                ("460.3", "Fassadenbefahranlage Dach-BMU", "pcs", 1, 185000.00, {"din276": "462"}),
            ],
        ),
        # ── KG 480 Gebaeude- und Anlagenautomation ───────────────────
        (
            "480",
            "KG 480 - Gebäudeautomation (GA/MSR)",
            {"din276": "480"},
            [
                ("480.1", "GLT Managementebene + Server", "lsum", 1, 165000.00, {"din276": "481"}),
                ("480.2", "DDC-Automationsstationen", "pcs", 48, 4200.00, {"din276": "482"}),
                ("480.3", "Feldgeräte / Sensorik / Aktorik", "lsum", 1, 285000.00, {"din276": "483"}),
                ("480.4", "Raumautomation Büro KNX", "m2", 9800, 22.00, {"din276": "484"}),
                ("480.5", "Inbetriebnahme + GA-Funktionsprüfung", "lsum", 1, 88000.00, {"din276": "485"}),
            ],
        ),
        # ── KG 500 Aussenanlagen und Freiflaechen ────────────────────
        (
            "500",
            "KG 500 - Außenanlagen und Freiflächen",
            {"din276": "500"},
            [
                ("500.1", "Erdarbeiten Außenanlagen / Oberboden", "m3", 2200, 22.00, {"din276": "510"}),
                ("500.2", "Tiefgaragenrampe Beton + Heizung", "m2", 220, 245.00, {"din276": "520"}),
                ("500.3", "Verkehrsflächen Asphalt + Pflaster", "m2", 2400, 78.00, {"din276": "520"}),
                ("500.4", "Plattenbelag Naturstein Vorplatz", "m2", 1200, 165.00, {"din276": "520"}),
                ("500.5", "Baumpflanzung + Pflanzbeete", "pcs", 42, 1850.00, {"din276": "530"}),
                ("500.6", "Rasen-/Staudenflächen", "m2", 1800, 32.00, {"din276": "530"}),
                ("500.7", "Außenkanalisation + Anschluss", "m", 320, 145.00, {"din276": "541"}),
                ("500.8", "Versorgungsanschlüsse MS/Wasser/FW", "lsum", 1, 165000.00, {"din276": "540"}),
                ("500.9", "Außenbeleuchtung Mastleuchten + Poller", "pcs", 38, 1450.00, {"din276": "550"}),
                ("500.10", "Fahrradstellplätze überdacht", "pcs", 120, 320.00, {"din276": "560"}),
                ("500.11", "Einfriedung + Tore", "m", 240, 145.00, {"din276": "560"}),
                ("500.12", "Regenrückhaltung / Versickerung", "lsum", 1, 78000.00, {"din276": "541"}),
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
    total_months=30,
    tender_name="Rohbau",
    tender_companies=[
        ("Rahnstett Bau Hessen GmbH", "vergabe@rahnstett.example", 0.98),
        ("Wehrsen & Talbrunn GmbH & Co. KG", "ausschreibung@wehrsen-talbrunn.example", 1.03),
        ("Adalbert Nauklin GmbH + Co KG", "angebote@nauklin.example", 1.01),
    ],
    project_metadata={
        "address": "Europa-Allee 90, 60486 Frankfurt am Main",
        "client": "Nordkranz Projekt GmbH & Co. KG",
        "main_contractor": "Herwaldt Bau Frankfurt GmbH",
        "architect": "brandhoff+lenzen Architekten, Frankfurt",
        "structural_engineer": "Trautvend+Kastner Ingenieure",
        "mep_engineer": "VKT Ingenieur-AG",
        "gfa_m2": 14000,
        "rentable_area_m2": 9800,
        "bri_m3": 56000,
        "storeys_above": 9,
        "storeys_below": 2,
        "parking_spaces": 140,
        "structure_system": "Stahlbeton-Skelettbau / RC frame, flat slabs, core-braced",
        "facade_system": "Elementfassade / unitised curtain wall, triple glazing Uw 0,9",
        "grid_m": "8.10 x 8.10",
        "energy_standard": "GEG / KfW Effizienzgebäude 40 (NWG)",
        "sustainability_target": "DGNB Gold",
        "bim_standard": "ISO 19650 (BAP/AIA), IFC4 coordination model",
        "design_phase": "HOAI LP3 Entwurfsplanung / Kostenberechnung",
        "applicable_standards": [
            "DIN 276:2018-12",
            "VOB/C (DIN 18299 ff.)",
            "GAEB DA XML 3.3 (X83)",
            "HOAI 2021",
            "ISO 19650-1/-2",
            "GEG 2024",
            "Baukosten-Benchmarks 2025 (Neubau Büroge.)",
        ],
        "permit_authority": "Bauaufsicht Stadt Frankfurt am Main (HBO 2018)",
        "fire_concept": "Brandschutzkonzept gem. HBO / MIndBauRL, Sonderbau",
        "cost_basis": "Baukosten-Benchmarks Gebäude Neubau 2025, Regionalfaktor Frankfurt/M.",
    },
    tender_packages=[
        (
            "Rohbau",
            "Baugrube, Verbau, Gründung, Stahlbeton-Skelettbau, Kerne, Decken",
            "evaluating",
            [
                ("Rahnstett Bau Hessen GmbH", "vergabe@rahnstett.example", 0.98),
                ("Wehrsen & Talbrunn GmbH & Co. KG", "ausschreibung@wehrsen-talbrunn.example", 1.03),
                ("Adalbert Nauklin GmbH + Co KG", "angebote@nauklin.example", 1.01),
            ],
        ),
        (
            "Fassade",
            "Elementfassade, Pfosten-Riegel, Sonnenschutz, Dachabdichtung",
            "evaluating",
            [
                ("Falkried Fassaden GmbH", "vergabe@falkried.example", 0.97),
                ("Tenneberg / Clanmere Group", "tender@tenneberg.example", 1.05),
                ("Metallbau Drenthal GmbH", "angebote@drenthal.example", 1.02),
            ],
        ),
        (
            "TGA Heizung/Lüftung/Sanitär",
            "Fernwärme, Wärmepumpen, BKT, RLT-Anlagen, Sanitär",
            "evaluating",
            [
                ("Merrowtech Deutschland GmbH", "vergabe@merrowtech.example", 0.99),
                ("Havenion Deutschland GmbH", "angebote@havenion.example", 1.06),
                ("Rud. Emil Brausthal Technik (REB)", "tga@brausthal.example", 1.02),
            ],
        ),
        (
            "Elektro / GA",
            "MS/NS-Verteilung, NEA/USV, Beleuchtung, Sicherheitstechnik, GLT",
            "evaluating",
            [
                ("Roverval Deutschland & Zentraleuropa", "tender@roverval-de.example", 0.98),
                ("Belcaris / Ardevin Energies", "angebote@belcaris.example", 1.04),
                ("Talbriet Elektroanlagen Hessen", "vergabe@talbriet.example", 1.01),
            ],
        ),
        (
            "Innenausbau",
            "Trockenbau, Doppelboden, Akustikdecken, Bodenbeläge, Türen",
            "draft",
            [
                ("Falkried Group", "ausbau@falkried.example", 0.96),
                ("Selbrandt Gebäudetechnik", "angebote@selbrandt.example", 1.03),
                ("Grausbach Bauunternehmen Hessen", "vergabe@grausbach.example", 1.02),
            ],
        ),
        (
            "Außenanlagen",
            "Erdbau, Verkehrsflächen, Begrünung, Außenleuchten, Anschlüsse",
            "draft",
            [
                ("Marnstett Baugesellschaft Hessen", "angebote@marnstett.example", 0.99),
                ("GaLaBau Korndelt Rhein-Main GmbH", "vergabe@korndelt.example", 1.05),
            ],
        ),
    ],
    # E-Rechnung showcase: one receivable interim invoice from the main
    # contractor to the client, complete enough to pass an XRechnung 3.0
    # dry-run on a fresh install. All parties are fictional companies.
    einvoice_showcase={
        # Buyer master data merged onto the generated client contact
        # (Nordkranz Projekt GmbH & Co. KG, from project_metadata["client"]).
        # The e-invoice engine reads BG-8 / BR-DE-8/9 / BR-11 off this record.
        "buyer_contact": {
            "legal_name": "Nordkranz Projekt GmbH & Co. KG",
            "vat_number": "DE297543861",
            "address": {
                "street": "Mainzer Landstraße 178",
                "city": "Frankfurt am Main",
                "postcode": "60327",
            },
        },
        # The receivable invoice row itself.
        #
        # The line amounts are measured progress values, not round numbers: a
        # Abschlagsrechnung is billed off an Aufmaß, so a figure ending in six
        # zeros reads as a placeholder to anybody who has priced one.
        #
        # They are whole euros on purpose. The installer derives the header from
        # these lines (subtotal = sum, tax = 19% of subtotal, total = the two
        # added) in float, while the EN 16931 engine recomputes the VAT group in
        # Decimal; on a whole-euro basis 19% lands exactly on a cent, so the two
        # arithmetics cannot disagree and BR-CO-17 cannot fire on a rounding
        # difference nobody can see. Cents here would make the invoice depend on
        # two rounding modes agreeing.
        "invoice": {
            "invoice_number": "AR-2026-014",
            "notes": "3. Abschlagsrechnung Rohbau gem. Leistungsstand",
            "line_items": [
                {
                    "description": "Rohbauarbeiten UG2-UG1 gem. Aufmaß",
                    "quantity": "1",
                    "unit": "lsum",
                    "unit_rate": "1287413.00",
                    "amount": "1287413.00",
                },
                {
                    "description": "Rohbauarbeiten EG-3.OG gem. Aufmaß",
                    "quantity": "1",
                    "unit": "lsum",
                    "unit_rate": "638945.00",
                    "amount": "638945.00",
                },
            ],
        },
        # Stored under Invoice.metadata["einvoice"]: the Leitweg-ID (BT-10,
        # BR-DE-15), the seller party (BG-4 with the BG-6 contact XRechnung
        # wants) and the payment details (BG-16/BG-17). The IBAN is the
        # standard demonstration IBAN, not a live account.
        "einvoice": {
            "leitweg_id": "06-4300251-83",
            "vat_rate": "19",
            "seller": {
                "name": "Herwaldt Bau Frankfurt GmbH",
                "vat_id": "DE164819273",
                "country_code": "DE",
                "line1": "Hanauer Landstraße 210",
                "postcode": "60314",
                "city": "Frankfurt am Main",
                "contact_name": "Sabine Herwaldt",
                "contact_phone": "+49 69 4089210",
                "contact_email": "rechnung@herwaldt-bau.example",
            },
            "payee_iban": "DE89370400440532013000",
            "payee_account_name": "Herwaldt Bau Frankfurt GmbH",
            "payment_terms": "Zahlbar innerhalb von 30 Tagen netto gem. § 16 VOB/B",
        },
    },
    # Detailed build-up of the drywall positions as a German estimator writes
    # it: quantities per m2 of wall or ceiling (cutting waste included) at
    # Frankfurt merchant prices 2026, and the crew's hours per m2 at the
    # average site wage (Mittellohn, 54 EUR/h including wage-related costs).
    # Each list adds up to the position's unit rate to the cent.
    position_resources={
        # CW 100, two layers of 12.5 mm board each side, mineral wool in the cavity.
        "340.4": [
            ("drywall_cw_stud_100", "material", "m", 2.00, 2.30),
            ("drywall_uw_track_100", "material", "m", 0.80, 2.10),
            ("drywall_board_gkb_12_5", "material", "m2", 4.20, 3.20),
            ("drywall_mineral_wool", "material", "m2", 1.05, 4.00),
            ("drywall_screws", "material", "pcs", 40, 0.012),
            ("drywall_joint_compound", "material", "kg", 0.60, 1.20),
            ("drywall_sealing_tape", "material", "m", 1.20, 0.375),
            ("drywall_anchors", "material", "pcs", 1.60, 0.15),
            ("drywall_installer_avg_wage", "labor", "hr", 0.58, 54.00),
            ("drywall_small_tools", "equipment", "hr", 0.58, 1.50),
        ],
        # Fire wall: fire-rated boards, a steel sheet inlay each side for impact,
        # non-combustible insulation and metal anchors.
        "340.5": [
            ("drywall_cw_stud_100", "material", "m", 2.20, 2.30),
            ("drywall_uw_track_100", "material", "m", 0.80, 2.10),
            ("drywall_board_gkf_12_5", "material", "m2", 4.20, 4.10),
            ("drywall_steel_sheet_inlay", "material", "m2", 2.10, 10.20),
            ("drywall_mineral_wool_fire", "material", "m2", 1.05, 6.20),
            ("drywall_screws", "material", "pcs", 50, 0.012),
            ("drywall_joint_compound", "material", "kg", 0.60, 1.20),
            ("drywall_fire_sealing_tape", "material", "m", 1.20, 0.70),
            ("drywall_anchors", "material", "pcs", 2.00, 0.31),
            ("drywall_installer_avg_wage", "labor", "hr", 1.45, 54.00),
            ("drywall_small_tools", "equipment", "hr", 1.45, 1.40),
        ],
        # Shaft wall, boarded from one side only: CW 75 and two layers of 25 mm
        # fire-rated board.
        "340.7": [
            ("drywall_cw_stud_75", "material", "m", 2.00, 1.90),
            ("drywall_uw_track_75", "material", "m", 0.80, 1.70),
            ("drywall_board_gkf_25", "material", "m2", 2.10, 9.90),
            ("drywall_mineral_wool_fire", "material", "m2", 1.05, 2.60),
            ("drywall_screws", "material", "pcs", 30, 0.015),
            ("drywall_joint_compound", "material", "kg", 0.40, 1.20),
            ("drywall_fire_sealing_tape", "material", "m", 1.20, 0.60),
            ("drywall_anchors", "material", "pcs", 2.00, 0.31),
            ("drywall_installer_avg_wage", "labor", "hr", 1.10, 54.00),
            ("drywall_small_tools", "equipment", "hr", 1.10, 1.50),
        ],
        # Suspended ceiling: CD channel grid on adjustable hangers, two layers of
        # 12.5 mm fire-rated board.
        "350.12": [
            ("ceiling_cd_profile", "material", "m", 3.20, 1.15),
            ("ceiling_ud_profile", "material", "m", 0.80, 0.95),
            ("ceiling_hangers", "material", "pcs", 1.30, 0.90),
            ("ceiling_anchors", "material", "pcs", 1.30, 0.30),
            ("drywall_board_gkf_12_5", "material", "m2", 2.10, 4.10),
            ("drywall_screws", "material", "pcs", 30, 0.012),
            ("drywall_joint_compound", "material", "kg", 0.50, 1.10),
            ("ceiling_installer_avg_wage", "labor", "hr", 0.64, 54.00),
            ("ceiling_tools_mobile_scaffold", "equipment", "hr", 0.64, 3.00),
        ],
    },
)
