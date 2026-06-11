# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Public showcase demo: Lebensmittelmarkt Karlsruhe / Retail Market Karlsruhe.

Greenfield single-storey discount-grocery store with a large surface car
park in the Karlsruhe-Durlach commercial belt (DE). Sister pack to the
Heilbronn market, but a deliberately larger and differently equipped format:
a 2,050 m2 sales floor, a drive-through bake-off lane, an expanded
checkout zone, about 150 parking stalls, a 380 kWp roof PV array with a
240 kWh battery, and a wider e-mobility build-out. DIN 276:2018-12 cost
frame, GAEB-style LV structure, EUR, German locale. All companies are
fictional with descriptive generic names.

Data layer
----------
The BOQ is assembled from two module-level tables so later passes only have
to touch the data, never the assembly logic:

* ``_VE_SECTIONS`` - the 16 priced procurement units (Vergabeeinheiten) that
  map 1:1 to LV sections (OZ scheme ``VE.subsection.position``). Budgets
  come from the reconciled DIN 276 cost plan; their sum is exactly
  9,600,000.00 EUR net.
* ``_POSITIONS`` - the full LV, grouped into thematic OZ subsections per
  Gewerk. Every section sums EXACTLY to its procurement-unit budget;
  ``_build_sections`` raises if any section drifts by a cent. Each section
  carries one trailing balancing line (general site overheads, ancillary
  works, daywork, commissioning and the like) that absorbs the rounding so
  the bill closes by data, exactly as the Heilbronn pack does.

Money contract
--------------
The LV grand total (sum of the 16 procurement-unit budgets) lands on
9,600,000.00 EUR net to the cent. All money arithmetic runs through
``Decimal`` so the emitted 2-decimal floats are exact.

Quantities derive from the canonical building geometry (footprint
75 x 42 m = 3,150 m2, work area 3,213 m2 = footprint x 1.02, perimeter
234 m, 13 axes a 6.25 m -> 39 columns / 39 pocket foundations / 26 binders
/ 24 edge beams, slab 630 m3 = 3,150 x 0.20, 864 PV modules a 440 Wp =
380 kWp, ~150 stalls). Non-obvious derivations are documented inline.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.demo_projects import DemoTemplate, SectionDef

__all__ = ["TEMPLATE"]

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
        175_000.00,
    ),
    ("02", "VE-02", "LV 02 - Erdbau und Erschliessung (Earthworks and site servicing)", "210", 430_000.00),
    (
        "04",
        "VE-04",
        "LV 04 - Rohbau: Gruendung, Bodenplatte, Industrieboden, Massivbau (Shell works)",
        "320",
        1_000_000.00,
    ),
    (
        "05",
        "VE-05",
        "LV 05 - Dach: Trapezblech, Daemmung, Abdichtung, RWA (Roof works incl. smoke vents)",
        "360",
        700_000.00,
    ),
    (
        "06",
        "VE-06",
        "LV 06 - Stahlbeton-Fertigteile und BSH-Binder (Precast RC frame and glulam binders)",
        "330",
        660_000.00,
    ),
    ("07", "VE-07", "LV 07 - Fassade: Sandwichpaneele, Laerchen-Lattung, Sockel (Facade works)", "330", 500_000.00),
    (
        "08",
        "VE-08",
        "LV 08 - Fenster, Tueren, Tore, Pfosten-Riegel-Fassade (Windows, doors, gates, curtain wall)",
        "330",
        310_000.00,
    ),
    (
        "09",
        "VE-09",
        "LV 09 - Innenausbau: Trockenbau, Fliesen, Maler, Innentueren, Decken (Interior fit-out)",
        "340",
        340_000.00,
    ),
    (
        "14",
        "VE-14",
        "LV 14 - HLS: Sanitaer, Waermepumpe, Fussbodenheizung, RLT (Mechanical services)",
        "410",
        760_000.00,
    ),
    (
        "15",
        "VE-15",
        "LV 15 - Kaeltetechnik CO2-Verbund und Kuehlmoebel (CO2 refrigeration and cabinets)",
        "470",
        980_000.00,
    ),
    (
        "16",
        "VE-16",
        "LV 16 - Elektrotechnik inkl. BMA und GLT (Electrical incl. fire alarm and automation)",
        "440",
        820_000.00,
    ),
    (
        "17",
        "VE-17",
        "LV 17 - PV 380 kWp, Batteriespeicher 240 kWh, Ladeinfrastruktur (PV, battery, EV charging)",
        "440",
        660_000.00,
    ),
    (
        "18",
        "VE-18",
        "LV 18 - Aussenanlagen, Stellplaetze, Entwaesserung (External works, parking, drainage)",
        "510",
        1_250_000.00,
    ),
    (
        "19",
        "VE-19",
        "LV 19 - Werbepylon, Einkaufswagen-Boxen, Anfahrschutz (Pylon, cart shelters, protection)",
        "530",
        165_000.00,
    ),
    (
        "20",
        "VE-20",
        "LV 20 - Ladeneinrichtung, Kassenzone, Drive-in-Backstation (Store fit-out, checkout, bake-off)",
        "610",
        700_000.00,
    ),
    (
        "21",
        "VE-21",
        "LV 21 - Pfandraumtechnik und sonstige Ausstattung (Reverse-vending room and equipment)",
        "690",
        150_000.00,
    ),
]

