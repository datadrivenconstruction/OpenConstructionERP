# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Public showcase demo: Lebensmittelmarkt Heilbronn / Retail Market Heilbronn.

New-build single-storey food retail market with parking facilities in the
Wannenaecker commercial belt, Heilbronn-Boeckingen (DE). Ninth showcase
project on fresh installs (see ``SHOWCASE_DEMO_IDS``), backfilled
idempotently on every boot like the flagship. DIN 276:2018-12 cost frame,
GAEB-style LV structure, EUR, German locale. All companies are fictional
with descriptive generic names; the only real entity is the public building
authority.

Data layer
----------
The BOQ is assembled from two module-level tables so later passes only have
to touch the data, never the assembly logic:

* ``_VE_SECTIONS`` - the 16 priced procurement units (Vergabeeinheiten) that
  map 1:1 to LV sections (OZ scheme ``VE.subsection.position``). Budgets
  come from the reconciled DIN 276 cost plan; their sum is exactly
  7,905,000 EUR net (KG 200-600 minus the 185,000 EUR KG 220 connection
  fees, which are levied by the utilities and are not tendered works).
* ``_POSITIONS`` - the full LV, 303 positions across all 16 procurement
  units, grouped into thematic OZ subsections per Gewerk. Every section
  sums EXACTLY to its procurement-unit budget and every DIN 276 cost group
  (2nd level) sums EXACTLY to the reconciled cost plan; ``_build_sections``
  raises if either drifts by a cent.

Money contract (pinned by tests/unit/test_retail_market_heilbronn_demo.py)
--------------------------------------------------------------------------
Two exactness invariants hold simultaneously, to the cent:

* per LV section: position sum == procurement-unit budget;
* per DIN 276 cost group: position sum == reconciled KG plan (e.g. KG 320
  = 900,000 across VE-02 + VE-04 + VE-06, KG 440 = 1,060,000 across VE-16
  + VE-17, KG 530 = 130,000 in VE-19).

Quantities derive from the canonical building geometry (footprint
68 x 40 m = 2,720 m2, work area 2,774 m2 = footprint x 1.02, perimeter
216 m, 12 axes a 6.18 m -> 36 columns / 36 pocket foundations / 24 binders
/ 22 edge beams, slab 544 m3 = 2,720 x 0.20, facade balance 1,292 + 120 +
42 + 13.2 + 23.6 ~= 216 x 6.9, 660 PV modules a 440 Wp = 290 kWp, 112
stalls -> 952 m marking). Non-obvious derivations are documented inline.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.demo_packs._retail_heilbronn_geometry import CANONICAL_GEOMETRY
from app.core.demo_projects import DemoTemplate, SectionDef

# Canonical building geometry is the single source of truth for both the LV
# quantities below and the procedural 3D model emitted by
# ``app.scripts.gen_retail_heilbronn_assets``. It lives in a dependency-free
# companion module so the generator can import it offline (no DB engine), and
# is re-exported here so the bill and the model read identical numbers: element
# sums in the canonical BIM model equal the corresponding BOQ quantities to the
# unit (R-01..R-06 hold in 3D as well as in the bill).
__all__ = ["CANONICAL_GEOMETRY", "TEMPLATE"]

# (oz, description, unit, quantity, unit_rate_eur, din276_code)
_PositionRow = tuple[str, str, str, float, float, str]

# (section_ordinal, ve_id, section_title, primary_din276_kg, ve_budget_eur)
_VeSection = tuple[str, str, str, str, float]

_VE_SECTIONS: list[_VeSection] = [
    (
        "01",
        "VE-01",
        "LV 01 - Baustelleneinrichtung und Gemeinkosten (Site establishment and general items)",
        "390",
        150_000.00,
    ),
    ("02", "VE-02", "LV 02 - Erdbau und Erschliessung (Earthworks and site servicing)", "210", 365_000.00),
    (
        "04",
        "VE-04",
        "LV 04 - Rohbau: Gruendung, Bodenplatte, Industrieboden, Massivbau (Shell works)",
        "320",
        820_000.00,
    ),
    (
        "05",
        "VE-05",
        "LV 05 - Dach: Trapezblech, Daemmung, Abdichtung, RWA (Roof works incl. smoke vents)",
        "360",
        580_000.00,
    ),
    (
        "06",
        "VE-06",
        "LV 06 - Stahlbeton-Fertigteile und BSH-Binder (Precast RC frame and glulam binders)",
        "330",
        540_000.00,
    ),
    ("07", "VE-07", "LV 07 - Fassade: Sandwichpaneele, Laerchen-Lattung, Sockel (Facade works)", "330", 410_000.00),
    (
        "08",
        "VE-08",
        "LV 08 - Fenster, Tueren, Tore, Pfosten-Riegel-Fassade (Windows, doors, gates, curtain wall)",
        "330",
        250_000.00,
    ),
    (
        "09",
        "VE-09",
        "LV 09 - Innenausbau: Trockenbau, Fliesen, Maler, Innentueren, Decken (Interior fit-out)",
        "340",
        280_000.00,
    ),
    (
        "14",
        "VE-14",
        "LV 14 - HLS: Sanitaer, Waermepumpe, Fussbodenheizung, RLT (Mechanical services)",
        "410",
        630_000.00,
    ),
    (
        "15",
        "VE-15",
        "LV 15 - Kaeltetechnik CO2-Verbund und Kuehlmoebel (CO2 refrigeration and cabinets)",
        "470",
        830_000.00,
    ),
    (
        "16",
        "VE-16",
        "LV 16 - Elektrotechnik inkl. BMA und GLT (Electrical incl. fire alarm and automation)",
        "440",
        680_000.00,
    ),
    (
        "17",
        "VE-17",
        "LV 17 - PV 290 kWp, Batteriespeicher 135 kWh, Ladeinfrastruktur (PV, battery, EV charging)",
        "440",
        520_000.00,
    ),
    (
        "18",
        "VE-18",
        "LV 18 - Aussenanlagen, Stellplaetze, Entwaesserung (External works, parking, drainage)",
        "510",
        1_020_000.00,
    ),
    (
        "19",
        "VE-19",
        "LV 19 - Werbepylon, Einkaufswagen-Boxen, Anfahrschutz (Pylon, cart shelters, protection)",
        "530",
        130_000.00,
    ),
    (
        "20",
        "VE-20",
        "LV 20 - Ladeneinrichtung, Kassenzone, Backstation (Store fit-out, checkout, bake-off)",
        "610",
        560_000.00,
    ),
    (
        "21",
        "VE-21",
        "LV 21 - Pfandraumtechnik und sonstige Ausstattung (Reverse-vending room and equipment)",
        "690",
        140_000.00,
    ),
]

