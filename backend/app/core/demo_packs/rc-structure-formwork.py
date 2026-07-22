# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Demo pack: doker-formwork (Doker - Schalung / formwork specialist, DACH)
#
# Flagship project where the cast-in-place reinforced-concrete structure and
# the FORMWORK SYSTEMS are the hero of the BOQ: a 7-storey reinforced-concrete
# multi-storey car park (Parkhaus) with an integrated ground-floor office /
# retail podium in Stuttgart. The dominant cost drivers are wall formwork
# (Rahmen-/Traegerschalung), slab formwork (Deckenschalung), column formwork
# (Stuetzenschalung), self-climbing formwork to the cores (Kletterschalung)
# and the falsework / shoring towers (Traggerueste), all dimensioned against
# fresh-concrete pressure to DIN 18218, falsework design to DIN EN 12812,
# concrete execution to DIN EN 13670 / DIN 1045-3 and VOB/C DIN 18331 (Beton).
#
# Standards / norms referenced:
#   DIN 276:2018-12               cost groups (KG 300-540)
#   DIN EN 1992-1-1 / NA          structural concrete design (Eurocode 2)
#   DIN EN 206 + DIN 1045-2       concrete specification, exposure classes
#   DIN EN 13670 / DIN 1045-3     execution of concrete structures
#   DIN 18218:2010-01            fresh-concrete pressure on vertical formwork
#   DIN EN 12812 (DIN 4421)      falsework - performance + design
#   DIN EN 12813                 load-bearing towers of prefab components
#   VOB/C DIN 18331              concrete works (contract terms)
#   VOB/C DIN 18451              scaffolding works
#   DGUV Information 101-008      formwork safety on construction sites
#   DIN 488                      reinforcing steel BSt 500 B / 500 S
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="rc-structure-formwork",
    project_name="Parkhaus & Buero-Podium Stuttgart-Vaihingen",
    project_description=(
        "Neubau eines 7-geschossigen Stahlbeton-Parkhauses (Ortbeton) mit "
        "rund 612 Stellplaetzen und einem zweigeschossigen Buero-/Einzelhandels-"
        "Podium im Erdgeschoss. BGF ca. 18.400 m2 Parkdeck zzgl. 2.100 m2 Podium. "
        "Tragwerk: Ortbeton-Flachdecken mit Unterzuegen, Rundstuetzen und zwei "
        "aussteifenden Stahlbetonkernen (Treppe/Aufzug) im Gleitschalverfahren. "
        "Betonguete C30/37 bis C45/55, Expositionsklassen XC4/XD3/XF4 (Streusalz). "
        "Schalung ist kostenfuehrend: Rahmenschalung Waende, Deckentische, "
        "Stuetzenschalung, Selbstkletterschalung Kerne, Traggerueste. "
        "Frischbetondruck nach DIN 18218, Traggerueste nach DIN EN 12812, "
        "Betonausfuehrung DIN EN 13670 / VOB/C DIN 18331. "
        "Konstruktionskosten (Rohbau, netto) ca. 16 Mio EUR; "
        "Direktkosten KG 300-500 ca. 13,0 Mio EUR. "
        "(7-storey cast-in-place RC car park, ~612 bays, formwork-led BOQ.)"
    ),
    region="DACH",
    classification_standard="din276",
    currency="EUR",
    locale="de",
    address={
        "street": "Industriestraße 12",
        "city": "Stuttgart",
        "postcode": "70563",
        "country": "Germany",
        "lat": 48.7261,
        "lng": 9.1126,
    },
    validation_rule_sets=["din276", "gaeb", "boq_quality"],
    boq_name="Kostenberechnung Rohbau nach DIN 276 - Schalung/Beton",
    boq_description=(
        "Detaillierte Kostenberechnung Konstruktion gem. DIN 276 mit Schwerpunkt "
        "Schalung, Traggerueste und Ortbeton. Mengen je Schalzyklus / Betonierabschnitt, "
        "Betonguete und Expositionsklasse nach DIN EN 206 / DIN 1045-2. "
        "(Detailed RC-structure cost estimate, formwork-led.)"
    ),
    boq_metadata={
        "standard": "DIN 276:2018-12",
        "phase": "Kostenberechnung (LP 3) / Ausfuehrungsplanung",
        "base_date": "2026-Q1",
        "price_level": "Stuttgart 2026",
    },
    sections=[
        # ── KG 310 Baugrube / Erdbau ──────────────────────────────────
        (
            "310",
            "KG 310 - Baugrube / Erdbau",
            {"din276": "310"},
            [
                ("310.1", "Baugrundgutachten und Probebelastung (Geotech. survey)", "lsum", 1, 24000.00, {"din276": "310"}),
                ("310.2", "Oberbodenabtrag und Lagerung (Topsoil strip)", "m3", 3200, 9.50, {"din276": "310"}),
                ("310.3", "Aushub Baugrube Bodenklasse 3-5 (Pit excavation)", "m3", 14500, 13.80, {"din276": "310"}),
                ("310.4", "Bodenabtransport und Entsorgung Z1.1 (Soil disposal)", "m3", 12800, 21.50, {"din276": "310"}),
                ("310.5", "Trägerbohlwand-Verbau IPB300 (Soldier-pile wall)", "m2", 1850, 138.00, {"din276": "310"}),
                ("310.6", "Spritzbetonsicherung Boeschung (Shotcrete slope)", "m2", 720, 62.00, {"din276": "310"}),
                ("310.7", "Wasserhaltung offene + Brunnen (Dewatering)", "month", 14, 9800.00, {"din276": "310"}),
                ("310.8", "Verfuellung / Hinterfuellung lagenweise (Backfill)", "m3", 2600, 17.20, {"din276": "310"}),
                ("310.9", "Verdichtung Planum Ev2>=45 MN/m2 (Subgrade compaction)", "m2", 5400, 5.20, {"din276": "310"}),
                ("310.10", "Baustrasse Schottertragschicht 0/45 (Haul road)", "m2", 1200, 29.50, {"din276": "310"}),
            ],
        ),
        # ── KG 322 Flachgruendungen / Bodenplatte ─────────────────────
        (
            "322",
            "KG 322 - Flachgruendungen / Bodenplatte",
            {"din276": "322"},
            [
                ("322.1", "Sauberkeitsschicht C8/10, d=8cm (Blinding concrete)", "m2", 5400, 13.50, {"din276": "322"}),
                ("322.2", "Frischbetonverbundabdichtung FBV unter Platte (FBV membrane)", "m2", 5400, 26.50, {"din276": "322"}),
                ("322.3", "Einzelfundamente Stuetzen C30/37 (Column pad footings)", "m3", 480, 168.00, {"din276": "322"}),
                ("322.4", "Schalung Fundamente Rahmenschalung (Footing formwork)", "m2", 640, 41.00, {"din276": "322"}),
                ("322.5", "Bodenplatte WU-Beton C30/37, d=40cm, XC4/XD3 (RC raft slab)", "m3", 2160, 158.00, {"din276": "322"}),
                ("322.6", "Bewehrung Bodenplatte BSt 500 B, 145 kg/m3 (Slab reinforcement)", "t", 313, 1480.00, {"din276": "322"}),
                ("322.7", "Randschalung Bodenplatte (Edge formwork to raft)", "m2", 460, 38.00, {"din276": "322"}),
                ("322.8", "Arbeitsfugenbleche + Fugenband außen (WU joint waterbars)", "m", 980, 34.00, {"din276": "322"}),
                ("322.9", "Aufkantungen / Sockel Ortbeton (Upstands / kerbs)", "m3", 95, 285.00, {"din276": "322"}),
                ("322.10", "Perimeterdaemmung XPS 120mm (Perimeter insulation)", "m2", 1450, 46.00, {"din276": "322"}),
            ],
        ),
        # ── KG 331 Tragende Aussenwaende - Schalung & Beton ──────────
        (
            "331",
            "KG 331 - Tragende Aussenwaende (Schalung/Beton)",
            {"din276": "331"},
            [
                ("331.1", "Schalung Aussenwand Rahmenschalung 25cm, beidseitig (Wall framed formwork)", "m2", 9200, 33.50, {"din276": "331"}),
                ("331.2", "Schalung Wandanschluss / Ankerstellen DIN 18218 (Tie / anchor points)", "pcs", 4600, 6.80, {"din276": "331"}),
                ("331.3", "Schalhaut sichtbeton-tauglich SB2 Zuschlag (Fair-faced facing surcharge)", "m2", 2400, 9.50, {"din276": "331"}),
                ("331.4", "Stahlbeton Aussenwand C30/37, d=25cm, XC4/XF4 (RC external wall)", "m3", 1150, 152.00, {"din276": "331"}),
                ("331.5", "Bewehrung Aussenwaende BSt 500 B, ~95 kg/m3 (Wall reinforcement)", "t", 109, 1520.00, {"din276": "331"}),
                ("331.6", "Aussparungen / Kastenaussparungen Wand (Wall box-outs)", "pcs", 180, 48.00, {"din276": "331"}),
                ("331.7", "Betoniergeruest / Arbeitsbuehne Wand (Wall working platform)", "m2", 2300, 18.50, {"din276": "331"}),
                ("331.8", "Bruestungen Parkdeck Ortbeton h=1,10m (RC parapet upstands)", "m3", 320, 198.00, {"din276": "331"}),
                ("331.9", "Schalung Bruestungen beidseitig (Parapet formwork)", "m2", 5800, 36.00, {"din276": "331"}),
                ("331.10", "Anschlussbewehrung / Schraubmuffen (Coupler starter bars)", "pcs", 2400, 12.50, {"din276": "331"}),
            ],
        ),
        # ── KG 333 Aussenstuetzen - Schalung & Beton ─────────────────
        (
            "333",
            "KG 333 - Aussenstuetzen (Schalung/Beton)",
            {"din276": "333"},
            [
                ("333.1", "Stuetzenschalung Rundstuetze d=40cm, Kartonschalung (Round column formwork)", "m2", 1180, 52.00, {"din276": "333"}),
                ("333.2", "Stuetzenschalung Rechteck 40x40, Stuetzenklappschalung (Rect. column formwork)", "m2", 860, 44.00, {"din276": "333"}),
                ("333.3", "Stahlbeton Stuetzen C45/55, XC4/XD3 (RC columns high-grade)", "m3", 410, 218.00, {"din276": "333"}),
                ("333.4", "Bewehrung Stuetzen BSt 500 B, ~220 kg/m3 (Column reinforcement)", "t", 90, 1620.00, {"din276": "333"}),
                ("333.5", "Stuetzenfuesse / Schwertanschluss (Column base fixings)", "pcs", 168, 95.00, {"din276": "333"}),
                ("333.6", "Anprallschutz Stuetzen Stahl (Column impact protection)", "pcs", 168, 280.00, {"din276": "333"}),
                ("333.7", "Stuetzenkopf-Verstaerkung / Pilzkopf Schalung (Column head drop formwork)", "pcs", 84, 145.00, {"din276": "333"}),
            ],
        ),
        # ── KG 341 Tragende Innenwaende / Kerne - Kletterschalung ────
        (
            "341",
            "KG 341 - Tragende Innenwaende / Kerne (Kletterschalung)",
            {"din276": "341"},
            [
                ("341.1", "Selbstkletterschalung Kerne SKE, Auf-/Abbau + Vorhaltung (Self-climbing formwork cores)", "m2", 3600, 78.00, {"din276": "341"}),
                ("341.2", "Schalung Innenwaende Traegerschalung, d=30cm (Girder wall formwork)", "m2", 6400, 31.50, {"din276": "341"}),
                ("341.3", "Stahlbeton Kernwaende C35/45, d=30cm (RC core walls)", "m3", 980, 162.00, {"din276": "341"}),
                ("341.4", "Stahlbeton Innenwaende C30/37, d=25cm (RC internal walls)", "m3", 640, 150.00, {"din276": "341"}),
                ("341.5", "Bewehrung Kerne + Innenwaende BSt 500 B, ~110 kg/m3 (Reinforcement)", "t", 178, 1520.00, {"din276": "341"}),
                ("341.6", "Klettergeruest / Klettersteg Absturzsicherung DGUV 101-008 (Climbing access / edge prot.)", "m2", 1200, 28.00, {"din276": "341"}),
                ("341.7", "Aussparungen Kern Tueren/Schaechte (Core openings doors/shafts)", "pcs", 96, 88.00, {"din276": "341"}),
                ("341.8", "Schalankerstellen wasserdicht verschließen (Tie-hole sealing WU)", "pcs", 3800, 4.20, {"din276": "341"}),
                ("341.9", "Betonpumpe Hochdruck Kern, Vorhaltung (High-rise concrete pump standing time)", "day", 42, 1250.00, {"din276": "341"}),
            ],
        ),
        # ── KG 351 Decken - Deckenschalung & Beton ───────────────────
        (
            "351",
            "KG 351 - Decken (Deckenschalung/Beton)",
            {"din276": "351"},
            [
                ("351.1", "Deckenschalung Deckentische, h bis 3,20m (Slab table formwork)", "m2", 20400, 29.50, {"din276": "351"}),
                ("351.2", "Deckenschalung Traegerschalung Rand-/Restflaechen (Beam-girder slab formwork)", "m2", 4800, 34.00, {"din276": "351"}),
                ("351.3", "Stahlbeton Flachdecke C30/37, d=30cm, XC4/XD1 (RC flat slab)", "m3", 6720, 148.00, {"din276": "351"}),
                ("351.4", "Bewehrung Decken BSt 500 B, ~130 kg/m3 (Slab reinforcement)", "t", 874, 1480.00, {"din276": "351"}),
                ("351.5", "Unterzuege Ortbeton C35/45 b/h=40/70 (RC downstand beams)", "m3", 720, 175.00, {"din276": "351"}),
                ("351.6", "Schalung Unterzuege dreiseitig (Beam formwork three-sided)", "m2", 5400, 38.00, {"din276": "351"}),
                ("351.7", "Durchstanzbewehrung Duebelleisten Stuetzen (Punching shear rails)", "pcs", 168, 320.00, {"din276": "351"}),
                ("351.8", "Aussparungen Decke / Schalungskoerper (Slab penetrations / formers)", "pcs", 420, 42.00, {"din276": "351"}),
                ("351.9", "Deckenrandabschalung magnetisch (Magnetic slab edge formwork)", "m", 4200, 9.80, {"din276": "351"}),
                ("351.10", "Betonnachbehandlung Curing nach DIN EN 13670 (Concrete curing)", "m2", 22600, 2.40, {"din276": "351"}),
                ("351.11", "Gefaelleestrich Parkdeck im Verbund 1,5% (Bonded fall screed)", "m2", 17800, 26.00, {"din276": "351"}),
            ],
        ),
        # ── KG 352 Traggerueste / Schalungszubehoer ──────────────────
        (
            "352",
            "KG 352 - Traggerueste / Schalungszubehoer (DIN EN 12812)",
            {"din276": "352"},
            [
                ("352.1", "Traggeruest Deckenstuetzen Eurex, Auf-/Abbau (Falsework props erect/strip)", "m2", 25200, 8.50, {"din276": "352"}),
                ("352.2", "Lasttuerme fuer hohe Geschosshoehe (Shoring towers high storeys)", "pcs", 320, 145.00, {"din276": "352"}),
                ("352.3", "Vorhaltung Schalung/Traggeruest je Betonierabschnitt (Standing time per pour)", "month", 16, 38000.00, {"din276": "352"}),
                ("352.4", "Schalungsumsetzen / Kran-Umsetztakt Decken (Crane re-positioning cycles)", "each", 24, 4200.00, {"din276": "352"}),
                ("352.5", "Trennmittel / Schalungsoel umweltvertraeglich (Release agent)", "l", 6800, 4.80, {"din276": "352"}),
                ("352.6", "Distanzhalter / Abstandhalter Bewehrung (Rebar spacers)", "pcs", 48000, 0.42, {"din276": "352"}),
                ("352.7", "Schalungsreinigung und Instandhaltung (Formwork cleaning/maintenance)", "month", 16, 6500.00, {"din276": "352"}),
                ("352.8", "Mietgeruest Fassadengeruest Last-/Schutzklasse (Facade scaffold rental)", "m2", 6400, 14.50, {"din276": "352"}),
            ],
        ),
        # ── KG 359 Sonstige Konstruktion / Fugen ─────────────────────
        (
            "359",
            "KG 359 - Sonstige Konstruktion / Fugen",
            {"din276": "359"},
            [
                ("359.1", "Dehnfugen Parkdeck mit Fugenprofil (Expansion joints to deck)", "m", 480, 165.00, {"din276": "359"}),
                ("359.2", "Scheinfugen / Sollrissstellen schneiden (Saw-cut control joints)", "m", 1850, 14.00, {"din276": "359"}),
                ("359.3", "Schwindgassen / Pour-Strips bewehrt (Reinforced pour strips)", "m", 620, 58.00, {"din276": "359"}),
                ("359.4", "Elastomerlager Unterzug/Stuetze (Elastomeric bearings)", "pcs", 96, 285.00, {"din276": "359"}),
                ("359.5", "Brandschutzbeschichtung exponierte Bewehrung (Fire coating to exposed rebar)", "m2", 1200, 38.00, {"din276": "359"}),
                ("359.6", "Probekoerper / Wuerfeldruckpruefung DIN EN 12390 (Cube test specimens)", "pcs", 360, 28.00, {"din276": "359"}),
                ("359.7", "Betonprüfung frisch (Konsistenz/Luftgehalt) (Fresh-concrete testing)", "each", 280, 65.00, {"din276": "359"}),
            ],
        ),
        # ── KG 363 Dachkonstruktion / oberstes Parkdeck ──────────────
        (
            "363",
            "KG 363 - Dachkonstruktion / oberstes Parkdeck",
            {"din276": "363"},
            [
                ("363.1", "Stahlbeton-Dachdecke oberstes Parkdeck C35/45, XF4 (RC top deck XF4)", "m3", 920, 162.00, {"din276": "363"}),
                ("363.2", "Deckenschalung oberstes Parkdeck (Top-deck slab formwork)", "m2", 2900, 31.00, {"din276": "363"}),
                ("363.3", "Bewehrung Dachdecke BSt 500 B (Top-deck reinforcement)", "t", 124, 1480.00, {"din276": "363"}),
                ("363.4", "OS 11 rissueberbrueckende Beschichtung Parkdeck (OS-11 deck coating)", "m2", 2900, 58.00, {"din276": "363"}),
                ("363.5", "Gefaelledaemmung / Entwaesserung oberstes Deck (Falls + drainage)", "m2", 2900, 34.00, {"din276": "363"}),
                ("363.6", "Attika Ortbeton + Schalung (RC parapet + formwork)", "m", 320, 185.00, {"din276": "363"}),
                ("363.7", "Photovoltaik-Unterkonstruktion Dachdeck (PV mounting substructure)", "m2", 1800, 42.00, {"din276": "363"}),
            ],
        ),
        # ── KG 371 Treppen / Rampen Ortbeton ─────────────────────────
        (
            "371",
            "KG 371 - Treppen / Rampen (Ortbeton)",
            {"din276": "371"},
            [
                ("371.1", "Ortbetontreppe gewendelt, Treppenschalung (In-situ stair + formwork)", "pcs", 14, 6800.00, {"din276": "371"}),
                ("371.2", "Parkrampen Ortbeton C35/45 Spindelrampe (Spiral RC ramps)", "m3", 540, 188.00, {"din276": "371"}),
                ("371.3", "Schalung Rampen gekruemmt (Curved ramp formwork)", "m2", 2200, 56.00, {"din276": "371"}),
                ("371.4", "Bewehrung Treppen/Rampen BSt 500 B (Stair/ramp reinforcement)", "t", 78, 1560.00, {"din276": "371"}),
                ("371.5", "Treppenpodeste / Zwischenpodeste Ortbeton (Stair landings)", "m2", 320, 215.00, {"din276": "371"}),
                ("371.6", "Antirutschbeschichtung Rampen (Anti-slip ramp coating)", "m2", 1600, 32.00, {"din276": "371"}),
            ],
        ),
        # ── KG 359 Fertigteil-Ergaenzungen - use KG 379 ──────────────
        (
            "379",
            "KG 379 - Fertigteil-Ergaenzungen",
            {"din276": "379"},
            [
                ("379.1", "Fertigteil-Stuetzen UG ergaenzend (Precast columns basement)", "pcs", 48, 1450.00, {"din276": "379"}),
                ("379.2", "Fertigteil-Treppenlaeufe (Precast stair flights)", "pcs", 28, 2400.00, {"din276": "379"}),
                ("379.3", "Halbfertigteildecken Filigran Restflaechen (Filigree slab elements)", "m2", 1800, 64.00, {"din276": "379"}),
                ("379.4", "Montage / Verguss Fertigteile (Erection + grouting)", "lsum", 1, 58000.00, {"din276": "379"}),
            ],
        ),
        # ── KG 411 Entwaesserung Parkdeck ────────────────────────────
        (
            "411",
            "KG 411 - Entwaesserung Parkdeck",
            {"din276": "411"},
            [
                ("411.1", "Bodenablaeufe Parkdeck Edelstahl DN100 (SS deck gullies)", "pcs", 96, 320.00, {"din276": "411"}),
                ("411.2", "Entwaesserungsleitung Gusseisen SML DN150 (Cast-iron drainage)", "m", 1400, 62.00, {"din276": "411"}),
                ("411.3", "Leichtfluessigkeitsabscheider Klasse I (Oil separator class I)", "pcs", 2, 18500.00, {"din276": "411"}),
                ("411.4", "Hebeanlage Tiefpunkt (Sump pump station)", "pcs", 2, 5200.00, {"din276": "411"}),
                ("411.5", "Rinnen Schlitzrinne Parkdeck (Slot drainage channels)", "m", 320, 138.00, {"din276": "411"}),
            ],
        ),
        # ── KG 443 Elektro Rohbau / Erdung ───────────────────────────
        (
            "443",
            "KG 443 - Elektro Rohbau / Erdung",
            {"din276": "443"},
            [
                ("443.1", "Fundamenterder Banderder DIN 18014 (Foundation earth electrode)", "m", 1850, 14.50, {"din276": "443"}),
                ("443.2", "Potentialausgleich Bewehrung / Anschlussfahnen (Equipotential bonding)", "pcs", 96, 65.00, {"din276": "443"}),
                ("443.3", "Leerrohre / Elektroeinbauteile in Beton (Conduit cast in concrete)", "m", 4200, 6.80, {"din276": "443"}),
                ("443.4", "Aeussere Blitzschutzanlage Parkhaus (External lightning protection)", "lsum", 1, 32000.00, {"din276": "443"}),
            ],
        ),
        # ── KG 538 Aussenanlagen / Baustelleneinrichtung ─────────────
        (
            "538",
            "KG 538 - Baustelleneinrichtung / Aussenanlagen Konstruktion",
            {"din276": "538"},
            [
                ("538.1", "Turmdrehkran 60m, Vorhaltung + Betrieb (Tower crane standing + operation)", "month", 15, 16500.00, {"din276": "538"}),
                ("538.2", "Krangruendung / Kranfundament Ortbeton (Crane foundation)", "pcs", 2, 24000.00, {"din276": "538"}),
                ("538.3", "Baustelleneinrichtung Container / Versorgung (Site setup / welfare)", "month", 16, 8200.00, {"din276": "538"}),
                ("538.4", "Bauzaun / Verkehrssicherung (Hoarding / traffic management)", "m", 480, 28.00, {"din276": "538"}),
                ("538.5", "Asphalt Zufahrt / Stellplaetze Aussen (External asphalt access)", "m2", 1800, 46.00, {"din276": "538"}),
                ("538.6", "Schrankenanlage / Parkleitsystem Rohinstallation (Barrier / PGS rough-in)", "lsum", 1, 42000.00, {"din276": "538"}),
            ],
        ),
    ],
    markups=[
        ("Baustellengemeinkosten (BGK)", 9.0, "overhead", "direct_cost"),
        ("Allgemeine Geschaeftskosten (AGK)", 7.0, "overhead", "direct_cost"),
        ("Wagnis (W)", 2.5, "contingency", "direct_cost"),
        ("Gewinn (G)", 4.0, "profit", "direct_cost"),
        ("Mehrwertsteuer (MwSt.)", 19.0, "tax", "cumulative"),
    ],
    total_months=18,
    tender_name="Rohbau Schalung/Beton (RC structure & formwork)",
    tender_companies=[
        ("Doker Schalungstechnik GmbH", "vergabe@doker.de", 0.99),
        ("Wolff & Mueller Hoch- und Industriebau GmbH", "angebot@wolff-mueller.de", 1.03),
        ("Leonhard Weiss GmbH & Co. KG", "rohbau@leonhard-weiss.de", 1.01),
        ("Gottlob Brodbeck GmbH & Co. KG", "kalkulation@brodbeck-bau.de", 1.06),
    ],
    project_metadata={
        "address": "Industriestrasse 12, 70563 Stuttgart-Vaihingen",
        "client": "Stuttgarter Parkraum- und Immobilien GmbH",
        "architect": "Wulf Architekten",
        "structural_engineer": "Boll und Partner Tragwerksplanung",
        "gfa_m2": 20500,
        "parking_spaces": 612,
        "storeys": 7,
        "structure_system": "Ortbeton-Flachdecke mit Unterzuegen, Rundstuetzen, 2 SB-Kerne (Gleitschalung)",
        "concrete_grades": "C30/37 - C45/55",
        "exposure_classes": "XC4, XD3, XF4 (Streusalzbelastung)",
        "reinforcement": "BSt 500 B / 500 S (DIN 488)",
        "formwork_systems": "Rahmenschalung, Traegerschalung, Deckentische, Stuetzenschalung, Selbstkletterschalung",
        "standards": "DIN EN 1992-1-1, DIN EN 206/DIN 1045-2, DIN EN 13670/DIN 1045-3, DIN 18218, DIN EN 12812, VOB/C DIN 18331",
        "safety": "DGUV Information 101-008 (Schalungsarbeiten)",
        "permit_note": "Baugenehmigung Stadt Stuttgart, Baurechtsamt; Pruefstatik durch Pruefingenieur fuer Baustatik (PIB)",
        "sustainability": "PV-ready oberstes Deck, CEM II/III-Beton (CO2-reduziert), Bewehrung aus Recyclingstahl",
        "fresh_concrete_pressure": "Bemessung Schalungsdruck nach DIN 18218 (Steiggeschwindigkeit / Frischbetontemperatur)",
    },
    tender_packages=[
        (
            "Rohbau Schalung/Beton (RC structure & formwork)",
            "Schalung, Traggerueste, Bewehrung und Ortbeton - Bodenplatte bis oberstes Parkdeck",
            "evaluating",
            [
                ("Doker Schalungstechnik GmbH", "vergabe@doker.de", 0.99),
                ("Wolff & Mueller Hoch- und Industriebau GmbH", "angebot@wolff-mueller.de", 1.03),
                ("Leonhard Weiss GmbH & Co. KG", "rohbau@leonhard-weiss.de", 1.01),
                ("Gottlob Brodbeck GmbH & Co. KG", "kalkulation@brodbeck-bau.de", 1.06),
            ],
        ),
        (
            "Erd- und Verbauarbeiten (Earthworks & shoring)",
            "Aushub, Traegerbohlwand, Wasserhaltung",
            "open",
            [
                ("Max Wild GmbH", "tiefbau@max-wild.com", 0.98),
                ("Storz GmbH & Co. KG", "erdbau@storz-bau.de", 1.04),
            ],
        ),
    ],
)
