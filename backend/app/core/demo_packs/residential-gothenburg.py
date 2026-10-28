# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Demo pack: Bostadskvarter Hisingen - Goeteborg (Residential, Gothenburg)
# ---------------------------------------------------------------------------
# Residential project on Hisingen, Gothenburg. Structured by BSAB elements,
# specified to AMA Hus, contracted under AB 04. Rates are Gothenburg 2026
# market levels in SEK excluding moms.
#
# Gothenburg sits on soft Goeta aelv clay, and the Hisingen side is
# particularly challenging: settlement-sensitive ground that requires
# friction piles or lime-cement columns rather than end-bearing piles to
# rock. The foundation section reflects this.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-gothenburg",
    project_name="Bostadskvarter Hisingen - Goeteborg (Residential Quarter, Gothenburg Hisingen)",
    project_description=(
        "Nybyggnad av bostadskvarter paa Hisingen, Goeteborg. Fyra huskroppar med "
        "totalt 96 laegenheter, 6 vaaningar plus kallare. Bruttoarea cirka 12 800 m2. "
        "Betongstomme med prefabricerade vaeggar och bjoerklagselement. "
        "Fjaerrvaaerme, FTX-ventilation, solceller 120 kWp. "
        "Byggkostnad cirka 385 MSEK exklusive moms. "
        "New-build residential quarter on Hisingen, Gothenburg. Four buildings with "
        "96 apartments, 6 storeys plus basement. GFA approx. 12,800 m2. "
        "Concrete frame with precast walls and floor elements. District heating, "
        "mechanical ventilation with heat recovery, 120 kWp PV. "
        "Construction cost approx. SEK 385M excluding VAT."
    ),
    region="SE",
    classification_standard="bsab",
    currency="SEK",
    locale="sv",
    address={
        "street": "Lundbyleden 18",
        "city": "Gothenburg",
        "postcode": "417 63",
        "country": "Sweden",
        "lat": 57.7180,
        "lng": 11.9365,
    },
    validation_rule_sets=["boq_quality", "project_completeness"],
    project_code="GBG-HIS-2026-01",
    boq_name="Kalkyl BSAB - prislaege Goeteborg 2026 (Cost Estimate, BSAB classification)",
    boq_description=(
        "Kalkyl uppstaelld efter BSAB-systemet med enhetspriser per byggnadsdel. "
        "Prislaege Goeteborg foersta kvartalet 2026, exklusive moms. "
        "Cost estimate structured by BSAB elements. "
        "Gothenburg Q1 2026 price level, excluding VAT."
    ),
    boq_metadata={
        "standard": "BSAB 96 elementindelning",
        "phase": "Systemhandling - kalkyl (Detailed design estimate)",
        "base_date": "2026-Q1",
        "price_level": "Goeteborg 2026, exklusive moms",
    },
    sections=[
        # -- 01 Mark och grundlaeggning (Site and foundations) --
        (
            "01",
            "01 Mark och grundlaeggning (Site and foundations)",
            {"bsab": "1", "din276": "310"},
            [
                ("01.1", "Roejning och markberedning (Site clearance and preparation)", "m2", 4200, 125.00, {"bsab": "1.1", "din276": "212"}),
                ("01.2", "Kalk-cementpelare KC-pelare, markfoerstaerkning lera (Lime-cement columns, ground improvement in clay)", "m", 12500, 285.00, {"bsab": "1.2", "din276": "319"}),
                ("01.3", "Schakt och fyllning, lermoraan (Excavation and fill, clay moraine)", "m3", 6500, 145.00, {"bsab": "1.2", "din276": "311"}),
                ("01.4", "Slagna betongpaaalar 270x270 mm, friktionspaaalar (Driven concrete piles 270x270 mm, friction piles)", "m", 8500, 485.00, {"bsab": "1.3", "din276": "323"}),
                ("01.5", "Paalplattor och grundbalkar (Pile caps and ground beams)", "m3", 520, 6800.00, {"bsab": "1.3", "din276": "322"}),
                ("01.6", "Bottenplatta betong 200 mm paa isolering (Ground slab 200 mm on insulation)", "m2", 3200, 1350.00, {"bsab": "1.4", "din276": "324"}),
                ("01.7", "Kallarvaeggar prefab betong 200 mm (Basement walls, precast concrete 200 mm)", "m2", 2800, 2250.00, {"bsab": "1.4", "din276": "331"}),
                ("01.8", "Draanering och dagvattenhantering (Drainage and stormwater management)", "m", 850, 985.00, {"bsab": "1.5", "din276": "313"}),
                ("01.9", "Tillfaellig byggvaeg och tillfart (Temporary site road and access)", "m2", 1200, 285.00, {"bsab": "1.1", "din276": "220"}),
                ("01.10", "Paalbelastningsprov (Pile load testing)", "st", 8, 45000.00, {"bsab": "1.3", "din276": "329"}),
                ("01.11", "Yttre VA-ledningar och dagvattenmagasin (External drainage and stormwater attenuation)", "m", 620, 1250.00, {"bsab": "1.5", "din276": "550"}),
            ],
        ),
        # -- 02 Baerande konstruktion (Primary structure) --
        (
            "02",
            "02 Baerande konstruktion (Primary structure)",
            {"bsab": "2", "din276": "300"},
            [
                ("02.1", "Prefab betongvaeggar baerande 200 mm (Precast loadbearing concrete walls 200 mm)", "m2", 8500, 1850.00, {"bsab": "2.1", "din276": "341"}),
                ("02.2", "Prefab betongbjoerklag HDF 200 mm (Precast concrete floor slabs HDF 200 mm)", "m2", 11500, 1150.00, {"bsab": "2.2", "din276": "351"}),
                ("02.3", "Platsgjutna betongvaeggar trapphus och hisschakt (In-situ concrete walls, stairwells and lift shafts)", "m3", 580, 11500.00, {"bsab": "2.3", "din276": "341"}),
                ("02.4", "Armering B500B (Reinforcement B500B)", "ton", 285, 16500.00, {"bsab": "2.1", "din276": "300"}),
                ("02.5", "Prefab betongtrappor (Precast concrete stairs)", "st", 48, 32000.00, {"bsab": "2.4", "din276": "351"}),
                ("02.6", "Balkonger prefab betong med raecken (Precast concrete balconies with railings)", "st", 192, 45000.00, {"bsab": "2.5", "din276": "351"}),
                ("02.7", "Platsgjuten betong, diverse kompletteringar (In-situ concrete, miscellaneous)", "m3", 280, 9500.00, {"bsab": "2.1", "din276": "300"}),
                ("02.8", "Staalinfaestningar och ingjutningsgods (Steel fixings and cast-in items)", "ton", 18, 28500.00, {"bsab": "2.1", "din276": "341"}),
                ("02.9", "Bjaealklagskomplettering vid trapphus och installationsschakt (Floor slab completion at stairs and risers)", "m2", 850, 1850.00, {"bsab": "2.2", "din276": "351"}),
            ],
        ),
        # -- 03 Yttervaeggar och tak (External walls and roof) --
        (
            "03",
            "03 Yttervaeggar och tak (External walls and roof)",
            {"bsab": "3", "din276": "330"},
            [
                ("03.1", "Yttervaggsisolering mineralull 250 mm med putsad fasad (External wall insulation, mineral wool 250 mm with rendered facade)", "m2", 5800, 2450.00, {"bsab": "3.1", "din276": "335"}),
                ("03.2", "Foenster aluminium/trae, treglas U 0,9 (Windows, aluminium/timber, triple glazing U 0.9)", "m2", 2200, 5500.00, {"bsab": "3.2", "din276": "334"}),
                ("03.3", "Entreportaler och porttelefon (Entrance doors and intercom)", "st", 8, 85000.00, {"bsab": "3.3", "din276": "344"}),
                ("03.4", "Balkongdoerrar, treglas med laag troeskel (Balcony doors, triple-glazed, low threshold)", "st", 192, 18500.00, {"bsab": "3.2", "din276": "334"}),
                ("03.5", "Taktaeckning tvaalags papp, isolering U 0,10 (Roof covering, two-layer bituminous, insulation U 0.10)", "m2", 3200, 1250.00, {"bsab": "3.5", "din276": "363"}),
                ("03.6", "Takavvattning, stuprinnor och bruennar (Roof drainage, downpipes and gullies)", "m", 480, 585.00, {"bsab": "3.5", "din276": "364"}),
                ("03.7", "Taakraecken och saekerhetsanordningar (Roof railings and fall arrest)", "m", 280, 2850.00, {"bsab": "3.5", "din276": "369"}),
                ("03.8", "Sockelisolering och sockelbeklaeadnad (Plinth insulation and cladding)", "m", 420, 1650.00, {"bsab": "3.1", "din276": "327"}),
                ("03.9", "Fasadfogar och fogmassor (Facade joints and sealants)", "m", 1800, 185.00, {"bsab": "3.1", "din276": "335"}),
                ("03.10", "Plaaattak tillbehoer, takstegar och snoerasskydd (Roof accessories, ladders and snow guards)", "m", 320, 585.00, {"bsab": "3.5", "din276": "369"}),
                ("03.11", "Ventilerade fasadpartier vid garage och teknikrum (Ventilated facade zones at garage and plant rooms)", "m2", 450, 1850.00, {"bsab": "3.1", "din276": "335"}),
            ],
        ),
        # -- 04 Innervaeggar och inredning (Internal walls and fit-out) --
        (
            "04",
            "04 Innervaeggar och inredning (Internal walls and fit-out)",
            {"bsab": "4", "din276": "340"},
            [
                ("04.1", "Laaegenhetsskiljande vaeggar 250 mm, ljudklass B (Party walls 250 mm, sound class B)", "m2", 4800, 1450.00, {"bsab": "4.1", "din276": "342"}),
                ("04.2", "Innervaeggar laegenheter gips paa reglar (Apartment internal walls, plasterboard on studs)", "m2", 8500, 685.00, {"bsab": "4.1", "din276": "342"}),
                ("04.3", "Innerdoerrar laegenheter inkl. brand EI 30 (Apartment doors including EI 30 fire doors)", "st", 650, 8500.00, {"bsab": "4.2", "din276": "344"}),
                ("04.4", "Golvbelaggning parkett, klinker och plastmatta (Floor finishes, parquet, ceramic and vinyl)", "m2", 9600, 585.00, {"bsab": "4.3", "din276": "353"}),
                ("04.5", "Undertak vaatrum och allmaanna utrymmen (Suspended ceilings to wet rooms and common areas)", "m2", 3200, 485.00, {"bsab": "4.4", "din276": "354"}),
                ("04.6", "Vaggbeklaeadnad och maaalning (Wall finishes and painting)", "m2", 24000, 185.00, {"bsab": "4.5", "din276": "345"}),
                ("04.7", "Koek komplett med vitvaror, baenkskivor och skaaap (Kitchens complete with appliances, worktops and cabinets)", "st", 96, 125000.00, {"bsab": "4.6", "din276": "381"}),
                ("04.8", "Badrum komplett kakel, klinker, sanitet och blandare (Bathrooms complete with tiles, sanitary ware and fittings)", "st", 120, 95000.00, {"bsab": "4.6", "din276": "381"}),
                ("04.9", "Trapphus ytskikt, raecken och belysning (Stairwell finishes, railings and lighting)", "st", 8, 285000.00, {"bsab": "4.7", "din276": "345"}),
                ("04.10", "Tvaettstuga komplett inredning (Laundry room complete fit-out)", "st", 4, 185000.00, {"bsab": "4.6", "din276": "381"}),
                ("04.11", "Foerraadsutrymen inkl. doerrar och belysning (Storage rooms with doors and lighting)", "st", 96, 12500.00, {"bsab": "4.6", "din276": "381"}),
                ("04.12", "Ljudisolering laaegenhetsskiljande konstruktioner (Acoustic insulation to separating elements)", "m2", 2400, 285.00, {"bsab": "4.1", "din276": "342"}),
                ("04.13", "Vaatrumsmattor och taetskikt (Wet room membranes and tanking)", "m2", 1800, 485.00, {"bsab": "4.3", "din276": "353"}),
            ],
        ),
        # -- 05 VVS-installationer (Mechanical services) --
        (
            "05",
            "05 VVS-installationer (Mechanical services)",
            {"bsab": "5", "din276": "400"},
            [
                ("05.1", "Fjaerrvaaermeundercentral (District heating substation)", "st", 4, 485000.00, {"bsab": "5.1", "din276": "421"}),
                ("05.2", "Vaarmeledningar och radiatorer (Heating pipework and radiators)", "st", 96, 32000.00, {"bsab": "5.1", "din276": "422"}),
                ("05.3", "FTX-ventilation med vaermeaaatervinning 80% (Mechanical ventilation with 80% heat recovery)", "st", 4, 650000.00, {"bsab": "5.4", "din276": "432"}),
                ("05.4", "Ventilationskanaler och don (Ductwork and terminals)", "m2", 12800, 385.00, {"bsab": "5.4", "din276": "431"}),
                ("05.5", "Tappvatten kall och varm, stamsystem (Potable water risers, hot and cold)", "laaegenhet", 96, 28500.00, {"bsab": "5.5", "din276": "412"}),
                ("05.6", "Spillvatten och dagvatten, stamsystem och serviser (Drainage risers and external connections)", "laaegenhet", 96, 18500.00, {"bsab": "5.6", "din276": "411"}),
                ("05.7", "Vaarmepump fraan fraaanluften 4 st (Exhaust air heat pumps, 4 units)", "st", 4, 285000.00, {"bsab": "5.1", "din276": "421"}),
                ("05.8", "Golvvaarme badrum (Underfloor heating to bathrooms)", "m2", 720, 585.00, {"bsab": "5.1", "din276": "422"}),
                ("05.9", "Brandspjaell och genomfoeringar (Fire dampers and penetration seals)", "st", 480, 1850.00, {"bsab": "5.4", "din276": "431"}),
                ("05.10", "Styr- och oevervakning, injustering (BMS, controls and balancing)", "post", 1, 850000.00, {"bsab": "5.8", "din276": "480"}),
                ("05.11", "Koeeksventilation och imsugare (Kitchen ventilation and extractor hoods)", "st", 96, 8500.00, {"bsab": "5.4", "din276": "431"}),
            ],
        ),
        # -- 06 El-installationer (Electrical services) --
        (
            "06",
            "06 El-installationer (Electrical services)",
            {"bsab": "6", "din276": "440"},
            [
                ("06.1", "Elcentral och matning fraan naet (Main distribution and supply)", "post", 1, 1250000.00, {"bsab": "6.1", "din276": "441"}),
                ("06.2", "Elinstallation per laaegenhet inkl. gruppcentral (Electrical installation per apartment with consumer unit)", "laaegenhet", 96, 85000.00, {"bsab": "6.2", "din276": "444"}),
                ("06.3", "Allmaen belysning trapphus, garage och utemiljoe (Common area lighting, stairs, garage and external)", "post", 1, 1450000.00, {"bsab": "6.3", "din276": "445"}),
                ("06.4", "Brandlarmanlaaeggning och utrymningslarm (Fire detection and evacuation alarm)", "m2", 12800, 185.00, {"bsab": "6.5", "din276": "456"}),
                ("06.5", "Passagesystem och porttelefon (Access control and intercom)", "post", 1, 950000.00, {"bsab": "6.5", "din276": "456"}),
                ("06.6", "Solcellsinstallation tak 120 kWp (Rooftop PV installation 120 kWp)", "kWp", 120, 7800.00, {"bsab": "6.1", "din276": "442"}),
                ("06.7", "Hissar 4 st personhiss (Passenger lifts, 4 units)", "st", 4, 1050000.00, {"bsab": "6.6", "din276": "461"}),
                ("06.8", "Laddplatser elbilar garage 48 st (EV charging points, 48 units)", "st", 48, 32000.00, {"bsab": "6.2", "din276": "444"}),
                ("06.9", "Fiber- och bredbandsnaat till laegenheter (Fibre broadband to apartments)", "laaegenhet", 96, 8500.00, {"bsab": "6.4", "din276": "451"}),
                ("06.10", "Noedbelysning och utrymningsskyltar (Emergency lighting and exit signage)", "post", 1, 485000.00, {"bsab": "6.3", "din276": "446"}),
                ("06.11", "Jordfelsskydd och aaskskydd (Earth fault protection and lightning protection)", "post", 1, 385000.00, {"bsab": "6.1", "din276": "446"}),
            ],
        ),
        # -- 07 Mark och utemiljoe (External works) --
        (
            "07",
            "07 Mark och utemiljoe (External works)",
            {"bsab": "7", "din276": "500"},
            [
                ("07.1", "Innergaard, markbelaaeggning och plantering (Courtyard paving and planting)", "m2", 2800, 1250.00, {"bsab": "7.3", "din276": "530"}),
                ("07.2", "Lekplats enligt BFS 2011:5 (Playground to BFS 2011:5)", "post", 1, 850000.00, {"bsab": "7.3", "din276": "570"}),
                ("07.3", "Sopsuganlaeggning eller sooprum (Waste collection system or bin stores)", "post", 1, 1250000.00, {"bsab": "7.4", "din276": "382"}),
                ("07.4", "Cykelfoerraad och cykelstaell 192 platser (Cycle stores and racks, 192 spaces)", "st", 192, 4500.00, {"bsab": "7.2", "din276": "382"}),
                ("07.5", "Markledningar, VA-anslutningar och utebelysning (External services and site lighting)", "post", 1, 2450000.00, {"bsab": "7.4", "din276": "550"}),
                ("07.6", "Bullerskydd och avskaaermning mot Lundbyleden (Noise barriers toward Lundbyleden)", "m", 180, 8500.00, {"bsab": "7.5", "din276": "539"}),
                ("07.7", "Garage ramper och saekerhetsanordningar (Garage ramps and safety equipment)", "post", 1, 485000.00, {"bsab": "7.2", "din276": "382"}),
                ("07.8", "Miljoestation och aaatervinningsrum (Recycling station and environmental room)", "post", 1, 385000.00, {"bsab": "7.4", "din276": "382"}),
                ("07.9", "Staengsel och grindar (Fencing and gates)", "m", 280, 1250.00, {"bsab": "7.3", "din276": "530"}),
                ("07.10", "Dagvattenmagasin och foerdroejning (Stormwater attenuation)", "post", 1, 485000.00, {"bsab": "7.4", "din276": "550"}),
                ("07.11", "Gemensamma foerraadsutrymmen (Common storage rooms)", "st", 4, 85000.00, {"bsab": "7.1", "din276": "381"}),
                ("07.12", "Uteplats med moebleringszon och grillplats (Outdoor amenity with BBQ area)", "post", 1, 285000.00, {"bsab": "7.3", "din276": "570"}),
                ("07.13", "Byggstaeadning slutstaeadning (Final clean)", "m2", 12800, 35.00, {"bsab": "7.9", "din276": "381"}),
                ("07.14", "Relationshandlingar (As-built drawings)", "post", 1, 385000.00, {"bsab": "7.9", "din276": "381"}),
            ],
        ),
    ],
    markups=[
        ("Arbetsplatsomkostnader, APO (Site overheads and preliminaries 10%)", 10.0, "overhead", "direct_cost"),
        ("Centraladministration, CA (Head-office overheads 5%)", 5.0, "overhead", "cumulative"),
        ("Foersakring och garanti (Insurance and bond 0,5%)", 0.5, "insurance", "cumulative"),
        ("Vinst och risk (Profit and risk 4,5%)", 4.5, "profit", "cumulative"),
        ("Moms 25 procent (Swedish VAT at 25 percent)", 25.0, "tax", "cumulative"),
    ],
    total_months=24,
    tender_name="Generalentreprenad bostaeaeder (Main contract, residential)",
    tender_companies=[
        ("Hisingen Bostad AB", "anbud@hisingenbostad.example", 0.97),
        ("Goeteborg Bostadsbyggare", "offert@gbgbostad.example", 1.02),
        ("Vaestsvensk Entreprenad AB", "tender@vastsvensk-ent.example", 1.01),
    ],
    schedule_activities=[
        ("Etablering och markarbeten (Site setup and enabling)", "2026-03-02", "2026-05-29"),
        ("Grundfoerstaerkning och paalning (Ground improvement and piling)", "2026-04-15", "2026-08-31"),
        ("Grundlaeggning och kallare (Foundations and basement)", "2026-07-01", "2026-11-30"),
        ("Stomme hus 1-2 (Frame, buildings 1-2)", "2026-10-01", "2027-03-31"),
        ("Stomme hus 3-4 (Frame, buildings 3-4)", "2027-01-03", "2027-06-30"),
        ("Fasad och tak (Facade and roof)", "2027-03-01", "2027-09-30"),
        ("VVS och el (M&E installation)", "2027-05-01", "2027-11-30"),
        ("Inredning och ytskikt (Fit-out and finishes)", "2027-07-01", "2028-01-31"),
        ("Mark och utemiljoe (External works)", "2027-10-01", "2028-02-28"),
        ("Slutbesiktning och oeverlaamning (Final inspection and handover)", "2028-01-03", "2028-02-28"),
    ],
    project_metadata={
        "address": "Lundbyleden 18, 417 63 Goeteborg, Sverige",
        "client": "Hisingen Bostadsfoerening (Hisingen Housing Association)",
        "architect": "Arkitektkontoret Alvsborg (Alvsborg Architects)",
        "structural_engineer": "Konstruktoersbyraaan Vaest (Western Structural Engineers)",
        "services_engineer": "VVS-Konsult Goeteborg AB (Gothenburg M&E Consultants)",
        "gfa_m2": 12800,
        "storeys": "6 vaaningar plus kallare (6 storeys plus basement)",
        "apartments": 96,
        "contract": "AB 04, generalentreprenad med fast pris (General contracting under AB 04, lump sum)",
    },
    budget_boq_name="Kalkyl bostadskvarter Hisingen (Residential Quarter Cost Estimate)",
    planned_budget=385000000.0,
    actual_spend_ratio=0.42,
    spi_override=0.96,
    cpi_override=1.02,
)