# Full LV: 303 positions across all 16 procurement units. Net unit rates,
# price level Heilbronn 2026. Quantities derive from the canonical building
# geometry (work area 2,774 m2, 36 pocket foundations, perimeter 216 m,
# slab 544 m3, ...), so the procedural 3D model and the BOQ stay
# quantity-consistent. Within each procurement unit the rows are grouped
# into thematic OZ subsections (second OZ segment); each subsection carries
# one DIN 276 cost-group bucket whose rows close EXACTLY on the reconciled
# KG plan share, so both the per-section budgets and the per-KG rollups are
# exact to the cent (see the module docstring for the full matrix).
_POSITIONS: dict[str, list[_PositionRow]] = {
    # LV 01 (KG 390 = 150,000.00). Provision periods follow the 9-month
    # construction window (W8 foundations to M7 VOB acceptance).
    "VE-01": [
        (
            "01.01.0010",
            "Baustelle einrichten und raeumen, An- und Abtransport Geraete (Site establishment and clearance incl. plant transport)",
            "lsum",
            1,
            28500.00,
            "390",
        ),
        # qty: site hoarding ~ plot frontage loop (118 + 80) x 2 ~= 396 m + gates/reserve = 420 m
        (
            "01.01.0020",
            "Bauzaun mobil h = 2,0 m, Vorhaltung 9 Monate (Mobile site fence 2.0 m, 9 months provision)",
            "m",
            420,
            21.50,
            "390",
        ),
        (
            "01.01.0030",
            "Bauzufahrt und Baustrasse Schotter, herstellen und rueckbauen (Gravel site access road, build and remove)",
            "m2",
            850,
            18.40,
            "390",
        ),
        (
            "01.01.0040",
            "Buero- und Sozialcontainer, Vorhaltung 9 Monate (Office and welfare containers, 9 months provision)",
            "pcs",
            6,
            2850.00,
            "390",
        ),
        (
            "01.01.0050",
            "Baustromversorgung inkl. Verteiler und Verbrauch (Site power supply incl. distribution and consumption)",
            "lsum",
            1,
            14800.00,
            "390",
        ),
        (
            "01.01.0060",
            "Bauwasseranschluss inkl. Verbrauch (Site water connection incl. consumption)",
            "lsum",
            1,
            6400.00,
            "390",
        ),
        (
            "01.01.0070",
            "Mobilkran- und Hebezeugvorhaltung fuer Fremdgewerke (Mobile crane and hoisting provision for other trades)",
            "lsum",
            1,
            12500.00,
            "390",
        ),
        (
            "01.01.0080",
            "Bauschild und bauzeitliche Verkehrssicherung (Site sign and temporary traffic safety measures)",
            "lsum",
            1,
            4850.00,
            "390",
        ),
        (
            "01.01.0090",
            "Baustellenbewachung und Kamerasystem (Site security and camera system)",
            "lsum",
            1,
            7900.00,
            "390",
        ),
        (
            "01.01.0100",
            "Bautrocknung und Winterbaumassnahmen (Construction drying and winter working measures)",
            "lsum",
            1,
            9200.00,
            "390",
        ),
        (
            "01.01.0110",
            "Baustellen-IT, Funk und Zutrittskontrolle (Site IT, radio and access control)",
            "lsum",
            1,
            3800.00,
            "390",
        ),
        ("01.01.0120", "Endreinigung und Uebergabe (Final cleaning and handover)", "m2", 2840, 2.80, "390"),
        (
            "01.01.0130",
            "Allgemeine Baustellengemeinkosten, Versicherungen, Bautagesberichte (General site overheads, insurances, daily reports)",
            "lsum",
            1,
            12328.00,
            "390",
        ),
    ],
    # LV 02 - subsections: 02.01 Herrichten (KG 210 = 35,000.00),
    # 02.02 nichtoeffentliche Erschliessung (KG 230 = 60,000.00),
    # 02.03 Erdbau (KG 310 share = 226,480.00; VE-04 carries the pit
    # excavation 43,520.00, together KG 310 = 270,000.00 exact),
    # 02.04 Unterbau (KG 320 share = 43,520.00 of the 900,000.00 group).
    "VE-02": [
        (
            "02.01.0010",
            "Baufeldfreimachung, Roden Bewuchs, Abbruch Kleinstrukturen (Site clearance, grubbing, removal of minor structures)",
            "lsum",
            1,
            9400.00,
            "210",
        ),
        # qty: topsoil strip over footprint 2,720 m2 x 0.25 m = 680 m3 (external topsoil is in VE-18)
        (
            "02.01.0020",
            "Oberbodenabtrag Baufeld d = 25 cm, in Mieten lagern (Topsoil strip building field 25 cm, stockpile on site)",
            "m3",
            680,
            8.90,
            "210",
        ),
        (
            "02.01.0030",
            "Schnurgeruest, Absteckung und Feinabsteckung Gebaeude (Batter boards, setting-out and fine staking)",
            "lsum",
            1,
            4200.00,
            "210",
        ),
        (
            "02.01.0040",
            "Kampfmittelsondierung und Freigabedokumentation Baufeld (UXO probing and clearance documentation)",
            "lsum",
            1,
            15348.00,
            "210",
        ),
        (
            "02.02.0010",
            "Hausanschluss Wasser DN 50 inkl. Graben und Wiederherstellung (Water service connection DN 50 incl. trench)",
            "m",
            38,
            145.00,
            "230",
        ),
        (
            "02.02.0020",
            "Hausanschluss Abwasser DN 200 bis Uebergabeschacht (Sewer service connection DN 200 to transfer chamber)",
            "m",
            46,
            210.00,
            "230",
        ),
        (
            "02.02.0030",
            "Leerrohrtrasse Strom und Telekom, Trafostation bis NSHV (Conduit route power and telecom, substation to main LV board)",
            "m",
            120,
            96.00,
            "230",
        ),
        (
            "02.02.0040",
            "Uebergabeschaechte DN 1000 inkl. Abdeckung Kl. D (Transfer chambers DN 1000 incl. class D covers)",
            "pcs",
            2,
            3400.00,
            "230",
        ),
        (
            "02.02.0050",
            "Loeschwasser- und Hydrantenleitung DN 100 auf dem Grundstueck (Fire-water and hydrant main DN 100 on the plot)",
            "m",
            85,
            240.00,
            "230",
        ),
        (
            "02.02.0060",
            "Pruefung, Spuelung, Desinfektion und Dokumentation Anschluesse (Testing, flushing, disinfection and records)",
            "lsum",
            1,
            6110.00,
            "230",
        ),
        (
            "02.03.0010",
            "Erdaushub Planum Bauwerk und Anlieferrampe, Kl. 3-5 (Bulk excavation to formation, building and dock ramp)",
            "m3",
            2100,
            11.20,
            "310",
        ),
        (
            "02.03.0020",
            "Liefern und Einbau gepruefte Auffuellung, lagenweise verdichtet (Supply and place certified fill, compacted in layers)",
            "m3",
            1650,
            26.40,
            "310",
        ),
        # qty: surplus = pits 3,400 (VE-04) + grading 2,100 - 600 re-used on site = 4,900 m3
        (
            "02.03.0030",
            "Abfuhr und Entsorgung Ueberschussmassen Z1.1 (Haul-off and disposal of surplus soil, class Z1.1)",
            "m3",
            4900,
            18.60,
            "310",
        ),
        (
            "02.03.0040",
            "Offene Wasserhaltung, Vorhaltung 12 Wochen (Open dewatering, 12 weeks provision)",
            "lsum",
            1,
            8900.00,
            "310",
        ),
        (
            "02.03.0050",
            "Boeschungen sichern, Folienabdeckung (Slope protection, sheeting cover)",
            "m2",
            980,
            6.40,
            "310",
        ),
        # qty: R-02 work area 2,774 m2 = footprint x 1.02
        (
            "02.03.0060",
            "Kalk-Zement-Stabilisierung Planum d = 30 cm (Lime-cement stabilisation of formation, 30 cm)",
            "m2",
            2774,
            16.80,
            "310",
        ),
        (
            "02.03.0070",
            "Baustrassen-Unterhaltung waehrend Erdbau (Maintenance of site roads during earthworks)",
            "lsum",
            1,
            2900.00,
            "310",
        ),
        (
            "02.03.0080",
            "Plattendruckversuche und Verdichtungsnachweise (Plate-load tests and compaction verification)",
            "lsum",
            1,
            3584.80,
            "310",
        ),
        # qty: R-02 work area 2,774 m2
        (
            "02.04.0010",
            "Kapillarbrechende Kiesschicht 0/32, d = 15 cm (Capillary-breaking gravel layer 0/32, 15 cm)",
            "m2",
            2774,
            12.40,
            "320",
        ),
        (
            "02.04.0020",
            "Geotextil-Trennvlies GRK 4 inkl. Randanschluesse (Geotextile separation fleece GRK 4 incl. edge details)",
            "lsum",
            1,
            9122.40,
            "320",
        ),
    ],
    "VE-04": [
        (
            "04.01.0010",
            "Aushub Baugrube und Fundamente, Boden Kl. 3-5, seitlich lagern (Excavation pits and foundations, on-site storage)",
            "m3",
            3400,
            12.80,
            "310",
        ),
        (
            "04.01.0020",
            "Bodenaustausch / Tragschicht 0/45 unter Bodenplatte, d = 40 cm, verdichtet (Soil replacement / sub-base 0/45 under slab, 40 cm)",
            "m2",
            2774,
            14.20,
            "320",
        ),
        ("04.01.0030", "Sauberkeitsschicht C12/15, d = 5 cm (Blinding layer C12/15, 5 cm)", "m2", 2774, 9.40, "320"),
        (
            "04.01.0040",
            "Koecherfundamente 1,80 x 1,80 x 1,00 m, C25/30, inkl. Schalung und Aussparung (Pocket foundations 1.8 x 1.8 x 1.0 m C25/30)",
            "pcs",
            36,
            1480.00,
            "320",
        ),
        (
            "04.01.0050",
            "Frostschuerze umlaufend, h = 80 cm, C25/30 (Perimeter frost skirt 80 cm C25/30)",
            "m",
            216,
            96.00,
            "320",
        ),
        (
            "04.01.0060",
            "Betonstahl B500B Fundamente und Frostschuerze, liefern und verlegen (Rebar B500B foundations and skirt)",
            "t",
            38,
            1380.00,
            "320",
        ),
        (
            "04.01.0070",
            "PE-Folie Trennlage 2-lagig unter Bodenplatte (PE separation layer, 2-ply)",
            "m2",
            2774,
            2.10,
            "320",
        ),
        (
            "04.01.0080",
            "XPS-Daemmung 120 mm unter Bodenplatte, Heizzone, druckfest (XPS insulation 120 mm under slab, heated zone)",
            "m2",
            1750,
            28.50,
            "320",
        ),
        (
            "04.01.0090",
            "Bodenplatte C25/30 (RC-Beton), d = 20 cm, inkl. Einbau und Abziehen (Ground slab C25/30 recycled aggregate, 20 cm)",
            "m3",
            544,
            178.00,
            "320",
        ),
        (
            "04.01.0100",
            "Betonstahl B500B Bodenplatte inkl. Randzonenbewehrung (Rebar B500B ground slab incl. edge zones)",
            "t",
            49,
            1350.00,
            "320",
        ),
        (
            "04.01.0110",
            "Industrieboden: Hartstoffeinstreuung, monolithisch geglaettet, Fugenschnitt und Verguss (Industrial floor: dry-shake topping, power-floated, joints)",
            "m2",
            2400,
            24.50,
            "320",
        ),
        (
            "04.01.0120",
            "Grundleitungen DN 100 - DN 150 unter Bodenplatte inkl. Dichtheitspruefung DIN EN 1610 (Below-slab drainage DN100-150 incl. tightness test)",
            "m",
            380,
            88.00,
            "320",
        ),
        (
            "04.01.0130",
            "Bodeneinlaeufe, Pumpensumpf, Revisionsschaechte komplett (Floor drains, sump, inspection chambers)",
            "lsum",
            1,
            18600.00,
            "320",
        ),
        (
            "04.01.0140",
            "Stahlbeton-Wandscheiben Aussteifung, C30/37, inkl. Schalung (RC shear walls C30/37 incl. formwork)",
            "m3",
            36,
            580.00,
            "330",
        ),
        (
            "04.01.0150",
            "Massivbau Sozialtrakt und Technikraeume, komplett (Masonry/RC staff and plant rooms, complete)",
            "lsum",
            1,
            76900.20,
            "340",
        ),
        # 04.02 Rampen, Sockel und Ergaenzungen Bodenplatte (KG 320). VE-04
        # carries 645,600.00 of KG 320; with VE-02 (43,520.00) and VE-06
        # (210,880.00) the group closes on 900,000.00 exact.
        (
            "04.02.0010",
            "WU-Beton Rampenwaende Anlieferung C25/30 inkl. Schalung (Watertight RC dock ramp walls C25/30 incl. formwork)",
            "m3",
            48,
            640.00,
            "320",
        ),
        (
            "04.02.0020",
            "Betonstahl B500B Rampenwaende und Aufkantungen (Rebar B500B ramp walls and upstands)",
            "t",
            6,
            1420.00,
            "320",
        ),
        (
            "04.02.0030",
            "Grube Ueberladebruecke inkl. Randwinkel und Entwaesserung (Dock leveller pit incl. edge angles and drainage)",
            "pcs",
            1,
            8400.00,
            "320",
        ),
        # qty: R-03 perimeter 216 m
        (
            "04.02.0040",
            "Randschalung Bodenplatte inkl. Hoehenjustierung (Slab edge formwork incl. level adjustment)",
            "m",
            216,
            24.50,
            "320",
        ),
        (
            "04.02.0050",
            "Dehnfugenprofile Schwerlast einbauen (Heavy-duty expansion joint profiles, installed)",
            "m",
            120,
            86.00,
            "320",
        ),
        (
            "04.02.0060",
            "Fugenprofile Edelstahl Sichtbereiche (Stainless joint profiles in visible areas)",
            "m",
            60,
            64.00,
            "320",
        ),
        # qty: R-03 perimeter 216 m
        (
            "04.02.0070",
            "Sockel- und Perimeterabdichtung Bitumendickbeschichtung (Plinth and perimeter waterproofing, thick bitumen coating)",
            "m",
            216,
            32.50,
            "320",
        ),
        (
            "04.02.0080",
            "Aussparungen, Einbauteile, Leerrohre und Huelsen Bodenplatte (Recesses, cast-in items, conduits and sleeves in slab)",
            "lsum",
            1,
            9800.00,
            "320",
        ),
        (
            "04.02.0090",
            "Industrieboden Oberflaechenhaertung und Versiegelung, Zulage (Industrial floor surface hardening and sealing, extra-over)",
            "m2",
            2400,
            3.20,
            "320",
        ),
        # qty: R-01 footprint 2,720 m2
        ("04.02.0100", "Betonnachbehandlung Bodenplatte (Concrete curing of ground slab)", "m2", 2720, 1.20, "320"),
        (
            "04.02.0110",
            "Gefaelle- und Ausgleichsestrich Technik- und Nassbereiche (Sloped and levelling screed, plant and wet areas)",
            "m2",
            140,
            38.50,
            "320",
        ),
        (
            "04.02.0120",
            "Stundenlohnarbeiten Rohbau, Kernbohrungen und Anpassarbeiten (Daywork shell, core drilling and adaptations)",
            "lsum",
            1,
            23909.20,
            "320",
        ),
        # 04.03 Massivbau-Ergaenzungen: the mezzanine deck is the VE-04
        # share of KG 350 (28,800.00; VE-09 carries 81,200.00 -> 110,000.00
        # exact); the lintel row closes the VE-04 share of KG 340 on
        # 81,200.00 (VE-09 carries 198,800.00 -> 280,000.00 exact).
        (
            "04.03.0010",
            "Technik-Mezzanin 120 m2: Spannbeton-Hohldielen d = 20 cm inkl. Aufbeton (Plant mezzanine 120 m2: hollow-core slabs 20 cm incl. topping)",
            "m2",
            120,
            240.00,
            "350",
        ),
        (
            "04.03.0020",
            "Stuerze, Ringanker und Aussparungen Massivbau (Lintels, ring beams and openings in masonry works)",
            "lsum",
            1,
            4299.80,
            "340",
        ),
    ],
    "VE-05": [
        (
            "05.01.0010",
            "Stahltrapezprofil 160/250, t = 1,0 mm, als Dachtragschale inkl. Befestigung (Trapezoidal steel deck 160/250, 1.0 mm)",
            "m2",
            2774,
            31.50,
            "360",
        ),
        ("05.01.0020", "Dampfsperre bituminoes, vollflaechig (Bituminous vapour barrier)", "m2", 2774, 6.80, "360"),
        (
            "05.01.0030",
            "PIR-Gefaelledaemmung 200-260 mm, WLG 023 (PIR tapered insulation 200-260 mm)",
            "m2",
            2774,
            52.00,
            "360",
        ),
        (
            "05.01.0040",
            "FPO-Dachbahn, mechanisch befestigt, inkl. An- und Abschluesse (FPO membrane, mechanically fixed)",
            "m2",
            2774,
            28.40,
            "360",
        ),
        (
            "05.01.0050",
            "Attika-Abdeckung Aluminium inkl. Unterkonstruktion (Aluminium parapet capping)",
            "m",
            216,
            68.00,
            "360",
        ),
        (
            "05.01.0060",
            "Lichtkuppeln 1,5 x 1,5 m als NRWG nach DIN 18232, elektrisch 24 V, inkl. Aufsetzkranz (Rooflights 1.5 x 1.5 m as smoke vents per DIN 18232)",
            "pcs",
            8,
            4950.00,
            "360",
        ),
        (
            "05.01.0070",
            "Dachgullys DN 100 beheizt und Notueberlaeufe (Heated roof drains DN100 and emergency overflows)",
            "pcs",
            22,
            740.00,
            "360",
        ),
        (
            "05.01.0080",
            "Durchdringungen und Einfassungen fuer RLT, Kaelte, PV (Penetrations and flashings for HVAC, refrigeration, PV)",
            "lsum",
            1,
            12400.00,
            "360",
        ),
        (
            "05.01.0090",
            "Absturzsicherung Sekuranten umlaufend (Fall-arrest anchors along perimeter)",
            "pcs",
            28,
            290.00,
            "360",
        ),
        (
            "05.01.0100",
            "Blitzschutzanlage komplett inkl. Erdungsanlage und Potentialausgleich (Lightning protection complete incl. earthing)",
            "lsum",
            1,
            36028.20,
            "360",
        ),
        # 05.02 Daecher Ergaenzungen (KG 360). VE-05 carries 580,000.00 of
        # KG 360; with the VE-06 timber roof structure (210,000.00) the
        # group closes on 790,000.00 exact.
        # qty: portal width 24 m x 3 m canopy depth = 72 m2
        (
            "05.02.0010",
            "Vordach Eingang Stahlkonstruktion auskragend 24 x 3 m inkl. Abdichtung und Entwaesserung (Entrance canopy, cantilevered steel 24 x 3 m incl. waterproofing and drainage)",
            "m2",
            72,
            580.00,
            "360",
        ),
        # qty: R-03 perimeter 216 m
        (
            "05.02.0020",
            "Attika-Aufkantung Daemmung und Holzwerkstoff inkl. Befestigung (Parapet upstand insulation and timber-based board incl. fixing)",
            "m",
            216,
            84.00,
            "360",
        ),
        (
            "05.02.0030",
            "Dachrand- und Anschlussbleche Titanzink (Roof edge and flashing sheets, titanium-zinc)",
            "m",
            216,
            38.50,
            "360",
        ),
        # qty: wind edge and corner zones per DIN EN 1991-1-4 ~ 25 % of 2,774 m2 = 690 m2
        (
            "05.02.0040",
            "Windsogsicherung Verstaerkung Rand- und Eckzonen, Zulage (Wind uplift reinforcement edge and corner zones, extra-over)",
            "m2",
            690,
            6.80,
            "360",
        ),
        (
            "05.02.0050",
            "Gefaellekeile Kehlen und Grate, Zulage (Tapered crickets at valleys and ridges, extra-over)",
            "m",
            96,
            28.50,
            "360",
        ),
        (
            "05.02.0060",
            "Schaumglas-Daemmung druckfest Bereich Durchdringungen, Zulage (Compression-proof foam glass insulation at penetrations, extra-over)",
            "lsum",
            1,
            2400.00,
            "360",
        ),
        (
            "05.02.0070",
            "Wartungswege Plattenbelag begehbar (Walkable maintenance paths, paving slabs)",
            "m2",
            140,
            45.00,
            "360",
        ),
        # qty: 8 NRWG rooflights per the smoke-extraction concept (9.0 m2 aerodynamic)
        (
            "05.02.0080",
            "RWA-Steuerzentrale 24 V, Wind- und Regensensorik, Verkabelung 8 NRWG (Smoke vent control 24 V, wind and rain sensors, wiring for 8 NRWG)",
            "lsum",
            1,
            12800.00,
            "360",
        ),
        (
            "05.02.0090",
            "Anschluss Aufsetzkraenze Abdichtung, Zulage (Waterproofing connection to upstand kerbs, extra-over)",
            "pcs",
            8,
            380.00,
            "360",
        ),
        (
            "05.02.0100",
            "Durchsturzsicherung Lichtkuppeln, Gitter (Fall-through protection grids for rooflights)",
            "pcs",
            8,
            290.00,
            "360",
        ),
        (
            "05.02.0110",
            "Notabdichtungen Bauphase, Reinigung, Dichtheitspruefung und Dokumentation (Temporary seals during works, cleaning, leak test and records)",
            "lsum",
            1,
            21102.00,
            "360",
        ),
    ],
    # LV 06 - subsections: 06.01 Sockel und Gruendungsergaenzung (KG 320
    # share = 210,880.00), 06.02 Stuetzen und Attika-FT (KG 330 share =
    # 119,120.00; with VE-04 20,880.00, VE-07 410,000.00 and VE-08
    # 190,000.00 the group closes on 740,000.00), 06.03 Dachtragwerk
    # (KG 360 share = 210,000.00).
    "VE-06": [
        # qty: R-03 perimeter 216 m; precast socket panels between columns carry the facade base
        (
            "06.01.0010",
            "Stahlbeton-Sockelelemente FT h = 80 cm, tragend fuer Fassade, liefern und montieren (Precast RC socket panels 80 cm, load-bearing for facade, supply and erect)",
            "m",
            216,
            760.00,
            "320",
        ),
        # qty: R-06 = 36 pocket foundations, one grout joint per column
        (
            "06.01.0020",
            "Vergussmoertel Stuetzenfuesse Koecher C60/75 (Grouting of column feet in pockets, C60/75)",
            "pcs",
            36,
            240.00,
            "320",
        ),
        (
            "06.01.0030",
            "Perimeterdaemmung XPS d = 100 mm Sockelelemente (Perimeter insulation XPS 100 mm at socket panels)",
            "m",
            216,
            64.00,
            "320",
        ),
        (
            "06.01.0040",
            "Fugenabdichtung FT-Stoesse dauerelastisch (Flexible joint sealing of precast element joints)",
            "m",
            420,
            12.50,
            "320",
        ),
        (
            "06.01.0050",
            "Anschlussbewehrung, Einbauteile und Daemmstreifen Sockelelemente (Starter bars, cast-in items and insulation strips, socket panels)",
            "lsum",
            1,
            19006.00,
            "320",
        ),
        # qty: R-05 structural grid = 12 axes x 3 bearing rows = 36 columns
        (
            "06.02.0010",
            "FT-Stuetzen C40/50, 40/40 cm, h = 6,4 m, in Koecher versetzt (Precast columns C40/50, 40/40 cm, h = 6.4 m, set in pockets)",
            "pcs",
            36,
            2680.00,
            "330",
        ),
        # qty: portal parapet 7.50 m vs standard Attika 6.90 m over the 24 m entrance front
        (
            "06.02.0020",
            "FT-Attikaelemente Portal Eingangsseite, h = 60 cm (Precast parapet elements at entrance portal, 60 cm)",
            "m",
            24,
            420.00,
            "330",
        ),
        (
            "06.02.0030",
            "Bemusterung Sichtoberflaechen FT, Musterflaeche (Sampling of fair-faced precast surfaces, mock-up panel)",
            "lsum",
            1,
            1800.00,
            "330",
        ),
        (
            "06.02.0040",
            "Fugenverguss, Anschlussbewehrung und Montagematerial FT-Stuetzen (Joint grouting, starter bars and erection material for columns)",
            "lsum",
            1,
            10760.00,
            "330",
        ),
        # qty: R-05 = 12 main binders 23.8 m + 12 side binders 16.2 m
        (
            "06.03.0010",
            "BSH-Binder GL24h, b/h = 20/120 cm, l = 23,8 m, liefern und montieren (Glulam binders GL24h 20/120 cm, l = 23.8 m, supply and erect)",
            "pcs",
            12,
            7650.00,
            "360",
        ),
        (
            "06.03.0020",
            "BSH-Binder GL24h, l = 16,2 m, liefern und montieren (Glulam binders GL24h, l = 16.2 m, supply and erect)",
            "pcs",
            12,
            5650.00,
            "360",
        ),
        # qty: R-05 = (12 axes - 1) x 2 rows = 22 edge beams
        ("06.03.0030", "BSH-Randtraeger und Wechsel (Glulam edge beams and trimmers)", "pcs", 22, 1150.00, "360"),
        (
            "06.03.0040",
            "Dachverband Zugstaebe Stahl inkl. Anschlussbleche (Steel rod roof bracing incl. connection plates)",
            "lsum",
            1,
            8200.00,
            "360",
        ),
        (
            "06.03.0050",
            "Schwertransporte und Telekran-Einsatz Binder 23,8 m, Sondergenehmigungen (Heavy haulage and crane operations for 23.8 m binders incl. permits)",
            "lsum",
            1,
            12000.00,
            "360",
        ),
        (
            "06.03.0060",
            "Elastomer-Auflagerlager und Verbindungsmittel, komplett (Elastomeric bearings and fasteners, complete)",
            "lsum",
            1,
            4900.00,
            "360",
        ),
    ],
    # LV 07 (KG 330 share = 410,000.00).
    "VE-07": [
        # qty: R-04 facade balance, sandwich share 1,292 m2
        (
            "07.01.0010",
            "Sandwichpaneele MW-Kern 200 mm, U = 0,20, vertikal verlegt inkl. Befestigung (Sandwich panels mineral-wool core 200 mm, U = 0.20, vertical, incl. fixing)",
            "m2",
            1292,
            215.00,
            "330",
        ),
        (
            "07.01.0020",
            "Laerchenholz-Lattung vorgehaengt auf Alu-UK, Eingangsfassade (Larch battens, hung on aluminium subframe, entrance facade)",
            "m2",
            180,
            265.00,
            "330",
        ),
        (
            "07.01.0030",
            "Zulage Farbton nach Bemusterung, mikroprofilierte Oberflaeche (Extra-over for sampled colour, micro-profiled surface)",
            "m2",
            1292,
            12.50,
            "330",
        ),
        # qty: R-03 perimeter 216 m
        (
            "07.01.0040",
            "Sockelblech- und Anschlussprofile, Eckausbildungen (Plinth flashings, connection profiles and corner details)",
            "m",
            216,
            48.00,
            "330",
        ),
        # qty: 2 gates + 6 steel doors + 1 window band = 9 framed openings
        (
            "07.01.0050",
            "Oeffnungen herstellen, Wechselrahmen fuer Tore, Tueren und Fensterband (Forming openings, trimmer frames for gates, doors and window band)",
            "pcs",
            9,
            1150.00,
            "330",
        ),
        (
            "07.01.0060",
            "Fensterbankbleche und Leibungsverkleidungen (Sill flashings and reveal claddings)",
            "m",
            84,
            68.00,
            "330",
        ),
        (
            "07.01.0070",
            "Brandriegel und REI90-Anschluesse an Brandwaende (Fire barriers and REI90 connections to fire walls)",
            "lsum",
            1,
            6800.00,
            "330",
        ),
        # qty: R-04 envelope total ~ 216 m x 6.9 m = 1,490 m2
        ("07.01.0080", "Geruestvorhaltung Fassade (Facade scaffolding provision)", "m2", 1490, 9.80, "330"),
        (
            "07.01.0090",
            "Mock-up- und Bemusterungsflaeche Fassade 3 x 3 m (Facade mock-up and sampling area 3 x 3 m)",
            "lsum",
            1,
            2900.00,
            "330",
        ),
        (
            "07.01.0100",
            "Schutzfolien entfernen, Endreinigung Fassade (Removal of protective films, final facade cleaning)",
            "m2",
            1292,
            2.50,
            "330",
        ),
        (
            "07.01.0110",
            "Montagezugaben, Dichtbaender, Kleinstahl und Befestigungsmittel (Erection allowances, sealing tapes, minor steel and fixings)",
            "lsum",
            1,
            14408.00,
            "330",
        ),
    ],
    # LV 08 - subsections: 08.01 Fenster, Tueren, Tore (KG 330 share =
    # 190,000.00), 08.02 Verladetechnik und Einbauten (KG 370 = 60,000.00,
    # the only carrier of this group).
    "VE-08": [
        # qty: R-04 glazing share, curtain wall 24.0 x 5.0 m = 120 m2
        (
            "08.01.0010",
            "Pfosten-Riegel-Fassade Alu 24,0 x 5,0 m, Uw = 0,9, inkl. Verglasung (Aluminium curtain wall 24.0 x 5.0 m, Uw = 0.9, incl. glazing)",
            "m2",
            120,
            680.00,
            "330",
        ),
        (
            "08.01.0020",
            "Automatik-Schiebetueranlagen 2-fluegelig im Windfang (Automatic bi-parting sliding doors in the entrance lobby)",
            "pcs",
            2,
            12400.00,
            "330",
        ),
        # qty: R-04 window band 28.0 x 1.5 m = 42 m2
        (
            "08.01.0030",
            "Fensterband Alu 28,0 x 1,5 m, festverglast (Aluminium window band 28.0 x 1.5 m, fixed glazing)",
            "m2",
            42,
            540.00,
            "330",
        ),
        (
            "08.01.0040",
            "Sektionaltor 3,5 x 4,0 m ebenerdig, elektrisch (Sectional gate 3.5 x 4.0 m at grade, electric)",
            "pcs",
            1,
            8900.00,
            "330",
        ),
        (
            "08.01.0050",
            "Dock-Tor 3,0 x 3,2 m an der Andockstelle (Dock gate 3.0 x 3.2 m at the loading dock)",
            "pcs",
            1,
            7400.00,
            "330",
        ),
        (
            "08.01.0060",
            "Stahltueren T30/RC2 einfluegelig inkl. Beschlaege (Steel doors T30/RC2 single-leaf incl. hardware)",
            "pcs",
            6,
            2950.00,
            "330",
        ),
        (
            "08.01.0070",
            "Fluchttuersteuerung, Panikschloesser und E-Oeffner (Escape door control, panic locks and electric strikes)",
            "lsum",
            1,
            5200.00,
            "330",
        ),
        (
            "08.01.0080",
            "Beschlaege-Komplettierung, mechanische Schliessanlage (Hardware completion, mechanical master-key system)",
            "lsum",
            1,
            4200.00,
            "330",
        ),
        (
            "08.01.0090",
            "Glasreinigung und Einstellarbeiten zur Schlussabnahme (Glass cleaning and adjustment for final acceptance)",
            "lsum",
            1,
            1950.00,
            "330",
        ),
        (
            "08.01.0100",
            "Anschlussarbeiten, Abdichtung und Einstellung Fassadenelemente (Connection works, sealing and adjustment of facade elements)",
            "lsum",
            1,
            15570.00,
            "330",
        ),
        (
            "08.02.0010",
            "Ueberladebruecke hydraulisch 2,00 x 2,75 m, Tragkraft 60 kN (Hydraulic dock leveller 2.00 x 2.75 m, 60 kN capacity)",
            "pcs",
            1,
            14800.00,
            "370",
        ),
        (
            "08.02.0020",
            "Torabdichtung aufblasbar inkl. Anfahrpuffer und Radfuehrungen (Inflatable dock shelter incl. bumpers and wheel guides)",
            "pcs",
            1,
            6900.00,
            "370",
        ),
        # qty: 12 warehouse-zone columns plus 2 guards per gate frame ~ 24 guards
        (
            "08.02.0030",
            "Rammschutz innen Anlieferung und Lager, Stahlbuegel verzinkt (Interior impact protection delivery and warehouse, galvanised steel hoops)",
            "pcs",
            24,
            290.00,
            "370",
        ),
        (
            "08.02.0040",
            "Stahltreppe Technik-Mezzanin inkl. Gelaender (Steel stair to plant mezzanine incl. railing)",
            "pcs",
            1,
            9400.00,
            "370",
        ),
        (
            "08.02.0050",
            "Wartungsstege und Leiteranlagen Technikflaechen (Maintenance walkways and ladder systems, plant areas)",
            "lsum",
            1,
            21940.00,
            "370",
        ),
    ],
    # LV 09 - subsections: 09.01 Waende und Tueren (KG 340 share =
    # 198,800.00), 09.02 Boeden und Decken (KG 350 share = 81,200.00).
    "VE-09": [
        (
            "09.01.0010",
            "Trockenbauwaende Sozialtrakt und Bueros, doppelt beplankt, MW-Daemmung (Drywall partitions staff wing and offices, double-boarded, mineral wool)",
            "m2",
            640,
            92.00,
            "340",
        ),
        (
            "09.01.0020",
            "Brandwand REI90 Trennung Technikraum und Lager (Fire wall REI90 separating plant room and warehouse)",
            "m2",
            280,
            148.00,
            "340",
        ),
        # qty: room schedule staff wing (offices, WCs, break, changing, stores) = 18 doors
        (
            "09.01.0030",
            "Innentueren Holz mit Stahl-Umfassungszarge, teils Feuchtraum (Interior timber doors with steel frames, partly wet-room rated)",
            "pcs",
            18,
            980.00,
            "340",
        ),
        (
            "09.01.0040",
            "T30-RS-Tueren Technik- und LV-Raum (T30 smoke-control doors, plant and main LV room)",
            "pcs",
            4,
            2350.00,
            "340",
        ),
        (
            "09.01.0050",
            "Wandfliesen WC, Umkleiden und Backstation h = 2,0 m (Wall tiling WCs, changing rooms and bake-off, h = 2.0 m)",
            "m2",
            240,
            68.00,
            "340",
        ),
        (
            "09.01.0060",
            "Innenwandbekleidung Windfang und Kassenzone, HPL-Paneele (Interior wall cladding lobby and checkout zone, HPL panels)",
            "m2",
            95,
            145.00,
            "340",
        ),
        (
            "09.01.0070",
            "Vorsatzschalen und Installationswaende Nassbereiche (Furring and installation walls in wet areas)",
            "m2",
            120,
            78.00,
            "340",
        ),
        (
            "09.01.0080",
            "Eckschutzschienen und Rammschutz-Sockelleisten Flure (Corner guards and impact-protection skirtings, corridors)",
            "m",
            90,
            36.00,
            "340",
        ),
        (
            "09.01.0090",
            "Malerarbeiten Waende Innenbereich, Dispersion (Painting of interior walls, emulsion)",
            "m2",
            1850,
            9.80,
            "340",
        ),
        (
            "09.01.0100",
            "Beschlaege, Tuerstopper, Revisionsklappen und Kleinleistungen (Hardware, door stops, access panels and minor works)",
            "lsum",
            1,
            10615.00,
            "340",
        ),
        (
            "09.02.0010",
            "Zementestrich schwimmend Sozialtrakt (Floating cement screed, staff wing)",
            "m2",
            290,
            38.50,
            "350",
        ),
        # qty: room schedule break 32 + changing 24 + WCs 20 + offices 22 = 98 m2
        (
            "09.02.0020",
            "Bodenfliesen R10 Sozialraeume und WC inkl. Abdichtung (Floor tiling R10 staff rooms and WCs incl. waterproofing)",
            "m2",
            98,
            96.00,
            "350",
        ),
        (
            "09.02.0030",
            "Sauberlaufzone Eingang inkl. Edelstahlrahmen (Entrance matting zone incl. stainless frame)",
            "m2",
            24,
            320.00,
            "350",
        ),
        (
            "09.02.0040",
            "Abgehaengte Rasterdecke Sozialtrakt und Bueros (Suspended grid ceiling, staff wing and offices)",
            "m2",
            220,
            58.00,
            "350",
        ),
        (
            "09.02.0050",
            "Akustikdecke Kassenzone und Windfang (Acoustic ceiling, checkout zone and lobby)",
            "m2",
            180,
            84.00,
            "350",
        ),
        ("09.02.0060", "Revisionsoeffnungen Decke (Ceiling access openings)", "pcs", 12, 185.00, "350"),
        (
            "09.02.0070",
            "Sockelleisten, Uebergangsprofile und Restarbeiten Bodenbelaege (Skirtings, transition profiles and finishing works, floor coverings)",
            "lsum",
            1,
            22847.00,
            "350",
        ),
    ],
    "VE-14": [
        (
            "14.01.0010",
            "Luft/Wasser-Waermepumpe R290, 60 kW heizen / 75 kW kuehlen, inkl. hydraulischer Einbindung (Air/water heat pump R290 60/75 kW incl. hydraulics)",
            "pcs",
            1,
            58500.00,
            "420",
        ),
        (
            "14.01.0020",
            "Fussbodenheizung Vorlauf 35/28 Grad C inkl. Verteiler, gespeist aus Kaelte-Abwaerme (Underfloor heating 35/28 C incl. manifolds)",
            "m2",
            1650,
            31.00,
            "420",
        ),
        (
            "14.01.0030",
            "RLT-Geraet 11.500 m3/h, Rotations-WRG eta = 78 %, adiabate Kuehlung, auf Technik-Mezzanin (AHU 11,500 m3/h rotary heat recovery, adiabatic cooling)",
            "pcs",
            1,
            64800.00,
            "430",
        ),
        (
            "14.01.0040",
            "Lueftungskanaele verzinkt inkl. Daemmung und Brandschotts (Galvanised ductwork incl. insulation and firestopping)",
            "m2",
            980,
            38.50,
            "430",
        ),
        (
            "14.01.0050",
            "Tuerluftschleier Eingang 9 kW, WRG-gespeist (Entrance air curtain 9 kW, heat-recovery fed)",
            "pcs",
            1,
            6900.00,
            "430",
        ),
        (
            "14.01.0060",
            "Sanitaerinstallation komplett: WC-Anlagen, Sozialraeume, TWW-Speicher 300 l (Plumbing complete: WCs, staff rooms, 300 l DHW tank)",
            "lsum",
            1,
            48200.00,
            "410",
        ),
        # KG 430 with the air-side works: the central building automation
        # head end sits in VE-16 (KG 480 = 40,000.00 exact).
        (
            "14.01.0070",
            "Regelung und GLT-Schnittstellen HLS, Einregulierung, Abnahme (Controls and BMS interfaces HVAC, balancing, acceptance)",
            "lsum",
            1,
            22820.00,
            "430",
        ),
        # 14.02 Sanitaer Ergaenzungen (KG 410, VE-14 total 160,000.00).
        (
            "14.02.0010",
            "Schmutz- und Regenwasserleitungen im Gebaeude, SML/PE, inkl. Daemmung (Foul and rainwater pipework inside the building, cast iron/PE, insulated)",
            "m",
            360,
            64.00,
            "410",
        ),
        (
            "14.02.0020",
            "Trinkwasser-Installation Edelstahl press inkl. Daemmung und Spuelung (Potable water installation, pressed stainless, insulated and flushed)",
            "m",
            420,
            58.00,
            "410",
        ),
        # qty: R-11 = 11 roof gullies, one internal downpipe each
        (
            "14.02.0030",
            "Regenwasser-Fallleitungen innenliegend DN 100 inkl. Anschluss (Internal rainwater downpipes DN 100 incl. connection)",
            "pcs",
            11,
            1450.00,
            "410",
        ),
        (
            "14.02.0040",
            "Fettabscheider NS 4 Backstation inkl. Einbau (Grease separator NS 4 for bake-off incl. installation)",
            "pcs",
            1,
            8600.00,
            "410",
        ),
        # qty: fire concept = 4 wall hydrants type S
        (
            "14.02.0050",
            "Wandhydranten Typ S inkl. Leitungsnetz (Wall hydrants type S incl. pipe network)",
            "pcs",
            4,
            3900.00,
            "410",
        ),
        (
            "14.02.0060",
            "Wasserzaehleranlage, Feinfilter und Druckminderer (Water metering assembly, fine filter and pressure reducer)",
            "lsum",
            1,
            6200.00,
            "410",
        ),
        (
            "14.02.0070",
            "Brandschotts, Restdaemmung und Einweisung Sanitaer (Fire stopping, remaining insulation and instruction, plumbing)",
            "lsum",
            1,
            18050.00,
            "410",
        ),
        # 14.03 Heizung Ergaenzungen (KG 420, VE-14 total 250,000.00).
        (
            "14.03.0010",
            "Pufferspeicher 2.000 l WRG-Einbindung inkl. Armaturen (Buffer tank 2,000 l for heat-recovery integration incl. valves)",
            "pcs",
            1,
            12800.00,
            "420",
        ),
        (
            "14.03.0020",
            "Rohrnetz Heizung Verteilung Decke, Stahl/Verbundrohr (Heating distribution pipework at ceiling, steel/composite)",
            "m",
            380,
            72.00,
            "420",
        ),
        (
            "14.03.0030",
            "Daemmung Heizleitungen inkl. Armaturen (Insulation of heating pipework incl. valves)",
            "m",
            380,
            21.50,
            "420",
        ),
        (
            "14.03.0040",
            "Einbindung WRG Kaelteanlage, Waermetauscher und Regelventile (Integration of refrigeration heat recovery, exchangers and control valves)",
            "lsum",
            1,
            16400.00,
            "420",
        ),
        (
            "14.03.0050",
            "Nahwaermeleitung erdverlegt WP zu Technikzentrale, PEX DN 65 (Buried heat main, heat pump to plant room, PEX DN 65)",
            "m",
            45,
            320.00,
            "420",
        ),
        (
            "14.03.0060",
            "Aufstellung WP: Fundament, Schwingungsdaempfer, Schallschutzhaube (Heat pump installation: base, vibration dampers, acoustic hood)",
            "lsum",
            1,
            9800.00,
            "420",
        ),
        (
            "14.03.0070",
            "Heizkoerper und Konvektoren Nebenraeume (Radiators and convectors, ancillary rooms)",
            "pcs",
            14,
            640.00,
            "420",
        ),
        (
            "14.03.0080",
            "Einzelraumregelung FBH, Raumthermostate (Room-by-room underfloor heating control, thermostats)",
            "pcs",
            22,
            385.00,
            "420",
        ),
        (
            "14.03.0090",
            "Druckhaltung, MAG und Sicherheitsarmaturen (Pressurisation, expansion vessel and safety valves)",
            "lsum",
            1,
            6900.00,
            "420",
        ),
        (
            "14.03.0100",
            "Inbetriebnahme, hydraulischer Abgleich und Dokumentation Heizung (Commissioning, hydraulic balancing and records, heating)",
            "lsum",
            1,
            27090.00,
            "420",
        ),
        # 14.04 Lueftung Ergaenzungen (KG 430, VE-14 total 220,000.00).
        (
            "14.04.0010",
            "Brandschutz- und Jalousieklappen inkl. Ansteuerung (Fire and louvre dampers incl. actuation)",
            "pcs",
            18,
            640.00,
            "430",
        ),
        (
            "14.04.0020",
            "Wickelfalzrohr-Netz Nebenraeume inkl. Formteile (Spiral duct network ancillary rooms incl. fittings)",
            "m",
            240,
            52.00,
            "430",
        ),
        (
            "14.04.0030",
            "Luftdurchlaesse und Weitwurfduesen Verkaufsraum (Air diffusers and long-throw nozzles, sales area)",
            "pcs",
            42,
            285.00,
            "430",
        ),
        (
            "14.04.0040",
            "Abluftanlagen WC, Sozialraeume und Backstation (Extract systems WCs, staff rooms and bake-off)",
            "lsum",
            1,
            13800.00,
            "430",
        ),
        (
            "14.04.0050",
            "Aussenluft- und Fortluftgitter, Schalldaempfer (Outdoor and exhaust air louvres, attenuators)",
            "lsum",
            1,
            9400.00,
            "430",
        ),
        (
            "14.04.0060",
            "Splitgeraet Kuehlung LV- und Serverraum (Split cooling unit, main LV and server room)",
            "pcs",
            1,
            6800.00,
            "430",
        ),
        (
            "14.04.0070",
            "Einregulierung Luftmengen, Hygieneinspektion und IBN RLT (Air volume balancing, hygiene inspection and AHU commissioning)",
            "lsum",
            1,
            21780.00,
            "430",
        ),
    ],
    "VE-15": [
        (
            "15.01.0010",
            "Transkritische CO2-Booster-Verbundanlage mit Parallelverdichtung, NK 95 kW / TK 26 kW (Transcritical CO2 booster rack with parallel compression, MT 95 / LT 26 kW)",
            "lsum",
            1,
            148000.00,
            "470",
        ),
        (
            "15.01.0020",
            "Gaskuehler Dachaufstellung inkl. Stahlrahmen und Schwingungsdaempfung (Gas cooler roof-mounted incl. steel frame)",
            "pcs",
            1,
            18400.00,
            "470",
        ),
        (
            "15.01.0030",
            "Waermerueckgewinnung 2-stufig (Enthitzer + Kondensator) bis 120 kW thermisch (Two-stage heat recovery, desuperheater plus condenser, up to 120 kW)",
            "lsum",
            1,
            26500.00,
            "470",
        ),
        (
            "15.01.0040",
            "CO2-Rohrleitungsnetz K65/Edelstahl inkl. Daemmung und Halterung (CO2 piping network K65/stainless incl. insulation)",
            "m",
            420,
            96.00,
            "470",
        ),
        (
            "15.01.0050",
            "NK-Kuehlzelle +2 Grad C, ca. 45 m2, PU 100 mm, inkl. Tuer (Chiller cell +2 C, ~45 m2, PU 100 mm incl. door)",
            "pcs",
            1,
            12940.00,
            "470",
        ),
        (
            "15.01.0060",
            "Obst/Gemuese-Kuehlraum +8 Grad C, ca. 25 m2, PU 80 mm (Produce cool room +8 C, ~25 m2, PU 80 mm)",
            "pcs",
            1,
            7900.00,
            "470",
        ),
        (
            "15.01.0070",
            "TK-Zelle -22 Grad C, ca. 30 m2, PU 150 mm, inkl. Boden (Freezer room ~30 m2, PU 150 mm incl. floor)",
            "pcs",
            1,
            24500.00,
            "470",
        ),
        (
            "15.01.0080",
            "Luftkuehler/Verdampfer CO2-geeignet, Zellen (CO2 unit coolers for cold rooms)",
            "pcs",
            5,
            2950.00,
            "470",
        ),
        (
            "15.01.0090",
            "Anbindung Verbund-Kuehlmoebel (bauseits gestellt), Verrohrung und IBN (Connection of operator-supplied remote cabinets)",
            "pcs",
            14,
            1150.00,
            "470",
        ),
        (
            "15.01.0100",
            "CO2-Gaswarnanlage Maschinenraum/Verkaufsraum (CO2 gas detection system)",
            "lsum",
            1,
            7400.00,
            "470",
        ),
        # Refrigeration plant controls stay in the use-specific group
        # KG 470; the central building automation budget (KG 480) is
        # carried by VE-16.
        (
            "15.01.0110",
            "MSR/Anlagenregelung Kaelte, inkl. Fernueberwachung (Refrigeration controls incl. remote monitoring)",
            "lsum",
            1,
            13800.00,
            "470",
        ),
        (
            "15.01.0120",
            "Dichtheitspruefung, Inbetriebnahme, Abnahme EN 378, Einweisung (Pressure test, commissioning, EN 378 acceptance)",
            "lsum",
            1,
            8900.00,
            "470",
        ),
        # 15.02 Verbund-Kuehlmoebel und Komplettierung (KG 470; VE-15 is
        # the only carrier of the group, total 830,000.00 exact).
        # qty: cabinet layout = 48 lfm chilled (glass doors)
        (
            "15.02.0010",
            "NK-Kuehlregale steckerlos, Glastueren, H = 2,0 m, anschlussfertig an Verbund (Remote chilled multidecks, glass doors, H = 2.0 m, rack-ready)",
            "m",
            48,
            4980.00,
            "470",
        ),
        # qty: cabinet layout = 22 lfm frozen
        (
            "15.02.0020",
            "TK-Schrankmoebel Glastueren, Verbundanschluss (Remote glass-door freezer cabinets, rack-connected)",
            "m",
            22,
            6400.00,
            "470",
        ),
        # qty: cabinet layout = 6 lfm serve-over
        (
            "15.02.0030",
            "Bedientheke Frische 6 lfm inkl. Anbindung Maschinensatz (Serve-over fresh counter 6 lm incl. rack connection)",
            "m",
            6,
            7950.00,
            "470",
        ),
        # qty: 20 cabinet sections + 3 cold rooms + serve-over + spares ~ 26 control points
        (
            "15.02.0040",
            "Kuehlstellenregler, Fuehler und Busverkabelung (Case controllers, sensors and bus wiring)",
            "pcs",
            26,
            485.00,
            "470",
        ),
        (
            "15.02.0050",
            "Abtau- und Tauwasserleitungen isoliert bis Grundleitung (Insulated defrost and condensate pipework to below-slab drainage)",
            "m",
            180,
            86.00,
            "470",
        ),
        (
            "15.02.0060",
            "Schallschutzmassnahmen und Aufstellrahmen Verbundanlage (Acoustic measures and mounting frame for the rack)",
            "lsum",
            1,
            8900.00,
            "470",
        ),
        (
            "15.02.0070",
            "Wartungsvertrag Jahr 1 inkl. 24h-Bereitschaft (Maintenance contract year 1 incl. 24h standby)",
            "lsum",
            1,
            6800.00,
            "470",
        ),
        (
            "15.02.0080",
            "CO2-Erstbefuellung, Dichtheitsnachweis und Probebetrieb 72 h (Initial CO2 charge, leak verification and 72 h trial run)",
            "lsum",
            1,
            19160.00,
            "470",
        ),
    ],
    "VE-16": [
        (
            "16.01.0010",
            "NSHV 1.250 A inkl. Messung und Zaehlerplatz (Main LV board 1,250 A incl. metering)",
            "pcs",
            1,
            38400.00,
            "440",
        ),
        (
            "16.01.0020",
            "Kabeltrassen und Leitungsnetz komplett (Cable trays and wiring complete)",
            "m",
            1850,
            24.50,
            "440",
        ),
        (
            "16.01.0030",
            "LED-Lichtbandsystem Verkaufsraum 800 lx, DALI mit Tageslicht-/Praesenzregelung (LED light-band system sales area 800 lx, DALI daylight/presence control)",
            "m",
            539,
            142.00,
            "440",
        ),
        (
            "16.01.0040",
            "Beleuchtung Lager/Nebenraeume 300 lx und Sicherheitsbeleuchtung (Warehouse/ancillary lighting 300 lx and emergency lighting)",
            "lsum",
            1,
            28900.00,
            "440",
        ),
        (
            "16.01.0050",
            "Elektroinstallation Sozialtrakt, Unterverteilungen, Endgeraete (Electrical installation staff wing, sub-distribution boards)",
            "lsum",
            1,
            26040.00,
            "440",
        ),
        (
            "16.01.0060",
            "Brandmeldeanlage Kat. 2 mit Aufschaltung (Fire alarm system cat. 2 with monitoring link)",
            "lsum",
            1,
            24600.00,
            "450",
        ),
        (
            "16.01.0070",
            "Datennetz Cat 6A inkl. IT-Schrank und Patchfeld (Data network Cat 6A incl. IT cabinet)",
            "lsum",
            1,
            14800.00,
            "450",
        ),
        (
            "16.01.0080",
            "GLT/Gebaeudeautomation: Feldgeraete, Aufschaltung, Energiemonitoring ISO 50001-faehig (BMS field devices, integration, ISO 50001-ready energy monitoring)",
            "lsum",
            1,
            19322.00,
            "480",
        ),
        # 16.02 Starkstrom Ergaenzungen (KG 440 share = 540,000.00; with
        # VE-17 (520,000.00) the group closes on 1,060,000.00 exact).
        (
            "16.02.0010",
            "Kompakt-Trafostation 630 kVA inkl. MS-Schaltanlage und IBN (Compact transformer station 630 kVA incl. MV switchgear and commissioning)",
            "pcs",
            1,
            118000.00,
            "440",
        ),
        (
            "16.02.0020",
            "Unterverteilungen Markt, Technik und Kasse (Sub-distribution boards sales, plant and checkout)",
            "pcs",
            6,
            7400.00,
            "440",
        ),
        (
            "16.02.0030",
            "Installationsgeraete, Schalter, Steckdosen und CEE-Anschluesse (Wiring accessories, switches, sockets and CEE outlets)",
            "lsum",
            1,
            18600.00,
            "440",
        ),
        (
            "16.02.0040",
            "LED-Panels Nebenraeume und Sozialtrakt inkl. Praesenzmelder (LED panels ancillary rooms and staff wing incl. presence detectors)",
            "pcs",
            64,
            285.00,
            "440",
        ),
        (
            "16.02.0050",
            "Anschluss Maschinen und Anlagen: RLT, WP, Kaelte, Backoefen, Tore (Connection of plant: AHU, heat pump, refrigeration, ovens, gates)",
            "lsum",
            1,
            32400.00,
            "440",
        ),
        (
            "16.02.0060",
            "USV-Anlage 20 kVA Kassen- und IT-Versorgung (UPS 20 kVA for checkout and IT supply)",
            "pcs",
            1,
            24500.00,
            "440",
        ),
        (
            "16.02.0070",
            "Fassadenbeleuchtung und Anschluss Werbeanlagen (Facade lighting and connection of signage)",
            "lsum",
            1,
            12800.00,
            "440",
        ),
        (
            "16.02.0080",
            "Potentialausgleich, Erdung und Ueberspannungsschutz Typ 1+2 (Equipotential bonding, earthing and surge protection type 1+2)",
            "lsum",
            1,
            9800.00,
            "440",
        ),
        # qty: R-03 perimeter 216 m ring earth electrode
        (
            "16.02.0090",
            "Fundament- und Ringerder inkl. Anschlussfahnen (Foundation and ring earth electrode incl. connection lugs)",
            "m",
            216,
            14.50,
            "440",
        ),
        (
            "16.02.0100",
            "Leerrohre und Bodentanks Kassenzone (Conduits and floor boxes, checkout zone)",
            "lsum",
            1,
            7600.00,
            "440",
        ),
        (
            "16.02.0110",
            "Torsteuerungen und Tuerkommunikation Anlieferung anschliessen (Connection of gate controls and door intercom, delivery area)",
            "lsum",
            1,
            3400.00,
            "440",
        ),
        (
            "16.02.0120",
            "Messungen, Pruefungen DIN VDE, Beschriftung und Dokumentation (Measurements, DIN VDE testing, labelling and documentation)",
            "lsum",
            1,
            31925.00,
            "440",
        ),
        # 16.03 Sicherheits- und Kommunikationstechnik (KG 450, VE-16
        # total 100,000.00).
        (
            "16.03.0010",
            "Videoueberwachung 16 IP-Kameras inkl. Aufzeichnung (Video surveillance, 16 IP cameras incl. recording)",
            "pcs",
            16,
            1450.00,
            "450",
        ),
        (
            "16.03.0020",
            "Einbruchmeldeanlage Aussenhaut und Bueros (Intruder alarm, building envelope and offices)",
            "lsum",
            1,
            14200.00,
            "450",
        ),
        (
            "16.03.0030",
            "ELA- und Durchsageanlage Verkaufsraum (Public address system, sales area)",
            "lsum",
            1,
            9600.00,
            "450",
        ),
        (
            "16.03.0040",
            "Elektronische Schliessanlage und Zutrittskontrolle Personal (Electronic locking and staff access control)",
            "lsum",
            1,
            13600.00,
            "450",
        ),
        # 16.04 Gebaeudeautomation (KG 480, VE-16 total 40,000.00 exact).
        (
            "16.04.0010",
            "Energiezaehler M-Bus, 14 Messstellen, Aufschaltung (M-Bus energy meters, 14 metering points, integration)",
            "pcs",
            14,
            685.00,
            "480",
        ),
        (
            "16.04.0020",
            "GLT-Visualisierung, Trendaufzeichnung, Fernzugriff und Einweisung (BMS visualisation, trending, remote access and instruction)",
            "lsum",
            1,
            11088.00,
            "480",
        ),
    ],
    # LV 17 (KG 440 share = 520,000.00, owner direct award VP-11) -
    # subsections: 17.01 PV-Anlage, 17.02 Speicher und Netz, 17.03
    # Ladeinfrastruktur.
    "VE-17": [
        # qty: R-12 = 660 modules a 440 Wp = 290.4 kWp
        (
            "17.01.0010",
            "PV-Module 440 Wp, Ost-West-Aufstaenderung aerodynamisch (PV modules 440 Wp, aerodynamic east-west racking)",
            "pcs",
            660,
            285.00,
            "440",
        ),
        # qty: 60 % of the solar-suitable roof = 1,440 m2 (KlimaG BW duty)
        (
            "17.01.0020",
            "Unterkonstruktion und Ballastierung inkl. Bautenschutzmatten (Substructure and ballasting incl. protection mats)",
            "m2",
            1440,
            28.50,
            "440",
        ),
        (
            "17.01.0030",
            "Wechselrichter 25 kW inkl. DC-Ueberspannungsschutz (Inverters 25 kW incl. DC surge protection)",
            "pcs",
            10,
            4200.00,
            "440",
        ),
        (
            "17.01.0040",
            "DC-Verkabelung, Stringleitungen und Generatoranschlusskasten (DC cabling, string lines and generator junction box)",
            "lsum",
            1,
            12400.00,
            "440",
        ),
        (
            "17.01.0050",
            "Dachdurchfuehrungen DC-Leitungen inkl. Abdichtungskoordination (Roof penetrations for DC cabling incl. waterproofing coordination)",
            "pcs",
            6,
            420.00,
            "440",
        ),
        (
            "17.01.0060",
            "Erstreinigung Module und Kennlinien-Abnahmemessung (Initial module cleaning and IV-curve acceptance measurement)",
            "lsum",
            1,
            3200.00,
            "440",
        ),
        (
            "17.02.0010",
            "Batteriespeicher 135 kWh inkl. BMS und Anbindung (Battery storage 135 kWh incl. BMS and integration)",
            "pcs",
            1,
            86500.00,
            "440",
        ),
        (
            "17.02.0020",
            "NA-Schutz, Zaehlerwesen und Direktvermarktungs-Gateway (Grid protection, metering and direct-marketing gateway)",
            "lsum",
            1,
            14800.00,
            "440",
        ),
        (
            "17.02.0030",
            "Dynamisches Lastmanagement fuer Ladeinfrastruktur (Dynamic load management for EV charging)",
            "lsum",
            1,
            9800.00,
            "440",
        ),
        # qty: 2 DC chargers a 2 points + 4 AC wallboxes a 2 points = 12 charge points
        (
            "17.03.0010",
            "DC-Schnellladestation 150 kW mit 2 Ladepunkten (DC fast charger 150 kW with 2 charge points)",
            "pcs",
            2,
            28400.00,
            "440",
        ),
        ("17.03.0020", "AC-Wallboxen 22 kW (AC wallboxes 22 kW)", "pcs", 4, 2850.00, "440"),
        (
            "17.03.0030",
            "Tiefbau und Fundamente Ladestationen inkl. Schutzbuegel (Civils and foundations for chargers incl. protection hoops)",
            "lsum",
            1,
            16900.00,
            "440",
        ),
        # qty: GEIG pre-equipment for 38 stalls, conduit route 280 m
        (
            "17.03.0040",
            "Leerrohr- und Kabeltrasse GEIG, 38 Stellplaetze vorgeruestet (Conduit and cable route per GEIG, 38 stalls pre-equipped)",
            "m",
            280,
            36.00,
            "440",
        ),
        (
            "17.03.0050",
            "Anmeldung, Zertifikate VDE-AR-N 4110, Monitoring und Dokumentation (Registration, VDE-AR-N 4110 certificates, monitoring and records)",
            "lsum",
            1,
            24460.00,
            "440",
        ),
    ],
    "VE-18": [
        (
            "18.01.0010",
            "Oberbodenabtrag und Erdarbeiten Aussenanlagen (Topsoil strip and earthworks external areas)",
            "m3",
            2028,
            9.80,
            "510",
        ),
        (
            "18.01.0020",
            "Frostschutzschicht 0/45, d = 40 cm, fuer befestigte Flaechen (Frost protection layer 0/45, 40 cm)",
            "m2",
            4590,
            13.60,
            "520",
        ),
        (
            "18.01.0030",
            "Asphalttrag- und Deckschicht Fahrgassen und Anlieferhof (Asphalt base and wearing course, lanes and delivery yard)",
            "m2",
            3140,
            42.50,
            "520",
        ),
        (
            "18.01.0040",
            "Draen-Betonpflaster Stellplaetze, d = 10 cm, sickerfaehig (Permeable concrete pavers parking stalls, 10 cm)",
            "m2",
            1450,
            48.00,
            "520",
        ),
        ("18.01.0050", "Bordsteine und Einfassungen (Kerbs and edgings)", "m", 920, 28.50, "520"),
        (
            "18.01.0060",
            "Entwaesserungsrinnen und Hofablaeufe inkl. Anschluss (Drainage channels and yard gullies incl. connection)",
            "lsum",
            1,
            24800.00,
            "540",
        ),
        (
            "18.01.0070",
            "Rigole 190 m3 und Versickerungsmulden 350 m2 inkl. Drosselschacht 12 l/s (DWA-A 138) (Retention trench 190 m3 and infiltration swales 350 m2 incl. 12 l/s throttle)",
            "lsum",
            1,
            68500.00,
            "540",
        ),
        (
            "18.01.0080",
            "Zisterne 10 m3 inkl. Pumpentechnik fuer Bewaesserung (Cistern 10 m3 incl. pump for irrigation)",
            "pcs",
            1,
            9400.00,
            "540",
        ),
        (
            "18.01.0090",
            "Fahrbahn- und Stellplatzmarkierung inkl. Sonderflaechen (Lane and stall marking incl. special stalls)",
            "m",
            952,
            4.20,
            "520",
        ),
        (
            "18.01.0100",
            "Aussenbeleuchtung 14 LED-Mastleuchten h = 6 m, 3000 K insektenfreundlich, inkl. Kabel und Fundamente (External lighting 14 LED masts 6 m incl. cabling and foundations)",
            "pcs",
            14,
            2350.00,
            "540",
        ),
        (
            "18.01.0110",
            "Hochstamm-Baeume pflanzen inkl. Substrat und Verankerung (Standard trees incl. substrate and anchoring)",
            "pcs",
            19,
            980.00,
            "550",
        ),
        (
            "18.01.0120",
            "Strauch-/Rasenflaechen und Fassadenbegruenung (Shrub/lawn areas and green facade)",
            "m2",
            1720,
            12.50,
            "550",
        ),
        # 18.02 Erdbau Aussenanlagen (KG 510, VE-18 total 240,000.00).
        # qty: R-08 paved area 4,590 m2 x 0.6 m formation depth = 2,754 m3
        (
            "18.02.0010",
            "Kofferaushub befestigte Flaechen, d = 60 cm (Box excavation for paved areas, 60 cm)",
            "m3",
            2754,
            14.20,
            "510",
        ),
        (
            "18.02.0020",
            "Erdbau Profilierung Aussenanlagen, Auf- und Abtrag, Feinplanum (Earthworks profiling external areas, cut and fill, fine grading)",
            "m3",
            3200,
            12.40,
            "510",
        ),
        (
            "18.02.0030",
            "Entsorgung Ueberschussmassen Aussenanlagen Z1.1 (Disposal of surplus soil external works, class Z1.1)",
            "m3",
            2400,
            16.80,
            "510",
        ),
        (
            "18.02.0040",
            "Liefern und Einbau Fuellboden und Frostschutzmaterial (Supply and place fill and frost-protection material)",
            "m3",
            1850,
            24.60,
            "510",
        ),
        (
            "18.02.0050",
            "Leitungsgraeben Entwaesserung und Beleuchtung inkl. Verfuellung (Service trenches drainage and lighting incl. backfill)",
            "m",
            680,
            28.40,
            "510",
        ),
        # qty: R-09 green areas 1,950 m2 + swales 350 m2 = 2,300 m2
        (
            "18.02.0060",
            "Erdplanum und Verdichtung Pflanz- und Muldenbereiche (Formation and compaction, planting and swale areas)",
            "m2",
            2300,
            3.40,
            "510",
        ),
        # qty: Rigole 190 m3 net + working space and cover ~ 640 m3 excavation
        (
            "18.02.0070",
            "Baugruben Rigole und Zisterne ausheben und verfuellen (Excavation and backfill for retention trench and cistern)",
            "m3",
            640,
            18.50,
            "510",
        ),
        (
            "18.02.0080",
            "Verdichtungsnachweise, Feinplanum Restflaechen, bauzeitliche Entwaesserung (Compaction verification, fine grading of remaining areas, temporary drainage)",
            "lsum",
            1,
            16536.80,
            "510",
        ),
        # 18.03 Belaege Ergaenzungen (KG 520, VE-18 total 540,000.00).
        # qty: R-08 = asphalt 3,140 + pavers 1,450 = 4,590 m2
        (
            "18.03.0010",
            "Geogitter-Bewehrung Unterbau befestigte Flaechen (Geogrid reinforcement of paved-area sub-base)",
            "m2",
            4590,
            9.90,
            "520",
        ),
        (
            "18.03.0020",
            "Asphaltbinderschicht AC 16 BS, d = 6 cm (Asphalt binder course AC 16 BS, 6 cm)",
            "m2",
            3140,
            21.80,
            "520",
        ),
        # qty: delivery yard 760 m2 (of the 3,140 m2 asphalt)
        (
            "18.03.0030",
            "Zulage PmB-Asphalt Anlieferhof Schwerlast (Extra-over polymer-modified asphalt, heavy-duty delivery yard)",
            "m2",
            760,
            18.60,
            "520",
        ),
        # qty: R-09 walkways 220 m2
        (
            "18.03.0040",
            "Gehwegplatten und Betonpflaster Gehwege, d = 8 cm (Paving slabs and concrete pavers, walkways, 8 cm)",
            "m2",
            220,
            54.00,
            "520",
        ),
        (
            "18.03.0050",
            "Tiefbord-Randeinfassung Pflasterflaechen (Flush kerb edging of paved areas)",
            "m",
            380,
            24.50,
            "520",
        ),
        (
            "18.03.0060",
            "Bordrinnen und Muldensteine V-Profil (Kerb channels and V-profile dished channels)",
            "m",
            240,
            46.00,
            "520",
        ),
        (
            "18.03.0070",
            "Eingangspodest und Rampen Betonfertigteile, taktile Elemente (Entrance landing and ramps, precast concrete, tactile elements)",
            "lsum",
            1,
            9400.00,
            "520",
        ),
        (
            "18.03.0080",
            "Zulage Einkornbeton-Bettung und Splittfugen Draen-Pflaster (Extra-over no-fines concrete bedding and grit joints, permeable pavers)",
            "m2",
            1450,
            9.80,
            "520",
        ),
        # qty: 6 accessible + 6 parent-child + 12 EV stalls = 24 special stalls
        (
            "18.03.0090",
            "Markierung Sonderstellplaetze: barrierefrei, Eltern-Kind, E-Laden (Marking of special stalls: accessible, parent-child, EV)",
            "pcs",
            24,
            95.00,
            "520",
        ),
        (
            "18.03.0100",
            "Beschilderung Parkplatz und Wegweisung (Car park signage and wayfinding)",
            "pcs",
            18,
            240.00,
            "520",
        ),
        (
            "18.03.0110",
            "Anschluss oeffentliche Strasse inkl. Bordabsenkung (Connection to the public road incl. dropped kerb)",
            "lsum",
            1,
            14200.00,
            "520",
        ),
        (
            "18.03.0120",
            "Anrampungen und Anpassung Bestandsgehweg Wannenaeckerstrasse (Ramping and adaptation of the existing footway, Wannenaeckerstrasse)",
            "lsum",
            1,
            12400.00,
            "520",
        ),
        (
            "18.03.0130",
            "Fugenverguss Asphaltanschluesse und Abnahmebefahrung (Joint sealing of asphalt connections and acceptance drive-over)",
            "m",
            420,
            8.50,
            "520",
        ),
        (
            "18.03.0140",
            "Stundenlohnarbeiten und Kleinleistungen Belagsflaechen (Daywork and minor works, paved surfaces)",
            "lsum",
            1,
            23668.60,
            "520",
        ),
        # 18.04 Entwaesserung Ergaenzungen (KG 540, VE-18 total 140,000.00).
        (
            "18.04.0010",
            "Kontrollschaechte DN 600 Rigolenanbindung (Inspection chambers DN 600 at retention trench connection)",
            "pcs",
            2,
            1450.00,
            "540",
        ),
        (
            "18.04.0020",
            "Anschlussleitung Dachentwaesserung an Rigole DN 200 (Connection pipe, roof drainage to retention trench, DN 200)",
            "lsum",
            1,
            1500.00,
            "540",
        ),
        # 18.05 Begruenung Ergaenzungen (KG 550, VE-18 total 100,000.00).
        # qty: 19 trees per the planting plan (1 tree per 6 stalls)
        (
            "18.05.0010",
            "Baumscheiben, Unterpflanzung und Tropfbewaesserung (Tree pits, underplanting and drip irrigation)",
            "pcs",
            19,
            420.00,
            "550",
        ),
        # qty: facade greening 120 m2 per the sustainability concept
        (
            "18.05.0020",
            "Rankhilfen Fassadenbegruenung, Edelstahlseile (Climbing aids for facade greening, stainless cables)",
            "m2",
            120,
            145.00,
            "550",
        ),
        (
            "18.05.0030",
            "Staudenpflanzung Eingangsbereich, Hochbeet (Perennial planting at the entrance, raised bed)",
            "m2",
            45,
            64.00,
            "550",
        ),
        (
            "18.05.0040",
            "Fertigstellungs- und Entwicklungspflege 2 Jahre (Completion and establishment maintenance, 2 years)",
            "lsum",
            1,
            14800.00,
            "550",
        ),
        (
            "18.05.0050",
            "Wildkrautvlies, Mulchabdeckung und Pflegedokumentation (Weed-control fleece, mulch cover and maintenance records)",
            "lsum",
            1,
            16820.00,
            "550",
        ),
    ],
    # LV 19 (KG 530 = 130,000.00, the only carrier of this group; the bike
    # shelter therefore lives here with the other free-standing external
    # structures, not in VE-18).
    "VE-19": [
        (
            "19.01.0010",
            "Werbepylon h = 8,0 m, Stahlkonstruktion, beleuchtet, inkl. Fundament 12 m3 (Advertising pylon 8.0 m, steel, illuminated, incl. 12 m3 foundation)",
            "pcs",
            1,
            38500.00,
            "530",
        ),
        # qty: 3 cart shelters a 27 m2 with green roofs per the site plan
        (
            "19.01.0020",
            "Einkaufswagen-Ueberdachungen 27 m2 mit Gruendach (Cart shelters 27 m2 with green roofs)",
            "pcs",
            3,
            16800.00,
            "530",
        ),
        (
            "19.01.0030",
            "Fahrradueberdachung 20 Plaetze und 2 Lastenrad-Plaetze (Bike shelter 20 spaces plus 2 cargo-bike spaces)",
            "lsum",
            1,
            12243.20,
            "530",
        ),
        # qty: (34 bike stalls - 20 covered) / 2 stalls per hoop = 7 hoops
        (
            "19.01.0040",
            "Fahrradanlehnbuegel Edelstahl, nicht ueberdacht (Stainless bike hoops, uncovered)",
            "pcs",
            7,
            385.00,
            "530",
        ),
        (
            "19.01.0050",
            "Anfahrschutz Poller und Schutzbuegel: Ladesaeulen, Pylon, Gebaeudeecken (Impact protection bollards and hoops: chargers, pylon, building corners)",
            "pcs",
            22,
            460.00,
            "530",
        ),
        (
            "19.01.0060",
            "Fahnenmasten h = 8 m inkl. Huelsenfundament (Flag poles 8 m incl. sleeve foundations)",
            "pcs",
            3,
            1950.00,
            "530",
        ),
        (
            "19.01.0070",
            "Beleuchtung Pylon-Logoblende, Anschluss und IBN (Pylon sign lighting, connection and commissioning)",
            "lsum",
            1,
            2400.00,
            "530",
        ),
        (
            "19.01.0080",
            "Fundamente, Montage und Nebenleistungen Aussenbauwerke (Foundations, erection and ancillary works, external structures)",
            "lsum",
            1,
            7791.80,
            "530",
        ),
    ],
    # LV 20 (KG 610 = 560,000.00, owner direct award VP-10) - subsections:
    # 20.01 Regale und Kassenzone, 20.02 Backstation und Sondermoebel.
    "VE-20": [
        # qty: 8 aisles a 2 runs a 30 m = 480 lfm shelving in the 1,590 m2 sales hall
        (
            "20.01.0010",
            "Regalanlage Verkaufsraum 8 Gaenge, Grund- und Anbaufelder, H = 2,2 m (Sales-area shelving 8 aisles, starter and add-on bays, H = 2.2 m)",
            "m",
            480,
            545.00,
            "610",
        ),
        ("20.01.0020", "Bandkassen-Arbeitsplaetze (Belt checkout workstations)", "pcs", 2, 18400.00, "610"),
        (
            "20.01.0030",
            "Self-Checkout-Systeme inkl. Software-Inbetriebnahme (Self-checkout systems incl. software commissioning)",
            "pcs",
            4,
            21500.00,
            "610",
        ),
        (
            "20.01.0040",
            "Kassenzonen-Leitsystem, Warentrenner und Gondelkoepfe (Checkout guidance system, dividers and gondola ends)",
            "lsum",
            1,
            14800.00,
            "610",
        ),
        (
            "20.01.0050",
            "Warensicherung Antennen Ein- und Ausgang (Article surveillance antennas, entrance and exit)",
            "pcs",
            2,
            4850.00,
            "610",
        ),
        (
            "20.01.0060",
            "Einkaufswagen inkl. Pfandschloss (Shopping carts incl. deposit locks)",
            "pcs",
            220,
            145.00,
            "610",
        ),
        (
            "20.01.0070",
            "Pfandbon-Drucker, IT-Halterungen und Kleinmontagen Kasse (Deposit-receipt printers, IT mounts and minor checkout fitting)",
            "lsum",
            1,
            2800.00,
            "610",
        ),
        # qty: bake-off 3 ovens a 18 kW per the space program
        (
            "20.02.0010",
            "Backstation 3 Oefen a 18 kW inkl. Beschickungs- und Ablufttechnik (Bake-off station, 3 ovens a 18 kW incl. loading and extract equipment)",
            "pcs",
            3,
            16900.00,
            "610",
        ),
        (
            "20.02.0020",
            "Brotregale und Praesentationsmoebel Backstation (Bread racks and display furniture, bake-off)",
            "lsum",
            1,
            12400.00,
            "610",
        ),
        (
            "20.02.0030",
            "Obst- und Gemuese-Praesentation, Kistenregale (Fruit and vegetable displays, crate racks)",
            "m",
            24,
            680.00,
            "610",
        ),
        (
            "20.02.0040",
            "Aktionsmoebel Gondelkopf und mobile Verkostungstheke (Promotional gondola-end units and mobile tasting counter)",
            "pcs",
            6,
            1450.00,
            "610",
        ),
        # qty: ~20 staff per the operating concept
        (
            "20.02.0050",
            "Buero- und Sozialraummoebel, Spinde 20 Personal (Office and staff-room furniture, lockers for 20 staff)",
            "pcs",
            20,
            485.00,
            "610",
        ),
        (
            "20.02.0060",
            "Innenbeschilderung, Deckenhaenger und Regalstirn-Beschilderung (Interior signage, ceiling hangers and shelf-end signage)",
            "lsum",
            1,
            9400.00,
            "610",
        ),
        (
            "20.02.0070",
            "Montage, Ausrichtung, Erstbestueckungs-Logistik und Einweisung (Erection, alignment, initial-stocking logistics and instruction)",
            "lsum",
            1,
            9180.00,
            "610",
        ),
    ],
    # LV 21 (KG 690 = 140,000.00, the only carrier of this group).
    "VE-21": [
        # qty: 2 reverse-vending machines per the space program (Pfandraum 42 m2)
        (
            "21.01.0010",
            "Leergut-Ruecknahmeautomaten Doppelgeraet mit Durchreiche (Reverse-vending machines, twin unit with pass-through)",
            "pcs",
            2,
            32500.00,
            "690",
        ),
        (
            "21.01.0020",
            "Leergut-Foerder- und Sortieranlage Pfandraum (Empties conveying and sorting system, deposit room)",
            "lsum",
            1,
            24800.00,
            "690",
        ),
        ("21.01.0030", "Ballenpresse Kartonage 50 kN (Cardboard baler 50 kN)", "pcs", 1, 12400.00, "690"),
        ("21.01.0040", "Scheuersaugmaschine Reinigung (Scrubber-dryer cleaning machine)", "pcs", 1, 8900.00, "690"),
        (
            "21.01.0050",
            "Behaeltersystem Wertstoffe und Muellpress-Stellplatz (Recyclables container system and waste-press bay)",
            "lsum",
            1,
            6400.00,
            "690",
        ),
        (
            "21.01.0060",
            "Kleinausstattung: Feuerloescher, Erste-Hilfe, Arbeitsschutz-Beschilderung (Minor equipment: extinguishers, first aid, safety signage)",
            "lsum",
            1,
            4200.00,
            "690",
        ),
        (
            "21.01.0070",
            "Ersatzteil- und Verschleisspaket RVM inkl. Personaleinweisung (Spare and wear-part package for the RVMs incl. staff instruction)",
            "lsum",
            1,
            2900.00,
            "690",
        ),
        (
            "21.01.0080",
            "Anlieferung, Montage, IBN und Einweisung Betriebstechnik (Delivery, assembly, commissioning and instruction, operational equipment)",
            "lsum",
            1,
            15400.00,
            "690",
        ),
    ],
}