# Full LV. Net unit rates, price level Karlsruhe 2026. Quantities derive
# from the canonical building geometry (work area 3,213 m2, 39 pocket
# foundations, perimeter 234 m, slab 630 m3, ...). Within each procurement
# unit the rows are grouped into thematic OZ subsections; each section
# carries a trailing balancing line that closes it exactly on its budget.
_POSITIONS: dict[str, list[_PositionRow]] = {
    # LV 01 (KG 390 = 175,000.00). Provision periods follow the 10-month
    # construction window.
    "VE-01": [
        (
            "01.01.0010",
            "Baustelle einrichten und raeumen, An- und Abtransport Geraete (Site establishment and clearance incl. plant transport)",
            "lsum",
            1,
            32500.00,
            "390",
        ),
        # qty: site hoarding ~ plot frontage loop (132 + 92) x 2 ~= 448 m + gates/reserve = 470 m
        (
            "01.01.0020",
            "Bauzaun mobil h = 2,0 m, Vorhaltung 10 Monate (Mobile site fence 2.0 m, 10 months provision)",
            "m",
            470,
            22.50,
            "390",
        ),
        (
            "01.01.0030",
            "Bauzufahrt und Baustrasse Schotter, herstellen und rueckbauen (Gravel site access road, build and remove)",
            "m2",
            1050,
            18.90,
            "390",
        ),
        (
            "01.01.0040",
            "Buero- und Sozialcontainer, Vorhaltung 10 Monate (Office and welfare containers, 10 months provision)",
            "pcs",
            8,
            2950.00,
            "390",
        ),
        (
            "01.01.0050",
            "Baustromversorgung inkl. Verteiler und Verbrauch (Site power supply incl. distribution and consumption)",
            "lsum",
            1,
            17800.00,
            "390",
        ),
        (
            "01.01.0060",
            "Bauwasseranschluss inkl. Verbrauch (Site water connection incl. consumption)",
            "lsum",
            1,
            7400.00,
            "390",
        ),
        (
            "01.01.0070",
            "Mobilkran- und Hebezeugvorhaltung fuer Fremdgewerke (Mobile crane and hoisting provision for other trades)",
            "lsum",
            1,
            14800.00,
            "390",
        ),
        (
            "01.01.0080",
            "Bauschild und bauzeitliche Verkehrssicherung (Site sign and temporary traffic safety measures)",
            "lsum",
            1,
            5600.00,
            "390",
        ),
        (
            "01.01.0090",
            "Baustellenbewachung und Kamerasystem (Site security and camera system)",
            "lsum",
            1,
            9400.00,
            "390",
        ),
        (
            "01.01.0100",
            "Bautrocknung und Winterbaumassnahmen (Construction drying and winter working measures)",
            "lsum",
            1,
            10800.00,
            "390",
        ),
        (
            "01.01.0110",
            "Baustellen-IT, Funk und Zutrittskontrolle (Site IT, radio and access control)",
            "lsum",
            1,
            4400.00,
            "390",
        ),
        ("01.01.0120", "Endreinigung und Uebergabe (Final cleaning and handover)", "m2", 3290, 2.90, "390"),
        (
            "01.01.0130",
            "Allgemeine Baustellengemeinkosten, Versicherungen, Bautagesberichte (General site overheads, insurances, daily reports)",
            "lsum",
            1,
            8739.00,
            "390",
        ),
    ],
    # LV 02 - subsections: 02.01 Herrichten (KG 210), 02.02 nichtoeffentliche
    # Erschliessung (KG 230), 02.03 Erdbau (KG 310), 02.04 Unterbau (KG 320).
    "VE-02": [
        (
            "02.01.0010",
            "Baufeldfreimachung, Roden Bewuchs, Abbruch Kleinstrukturen (Site clearance, grubbing, removal of minor structures)",
            "lsum",
            1,
            11400.00,
            "210",
        ),
        # qty: topsoil strip over footprint 3,150 m2 x 0.25 m = 788 m3 (external topsoil is in VE-18)
        (
            "02.01.0020",
            "Oberbodenabtrag Baufeld d = 25 cm, in Mieten lagern (Topsoil strip building field 25 cm, stockpile on site)",
            "m3",
            788,
            9.20,
            "210",
        ),
        (
            "02.01.0030",
            "Schnurgeruest, Absteckung und Feinabsteckung Gebaeude (Batter boards, setting-out and fine staking)",
            "lsum",
            1,
            4800.00,
            "210",
        ),
        (
            "02.01.0040",
            "Kampfmittelsondierung und Freigabedokumentation Baufeld (UXO probing and clearance documentation)",
            "lsum",
            1,
            17600.00,
            "210",
        ),
        (
            "02.02.0010",
            "Hausanschluss Wasser DN 80 inkl. Graben und Wiederherstellung (Water service connection DN 80 incl. trench)",
            "m",
            46,
            158.00,
            "230",
        ),
        (
            "02.02.0020",
            "Hausanschluss Abwasser DN 250 bis Uebergabeschacht (Sewer service connection DN 250 to transfer chamber)",
            "m",
            58,
            228.00,
            "230",
        ),
        (
            "02.02.0030",
            "Leerrohrtrasse Strom und Telekom, Trafostation bis NSHV (Conduit route power and telecom, substation to main LV board)",
            "m",
            145,
            102.00,
            "230",
        ),
        (
            "02.02.0040",
            "Uebergabeschaechte DN 1000 inkl. Abdeckung Kl. D (Transfer chambers DN 1000 incl. class D covers)",
            "pcs",
            3,
            3600.00,
            "230",
        ),
        (
            "02.02.0050",
            "Loeschwasser- und Hydrantenleitung DN 150 auf dem Grundstueck (Fire-water and hydrant main DN 150 on the plot)",
            "m",
            105,
            268.00,
            "230",
        ),
        (
            "02.02.0060",
            "Pruefung, Spuelung, Desinfektion und Dokumentation Anschluesse (Testing, flushing, disinfection and records)",
            "lsum",
            1,
            7200.00,
            "230",
        ),
        (
            "02.03.0010",
            "Erdaushub Planum Bauwerk und Anlieferrampe, Kl. 3-5 (Bulk excavation to formation, building and dock ramp)",
            "m3",
            2480,
            11.60,
            "310",
        ),
        (
            "02.03.0020",
            "Liefern und Einbau gepruefte Auffuellung, lagenweise verdichtet (Supply and place certified fill, compacted in layers)",
            "m3",
            1920,
            27.20,
            "310",
        ),
        # qty: surplus = pits 3,900 (VE-04) + grading 2,480 - 700 re-used on site = 5,680 m3
        (
            "02.03.0030",
            "Abfuhr und Entsorgung Ueberschussmassen Z1.1 (Haul-off and disposal of surplus soil, class Z1.1)",
            "m3",
            5680,
            19.40,
            "310",
        ),
        (
            "02.03.0040",
            "Offene Wasserhaltung, Vorhaltung 12 Wochen (Open dewatering, 12 weeks provision)",
            "lsum",
            1,
            9800.00,
            "310",
        ),
        (
            "02.03.0050",
            "Boeschungen sichern, Folienabdeckung (Slope protection, sheeting cover)",
            "m2",
            1180,
            6.80,
            "310",
        ),
        # qty: work area 3,213 m2 = footprint x 1.02
        (
            "02.03.0060",
            "Kalk-Zement-Stabilisierung Planum d = 30 cm (Lime-cement stabilisation of formation, 30 cm)",
            "m2",
            3213,
            17.40,
            "310",
        ),
        (
            "02.03.0070",
            "Baustrassen-Unterhaltung waehrend Erdbau (Maintenance of site roads during earthworks)",
            "lsum",
            1,
            1400.00,
            "310",
        ),
        # qty: work area 3,213 m2
        (
            "02.04.0010",
            "Kapillarbrechende Kiesschicht 0/32, d = 15 cm (Capillary-breaking gravel layer 0/32, 15 cm)",
            "m2",
            3213,
            12.80,
            "320",
        ),
        (
            "02.04.0020",
            "Geotextil-Trennvlies GRK 4, Plattendruckversuche und Verdichtungsnachweise (Geotextile fleece GRK 4, plate-load tests and compaction verification)",
            "lsum",
            1,
            87.80,
            "320",
        ),
    ],
    "VE-04": [
        (
            "04.01.0010",
            "Aushub Baugrube und Fundamente, Boden Kl. 3-5, seitlich lagern (Excavation pits and foundations, on-site storage)",
            "m3",
            3900,
            13.20,
            "310",
        ),
        (
            "04.01.0020",
            "Bodenaustausch / Tragschicht 0/45 unter Bodenplatte, d = 40 cm, verdichtet (Soil replacement / sub-base 0/45 under slab, 40 cm)",
            "m2",
            3213,
            14.60,
            "320",
        ),
        ("04.01.0030", "Sauberkeitsschicht C12/15, d = 5 cm (Blinding layer C12/15, 5 cm)", "m2", 3213, 9.80, "320"),
        (
            "04.01.0040",
            "Koecherfundamente 1,90 x 1,90 x 1,05 m, C25/30, inkl. Schalung und Aussparung (Pocket foundations 1.9 x 1.9 x 1.05 m C25/30)",
            "pcs",
            39,
            1560.00,
            "320",
        ),
        (
            "04.01.0050",
            "Frostschuerze umlaufend, h = 80 cm, C25/30 (Perimeter frost skirt 80 cm C25/30)",
            "m",
            234,
            98.00,
            "320",
        ),
        (
            "04.01.0060",
            "Betonstahl B500B Fundamente und Frostschuerze, liefern und verlegen (Rebar B500B foundations and skirt)",
            "t",
            44,
            1390.00,
            "320",
        ),
        (
            "04.01.0070",
            "PE-Folie Trennlage 2-lagig unter Bodenplatte (PE separation layer, 2-ply)",
            "m2",
            3213,
            2.20,
            "320",
        ),
        (
            "04.01.0080",
            "XPS-Daemmung 120 mm unter Bodenplatte, Heizzone, druckfest (XPS insulation 120 mm under slab, heated zone)",
            "m2",
            2050,
            29.50,
            "320",
        ),
        (
            "04.01.0090",
            "Bodenplatte C25/30 (RC-Beton), d = 20 cm, inkl. Einbau und Abziehen (Ground slab C25/30 recycled aggregate, 20 cm)",
            "m3",
            630,
            182.00,
            "320",
        ),
        (
            "04.01.0100",
            "Betonstahl B500B Bodenplatte inkl. Randzonenbewehrung (Rebar B500B ground slab incl. edge zones)",
            "t",
            57,
            1360.00,
            "320",
        ),
        (
            "04.01.0110",
            "Industrieboden: Hartstoffeinstreuung, monolithisch geglaettet, Fugenschnitt und Verguss (Industrial floor: dry-shake topping, power-floated, joints)",
            "m2",
            2820,
            25.50,
            "320",
        ),
        (
            "04.01.0120",
            "Grundleitungen DN 100 - DN 150 unter Bodenplatte inkl. Dichtheitspruefung DIN EN 1610 (Below-slab drainage DN100-150 incl. tightness test)",
            "m",
            450,
            92.00,
            "320",
        ),
        (
            "04.01.0130",
            "Bodeneinlaeufe, Pumpensumpf, Revisionsschaechte komplett (Floor drains, sump, inspection chambers)",
            "lsum",
            1,
            21600.00,
            "320",
        ),
        (
            "04.01.0140",
            "Stahlbeton-Wandscheiben Aussteifung, C30/37, inkl. Schalung (RC shear walls C30/37 incl. formwork)",
            "m3",
            44,
            590.00,
            "330",
        ),
        (
            "04.01.0150",
            "Massivbau Sozialtrakt und Technikraeume, komplett (Masonry/RC staff and plant rooms, complete)",
            "lsum",
            1,
            92800.00,
            "340",
        ),
        # 04.02 Rampen, Sockel und Ergaenzungen Bodenplatte (KG 320).
        (
            "04.02.0010",
            "WU-Beton Rampenwaende Anlieferung C25/30 inkl. Schalung (Watertight RC dock ramp walls C25/30 incl. formwork)",
            "m3",
            64,
            660.00,
            "320",
        ),
        (
            "04.02.0020",
            "Betonstahl B500B Rampenwaende und Aufkantungen (Rebar B500B ramp walls and upstands)",
            "t",
            8,
            1430.00,
            "320",
        ),
        (
            "04.02.0030",
            "Gruben Ueberladebruecken inkl. Randwinkel und Entwaesserung (Dock leveller pits incl. edge angles and drainage)",
            "pcs",
            2,
            8800.00,
            "320",
        ),
        # qty: perimeter 234 m
        (
            "04.02.0040",
            "Randschalung Bodenplatte inkl. Hoehenjustierung (Slab edge formwork incl. level adjustment)",
            "m",
            234,
            25.50,
            "320",
        ),
        (
            "04.02.0050",
            "Dehnfugenprofile Schwerlast einbauen (Heavy-duty expansion joint profiles, installed)",
            "m",
            150,
            88.00,
            "320",
        ),
        (
            "04.02.0060",
            "Fugenprofile Edelstahl Sichtbereiche (Stainless joint profiles in visible areas)",
            "m",
            80,
            66.00,
            "320",
        ),
        # qty: perimeter 234 m
        (
            "04.02.0070",
            "Sockel- und Perimeterabdichtung Bitumendickbeschichtung (Plinth and perimeter waterproofing, thick bitumen coating)",
            "m",
            234,
            33.50,
            "320",
        ),
        (
            "04.02.0080",
            "Aussparungen, Einbauteile, Leerrohre und Huelsen Bodenplatte (Recesses, cast-in items, conduits and sleeves in slab)",
            "lsum",
            1,
            11800.00,
            "320",
        ),
        (
            "04.02.0090",
            "Industrieboden Oberflaechenhaertung und Versiegelung, Zulage (Industrial floor surface hardening and sealing, extra-over)",
            "m2",
            2820,
            3.40,
            "320",
        ),
        # qty: footprint 3,150 m2
        ("04.02.0100", "Betonnachbehandlung Bodenplatte (Concrete curing of ground slab)", "m2", 3150, 1.30, "320"),
        (
            "04.02.0110",
            "Gefaelle- und Ausgleichsestrich Technik- und Nassbereiche (Sloped and levelling screed, plant and wet areas)",
            "m2",
            180,
            39.50,
            "320",
        ),
        # 04.03 Massivbau-Ergaenzungen.
        (
            "04.03.0010",
            "Technik-Mezzanin 160 m2: Spannbeton-Hohldielen d = 20 cm inkl. Aufbeton (Plant mezzanine 160 m2: hollow-core slabs 20 cm incl. topping)",
            "m2",
            160,
            248.00,
            "350",
        ),
        (
            "04.03.0020",
            "Stuerze, Ringanker und Aussparungen Massivbau (Lintels, ring beams and openings in masonry works)",
            "lsum",
            1,
            6400.00,
            "340",
        ),
        (
            "04.02.0120",
            "Stundenlohnarbeiten Rohbau, Kernbohrungen und Anpassarbeiten (Daywork shell, core drilling and adaptations)",
            "lsum",
            1,
            29558.20,
            "320",
        ),
    ],
    "VE-05": [
        (
            "05.01.0010",
            "Stahltrapezprofil 160/250, t = 1,0 mm, als Dachtragschale inkl. Befestigung (Trapezoidal steel deck 160/250, 1.0 mm)",
            "m2",
            3213,
            32.50,
            "360",
        ),
        ("05.01.0020", "Dampfsperre bituminoes, vollflaechig (Bituminous vapour barrier)", "m2", 3213, 7.20, "360"),
        (
            "05.01.0030",
            "PIR-Gefaelledaemmung 200-280 mm, WLG 023 (PIR tapered insulation 200-280 mm)",
            "m2",
            3213,
            54.00,
            "360",
        ),
        (
            "05.01.0040",
            "FPO-Dachbahn, mechanisch befestigt, inkl. An- und Abschluesse (FPO membrane, mechanically fixed)",
            "m2",
            3213,
            29.40,
            "360",
        ),
        (
            "05.01.0050",
            "Attika-Abdeckung Aluminium inkl. Unterkonstruktion (Aluminium parapet capping)",
            "m",
            234,
            70.00,
            "360",
        ),
        (
            "05.01.0060",
            "Lichtkuppeln 1,5 x 1,5 m als NRWG nach DIN 18232, elektrisch 24 V, inkl. Aufsetzkranz (Rooflights 1.5 x 1.5 m as smoke vents per DIN 18232)",
            "pcs",
            10,
            5100.00,
            "360",
        ),
        (
            "05.01.0070",
            "Dachgullys DN 100 beheizt und Notueberlaeufe (Heated roof drains DN100 and emergency overflows)",
            "pcs",
            26,
            780.00,
            "360",
        ),
        (
            "05.01.0080",
            "Durchdringungen und Einfassungen fuer RLT, Kaelte, PV (Penetrations and flashings for HVAC, refrigeration, PV)",
            "lsum",
            1,
            15400.00,
            "360",
        ),
        (
            "05.01.0090",
            "Absturzsicherung Sekuranten umlaufend (Fall-arrest anchors along perimeter)",
            "pcs",
            32,
            310.00,
            "360",
        ),
        (
            "05.01.0100",
            "Blitzschutzanlage komplett inkl. Erdungsanlage und Potentialausgleich (Lightning protection complete incl. earthing)",
            "lsum",
            1,
            42800.00,
            "360",
        ),
        # 05.02 Daecher Ergaenzungen (KG 360).
        # qty: portal width 26 m x 3 m canopy depth = 78 m2
        (
            "05.02.0010",
            "Vordach Eingang Stahlkonstruktion auskragend 26 x 3 m inkl. Abdichtung und Entwaesserung (Entrance canopy, cantilevered steel 26 x 3 m incl. waterproofing and drainage)",
            "m2",
            78,
            600.00,
            "360",
        ),
        # qty: perimeter 234 m
        (
            "05.02.0020",
            "Attika-Aufkantung Daemmung und Holzwerkstoff inkl. Befestigung (Parapet upstand insulation and timber-based board incl. fixing)",
            "m",
            234,
            86.00,
            "360",
        ),
        (
            "05.02.0030",
            "Dachrand- und Anschlussbleche Titanzink (Roof edge and flashing sheets, titanium-zinc)",
            "m",
            234,
            39.50,
            "360",
        ),
        # qty: wind edge and corner zones ~ 25 % of 3,213 m2 = 800 m2
        (
            "05.02.0040",
            "Windsogsicherung Verstaerkung Rand- und Eckzonen, Zulage (Wind uplift reinforcement edge and corner zones, extra-over)",
            "m2",
            800,
            7.20,
            "360",
        ),
        (
            "05.02.0050",
            "Gefaellekeile Kehlen und Grate, Zulage (Tapered crickets at valleys and ridges, extra-over)",
            "m",
            110,
            29.50,
            "360",
        ),
        (
            "05.02.0070",
            "Wartungswege Plattenbelag begehbar (Walkable maintenance paths, paving slabs)",
            "m2",
            170,
            46.00,
            "360",
        ),
        # qty: 10 NRWG rooflights per the smoke-extraction concept
        (
            "05.02.0080",
            "RWA-Steuerzentrale 24 V, Wind- und Regensensorik, Verkabelung 10 NRWG (Smoke vent control 24 V, wind and rain sensors, wiring for 10 NRWG)",
            "lsum",
            1,
            14600.00,
            "360",
        ),
        (
            "05.02.0090",
            "Anschluss Aufsetzkraenze Abdichtung und Durchsturzsicherung Lichtkuppeln (Waterproofing connection to upstand kerbs and fall-through grids)",
            "pcs",
            10,
            640.00,
            "360",
        ),
        (
            "05.02.0110",
            "Notabdichtungen Bauphase, Reinigung, Dichtheitspruefung und Dokumentation (Temporary seals during works, cleaning, leak test and records)",
            "lsum",
            1,
            34707.70,
            "360",
        ),
    ],
    # LV 06 - subsections: 06.01 Sockel und Gruendungsergaenzung (KG 320),
    # 06.02 Stuetzen und Attika-FT (KG 330), 06.03 Dachtragwerk (KG 360).
    "VE-06": [
        # qty: perimeter 234 m; precast socket panels between columns carry the facade base
        (
            "06.01.0010",
            "Stahlbeton-Sockelelemente FT h = 80 cm, tragend fuer Fassade, liefern und montieren (Precast RC socket panels 80 cm, load-bearing for facade, supply and erect)",
            "m",
            234,
            780.00,
            "320",
        ),
        # qty: 39 pocket foundations, one grout joint per column
        (
            "06.01.0020",
            "Vergussmoertel Stuetzenfuesse Koecher C60/75 (Grouting of column feet in pockets, C60/75)",
            "pcs",
            39,
            250.00,
            "320",
        ),
        (
            "06.01.0030",
            "Perimeterdaemmung XPS d = 100 mm Sockelelemente (Perimeter insulation XPS 100 mm at socket panels)",
            "m",
            234,
            66.00,
            "320",
        ),
        (
            "06.01.0040",
            "Fugenabdichtung FT-Stoesse dauerelastisch (Flexible joint sealing of precast element joints)",
            "m",
            460,
            13.00,
            "320",
        ),
        (
            "06.01.0050",
            "Anschlussbewehrung, Einbauteile und Daemmstreifen Sockelelemente (Starter bars, cast-in items and insulation strips, socket panels)",
            "lsum",
            1,
            21400.00,
            "320",
        ),
        # qty: structural grid = 13 axes x 3 bearing rows = 39 columns
        (
            "06.02.0010",
            "FT-Stuetzen C40/50, 40/40 cm, h = 6,6 m, in Koecher versetzt (Precast columns C40/50, 40/40 cm, h = 6.6 m, set in pockets)",
            "pcs",
            39,
            2780.00,
            "330",
        ),
        # qty: portal parapet over the 26 m entrance front
        (
            "06.02.0020",
            "FT-Attikaelemente Portal Eingangsseite, h = 60 cm (Precast parapet elements at entrance portal, 60 cm)",
            "m",
            26,
            440.00,
            "330",
        ),
        (
            "06.02.0030",
            "Bemusterung Sichtoberflaechen FT, Musterflaeche (Sampling of fair-faced precast surfaces, mock-up panel)",
            "lsum",
            1,
            2200.00,
            "330",
        ),
        (
            "06.02.0040",
            "Fugenverguss, Anschlussbewehrung und Montagematerial FT-Stuetzen (Joint grouting, starter bars and erection material for columns)",
            "lsum",
            1,
            12400.00,
            "330",
        ),
        # qty: 13 main binders 25.0 m + 13 side binders 17.0 m
        (
            "06.03.0010",
            "BSH-Binder GL24h, b/h = 20/120 cm, l = 25,0 m, liefern und montieren (Glulam binders GL24h 20/120 cm, l = 25.0 m, supply and erect)",
            "pcs",
            13,
            8100.00,
            "360",
        ),
        (
            "06.03.0020",
            "BSH-Binder GL24h, l = 17,0 m, liefern und montieren (Glulam binders GL24h, l = 17.0 m, supply and erect)",
            "pcs",
            13,
            5950.00,
            "360",
        ),
        # qty: (13 axes - 1) x 2 rows = 24 edge beams
        ("06.03.0030", "BSH-Randtraeger und Wechsel (Glulam edge beams and trimmers)", "pcs", 24, 1180.00, "360"),
        (
            "06.03.0040",
            "Dachverband Zugstaebe Stahl inkl. Anschlussbleche (Steel rod roof bracing incl. connection plates)",
            "lsum",
            1,
            9400.00,
            "360",
        ),
        (
            "06.03.0050",
            "Schwertransporte und Telekran-Einsatz Binder 25,0 m, Sondergenehmigungen (Heavy haulage and crane operations for 25.0 m binders incl. permits)",
            "lsum",
            1,
            13800.00,
            "360",
        ),
        (
            "06.03.0060",
            "Elastomer-Auflagerlager und Verbindungsmittel, komplett (Elastomeric bearings and fasteners, complete)",
            "lsum",
            1,
            56276.00,
            "360",
        ),
    ],
    # LV 07 (KG 330 = 500,000.00).
    "VE-07": [
        # qty: facade balance, sandwich share 1,560 m2
        (
            "07.01.0010",
            "Sandwichpaneele MW-Kern 200 mm, U = 0,20, vertikal verlegt inkl. Befestigung (Sandwich panels mineral-wool core 200 mm, U = 0.20, vertical, incl. fixing)",
            "m2",
            1560,
            220.00,
            "330",
        ),
        (
            "07.01.0020",
            "Laerchenholz-Lattung vorgehaengt auf Alu-UK, Eingangsfassade (Larch battens, hung on aluminium subframe, entrance facade)",
            "m2",
            220,
            272.00,
            "330",
        ),
        (
            "07.01.0030",
            "Zulage Farbton nach Bemusterung, mikroprofilierte Oberflaeche (Extra-over for sampled colour, micro-profiled surface)",
            "m2",
            1560,
            13.00,
            "330",
        ),
        # qty: perimeter 234 m
        (
            "07.01.0040",
            "Sockelblech- und Anschlussprofile, Eckausbildungen (Plinth flashings, connection profiles and corner details)",
            "m",
            234,
            49.00,
            "330",
        ),
        # qty: 3 gates + 7 steel doors + 1 window band = 11 framed openings
        (
            "07.01.0050",
            "Oeffnungen herstellen, Wechselrahmen fuer Tore, Tueren und Fensterband (Forming openings, trimmer frames for gates, doors and window band)",
            "pcs",
            11,
            1180.00,
            "330",
        ),
        (
            "07.01.0060",
            "Fensterbankbleche und Leibungsverkleidungen (Sill flashings and reveal claddings)",
            "m",
            96,
            70.00,
            "330",
        ),
        (
            "07.01.0070",
            "Brandriegel und REI90-Anschluesse an Brandwaende (Fire barriers and REI90 connections to fire walls)",
            "lsum",
            1,
            8200.00,
            "330",
        ),
        # qty: envelope total ~ 234 m x 7.1 m = 1,660 m2
        ("07.01.0080", "Geruestvorhaltung Fassade (Facade scaffolding provision)", "m2", 1660, 10.20, "330"),
        (
            "07.01.0090",
            "Mock-up- und Bemusterungsflaeche Fassade 3 x 3 m (Facade mock-up and sampling area 3 x 3 m)",
            "lsum",
            1,
            3200.00,
            "330",
        ),
        (
            "07.01.0100",
            "Schutzfolien entfernen, Endreinigung Fassade (Removal of protective films, final facade cleaning)",
            "m2",
            1560,
            2.60,
            "330",
        ),
        (
            "07.01.0110",
            "Montagezugaben, Dichtbaender, Kleinstahl und Befestigungsmittel (Erection allowances, sealing tapes, minor steel and fixings)",
            "lsum",
            1,
            13126.00,
            "330",
        ),
    ],
    # LV 08 - subsections: 08.01 Fenster, Tueren, Tore (KG 330), 08.02
    # Verladetechnik und Einbauten (KG 370).
    "VE-08": [
        # qty: glazing share, curtain wall 26.0 x 5.0 m = 130 m2
        (
            "08.01.0010",
            "Pfosten-Riegel-Fassade Alu 26,0 x 5,0 m, Uw = 0,9, inkl. Verglasung (Aluminium curtain wall 26.0 x 5.0 m, Uw = 0.9, incl. glazing)",
            "m2",
            130,
            700.00,
            "330",
        ),
        (
            "08.01.0020",
            "Automatik-Schiebetueranlagen 2-fluegelig im Windfang (Automatic bi-parting sliding doors in the entrance lobby)",
            "pcs",
            2,
            12800.00,
            "330",
        ),
        # qty: window band 32.0 x 1.5 m = 48 m2
        (
            "08.01.0030",
            "Fensterband Alu 32,0 x 1,5 m, festverglast (Aluminium window band 32.0 x 1.5 m, fixed glazing)",
            "m2",
            48,
            560.00,
            "330",
        ),
        (
            "08.01.0040",
            "Sektionaltor 3,5 x 4,0 m ebenerdig, elektrisch (Sectional gate 3.5 x 4.0 m at grade, electric)",
            "pcs",
            1,
            9400.00,
            "330",
        ),
        (
            "08.01.0050",
            "Dock-Tore 3,0 x 3,2 m an den Andockstellen (Dock gates 3.0 x 3.2 m at the loading docks)",
            "pcs",
            2,
            7600.00,
            "330",
        ),
        (
            "08.01.0060",
            "Stahltueren T30/RC2 einfluegelig inkl. Beschlaege (Steel doors T30/RC2 single-leaf incl. hardware)",
            "pcs",
            7,
            3050.00,
            "330",
        ),
        (
            "08.01.0070",
            "Fluchttuersteuerung, Panikschloesser und E-Oeffner (Escape door control, panic locks and electric strikes)",
            "lsum",
            1,
            6200.00,
            "330",
        ),
        (
            "08.01.0080",
            "Beschlaege-Komplettierung, mechanische Schliessanlage (Hardware completion, mechanical master-key system)",
            "lsum",
            1,
            4800.00,
            "330",
        ),
        (
            "08.01.0090",
            "Glasreinigung und Einstellarbeiten zur Schlussabnahme (Glass cleaning and adjustment for final acceptance)",
            "lsum",
            1,
            2400.00,
            "330",
        ),
        (
            "08.01.0100",
            "Anschlussarbeiten, Abdichtung und Einstellung Fassadenelemente (Connection works, sealing and adjustment of facade elements)",
            "lsum",
            1,
            17600.00,
            "330",
        ),
        (
            "08.02.0010",
            "Ueberladebruecken hydraulisch 2,00 x 2,75 m, Tragkraft 60 kN (Hydraulic dock levellers 2.00 x 2.75 m, 60 kN capacity)",
            "pcs",
            2,
            15400.00,
            "370",
        ),
        (
            "08.02.0020",
            "Torabdichtungen aufblasbar inkl. Anfahrpuffer und Radfuehrungen (Inflatable dock shelters incl. bumpers and wheel guides)",
            "pcs",
            2,
            7200.00,
            "370",
        ),
        # qty: warehouse-zone columns plus guards per gate frame ~ 28 guards
        (
            "08.02.0030",
            "Rammschutz innen Anlieferung und Lager, Stahlbuegel verzinkt (Interior impact protection delivery and warehouse, galvanised steel hoops)",
            "pcs",
            28,
            310.00,
            "370",
        ),
        (
            "08.02.0040",
            "Stahltreppe Technik-Mezzanin inkl. Gelaender (Steel stair to plant mezzanine incl. railing)",
            "pcs",
            1,
            10200.00,
            "370",
        ),
        (
            "08.02.0050",
            "Wartungsstege und Leiteranlagen Technikflaechen (Maintenance walkways and ladder systems, plant areas)",
            "lsum",
            1,
            25490.00,
            "370",
        ),
    ],
    # LV 09 - subsections: 09.01 Waende und Tueren (KG 340), 09.02 Boeden und
    # Decken (KG 350).
    "VE-09": [
        (
            "09.01.0010",
            "Trockenbauwaende Sozialtrakt und Bueros, doppelt beplankt, MW-Daemmung (Drywall partitions staff wing and offices, double-boarded, mineral wool)",
            "m2",
            780,
            94.00,
            "340",
        ),
        (
            "09.01.0020",
            "Brandwand REI90 Trennung Technikraum und Lager (Fire wall REI90 separating plant room and warehouse)",
            "m2",
            340,
            150.00,
            "340",
        ),
        # qty: room schedule staff wing = 22 doors
        (
            "09.01.0030",
            "Innentueren Holz mit Stahl-Umfassungszarge, teils Feuchtraum (Interior timber doors with steel frames, partly wet-room rated)",
            "pcs",
            22,
            1000.00,
            "340",
        ),
        (
            "09.01.0040",
            "T30-RS-Tueren Technik- und LV-Raum (T30 smoke-control doors, plant and main LV room)",
            "pcs",
            5,
            2400.00,
            "340",
        ),
        (
            "09.01.0050",
            "Wandfliesen WC, Umkleiden und Backstation h = 2,0 m (Wall tiling WCs, changing rooms and bake-off, h = 2.0 m)",
            "m2",
            300,
            70.00,
            "340",
        ),
        (
            "09.01.0060",
            "Innenwandbekleidung Windfang und Kassenzone, HPL-Paneele (Interior wall cladding lobby and checkout zone, HPL panels)",
            "m2",
            120,
            148.00,
            "340",
        ),
        (
            "09.01.0070",
            "Vorsatzschalen und Installationswaende Nassbereiche (Furring and installation walls in wet areas)",
            "m2",
            150,
            80.00,
            "340",
        ),
        (
            "09.01.0080",
            "Eckschutzschienen und Rammschutz-Sockelleisten Flure (Corner guards and impact-protection skirtings, corridors)",
            "m",
            110,
            37.00,
            "340",
        ),
        (
            "09.01.0090",
            "Malerarbeiten Waende Innenbereich, Dispersion (Painting of interior walls, emulsion)",
            "m2",
            2250,
            10.20,
            "340",
        ),
        (
            "09.01.0100",
            "Beschlaege, Tuerstopper, Revisionsklappen und Kleinleistungen (Hardware, door stops, access panels and minor works)",
            "lsum",
            1,
            12400.00,
            "340",
        ),
        (
            "09.02.0010",
            "Zementestrich schwimmend Sozialtrakt (Floating cement screed, staff wing)",
            "m2",
            350,
            39.50,
            "350",
        ),
        # qty: room schedule break + changing + WCs + offices = 120 m2
        (
            "09.02.0020",
            "Bodenfliesen R10 Sozialraeume und WC inkl. Abdichtung (Floor tiling R10 staff rooms and WCs incl. waterproofing)",
            "m2",
            120,
            98.00,
            "350",
        ),
        (
            "09.02.0030",
            "Sauberlaufzone Eingang inkl. Edelstahlrahmen (Entrance matting zone incl. stainless frame)",
            "m2",
            30,
            330.00,
            "350",
        ),
        (
            "09.02.0040",
            "Abgehaengte Rasterdecke Sozialtrakt und Bueros (Suspended grid ceiling, staff wing and offices)",
            "m2",
            270,
            60.00,
            "350",
        ),
        (
            "09.02.0050",
            "Akustikdecke Kassenzone und Windfang (Acoustic ceiling, checkout zone and lobby)",
            "m2",
            220,
            86.00,
            "350",
        ),
        ("09.02.0060", "Revisionsoeffnungen Decke (Ceiling access openings)", "pcs", 14, 190.00, "350"),
        (
            "09.02.0070",
            "Sockelleisten, Uebergangsprofile und Restarbeiten Bodenbelaege (Skirtings, transition profiles and finishing works, floor coverings)",
            "lsum",
            1,
            18235.00,
            "350",
        ),
    ],
    "VE-14": [
        (
            "14.01.0010",
            "Luft/Wasser-Waermepumpe R290, 75 kW heizen / 92 kW kuehlen, inkl. hydraulischer Einbindung (Air/water heat pump R290 75/92 kW incl. hydraulics)",
            "pcs",
            1,
            68500.00,
            "420",
        ),
        (
            "14.01.0020",
            "Fussbodenheizung Vorlauf 35/28 Grad C inkl. Verteiler, gespeist aus Kaelte-Abwaerme (Underfloor heating 35/28 C incl. manifolds)",
            "m2",
            2050,
            32.00,
            "420",
        ),
        (
            "14.01.0030",
            "RLT-Geraet 14.000 m3/h, Rotations-WRG eta = 78 %, adiabate Kuehlung, auf Technik-Mezzanin (AHU 14,000 m3/h rotary heat recovery, adiabatic cooling)",
            "pcs",
            1,
            74800.00,
            "430",
        ),
        (
            "14.01.0040",
            "Lueftungskanaele verzinkt inkl. Daemmung und Brandschotts (Galvanised ductwork incl. insulation and firestopping)",
            "m2",
            1180,
            39.50,
            "430",
        ),
        (
            "14.01.0050",
            "Tuerluftschleier Eingang 11 kW, WRG-gespeist (Entrance air curtain 11 kW, heat-recovery fed)",
            "pcs",
            2,
            7200.00,
            "430",
        ),
        (
            "14.01.0060",
            "Sanitaerinstallation komplett: WC-Anlagen, Sozialraeume, TWW-Speicher 400 l (Plumbing complete: WCs, staff rooms, 400 l DHW tank)",
            "lsum",
            1,
            56400.00,
            "410",
        ),
        (
            "14.01.0070",
            "Regelung und GLT-Schnittstellen HLS, Einregulierung, Abnahme (Controls and BMS interfaces HVAC, balancing, acceptance)",
            "lsum",
            1,
            26800.00,
            "430",
        ),
        # 14.02 Sanitaer Ergaenzungen (KG 410).
        (
            "14.02.0010",
            "Schmutz- und Regenwasserleitungen im Gebaeude, SML/PE, inkl. Daemmung (Foul and rainwater pipework inside the building, cast iron/PE, insulated)",
            "m",
            430,
            66.00,
            "410",
        ),
        (
            "14.02.0020",
            "Trinkwasser-Installation Edelstahl press inkl. Daemmung und Spuelung (Potable water installation, pressed stainless, insulated and flushed)",
            "m",
            500,
            60.00,
            "410",
        ),
        # qty: 13 internal downpipes, one per roof gully group
        (
            "14.02.0030",
            "Regenwasser-Fallleitungen innenliegend DN 100 inkl. Anschluss (Internal rainwater downpipes DN 100 incl. connection)",
            "pcs",
            13,
            1500.00,
            "410",
        ),
        (
            "14.02.0040",
            "Fettabscheider NS 7 Drive-in-Backstation inkl. Einbau (Grease separator NS 7 for drive-through bake-off incl. installation)",
            "pcs",
            1,
            11800.00,
            "410",
        ),
        # qty: fire concept = 5 wall hydrants type S
        (
            "14.02.0050",
            "Wandhydranten Typ S inkl. Leitungsnetz (Wall hydrants type S incl. pipe network)",
            "pcs",
            5,
            4100.00,
            "410",
        ),
        (
            "14.02.0060",
            "Wasserzaehleranlage, Feinfilter und Druckminderer (Water metering assembly, fine filter and pressure reducer)",
            "lsum",
            1,
            7400.00,
            "410",
        ),
        (
            "14.02.0070",
            "Brandschotts, Restdaemmung und Einweisung Sanitaer (Fire stopping, remaining insulation and instruction, plumbing)",
            "lsum",
            1,
            21800.00,
            "410",
        ),
        # 14.03 Heizung Ergaenzungen (KG 420).
        (
            "14.03.0010",
            "Pufferspeicher 3.000 l WRG-Einbindung inkl. Armaturen (Buffer tank 3,000 l for heat-recovery integration incl. valves)",
            "pcs",
            1,
            15400.00,
            "420",
        ),
        (
            "14.03.0020",
            "Rohrnetz Heizung Verteilung Decke, Stahl/Verbundrohr (Heating distribution pipework at ceiling, steel/composite)",
            "m",
            450,
            74.00,
            "420",
        ),
        (
            "14.03.0030",
            "Daemmung Heizleitungen inkl. Armaturen (Insulation of heating pipework incl. valves)",
            "m",
            450,
            22.50,
            "420",
        ),
        (
            "14.03.0040",
            "Einbindung WRG Kaelteanlage, Waermetauscher und Regelventile (Integration of refrigeration heat recovery, exchangers and control valves)",
            "lsum",
            1,
            18800.00,
            "420",
        ),
        (
            "14.03.0050",
            "Nahwaermeleitung erdverlegt WP zu Technikzentrale, PEX DN 65 (Buried heat main, heat pump to plant room, PEX DN 65)",
            "m",
            55,
            340.00,
            "420",
        ),
        (
            "14.03.0060",
            "Aufstellung WP: Fundament, Schwingungsdaempfer, Schallschutzhaube (Heat pump installation: base, vibration dampers, acoustic hood)",
            "lsum",
            1,
            11400.00,
            "420",
        ),
        (
            "14.03.0070",
            "Heizkoerper und Konvektoren Nebenraeume (Radiators and convectors, ancillary rooms)",
            "pcs",
            18,
            660.00,
            "420",
        ),
        (
            "14.03.0080",
            "Einzelraumregelung FBH, Raumthermostate (Room-by-room underfloor heating control, thermostats)",
            "pcs",
            26,
            395.00,
            "420",
        ),
        (
            "14.03.0090",
            "Druckhaltung, MAG und Sicherheitsarmaturen (Pressurisation, expansion vessel and safety valves)",
            "lsum",
            1,
            7800.00,
            "420",
        ),
        # 14.04 Lueftung Ergaenzungen (KG 430).
        (
            "14.04.0010",
            "Brandschutz- und Jalousieklappen inkl. Ansteuerung (Fire and louvre dampers incl. actuation)",
            "pcs",
            22,
            660.00,
            "430",
        ),
        (
            "14.04.0020",
            "Wickelfalzrohr-Netz Nebenraeume inkl. Formteile (Spiral duct network ancillary rooms incl. fittings)",
            "m",
            290,
            54.00,
            "430",
        ),
        (
            "14.04.0030",
            "Luftdurchlaesse und Weitwurfduesen Verkaufsraum (Air diffusers and long-throw nozzles, sales area)",
            "pcs",
            52,
            295.00,
            "430",
        ),
        (
            "14.04.0040",
            "Abluftanlagen WC, Sozialraeume und Backstation (Extract systems WCs, staff rooms and bake-off)",
            "lsum",
            1,
            16400.00,
            "430",
        ),
        (
            "14.04.0050",
            "Aussenluft- und Fortluftgitter, Schalldaempfer (Outdoor and exhaust air louvres, attenuators)",
            "lsum",
            1,
            11200.00,
            "430",
        ),
        (
            "14.04.0060",
            "Splitgeraet Kuehlung LV- und Serverraum (Split cooling unit, main LV and server room)",
            "pcs",
            1,
            7400.00,
            "430",
        ),
        (
            "14.04.0070",
            "Einregulierung Luftmengen, Hygieneinspektion und IBN RLT (Air volume balancing, hygiene inspection and AHU commissioning)",
            "lsum",
            1,
            49315.00,
            "430",
        ),
    ],
    "VE-15": [
        (
            "15.01.0010",
            "Transkritische CO2-Booster-Verbundanlage mit Parallelverdichtung, NK 120 kW / TK 34 kW (Transcritical CO2 booster rack with parallel compression, MT 120 / LT 34 kW)",
            "lsum",
            1,
            145000.00,
            "470",
        ),
        (
            "15.01.0020",
            "Gaskuehler Dachaufstellung inkl. Stahlrahmen und Schwingungsdaempfung (Gas cooler roof-mounted incl. steel frame)",
            "pcs",
            1,
            21400.00,
            "470",
        ),
        (
            "15.01.0030",
            "Waermerueckgewinnung 2-stufig (Enthitzer + Kondensator) bis 150 kW thermisch (Two-stage heat recovery, desuperheater plus condenser, up to 150 kW)",
            "lsum",
            1,
            29800.00,
            "470",
        ),
        (
            "15.01.0040",
            "CO2-Rohrleitungsnetz K65/Edelstahl inkl. Daemmung und Halterung (CO2 piping network K65/stainless incl. insulation)",
            "m",
            520,
            98.00,
            "470",
        ),
        (
            "15.01.0050",
            "NK-Kuehlzelle +2 Grad C, ca. 60 m2, PU 100 mm, inkl. Tuer (Chiller cell +2 C, ~60 m2, PU 100 mm incl. door)",
            "pcs",
            1,
            16400.00,
            "470",
        ),
        (
            "15.01.0060",
            "Obst/Gemuese-Kuehlraum +8 Grad C, ca. 32 m2, PU 80 mm (Produce cool room +8 C, ~32 m2, PU 80 mm)",
            "pcs",
            1,
            9400.00,
            "470",
        ),
        (
            "15.01.0070",
            "TK-Zelle -22 Grad C, ca. 40 m2, PU 150 mm, inkl. Boden (Freezer room ~40 m2, PU 150 mm incl. floor)",
            "pcs",
            1,
            29500.00,
            "470",
        ),
        (
            "15.01.0080",
            "Luftkuehler/Verdampfer CO2-geeignet, Zellen (CO2 unit coolers for cold rooms)",
            "pcs",
            6,
            3100.00,
            "470",
        ),
        (
            "15.01.0090",
            "Anbindung Verbund-Kuehlmoebel (bauseits gestellt), Verrohrung und IBN (Connection of operator-supplied remote cabinets)",
            "pcs",
            18,
            1200.00,
            "470",
        ),
        (
            "15.01.0100",
            "CO2-Gaswarnanlage Maschinenraum/Verkaufsraum (CO2 gas detection system)",
            "lsum",
            1,
            8400.00,
            "470",
        ),
        (
            "15.01.0110",
            "MSR/Anlagenregelung Kaelte, inkl. Fernueberwachung (Refrigeration controls incl. remote monitoring)",
            "lsum",
            1,
            15400.00,
            "470",
        ),
        (
            "15.01.0120",
            "Dichtheitspruefung, Inbetriebnahme, Abnahme EN 378, Einweisung (Pressure test, commissioning, EN 378 acceptance)",
            "lsum",
            1,
            10200.00,
            "470",
        ),
        # 15.02 Verbund-Kuehlmoebel und Komplettierung (KG 470).
        # qty: cabinet layout = 60 lfm chilled (glass doors)
        (
            "15.02.0010",
            "NK-Kuehlregale steckerlos, Glastueren, H = 2,0 m, anschlussfertig an Verbund (Remote chilled multidecks, glass doors, H = 2.0 m, rack-ready)",
            "m",
            60,
            5050.00,
            "470",
        ),
        # qty: cabinet layout = 28 lfm frozen
        (
            "15.02.0020",
            "TK-Schrankmoebel Glastueren, Verbundanschluss (Remote glass-door freezer cabinets, rack-connected)",
            "m",
            28,
            6500.00,
            "470",
        ),
        # qty: cabinet layout = 8 lfm serve-over
        (
            "15.02.0030",
            "Bedientheke Frische 8 lfm inkl. Anbindung Maschinensatz (Serve-over fresh counter 8 lm incl. rack connection)",
            "m",
            8,
            8100.00,
            "470",
        ),
        # qty: cabinet sections + cold rooms + serve-over + spares ~ 32 control points
        (
            "15.02.0040",
            "Kuehlstellenregler, Fuehler und Busverkabelung (Case controllers, sensors and bus wiring)",
            "pcs",
            32,
            495.00,
            "470",
        ),
        (
            "15.02.0050",
            "Abtau- und Tauwasserleitungen isoliert bis Grundleitung (Insulated defrost and condensate pipework to below-slab drainage)",
            "m",
            220,
            88.00,
            "470",
        ),
        (
            "15.02.0060",
            "Schallschutzmassnahmen und Aufstellrahmen Verbundanlage (Acoustic measures and mounting frame for the rack)",
            "lsum",
            1,
            10400.00,
            "470",
        ),
        (
            "15.02.0070",
            "Wartungsvertrag Jahr 1 inkl. 24h-Bereitschaft (Maintenance contract year 1 incl. 24h standby)",
            "lsum",
            1,
            7800.00,
            "470",
        ),
        (
            "15.02.0080",
            "CO2-Erstbefuellung, Dichtheitsnachweis und Probebetrieb 72 h (Initial CO2 charge, leak verification and 72 h trial run)",
            "lsum",
            1,
            140.00,
            "470",
        ),
    ],
    "VE-16": [
        (
            "16.01.0010",
            "NSHV 1.600 A inkl. Messung und Zaehlerplatz (Main LV board 1,600 A incl. metering)",
            "pcs",
            1,
            44400.00,
            "440",
        ),
        (
            "16.01.0020",
            "Kabeltrassen und Leitungsnetz komplett (Cable trays and wiring complete)",
            "m",
            2200,
            25.50,
            "440",
        ),
        (
            "16.01.0030",
            "LED-Lichtbandsystem Verkaufsraum 800 lx, DALI mit Tageslicht-/Praesenzregelung (LED light-band system sales area 800 lx, DALI daylight/presence control)",
            "m",
            640,
            145.00,
            "440",
        ),
        (
            "16.01.0040",
            "Beleuchtung Lager/Nebenraeume 300 lx und Sicherheitsbeleuchtung (Warehouse/ancillary lighting 300 lx and emergency lighting)",
            "lsum",
            1,
            33800.00,
            "440",
        ),
        (
            "16.01.0050",
            "Elektroinstallation Sozialtrakt, Unterverteilungen, Endgeraete (Electrical installation staff wing, sub-distribution boards)",
            "lsum",
            1,
            30400.00,
            "440",
        ),
        (
            "16.01.0060",
            "Brandmeldeanlage Kat. 2 mit Aufschaltung (Fire alarm system cat. 2 with monitoring link)",
            "lsum",
            1,
            28600.00,
            "450",
        ),
        (
            "16.01.0070",
            "Datennetz Cat 6A inkl. IT-Schrank und Patchfeld (Data network Cat 6A incl. IT cabinet)",
            "lsum",
            1,
            17400.00,
            "450",
        ),
        (
            "16.01.0080",
            "GLT/Gebaeudeautomation: Feldgeraete, Aufschaltung, Energiemonitoring ISO 50001-faehig (BMS field devices, integration, ISO 50001-ready energy monitoring)",
            "lsum",
            1,
            22400.00,
            "480",
        ),
        # 16.02 Starkstrom Ergaenzungen (KG 440).
        (
            "16.02.0010",
            "Kompakt-Trafostation 800 kVA inkl. MS-Schaltanlage und IBN (Compact transformer station 800 kVA incl. MV switchgear and commissioning)",
            "pcs",
            1,
            132000.00,
            "440",
        ),
        (
            "16.02.0020",
            "Unterverteilungen Markt, Technik und Kasse (Sub-distribution boards sales, plant and checkout)",
            "pcs",
            8,
            7600.00,
            "440",
        ),
        (
            "16.02.0030",
            "Installationsgeraete, Schalter, Steckdosen und CEE-Anschluesse (Wiring accessories, switches, sockets and CEE outlets)",
            "lsum",
            1,
            21400.00,
            "440",
        ),
        (
            "16.02.0040",
            "LED-Panels Nebenraeume und Sozialtrakt inkl. Praesenzmelder (LED panels ancillary rooms and staff wing incl. presence detectors)",
            "pcs",
            78,
            295.00,
            "440",
        ),
        (
            "16.02.0050",
            "Anschluss Maschinen und Anlagen: RLT, WP, Kaelte, Backoefen, Tore (Connection of plant: AHU, heat pump, refrigeration, ovens, gates)",
            "lsum",
            1,
            36800.00,
            "440",
        ),
        (
            "16.02.0060",
            "USV-Anlage 30 kVA Kassen- und IT-Versorgung (UPS 30 kVA for checkout and IT supply)",
            "pcs",
            1,
            28500.00,
            "440",
        ),
        (
            "16.02.0070",
            "Fassadenbeleuchtung und Anschluss Werbeanlagen (Facade lighting and connection of signage)",
            "lsum",
            1,
            14600.00,
            "440",
        ),
        (
            "16.02.0080",
            "Potentialausgleich, Erdung und Ueberspannungsschutz Typ 1+2 (Equipotential bonding, earthing and surge protection type 1+2)",
            "lsum",
            1,
            11400.00,
            "440",
        ),
        # qty: perimeter 234 m ring earth electrode
        (
            "16.02.0090",
            "Fundament- und Ringerder inkl. Anschlussfahnen (Foundation and ring earth electrode incl. connection lugs)",
            "m",
            234,
            15.00,
            "440",
        ),
        (
            "16.02.0100",
            "Leerrohre und Bodentanks Kassenzone (Conduits and floor boxes, checkout zone)",
            "lsum",
            1,
            9400.00,
            "440",
        ),
        (
            "16.02.0110",
            "Torsteuerungen und Tuerkommunikation Anlieferung anschliessen (Connection of gate controls and door intercom, delivery area)",
            "lsum",
            1,
            4200.00,
            "440",
        ),
        # 16.03 Sicherheits- und Kommunikationstechnik (KG 450).
        (
            "16.03.0010",
            "Videoueberwachung 20 IP-Kameras inkl. Aufzeichnung (Video surveillance, 20 IP cameras incl. recording)",
            "pcs",
            20,
            1480.00,
            "450",
        ),
        (
            "16.03.0020",
            "Einbruchmeldeanlage Aussenhaut und Bueros (Intruder alarm, building envelope and offices)",
            "lsum",
            1,
            16400.00,
            "450",
        ),
        (
            "16.03.0030",
            "ELA- und Durchsageanlage Verkaufsraum (Public address system, sales area)",
            "lsum",
            1,
            11400.00,
            "450",
        ),
        (
            "16.03.0040",
            "Elektronische Schliessanlage und Zutrittskontrolle Personal (Electronic locking and staff access control)",
            "lsum",
            1,
            15600.00,
            "450",
        ),
        # 16.04 Gebaeudeautomation (KG 480).
        (
            "16.04.0010",
            "Energiezaehler M-Bus, 18 Messstellen, Aufschaltung (M-Bus energy meters, 18 metering points, integration)",
            "pcs",
            18,
            695.00,
            "480",
        ),
        (
            "16.04.0020",
            "GLT-Visualisierung, Trendaufzeichnung, Fernzugriff und Einweisung (BMS visualisation, trending, remote access and instruction)",
            "lsum",
            1,
            62970.00,
            "480",
        ),
    ],
    # LV 17 (KG 440, owner direct award VP-11) - subsections: 17.01 PV-Anlage,
    # 17.02 Speicher und Netz, 17.03 Ladeinfrastruktur.
    "VE-17": [
        # qty: 864 modules a 440 Wp = 380.2 kWp
        (
            "17.01.0010",
            "PV-Module 440 Wp, Ost-West-Aufstaenderung aerodynamisch (PV modules 440 Wp, aerodynamic east-west racking)",
            "pcs",
            864,
            270.00,
            "440",
        ),
        # qty: 60 % of the solar-suitable roof = 1,920 m2 (KlimaG BW duty)
        (
            "17.01.0020",
            "Unterkonstruktion und Ballastierung inkl. Bautenschutzmatten (Substructure and ballasting incl. protection mats)",
            "m2",
            1920,
            29.50,
            "440",
        ),
        (
            "17.01.0030",
            "Wechselrichter 30 kW inkl. DC-Ueberspannungsschutz (Inverters 30 kW incl. DC surge protection)",
            "pcs",
            12,
            4200.00,
            "440",
        ),
        (
            "17.01.0040",
            "DC-Verkabelung, Stringleitungen und Generatoranschlusskasten (DC cabling, string lines and generator junction box)",
            "lsum",
            1,
            15400.00,
            "440",
        ),
        (
            "17.01.0050",
            "Dachdurchfuehrungen DC-Leitungen inkl. Abdichtungskoordination (Roof penetrations for DC cabling incl. waterproofing coordination)",
            "pcs",
            8,
            440.00,
            "440",
        ),
        (
            "17.01.0060",
            "Erstreinigung Module und Kennlinien-Abnahmemessung (Initial module cleaning and IV-curve acceptance measurement)",
            "lsum",
            1,
            3800.00,
            "440",
        ),
        (
            "17.02.0010",
            "Batteriespeicher 240 kWh inkl. BMS und Anbindung (Battery storage 240 kWh incl. BMS and integration)",
            "pcs",
            1,
            110000.00,
            "440",
        ),
        (
            "17.02.0020",
            "NA-Schutz, Zaehlerwesen und Direktvermarktungs-Gateway (Grid protection, metering and direct-marketing gateway)",
            "lsum",
            1,
            16400.00,
            "440",
        ),
        (
            "17.02.0030",
            "Dynamisches Lastmanagement fuer Ladeinfrastruktur (Dynamic load management for EV charging)",
            "lsum",
            1,
            11400.00,
            "440",
        ),
        # qty: 4 DC chargers a 2 points + 6 AC wallboxes a 2 points = 20 charge points
        (
            "17.03.0010",
            "DC-Schnellladestation 150 kW mit 2 Ladepunkten (DC fast charger 150 kW with 2 charge points)",
            "pcs",
            4,
            27000.00,
            "440",
        ),
        ("17.03.0020", "AC-Wallboxen 22 kW (AC wallboxes 22 kW)", "pcs", 6, 2950.00, "440"),
        (
            "17.03.0030",
            "Tiefbau und Fundamente Ladestationen inkl. Schutzbuegel (Civils and foundations for chargers incl. protection hoops)",
            "lsum",
            1,
            19400.00,
            "440",
        ),
        # qty: GEIG pre-equipment for 50 stalls, conduit route 360 m
        (
            "17.03.0040",
            "Leerrohr- und Kabeltrasse GEIG, 50 Stellplaetze vorgeruestet (Conduit and cable route per GEIG, 50 stalls pre-equipped)",
            "m",
            360,
            38.00,
            "440",
        ),
        (
            "17.03.0050",
            "Anmeldung, Zertifikate VDE-AR-N 4110, Monitoring und Dokumentation (Registration, VDE-AR-N 4110 certificates, monitoring and records)",
            "lsum",
            1,
            380.00,
            "440",
        ),
    ],
    "VE-18": [
        (
            "18.01.0010",
            "Oberbodenabtrag und Erdarbeiten Aussenanlagen (Topsoil strip and earthworks external areas)",
            "m3",
            2560,
            10.20,
            "510",
        ),
        (
            "18.01.0020",
            "Frostschutzschicht 0/45, d = 40 cm, fuer befestigte Flaechen (Frost protection layer 0/45, 40 cm)",
            "m2",
            5950,
            13.90,
            "520",
        ),
        (
            "18.01.0030",
            "Asphalttrag- und Deckschicht Fahrgassen und Anlieferhof (Asphalt base and wearing course, lanes and delivery yard)",
            "m2",
            4080,
            43.50,
            "520",
        ),
        (
            "18.01.0040",
            "Draen-Betonpflaster Stellplaetze, d = 10 cm, sickerfaehig (Permeable concrete pavers parking stalls, 10 cm)",
            "m2",
            1870,
            49.00,
            "520",
        ),
        ("18.01.0050", "Bordsteine und Einfassungen (Kerbs and edgings)", "m", 1180, 29.50, "520"),
        (
            "18.01.0060",
            "Entwaesserungsrinnen und Hofablaeufe inkl. Anschluss (Drainage channels and yard gullies incl. connection)",
            "lsum",
            1,
            29800.00,
            "540",
        ),
        (
            "18.01.0070",
            "Rigole 260 m3 und Versickerungsmulden 450 m2 inkl. Drosselschacht 15 l/s (DWA-A 138) (Retention trench 260 m3 and infiltration swales 450 m2 incl. 15 l/s throttle)",
            "lsum",
            1,
            82500.00,
            "540",
        ),
        (
            "18.01.0080",
            "Zisterne 15 m3 inkl. Pumpentechnik fuer Bewaesserung (Cistern 15 m3 incl. pump for irrigation)",
            "pcs",
            1,
            11400.00,
            "540",
        ),
        (
            "18.01.0090",
            "Fahrbahn- und Stellplatzmarkierung inkl. Sonderflaechen (Lane and stall marking incl. special stalls)",
            "m",
            1280,
            4.40,
            "520",
        ),
        (
            "18.01.0100",
            "Aussenbeleuchtung 18 LED-Mastleuchten h = 6 m, 3000 K insektenfreundlich, inkl. Kabel und Fundamente (External lighting 18 LED masts 6 m incl. cabling and foundations)",
            "pcs",
            18,
            2450.00,
            "540",
        ),
        (
            "18.01.0110",
            "Hochstamm-Baeume pflanzen inkl. Substrat und Verankerung (Standard trees incl. substrate and anchoring)",
            "pcs",
            25,
            1020.00,
            "550",
        ),
        (
            "18.01.0120",
            "Strauch-/Rasenflaechen und Fassadenbegruenung (Shrub/lawn areas and green facade)",
            "m2",
            2150,
            13.00,
            "550",
        ),
        # 18.02 Erdbau Aussenanlagen (KG 510).
        # qty: paved area 5,950 m2 x 0.6 m formation depth = 3,570 m3
        (
            "18.02.0010",
            "Kofferaushub befestigte Flaechen, d = 60 cm (Box excavation for paved areas, 60 cm)",
            "m3",
            3570,
            14.60,
            "510",
        ),
        (
            "18.02.0020",
            "Erdbau Profilierung Aussenanlagen, Auf- und Abtrag, Feinplanum (Earthworks profiling external areas, cut and fill, fine grading)",
            "m3",
            3900,
            12.80,
            "510",
        ),
        (
            "18.02.0030",
            "Entsorgung Ueberschussmassen Aussenanlagen Z1.1 (Disposal of surplus soil external works, class Z1.1)",
            "m3",
            2950,
            17.40,
            "510",
        ),
        (
            "18.02.0040",
            "Liefern und Einbau Fuellboden und Frostschutzmaterial (Supply and place fill and frost-protection material)",
            "m3",
            2300,
            25.20,
            "510",
        ),
        (
            "18.02.0050",
            "Leitungsgraeben Entwaesserung und Beleuchtung inkl. Verfuellung (Service trenches drainage and lighting incl. backfill)",
            "m",
            850,
            29.40,
            "510",
        ),
        # qty: green areas 2,150 m2 + swales 450 m2 = 2,600 m2
        (
            "18.02.0060",
            "Erdplanum und Verdichtung Pflanz- und Muldenbereiche (Formation and compaction, planting and swale areas)",
            "m2",
            2600,
            3.60,
            "510",
        ),
        (
            "18.02.0070",
            "Baugruben Rigole und Zisterne ausheben und verfuellen (Excavation and backfill for retention trench and cistern)",
            "m3",
            820,
            19.20,
            "510",
        ),
        # 18.03 Belaege Ergaenzungen (KG 520).
        # qty: asphalt 4,080 + pavers 1,870 = 5,950 m2
        (
            "18.03.0010",
            "Geogitter-Bewehrung Unterbau befestigte Flaechen (Geogrid reinforcement of paved-area sub-base)",
            "m2",
            5950,
            10.20,
            "520",
        ),
        (
            "18.03.0020",
            "Asphaltbinderschicht AC 16 BS, d = 6 cm (Asphalt binder course AC 16 BS, 6 cm)",
            "m2",
            4080,
            20.40,
            "520",
        ),
        # qty: delivery yard 960 m2 (of the 4,080 m2 asphalt)
        (
            "18.03.0030",
            "Zulage PmB-Asphalt Anlieferhof Schwerlast (Extra-over polymer-modified asphalt, heavy-duty delivery yard)",
            "m2",
            960,
            19.20,
            "520",
        ),
        # qty: walkways 280 m2
        (
            "18.03.0040",
            "Gehwegplatten und Betonpflaster Gehwege, d = 8 cm (Paving slabs and concrete pavers, walkways, 8 cm)",
            "m2",
            280,
            56.00,
            "520",
        ),
        (
            "18.03.0050",
            "Tiefbord-Randeinfassung Pflasterflaechen (Flush kerb edging of paved areas)",
            "m",
            460,
            25.50,
            "520",
        ),
        (
            "18.03.0060",
            "Bordrinnen und Muldensteine V-Profil (Kerb channels and V-profile dished channels)",
            "m",
            300,
            48.00,
            "520",
        ),
        (
            "18.03.0070",
            "Eingangspodest und Rampen Betonfertigteile, taktile Elemente (Entrance landing and ramps, precast concrete, tactile elements)",
            "lsum",
            1,
            11400.00,
            "520",
        ),
        (
            "18.03.0080",
            "Zulage Einkornbeton-Bettung und Splittfugen Draen-Pflaster (Extra-over no-fines concrete bedding and grit joints, permeable pavers)",
            "m2",
            1870,
            10.20,
            "520",
        ),
        # qty: 8 accessible + 8 parent-child + 20 EV stalls = 36 special stalls
        (
            "18.03.0090",
            "Markierung Sonderstellplaetze: barrierefrei, Eltern-Kind, E-Laden (Marking of special stalls: accessible, parent-child, EV)",
            "pcs",
            36,
            98.00,
            "520",
        ),
        (
            "18.03.0100",
            "Beschilderung Parkplatz und Wegweisung (Car park signage and wayfinding)",
            "pcs",
            24,
            250.00,
            "520",
        ),
        (
            "18.03.0110",
            "Anschluss oeffentliche Strasse inkl. Bordabsenkung (Connection to the public road incl. dropped kerb)",
            "lsum",
            1,
            16400.00,
            "520",
        ),
        (
            "18.03.0120",
            "Anrampungen und Anpassung Bestandsgehweg Pfinzstrasse (Ramping and adaptation of the existing footway, Pfinzstrasse)",
            "lsum",
            1,
            14600.00,
            "520",
        ),
        (
            "18.03.0130",
            "Fugenverguss Asphaltanschluesse und Abnahmebefahrung (Joint sealing of asphalt connections and acceptance drive-over)",
            "m",
            500,
            8.80,
            "520",
        ),
        # 18.04 Entwaesserung Ergaenzungen (KG 540).
        (
            "18.04.0010",
            "Kontrollschaechte DN 600 Rigolenanbindung (Inspection chambers DN 600 at retention trench connection)",
            "pcs",
            3,
            1500.00,
            "540",
        ),
        (
            "18.04.0020",
            "Anschlussleitung Dachentwaesserung an Rigole DN 200 (Connection pipe, roof drainage to retention trench, DN 200)",
            "lsum",
            1,
            8400.00,
            "540",
        ),
        # 18.05 Begruenung Ergaenzungen (KG 550).
        (
            "18.05.0010",
            "Baumscheiben, Unterpflanzung und Tropfbewaesserung (Tree pits, underplanting and drip irrigation)",
            "pcs",
            25,
            440.00,
            "550",
        ),
        (
            "18.05.0020",
            "Rankhilfen Fassadenbegruenung, Edelstahlseile (Climbing aids for facade greening, stainless cables)",
            "m2",
            160,
            148.00,
            "550",
        ),
        (
            "18.05.0030",
            "Staudenpflanzung Eingangsbereich, Hochbeet (Perennial planting at the entrance, raised bed)",
            "m2",
            60,
            66.00,
            "550",
        ),
        (
            "18.05.0040",
            "Fertigstellungs- und Entwicklungspflege 2 Jahre (Completion and establishment maintenance, 2 years)",
            "lsum",
            1,
            17400.00,
            "550",
        ),
        (
            "18.03.0140",
            "Stundenlohnarbeiten und Kleinleistungen Belagsflaechen (Daywork and minor works, paved surfaces)",
            "lsum",
            1,
            449.00,
            "520",
        ),
    ],
    # LV 19 (KG 530 = 165,000.00).
    "VE-19": [
        (
            "19.01.0010",
            "Werbepylon h = 9,0 m, Stahlkonstruktion, beleuchtet, inkl. Fundament 14 m3 (Advertising pylon 9.0 m, steel, illuminated, incl. 14 m3 foundation)",
            "pcs",
            1,
            44500.00,
            "530",
        ),
        # qty: 4 cart shelters a 30 m2 with green roofs per the site plan
        (
            "19.01.0020",
            "Einkaufswagen-Ueberdachungen 30 m2 mit Gruendach (Cart shelters 30 m2 with green roofs)",
            "pcs",
            4,
            18200.00,
            "530",
        ),
        (
            "19.01.0030",
            "Fahrradueberdachung 28 Plaetze und 4 Lastenrad-Plaetze (Bike shelter 28 spaces plus 4 cargo-bike spaces)",
            "lsum",
            1,
            16400.00,
            "530",
        ),
        # qty: uncovered bike hoops
        (
            "19.01.0040",
            "Fahrradanlehnbuegel Edelstahl, nicht ueberdacht (Stainless bike hoops, uncovered)",
            "pcs",
            10,
            395.00,
            "530",
        ),
        (
            "19.01.0050",
            "Anfahrschutz Poller und Schutzbuegel: Ladesaeulen, Pylon, Gebaeudeecken (Impact protection bollards and hoops: chargers, pylon, building corners)",
            "pcs",
            30,
            480.00,
            "530",
        ),
        (
            "19.01.0060",
            "Fahnenmasten h = 8 m inkl. Huelsenfundament (Flag poles 8 m incl. sleeve foundations)",
            "pcs",
            4,
            1980.00,
            "530",
        ),
        (
            "19.01.0070",
            "Beleuchtung Pylon-Logoblende, Anschluss und IBN (Pylon sign lighting, connection and commissioning)",
            "lsum",
            1,
            3400.00,
            "530",
        ),
        (
            "19.01.0080",
            "Fundamente, Montage und Nebenleistungen Aussenbauwerke (Foundations, erection and ancillary works, external structures)",
            "lsum",
            1,
            1630.00,
            "530",
        ),
    ],
    # LV 20 (KG 610 = 700,000.00, owner direct award VP-10) - subsections:
    # 20.01 Regale und Kassenzone, 20.02 Drive-in-Backstation und Sondermoebel.
    "VE-20": [
        # qty: 10 aisles a 2 runs a 32 m = 640 lfm shelving in the 1,950 m2 sales hall
        (
            "20.01.0010",
            "Regalanlage Verkaufsraum 10 Gaenge, Grund- und Anbaufelder, H = 2,2 m (Sales-area shelving 10 aisles, starter and add-on bays, H = 2.2 m)",
            "m",
            640,
            500.00,
            "610",
        ),
        ("20.01.0020", "Bandkassen-Arbeitsplaetze (Belt checkout workstations)", "pcs", 3, 16800.00, "610"),
        (
            "20.01.0030",
            "Self-Checkout-Systeme inkl. Software-Inbetriebnahme (Self-checkout systems incl. software commissioning)",
            "pcs",
            6,
            19800.00,
            "610",
        ),
        (
            "20.01.0040",
            "Kassenzonen-Leitsystem, Warentrenner und Gondelkoepfe (Checkout guidance system, dividers and gondola ends)",
            "lsum",
            1,
            14400.00,
            "610",
        ),
        (
            "20.01.0050",
            "Warensicherung Antennen Ein- und Ausgang (Article surveillance antennas, entrance and exit)",
            "pcs",
            3,
            4950.00,
            "610",
        ),
        (
            "20.01.0060",
            "Einkaufswagen inkl. Pfandschloss (Shopping carts incl. deposit locks)",
            "pcs",
            300,
            128.00,
            "610",
        ),
        (
            "20.01.0070",
            "Pfandbon-Drucker, IT-Halterungen und Kleinmontagen Kasse (Deposit-receipt printers, IT mounts and minor checkout fitting)",
            "lsum",
            1,
            3400.00,
            "610",
        ),
        # qty: drive-in bake-off, 4 ovens a 18 kW per the space program
        (
            "20.02.0010",
            "Drive-in-Backstation 4 Oefen a 18 kW inkl. Beschickungs-, Abluft- und Ausgabetechnik (Drive-through bake-off, 4 ovens a 18 kW incl. loading, extract and handout equipment)",
            "pcs",
            4,
            16900.00,
            "610",
        ),
        (
            "20.02.0020",
            "Brotregale und Praesentationsmoebel Backstation (Bread racks and display furniture, bake-off)",
            "lsum",
            1,
            14600.00,
            "610",
        ),
        (
            "20.02.0030",
            "Obst- und Gemuese-Praesentation, Kistenregale (Fruit and vegetable displays, crate racks)",
            "m",
            30,
            700.00,
            "610",
        ),
        (
            "20.02.0040",
            "Aktionsmoebel Gondelkopf und mobile Verkostungstheke (Promotional gondola-end units and mobile tasting counter)",
            "pcs",
            8,
            1480.00,
            "610",
        ),
        # qty: ~26 staff per the operating concept
        (
            "20.02.0050",
            "Buero- und Sozialraummoebel, Spinde 26 Personal (Office and staff-room furniture, lockers for 26 staff)",
            "pcs",
            26,
            495.00,
            "610",
        ),
        (
            "20.02.0060",
            "Innenbeschilderung, Deckenhaenger und Regalstirn-Beschilderung (Interior signage, ceiling hangers and shelf-end signage)",
            "lsum",
            1,
            11400.00,
            "610",
        ),
        (
            "20.02.0070",
            "Montage, Ausrichtung, Erstbestueckungs-Logistik und Einweisung (Erection, alignment, initial-stocking logistics and instruction)",
            "lsum",
            1,
            440.00,
            "610",
        ),
    ],
    # LV 21 (KG 690 = 150,000.00).
    "VE-21": [
        # qty: 3 reverse-vending machines per the space program (larger Pfandraum)
        (
            "21.01.0010",
            "Leergut-Ruecknahmeautomaten Doppelgeraet mit Durchreiche (Reverse-vending machines, twin unit with pass-through)",
            "pcs",
            3,
            28500.00,
            "690",
        ),
        (
            "21.01.0020",
            "Leergut-Foerder- und Sortieranlage Pfandraum (Empties conveying and sorting system, deposit room)",
            "lsum",
            1,
            25800.00,
            "690",
        ),
        ("21.01.0030", "Ballenpresse Kartonage 50 kN (Cardboard baler 50 kN)", "pcs", 1, 13400.00, "690"),
        ("21.01.0040", "Scheuersaugmaschine Reinigung (Scrubber-dryer cleaning machine)", "pcs", 1, 9400.00, "690"),
        (
            "21.01.0050",
            "Behaeltersystem Wertstoffe und Muellpress-Stellplatz (Recyclables container system and waste-press bay)",
            "lsum",
            1,
            7400.00,
            "690",
        ),
        (
            "21.01.0060",
            "Kleinausstattung: Feuerloescher, Erste-Hilfe, Arbeitsschutz-Beschilderung (Minor equipment: extinguishers, first aid, safety signage)",
            "lsum",
            1,
            4800.00,
            "690",
        ),
        (
            "21.01.0070",
            "Ersatzteil- und Verschleisspaket RVM inkl. Personaleinweisung (Spare and wear-part package for the RVMs incl. staff instruction)",
            "lsum",
            1,
            3400.00,
            "690",
        ),
        (
            "21.01.0080",
            "Anlieferung, Montage, IBN und Einweisung Betriebstechnik (Delivery, assembly, commissioning and instruction, operational equipment)",
            "lsum",
            1,
            300.00,
            "690",
        ),
    ],
}


