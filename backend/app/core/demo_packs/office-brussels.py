# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: belgium-be - Kantoorgebouw Leopold, Brussels
# ---------------------------------------------------------------------------
# A Belgian meetstaat structured by BB/SfB elements, mapped to DIN 276 for
# the product's classification resolution. Prices are EUR excluding 21%
# BTW/TVA. Brussels sits on sand and clay, typical pad foundations.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="office-brussels",
    project_name="Kantoorgebouw Leopold - Brussels (Office Building, European Quarter)",
    project_description=(
        "Nieuwbouw kantoorgebouw in de Europese wijk van Brussel, 10 bouwlagen "
        "bovengronds en 2 kelderlagen met 80 parkeerplaatsen. BVO circa 15.000 m2. "
        "Betonnen draagstructuur met vlakke plaatvloeren. Gevelisolatie met "
        "drievoudig beglaasde raampartijen. EPB-peil E40 conform Brussels "
        "Hoofdstedelijk Gewest. New-build office in the European Quarter of "
        "Brussels, 10 storeys with 2 basement levels. GFA approx. 15,000 m2. "
        "RC frame. Priced at Brussels 2026 market levels in EUR excluding "
        "BTW/TVA."
    ),
    region="BE",
    classification_standard="din276",
    currency="EUR",
    locale="nl",
    address={
        "street": "Rue de la Loi 200",
        "city": "Brussels",
        "postcode": "1040",
        "country": "Belgium",
        "lat": 50.8427,
        "lng": 4.3826,
    },
    validation_rule_sets=["din276", "boq_quality"],
    boq_name="Meetstaat - Kantoorgebouw Leopold (Bill of Quantities)",
    boq_description=(
        "Elementengewijze meetstaat voor een kantoorgebouw met 10 bouwlagen "
        "en 2 kelderlagen in de Europese wijk. Prijzen op Brussels 2026 niveau "
        "in EUR exclusief BTW. Element-based bill for a 10-storey office "
        "building in the European Quarter, priced at Brussels 2026 levels."
    ),
    boq_metadata={
        "standard": "BB/SfB / DIN 276",
        "phase": "Aanbestedingsdossier (Tender)",
        "base_date": "2026-Q1",
        "price_level": "Brussels 2026 (EUR, excl BTW)",
    },
    sections=[
        (
            "310",
            "310 - Grondwerken en fundering (Earthworks and foundations)",
            {"din276": "310"},
            [
                ("310.01", "Grondonderzoek en sondering (Soil investigation and CPT)", "lsum", 1, 65000.00, {"din276": "311"}),
                ("310.02", "Uitgraving bouwput (Bulk excavation)", "m3", 12000, 14.00, {"din276": "313"}),
                ("310.03", "Grondafvoer en storten (Disposal off site)", "m3", 10000, 22.00, {"din276": "313"}),
                ("310.04", "Berlijnse wand (Berlin wall shoring)", "m2", 2400, 195.00, {"din276": "312"}),
                ("310.05", "Schroefpalen 500mm (CFA piles 500mm)", "m", 2800, 145.00, {"din276": "322"}),
                ("310.06", "Funderingsbalken en poeren C30/37 (Pile caps and beams)", "m3", 980, 275.00, {"din276": "324"}),
                ("310.07", "Funderingsplaat C30/37 waterdicht (Raft slab watertight)", "m3", 850, 285.00, {"din276": "324"}),
                ("310.08", "Wapening funderingen B500B (Reinforcement)", "t", 195, 1380.00, {"din276": "324"}),
                ("310.09", "Waterdichting kelderconstructie (Basement waterproofing)", "m2", 2800, 48.00, {"din276": "325"}),
            ],
        ),
        (
            "330",
            "330 - Buitenwanden (External walls)",
            {"din276": "330"},
            [
                ("330.01", "Betonskelet kolommen C45/55 (RC columns)", "m3", 520, 395.00, {"din276": "331"}),
                ("330.02", "Betonskelet kernwanden C40/50 (RC core walls)", "m3", 1100, 375.00, {"din276": "331"}),
                ("330.03", "Bekleding buitenwanden steenstrips (Brick slip cladding)", "m2", 3200, 125.00, {"din276": "335"}),
                ("330.04", "Unitized gevelsysteem driedubbel glas (Curtain wall triple glazed)", "m2", 5800, 650.00, {"din276": "337"}),
                ("330.05", "Aluminium inkomdeur automatisch (Entrance doors automatic)", "pcs", 4, 8500.00, {"din276": "334"}),
                ("330.06", "Zonwering buitengelegen screens (External sun screens)", "m2", 3200, 145.00, {"din276": "338"}),
            ],
        ),
        (
            "340",
            "340 - Binnenwanden (Internal walls)",
            {"din276": "340"},
            [
                ("340.01", "Metalstud wand dubbel beplaat 100mm (Metal stud partition)", "m2", 7200, 55.00, {"din276": "342"}),
                ("340.02", "Brandwerende wand 1u/2u (Fire rated partition)", "m2", 1800, 125.00, {"din276": "342"}),
                ("340.03", "Glazen scheidingswand kantoren (Glazed office partition)", "m2", 2800, 310.00, {"din276": "342"}),
                ("340.04", "Binnendeuren hout met beslag (Internal timber doors)", "pcs", 200, 720.00, {"din276": "344"}),
                ("340.05", "Branddeuren RF30/RF60 (Fire doors)", "pcs", 72, 1180.00, {"din276": "344"}),
                ("340.06", "Wandtegels sanitair (Wall tiles to WCs)", "m2", 1400, 68.00, {"din276": "345"}),
                ("340.07", "Latexverf binnenwanden 2 lagen (Emulsion paint)", "m2", 18000, 8.00, {"din276": "345"}),
                ("340.08", "Sanitaire cabines HPL (Toilet cubicles)", "pcs", 40, 920.00, {"din276": "346"}),
            ],
        ),
        (
            "350",
            "350 - Vloeren en plafonds (Floors and ceilings)",
            {"din276": "350"},
            [
                ("350.01", "Betonvloer vlakke plaat C35/45, 280mm (RC flat slab)", "m2", 13500, 118.00, {"din276": "351"}),
                ("350.02", "Wapening vloeren B500B (Floor reinforcement)", "t", 1400, 1420.00, {"din276": "351"}),
                ("350.03", "Bekisting vloeren en kolommen (Formwork)", "m2", 28000, 36.00, {"din276": "351"}),
                ("350.04", "Verhoogde vloer 150mm (Raised access floor)", "m2", 11000, 78.00, {"din276": "352"}),
                ("350.05", "Tapijttegel kantoren (Carpet tile to offices)", "m2", 9500, 45.00, {"din276": "352"}),
                ("350.06", "Keramische tegel lobby (Porcelain tile to lobby)", "m2", 1200, 125.00, {"din276": "352"}),
                ("350.07", "Systeemplafond metalen tegels (Suspended metal ceiling)", "m2", 11000, 62.00, {"din276": "353"}),
                ("350.08", "Gipskarton soffiet dienstruimten (Plasterboard bulkhead)", "m2", 2800, 48.00, {"din276": "353"}),
            ],
        ),
        (
            "360",
            "360 - Daken (Roofs)",
            {"din276": "360"},
            [
                ("360.01", "Dakisolatie PIR 180mm (Roof insulation)", "m2", 1500, 58.00, {"din276": "363"}),
                ("360.02", "Eenlaags dakmembraan EPDM (Single ply roof membrane)", "m2", 1500, 45.00, {"din276": "363"}),
                ("360.03", "Extensief groendak (Extensive green roof)", "m2", 600, 72.00, {"din276": "363"}),
                ("360.04", "Dakrandafwerking en noodafvoer (Roof edge and drainage)", "lsum", 1, 38000.00, {"din276": "362"}),
                ("360.05", "PV-installatie 60 kWp (PV array)", "lsum", 1, 95000.00, {"din276": "362"}),
            ],
        ),
        (
            "410",
            "410 - Sanitair en waterafvoer (Plumbing and drainage)",
            {"din276": "410"},
            [
                ("410.01", "Riolering en grondleidingen (Drainage and below-ground pipes)", "m", 1200, 48.00, {"din276": "411"}),
                ("410.02", "Sanitaire toestellen compleet (Sanitaryware complete)", "pcs", 120, 850.00, {"din276": "412"}),
                ("410.03", "Watervoorziening leidingen (Water supply pipework)", "m", 2400, 35.00, {"din276": "412"}),
                ("410.04", "Leidingisolatie (Pipe insulation)", "m", 2400, 12.00, {"din276": "419"}),
            ],
        ),
        (
            "420",
            "420 - Verwarming en koeling (Heating and cooling)",
            {"din276": "420"},
            [
                ("420.01", "Warmtepomp lucht-water 180 kW (Air source heat pump)", "lsum", 1, 145000.00, {"din276": "421"}),
                ("420.02", "Vloerverwarming en koeling (Underfloor heating/cooling)", "m2", 11000, 42.00, {"din276": "423"}),
                ("420.03", "Luchtgroepen met WTW (AHU with heat recovery)", "pcs", 4, 62000.00, {"din276": "431"}),
                ("420.04", "Kanaalwerk verzinkt (Ductwork galvanised)", "m2", 4800, 65.00, {"din276": "431"}),
            ],
        ),
        (
            "440",
            "440 - Elektriciteit (Electrical)",
            {"din276": "440"},
            [
                ("440.01", "Elektrische hoofdverdeling (Main switchboard)", "pcs", 1, 65000.00, {"din276": "443"}),
                ("440.02", "Onderverdeling per verdieping (Floor distribution boards)", "pcs", 12, 4800.00, {"din276": "443"}),
                ("440.03", "Noodstroomgroep 400 kVA (Standby generator)", "pcs", 1, 145000.00, {"din276": "442"}),
                ("440.04", "LED verlichting DALI (LED lighting)", "m2", 13500, 52.00, {"din276": "445"}),
                ("440.05", "Branddetectie en alarm (Fire detection and alarm)", "m2", 15000, 14.00, {"din276": "454"}),
                ("440.06", "Sprinklerinstallatie (Sprinkler system)", "m2", 15000, 32.00, {"din276": "454"}),
                ("440.07", "Liften personen 1600 kg, 12 haltes (Passenger lifts)", "pcs", 3, 155000.00, {"din276": "461"}),
                ("440.08", "Goederenlift 2000 kg (Goods lift)", "pcs", 1, 175000.00, {"din276": "461"}),
                ("440.09", "Gestructureerde bekabeling Cat 6A (Structured cabling)", "m2", 11000, 25.00, {"din276": "456"}),
                ("440.10", "GBS/BMS systeem (Building management system)", "lsum", 1, 195000.00, {"din276": "481"}),
                ("440.11", "Toegangscontrole en CCTV (Access control and CCTV)", "lsum", 1, 145000.00, {"din276": "453"}),
                ("440.12", "Inbraakbeveiliging (Intruder alarm)", "lsum", 1, 48000.00, {"din276": "452"}),
                ("440.13", "EV-laadpunten 11 kW (EV charging 11 kW)", "pcs", 8, 2400.00, {"din276": "442"}),
                ("440.14", "Indienststelling en testen (Commissioning and testing)", "lsum", 1, 95000.00, {"din276": "485"}),
                ("440.15", "Regenwater opvang en hergebruik (Rainwater harvesting)", "lsum", 1, 42000.00, {"din276": "419"}),
                ("440.16", "Noodverlichting centraal (Emergency lighting)", "lsum", 1, 58000.00, {"din276": "445"}),
                ("440.17", "Rookmelders parkeergarage (Smoke detection car park)", "m2", 3200, 12.00, {"din276": "454"}),
            ],
        ),
        (
            "500",
            "500 - Buitenaanleg (External works)",
            {"din276": "500"},
            [
                ("500.01", "Verhardingen en bestrating (Hard landscaping)", "m2", 1600, 95.00, {"din276": "520"}),
                ("500.02", "Beplanting en groenvoorziening (Soft landscaping)", "m2", 1200, 52.00, {"din276": "530"}),
                ("500.03", "Buitenriolering en aansluitingen (External drainage)", "lsum", 1, 125000.00, {"din276": "541"}),
                ("500.04", "Buitenverlichting (External lighting)", "pcs", 24, 2200.00, {"din276": "550"}),
                ("500.05", "Fietsenstalling 60 plaatsen (Bicycle parking)", "pcs", 60, 280.00, {"din276": "560"}),
            ],
        ),
    ],
    markups=[
        ("Algemene bouwplaatskosten (Site overheads)", 10.0, "overhead", "direct_cost"),
        ("Algemene kosten (Head office overheads)", 6.0, "overhead", "direct_cost"),
        ("Winst en risico (Profit and risk)", 5.0, "profit", "direct_cost"),
        ("BTW/TVA 21%", 21.0, "tax", "cumulative"),
    ],
    total_months=26,
    tender_name="Hoofdaanneming - Kantoorgebouw Leopold",
    tender_companies=[
        ("Vanderstraeten Bouw NV", "offerte@vanderstraeten-bouw.example", 0.98),
        ("De Ridder Entreprises SA", "soumission@deridder-ent.example", 1.03),
        ("Claessens Algemene Aanneming NV", "offerte@claessens-aa.example", 1.01),
    ],
    project_metadata={
        "address": "Rue de la Loi 200, 1040 Brussels",
        "client": "Quartier Leopold Vastgoed NV",
        "architect": "Architectenbureau Janssens en Partners",
        "structural_engineer": "Bureau Peeters Ingenieursbureau",
        "qs": "Meetbureau De Smedt BVBA",
        "gfa_m2": 15000,
        "storeys_above": 10,
        "storeys_below": 2,
        "parking_spaces": 80,
        "epb_target": "E40",
    },
    tender_packages=[
        (
            "Ruwbouw (Structure)",
            "Fundering, betonskelet, metselwerk",
            "evaluating",
            [
                ("Vanderstraeten Bouw NV", "offerte@vanderstraeten-bouw.example", 0.98),
                ("De Ridder Entreprises SA", "soumission@deridder-ent.example", 1.03),
                ("Claessens Algemene Aanneming NV", "offerte@claessens-aa.example", 1.01),
            ],
        ),
        (
            "Technieken (M&E Services)",
            "HVAC, elektriciteit, sanitair, liften, brandveiligheid",
            "issued",
            [
                ("Vermeersch Technics NV", "offerte@vermeersch-tech.example", 0.99),
                ("Dumont Installations SA", "soumission@dumont-inst.example", 1.04),
            ],
        ),
    ],
)
