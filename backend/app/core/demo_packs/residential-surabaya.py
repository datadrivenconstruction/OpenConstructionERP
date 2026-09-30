# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: indonesia-id - Residential, Surabaya
# ---------------------------------------------------------------------------
# Indonesian residential RAB. Prices are IDR excluding 11% PPN.
# Surabaya rates are typically 10-15% below Jakarta.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-surabaya",
    project_name="Apartemen - Surabaya Barat (Residential, West Surabaya)",
    project_description=(
        "Pembangunan apartemen 12 lantai di Surabaya Barat dengan 180 unit, "
        "2 lantai basement parkir 200 slot, kolam renang dan fasilitas "
        "komunal. Luas bangunan kotor sekitar 22.000 m2. Struktur beton "
        "bertulang. New-build 12-storey apartment building in West Surabaya, "
        "180 units, 2 basements with 200 parking spaces. GFA approx. "
        "22,000 m2. Priced at Surabaya 2026 levels in IDR excluding PPN."
    ),
    region="ID",
    classification_standard="masterformat",
    currency="IDR",
    locale="id",
    address={
        "street": "Jl. HR Muhammad 88",
        "city": "Surabaya",
        "postcode": "60226",
        "country": "Indonesia",
        "lat": -7.2919,
        "lng": 112.6959,
    },
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="RAB - Apartemen Surabaya Barat (Cost Plan)",
    boq_description=(
        "Rencana Anggaran Biaya untuk apartemen 180 unit. Harga satuan "
        "Surabaya 2026 dalam IDR belum termasuk PPN."
    ),
    boq_metadata={
        "standard": "AHSP + division-based classification",
        "phase": "RAB Tender",
        "base_date": "2026-Q1",
        "price_level": "Surabaya 2026 (IDR, excl PPN)",
    },
    sections=[
        (
            "01",
            "01 - Pekerjaan Persiapan (Preliminaries)",
            {"masterformat": "01 00 00"},
            [
                ("01.01", "Mobilisasi (Mobilisation)", "lsum", 1, 1450000000, {"masterformat": "01 00 00"}),
                ("01.02", "Pagar proyek (Site hoarding)", "m", 320, 1250000, {"masterformat": "01 00 00"}),
                ("01.03", "Tower crane (Tower crane)", "month", 18, 245000000, {"masterformat": "01 00 00"}),
            ],
        ),
        (
            "02",
            "02 - Pekerjaan Tanah dan Fondasi (Earthworks and foundations)",
            {"masterformat": "31 00 00"},
            [
                ("02.01", "Galian tanah (Bulk excavation)", "m3", 22000, 85000, {"masterformat": "31 00 00"}),
                ("02.02", "Buang tanah (Disposal)", "m3", 18000, 165000, {"masterformat": "31 00 00"}),
                ("02.03", "Dinding penahan sheet pile (Sheet pile wall)", "m2", 2400, 2850000, {"masterformat": "31 00 00"}),
                ("02.04", "Tiang bor dia 800mm (Bored piles 800mm)", "m", 3600, 4250000, {"masterformat": "31 00 00"}),
                ("02.05", "Pile cap K-350 (Pile caps)", "m3", 1450, 4500000, {"masterformat": "03 00 00"}),
                ("02.06", "Plat lantai dasar K-300 (Ground slab)", "m3", 1100, 4850000, {"masterformat": "03 00 00"}),
                ("02.07", "Besi tulangan fondasi (Reinforcement)", "t", 320, 17500000, {"masterformat": "03 00 00"}),
                ("02.08", "Waterproofing basement (Waterproofing)", "m2", 4200, 425000, {"masterformat": "07 00 00"}),
            ],
        ),
        (
            "03",
            "03 - Pekerjaan Struktur (Structure)",
            {"masterformat": "03 00 00"},
            [
                ("03.01", "Kolom beton K-400 (RC columns)", "m3", 720, 6200000, {"masterformat": "03 00 00"}),
                ("03.02", "Dinding geser K-400 (Shear walls)", "m3", 1600, 5800000, {"masterformat": "03 00 00"}),
                ("03.03", "Plat lantai K-300, 200mm (RC slab)", "m2", 20000, 1650000, {"masterformat": "03 00 00"}),
                ("03.04", "Besi tulangan struktur atas (Reinforcement)", "t", 2000, 18500000, {"masterformat": "03 00 00"}),
                ("03.05", "Bekisting (Formwork)", "m2", 38000, 345000, {"masterformat": "03 00 00"}),
                ("03.06", "Tangga pracetak (Precast stairs)", "pcs", 24, 72000000, {"masterformat": "03 00 00"}),
                ("03.07", "Balkon pracetak (Precast balcony)", "pcs", 360, 25000000, {"masterformat": "03 00 00"}),
            ],
        ),
        (
            "04",
            "04 - Dinding Luar (External walls)",
            {"masterformat": "04 00 00"},
            [
                ("04.01", "Panel pracetak fasad (Precast facade panels)", "m2", 9600, 1850000, {"masterformat": "03 00 00"}),
                ("04.02", "Jendela aluminium kaca ganda (Aluminium windows DGU)", "m2", 3200, 3850000, {"masterformat": "08 00 00"}),
                ("04.03", "Pintu geser balkon (Sliding balcony doors)", "pcs", 180, 12500000, {"masterformat": "08 00 00"}),
                ("04.04", "Railing balkon kaca (Glass balcony balustrade)", "m", 2700, 2450000, {"masterformat": "05 00 00"}),
                ("04.05", "Cat eksterior (External paint)", "m2", 9600, 125000, {"masterformat": "09 00 00"}),
                ("04.06", "Pintu masuk aluminium (Entrance doors)", "pcs", 4, 85000000, {"masterformat": "08 00 00"}),
                ("04.07", "Louvre ventilasi servis (Service area louvres)", "m2", 1200, 1250000, {"masterformat": "08 00 00"}),
                ("04.08", "Waterproofing balkon (Balcony waterproofing)", "m2", 2700, 385000, {"masterformat": "07 00 00"}),
                ("04.09", "Sealant sambungan eksterior (External joint sealant)", "m", 4800, 125000, {"masterformat": "07 00 00"}),
                ("04.10", "Kanopi masuk utama (Main entrance canopy)", "m2", 120, 3850000, {"masterformat": "10 00 00"}),
                ("04.11", "Cladding batu alam podium (Stone cladding podium)", "m2", 480, 2450000, {"masterformat": "07 00 00"}),
            ],
        ),
        (
            "05",
            "05 - Dinding Interior dan Finishing (Internal works)",
            {"masterformat": "09 00 00"},
            [
                ("05.01", "Partisi bata ringan 100mm (Lightweight block partition)", "m2", 14000, 385000, {"masterformat": "09 00 00"}),
                ("05.02", "Plester dan aci dinding (Plaster and skim)", "m2", 48000, 125000, {"masterformat": "09 00 00"}),
                ("05.03", "Cat dinding (Wall paint)", "m2", 65000, 75000, {"masterformat": "09 00 00"}),
                ("05.04", "Keramik dinding kamar mandi (Bathroom wall tiles)", "m2", 7200, 485000, {"masterformat": "09 00 00"}),
                ("05.05", "Lantai keramik unit (Ceramic floor tiles to units)", "m2", 14000, 385000, {"masterformat": "09 00 00"}),
                ("05.06", "Lantai granit lobby (Granite lobby floor)", "m2", 850, 1850000, {"masterformat": "09 00 00"}),
                ("05.07", "Pintu kayu interior (Internal doors)", "pcs", 720, 4250000, {"masterformat": "08 00 00"}),
                ("05.08", "Pintu tahan api (Fire doors)", "pcs", 96, 9500000, {"masterformat": "08 00 00"}),
                ("05.09", "Kitchen set per unit (Kitchen units per flat)", "unit", 180, 28500000, {"masterformat": "12 00 00"}),
                ("05.10", "Plafon gypsum (Plasterboard ceiling)", "m2", 16000, 185000, {"masterformat": "09 00 00"}),
                ("05.11", "Lemari pakaian built-in per unit (Built-in wardrobe)", "unit", 180, 12500000, {"masterformat": "12 00 00"}),
                ("05.12", "Sanitasi per unit (Sanitaryware per flat)", "unit", 180, 9500000, {"masterformat": "22 00 00"}),
                ("05.13", "Skirting keramik (Ceramic skirting)", "m", 10800, 85000, {"masterformat": "09 00 00"}),
                ("05.14", "Railing tangga stainless (Stair handrail stainless)", "m", 360, 1850000, {"masterformat": "05 00 00"}),
                ("05.15", "Kotak surat dan signage (Letterboxes and signage)", "lsum", 1, 185000000, {"masterformat": "10 00 00"}),
            ],
        ),
        (
            "06",
            "06 - Atap (Roof)",
            {"masterformat": "07 00 00"},
            [
                ("06.01", "Waterproofing atap (Roof waterproofing)", "m2", 2000, 345000, {"masterformat": "07 00 00"}),
                ("06.02", "Insulasi atap (Roof insulation)", "m2", 2000, 285000, {"masterformat": "07 00 00"}),
                ("06.03", "Drainase atap (Roof drainage)", "lsum", 1, 285000000, {"masterformat": "07 00 00"}),
            ],
        ),
        (
            "07",
            "07 - MEP (Mechanical, electrical, plumbing)",
            {"masterformat": "23 00 00"},
            [
                ("07.01", "AC split per unit (Split AC per flat)", "unit", 180, 18500000, {"masterformat": "23 00 00"}),
                ("07.02", "Ventilasi basement dan koridor (Basement and corridor ventilation)", "lsum", 1, 2850000000, {"masterformat": "23 00 00"}),
                ("07.03", "Instalasi listrik per unit (Electrical per flat)", "unit", 180, 22500000, {"masterformat": "26 00 00"}),
                ("07.04", "Listrik area umum (Common area electrical)", "lsum", 1, 4850000000, {"masterformat": "26 00 00"}),
                ("07.05", "Plumbing dan sanitasi per unit (Plumbing per flat)", "unit", 180, 18500000, {"masterformat": "22 00 00"}),
                ("07.06", "Sistem alarm kebakaran (Fire alarm system)", "m2", 22000, 165000, {"masterformat": "21 00 00"}),
                ("07.07", "Sprinkler (Sprinkler system)", "m2", 22000, 285000, {"masterformat": "21 00 00"}),
                ("07.08", "Lift penumpang 13 orang, 14 lantai (Passenger lifts)", "pcs", 3, 3850000000, {"masterformat": "14 00 00"}),
                ("07.09", "Penangkal petir (Lightning protection)", "lsum", 1, 485000000, {"masterformat": "26 00 00"}),
                ("07.10", "Intercom video per unit (Video intercom)", "unit", 180, 2850000, {"masterformat": "27 00 00"}),
                ("07.11", "CCTV area umum (CCTV common areas)", "lsum", 1, 1450000000, {"masterformat": "27 00 00"}),
                ("07.12", "Akses kontrol lobby (Access control)", "pcs", 8, 65000000, {"masterformat": "27 00 00"}),
                ("07.13", "Charger EV parkir (EV charging provision)", "pcs", 18, 35000000, {"masterformat": "26 00 00"}),
                ("07.14", "Genset darurat 500 kVA (Emergency generator)", "pcs", 1, 2850000000, {"masterformat": "26 00 00"}),
                ("07.15", "Pompa air bersih dan tangki (Water pump and tank)", "lsum", 1, 1250000000, {"masterformat": "22 00 00"}),
                ("07.16", "Sistem pemadam otomatis (Automatic fire suppression)", "m2", 22000, 245000, {"masterformat": "21 00 00"}),
            ],
        ),
        (
            "08",
            "08 - Fasilitas dan Pekerjaan Luar (Facilities and external works)",
            {"masterformat": "32 00 00"},
            [
                ("08.01", "Kolam renang 25m dengan plant room (Swimming pool)", "lsum", 1, 4850000000, {"masterformat": "13 00 00"}),
                ("08.02", "Gym dan ruang komunal (Gym and function room)", "m2", 350, 4250000, {"masterformat": "32 00 00"}),
                ("08.03", "Lansekap dan taman (Landscaping)", "m2", 3200, 685000, {"masterformat": "32 00 00"}),
                ("08.04", "Penerangan luar (External lighting)", "pcs", 36, 15500000, {"masterformat": "26 00 00"}),
                ("08.05", "Drainase luar (External drainage)", "lsum", 1, 1850000000, {"masterformat": "22 00 00"}),
                ("08.06", "Pagar keliling dan gerbang (Boundary fence and gate)", "m", 380, 2450000, {"masterformat": "32 00 00"}),
                ("08.07", "Pos keamanan (Guard house)", "pcs", 1, 485000000, {"masterformat": "13 00 00"}),
                ("08.08", "Area bermain anak (Children playground)", "lsum", 1, 850000000, {"masterformat": "32 00 00"}),
                ("08.09", "Jogging track (Jogging track)", "m", 380, 1850000, {"masterformat": "32 00 00"}),
                ("08.10", "Tempat sampah terpilah (Refuse collection point)", "pcs", 4, 125000000, {"masterformat": "32 00 00"}),
            ],
        ),
    ],
    markups=[
        ("Overhead dan umum (Overheads)", 9.0, "overhead", "direct_cost"),
        ("Keuntungan (Profit)", 7.0, "profit", "direct_cost"),
        ("Kontinjensi (Contingency)", 5.0, "contingency", "direct_cost"),
        ("PPN 11%", 11.0, "tax", "cumulative"),
    ],
    total_months=28,
    tender_name="Kontrak Utama - Apartemen Surabaya Barat",
    tender_companies=[
        ("PT Jawa Timur Konstruksi", "tender@jawatimur-konst.example", 0.99),
        ("PT Surabaya Pembangunan", "penawaran@surabaya-pemb.example", 1.02),
        ("PT Nusantara Karya Beton", "tender@nusantarakarya.example", 1.04),
    ],
    project_metadata={
        "address": "Jl. HR Muhammad 88, Surabaya 60226",
        "client": "PT Ciputra Surabaya Properti",
        "architect": "PT Arsitek Jawa Timur",
        "structural_engineer": "PT Struktur Teknik Surabaya",
        "qs": "PT Estimasi Bangunan Timur",
        "gfa_m2": 22000,
        "units": 180,
        "storeys_above": 12,
        "storeys_below": 2,
        "parking_spaces": 200,
    },
)
