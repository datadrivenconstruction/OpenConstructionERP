# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: romania-ro - Residential Block, Cluj-Napoca
# ---------------------------------------------------------------------------
# A deviz pe obiect for one residential block, filed line by line under the
# HG 907/2016 deviz general chapters (classification key ``deviz``) and
# classified against DIN 276 for the cost-group view. Most lines are 4.1,
# construction and installation works; site preparation sits in 1.2, utility
# connections in 2 and site organisation in 5.1, which is where a Romanian
# budget puts them.
#
# Prices are Cluj-Napoca 2026 levels in RON excluding TVA, all-in unit rates
# (material, labour, plant). The cascade is the Romanian one: indirect costs,
# profit, contingency, then TVA at 21 percent.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-cluj",
    project_name="Bloc de locuințe - Cluj-Napoca, Borhanci (Residential Block, Cluj-Napoca)",
    project_description=(
        "Bloc de locuințe nou S+P+6E cu 64 de apartamente, parcare subterană "
        "cu 58 de locuri și spații comerciale la parter, în cartierul Borhanci "
        "din Cluj-Napoca. Suprafața construită desfășurată aproximativ 6 400 m2. "
        "Structură în cadre din beton armat, zidărie de umplutură din BCA, "
        "termosistem cu vată minerală, tâmplărie PVC cu geam triplu. "
        "New-build residential block, basement plus ground plus six storeys, "
        "64 flats, 58 underground parking spaces and ground-floor retail in "
        "Cluj-Napoca. GFA approx. 6,400 m2. Priced at Cluj 2026 levels in RON "
        "excluding TVA."
    ),
    region="RO",
    classification_standard="din276",
    currency="RON",
    locale="ro",
    address={
        "street": "Strada Borhanciului 42",
        "city": "Cluj-Napoca",
        "postcode": "400432",
        "country": "Romania",
        "lat": 46.7456,
        "lng": 23.6180,
    },
    validation_rule_sets=["romania", "din276", "boq_quality"],
    boq_name="Deviz pe obiect - Bloc de locuințe Borhanci (Per-object estimate)",
    boq_description=(
        "Deviz pe obiect pentru un bloc de locuințe S+P+6E cu 64 de apartamente. "
        "Fiecare poziție este încadrată în capitolul devizului general (HG 907/2016) "
        "și clasificată DIN 276. Prețuri Cluj-Napoca 2026 în RON, fără TVA."
    ),
    boq_metadata={
        "standard": "HG 907/2016 deviz general / DIN 276",
        "phase": "Deviz pe obiect pentru documentația de atribuire (Pre-tender estimate)",
        "base_date": "2026-Q3",
        "price_level": "Cluj-Napoca 2026 (RON, fără TVA)",
    },
    sections=[
        (
            "1.2",
            "1.2 - Amenajarea terenului (Site preparation)",
            {"din276": "210", "deviz": "1.2"},
            [
                ("1.2.01", "Decopertare strat vegetal 20 cm (Topsoil strip, 200 mm)", "m2", 2600, 14, {"din276": "214", "deviz": "1.2"}),
                ("1.2.02", "Demolare platformă betonată existentă (Break out existing concrete hardstanding)", "m2", 680, 85, {"din276": "212", "deviz": "1.2"}),
                ("1.2.03", "Nivelare și compactare platformă (Level and compact formation)", "m2", 2600, 9, {"din276": "214", "deviz": "1.2"}),
            ],
        ),
        (
            "2",
            "2 - Asigurarea utilităților (Utility connections)",
            {"din276": "220", "deviz": "2"},
            [
                ("2.01", "Branșament apă PEHD DN 110 (Water connection)", "m", 85, 780, {"din276": "222", "deviz": "2"}),
                ("2.02", "Racord canalizare PVC DN 250 cu cămine (Sewer connection with manholes)", "m", 120, 950, {"din276": "221", "deviz": "2"}),
                ("2.03", "Branșament gaze naturale (Gas connection)", "lsum", 1, 68000, {"din276": "223", "deviz": "2"}),
                ("2.04", "Post de transformare și racord electric 630 kVA (Transformer station and power connection)", "lsum", 1, 485000, {"din276": "225", "deviz": "2"}),
            ],
        ),
        (
            "4.1-310",
            "4.1 / 310 - Terasamente și sprijiniri (Earthworks and shoring)",
            {"din276": "310", "deviz": "4.1"},
            [
                ("4.1.01", "Săpătură mecanizată la groapa de fundație (Bulk excavation by machine)", "m3", 8200, 48, {"din276": "311", "deviz": "4.1"}),
                ("4.1.02", "Încărcare și transport pământ excedentar la depozit autorizat (Load and cart surplus spoil)", "m3", 7300, 62, {"din276": "311", "deviz": "4.1"}),
                ("4.1.03", "Sprijinire maluri cu pereți berlinezi (Soldier pile and lagging shoring)", "m2", 1150, 520, {"din276": "312", "deviz": "4.1"}),
                ("4.1.04", "Epuismente pe durata execuției infrastructurii (Dewatering during substructure works)", "lsum", 1, 95000, {"din276": "313", "deviz": "4.1"}),
                ("4.1.05", "Umplutură compactată cu balast (Compacted granular backfill)", "m3", 950, 115, {"din276": "311", "deviz": "4.1"}),
            ],
        ),
        (
            "4.1-320",
            "4.1 / 320 - Fundații și infrastructură (Foundations and substructure)",
            {"din276": "320", "deviz": "4.1"},
            [
                ("4.1.06", "Beton de egalizare C12/15 (Blinding concrete)", "m3", 175, 610, {"din276": "322", "deviz": "4.1"}),
                ("4.1.07", "Radier general beton C30/37 XC2, turnat cu pompa (Raft foundation concrete, pumped)", "m3", 1250, 1020, {"din276": "322", "deviz": "4.1"}),
                ("4.1.08", "Armătură B500C fasonată și montată la radier (Raft reinforcement, cut, bent and fixed)", "t", 150, 6900, {"din276": "322", "deviz": "4.1"}),
                ("4.1.09", "Hidroizolație membrană bentonitică sub radier și pereți subsol (Bentonite membrane waterproofing)", "m2", 2900, 145, {"din276": "325", "deviz": "4.1"}),
                ("4.1.10", "Pereți subsol beton C30/37 impermeabil (Basement walls, watertight concrete)", "m3", 460, 1080, {"din276": "331", "deviz": "4.1"}),
            ],
        ),
        (
            "4.1-330",
            "4.1 / 330-350 - Structură din beton armat (Reinforced concrete frame)",
            {"din276": "350", "deviz": "4.1"},
            [
                ("4.1.11", "Stâlpi beton C30/37 (Columns, C30/37)", "m3", 340, 1150, {"din276": "343", "deviz": "4.1"}),
                ("4.1.12", "Pereți structurali și nuclee beton C30/37 (Shear walls and cores)", "m3", 820, 1090, {"din276": "341", "deviz": "4.1"}),
                ("4.1.13", "Plăci beton C30/37 grosime 20 cm (Flat slabs, 200 mm)", "m3", 1420, 1060, {"din276": "351", "deviz": "4.1"}),
                ("4.1.14", "Armătură B500C la suprastructură (Superstructure reinforcement)", "t", 395, 6900, {"din276": "351", "deviz": "4.1"}),
                ("4.1.15", "Cofraje la stâlpi, pereți și plăci (Formwork to columns, walls and slabs)", "m2", 17800, 115, {"din276": "351", "deviz": "4.1"}),
                ("4.1.16", "Scări prefabricate din beton armat (Precast concrete stair flights)", "pcs", 16, 6800, {"din276": "351", "deviz": "4.1"}),
            ],
        ),
        (
            "4.1-330b",
            "4.1 / 330 - Închideri și fațade (Envelope and facades)",
            {"din276": "330", "deviz": "4.1"},
            [
                ("4.1.17", "Zidărie de umplutură BCA 30 cm (Aerated concrete infill masonry, 300 mm)", "m2", 4300, 290, {"din276": "332", "deviz": "4.1"}),
                ("4.1.18", "Termosistem vată minerală bazaltică 15 cm (ETICS, mineral wool 150 mm)", "m2", 4700, 265, {"din276": "335", "deviz": "4.1"}),
                ("4.1.19", "Tâmplărie PVC cu geam triplu Uw 0,9 (PVC windows, triple glazed)", "m2", 1320, 1450, {"din276": "334", "deviz": "4.1"}),
                ("4.1.20", "Uși de intrare în bloc din aluminiu (Aluminium entrance doors)", "pcs", 3, 24500, {"din276": "334", "deviz": "4.1"}),
                ("4.1.21", "Balustrade balcoane din sticlă securizată (Glass balcony balustrades)", "m", 540, 1150, {"din276": "339", "deviz": "4.1"}),
            ],
        ),
        (
            "4.1-360",
            "4.1 / 360 - Acoperiș terasă (Flat roof)",
            {"din276": "360", "deviz": "4.1"},
            [
                ("4.1.22", "Termoizolație terasă XPS 20 cm și beton de pantă (Roof insulation and screed to falls)", "m2", 920, 195, {"din276": "363", "deviz": "4.1"}),
                ("4.1.23", "Hidroizolație bitum modificat în două straturi (Two-layer modified bitumen membrane)", "m2", 920, 110, {"din276": "363", "deviz": "4.1"}),
                ("4.1.24", "Receptoare pluviale și trape de acces (Roof outlets and access hatches)", "lsum", 1, 38000, {"din276": "362", "deviz": "4.1"}),
            ],
        ),
        (
            "4.1-340",
            "4.1 / 340 - Compartimentări și finisaje (Partitions and finishes)",
            {"din276": "340", "deviz": "4.1"},
            [
                ("4.1.25", "Pereți despărțitori gips-carton pe structură metalică (Plasterboard partitions)", "m2", 5600, 150, {"din276": "342", "deviz": "4.1"}),
                ("4.1.26", "Tencuieli interioare pe bază de ipsos, mecanizat (Machine-applied gypsum plaster)", "m2", 16500, 48, {"din276": "345", "deviz": "4.1"}),
                ("4.1.27", "Zugrăveli lavabile în două straturi (Emulsion paint, two coats)", "m2", 26000, 24, {"din276": "345", "deviz": "4.1"}),
                ("4.1.28", "Șapă autonivelantă 5 cm (Self-levelling screed, 50 mm)", "m2", 5200, 68, {"din276": "353", "deviz": "4.1"}),
                ("4.1.29", "Parchet laminat cu folie fonoizolantă (Laminate flooring with acoustic underlay)", "m2", 3300, 120, {"din276": "353", "deviz": "4.1"}),
                ("4.1.30", "Gresie și faianță în băi și bucătării (Floor and wall tiles to wet rooms)", "m2", 3100, 220, {"din276": "353", "deviz": "4.1"}),
                ("4.1.31", "Uși interioare și uși de intrare în apartament (Internal and flat entrance doors)", "pcs", 384, 1950, {"din276": "344", "deviz": "4.1"}),
            ],
        ),
        (
            "4.1-400",
            "4.1 / 400 - Instalații (Building services)",
            {"din276": "400", "deviz": "4.1"},
            [
                ("4.1.32", "Instalații sanitare interioare și obiecte sanitare (Plumbing and sanitaryware)", "pcs", 64, 26000, {"din276": "412", "deviz": "4.1"}),
                ("4.1.33", "Canalizare interioară și coloane (Internal drainage and stacks)", "lsum", 1, 310000, {"din276": "411", "deviz": "4.1"}),
                ("4.1.34", "Centrale termice murale în condensare, individuale (Individual condensing boilers)", "pcs", 64, 11500, {"din276": "421", "deviz": "4.1"}),
                ("4.1.35", "Încălzire în pardoseală și distribuție (Underfloor heating and distribution)", "m2", 4650, 165, {"din276": "423", "deviz": "4.1"}),
                ("4.1.36", "Ventilare mecanică parcare subterană (Car park ventilation)", "lsum", 1, 265000, {"din276": "431", "deviz": "4.1"}),
                ("4.1.37", "Instalații electrice interioare și tablouri (Electrical installation and boards)", "pcs", 64, 24000, {"din276": "444", "deviz": "4.1"}),
                ("4.1.38", "Iluminat spații comune și iluminat de siguranță (Common area and emergency lighting)", "lsum", 1, 185000, {"din276": "445", "deviz": "4.1"}),
                ("4.1.39", "Instalație de paratrăsnet și împământare (Lightning protection and earthing)", "lsum", 1, 42000, {"din276": "446", "deviz": "4.1"}),
                ("4.1.40", "Detecție și alarmare incendiu, desfumare casa scării (Fire detection and stair smoke venting)", "lsum", 1, 235000, {"din276": "456", "deviz": "4.1"}),
                ("4.1.41", "Ascensoare 630 kg, 8 stații (Passenger lifts, 8 stops)", "pcs", 2, 310000, {"din276": "461", "deviz": "4.1"}),
            ],
        ),
        (
            "4.1-500",
            "4.1 / 500 - Amenajări exterioare (External works)",
            {"din276": "500", "deviz": "4.1"},
            [
                ("4.1.42", "Alei și platforme din pavele (Block paving to paths and hardstanding)", "m2", 1150, 175, {"din276": "530", "deviz": "4.1"}),
                ("4.1.43", "Spații verzi și plantații (Soft landscaping and planting)", "m2", 950, 65, {"din276": "570", "deviz": "4.1"}),
                ("4.1.44", "Loc de joacă pentru copii (Children's play area)", "lsum", 1, 115000, {"din276": "550", "deviz": "4.1"}),
            ],
        ),
        (
            "5.1",
            "5.1 - Organizare de șantier (Site organisation)",
            {"din276": "390", "deviz": "5.1"},
            [
                ("5.1.01", "Împrejmuire provizorie și porți de acces (Site hoarding and gates)", "m", 320, 145, {"din276": "391", "deviz": "5.1"}),
                ("5.1.02", "Containere birou, vestiare și grupuri sanitare (Site cabins and welfare)", "month", 20, 9800, {"din276": "391", "deviz": "5.1"}),
                ("5.1.03", "Macara turn, montaj, chirie și demontaj (Tower crane, erect, hire and dismantle)", "month", 14, 32000, {"din276": "391", "deviz": "5.1"}),
                ("5.1.04", "Schele fațadă (Facade scaffolding)", "m2", 5100, 38, {"din276": "392", "deviz": "5.1"}),
            ],
        ),
    ],
    markups=[
        ("Cheltuieli indirecte (Indirect costs)", 10.0, "overhead", "direct_cost"),
        ("Profit", 5.0, "profit", "cumulative"),
        ("Cheltuieli diverse și neprevăzute (Contingency)", 10.0, "contingency", "cumulative"),
        ("TVA 21%", 21.0, "tax", "cumulative"),
    ],
    total_months=20,
    tender_name="Execuție lucrări - Bloc de locuințe Borhanci",
    tender_companies=[
        ("Transilvania Construct SRL", "ofertare@transilvania-construct.example", 0.97),
        ("Someș Edil SA", "oferte@somes-edil.example", 1.02),
        ("Carpați Structuri SRL", "licitatii@carpati-structuri.example", 1.04),
    ],
    tender_packages=[
        (
            "Structură și închideri (Structure and envelope)",
            "Terasamente, radier, cadre din beton armat, zidărie BCA, termosistem și tâmplărie",
            "evaluating",
            [
                ("Transilvania Construct SRL", "ofertare@transilvania-construct.example", 0.97),
                ("Someș Edil SA", "oferte@somes-edil.example", 1.02),
                ("Carpați Structuri SRL", "licitatii@carpati-structuri.example", 1.04),
            ],
        ),
        (
            "Instalații (Building services)",
            "Instalații sanitare, termice, electrice, ascensoare și detecție incendiu",
            "issued",
            [
                ("Instal Nord-Vest SRL", "oferte@instal-nordvest.example", 0.99),
                ("Electro Cluj SRL", "tender@electro-cluj.example", 1.03),
            ],
        ),
    ],
    project_metadata={
        "address": "Strada Borhanciului 42, 400432 Cluj-Napoca, Romania",
        "client": "Borhanci Residence SRL",
        "architect": "Atelier Arhitectură Someș SRL",
        "structural_engineer": "Proiect Structuri Cluj SRL",
        "quantity_surveyor": "Devize și Consultanță Transilvania SRL",
        "gfa_m2": 6400,
        "storeys_above": 7,
        "storeys_below": 1,
        "apartments": 64,
        "parking_spaces": 58,
        "seismic_design": "P100-1/2013, ag = 0.10 g (Cluj-Napoca)",
        "construction_standards": [
            "HG 907/2016 - deviz general",
            "P100-1/2013 - cod de proiectare seismică",
            "Legea 169/2026 - Codul amenajării teritoriului, urbanismului și construcțiilor",
        ],
        "vat_note": "Toate prețurile unitare sunt fără TVA. TVA 21% se aplică pe centralizator.",
        "labour_note": "Salariul minim brut în construcții 4 582 RON/lună; CAM 2,25% inclus în manopera pozițiilor.",
    },
)
