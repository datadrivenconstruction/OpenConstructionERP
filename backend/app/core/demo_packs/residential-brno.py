# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: czechia-cz - Residential, Brno Ponava
# ---------------------------------------------------------------------------
# Czech residential rozpocet. Prices are CZK excluding 21% DPH.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-brno",
    project_name="Bytovy dum - Brno Ponava (Residential Block, Brno)",
    project_description=(
        "Novostavba bytoveho domu v Brne Ponavce, 7 nadzemich podlazi se "
        "108 bytovymi jednotkami, komercni prostory v priizemi a podzemni "
        "garaz se 120 parkovacimi misty. Celkova podlahova plocha cca "
        "11 500 m2. Monoliticky zelezobetonovy skelet. Energeticka narocnost "
        "trida B. New-build residential block in Brno Ponava, 7 storeys, "
        "108 flats, ground-floor retail, underground car park. GFA approx. "
        "11,500 m2. Priced at Brno 2026 levels in CZK excluding DPH."
    ),
    region="CZ",
    classification_standard="din276",
    currency="CZK",
    locale="cs",
    address={
        "street": "Sportovni 4",
        "city": "Brno",
        "postcode": "602 00",
        "country": "Czech Republic",
        "lat": 49.2094,
        "lng": 16.6130,
    },
    validation_rule_sets=["din276", "boq_quality"],
    boq_name="Rozpocet - Bytovy dum Ponava (Budget)",
    boq_description=(
        "Polozkovity rozpocet pro bytovy dum o 108 jednotkach. Ceny Brno "
        "2026 v CZK bez DPH."
    ),
    boq_metadata={
        "standard": "TSKP / DIN 276",
        "phase": "Rozpocet pro vyberove rizeni (Tender budget)",
        "base_date": "2026-Q1",
        "price_level": "Brno 2026 (CZK, bez DPH)",
    },
    sections=[
        (
            "310",
            "310 - Zemni prace a zakladani (Earthworks and foundations)",
            {"din276": "310"},
            [
                ("310.01", "Sejmuti ornice (Topsoil strip)", "m2", 4200, 85, {"din276": "311"}),
                ("310.02", "Vykop stavebni jamy (Bulk excavation)", "m3", 9800, 295, {"din276": "313"}),
                ("310.03", "Odvoz vytezku (Disposal off site)", "m3", 8500, 420, {"din276": "313"}),
                ("310.04", "Zapazkovy system (Shoring)", "m2", 1600, 4200, {"din276": "312"}),
                ("310.05", "Piloty CFA prumer 450mm (CFA piles 450mm)", "m", 2400, 3200, {"din276": "322"}),
                ("310.06", "Hlavice pilot a pasy C30/37 (Pile caps and beams)", "m3", 720, 6500, {"din276": "324"}),
                ("310.07", "Zakladova deska C30/37 (Ground slab)", "m3", 580, 6800, {"din276": "324"}),
                ("310.08", "Vyztuze B500B (Reinforcement)", "t", 125, 32500, {"din276": "324"}),
                ("310.09", "Hydroizolace (Waterproofing)", "m2", 2000, 1080, {"din276": "325"}),
            ],
        ),
        (
            "330",
            "330 - Svisle konstrukce (Vertical structures)",
            {"din276": "330"},
            [
                ("330.01", "Obvodove zdivo s izolaci 380mm (External cavity wall)", "m2", 4800, 4200, {"din276": "335"}),
                ("330.02", "Omitka a natery fasada (Render and paint exterior)", "m2", 4800, 1650, {"din276": "335"}),
                ("330.03", "Plastova okna trojite zaskleni (uPVC windows triple glazed)", "m2", 2000, 8500, {"din276": "337"}),
                ("330.04", "Balkonove dvere posuvne (Sliding balcony doors)", "pcs", 108, 32500, {"din276": "337"}),
                ("330.05", "Balkonove zabradli sklo a ocel (Balcony balustrade)", "m", 1080, 5800, {"din276": "338"}),
                ("330.06", "Vylozna prosklena stena (Shopfront glazing)", "m2", 320, 9500, {"din276": "337"}),
                ("330.07", "Vstupni dvere a striska (Entrance doors and canopy)", "pcs", 3, 165000, {"din276": "334"}),
                ("330.08", "Hydroizolace balkonu (Balcony waterproofing)", "m2", 1620, 920, {"din276": "335"}),
                ("330.09", "Tmeleni spoju fasady (External sealant joints)", "m", 2800, 320, {"din276": "335"}),
                ("330.10", "Ventilacni mrizky (Service area louvres)", "m2", 420, 2800, {"din276": "338"}),
                ("330.11", "Pozarni unikovy schodiste ocel (External fire escape)", "pcs", 2, 420000, {"din276": "379"}),
                ("330.12", "Obklad soklu kamenny (Stone plinth cladding)", "m2", 320, 2400, {"din276": "335"}),
            ],
        ),
        (
            "340",
            "340 - Vnitrni steny a povrchy (Internal walls and finishes)",
            {"din276": "340"},
            [
                ("340.01", "Zdene pricky 150mm (Block partition 150mm)", "m2", 8400, 980, {"din276": "342"}),
                ("340.02", "Zdene pricky 100mm (Block partition 100mm)", "m2", 5600, 820, {"din276": "342"}),
                ("340.03", "Omitky a stitky vnitrni (Internal plaster)", "m2", 32000, 285, {"din276": "345"}),
                ("340.04", "Malba latexova (Paint)", "m2", 45000, 175, {"din276": "345"}),
                ("340.05", "Obklady koupelny keramicke (Bathroom wall tiles)", "m2", 4200, 1480, {"din276": "345"}),
                ("340.06", "Laminatova podlaha byty (Laminate flooring flats)", "m2", 6800, 1080, {"din276": "352"}),
                ("340.07", "Keramicka dlazba kuchyne a predsine (Ceramic floor tile)", "m2", 3600, 1180, {"din276": "352"}),
                ("340.08", "Vnitrni dvere vcetne zarubni (Internal doors with frames)", "pcs", 432, 12500, {"din276": "344"}),
                ("340.09", "Pozarni dvere EI 30 (Fire doors)", "pcs", 112, 19500, {"din276": "344"}),
                ("340.10", "Kuchynska linka zakladni na byt (Kitchen units per flat)", "unit", 108, 85000, {"din276": "371"}),
                ("340.11", "Vestavena skrin na byt (Built-in wardrobe per flat)", "unit", 108, 28500, {"din276": "371"}),
                ("340.12", "Sanitarni keramika na byt (Sanitaryware per flat)", "unit", 108, 58000, {"din276": "412"}),
                ("340.13", "Soklova lista drevena (Timber skirting)", "m", 6400, 280, {"din276": "352"}),
                ("340.14", "Zabradli schodiste nerez (Stair balustrade stainless)", "m", 380, 4800, {"din276": "379"}),
                ("340.15", "Postovni schranky a oznaceni (Letterboxes and signage)", "pcs", 2, 95000, {"din276": "374"}),
            ],
        ),
        (
            "350",
            "350 - Vodorovne konstrukce (Horizontal structures)",
            {"din276": "350"},
            [
                ("350.01", "Zelezobeton stropni deska C30/37, 220mm (RC slab)", "m2", 10200, 2650, {"din276": "351"}),
                ("350.02", "Vyztuze stropen B500B (Slab reinforcement)", "t", 980, 32500, {"din276": "351"}),
                ("350.03", "Bedneni (Formwork)", "m2", 20500, 780, {"din276": "351"}),
                ("350.04", "Sloupy C35/45 (RC columns)", "m3", 295, 9200, {"din276": "331"}),
                ("350.05", "Nosne steny C35/45 (RC shear walls)", "m3", 850, 8800, {"din276": "331"}),
                ("350.06", "Prefab schodistove rameno (Precast stairs)", "pcs", 14, 125000, {"din276": "379"}),
                ("350.07", "Anhydritovy poter (Screed)", "m2", 8400, 680, {"din276": "352"}),
                ("350.08", "Krocejova izolace 30mm (Impact insulation)", "m2", 7400, 320, {"din276": "352"}),
            ],
        ),
        (
            "360",
            "360 - Zastreseni (Roofs)",
            {"din276": "360"},
            [
                ("360.01", "Tepelna izolace PIR 200mm (Roof insulation)", "m2", 1500, 1380, {"din276": "363"}),
                ("360.02", "Strecha PVC folie (PVC roof membrane)", "m2", 1500, 980, {"din276": "363"}),
                ("360.03", "Odvodneni strechy (Roof drainage)", "lsum", 1, 650000, {"din276": "362"}),
                ("360.04", "FV panely 40 kWp (PV array)", "lsum", 1, 1480000, {"din276": "362"}),
            ],
        ),
        (
            "400",
            "400 - Technicke zarizeni budovy (Services)",
            {"din276": "400"},
            [
                ("400.01", "Tepelne cerpadlo 100 kW (Heat pump)", "lsum", 1, 2400000, {"din276": "421"}),
                ("400.02", "Podlahove topeni na byt (Underfloor heating per flat)", "unit", 108, 72000, {"din276": "423"}),
                ("400.03", "Rekuperace na byt (MVHR per flat)", "unit", 108, 58000, {"din276": "431"}),
                ("400.04", "Elektroinstalace na byt (Electrical per flat)", "unit", 108, 115000, {"din276": "444"}),
                ("400.05", "Spolecna elektroinstalace (Common electrical)", "lsum", 1, 4200000, {"din276": "444"}),
                ("400.06", "Vodovod a kanalizace na byt (Plumbing per flat)", "unit", 108, 135000, {"din276": "412"}),
                ("400.07", "EPS elektricky pozarni system (Fire detection)", "m2", 11500, 320, {"din276": "454"}),
                ("400.08", "Osobni vytah 8 osob, 8 stanic (Passenger lift)", "pcs", 2, 2800000, {"din276": "461"}),
                ("400.09", "Hromosvod (Lightning protection)", "lsum", 1, 850000, {"din276": "446"}),
                ("400.10", "Domaci telefon a video (Intercom and video entry)", "unit", 108, 8500, {"din276": "453"}),
                ("400.11", "Kamerovy system (CCTV)", "lsum", 1, 1250000, {"din276": "452"}),
                ("400.12", "Pristupovy system (Access control)", "pcs", 6, 85000, {"din276": "453"}),
                ("400.13", "Nabijeci stanice EV (EV charging points)", "pcs", 12, 55000, {"din276": "442"}),
                ("400.14", "Solarni termal kolektory (Solar thermal)", "lsum", 1, 1450000, {"din276": "421"}),
                ("400.15", "Sprinklerovy system (Sprinkler)", "m2", 11500, 680, {"din276": "454"}),
                ("400.16", "Destova kanalizace retence (Rainwater retention)", "lsum", 1, 950000, {"din276": "419"}),
            ],
        ),
        (
            "500",
            "500 - Venkovni upravy (External works)",
            {"din276": "500"},
            [
                ("500.01", "Zpevnene plochy (Hard landscaping)", "m2", 1600, 2200, {"din276": "520"}),
                ("500.02", "Sadove upravy (Soft landscaping)", "m2", 1200, 1150, {"din276": "530"}),
                ("500.03", "Venkovni kanalizace (External drainage)", "lsum", 1, 2200000, {"din276": "541"}),
                ("500.04", "Venkovni osvetleni (External lighting)", "pcs", 18, 48000, {"din276": "550"}),
                ("500.05", "Kolarny 108 mist (Bicycle store)", "pcs", 108, 5200, {"din276": "560"}),
                ("500.06", "Oploceni a brany (Boundary fence and gate)", "m", 220, 3200, {"din276": "560"}),
                ("500.07", "Detske hriste (Playground)", "lsum", 1, 950000, {"din276": "530"}),
                ("500.08", "Kontejnerove stanovi (Refuse store)", "pcs", 2, 185000, {"din276": "560"}),
                ("500.09", "Pozarni vodovodny privod (External fire main)", "lsum", 1, 650000, {"din276": "541"}),
            ],
        ),
    ],
    markups=[
        ("Vedlejsi rozpoctove naklady (Site overheads)", 9.0, "overhead", "direct_cost"),
        ("Rezijni naklady (Head office overheads)", 5.0, "overhead", "direct_cost"),
        ("Zisk (Profit)", 5.0, "profit", "direct_cost"),
        ("DPH 21%", 21.0, "tax", "cumulative"),
    ],
    total_months=22,
    tender_name="Generalni dodavka - Bytovy dum Ponava",
    tender_companies=[
        ("Moravska Stavba a.s.", "nabidky@moravska-stavba.example", 0.99),
        ("Brnostavby s.r.o.", "tender@brnostavby.example", 1.02),
        ("Jihomoravske Stavitelstvi a.s.", "nabidky@jihost.example", 1.04),
    ],
    project_metadata={
        "address": "Sportovni 4, 602 00 Brno",
        "client": "Ponava Development s.r.o.",
        "architect": "Ateliery Brno s.r.o.",
        "structural_engineer": "Statik Morava s.r.o.",
        "qs": "Rozpocty Brno s.r.o.",
        "gfa_m2": 11500,
        "units": 108,
        "storeys_above": 7,
        "storeys_below": 1,
        "parking_spaces": 120,
        "energy_class": "B",
    },
)
