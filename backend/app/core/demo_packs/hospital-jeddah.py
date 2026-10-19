# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Flagship demo: General Hospital, Jeddah (Makkah Province, KSA)
# ---------------------------------------------------------------------------
# Realistic flagship demo authored as a healthcare quantity surveyor / cost
# estimator. Program: a 300-bed acute general hospital on a greenfield plot
# in Jeddah, served from the city ring road. Two-level basement (parking,
# central plant, sterile stores, FM workshops), a 2-storey diagnostic and
# treatment podium (Emergency Department, imaging, operating theatres,
# central sterile services, laboratories, pharmacy, dialysis) and a 6-storey
# inpatient ward block above (medical/surgical wards, ICU/CCU, maternity,
# paediatrics, isolation suites). Reinforced concrete frame on a piled raft,
# medical-grade mechanical and electrical services, full medical gas
# pipeline system and radiation shielding to imaging and oncology. Designed
# to the Saudi Building Code (SBC 2024) and Ministry of Health (MOH) design
# standards for healthcare facilities. GFA ~52,000 m2.
#
# Classification: CSI MasterFormat 2018 (primary, as required by the demo
# harness) with Saudi Building Code (SBC 2024) part references carried in
# each classification dict under the "sbc" key. Rates are Jeddah 2026
# market rates in SAR, exclusive of VAT (15% carried as a separate markup
# line). All descriptions are in Arabic (RTL) with an English gloss in
# parentheses; recognised standard codes are kept verbatim.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="hospital-jeddah",
    project_name="مستشفى جدة العام - 300 سرير (Jeddah General Hospital, 300 Beds)",
    project_description=(
        "مستشفى عام حاد سعة 300 سرير على طريق الحرمين السريع بجدة. "
        "(A 300-bed acute general hospital on the Haramain Expressway, Jeddah.) "
        "بدروم بمستويين لمواقف السيارات والمحطة المركزية والمخازن المعقمة، "
        "وقاعدة تشخيص وعلاج من طابقين تضم قسم الطوارئ والأشعة وغرف العمليات "
        "وقسم التعقيم المركزي والمختبرات والصيدلية ووحدة غسيل الكلى، "
        "وكتلة تنويم من ستة طوابق تضم أجنحة باطنية وجراحية والعناية المركزة "
        "وقسم الولادة والأطفال وغرف العزل. "
        "(Two-level basement for parking, central plant and sterile stores; a "
        "2-storey diagnostic and treatment podium with Emergency Department, "
        "imaging, operating theatres, central sterile services, laboratories, "
        "pharmacy and dialysis; and a 6-storey inpatient block with medical and "
        "surgical wards, ICU/CCU, maternity, paediatrics and isolation rooms.) "
        "إجمالي المسطح البنائي حوالي 52,000 م². نظام إنشائي خرساني مسلح على "
        "لبشة خازوقية، مع أنظمة ميكانيكية وكهربائية بالمواصفات الطبية وشبكة "
        "غازات طبية كاملة وحماية إشعاعية لأقسام الأشعة والأورام. "
        "(Total GFA approx. 52,000 m2. RC frame on a piled raft, with "
        "medical-grade MEP, a full medical gas pipeline system and radiation "
        "shielding to imaging and oncology.) "
        "مصمم وفق كود البناء السعودي SBC 2024 ومعايير وزارة الصحة لتصميم "
        "المنشآت الصحية. "
        "(Designed to Saudi Building Code SBC 2024 and Ministry of Health (MOH) "
        "design standards for healthcare facilities.) "
        "تكلفة الإنشاء المباشرة التقديرية حوالي 720 مليون ريال سعودي "
        "(قبل المصاريف والضريبة). "
        "(Estimated direct construction cost approx. SAR 720 million, before "
        "overheads/VAT.)"
    ),
    region="SA",
    classification_standard="masterformat",
    currency="SAR",
    locale="ar",
    address={
        "street": "طريق الحرمين السريع (Haramain Expressway), Ash Shati District",
        "city": "Jeddah",
        "postcode": "23612",
        "country": "Saudi Arabia",
        "lat": 21.6005,
        "lng": 39.1357,
    },
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name=(
        "جدول الكميات - مستشفى عام وفق SBC 2024 ومعايير وزارة الصحة "
        "(BOQ - General Hospital, SBC 2024 & MOH Standards)"
    ),
    boq_description=(
        "جدول كميات تفصيلي وفق تصنيف الأقسام مع مراجع كود البناء السعودي "
        "ومتطلبات وزارة الصحة لتصميم المستشفيات. "
        "(Detailed BOQ by standard divisions with Saudi Building Code references and "
        "Ministry of Health hospital design requirements.)"
    ),
    boq_metadata={
        "standard": "Division-based classification + SBC 2024 (SBC 201/301/304/501/601/801) + MOH",
        "phase": "Detailed Estimate (Tender Documents)",
        "base_date": "2026-Q1",
        "price_level": "Jeddah 2026 (SAR, excl. VAT)",
        "facility_type": "Acute general hospital, 300 beds",
    },
    sections=[
        # ── 02/31 - Earthworks, Piling & Foundations (الحفر والأساسات) ───
        (
            "02",
            "02 - أعمال الموقع والحفر والأساسات الخازوقية (Earthworks & Piled Foundations)",
            {"masterformat": "02", "sbc": "SBC 301"},
            [
                ("02.01", "تجهيز الموقع وإزالة العوائق (Site clearance & grubbing)", "m2", 38000, 16.00, {"masterformat": "02 41 00", "sbc": "SBC 201"}),
                ("02.02", "دراسة جسات التربة والتقرير الجيوتقني (Geotechnical investigation & report)", "lsum", 1, 480000.00, {"masterformat": "02 32 00", "sbc": "SBC 301"}),
                ("02.03", "حفر البدروم وتسوية المنسوب (Bulk excavation to basement level)", "m3", 165000, 30.00, {"masterformat": "31 23 16", "sbc": "SBC 301"}),
                ("02.04", "نقل وترحيل المخلفات للمكب المرخص (Spoil cart-away to licensed tip)", "m3", 150000, 28.00, {"masterformat": "31 23 23", "sbc": "SBC 201"}),
                ("02.05", "نظام إسناد جوانب الحفر خوازيق متلاصقة (Secant-pile shoring to excavation)", "m2", 9800, 255.00, {"masterformat": "31 50 00", "sbc": "SBC 301"}),
                ("02.06", "نزح المياه الجوفية أثناء الإنشاء (Dewatering during construction)", "lsum", 1, 320000.00, {"masterformat": "31 23 19", "sbc": "SBC 301"}),
                ("02.07", "خوازيق خرسانية مصبوبة بالموقع d=900مم (Bored cast-in-situ piles d=900mm)", "m", 9600, 510.00, {"masterformat": "31 63 29", "sbc": "SBC 301"}),
                ("02.08", "اختبار تحميل الخوازيق ساكن وديناميكي (Static & dynamic pile load testing)", "pcs", 14, 78000.00, {"masterformat": "31 63 00", "sbc": "SBC 301"}),
                ("02.09", "ردم وإعادة دك بطبقات مدموكة (Engineered backfill, compacted layers)", "m3", 22000, 42.00, {"masterformat": "31 23 23", "sbc": "SBC 301"}),
                ("02.10", "معالجة التربة ضد النمل الأبيض (Anti-termite soil treatment)", "m2", 18000, 9.50, {"masterformat": "31 31 16", "sbc": "SBC 201"}),
            ],
        ),
        # ── 03 - Concrete Structure (الأعمال الخرسانية) ──────────────────
        (
            "03",
            "03 - الهيكل الخرساني المسلح (Reinforced Concrete Structure - SBC 304)",
            {"masterformat": "03", "sbc": "SBC 304"},
            [
                ("03.01", "خرسانة نظافة C15 تحت الأساسات (Blinding concrete C15)", "m3", 1850, 290.00, {"masterformat": "03 30 00", "sbc": "SBC 304"}),
                ("03.02", "لبشة أساس خرسانية C40 سمك 1.5م (Raft foundation C40, 1.5m)", "m3", 14500, 525.00, {"masterformat": "03 31 00", "sbc": "SBC 304"}),
                ("03.03", "أعمدة خرسانية C45 للكتلة والقاعدة (RC columns C45)", "m3", 4800, 620.00, {"masterformat": "03 30 00", "sbc": "SBC 304"}),
                ("03.04", "جدران قص خرسانية C45 للنواة والدرج (RC shear/core walls C45)", "m3", 6200, 600.00, {"masterformat": "03 30 00", "sbc": "SBC 304"}),
                ("03.05", "بلاطات وكمرات خرسانية C40 لكتلة التنويم (RC slabs & beams, ward block)", "m3", 17500, 565.00, {"masterformat": "03 30 00", "sbc": "SBC 304"}),
                ("03.06", "بلاطات سميكة C40 لأقسام الأشعة والعمليات (Thickened slabs, imaging/OT)", "m3", 3200, 595.00, {"masterformat": "03 30 00", "sbc": "SBC 304"}),
                ("03.07", "بلاطات وكمرات خرسانية C40 للبدروم والقاعدة (RC slabs, basement/podium)", "m3", 12800, 560.00, {"masterformat": "03 30 00", "sbc": "SBC 304"}),
                ("03.08", "حديد تسليح عالي المقاومة B500B (High-yield reinforcement B500B)", "t", 9800, 4150.00, {"masterformat": "03 21 00", "sbc": "SBC 304"}),
                ("03.09", "خرسانة ثقيلة بالباريت لحماية الأشعة (Barite heavyweight concrete, radiation)", "m3", 380, 1850.00, {"masterformat": "03 31 00", "sbc": "SBC 304"}),
                ("03.10", "شدات وقوالب للأعمدة والجدران (Formwork to columns & walls)", "m2", 58000, 80.00, {"masterformat": "03 11 00", "sbc": "SBC 304"}),
                ("03.11", "شدات وطاولات للبلاطات (Table/slab formwork)", "m2", 96000, 90.00, {"masterformat": "03 11 13", "sbc": "SBC 304"}),
                ("03.12", "معالجة وحماية الخرسانة من الحرارة (Hot-weather curing & protection)", "m2", 105000, 12.50, {"masterformat": "03 39 00", "sbc": "SBC 304"}),
            ],
        ),
        # ── 04 - Brick, block and stone work (أعمال البلوك) ──────────────────────
        (
            "04",
            "04 - أعمال البلوك والمباني (Brick, block and stone work)",
            {"masterformat": "04", "sbc": "SBC 201"},
            [
                ("04.01", "بلوك أسمنتي للجدران الخارجية 200مم (External concrete block 200mm)", "m2", 24000, 92.00, {"masterformat": "04 22 00", "sbc": "SBC 201"}),
                ("04.02", "بلوك خفيف عازل للجدران الداخلية 150مم (AAC light block 150mm, internal)", "m2", 42000, 78.00, {"masterformat": "04 22 23", "sbc": "SBC 201"}),
                ("04.03", "بلوك مقاوم للحريق لجدران الدرج والممرات (Fire-rated block, stairs/corridors)", "m2", 9800, 118.00, {"masterformat": "04 22 00", "sbc": "SBC 801"}),
                ("04.04", "جدران فاصلة صحية حول مناطق العزل (Hygienic separation walls, isolation)", "m2", 3600, 165.00, {"masterformat": "04 22 00", "sbc": "SBC 201"}),
                ("04.05", "أعتاب وكمرات رابطة خرسانية (RC lintels & tie beams to block)", "m", 11500, 48.00, {"masterformat": "04 05 16", "sbc": "SBC 201"}),
                ("04.06", "أربطة ومثبتات البلوك المعدنية (Masonry ties & wall starters)", "m2", 75000, 6.50, {"masterformat": "04 05 23", "sbc": "SBC 201"}),
            ],
        ),
        # ── 07 - Façade, Waterproofing & Insulation (الواجهات والعزل) ────
        (
            "07",
            "07 - الواجهات والعزل المائي والحراري (Façade, Waterproofing & Thermal - SBC 601)",
            {"masterformat": "07", "sbc": "SBC 601"},
            [
                ("07.01", "حائط ستائري وحدات بزجاج عاكس مزدوج (Unitised curtain wall, double low-E)", "m2", 9800, 1480.00, {"masterformat": "08 44 00", "sbc": "SBC 601"}),
                ("07.02", "نظام واجهة كلادينج ألمنيوم مركب صحي (Aluminium composite cladding ACP)", "m2", 11500, 640.00, {"masterformat": "07 42 43", "sbc": "SBC 601"}),
                ("07.03", "كاسرات شمسية أفقية ألمنيوم (Aluminium horizontal solar shading)", "m", 3800, 285.00, {"masterformat": "10 71 13", "sbc": "SBC 601"}),
                ("07.04", "عزل مائي للبشة والجدران أسفل المنسوب (Tanking to raft & retaining walls)", "m2", 18500, 90.00, {"masterformat": "07 13 00", "sbc": "SBC 601"}),
                ("07.05", "عزل مائي للأسطح طبقتان بيتومين معدّل (Roof waterproofing, 2-ply APP)", "m2", 9600, 74.00, {"masterformat": "07 52 00", "sbc": "SBC 601"}),
                ("07.06", "عزل حراري للأسطح بألواح بوليسترين 100مم (Roof thermal insulation XPS 100mm)", "m2", 9600, 58.00, {"masterformat": "07 22 00", "sbc": "SBC 601"}),
                ("07.07", "عزل حراري للجدران الخارجية صوف صخري 75مم (External wall insulation, rockwool 75mm)", "m2", 24000, 64.00, {"masterformat": "07 21 00", "sbc": "SBC 601"}),
                ("07.08", "عزل مائي للحمامات والمناطق الرطبة (Wet-area waterproofing)", "m2", 16500, 58.00, {"masterformat": "07 14 00", "sbc": "SBC 601"}),
                ("07.09", "مانع تسرب وفواصل التمدد (Sealants & expansion joints)", "m", 5200, 38.00, {"masterformat": "07 92 00", "sbc": "SBC 201"}),
                ("07.10", "معالجة مقاومة الحريق للفتحات (Firestopping to penetrations)", "lsum", 1, 620000.00, {"masterformat": "07 84 00", "sbc": "SBC 801"}),
            ],
        ),
        # ── 08 - Doors and glazing (الأبواب والزجاج) ─────────────────────
        (
            "08",
            "08 - الأبواب والزجاج الداخلي (Doors and interior glazing)",
            {"masterformat": "08", "sbc": "SBC 801"},
            [
                ("08.01", "أبواب أوتوماتيكية منزلقة هرمسية للعمليات (Hermetic sliding OT doors)", "pcs", 22, 38000.00, {"masterformat": "08 34 16", "sbc": "SBC 501"}),
                ("08.02", "أبواب رصاصية للأشعة (Lead-lined doors, imaging)", "pcs", 28, 22000.00, {"masterformat": "08 34 49", "sbc": "SBC 801"}),
                ("08.03", "أبواب داخلية صفائحية مضادة للبكتيريا (Anti-bacterial laminate doors)", "pcs", 1850, 1850.00, {"masterformat": "08 14 16", "sbc": "SBC 201"}),
                ("08.04", "أبواب حريقية معتمدة بزجاج مقاوم (Fire-rated doors w/ vision panels)", "pcs", 520, 2400.00, {"masterformat": "08 11 13", "sbc": "SBC 801"}),
                ("08.05", "أبواب معدنية للخدمات والمحطات (Hollow-metal doors, plant/services)", "pcs", 380, 1250.00, {"masterformat": "08 11 13", "sbc": "SBC 201"}),
                ("08.06", "أبواب دوارة آلية للمدخل الرئيسي (Automatic revolving entrance doors)", "pcs", 3, 145000.00, {"masterformat": "08 42 33", "sbc": "SBC 201"}),
                ("08.07", "قواطع وأبواب زجاجية للعيادات الخارجية (Glazed partitions/doors, OPD)", "m2", 3200, 320.00, {"masterformat": "08 80 00", "sbc": "SBC 201"}),
                ("08.08", "إكسسوارات وقطع تصادم للأسرّة بالأبواب (Door protection & impact plates)", "pcs", 1850, 280.00, {"masterformat": "08 71 00", "sbc": "SBC 201"}),
            ],
        ),
        # ── 09 - Internal Finishes incl. Antimicrobial (التشطيبات) ───────
        (
            "09",
            "09 - التشطيبات الداخلية بالمواصفات الصحية (Internal Finishes - Healthcare-Grade)",
            {"masterformat": "09", "sbc": "SBC 201"},
            [
                ("09.01", "لياسة أسمنتية للجدران الداخلية (Cement plaster to internal walls)", "m2", 118000, 38.00, {"masterformat": "09 24 00", "sbc": "SBC 201"}),
                ("09.02", "ألواح جبسية مقاومة للرطوبة للقواطع (Moisture-resistant gypsum partitions)", "m2", 36000, 92.00, {"masterformat": "09 29 00", "sbc": "SBC 201"}),
                ("09.03", "أسقف معلقة معدنية قابلة للتنظيف للمناطق الحرجة (Washable metal ceilings, critical)", "m2", 18500, 185.00, {"masterformat": "09 54 00", "sbc": "SBC 501"}),
                ("09.04", "أسقف معلقة أكوستيك للأجنحة والممرات (Acoustic ceilings, wards/corridors)", "m2", 42000, 115.00, {"masterformat": "09 51 00", "sbc": "SBC 201"}),
                ("09.05", "أرضيات فينيل لحامية متصلة طبية (Welded sheet-vinyl flooring, clinical)", "m2", 48000, 165.00, {"masterformat": "09 65 16", "sbc": "SBC 201"}),
                ("09.06", "أرضيات موصلة للكهرباء الساكنة للعمليات (Conductive/ESD flooring, OT)", "m2", 4200, 320.00, {"masterformat": "09 65 33", "sbc": "SBC 501"}),
                ("09.07", "بلاط بورسلين للوبيات والمناطق العامة (Porcelain tiling, lobbies/public)", "m2", 22000, 165.00, {"masterformat": "09 30 13", "sbc": "SBC 201"}),
                ("09.08", "بلاط سيراميك لجدران الحمامات والمناطق الرطبة (Ceramic wall tiling, wet)", "m2", 28000, 95.00, {"masterformat": "09 30 00", "sbc": "SBC 201"}),
                ("09.09", "ألواح جدارية صحية للمناطق الحرجة (Hygienic wall cladding, critical areas)", "m2", 14500, 245.00, {"masterformat": "09 77 13", "sbc": "SBC 501"}),
                ("09.10", "حواجز حماية الجدران ومساند اليد للممرات (Wall protection rails & handrails)", "m", 9800, 165.00, {"masterformat": "10 26 00", "sbc": "SBC 201"}),
                ("09.11", "دهانات بلاستيكية وإيبوكسي مضادة للبكتيريا (Antibacterial emulsion/epoxy paint)", "m2", 165000, 28.00, {"masterformat": "09 91 00", "sbc": "SBC 201"}),
                ("09.12", "دهان أرضيات الجراج والمحطات إيبوكسي (Epoxy floor coating, car park/plant)", "m2", 28000, 58.00, {"masterformat": "09 67 00", "sbc": "SBC 201"}),
            ],
        ),
        # ── 13 - Specialty: Operating Theatres & Clean Rooms (الغرف النظيفة) ─
        (
            "13",
            "13 - الإنشاءات الخاصة: غرف العمليات والغرف النظيفة (Operating Theatres & Clean Rooms)",
            {"masterformat": "13", "sbc": "SBC 501"},
            [
                ("13.01", "غرف عمليات معيارية مسبقة الصنع كاملة (Modular prefabricated operating theatres)", "pcs", 14, 2350000.00, {"masterformat": "13 49 00", "sbc": "SBC 501"}),
                ("13.02", "غرف عزل ضغط سالب كاملة التجهيز (Negative-pressure isolation rooms, AIIR)", "pcs", 24, 285000.00, {"masterformat": "13 21 26", "sbc": "SBC 501"}),
                ("13.03", "غرف عزل ضغط موجب لنقص المناعة (Positive-pressure protective isolation)", "pcs", 8, 265000.00, {"masterformat": "13 21 26", "sbc": "SBC 501"}),
                ("13.04", "بطانة الغرف النظيفة لقسم التعقيم المركزي (Clean-room lining, CSSD)", "m2", 2600, 1450.00, {"masterformat": "13 21 13", "sbc": "SBC 501"}),
                ("13.05", "صيدلية تحضير المعقم بالضغط السالب/الموجب (Aseptic pharmacy clean suite)", "lsum", 1, 1850000.00, {"masterformat": "13 21 13", "sbc": "SBC 501"}),
                ("13.06", "حماية إشعاعية ألواح رصاص لغرف الأشعة (Lead sheet radiation shielding, X-ray/CT)", "m2", 3200, 1650.00, {"masterformat": "13 49 13", "sbc": "SBC 801"}),
                ("13.07", "حماية إشعاعية للرنين المغناطيسي قفص فاراداي (MRI RF/Faraday cage & shielding)", "pcs", 3, 980000.00, {"masterformat": "13 49 00", "sbc": "SBC 501"}),
                ("13.08", "حماية إشعاعية لغرف العلاج بالأشعة الخرسانية (Bunker shielding, linear accelerator)", "lsum", 1, 4200000.00, {"masterformat": "13 49 13", "sbc": "SBC 801"}),
            ],
        ),
        # ── 23 - Medical-Grade HVAC (التكييف الطبي) - large critical load ─
        (
            "23",
            "23 - التكييف والتهوية بالمواصفات الطبية (Medical-Grade HVAC - SBC 501 / MOH)",
            {"masterformat": "23", "sbc": "SBC 501"},
            [
                ("23.01", "محطة تبريد مركزية وحدات تبريد (Central chiller plant - 6000 TR)", "lsum", 1, 28500000.00, {"masterformat": "23 64 00", "sbc": "SBC 501"}),
                ("23.02", "وحدات مناولة هواء بفلاتر HEPA للمناطق الحرجة (HEPA-filtered AHUs, critical)", "pcs", 48, 185000.00, {"masterformat": "23 73 13", "sbc": "SBC 501"}),
                ("23.03", "وحدات مناولة هواء عامة للأجنحة (General AHUs, wards/support)", "pcs", 64, 78000.00, {"masterformat": "23 73 00", "sbc": "SBC 501"}),
                ("23.04", "وحدات ملف المروحة FCU للمكاتب والعيادات (Fan-coil units FCU)", "pcs", 980, 4200.00, {"masterformat": "23 82 19", "sbc": "SBC 501"}),
                ("23.05", "شبكة مجاري هواء معزولة ستانلس للمناطق الحرجة (Stainless ductwork, critical)", "kg", 95000, 58.00, {"masterformat": "23 31 13", "sbc": "SBC 501"}),
                ("23.06", "شبكة مجاري الهواء المجلفنة المعزولة العامة (Insulated GI ductwork, general)", "kg", 285000, 32.00, {"masterformat": "23 31 00", "sbc": "SBC 501"}),
                ("23.07", "مواسير مياه مثلجة معزولة (Insulated chilled-water piping)", "m", 18500, 165.00, {"masterformat": "23 21 13", "sbc": "SBC 501"}),
                ("23.08", "فلاتر HEPA نهائية وإطارات للغرف الحرجة (Terminal HEPA filters & housings)", "pcs", 1200, 2400.00, {"masterformat": "23 41 00", "sbc": "SBC 501"}),
                ("23.09", "نظام تهوية ودخان الجراج (Car-park ventilation & smoke extract)", "lsum", 1, 2650000.00, {"masterformat": "23 34 00", "sbc": "SBC 801"}),
                ("23.10", "أنظمة التحكم بالضغط والمراقبة للغرف الحرجة (Room pressure control & monitoring)", "pcs", 320, 18500.00, {"masterformat": "23 09 23", "sbc": "SBC 501"}),
                ("23.11", "نظام إدارة المباني BMS للتكييف الطبي (BMS controls for medical HVAC)", "lsum", 1, 4850000.00, {"masterformat": "25 30 00", "sbc": "SBC 501"}),
                ("23.12", "نظام التحكم بضغط السلالم ضد الدخان (Stair pressurisation system)", "pcs", 12, 145000.00, {"masterformat": "23 34 23", "sbc": "SBC 801"}),
                ("23.13", "اختبار وموازنة وتشغيل تجريبي للأنظمة (Testing, balancing & commissioning)", "lsum", 1, 3200000.00, {"masterformat": "23 05 93", "sbc": "SBC 501"}),
            ],
        ),
        # ── 22 - Piping systems & medical gases (السباكة والغازات الطبية) ──────
        (
            "22",
            "22 - السباكة والصرف والغازات الطبية (Piping, drainage & medical gases)",
            {"masterformat": "22", "sbc": "SBC 701"},
            [
                ("22.01", "شبكة تغذية مياه باردة نحاس/PPR (Cold-water supply, copper/PPR)", "m", 24000, 82.00, {"masterformat": "22 11 16", "sbc": "SBC 701"}),
                ("22.02", "شبكة تغذية مياه ساخنة معزولة بتدوير (Insulated hot-water supply w/ recirc.)", "m", 16500, 98.00, {"masterformat": "22 11 23", "sbc": "SBC 701"}),
                ("22.03", "شبكة صرف صحي وتهوية UPVC/HDPE (Soil, waste & vent, UPVC/HDPE)", "m", 22000, 90.00, {"masterformat": "22 13 16", "sbc": "SBC 701"}),
                ("22.04", "شبكة صرف معدية معالجة من المختبرات (Lab/clinical effluent drainage)", "m", 3600, 185.00, {"masterformat": "22 13 19", "sbc": "SBC 701"}),
                ("22.05", "أطقم صحية كاملة بلمسة مرفقية طبية (Clinical sanitary fixtures, hands-free)", "pcs", 1650, 2200.00, {"masterformat": "22 40 00", "sbc": "SBC 701"}),
                ("22.06", "مغاسل تعقيم الجراحين (Surgeons' scrub-up troughs)", "pcs", 48, 14500.00, {"masterformat": "22 42 00", "sbc": "SBC 501"}),
                ("22.07", "خزانات مياه أرضية وعلوية + مضخات تعزيز (Water tanks & booster pumps)", "lsum", 1, 3200000.00, {"masterformat": "22 12 00", "sbc": "SBC 701"}),
                ("22.08", "محطة الأكسجين السائل VIE والمشعبات (Liquid-oxygen VIE plant & manifolds)", "lsum", 1, 2850000.00, {"masterformat": "22 61 13", "sbc": "SBC 501"}),
                ("22.09", "محطة هواء طبي مضغوط وتفريغ (Medical air compressor & vacuum plant)", "lsum", 1, 1950000.00, {"masterformat": "22 62 00", "sbc": "SBC 501"}),
                ("22.10", "شبكة أنابيب الغازات الطبية نحاس MGPS (Copper medical-gas pipeline MGPS)", "m", 18500, 245.00, {"masterformat": "22 63 00", "sbc": "SBC 501"}),
                ("22.11", "مخارج وأعمدة الغازات الطبية للأسرّة (Medical-gas outlets & bedhead units)", "pcs", 1850, 1450.00, {"masterformat": "22 66 53", "sbc": "SBC 501"}),
                ("22.12", "وحدات إنذار ومراقبة الغازات الطبية (Medical-gas area alarms & monitoring)", "pcs", 120, 9800.00, {"masterformat": "22 63 19", "sbc": "SBC 501"}),
                ("22.13", "نظام تصريف مياه الأمطار للأسطح (Roof rainwater drainage)", "m", 2600, 95.00, {"masterformat": "22 14 00", "sbc": "SBC 701"}),
            ],
        ),
        # ── 26 - Power distribution, ELV & nurse-call (الكهرباء وأنظمة الجهد المنخفض) ─
        (
            "26",
            "26 - الأعمال الكهربائية والجهد المنخفض ونداء الممرضات (Power distribution, ELV & nurse-call)",
            {"masterformat": "26", "sbc": "SBC 401"},
            [
                ("26.01", "غرف محولات وتوصيلة شبكة الكهرباء المحلية (HV substations & utility connection)", "lsum", 1, 6800000.00, {"masterformat": "26 11 00", "sbc": "SBC 401"}),
                ("26.02", "لوحات التوزيع الرئيسية للجهد المنخفض MDB (Main LV distribution boards MDB)", "pcs", 6, 320000.00, {"masterformat": "26 24 13", "sbc": "SBC 401"}),
                ("26.03", "لوحات توزيع فرعية للأدوار والأقسام (Sub-distribution boards per dept.)", "pcs", 145, 18500.00, {"masterformat": "26 24 16", "sbc": "SBC 401"}),
                ("26.04", "مولدات احتياطية ديزل 2000kVA (Standby diesel generators 2000kVA)", "pcs", 4, 1650000.00, {"masterformat": "26 32 13", "sbc": "SBC 401"}),
                ("26.05", "أنظمة عزل طبي IT للمناطق الحرجة (Medical IT isolated power systems)", "pcs", 64, 95000.00, {"masterformat": "26 23 00", "sbc": "SBC 501"}),
                ("26.06", "أنظمة UPS مركزية للمناطق الحرجة (Central UPS systems, critical care)", "lsum", 1, 4200000.00, {"masterformat": "26 33 53", "sbc": "SBC 401"}),
                ("26.07", "كيبلات ومسارات كيبلات نحاسية خالية من الهالوجين (LSZH copper cabling & trays)", "m", 285000, 46.00, {"masterformat": "26 05 19", "sbc": "SBC 401"}),
                ("26.08", "نقاط إنارة ومفاتيح وأفياش طبية (Lighting points, switches & medical sockets)", "pcs", 52000, 195.00, {"masterformat": "26 27 26", "sbc": "SBC 401"}),
                ("26.09", "إنارة LED موفرة للطاقة وإنارة الفحص (LED luminaires & examination lights)", "pcs", 32000, 165.00, {"masterformat": "26 51 00", "sbc": "SBC 601"}),
                ("26.10", "إنارة الطوارئ ولوحات الإخلاء (Emergency lighting & exit signage)", "pcs", 4800, 245.00, {"masterformat": "26 52 00", "sbc": "SBC 801"}),
                ("26.11", "نظام التأريض ومانعة الصواعق (Earthing & lightning protection)", "lsum", 1, 850000.00, {"masterformat": "26 41 00", "sbc": "SBC 401"}),
                ("26.12", "نظام نداء الممرضات والاتصال بالمرضى (Nurse-call & patient communication)", "pcs", 1850, 4800.00, {"masterformat": "27 52 23", "sbc": "SBC 501"}),
                ("26.13", "نظام إنذار الحريق المعنون (Addressable fire-alarm system)", "lsum", 1, 3850000.00, {"masterformat": "28 31 00", "sbc": "SBC 801"}),
                ("26.14", "أنظمة المراقبة والتحكم بالدخول CCTV (CCTV, access control & security)", "lsum", 1, 2650000.00, {"masterformat": "28 20 00", "sbc": "SBC 201"}),
                ("26.15", "بنية تحتية للاتصالات والبيانات والاستدعاء (Structured cabling, telecoms & paging)", "lsum", 1, 4850000.00, {"masterformat": "27 10 00", "sbc": "SBC 201"}),
                ("26.16", "نظام طاقة شمسية على السطح 500kWp (Rooftop solar PV 500kWp)", "lsum", 1, 3650000.00, {"masterformat": "48 14 00", "sbc": "SBC 601"}),
            ],
        ),
        # ── 14 - Vertical Transport & Logistics (المصاعد والنقل الداخلي) ─
        (
            "14",
            "14 - المصاعد والنقل الداخلي اللوجستي (Vertical Transport & Logistics)",
            {"masterformat": "14", "sbc": "SBC 201"},
            [
                ("14.01", "مصاعد أسرّة للمرضى 2500كجم (Bed/patient lifts 2500kg)", "pcs", 10, 720000.00, {"masterformat": "14 21 00", "sbc": "SBC 201"}),
                ("14.02", "مصاعد ركاب 1600كجم للزوار (Passenger lifts 1600kg, visitors)", "pcs", 8, 580000.00, {"masterformat": "14 21 00", "sbc": "SBC 201"}),
                ("14.03", "مصاعد خدمة/بضائع نظيفة وملوثة 2000كجم (Goods lifts, clean/dirty 2000kg)", "pcs", 6, 620000.00, {"masterformat": "14 20 00", "sbc": "SBC 201"}),
                ("14.04", "نظام نقل بالأنابيب الهوائية للعينات (Pneumatic tube transport system)", "lsum", 1, 2850000.00, {"masterformat": "14 92 00", "sbc": "SBC 201"}),
                ("14.05", "نظام نقل آلي بالعربات للوجستيات AGV (Automated guided vehicle logistics)", "lsum", 1, 4200000.00, {"masterformat": "14 90 00", "sbc": "SBC 201"}),
            ],
        ),
        # ── 11 - Medical & Laboratory Equipment (التجهيزات الطبية) ──────
        (
            "11",
            "11 - التجهيزات الطبية والمخبرية والإشعاعية (Medical, Laboratory & Imaging Equipment)",
            {"masterformat": "11", "sbc": "SBC 501"},
            [
                ("11.01", "جهاز تصوير مقطعي CT 128 شريحة (CT scanner, 128-slice)", "pcs", 3, 6800000.00, {"masterformat": "11 71 16", "sbc": "SBC 501"}),
                ("11.02", "جهاز رنين مغناطيسي MRI 3 تسلا (MRI scanner, 3.0 Tesla)", "pcs", 2, 12500000.00, {"masterformat": "11 71 16", "sbc": "SBC 501"}),
                ("11.03", "أجهزة أشعة سينية رقمية ثابتة ومتحركة (Digital X-ray, fixed & mobile)", "pcs", 12, 1450000.00, {"masterformat": "11 71 13", "sbc": "SBC 501"}),
                ("11.04", "جهاز تصوير الثدي الرقمي (Digital mammography unit)", "pcs", 2, 1850000.00, {"masterformat": "11 71 13", "sbc": "SBC 501"}),
                ("11.05", "وحدة قسطرة قلبية Cath-Lab (Cardiac catheterisation lab)", "pcs", 2, 9800000.00, {"masterformat": "11 71 00", "sbc": "SBC 501"}),
                ("11.06", "أضوية ووحدات تعليق غرف العمليات (Surgical lights & ceiling pendants)", "pcs", 14, 480000.00, {"masterformat": "11 73 00", "sbc": "SBC 501"}),
                ("11.07", "أجهزة تعقيم بخاري كبيرة CSSD (Large steam sterilisers, CSSD)", "pcs", 8, 620000.00, {"masterformat": "11 78 00", "sbc": "SBC 501"}),
                ("11.08", "أجهزة غسيل الكلى للوحدة (Haemodialysis machines, renal unit)", "pcs", 40, 185000.00, {"masterformat": "11 76 00", "sbc": "SBC 501"}),
                ("11.09", "حاضنات ومدافئ حديثي الولادة NICU (Neonatal incubators & warmers)", "pcs", 36, 145000.00, {"masterformat": "11 75 00", "sbc": "SBC 501"}),
                ("11.10", "أجهزة المختبر الآلية وأنظمة المسار (Automated lab analysers & track)", "lsum", 1, 8500000.00, {"masterformat": "11 53 00", "sbc": "SBC 501"}),
                ("11.11", "أثاث طبي ثابت ومناضد فحص (Built-in medical furniture & exam couches)", "lsum", 1, 4200000.00, {"masterformat": "11 72 00", "sbc": "SBC 201"}),
                ("11.12", "تجهيزات الصيدلية الآلية وأرفف التخزين (Automated pharmacy & storage)", "lsum", 1, 2650000.00, {"masterformat": "11 79 00", "sbc": "SBC 501"}),
            ],
        ),
        # ── 32 - External Works & Helipad (الأعمال الخارجية والمهبط) ─────
        (
            "32",
            "32 - الأعمال الخارجية وتنسيق الموقع ومهبط الطوارئ (External Works & Helipad)",
            {"masterformat": "32", "sbc": "SBC 201"},
            [
                ("32.01", "أعمال أسفلت للطرق ومدخل الطوارئ (Asphalt to roads & ambulance approach)", "m2", 18500, 95.00, {"masterformat": "32 12 16", "sbc": "SBC 201"}),
                ("32.02", "إنترلوك للممرات وساحات الاستقبال (Interlock paving, plazas/drop-off)", "m2", 12000, 135.00, {"masterformat": "32 14 13", "sbc": "SBC 201"}),
                ("32.03", "مظلات استقبال المرضى والإسعاف (Patient/ambulance entrance canopies)", "lsum", 1, 1850000.00, {"masterformat": "10 73 00", "sbc": "SBC 201"}),
                ("32.04", "مهبط طائرات الإسعاف على السطح (Rooftop emergency helipad)", "lsum", 1, 3200000.00, {"masterformat": "32 11 00", "sbc": "SBC 801"}),
                ("32.05", "تنسيق حدائق وزراعة محلية مقاومة للجفاف (Drought-tolerant landscaping)", "m2", 22000, 165.00, {"masterformat": "32 90 00", "sbc": "SBC 601"}),
                ("32.06", "شبكة ري بالتنقيط ذكية (Smart drip irrigation network)", "m2", 22000, 58.00, {"masterformat": "32 84 00", "sbc": "SBC 601"}),
                ("32.07", "أسوار وبوابات محيطية أمنية (Perimeter security fencing & gates)", "m", 1850, 420.00, {"masterformat": "32 31 00", "sbc": "SBC 201"}),
                ("32.08", "إنارة خارجية وأعمدة الموقع (External & site lighting)", "pcs", 280, 2800.00, {"masterformat": "26 56 00", "sbc": "SBC 601"}),
                ("32.09", "غرف تفتيش وتصريف مياه السطح (External drainage & manholes)", "m", 3600, 245.00, {"masterformat": "33 40 00", "sbc": "SBC 701"}),
                ("32.10", "محطة معالجة أولية للنفايات الطبية (Clinical-waste handling compound)", "lsum", 1, 1450000.00, {"masterformat": "32 30 00", "sbc": "SBC 201"}),
            ],
        ),
    ],
    markups=[
        ("مصاريف الموقع العامة (Site Overheads / Preliminaries)", 10.0, "overhead", "direct_cost"),
        ("المصاريف الإدارية العامة (Head-Office Overheads)", 5.0, "overhead", "direct_cost"),
        ("الربح (Profit)", 6.0, "profit", "direct_cost"),
        ("احتياطي للطوارئ (Contingency)", 8.0, "contingency", "direct_cost"),
        ("ضريبة القيمة المضافة (VAT)", 15.0, "tax", "cumulative"),
    ],
    total_months=38,
    tender_name="حزمة الأعمال الإنشائية والأساسات (Structure & Foundations Package)",
    tender_companies=[
        ("Talveen Engineering Contracting", "tenders@talveen.example", 0.98),
        ("Rukhban Construction Group", "bids@rukhban.example", 1.05),
        ("Sarwaneh & Partners Contracting", "estimation@sarwaneh.example", 1.02),
        ("Wadhaan General Contractors", "tenders@wadhaan.example", 1.01),
        ("Nakhbara International (KSA)", "bids@nakhbara.example", 1.06),
    ],
    tender_packages=[
        (
            "حزمة الأعمال الإنشائية والأساسات (Structure & Foundations Package)",
            "Piled raft foundation, two-level basement, reinforced concrete superstructure frame.",
            "evaluating",
            [
                ("Talveen Engineering Contracting", "tenders@talveen.example", 0.98),
                ("Rukhban Construction Group", "bids@rukhban.example", 1.05),
                ("Wadhaan General Contractors", "tenders@wadhaan.example", 1.01),
            ],
        ),
        (
            "حزمة الأعمال الميكانيكية والكهربائية والصحية (MEP & Medical Services Package)",
            "HVAC, medical gases, electrical, plumbing, BMS and healthcare-specific services.",
            "issued",
            [
                ("Nakhbara International (KSA)", "bids@nakhbara.example", 1.06),
                ("Sarwaneh & Partners Contracting", "estimation@sarwaneh.example", 1.02),
                ("AMS Muraikh Contracting", "tenders@muraikh.example", 1.04),
            ],
        ),
        (
            "حزمة التشطيبات والواجهات (Finishes & Facade Package)",
            "Internal finishes, specialist clinical finishes, curtain walling and external envelope.",
            "draft",
            [
                ("Rukhban Construction Group", "bids@rukhban.example", 1.03),
                ("Sarwaneh & Partners Contracting", "estimation@sarwaneh.example", 1.00),
            ],
        ),
    ],
    project_metadata={
        "address": "Haramain Expressway, Ash Shati District, Jeddah 23612, Saudi Arabia",
        "client": "Ministry of Health (MOH) - Jeddah Health Cluster",
        "operator": "Jeddah Second Health Cluster",
        "architect": "Sirhaan Amjadi Partnership (SAMP)",
        "main_consultant": "Dar Al-Hadeeba (Marhoun & Partners)",
        "healthcare_planner": "Medraplan (healthcare facility planning)",
        "facility_type": "Acute general hospital, 300 beds",
        "gfa_m2": 52000,
        "storeys": 8,
        "basement_levels": 2,
        "departments": (
            "Emergency Department, ICU/CCU, 14 operating theatres, diagnostic "
            "imaging (CT/MRI/X-ray/mammography), Cath-Lab, laboratories, central "
            "sterile services (CSSD), pharmacy, dialysis, maternity/NICU, "
            "paediatrics, isolation suites, outpatient clinics"
        ),
        "structure": "Reinforced concrete frame on a piled raft foundation",
        "building_code": "Saudi Building Code SBC 2024",
        "code_parts": (
            "SBC 201 (general), SBC 301 (structural loads), SBC 304 (concrete), "
            "SBC 401 (electrical), SBC 501 (mechanical/HVAC), SBC 601 (energy "
            "conservation), SBC 701 (plumbing), SBC 801 (fire protection)"
        ),
        "moh_standards": (
            "Ministry of Health (MOH) Design & Construction Guidelines for "
            "healthcare facilities; CBAHI accreditation requirements"
        ),
        "infection_control": (
            "ASHRAE 170 / SBC 501 ventilation for healthcare; HEPA filtration "
            "to critical areas; negative-pressure (AIIR) and positive-pressure "
            "protective isolation rooms"
        ),
        "medical_gases": (
            "Medical gas pipeline system (MGPS): liquid-oxygen VIE plant, "
            "medical air and vacuum plant, nitrous oxide, with area alarms - "
            "per HTM 02-01 / ISO 7396-1 referenced in MOH standards"
        ),
        "radiation_protection": (
            "Lead shielding to imaging rooms, RF/Faraday shielding to MRI, and "
            "barite-concrete bunker to linear accelerator; licensed per the "
            "Saudi Nuclear and Radiological Regulatory Commission (NRRC)"
        ),
        "energy_standard": (
            "SBC 601 - hot-climate energy conservation (high-efficiency chiller "
            "plant, low-E glazing, heat recovery, rooftop PV 500kWp)"
        ),
        "cooling": "Central chiller plant, ~6,000 TR connected load, N+1 redundancy",
        "resilience": "Standby diesel generators (N+1), central UPS to critical care, dual SEC feeds",
        "seismic": "Jeddah is a low-to-moderate seismicity zone; structure designed per SBC 301",
        "bim_standard": "ISO 19650-1/2 - BIM execution plan, LOD 350 at tender",
        "vat_note": "All BOQ rates are exclusive of VAT. KSA VAT of 15% (ZATCA) is applied as a separate markup line.",
        "saudization_note": (
            "Project subject to Nitaqat Saudization quotas (MHRSD); contractor and "
            "subcontractors must maintain a Green/Platinum band - local-workforce "
            "ratios priced into preliminaries"
        ),
        "regulator": (
            "Jeddah Municipality (Amanah) building permit; Saudi Civil Defense "
            "(fire/life-safety) approval; MOH facility licensing; NRRC radiation "
            "licensing; SEC power connection"
        ),
    },
    budget_boq_name=(
        "موازنة 5D - مستشفى جدة العام (5D Budget - Jeddah General Hospital)"
    ),
    planned_budget=1_050_000_000.0,
    actual_spend_ratio=0.42,
    spi_override=0.97,
    cpi_override=1.03,
)
