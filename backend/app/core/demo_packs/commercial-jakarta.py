# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: indonesia-id - Commercial Tower, Jakarta SCBD
# ---------------------------------------------------------------------------
# Indonesian RAB structured by AHSP-like work divisions. Prices are IDR
# excluding 11% PPN. Jakarta sits on alluvial soil, so bored pile foundations
# to 30-50m depth are standard for high-rise.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="commercial-jakarta",
    project_name="Gedung Perkantoran - Jakarta SCBD (Commercial Tower, Jakarta)",
    project_description=(
        "Pembangunan gedung perkantoran 20 lantai di kawasan SCBD Jakarta "
        "Selatan, dengan 3 lantai basement dan 250 slot parkir. Luas bangunan "
        "kotor sekitar 32.000 m2. Struktur beton bertulang dengan fondasi "
        "tiang bor. Fasad curtain wall kaca ganda. Sertifikasi Greenship "
        "Gold target. New-build 20-storey office tower in SCBD Jakarta, "
        "3 basements with 250 parking spaces. GFA approx. 32,000 m2. "
        "Priced at Jakarta 2026 levels in IDR excluding PPN."
    ),
    region="ID",
    classification_standard="masterformat",
    currency="IDR",
    locale="id",
    address={
        "street": "Jl. Jenderal Sudirman Kav. 52-53",
        "city": "Jakarta",
        "postcode": "12190",
        "country": "Indonesia",
        "lat": -6.2246,
        "lng": 106.8097,
    },
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="RAB - Gedung Perkantoran SCBD (Cost Plan)",
    boq_description=(
        "Rencana Anggaran Biaya untuk gedung perkantoran 20 lantai "
        "dengan 3 basement. Harga satuan Jakarta 2026 dalam IDR "
        "belum termasuk PPN."
    ),
    boq_metadata={
        "standard": "AHSP + division-based classification",
        "phase": "RAB Tender",
        "base_date": "2026-Q1",
        "price_level": "Jakarta 2026 (IDR, excl PPN)",
    },
    sections=[
        (
            "01",
            "01 - Pekerjaan Persiapan (Preliminaries)",
            {"masterformat": "01 00 00"},
            [
                ("01.01", "Mobilisasi dan demobilisasi (Mobilisation)", "lsum", 1, 2850000000, {"masterformat": "01 00 00"}),
                ("01.02", "Pagar proyek dan keamanan (Site hoarding and security)", "m", 380, 1450000, {"masterformat": "01 00 00"}),
                ("01.03", "Tower crane sewa dan pemasangan (Tower crane)", "month", 24, 285000000, {"masterformat": "01 00 00"}),
                ("01.04", "K3 dan keselamatan kerja (Health and safety)", "lsum", 1, 1850000000, {"masterformat": "01 00 00"}),
            ],
        ),
        (
            "02",
            "02 - Pekerjaan Tanah dan Fondasi (Earthworks and foundations)",
            {"masterformat": "31 00 00"},
            [
                ("02.01", "Penyelidikan tanah SPT dan lab (Soil investigation)", "lsum", 1, 850000000, {"masterformat": "31 00 00"}),
                ("02.02", "Galian tanah (Bulk excavation)", "m3", 48000, 95000, {"masterformat": "31 00 00"}),
                ("02.03", "Buang tanah ke disposal area (Disposal off site)", "m3", 42000, 185000, {"masterformat": "31 00 00"}),
                ("02.04", "Dinding penahan tanah secant pile (Secant pile wall)", "m2", 4200, 3850000, {"masterformat": "31 00 00"}),
                ("02.05", "Tiang bor dia 1000mm kedalaman 40m (Bored pile 1000mm)", "m", 6400, 5200000, {"masterformat": "31 00 00"}),
                ("02.06", "Pile cap beton K-350 (Pile caps)", "m3", 2400, 4850000, {"masterformat": "03 00 00"}),
                ("02.07", "Raft foundation K-350 kedap air (Raft slab watertight)", "m3", 2000, 5200000, {"masterformat": "03 00 00"}),
                ("02.08", "Besi tulangan BJTD 40 fondasi (Reinforcement)", "t", 520, 18500000, {"masterformat": "03 00 00"}),
                ("02.09", "Waterproofing basement membran (Waterproofing)", "m2", 6800, 485000, {"masterformat": "07 00 00"}),
            ],
        ),
        (
            "03",
            "03 - Pekerjaan Struktur (Structural works)",
            {"masterformat": "03 00 00"},
            [
                ("03.01", "Kolom beton K-500 (RC columns)", "m3", 1450, 6800000, {"masterformat": "03 00 00"}),
                ("03.02", "Dinding inti beton K-500 (RC core walls)", "m3", 2400, 6200000, {"masterformat": "03 00 00"}),
                ("03.03", "Plat lantai beton K-350, 250mm (RC flat slab)", "m2", 28000, 1850000, {"masterformat": "03 00 00"}),
                ("03.04", "Besi tulangan BJTD 40 struktur atas (Reinforcement)", "t", 3200, 19500000, {"masterformat": "03 00 00"}),
                ("03.05", "Bekisting (Formwork)", "m2", 52000, 385000, {"masterformat": "03 00 00"}),
                ("03.06", "Tangga pracetak (Precast stairs)", "pcs", 40, 85000000, {"masterformat": "03 00 00"}),
                ("03.07", "Balok transfer lantai 5 (Transfer beam)", "m3", 380, 8500000, {"masterformat": "03 00 00"}),
            ],
        ),
        (
            "04",
            "04 - Pekerjaan Fasad (Facade works)",
            {"masterformat": "04 00 00"},
            [
                ("04.01", "Curtain wall aluminium kaca ganda (Curtain wall DGU)", "m2", 12000, 8500000, {"masterformat": "08 00 00"}),
                ("04.02", "Pintu masuk otomatis aluminium (Entrance doors)", "pcs", 6, 125000000, {"masterformat": "08 00 00"}),
                ("04.03", "Cladding granit podium (Stone cladding)", "m2", 1800, 3850000, {"masterformat": "07 00 00"}),
                ("04.04", "Sun shading aluminium louvre (Sun shading)", "m2", 3600, 2450000, {"masterformat": "10 00 00"}),
            ],
        ),
        (
            "05",
            "05 - Pekerjaan Dinding Interior dan Finishing (Internal works)",
            {"masterformat": "09 00 00"},
            [
                ("05.01", "Partisi gypsum rangka metal 100mm (Drywall partition)", "m2", 12000, 585000, {"masterformat": "09 00 00"}),
                ("05.02", "Partisi tahan api 2 jam (Fire rated partition)", "m2", 3200, 1450000, {"masterformat": "09 00 00"}),
                ("05.03", "Partisi kaca kantor (Glazed partition)", "m2", 4200, 3850000, {"masterformat": "08 00 00"}),
                ("05.04", "Pintu kayu interior (Internal timber doors)", "pcs", 380, 5850000, {"masterformat": "08 00 00"}),
                ("05.05", "Pintu tahan api (Fire doors)", "pcs", 120, 12500000, {"masterformat": "08 00 00"}),
                ("05.06", "Keramik dinding kamar mandi (Wall tiles WCs)", "m2", 2800, 685000, {"masterformat": "09 00 00"}),
                ("05.07", "Cat dinding latex 2 lapis (Emulsion paint)", "m2", 32000, 95000, {"masterformat": "09 00 00"}),
                ("05.08", "Raised floor 150mm (Raised access floor)", "m2", 24000, 785000, {"masterformat": "09 00 00"}),
                ("05.09", "Karpet tile kantor (Carpet tile)", "m2", 20000, 485000, {"masterformat": "09 00 00"}),
                ("05.10", "Granit tile lobby utama (Granite lobby tile)", "m2", 1200, 2850000, {"masterformat": "09 00 00"}),
                ("05.11", "Plafon metal suspended (Suspended metal ceiling)", "m2", 24000, 685000, {"masterformat": "09 00 00"}),
            ],
        ),
        (
            "06",
            "06 - Pekerjaan Atap (Roof works)",
            {"masterformat": "07 00 00"},
            [
                ("06.01", "Insulasi atap 100mm (Roof insulation)", "m2", 1800, 485000, {"masterformat": "07 00 00"}),
                ("06.02", "Waterproofing membran atap (Roof membrane)", "m2", 1800, 385000, {"masterformat": "07 00 00"}),
                ("06.03", "Drainase atap (Roof drainage)", "lsum", 1, 450000000, {"masterformat": "07 00 00"}),
                ("06.04", "Panel surya 150 kWp (PV array)", "lsum", 1, 2850000000, {"masterformat": "48 00 00"}),
            ],
        ),
        (
            "07",
            "07 - Pekerjaan Mekanikal (Mechanical services)",
            {"masterformat": "23 00 00"},
            [
                ("07.01", "Chiller water-cooled 800 TR (Chiller plant)", "lsum", 1, 18500000000, {"masterformat": "23 00 00"}),
                ("07.02", "AHU dan FCU distribusi (AHU/FCU distribution)", "m2", 28000, 1250000, {"masterformat": "23 00 00"}),
                ("07.03", "Plumbing dan sanitasi (Plumbing and sanitary)", "lsum", 1, 8500000000, {"masterformat": "22 00 00"}),
                ("07.04", "Pompa kebakaran dan sprinkler (Fire pump and sprinkler)", "m2", 32000, 385000, {"masterformat": "21 00 00"}),
                ("07.05", "Lift penumpang 2100 kg, 23 lantai (Passenger lifts)", "pcs", 6, 4850000000, {"masterformat": "14 00 00"}),
                ("07.06", "Lift barang 3000 kg (Goods lift)", "pcs", 2, 3850000000, {"masterformat": "14 00 00"}),
            ],
        ),
        (
            "08",
            "08 - Pekerjaan Elektrikal (Electrical services)",
            {"masterformat": "26 00 00"},
            [
                ("08.01", "Panel distribusi utama LVMDP (Main LV distribution)", "lsum", 1, 4850000000, {"masterformat": "26 00 00"}),
                ("08.02", "Genset 1500 kVA (Emergency generator)", "pcs", 2, 4250000000, {"masterformat": "26 00 00"}),
                ("08.03", "Penerangan LED DALI (LED lighting)", "m2", 28000, 585000, {"masterformat": "26 00 00"}),
                ("08.04", "Sistem deteksi dan alarm kebakaran (Fire alarm)", "m2", 32000, 185000, {"masterformat": "21 00 00"}),
                ("08.05", "BMS sistem otomasi gedung (Building automation)", "lsum", 1, 12500000000, {"masterformat": "27 00 00"}),
                ("08.06", "Kabel data Cat 6A dan fiber (Structured cabling)", "m2", 28000, 285000, {"masterformat": "27 00 00"}),
                ("08.07", "CCTV dan akses kontrol (CCTV and access control)", "lsum", 1, 4850000000, {"masterformat": "27 00 00"}),
                ("08.08", "UPS untuk data center (UPS for data center)", "pcs", 2, 2850000000, {"masterformat": "27 00 00"}),
                ("08.09", "Sistem anti-petir (Lightning protection)", "lsum", 1, 1850000000, {"masterformat": "26 00 00"}),
                ("08.10", "Iluminasi darurat (Emergency lighting)", "lsum", 1, 2450000000, {"masterformat": "26 00 00"}),
                ("08.11", "Charger EV basement (EV charging provision)", "pcs", 25, 45000000, {"masterformat": "26 00 00"}),
                ("08.12", "Komissioning dan pengujian (Commissioning)", "lsum", 1, 3850000000, {"masterformat": "01 00 00"}),
                ("08.13", "Panel surya atap parkir (Car park roof PV)", "lsum", 1, 1850000000, {"masterformat": "48 00 00"}),
                ("08.14", "Sistem penangkap air hujan (Rainwater harvesting)", "lsum", 1, 1250000000, {"masterformat": "26 00 00"}),
                ("08.15", "Sistem komunikasi gedung (Building communication)", "lsum", 1, 2850000000, {"masterformat": "27 00 00"}),
                ("08.16", "Tata udara parkir basement (Basement ventilation)", "lsum", 1, 3250000000, {"masterformat": "23 00 00"}),
            ],
        ),
        (
            "09",
            "09 - Pekerjaan Luar (External works)",
            {"masterformat": "32 00 00"},
            [
                ("09.01", "Lansekap dan hardscape (Landscaping)", "m2", 2800, 1250000, {"masterformat": "32 00 00"}),
                ("09.02", "Drainase luar dan sambungan (External drainage)", "lsum", 1, 2850000000, {"masterformat": "22 00 00"}),
                ("09.03", "Penerangan luar (External lighting)", "pcs", 42, 18500000, {"masterformat": "26 00 00"}),
                ("09.04", "Drop-off canopy (Entrance canopy)", "m2", 380, 3850000, {"masterformat": "10 00 00"}),
                ("09.05", "Parkir sepeda 150 slot (Bicycle parking)", "pcs", 150, 2850000, {"masterformat": "32 00 00"}),
            ],
        ),
    ],
    markups=[
        ("Overhead dan umum (Overheads)", 10.0, "overhead", "direct_cost"),
        ("Keuntungan (Profit)", 8.0, "profit", "direct_cost"),
        ("Kontinjensi (Contingency)", 5.0, "contingency", "direct_cost"),
        ("PPN 11%", 11.0, "tax", "cumulative"),
    ],
    total_months=32,
    tender_name="Kontrak Utama - Gedung Perkantoran SCBD",
    tender_companies=[
        ("PT Bangun Karya Persada", "tender@bangunkarya.example", 0.98),
        ("PT Mitra Konstruksi Nusantara", "penawaran@mitrakonstruksi.example", 1.03),
        ("PT Graha Pembangunan Utama", "tender@grahapembangunan.example", 1.01),
    ],
    project_metadata={
        "address": "Jl. Jenderal Sudirman Kav. 52-53, Jakarta 12190",
        "client": "PT Sudirman Central Properti",
        "architect": "PT Arsitek Nusantara Raya",
        "structural_engineer": "PT Rekayasa Struktur Indonesia",
        "qs": "PT Estimasi Bangunan Prima",
        "gfa_m2": 32000,
        "storeys_above": 20,
        "storeys_below": 3,
        "parking_spaces": 250,
        "greenship_target": "Gold",
    },
    tender_packages=[
        (
            "Struktur (Structure)",
            "Fondasi, beton bertulang, tangga pracetak",
            "evaluating",
            [
                ("PT Bangun Karya Persada", "tender@bangunkarya.example", 0.98),
                ("PT Mitra Konstruksi Nusantara", "penawaran@mitrakonstruksi.example", 1.03),
                ("PT Graha Pembangunan Utama", "tender@grahapembangunan.example", 1.01),
            ],
        ),
        (
            "MEP (M&E Services)",
            "HVAC, mekanikal, elektrikal, lift, proteksi kebakaran",
            "issued",
            [
                ("PT Teknik Mesin Elektrik", "tender@teknikme.example", 0.99),
                ("PT Instalasi Menara Jaya", "penawaran@instmenara.example", 1.04),
            ],
        ),
    ],
)