def _build_sections() -> list[SectionDef]:
    """Assemble the 16 LV sections, each summing exactly to its VE budget.

    The full LV closes by data: every section's positions must reproduce
    the procurement-unit budget to the cent, with the trailing balancing
    row carrying the remainder. All money arithmetic runs through Decimal
    so the emitted 2-decimal floats are exact and the LV grand total lands
    on 9,600,000.00 EUR. A nonzero remainder is a data error and raises
    immediately, so a careless edit can never silently drift a budget.
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
_LV_GRAND_TOTAL = 9_600_000.00
_PKG_SHARE = _LV_GRAND_TOTAL / 4  # = 2,400,000.00

TEMPLATE = DemoTemplate(
    demo_id="retail-market-karlsruhe",
    project_name="Lebensmittelmarkt Karlsruhe",
    project_description=(
        "Neubau eines eingeschossigen Lebensmittelmarktes mit grosser "
        "Stellplatzanlage im Gewerbegebiet Karlsruhe-Durlach (New-build "
        "food retail market with a large surface car park). Greenfield-"
        "Grossformat: Verkaufsflaeche 2.050 m2, BGF 3.310 m2 (EG 3.150 + "
        "Technik-Mezzanin 160), BRI 23.600 m3, Grundstueck 12.400 m2. "
        "Tragwerk: 39 Stahlbeton-Fertigteilstuetzen 40/40 cm auf "
        "Koecherfundamenten, 26 BSH-Binder GL24h (Spannweiten 25,0 m + "
        "17,0 m) auf 13 Achsen a 6,25 m, Bodenplatte d = 20 cm (630 m3 "
        "RC-Beton), Stahltrapezblech-Dach mit 10 RWA-Lichtkuppeln. "
        "Fassade: Sandwichpaneele 1.560 m2 mit Laerchen-Akzent, "
        "Pfosten-Riegel-Verglasung 130 m2. 100 % fossilfrei: "
        "transkritische CO2-Kaelteanlage (NK 120 kW / TK 34 kW) mit "
        "2-stufiger Waermerueckgewinnung und Fussbodenheizung, PV-Anlage "
        "380 kWp mit Batteriespeicher 240 kWh, 20 E-Ladepunkte. "
        "Drive-in-Backstation mit 4 Oefen und erweiterte Kassenzone. "
        "150 Pkw-Stellplaetze, 42 Fahrradplaetze, Rigole 260 m3 "
        "(DWA-A 138). KfW 299 (EG 40 + QNG-PLUS), DGNB Gold angestrebt. "
        "Genehmigtes Projektbudget 11,40 Mio EUR netto (KG 200-700 zzgl. "
        "Reserve)."
    ),
    region="DACH",
    classification_standard="din276",
    currency="EUR",
    locale="de",
    address={
        "street": "Pfinzstrasse 88",
        "city": "Karlsruhe",
        "postcode": "76227",
        "country": "Germany",
        "lat": 49.0008,
        "lng": 8.4737,
    },
    validation_rule_sets=["din276", "gaeb", "boq_quality"],
    boq_name="Kostenberechnung nach DIN 276",
    boq_description=(
        "Kostenberechnung gem. DIN 276:2018-12 auf Basis der "
        "Vergabeeinheiten: 16 bepreiste LV-Abschnitte im OZ-Schema "
        "VE.Abschnitt.Position, Summe exakt 9.600.000 EUR netto. "
        "Vollstaendiges LV; jeder Abschnitt schliesst centgenau auf sein "
        "VE-Budget (full bill of quantities, every section closing exactly "
        "on its procurement-unit budget)."
    ),
    boq_metadata={
        "standard": "DIN 276:2018-12",
        "phase": "LP 3 Kostenberechnung, fortgeschrieben mit Vergabestand",
        "base_date": "2026-Q2",
        "price_level": "Karlsruhe 2026",
        "oz_scheme": "VE.Abschnitt.Position",
        "project_code": "LM-KA-2026-01",
    },
    sections=_build_sections(),
    markups=[
        ("Baustellengemeinkosten (BGK / site overhead)", 9.0, "overhead", "direct_cost"),
        ("Mehrwertsteuer (MwSt. / VAT)", 19.0, "tax", "cumulative"),
    ],
    total_months=12,
    # Legacy single-package fields (required by DemoTemplate). They are
    # overridden by ``tender_packages`` below, but kept as the VP-07 award so
    # the descriptor still reads correctly if the multi-package path is ever
    # disabled.
    tender_name="VP-07 Kaeltetechnik CO2-Verbund und Kuehlmoebel (CO2 refrigeration, owner direct award)",
    tender_companies=[
        ("Badische Kaeltetechnik GmbH", "vergabe@badische-kaeltetechnik.de", 958_400 / _LV_GRAND_TOTAL),
        ("PfinzKlima Kaelte- und Klimatechnik GmbH", "angebote@pfinzklima-kaelte.de", 1_012_600 / _LV_GRAND_TOTAL),
        ("Kuehlanlagenbau Rheintal GmbH", "ausschreibung@kaeltebau-rheintal.de", 1_058_900 / _LV_GRAND_TOTAL),
    ],
    # Four procurement packages (VP-07/09/10/11 of the design dossier), each
    # mapping to a procurement unit budget. Status reflects the week-21
    # snapshot: VP-07 awarded, VP-09 out for submission, VP-10 in
    # evaluation, VP-11 in evaluation pending the grid feed-in approval.
    # The bid factor is ``net_bid / _PKG_SHARE`` so install_demo_project
    # (which prices each package off an equal grand_total / 4 share) lands
    # every bid on its exact net figure.
    tender_packages=[
        (
            "VP-07 Kaeltetechnik CO2-Verbund und Kuehlmoebel (CO2 refrigeration and cabinets, KG 470)",
            "Bauherren-Direktvergabe, vergeben am 2026-05-12 an Badische Kaeltetechnik GmbH; 3 Angebote, Spread 10,5 %. Budget 980.000 EUR netto (VE-15).",
            "awarded",
            [
                # bids 958,400 / 1,012,600 / 1,058,900 EUR, spread 10.5 %
                ("Badische Kaeltetechnik GmbH", "vergabe@badische-kaeltetechnik.de", 958_400 / _PKG_SHARE),
                ("PfinzKlima Kaelte- und Klimatechnik GmbH", "angebote@pfinzklima-kaelte.de", 1_012_600 / _PKG_SHARE),
                ("Kuehlanlagenbau Rheintal GmbH", "ausschreibung@kaeltebau-rheintal.de", 1_058_900 / _PKG_SHARE),
            ],
        ),
        (
            "VP-09 Aussenanlagen, Stellplaetze, Entwaesserung (External works, parking, drainage, KG 510+520+540+550)",
            "Ausgeschrieben, Submission 2026-07-16; 3 indikative Angebote, Spread 13,2 %. Budget 1.250.000 EUR netto (VE-18).",
            "collecting",
            [
                # indicative bids 1,205,000 / 1,278,400 / 1,364,200 EUR, spread 13.2 %
                ("Galabau Hardtwald GmbH", "angebot@galabau-hardtwald.de", 1_205_000 / _PKG_SHARE),
                ("Tiefbau Albtal GmbH", "vergabe@tiefbau-albtal.de", 1_278_400 / _PKG_SHARE),
                ("Gruenbau Kraichgau GmbH", "ausschreibung@gruenbau-kraichgau.de", 1_364_200 / _PKG_SHARE),
            ],
        ),
        (
            "VP-10 Ladeneinrichtung, Regaltechnik, Kassenzone, Drive-in-Backstation (Store fit-out, KG 610)",
            "Bauherren-Direktvergabe, in Verhandlung, Zuschlag geplant 2026-07-31; 2 Angebote, Spread 5,4 %. Budget 700.000 EUR netto (VE-20).",
            "evaluating",
            [
                # bids 671,200 / 707,400 EUR, spread 5.4 %
                ("Ladenbau Goldmann GmbH", "f.goldmann@ladenbau-goldmann.de", 671_200 / _PKG_SHARE),
                ("Objekteinrichtung Brettinger & Co. KG", "vergabe@brettinger-objekt.de", 707_400 / _PKG_SHARE),
            ],
        ),
        (
            "VP-11 PV 380 kWp, Batteriespeicher 240 kWh, Ladeinfrastruktur (PV, battery, EV charging, KG 440)",
            "Bauherren-Direktvergabe, in Wertung, Zuschlag nach Einspeisezusage (Risiko R06); 3 Angebote, Spread 12,4 %. Budget 660.000 EUR netto (VE-17).",
            "evaluating",
            [
                # bids 631,800 / 678,400 / 710,200 EUR, spread 12.4 %
                ("Sonnkraft Solartechnik GmbH", "angebot@sonnkraft-solar.de", 631_800 / _PKG_SHARE),
                ("EnergieWerk Oberrhein GmbH", "vergabe@energiewerk-oberrhein.de", 678_400 / _PKG_SHARE),
                ("Elektro Wuermtal GmbH", "k.wuermtal@elektro-wuermtal.de", 710_200 / _PKG_SHARE),
            ],
        ),
    ],
    # 35 schedule activities (T01..T35 of the design dossier), anchored on the
    # real calendar so the project reads mid-construction at week 21 of 48
    # (Mon 2026-02-09 start, opening Thu 2027-01-14). install_demo_project
    # derives a progress ramp from the activity order; the SPI/CPI overrides
    # carry the "slightly behind on roof/facade, under cost" story.
    schedule_activities=[
        ("T01 Werk- und Montageplanung Fertigteile (precast shop and erection drawings)", "2026-02-09", "2026-03-13"),
        (
            "T02 Baustelleneinrichtung inkl. Baustrom und Bauwasser (site setup incl. power and water)",
            "2026-02-09",
            "2026-02-20",
        ),
        (
            "T03 Erschliessung Kanal, Wasser, Strom bis Grundstuecksgrenze (utility connections to plot)",
            "2026-02-23",
            "2026-03-13",
        ),
        ("T04 Baufeldfreimachung und Oberbodenabtrag (site clearance and topsoil strip)", "2026-02-23", "2026-02-27"),
        ("T05 Erdaushub und Bodenaustausch (excavation and soil replacement)", "2026-03-02", "2026-03-20"),
        (
            "T06 Planumserstellung und Verdichtungsnachweis (subgrade formation and compaction)",
            "2026-03-23",
            "2026-03-27",
        ),
        ("T07 Koecher- und Streifenfundamente (pocket and strip foundations)", "2026-03-30", "2026-04-10"),
        ("T08 Grundleitungen unter Bodenplatte (below-slab drainage)", "2026-04-06", "2026-04-17"),
        (
            "T09 Bodenplatte: Daemmung, Bewehrung, Betonage (ground slab: insulation, rebar, pour)",
            "2026-04-13",
            "2026-05-01",
        ),
        ("T10 Fertigteilproduktion im Werk (precast production at plant)", "2026-03-16", "2026-05-01"),
        ("T11 Montage Stuetzen und BSH-Binder (erection of columns and glulam beams)", "2026-05-04", "2026-05-15"),
        ("T12 Montage Wand- und Sandwichelemente (erection of wall and sandwich panels)", "2026-05-11", "2026-05-22"),
        ("T13 Dachtragschale Trapezblech (roof deck trapezoidal sheeting)", "2026-05-18", "2026-05-29"),
        (
            "T14 Dachabdichtung, Daemmung, RWA und Lichtkuppeln (roof waterproofing, smoke vents, rooflights)",
            "2026-06-01",
            "2026-06-26",
        ),
        ("T15 Fassadenarbeiten: Sandwichpaneele, Laerchen-Lattung, Sockel (facade works)", "2026-06-01", "2026-07-03"),
        (
            "T16 Fenster, Pfosten-Riegel-Glasfront, Tueren, Sektionaltore (windows, curtain wall, doors, gates)",
            "2026-06-22",
            "2026-07-10",
        ),
        ("T17 Heizung/Sanitaer Rohinstallation (heating/plumbing rough-in)", "2026-06-08", "2026-07-17"),
        ("T18 Lueftungskanaele Montage (ventilation ductwork installation)", "2026-06-15", "2026-07-17"),
        (
            "T19 Elektro-Rohinstallation und Kabeltrassen (electrical rough-in and cable trays)",
            "2026-06-08",
            "2026-07-24",
        ),
        ("T20 CO2-Kaelteleitungen Rohmontage (CO2 refrigerant piping rough-in)", "2026-07-06", "2026-07-31"),
        (
            "T21 Netzanschluss, Trafostation, NSHV (grid connection, transformer, main LV board)",
            "2026-06-22",
            "2026-07-31",
        ),
        ("T22 Trockenbau Sozial- und Nebenraeume (drywall for staff and ancillary rooms)", "2026-07-13", "2026-08-14"),
        ("T23 Industrieboden Verkaufsraum (industrial flooring sales area)", "2026-07-20", "2026-07-31"),
        ("T24 Fliesen, Maler, Innentueren (tiling, painting, internal doors)", "2026-08-10", "2026-09-04"),
        ("T25 Akustikdecken und Beleuchtungsmontage (acoustic ceilings and lighting)", "2026-08-17", "2026-09-04"),
        (
            "T26 TGA-Endmontage: Waermepumpe, RLT, Verteilungen, GLT (MEP completion incl. BMS)",
            "2026-08-17",
            "2026-09-18",
        ),
        (
            "T27 Aussenanlagen: Unterbau, Entwaesserung, Belaege, Pylon, Begruenung (external works)",
            "2026-08-17",
            "2026-10-23",
        ),
        (
            "T28 PV-Anlage, Batteriespeicher und Ladeinfrastruktur (PV, battery and EV charging)",
            "2026-08-31",
            "2026-09-25",
        ),
        ("T29 Kuehlmoebel stellen und anbinden (set and connect refrigerated cabinets)", "2026-09-07", "2026-09-25"),
        (
            "T30 Kaelteanlage: Druckprobe, Inbetriebnahme, Kuehlstellen kalt (refrigeration commissioning)",
            "2026-09-28",
            "2026-10-09",
        ),
        (
            "T31 Ladeneinrichtung: Regale, Kassenzone, Drive-in-Backstation, Pfandraum (store fit-out)",
            "2026-10-05",
            "2026-10-30",
        ),
        (
            "T32 Sachverstaendigen- und behoerdliche Abnahmen (expert and authority acceptance tests)",
            "2026-11-02",
            "2026-11-13",
        ),
        (
            "T33 VOB-Abnahme GU und Maengelbeseitigung (VOB acceptance of GC works and snagging)",
            "2026-11-16",
            "2026-11-27",
        ),
        (
            "T34 Revisionsunterlagen, Einweisungen, Wartungsvertraege (as-builts, briefings, maintenance)",
            "2026-11-16",
            "2026-12-04",
        ),
        (
            "T35 Warenerstbestueckung, Personaleinarbeitung, Pre-Opening (initial stocking, training)",
            "2026-12-07",
            "2027-01-14",
        ),
    ],
    project_metadata={
        "name_en": "Retail Market Karlsruhe",
        "long_name_de": "Neubau Lebensmittelmarkt mit Stellplatzanlage, Karlsruhe-Durlach",
        "long_name_en": "New-build food retail market with parking facilities, Karlsruhe-Durlach",
        "address": "Pfinzstrasse 88, 76227 Karlsruhe",
        "client": "Oberrhein Handelsimmobilien GmbH",
        "operator": "Oberrhein Lebensmittelmaerkte GmbH",
        "architect": "Architekturbuero Fechtig + Partner Architekten PartG mbB",
        "structural_engineer": "Wehrle Ingenieure Tragwerksplanung GmbH",
        "mep_engineer": "Brenner & Partner TGA-Planung GmbH",
        "main_contractor": "Hardtwald Bau GmbH & Co. KG",
        "gfa_m2": 3310,
        "bri_m3": 23600,
        "plot_m2": 12400,
        "footprint_m2": 3150,
        "sales_area_m2": 2050,
        "parking_stalls": 150,
        "bike_stalls": 42,
        "ev_charge_points": 20,
        "pv_kwp": 380,
        "battery_kwh": 240,
        "structure_system": "Precast RC columns 40/40 on pocket foundations, glulam binders GL24h, steel roof deck",
        "facade_system": "Sandwich panels MW 200 mm, larch batten accent, aluminium curtain wall entrance",
        "grid_m": "13 axes a 6.25, spans 25.0 + 17.0",
        "refrigeration": "Transcritical CO2 (R744) booster rack, MT 120 kW / LT 34 kW, 2-stage heat recovery",
        "energy_standard": "GEG 2024 / KfW 299 (EG 40 + QNG-PLUS)",
        "sustainability_target": "DGNB Gold (Neubau 2023)",
        "zoning": "Vorhabenbezogener B-Plan 76/14 Durlach-Ost - Nahversorgung (SO Nahversorgung)",
        "permit_authority": "Stadt Karlsruhe, Bauordnungsamt (LBO BW, Sonderbau Verkaufsstaette)",
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
        "cost_basis": "Net, price level Karlsruhe 2026, reconciled DIN 276 cost frame",
        "budget": "11.40M EUR",
    },
    project_code="LM-KA-2026-01",
    # 5D tuning - matches the week-21-of-48 finance story: ~32 % billed,
    # slightly behind on roof/facade (SPI 0.98), under cost (CPI 1.02).
    planned_budget=11_400_000.0,
    actual_spend_ratio=0.32,
    spi_override=0.98,
    cpi_override=1.02,
)
