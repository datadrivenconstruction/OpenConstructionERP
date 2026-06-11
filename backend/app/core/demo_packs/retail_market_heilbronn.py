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
  map 1:1 to LV sections (OZ scheme ``VE.section.position``). Budgets come
  from the reconciled DIN 276 cost plan; their sum is exactly 7,905,000 EUR
  net (KG 200-600 minus the 185,000 EUR KG 220 connection fees, which are
  not tendered works).
* ``_SAMPLE_POSITIONS`` - detailed positions for the six largest procurement
  units. Swap or extend this dict to densify the LV; ``_build_sections``
  recomputes the per-section remainder rows so every section keeps summing
  exactly to its procurement-unit budget.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.demo_projects import DemoTemplate, SectionDef

# (oz, description, unit, quantity, unit_rate_eur, din276_code)
_PositionRow = tuple[str, str, str, float, float, str]

# (section_ordinal, ve_id, section_title, primary_din276_kg, ve_budget_eur,
#  lump_row_description) - the lump row closes the gap between the detailed
# sample positions and the procurement-unit budget (or carries the whole
# budget for not-yet-detailed units).
_VeSection = tuple[str, str, str, str, float, str]

_VE_SECTIONS: list[_VeSection] = [
    (
        "01",
        "VE-01",
        "LV 01 - Baustelleneinrichtung und Gemeinkosten (Site establishment and general items)",
        "390",
        150_000.00,
        "Baustelleneinrichtung, Vorhaltung, Baustrom/-wasser, Reinigung, komplett gem. Kostenberechnung (Site setup, provision and utilities, complete per cost plan)",
    ),
    (
        "02",
        "VE-02",
        "LV 02 - Erdbau und Erschliessung (Earthworks and site servicing)",
        "210",
        365_000.00,
        "Erdbau, Baufeldfreimachung und Erschliessung, komplett gem. Kostenberechnung (Earthworks, site clearance and servicing, complete per cost plan)",
    ),
    (
        "04",
        "VE-04",
        "LV 04 - Rohbau: Gruendung, Bodenplatte, Industrieboden, Massivbau (Shell works)",
        "320",
        820_000.00,
        "Restleistungen Rohbau gem. Kostenberechnung, Detaillierung folgt (Remaining shell works to procurement-unit budget, to be detailed)",
    ),
    (
        "05",
        "VE-05",
        "LV 05 - Dach: Trapezblech, Daemmung, Abdichtung, RWA (Roof works incl. smoke vents)",
        "360",
        580_000.00,
        "Restleistungen Dach gem. Kostenberechnung, Detaillierung folgt (Remaining roof works to procurement-unit budget, to be detailed)",
    ),
    (
        "06",
        "VE-06",
        "LV 06 - Stahlbeton-Fertigteile und BSH-Binder (Precast RC frame and glulam binders)",
        "330",
        540_000.00,
        "36 FT-Stuetzen 40/40, 24 BSH-Binder GL24h, 22 Randtraeger, Montage, komplett gem. Kostenberechnung (36 precast columns, 24 glulam binders, 22 edge beams, erection, complete per cost plan)",
    ),
    (
        "07",
        "VE-07",
        "LV 07 - Fassade: Sandwichpaneele, Laerchen-Lattung, Sockel (Facade works)",
        "330",
        410_000.00,
        "Sandwichpaneele MW 200 mm 1.292 m2, Laerchen-Akzent 180 m2, Sockel, komplett gem. Kostenberechnung (Sandwich panels 1,292 m2, larch accent 180 m2, plinth, complete per cost plan)",
    ),
    (
        "08",
        "VE-08",
        "LV 08 - Fenster, Tueren, Tore, Pfosten-Riegel-Fassade (Windows, doors, gates, curtain wall)",
        "330",
        250_000.00,
        "PR-Fassade 120 m2, Fensterband 42 m2, 2 Tore, 6 Stahltueren T30/RC2, komplett gem. Kostenberechnung (Curtain wall 120 m2, window band 42 m2, 2 gates, 6 steel doors, complete per cost plan)",
    ),
    (
        "09",
        "VE-09",
        "LV 09 - Innenausbau: Trockenbau, Fliesen, Maler, Innentueren, Decken (Interior fit-out)",
        "340",
        280_000.00,
        "Innenausbau Sozialtrakt und Nebenraeume, komplett gem. Kostenberechnung (Interior fit-out staff wing and ancillary rooms, complete per cost plan)",
    ),
    (
        "14",
        "VE-14",
        "LV 14 - HLS: Sanitaer, Waermepumpe, Fussbodenheizung, RLT (Mechanical services)",
        "410",
        630_000.00,
        "Restleistungen HLS gem. Kostenberechnung, Detaillierung folgt (Remaining mechanical works to procurement-unit budget, to be detailed)",
    ),
    (
        "15",
        "VE-15",
        "LV 15 - Kaeltetechnik CO2-Verbund und Kuehlmoebel (CO2 refrigeration rack and refrigerated cabinets)",
        "470",
        830_000.00,
        "Verbund-Kuehlmoebel: 48 lfm NK-Glastuerregale, 22 lfm TK, 6 lfm Bedientheke, gem. Kostenberechnung (Remote cabinets: 48 lm chilled, 22 lm frozen, 6 lm serve-over, per cost plan)",
    ),
    (
        "16",
        "VE-16",
        "LV 16 - Elektrotechnik inkl. BMA und GLT (Electrical incl. fire alarm and building automation)",
        "440",
        680_000.00,
        "Restleistungen Elektrotechnik gem. Kostenberechnung, Detaillierung folgt (Remaining electrical works to procurement-unit budget, to be detailed)",
    ),
    (
        "17",
        "VE-17",
        "LV 17 - PV 290 kWp, Batteriespeicher 135 kWh, Ladeinfrastruktur (PV, battery, EV charging)",
        "440",
        520_000.00,
        "PV Ost-West 660 Module a 440 Wp, Speicher 135 kWh, 12 Ladepunkte, 38 Stellplaetze GEIG-vorgeruestet, komplett gem. Kostenberechnung (PV east-west 660 modules, 135 kWh battery, 12 charge points, 38 GEIG-prepared stalls, complete per cost plan)",
    ),
    (
        "18",
        "VE-18",
        "LV 18 - Aussenanlagen, Stellplaetze, Entwaesserung (External works, parking, drainage)",
        "510",
        1_020_000.00,
        "Restleistungen Aussenanlagen gem. Kostenberechnung, Detaillierung folgt (Remaining external works to procurement-unit budget, to be detailed)",
    ),
    (
        "19",
        "VE-19",
        "LV 19 - Werbepylon, Einkaufswagen-Boxen, Anfahrschutz (Pylon, cart shelters, impact protection)",
        "530",
        130_000.00,
        "Pylon h = 8,0 m inkl. Fundament 12 m3, 3 Einkaufswagen-Boxen a 27 m2 begruent, Anfahrschutz, komplett gem. Kostenberechnung (Pylon 8.0 m incl. foundation, 3 green-roofed cart shelters, impact protection, complete per cost plan)",
    ),
    (
        "20",
        "VE-20",
        "LV 20 - Ladeneinrichtung, Kassenzone, Backstation (Store fit-out, checkout zone, bake-off station)",
        "610",
        560_000.00,
        "Regaltechnik 8 Gaenge, 6 Kassen (2 Band + 4 SCO), Backstation 3 Oefen a 18 kW, komplett gem. Kostenberechnung (Shelving 8 aisles, 6 checkouts, bake-off 3 ovens, complete per cost plan)",
    ),
    (
        "21",
        "VE-21",
        "LV 21 - Pfandraumtechnik und sonstige Ausstattung (Reverse-vending room and other equipment)",
        "690",
        140_000.00,
        "2 Leergut-Ruecknahmeautomaten, Pfandraum-Foerdertechnik, Ballenpresse, komplett gem. Kostenberechnung (2 reverse-vending machines, conveyors, baler, complete per cost plan)",
    ),
]

