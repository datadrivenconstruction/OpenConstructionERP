# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Renewables EPC sector pack
# Utility-scale solar PV + battery energy storage (BESS), turnkey EPC.
#
# Program:  50 MWp DC ground-mount single-axis tracker PV plant
#           (~37 MWac point of interconnection, DC/AC ratio ~1.35)
#           + 20 MWh / 10 MW lithium-iron-phosphate (LFP) BESS
#           + 33 kV / 110 kV collector + grid substation.
#
# Classification: CSI MasterFormat (electrical-utility divisions 26/33/48).
# Currency / price level: EUR, EU 2026.
# Standards: IEC 61215 / 61730 (module qualification + safety),
#            IEC 62548 / IEC 60364-7-712 (PV array design),
#            IEC 62109 (inverter safety), IEC 62619 + UL 1973 (battery),
#            NFPA 855 + UL 9540 / UL 9540A (BESS install + thermal runaway),
#            IEEE 1547 + EN 50549 (grid interconnection),
#            IEC 61936-1 / EN 50522 (HV installations & earthing).
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="solar-bess-epc",
    project_name="Solar PV + BESS Plant 50 MWp",
    project_description=(
        "Turnkey EPC of a 50 MWp DC ground-mount solar PV plant on single-axis "
        "trackers (~37 MWac point of interconnection, DC/AC ratio 1.35) co-located "
        "with a 20 MWh / 10 MW lithium-iron-phosphate (LFP) battery storage system. "
        "Site area ca. 65 ha. Bifacial PERC modules (IEC 61215/61730), string "
        "inverters, 33 kV internal collector grid stepped up to 110 kV at the grid "
        "substation. BESS to NFPA 855 / UL 9540 / IEC 62619. Estimated EPC cost "
        "ca. EUR 41 million (ca. 0.82 EUR/Wp incl. storage and grid connection)."
    ),
    region="EU",
    classification_standard="masterformat",
    currency="EUR",
    locale="en",
    address={
        "street": "Solarpark Witznitz, Bornaer Strasse",
        "city": "Borna",
        "postcode": "04552",
        "country": "Germany",
        "lat": 51.1230,
        "lng": 12.4940,
    },
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="Solar PV + BESS EPC - Cost Estimate",
    boq_description=(
        "Detailed turnkey EPC cost estimate for a 50 MWp PV + 20 MWh BESS plant, "
        "standard utility divisions (26/33/34/48), EU 2026 price level."
    ),
    boq_metadata={
        "standard": "Division-based classification (utility/electrical)",
        "phase": "EPC Detailed Estimate (FID stage)",
        "base_date": "2026-Q1",
        "price_level": "EU 2026",
    },
    sections=[
        # -- 01 Project requirements (EPC indirects) ---------------------------
        (
            "01",
            "01 - Project requirements / EPC indirects",
            {"masterformat": "01"},
            [
                ("01.001", "Project management & site supervision (EPC team)", "month", 18, 42000.00, {"masterformat": "01 31 00"}),
                ("01.002", "Engineering & detailed design (PV/BESS/HV)", "lsum", 1, 620000.00, {"masterformat": "01 33 00"}),
                ("01.003", "Owner's engineer & independent grid study", "lsum", 1, 145000.00, {"masterformat": "01 45 00"}),
                ("01.004", "Site offices, welfare & temporary facilities", "month", 18, 9500.00, {"masterformat": "01 52 00"}),
                ("01.005", "Construction power, water & temporary services", "lsum", 1, 95000.00, {"masterformat": "01 51 00"}),
                ("01.006", "Mobile cranes & heavy lift plant (hire)", "month", 12, 28000.00, {"masterformat": "01 54 00"}),
                ("01.007", "HSE management, site security & CCTV", "month", 18, 14500.00, {"masterformat": "01 35 00"}),
                ("01.008", "As-built documentation, O&M manuals & training", "lsum", 1, 78000.00, {"masterformat": "01 78 00"}),
            ],
        ),
        # -- 31 Earthwork ------------------------------------------------------
        (
            "31",
            "31 - Site Civil & Earthworks",
            {"masterformat": "31"},
            [
                ("31.001", "Topographic & geotechnical survey, pull-out tests", "lsum", 1, 68000.00, {"masterformat": "31 09 00"}),
                ("31.002", "Site clearance & vegetation strip (65 ha)", "ha", 65, 2800.00, {"masterformat": "31 11 00"}),
                ("31.003", "Bulk grading & levelling of array zones", "m3", 42000, 9.50, {"masterformat": "31 22 00"}),
                ("31.004", "Cut & fill, slope shaping and compaction", "m3", 28000, 7.20, {"masterformat": "31 23 16"}),
                ("31.005", "Stormwater swales & drainage ditches", "m", 6200, 38.00, {"masterformat": "31 25 00"}),
                ("31.006", "Erosion & sediment control, silt fencing", "m", 4800, 12.50, {"masterformat": "31 25 00"}),
                ("31.007", "Substation & BESS pad sub-base (granular)", "m3", 3400, 32.00, {"masterformat": "31 23 23"}),
                ("31.008", "Cable trenching, sand bedding & backfill", "m", 38000, 14.00, {"masterformat": "31 23 33"}),
                ("31.009", "Cable warning tape & marker posts", "m", 38000, 1.80, {"masterformat": "31 23 33"}),
            ],
        ),
        # -- 32 Exterior Improvements (roads, fencing) -------------------------
        (
            "32",
            "32 - Access Roads, Fencing & Security",
            {"masterformat": "32"},
            [
                ("32.001", "Permanent access road, granular pavement 5 m", "m2", 24000, 36.00, {"masterformat": "32 11 23"}),
                ("32.002", "Internal service tracks within array", "m2", 18000, 22.00, {"masterformat": "32 11 23"}),
                ("32.003", "Reinforced concrete entrance & turning apron", "m2", 1200, 95.00, {"masterformat": "32 13 13"}),
                ("32.004", "Perimeter security fence galv. 2.4 m incl. posts", "m", 3400, 58.00, {"masterformat": "32 31 13"}),
                ("32.005", "Double-leaf vehicle gates with access control", "pcs", 4, 6800.00, {"masterformat": "32 31 13"}),
                ("32.006", "Perimeter intrusion detection & CCTV columns", "lsum", 1, 165000.00, {"masterformat": "32 31 13"}),
                ("32.007", "Site signage, hazard & arc-flash labelling", "lsum", 1, 22000.00, {"masterformat": "32 17 23"}),
                ("32.008", "Site restoration, seeding & pollinator planting", "ha", 55, 3200.00, {"masterformat": "32 92 00"}),
            ],
        ),
        # -- 26 Earthing & LV/aux power ----------------------------------------
        (
            "26",
            "26 - Earthing, Lightning & Auxiliary Power",
            {"masterformat": "26"},
            [
                ("26.001", "Bare copper earthing conductor 70 mm2 (EN 50522)", "m", 16000, 7.80, {"masterformat": "26 05 26"}),
                ("26.002", "Earthing rods & exothermic connections", "pcs", 1800, 28.00, {"masterformat": "26 05 26"}),
                ("26.003", "Equipotential bonding of structures & frames", "lsum", 1, 86000.00, {"masterformat": "26 05 26"}),
                ("26.004", "Lightning protection & surge arresters (IEC 62305)", "lsum", 1, 124000.00, {"masterformat": "26 41 00"}),
                ("26.005", "Auxiliary LV distribution boards & UPS", "pcs", 12, 4200.00, {"masterformat": "26 24 16"}),
                ("26.006", "Auxiliary transformer 33 kV / 400 V, 250 kVA", "pcs", 2, 18500.00, {"masterformat": "26 12 00"}),
                ("26.007", "Site & security LED lighting incl. poles", "pcs", 60, 680.00, {"masterformat": "26 56 00"}),
                ("26.008", "Standby diesel genset 100 kVA (black-start aux)", "pcs", 1, 42000.00, {"masterformat": "26 32 13"}),
            ],
        ),
        # -- 34.1 Mounting structures / trackers -------------------------------
        (
            "34A",
            "34 - Mounting Structures & Single-Axis Trackers",
            {"masterformat": "34"},
            [
                ("34A.001", "Driven steel pile foundations (ramming)", "pcs", 22000, 38.00, {"masterformat": "34 71 00"}),
                ("34A.002", "Pre-drilled / screw foundations (rock zones)", "pcs", 2800, 72.00, {"masterformat": "34 71 00"}),
                ("34A.003", "Single-axis tracker torque tubes & bearings", "t", 1850, 1650.00, {"masterformat": "34 71 00"}),
                ("34A.004", "Module rails, clamps & purlins (galv. steel)", "t", 720, 1480.00, {"masterformat": "34 71 00"}),
                ("34A.005", "Tracker drive motors & gearboxes", "pcs", 460, 880.00, {"masterformat": "34 71 00"}),
                ("34A.006", "Tracker control units & wind-stow controllers", "pcs", 460, 540.00, {"masterformat": "34 71 00"}),
                ("34A.007", "Mechanical install & torque-to-spec of trackers", "lsum", 1, 1280000.00, {"masterformat": "34 71 00"}),
            ],
        ),
        # -- 48.1 PV modules ---------------------------------------------------
        (
            "48A",
            "48 - PV Modules (IEC 61215 / 61730)",
            {"masterformat": "48"},
            [
                ("48A.001", "Bifacial mono PERC module 580 Wp (IEC 61215)", "pcs", 86200, 118.00, {"masterformat": "48 14 00"}),
                ("48A.002", "Module mounting, clamping & torque verification", "pcs", 86200, 6.50, {"masterformat": "48 14 00"}),
                ("48A.003", "Spare modules (2% strategic stock)", "pcs", 1724, 118.00, {"masterformat": "48 14 00"}),
                ("48A.004", "Electroluminescence / flash-test QA on arrival", "lsum", 1, 64000.00, {"masterformat": "48 14 00"}),
            ],
        ),
        # -- 48.2 Inverters ----------------------------------------------------
        (
            "48B",
            "48 - Inverters & Conversion (IEC 62109)",
            {"masterformat": "48"},
            [
                ("48B.001", "String inverter 350 kVA, 1500 V DC (IEC 62109)", "pcs", 108, 9800.00, {"masterformat": "48 15 00"}),
                ("48B.002", "Inverter mounting posts & shade canopies", "pcs", 108, 620.00, {"masterformat": "48 15 00"}),
                ("48B.003", "Inverter commissioning & parameterisation", "pcs", 108, 480.00, {"masterformat": "48 15 00"}),
                ("48B.004", "Reactive power / grid-code compliance setup", "lsum", 1, 88000.00, {"masterformat": "48 15 00"}),
            ],
        ),
        # -- 48.3 DC system ----------------------------------------------------
        (
            "48C",
            "48 - DC Cabling, Combiners & Array (IEC 62548)",
            {"masterformat": "48"},
            [
                ("48C.001", "DC string cable 6 mm2 solar (PV1-F), incl. MC4", "m", 420000, 1.95, {"masterformat": "48 14 00"}),
                ("48C.002", "DC main cable 1500 V, 95-240 mm2 Al", "m", 36000, 8.40, {"masterformat": "48 14 00"}),
                ("48C.003", "String combiner boxes with DC fuses & SPD", "pcs", 540, 380.00, {"masterformat": "48 14 00"}),
                ("48C.004", "DC connectors, crimping & string termination", "lsum", 1, 142000.00, {"masterformat": "48 14 00"}),
                ("48C.005", "Cable management trays, clips & UV ties", "m", 60000, 2.40, {"masterformat": "48 14 00"}),
                ("48C.006", "DC arc-fault detection & string monitoring", "lsum", 1, 96000.00, {"masterformat": "48 14 00"}),
            ],
        ),
        # -- 48.4 AC collector system ------------------------------------------
        (
            "48D",
            "48 - AC Collector System & Transformers",
            {"masterformat": "48"},
            [
                ("48D.001", "AC LV cable inverter-to-RMU, Al XLPE 0.4 kV", "m", 14000, 11.50, {"masterformat": "48 13 00"}),
                ("48D.002", "MV collector cable 33 kV Al XLPE, 240 mm2", "m", 22000, 34.00, {"masterformat": "48 13 00"}),
                ("48D.003", "Skid step-up transformer 3.15 MVA 0.4/33 kV", "pcs", 12, 78000.00, {"masterformat": "48 13 00"}),
                ("48D.004", "Ring main units 33 kV (SF6-free, IEC 62271)", "pcs", 12, 26000.00, {"masterformat": "48 13 00"}),
                ("48D.005", "MV cable jointing, terminations & testing", "pcs", 96, 1450.00, {"masterformat": "48 13 00"}),
                ("48D.006", "Transformer foundations & oil bunds", "pcs", 12, 8800.00, {"masterformat": "48 13 00"}),
            ],
        ),
        # -- 48.5 BESS ---------------------------------------------------------
        (
            "48E",
            "48 - BESS Containers & PCS (NFPA 855 / IEC 62619)",
            {"masterformat": "48"},
            [
                ("48E.001", "LFP battery containers 5 MWh, liquid-cooled", "pcs", 4, 1180000.00, {"masterformat": "48 17 00"}),
                ("48E.002", "Power conversion system (PCS) 2.5 MW bidirectional", "pcs", 4, 285000.00, {"masterformat": "48 17 00"}),
                ("48E.003", "BESS step-up transformer 5 MVA 0.69/33 kV", "pcs", 2, 96000.00, {"masterformat": "48 17 00"}),
                ("48E.004", "Battery management system & energy management (EMS)", "lsum", 1, 320000.00, {"masterformat": "48 17 00"}),
                ("48E.005", "Aerosol fire suppression & gas detection (NFPA 855)", "lsum", 1, 245000.00, {"masterformat": "48 17 00"}),
                ("48E.006", "BESS RC foundation slabs & spill containment", "m2", 640, 165.00, {"masterformat": "48 17 00"}),
                ("48E.007", "HVAC / thermal management auxiliaries", "lsum", 1, 88000.00, {"masterformat": "48 17 00"}),
                ("48E.008", "BESS DC/AC cabling, busbars & interconnection", "lsum", 1, 156000.00, {"masterformat": "48 17 00"}),
            ],
        ),
        # -- 33 Utility substation & grid connection ---------------------------
        (
            "33",
            "33 - MV/HV Substation & Grid Connection",
            {"masterformat": "33"},
            [
                ("33.001", "Main power transformer 50 MVA 33/110 kV", "pcs", 1, 1480000.00, {"masterformat": "33 71 00"}),
                ("33.002", "110 kV GIS bay with circuit breaker & protection", "pcs", 1, 920000.00, {"masterformat": "33 72 00"}),
                ("33.003", "33 kV switchgear lineup (incoming feeders)", "pcs", 14, 32000.00, {"masterformat": "33 72 00"}),
                ("33.004", "Substation control & relay protection panels", "lsum", 1, 385000.00, {"masterformat": "33 72 00"}),
                ("33.005", "Substation steel structures & gantries", "t", 95, 3200.00, {"masterformat": "33 71 00"}),
                ("33.006", "Substation control building (RC + fit-out)", "m2", 220, 1850.00, {"masterformat": "33 72 00"}),
                ("33.007", "Substation earthing grid & lightning masts", "lsum", 1, 168000.00, {"masterformat": "33 79 00"}),
                ("33.008", "110 kV overhead line / cable to POI (2 km)", "m", 2000, 420.00, {"masterformat": "33 71 19"}),
                ("33.009", "Metering, revenue meters & grid-operator interface", "lsum", 1, 145000.00, {"masterformat": "33 79 00"}),
                ("33.010", "Grid connection charges & utility witness testing", "lsum", 1, 480000.00, {"masterformat": "33 79 00"}),
            ],
        ),
        # -- 25 SCADA & monitoring ---------------------------------------------
        (
            "25",
            "25 - SCADA, Monitoring & Communications",
            {"masterformat": "25"},
            [
                ("25.001", "Plant SCADA system & control room HMI", "lsum", 1, 285000.00, {"masterformat": "25 35 00"}),
                ("25.002", "Power plant controller (PPC) for grid services", "lsum", 1, 165000.00, {"masterformat": "25 35 00"}),
                ("25.003", "Fibre-optic backbone & junction boxes", "m", 24000, 6.20, {"masterformat": "25 13 00"}),
                ("25.004", "Network switches, RTUs & data concentrators", "pcs", 28, 2400.00, {"masterformat": "25 13 00"}),
                ("25.005", "Meteorological station (irradiance, wind, temp)", "pcs", 3, 14500.00, {"masterformat": "25 14 00"}),
                ("25.006", "String-level monitoring & soiling sensors", "lsum", 1, 92000.00, {"masterformat": "25 35 00"}),
                ("25.007", "Cybersecurity hardening & remote access VPN", "lsum", 1, 58000.00, {"masterformat": "25 36 00"}),
            ],
        ),
        # -- 48.6 Commissioning & testing --------------------------------------
        (
            "48F",
            "48 - Commissioning, Testing & Energisation",
            {"masterformat": "48"},
            [
                ("48F.001", "DC & AC system testing (IEC 62446 incl. IV curves)", "lsum", 1, 142000.00, {"masterformat": "48 19 00"}),
                ("48F.002", "Substation & HV protection commissioning", "lsum", 1, 96000.00, {"masterformat": "48 19 00"}),
                ("48F.003", "BESS commissioning & UL 9540A response testing", "lsum", 1, 118000.00, {"masterformat": "48 19 00"}),
                ("48F.004", "Grid-code compliance & witness testing (IEEE 1547)", "lsum", 1, 88000.00, {"masterformat": "48 19 00"}),
                ("48F.005", "Performance ratio (PR) & capacity test (60 days)", "lsum", 1, 76000.00, {"masterformat": "48 19 00"}),
                ("48F.006", "Energisation, hold-point & handover to operations", "lsum", 1, 54000.00, {"masterformat": "48 19 00"}),
            ],
        ),
        # -- 01.9 Environmental & permitting -----------------------------------
        (
            "01E",
            "01 - Environmental, Permitting & Compliance",
            {"masterformat": "01"},
            [
                ("01E.001", "Environmental impact assessment & ecology surveys", "lsum", 1, 165000.00, {"masterformat": "01 57 00"}),
                ("01E.002", "Building / construction permit & planning fees", "lsum", 1, 98000.00, {"masterformat": "01 41 00"}),
                ("01E.003", "Grid connection & generation licensing", "lsum", 1, 72000.00, {"masterformat": "01 41 00"}),
                ("01E.004", "Biodiversity net-gain & habitat mitigation", "ha", 8, 4800.00, {"masterformat": "01 57 00"}),
                ("01E.005", "Archaeological watching brief & monitoring", "lsum", 1, 38000.00, {"masterformat": "01 57 00"}),
                ("01E.006", "Construction environmental management plan (CEMP)", "lsum", 1, 28000.00, {"masterformat": "01 35 43"}),
            ],
        ),
    ],
    markups=[
        ("EPC Margin", 9.0, "profit", "direct_cost"),
        ("Contingency", 6.0, "contingency", "direct_cost"),
        ("Insurance (CAR / erection all-risk)", 1.2, "insurance", "direct_cost"),
        ("Performance & Advance Payment Bond", 1.5, "insurance", "cumulative"),
    ],
    total_months=18,
    tender_name="Balance of Plant (BoP) Civil & Electrical",
    tender_companies=[
        ("Sarveen Renewable Energy", "tenders@sarveen.example", 0.98),
        ("Feldstern r.e. Solar Projects", "epc-bids@feldstern.example", 1.03),
        ("Solvarc AG", "vergabe@solvarc.example", 1.01),
    ],
    project_metadata={
        "client": "Solarpark Ehrfeld Renewables GmbH",
        "epc_contractor": "Feldstern r.e. / Sarveen JV (illustrative)",
        "owner_engineer": "Verdicta Energy Systems",
        "dc_capacity_mwp": 50,
        "ac_capacity_mwac": 37,
        "dc_ac_ratio": 1.35,
        "bess_energy_mwh": 20,
        "bess_power_mw": 10,
        "site_area_ha": 65,
        "module_count": 86200,
        "module_type": "Bifacial mono PERC 580 Wp",
        "tracker_type": "Single-axis (horizontal)",
        "grid_voltage_kv": 110,
        "collector_voltage_kv": 33,
        "expected_annual_yield_gwh": 62,
        "standards": [
            "IEC 61215 / IEC 61730 (PV module qualification & safety)",
            "IEC 62548 / IEC 60364-7-712 (PV array installation)",
            "IEC 62109 (inverter safety)",
            "IEC 62619 / UL 1973 (battery cell & system safety)",
            "NFPA 855 / UL 9540 / UL 9540A (BESS install & thermal runaway)",
            "IEEE 1547 / EN 50549 (grid interconnection)",
            "IEC 61936-1 / EN 50522 (HV installations & earthing)",
            "IEC 62446 (PV commissioning & inspection)",
        ],
        "regulator": "Bundesnetzagentur (grid) + Landesdirektion Sachsen (planning)",
        "permit_notes": (
            "BImSchG/BauGB planning consent, grid connection agreement under "
            "EnWG, generation registered in Marktstammdatenregister."
        ),
        "sustainability": (
            "Pollinator-friendly seeding, biodiversity net gain, SF6-free MV "
            "switchgear, end-of-life module & battery recycling plan."
        ),
    },
    tender_packages=[
        (
            "Balance of Plant (BoP) Civil & Electrical",
            "Earthworks, roads, fencing, foundations, trenching, MV cabling, earthing",
            "evaluating",
            [
                ("Sarveen Renewable Energy", "tenders@sarveen.example", 0.98),
                ("Feldstern r.e. Solar Projects", "epc-bids@feldstern.example", 1.03),
                ("Solvarc AG", "vergabe@solvarc.example", 1.01),
            ],
        ),
        (
            "PV Supply (Modules, Trackers, Inverters)",
            "Module supply, single-axis trackers, string inverters, DC system",
            "evaluating",
            [
                ("Renlux Solar / RenluxTracker", "projects@renlux.example", 0.97),
                ("Axitrace", "epc@axitrace.example", 1.04),
                ("Solmatik Technology AG", "vertrieb@solmatik.example", 1.02),
            ],
        ),
        (
            "BESS Supply & Integration",
            "LFP battery containers, PCS, EMS, fire suppression, integration",
            "evaluating",
            [
                ("Cellara Energy", "bids@cellara.example", 0.99),
                ("Halvasten Energy Storage", "ess-tenders@halvasten.example", 1.05),
                ("Voltbank Systems (Kestrove Energy)", "energy.epc@kestrove.example", 1.06),
            ],
        ),
        (
            "Grid Substation & Connection",
            "33/110 kV substation, GIS, transformer, protection, POI line",
            "evaluating",
            [
                ("Nordwerk Energy", "grid-tenders@nordwerk.example", 0.98),
                ("Toriwara Energy", "substation.bids@toriwara-energy.example", 1.04),
                ("Roverval Deutschland & Zentraleuropa", "netze@roverval-de.example", 1.02),
            ],
        ),
    ],
)
