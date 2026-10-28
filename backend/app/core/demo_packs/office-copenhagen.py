# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Demo pack: Kontorbygning Nordhavn - Koebenhavn (Office Building, Copenhagen)
# ---------------------------------------------------------------------------
# A Danish kalkulation is structured by SfB/CCS elements, specified to V&S,
# and contracted under AB 18 (general) or ABT 18 (design-build). Tax is 25%
# moms. Rates are Copenhagen 2026 market levels in DKK excluding moms.
#
# Nordhavn is Copenhagen's new harbour district, built on reclaimed land.
# Ground conditions are fill over marine clay, requiring driven piles and
# careful attention to the high water table. The foundation section reflects
# this.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="office-copenhagen",
    project_name="Kontorbygning Nordhavn - Koebenhavn (Office Building, Copenhagen Nordhavn)",
    project_description=(
        "Nybyggeri af kontorbygning i Nordhavn, Koebenhavn. Elleve etager over "
        "terrae og en kae lderetage. Bruttoetageareal cirka 17 400 m2 maalt efter "
        "DS 13000. Betonstruktur med prefabrikerede elementer, elementfacade i "
        "aluminium med trelagsglas. Fjernvarme og fjernkoeling, 160 kWp solceller "
        "paa taget. Byggeomkostninger cirka 470 MDKK eksklusiv moms. "
        "New-build office in Nordhavn, Copenhagen. Eleven storeys above ground "
        "and one basement level. Gross floor area approx. 17,400 m2 measured to "
        "DS 13000. Concrete frame with precast elements, unitised aluminium "
        "curtain wall with triple glazing. District heating and cooling, 160 kWp "
        "rooftop PV. Construction cost approx. DKK 470M excluding VAT."
    ),
    region="DK",
    classification_standard="sfb_ccs",
    currency="DKK",
    locale="da",
    address={
        "street": "Orientkaj 14",
        "city": "Copenhagen",
        "postcode": "2150",
        "country": "Denmark",
        "lat": 55.7078,
        "lng": 12.5993,
    },
    validation_rule_sets=["boq_quality", "project_completeness"],
    project_code="CPH-NHV-2026-01",
    boq_name="Byggebudget SfB - prisniveau Koebenhavn 2026 (Cost Estimate, SfB classification)",
    boq_description=(
        "Byggebudget opstillet efter SfB-bygningsdelssystemet med enhedspriser "
        "per bygningsdel. Byggepladsomkostninger, faellesomkostninger og "
        "avance som separate tillae g. Prisniveau Koebenhavn foerste kvartal "
        "2026, eksklusiv moms. "
        "Cost estimate structured by SfB building elements with unit rates. "
        "Site overheads, head-office overheads and profit as separate uplifts. "
        "Copenhagen Q1 2026 price level, excluding VAT."
    ),
    boq_metadata={
        "standard": "SfB-bygningsdelssystemet",
        "phase": "Hovedprojekt - byggebudget (Detailed design estimate)",
        "base_date": "2026-Q1",
        "price_level": "Koebenhavn 2026, eksklusiv moms",
        "pricing_method": "Bygningsdelskalkulation med enhedspriser",
        "measurement": "DS 13000 (bruttoetageareal)",
    },
    sections=[
        # -- 01 Jord og fundering (Site and foundations) --
        (
            "01",
            "01 Jord og fundering (Site and foundations)",
            {"sfb": "1", "din276": "310"},
            [
                ("01.1", "Rydning, nedrivning og jordsanering (Site clearance, demolition and remediation)", "m2", 2800, 145.00, {"sfb": "10", "din276": "212"}),
                ("01.2", "Spuns staalspuns til moraaene (Sheet piling to moraine)", "m2", 2600, 1250.00, {"sfb": "11", "din276": "312"}),
                ("01.3", "Udgravning og bortkoesel, opfyld og ler (Excavation and disposal, fill and clay)", "m3", 7500, 165.00, {"sfb": "12", "din276": "311"}),
                ("01.4", "Rammede betonpae le 300x300 mm (Driven concrete piles 300x300 mm)", "m", 6800, 485.00, {"sfb": "13", "din276": "323"}),
                ("01.5", "Pae lehoveder, punktfundamenter og fundamentsbjaelker (Pile caps, pad foundations and ground beams)", "m3", 520, 6500.00, {"sfb": "13", "din276": "322"}),
                ("01.6", "Kaeldergulv betong 200 mm paa isolering (Basement floor slab 200 mm on insulation)", "m2", 1580, 1350.00, {"sfb": "14", "din276": "324"}),
                ("01.7", "Kaeldervae gge pladstoeybt beton 300 mm, vandtae t (Basement walls, in-situ concrete 300 mm, watertight)", "m2", 2200, 2450.00, {"sfb": "14", "din276": "331"}),
                ("01.8", "Grundvandssaenkning og laensepumpning (Groundwater lowering and dewatering)", "mdr", 10, 115000.00, {"sfb": "11", "din276": "313"}),
                ("01.9", "Geoteknisk kontrol og overvaaagning (Geotechnical monitoring)", "post", 1, 650000.00, {"sfb": "11", "din276": "319"}),
                ("01.10", "Midlertidig omlaegning af ledninger og trafik (Temporary utility diversions and traffic management)", "post", 1, 425000.00, {"sfb": "10", "din276": "220"}),
                ("01.11", "Proevebelastning og integritetskontrol af pae le (Pile load and integrity testing)", "stk", 12, 55000.00, {"sfb": "13", "din276": "329"}),
            ],
        ),
        # -- 02 Baerende konstruktion (Primary structure) --
        (
            "02",
            "02 Baerende konstruktion (Primary structure)",
            {"sfb": "2", "din276": "300"},
            [
                ("02.1", "Betonsoejler pladstoeybt C45/55 (In-situ concrete columns C45/55)", "m3", 440, 10500.00, {"sfb": "21", "din276": "343"}),
                ("02.2", "Betonkaerner pladstoeybt C35/45, kaerner og trapperum (In-situ concrete cores C35/45, cores and stairwells)", "m3", 1350, 9800.00, {"sfb": "21", "din276": "341"}),
                ("02.3", "Hauldaek HD 265 mm med konstruktiv overstoeybing (Hollow-core floor slabs HD 265 mm with structural topping)", "m2", 14200, 1050.00, {"sfb": "22", "din276": "351"}),
                ("02.4", "Prefab betonbjaelker og randbjaelker (Precast concrete beams and edge beams)", "m3", 620, 11500.00, {"sfb": "21", "din276": "351"}),
                ("02.5", "Armering B500C (Reinforcement B500C)", "ton", 385, 14500.00, {"sfb": "21", "din276": "300"}),
                ("02.6", "Prefab betontrapper og reposer (Precast concrete stairs and landings)", "stk", 24, 38000.00, {"sfb": "23", "din276": "351"}),
                ("02.7", "Staalkonstruktion tagopbygning inkl. brandbeskyttelse R60 (Roof steelwork with R60 fire protection)", "ton", 68, 28500.00, {"sfb": "24", "din276": "361"}),
                ("02.8", "Fuger, dilatationer og lejer (Joints, expansion joints and bearings)", "m", 240, 1150.00, {"sfb": "21", "din276": "359"}),
                ("02.9", "Pladstoeybt beton diverse kompletteringer (In-situ concrete miscellaneous)", "m3", 165, 7800.00, {"sfb": "21", "din276": "300"}),
                ("02.10", "Staalindstoeybningsgods og befaestigelser (Cast-in items and fixings)", "ton", 22, 28500.00, {"sfb": "21", "din276": "341"}),
            ],
        ),
        # -- 03 Ydervae gge og facade (External walls and facade) --
        (
            "03",
            "03 Ydervae gge og facade (External walls and facade)",
            {"sfb": "3", "din276": "330"},
            [
                ("03.1", "Elementfacade aluminium med trelagsglas (Unitised aluminium curtain wall with triple glazing)", "m2", 4600, 7850.00, {"sfb": "31", "din276": "337"}),
                ("03.2", "Lukkede facadepartier, isolerede paneler U 0,15 (Opaque facade zones, insulated panels U 0.15)", "m2", 720, 4250.00, {"sfb": "31", "din276": "337"}),
                ("03.3", "Indgangsparti natursten og glasdoer med karuseldoer (Entrance facade, natural stone and glass with revolving door)", "m2", 300, 6850.00, {"sfb": "32", "din276": "335"}),
                ("03.4", "Udvendig solafskae rmning, screenkaassetter med vindfoeler (External solar shading, screen cassettes with wind sensor)", "m2", 3600, 1350.00, {"sfb": "33", "din276": "338"}),
                ("03.5", "Brandmoedstandsgivende facadebaand EI 60 (Fire-resisting spandrel zones EI 60)", "m", 1350, 1450.00, {"sfb": "31", "din276": "337"}),
                ("03.6", "Facadevedligeholdelsesinstallation, bjaelkebane og gondol (Facade access system, rail and cradle)", "post", 1, 2250000.00, {"sfb": "39", "din276": "339"}),
                ("03.7", "Tagtae kning tolag tagpap paa PIR-isolering U 0,12 (Two-layer bituminous roof on PIR insulation U 0.12)", "m2", 1580, 1050.00, {"sfb": "36", "din276": "363"}),
                ("03.8", "Groent tag med forsinkelse 40 mm (Green roof with detention 40 mm)", "m2", 850, 1350.00, {"sfb": "36", "din276": "363"}),
                ("03.9", "Tagkanter, raekvaerker og faldsikring (Roof edges, railings and fall arrest)", "m", 260, 2850.00, {"sfb": "36", "din276": "369"}),
                ("03.10", "Tagbroende og afvandingssystem (Roof outlets and drainage system)", "stk", 40, 4250.00, {"sfb": "36", "din276": "364"}),
                ("03.11", "Facadefuger og fugemasser (Facade joints and sealants)", "m", 2200, 265.00, {"sfb": "31", "din276": "337"}),
            ],
        ),
        # -- 04 Indervae gge og aptering (Internal walls and fit-out) --
        (
            "04",
            "04 Indervae gge og aptering (Internal walls and fit-out)",
            {"sfb": "4", "din276": "340"},
            [
                ("04.1", "Lette indervae gge staalskinne 95 mm med gips, EI 60 (Metal stud partitions 95 mm, EI 60)", "m2", 5600, 785.00, {"sfb": "41", "din276": "342"}),
                ("04.2", "Glasvae gge moedelokaler, demonterbare (Demountable glazed partitions, meeting rooms)", "m2", 1800, 2650.00, {"sfb": "41", "din276": "346"}),
                ("04.3", "Inderdoere og karme, inkl. brand- og roegdoere (Door sets, including fire and smoke rated)", "stk", 400, 9800.00, {"sfb": "42", "din276": "344"}),
                ("04.4", "Haevet installationsgulv paa kontorplan (Raised access floor to office floors)", "m2", 12800, 625.00, {"sfb": "43", "din276": "353"}),
                ("04.5", "Gulvbelaegning tekstilfliser, natursten og keramik (Floor finishes, carpet tile, natural stone and ceramic)", "m2", 13200, 485.00, {"sfb": "43", "din276": "353"}),
                ("04.6", "Gulvbelaegning parkering og teknikrum, epoxy (Resin flooring to parking and plant rooms)", "m2", 1580, 465.00, {"sfb": "43", "din276": "353"}),
                ("04.7", "Nedhae ngte lofter mineraluld med akustisk krav (Suspended ceilings, mineral wool, acoustic rated)", "m2", 12500, 465.00, {"sfb": "44", "din276": "354"}),
                ("04.8", "Akustiske loftseilande og absorptionspaneler (Acoustic ceiling rafts and absorption panels)", "m2", 2200, 1150.00, {"sfb": "44", "din276": "354"}),
                ("04.9", "Vae g- og loftsbeklae dning, spartling og maling (Wall and ceiling finishes, skim and paint)", "m2", 16500, 195.00, {"sfb": "45", "din276": "345"}),
                ("04.10", "Toiletgrupper, komplet indretningspakke (Sanitary cores, complete fit-out package)", "stk", 20, 245000.00, {"sfb": "46", "din276": "381"}),
                ("04.11", "Natursten reception og fae llesarealer (Natural stone, reception and common areas)", "m2", 420, 1850.00, {"sfb": "43", "din276": "353"}),
                ("04.12", "Lydisolering skillevae gge og installationsskakte (Acoustic insulation, partitions and risers)", "m2", 2600, 285.00, {"sfb": "41", "din276": "342"}),
            ],
        ),
        # -- 05 VVS-installationer (Mechanical services) --
        (
            "05",
            "05 VVS-installationer (Mechanical services)",
            {"sfb": "5", "din276": "400"},
            [
                ("05.1", "Fjernvarmeunit 2 x 700 kW (District heating unit 2 x 700 kW)", "stk", 2, 1050000.00, {"sfb": "51", "din276": "421"}),
                ("05.2", "Fjernkoeling, vekslere og distribution (District cooling, heat exchangers and distribution)", "post", 1, 3050000.00, {"sfb": "52", "din276": "423"}),
                ("05.3", "Koelelofter og induktionsenheder paa kontorplan (Chilled ceilings and induction units to office floors)", "m2", 12800, 525.00, {"sfb": "52", "din276": "423"}),
                ("05.4", "Ventilationsaggregater med varmegenvinding 85% (Air handling units with 85% heat recovery)", "stk", 5, 1250000.00, {"sfb": "53", "din276": "432"}),
                ("05.5", "Ventilationskanaler galvaniseret staal inkl. isolering (Galvanised steel ductwork with insulation)", "m2", 8200, 925.00, {"sfb": "53", "din276": "431"}),
                ("05.6", "Brandspjaeld og gennemfoeringer (Fire dampers and penetration seals)", "stk", 1000, 2350.00, {"sfb": "53", "din276": "431"}),
                ("05.7", "Varme- og koeleledninger inkl. ventiler (Heating and cooling pipework with valves)", "m", 5600, 785.00, {"sfb": "51", "din276": "422"}),
                ("05.8", "Brugsvandsinstallation og legionellasikring (Potable water and legionella control)", "stk", 200, 14500.00, {"sfb": "54", "din276": "412"}),
                ("05.9", "Spildevand og regnvandsafloeb (Foul and rainwater drainage)", "m", 2100, 785.00, {"sfb": "55", "din276": "411"}),
                ("05.10", "Sprinkleranlae g fuldtdae kkende inkl. pumperum (Full-coverage sprinkler with pump room)", "m2", 17400, 265.00, {"sfb": "56", "din276": "412"}),
                ("05.11", "Roeg- og varmeventilation parkering og trykavlastning trapperum (Smoke extract and stair pressurisation)", "post", 1, 2850000.00, {"sfb": "53", "din276": "431"}),
                ("05.12", "CTS-anlae g, reguleringsteknik og indregulering (BMS, controls and balancing)", "m2", 17400, 225.00, {"sfb": "57", "din276": "480"}),
                ("05.13", "Koeling serverrum, redundant (Server room cooling, redundant)", "post", 1, 2450000.00, {"sfb": "52", "din276": "434"}),
            ],
        ),
        # -- 06 El og tele (Electrical and IT services) --
        (
            "06",
            "06 El og tele (Electrical and IT services)",
            {"sfb": "6", "din276": "440"},
            [
                ("06.1", "Hovedtavle og transformatorer 2 x 1000 kVA (Main switchboard and transformers 2 x 1,000 kVA)", "post", 1, 4850000.00, {"sfb": "61", "din276": "441"}),
                ("06.2", "Kabelbaaner, hovedtraceer og vertikale skakte (Cable containment, main routes and risers)", "m", 5000, 525.00, {"sfb": "62", "din276": "444"}),
                ("06.3", "Kraft- og lysgrupper, DS/HD 60364 (Power and lighting circuits)", "m2", 17400, 325.00, {"sfb": "62", "din276": "444"}),
                ("06.4", "LED-belysning med dagslys- og tilstedevaerelsesstyrring (LED lighting with daylight and presence control)", "m2", 14200, 465.00, {"sfb": "63", "din276": "445"}),
                ("06.5", "Noedbelysning, flugtveisskilte og lynafledning (Emergency lighting, exit signage and lightning protection)", "post", 1, 2450000.00, {"sfb": "63", "din276": "446"}),
                ("06.6", "Solcelleanlaeg tag 160 kWp (Rooftop PV, 160 kWp)", "kWp", 160, 6850.00, {"sfb": "61", "din276": "442"}),
                ("06.7", "Brandalarmeringsanlae g og varslingsanlae g (Fire detection and alarm)", "m2", 17400, 195.00, {"sfb": "65", "din276": "456"}),
                ("06.8", "Adgangskontrol, videoovervaaagning og tyverialarm (Access control, CCTV and intruder alarm)", "post", 1, 3850000.00, {"sfb": "65", "din276": "456"}),
                ("06.9", "Datainfrastruktur og koblingsskap (Structured cabling and patch panels)", "post", 1, 3450000.00, {"sfb": "64", "din276": "451"}),
                ("06.10", "Personelevatorer og brandmandselevator, 6 stk, 1,6 m/s (Passenger and firefighting lifts, 6 units)", "stk", 6, 1450000.00, {"sfb": "66", "din276": "461"}),
                ("06.11", "Solafskae rmnings- og belysningsstyring koblet til CTS (Shading and lighting control linked to BMS)", "m2", 14200, 95.00, {"sfb": "63", "din276": "480"}),
                ("06.12", "Energimonitorering og undermaaling (Energy monitoring and submetering)", "post", 1, 1050000.00, {"sfb": "61", "din276": "480"}),
                ("06.13", "Noedstroemsanlae g dieselgenerator 500 kVA (Standby power, diesel generator 500 kVA)", "stk", 1, 2050000.00, {"sfb": "61", "din276": "443"}),
            ],
        ),
        # -- 07 Fast inventar og terrae n (Fixed fittings and external works) --
        (
            "07",
            "07 Fast inventar og terrae n (Fixed fittings and external works)",
            {"sfb": "7", "din276": "500"},
            [
                ("07.1", "Fast indretning foyer, reception og tekoekkener (Fixed fittings, entrance, reception and pantries)", "post", 1, 2850000.00, {"sfb": "71", "din276": "381"}),
                ("07.2", "Cykelparkering 320 pladser, stativer og adgang (Cycle parking, 320 spaces, racks and access)", "stk", 320, 5500.00, {"sfb": "72", "din276": "382"}),
                ("07.3", "Parkering kae lder, 30 pladser inkl. ladestandere (Basement parking, 30 spaces with EV chargers)", "stk", 30, 42000.00, {"sfb": "72", "din276": "382"}),
                ("07.4", "Belae gning, fliser og brostensbelae gning (External paving)", "m2", 1500, 1050.00, {"sfb": "73", "din276": "530"}),
                ("07.5", "Beplantning, trae er og regnvandshaaandtering (Landscaping, trees and stormwater management)", "m2", 950, 1450.00, {"sfb": "73", "din276": "570"}),
                ("07.6", "Udvendige ledninger, stikledninger og udebelysning (External services and site lighting)", "post", 1, 2450000.00, {"sfb": "74", "din276": "550"}),
                ("07.7", "Skiltning, husnummerering og facadebelysning (Signage, numbering and facade lighting)", "post", 1, 950000.00, {"sfb": "75", "din276": "381"}),
                ("07.8", "Affaldshaaandtering, kildesortering og affaldsskakte (Waste management and sorting)", "post", 1, 650000.00, {"sfb": "74", "din276": "382"}),
                ("07.9", "Hegn, laager og ejendomsskiltning (Fencing, gates and property signage)", "post", 1, 385000.00, {"sfb": "73", "din276": "530"}),
                ("07.10", "Ladestandere elbiler parkering 30 stk (EV chargers, 30 units)", "stk", 30, 28500.00, {"sfb": "72", "din276": "382"}),
                ("07.11", "Regnvandsbassin og forsinkelse (Stormwater attenuation tank)", "post", 1, 525000.00, {"sfb": "74", "din276": "550"}),
                ("07.12", "Opbevaringsrum bygning, doere og ventilation (Building stores, doors and ventilation)", "stk", 4, 105000.00, {"sfb": "71", "din276": "381"}),
                ("07.13", "Udendoers terrasse med raekvaerk og belysning (Outdoor terrace with railings and lighting)", "m2", 300, 2150.00, {"sfb": "73", "din276": "570"}),
                ("07.14", "Bygningsrengoering sluttrengoering (Final clean to building)", "m2", 17400, 38.00, {"sfb": "79", "din276": "381"}),
                ("07.15", "Saombygget-dokumentation og driftsinstruktioner (As-built drawings and O&M manuals)", "post", 1, 785000.00, {"sfb": "79", "din276": "381"}),
            ],
        ),
    ],
    markups=[
        ("Byggepladsomkostninger (Site overheads and preliminaries 9%)", 9.0, "overhead", "direct_cost"),
        ("Faellesomkostninger (Head-office overheads 5,5%)", 5.5, "overhead", "cumulative"),
        ("Forsikring og garanti (Insurance and bond 0,5%)", 0.5, "insurance", "cumulative"),
        ("Avance og risiko (Profit and risk 5%)", 5.0, "profit", "cumulative"),
        ("Moms 25 procent (Danish VAT at 25 percent)", 25.0, "tax", "cumulative"),
    ],
    total_months=28,
    tender_name="Hovedentreprise bygge- og installationsarbejder (Main contract, building and services)",
    tender_companies=[
        ("Nordhavn Byggeri A/S", "tilbud@nordhavnbyggeri.example", 0.98),
        ("Koebenhavns Entreprenoergruppe", "udbud@kbhentreprenoer.example", 1.03),
        ("OEresund Byg A/S", "tender@oeresundbyg.example", 1.01),
    ],
    tender_packages=[
        (
            "Jord og fundering (Ground and foundations)",
            "Spuns, udgravning, pae leramning og kae lderkonstruktioner.",
            "evaluating",
            [
                ("Dybgrund Geoteknik A/S", "tilbud@dybgrund.example", 0.97),
                ("Pae leteknik Danmark", "udbud@paeleteknik.example", 1.04),
                ("Havnefundament A/S", "tender@havnefundament.example", 1.01),
            ],
        ),
        (
            "Baerende konstruktion og facade (Structure and facade)",
            "Betonkaerner, hauldaek, elementfacade og tag.",
            "evaluating",
            [
                ("Nordhavn Byggeri A/S", "tilbud@nordhavnbyggeri.example", 0.98),
                ("Koebenhavns Entreprenoergruppe", "udbud@kbhentreprenoer.example", 1.03),
                ("OEresund Byg A/S", "tender@oeresundbyg.example", 1.02),
            ],
        ),
        (
            "VVS og el (Mechanical and electrical services)",
            "Fjernvarme, koeling, ventilation, el, brandalarm og elevatorer.",
            "issued",
            [
                ("Klimateknik OEst A/S", "tilbud@klimateknik.example", 0.99),
                ("Elinstallation Danmark A/S", "udbud@elinstallation.example", 1.04),
                ("VVS-Partner Koebenhavn", "tender@vvspartner.example", 1.01),
            ],
        ),
    ],
    schedule_activities=[
        ("Etablering og byggeplads (Site setup)", "2026-03-02", "2026-05-29"),
        ("Spunsning og udgravning (Sheet piling and excavation)", "2026-04-01", "2026-08-31"),
        ("Pae leramning og fundamenter (Piling and foundations)", "2026-06-01", "2026-10-30"),
        ("Kae lderkonstruktioner (Basement structures)", "2026-09-01", "2027-01-31"),
        ("Baerende konstruktion overbygning (Superstructure frame)", "2026-12-01", "2027-06-30"),
        ("Facade og tag (Facade and roof)", "2027-03-01", "2027-10-31"),
        ("VVS og el, hovedtraaceer (M&E main distribution)", "2027-05-01", "2027-11-30"),
        ("Indervae gge og doere (Internal walls and doors)", "2027-07-01", "2027-12-31"),
        ("Elevatorer (Lifts)", "2027-08-01", "2027-12-31"),
        ("Aptering og overflader (Fit-out and finishes)", "2027-09-01", "2028-03-31"),
        ("Terrae n og beplantning (External works)", "2028-01-03", "2028-04-30"),
        ("Ibrugtagning og aflevering (Commissioning and handover)", "2028-03-01", "2028-06-30"),
    ],
    project_metadata={
        "address": "Orientkaj 14, 2150 Nordhavn, Koebenhavn, Danmark",
        "client": "Nordhavn Erhvervsejendomme A/S (Nordhavn Commercial Property)",
        "architect": "Arkitektkontoret Havnen (Havnen Architects)",
        "structural_engineer": "Ingenioerhuset Sjae lland A/S (Sjaelland Structural Engineers)",
        "services_engineer": "Installationsraadgivning Koebenhavn A/S (Copenhagen M&E Consultants)",
        "quantity_surveyor": "Byggeoekonomi Danmark A/S (Danish Cost Consultants)",
        "gfa_m2": 17400,
        "gfa_above_grade_m2": 15800,
        "gfa_basement_m2": 1600,
        "site_area_m2": 2800,
        "storeys": "11 etager over terrae n, 1 kae lderetage (11 storeys above ground, 1 basement level)",
        "building_height_m": 40,
        "parking_spaces": 30,
        "cycle_spaces": 320,
        "contract": (
            "AB 18, hovedentreprise med fast pris. General contracting under AB 18, lump sum."
        ),
    },
    budget_boq_name="Byggebudget kontorbygning Nordhavn (Office Building Cost Estimate)",
    planned_budget=470000000.0,
    actual_spend_ratio=0.34,
    spi_override=0.97,
    cpi_override=1.01,
)