# Detailed sample positions for the six largest procurement units (65 rows,
# 2,526,200.00 EUR = 55.4 % of their combined 4,560,000 EUR budgets). Net
# unit rates, price level Heilbronn 2026. Quantities derive from the
# canonical building geometry (work area 2,774 m2, 36 pocket foundations,
# perimeter 216 m, slab 544 m3, ...), so the future procedural 3D model and
# the BOQ stay quantity-consistent.
_SAMPLE_POSITIONS: dict[str, list[_PositionRow]] = {
    "VE-04": [
        ("04.01.0010", "Aushub Baugrube und Fundamente, Boden Kl. 3-5, seitlich lagern (Excavation pits and foundations, on-site storage)", "m3", 3400, 12.80, "310"),
        ("04.01.0020", "Bodenaustausch / Tragschicht 0/45 unter Bodenplatte, d = 40 cm, verdichtet (Soil replacement / sub-base 0/45 under slab, 40 cm)", "m2", 2774, 14.20, "320"),
        ("04.01.0030", "Sauberkeitsschicht C12/15, d = 5 cm (Blinding layer C12/15, 5 cm)", "m2", 2774, 9.40, "320"),
        ("04.01.0040", "Koecherfundamente 1,80 x 1,80 x 1,00 m, C25/30, inkl. Schalung und Aussparung (Pocket foundations 1.8 x 1.8 x 1.0 m C25/30)", "pcs", 36, 1480.00, "320"),
        ("04.01.0050", "Frostschuerze umlaufend, h = 80 cm, C25/30 (Perimeter frost skirt 80 cm C25/30)", "m", 216, 96.00, "320"),
        ("04.01.0060", "Betonstahl B500B Fundamente und Frostschuerze, liefern und verlegen (Rebar B500B foundations and skirt)", "t", 38, 1380.00, "320"),
        ("04.01.0070", "PE-Folie Trennlage 2-lagig unter Bodenplatte (PE separation layer, 2-ply)", "m2", 2774, 2.10, "320"),
        ("04.01.0080", "XPS-Daemmung 120 mm unter Bodenplatte, Heizzone, druckfest (XPS insulation 120 mm under slab, heated zone)", "m2", 1750, 28.50, "320"),
        ("04.01.0090", "Bodenplatte C25/30 (RC-Beton), d = 20 cm, inkl. Einbau und Abziehen (Ground slab C25/30 recycled aggregate, 20 cm)", "m3", 544, 178.00, "320"),
        ("04.01.0100", "Betonstahl B500B Bodenplatte inkl. Randzonenbewehrung (Rebar B500B ground slab incl. edge zones)", "t", 49, 1350.00, "320"),
        ("04.01.0110", "Industrieboden: Hartstoffeinstreuung, monolithisch geglaettet, Fugenschnitt und Verguss (Industrial floor: dry-shake topping, power-floated, joints)", "m2", 2400, 24.50, "320"),
        ("04.01.0120", "Grundleitungen DN 100 - DN 150 unter Bodenplatte inkl. Dichtheitspruefung DIN EN 1610 (Below-slab drainage DN100-150 incl. tightness test)", "m", 380, 88.00, "320"),
        ("04.01.0130", "Bodeneinlaeufe, Pumpensumpf, Revisionsschaechte komplett (Floor drains, sump, inspection chambers)", "lsum", 1, 18600.00, "320"),
        ("04.01.0140", "Stahlbeton-Wandscheiben Aussteifung, C30/37, inkl. Schalung (RC shear walls C30/37 incl. formwork)", "m3", 36, 580.00, "330"),
        ("04.01.0150", "Massivbau Sozialtrakt und Technikraeume inkl. Mezzanindecke 120 m2, komplett (Masonry/RC staff and plant rooms incl. mezzanine slab 120 m2)", "lsum", 1, 76900.20, "340"),
    ],
    "VE-05": [
        ("05.01.0010", "Stahltrapezprofil 160/250, t = 1,0 mm, als Dachtragschale inkl. Befestigung (Trapezoidal steel deck 160/250, 1.0 mm)", "m2", 2774, 31.50, "360"),
        ("05.01.0020", "Dampfsperre bituminoes, vollflaechig (Bituminous vapour barrier)", "m2", 2774, 6.80, "360"),
        ("05.01.0030", "PIR-Gefaelledaemmung 200-260 mm, WLG 023 (PIR tapered insulation 200-260 mm)", "m2", 2774, 52.00, "360"),
        ("05.01.0040", "FPO-Dachbahn, mechanisch befestigt, inkl. An- und Abschluesse (FPO membrane, mechanically fixed)", "m2", 2774, 28.40, "360"),
        ("05.01.0050", "Attika-Abdeckung Aluminium inkl. Unterkonstruktion (Aluminium parapet capping)", "m", 216, 68.00, "360"),
        ("05.01.0060", "Lichtkuppeln 1,5 x 1,5 m als NRWG nach DIN 18232, elektrisch 24 V, inkl. Aufsetzkranz (Rooflights 1.5 x 1.5 m as smoke vents per DIN 18232)", "pcs", 8, 4950.00, "360"),
        ("05.01.0070", "Dachgullys DN 100 beheizt und Notueberlaeufe (Heated roof drains DN100 and emergency overflows)", "pcs", 22, 740.00, "360"),
        ("05.01.0080", "Durchdringungen und Einfassungen fuer RLT, Kaelte, PV (Penetrations and flashings for HVAC, refrigeration, PV)", "lsum", 1, 12400.00, "360"),
        ("05.01.0090", "Absturzsicherung Sekuranten umlaufend (Fall-arrest anchors along perimeter)", "pcs", 28, 290.00, "360"),
        ("05.01.0100", "Blitzschutzanlage komplett inkl. Erdungsanlage und Potentialausgleich (Lightning protection complete incl. earthing)", "lsum", 1, 36028.20, "360"),
    ],
    "VE-14": [
        ("14.01.0010", "Luft/Wasser-Waermepumpe R290, 60 kW heizen / 75 kW kuehlen, inkl. hydraulischer Einbindung (Air/water heat pump R290 60/75 kW incl. hydraulics)", "pcs", 1, 58500.00, "420"),
        ("14.01.0020", "Fussbodenheizung Vorlauf 35/28 Grad C inkl. Verteiler, gespeist aus Kaelte-Abwaerme (Underfloor heating 35/28 C incl. manifolds)", "m2", 1650, 31.00, "420"),
        ("14.01.0030", "RLT-Geraet 11.500 m3/h, Rotations-WRG eta = 78 %, adiabate Kuehlung, auf Technik-Mezzanin (AHU 11,500 m3/h rotary heat recovery, adiabatic cooling)", "pcs", 1, 64800.00, "430"),
        ("14.01.0040", "Lueftungskanaele verzinkt inkl. Daemmung und Brandschotts (Galvanised ductwork incl. insulation and firestopping)", "m2", 980, 38.50, "430"),
        ("14.01.0050", "Tuerluftschleier Eingang 9 kW, WRG-gespeist (Entrance air curtain 9 kW, heat-recovery fed)", "pcs", 1, 6900.00, "430"),
        ("14.01.0060", "Sanitaerinstallation komplett: WC-Anlagen, Sozialraeume, TWW-Speicher 300 l (Plumbing complete: WCs, staff rooms, 300 l DHW tank)", "lsum", 1, 48200.00, "410"),
        ("14.01.0070", "Regelung und GLT-Schnittstellen HLS, Einregulierung, Abnahme (Controls and BMS interfaces HVAC, balancing, acceptance)", "lsum", 1, 22820.00, "480"),
    ],
    "VE-15": [
        ("15.01.0010", "Transkritische CO2-Booster-Verbundanlage mit Parallelverdichtung, NK 95 kW / TK 26 kW (Transcritical CO2 booster rack with parallel compression, MT 95 / LT 26 kW)", "lsum", 1, 148000.00, "470"),
        ("15.01.0020", "Gaskuehler Dachaufstellung inkl. Stahlrahmen und Schwingungsdaempfung (Gas cooler roof-mounted incl. steel frame)", "pcs", 1, 18400.00, "470"),
        ("15.01.0030", "Waermerueckgewinnung 2-stufig (Enthitzer + Kondensator) bis 120 kW thermisch (Two-stage heat recovery, desuperheater plus condenser, up to 120 kW)", "lsum", 1, 26500.00, "470"),
        ("15.01.0040", "CO2-Rohrleitungsnetz K65/Edelstahl inkl. Daemmung und Halterung (CO2 piping network K65/stainless incl. insulation)", "m", 420, 96.00, "470"),
        ("15.01.0050", "NK-Kuehlzelle +2 Grad C, ca. 45 m2, PU 100 mm, inkl. Tuer (Chiller cell +2 C, ~45 m2, PU 100 mm incl. door)", "pcs", 1, 12940.00, "470"),
        ("15.01.0060", "Obst/Gemuese-Kuehlraum +8 Grad C, ca. 25 m2, PU 80 mm (Produce cool room +8 C, ~25 m2, PU 80 mm)", "pcs", 1, 7900.00, "470"),
        ("15.01.0070", "TK-Zelle -22 Grad C, ca. 30 m2, PU 150 mm, inkl. Boden (Freezer room ~30 m2, PU 150 mm incl. floor)", "pcs", 1, 24500.00, "470"),
        ("15.01.0080", "Luftkuehler/Verdampfer CO2-geeignet, Zellen (CO2 unit coolers for cold rooms)", "pcs", 5, 2950.00, "470"),
        ("15.01.0090", "Anbindung Verbund-Kuehlmoebel (bauseits gestellt), Verrohrung und IBN (Connection of operator-supplied remote cabinets)", "pcs", 14, 1150.00, "470"),
        ("15.01.0100", "CO2-Gaswarnanlage Maschinenraum/Verkaufsraum (CO2 gas detection system)", "lsum", 1, 7400.00, "470"),
        ("15.01.0110", "MSR/Anlagenregelung Kaelte, inkl. Fernueberwachung (Refrigeration controls incl. remote monitoring)", "lsum", 1, 13800.00, "480"),
        ("15.01.0120", "Dichtheitspruefung, Inbetriebnahme, Abnahme EN 378, Einweisung (Pressure test, commissioning, EN 378 acceptance)", "lsum", 1, 8900.00, "470"),
    ],
    "VE-16": [
        ("16.01.0010", "NSHV 1.250 A inkl. Messung und Zaehlerplatz (Main LV board 1,250 A incl. metering)", "pcs", 1, 38400.00, "440"),
        ("16.01.0020", "Kabeltrassen und Leitungsnetz komplett (Cable trays and wiring complete)", "m", 1850, 24.50, "440"),
        ("16.01.0030", "LED-Lichtbandsystem Verkaufsraum 800 lx, DALI mit Tageslicht-/Praesenzregelung (LED light-band system sales area 800 lx, DALI daylight/presence control)", "m", 539, 142.00, "440"),
        ("16.01.0040", "Beleuchtung Lager/Nebenraeume 300 lx und Sicherheitsbeleuchtung (Warehouse/ancillary lighting 300 lx and emergency lighting)", "lsum", 1, 28900.00, "440"),
        ("16.01.0050", "Elektroinstallation Sozialtrakt, Unterverteilungen, Endgeraete (Electrical installation staff wing, sub-distribution boards)", "lsum", 1, 26040.00, "440"),
        ("16.01.0060", "Brandmeldeanlage Kat. 2 mit Aufschaltung (Fire alarm system cat. 2 with monitoring link)", "lsum", 1, 24600.00, "450"),
        ("16.01.0070", "Datennetz Cat 6A inkl. IT-Schrank und Patchfeld (Data network Cat 6A incl. IT cabinet)", "lsum", 1, 14800.00, "450"),
        ("16.01.0080", "GLT/Gebaeudeautomation: Feldgeraete, Aufschaltung, Energiemonitoring ISO 50001-faehig (BMS field devices, integration, ISO 50001-ready energy monitoring)", "lsum", 1, 19322.00, "480"),
    ],
    "VE-18": [
        ("18.01.0010", "Oberbodenabtrag und Erdarbeiten Aussenanlagen (Topsoil strip and earthworks external areas)", "m3", 2028, 9.80, "510"),
        ("18.01.0020", "Frostschutzschicht 0/45, d = 40 cm, fuer befestigte Flaechen (Frost protection layer 0/45, 40 cm)", "m2", 4590, 13.60, "520"),
        ("18.01.0030", "Asphalttrag- und Deckschicht Fahrgassen und Anlieferhof (Asphalt base and wearing course, lanes and delivery yard)", "m2", 3140, 42.50, "520"),
        ("18.01.0040", "Draen-Betonpflaster Stellplaetze, d = 10 cm, sickerfaehig (Permeable concrete pavers parking stalls, 10 cm)", "m2", 1450, 48.00, "520"),
        ("18.01.0050", "Bordsteine und Einfassungen (Kerbs and edgings)", "m", 920, 28.50, "520"),
        ("18.01.0060", "Entwaesserungsrinnen und Hofablaeufe inkl. Anschluss (Drainage channels and yard gullies incl. connection)", "lsum", 1, 24800.00, "540"),
        ("18.01.0070", "Rigole 190 m3 und Versickerungsmulden 350 m2 inkl. Drosselschacht 12 l/s (DWA-A 138) (Retention trench 190 m3 and infiltration swales 350 m2 incl. 12 l/s throttle)", "lsum", 1, 68500.00, "540"),
        ("18.01.0080", "Zisterne 10 m3 inkl. Pumpentechnik fuer Bewaesserung (Cistern 10 m3 incl. pump for irrigation)", "pcs", 1, 9400.00, "540"),
        ("18.01.0090", "Fahrbahn- und Stellplatzmarkierung inkl. Sonderflaechen (Lane and stall marking incl. special stalls)", "m", 952, 4.20, "520"),
        ("18.01.0100", "Aussenbeleuchtung 14 LED-Mastleuchten h = 6 m, 3000 K insektenfreundlich, inkl. Kabel und Fundamente (External lighting 14 LED masts 6 m incl. cabling and foundations)", "pcs", 14, 2350.00, "540"),
        ("18.01.0110", "Hochstamm-Baeume pflanzen inkl. Substrat und Verankerung (Standard trees incl. substrate and anchoring)", "pcs", 19, 980.00, "550"),
        ("18.01.0120", "Strauch-/Rasenflaechen und Fassadenbegruenung (Shrub/lawn areas and green facade)", "m2", 1720, 12.50, "550"),
        ("18.01.0130", "Fahrradueberdachung 20 Plaetze und 2 Lastenrad-Plaetze (Bike shelter 20 spaces plus 2 cargo-bike spaces)", "lsum", 1, 12243.20, "530"),
    ],
}


