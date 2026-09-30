# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Demo pack: Boligprosjekt Sandviken - Bergen (Residential, Bergen)
# ---------------------------------------------------------------------------
# Residential project in Sandviken, Bergen. Structured by NS 3451 building
# element codes, specified to NS 3420, contracted under NS 8405. Rates are
# Bergen 2026 market levels in NOK excluding MVA.
#
# Bergen receives over 2,000 mm of precipitation per year, so detailing
# against wind-driven rain and damp is critical. The terrain is steep, and
# sites often require rock blasting and retaining walls. The foundation
# section reflects this.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-bergen",
    project_name="Boligprosjekt Sandviken - Bergen (Residential Project, Bergen Sandviken)",
    project_description=(
        "Nybygg av boligprosjekt i Sandviken, Bergen. Tre bygningskropper med "
        "totalt 72 leiligheter, 5 etasjer pluss parkeringskjeller. Bruttoareal "
        "cirka 9 800 m2. Betongkonstruksjon med prefabrikkerte vegger og dekker. "
        "Fjaernvarme, balansert ventilasjon med varmegjenvinner, 90 kWp solceller. "
        "Byggekostnad cirka 345 MNOK eksklusive MVA. "
        "New-build residential project in Sandviken, Bergen. Three buildings with "
        "72 apartments, 5 storeys plus parking basement. GFA approx. 9,800 m2. "
        "Concrete frame with precast walls and floor slabs. District heating, "
        "balanced ventilation with heat recovery, 90 kWp PV. "
        "Construction cost approx. NOK 345M excluding VAT."
    ),
    region="NO",
    classification_standard="ns3451",
    currency="NOK",
    locale="no",
    address={
        "street": "Sandviksboder 42",
        "city": "Bergen",
        "postcode": "5035",
        "country": "Norway",
        "lat": 60.4060,
        "lng": 5.3275,
    },
    validation_rule_sets=["boq_quality", "project_completeness"],
    project_code="BER-SDV-2026-01",
    boq_name="Kalkyle NS 3451 - prisnivaa Bergen 2026 (Cost Estimate, NS 3451 classification)",
    boq_description=(
        "Kalkyle oppstilt etter NS 3451 bygningsdelstabell med enhetspriser per "
        "bygningsdel. Prisnivaa Bergen foerste kvartal 2026, eksklusive MVA. "
        "Cost estimate structured by NS 3451 building element table. "
        "Bergen Q1 2026 price level, excluding VAT."
    ),
    boq_metadata={
        "standard": "NS 3451 Bygningsdelstabell / NS 3453 Kostnadsoppstilling",
        "phase": "Detaljprosjekt - kalkyle (Detailed design estimate)",
        "base_date": "2026-Q1",
        "price_level": "Bergen 2026, eksklusive MVA",
    },
    sections=[
        # -- 2 Grunn og fundamenter (Ground and foundations) --
        (
            "2",
            "2 Grunn og fundamenter (Ground and foundations)",
            {"ns3451": "2", "din276": "310"},
            [
                ("2.01", "Rydding, rivning og midlertidig sikring (Site clearance and temporary works)", "m2", 3800, 185.00, {"ns3451": "21", "din276": "212"}),
                ("2.02", "Fjellsprengning og massetransport (Rock blasting and disposal)", "m3", 4200, 385.00, {"ns3451": "21", "din276": "311"}),
                ("2.03", "Graving i loesmasser og fyllingsarbeider (Excavation in soil and filling)", "m3", 3500, 215.00, {"ns3451": "21", "din276": "311"}),
                ("2.04", "Stoettevegger plasstoeypt betong, terrengsikring (Retaining walls, in-situ concrete, slope retention)", "m2", 850, 3850.00, {"ns3451": "22", "din276": "312"}),
                ("2.05", "Pelefundamentering til berg, borede staalpeler d 400 mm (Bored steel piles d 400 mm to rock)", "m", 2200, 2250.00, {"ns3451": "23", "din276": "323"}),
                ("2.06", "Pelehoder, grunnmurer og ringmurer (Pile caps, foundation and ring walls)", "m3", 420, 8500.00, {"ns3451": "23", "din276": "322"}),
                ("2.07", "Bunnplate betong 200 mm paa isolasjon (Ground slab 200 mm on insulation)", "m2", 3260, 1850.00, {"ns3451": "24", "din276": "324"}),
                ("2.08", "Kjellervegg prefab betong 200 mm (Basement wall, precast concrete 200 mm)", "m2", 2400, 2850.00, {"ns3451": "24", "din276": "331"}),
                ("2.09", "Drenering og overvannshaaandtering mot terreng (Drainage and stormwater management)", "m", 920, 1250.00, {"ns3451": "25", "din276": "313"}),
                ("2.10", "Midlertidig anleggsvei og riggomraade (Temporary site road and compound)", "m2", 1200, 325.00, {"ns3451": "21", "din276": "220"}),
                ("2.11", "Proevebelastning peler (Pile load testing)", "st", 8, 55000.00, {"ns3451": "23", "din276": "329"}),
                ("2.12", "Utvendige VA-ledninger og overvannsfordroeying (External drainage and stormwater attenuation)", "m", 580, 1550.00, {"ns3451": "25", "din276": "550"}),
            ],
        ),
        # -- 3 Baeresystem (Primary structure) --
        (
            "3",
            "3 Baeresystem (Primary structure)",
            {"ns3451": "3", "din276": "300"},
            [
                ("3.01", "Prefab betongvegger baerende 200 mm (Precast loadbearing concrete walls 200 mm)", "m2", 6500, 2250.00, {"ns3451": "32", "din276": "341"}),
                ("3.02", "Hulldekker HD 200 mm med paastoeyp (Hollow-core floor slabs HD 200 mm with topping)", "m2", 8800, 1450.00, {"ns3451": "33", "din276": "351"}),
                ("3.03", "Plasstoeypte betongvegger trapperom og sjakter (In-situ concrete walls, stairwells and shafts)", "m3", 420, 12500.00, {"ns3451": "32", "din276": "341"}),
                ("3.04", "Armering B500NC (Reinforcement B500NC)", "tonn", 215, 19500.00, {"ns3451": "32", "din276": "300"}),
                ("3.05", "Prefab betongtrapper (Precast concrete stairs)", "st", 30, 42000.00, {"ns3451": "34", "din276": "351"}),
                ("3.06", "Balkonger prefab betong med rekkverk (Precast concrete balconies with railings)", "st", 144, 55000.00, {"ns3451": "35", "din276": "351"}),
                ("3.07", "Plasstoeypt betong, diverse kompletteringer (In-situ concrete, miscellaneous)", "m3", 180, 11500.00, {"ns3451": "32", "din276": "300"}),
                ("3.08", "Staalinnstoeypningsgods og festemidler (Cast-in items and fixings)", "tonn", 14, 32000.00, {"ns3451": "32", "din276": "341"}),
                ("3.09", "Dekkepaastoeyp og komplettering ved sjakter (Floor topping and completion at risers)", "m2", 720, 1850.00, {"ns3451": "33", "din276": "351"}),
            ],
        ),
        # -- 4 Yttervegger og tak (External walls and roof) --
        (
            "4",
            "4 Yttervegger og tak (External walls and roof)",
            {"ns3451": "4", "din276": "330"},
            [
                ("4.01", "Yttervegger teglkledning paa isolert bindingsverk U 0,18 (External walls, brick cladding on insulated frame U 0.18)", "m2", 4200, 3250.00, {"ns3451": "42", "din276": "335"}),
                ("4.02", "Vinduer aluminium/tre, trelagsglass U 0,8 (Windows, aluminium/timber, triple glazing U 0.8)", "m2", 1650, 6500.00, {"ns3451": "43", "din276": "334"}),
                ("4.03", "Inngangsdoerer og porttelefon (Entrance doors and intercom)", "st", 6, 95000.00, {"ns3451": "43", "din276": "344"}),
                ("4.04", "Balkongdoerer, trelagsglass med lav terskel (Balcony doors, triple-glazed, low threshold)", "st", 144, 22500.00, {"ns3451": "43", "din276": "334"}),
                ("4.05", "Taktekking tolag papp, isolasjon U 0,09 (Roof covering, two-layer bituminous, insulation U 0.09)", "m2", 3260, 1450.00, {"ns3451": "47", "din276": "363"}),
                ("4.06", "Takavvanning, nedloep og sluk, dimensjonert for Bergen (Roof drainage, downpipes, sized for Bergen rainfall)", "m", 580, 785.00, {"ns3451": "47", "din276": "364"}),
                ("4.07", "Takrekkverk og sikkerhetsutstyr (Roof railings and fall arrest)", "m", 240, 3650.00, {"ns3451": "47", "din276": "369"}),
                ("4.08", "Sokkelisolasjon og sokkelbeklædning (Plinth insulation and cladding)", "m", 360, 2150.00, {"ns3451": "42", "din276": "327"}),
                ("4.09", "Vindtetting og vaerbestandig detaljering, Bergen-klima (Weather detailing for Bergen climate)", "m2", 4200, 185.00, {"ns3451": "42", "din276": "339"}),
                ("4.10", "Fasadefuger og fugmasser (Facade joints and sealants)", "m", 1600, 225.00, {"ns3451": "42", "din276": "335"}),
                ("4.11", "Takutstyr, takstiger og snoeefangere (Roof accessories, ladders and snow guards)", "m", 280, 725.00, {"ns3451": "47", "din276": "369"}),
            ],
        ),
        # -- 5 Innervegger og innredning (Internal walls and fit-out) --
        (
            "5",
            "5 Innervegger og innredning (Internal walls and fit-out)",
            {"ns3451": "5", "din276": "340"},
            [
                ("5.01", "Leilighetsskillende vegger 250 mm, lydklasse B (Party walls 250 mm, sound class B)", "m2", 3600, 1850.00, {"ns3451": "52", "din276": "342"}),
                ("5.02", "Innervegger leiligheter, gips paa staalskinne (Apartment partitions, plasterboard on studs)", "m2", 6400, 885.00, {"ns3451": "52", "din276": "342"}),
                ("5.03", "Doerer og karmer, inkl. brann EI 30 (Door sets including EI 30 fire doors)", "st", 480, 10500.00, {"ns3451": "53", "din276": "344"}),
                ("5.04", "Gulvbelegg parkett, keramikk og vinyl (Floor finishes, parquet, ceramic and vinyl)", "m2", 7200, 725.00, {"ns3451": "54", "din276": "353"}),
                ("5.05", "Himlinger vaatrom og fellesarealer (Suspended ceilings, wet rooms and common areas)", "m2", 2400, 585.00, {"ns3451": "55", "din276": "354"}),
                ("5.06", "Overflatebehandling vegger og tak, sparkling og maling (Wall and ceiling finishes, skim and paint)", "m2", 18000, 225.00, {"ns3451": "56", "din276": "345"}),
                ("5.07", "Kjoeekken komplett med hvitevarer og benkeplater (Kitchens with appliances and worktops)", "st", 72, 165000.00, {"ns3451": "57", "din276": "381"}),
                ("5.08", "Bad komplett fliser, sanitaerutstyr og armaturer (Bathrooms with tiles, sanitary ware and fittings)", "st", 96, 125000.00, {"ns3451": "57", "din276": "381"}),
                ("5.09", "Trapperom overflater, rekkverk og belysning (Stairwell finishes, railings and lighting)", "st", 6, 365000.00, {"ns3451": "58", "din276": "345"}),
                ("5.10", "Vaskerom komplett innredning (Laundry room complete fit-out)", "st", 3, 225000.00, {"ns3451": "57", "din276": "381"}),
                ("5.11", "Bodareal inkl. doerer og belysning (Storage rooms with doors and lighting)", "st", 72, 15500.00, {"ns3451": "57", "din276": "381"}),
                ("5.12", "Lydisolasjon leilighetsskillende konstruksjoner (Acoustic insulation to party elements)", "m2", 2200, 365.00, {"ns3451": "52", "din276": "342"}),
                ("5.13", "Vaatromsmembran og tetting (Wet room membranes and tanking)", "m2", 1400, 585.00, {"ns3451": "54", "din276": "353"}),
            ],
        ),
        # -- 6 VVS-installasjoner (Mechanical services) --
        (
            "6",
            "6 VVS-installasjoner (Mechanical services)",
            {"ns3451": "6", "din276": "400"},
            [
                ("6.01", "Fjaernvarmesentral (District heating substation)", "st", 3, 585000.00, {"ns3451": "62", "din276": "421"}),
                ("6.02", "Varmeledninger og radiatorer (Heating pipework and radiators)", "leilighet", 72, 42000.00, {"ns3451": "62", "din276": "422"}),
                ("6.03", "Balansert ventilasjon med varmegjenvinner 80% (Balanced ventilation with 80% heat recovery)", "st", 3, 785000.00, {"ns3451": "64", "din276": "432"}),
                ("6.04", "Ventilasjonskanaler og ventiler (Ductwork and terminals)", "m2", 9800, 485.00, {"ns3451": "64", "din276": "431"}),
                ("6.05", "Tappevann kaldt og varmt, stamledninger (Potable water risers, hot and cold)", "leilighet", 72, 35000.00, {"ns3451": "65", "din276": "412"}),
                ("6.06", "Spillvann og overvann, stamledninger og stikkledninger (Drainage risers and connections)", "leilighet", 72, 24500.00, {"ns3451": "66", "din276": "411"}),
                ("6.07", "Gulvvarme bad og entree (Underfloor heating, bathrooms and entrances)", "m2", 620, 725.00, {"ns3451": "62", "din276": "422"}),
                ("6.08", "Varmtvannsberedere med varmepumpe (Hot water heaters with heat pump)", "st", 3, 325000.00, {"ns3451": "62", "din276": "421"}),
                ("6.09", "Brannspjeld og gjennomfoeringer (Fire dampers and penetrations)", "st", 360, 2250.00, {"ns3451": "64", "din276": "431"}),
                ("6.10", "SD-anlegg, reguleringsteknikk og innregulering (BMS, controls and balancing)", "post", 1, 1050000.00, {"ns3451": "68", "din276": "480"}),
                ("6.11", "Kjoeekkenventilasjon og avtrekkshetter (Kitchen ventilation and hoods)", "st", 72, 10500.00, {"ns3451": "64", "din276": "431"}),
            ],
        ),
        # -- 7 Elkraft og tele (Electrical services) --
        (
            "7",
            "7 Elkraft og tele (Electrical services)",
            {"ns3451": "7", "din276": "440"},
            [
                ("7.01", "Hovedfordeling og mating fra nett (Main distribution and supply)", "post", 1, 1650000.00, {"ns3451": "71", "din276": "441"}),
                ("7.02", "Elinstallasjon per leilighet inkl. sikringsskap (Electrical per apartment with consumer unit)", "leilighet", 72, 115000.00, {"ns3451": "72", "din276": "444"}),
                ("7.03", "Fellesbelysning trapperom, garasje og utomhus (Common lighting, stairs, garage and external)", "post", 1, 1850000.00, {"ns3451": "73", "din276": "445"}),
                ("7.04", "Brannalarmanlegg og roemningstegn (Fire detection and exit signage)", "m2", 9800, 225.00, {"ns3451": "75", "din276": "456"}),
                ("7.05", "Adgangskontroll og porttelefon (Access control and intercom)", "post", 1, 1150000.00, {"ns3451": "75", "din276": "456"}),
                ("7.06", "Solcelleanlegg tak 90 kWp (Rooftop PV, 90 kWp)", "kWp", 90, 9500.00, {"ns3451": "71", "din276": "442"}),
                ("7.07", "Heiser 3 stk personheis (Passenger lifts, 3 units)", "st", 3, 1350000.00, {"ns3451": "76", "din276": "461"}),
                ("7.08", "Elbillading parkeringskjeller 36 plasser (EV charging, 36 spaces)", "st", 36, 42000.00, {"ns3451": "72", "din276": "444"}),
                ("7.09", "Fiber- og brebaaandsinfrastruktur til leiligheter (Fibre broadband to apartments)", "leilighet", 72, 10500.00, {"ns3451": "74", "din276": "451"}),
                ("7.10", "Noedlys og roemningstegn (Emergency lighting and exit signage)", "post", 1, 585000.00, {"ns3451": "73", "din276": "446"}),
                ("7.11", "Jordfeilvern og lynvern (Earth fault and lightning protection)", "post", 1, 485000.00, {"ns3451": "71", "din276": "446"}),
            ],
        ),
        # -- 8 Utomhus og terreng (External works) --
        (
            "8",
            "8 Utomhus og terreng (External works)",
            {"ns3451": "8", "din276": "500"},
            [
                ("8.01", "Uteoppholdsareal, belegningsstein og beplantning (Outdoor amenity, paving and planting)", "m2", 2400, 1550.00, {"ns3451": "83", "din276": "530"}),
                ("8.02", "Lekeplass iht. TEK17 (Playground per TEK17)", "post", 1, 1050000.00, {"ns3451": "83", "din276": "570"}),
                ("8.03", "Avfallshaaandtering, oppsamling og soertering (Waste management and sorting)", "post", 1, 950000.00, {"ns3451": "84", "din276": "382"}),
                ("8.04", "Sykkelskur og sykkelstativer 144 plasser (Cycle shelters and racks, 144 spaces)", "st", 144, 5500.00, {"ns3451": "82", "din276": "382"}),
                ("8.05", "Utomhus VA, stikkledninger og utebelysning (External services and site lighting)", "post", 1, 2850000.00, {"ns3451": "84", "din276": "550"}),
                ("8.06", "Terrengtilpasning og stoettemurer (Terrain adaptation and retaining walls)", "m", 160, 9500.00, {"ns3451": "83", "din276": "539"}),
                ("8.07", "Garasjerampe og sikkerhetsutstyr (Garage ramp and safety equipment)", "post", 1, 585000.00, {"ns3451": "82", "din276": "382"}),
                ("8.08", "Miljoestasjon og avfallssortering (Recycling station and waste sorting)", "post", 1, 485000.00, {"ns3451": "84", "din276": "382"}),
                ("8.09", "Overvannsfordroeying (Stormwater attenuation)", "post", 1, 585000.00, {"ns3451": "84", "din276": "550"}),
                ("8.10", "Felles boder og lagerrom (Common storage rooms)", "st", 3, 125000.00, {"ns3451": "81", "din276": "381"}),
                ("8.11", "Uteoppholdsplass med grillplass og sittegrupper (Outdoor amenity with BBQ and seating)", "post", 1, 365000.00, {"ns3451": "83", "din276": "570"}),
                ("8.12", "Byggrenhold sluttrengjoeering (Final clean)", "m2", 9800, 45.00, {"ns3451": "89", "din276": "381"}),
                ("8.13", "Som-bygget-dokumentasjon (As-built drawings)", "post", 1, 485000.00, {"ns3451": "89", "din276": "381"}),
            ],
        ),
    ],
    markups=[
        ("Rigging og drift av byggeplass (Site overheads and preliminaries 11%)", 11.0, "overhead", "direct_cost"),
        ("Administrasjonskostnader (Head-office overheads 5%)", 5.0, "overhead", "cumulative"),
        ("Forsikring og garanti (Insurance and bond 0,5%)", 0.5, "insurance", "cumulative"),
        ("Fortjeneste og risiko (Profit and risk 4,5%)", 4.5, "profit", "cumulative"),
        ("MVA 25 prosent (Norwegian VAT at 25 percent)", 25.0, "tax", "cumulative"),
    ],
    total_months=22,
    tender_name="Hovedentreprise bolig (Main contract, residential)",
    tender_companies=[
        ("Sandviken Bolig AS", "anbud@sandvikenbolig.example", 0.97),
        ("Bergen Boligbyggere", "tilbud@bergenbolig.example", 1.03),
        ("Fjellsiden Entreprenoer AS", "tender@fjellsiden-ent.example", 1.01),
    ],
    schedule_activities=[
        ("Etablering og klargjoeering (Site setup and enabling)", "2026-03-02", "2026-05-29"),
        ("Sprengning og graving (Blasting and excavation)", "2026-04-15", "2026-08-31"),
        ("Fundamenter og kjeller (Foundations and basement)", "2026-07-01", "2026-11-30"),
        ("Baeresystem bygning 1 (Frame, building 1)", "2026-10-01", "2027-02-28"),
        ("Baeresystem bygning 2-3 (Frame, buildings 2-3)", "2027-01-03", "2027-05-31"),
        ("Fasade og tak (Facade and roof)", "2027-03-01", "2027-09-30"),
        ("VVS og el (M&E installation)", "2027-05-01", "2027-10-31"),
        ("Innredning og overflater (Fit-out and finishes)", "2027-07-01", "2027-12-31"),
        ("Utomhus og terreng (External works)", "2027-10-01", "2028-01-31"),
        ("Ferdigstillelse og overtakelse (Completion and handover)", "2027-12-01", "2028-01-31"),
    ],
    project_metadata={
        "address": "Sandviksboder 42, 5035 Bergen, Norge",
        "client": "Sandviken Boligutvikling AS (Sandviken Housing Development)",
        "architect": "Arkitektgruppen Fjellet (Fjellet Architects)",
        "structural_engineer": "Konstruktoer Vestlandet AS (Vestlandet Structural Engineers)",
        "services_engineer": "VVS-Raadgivning Bergen AS (Bergen M&E Consultants)",
        "gfa_m2": 9800,
        "storeys": "5 etasjer pluss parkeringskjeller (5 storeys plus parking basement)",
        "apartments": 72,
        "contract": "NS 8405, hovedentreprise med fastpris (General contracting under NS 8405, lump sum)",
    },
    budget_boq_name="Kalkyle boligprosjekt Sandviken (Residential Project Cost Estimate)",
    planned_budget=345000000.0,
    actual_spend_ratio=0.40,
    spi_override=0.95,
    cpi_override=1.03,
)
