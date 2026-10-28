# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Demo pack: Kantoorgebouw Zuidas - Amsterdam (Office Building, Amsterdam)
# ---------------------------------------------------------------------------
# A Dutch begroting is organised by element, not by trade, and it separates
# the direct construction cost from three named uplifts that every Dutch
# estimator reads in the same order: algemene bouwplaatskosten (site
# overheads), algemene kosten (head-office overheads) and winst en risico
# (profit and risk). The markup block below follows that order and that
# cascade, then BTW at 21 percent on the running total, which is the rate
# a new-build office carries.
#
# TWO CLASSIFICATION KEYS, AND WHY. The Netherlands has no native
# cost-group standard in the product, so the country table in
# app/core/classification_registry.py maps NL to DIN 276 as the nearest
# hierarchy Dutch tender documents map onto. That is a stand-in and this
# file says so rather than dressing it up: a Dutch estimator does not read
# DIN 276, they read NL/SfB elements. So every line carries both. The
# "nlsfb" key is what the local market actually reads. The "din276" key is
# what the product resolves: classification_order() returns din276 first
# for an NL project, the section-path builder looks the code up by that
# key, and a line carrying only "nlsfb" would render with no section path
# and nothing anywhere would say why. Carrying both costs nothing and
# removes the question. Do not register "nlsfb" in the registry to fix
# this; that table is keyed by country and adding a value there changes
# resolution for every country in it.
#
# WHAT IS INDICATIVE HERE, PLAINLY.
#
# Rates are Amsterdam 2026 market levels in EUR excluding BTW, built up as
# element unit rates for a Grade A Zuidas office. They are not taken from a
# published Dutch price book. They are the right order of magnitude and the
# right shape relative to each other, which is what a demo needs, but a
# kostendeskundige should replace the whole rate column with a current
# calculation before this goes anywhere near a real tender.
#
# On the NL/SfB codes: the two-digit element group before the dot is the
# part we stand behind, and it is correct per line. The two-digit
# subdivision after the dot is correctly shaped but has not been verified
# line by line against the published NL/SfB table 1, so read it as "this
# element group" rather than as a citation. The DIN 276 cost groups are
# third-level codes where the line maps to one unambiguously and the group
# or top-level code where it does not, e.g. reinforcement, which spans
# several groups in one bill line.
#
# Statutory thresholds move and this file is dated. BENG 1 is quoted at its
# base value for the kantoorfunctie, before the compactness (Als/Ag)
# correction that actually sets the limit for a given massing. The MPG
# figure in the metadata is a design target, not a quoted statutory limit.
# The Wet kwaliteitsborging voor het bouwen note says only that a building
# of this size sits outside gevolgklasse 1, because the phasing for classes
# 2 and 3 has moved repeatedly and a date here would go stale. Check all
# three against the current Besluit bouwwerken leefomgeving before quoting
# any of them to a client.
#
# The substructure is deliberately heavy: sections 01 and 02 together are
# about 21 percent of the direct cost. That is not padding, that is
# Amsterdam. Loads go to the second sand layer at roughly NAP -20 m through
# soft Holocene peat and clay, the groundwater table sits within a metre of
# ground level, and a two-level basement needs a diaphragm wall, an
# underwater concrete floor and tension piles before any of the building
# above it exists. A pack that priced this like a German or British office
# would be teaching the wrong lesson about building in this city.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="office-amsterdam",
    project_name="Kantoorgebouw Zuidas - Amsterdam (Office Building, Amsterdam Zuidas)",
    project_description=(
        "Nieuwbouw van een kantoorgebouw op de Zuidas in Amsterdam, veertien bouwlagen "
        "boven maaiveld en twee kelderlagen, bouwhoogte circa 58 meter. Bruto "
        "vloeroppervlak circa 31.000 m2 gemeten volgens NEN 2580, waarvan circa 24.500 m2 "
        "boven maaiveld en 6.500 m2 in de kelder. Het gebouw wordt casco met basisafbouw "
        "opgeleverd voor meerdere huurders, met een gedeelde entree, 620 inpandige "
        "fietsparkeerplaatsen en 48 parkeerplaatsen in de kelder. Draagconstructie van in "
        "het werk gestorte betonkernen met prefab kolommen en kanaalplaatvloeren, "
        "elementengevel in aluminium met drievoudige beglazing en buitenzonwering. Warmte "
        "en koude komen uit twee WKO-doubletten met water-waterwarmtepompen, aangevuld met "
        "320 kWp zonnestroom, zodat het gebouw voldoet aan de BENG-eisen voor de "
        "kantoorfunctie. De fundering draagt via schroefinjectiepalen af op de tweede "
        "zandlaag op circa NAP -20 meter; de bouwkuip bestaat uit een diepwand met "
        "onderwaterbetonvloer en trekpalen. Directe bouwkosten circa EUR 71,0 miljoen, "
        "exclusief algemene bouwplaatskosten, algemene kosten, winst en risico en BTW. "
        "New-build office on the Zuidas in Amsterdam: fourteen storeys above ground and "
        "two basement levels, approx. 58 m tall. Gross floor area approx. 31,000 m2 "
        "measured to NEN 2580, of which approx. 24,500 m2 above ground and 6,500 m2 below. "
        "Delivered shell and core with base fit-out for multiple tenants, with a shared "
        "entrance, 620 internal cycle spaces and 48 basement parking bays. In-situ "
        "concrete cores with precast columns and hollow-core floor slabs; unitised "
        "aluminium curtain wall with triple glazing and external solar shading. Heating "
        "and cooling from two aquifer thermal energy storage doublets with water-to-water "
        "heat pumps plus 320 kWp of photovoltaics, so the building meets the BENG "
        "near-energy-neutral requirements for an office. Foundations carry to the second "
        "sand layer at roughly NAP -20 m on vibration-free screw-injection piles; the "
        "excavation is retained by a diaphragm wall with an underwater concrete floor and "
        "tension piles. Direct construction cost approx. EUR 71.0 million, excluding site "
        "overheads, head-office overheads, profit and risk, and VAT."
    ),
    region="NL",
    classification_standard="din276",
    currency="EUR",
    locale="nl",
    address={
        "street": "Gustav Mahlerlaan 62",
        "city": "Amsterdam",
        "postcode": "1082 MC",
        "country": "Netherlands",
        "lat": 52.3376,
        "lng": 4.8730,
    },
    validation_rule_sets=["boq_quality", "project_completeness"],
    project_code="AMS-ZAS-2026-01",
    boq_name="Elementenbegroting NL/SfB - prijspeil Amsterdam 2026 (Element Cost Plan)",
    boq_description=(
        "Elementenbegroting op basis van de NL/SfB-elementenmethode, opgebouwd uit directe "
        "bouwkosten per element. Algemene bouwplaatskosten, algemene kosten en winst en "
        "risico zijn als afzonderlijke opslagen opgenomen, volgens de kostenindeling van "
        "NEN 2699. Prijspeil Amsterdam eerste kwartaal 2026, exclusief BTW. "
        "Element cost plan on NL/SfB elements, made up of direct construction cost per "
        "element. Site overheads, head-office overheads and profit and risk are carried as "
        "separate uplifts per the NEN 2699 cost breakdown. Amsterdam Q1 2026 price level, "
        "excluding VAT."
    ),
    boq_metadata={
        "standard": "NL/SfB elementenmethode; kostenindeling NEN 2699",
        "phase": "Definitief ontwerp - directiebegroting (Detailed design, client control estimate)",
        "base_date": "2026-Q1",
        "price_level": "Amsterdam 2026, exclusief BTW",
        "pricing_method": "Elementenraming met eenheidsprijzen per element",
        "measurement": "NEN 2580 (BVO, VVO)",
    },
    sections=[
        # ── 01 Voorbereiding, bouwkuip en grondwerk ──────────────────
        (
            "01",
            "01 Voorbereiding, bouwkuip en grondwerk (Enabling works, shoring and excavation)",
            {"nlsfb": "11", "din276": "310"},
            [
                ("01.1", "Opruimen terrein, verwijderen verharding en beplanting (Site clearance, paving and planting removal)", "m2", 4100, 18.50, {"nlsfb": "90.10", "din276": "212"}),
                ("01.2", "Bodem-, milieu- en explosievenonderzoek, archeologische begeleiding (Ground, environmental and unexploded-ordnance survey, archaeological watching brief)", "post", 1, 185000.00, {"nlsfb": "11.00", "din276": "319"}),
                ("01.3", "Bouwkundige vooropname belendingen, trillings- en zakkingsmonitoring (Pre-construction condition survey of adjoining buildings, vibration and settlement monitoring)", "mnd", 18, 12500.00, {"nlsfb": "11.00", "din276": "319"}),
                ("01.4", "Verleggen kabels en leidingen, tijdelijke nutsaansluitingen (Utility diversions and temporary connections)", "m", 320, 485.00, {"nlsfb": "90.50", "din276": "220"}),
                ("01.5", "Diepwand 800 mm tot NAP -28 m als bouwkuipwand (Diaphragm wall 800 mm to NAP -28 m as pit retention)", "m2", 6900, 465.00, {"nlsfb": "11.20", "din276": "312"}),
                ("01.6", "Stempelraam en groutankers bouwkuip (Propping frame and ground anchors to the excavation)", "post", 1, 1850000.00, {"nlsfb": "11.20", "din276": "312"}),
                ("01.7", "Ontgraven bouwput twee kelderlagen incl. afvoer grond (Bulk excavation, two basement levels, including disposal)", "m3", 26000, 38.50, {"nlsfb": "11.10", "din276": "311"}),
                ("01.8", "Afvoer en verwerking verontreinigde grond, klasse industrie (Disposal and treatment of contaminated soil, industrial class)", "m3", 3200, 78.00, {"nlsfb": "11.10", "din276": "213"}),
                ("01.9", "Bemaling en beheersing waterbezwaar bouwput (Dewatering and groundwater control to the excavation)", "mnd", 12, 32000.00, {"nlsfb": "11.30", "din276": "313"}),
            ],
        ),
        # ── 02 Fundering en onderbouw ────────────────────────────────
        (
            "02",
            "02 Fundering en onderbouw (Piled foundations and substructure)",
            {"nlsfb": "16", "din276": "320"},
            [
                ("02.1", "Grondverbetering en werkvloer voor de heistelling (Ground improvement and working platform for the piling rig)", "m2", 3250, 42.00, {"nlsfb": "11.10", "din276": "321"}),
                ("02.2", "Schroefinjectiepalen d 560 mm, trillingsarm, tot tweede zandlaag NAP -20 m (Screw-injection piles d 560 mm, vibration-free, to second sand layer at NAP -20 m)", "st", 268, 4850.00, {"nlsfb": "17.10", "din276": "323"}),
                ("02.3", "Trekpalen met GEWI-ankers onder onderwaterbetonvloer (Tension piles with GEWI anchors beneath the underwater concrete floor)", "st", 420, 2650.00, {"nlsfb": "17.20", "din276": "323"}),
                ("02.4", "Sloop paalkoppen en aanbrengen stekwapening (Pile head trimming and starter-bar installation)", "st", 688, 285.00, {"nlsfb": "17.10", "din276": "329"}),
                ("02.5", "Onderwaterbetonvloer 1.000 mm, C20/25, in den natte gestort (Underwater concrete floor 1,000 mm, C20/25, tremie placed)", "m2", 3250, 385.00, {"nlsfb": "13.10", "din276": "322"}),
                ("02.6", "Proefbelasting en integriteitsonderzoek palen (Pile load testing and integrity testing)", "st", 24, 6800.00, {"nlsfb": "17.10", "din276": "329"}),
                ("02.7", "Constructieve keldervloer 400 mm, C30/37, op onderwaterbeton (Structural basement slab 400 mm, C30/37, over underwater concrete)", "m2", 3250, 178.00, {"nlsfb": "13.20", "din276": "324"}),
                ("02.8", "Poeren, funderingsbalken en kernvoetplaten (Pile caps, ground beams and core base slabs)", "m3", 1180, 620.00, {"nlsfb": "16.20", "din276": "322"}),
                ("02.9", "Kelderwanden in het werk gestort 400 mm, waterdicht beton (In-situ basement walls 400 mm, watertight concrete)", "m2", 4600, 268.00, {"nlsfb": "21.10", "din276": "331"}),
                ("02.10", "Thermische isolatie en drainage kelderwanden buitenzijde (External thermal insulation and drainage to basement walls)", "m2", 4600, 68.00, {"nlsfb": "21.10", "din276": "327"}),
                ("02.11", "Kelderdek 350 mm met verkeersbelasting, incl. sparingen en putten (Basement deck 350 mm, traffic loading, including openings and pits)", "m2", 1500, 268.00, {"nlsfb": "23.10", "din276": "351"}),
                ("02.12", "Hellingbaan parkeergarage, constructief incl. slijtlaag (Car-park access ramp, structure and wearing surface)", "m2", 420, 485.00, {"nlsfb": "24.20", "din276": "324"}),
                ("02.13", "Kelderdichting, injectieslangen en voegafdichting (Basement watertightness detailing, injection hoses and joint sealing)", "m", 1850, 92.00, {"nlsfb": "13.10", "din276": "326"}),
            ],
        ),
        # ── 03 Ruwbouw en draagconstructie ───────────────────────────
        (
            "03",
            "03 Ruwbouw en draagconstructie (Superstructure and primary frame)",
            {"nlsfb": "28", "din276": "300"},
            [
                ("03.1", "Prefab betonkolommen C45/55 (Precast concrete columns C45/55)", "m3", 640, 1180.00, {"nlsfb": "28.10", "din276": "343"}),
                ("03.2", "In het werk gestorte betonkernen C35/45, glijbekisting (In-situ concrete cores C35/45, climbing formwork)", "m3", 2150, 1050.00, {"nlsfb": "28.30", "din276": "341"}),
                ("03.3", "Wapening betonconstructies bovenbouw, B500B (Reinforcement to superstructure concrete, B500B)", "ton", 1320, 1820.00, {"nlsfb": "28.10", "din276": "300"}),
                ("03.4", "Kanaalplaatvloeren 320 mm incl. constructieve druklaag (Hollow-core floor slabs 320 mm with structural topping)", "m2", 22400, 128.00, {"nlsfb": "23.10", "din276": "351"}),
                ("03.5", "Prefab betonliggers en randliggers (Precast concrete beams and edge beams)", "m3", 980, 1320.00, {"nlsfb": "28.10", "din276": "351"}),
                ("03.6", "In het werk gestorte vloerzones bij kernen en sparingen (In-situ floor zones at cores and openings)", "m2", 2100, 215.00, {"nlsfb": "23.10", "din276": "351"}),
                ("03.7", "Prefab betontrappen en bordessen (Precast concrete stairs and landings)", "st", 62, 3850.00, {"nlsfb": "24.10", "din276": "351"}),
                ("03.8", "Voegovergangen, dilataties en oplegblokken hoofddraagconstructie (Movement joints, expansion joints and bearings in the primary frame)", "m", 420, 145.00, {"nlsfb": "28.10", "din276": "359"}),
                ("03.9", "Staalconstructie dakopbouw incl. brandwerende bekleding 60 minuten (Roof plant steelwork including 60-minute fire protection)", "ton", 145, 5250.00, {"nlsfb": "27.10", "din276": "361"}),
                ("03.10", "Staalconstructie atrium en entreeluifel met glazen dakvlak (Atrium and entrance canopy steelwork with glazed roof)", "ton", 68, 6850.00, {"nlsfb": "27.10", "din276": "361"}),
            ],
        ),
        # ── 04 Gevel en dak ──────────────────────────────────────────
        (
            "04",
            "04 Gevel en dak (Facade and roof)",
            {"nlsfb": "21", "din276": "330"},
            [
                ("04.1", "Elementengevel aluminium met drievoudige beglazing HR+++ (Unitised aluminium curtain wall, triple glazing)", "m2", 7600, 985.00, {"nlsfb": "21.20", "din276": "337"}),
                ("04.2", "Gesloten geveldelen, geïsoleerde panelen Rc 4,7 (Opaque facade zones, insulated panels Rc 4.7)", "m2", 1150, 465.00, {"nlsfb": "21.20", "din276": "337"}),
                ("04.3", "Brandwerende gevelbanden en doorvalbeveiliging in de vliesgevel (Fire-resisting spandrel zones and fall-protection glazing in the curtain wall)", "m", 2400, 185.00, {"nlsfb": "21.20", "din276": "337"}),
                ("04.4", "Natuursteen plintafwerking begane grond en entreepui met tourniquet (Natural stone plinth cladding and entrance screen with revolving door)", "m2", 640, 685.00, {"nlsfb": "41.10", "din276": "335"}),
                ("04.5", "Buitenzonwering, uitwendige screens met windsensor (External solar shading screens, wind-sensor controlled)", "m2", 6200, 168.00, {"nlsfb": "21.30", "din276": "338"}),
                ("04.6", "Natuurinclusieve gevelvoorzieningen, nestkasten en verblijfplaatsen (Nature-inclusive facade provisions, nest boxes and roosting spaces)", "st", 120, 385.00, {"nlsfb": "21.30", "din276": "339"}),
                ("04.7", "Gevelonderhoudsinstallatie, gevelrail en gondel (Facade access system, roof rail and cradle)", "post", 1, 385000.00, {"nlsfb": "75.10", "din276": "339"}),
                ("04.8", "Dakbedekking tweelaags bitumineus op PIR-isolatie Rc 6,3 (Two-layer bituminous roof covering on PIR insulation Rc 6.3)", "m2", 1900, 148.00, {"nlsfb": "47.10", "din276": "363"}),
                ("04.9", "Waterbergend vegetatiedak, 60 mm berging conform hemelwaterverordening (Water-retaining green roof, 60 mm storage per the municipal stormwater by-law)", "m2", 1250, 178.00, {"nlsfb": "47.20", "din276": "363"}),
                ("04.10", "Dakranden, valbeveiliging en balustrades dakterras (Roof edges, fall arrest and roof-terrace balustrades)", "m", 440, 395.00, {"nlsfb": "34.10", "din276": "369"}),
            ],
        ),
        # ── 05 Binnenwanden, kozijnen en afbouw ──────────────────────
        (
            "05",
            "05 Binnenwanden, kozijnen en afbouw (Internal walls, door sets and finishes)",
            {"nlsfb": "22", "din276": "340"},
            [
                ("05.1", "Kalkzandsteen binnenwanden 150 mm, schachten en bergingen (Calcium-silicate internal walls 150 mm, shafts and stores)", "m2", 5800, 88.00, {"nlsfb": "22.10", "din276": "342"}),
                ("05.2", "Metalstud scheidingswanden, brandwerend 60 minuten (Metal-stud partitions, 60-minute fire rating)", "m2", 9400, 96.00, {"nlsfb": "22.20", "din276": "342"}),
                ("05.3", "Demontabele glazen systeemwanden, vergaderruimten (Demountable glazed system partitions, meeting rooms)", "m2", 3200, 285.00, {"nlsfb": "22.30", "din276": "346"}),
                ("05.4", "Binnendeurkozijnen en deuren, incl. brandwerende en rookwerende uitvoering (Internal door sets, including fire and smoke rated)", "st", 645, 1120.00, {"nlsfb": "32.20", "din276": "344"}),
                ("05.5", "Verhoogde computervloer op kantoorvloeren (Raised access floor to office floors)", "m2", 20800, 78.00, {"nlsfb": "43.20", "din276": "353"}),
                ("05.6", "Vloerafwerking tapijttegels, natuursteen en tegelwerk (Floor finishes, carpet tile, natural stone and ceramic tiling)", "m2", 21700, 62.00, {"nlsfb": "43.10", "din276": "353"}),
                ("05.7", "Gietvloer parkeergarage, fietsenstalling en technische ruimten (Resin flooring to car park, cycle store and plant rooms)", "m2", 4200, 58.00, {"nlsfb": "43.30", "din276": "353"}),
                ("05.8", "Systeemplafonds minerale wol met akoestische eis (Mineral-wool suspended ceilings, acoustic specification)", "m2", 21400, 58.00, {"nlsfb": "45.10", "din276": "354"}),
                ("05.9", "Akoestische plafondeilanden en absorptiepanelen kantoortuinen (Acoustic ceiling rafts and absorption panels to open-plan offices)", "m2", 4200, 145.00, {"nlsfb": "45.20", "din276": "354"}),
                ("05.10", "Wand- en plafondafwerking, spuitwerk en schilderwerk (Wall and ceiling finishes, spray plaster and painting)", "m2", 26500, 24.00, {"nlsfb": "42.10", "din276": "345"}),
            ],
        ),
        # ── 06 Werktuigbouwkundige installaties ──────────────────────
        (
            "06",
            "06 Werktuigbouwkundige installaties (Mechanical services)",
            {"nlsfb": "50", "din276": "400"},
            [
                ("06.1", "WKO-installatie, twee doubletten met bronpompen en regelput (Aquifer thermal energy storage, two doublets with well pumps and control chamber)", "st", 4, 385000.00, {"nlsfb": "51.20", "din276": "421"}),
                ("06.2", "Warmtepompen water-water 2 x 900 kW incl. piekvoorziening (Water-to-water heat pumps 2 x 900 kW with peak plant)", "st", 2, 465000.00, {"nlsfb": "51.10", "din276": "421"}),
                ("06.3", "Warmtapwaterbereiding met boosterwarmtepomp en buffervaten (Domestic hot water generation with booster heat pump and buffer vessels)", "post", 1, 285000.00, {"nlsfb": "53.20", "din276": "421"}),
                ("06.4", "Klimaatplafonds en inductie-units op kantoorvloeren (Chilled ceilings and induction units to office floors)", "m2", 20800, 62.00, {"nlsfb": "56.10", "din276": "423"}),
                ("06.5", "Koeling datavloeren en serverruimten, redundante opstelling (Cooling to data floors and server rooms, redundant configuration)", "post", 1, 465000.00, {"nlsfb": "55.10", "din276": "434"}),
                ("06.6", "Luchtbehandelingskasten met warmteterugwinning, rendement 85 procent (Air-handling units with 85 percent heat recovery)", "st", 8, 148000.00, {"nlsfb": "57.10", "din276": "432"}),
                ("06.7", "Luchtkanalen gegalvaniseerd staal incl. isolatie en roosters (Galvanised-steel ductwork including insulation and grilles)", "m2", 14500, 118.00, {"nlsfb": "57.20", "din276": "431"}),
                ("06.8", "Brandkleppen, doorvoeringen en brandwerende afdichtingen installaties (Fire dampers, penetrations and fire stopping to services)", "st", 1850, 285.00, {"nlsfb": "57.20", "din276": "431"}),
                ("06.9", "Hydraulisch leidingwerk verwarming en koeling incl. appendages (Hydronic heating and cooling pipework with valves)", "m", 9800, 96.00, {"nlsfb": "56.20", "din276": "422"}),
                ("06.10", "Leidingwaterinstallatie NEN 1006 met legionellabeheersing en sanitaire toestellen (Potable water installation to NEN 1006 with legionella control and sanitary appliances)", "st", 340, 1750.00, {"nlsfb": "53.10", "din276": "412"}),
                ("06.11", "Vuilwater- en hemelwaterafvoer incl. vertraagde afvoer (Foul and rainwater drainage with attenuated discharge)", "m", 3600, 92.00, {"nlsfb": "52.10", "din276": "411"}),
                ("06.12", "Sprinklerinstallatie volledige dekking incl. pompkamer en watervoorraad (Sprinkler installation, full coverage, with pump room and water store)", "m2", 31000, 32.00, {"nlsfb": "53.40", "din276": "412"}),
                ("06.13", "Rook- en warmteafvoer parkeergarage en overdruk trappenhuizen (Car-park smoke extract and stair pressurisation)", "post", 1, 585000.00, {"nlsfb": "57.30", "din276": "431"}),
                ("06.14", "Gebouwbeheersysteem, regeltechniek, inregelen en prestatietoets (Building management system, controls, balancing and performance testing)", "m2", 31000, 28.00, {"nlsfb": "67.10", "din276": "480"}),
            ],
        ),
        # ── 07 Elektrotechnische installaties en transport ───────────
        (
            "07",
            "07 Elektrotechnische installaties en transport (Electrical services and transport)",
            {"nlsfb": "60", "din276": "440"},
            [
                ("07.1", "Middenspanningsruimte en transformatoren 2 x 1.600 kVA (MV switch room and transformers 2 x 1,600 kVA)", "post", 1, 585000.00, {"nlsfb": "61.10", "din276": "441"}),
                ("07.2", "Hoofdverdeelinrichting, onderverdelers en noodstroomvoorziening (Main switchboard, distribution boards and standby power)", "post", 1, 785000.00, {"nlsfb": "61.20", "din276": "443"}),
                ("07.3", "Kabelgoten, hoofdtracés en verticale schachten (Cable containment, main routes and risers)", "m", 8600, 62.00, {"nlsfb": "62.10", "din276": "444"}),
                ("07.4", "Krachtstroom- en verlichtingsgroepen, bedradingsinstallatie NEN 1010 (Power and lighting final circuits, wiring installation to NEN 1010)", "m2", 31000, 42.00, {"nlsfb": "62.20", "din276": "444"}),
                ("07.5", "LED-verlichting met daglicht- en aanwezigheidsregeling (LED lighting with daylight and presence control)", "m2", 26500, 58.00, {"nlsfb": "63.10", "din276": "445"}),
                ("07.6", "Zonwering- en verlichtingssturing gekoppeld aan het gebouwbeheersysteem (Shading and lighting control integrated with the building management system)", "m2", 26500, 12.00, {"nlsfb": "63.30", "din276": "480"}),
                ("07.7", "Noodverlichting, vluchtwegaanduiding en bliksembeveiliging (Emergency lighting, escape route signage and lightning protection)", "post", 1, 345000.00, {"nlsfb": "63.20", "din276": "446"}),
                ("07.8", "PV-installatie op dak en zuidgevel, 320 kWp (Photovoltaic installation to roof and south facade, 320 kWp)", "kWp", 320, 785.00, {"nlsfb": "61.30", "din276": "442"}),
                ("07.9", "Energiemonitoring, submetering en NTA 8800-rapportage (Energy monitoring, submetering and NTA 8800 reporting)", "post", 1, 165000.00, {"nlsfb": "61.40", "din276": "480"}),
                ("07.10", "Brandmeldinstallatie en ontruimingsalarminstallatie, gecertificeerd (Certified fire detection and evacuation alarm installation)", "m2", 31000, 24.00, {"nlsfb": "65.10", "din276": "456"}),
                ("07.11", "Toegangscontrole, camerabewaking en inbraakbeveiliging (Access control, CCTV and intruder alarm)", "post", 1, 595000.00, {"nlsfb": "65.20", "din276": "456"}),
                ("07.12", "Data-infrastructuur, bekabeling en patchruimten (Structured cabling and patch rooms)", "post", 1, 585000.00, {"nlsfb": "64.10", "din276": "451"}),
                ("07.13", "Personen- en brandweerliften, 9 stuks, 1,6 m/s (Passenger and firefighting lifts, 9 units, 1.6 m/s)", "st", 9, 182000.00, {"nlsfb": "66.10", "din276": "461"}),
            ],
        ),
        # ── 08 Vaste voorzieningen en terrein ────────────────────────
        (
            "08",
            "08 Vaste voorzieningen en terrein (Fixed fittings and external works)",
            {"nlsfb": "70", "din276": "500"},
            [
                ("08.1", "Vaste inrichting entree, receptiebalie en pantry's (Fixed fittings to entrance, reception desk and pantries)", "post", 1, 385000.00, {"nlsfb": "72.10", "din276": "381"}),
                ("08.2", "Toiletgroepen, inbouwpakket compleet (Sanitary cores, complete fit-out package)", "st", 28, 24500.00, {"nlsfb": "74.10", "din276": "381"}),
                ("08.3", "Bewegwijzering, huisnummering en gevelbelettering (Wayfinding, numbering and facade signage)", "post", 1, 145000.00, {"nlsfb": "72.20", "din276": "381"}),
                ("08.4", "Inpandige fietsenstalling 620 plaatsen, rekken en toegangscontrole (Internal cycle store, 620 spaces, racks and access control)", "st", 620, 685.00, {"nlsfb": "71.10", "din276": "382"}),
                ("08.5", "Parkeervoorzieningen kelder, belijning, hoogtebegrenzing en laadpunten (Basement parking fit-out, markings, height control and EV charge points)", "st", 48, 4850.00, {"nlsfb": "71.20", "din276": "382"}),
                ("08.6", "Terreinverharding, gebakken klinkers en trottoirs (External paving, clay pavers and footways)", "m2", 2600, 145.00, {"nlsfb": "90.20", "din276": "530"}),
                ("08.7", "Terreininrichting, groen, bomen en waterberging op maaiveld (Landscaping, planting, trees and surface water storage)", "m2", 1500, 185.00, {"nlsfb": "90.40", "din276": "570"}),
                ("08.8", "Terreinleidingen, nutsaansluitingen en buitenverlichting (External services, utility connections and site lighting)", "post", 1, 385000.00, {"nlsfb": "90.50", "din276": "550"}),
            ],
        ),
    ],
    # Dutch price build-up. ABK is taken on the direct cost because site
    # overheads scale with the works themselves; AK, the insurance premium
    # and W&R are taken on the running total, which is the cascade a Dutch
    # begroting uses and the reason the order of these five lines matters.
    # BTW is 21 percent: a new-build office is not one of the reduced-rate
    # categories. Percentages are typical market levels, not negotiated
    # ones, and the ABK figure in particular moves a lot with site access,
    # which on a Zuidas plot is tight.
    markups=[
        ("Algemene bouwplaatskosten, ABK (Site overheads and preliminaries 8,5%)", 8.5, "overhead", "direct_cost"),
        ("Algemene kosten, AK (Head-office overheads 6%)", 6.0, "overhead", "cumulative"),
        ("CAR-verzekering en bankgarantie (Contractors all-risks insurance and bond 0,6%)", 0.6, "insurance", "cumulative"),
        ("Winst en risico, W&R (Profit and risk 4,5%)", 4.5, "profit", "cumulative"),
        ("BTW 21 procent (Dutch VAT at 21 percent)", 21.0, "tax", "cumulative"),
    ],
    total_months=30,
    tender_name="Hoofdaannemer bouwkundig en installaties (Main contract, building and services)",
    tender_companies=[
        ("Bouwcombinatie Amstelveld", "aanbesteding@amstelveld.example", 0.98),
        ("Noordwal Bouwgroep", "inschrijving@noordwal.example", 1.03),
        ("Van Kerkhoven Bouw en Ontwikkeling", "tender@vankerkhoven.example", 1.01),
    ],
    tender_packages=[
        (
            "Bouwkuip en fundering (Shoring and foundations)",
            "Diepwand, stempelraam, schroefinjectiepalen, trekpalen, onderwaterbeton en keldervloer.",
            "evaluating",
            [
                ("Zandlaag Funderingstechniek", "aanbesteding@zandlaag-ft.example", 0.97),
                ("Diepwerk Amstel Funderingen", "inschrijving@diepwerk.example", 1.04),
                ("Palenveld Geotechniek", "tender@palenveld.example", 1.01),
            ],
        ),
        (
            "Ruwbouw en betonconstructies (Superstructure and concrete)",
            "Betonkernen, prefab kolommen en liggers, kanaalplaatvloeren, trappen en dakstaal.",
            "evaluating",
            [
                ("Bouwcombinatie Amstelveld", "aanbesteding@amstelveld.example", 0.98),
                ("Noordwal Bouwgroep", "inschrijving@noordwal.example", 1.03),
                ("Van Kerkhoven Bouw en Ontwikkeling", "tender@vankerkhoven.example", 1.02),
            ],
        ),
        (
            "Gevel en dak (Facade and roofing)",
            "Elementengevel, gesloten geveldelen, buitenzonwering, gevelonderhoud, dakbedekking en vegetatiedak.",
            "issued",
            [
                ("Meerhoven Gevelbouw", "aanbesteding@meerhoven-gevel.example", 0.99),
                ("Westerkade Gevelsystemen", "inschrijving@westerkade.example", 1.05),
                ("Duinvliet Aluminiumbouw", "tender@duinvliet.example", 1.02),
            ],
        ),
        (
            "Installaties werktuigbouwkundig en elektrotechnisch (Mechanical and electrical services)",
            "WKO en warmtepompen, luchtbehandeling, klimaatplafonds, sanitair, sprinkler, elektro, brandmelding en liften.",
            "evaluating",
            [
                ("Vlietstra Installatietechniek", "aanbesteding@vlietstra-it.example", 0.98),
                ("Ravenstijn Elektrotechniek", "inschrijving@ravenstijn-e.example", 1.04),
                ("Havenzand Klimaattechniek", "tender@havenzand-kt.example", 1.01),
            ],
        ),
    ],
    schedule_activities=[
        ("Bouwrijp maken en inrichten bouwplaats (Site enabling and setup)", "2026-03-02", "2026-05-29"),
        ("Diepwand en bouwkuip (Diaphragm wall and shoring)", "2026-04-01", "2026-08-31"),
        ("WKO-bronnen en energiecentrale (ATES wells and energy plant)", "2026-06-01", "2026-11-30"),
        ("Paalfundering en trekpalen (Piling and tension piles)", "2026-07-01", "2026-10-30"),
        ("Ontgraven en onderwaterbeton (Excavation and underwater concrete)", "2026-09-01", "2026-12-29"),
        ("Kelderconstructie (Basement structure)", "2026-12-01", "2027-04-30"),
        ("Ruwbouw bovenbouw (Superstructure)", "2027-03-01", "2027-11-30"),
        ("Gevel en dak (Facade and roof)", "2027-07-01", "2028-02-29"),
        ("Installaties hoofdtracés (Services, main distribution)", "2027-08-02", "2028-03-31"),
        ("Binnenwanden en kozijnen (Internal walls and door sets)", "2027-11-01", "2028-04-28"),
        ("Liften en transportinstallaties (Lifts and transport installations)", "2027-12-01", "2028-04-28"),
        ("Afbouw en afwerking (Fit-out and finishes)", "2028-01-03", "2028-06-30"),
        ("Terreininrichting en fietsenstalling (External works and cycle store)", "2028-03-01", "2028-06-30"),
        ("Inregelen, BENG-verificatie en oplevering (Commissioning, BENG verification and handover)", "2028-05-01", "2028-08-31"),
    ],
    project_metadata={
        "address": "Gustav Mahlerlaan 62, 1082 MC Amsterdam, Nederland",
        "client": "Zuidoever Vastgoedontwikkeling B.V. (Zuidoever Property Development)",
        "architect": "Bureau Havenlicht Architecten (Havenlicht Architects)",
        "structural_engineer": "Constructiebureau Waalsteen (Waalsteen Structural Engineers)",
        "services_engineer": "Adviesbureau Noorderhaven Installaties (Noorderhaven Building Services)",
        "quantity_surveyor": "Kostendeskundigen Van Rhijn en Partners (Van Rhijn and Partners, cost consultants)",
        "gfa_m2": 31000,
        "gfa_above_grade_m2": 24500,
        "gfa_basement_m2": 6500,
        "site_area_m2": 4100,
        "storeys": "14 bouwlagen boven maaiveld, 2 kelderlagen (14 storeys above ground, 2 basement levels)",
        "building_height_m": 58,
        "parking_spaces": 48,
        "cycle_spaces": 620,
        "structure_system": (
            "In het werk gestorte betonkernen met prefab betonkolommen, prefab liggers en "
            "kanaalplaatvloeren; staalconstructie voor de dakopbouw. In-situ concrete cores "
            "with precast columns and beams and hollow-core floor slabs; steel framing to the "
            "roof plant enclosure."
        ),
        "foundation": (
            "Schroefinjectiepalen d 560 mm, trillingsarm in verband met belendingen, afdragend "
            "op de tweede zandlaag op circa NAP -20 m. Bouwkuip als diepwand tot NAP -28 m met "
            "onderwaterbetonvloer en GEWI-trekpalen; grondwaterstand ligt op circa NAP -0,4 m. "
            "Vibration-free screw-injection piles to the second sand layer at approx. NAP -20 m; "
            "diaphragm-wall excavation to NAP -28 m with underwater concrete floor and GEWI "
            "tension piles, groundwater table at approx. NAP -0.4 m."
        ),
        "construction_standards": [
            "Besluit bouwwerken leefomgeving (Bbl), technische bouwvoorschriften onder de Omgevingswet",
            "NEN-EN 1990 tot en met 1999 Eurocodes met Nationale Bijlage",
            "NEN 2580 Oppervlakten en inhouden van gebouwen (BVO, GBO, VVO)",
            "NEN 2699 Investerings- en exploitatiekosten van onroerende zaken",
            "NEN 6068 Bepaling van de weerstand tegen branddoorslag en brandoverslag (WBDBO)",
            "NEN 1006 Algemene voorschriften voor leidingwaterinstallaties",
            "NEN 1010 Veiligheidsbepalingen voor laagspanningsinstallaties",
            "NTA 8800 Bepalingsmethode energieprestatie van gebouwen",
        ],
        "estimating_method": (
            "Elementenbegroting op NL/SfB-elementen. Directe bouwkosten per element, met "
            "algemene bouwplaatskosten, algemene kosten en winst en risico als afzonderlijke "
            "opslagen volgens de kostenindeling van NEN 2699. Element-based estimate on NL/SfB "
            "elements, direct cost per element with site overheads, head-office overheads and "
            "profit and risk carried as separate uplifts per NEN 2699."
        ),
        "regulator": (
            "Gemeente Amsterdam, omgevingsvergunning onder de Omgevingswet. De bouwtechnische "
            "toets blijft bij de gemeente: een kantoorgebouw van deze omvang valt buiten "
            "gevolgklasse 1 van de Wet kwaliteitsborging voor het bouwen. Municipality of "
            "Amsterdam grants the environment permit; technical assessment stays with the "
            "municipality because a building of this size falls outside quality-assurance "
            "consequence class 1."
        ),
        "energy_performance": (
            "BENG voor de kantoorfunctie, aangetoond met NTA 8800: BENG 1 energiebehoefte "
            "ten hoogste 90 kWh/m2 per jaar als basiswaarde voor de compactheidscorrectie, "
            "BENG 2 primair fossiel energiegebruik ten hoogste 40 kWh/m2 per jaar, BENG 3 "
            "aandeel hernieuwbare energie ten minste 30 procent. Warmte en koude uit twee "
            "WKO-doubletten met water-waterwarmtepompen, 320 kWp PV op dak en zuidgevel."
        ),
        "sustainability": (
            "MPG als ontwerpdoelstelling, aan te tonen bij de vergunningaanvraag; "
            "waterbergend vegetatiedak met 60 mm berging conform de hemelwaterverordening "
            "van de gemeente Amsterdam; laadinfrastructuur op alle 48 parkeerplaatsen."
        ),
        "tenure": (
            "Eeuwigdurende erfpacht van de gemeente Amsterdam. De canon en de erfpachtafkoop "
            "zitten niet in deze bouwkosten. Perpetual municipal ground lease; ground rent and "
            "its buy-out are outside this construction cost."
        ),
        "tax_note": (
            "Eenheidsprijzen zijn exclusief BTW. Nieuwbouw van een kantoor valt onder het "
            "algemene tarief van 21 procent, dat als aparte regel is opgenomen. Unit rates are "
            "exclusive of VAT; a new-build office carries the 21 percent standard rate, shown "
            "as a separate line."
        ),
        "markup_base_note": (
            "ABK wordt genomen over de directe bouwkosten; AK, verzekering en winst en risico "
            "cascaderen over het lopende totaal, in die volgorde. Dat is de Nederlandse "
            "opbouw, en daarom is de volgorde van de opslagregels betekenisvol."
        ),
        "contract": (
            "UAV-GC 2005, geïntegreerd contract Design and Construct met vaste aanneemsom. "
            "Design and build under the Dutch integrated contract conditions, lump sum."
        ),
    },
    budget_boq_name="Directiebegroting - elementenraming (Client Control Budget)",
    planned_budget=85900000.0,
    actual_spend_ratio=0.38,
    spi_override=0.97,
    cpi_override=1.01,
)
