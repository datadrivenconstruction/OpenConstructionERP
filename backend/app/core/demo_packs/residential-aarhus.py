# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Demo pack: Boligprojekt Aarhus OE - Aarhus (Residential, Aarhus)
# ---------------------------------------------------------------------------
# Residential project in Aarhus OE. Structured by SfB elements, specified to
# V&S, contracted under AB 18. Rates are Aarhus 2026 market levels in DKK
# excluding moms.
#
# Aarhus OE is a new waterfront district on reclaimed harbour land, similar
# in character to Copenhagen's Nordhavn. Ground is fill over clay, requiring
# driven piles. The project is a mid-rise apartment complex typical of
# current Danish residential development: compact, energy-efficient, with
# generous shared facilities and cycle infrastructure.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-aarhus",
    project_name="Boligprojekt Aarhus OE (Residential Project, Aarhus OE)",
    project_description=(
        "Nybyggeri af boligprojekt i Aarhus OE. Tre bygningskroppe med i alt "
        "80 boliger, 5 etager plus kae lder. Bruttoetageareal cirka 10 200 m2. "
        "Betonstruktur med prefabrikerede vae gge og dae kelementer. "
        "Fjernvarme, balanceret ventilation med varmegenvinding, 100 kWp "
        "solceller. Byggeomkostninger cirka 265 MDKK eksklusiv moms. "
        "New-build residential project in Aarhus OE. Three buildings with "
        "80 apartments, 5 storeys plus basement. GFA approx. 10,200 m2. "
        "Concrete frame with precast walls and floor elements. District "
        "heating, balanced ventilation with heat recovery, 100 kWp PV. "
        "Construction cost approx. DKK 265M excluding VAT."
    ),
    region="DK",
    classification_standard="sfb_ccs",
    currency="DKK",
    locale="da",
    address={
        "street": "Bernhardt Jensens Boulevard 22",
        "city": "Aarhus",
        "postcode": "8000",
        "country": "Denmark",
        "lat": 56.1530,
        "lng": 10.2270,
    },
    validation_rule_sets=["boq_quality", "project_completeness"],
    project_code="AAR-OE-2026-01",
    boq_name="Byggebudget SfB - prisniveau Aarhus 2026 (Cost Estimate, SfB classification)",
    boq_description=(
        "Byggebudget opstillet efter SfB-bygningsdelssystemet med enhedspriser. "
        "Prisniveau Aarhus foerste kvartal 2026, eksklusiv moms. "
        "Cost estimate structured by SfB building elements. "
        "Aarhus Q1 2026 price level, excluding VAT."
    ),
    boq_metadata={
        "standard": "SfB-bygningsdelssystemet",
        "phase": "Hovedprojekt - byggebudget (Detailed design estimate)",
        "base_date": "2026-Q1",
        "price_level": "Aarhus 2026, eksklusiv moms",
    },
    sections=[
        # -- 01 Jord og fundering (Site and foundations) --
        (
            "01",
            "01 Jord og fundering (Site and foundations)",
            {"sfb": "1", "din276": "310"},
            [
                ("01.1", "Rydning og forberedelse af byggeplads (Site clearance and preparation)", "m2", 4200, 115.00, {"sfb": "10", "din276": "212"}),
                ("01.2", "Udgravning i opfyld og bortkoesel (Excavation in fill and disposal)", "m3", 5500, 145.00, {"sfb": "12", "din276": "311"}),
                ("01.3", "Rammede betonpae le 250x250 mm (Driven concrete piles 250x250 mm)", "m", 5200, 425.00, {"sfb": "13", "din276": "323"}),
                ("01.4", "Pae lehoveder og fundamentsbjaelker (Pile caps and ground beams)", "m3", 380, 5850.00, {"sfb": "13", "din276": "322"}),
                ("01.5", "Bundplade betong 200 mm paa isolering (Ground slab 200 mm on insulation)", "m2", 3400, 1150.00, {"sfb": "14", "din276": "324"}),
                ("01.6", "Kae ldervae gge prefab beton 200 mm (Basement walls, precast concrete 200 mm)", "m2", 2400, 1950.00, {"sfb": "14", "din276": "331"}),
                ("01.7", "Draenering og regnvandshaaandtering (Drainage and stormwater management)", "m", 780, 785.00, {"sfb": "15", "din276": "313"}),
                ("01.8", "Midlertidig spunsning og grundvandssaenkning (Temporary sheet piling and dewatering)", "post", 1, 1250000.00, {"sfb": "11", "din276": "312"}),
                ("01.9", "Midlertidig adgangsvej og byggepladsindhegning (Temporary access road and site fencing)", "m2", 1100, 195.00, {"sfb": "10", "din276": "220"}),
                ("01.10", "Proevebelastning af pae le (Pile load testing)", "stk", 6, 38000.00, {"sfb": "13", "din276": "329"}),
                ("01.11", "Udvendige kloakledninger og regnvandsbassin (External drainage and stormwater basin)", "m", 520, 1050.00, {"sfb": "15", "din276": "550"}),
            ],
        ),
        # -- 02 Baerende konstruktion (Primary structure) --
        (
            "02",
            "02 Baerende konstruktion (Primary structure)",
            {"sfb": "2", "din276": "300"},
            [
                ("02.1", "Prefab betonvae gge baerende 200 mm (Precast loadbearing concrete walls 200 mm)", "m2", 6200, 1550.00, {"sfb": "21", "din276": "341"}),
                ("02.2", "Hauldaek HD 200 mm med konstruktiv overstoeybing (Hollow-core floor slabs HD 200 mm with topping)", "m2", 9200, 950.00, {"sfb": "22", "din276": "351"}),
                ("02.3", "Pladstoeybt beton trapperum og elevatorskaete (In-situ concrete, stairwells and lift shafts)", "m3", 380, 8500.00, {"sfb": "21", "din276": "341"}),
                ("02.4", "Armering B500C (Reinforcement B500C)", "ton", 195, 13500.00, {"sfb": "21", "din276": "300"}),
                ("02.5", "Prefab betontrapper (Precast concrete stairs)", "stk", 30, 32000.00, {"sfb": "23", "din276": "351"}),
                ("02.6", "Altaner prefab beton med raekvaerk (Precast concrete balconies with railings)", "stk", 160, 36000.00, {"sfb": "24", "din276": "351"}),
                ("02.7", "Pladstoeybt beton, diverse kompletteringer (In-situ concrete, miscellaneous)", "m3", 165, 7800.00, {"sfb": "21", "din276": "300"}),
                ("02.8", "Staalindstoeybningsgods og befaestigelser (Cast-in items and fixings)", "ton", 12, 24500.00, {"sfb": "21", "din276": "341"}),
                ("02.9", "Daekpaastoeyb og komplettering ved skakte (Floor topping at risers)", "m2", 620, 1450.00, {"sfb": "22", "din276": "351"}),
            ],
        ),
        # -- 03 Ydervae gge og tag (External walls and roof) --
        (
            "03",
            "03 Ydervae gge og tag (External walls and roof)",
            {"sfb": "3", "din276": "330"},
            [
                ("03.1", "Ydervae gge tegl paa isoleret skalvae g U 0,15 (External walls, brick on insulated cavity wall U 0.15)", "m2", 4800, 2150.00, {"sfb": "31", "din276": "335"}),
                ("03.2", "Vinduer aluminium/trae, trelagsglas U 0,8 (Windows, aluminium/timber, triple glazing U 0.8)", "m2", 1650, 4250.00, {"sfb": "32", "din276": "334"}),
                ("03.3", "Indgangsdoere og doertelefon (Entrance doors and intercom)", "stk", 6, 65000.00, {"sfb": "32", "din276": "344"}),
                ("03.4", "Altandoere, trelagsglas med lav tae rskel (Balcony doors, triple-glazed, low threshold)", "stk", 160, 14500.00, {"sfb": "32", "din276": "334"}),
                ("03.5", "Tagtae kning tolag tagpap, isolering U 0,09 (Roof covering, two-layer bituminous, insulation U 0.09)", "m2", 3400, 985.00, {"sfb": "36", "din276": "363"}),
                ("03.6", "Tagafvanding, nedloeb og broenede (Roof drainage, downpipes and gullies)", "m", 420, 485.00, {"sfb": "36", "din276": "364"}),
                ("03.7", "Tagraekvaerker og faldsikring (Roof railings and fall arrest)", "m", 220, 2350.00, {"sfb": "36", "din276": "369"}),
                ("03.8", "Sokkelisolering og sokkelbeklae dning (Plinth insulation and cladding)", "m", 380, 1350.00, {"sfb": "31", "din276": "327"}),
                ("03.9", "Facadefuger og fugemasser (Facade joints and sealants)", "m", 1400, 155.00, {"sfb": "31", "din276": "335"}),
                ("03.10", "Tagtilbehoer, tagstiger og sneefang (Roof accessories, ladders and snow guards)", "m", 260, 465.00, {"sfb": "36", "din276": "369"}),
                ("03.11", "Ventilerede facadepartier ved parkering og teknikrum (Ventilated facade zones at parking and plant rooms)", "m2", 380, 1450.00, {"sfb": "31", "din276": "335"}),
            ],
        ),
        # -- 04 Indervae gge og aptering (Internal walls and fit-out) --
        (
            "04",
            "04 Indervae gge og aptering (Internal walls and fit-out)",
            {"sfb": "4", "din276": "340"},
            [
                ("04.1", "Boligskillende vae gge 250 mm, lydklasse B (Party walls 250 mm, sound class B)", "m2", 3200, 1250.00, {"sfb": "41", "din276": "342"}),
                ("04.2", "Indervae gge boliger, gips paa staalskinne (Apartment partitions, plasterboard on studs)", "m2", 6800, 585.00, {"sfb": "41", "din276": "342"}),
                ("04.3", "Inderdoere og karme, inkl. brand EI 30 (Door sets including EI 30 fire doors)", "stk", 520, 6850.00, {"sfb": "42", "din276": "344"}),
                ("04.4", "Gulvbelae gning traeagulv, klinker og vinyl (Floor finishes, wood, ceramic and vinyl)", "m2", 7600, 485.00, {"sfb": "43", "din276": "353"}),
                ("04.5", "Nedhae ngte lofter vaadrum og fae llesarealer (Suspended ceilings, wet rooms and common areas)", "m2", 2600, 385.00, {"sfb": "44", "din276": "354"}),
                ("04.6", "Overfladebehandling vae gge og lofter (Wall and ceiling finishes)", "m2", 20000, 145.00, {"sfb": "45", "din276": "345"}),
                ("04.7", "Koekken komplet med hvidevarer og bordplader (Kitchens with appliances and worktops)", "stk", 80, 85000.00, {"sfb": "46", "din276": "381"}),
                ("04.8", "Badevaerelse komplet fliser, sanitet og armaturer (Bathrooms with tiles, sanitary ware and fittings)", "stk", 104, 78000.00, {"sfb": "46", "din276": "381"}),
                ("04.9", "Trapperum overflader, raekvaerker og belysning (Stairwell finishes, railings and lighting)", "stk", 6, 235000.00, {"sfb": "47", "din276": "345"}),
                ("04.10", "Vaskeri komplet indretning (Laundry room complete fit-out)", "stk", 3, 145000.00, {"sfb": "46", "din276": "381"}),
                ("04.11", "Pulterrum inkl. doere og belysning (Storage rooms with doors and lighting)", "stk", 80, 10500.00, {"sfb": "46", "din276": "381"}),
                ("04.12", "Lydisolering boligskillende konstruktioner (Acoustic insulation to party elements)", "m2", 2000, 235.00, {"sfb": "41", "din276": "342"}),
                ("04.13", "Vaadrumsmaatter og taetning (Wet room membranes and tanking)", "m2", 1200, 385.00, {"sfb": "43", "din276": "353"}),
            ],
        ),
        # -- 05 VVS-installationer (Mechanical services) --
        (
            "05",
            "05 VVS-installationer (Mechanical services)",
            {"sfb": "5", "din276": "400"},
            [
                ("05.1", "Fjernvarmeunit (District heating substation)", "stk", 3, 385000.00, {"sfb": "51", "din276": "421"}),
                ("05.2", "Varmeledninger og radiatorer (Heating pipework and radiators)", "bolig", 80, 28500.00, {"sfb": "51", "din276": "422"}),
                ("05.3", "Balanceret ventilation med varmegenvinding 80% (Balanced ventilation with 80% heat recovery)", "stk", 3, 525000.00, {"sfb": "53", "din276": "432"}),
                ("05.4", "Ventilationskanaler og armaturer (Ductwork and terminals)", "m2", 10200, 325.00, {"sfb": "53", "din276": "431"}),
                ("05.5", "Brugsvand koldt og varmt, stigstrenge (Potable water risers, hot and cold)", "bolig", 80, 22500.00, {"sfb": "54", "din276": "412"}),
                ("05.6", "Spildevand og regnvand, stigstrenge og stikledninger (Drainage risers and connections)", "bolig", 80, 15500.00, {"sfb": "55", "din276": "411"}),
                ("05.7", "Gulvvarme badevae relse og entree (Underfloor heating, bathrooms and entrances)", "m2", 580, 485.00, {"sfb": "51", "din276": "422"}),
                ("05.8", "Varmtvandsbeholdere med varmepumpe (Hot water heaters with heat pump)", "stk", 3, 215000.00, {"sfb": "51", "din276": "421"}),
                ("05.9", "Brandspjaeld og gennemfoeringer (Fire dampers and penetrations)", "stk", 320, 1650.00, {"sfb": "53", "din276": "431"}),
                ("05.10", "CTS-anlae g, reguleringsteknik og indregulering (BMS, controls and balancing)", "post", 1, 685000.00, {"sfb": "57", "din276": "480"}),
                ("05.11", "Koekkenventilation og emhaetter (Kitchen ventilation and hoods)", "stk", 80, 6850.00, {"sfb": "53", "din276": "431"}),
            ],
        ),
        # -- 06 El-installationer (Electrical services) --
        (
            "06",
            "06 El-installationer (Electrical services)",
            {"sfb": "6", "din276": "440"},
            [
                ("06.1", "Hovedtavle og forsyning fra net (Main distribution and supply)", "post", 1, 1050000.00, {"sfb": "61", "din276": "441"}),
                ("06.2", "Elinstallation per bolig inkl. gruppetavle (Electrical per apartment with consumer unit)", "bolig", 80, 72000.00, {"sfb": "62", "din276": "444"}),
                ("06.3", "Fae llesbelysning trapperum, parkering og udvendigt (Common lighting, stairs, parking and external)", "post", 1, 1150000.00, {"sfb": "63", "din276": "445"}),
                ("06.4", "Brandalarmanlae g og flugtvejsskiltning (Fire detection and exit signage)", "m2", 10200, 155.00, {"sfb": "65", "din276": "456"}),
                ("06.5", "Adgangskontrol og doertelefon (Access control and intercom)", "post", 1, 785000.00, {"sfb": "65", "din276": "456"}),
                ("06.6", "Solcelleanlaeg tag 100 kWp (Rooftop PV, 100 kWp)", "kWp", 100, 6250.00, {"sfb": "61", "din276": "442"}),
                ("06.7", "Elevatorer 3 stk personelevator (Passenger lifts, 3 units)", "stk", 3, 885000.00, {"sfb": "66", "din276": "461"}),
                ("06.8", "Elbilladestandere parkering 40 stk (EV chargers, 40 units)", "stk", 40, 22500.00, {"sfb": "62", "din276": "444"}),
                ("06.9", "Fiber- og brebaaandsinfrastruktur til boliger (Fibre broadband to apartments)", "bolig", 80, 6850.00, {"sfb": "64", "din276": "451"}),
                ("06.10", "Noedbelysning og flugtvejsskiltning (Emergency lighting and exit signage)", "post", 1, 385000.00, {"sfb": "63", "din276": "446"}),
                ("06.11", "Jordfejtbeskyttelse og lynafledning (Earth fault and lightning protection)", "post", 1, 285000.00, {"sfb": "61", "din276": "446"}),
            ],
        ),
        # -- 07 Terrae n og udearealer (External works) --
        (
            "07",
            "07 Terrae n og udearealer (External works)",
            {"sfb": "7", "din276": "500"},
            [
                ("07.1", "Gaardrum, belae gning og beplantning (Courtyard paving and planting)", "m2", 2800, 885.00, {"sfb": "73", "din276": "530"}),
                ("07.2", "Legeplads iht. DS/EN 1176 (Playground to DS/EN 1176)", "post", 1, 685000.00, {"sfb": "73", "din276": "570"}),
                ("07.3", "Affaldshaaandtering, rum og sortering (Waste management and sorting)", "post", 1, 625000.00, {"sfb": "74", "din276": "382"}),
                ("07.4", "Cykelskure og cykelstativer 160 pladser (Cycle shelters and racks, 160 spaces)", "stk", 160, 3850.00, {"sfb": "72", "din276": "382"}),
                ("07.5", "Udvendige ledninger, stikledninger og udebelysning (External services and lighting)", "post", 1, 1850000.00, {"sfb": "74", "din276": "550"}),
                ("07.6", "Terrae ntilpasning og stoettemure (Terrain adaptation and retaining walls)", "m", 120, 5850.00, {"sfb": "73", "din276": "539"}),
                ("07.7", "Parkeringsrampe og sikkerhedsudstyr (Parking ramp and safety equipment)", "post", 1, 385000.00, {"sfb": "72", "din276": "382"}),
                ("07.8", "Miljooestation og affaldssortering (Recycling station and waste sorting)", "post", 1, 325000.00, {"sfb": "74", "din276": "382"}),
                ("07.9", "Hegn og laager (Fencing and gates)", "m", 240, 985.00, {"sfb": "73", "din276": "530"}),
                ("07.10", "Regnvandsbassin og forsinkelse (Stormwater attenuation)", "post", 1, 385000.00, {"sfb": "74", "din276": "550"}),
                ("07.11", "Fae lles opbevaringsrum (Common storage rooms)", "stk", 3, 65000.00, {"sfb": "71", "din276": "381"}),
                ("07.12", "Udendoers opholdsplads med grillomraade (Outdoor amenity with BBQ area)", "post", 1, 195000.00, {"sfb": "73", "din276": "570"}),
                ("07.13", "Bygningsrengoering sluttrengoering (Final clean)", "m2", 10200, 28.00, {"sfb": "79", "din276": "381"}),
                ("07.14", "Saombygget-dokumentation (As-built drawings)", "post", 1, 285000.00, {"sfb": "79", "din276": "381"}),
            ],
        ),
    ],
    markups=[
        ("Byggepladsomkostninger (Site overheads and preliminaries 10%)", 10.0, "overhead", "direct_cost"),
        ("Faellesomkostninger (Head-office overheads 5%)", 5.0, "overhead", "cumulative"),
        ("Forsikring og garanti (Insurance and bond 0,5%)", 0.5, "insurance", "cumulative"),
        ("Avance og risiko (Profit and risk 4,5%)", 4.5, "profit", "cumulative"),
        ("Moms 25 procent (Danish VAT at 25 percent)", 25.0, "tax", "cumulative"),
    ],
    total_months=22,
    tender_name="Hovedentreprise boliger (Main contract, residential)",
    tender_companies=[
        ("Aarhus OE Bolig A/S", "tilbud@aarhusbolig.example", 0.97),
        ("Jysk Byggegruppe", "udbud@jyskbyg.example", 1.03),
        ("OEstjysk Entreprenoer A/S", "tender@oestjysk-ent.example", 1.01),
    ],
    schedule_activities=[
        ("Etablering og byggeplads (Site setup and enabling)", "2026-03-02", "2026-05-29"),
        ("Pae leramning og udgravning (Piling and excavation)", "2026-04-15", "2026-08-31"),
        ("Fundament og kae lder (Foundations and basement)", "2026-07-01", "2026-11-30"),
        ("Baerende konstruktion bygning 1-2 (Frame, buildings 1-2)", "2026-10-01", "2027-03-31"),
        ("Baerende konstruktion bygning 3 (Frame, building 3)", "2027-01-03", "2027-05-31"),
        ("Facade og tag (Facade and roof)", "2027-03-01", "2027-09-30"),
        ("VVS og el (M&E installation)", "2027-05-01", "2027-10-31"),
        ("Aptering og overflader (Fit-out and finishes)", "2027-07-01", "2027-12-31"),
        ("Terrae n og udearealer (External works)", "2027-10-01", "2028-01-31"),
        ("Ibrugtagning og aflevering (Commissioning and handover)", "2027-12-01", "2028-01-31"),
    ],
    project_metadata={
        "address": "Bernhardt Jensens Boulevard 22, 8000 Aarhus, Danmark",
        "client": "Aarhus OE Boligudvikling A/S (Aarhus OE Housing Development)",
        "architect": "Arkitektkontoret Bugten (Bugten Architects)",
        "structural_engineer": "Ingenioerhuset Jylland A/S (Jutland Structural Engineers)",
        "services_engineer": "VVS-Raadgivning Aarhus A/S (Aarhus M&E Consultants)",
        "gfa_m2": 10200,
        "storeys": "5 etager plus kae lder (5 storeys plus basement)",
        "apartments": 80,
        "contract": "AB 18, hovedentreprise med fast pris (General contracting under AB 18, lump sum)",
    },
    budget_boq_name="Byggebudget boligprojekt Aarhus OE (Residential Project Cost Estimate)",
    planned_budget=265000000.0,
    actual_spend_ratio=0.41,
    spi_override=0.96,
    cpi_override=1.02,
)