def _build_sections() -> list[SectionDef]:
    """Assemble the 16 LV sections, each summing exactly to its VE budget.

    Detailed sample rows are taken as-is; the per-section gap to the
    procurement-unit budget is closed with one lump-sum row (``<nn>.02.0010``
    after samples, ``<nn>.01.0010`` for not-yet-detailed units). All money
    arithmetic runs through Decimal so the emitted 2-decimal floats are
    exact and the LV grand total lands on 7,905,000.00 EUR to the cent.
    """
    sections: list[SectionDef] = []
    for ordinal, ve_id, title, kg, budget, lump_text in _VE_SECTIONS:
        rows = _SAMPLE_POSITIONS.get(ve_id, [])
        items: list[tuple[str, str, str, float, float, dict]] = [
            (oz, desc, unit, qty, rate, {"din276": code}) for oz, desc, unit, qty, rate, code in rows
        ]
        sampled = sum(
            (Decimal(str(qty)) * Decimal(str(rate)) for _, _, _, qty, rate, _ in rows),
            Decimal("0"),
        )
        remainder = Decimal(str(budget)) - sampled
        if remainder < 0:
            msg = f"{ve_id}: sample positions ({sampled}) exceed the VE budget ({budget})"
            raise ValueError(msg)
        if remainder > 0:
            lump_oz = f"{ordinal}.02.0010" if rows else f"{ordinal}.01.0010"
            items.append((lump_oz, lump_text, "lsum", 1.0, float(remainder), {"din276": kg}))
        sections.append((ordinal, title, {"din276": kg}, items))
    return sections