def _build_sections() -> list[SectionDef]:
    """Assemble the 16 LV sections, each summing exactly to its VE budget.

    The full LV closes by data: every section's positions must reproduce
    the procurement-unit budget to the cent, with no remainder rows. All
    money arithmetic runs through Decimal so the emitted 2-decimal floats
    are exact and the LV grand total lands on 7,905,000.00 EUR to the
    cent. A nonzero remainder is a data error and raises immediately, so
    a careless edit can never silently drift a budget or a KG rollup.
    """
    sections: list[SectionDef] = []
    for ordinal, ve_id, title, kg, budget in _VE_SECTIONS:
        rows = _POSITIONS[ve_id]
        items: list[tuple[str, str, str, float, float, dict]] = [
            (oz, desc, unit, qty, rate, {"din276": code}) for oz, desc, unit, qty, rate, code in rows
        ]
        total = sum(
            (Decimal(str(qty)) * Decimal(str(rate)) for _, _, _, qty, rate, _ in rows),
            Decimal("0"),
        )
        remainder = Decimal(str(budget)) - total
        if remainder != 0:
            msg = f"{ve_id}: positions sum to {total}, budget is {budget} (off by {remainder})"
            raise ValueError(msg)
        sections.append((ordinal, title, {"din276": kg}, items))
    return sections


