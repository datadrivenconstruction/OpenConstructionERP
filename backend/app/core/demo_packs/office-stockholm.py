# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Demo pack: Kontorsbyggnad Norrmalm - Stockholm (Office Building, Stockholm)
# ---------------------------------------------------------------------------
# A Swedish kalkyl is organised by BSAB element codes. Specifications follow
# AMA Hus, and the contract form is AB 04 for general contracting or ABT 06
# for design-build. Tax is 25% moms on new-build construction services.
#
# Rates are Stockholm 2026 market levels in SEK excluding moms. They are the
# right order of magnitude for a Grade A office in central Stockholm but are
# not taken from a published Swedish price book. A kalkylator should replace
# the rate column with a current calculation before using this anywhere near
# a real tender.
#
# Stockholm sits on clay and bedrock. A city-centre office typically needs
# piled foundations to rock, and excavation through clay requires sheet piling
# and dewatering. The substructure cost reflects this.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="office-stockholm",
    project_name="Kontorsbyggnad Norrmalm - Stockholm (Office Building, Stockholm Norrmalm)",
    project_description=(
        "Nybyggnad av kontorsbyggnad i Norrmalm, Stockholm. Tolv vaaningar ovan mark "
        "och en kallarvaaning. Bruttoarea cirka 18 500 m2 matt enligt SS 21054. "
        "Staalkonstruktion med prefabricerade betongbjoerklag, elementfasad i aluminium "
        "med treglasfoenster. Vaerme fraan fjaerrvaarme, kyla fraan fjaerrkyla, 180 kWp "
        "solceller paa taket. Byggkostnad cirka 620 MSEK exklusive moms. "
        "New-build office in Norrmalm, Stockholm. Twelve storeys above ground and one "
        "basement level. Gross floor area approx. 18,500 m2 measured to SS 21054. "
        "Steel frame with precast concrete floor slabs, unitised aluminium curtain wall "
        "with triple glazing. Heating from district heating, cooling from district cooling, "
        "180 kWp rooftop PV. Construction cost approx. SEK 620M excluding VAT."
    ),
    region="SE",
    classification_standard="bsab",
    currency="SEK",
    locale="sv",
    address={
        "street": "Malmskillnadsgatan 32",
        "city": "Stockholm",
        "postcode": "111 51",
        "country": "Sweden",
        "lat": 59.3346,
        "lng": 18.0632,
    },
    validation_rule_sets=["boq_quality", "project_completeness"],
    project_code="STO-NRM-2026-01",
    boq_name="Kalkyl BSAB - prislaege Stockholm 2026 (Cost Estimate, BSAB classification)",
    boq_description=(
        "Kalkyl uppstaelld efter BSAB-systemet med enhetspriser per byggnadsdel. "
        "Arbetsplatsomkostnader, centraladministration och vinst som separata paaslag. "
        "Prislaege Stockholm foersta kvartalet 2026, exklusive moms. "
        "Cost estimate structured by BSAB elements with unit rates per building element. "
        "Site overheads, head-office overheads and profit as separate uplifts. "
        "Stockholm Q1 2026 price level, excluding VAT."
    ),
    boq_metadata={
        "standard": "BSAB 96 elementindelning",
        "phase": "Systemhandling - kalkyl (Detailed design estimate)",
        "base_date": "2026-Q1",
        "price_level": "Stockholm 2026, exklusive moms",
        "pricing_method": "Elementkalkyl med enhetspriser",
        "measurement": "SS 21054 (BTA, BRA)",
    },
    sections=[
        # -- 01 Mark och grundlaeggning (Site and foundations) --
        (
            "01",
            "01 Mark och grundlaeggning (Site and foundations)",
            {"bsab": "1", "din276": "310"},
            [
                ("01.1", "Roejning, rivning och marksanering (Site clearance, demolition and remediation)", "m2", 2800, 185.00, {"bsab": "1.1", "din276": "212"}),
                ("01.2", "Spontning staalspont HZ 680 till berg (Sheet piling HZ 680 to rock)", "m2", 3200, 1150.00, {"bsab": "1.2", "din276": "312"}),
                ("01.3", "Schakt och jordtransport, lermoraan (Excavation and disposal, clay moraine)", "m3", 8500, 165.00, {"bsab": "1.2", "din276": "311"}),
                ("01.4", "Grundlaeggning borrade staalroerspaaalar d 170 mm till berg (Bored steel pipe piles d 170 mm to rock)", "m", 4200, 1250.00, {"bsab": "1.3", "din276": "323"}),
                ("01.5", "Paalplattor, grundbalkar och sulor (Pile caps, ground beams and pad foundations)", "m3", 680, 7800.00, {"bsab": "1.3", "din276": "322"}),
                ("01.6", "Kallargolv betong 200 mm paa isolering (Basement floor slab 200 mm on insulation)", "m2", 1550, 1650.00, {"bsab": "1.4", "din276": "324"}),
                ("01.7", "Kallarvaeggar platsgjuten betong 300 mm, vattentaat (Basement walls in-situ concrete 300 mm, watertight)", "m2", 2400, 2850.00, {"bsab": "1.4", "din276": "331"}),
                ("01.8", "Grundlaggning, laenspumpning och tillfaelligt grundvattenskydd (Dewatering and temporary groundwater control)", "maan", 8, 125000.00, {"bsab": "1.2", "din276": "313"}),
                ("01.9", "Markfoerstaerkning och geoteknisk kontroll (Ground improvement and geotechnical monitoring)", "post", 1, 850000.00, {"bsab": "1.1", "din276": "319"}),
                ("01.10", "Tillfaellig omledning av ledningar och trafik (Temporary utility diversion and traffic management)", "post", 1, 485000.00, {"bsab": "1.1", "din276": "220"}),
                ("01.11", "Paalbelastningsprov och integritetstest (Pile load testing and integrity testing)", "st", 12, 65000.00, {"bsab": "1.3", "din276": "329"}),
            ],
        ),
        # -- 02 Baerande konstruktion (Primary structure) --
        (
            "02",
            "02 Baerande konstruktion (Primary structure)",
            {"bsab": "2", "din276": "300"},
            [
                ("02.1", "Staalstomme pelare HEB 300-500 (Steel columns HEB 300-500)", "ton", 420, 28500.00, {"bsab": "2.1", "din276": "341"}),
                ("02.2", "Staalstomme balkar IPE/HEA (Steel beams IPE/HEA)", "ton", 580, 26500.00, {"bsab": "2.1", "din276": "341"}),
                ("02.3", "Prefab betongbjoerklag HD/F 265 mm med paalgjutning (Precast concrete floor slabs HD/F 265 mm with structural topping)", "m2", 15800, 1350.00, {"bsab": "2.2", "din276": "351"}),
                ("02.4", "Platsgjutna betongkaernor C35/45, kaernor och trapphus (In-situ concrete cores C35/45, cores and stairwells)", "m3", 1250, 12500.00, {"bsab": "2.3", "din276": "341"}),
                ("02.5", "Armering B500B, stomkomplettering (Reinforcement B500B, structural completion)", "ton", 380, 18500.00, {"bsab": "2.1", "din276": "300"}),
                ("02.6", "Prefab betongtrappor och vilplan (Precast concrete stairs and landings)", "st", 26, 42000.00, {"bsab": "2.4", "din276": "351"}),
                ("02.7", "Staalstomme takuppbyggnad inkl. brandskydd R60 (Roof steelwork including R60 fire protection)", "ton", 85, 34500.00, {"bsab": "2.1", "din276": "361"}),
                ("02.8", "Fogar, dilatationer och upplag (Joints, expansion joints and bearings)", "m", 280, 1450.00, {"bsab": "2.1", "din276": "359"}),
                ("02.9", "Platsgjuten betong diverse kompletteringar (In-situ concrete miscellaneous)", "m3", 180, 9800.00, {"bsab": "2.1", "din276": "300"}),
                ("02.10", "Staalinfaestningar och ingjutningsgods (Steel fixings and cast-in items)", "ton", 28, 32000.00, {"bsab": "2.1", "din276": "341"}),
            ],
        ),
        # -- 03 Yttervaeggar och fasad (External walls and facade) --
        (
            "03",
            "03 Yttervaeggar och fasad (External walls and facade)",
            {"bsab": "3", "din276": "330"},
            [
                ("03.1", "Elementfasad aluminium med treglasfoenster (Unitised aluminium curtain wall with triple glazing)", "m2", 5200, 9500.00, {"bsab": "3.1", "din276": "337"}),
                ("03.2", "Slutna fasadelement, isolerade paneler U 0,15 (Opaque facade zones, insulated panels U 0.15)", "m2", 850, 5200.00, {"bsab": "3.1", "din276": "337"}),
                ("03.3", "Entrefasad natursten och glaspartier med karuselldoerr (Entrance facade, natural stone and glazed screen with revolving door)", "m2", 380, 8500.00, {"bsab": "3.2", "din276": "335"}),
                ("03.4", "Utvaaendig solskydd, screenkassetter med vindgivare (External solar shading, screen cassettes with wind sensor)", "m2", 4200, 1650.00, {"bsab": "3.3", "din276": "338"}),
                ("03.5", "Brandavskiljande fasadband EI 60 (Fire-resisting spandrel zones EI 60)", "m", 1600, 1850.00, {"bsab": "3.1", "din276": "337"}),
                ("03.6", "Fasadunderhaallsinstallation, balkbana och gondol (Facade access, rail and cradle)", "post", 1, 2850000.00, {"bsab": "3.9", "din276": "339"}),
                ("03.7", "Taktaeckning tvaalags papp paa PIR-isolering U 0,13 (Two-layer bituminous roof on PIR insulation U 0.13)", "m2", 1450, 1350.00, {"bsab": "3.5", "din276": "363"}),
                ("03.8", "Sedumtak med foerdroejningsmagasin, 50 mm (Green roof with retention layer, 50 mm)", "m2", 800, 1650.00, {"bsab": "3.5", "din276": "363"}),
                ("03.9", "Taakkanter, raecken och saekerhetsanordningar (Roof edges, railings and fall arrest)", "m", 320, 3500.00, {"bsab": "3.5", "din276": "369"}),
                ("03.10", "Takbrunnar och avvattningssystem (Roof outlets and drainage system)", "st", 48, 4850.00, {"bsab": "3.5", "din276": "364"}),
                ("03.11", "Fasadfogar och fogmassor (Facade joints and sealants)", "m", 2800, 285.00, {"bsab": "3.1", "din276": "337"}),
            ],
        ),
        # -- 04 Innervaeggar och inredning (Internal walls and fit-out) --
        (
            "04",
            "04 Innervaeggar och inredning (Internal walls and fit-out)",
            {"bsab": "4", "din276": "340"},
            [
                ("04.1", "Laetta innervaeggar staaalreglar 95 mm med gips, EI 60 (Metal stud partitions 95 mm with plasterboard, EI 60)", "m2", 6800, 985.00, {"bsab": "4.1", "din276": "342"}),
                ("04.2", "Glasvaeggar konferensrum, demonterbara (Demountable glazed partitions, meeting rooms)", "m2", 2200, 3250.00, {"bsab": "4.1", "din276": "346"}),
                ("04.3", "Innerdoerrar och karmar, inkl. brand- och roekdoerrar (Internal door sets, including fire and smoke rated)", "st", 480, 12500.00, {"bsab": "4.2", "din276": "344"}),
                ("04.4", "Upphoeojt installationsgolv paa kontorsplan (Raised access floor to office floors)", "m2", 14200, 785.00, {"bsab": "4.3", "din276": "353"}),
                ("04.5", "Golvbelaggning textilplatta, natursten och kakel (Floor finishes, carpet tile, natural stone and ceramic)", "m2", 14800, 650.00, {"bsab": "4.3", "din276": "353"}),
                ("04.6", "Golvbelaggning garage och teknikrum, epoxibelaggning (Resin flooring to garage and plant rooms)", "m2", 1550, 585.00, {"bsab": "4.3", "din276": "353"}),
                ("04.7", "Undertakssystem mineralull, akustikklass A (Suspended ceilings, mineral wool, acoustic class A)", "m2", 14600, 585.00, {"bsab": "4.4", "din276": "354"}),
                ("04.8", "Akustiska takoear och absorptionspaneler (Acoustic ceiling rafts and absorption panels)", "m2", 2800, 1450.00, {"bsab": "4.4", "din276": "354"}),
                ("04.9", "Vaggbeklaeaednad och maaalning (Wall finishes and painting)", "m2", 18500, 245.00, {"bsab": "4.5", "din276": "345"}),
                ("04.10", "Toalettgrupper, komplett inredningspaket (Sanitary cores, complete fit-out package)", "st", 24, 285000.00, {"bsab": "4.6", "din276": "381"}),
                ("04.11", "Kalkstensskivor baenkar och foensterbaenkar (Limestone sills and window boards)", "m", 580, 1850.00, {"bsab": "4.5", "din276": "345"}),
                ("04.12", "Ljudisolering mellanvaeggar och instalschakt (Acoustic insulation to partitions and risers)", "m2", 3200, 325.00, {"bsab": "4.1", "din276": "342"}),
            ],
        ),
        # -- 05 VVS-installationer (Mechanical services) --
        (
            "05",
            "05 VVS-installationer (Mechanical services)",
            {"bsab": "5", "din276": "400"},
            [
                ("05.1", "Fjaerrvaaermeundercentral 2 x 800 kW (District heating substation 2 x 800 kW)", "st", 2, 1250000.00, {"bsab": "5.1", "din276": "421"}),
                ("05.2", "Fjaerrkyla, vaexlare och distributionsroer (District cooling, heat exchangers and distribution piping)", "post", 1, 3850000.00, {"bsab": "5.2", "din276": "423"}),
                ("05.3", "Klimattak och induktionsdon paa kontorsplan (Chilled ceilings and induction units to office floors)", "m2", 14200, 650.00, {"bsab": "5.3", "din276": "423"}),
                ("05.4", "Luftbehandlingsaggregat med vaermeaaatervinning 85% (Air handling units with 85% heat recovery)", "st", 6, 1450000.00, {"bsab": "5.4", "din276": "432"}),
                ("05.5", "Ventilationskanaler galvaniserat staal inkl. isolering (Galvanised steel ductwork including insulation)", "m2", 9800, 1150.00, {"bsab": "5.4", "din276": "431"}),
                ("05.6", "Brandspjaell och genomfoeringar (Fire dampers and penetration seals)", "st", 1200, 2850.00, {"bsab": "5.4", "din276": "431"}),
                ("05.7", "Roersystem vaerme och kyla inkl. ventiler (Hydronic pipework, heating and cooling with valves)", "m", 6500, 985.00, {"bsab": "5.1", "din276": "422"}),
                ("05.8", "Tappvatteninstallation och legionellaskydd (Potable water installation and legionella control)", "st", 240, 18500.00, {"bsab": "5.5", "din276": "412"}),
                ("05.9", "Spillvatten- och dagvattenavlopp (Foul and rainwater drainage)", "m", 2400, 985.00, {"bsab": "5.6", "din276": "411"}),
                ("05.10", "Sprinklerinstallation heltaeckande inkl. pumprum (Full-coverage sprinkler installation with pump room)", "m2", 18500, 325.00, {"bsab": "5.7", "din276": "412"}),
                ("05.11", "Roek- och vaermeventilation garage och tryckstaatta trapphus (Smoke extract to garage and stair pressurisation)", "post", 1, 3250000.00, {"bsab": "5.4", "din276": "431"}),
                ("05.12", "Styr- och oevervakning, injustering och provdrift (BMS, controls, balancing and commissioning)", "m2", 18500, 285.00, {"bsab": "5.8", "din276": "480"}),
                ("05.13", "Koeling serverrum och datahallar, redundant (Cooling to server rooms, redundant)", "post", 1, 2850000.00, {"bsab": "5.2", "din276": "434"}),
            ],
        ),
        # -- 06 El och transport (Electrical services and transport) --
        (
            "06",
            "06 El och transport (Electrical services and transport)",
            {"bsab": "6", "din276": "440"},
            [
                ("06.1", "Elhuvudcentral och transformatorer 2 x 1250 kVA (Main switchboard and transformers 2 x 1,250 kVA)", "post", 1, 5850000.00, {"bsab": "6.1", "din276": "441"}),
                ("06.2", "Kabelstegar, huvudstraak och vertikala schakt (Cable containment, main routes and risers)", "m", 5800, 650.00, {"bsab": "6.2", "din276": "444"}),
                ("06.3", "Kraft- och belysningsgrupper (Power and lighting circuits)", "m2", 18500, 425.00, {"bsab": "6.2", "din276": "444"}),
                ("06.4", "LED-belysning med dagsljus- och naarvarostyrning (LED lighting with daylight and presence control)", "m2", 15500, 585.00, {"bsab": "6.3", "din276": "445"}),
                ("06.5", "Noedbelysning, utrymningsskyltar och aaskskydd (Emergency lighting, exit signage and lightning protection)", "post", 1, 2850000.00, {"bsab": "6.3", "din276": "446"}),
                ("06.6", "Solcellsinstallation tak 180 kWp (Rooftop PV installation 180 kWp)", "kWp", 180, 8500.00, {"bsab": "6.1", "din276": "442"}),
                ("06.7", "Brandlarmanlaaeggning och utrymningslarm (Fire detection and evacuation alarm)", "m2", 18500, 245.00, {"bsab": "6.5", "din276": "456"}),
                ("06.8", "Passagesystem, kameraoevervakning och inbrottslarm (Access control, CCTV and intruder alarm)", "post", 1, 4850000.00, {"bsab": "6.5", "din276": "456"}),
                ("06.9", "Datainfrastruktur och kopplingsskapp (Structured cabling and patch panels)", "post", 1, 4250000.00, {"bsab": "6.4", "din276": "451"}),
                ("06.10", "Personhissar och brandmannshiss, 7 st, 1,6 m/s (Passenger and firefighting lifts, 7 units, 1.6 m/s)", "st", 7, 1850000.00, {"bsab": "6.6", "din276": "461"}),
                ("06.11", "Solskydds- och belysningsstyrning kopplad till BMS (Shading and lighting control linked to BMS)", "m2", 15500, 125.00, {"bsab": "6.3", "din276": "480"}),
                ("06.12", "Energimonitoring och undermaetning (Energy monitoring and submetering)", "post", 1, 1250000.00, {"bsab": "6.1", "din276": "480"}),
                ("06.13", "Reservkraft dieselaggregat 500 kVA (Standby power, diesel generator 500 kVA)", "st", 1, 2450000.00, {"bsab": "6.1", "din276": "443"}),
            ],
        ),
        # -- 07 Fast inredning och mark (Fixed fittings and external works) --
        (
            "07",
            "07 Fast inredning och mark (Fixed fittings and external works)",
            {"bsab": "7", "din276": "500"},
            [
                ("07.1", "Fast inredning entrehall, reception och pentry (Fixed fittings to entrance, reception and pantries)", "post", 1, 3850000.00, {"bsab": "7.1", "din276": "381"}),
                ("07.2", "Cykelgarage 350 platser, staell och passerkontroll (Cycle store, 350 spaces, racks and access)", "st", 350, 6500.00, {"bsab": "7.2", "din276": "382"}),
                ("07.3", "Parkeringsanlaggning kaellare, 32 platser inkl. laddstolpar (Basement parking, 32 spaces with EV chargers)", "st", 32, 52000.00, {"bsab": "7.2", "din276": "382"}),
                ("07.4", "Markbelaggning gatsten och plattor (External paving, setts and slabs)", "m2", 1800, 1450.00, {"bsab": "7.3", "din276": "530"}),
                ("07.5", "Markplantering, traed och dagvattenhantering (Landscaping, trees and stormwater management)", "m2", 1200, 1850.00, {"bsab": "7.3", "din276": "570"}),
                ("07.6", "Markledningar, servisanslutningar och utebelysning (External services, utility connections and site lighting)", "post", 1, 2850000.00, {"bsab": "7.4", "din276": "550"}),
                ("07.7", "Skyltning, husnumrering och fasadbelysning (Signage, numbering and facade lighting)", "post", 1, 1250000.00, {"bsab": "7.5", "din276": "381"}),
                ("07.8", "Avfallshantering, kae llsortering och sopsug (Waste management, sorting and vacuum collection)", "post", 1, 850000.00, {"bsab": "7.6", "din276": "382"}),
                ("07.9", "Staengsel, grindar och fastighetsskyltning (Fencing, gates and property signage)", "post", 1, 485000.00, {"bsab": "7.3", "din276": "530"}),
                ("07.10", "Laddplatser elbilar garage 32 st (EV charging points, 32 units)", "st", 32, 42000.00, {"bsab": "7.2", "din276": "382"}),
                ("07.11", "Dagvattenmagasin och foerdroejningsanlaaeggning (Stormwater attenuation tank)", "post", 1, 650000.00, {"bsab": "7.4", "din276": "550"}),
                ("07.12", "Foerraadsrum byggnad, doerrar och ventilation (Building stores, doors and ventilation)", "st", 4, 125000.00, {"bsab": "7.1", "din276": "381"}),
                ("07.13", "Uteservering terrass med raecken och belysning (Outdoor terrace with railings and lighting)", "m2", 350, 2450.00, {"bsab": "7.3", "din276": "570"}),
                ("07.14", "Byggstaeadning slutstaeadning (Final clean to building)", "m2", 18500, 45.00, {"bsab": "7.9", "din276": "381"}),
                ("07.15", "Relationshandlingar och driftinstruktioner (As-built drawings and O&M manuals)", "post", 1, 850000.00, {"bsab": "7.9", "din276": "381"}),
            ],
        ),
    ],
    markups=[
        ("Arbetsplatsomkostnader, APO (Site overheads and preliminaries 9%)", 9.0, "overhead", "direct_cost"),
        ("Centraladministration, CA (Head-office overheads 5,5%)", 5.5, "overhead", "cumulative"),
        ("Foersakring och garanti (Insurance and bond 0,5%)", 0.5, "insurance", "cumulative"),
        ("Vinst och risk (Profit and risk 5%)", 5.0, "profit", "cumulative"),
        ("Moms 25 procent (Swedish VAT at 25 percent)", 25.0, "tax", "cumulative"),
    ],
    total_months=26,
    tender_name="Generalentreprenad bygg och installation (Main contract, building and services)",
    tender_companies=[
        ("Norrmalm Bygg AB", "anbud@norrmalmbygg.example", 0.98),
        ("Stockholms Byggkonsort", "offert@sthlmbygg.example", 1.02),
        ("Kungsholmen Entreprenad AB", "tender@kungsholmen-ent.example", 1.01),
    ],
    tender_packages=[
        (
            "Mark och grundlaeggning (Site and foundations)",
            "Spontning, schakt, paalning och kallarbjaealklag.",
            "evaluating",
            [
                ("Djupgrund Geoteknik AB", "anbud@djupgrund.example", 0.97),
                ("Berg och Mark Entreprenad", "offert@bergmark.example", 1.03),
                ("Paaltech Norden AB", "tender@paaltech.example", 1.01),
            ],
        ),
        (
            "Stomme och fasad (Structure and facade)",
            "Staalstomme, betongkaernor, fasadelement och tak.",
            "evaluating",
            [
                ("Norrmalm Bygg AB", "anbud@norrmalmbygg.example", 0.98),
                ("Stockholms Byggkonsort", "offert@sthlmbygg.example", 1.03),
                ("Kungsholmen Entreprenad AB", "tender@kungsholmen-ent.example", 1.01),
            ],
        ),
        (
            "VVS och el (Mechanical and electrical services)",
            "Fjaerrvaaerme, kyla, ventilation, el, brandlarm och hissar.",
            "issued",
            [
                ("Klimatteknik Syd AB", "anbud@klimatteknik.example", 0.99),
                ("Elinstallation Norden AB", "offert@elinstallation.example", 1.04),
                ("VVS Partner Stockholm", "tender@vvspartner.example", 1.01),
            ],
        ),
    ],
    schedule_activities=[
        ("Etablering och markarbeten (Site setup and enabling)", "2026-03-02", "2026-05-29"),
        ("Spontning och schakt (Sheet piling and excavation)", "2026-04-01", "2026-07-31"),
        ("Paalning och grundlaeggning (Piling and foundations)", "2026-06-01", "2026-09-30"),
        ("Kallarbjaealklag och vaeggar (Basement slab and walls)", "2026-08-01", "2026-11-30"),
        ("Staalstomme och betongkaernor (Steel frame and concrete cores)", "2026-10-01", "2027-04-30"),
        ("Fasad och tak (Facade and roof)", "2027-02-01", "2027-08-31"),
        ("VVS och el, huvudledningar (M&E main distribution)", "2027-04-01", "2027-09-30"),
        ("Innervaeggar och doerrar (Internal walls and doors)", "2027-06-01", "2027-10-31"),
        ("Hissar och transport (Lifts and transport)", "2027-07-01", "2027-10-31"),
        ("Inredning och ytskikt (Fit-out and finishes)", "2027-08-01", "2027-12-31"),
        ("Mark och utemiljoe (External works and landscaping)", "2027-10-01", "2028-01-31"),
        ("Injustering och oeverlaamning (Commissioning and handover)", "2027-12-01", "2028-04-30"),
    ],
    project_metadata={
        "address": "Malmskillnadsgatan 32, 111 51 Stockholm, Sverige",
        "client": "Norrmalm Fastigheter AB (Norrmalm Properties)",
        "architect": "Arkitektkontoret Strandvaegen (Strandvaegen Architects)",
        "structural_engineer": "Konstruktoererna Norden AB (Norden Structural Engineers)",
        "services_engineer": "Installationsbyraaan Kungsholmen (Kungsholmen Building Services)",
        "quantity_surveyor": "Kalkylgruppen Stockholm AB (Stockholm Cost Consultants)",
        "gfa_m2": 18500,
        "gfa_above_grade_m2": 17000,
        "gfa_basement_m2": 1500,
        "site_area_m2": 2800,
        "storeys": "12 vaaningar ovan mark, 1 kaallarvaaning (12 storeys above ground, 1 basement level)",
        "building_height_m": 44,
        "parking_spaces": 32,
        "cycle_spaces": 350,
        "structure_system": (
            "Staalstomme med prefab betongbjoerklag och platsgjutna betongkaernor. "
            "Steel frame with precast concrete floor slabs and in-situ concrete cores."
        ),
        "foundation": (
            "Borrade staalroerspaaalar d 170 mm till berg. Spontning med staalspont under "
            "schakt genom lera. Bored steel pipe piles to rock. Sheet-piled excavation through clay."
        ),
        "contract": (
            "AB 04, generalentreprenad med fast pris. General contracting under AB 04, lump sum."
        ),
    },
    budget_boq_name="Kalkyl kontorsbyggnad Norrmalm (Office Building Cost Estimate)",
    planned_budget=620000000.0,
    actual_spend_ratio=0.35,
    spi_override=0.98,
    cpi_override=1.01,
)
