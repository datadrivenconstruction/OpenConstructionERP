# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner-pack demo: 住宅小区 - 深圳南山 (Residential Community, Shenzhen Nanshan)
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
# 2024 text is in hand. Note the prefix when reading the two: the 2013
# edition is GB, a mandatory code, and the 2024 edition is GB/T, a
# recommended standard. Shenzhen binds the 2024 standard on state-funded
# and collectively-funded work from 2026-01-01, on top of its own SJG
# consumption standards, so a Shenzhen job priced at 2026 levels is the
# case where this label is most likely to need revisiting once the text
# can be read.
#
# Comprehensive unit rates are Shenzhen 2026 market prices in CNY for a
# high-rise residential community (6 towers, a 2-level basement car park
# and ancillary works) in Nanshan District, Shenzhen. Each item carries
# its project code in the classification dict under the key "gb50500",
# which is the spelling ``classification_order`` returns for a Chinese
# project. It read "gbt50500" until 2026-08, and because the section path
# builder looks the code up by that key and simply finds nothing when it
# misses, every line of this bill rendered with no section path at all and
# nothing anywhere said why. The rule set keeps the older spelling on
# purpose: that is a different namespace and it resolves.
# Descriptions are bilingual (Chinese + English). No em-dashes anywhere;
# plain ASCII hyphens only.
#
# The 9-digit item codes below (e.g. 010101001) were authored against
# the 2013 measurement standard, which is the other reason the bill is
# labelled 2013: it is the edition the data actually follows. Whether
# the 2024 family shifted the appendix chapter numbering has not been
# checked against the standard text, so the codes are left as authored
# rather than renumbered on inference. A wrong code that looks current
# is worse than an old one, because the old one is at least traceable.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-shenzhen",
    project_name="住宅小区 - 深圳南山 (Residential Community, Shenzhen Nanshan)",
    project_description=(
        "新建高层住宅小区，共 6 栋塔楼，地上 28 至 33 层，2 层整体地下室及车库，"
        "总建筑面积约 168,000 平方米（地上约 132,000 平方米，地下约 36,000 平方米），"
        "共 1,180 套住宅及约 1,050 个机动车位。剪力墙结构，单元式装配整体式构件，"
        "外墙真石漆及局部干挂石材，铝合金断桥隔热中空玻璃门窗。抗震设防烈度 7 度，"
        "按 GB 50011-2010 设计。绿色建筑二星级（GB/T 50378），装配率不低于 50%。"
        "造价按深圳 2026 年价格水平、GB 50500-2013 计价规范编制，工程总造价约人民币 12 亿元。 "
        "New-build high-rise residential community of 6 towers, 28 to 33 storeys "
        "above grade with a 2-level basement car park. Gross floor area approx. "
        "168,000 m2 (approx. 132,000 m2 above grade, 36,000 m2 below), 1,180 "
        "dwelling units and approx. 1,050 parking bays. Shear-wall structure with "
        "precast monolithic components; textured stone-effect render with local "
        "dry-hung stone, aluminium thermal-break double-glazed windows. Seismic "
        "design intensity 7 to GB 50011-2010. Two-star Green Building (GB/T 50378), "
        "prefabrication ratio at least 50 percent. Priced at Shenzhen 2026 levels "
        "on GB 50500-2013. Headline construction cost approx. CNY 1.2 billion."
    ),
    region="CN",
    classification_standard="gb50500",
    currency="CNY",
    locale="zh",
    address={
        "street": "科苑南路 2888 号 (2888 Keyuan South Road)",
        "city": "深圳 (Shenzhen)",
        "postcode": "518052",
        "country": "China",
        "lat": 22.5108,
        "lng": 113.9332,
    },
    validation_rule_sets=["gbt50500", "boq_quality", "project_completeness"],
    boq_name="工程量清单 - GB 50500-2013 (Bill of Quantities)",
    boq_description=(
        "按 GB 50500-2013《建设工程工程量清单计价规范》编制的分部分项工程量清单，"
        "综合单价含人工、材料、机械、管理费及利润，深圳 2026 年价。 "
        "Bill of Quantities to GB 50500-2013; comprehensive unit rates "
        "include labour, materials, plant, overheads and profit, Shenzhen "
        "2026 price level."
    ),
    boq_metadata={
        "standard": "GB 50500-2013",
        "phase": "施工图预算 / 招标工程量清单 (Tender BoQ)",
        "base_date": "2026-Q1",
        "price_level": "深圳 2026 (Shenzhen 2026)",
    },
    sections=[
        # ── 0101 土石方工程 (Earthworks) ──────────────────────────────
        (
            "0101",
            "土石方工程 (Earthworks)",
            {"gb50500": "0101"},
            [
                ("0101.1", "平整场地 (Site clearance and grading)", "m2", 28000, 9.50, {"gb50500": "010101001"}),
                (
                    "0101.2",
                    "挖一般土方，机械开挖 (General excavation, machine)",
                    "m3",
                    285000,
                    26.00,
                    {"gb50500": "010101002"},
                ),
                (
                    "0101.3",
                    "挖基坑土方，两层地下室 (Pit excavation, 2 basements)",
                    "m3",
                    96000,
                    38.00,
                    {"gb50500": "010101004"},
                ),
                (
                    "0101.4",
                    "挖石方，中风化花岗岩 (Rock excavation, moderately weathered granite)",
                    "m3",
                    42000,
                    168.00,
                    {"gb50500": "010102001"},
                ),
                (
                    "0101.5",
                    "土石方外运，运距 15km 内 (Spoil haulage and disposal, within 15 km)",
                    "m3",
                    360000,
                    36.00,
                    {"gb50500": "010103002"},
                ),
                (
                    "0101.6",
                    "基坑回填土，分层夯实 (Backfill, layered and compacted)",
                    "m3",
                    48000,
                    30.00,
                    {"gb50500": "010103001"},
                ),
                (
                    "0101.7",
                    "室内回填级配砂石 (Graded sand-gravel fill under floors)",
                    "m3",
                    14500,
                    92.00,
                    {"gb50500": "010103001"},
                ),
                (
                    "0101.8",
                    "基坑管井降水 (Tube-well dewatering of pit)",
                    "项",
                    1,
                    2150000.00,
                    {"gb50500": "010103004"},
                ),
            ],
        ),
        # ── 0102 地基处理与边坡支护 (Ground treatment and shoring) ─────
        (
            "0102",
            "地基处理与基坑支护工程 (Ground treatment and pit support)",
            {"gb50500": "0102"},
            [
                (
                    "0102.1",
                    "灌注桩排桩支护 D=1000mm (Bored-pile retaining wall D1000)",
                    "m",
                    16800,
                    1620.00,
                    {"gb50500": "010201001"},
                ),
                (
                    "0102.2",
                    "三轴水泥搅拌桩止水帷幕 (Triaxial cement-mixing water cutoff)",
                    "m3",
                    22000,
                    415.00,
                    {"gb50500": "010201013"},
                ),
                (
                    "0102.3",
                    "预应力锚索及腰梁 (Prestressed anchor cables and wales)",
                    "m",
                    9600,
                    285.00,
                    {"gb50500": "010201009"},
                ),
                (
                    "0102.4",
                    "土钉墙喷锚支护 (Soil-nail wall with shotcrete)",
                    "m2",
                    8200,
                    168.00,
                    {"gb50500": "010201008"},
                ),
                (
                    "0102.5",
                    "高压旋喷桩地基加固 (Jet-grouting pile ground improvement)",
                    "m",
                    6400,
                    320.00,
                    {"gb50500": "010201002"},
                ),
                (
                    "0102.6",
                    "基坑监测及第三方检测 (Pit monitoring and third-party testing)",
                    "项",
                    1,
                    1350000.00,
                    {"gb50500": "010201001"},
                ),
            ],
        ),
        # ── 0103 桩基工程 (Piling) ────────────────────────────────────
        (
            "0103",
            "桩基工程 (Piling and foundations)",
            {"gb50500": "0103"},
            [
                (
                    "0103.1",
                    "钻孔灌注桩 D=800mm，C40 水下混凝土 (Bored cast-in-situ pile D800, C40)",
                    "m",
                    32000,
                    1180.00,
                    {"gb50500": "010302001"},
                ),
                (
                    "0103.2",
                    "钻孔灌注桩 D=600mm (Bored cast-in-situ pile D600)",
                    "m",
                    18500,
                    860.00,
                    {"gb50500": "010302001"},
                ),
                (
                    "0103.3",
                    "预应力混凝土管桩 PHC-500 (Prestressed concrete pipe pile PHC-500)",
                    "m",
                    24000,
                    320.00,
                    {"gb50500": "010301002"},
                ),
                (
                    "0103.4",
                    "桩基钢筋笼制作安装 HRB400 (Pile cage reinforcement HRB400)",
                    "t",
                    1680,
                    6450.00,
                    {"gb50500": "010302001"},
                ),
                (
                    "0103.5",
                    "灌注桩泥浆护壁与外运 (Slurry wall support and disposal)",
                    "m3",
                    28000,
                    62.00,
                    {"gb50500": "010302001"},
                ),
                ("0103.6", "截桩头 (Pile head trimming)", "根", 1420, 420.00, {"gb50500": "010301004"}),
                (
                    "0103.7",
                    "单桩竖向抗压静载试验 (Static load test of pile)",
                    "组",
                    18,
                    36500.00,
                    {"gb50500": "010302007"},
                ),
                (
                    "0103.8",
                    "桩身完整性低应变检测 (Low-strain pile integrity test)",
                    "根",
                    980,
                    280.00,
                    {"gb50500": "010302007"},
                ),
            ],
        ),
        # ── 0104 混凝土及钢筋混凝土工程 (Cast-in-situ RC) ─────────────
        (
            "0104",
            "混凝土及钢筋混凝土工程 (Cast-in-situ reinforced concrete)",
            {"gb50500": "0104"},
            [
                ("0104.1", "垫层混凝土 C15 (Blinding concrete C15)", "m3", 3200, 510.00, {"gb50500": "010401001"}),
                (
                    "0104.2",
                    "筏板基础混凝土 C40 抗渗 P8 (Raft foundation C40, P8)",
                    "m3",
                    32000,
                    660.00,
                    {"gb50500": "010501004"},
                ),
                (
                    "0104.3",
                    "承台及地梁混凝土 C40 (Pile cap and ground beam C40)",
                    "m3",
                    9800,
                    700.00,
                    {"gb50500": "010501005"},
                ),
                (
                    "0104.4",
                    "剪力墙混凝土 C45 (Shear-wall concrete C45)",
                    "m3",
                    58000,
                    720.00,
                    {"gb50500": "010504001"},
                ),
                (
                    "0104.5",
                    "框架柱混凝土 C40 (Frame column concrete C40)",
                    "m3",
                    8600,
                    740.00,
                    {"gb50500": "010502001"},
                ),
                ("0104.6", "梁混凝土 C35 (Beam concrete C35)", "m3", 22000, 700.00, {"gb50500": "010503002"}),
                (
                    "0104.7",
                    "现浇楼板混凝土 C30 (Suspended slab concrete C30)",
                    "m3",
                    64000,
                    660.00,
                    {"gb50500": "010505001"},
                ),
                ("0104.8", "楼梯混凝土 C30 (Staircase concrete C30)", "m3", 2400, 900.00, {"gb50500": "010506001"}),
                (
                    "0104.9",
                    "地下室外墙混凝土 C40 抗渗 P8 (Basement RC wall C40, P8)",
                    "m3",
                    18500,
                    740.00,
                    {"gb50500": "010504001"},
                ),
                (
                    "0104.10",
                    "现浇构件钢筋 HRB400 (Reinforcement HRB400, in-situ)",
                    "t",
                    38500,
                    5780.00,
                    {"gb50500": "010515001"},
                ),
                (
                    "0104.11",
                    "现浇构件钢筋 HRB500 大直径 (Reinforcement HRB500, large dia.)",
                    "t",
                    8200,
                    6080.00,
                    {"gb50500": "010515001"},
                ),
                (
                    "0104.12",
                    "墙柱模板，铝合金模板 (Wall/column formwork, aluminium system)",
                    "m2",
                    248000,
                    72.00,
                    {"gb50500": "011702011"},
                ),
                (
                    "0104.13",
                    "梁板模板，钢框胶合板 (Beam/slab formwork, steel-framed ply)",
                    "m2",
                    312000,
                    68.00,
                    {"gb50500": "011702014"},
                ),
                (
                    "0104.14",
                    "混凝土泵送及养护 (Concrete pumping and curing)",
                    "m3",
                    165000,
                    36.00,
                    {"gb50500": "010515001"},
                ),
                (
                    "0104.15",
                    "后浇带及微膨胀混凝土 (Post-cast strip, expansive concrete)",
                    "m3",
                    1850,
                    1120.00,
                    {"gb50500": "010508001"},
                ),
            ],
        ),
        # ── 0105 装配式混凝土构件 (Precast concrete components) ────────
        (
            "0105",
            "装配式混凝土工程 (Precast concrete components)",
            {"gb50500": "0105"},
            [
                (
                    "0105.1",
                    "预制叠合楼板，工厂预制 (Precast composite floor slabs, factory-made)",
                    "m3",
                    12800,
                    1450.00,
                    {"gb50500": "010512002"},
                ),
                ("0105.2", "预制楼梯段 (Precast stair flights)", "m3", 1650, 1680.00, {"gb50500": "010512008"}),
                (
                    "0105.3",
                    "预制混凝土外墙挂板 (Precast concrete facade panels)",
                    "m2",
                    26000,
                    580.00,
                    {"gb50500": "010512001"},
                ),
                (
                    "0105.4",
                    "预制阳台及空调板 (Precast balcony and AC ledge units)",
                    "m3",
                    2200,
                    1620.00,
                    {"gb50500": "010512004"},
                ),
                (
                    "0105.5",
                    "构件吊装及灌浆连接 (Component hoisting and grouted connections)",
                    "项",
                    1,
                    6850000.00,
                    {"gb50500": "010515009"},
                ),
                (
                    "0105.6",
                    "套筒灌浆料及坐浆料 (Sleeve grout and bedding mortar)",
                    "t",
                    480,
                    4200.00,
                    {"gb50500": "010515009"},
                ),
            ],
        ),
        # ── 0106 砌筑工程 (Masonry) ───────────────────────────────────
        (
            "0106",
            "砌筑工程 (Masonry)",
            {"gb50500": "0106"},
            [
                (
                    "0106.1",
                    "蒸压加气混凝土砌块墙 200mm (AAC block wall 200 mm)",
                    "m3",
                    22000,
                    460.00,
                    {"gb50500": "010402001"},
                ),
                (
                    "0106.2",
                    "蒸压加气混凝土砌块墙 100mm 隔墙 (AAC block partition 100 mm)",
                    "m2",
                    42000,
                    88.00,
                    {"gb50500": "010402001"},
                ),
                (
                    "0106.3",
                    "烧结页岩砖墙，地下室及设备间 (Fired shale brick wall, basement/plant)",
                    "m3",
                    4800,
                    600.00,
                    {"gb50500": "010401003"},
                ),
                (
                    "0106.4",
                    "砌体加固钢筋及拉结筋 (Masonry tie bars and reinforcement)",
                    "t",
                    168,
                    6280.00,
                    {"gb50500": "010515003"},
                ),
                (
                    "0106.5",
                    "构造柱、过梁、圈梁混凝土 (Constructional columns, lintels, ring beams)",
                    "m3",
                    3600,
                    860.00,
                    {"gb50500": "010507001"},
                ),
                (
                    "0106.6",
                    "填充墙顶斜砌及塞缝 (Infill wall top wedging and grouting)",
                    "m",
                    28500,
                    20.00,
                    {"gb50500": "010402001"},
                ),
            ],
        ),
        # ── 0108 门窗工程 (Doors and windows) ─────────────────────────
        (
            "0108",
            "门窗工程 (Doors and windows)",
            {"gb50500": "0108"},
            [
                (
                    "0108.1",
                    "户内成品木门，含五金 (Apartment timber door set with hardware)",
                    "樘",
                    7080,
                    1180.00,
                    {"gb50500": "010801004"},
                ),
                (
                    "0108.2",
                    "户门，钢质防盗门甲级 (Apartment entrance steel security door, Class A)",
                    "樘",
                    1180,
                    2280.00,
                    {"gb50500": "010802001"},
                ),
                (
                    "0108.3",
                    "钢质防火门，乙级 (Steel fire door, Class B)",
                    "樘",
                    1860,
                    1980.00,
                    {"gb50500": "010802003"},
                ),
                (
                    "0108.4",
                    "铝合金断桥隔热中空玻璃窗 (Aluminium thermal-break double-glazed window)",
                    "m2",
                    38000,
                    720.00,
                    {"gb50500": "010807001"},
                ),
                (
                    "0108.5",
                    "铝合金推拉门，阳台 (Aluminium sliding door, balconies)",
                    "m2",
                    8600,
                    620.00,
                    {"gb50500": "010802004"},
                ),
                (
                    "0108.6",
                    "单元入口玻璃门，电控门禁 (Lobby glass entrance door with access control)",
                    "樘",
                    24,
                    18500.00,
                    {"gb50500": "010805002"},
                ),
                (
                    "0108.7",
                    "车库电动卷帘门 (Garage motorised roller shutter)",
                    "樘",
                    12,
                    24500.00,
                    {"gb50500": "010803001"},
                ),
            ],
        ),
        # ── 0109 屋面及防水工程 (Roofing and waterproofing) ───────────
        (
            "0109",
            "屋面及防水工程 (Roofing and waterproofing)",
            {"gb50500": "0109"},
            [
                (
                    "0109.1",
                    "屋面 SBS 改性沥青卷材防水，双层 (SBS membrane roof waterproofing, 2-ply)",
                    "m2",
                    14500,
                    86.00,
                    {"gb50500": "010902001"},
                ),
                (
                    "0109.2",
                    "屋面挤塑聚苯板保温 80mm (Roof XPS insulation 80 mm)",
                    "m2",
                    14500,
                    58.00,
                    {"gb50500": "011001001"},
                ),
                (
                    "0109.3",
                    "屋面细石混凝土保护层 40mm (Roof fine-aggregate concrete topping 40 mm)",
                    "m2",
                    14500,
                    40.00,
                    {"gb50500": "010902004"},
                ),
                (
                    "0109.4",
                    "地下室底板及侧墙卷材防水 (Basement raft/wall membrane waterproofing)",
                    "m2",
                    62000,
                    76.00,
                    {"gb50500": "010903001"},
                ),
                (
                    "0109.5",
                    "卫生间及厨房聚氨酯防水涂膜 (PU coating waterproofing, bathrooms/kitchens)",
                    "m2",
                    42000,
                    56.00,
                    {"gb50500": "010904001"},
                ),
                (
                    "0109.6",
                    "阳台及露台防水 (Balcony and terrace waterproofing)",
                    "m2",
                    16500,
                    62.00,
                    {"gb50500": "010904001"},
                ),
                (
                    "0109.7",
                    "种植屋面排（蓄）水板及覆土 (Green-roof drainage board and soil)",
                    "m2",
                    3200,
                    158.00,
                    {"gb50500": "010902007"},
                ),
            ],
        ),
        # ── 0111 楼地面装饰工程 (Floor finishes) ──────────────────────
        (
            "0111",
            "楼地面装饰工程 (Floor finishes)",
            {"gb50500": "0111"},
            [
                (
                    "0111.1",
                    "水泥砂浆找平层 (Cement-mortar levelling screed)",
                    "m2",
                    132000,
                    30.00,
                    {"gb50500": "011101001"},
                ),
                (
                    "0111.2",
                    "户内地砖地面，厨卫及客厅 (Tile flooring, kitchens/baths/living)",
                    "m2",
                    78000,
                    145.00,
                    {"gb50500": "011102003"},
                ),
                (
                    "0111.3",
                    "石材地面，单元大堂及电梯厅 (Stone flooring, lobbies and lift halls)",
                    "m2",
                    6800,
                    620.00,
                    {"gb50500": "011102001"},
                ),
                (
                    "0111.4",
                    "地砖地面，公共走道 (Tile flooring, common corridors)",
                    "m2",
                    18500,
                    155.00,
                    {"gb50500": "011102003"},
                ),
                (
                    "0111.5",
                    "环氧自流平地面，车库及设备房 (Epoxy self-levelling floor, garage/plant)",
                    "m2",
                    32000,
                    92.00,
                    {"gb50500": "011101006"},
                ),
                ("0111.6", "地砖踢脚线 (Tile skirting)", "m", 42000, 22.00, {"gb50500": "011105003"}),
                (
                    "0111.7",
                    "金刚砂耐磨地坪，车库行车道 (Emery hardener floor, garage driveways)",
                    "m2",
                    24000,
                    62.00,
                    {"gb50500": "011101006"},
                ),
                (
                    "0111.8",
                    "塑胶地面，活动室及架空层 (Rubber flooring, activity rooms/podium)",
                    "m2",
                    4200,
                    185.00,
                    {"gb50500": "011104003"},
                ),
            ],
        ),
        # ── 0112 墙柱面及天棚装饰工程 (Wall and ceiling finishes) ─────
        (
            "0112",
            "墙柱面及天棚装饰工程 (Wall and ceiling finishes)",
            {"gb50500": "0112"},
            [
                (
                    "0112.1",
                    "内墙水泥砂浆抹灰 (Internal cement-mortar plaster)",
                    "m2",
                    285000,
                    36.00,
                    {"gb50500": "011201001"},
                ),
                (
                    "0112.2",
                    "户内墙面腻子及乳胶漆两遍 (Internal putty and emulsion paint, 2 coats)",
                    "m2",
                    312000,
                    26.00,
                    {"gb50500": "011406001"},
                ),
                (
                    "0112.3",
                    "外墙真石漆，含找平及底涂 (External textured stone-effect render with base coat)",
                    "m2",
                    96000,
                    95.00,
                    {"gb50500": "011407001"},
                ),
                (
                    "0112.4",
                    "外墙干挂石材，裙楼及入口 (Dry-hung stone cladding, podium and entrances)",
                    "m2",
                    8600,
                    685.00,
                    {"gb50500": "011204003"},
                ),
                (
                    "0112.5",
                    "外墙保温，岩棉板薄抹灰系统 (External wall insulation, rock-wool thin-render)",
                    "m2",
                    96000,
                    118.00,
                    {"gb50500": "011001003"},
                ),
                (
                    "0112.6",
                    "厨卫墙面瓷砖 (Wall tiling, kitchens and bathrooms)",
                    "m2",
                    64000,
                    138.00,
                    {"gb50500": "011204004"},
                ),
                (
                    "0112.7",
                    "户内顶棚刮腻子及乳胶漆 (Ceiling putty and emulsion, apartments)",
                    "m2",
                    128000,
                    28.00,
                    {"gb50500": "011407002"},
                ),
                (
                    "0112.8",
                    "石膏板吊顶，大堂及公共区 (Plasterboard ceiling, lobbies/public areas)",
                    "m2",
                    12500,
                    115.00,
                    {"gb50500": "011302001"},
                ),
                (
                    "0112.9",
                    "铝扣板吊顶，厨卫 (Aluminium-panel ceiling, kitchens/baths)",
                    "m2",
                    38000,
                    128.00,
                    {"gb50500": "011302001"},
                ),
                (
                    "0112.10",
                    "单元大堂石材干挂墙面 (Dry-hung stone wall, lobbies)",
                    "m2",
                    4200,
                    660.00,
                    {"gb50500": "011204003"},
                ),
                (
                    "0112.11",
                    "外墙铝合金线条及装饰构件 (External aluminium trim and decorative elements)",
                    "m",
                    9600,
                    145.00,
                    {"gb50500": "011209001"},
                ),
            ],
        ),
        # ── 0113 油漆、涂料及裱糊工程 (Painting and coatings) ─────────
        (
            "0113",
            "油漆、涂料及防护工程 (Painting, coatings and protection)",
            {"gb50500": "0113"},
            [
                (
                    "0113.1",
                    "金属栏杆及构件防锈防腐涂装 (Metalwork anti-rust and protective coating)",
                    "m2",
                    18500,
                    48.00,
                    {"gb50500": "011401001"},
                ),
                (
                    "0113.2",
                    "车库墙顶面涂料 (Garage wall and soffit coating)",
                    "m2",
                    86000,
                    22.00,
                    {"gb50500": "011406001"},
                ),
                (
                    "0113.3",
                    "外露钢结构防火涂料，架空层 (Fire-retardant coating to exposed steel, podium)",
                    "m2",
                    3200,
                    88.00,
                    {"gb50500": "011403001"},
                ),
                (
                    "0113.4",
                    "停车位划线及交通标识 (Parking-bay line marking and traffic signage)",
                    "项",
                    1,
                    480000.00,
                    {"gb50500": "011406001"},
                ),
            ],
        ),
        # ── 0304 电气设备安装工程 (Electrical) ───────────────────────
        (
            "0304",
            "电气设备安装工程 (Electrical installation)",
            {"gb50500": "0304"},
            [
                (
                    "0304.1",
                    "10kV 箱式变电站，4x1250kVA (10kV package substation, 4x1250 kVA)",
                    "项",
                    1,
                    7850000.00,
                    {"gb50500": "030404017"},
                ),
                ("0304.2", "柴油发电机组 800kW (Diesel genset 800 kW)", "台", 2, 1850000.00, {"gb50500": "030409001"}),
                (
                    "0304.3",
                    "低压配电柜及双电源切换 (LV switchgear and ATS)",
                    "项",
                    1,
                    4850000.00,
                    {"gb50500": "030404017"},
                ),
                (
                    "0304.4",
                    "户内配电箱及计量表箱 (Apartment distribution and meter boards)",
                    "台",
                    1180,
                    1280.00,
                    {"gb50500": "030404017"},
                ),
                (
                    "0304.5",
                    "母线槽 2500A 垂直供电 (Busduct 2500 A, vertical risers)",
                    "m",
                    2400,
                    2280.00,
                    {"gb50500": "030408001"},
                ),
                (
                    "0304.6",
                    "电力电缆敷设，YJV 铜芯 (Power cable laying, YJV copper)",
                    "m",
                    168000,
                    82.00,
                    {"gb50500": "030408001"},
                ),
                (
                    "0304.7",
                    "桥架及线槽，热镀锌 (Cable tray and trunking, hot-dip galv.)",
                    "m",
                    62000,
                    92.00,
                    {"gb50500": "030411001"},
                ),
                (
                    "0304.8",
                    "管内穿线及配电支线 (Conduit wiring and final circuits)",
                    "m",
                    485000,
                    11.50,
                    {"gb50500": "030411004"},
                ),
                (
                    "0304.9",
                    "LED 灯具，公共区及车库 (LED luminaires, public areas and garage)",
                    "套",
                    28500,
                    168.00,
                    {"gb50500": "030412001"},
                ),
                (
                    "0304.10",
                    "应急照明及疏散指示 (Emergency lighting and exit signs)",
                    "套",
                    6800,
                    158.00,
                    {"gb50500": "030412004"},
                ),
                (
                    "0304.11",
                    "新能源汽车充电桩，7kW 交流 (EV charging points, 7 kW AC)",
                    "台",
                    320,
                    6850.00,
                    {"gb50500": "030409001"},
                ),
                (
                    "0304.12",
                    "防雷接地及等电位联结 (Lightning protection and equipotential bonding)",
                    "项",
                    1,
                    1650000.00,
                    {"gb50500": "030409002"},
                ),
                (
                    "0304.13",
                    "火灾自动报警系统 (Automatic fire-alarm system)",
                    "项",
                    1,
                    4250000.00,
                    {"gb50500": "030904001"},
                ),
                (
                    "0304.14",
                    "智能化及社区安防系统 (Smart-community and security system)",
                    "项",
                    1,
                    5850000.00,
                    {"gb50500": "030503001"},
                ),
                (
                    "0304.15",
                    "可视对讲及门禁系统 (Video intercom and access-control system)",
                    "项",
                    1,
                    3650000.00,
                    {"gb50500": "030502001"},
                ),
            ],
        ),
        # ── 0306 给排水、暖通空调工程 (Plumbing and HVAC) ────────────
        (
            "0306",
            "给排水、暖通空调工程 (Plumbing, HVAC and ventilation)",
            {"gb50500": "0306"},
            [
                (
                    "0306.1",
                    "给水管道，PP-R 及钢塑复合管 (Water-supply piping, PP-R and steel-plastic)",
                    "m",
                    96000,
                    78.00,
                    {"gb50500": "031001001"},
                ),
                (
                    "0306.2",
                    "排水管道，UPVC 及柔性铸铁管 (Drainage piping, UPVC and flexible cast iron)",
                    "m",
                    88000,
                    95.00,
                    {"gb50500": "031001005"},
                ),
                (
                    "0306.3",
                    "雨水管道及虹吸排水 (Rainwater and siphonic drainage)",
                    "m",
                    18500,
                    128.00,
                    {"gb50500": "031001006"},
                ),
                (
                    "0306.4",
                    "户内卫生器具及配件安装 (Apartment sanitary fixtures and fittings)",
                    "组",
                    4720,
                    980.00,
                    {"gb50500": "031004003"},
                ),
                (
                    "0306.5",
                    "太阳能热水系统，集中式 (Centralised solar hot-water system)",
                    "项",
                    1,
                    4850000.00,
                    {"gb50500": "031003013"},
                ),
                (
                    "0306.6",
                    "生活水泵及变频供水设备 (Domestic pumps and VFD water-supply set)",
                    "项",
                    1,
                    2650000.00,
                    {"gb50500": "031003013"},
                ),
                (
                    "0306.7",
                    "消火栓系统及管网 (Fire-hydrant system and pipework)",
                    "项",
                    1,
                    4250000.00,
                    {"gb50500": "030901001"},
                ),
                (
                    "0306.8",
                    "自动喷淋灭火系统，车库及公区 (Automatic sprinkler system, garage/public)",
                    "m2",
                    96000,
                    88.00,
                    {"gb50500": "030901002"},
                ),
                (
                    "0306.9",
                    "户式多联机空调预留及冷媒管 (Apartment VRF provisions and refrigerant pipe)",
                    "套",
                    1180,
                    4200.00,
                    {"gb50500": "030701008"},
                ),
                (
                    "0306.10",
                    "地下车库通风及防排烟系统 (Garage ventilation and smoke-extract system)",
                    "项",
                    1,
                    6850000.00,
                    {"gb50500": "030703001"},
                ),
                (
                    "0306.11",
                    "镀锌钢板风管制作安装 (Galvanised-steel ductwork)",
                    "m2",
                    58000,
                    158.00,
                    {"gb50500": "030702001"},
                ),
                (
                    "0306.12",
                    "防排烟风机及加压送风系统 (Smoke-extract and pressurisation fans)",
                    "项",
                    1,
                    3250000.00,
                    {"gb50500": "030703001"},
                ),
                (
                    "0306.13",
                    "客梯及消防电梯，1.75m/s (Passenger and fire lifts, 1.75 m/s)",
                    "台",
                    36,
                    980000.00,
                    {"gb50500": "030601001"},
                ),
                ("0306.14", "燃气管道及计量 (Gas piping and metering)", "m", 24000, 88.00, {"gb50500": "031101001"}),
            ],
        ),
        # ── 0205 园林绿化及室外配套 (Landscape and external works) ────
        (
            "0205",
            "园林绿化及室外配套工程 (Landscape and external works)",
            {"gb50500": "0205"},
            [
                (
                    "0205.1",
                    "园路及广场铺装，透水砖 (Pathway and plaza paving, permeable brick)",
                    "m2",
                    18500,
                    185.00,
                    {"gb50500": "050201001"},
                ),
                (
                    "0205.2",
                    "乔木种植，含支撑及养护 (Tree planting, with staking and care)",
                    "根",
                    480,
                    1850.00,
                    {"gb50500": "050102001"},
                ),
                (
                    "0205.3",
                    "灌木及地被种植 (Shrub and groundcover planting)",
                    "m2",
                    26000,
                    95.00,
                    {"gb50500": "050102004"},
                ),
                ("0205.4", "草坪铺植 (Lawn turfing)", "m2", 14500, 38.00, {"gb50500": "050102004"}),
                (
                    "0205.5",
                    "景观水景及循环系统 (Water feature and recirculation system)",
                    "项",
                    1,
                    2850000.00,
                    {"gb50500": "050304001"},
                ),
                (
                    "0205.6",
                    "室外综合管网，雨污水及给水 (External utility network, drainage and water)",
                    "m",
                    9600,
                    420.00,
                    {"gb50500": "050201001"},
                ),
                (
                    "0205.7",
                    "围墙、大门及门卫房 (Boundary wall, gates and guardhouse)",
                    "项",
                    1,
                    1850000.00,
                    {"gb50500": "050201001"},
                ),
                (
                    "0205.8",
                    "儿童活动场地及健身设施 (Children play area and fitness equipment)",
                    "项",
                    1,
                    1280000.00,
                    {"gb50500": "050304005"},
                ),
                (
                    "0205.9",
                    "室外照明及景观灯具 (External lighting and landscape luminaires)",
                    "套",
                    1850,
                    1280.00,
                    {"gb50500": "030412001"},
                ),
                (
                    "0205.10",
                    "海绵城市设施，雨水花园及调蓄 (Sponge-city features, rain gardens and storage)",
                    "项",
                    1,
                    3650000.00,
                    {"gb50500": "050201001"},
                ),
            ],
        ),
    ],
    # Chinese construction cost build-up. The enterprise management fee and
    # profit are the two 综合单价 components, and they carry the ``overhead``
    # and ``profit`` categories because that is what the per-position price
    # analysis reads to split a unit rate. 安全文明施工费 and 规费 are heads on
    # the 造价形成 axis rather than parts of a rate, so they are ``other``:
    # while they were categorised as overhead the analysis sheet reported ten
    # percent of overhead inside a rate whose management fee is 4.5. All four
    # are taken on the direct cost; VAT (output) is taken on the cumulative
    # amount (general tax method 9%).
    markups=[
        ("安全文明施工费 (Safe and civilised construction fee 2.5%)", 2.5, "other", "direct_cost"),
        ("企业管理费 (Enterprise management fee 4.5%)", 4.5, "overhead", "direct_cost"),
        ("规费 (Statutory charges 3%)", 3.0, "other", "direct_cost"),
        ("利润 (Profit 6.5%)", 6.5, "profit", "direct_cost"),
        ("增值税 (Value-added tax, VAT 9%)", 9.0, "tax", "cumulative"),
    ],
    total_months=30,
    tender_name="土建及机电总承包 (Civil and MEP main contract)",
    tender_companies=[
        ("屹澜建筑 (Yilan Construction)", "tender@yilan.example", 0.98),
        ("深圳市黎沐建工集团 (Shenzhen Limu Construction Group)", "bids@limu.example", 1.02),
        ("桓岳建设集团 (Huanyue Construction Group)", "tender@huanyue.example", 1.01),
    ],
    project_metadata={
        "address": "深圳市南山区科苑南路 2888 号 (2888 Keyuan South Road, Nanshan, Shenzhen 518052)",
        "client": "深圳筑荟安居集团有限公司 (Shenzhen Zhuhui Housing Group Co., Ltd.)",
        "architect": "深圳市棠序建筑设计研究总院 (Shenzhen Tangxu General Institute of Architectural Design & Research)",
        "structural_consultant": "深圳市棠序建筑设计研究总院结构院 (TXGI Structural Division)",
        "gfa_m2": 168000,
        "dwelling_units": 1180,
        "parking_bays": 1050,
        "storeys": "地上 28 至 33 层，地下 2 层 (28 to 33 above grade, 2 basements)",
        "structure_system": "剪力墙结构，装配整体式 (Shear-wall structure, precast monolithic)",
        "seismic_design": "抗震设防烈度 7 度 (GB 50011-2010, intensity 7)",
        "design_codes": "GB 50010 (混凝土结构), GB 50011 (抗震), GB 50009 (荷载), GB 50016 (建筑防火), GB 50096 (住宅设计规范), GB 50368 (住宅建筑规范)",
        "pricing_standard": "GB 50500-2013《建设工程工程量清单计价规范》 (Standard Method of Measurement)",
        "measurement_standard": "GB 50854-2013《房屋建筑与装饰工程工程量计算规范》 (Quantity calculation code)",
        "prefabrication": "装配率不低于 50% (Prefabrication ratio at least 50 percent)",
        "sustainability": "绿色建筑二星级 (GB/T 50378 Two-star); 海绵城市设计 (Sponge-city design)",
        "tax_note": (
            "清单综合单价为不含税直接费；增值税按一般计税方法 9% 单列。 "
            "BoQ comprehensive unit rates are tax-exclusive direct cost; VAT "
            "at 9% (general tax method) is shown as a separate line."
        ),
        "statutory": (
            "施工图审查、消防设计审查、人防工程及竣工验收备案按深圳市住建局要求办理。 "
            "Drawing review, fire-design review, civil-defence works and "
            "completion filing per the Shenzhen Housing & Construction Bureau."
        ),
        "headline_cost_cny": "约人民币 12 亿元 (approx. CNY 1.2 billion)",
    },
    tender_packages=[
        (
            "桩基及基坑支护 (Piling and pit support)",
            "钻孔灌注桩、预应力管桩、排桩支护、止水帷幕及锚索支护",
            "evaluating",
            [
                ("屹澜建筑 (Yilan Construction)", "tender@yilan.example", 0.98),
                ("深圳市黎沐建工集团 (Shenzhen Limu Construction Group)", "bids@limu.example", 1.02),
                ("桓岳建设集团 (Huanyue Construction Group)", "tender@huanyue.example", 1.01),
            ],
        ),
        (
            "主体结构及装配式构件 (Superstructure and precast components)",
            "剪力墙、框架、楼板、楼梯及装配式叠合板、外墙挂板吊装",
            "evaluating",
            [
                ("深圳市黎沐建工集团 (Shenzhen Limu Construction Group)", "bids@limu.example", 0.99),
                ("祁川建设集团 (Qichuan Construction Group)", "tender@qichuan.example", 1.03),
                ("砚溪建设 (Yanxi Construction Group)", "bids@yanxi.example", 1.02),
            ],
        ),
        (
            "外立面及门窗 (Facade and windows)",
            "外墙真石漆、干挂石材、外保温系统及铝合金门窗安装",
            "evaluating",
            [
                ("宸砺幕墙 (Chenli Facade)", "tender@chenli.example", 0.98),
                ("澜屿幕墙 (Lanyu Curtain Wall)", "bids@lanyu.example", 1.04),
                ("樾泓幕墙 (Yuehong Curtain Wall)", "tender@yuehong.example", 1.01),
            ],
        ),
        (
            "机电安装 (MEP installation)",
            "给排水、消防、通风、电气、智能化、电梯及充电设施安装",
            "evaluating",
            [
                ("深圳市阙铭安装集团 (Shenzhen Queming Installation Group)", "tender@queming.example", 0.99),
                ("骏枢智能电子 (Junshu Intelligent Electronics)", "bids@junshu.example", 1.03),
                ("洵坤机电 (Xunkun Electromechanical)", "tender@xunkun.example", 1.02),
            ],
        ),
        (
            "精装修及室外园林 (Interior fit-out and landscape)",
            "户内精装修、公共部位装修、园林绿化及室外配套工程",
            "evaluating",
            [
                ("青梧建筑装饰 (Qingwu Construction Decoration)", "tender@qingwu.example", 0.98),
                ("黛屏装饰 (Daiping Decoration)", "bids@daiping.example", 1.04),
                ("鹭汀装饰集团 (Luting Decoration Group)", "tender@luting.example", 1.02),
            ],
        ),
    ],
    budget_boq_name="施工图预算 - GB 50500-2013 (Control Budget)",
    planned_budget=1_200_000_000.0,
    actual_spend_ratio=0.40,
    spi_override=1.01,
    cpi_override=0.99,
)