# Net LV grand total across the 16 priced procurement units (= sum of the
# VE budgets). install_demo_project prices bids as a factor of a share of
# this figure: with four tender packages each package gets an equal share
# (grand_total / 4) and each bid is priced as ``share * factor``. The
# factors below are therefore authored as ``net_bid / _PKG_SHARE`` so every
# bid lands on its exact net amount regardless of the equal-share split.
_LV_GRAND_TOTAL = 7_905_000.00
_PKG_SHARE = _LV_GRAND_TOTAL / 4  # = 1,976,250.00

TEMPLATE = DemoTemplate(
    demo_id="retail-market-heilbronn",
    project_name="Lebensmittelmarkt Heilbronn",
    project_description=(
        "Neubau eines eingeschossigen Lebensmittelmarktes mit Stellplatzanlage "
        "im Gewerbegebiet Wannenaecker, Heilbronn-Boeckingen (New-build food "
        "retail market with parking facilities). Verkaufsflaeche 1.672 m2, "
        "BGF 2.840 m2 (EG 2.720 + Technik-Mezzanin 120), BRI 19.050 m3, "
        "Grundstueck 9.480 m2. Tragwerk: 36 Stahlbeton-Fertigteilstuetzen "
        "40/40 cm auf Koecherfundamenten, 24 BSH-Binder GL24h (Spannweiten "
        "23,8 m + 16,2 m) auf 12 Achsen a 6,18 m, Bodenplatte d = 20 cm "
        "(544 m3 RC-Beton), Stahltrapezblech-Dach mit 8 RWA-Lichtkuppeln. "
        "Fassade: Sandwichpaneele 1.292 m2 mit Laerchen-Akzent, "
        "Pfosten-Riegel-Verglasung 120 m2. 100 % fossilfrei: transkritische "
        "CO2-Kaelteanlage (NK 95 kW / TK 26 kW) mit 2-stufiger "
        "Waermerueckgewinnung und Fussbodenheizung, PV-Anlage 290 kWp mit "
        "Batteriespeicher 135 kWh, 12 E-Ladepunkte. 112 Pkw-Stellplaetze, "
        "34 Fahrradplaetze, Rigole 190 m3 (DWA-A 138). KfW 299 (EG 40 + "
        "QNG-PLUS), DGNB Gold angestrebt. Genehmigtes Projektbudget "
        "9,43 Mio EUR netto (KG 200-700 zzgl. Reserve)."
    ),
    region="DACH",
    classification_standard="din276",
    currency="EUR",
    locale="de",
    address={
        "street": "Wannenaeckerstrasse 64",
        "city": "Heilbronn",
        "postcode": "74078",
        "country": "Germany",
        "lat": 49.155,
        "lng": 9.175,
    },
    validation_rule_sets=["din276", "gaeb", "boq_quality"],
    boq_name="Kostenberechnung nach DIN 276",
    boq_description=(
        "Kostenberechnung gem. DIN 276:2018-12 auf Basis der Vergabeeinheiten: "
        "16 bepreiste LV-Abschnitte im OZ-Schema VE.Abschnitt.Position, "
        "Summe exakt 7.905.000 EUR netto (KG 200-600 ohne KG 220 "
        "Anschlussgebuehren). Vollstaendiges LV mit 303 Positionen; jeder "
        "Abschnitt schliesst centgenau auf sein VE-Budget und jede "
        "DIN 276-Kostengruppe der 2. Ebene centgenau auf den Kostenplan "
        "(full bill of quantities, 303 positions, every section closing "
        "exactly on its procurement-unit budget and every 2nd-level cost "
        "group exactly on the reconciled cost plan)."
    ),
    boq_metadata={
        "standard": "DIN 276:2018-12",
        "phase": "LP 3 Kostenberechnung, fortgeschrieben mit Vergabestand",
        "base_date": "2026-Q2",
        "price_level": "Heilbronn 2026",
        "oz_scheme": "VE.Abschnitt.Position",
        "project_code": "LM-HN-2026-01",
    },
    sections=_build_sections(),
    markups=[
        ("Baustellengemeinkosten (BGK / site overhead)", 9.0, "overhead", "direct_cost"),
        ("Mehrwertsteuer (MwSt. / VAT)", 19.0, "tax", "cumulative"),
    ],
    total_months=11,
    # Legacy single-package fields (required by DemoTemplate). They are
    # overridden by ``tender_packages`` below, but kept as the VP-07 award so
    # the descriptor still reads correctly if the multi-package path is ever
    # disabled.
    tender_name="VP-07 Kaeltetechnik CO2-Verbund und Kuehlmoebel (CO2 refrigeration, owner direct award)",
    tender_companies=[
        ("Sommerfeld Kaeltetechnik GmbH", "vergabe@sommerfeld-kaeltetechnik.de", 812_400 / _LV_GRAND_TOTAL),
        ("NeckarFrost Kaelte- und Klimatechnik GmbH", "angebote@neckarfrost-kaelte.de", 858_900 / _LV_GRAND_TOTAL),
        ("Kuehlanlagenbau Westheimer GmbH", "ausschreibung@kaeltebau-westheimer.de", 901_200 / _LV_GRAND_TOTAL),
    ],
    # Four procurement packages (VP-07/09/10/11 of the design dossier), each
    # mapping to a procurement unit budget. Status reflects the week-19
    # snapshot: VP-07 awarded, VP-09 out for submission, VP-10 in
    # negotiation, VP-11 in evaluation pending the grid feed-in approval.
    # The bid factor is ``net_bid / _PKG_SHARE`` so install_demo_project
    # (which prices each package off an equal grand_total / 4 share) lands
    # every bid on its exact net figure.
    tender_packages=[
        (
            "VP-07 Kaeltetechnik CO2-Verbund und Kuehlmoebel (CO2 refrigeration and cabinets, KG 470)",
            "Bauherren-Direktvergabe, vergeben am 2026-04-24 an Sommerfeld Kaeltetechnik GmbH; 3 Angebote, Spread 10,9 %. Budget 830.000 EUR netto (VE-15).",
            "awarded",
            [
                # bids 812,400 / 858,900 / 901,200 EUR, spread 10.9 %
                ("Sommerfeld Kaeltetechnik GmbH", "vergabe@sommerfeld-kaeltetechnik.de", 812_400 / _PKG_SHARE),
                ("NeckarFrost Kaelte- und Klimatechnik GmbH", "angebote@neckarfrost-kaelte.de", 858_900 / _PKG_SHARE),
                ("Kuehlanlagenbau Westheimer GmbH", "ausschreibung@kaeltebau-westheimer.de", 901_200 / _PKG_SHARE),
            ],
        ),
        (
            "VP-09 Aussenanlagen, Stellplaetze, Entwaesserung (External works, parking, drainage, KG 510+520+540+550)",
            "Ausgeschrieben, Submission 2026-06-18; 3 indikative Angebote, Spread 14,0 %. Budget 1.020.000 EUR netto (VE-18).",
            "collecting",
            [
                # indicative bids 981,400 / 1,041,200 / 1,118,900 EUR, spread 14.0 %
                ("Galabau Ergenzinger GmbH", "angebot@galabau-ergenzinger.de", 981_400 / _PKG_SHARE),
                ("Tiefbau Krummacher GmbH", "vergabe@tiefbau-krummacher.de", 1_041_200 / _PKG_SHARE),
                ("Gruenbau Remstal GmbH", "ausschreibung@gruenbau-remstal.de", 1_118_900 / _PKG_SHARE),
            ],
        ),
        (
            "VP-10 Ladeneinrichtung, Regaltechnik, Kassenzone, Backstation (Store fit-out, KG 610)",
            "Bauherren-Direktvergabe, in Verhandlung, Zuschlag geplant 2026-06-30; 2 Angebote, Spread 5,8 %. Budget 560.000 EUR netto (VE-20).",
            "evaluating",
            [
                # bids 528,700 / 559,400 EUR, spread 5.8 %
                ("Ladenbau Krettner GmbH", "e.krettner@ladenbau-krettner.de", 528_700 / _PKG_SHARE),
                ("Objekteinrichtung Sallinger & Co. KG", "vergabe@sallinger-objekt.de", 559_400 / _PKG_SHARE),
            ],
        ),
        (
            "VP-11 PV 290 kWp, Batteriespeicher 135 kWh, Ladeinfrastruktur (PV, battery, EV charging, KG 440)",
            "Bauherren-Direktvergabe, in Wertung, Zuschlag nach Einspeisezusage (Risiko R06); 3 Angebote, Spread 13,0 %. Budget 520.000 EUR netto (VE-17).",
            "evaluating",
            [
                # bids 497,800 / 534,600 / 562,300 EUR, spread 13.0 %
                ("Sonnfeld Solartechnik GmbH", "angebot@sonnfeld-solar.de", 497_800 / _PKG_SHARE),
                ("EnergieWerk Hohenlohe GmbH", "vergabe@energiewerk-hohenlohe.de", 534_600 / _PKG_SHARE),
                ("Elektro Haeberlen GmbH", "u.haeberlen@elektro-haeberlen.de", 562_300 / _PKG_SHARE),
            ],
        ),
    ],
    # 35 schedule activities (T01..T35 of the design dossier), anchored on the
    # real calendar so the project reads mid-construction at week 19 of 45
    # (Mon 2026-02-02 start, opening Thu 2026-12-10). install_demo_project
    # derives a progress ramp from the activity order; the SPI/CPI overrides
    # above carry the "slightly behind on roof/facade, under cost" story.
    schedule_activities=[
        ("T01 Werk- und Montageplanung Fertigteile (precast shop and erection drawings)", "2026-02-02", "2026-03-06"),
        (
            "T02 Baustelleneinrichtung inkl. Baustrom und Bauwasser (site setup incl. power and water)",
            "2026-02-02",
            "2026-02-13",
        ),
        (
            "T03 Erschliessung Kanal, Wasser, Strom bis Grundstuecksgrenze (utility connections to plot)",
            "2026-02-16",
            "2026-03-06",
        ),
        ("T04 Baufeldfreimachung und Oberbodenabtrag (site clearance and topsoil strip)", "2026-02-16", "2026-02-20"),
        ("T05 Erdaushub und Bodenaustausch (excavation and soil replacement)", "2026-02-23", "2026-03-13"),
        (
            "T06 Planumserstellung und Verdichtungsnachweis (subgrade formation and compaction)",
            "2026-03-16",
            "2026-03-20",
        ),
        ("T07 Koecher- und Streifenfundamente (pocket and strip foundations)", "2026-03-23", "2026-04-03"),
        ("T08 Grundleitungen unter Bodenplatte (below-slab drainage)", "2026-03-30", "2026-04-10"),
        (
            "T09 Bodenplatte: Daemmung, Bewehrung, Betonage (ground slab: insulation, rebar, pour)",
            "2026-04-06",
            "2026-04-24",
        ),
        ("T10 Fertigteilproduktion im Werk (precast production at plant)", "2026-03-09", "2026-04-24"),
        ("T11 Montage Stuetzen und BSH-Binder (erection of columns and glulam beams)", "2026-04-27", "2026-05-08"),
        ("T12 Montage Wand- und Sandwichelemente (erection of wall and sandwich panels)", "2026-05-04", "2026-05-15"),
        ("T13 Dachtragschale Trapezblech (roof deck trapezoidal sheeting)", "2026-05-11", "2026-05-22"),
        (
            "T14 Dachabdichtung, Daemmung, RWA und Lichtkuppeln (roof waterproofing, smoke vents, rooflights)",
            "2026-05-25",
            "2026-06-19",
        ),
        ("T15 Fassadenarbeiten: Sandwichpaneele, Laerchen-Lattung, Sockel (facade works)", "2026-05-25", "2026-06-26"),
        (
            "T16 Fenster, Pfosten-Riegel-Glasfront, Tueren, Sektionaltore (windows, curtain wall, doors, gates)",
            "2026-06-15",
            "2026-07-03",
        ),
        ("T17 Heizung/Sanitaer Rohinstallation (heating/plumbing rough-in)", "2026-06-01", "2026-07-10"),
        ("T18 Lueftungskanaele Montage (ventilation ductwork installation)", "2026-06-08", "2026-07-10"),
        (
            "T19 Elektro-Rohinstallation und Kabeltrassen (electrical rough-in and cable trays)",
            "2026-06-01",
            "2026-07-17",
        ),
        ("T20 CO2-Kaelteleitungen Rohmontage (CO2 refrigerant piping rough-in)", "2026-06-29", "2026-07-24"),
        (
            "T21 Netzanschluss, Trafostation, NSHV (grid connection, transformer, main LV board)",
            "2026-06-15",
            "2026-07-24",
        ),
        ("T22 Trockenbau Sozial- und Nebenraeume (drywall for staff and ancillary rooms)", "2026-07-06", "2026-08-07"),
        ("T23 Industrieboden Verkaufsraum (industrial flooring sales area)", "2026-07-13", "2026-07-24"),
        ("T24 Fliesen, Maler, Innentueren (tiling, painting, internal doors)", "2026-08-03", "2026-08-28"),
        ("T25 Akustikdecken und Beleuchtungsmontage (acoustic ceilings and lighting)", "2026-08-10", "2026-08-28"),
        (
            "T26 TGA-Endmontage: Waermepumpe, RLT, Verteilungen, GLT (MEP completion incl. BMS)",
            "2026-08-10",
            "2026-09-11",
        ),
        (
            "T27 Aussenanlagen: Unterbau, Entwaesserung, Belaege, Pylon, Begruenung (external works)",
            "2026-08-10",
            "2026-10-16",
        ),
        (
            "T28 PV-Anlage, Batteriespeicher und Ladeinfrastruktur (PV, battery and EV charging)",
            "2026-08-24",
            "2026-09-18",
        ),
        ("T29 Kuehlmoebel stellen und anbinden (set and connect refrigerated cabinets)", "2026-08-31", "2026-09-18"),
        (
            "T30 Kaelteanlage: Druckprobe, Inbetriebnahme, Kuehlstellen kalt (refrigeration commissioning)",
            "2026-09-21",
            "2026-10-02",
        ),
        (
            "T31 Ladeneinrichtung: Regale, Kassenzone, Backstation, Pfandraum (store fit-out)",
            "2026-09-28",
            "2026-10-23",
        ),
        (
            "T32 Sachverstaendigen- und behoerdliche Abnahmen (expert and authority acceptance tests)",
            "2026-10-19",
            "2026-10-30",
        ),
        (
            "T33 VOB-Abnahme GU und Maengelbeseitigung (VOB acceptance of GC works and snagging)",
            "2026-11-02",
            "2026-11-13",
        ),
        (
            "T34 Revisionsunterlagen, Einweisungen, Wartungsvertraege (as-builts, briefings, maintenance)",
            "2026-11-02",
            "2026-11-20",
        ),
        (
            "T35 Warenerstbestueckung, Personaleinarbeitung, Pre-Opening (initial stocking, training)",
            "2026-11-23",
            "2026-12-10",
        ),
    ],
    project_metadata={
        "name_en": "Retail Market Heilbronn",
        "long_name_de": "Neubau Lebensmittelmarkt mit Stellplatzanlage, Heilbronn-Boeckingen",
        "long_name_en": "New-build food retail market with parking facilities, Heilbronn-Boeckingen",
        "address": "Wannenaeckerstrasse 64, 74078 Heilbronn",
        "client": "Sueddeutsche Handelsimmobilien GmbH",
        "operator": "Sueddeutsche Lebensmittelmaerkte GmbH",
        "architect": "Architekturbuero Sandweg + Partner Architekten PartG mbB",
        "structural_engineer": "Trautmann Ingenieure Tragwerksplanung GmbH",
        "mep_engineer": "Klein & Partner TGA-Planung GmbH",
        "main_contractor": "Trautwein Bau GmbH & Co. KG",
        "gfa_m2": 2840,
        "bri_m3": 19050,
        "plot_m2": 9480,
        "footprint_m2": 2720,
        "sales_area_m2": 1672,
        "parking_stalls": 112,
        "bike_stalls": 34,
        "ev_charge_points": 12,
        "pv_kwp": 290,
        "battery_kwh": 135,
        "structure_system": "Precast RC columns 40/40 on pocket foundations, glulam binders GL24h, steel roof deck",
        "facade_system": "Sandwich panels MW 200 mm, larch batten accent, aluminium curtain wall entrance",
        "grid_m": "12 axes a 6.18, spans 23.8 + 16.2",
        "refrigeration": "Transcritical CO2 (R744) booster rack, MT 95 kW / LT 26 kW, 2-stage heat recovery",
        "energy_standard": "GEG 2024 / KfW 299 (EG 40 + QNG-PLUS)",
        "sustainability_target": "DGNB Gold (Neubau 2023)",
        "zoning": "Vorhabenbezogener B-Plan 103/27 Wannenaecker - Nahversorgung Sued (SO Nahversorgung)",
        "permit_authority": "Stadt Heilbronn, Planungs- und Baurechtsamt (LBO BW, Sonderbau Verkaufsstaette)",
        "design_phase": "LP 3 Kostenberechnung, fortgeschrieben mit Vergabestand",
        "applicable_standards": [
            "DIN 276:2018-12",
            "VOB/B + VOB/C (DIN 18299 ff.)",
            "GAEB DA XML 3.3 (X83)",
            "GEG 2024",
            "GEIG",
            "KlimaG BW (PV-Pflicht)",
            "EN 378 (CO2-Kaelteanlage)",
            "DWA-A 138 (Versickerung)",
        ],
        "cost_basis": "Net, price level Heilbronn 2026, reconciled DIN 276 cost frame",
        "budget": "9.43M EUR",
    },
    project_code="LM-HN-2026-01",
    # 5D tuning - matches the week-19-of-45 finance story: ~30 % billed,
    # slightly behind on roof/facade (SPI 0.97), under cost (CPI 1.03,
    # EAC 9,156,300 = 273,700 under the 9,430,000 approved budget).
    planned_budget=9_430_000.0,
    actual_spend_ratio=0.30,
    spi_override=0.97,
    cpi_override=1.03,
)
