# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: romania-ro - Office Building, Bucharest
# ---------------------------------------------------------------------------
# The second Romanian demo, and a different kind of job from the Cluj block:
# a speculative office building in the northern business district of
# Bucharest, the highest seismic zone in the country, where the structure and
# the facade carry the weight and the fit-out is shell and core.
#
# Every line names its HG 907/2016 deviz general chapter under the ``deviz``
# key and its DIN 276 cost group. Prices are Bucharest 2026 levels in RON
# excluding TVA, all-in unit rates.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="office-bucharest",
    project_name="Clădire de birouri - București, Pipera (Office Building, Bucharest)",
    project_description=(
        "Clădire de birouri nouă 2S+P+9E în zona Pipera din București, "
        "aproximativ 18 500 m2 suprafață construită desfășurată, livrată la "
        "stadiul shell and core, cu 210 locuri de parcare subterane. "
        "Structură în cadre și nuclee din beton armat dimensionată pentru "
        "zona seismică ag = 0,30 g, fațadă cortină unitizată. Țintă de "
        "certificare verde. New-build office building in Pipera, Bucharest, "
        "two basements plus ground plus nine storeys, approx. 18,500 m2 GFA, "
        "shell and core, 210 underground parking spaces. Priced at Bucharest "
        "2026 levels in RON excluding TVA."
    ),
    region="RO",
    classification_standard="din276",
    currency="RON",
    locale="ro",
    address={
        "street": "Bulevardul Dimitrie Pompeiu 20",
        "city": "București",
        "postcode": "020337",
        "country": "Romania",
        "lat": 44.4808,
        "lng": 26.1175,
    },
    validation_rule_sets=["romania", "din276", "boq_quality"],
    boq_name="Deviz pe obiect - Clădire de birouri Pipera (Per-object estimate)",
    boq_description=(
        "Deviz pe obiect pentru o clădire de birouri 2S+P+9E, shell and core. "
        "Poziții încadrate în capitolele devizului general (HG 907/2016) și "
        "clasificate DIN 276. Prețuri București 2026 în RON, fără TVA."
    ),
    boq_metadata={
        "standard": "HG 907/2016 deviz general / DIN 276",
        "phase": "Deviz pe obiect, faza PT (Technical design estimate)",
        "base_date": "2026-Q3",
        "price_level": "București 2026 (RON, fără TVA)",
    },
    sections=[
        (
            "1.2",
            "1.2 - Amenajarea terenului (Site preparation)",
            {"din276": "210", "deviz": "1.2"},
            [
                ("1.2.01", "Demolare construcții existente și evacuare moloz (Demolition of existing sheds)", "m3", 3200, 95, {"din276": "212", "deviz": "1.2"}),
                ("1.2.02", "Relocare rețea electrică de medie tensiune (Relocate medium-voltage cable)", "lsum", 1, 420000, {"din276": "211", "deviz": "1.4"}),
            ],
        ),
        (
            "2",
            "2 - Asigurarea utilităților (Utility connections)",
            {"din276": "220", "deviz": "2"},
            [
                ("2.01", "Racord electric și post de transformare 2 x 1 600 kVA (Power connection and substation)", "lsum", 1, 1850000, {"din276": "225", "deviz": "2"}),
                ("2.02", "Branșament apă și racord canalizare (Water and sewer connections)", "lsum", 1, 420000, {"din276": "221", "deviz": "2"}),
                ("2.03", "Racord fibră optică și telecomunicații (Fibre and telecom connection)", "lsum", 1, 95000, {"din276": "226", "deviz": "2"}),
            ],
        ),
        (
            "4.1-310",
            "4.1 / 310-320 - Excavații, incintă și fundații (Excavation, retaining walls, foundations)",
            {"din276": "320", "deviz": "4.1"},
            [
                ("4.1.01", "Pereți mulați din beton armat 60 cm (Diaphragm walls, 600 mm)", "m2", 5200, 1650, {"din276": "312", "deviz": "4.1"}),
                ("4.1.02", "Săpătură generală în incintă și transport (Bulk excavation within the enclosure, carted away)", "m3", 38000, 95, {"din276": "311", "deviz": "4.1"}),
                ("4.1.03", "Epuismente și coborârea nivelului apei (Dewatering)", "lsum", 1, 1250000, {"din276": "313", "deviz": "4.1"}),
                ("4.1.04", "Piloți forați Ø 1 000 mm (Bored piles, 1,000 mm)", "m", 4600, 1450, {"din276": "323", "deviz": "4.1"}),
                ("4.1.05", "Radier beton C35/45 impermeabil, 1,5 m (Watertight raft, 1.5 m)", "m3", 3900, 1080, {"din276": "322", "deviz": "4.1"}),
                ("4.1.06", "Armătură B500C la infrastructură (Substructure reinforcement)", "t", 780, 6900, {"din276": "322", "deviz": "4.1"}),
                ("4.1.07", "Hidroizolație infrastructură și rosturi (Substructure waterproofing and joints)", "m2", 8400, 165, {"din276": "325", "deviz": "4.1"}),
            ],
        ),
        (
            "4.1-330",
            "4.1 / 340-350 - Suprastructură din beton armat (Reinforced concrete superstructure)",
            {"din276": "350", "deviz": "4.1"},
            [
                ("4.1.08", "Nuclee și pereți structurali C40/50 (Cores and shear walls)", "m3", 3100, 1250, {"din276": "341", "deviz": "4.1"}),
                ("4.1.09", "Stâlpi C40/50 (Columns)", "m3", 1150, 1320, {"din276": "343", "deviz": "4.1"}),
                ("4.1.10", "Plăci dală C35/45, 28 cm (Flat slabs, 280 mm)", "m3", 5300, 1120, {"din276": "351", "deviz": "4.1"}),
                ("4.1.11", "Armătură B500C la suprastructură (Superstructure reinforcement)", "t", 1680, 6900, {"din276": "351", "deviz": "4.1"}),
                ("4.1.12", "Cofraje sistem la plăci, stâlpi și nuclee (System formwork)", "m2", 52000, 125, {"din276": "351", "deviz": "4.1"}),
                ("4.1.13", "Scări din beton armat monolit (Cast in place stairs)", "pcs", 24, 14500, {"din276": "351", "deviz": "4.1"}),
            ],
        ),
        (
            "4.1-330b",
            "4.1 / 330 - Fațade (Facades)",
            {"din276": "330", "deviz": "4.1"},
            [
                ("4.1.14", "Fațadă cortină unitizată, geam triplu cu control solar (Unitised curtain wall, triple glazed)", "m2", 9800, 3650, {"din276": "337", "deviz": "4.1"}),
                ("4.1.15", "Placaj ceramic ventilat la parter (Ventilated ceramic cladding to podium)", "m2", 1400, 820, {"din276": "335", "deviz": "4.1"}),
                ("4.1.16", "Uși rotative și glisante automate (Revolving and automatic sliding doors)", "pcs", 3, 285000, {"din276": "334", "deviz": "4.1"}),
                ("4.1.17", "Parasolare exterioare motorizate (Motorised external sun shading)", "m2", 3200, 690, {"din276": "338", "deviz": "4.1"}),
            ],
        ),
        (
            "4.1-360",
            "4.1 / 360 - Acoperiș (Roof)",
            {"din276": "360", "deviz": "4.1"},
            [
                ("4.1.18", "Acoperiș terasă termoizolat și hidroizolat (Insulated and waterproofed flat roof)", "m2", 1900, 360, {"din276": "363", "deviz": "4.1"}),
                ("4.1.19", "Acoperiș verde extensiv (Extensive green roof)", "m2", 850, 240, {"din276": "363", "deviz": "4.1"}),
            ],
        ),
        (
            "4.1-340",
            "4.1 / 340-350 - Finisaje spații comune (Common area finishes)",
            {"din276": "340", "deviz": "4.1"},
            [
                ("4.1.20", "Pereți despărțitori gips-carton rezistenți la foc EI 90 (Fire-rated plasterboard walls)", "m2", 7800, 210, {"din276": "342", "deviz": "4.1"}),
                ("4.1.21", "Pardoseală piatră naturală lobby (Natural stone floor to lobby)", "m2", 650, 780, {"din276": "353", "deviz": "4.1"}),
                ("4.1.22", "Șapă și rășină epoxidică parcare (Screed and epoxy to car park)", "m2", 6900, 135, {"din276": "353", "deviz": "4.1"}),
                ("4.1.23", "Tavane suspendate metalice în spații comune (Metal suspended ceilings to common areas)", "m2", 2400, 240, {"din276": "354", "deviz": "4.1"}),
                ("4.1.24", "Uși metalice rezistente la foc (Fire doors)", "pcs", 140, 5200, {"din276": "344", "deviz": "4.1"}),
            ],
        ),
        (
            "4.1-400",
            "4.1 / 400 - Instalații (Building services)",
            {"din276": "400", "deviz": "4.1"},
            [
                ("4.1.25", "Instalații sanitare și grupuri sanitare pe nivel (Plumbing and core toilets)", "lsum", 1, 3200000, {"din276": "412", "deviz": "4.1"}),
                ("4.1.26", "Pompe de căldură aer-apă 1,6 MW și chillere (Air-to-water heat pumps and chillers)", "lsum", 1, 7400000, {"din276": "421", "deviz": "4.1"}),
                ("4.1.27", "Ventiloconvectoare și distribuție, shell and core (Fan coil units and distribution)", "m2", 13800, 390, {"din276": "423", "deviz": "4.1"}),
                ("4.1.28", "Centrale de tratare aer cu recuperare (Air handling units with heat recovery)", "pcs", 6, 820000, {"din276": "431", "deviz": "4.1"}),
                ("4.1.29", "Tubulatură ventilare și desfumare (Ductwork and smoke extract)", "m2", 11500, 210, {"din276": "431", "deviz": "4.1"}),
                ("4.1.30", "Stingere automată cu sprinklere (Sprinkler system)", "m2", 18500, 95, {"din276": "470", "deviz": "4.1"}),
                ("4.1.31", "Tablouri generale și distribuție de forță (Main switchboards and power distribution)", "lsum", 1, 4600000, {"din276": "443", "deviz": "4.1"}),
                ("4.1.32", "Grup electrogen 1 000 kVA (Standby generator)", "pcs", 1, 1650000, {"din276": "442", "deviz": "4.1"}),
                ("4.1.33", "Iluminat LED spații comune și iluminat de siguranță (LED and emergency lighting)", "lsum", 1, 1350000, {"din276": "445", "deviz": "4.1"}),
                ("4.1.34", "Detecție incendiu și alarmare vocală (Fire detection and voice alarm)", "m2", 18500, 58, {"din276": "456", "deviz": "4.1"}),
                ("4.1.35", "Control acces, supraveghere video (Access control and CCTV)", "lsum", 1, 1150000, {"din276": "456", "deviz": "4.1"}),
                ("4.1.36", "Sistem de management al clădirii BMS (Building management system)", "lsum", 1, 1850000, {"din276": "481", "deviz": "4.1"}),
                ("4.1.37", "Ascensoare 1 600 kg, 12 stații (Passenger lifts, 12 stops)", "pcs", 6, 720000, {"din276": "461", "deviz": "4.1"}),
                ("4.1.38", "Stații de încărcare vehicule electrice (EV charging points)", "pcs", 24, 14500, {"din276": "444", "deviz": "4.1"}),
            ],
        ),
        (
            "4.1-500",
            "4.1 / 500 - Amenajări exterioare (External works)",
            {"din276": "500", "deviz": "4.1"},
            [
                ("4.1.39", "Platforme și alei din piatră (Stone paving to forecourt)", "m2", 1800, 420, {"din276": "530", "deviz": "4.1"}),
                ("4.1.40", "Spații verzi, plantații și irigații (Landscaping, planting and irrigation)", "m2", 1400, 160, {"din276": "570", "deviz": "4.1"}),
            ],
        ),
        (
            "4.1-390",
            "4.1 / 350-440 - Lucrări complementare (Complementary works)",
            {"din276": "350", "deviz": "4.1"},
            [
                ("4.1.41", "Termoizolație la intradosul plăcii peste parcare (Insulation to car park soffit)", "m2", 2000, 140, {"din276": "354", "deviz": "4.1"}),
                ("4.1.42", "Balustrade din sticlă la scări și atrium (Glass balustrades to stairs and atrium)", "m", 260, 1450, {"din276": "359", "deviz": "4.1"}),
                ("4.1.43", "Hidroizolație terase circulabile (Waterproofing to accessible terraces)", "m2", 600, 280, {"din276": "363", "deviz": "4.1"}),
                ("4.1.44", "Marcaje și semnalizare parcare (Car park markings and signage)", "m2", 6900, 18, {"din276": "353", "deviz": "4.1"}),
                ("4.1.45", "Rampă auto cu încălzire (Heated vehicle ramp)", "m2", 280, 950, {"din276": "353", "deviz": "4.1"}),
                ("4.1.46", "Stații de pompare ape uzate subsol (Basement sewage pumping stations)", "pcs", 2, 85000, {"din276": "411", "deviz": "4.1"}),
                ("4.1.47", "Separator de hidrocarburi (Hydrocarbon separator)", "pcs", 1, 120000, {"din276": "411", "deviz": "4.1"}),
                ("4.1.48", "Instalație de paratrăsnet (Lightning protection)", "lsum", 1, 180000, {"din276": "446", "deviz": "4.1"}),
                ("4.1.49", "Detecție CO în parcare (Car park CO detection)", "lsum", 1, 210000, {"din276": "456", "deviz": "4.1"}),
            ],
        ),
        (
            "5.1",
            "5.1 - Organizare de șantier (Site organisation)",
            {"din276": "390", "deviz": "5.1"},
            [
                ("5.1.01", "Împrejmuire, porți și pază (Hoarding, gates and security)", "month", 26, 38000, {"din276": "391", "deviz": "5.1"}),
                ("5.1.02", "Macarale turn, două bucăți (Two tower cranes)", "month", 20, 78000, {"din276": "391", "deviz": "5.1"}),
                ("5.1.03", "Birouri de șantier și utilități provizorii (Site offices and temporary services)", "month", 26, 42000, {"din276": "391", "deviz": "5.1"}),
            ],
        ),
    ],
    markups=[
        ("Cheltuieli indirecte (Indirect costs)", 10.0, "overhead", "direct_cost"),
        ("Profit", 5.0, "profit", "cumulative"),
        ("Cheltuieli diverse și neprevăzute (Contingency)", 10.0, "contingency", "cumulative"),
        ("TVA 21%", 21.0, "tax", "cumulative"),
    ],
    total_months=26,
    tender_name="Antrepriză generală - Clădire de birouri Pipera",
    tender_companies=[
        ("Dunărea Construcții SA", "ofertare@dunarea-constructii.example", 0.98),
        ("Capitala Build SRL", "tender@capitala-build.example", 1.02),
        ("Muntenia Antrepriză SA", "licitatii@muntenia-antrepriza.example", 1.05),
    ],
    tender_packages=[
        (
            "Incintă, structură și fațadă (Enclosure, structure and facade)",
            "Pereți mulați, piloți, radier, structură din beton armat și fațadă cortină",
            "evaluating",
            [
                ("Dunărea Construcții SA", "ofertare@dunarea-constructii.example", 0.98),
                ("Capitala Build SRL", "tender@capitala-build.example", 1.02),
                ("Muntenia Antrepriză SA", "licitatii@muntenia-antrepriza.example", 1.05),
            ],
        ),
        (
            "Instalații (Building services)",
            "Climatizare, ventilare, sprinklere, electrice, BMS și ascensoare",
            "draft",
            [
                ("Instal Sud SRL", "oferte@instal-sud.example", 1.00),
                ("Energo Montaj București SA", "tender@energo-montaj.example", 1.03),
            ],
        ),
    ],
    project_metadata={
        "address": "Bulevardul Dimitrie Pompeiu 20, 020337 București, Romania",
        "client": "Pipera Office Development SRL",
        "architect": "Birou de Arhitectură Nord SRL",
        "structural_engineer": "Structuri Seismice București SRL",
        "quantity_surveyor": "Devize și Costuri Consult SRL",
        "gfa_m2": 18500,
        "storeys_above": 10,
        "storeys_below": 2,
        "parking_spaces": 210,
        "seismic_design": "P100-1/2013, ag = 0.30 g, TC = 1.6 s (București)",
        "delivery_standard": "Shell and core; amenajarea spațiilor chiriașilor nu face parte din deviz",
        "construction_standards": [
            "HG 907/2016 - deviz general",
            "P100-1/2013 - cod de proiectare seismică",
            "Legea 169/2026 - Codul amenajării teritoriului, urbanismului și construcțiilor",
        ],
        "vat_note": "Toate prețurile unitare sunt fără TVA. TVA 21% se aplică pe centralizator.",
    },
)