# Net LV grand total across the 16 priced procurement units (= sum of the
# VE budgets). The owner direct-award package VP-07 bids below are
# expressed as factors of this figure, the way install_demo_project prices
# single-package bids (bid = grand_total * factor).
_LV_GRAND_TOTAL = 7_905_000.00

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
        "Anschlussgebuehren). Die sechs groessten Vergabeeinheiten sind als "
        "Muster-LV detailliert; die uebrigen Abschnitte schliessen mit "
        "Pauschalpositionen exakt auf ihr VE-Budget (cost calculation by "
        "procurement units, six largest units detailed, remaining sections "
        "lump-summed to their budgets)."
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
    tender_name="VP-07 Kaeltetechnik CO2-Verbund und Kuehlmoebel (CO2 refrigeration, owner direct award)",
    tender_companies=[
        # factor = net bid / LV grand total; bids 812,400 / 858,900 / 901,200 EUR
        ("Sommerfeld Kaeltetechnik GmbH", "vergabe@sommerfeld-kaeltetechnik.de", 812_400 / _LV_GRAND_TOTAL),
        ("NeckarFrost Kaelte- und Klimatechnik GmbH", "angebote@neckarfrost-kaelte.de", 858_900 / _LV_GRAND_TOTAL),
        ("Kuehlanlagenbau Westheimer GmbH", "ausschreibung@kaeltebau-westheimer.de", 901_200 / _LV_GRAND_TOTAL),
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
