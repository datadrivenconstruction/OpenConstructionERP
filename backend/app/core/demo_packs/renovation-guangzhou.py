# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner-pack demo: 旧改商业综合体 - 广州天河 (Commercial renovation, Guangzhou Tianhe)
# ---------------------------------------------------------------------------
# Bill of Quantities prepared to the Chinese national standard
# GB 50500-2013, the pricing code for bill of quantities valuation of
# construction works.
#
# WHY 2013 AND NOT 2024. GB/T 50500-2024 superseded this edition from
# 2025-09-01, and the 2024 measurement standards GB/T 50854-2024 through
# GB/T 50862-2024 replaced the measurement family on the same date. We
# could not obtain either text, so we cannot state what conformance to
# them requires and this bill does not claim it. The label follows what
# we can verify rather than what is newest, and it moves the day the
# 2024 text is in hand.
#
# This bill covers a substantial interior and systems renovation of an
# existing commercial complex in Tianhe District, Guangzhou. The scope
# includes demolition, structural reinforcement of load-bearing members,
# complete MEP replacement, interior fit-out and facade remediation.
# Comprehensive unit rates are Guangzhou 2026 market prices in CNY.
#
# The 9-digit item codes follow GB 50854-2013 (building and decoration)
# and GB 50856-2013 (installations) for an alteration/renovation scope.
# Renovation works use the same national item code system as new-build,
# but items such as selective demolition do not have distinct codes in
# GB 50854 and are priced under the nearest scope match with a suffix
# description. Descriptions are bilingual (Chinese + English).
# No em-dashes anywhere; plain ASCII hyphens only.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="renovation-guangzhou",
    project_name="旧改商业综合体 - 广州天河 (Commercial Renovation, Guangzhou Tianhe)",
    project_description=(
        "既有商业综合体整体改造，位于广州天河区核心商圈，地上 5 层商业裙楼及 2 层地下室。"
        "改造面积约 38,000 平方米（商业 28,000 平方米，地下车库及设备 10,000 平方米），"
        "包括拆除原有装修及机电系统、结构加固（碳纤维/粘钢加固楼板及梁柱）、"
        "全新精装修、暖通空调更换、电气及消防系统全面升级、外立面整修。"
        "改造后定位为中高端零售及餐饮综合体，设计使用年限延长 30 年。"
        "造价按广州 2026 年价格水平、GB 50500-2013 计价规范编制，工程造价约人民币 1.52 亿元。 "
        "Comprehensive renovation of an existing commercial complex in the "
        "central Tianhe commercial district, Guangzhou. 5-storey retail podium "
        "with 2 basement levels. Renovation area approx. 38,000 m2 (28,000 m2 "
        "retail, 10,000 m2 basement car park and plant). Scope covers strip-out "
        "of existing finishes and MEP, structural strengthening (CFRP and "
        "bonded-steel plate reinforcement to slabs, beams and columns), "
        "complete interior fit-out, HVAC replacement, full electrical and "
        "fire-protection upgrade, and facade remediation. Post-renovation "
        "positioning as mid-to-high-end retail and F&B complex with a 30-year "
        "design-life extension. Priced at Guangzhou 2026 levels on "
        "GB 50500-2013. Headline cost approx. CNY 152 million."
    ),
    region="CN",
    classification_standard="gb50500",
    currency="CNY",
    locale="zh",
    address={
        "street": "天河路 385 号 (385 Tianhe Road)",
        "city": "广州 (Guangzhou)",
        "postcode": "510620",
        "country": "China",
        "lat": 23.1365,
        "lng": 113.3292,
    },
    validation_rule_sets=["gbt50500", "boq_quality", "project_completeness"],
    boq_name="工程量清单 - GB 50500-2013 (Bill of Quantities - Renovation)",
    boq_description=(
        "按 GB 50500-2013《建设工程工程量清单计价规范》编制的改造工程量清单，"
        "综合单价含人工、材料、机械、管理费及利润，广州 2026 年价。 "
        "Bill of Quantities to GB 50500-2013 for renovation works; "
        "comprehensive unit rates include labour, materials, plant, "
        "overheads and profit, Guangzhou 2026 price level."
    ),
    boq_metadata={
        "standard": "GB 50500-2013",
        "phase": "施工图预算 / 招标工程量清单 (Tender BoQ - Renovation)",
        "base_date": "2026-Q1",
        "price_level": "广州 2026 (Guangzhou 2026)",
    },
    sections=[
        # -- 01 拆除工程 (Demolition) ----------------------------------------
        (
            "01",
            "拆除工程 (Demolition and strip-out)",
            {"gb50500": "01"},
            [
                ("01.1", "拆除轻质隔墙 (Demolish lightweight partitions)", "m2", 8500, 18.00, {"gb50500": "011501001"}),
                ("01.2", "拆除吊顶及龙骨 (Remove suspended ceilings and framing)", "m2", 22000, 12.00, {"gb50500": "011502001"}),
                ("01.3", "拆除地面面层 (Remove floor finishes)", "m2", 28000, 15.00, {"gb50500": "011503001"}),
                ("01.4", "拆除墙面面层及瓷砖 (Remove wall finishes and tiles)", "m2", 18000, 14.00, {"gb50500": "011504001"}),
                ("01.5", "拆除旧门窗 (Remove existing doors and windows)", "樘", 650, 85.00, {"gb50500": "011505001"}),
                ("01.6", "拆除旧电气线路及灯具 (Strip out existing electrical wiring)", "m2", 28000, 22.00, {"gb50500": "011506001"}),
                ("01.7", "拆除旧暖通管道及风机 (Strip out existing HVAC ductwork)", "m2", 28000, 28.00, {"gb50500": "011507001"}),
                ("01.8", "拆除旧给排水管道 (Strip out existing plumbing)", "m2", 10000, 18.00, {"gb50500": "011508001"}),
                ("01.9", "建筑垃圾外运及处置 (Demolition waste haulage and disposal)", "m3", 9500, 65.00, {"gb50500": "010103002"}),
            ],
        ),
        # -- 02 结构加固工程 (Structural strengthening) ----------------------
        (
            "02",
            "结构加固工程 (Structural strengthening)",
            {"gb50500": "02"},
            [
                ("02.1", "碳纤维布加固梁 (CFRP sheet strengthening to beams)", "m2", 4200, 380.00, {"gb50500": "010509001"}),
                ("02.2", "碳纤维布加固楼板 (CFRP sheet strengthening to slabs)", "m2", 6800, 350.00, {"gb50500": "010509001"}),
                ("02.3", "粘钢板加固柱 (Bonded steel-plate strengthening to columns)", "m2", 1800, 520.00, {"gb50500": "010509002"}),
                ("02.4", "植筋加固 HRB400 (Post-installed rebar, HRB400)", "根", 12000, 35.00, {"gb50500": "010509003"}),
                ("02.5", "环氧注浆修复裂缝 (Epoxy injection crack repair)", "m", 2800, 120.00, {"gb50500": "010509004"}),
                ("02.6", "混凝土局部凿除与修复 (Concrete patch repair)", "m2", 1500, 280.00, {"gb50500": "010509005"}),
                ("02.7", "新增钢梁支撑 H400x200 (New steel beam support H400x200)", "t", 85, 12500.00, {"gb50500": "010510001"}),
                ("02.8", "加固工程检测，回弹法 (Structural testing, rebound hammer)", "项", 1, 185000.00, {"gb50500": "010509001"}),
            ],
        ),
        # -- 03 防水工程 (Waterproofing) ------------------------------------
        (
            "03",
            "防水工程 (Waterproofing)",
            {"gb50500": "03"},
            [
                ("03.1", "地下室外墙重做防水卷材 (Basement wall re-waterproofing, membrane)", "m2", 4200, 95.00, {"gb50500": "010903001"}),
                ("03.2", "卫生间聚氨酯防水涂膜 (PU waterproofing coating, toilets)", "m2", 3600, 62.00, {"gb50500": "010904001"}),
                ("03.3", "屋面防水翻修 SBS 双层 (Roof re-waterproofing, SBS 2-ply)", "m2", 5500, 92.00, {"gb50500": "010902001"}),
                ("03.4", "厨房区域防水涂膜 (Waterproof coating, kitchen areas)", "m2", 2800, 58.00, {"gb50500": "010904001"}),
                ("03.5", "变形缝防水处理 (Expansion joint waterproofing)", "m", 380, 185.00, {"gb50500": "010903003"}),
            ],
        ),
        # -- 04 楼地面装饰工程 (Floor finishes) ------------------------------
        (
            "04",
            "楼地面装饰工程 (Floor finishes)",
            {"gb50500": "04"},
            [
                ("04.1", "水泥自流平找平层 (Self-levelling cement screed)", "m2", 28000, 42.00, {"gb50500": "011101001"}),
                ("04.2", "石材地面，公共中庭及走道 (Stone flooring, atrium and corridors)", "m2", 6500, 720.00, {"gb50500": "011102001"}),
                ("04.3", "大理石拼花地面，主入口 (Marble mosaic flooring, main entrance)", "m2", 280, 1850.00, {"gb50500": "011102002"}),
                ("04.4", "瓷砖地面，餐饮区 (Porcelain tile flooring, F&B zone)", "m2", 8500, 185.00, {"gb50500": "011102003"}),
                ("04.5", "防滑地砖，卫生间 (Anti-slip tile, toilets)", "m2", 2200, 165.00, {"gb50500": "011102003"}),
                ("04.6", "环氧自流平，地下车库 (Epoxy self-levelling floor, basement parking)", "m2", 10000, 95.00, {"gb50500": "011101006"}),
                ("04.7", "石材踢脚线 80mm (Stone skirting 80 mm)", "m", 5200, 62.00, {"gb50500": "011105002"}),
                ("04.8", "木地板，品牌店铺公区 (Timber flooring, branded retail common areas)", "m2", 3200, 320.00, {"gb50500": "011103001"}),
            ],
        ),
        # -- 05 墙柱面及天棚装饰工程 (Wall and ceiling finishes) -------------
        (
            "05",
            "墙柱面及天棚装饰工程 (Wall, column and ceiling finishes)",
            {"gb50500": "05"},
            [
                ("05.1", "内墙水泥砂浆抹灰 (Internal cement-mortar plaster)", "m2", 42000, 38.00, {"gb50500": "011201001"}),
                ("05.2", "乳胶漆两遍含腻子 (Emulsion paint, 2 coats incl. putty)", "m2", 48000, 32.00, {"gb50500": "011406001"}),
                ("05.3", "石材干挂墙面，中庭 (Dry-hung stone wall cladding, atrium)", "m2", 3800, 720.00, {"gb50500": "011204003"}),
                ("05.4", "墙面瓷砖，卫生间及后厨 (Wall tiling, toilets and kitchens)", "m2", 6200, 155.00, {"gb50500": "011204004"}),
                ("05.5", "铝板吊顶，公共走道 (Aluminium panel ceiling, corridors)", "m2", 8500, 285.00, {"gb50500": "011302002"}),
                ("05.6", "石膏板吊顶含造型 (Shaped plasterboard ceiling)", "m2", 12000, 145.00, {"gb50500": "011302001"}),
                ("05.7", "GRG 玻璃纤维增强石膏，中庭天花 (GRG ceiling, atrium)", "m2", 1800, 580.00, {"gb50500": "011302003"}),
                ("05.8", "软膜天花，特色区域 (Stretch ceiling, feature areas)", "m2", 1200, 220.00, {"gb50500": "011302001"}),
                ("05.9", "外墙真石漆翻新 (External texture-stone paint renovation)", "m2", 9500, 65.00, {"gb50500": "011208001"}),
                ("05.10", "外墙铝板幕墙局部更换 (Partial aluminium curtain-wall replacement)", "m2", 2800, 980.00, {"gb50500": "011209002"}),
            ],
        ),
        # -- 06 门窗工程 (Doors and windows) ---------------------------------
        (
            "06",
            "门窗工程 (Doors and windows)",
            {"gb50500": "06"},
            [
                ("06.1", "钢质防火门甲级 (Steel fire door, Class A)", "樘", 85, 2850.00, {"gb50500": "010802003"}),
                ("06.2", "钢质防火门乙级 (Steel fire door, Class B)", "樘", 165, 2280.00, {"gb50500": "010802003"}),
                ("06.3", "玻璃感应自动门，主入口 (Glass auto door, main entrance)", "樘", 8, 42000.00, {"gb50500": "010805002"}),
                ("06.4", "铝合金中空玻璃门窗更换 (Aluminium DGU door/window replacement)", "m2", 3200, 620.00, {"gb50500": "010807001"}),
                ("06.5", "防火卷帘门，分区 (Fire-rated roller shutter, compartmentation)", "m2", 380, 1280.00, {"gb50500": "010803001"}),
                ("06.6", "不锈钢玻璃栏杆，中庭 (Stainless-steel glass balustrade, atrium)", "m", 280, 1650.00, {"gb50500": "010901005"}),
            ],
        ),
        # -- 07 电气设备安装工程 (Electrical) --------------------------------
        (
            "07",
            "电气设备安装工程 (Electrical installation)",
            {"gb50500": "07"},
            [
                ("07.1", "新增变压器 SCB13 干变 1000kVA (New dry transformer 1000 kVA)", "台", 2, 285000.00, {"gb50500": "030404017"}),
                ("07.2", "低压配电柜更换 (LV switchgear replacement)", "项", 1, 1850000.00, {"gb50500": "030404017"}),
                ("07.3", "电力电缆敷设 YJV 铜芯 (Power cable laying, YJV copper)", "m", 32000, 85.00, {"gb50500": "030408001"}),
                ("07.4", "桥架及线槽，热镀锌 (Cable tray and trunking, HDG)", "m", 12000, 95.00, {"gb50500": "030411001"}),
                ("07.5", "管内穿线及支路 (Conduit wiring and final circuits)", "m", 95000, 12.50, {"gb50500": "030411004"}),
                ("07.6", "LED 灯具商业照明 (LED commercial lighting)", "套", 8500, 380.00, {"gb50500": "030412001"}),
                ("07.7", "应急照明及疏散指示更新 (Emergency lighting and exit sign upgrade)", "套", 850, 165.00, {"gb50500": "030412004"}),
                ("07.8", "BA 楼宇自控系统 (BAS building automation system)", "项", 1, 1250000.00, {"gb50500": "030705003"}),
            ],
        ),
        # -- 08 暖通空调安装工程 (HVAC) -------------------------------------
        (
            "08",
            "暖通空调安装工程 (HVAC installation)",
            {"gb50500": "08"},
            [
                ("08.1", "风冷模块化冷水机组 800kW (Air-cooled modular chiller 800 kW)", "台", 3, 520000.00, {"gb50500": "030202001"}),
                ("08.2", "空调箱 AHU 含变频风机 (AHU with VFD fan)", "台", 18, 85000.00, {"gb50500": "030201001"}),
                ("08.3", "新风机组及热回收 (Fresh-air unit with heat recovery)", "台", 12, 62000.00, {"gb50500": "030201002"}),
                ("08.4", "镀锌钢板风管 (Galvanised steel ductwork)", "m2", 18500, 85.00, {"gb50500": "030205001"}),
                ("08.5", "保温风管 (Insulated ductwork)", "m2", 12000, 42.00, {"gb50500": "030205003"}),
                ("08.6", "冷冻水管及保温 (Chilled-water pipe and insulation)", "m", 8500, 185.00, {"gb50500": "030203001"}),
                ("08.7", "排烟系统 (Smoke extract system)", "项", 1, 1850000.00, {"gb50500": "030201003"}),
                ("08.8", "通风百叶及消声器 (Louvres and silencers)", "个", 120, 2800.00, {"gb50500": "030206001"}),
            ],
        ),
        # -- 09 给排水及消防工程 (Plumbing and fire protection) ---------------
        (
            "09",
            "给排水及消防工程 (Plumbing and fire protection)",
            {"gb50500": "09"},
            [
                ("09.1", "给水管道更换，PPR (Water supply pipe, PPR replacement)", "m", 4200, 68.00, {"gb50500": "030101001"}),
                ("09.2", "排水管道更换，HDPE (Drainage pipe, HDPE replacement)", "m", 3800, 85.00, {"gb50500": "030102001"}),
                ("09.3", "消防喷淋系统全面更新 (Fire sprinkler system complete renewal)", "m2", 28000, 45.00, {"gb50500": "030301001"}),
                ("09.4", "消防栓系统更新 (Fire hydrant system renewal)", "项", 1, 680000.00, {"gb50500": "030302001"}),
                ("09.5", "气体灭火系统，配电间 (Gas suppression, electrical rooms)", "项", 1, 380000.00, {"gb50500": "030303001"}),
                ("09.6", "卫生洁具 (Sanitary fittings)", "套", 320, 2200.00, {"gb50500": "030104001"}),
                ("09.7", "雨水排水管道修复 (Rainwater drainage pipe repair)", "m", 850, 120.00, {"gb50500": "030102002"}),
            ],
        ),
        # -- 10 电梯工程 (Lifts) --------------------------------------------
        (
            "10",
            "电梯及扶梯工程 (Lifts and escalators)",
            {"gb50500": "10"},
            [
                ("10.1", "客梯更换 1600kg 无机房 (Passenger lift replacement 1600 kg MRL)", "台", 4, 580000.00, {"gb50500": "030501001"}),
                ("10.2", "货梯更换 3000kg (Goods lift replacement 3000 kg)", "台", 1, 720000.00, {"gb50500": "030501002"}),
                ("10.3", "自动扶梯更换 (Escalator replacement)", "台", 8, 480000.00, {"gb50500": "030502001"}),
                ("10.4", "电梯井道修缮 (Lift shaft refurbishment)", "项", 5, 65000.00, {"gb50500": "030501001"}),
            ],
        ),
    ],
    markups=[
        ("企业管理费 (Enterprise management fee)", 5.5, "overhead", "direct_cost"),
        ("规费 - 社会保险及公积金 (Statutory charges - social insurance and housing fund)", 8.2, "statutory", "direct_cost"),
        ("利润 (Profit)", 4.5, "profit", "direct_cost"),
        ("安全文明施工费 (Safe and civilised construction fee)", 3.8, "safety", "direct_cost"),
        ("增值税 (VAT, general method 9%)", 9.0, "tax", "cumulative"),
    ],
    total_months=14,
    tender_name="旧改商业综合体改造 - 广州天河 (Commercial renovation tender, Guangzhou Tianhe)",
    tender_companies=[
        ("广州粤建建设集团 (Guangzhou Yuejian Construction Group)", "tender@yuejian.example", 0.98),
        ("深圳瑞达装饰工程 (Shenzhen Ruida Decoration Engineering)", "bids@ruida.example", 1.04),
        ("中铁建设集团华南分公司 (CRCC South China Branch)", "tender@crcc-south.example", 1.01),
    ],
    budget_boq_name="改造工程施工图预算 (Renovation control budget)",
    planned_budget=152_000_000.0,
    actual_spend_ratio=0.35,
    spi_override=0.92,
    cpi_override=1.05,
    project_metadata={
        "project_type": "改造 / Renovation",
        "original_construction_year": 2008,
        "renovation_scope": "内装、机电全面更新、结构加固 (Full interior + MEP renewal + structural strengthening)",
        "gfa_m2": 38000,
        "storeys": "地上 5 层，地下 2 层 (5 above grade, 2 basements)",
        "post_renovation_use": "中高端零售及餐饮综合体 (Mid-to-high-end retail and F&B complex)",
        "design_life_extension_years": 30,
        "structure_system": "钢筋混凝土框架 (RC frame, existing)",
        "strengthening_method": "碳纤维 + 粘钢板 + 植筋 (CFRP + bonded steel + post-installed rebar)",
        "seismic_design": "抗震鉴定及加固按 GB 50023-2009 (Seismic appraisal to GB 50023-2009)",
        "fire_rating": "改造后耐火等级一级 (Post-renovation fire resistance Grade I)",
        "pricing_standard": "GB 50500-2013《建设工程工程量清单计价规范》",
        "measurement_standard": "GB 50854-2013《房屋建筑与装饰工程工程量计算规范》",
        "sustainability": "绿色改造评价标准 (Green renovation assessment)",
        "tax_note": (
            "清单综合单价为不含税直接费；增值税按一般计税方法 9% 单列。 "
            "BoQ comprehensive unit rates are tax-exclusive direct cost; VAT "
            "at 9% (general tax method) is shown as a separate line."
        ),
        "headline_cost_cny": "约人民币 1.52 亿元 (approx. CNY 152 million)",
    },
)
