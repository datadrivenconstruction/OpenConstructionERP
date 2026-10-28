# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: saudi-vision2030 - Mixed-Use Development, Riyadh (KSA)
# ---------------------------------------------------------------------------
# Realistic flagship demo authored as a quantity surveyor / cost estimator.
# Program: mixed-use development on King Fahd Road, Riyadh. Two-level
# basement car park, a 2-storey retail podium and a 12-storey tower
# (offices on lower floors, serviced residential above). Reinforced
# concrete frame (post-tensioned flat slabs to tower), high-performance
# hot-climate envelope with solar-control glazing, served from a campus
# district-cooling plant. GFA ~21,500 m2.
#
# Classification: CSI MasterFormat 2018 (primary, as required by the demo
# harness) with Saudi Building Code (SBC 2018) part references carried in
# each classification dict under the "sbc" key. Rates are Riyadh 2026
# market rates in SAR, exclusive of VAT (15% carried as a separate markup
# line). All descriptions are in Arabic (RTL) with an English gloss in
# parentheses, recognised standard codes kept verbatim.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="mixed-use-riyadh",
    project_name="مجمع الواحة متعدد الاستخدامات - الرياض (Al Waha Mixed-Use, Riyadh)",
    project_description=(
        "تطوير مجمع متعدد الاستخدامات على طريق الملك فهد بالرياض. "
        "(Mixed-use development on King Fahd Road, Riyadh.) "
        "بدروم بمستويين لمواقف السيارات، قاعدة تجارية من طابقين، "
        "وبرج من 12 طابقاً (مكاتب وشقق فندقية). "
        "(Two-level basement car park, 2-storey retail podium, 12-storey tower "
        "with offices and serviced apartments.) "
        "إجمالي المسطح البنائي حوالي 21,500 م². نظام إنشائي خرساني مسلح مع "
        "بلاطات مسطحة سابقة الإجهاد للبرج. "
        "(Total GFA approx. 21,500 m2. RC frame with post-tensioned flat "
        "slabs to the tower.) "
        "مصمم وفق كود البناء السعودي SBC 2018 وتصنيف الطاقة SBC 601 للمناخ الحار. "
        "(Designed to Saudi Building Code SBC 2018, energy class per SBC 601 for "
        "the hot climate.) "
        "تكلفة الإنشاء المباشرة التقديرية حوالي 175 مليون ريال سعودي (قبل الضريبة والمصاريف). "
        "(Estimated direct construction cost approx. SAR 175 million, before overheads/VAT.)"
    ),
    region="SA",
    classification_standard="masterformat",
    currency="SAR",
    locale="ar",
    address={
        "street": "طريق الملك فهد (King Fahd Road), Al Olaya District",
        "city": "Riyadh",
        "postcode": "12214",
        "country": "Saudi Arabia",
        "lat": 24.6944,
        "lng": 46.6853,
    },
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="جدول الكميات - كود البناء السعودي SBC 2018 (BOQ - Saudi Building Code SBC 2018)",
    boq_description=(
        "جدول كميات تفصيلي وفق تصنيف الأقسام مع مراجع كود البناء السعودي. "
        "(Detailed BOQ by standard divisions with Saudi Building Code references.)"
    ),
    boq_metadata={
        "standard": "Division-based classification + SBC 2018 (SBC 201/301/304/501/601)",
        "phase": "Detailed Estimate (Tender Documents)",
        "base_date": "2026-Q1",
        "price_level": "Riyadh 2026 (SAR, excl. VAT)",
    },
    sections=[
        # ── 02 - Site preparation and demolition (أعمال الموقع) ───────────
        (
            "02",
            "02 - أعمال الموقع والحفر (Site preparation & earthworks)",
            {"masterformat": "02", "sbc": "SBC 201"},
            [
                ("02.01", "تجهيز الموقع وإزالة العوائق (Site clearance & grubbing)", "m2", 4200, 18.00, {"masterformat": "02 41 00", "sbc": "SBC 201"}),
                ("02.02", "دراسة جسات التربة والتقرير الجيوتقني (Geotechnical investigation & report)", "lsum", 1, 320000.00, {"masterformat": "02 32 00", "sbc": "SBC 301"}),
                ("02.03", "حفر البدروم في صخر/تربة (Bulk excavation incl. rock)", "m3", 78000, 32.00, {"masterformat": "31 23 16", "sbc": "SBC 301"}),
                ("02.04", "نقل وترحيل المخلفات للمكب المرخص (Spoil cart-away to licensed tip)", "m3", 70000, 28.00, {"masterformat": "31 23 23", "sbc": "SBC 201"}),
                ("02.05", "نظام إسناد جوانب الحفر (شدات/خوازيق) (Shoring/secant pile to excavation sides)", "m2", 6800, 245.00, {"masterformat": "31 50 00", "sbc": "SBC 301"}),
                ("02.06", "نزح المياه الجوفية أثناء الإنشاء (Dewatering during construction)", "lsum", 1, 180000.00, {"masterformat": "31 23 19", "sbc": "SBC 301"}),
                ("02.07", "ردم وإعادة دك بطبقات مدموكة (Engineered backfill, compacted layers)", "m3", 9500, 42.00, {"masterformat": "31 23 23", "sbc": "SBC 301"}),
                ("02.08", "معالجة التربة ضد النمل الأبيض (Anti-termite soil treatment)", "m2", 4000, 9.50, {"masterformat": "31 31 16", "sbc": "SBC 201"}),
            ],
        ),
        # ── 03 - Cast-in-place and precast concrete work (الأعمال الخرسانية) ─
        (
            "03",
            "03 - الأعمال الخرسانية المسلحة (Reinforced concrete - SBC 304)",
            {"masterformat": "03", "sbc": "SBC 304"},
            [
                ("03.01", "خرسانة نظافة C15 تحت الأساسات (Blinding concrete C15)", "m3", 620, 290.00, {"masterformat": "03 30 00", "sbc": "SBC 304"}),
                ("03.02", "لبشة أساس خرسانية C40 سمك 1.2م (Raft foundation C40, 1.2m)", "m3", 5200, 520.00, {"masterformat": "03 31 00", "sbc": "SBC 304"}),
                ("03.03", "خوازيق خرسانية مصبوبة بالموقع d=800مم (Bored cast-in-situ piles d=800mm)", "m", 4200, 480.00, {"masterformat": "31 63 29", "sbc": "SBC 301"}),
                ("03.04", "أعمدة خرسانية C45 للبرج والقاعدة (RC columns C45)", "m3", 1850, 610.00, {"masterformat": "03 30 00", "sbc": "SBC 304"}),
                ("03.05", "جدران قص خرسانية C45 للنواة (RC shear/core walls C45)", "m3", 2400, 595.00, {"masterformat": "03 30 00", "sbc": "SBC 304"}),
                ("03.06", "بلاطات مسطحة سابقة الإجهاد C40 للبرج (PT flat slabs C40, tower)", "m3", 6800, 640.00, {"masterformat": "03 38 00", "sbc": "SBC 304"}),
                ("03.07", "بلاطات وكمرات خرسانية C40 للبدروم والقاعدة (RC slabs & beams, basement/podium)", "m3", 5600, 560.00, {"masterformat": "03 30 00", "sbc": "SBC 304"}),
                ("03.08", "حديد تسليح عالي المقاومة B500B (High-yield reinforcement B500B)", "t", 4100, 4150.00, {"masterformat": "03 21 00", "sbc": "SBC 304"}),
                ("03.09", "حبال الإجهاد اللاصقة للبلاطات (Bonded PT tendons & anchors)", "t", 185, 9800.00, {"masterformat": "03 38 00", "sbc": "SBC 304"}),
                ("03.10", "شدات وقوالب للأعمدة والجدران (Formwork to columns & walls)", "m2", 24000, 78.00, {"masterformat": "03 11 00", "sbc": "SBC 304"}),
                ("03.11", "شدات وطاولات للبلاطات (Table/slab formwork)", "m2", 38000, 88.00, {"masterformat": "03 11 13", "sbc": "SBC 304"}),
                ("03.12", "معالجة وحماية الخرسانة من الحرارة (Hot-weather curing & protection)", "m2", 42000, 12.50, {"masterformat": "03 39 00", "sbc": "SBC 304"}),
            ],
        ),
        # ── 04 - Brick, block and stone work (أعمال البلوك) ──────────────────────
        (
            "04",
            "04 - أعمال البلوك والمباني (Brick, block and stone work)",
            {"masterformat": "04", "sbc": "SBC 201"},
            [
                ("04.01", "بلوك أسمنتي للجدران الخارجية 200مم (External concrete block 200mm)", "m2", 11500, 92.00, {"masterformat": "04 22 00", "sbc": "SBC 201"}),
                ("04.02", "بلوك خفيف عازل للجدران الداخلية 150مم (AAC light block 150mm, internal)", "m2", 18500, 78.00, {"masterformat": "04 22 23", "sbc": "SBC 201"}),
                ("04.03", "بلوك مقاوم للحريق لجدران الدرج والممرات (Fire-rated block, stairs/corridors)", "m2", 3200, 118.00, {"masterformat": "04 22 00", "sbc": "SBC 201"}),
                ("04.04", "أعتاب وكمرات رابطة خرسانية (RC lintels & tie beams to block)", "m", 4800, 48.00, {"masterformat": "04 05 16", "sbc": "SBC 201"}),
                ("04.05", "أربطة ومثبتات البلوك المعدنية (Masonry ties & wall starters)", "m2", 33000, 6.50, {"masterformat": "04 05 23", "sbc": "SBC 201"}),
            ],
        ),
        # ── 05 - Structural and miscellaneous metal work (الأعمال المعدنية) ─
        (
            "05",
            "05 - الأعمال المعدنية الإنشائية (Structural and miscellaneous metal work)",
            {"masterformat": "05", "sbc": "SBC 306"},
            [
                ("05.01", "هيكل معدني لمظلة المدخل والأتريوم (Structural steel - atrium/canopy)", "t", 220, 12500.00, {"masterformat": "05 12 00", "sbc": "SBC 306"}),
                ("05.02", "درج معدني للهروب من الحريق (Steel fire-escape stairs)", "pcs", 6, 68000.00, {"masterformat": "05 51 00", "sbc": "SBC 801"}),
                ("05.03", "دهان منتفخ مقاوم للحريق للهيكل المعدني (Intumescent fire protection to steel)", "m2", 3800, 95.00, {"masterformat": "05 05 23", "sbc": "SBC 801"}),
                ("05.04", "أعمال معدنية متنوعة ودرابزين (Miscellaneous metals & handrails)", "lsum", 1, 480000.00, {"masterformat": "05 50 00", "sbc": "SBC 306"}),
            ],
        ),
        # ── 07 - Waterproofing & Insulation (العزل) - heavy for climate ──
        (
            "07",
            "07 - أعمال العزل المائي والحراري (Waterproofing & Thermal - SBC 601)",
            {"masterformat": "07", "sbc": "SBC 601"},
            [
                ("07.01", "عزل مائي للبشة والجدران أسفل المنسوب (Tanking to raft & retaining walls)", "m2", 9200, 88.00, {"masterformat": "07 13 00", "sbc": "SBC 601"}),
                ("07.02", "عزل مائي للأسطح (طبقتان بيتومين معدّل) (Roof waterproofing, 2-ply APP)", "m2", 4600, 72.00, {"masterformat": "07 52 00", "sbc": "SBC 601"}),
                ("07.03", "عزل حراري للأسطح بألواح بوليسترين 100مم (Roof thermal insulation XPS 100mm)", "m2", 4600, 58.00, {"masterformat": "07 22 00", "sbc": "SBC 601"}),
                ("07.04", "عزل حراري للجدران الخارجية صوف صخري 75مم (External wall insulation, rockwool 75mm)", "m2", 11500, 64.00, {"masterformat": "07 21 00", "sbc": "SBC 601"}),
                ("07.05", "حاجز بخار وطبقة عاكسة للأسطح (Vapour barrier & reflective layer)", "m2", 4600, 22.00, {"masterformat": "07 26 00", "sbc": "SBC 601"}),
                ("07.06", "عزل مائي للحمامات والمناطق الرطبة (Wet-area waterproofing, bathrooms)", "m2", 6800, 58.00, {"masterformat": "07 14 00", "sbc": "SBC 601"}),
                ("07.07", "مانع تسرب وفواصل التمدد (Sealants & expansion joints)", "m", 2400, 38.00, {"masterformat": "07 92 00", "sbc": "SBC 201"}),
                ("07.08", "معالجة مقاومة الحريق للفتحات (Firestopping to penetrations)", "lsum", 1, 220000.00, {"masterformat": "07 84 00", "sbc": "SBC 801"}),
            ],
        ),
        # ── 08 - Facade and glazing (الواجهات والزجاج) ───────────────────
        (
            "08",
            "08 - الواجهات والزجاج بحماية شمسية (Facade & Solar-Control Glazing)",
            {"masterformat": "08", "sbc": "SBC 601"},
            [
                ("08.01", "حائط ستائري وحدات بزجاج عاكس مزدوج (Unitised curtain wall, double low-E glazing)", "m2", 7800, 1450.00, {"masterformat": "08 44 00", "sbc": "SBC 601"}),
                ("08.02", "نظام واجهة كلادينج ألمنيوم مركب (ACP) (Aluminium composite cladding ACP)", "m2", 5200, 620.00, {"masterformat": "07 42 43", "sbc": "SBC 601"}),
                ("08.03", "كاسرات شمسية أفقية ألمنيوم (Aluminium horizontal solar shading)", "m", 2800, 285.00, {"masterformat": "10 71 13", "sbc": "SBC 601"}),
                ("08.04", "نوافذ ألمنيوم مزدوجة الزجاج للبرج (Aluminium double-glazed windows, tower)", "m2", 2600, 880.00, {"masterformat": "08 51 13", "sbc": "SBC 601"}),
                ("08.05", "واجهة زجاجية للمدخل الرئيسي (Feature entrance glazing)", "m2", 420, 1850.00, {"masterformat": "08 44 13", "sbc": "SBC 601"}),
                ("08.06", "أبواب دوارة آلية للمدخل (Automatic revolving entrance doors)", "pcs", 3, 145000.00, {"masterformat": "08 42 33", "sbc": "SBC 201"}),
                ("08.07", "أبواب داخلية خشبية حريقية (Internal fire-rated timber doors)", "pcs", 680, 1650.00, {"masterformat": "08 14 16", "sbc": "SBC 801"}),
                ("08.08", "أبواب معدنية للخدمات والمخازن (Hollow-metal doors, plant/stores)", "pcs", 240, 1250.00, {"masterformat": "08 11 13", "sbc": "SBC 201"}),
            ],
        ),
        # ── 09 - Interior finishing: drywall, flooring, painting (التشطيبات) ─
        (
            "09",
            "09 - أعمال التشطيبات (Interior finishing)",
            {"masterformat": "09", "sbc": "SBC 201"},
            [
                ("09.01", "لياسة أسمنتية للجدران الداخلية (Cement plaster to internal walls)", "m2", 52000, 38.00, {"masterformat": "09 24 00", "sbc": "SBC 201"}),
                ("09.02", "ألواح جبسية للجدران والقواطع (Gypsum board partitions/linings)", "m2", 14500, 88.00, {"masterformat": "09 29 00", "sbc": "SBC 201"}),
                ("09.03", "أسقف معلقة جبسية وأكوستيك (Suspended gypsum & acoustic ceilings)", "m2", 28000, 115.00, {"masterformat": "09 51 00", "sbc": "SBC 201"}),
                ("09.04", "بلاط بورسلين للأرضيات (Porcelain floor tiling)", "m2", 16500, 165.00, {"masterformat": "09 30 13", "sbc": "SBC 201"}),
                ("09.05", "رخام طبيعي لأرضيات اللوبي (Natural marble flooring, lobbies)", "m2", 2400, 620.00, {"masterformat": "09 63 40", "sbc": "SBC 201"}),
                ("09.06", "بلاط سيراميك لجدران الحمامات (Ceramic wall tiling, wet areas)", "m2", 12000, 95.00, {"masterformat": "09 30 00", "sbc": "SBC 201"}),
                ("09.07", "أرضيات فينيل/SPC للشقق (SPC/vinyl flooring, apartments)", "m2", 9800, 135.00, {"masterformat": "09 65 00", "sbc": "SBC 201"}),
                ("09.08", "أرضيات مرفوعة للمكاتب (Raised access flooring, offices)", "m2", 6800, 245.00, {"masterformat": "09 69 00", "sbc": "SBC 201"}),
                ("09.09", "دهانات بلاستيكية وإيبوكسي (Emulsion & epoxy paint systems)", "m2", 78000, 26.00, {"masterformat": "09 91 00", "sbc": "SBC 201"}),
                ("09.10", "دهان أرضيات الجراج إيبوكسي (Epoxy floor coating, car park)", "m2", 14000, 58.00, {"masterformat": "09 67 00", "sbc": "SBC 201"}),
            ],
        ),
        # ── 11/12 - Fixed equipment and furniture (التجهيزات) ───────────
        (
            "11",
            "11 - التجهيزات الثابتة (Fixed equipment and furniture)",
            {"masterformat": "11", "sbc": "SBC 201"},
            [
                ("11.01", "مطابخ مجهزة للشقق الفندقية (Fitted kitchens, serviced apartments)", "pcs", 96, 18500.00, {"masterformat": "11 31 00", "sbc": "SBC 201"}),
                ("11.02", "واجهات محلات التجزئة (تسليم على الهيكل) (Retail shopfronts, shell)", "m", 480, 1850.00, {"masterformat": "11 14 00", "sbc": "SBC 201"}),
                ("11.03", "لوحات إرشادية وأنظمة التوجيه (Signage & wayfinding)", "lsum", 1, 380000.00, {"masterformat": "10 14 00", "sbc": "SBC 201"}),
                ("11.04", "تجهيزات دورات المياه (Toilet accessories & partitions)", "pcs", 220, 1450.00, {"masterformat": "10 28 00", "sbc": "SBC 201"}),
            ],
        ),
        # ── 14 - Conveying / Vertical Transport (المصاعد) ───────────────
        (
            "14",
            "14 - المصاعد والسلالم الكهربائية (Elevators, escalators and lifts)",
            {"masterformat": "14", "sbc": "SBC 201"},
            [
                ("14.01", "مصاعد ركاب عالية السرعة 1600كجم للبرج (High-speed passenger lifts 1600kg)", "pcs", 6, 580000.00, {"masterformat": "14 21 00", "sbc": "SBC 201"}),
                ("14.02", "مصعد خدمة/بضائع 2000كجم (Goods/service lift 2000kg)", "pcs", 2, 720000.00, {"masterformat": "14 20 00", "sbc": "SBC 201"}),
                ("14.03", "سلالم كهربائية للقاعدة التجارية (Escalators, retail podium)", "pcs", 4, 420000.00, {"masterformat": "14 31 00", "sbc": "SBC 201"}),
            ],
        ),
        # ── 23 - HVAC / District Cooling (التكييف) - large cooling load ─
        (
            "23",
            "23 - التكييف والتهوية وتبريد المناطق (HVAC & District Cooling - SBC 501)",
            {"masterformat": "23", "sbc": "SBC 501"},
            [
                ("23.01", "محطة تبريد مناطق وحدات تبريد (Chiller plant, district cooling - 3500 TR)", "lsum", 1, 14500000.00, {"masterformat": "23 64 00", "sbc": "SBC 501"}),
                ("23.02", "وحدات مناولة الهواء AHU (Air-handling units AHU)", "pcs", 38, 68000.00, {"masterformat": "23 73 00", "sbc": "SBC 501"}),
                ("23.03", "وحدات ملف المروحة FCU للشقق والمكاتب (Fan-coil units FCU)", "pcs", 620, 4200.00, {"masterformat": "23 82 19", "sbc": "SBC 501"}),
                ("23.04", "شبكة مجاري الهواء المعزولة (Insulated GI ductwork)", "kg", 185000, 32.00, {"masterformat": "23 31 00", "sbc": "SBC 501"}),
                ("23.05", "مواسير مياه مثلجة معزولة (Insulated chilled-water piping)", "m", 9800, 165.00, {"masterformat": "23 21 13", "sbc": "SBC 501"}),
                ("23.06", "نظام تهوية ودخان الجراج (Car-park ventilation & smoke extract)", "lsum", 1, 1850000.00, {"masterformat": "23 34 00", "sbc": "SBC 801"}),
                ("23.07", "مخمدات ومخارج هواء وموزعات (Dampers, grilles & diffusers)", "pcs", 2400, 185.00, {"masterformat": "23 37 00", "sbc": "SBC 501"}),
                ("23.08", "نظام إدارة المباني BMS للتكييف (BMS controls for HVAC)", "lsum", 1, 1650000.00, {"masterformat": "25 30 00", "sbc": "SBC 501"}),
                ("23.09", "نظام التحكم بالضغط للسلالم (Stair pressurisation system)", "pcs", 8, 145000.00, {"masterformat": "23 34 23", "sbc": "SBC 801"}),
            ],
        ),
        # ── 22 - Piping systems and sanitary fixtures (السباكة) ─────────
        (
            "22",
            "22 - أعمال السباكة والصرف (Piping systems and drainage)",
            {"masterformat": "22", "sbc": "SBC 701"},
            [
                ("22.01", "شبكة تغذية مياه باردة PPR (Cold-water supply, PPR)", "m", 8600, 78.00, {"masterformat": "22 11 16", "sbc": "SBC 701"}),
                ("22.02", "شبكة تغذية مياه ساخنة معزولة (Insulated hot-water supply)", "m", 5200, 95.00, {"masterformat": "22 11 23", "sbc": "SBC 701"}),
                ("22.03", "شبكة صرف صحي UPVC (Soil & waste drainage, UPVC)", "m", 7800, 88.00, {"masterformat": "22 13 16", "sbc": "SBC 701"}),
                ("22.04", "أطقم صحية كاملة (مغاسل/مراحيض) (Sanitary fixtures, complete)", "pcs", 880, 1850.00, {"masterformat": "22 40 00", "sbc": "SBC 701"}),
                ("22.05", "خزانات مياه أرضية وعلوية + مضخات (Water tanks & booster pumps)", "lsum", 1, 1450000.00, {"masterformat": "22 12 00", "sbc": "SBC 701"}),
                ("22.06", "نظام تجميع المياه الرمادية لإعادة الاستخدام (Greywater recycling system)", "lsum", 1, 680000.00, {"masterformat": "22 13 53", "sbc": "SBC 601"}),
                ("22.07", "نظام تصريف مياه الأمطار للأسطح (Roof rainwater drainage)", "m", 1200, 95.00, {"masterformat": "22 14 00", "sbc": "SBC 701"}),
                ("22.08", "سخانات مياه شمسية للشقق (Solar water heaters, apartments)", "pcs", 48, 6800.00, {"masterformat": "22 33 36", "sbc": "SBC 601"}),
            ],
        ),
        # ── 26 - Power distribution and lighting systems (الكهرباء) ─────
        (
            "26",
            "26 - الأعمال الكهربائية (Power distribution and lighting)",
            {"masterformat": "26", "sbc": "SBC 401"},
            [
                ("26.01", "غرفة محولات وتوصيلة شبكة الكهرباء المحلية (HV substation & utility connection)", "lsum", 1, 3200000.00, {"masterformat": "26 11 00", "sbc": "SBC 401"}),
                ("26.02", "لوحة التوزيع الرئيسية للجهد المنخفض MDB (Main LV distribution board MDB)", "pcs", 3, 285000.00, {"masterformat": "26 24 13", "sbc": "SBC 401"}),
                ("26.03", "لوحات توزيع فرعية للأدوار (Sub-distribution boards per floor)", "pcs", 64, 18500.00, {"masterformat": "26 24 16", "sbc": "SBC 401"}),
                ("26.04", "مولد احتياطي ديزل 1500kVA (Standby diesel generator 1500kVA)", "pcs", 2, 1250000.00, {"masterformat": "26 32 13", "sbc": "SBC 401"}),
                ("26.05", "كيبلات ومسارات كيبلات نحاسية (Copper cabling & cable trays)", "m", 96000, 42.00, {"masterformat": "26 05 19", "sbc": "SBC 401"}),
                ("26.06", "نقاط إنارة ومفاتيح وأفياش (Lighting points, switches & sockets)", "pcs", 18500, 185.00, {"masterformat": "26 27 26", "sbc": "SBC 401"}),
                ("26.07", "إنارة LED موفرة للطاقة (Energy-efficient LED luminaires - SBC 601)", "pcs", 12800, 145.00, {"masterformat": "26 51 00", "sbc": "SBC 601"}),
                ("26.08", "نظام التأريض ومانعة الصواعق (Earthing & lightning protection)", "lsum", 1, 420000.00, {"masterformat": "26 41 00", "sbc": "SBC 401"}),
                ("26.09", "محطة شحن السيارات الكهربائية 22kW (EV charging stations 22kW)", "pcs", 40, 32000.00, {"masterformat": "26 56 00", "sbc": "SBC 401"}),
                ("26.10", "نظام طاقة شمسية على السطح 250kWp (Rooftop solar PV 250kWp)", "lsum", 1, 1850000.00, {"masterformat": "48 14 00", "sbc": "SBC 601"}),
            ],
        ),
        # ── 27/28 - ICT, Fire Alarm & Safety (الأنظمة المنخفضة والحريق) ──
        (
            "28",
            "28 - أنظمة السلامة والإنذار والأمن (Fire, Life-Safety & Security - SBC 801)",
            {"masterformat": "28", "sbc": "SBC 801"},
            [
                ("28.01", "نظام إنذار الحريق المعنون (Addressable fire-alarm system)", "lsum", 1, 1450000.00, {"masterformat": "28 31 00", "sbc": "SBC 801"}),
                ("28.02", "نظام رشاشات مائية للحريق (Wet sprinkler system)", "m2", 21500, 95.00, {"masterformat": "21 13 13", "sbc": "SBC 801"}),
                ("28.03", "شبكة فوهات وخراطيم الحريق (Fire hose reels & landing valves)", "pcs", 180, 2200.00, {"masterformat": "21 12 00", "sbc": "SBC 801"}),
                ("28.04", "نظام إطفاء غازي لغرف الكهرباء (Clean-agent gas suppression, electrical rooms)", "lsum", 1, 580000.00, {"masterformat": "21 22 00", "sbc": "SBC 801"}),
                ("28.05", "أنظمة المراقبة والتحكم بالدخول CCTV (CCTV & access control)", "lsum", 1, 980000.00, {"masterformat": "28 20 00", "sbc": "SBC 201"}),
                ("28.06", "كيبلات وبنية تحتية للاتصالات والبيانات (Structured cabling & telecoms)", "lsum", 1, 1250000.00, {"masterformat": "27 10 00", "sbc": "SBC 201"}),
            ],
        ),
        # ── 31/32 - External Works & Landscaping (الأعمال الخارجية) ─────
        (
            "32",
            "32 - الأعمال الخارجية وتنسيق الموقع (External Works & Landscaping)",
            {"masterformat": "32", "sbc": "SBC 201"},
            [
                ("32.01", "أعمال أسفلت للطرق والمداخل (Asphalt to access roads)", "m2", 4200, 95.00, {"masterformat": "32 12 16", "sbc": "SBC 201"}),
                ("32.02", "إنترلوك للممرات والساحات (Interlock paving, plazas)", "m2", 6800, 135.00, {"masterformat": "32 14 13", "sbc": "SBC 201"}),
                ("32.03", "تنسيق حدائق وزراعة محلية مقاومة للجفاف (Drought-tolerant landscaping)", "m2", 5200, 165.00, {"masterformat": "32 90 00", "sbc": "SBC 601"}),
                ("32.04", "شبكة ري بالتنقيط ذكية (Smart drip irrigation network)", "m2", 5200, 58.00, {"masterformat": "32 84 00", "sbc": "SBC 601"}),
                ("32.05", "نوافير ومسطحات مائية (Water features & fountains)", "lsum", 1, 1200000.00, {"masterformat": "32 84 23", "sbc": "SBC 201"}),
                ("32.06", "أسوار وبوابات محيطية (Perimeter fencing & gates)", "m", 640, 380.00, {"masterformat": "32 31 00", "sbc": "SBC 201"}),
                ("32.07", "إنارة خارجية وأعمدة ديكورية (External & decorative lighting)", "pcs", 120, 2800.00, {"masterformat": "26 56 00", "sbc": "SBC 601"}),
                ("32.08", "غرف تفتيش وتصريف مياه السطح (External drainage & manholes)", "m", 1400, 245.00, {"masterformat": "33 40 00", "sbc": "SBC 701"}),
            ],
        ),
    ],
    markups=[
        ("مصاريف الموقع العامة (Site Overheads / Preliminaries)", 9.0, "overhead", "direct_cost"),
        ("المصاريف الإدارية العامة (Head-Office Overheads)", 5.0, "overhead", "direct_cost"),
        ("الربح (Profit)", 6.0, "profit", "direct_cost"),
        ("احتياطي للطوارئ (Contingency)", 5.0, "contingency", "direct_cost"),
        ("ضريبة القيمة المضافة (VAT)", 15.0, "tax", "cumulative"),
    ],
    total_months=30,
    tender_name="حزمة الأعمال الإنشائية (Structural Works Package)",
    tender_companies=[
        ("Talveen Engineering Contracting", "tenders@talveen.example", 0.98),
        ("Sarwaneh & Partners Contracting", "bids@sarwaneh.example", 1.04),
        ("Wadhaan General Contractors", "estimation@wadhaan.example", 1.01),
    ],
    tender_packages=[
        (
            "حزمة الأعمال الإنشائية والأساسات (Structure & Substructure Package)",
            "Foundations, basement parking, reinforced concrete frame and cores.",
            "evaluating",
            [
                ("Talveen Engineering Contracting", "tenders@talveen.example", 0.98),
                ("Wadhaan General Contractors", "estimation@wadhaan.example", 1.01),
                ("Sarwaneh & Partners Contracting", "bids@sarwaneh.example", 1.04),
            ],
        ),
        (
            "حزمة الواجهات والأظرفة (Facade & Envelope Package)",
            "Curtain walling, unitised facade, cladding and roofing to the mixed-use envelope.",
            "issued",
            [
                ("Sarwellan Glazing Industrial (KSA)", "tenders@sarwellan.example", 1.05),
                ("Clanmere Facades Gulf", "bids@clanmere-gulf.example", 1.08),
            ],
        ),
        (
            "حزمة الميكانيكا والكهرباء والتشطيبات (MEP & Fit-out Package)",
            "HVAC, electrical, plumbing, vertical transportation and tenant fit-out works.",
            "draft",
            [
                ("Nakhbara International (KSA)", "bids@nakhbara.example", 1.03),
                ("Sarwaneh & Partners Contracting", "bids@sarwaneh.example", 1.00),
            ],
        ),
    ],
    project_metadata={
        "address": "King Fahd Road, Al Olaya District, Riyadh 12214, Saudi Arabia",
        "client": "Sirhaan Real Estate Development Co.",
        "architect": "Hadeeba & Associates",
        "main_consultant": "Dar Al-Hadeeba (Marhoun & Partners)",
        "gfa_m2": 21500,
        "storeys": 12,
        "basement_levels": 2,
        "structure": "Reinforced concrete frame with post-tensioned flat slabs (tower)",
        "building_code": "Saudi Building Code SBC 2018",
        "code_parts": "SBC 201 (general), SBC 301 (structural loads), SBC 304 (concrete), SBC 501 (mechanical/HVAC), SBC 601 (energy conservation), SBC 801 (fire protection)",
        "energy_standard": "SBC 601 - hot-climate energy conservation (district cooling, low-E glazing, rooftop PV 250kWp)",
        "cooling": "Campus district-cooling plant, ~3,500 TR connected load",
        "seismic": "Riyadh is a low-seismicity zone; structure designed per SBC 301 with standard ductility detailing",
        "bim_standard": "ISO 19650-1/2 - BIM execution plan, LOD 350 at tender",
        "aramco_standards": "Aramco SAES/SAMSS referenced for fire-water, generator fuel storage and HV switchgear where applicable",
        "vat_note": "All BOQ rates are exclusive of VAT. KSA VAT of 15% (ZATCA) is applied as a separate markup line.",
        "saudization_note": "Project subject to Nitaqat Saudization quotas (MHRSD); contractor and subcontractors must maintain a Green/Platinum band - local-workforce ratios priced into preliminaries.",
        "regulator": "Riyadh Municipality (Amanah) building permit; Saudi Civil Defense fire approval; SEC power connection; permits per SBC 2018",
    },
)
