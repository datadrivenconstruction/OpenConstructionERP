# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: belgium-be - Appartementsgebouw, Antwerp
# ---------------------------------------------------------------------------
# Belgian residential development in Antwerp. Dutch-language descriptions.
# Prices are EUR excluding 21% BTW (new-build rate).
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-antwerp",
    project_name="Appartementsgebouw Eilandje - Antwerpen (Residential, Antwerp Docks)",
    project_description=(
        "Nieuwbouw appartementsgebouw op het Eilandje in Antwerpen, 8 bouwlagen "
        "met 96 wooneenheden, commerciele ruimte op het gelijkvloers en "
        "ondergrondse parkeergarage met 110 plaatsen. BVO circa 12.500 m2. "
        "Betonnen draagstructuur. EPB-peil E30 (S28) conform Vlaams "
        "Energieprestatiedecreet. Apartment building at Eilandje, Antwerp, "
        "8 storeys with 96 units, ground-floor retail and underground car "
        "park. GFA approx. 12,500 m2. Priced at Antwerp 2026 levels in EUR "
        "excluding BTW."
    ),
    region="BE",
    classification_standard="din276",
    currency="EUR",
    locale="nl",
    address={
        "street": "Kattendijkdok Oostkaai 25",
        "city": "Antwerp",
        "postcode": "2000",
        "country": "Belgium",
        "lat": 51.2327,
        "lng": 4.4070,
    },
    validation_rule_sets=["din276", "boq_quality"],
    boq_name="Meetstaat - Appartementsgebouw Eilandje (Bill of Quantities)",
    boq_description=(
        "Elementengewijze meetstaat voor 96 wooneenheden met ondergrondse "
        "parking. Antwerpen 2026 prijsniveau in EUR exclusief BTW."
    ),
    boq_metadata={
        "standard": "BB/SfB / DIN 276",
        "phase": "Aanbestedingsdossier (Tender)",
        "base_date": "2026-Q1",
        "price_level": "Antwerpen 2026 (EUR, excl BTW)",
    },
    sections=[
        (
            "310",
            "310 - Grondwerken en fundering (Earthworks and foundations)",
            {"din276": "310"},
            [
                ("310.01", "Bodemsanering vooronderzoek (Soil remediation assessment)", "lsum", 1, 42000.00, {"din276": "311"}),
                ("310.02", "Uitgraving bouwput (Bulk excavation)", "m3", 9500, 13.00, {"din276": "313"}),
                ("310.03", "Grondafvoer (Disposal off site)", "m3", 8000, 21.00, {"din276": "313"}),
                ("310.04", "Beschoeiiing damwand (Sheet pile shoring)", "m2", 1800, 175.00, {"din276": "312"}),
                ("310.05", "Schroefpalen 450mm (CFA piles 450mm)", "m", 2200, 128.00, {"din276": "322"}),
                ("310.06", "Poeren en funderingsbalken C30/37 (Pile caps and beams)", "m3", 780, 265.00, {"din276": "324"}),
                ("310.07", "Funderingsplaat C30/37 (Ground slab)", "m3", 620, 275.00, {"din276": "324"}),
                ("310.08", "Wapening funderingen B500B (Reinforcement)", "t", 155, 1350.00, {"din276": "324"}),
                ("310.09", "Waterdichting kelder (Basement waterproofing)", "m2", 2200, 45.00, {"din276": "325"}),
            ],
        ),
        (
            "330",
            "330 - Buitenwanden (External walls)",
            {"din276": "330"},
            [
                ("330.01", "Gevelmetselwerk isolerend 300mm (Cavity wall with insulation)", "m2", 5200, 175.00, {"din276": "335"}),
                ("330.02", "Crepi afwerking bovenverdiepingen (Render to upper floors)", "m2", 3200, 65.00, {"din276": "335"}),
                ("330.03", "Aluminium ramen driedubbel glas (Windows triple glazed)", "m2", 2200, 365.00, {"din276": "337"}),
                ("330.04", "Schuifdeuren balkons (Sliding doors to balconies)", "pcs", 96, 1380.00, {"din276": "337"}),
                ("330.05", "Balkonhekwerk glas en staal (Balcony balustrade)", "m", 960, 245.00, {"din276": "338"}),
                ("330.06", "Winkelpuien aluminium (Shopfront glazing)", "m2", 350, 395.00, {"din276": "337"}),
                ("330.07", "Inkomdeuren en luifel (Entrance doors and canopy)", "pcs", 3, 7800.00, {"din276": "334"}),
                ("330.08", "Waterdichting balkons (Balcony waterproofing)", "m2", 1440, 38.00, {"din276": "335"}),
                ("330.09", "Kitvoegen buitenzijde (External sealant joints)", "m", 3200, 14.00, {"din276": "335"}),
                ("330.10", "Ventilatierooster nutsruimten (Service area louvres)", "m2", 480, 125.00, {"din276": "338"}),
                ("330.11", "Steenstrips sokkel (Brick slip to plinth)", "m2", 380, 85.00, {"din276": "335"}),
                ("330.12", "Buitentrap nooduitgang staal (External fire escape stair)", "pcs", 2, 18500.00, {"din276": "379"}),
            ],
        ),
        (
            "340",
            "340 - Binnenwanden en afwerking (Internal walls and finishes)",
            {"din276": "340"},
            [
                ("340.01", "Betonblok scheidingswand 140mm (Block partition)", "m2", 9600, 38.00, {"din276": "342"}),
                ("340.02", "Betonblok scheidingswand 90mm (Block partition thin)", "m2", 6400, 32.00, {"din276": "342"}),
                ("340.03", "Bepleistering en gladwerk (Plaster and skim)", "m2", 36000, 11.00, {"din276": "345"}),
                ("340.04", "Latexverf muren en plafonds (Emulsion paint)", "m2", 52000, 7.00, {"din276": "345"}),
                ("340.05", "Wandtegels badkamer en keuken (Wall tiles)", "m2", 4200, 58.00, {"din276": "345"}),
                ("340.06", "Binnendeuren met beslag (Internal doors)", "pcs", 384, 480.00, {"din276": "344"}),
                ("340.07", "Brandwerende deuren RF30 (Fire doors)", "pcs", 100, 820.00, {"din276": "344"}),
                ("340.08", "Parketvloer eik in appartementen (Oak parquet flooring)", "m2", 6800, 52.00, {"din276": "352"}),
                ("340.09", "Keramische vloertegel keuken en hal (Ceramic floor tile)", "m2", 3800, 45.00, {"din276": "352"}),
                ("340.10", "Keukenblok per appartement (Kitchen units per flat)", "unit", 96, 3800.00, {"din276": "371"}),
                ("340.11", "Inbouwkast per appartement (Built-in wardrobe per flat)", "unit", 96, 1250.00, {"din276": "371"}),
                ("340.12", "Sanitaire toestellen per appartement (Sanitaryware per flat)", "unit", 96, 2400.00, {"din276": "412"}),
                ("340.13", "Plint hout gelakt (Painted skirting)", "m", 7200, 11.00, {"din276": "352"}),
                ("340.14", "Leuning en handgreep trappenhuis (Stair handrail)", "m", 420, 195.00, {"din276": "379"}),
                ("340.15", "Brievenbussen en naamplaatjes (Letterboxes and nameplates)", "pcs", 2, 4200.00, {"din276": "374"}),
            ],
        ),
        (
            "350",
            "350 - Vloeren (Floors and structure)",
            {"din276": "350"},
            [
                ("350.01", "Betonvloer C35/45, 220mm (RC slab)", "m2", 11000, 108.00, {"din276": "351"}),
                ("350.02", "Wapening vloeren B500B (Reinforcement)", "t", 1100, 1380.00, {"din276": "351"}),
                ("350.03", "Bekisting vloeren (Formwork)", "m2", 22000, 34.00, {"din276": "351"}),
                ("350.04", "Betonkolommen C40/50 (RC columns)", "m3", 340, 375.00, {"din276": "331"}),
                ("350.05", "Betonwanden draagstructuur C35/45 (RC shear walls)", "m3", 960, 355.00, {"din276": "331"}),
                ("350.06", "Prefab betontrap (Precast stairs)", "pcs", 16, 5200.00, {"din276": "379"}),
                ("350.07", "Chape op isolatie (Screed on insulation)", "m2", 9600, 28.00, {"din276": "352"}),
                ("350.08", "Contactgeluidsisolatie 30mm (Impact insulation)", "m2", 8400, 14.00, {"din276": "352"}),
            ],
        ),
        (
            "360",
            "360 - Daken (Roofs)",
            {"din276": "360"},
            [
                ("360.01", "Dakisolatie PIR 200mm (Roof insulation)", "m2", 1600, 58.00, {"din276": "363"}),
                ("360.02", "Dakmembraan EPDM (Roof membrane)", "m2", 1600, 42.00, {"din276": "363"}),
                ("360.03", "Dakafvoer en noodoverlopen (Roof drainage)", "lsum", 1, 32000.00, {"din276": "362"}),
                ("360.04", "PV-installatie 50 kWp (PV array)", "lsum", 1, 82000.00, {"din276": "362"}),
            ],
        ),
        (
            "400",
            "400 - Technieken (Services)",
            {"din276": "400"},
            [
                ("400.01", "Warmtepomp collectief 120 kW (Communal heat pump)", "lsum", 1, 115000.00, {"din276": "421"}),
                ("400.02", "Vloerverwarming per appartement (Underfloor heating per flat)", "unit", 96, 3200.00, {"din276": "423"}),
                ("400.03", "Ventilatie D met WTW per woning (MVHR per flat)", "unit", 96, 2400.00, {"din276": "431"}),
                ("400.04", "Elektrische installatie per woning (Electrical per flat)", "unit", 96, 4800.00, {"din276": "444"}),
                ("400.05", "Gemeenschappelijke elektriciteit (Common area electrical)", "lsum", 1, 185000.00, {"din276": "444"}),
                ("400.06", "Sanitair per appartement (Plumbing per flat)", "unit", 96, 5800.00, {"din276": "412"}),
                ("400.07", "Branddetectie en alarm (Fire detection)", "m2", 12500, 13.00, {"din276": "454"}),
                ("400.08", "Liften 8 personen, 9 haltes (Passenger lifts)", "pcs", 2, 118000.00, {"din276": "461"}),
                ("400.09", "Bliksembeveiliging (Lightning protection)", "lsum", 1, 38000.00, {"din276": "446"}),
                ("400.10", "Parlofonie en video-intercom (Intercom and video entry)", "unit", 96, 380.00, {"din276": "453"}),
                ("400.11", "CCTV gemeenschappelijke ruimten (CCTV common areas)", "lsum", 1, 52000.00, {"din276": "452"}),
                ("400.12", "Toegangscontrole lobbys (Access control)", "pcs", 6, 3800.00, {"din276": "453"}),
                ("400.13", "EV-laadpunten parking (EV charging points)", "pcs", 12, 2400.00, {"din276": "442"}),
                ("400.14", "Zonneboiler collectief (Communal solar thermal)", "lsum", 1, 65000.00, {"din276": "421"}),
                ("400.15", "Regenwateropvang (Rainwater harvesting)", "lsum", 1, 42000.00, {"din276": "419"}),
                ("400.16", "Sprinklerinstallatie (Sprinkler)", "m2", 12500, 28.00, {"din276": "454"}),
            ],
        ),
        (
            "500",
            "500 - Buitenaanleg (External works)",
            {"din276": "500"},
            [
                ("500.01", "Verhardingen en bestrating (Hard landscaping)", "m2", 1800, 85.00, {"din276": "520"}),
                ("500.02", "Beplanting en groenzone (Soft landscaping)", "m2", 1400, 45.00, {"din276": "530"}),
                ("500.03", "Buitenriolering (External drainage)", "lsum", 1, 95000.00, {"din276": "541"}),
                ("500.04", "Buitenverlichting (External lighting)", "pcs", 22, 1850.00, {"din276": "550"}),
                ("500.05", "Fietsenstalling 96 plaatsen (Bicycle parking)", "pcs", 96, 250.00, {"din276": "560"}),
                ("500.06", "Omheining en poort (Boundary fence and gate)", "m", 180, 135.00, {"din276": "560"}),
                ("500.07", "Speelplaats kinderen (Playground)", "lsum", 1, 42000.00, {"din276": "530"}),
                ("500.08", "Vuilniscontainerberging (Refuse store)", "pcs", 2, 8500.00, {"din276": "560"}),
                ("500.09", "Brandblusleiding extern (External fire main)", "lsum", 1, 28000.00, {"din276": "541"}),
            ],
        ),
    ],
    markups=[
        ("Algemene bouwplaatskosten (Site overheads)", 9.0, "overhead", "direct_cost"),
        ("Algemene kosten (Head office overheads)", 5.0, "overhead", "direct_cost"),
        ("Winst en risico (Profit and risk)", 5.0, "profit", "direct_cost"),
        ("BTW/TVA 21%", 21.0, "tax", "cumulative"),
    ],
    total_months=22,
    tender_name="Hoofdaanneming - Appartementsgebouw Eilandje",
    tender_companies=[
        ("Mertens Bouw NV", "offerte@mertens-bouw.example", 0.99),
        ("Van Hoeck Aannemingen NV", "offerte@vanhoeck.example", 1.02),
        ("Willems en Zoon Bouwbedrijf", "offerte@willems-zoon.example", 1.04),
    ],
    project_metadata={
        "address": "Kattendijkdok Oostkaai 25, 2000 Antwerpen",
        "client": "Eilandje Vastgoed Ontwikkeling NV",
        "architect": "Architectenbureau De Moor",
        "structural_engineer": "Ingenieursbureau Hendrickx",
        "qs": "Meetbureau Van Acker BVBA",
        "gfa_m2": 12500,
        "units": 96,
        "storeys_above": 8,
        "storeys_below": 1,
        "parking_spaces": 110,
        "epb_target": "E30 (S28)",
    },
)
