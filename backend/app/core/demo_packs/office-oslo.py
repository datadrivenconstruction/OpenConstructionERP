# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Demo pack: Kontorbygg Bjoervika - Oslo (Office Building, Oslo)
# ---------------------------------------------------------------------------
# A Norwegian kalkyle is organised by NS 3451 building element codes, specified
# to NS 3420, and contracted under NS 8405 (general) or NS 8407 (design-build).
# Tax is 25% merverdiavgift (MVA). Rates are Oslo 2026 market levels in NOK
# excluding MVA. Norway is one of the most expensive construction markets in
# the world; unit rates reflect that.
#
# The Bjoervika area in central Oslo sits on soft marine clay overlying rock.
# A waterfront office needs deep foundations, often to bedrock, and the
# excavation through clay and fill requires significant ground retention.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="office-oslo",
    project_name="Kontorbygg Bjoervika - Oslo (Office Building, Oslo Bjoervika)",
    project_description=(
        "Nybygg av kontorbygg i Bjoervika, Oslo. Ti etasjer over bakken og en "
        "kjelleretasje. Bruttoareal cirka 16 200 m2 maalt etter NS 3940. "
        "Betongkonstruksjon med prefabrikkerte elementer, elementfasade i aluminium "
        "med trelagsglass. Fjaernvarme og fjaernkjoeling, 150 kWp solceller paa taket. "
        "Byggekostnad cirka 820 MNOK eksklusive MVA. "
        "New-build office in Bjoervika, Oslo. Ten storeys above ground and one "
        "basement level. Gross floor area approx. 16,200 m2 measured to NS 3940. "
        "Concrete frame with precast elements, unitised aluminium curtain wall with "
        "triple glazing. District heating and cooling, 150 kWp rooftop PV. "
        "Construction cost approx. NOK 820M excluding VAT."
    ),
    region="NO",
    classification_standard="ns3451",
    currency="NOK",
    locale="no",
    address={
        "street": "Dronning Eufemias gate 28",
        "city": "Oslo",
        "postcode": "0191",
        "country": "Norway",
        "lat": 59.9074,
        "lng": 10.7578,
    },
    validation_rule_sets=["boq_quality", "project_completeness"],
    project_code="OSL-BJV-2026-01",
    boq_name="Kalkyle NS 3451 - prisnivaa Oslo 2026 (Cost Estimate, NS 3451 classification)",
    boq_description=(
        "Kalkyle oppstilt etter NS 3451 bygningsdelstabell med enhetspriser per "
        "bygningsdel. Rigging og drift, administrasjonskostnader og fortjeneste som "
        "separate paalegg. Prisnivaa Oslo foerste kvartal 2026, eksklusive MVA. "
        "Cost estimate structured by NS 3451 building element table with unit rates. "
        "Site overheads, head-office overheads and profit as separate uplifts. "
        "Oslo Q1 2026 price level, excluding VAT."
    ),
    boq_metadata={
        "standard": "NS 3451 Bygningsdelstabell / NS 3453 Kostnadsoppstilling",
        "phase": "Detaljprosjekt - kalkyle (Detailed design estimate)",
        "base_date": "2026-Q1",
        "price_level": "Oslo 2026, eksklusive MVA",
        "pricing_method": "Bygningsdelskalkyle med enhetspriser",
        "measurement": "NS 3940 (BTA, BRA)",
    },
    sections=[
        # -- 2 Bygning, grunn og fundamenter (Building, ground and foundations) --
        (
            "2",
            "2 Grunn og fundamenter (Ground and foundations)",
            {"ns3451": "2", "din276": "310"},
            [
                ("2.01", "Riving og rydding av tomt (Demolition and site clearance)", "m2", 2600, 215.00, {"ns3451": "21", "din276": "212"}),
                ("2.02", "Spontsikring staalspunt til berg (Sheet piling to rock)", "m2", 2800, 1850.00, {"ns3451": "22", "din276": "312"}),
                ("2.03", "Graving og massetransport, leire (Excavation and disposal, clay)", "m3", 7200, 245.00, {"ns3451": "21", "din276": "311"}),
                ("2.04", "Pelefundamentering, borede staalpeler d 600 mm til berg (Bored steel piles d 600 mm to rock)", "m", 3600, 2850.00, {"ns3451": "23", "din276": "323"}),
                ("2.05", "Pelehoder, peleaaaser og grunnmurer (Pile caps, pile beams and foundation walls)", "m3", 580, 9800.00, {"ns3451": "23", "din276": "322"}),
                ("2.06", "Bunnplate betong 250 mm paa isolasjon (Ground slab 250 mm on insulation)", "m2", 1620, 2150.00, {"ns3451": "24", "din276": "324"}),
                ("2.07", "Kjellervegg plasstoeypt betong 350 mm, vanntett (Basement walls, in-situ concrete 350 mm, watertight)", "m2", 2200, 3650.00, {"ns3451": "24", "din276": "331"}),
                ("2.08", "Grunnvannssikring og laensepumping (Groundwater control and dewatering)", "mnd", 10, 185000.00, {"ns3451": "22", "din276": "313"}),
                ("2.09", "Geoteknisk instrumentering og overvaakning (Geotechnical instrumentation and monitoring)", "post", 1, 1250000.00, {"ns3451": "22", "din276": "319"}),
                ("2.10", "Midlertidig omlegging av kabler og ledninger (Temporary utility diversions)", "post", 1, 650000.00, {"ns3451": "21", "din276": "220"}),
                ("2.11", "Proevebelastning og integritetskontroll av peler (Pile load and integrity testing)", "st", 12, 85000.00, {"ns3451": "23", "din276": "329"}),
            ],
        ),
        # -- 3 Baeresystem (Primary structure) --
        (
            "3",
            "3 Baeresystem (Primary structure)",
            {"ns3451": "3", "din276": "300"},
            [
                ("3.01", "Betongsoeyler plasstoeypt C45/55 (In-situ concrete columns C45/55)", "m3", 480, 16500.00, {"ns3451": "32", "din276": "343"}),
                ("3.02", "Betongkjerner plasstoeypt C35/45, kjerne og trapperom (In-situ concrete cores C35/45, cores and stairwells)", "m3", 1450, 14500.00, {"ns3451": "32", "din276": "341"}),
                ("3.03", "Hulldekker HD 265 mm med paastoeyp (Hollow-core floor slabs HD 265 mm with structural topping)", "m2", 13500, 1650.00, {"ns3451": "33", "din276": "351"}),
                ("3.04", "Prefab betongbjelker og randbjelker (Precast concrete beams and edge beams)", "m3", 680, 15800.00, {"ns3451": "32", "din276": "351"}),
                ("3.05", "Armering B500NC (Reinforcement B500NC)", "tonn", 420, 22500.00, {"ns3451": "32", "din276": "300"}),
                ("3.06", "Prefab betongtrapper og repos (Precast concrete stairs and landings)", "st", 22, 55000.00, {"ns3451": "34", "din276": "351"}),
                ("3.07", "Staalkonstruksjon takoppbygg inkl. brannbeskyttelse R60 (Roof steelwork with R60 fire protection)", "tonn", 72, 42000.00, {"ns3451": "35", "din276": "361"}),
                ("3.08", "Fuger, dilatasjoner og opplagring (Joints, expansion joints and bearings)", "m", 250, 1850.00, {"ns3451": "32", "din276": "359"}),
                ("3.09", "Plasstoeypta betonggulv og paastoeyp (In-situ concrete floors and topping)", "m2", 1800, 2650.00, {"ns3451": "33", "din276": "351"}),
                ("3.10", "Staalinnstoeypningsgods og festemidler (Cast-in items and fixings)", "tonn", 24, 42000.00, {"ns3451": "32", "din276": "341"}),
            ],
        ),
        # -- 4 Yttervegger og fasade (External walls and facade) --
        (
            "4",
            "4 Yttervegger og fasade (External walls and facade)",
            {"ns3451": "4", "din276": "330"},
            [
                ("4.01", "Elementfasade aluminium med trelagsglass (Unitised aluminium curtain wall with triple glazing)", "m2", 4800, 12500.00, {"ns3451": "42", "din276": "337"}),
                ("4.02", "Tette fasadepartier, isolerte paneler U 0,15 (Opaque facade zones, insulated panels U 0.15)", "m2", 750, 6500.00, {"ns3451": "42", "din276": "337"}),
                ("4.03", "Inngangsparti naturstein og glassdoer med karusell (Entrance facade, natural stone and glass with revolving door)", "m2", 320, 10500.00, {"ns3451": "43", "din276": "335"}),
                ("4.04", "Utvendig solavskjerming, screenkaassetter med vindsensor (External solar shading, screen cassettes with wind sensor)", "m2", 3800, 2150.00, {"ns3451": "44", "din276": "338"}),
                ("4.05", "Brannmotstand i fasadebaand EI 60 (Fire-resisting spandrel zones EI 60)", "m", 1400, 2250.00, {"ns3451": "42", "din276": "337"}),
                ("4.06", "Fasadevedlikeholdsinstallasjon, bjelkebane og gondol (Facade access system, rail and cradle)", "post", 1, 3850000.00, {"ns3451": "49", "din276": "339"}),
                ("4.07", "Taktekking tolag tekking paa PIR-isolasjon U 0,13 (Two-layer bituminous roof on PIR insulation U 0.13)", "m2", 1620, 1750.00, {"ns3451": "47", "din276": "363"}),
                ("4.08", "Sedumtak med fordroeyelsemagasin 50 mm (Green roof with detention layer 50 mm)", "m2", 850, 2150.00, {"ns3451": "47", "din276": "363"}),
                ("4.09", "Takkanter, rekkverk og sikkerhetsutstyr (Roof edges, railings and fall arrest)", "m", 280, 4500.00, {"ns3451": "47", "din276": "369"}),
                ("4.10", "Taksluk og avloepssystem (Roof outlets and drainage system)", "st", 42, 6500.00, {"ns3451": "47", "din276": "364"}),
                ("4.11", "Fasadefuger og fugmasser (Facade joints and sealants)", "m", 2400, 385.00, {"ns3451": "42", "din276": "337"}),
            ],
        ),
        # -- 5 Innervegger og innredning (Internal walls and fit-out) --
        (
            "5",
            "5 Innervegger og innredning (Internal walls and fit-out)",
            {"ns3451": "5", "din276": "340"},
            [
                ("5.01", "Lette innervegger staalskinne 95 mm med gips, EI 60 (Metal stud partitions 95 mm, EI 60)", "m2", 5800, 1250.00, {"ns3451": "52", "din276": "342"}),
                ("5.02", "Glassvegger moeterom, demonterbare (Demountable glazed partitions, meeting rooms)", "m2", 1800, 4250.00, {"ns3451": "52", "din276": "346"}),
                ("5.03", "Doerer og karmer, inkl. brann- og roekdoerer (Door sets, including fire and smoke rated)", "st", 420, 15500.00, {"ns3451": "53", "din276": "344"}),
                ("5.04", "Hevet installasjonsgulv paa kontorplan (Raised access floor to office floors)", "m2", 12200, 985.00, {"ns3451": "54", "din276": "353"}),
                ("5.05", "Gulvbelegg tekstilfliser, naturstein og keramikk (Floor finishes, carpet tile, natural stone and ceramic)", "m2", 12800, 785.00, {"ns3451": "54", "din276": "353"}),
                ("5.06", "Gulvbelegg garasje og tekniske rom, epoksy (Resin flooring to garage and plant rooms)", "m2", 1620, 725.00, {"ns3451": "54", "din276": "353"}),
                ("5.07", "Himlinger mineralull med akustisk krav (Suspended ceilings, mineral wool, acoustic rated)", "m2", 12500, 725.00, {"ns3451": "55", "din276": "354"}),
                ("5.08", "Akustiske himlingsoeer og absorpsjonspaneler (Acoustic ceiling rafts and absorption panels)", "m2", 2400, 1850.00, {"ns3451": "55", "din276": "354"}),
                ("5.09", "Vegg- og himlingsoverflate, sparkling og maling (Wall and ceiling finishes, skim and paint)", "m2", 16500, 325.00, {"ns3451": "56", "din276": "345"}),
                ("5.10", "Toalettgrupper, komplett innredningspakke (Sanitary cores, complete fit-out package)", "st", 20, 385000.00, {"ns3451": "57", "din276": "381"}),
                ("5.11", "Natursteinsbelegg resepsjon og fellesarealer (Natural stone finishes, reception and common areas)", "m2", 480, 2850.00, {"ns3451": "54", "din276": "353"}),
                ("5.12", "Lydisolasjon skillevegger og installasjonssjakter (Acoustic insulation to partitions and risers)", "m2", 2800, 425.00, {"ns3451": "52", "din276": "342"}),
            ],
        ),
        # -- 6 VVS-installasjoner (Mechanical services) --
        (
            "6",
            "6 VVS-installasjoner (Mechanical services)",
            {"ns3451": "6", "din276": "400"},
            [
                ("6.01", "Fjaernvarmesentral 2 x 700 kW (District heating substation 2 x 700 kW)", "st", 2, 1650000.00, {"ns3451": "62", "din276": "421"}),
                ("6.02", "Fjaernkjoeling, vekslere og distribusjon (District cooling, heat exchangers and distribution)", "post", 1, 4850000.00, {"ns3451": "63", "din276": "423"}),
                ("6.03", "Klimahimlinger og induksjonsenheter (Chilled ceilings and induction units)", "m2", 12200, 825.00, {"ns3451": "63", "din276": "423"}),
                ("6.04", "Luftbehandlingsaggregat med varmegjenvinner 85% (Air handling units with 85% heat recovery)", "st", 5, 1850000.00, {"ns3451": "64", "din276": "432"}),
                ("6.05", "Ventilasjonskanaler galvanisert staal inkl. isolasjon (Galvanised steel ductwork with insulation)", "m2", 8500, 1450.00, {"ns3451": "64", "din276": "431"}),
                ("6.06", "Brannspjeld og gjennomfoeringer (Fire dampers and penetration seals)", "st", 1050, 3650.00, {"ns3451": "64", "din276": "431"}),
                ("6.07", "Hydronikk roersystem varme og kjoeling (Hydronic pipework, heating and cooling)", "m", 5800, 1250.00, {"ns3451": "62", "din276": "422"}),
                ("6.08", "Sanitaeranlegg, vannforsyning og legionellasikring (Sanitary, water supply and legionella control)", "st", 200, 24500.00, {"ns3451": "65", "din276": "412"}),
                ("6.09", "Spillvann og overvannsavloep (Foul and stormwater drainage)", "m", 2200, 1250.00, {"ns3451": "66", "din276": "411"}),
                ("6.10", "Sprinkleranlegg fulldekkende inkl. pumperom (Full-coverage sprinkler with pump room)", "m2", 16200, 415.00, {"ns3451": "67", "din276": "412"}),
                ("6.11", "Roeyk- og varmeventilasjon garasje og trykkavlastning trapperom (Smoke extract and stair pressurisation)", "post", 1, 4250000.00, {"ns3451": "64", "din276": "431"}),
                ("6.12", "Sentral driftskontroll, reguleringsteknikk og innregulering (BMS, controls and balancing)", "m2", 16200, 365.00, {"ns3451": "68", "din276": "480"}),
                ("6.13", "Kjoeling serverrom, redundant (Server room cooling, redundant)", "post", 1, 3650000.00, {"ns3451": "63", "din276": "434"}),
            ],
        ),
        # -- 7 Elkraft og tele (Electrical and IT services) --
        (
            "7",
            "7 Elkraft og tele (Electrical and IT services)",
            {"ns3451": "7", "din276": "440"},
            [
                ("7.01", "Hovedfordeling og transformatorer 2 x 1000 kVA (Main switchboard and transformers 2 x 1,000 kVA)", "post", 1, 7250000.00, {"ns3451": "71", "din276": "441"}),
                ("7.02", "Kabelbaner, hovedtraaseer og vertikale sjakter (Cable containment, main routes and risers)", "m", 5200, 785.00, {"ns3451": "72", "din276": "444"}),
                ("7.03", "Kraft- og lysgrupper, NEK 400 (Power and lighting circuits, NEK 400)", "m2", 16200, 525.00, {"ns3451": "72", "din276": "444"}),
                ("7.04", "LED-belysning med dagslys- og tilstedevaerelsesstyrring (LED lighting with daylight and presence control)", "m2", 13500, 725.00, {"ns3451": "73", "din276": "445"}),
                ("7.05", "Noedlys, roemningstegn og lynvern (Emergency lighting, exit signage and lightning protection)", "post", 1, 3850000.00, {"ns3451": "73", "din276": "446"}),
                ("7.06", "Solcelleanlegg tak 150 kWp (Rooftop PV installation 150 kWp)", "kWp", 150, 10500.00, {"ns3451": "71", "din276": "442"}),
                ("7.07", "Brannalarmanlegg og talevarslingsanlegg (Fire detection and voice alarm)", "m2", 16200, 315.00, {"ns3451": "75", "din276": "456"}),
                ("7.08", "Adgangskontroll, kameraovervaakning og innbruddsalarm (Access control, CCTV and intruder alarm)", "post", 1, 5850000.00, {"ns3451": "75", "din276": "456"}),
                ("7.09", "Datainfrastruktur og koblingsskap (Structured cabling and patch panels)", "post", 1, 5250000.00, {"ns3451": "74", "din276": "451"}),
                ("7.10", "Personheiser og brannmannsheiss, 6 stk, 1,6 m/s (Passenger and firefighting lifts, 6 units)", "st", 6, 2250000.00, {"ns3451": "76", "din276": "461"}),
                ("7.11", "Solskjerming og belysningsstyring koblet til SD-anlegg (Shading and lighting control linked to BMS)", "m2", 13500, 165.00, {"ns3451": "73", "din276": "480"}),
                ("7.12", "Energimonitorering og undermaaling (Energy monitoring and submetering)", "post", 1, 1650000.00, {"ns3451": "71", "din276": "480"}),
                ("7.13", "Noedstroemsaggregat diesel 500 kVA (Standby power, diesel generator 500 kVA)", "st", 1, 3250000.00, {"ns3451": "71", "din276": "443"}),
            ],
        ),
        # -- 8 Fast inventar og utomhus (Fixed fittings and external works) --
        (
            "8",
            "8 Fast inventar og utomhus (Fixed fittings and external works)",
            {"ns3451": "8", "din276": "500"},
            [
                ("8.01", "Fast innredning inngangsparti, resepsjon og tekjoeekken (Fixed fittings, entrance, reception and pantries)", "post", 1, 4850000.00, {"ns3451": "81", "din276": "381"}),
                ("8.02", "Sykkelgarasje 280 plasser, stativer og adgangskontroll (Cycle store, 280 spaces, racks and access)", "st", 280, 8500.00, {"ns3451": "82", "din276": "382"}),
                ("8.03", "Parkeringsanlegg kjeller, 28 plasser inkl. elbillading (Basement parking, 28 spaces with EV charging)", "st", 28, 65000.00, {"ns3451": "82", "din276": "382"}),
                ("8.04", "Belegningsstein og dekker paa terreng (External paving)", "m2", 1600, 1850.00, {"ns3451": "83", "din276": "530"}),
                ("8.05", "Beplantning, traer og overvannshaaandtering (Landscaping, trees and stormwater management)", "m2", 1000, 2450.00, {"ns3451": "83", "din276": "570"}),
                ("8.06", "Utomhus tekniske anlegg, VA-tilknytning og utebelysning (External services, utility connections and lighting)", "post", 1, 3850000.00, {"ns3451": "84", "din276": "550"}),
                ("8.07", "Avfallshaaandtering, kildesortering og soppunkter (Waste management and sorting points)", "post", 1, 1050000.00, {"ns3451": "84", "din276": "382"}),
                ("8.08", "Gjerder, porter og eiendosskilt (Fencing, gates and property signage)", "post", 1, 650000.00, {"ns3451": "83", "din276": "530"}),
                ("8.09", "Ladeinfrastruktur elbiler garasje 28 plasser (EV charging infrastructure, 28 spaces)", "st", 28, 55000.00, {"ns3451": "82", "din276": "382"}),
                ("8.10", "Overvannsfordroeying og fordroeyelsesbasseng (Stormwater attenuation tank)", "post", 1, 850000.00, {"ns3451": "84", "din276": "550"}),
                ("8.11", "Lagerrom bygning, doerer og ventilasjon (Building stores, doors and ventilation)", "st", 4, 165000.00, {"ns3451": "81", "din276": "381"}),
                ("8.12", "Uteterrasse med rekkverk og belysning (Outdoor terrace with railings and lighting)", "m2", 320, 3250.00, {"ns3451": "83", "din276": "570"}),
                ("8.13", "Byggrenhold sluttrengjoeering (Final clean to building)", "m2", 16200, 55.00, {"ns3451": "89", "din276": "381"}),
                ("8.14", "Som-bygget-dokumentasjon og FDV (As-built drawings and O&M manuals)", "post", 1, 1150000.00, {"ns3451": "89", "din276": "381"}),
                ("8.15", "Skilt, husnummerering og fasadebelysning (Signage, numbering and facade lighting)", "post", 1, 850000.00, {"ns3451": "81", "din276": "381"}),
            ],
        ),
    ],
    markups=[
        ("Rigging og drift av byggeplass (Site overheads and preliminaries 10%)", 10.0, "overhead", "direct_cost"),
        ("Administrasjonskostnader (Head-office overheads 5,5%)", 5.5, "overhead", "cumulative"),
        ("Forsikring og garanti (Insurance and bond 0,5%)", 0.5, "insurance", "cumulative"),
        ("Fortjeneste og risiko (Profit and risk 5%)", 5.0, "profit", "cumulative"),
        ("MVA 25 prosent (Norwegian VAT at 25 percent)", 25.0, "tax", "cumulative"),
    ],
    total_months=28,
    tender_name="Hovedentreprise bygg og installasjoner (Main contract, building and services)",
    tender_companies=[
        ("Bjoervika Bygg AS", "anbud@bjoervikabygg.example", 0.98),
        ("Oslo Entreprenoer AS", "tilbud@osloentreprenoer.example", 1.03),
        ("Fjordbygg Norden AS", "tender@fjordbygg.example", 1.01),
    ],
    tender_packages=[
        (
            "Grunn og fundamenter (Ground and foundations)",
            "Spunt, graving, peling og kjellerkonstruksjoner.",
            "evaluating",
            [
                ("Dypgrunn Geoteknikk AS", "anbud@dypgrunn.example", 0.97),
                ("Berg og Fjell Entreprenoer", "tilbud@bergfjell.example", 1.04),
                ("Pelefundament Norge AS", "tender@pelefundament.example", 1.01),
            ],
        ),
        (
            "Baeresystem og fasade (Structure and facade)",
            "Betongkjerner, hulldekker, elementfasade og tak.",
            "evaluating",
            [
                ("Bjoervika Bygg AS", "anbud@bjoervikabygg.example", 0.98),
                ("Oslo Entreprenoer AS", "tilbud@osloentreprenoer.example", 1.03),
                ("Fjordbygg Norden AS", "tender@fjordbygg.example", 1.02),
            ],
        ),
        (
            "VVS og elkraft (Mechanical and electrical services)",
            "Fjaernvarme, kjoeling, ventilasjon, elkraft, brannalarm og heiser.",
            "issued",
            [
                ("Klimapartner Oestlandet AS", "anbud@klimapartner.example", 0.99),
                ("Elektro Norden AS", "tilbud@elektronorden.example", 1.04),
                ("VVS-Teknikk Oslo AS", "tender@vvsteknikk.example", 1.01),
            ],
        ),
    ],
    schedule_activities=[
        ("Etablering og tilrigging (Site setup)", "2026-03-02", "2026-05-29"),
        ("Spunting og graving (Sheet piling and excavation)", "2026-04-01", "2026-08-31"),
        ("Peling og fundamentering (Piling and foundations)", "2026-06-01", "2026-10-30"),
        ("Kjellerkonstruksjoner (Basement structures)", "2026-09-01", "2027-01-31"),
        ("Baeresystem overbygning (Superstructure frame)", "2026-12-01", "2027-06-30"),
        ("Fasade og tak (Facade and roof)", "2027-03-01", "2027-10-31"),
        ("VVS og el, hovedtraaseer (M&E main distribution)", "2027-05-01", "2027-11-30"),
        ("Innervegger og doerer (Internal walls and doors)", "2027-07-01", "2027-12-31"),
        ("Heiser (Lifts)", "2027-08-01", "2027-12-31"),
        ("Innredning og overflater (Fit-out and finishes)", "2027-09-01", "2028-03-31"),
        ("Utomhus og terreng (External works)", "2028-01-03", "2028-04-30"),
        ("Ferdigstillelse og overtakelse (Commissioning and handover)", "2028-03-01", "2028-06-30"),
    ],
    project_metadata={
        "address": "Dronning Eufemias gate 28, 0191 Oslo, Norge",
        "client": "Bjoervika Naeringseiendom AS (Bjoervika Commercial Property)",
        "architect": "Arkitektkontoret Fjorden (Fjorden Architects)",
        "structural_engineer": "Konstruktoerene Oestlandet AS (Eastern Structural Engineers)",
        "services_engineer": "Teknisk Raadgivning Oslo AS (Oslo M&E Consultants)",
        "quantity_surveyor": "Mengdeberegning Norden AS (Norden Quantity Surveyors)",
        "gfa_m2": 16200,
        "gfa_above_grade_m2": 14600,
        "gfa_basement_m2": 1600,
        "site_area_m2": 2600,
        "storeys": "10 etasjer over bakken, 1 kjelleretasje (10 storeys above ground, 1 basement level)",
        "building_height_m": 38,
        "parking_spaces": 28,
        "cycle_spaces": 280,
        "contract": (
            "NS 8405, hovedentreprise med fastpris. General contracting under NS 8405, lump sum."
        ),
    },
    budget_boq_name="Kalkyle kontorbygg Bjoervika (Office Building Cost Estimate)",
    planned_budget=820000000.0,
    actual_spend_ratio=0.33,
    spi_override=0.97,
    cpi_override=1.02,
)
