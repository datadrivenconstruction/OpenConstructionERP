# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner-pack demo: Office Building, Shibaura, Minato-ku, Tokyo
# ---------------------------------------------------------------------------
# A Japanese estimate is not an overhead-and-profit bill with a tax line at the
# bottom. It is a four-stage build-up that the Ministry of Land, Infrastructure,
# Transport and Tourism (MLIT) sets out in its standard estimating criteria for
# public building works, and every Japanese estimator reads a bill expecting to
# find the four stages in this order:
#
#     chokusetsu koji hi     direct construction cost, the priced bill below
#   + kyotsu kasetsu hi      common temporary works, a rate on direct cost
#   = jun koji hi            net construction cost
#   + genba kanri hi         site management cost, a rate on jun koji hi
#   = koji genka             construction prime cost
#   + ippan kanri hi to      head-office administration and profit
#   = koji kakaku            contract price, before tax
#   + shohizei at 10 percent consumption tax
#
# Each stage is taken on the running total of the stage above it, which is why
# every markup below except the first uses ``cumulative``. There is no separate
# profit line in Japanese practice: profit lives inside ippan kanri hi to
# together with head-office cost, so that one line carries the ``profit``
# category and genba kanri hi carries ``overhead``. Kyotsu kasetsu hi is site
# accommodation, temporary power, security and the like. It is a cost head, not
# a margin, so it is ``other``, the same treatment the Shanghai pack gives its
# statutory heads. Site-specific scaffolding, hoists and cranes are NOT in it;
# they are direct cost and are priced in section 01 below, which is the split a
# Japanese estimator will check first.
#
# WHAT IS INDICATIVE HERE, PLAINLY.
#
# The item codes. Every line carries a code under the key "sekisan" in the shape
# DD-MM-NNN: the work category (01 building, 02 electrical, 03 mechanical,
# 04 lifts, 05 external ancillary), the trade chapter within it, and a sequence
# number. The trade chapters follow the chapter order of the standard Japanese
# building estimate breakdown, so 01-04 is reinforcement, 01-07 is structural
# steel, 01-16 is joinery and so on, and a Japanese estimator will recognise
# where each line sits. The codes are shaped to that structure rather than
# quoted from a specific published edition of the MLIT criteria. We do not have
# the edition text in hand, so we do not claim conformance to it and we did not
# invent precise-looking references that cannot be traced. Replace them with the
# codes from the edition in force before this bill is used for a real tender.
#
# The rates. Comprehensive unit rates at Tokyo 2026 market levels in yen,
# excluding consumption tax. They are our estimate of the market, not extracts
# from a published unit-price book (kenchiku bukka or sekisan shiryo), and a
# Tokyo estimator should reprice at least the structural steel, the curtain wall
# and the mechanical services against the current issue before quoting. Steel
# and facade prices in particular have moved fast since 2024.
#
# The markup rates. MLIT derives kyotsu kasetsu hi, genba kanri hi and ippan
# kanri hi to from published formulas that step down as contract value rises.
# The percentages below are mid-band figures typical for a building contract of
# this size, not the formula output for this exact contract value.
#
# JPY has no minor unit in circulation, so every rate below is a whole yen and
# the numbers are large by design. Rounding to the yen is exact, not a shortcut.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="office-tokyo",
    project_name="オフィスビル新築工事 - 東京都港区芝浦 (Office Building, Shibaura, Minato-ku, Tokyo)",
    project_description=(
        "東京都港区芝浦三丁目における賃貸オフィスビルの新築工事。地上 12 階・地下 1 階、"
        "最高高さ 54.8 m、延床面積 約 22,400 平方メートル（基準階貸室面積 約 1,180 平方メートル）。"
        "鉄骨造（一部鉄骨鉄筋コンクリート造）、場所打ちコンクリート杭基礎、"
        "アルミカーテンウォールによる外装。建築基準法に基づく二次設計（保有水平耐力計算）により "
        "構造計算適合性判定を受け、座屈拘束ブレース 96 基による制振構造として層間変形角を抑制する。"
        "東京 2026 年価格水準で、直接工事費 約 96 億円、共通仮設費・現場管理費・一般管理費等を加えた "
        "工事価格 約 118 億円（消費税別）、坪当たり 約 174 万円。 "
        "New-build speculative office building in Shibaura 3-chome, Minato-ku, Tokyo, for a "
        "Tokyo property developer letting to corporate tenants. 12 storeys above grade plus one "
        "basement, maximum height 54.8 m, gross floor area approx. 22,400 m2 with a typical "
        "lettable floor of approx. 1,180 m2. Steel frame with part steel-reinforced concrete, "
        "cast-in-place concrete pile foundations, unitised aluminium curtain wall. Designed to "
        "the two-stage seismic route of the Building Standard Act and subject to structural "
        "calculation conformity review; 96 buckling-restrained braces provide the damping. "
        "At Tokyo 2026 levels the priced bill below (direct construction cost) is approx. "
        "JPY 9.63 billion; adding common temporary works, site management and head-office cost "
        "brings the contract price to approx. JPY 11.8 billion excluding consumption tax, about "
        "JPY 1.74 million per tsubo."
    ),
    region="JP",
    classification_standard="sekisan",
    currency="JPY",
    locale="ja",
    address={
        "street": "芝浦三丁目 12-8 (3-12-8 Shibaura)",
        "city": "東京都港区 (Minato-ku, Tokyo)",
        "postcode": "108-0023",
        "country": "Japan",
        "lat": 35.6427,
        "lng": 139.7492,
    },
    validation_rule_sets=["boq_quality", "project_completeness"],
    boq_name="工事費内訳書 - 公共建築工事積算基準準拠 (Bill of Quantities, sekisan build-up)",
    boq_description=(
        "科目別工事費内訳書。直接工事費を工種別に計上し、共通仮設費・現場管理費・一般管理費等を"
        "順次積み上げて工事価格を算出する。数量は建築数量積算基準により計測、"
        "単価は東京 2026 年市場価格の複合単価（労務・材料・機械経費を含む、消費税別）。 "
        "Bill of Quantities broken down by trade chapter. Direct construction cost is measured "
        "to the Japanese standard method of measurement for building works; comprehensive unit "
        "rates include labour, materials and plant at Tokyo 2026 market levels, excluding "
        "consumption tax. Common temporary works, site management and head-office cost are "
        "added in sequence to reach the contract price."
    ),
    boq_metadata={
        "standard": "公共建築工事積算基準 / 建築数量積算基準 (MLIT standard estimating criteria, standard method of measurement)",
        "phase": "実施設計積算 / 入札用内訳書 (Detailed design estimate, tender breakdown)",
        "base_date": "2026-Q2",
        "price_level": "東京 2026 (Tokyo 2026)",
        "pricing_method": "複合単価による積上げ積算 (Build-up estimate on comprehensive unit rates)",
        "tax_status": "消費税別 (Consumption tax excluded from unit rates)",
    },
    sections=[
        # -- 01-01 Direct temporary works ---------------------------------------
        # Site-specific temporary works. These are direct cost and deliberately
        # not folded into the kyotsu kasetsu hi markup, which covers the common
        # site establishment only.
        (
            "01",
            "直接仮設工事 (Direct temporary works)",
            {"sekisan": "01-01-000"},
            [
                ("1.1", "外部足場、くさび緊結式、養生シート共 (External wedge-lock scaffold with protection sheeting)", "m2", 9_400.0, 2_400.0, {"sekisan": "01-01-010"}),
                ("1.2", "内部足場、脚立足場及び移動式足場 (Internal scaffold, trestles and mobile towers)", "m2", 22_400.0, 520.0, {"sekisan": "01-01-020"}),
                ("1.3", "乗入れ構台設置・解体、地下工事用 (Temporary access deck for basement works, erect and dismantle)", "m2", 850.0, 28_000.0, {"sekisan": "01-01-030"}),
                ("1.4", "タワークレーン設置・解体及び運転、クライミング式 (Climbing tower crane, erect, operate, dismantle)", "基", 2.0, 72_000_000.0, {"sekisan": "01-01-040"}),
                ("1.5", "工事用エレベーター設置・解体及び運転 (Construction hoist, erect, operate, dismantle)", "基", 2.0, 28_000_000.0, {"sekisan": "01-01-050"}),
                ("1.6", "墨出し・遣方及び工事写真 (Setting out, profiles and progress record photography)", "m2", 22_400.0, 380.0, {"sekisan": "01-01-060"}),
                ("1.7", "仮囲い・ゲート・安全管理設備、養生清掃及び産業廃棄物処分 (Hoarding, gates, safety provision, cleaning and waste disposal)", "m2", 22_400.0, 2_050.0, {"sekisan": "01-01-070"}),
            ],
        ),
        # -- 01-02 / 01-03 Earthworks, retaining works and foundations ----------
        (
            "02",
            "土工事・地業工事 (Earthworks, retaining works and piling)",
            {"sekisan": "01-02-000"},
            [
                ("2.1", "根切り、機械掘削、地下 1 階 深さ 6.5 m (Bulk excavation by machine, one basement to 6.5 m)", "m3", 14_500.0, 2_800.0, {"sekisan": "01-02-010"}),
                ("2.2", "山留め工事、ソイルセメント柱列壁及び切梁支保工 (Soil-cement column retaining wall with strut and waling support)", "m2", 2_870.0, 63_000.0, {"sekisan": "01-02-020"}),
                ("2.3", "地盤改良、薬液注入工法、山留め壁背面 (Ground improvement by chemical grouting behind the retaining wall)", "m3", 1_850.0, 42_000.0, {"sekisan": "01-02-030"}),
                ("2.4", "釜場排水及び揚水ポンプ運転 (Sump dewatering and pump operation)", "式", 1.0, 18_000_000.0, {"sekisan": "01-02-040"}),
                ("2.5", "埋戻し・締固め、再生砂 (Backfilling and compaction, recycled sand)", "m3", 3_600.0, 3_200.0, {"sekisan": "01-02-050"}),
                ("2.6", "残土場外搬出及び処分、運搬距離 30 km 以内 (Surplus spoil haulage and disposal, within 30 km)", "m3", 11_800.0, 5_600.0, {"sekisan": "01-02-060"}),
                ("2.7", "場所打ちコンクリート杭、アースドリル工法 φ1,500 (Cast-in-place concrete piles, earth-drill method, 1500 mm dia.)", "m", 980.0, 198_000.0, {"sekisan": "01-03-010"}),
                ("2.8", "場所打ちコンクリート杭、アースドリル工法 φ1,200 (Cast-in-place concrete piles, earth-drill method, 1200 mm dia.)", "m", 520.0, 162_000.0, {"sekisan": "01-03-020"}),
                ("2.9", "杭頭処理及び杭頭補強筋 (Pile head trimming and pile head reinforcement)", "本", 34.0, 420_000.0, {"sekisan": "01-03-030"}),
                ("2.10", "砕石地業、捨てコンクリート及び防湿シート (Crushed stone bed, blinding concrete and damp-proof membrane)", "m2", 1_780.0, 6_800.0, {"sekisan": "01-03-040"}),
            ],
        ),
        # -- 01-04 / 01-05 / 01-06 Reinforcement, concrete and formwork ---------
        (
            "03",
            "鉄筋・コンクリート・型枠工事 (Reinforcement, concrete and formwork)",
            {"sekisan": "01-04-000"},
            [
                ("3.1", "異形鉄筋加工組立 SD345・SD390、D10-D32 (Deformed bar, cut, bend and fix, SD345 and SD390, D10 to D32)", "t", 1_150.0, 198_000.0, {"sekisan": "01-04-010"}),
                ("3.2", "機械式継手及びガス圧接 (Mechanical couplers and gas pressure welded splices)", "箇所", 18_500.0, 1_850.0, {"sekisan": "01-04-020"}),
                ("3.3", "溶接金網敷設、合成スラブ上端 (Welded wire mesh to composite slabs)", "m2", 20_700.0, 620.0, {"sekisan": "01-04-030"}),
                ("3.4", "普通コンクリート Fc27 打設、基礎・地下躯体 (Normal concrete Fc27, foundations and basement structure)", "m3", 2_650.0, 28_500.0, {"sekisan": "01-05-010"}),
                ("3.5", "普通コンクリート Fc36 打設、地上躯体・合成スラブ (Normal concrete Fc36, superstructure and composite slabs)", "m3", 2_900.0, 29_800.0, {"sekisan": "01-05-020"}),
                ("3.6", "打継処理及び止水板設置、地下躯体 (Construction joint preparation and waterstops, basement structure)", "m", 3_200.0, 4_800.0, {"sekisan": "01-05-030"}),
                ("3.7", "無収縮モルタル、露出型柱脚グラウト (Non-shrink grout to exposed column bases)", "箇所", 168.0, 68_000.0, {"sekisan": "01-05-040"}),
                ("3.8", "合板型枠、設置・解体共 (Plywood formwork, erect and strike)", "m2", 24_800.0, 9_200.0, {"sekisan": "01-06-010"}),
                ("3.9", "打放し仕上げ用化粧型枠、コア及びエントランス (Fair-face formwork, core walls and entrance)", "m2", 2_400.0, 12_500.0, {"sekisan": "01-06-020"}),
                ("3.10", "デッキプレート敷設、合成スラブ用 (Composite metal deck to suspended slabs)", "m2", 20_700.0, 5_600.0, {"sekisan": "01-06-030"}),
            ],
        ),
        # -- 01-07 Structural steelwork and seismic damping ---------------------
        # The seismic story of this building sits here. Under the Building
        # Standard Act a 54.8 m office is below the 60 m threshold, so it takes
        # the ultimate lateral strength route rather than time-history analysis
        # with ministerial approval, and it goes through structural calculation
        # conformity review. The buckling-restrained braces on 4.5 are what keep
        # storey drift inside the design limit under a moderate event; they are
        # a normal line in a Tokyo office bill, not an optional extra. The shop
        # primer on 4.9 and the column bases on 4.4 are billed separately rather
        # than bundled into the fabrication rates above them, which is why those
        # rates are lower than a bundled all-in figure would be.
        (
            "04",
            "鉄骨工事・制振部材 (Structural steelwork and seismic damping)",
            {"sekisan": "01-07-000"},
            [
                ("4.1", "鉄骨製作・建方、柱 BCP325 角形鋼管 (Steel columns, BCP325 cold-formed SHS, fabricate and erect)", "t", 1_180.0, 442_000.0, {"sekisan": "01-07-010"}),
                ("4.2", "鉄骨製作・建方、大梁 SN490B H 形鋼 (Primary steel beams, SN490B H-section, fabricate and erect)", "t", 1_420.0, 400_000.0, {"sekisan": "01-07-020"}),
                ("4.3", "鉄骨製作・建方、小梁・間柱・ブレース (Secondary beams, posts and bracing, fabricate and erect)", "t", 480.0, 348_000.0, {"sekisan": "01-07-030"}),
                ("4.4", "露出型柱脚及びアンカーボルト、ベースプレート共 (Exposed column bases with anchor bolts and base plates)", "箇所", 168.0, 185_000.0, {"sekisan": "01-07-040"}),
                ("4.5", "制振部材、座屈拘束ブレース (Seismic damping, buckling-restrained braces)", "基", 96.0, 2_400_000.0, {"sekisan": "01-07-050"}),
                ("4.6", "高力ボルト接合 F10T (High-strength bolted connections, F10T)", "本", 148_000.0, 620.0, {"sekisan": "01-07-060"}),
                ("4.7", "現場溶接、柱継手・柱梁接合部、超音波探傷検査共 (Site welding to column splices and beam-to-column joints, incl. ultrasonic testing)", "箇所", 3_850.0, 32_000.0, {"sekisan": "01-07-070"}),
                ("4.8", "頭付きスタッド溶接 (Headed shear stud welding)", "本", 62_000.0, 360.0, {"sekisan": "01-07-080"}),
                ("4.9", "鉄骨錆止め塗装、工場塗装 (Shop-applied anti-corrosion primer to steelwork)", "t", 3_080.0, 12_000.0, {"sekisan": "01-07-090"}),
                ("4.10", "耐火被覆、湿式吹付ロックウール及び耐火塗料 (Fire protection to steel, sprayed rock wool and intumescent coating)", "m2", 34_500.0, 4_600.0, {"sekisan": "01-07-100"}),
            ],
        ),
        # -- 01-09 / 01-13 / 01-14 / 01-16 / 01-19 / 01-23 External envelope ----
        (
            "05",
            "外装・防水工事 (External envelope and waterproofing)",
            {"sekisan": "01-09-000"},
            [
                ("5.1", "アルミカーテンウォール、複層 Low-E ガラス、ユニット方式 (Unitised aluminium curtain wall, Low-E double glazing)", "m2", 7_400.0, 112_000.0, {"sekisan": "01-16-010"}),
                ("5.2", "アルミサッシ、低層部及びバックヤード (Aluminium windows, podium and back of house)", "m2", 340.0, 62_000.0, {"sekisan": "01-16-020"}),
                ("5.3", "押出成形セメント板 t=60、外壁・機械室 (Extruded cement panel wall, 60 mm, back of house and plant)", "m2", 1_500.0, 19_500.0, {"sekisan": "01-19-010"}),
                ("5.4", "外壁内断熱、吹付硬質ウレタンフォーム (Internal wall insulation, sprayed rigid urethane foam)", "m2", 6_800.0, 3_800.0, {"sekisan": "01-19-020"}),
                ("5.5", "アルミパネル・金属笠木・日射遮蔽ルーバー (Aluminium panels, metal copings and solar shading louvres)", "m2", 780.0, 44_000.0, {"sekisan": "01-14-010"}),
                ("5.6", "屋上アスファルト防水、絶縁工法、断熱及び保護コンクリート共 (Roof asphalt waterproofing, unbonded, with insulation and protective screed)", "m2", 1_780.0, 21_000.0, {"sekisan": "01-09-010"}),
                ("5.7", "地下外壁・ピット防水、改質アスファルトシート (Basement wall and pit tanking, modified asphalt sheet)", "m2", 3_400.0, 7_800.0, {"sekisan": "01-09-020"}),
                ("5.8", "シーリング工事、外装目地及びガラス回り (Sealant to external joints and glazing perimeters)", "m", 16_200.0, 1_450.0, {"sekisan": "01-09-030"}),
                ("5.9", "とい・ルーフドレン及び屋外排水金物 (Rainwater goods, roof drains and external drainage fittings)", "式", 1.0, 14_800_000.0, {"sekisan": "01-13-010"}),
                ("5.10", "屋上緑化及び軽量土壌 (Green roof with lightweight growing medium)", "m2", 420.0, 28_000.0, {"sekisan": "01-23-010"}),
            ],
        ),
        # -- 01-10 / 01-11 / 01-14 / 01-15 / 01-16 / 01-18 / 01-19 / 01-20 ------
        (
            "06",
            "内装・建具工事 (Internal finishes and joinery)",
            {"sekisan": "01-19-000"},
            [
                ("6.1", "軽量鉄骨下地間仕切壁、せっこうボード二重張り (Light-gauge steel stud partitions, double-layer plasterboard)", "m2", 18_400.0, 12_000.0, {"sekisan": "01-19-030"}),
                ("6.2", "天井仕上げ、システム天井（貸室）及びせっこうボード天井（共用部） (Ceilings, system ceiling to lettable floors and plasterboard to common areas)", "m2", 19_800.0, 12_400.0, {"sekisan": "01-19-040"}),
                ("6.3", "フリーアクセスフロア H=100、置敷式 (Raised access floor, 100 mm, loose-lay)", "m2", 14_600.0, 11_600.0, {"sekisan": "01-19-050"}),
                ("6.4", "タイルカーペット張り、貸室及び共用部 (Carpet tiles to lettable and common areas)", "m2", 16_400.0, 4_800.0, {"sekisan": "01-19-060"}),
                ("6.5", "ビニル床シート張り、階段・機械室及び倉庫 (Vinyl sheet flooring to stairs, plant rooms and stores)", "m2", 3_800.0, 5_600.0, {"sekisan": "01-19-070"}),
                ("6.6", "石張り、エントランスホール床及び壁、花崗岩本磨き (Stone finish to entrance hall floor and walls, polished granite)", "m2", 1_150.0, 58_000.0, {"sekisan": "01-10-010"}),
                ("6.7", "磁器質タイル張り、便所・給湯室 (Porcelain tiling to toilets and pantries)", "m2", 2_900.0, 14_500.0, {"sekisan": "01-11-010"}),
                ("6.8", "左官工事、モルタル塗り及びセルフレベリング材 (Plastering, cement mortar render and self-levelling compound)", "m2", 9_600.0, 4_600.0, {"sekisan": "01-15-010"}),
                ("6.9", "塗装工事、EP・AEP・OP 及び防錆塗装 (Painting, emulsion, acrylic emulsion, oil paint and anti-corrosion coating)", "m2", 26_500.0, 1_850.0, {"sekisan": "01-18-010"}),
                ("6.10", "鋼製建具、防火戸・防煙シャッター及び鋼製枠 (Steel doors, fire doors, smoke shutters and steel frames)", "箇所", 285.0, 286_000.0, {"sekisan": "01-16-030"}),
                ("6.11", "木製建具、貸室及び共用部、枠・金物共 (Timber door sets to lettable and common areas, frames and ironmongery)", "箇所", 340.0, 168_000.0, {"sekisan": "01-16-040"}),
                ("6.12", "便所ブース・洗面カウンター及び衛生ユニット (Toilet cubicles, vanity counters and washroom units)", "箇所", 26.0, 3_850_000.0, {"sekisan": "01-20-010"}),
                ("6.13", "造作家具、受付カウンター及び共用部備付家具 (Joinery, reception counter and fitted furniture to common areas)", "式", 1.0, 42_000_000.0, {"sekisan": "01-20-020"}),
                ("6.14", "鋼製階段・手摺及びその他金属工事 (Steel stairs, balustrades and sundry metalwork)", "式", 1.0, 86_000_000.0, {"sekisan": "01-14-020"}),
            ],
        ),
        # -- 02 Electrical installation -----------------------------------------
        (
            "07",
            "電気設備工事 (Electrical installation)",
            {"sekisan": "02-00-000"},
            [
                ("7.1", "受変電設備、キュービクル式 6.6 kV 2,500 kVA (HV switchgear, cubicle type, 6.6 kV, 2500 kVA)", "式", 1.0, 178_000_000.0, {"sekisan": "02-03-010"}),
                ("7.2", "自家発電設備、ディーゼル 1,000 kVA 及び燃料小出槽 (Standby diesel generator, 1000 kVA, with day tank)", "台", 1.0, 128_000_000.0, {"sekisan": "02-05-010"}),
                ("7.3", "太陽光発電設備 200 kW、屋上設置 (Rooftop photovoltaic system, 200 kW)", "式", 1.0, 68_000_000.0, {"sekisan": "02-05-020"}),
                ("7.4", "幹線・動力設備、バスダクト及びケーブル、接地・雷保護共 (Rising mains and power, busduct and cable, incl. earthing and lightning protection)", "式", 1.0, 222_000_000.0, {"sekisan": "02-02-010"}),
                ("7.5", "電灯分電盤及び動力制御盤 (Lighting distribution boards and motor control panels)", "面", 26.0, 1_450_000.0, {"sekisan": "02-02-020"}),
                ("7.6", "電灯コンセント設備、LED 照明・非常照明及び誘導灯 (Lighting and small power, LED, emergency lighting and exit signs)", "m2", 22_400.0, 12_400.0, {"sekisan": "02-01-010"}),
                ("7.7", "自動火災報知設備及び非常放送設備 (Automatic fire alarm and emergency public address)", "式", 1.0, 78_000_000.0, {"sekisan": "02-06-010"}),
                ("7.8", "情報通信・構内 LAN・電話及び防犯監視設備 (Structured cabling, LAN, telephony, access control and CCTV)", "式", 1.0, 164_000_000.0, {"sekisan": "02-06-020"}),
                ("7.9", "中央監視制御設備、ビルエネルギー管理システム (Central monitoring and building energy management system)", "式", 1.0, 88_000_000.0, {"sekisan": "02-07-010"}),
            ],
        ),
        # -- 03 / 04 Mechanical services and lifts ------------------------------
        # 8.6 is not padding. Seismic restraint of plant, pipework and ductwork
        # is its own priced scope in Japan under the building services seismic
        # design guidance, and on a Tokyo office it is checked at handover.
        (
            "08",
            "機械設備工事・昇降機設備工事 (Mechanical services and lifts)",
            {"sekisan": "03-00-000"},
            [
                ("8.1", "空調熱源設備、空冷ヒートポンプチラー及び付属機器 (Air-cooled heat pump chillers and ancillary plant)", "式", 1.0, 318_000_000.0, {"sekisan": "03-01-010"}),
                ("8.2", "空調機・ファンコイルユニット及び空気搬送設備 (Air handling units, fan coil units and air distribution plant)", "m2", 22_400.0, 15_400.0, {"sekisan": "03-01-020"}),
                ("8.3", "ダクト設備、亜鉛鉄板製及び保温 (Galvanised steel ductwork and thermal insulation)", "m2", 22_400.0, 7_600.0, {"sekisan": "03-02-010"}),
                ("8.4", "換気・排煙設備、機械排煙及び加圧給気 (Ventilation and smoke control, mechanical extract and pressurisation)", "式", 1.0, 150_000_000.0, {"sekisan": "03-03-010"}),
                ("8.5", "自動制御設備 (Automatic controls)", "式", 1.0, 72_000_000.0, {"sekisan": "03-04-010"}),
                ("8.6", "建築設備耐震支持・防振架台 (Seismic restraint and anti-vibration mounts to building services)", "式", 1.0, 48_000_000.0, {"sekisan": "03-08-010"}),
                ("8.7", "給排水衛生設備、給水・給湯・排水通気配管 (Plumbing, cold water, hot water, soil and vent pipework)", "m2", 22_400.0, 9_200.0, {"sekisan": "03-05-010"}),
                ("8.8", "衛生器具設備、便所・給湯室 (Sanitary fixtures to toilets and pantries)", "箇所", 26.0, 4_600_000.0, {"sekisan": "03-05-020"}),
                ("8.9", "消火設備、屋内消火栓・スプリンクラー及び不活性ガス消火 (Fire fighting, hydrants, sprinklers and inert gas suppression)", "式", 1.0, 142_000_000.0, {"sekisan": "03-06-010"}),
                ("8.10", "都市ガス設備、引込及び屋内配管 (Town gas installation, service and internal pipework)", "式", 1.0, 26_000_000.0, {"sekisan": "03-07-010"}),
                ("8.11", "乗用エレベーター、定員 17 人 速度 150 m/min (Passenger lifts, 17 persons, 150 m/min)", "台", 6.0, 58_000_000.0, {"sekisan": "04-01-010"}),
                ("8.12", "非常用エレベーター及び荷物用エレベーター (Fire-fighting lift and goods lift)", "台", 2.0, 68_000_000.0, {"sekisan": "04-01-020"}),
            ],
        ),
        # -- 05 External ancillary works ----------------------------------------
        (
            "09",
            "屋外附帯工事 (External works and site services)",
            {"sekisan": "05-00-000"},
            [
                ("9.1", "屋外舗装、アスファルト及びインターロッキングブロック (External paving, asphalt and interlocking block)", "m2", 620.0, 18_500.0, {"sekisan": "05-01-010"}),
                ("9.2", "屋外排水工事、雨水・汚水桝及び管路 (External drainage, surface water and foul manholes and pipework)", "式", 1.0, 28_000_000.0, {"sekisan": "05-02-010"}),
                ("9.3", "植栽工事、高木・中低木及び地被類 (Planting, trees, shrubs and ground cover)", "式", 1.0, 32_000_000.0, {"sekisan": "05-03-010"}),
                ("9.4", "門扉・フェンス・車止め及び屋外サイン (Gates, fencing, bollards and external signage)", "式", 1.0, 18_600_000.0, {"sekisan": "05-04-010"}),
                ("9.5", "上下水道・ガス及び電力引込、屋外照明共 (Water, sewer, gas and electrical service connections, incl. external lighting)", "式", 1.0, 58_000_000.0, {"sekisan": "05-05-010"}),
            ],
        ),
    ],
    # The Japanese sekisan cascade, in the order an estimator reads it. Only the
    # first is taken on direct cost; each of the others is taken on the running
    # total produced by the line above, which is exactly what ``cumulative``
    # does. Reordering these lines changes the answer, so they are not a set.
    markups=[
        ("共通仮設費 5.5 パーセント (Common temporary works, 5.5 percent of direct cost)", 5.5, "other", "direct_cost"),
        ("現場管理費 9.0 パーセント (Site management cost, 9.0 percent of net construction cost)", 9.0, "overhead", "cumulative"),
        ("一般管理費等 6.5 パーセント (Head-office administration and profit, 6.5 percent of prime cost)", 6.5, "profit", "cumulative"),
        ("消費税 10 パーセント (Consumption tax at 10 percent)", 10.0, "tax", "cumulative"),
    ],
    total_months=24,
    tender_name="建築工事一式 総合建設請負 (Main building works contract)",
    tender_companies=[
        ("蒼稜建設株式会社 (Soryo Construction Co., Ltd.)", "nyusatsu@soryo-kensetsu.example", 0.98),
        ("湊嶺建設株式会社 (Minatomine Construction Co., Ltd.)", "tender@minatomine.example", 1.03),
        ("曙洋建設株式会社 (Shoyo Construction Co., Ltd.)", "mitsumori@shoyo-kensetsu.example", 1.01),
    ],
    tender_packages=[
        (
            "山留め・杭及び地下躯体工事 (Retaining works, piling and basement structure)",
            "ソイルセメント柱列壁、切梁支保工、場所打ちコンクリート杭、根切り及び地下躯体コンクリート工事。",
            "evaluating",
            [
                ("蒼稜建設株式会社 (Soryo Construction Co., Ltd.)", "nyusatsu@soryo-kensetsu.example", 0.98),
                ("湊嶺建設株式会社 (Minatomine Construction Co., Ltd.)", "tender@minatomine.example", 1.03),
                ("霞洲基礎工業株式会社 (Kasushu Foundation Engineering Co., Ltd.)", "tender@kasushu.example", 1.01),
            ],
        ),
        (
            "鉄骨製作・建方及び制振部材 (Steel fabrication, erection and damping devices)",
            "鉄骨柱・大梁・小梁の製作及び建方、座屈拘束ブレース、高力ボルト接合、現場溶接及び耐火被覆。",
            "issued",
            [
                ("鋼進製作鉄工株式会社 (Koshin Steel Fabrication Co., Ltd.)", "tender@koshin-steel.example", 0.99),
                ("北巌鉄構工業株式会社 (Hokugan Steel Structures Co., Ltd.)", "nyusatsu@hokugan.example", 1.04),
                ("曙洋建設株式会社 (Shoyo Construction Co., Ltd.)", "mitsumori@shoyo-kensetsu.example", 1.02),
            ],
        ),
        (
            "外装カーテンウォール工事 (Curtain wall and external envelope)",
            "アルミカーテンウォール、押出成形セメント板、アルミパネル、日射遮蔽ルーバー及びシーリング。",
            "evaluating",
            [
                ("玲光カーテンウォール株式会社 (Reiko Curtain Wall Co., Ltd.)", "tender@reiko-cw.example", 0.98),
                ("汀外装工業株式会社 (Migiwa Facade Engineering Co., Ltd.)", "nyusatsu@migiwa-facade.example", 1.05),
                ("穂積建材工業株式会社 (Hozumi Building Products Co., Ltd.)", "tender@hozumi-bp.example", 1.02),
            ],
        ),
        (
            "設備工事 - 電気・空調・衛生・昇降機 (Building services: electrical, HVAC, plumbing and lifts)",
            "受変電・幹線・電灯コンセント設備、空調換気設備、給排水衛生設備、消火設備及び昇降機設備。",
            "draft",
            [
                ("千鳥電設工業株式会社 (Chidori Electrical Engineering Co., Ltd.)", "tender@chidori-densetsu.example", 0.99),
                ("恒風空調工業株式会社 (Kofu HVAC Engineering Co., Ltd.)", "nyusatsu@kofu-kucho.example", 1.03),
                ("若菜衛生設備工業株式会社 (Wakana Plumbing Engineering Co., Ltd.)", "tender@wakana-eisei.example", 1.02),
            ],
        ),
        (
            "内装仕上工事 (Interior fit-out)",
            "間仕切壁、天井、フリーアクセスフロア、床仕上げ、石張り、建具及び塗装。",
            "draft",
            [
                ("藍屋内装工業株式会社 (Aiya Interior Works Co., Ltd.)", "tender@aiya-naiso.example", 0.98),
                ("柊内装株式会社 (Hiiragi Interiors Co., Ltd.)", "nyusatsu@hiiragi-naiso.example", 1.04),
                ("菱沼装工株式会社 (Hishinuma Finishing Works Co., Ltd.)", "tender@hishinuma.example", 1.01),
            ],
        ),
    ],
    schedule_activities=[
        ("準備・仮設工事 (Mobilisation and site setup)", "2026-04-01", "2026-05-31"),
        ("山留め・杭工事 (Retaining wall and piling)", "2026-05-01", "2026-08-31"),
        ("根切り・地下躯体工事 (Excavation and basement structure)", "2026-08-01", "2026-12-31"),
        ("鉄骨建方 (Steel erection)", "2026-12-01", "2027-05-31"),
        ("デッキ・床コンクリート工事 (Metal deck and floor concrete)", "2027-01-01", "2027-06-30"),
        ("耐火被覆工事 (Fire protection to steelwork)", "2027-04-01", "2027-08-31"),
        ("外装カーテンウォール工事 (Curtain wall installation)", "2027-04-01", "2027-09-30"),
        ("屋上防水・屋上緑化工事 (Roof waterproofing and green roof)", "2027-07-01", "2027-09-30"),
        ("電気設備配管配線 (Electrical containment and wiring)", "2027-03-01", "2027-11-30"),
        ("空調・衛生設備配管 (HVAC and plumbing installation)", "2027-03-01", "2027-11-30"),
        ("内装間仕切・天井工事 (Internal partitions and ceilings)", "2027-07-01", "2027-12-31"),
        ("昇降機設置工事 (Lift installation)", "2027-08-01", "2027-12-31"),
        ("内装仕上げ・建具工事 (Internal finishes and joinery)", "2027-10-01", "2028-01-31"),
        ("外構・植栽工事 (External works and planting)", "2027-11-01", "2028-02-29"),
        ("総合試運転調整 (Commissioning and balancing)", "2028-01-01", "2028-03-15"),
        ("完了検査・引渡し (Completion inspection and handover)", "2028-02-01", "2028-03-31"),
    ],
    project_metadata={
        "address": "〒108-0023 東京都港区芝浦三丁目 12-8 (3-12-8 Shibaura, Minato-ku, Tokyo 108-0023, Japan)",
        "client": "芝浦みなと開発株式会社 (Shibaura Minato Development Co., Ltd.)",
        "architect": "汐路建築設計事務所 (Shioji Architects and Engineers)",
        "structural_engineer": "汐路構造設計室 (Shioji Structural Design Office)",
        "quantity_surveyor": "東京積算コンサルタント株式会社 (Tokyo Sekisan Consultants Co., Ltd.)",
        "gfa_m2": 22400,
        "site_area_m2": 4150,
        "building_footprint_m2": 1780,
        "storeys": "地上 12 階、地下 1 階 (12 above grade, 1 basement)",
        "building_height_m": 54.8,
        "typical_floor_lettable_m2": 1180,
        "structure_system": "鉄骨造、一部鉄骨鉄筋コンクリート造、場所打ちコンクリート杭基礎 (Steel frame with part SRC, cast-in-place concrete piles)",
        "zoning": "商業地域、指定容積率 500 パーセント (Commercial zone, designated floor area ratio 500 percent)",
        "seismic_design": (
            "建築基準法施行令に基づく二次設計（保有水平耐力計算）。最高高さ 54.8 m のため "
            "時刻歴応答解析及び大臣認定の対象外、構造計算適合性判定を受ける。座屈拘束ブレース "
            "96 基による制振構造とし、一次設計時の層間変形角を 1/250 以下に抑える。 "
            "Two-stage seismic design under the Building Standard Act: allowable stress design "
            "followed by an ultimate lateral strength check. At 54.8 m the building sits below "
            "the 60 m threshold, so it does not need time-history analysis with ministerial "
            "approval, but it does go through structural calculation conformity review. "
            "96 buckling-restrained braces hold storey drift within 1/250 at the first design stage."
        ),
        "construction_standards": [
            "建築基準法及び同施行令 (Building Standard Act and its Enforcement Order)",
            "建築物の構造関係技術基準解説書 (Commentary on the technical standards for building structures)",
            "JASS 5 鉄筋コンクリート工事 (AIJ standard specification, reinforced concrete work)",
            "JASS 6 鉄骨工事 (AIJ standard specification, structural steelwork)",
            "公共建築工事標準仕様書 建築工事編 (MLIT standard specification for public building works)",
            "建築数量積算基準 (Standard method of measurement for building works)",
            "消防法及び東京都火災予防条例 (Fire Service Act and the Tokyo fire prevention ordinance)",
            "建築物省エネ法 (Act on Improving Energy Consumption Performance of Buildings)",
            "東京都建築安全条例 (Tokyo Metropolitan building safety ordinance)",
        ],
        "estimating_method": (
            "公共建築工事積算基準に準拠した積上げ積算。直接工事費に共通仮設費、現場管理費、"
            "一般管理費等を順次加算して工事価格を算出し、消費税を別途計上する。 "
            "Build-up estimate to the MLIT standard estimating criteria: direct cost, then "
            "common temporary works, site management and head-office cost in sequence to the "
            "contract price, with consumption tax stated separately."
        ),
        "regulator": (
            "指定確認検査機関による建築確認及び中間・完了検査、指定構造計算適合性判定機関による "
            "構造計算適合性判定、特定行政庁は東京都及び港区。 "
            "Building confirmation and interim and completion inspections by a designated "
            "confirmation and inspection body; structural calculation conformity review by a "
            "designated review body; the building control authorities are the Tokyo "
            "Metropolitan Government and Minato City."
        ),
        "tax_note": (
            "内訳書の単価は消費税抜きの複合単価。消費税は工事価格に対し 10 パーセントを別途計上する。"
            "軽減税率 8 パーセントは飲食料品等に適用されるもので、建設工事には適用されない。 "
            "Unit rates are tax-exclusive comprehensive rates. Consumption tax is charged at "
            "10 percent on the contract price. The reduced 8 percent rate applies to food and "
            "similar goods and never to construction work."
        ),
        "unit_note": (
            "円には流通する補助単位がないため、単価はすべて整数円。坪は 3.305785 平方メートルで、"
            "日本では坪単価が建築費の比較指標として使われる。 "
            "The yen has no circulating minor unit, so every rate is a whole yen. One tsubo is "
            "3.305785 m2, and cost per tsubo is the figure Japanese clients compare buildings on."
        ),
        # The marketplace card shows whatever "budget" says, and without it the
        # card would derive the DIRECT cost from the priced lines while the
        # description quoted the contract price, leaving two unreconciled
        # numbers on the same project. Both stages are named here and in the
        # description, and the card, headline and planned_budget all quote the
        # same one: koji kakaku, the contract price before consumption tax.
        "budget": "11.8B JPY",
        "headline_cost_jpy": "直接工事費 約 96 億円、工事価格 約 118 億円（消費税別）、消費税込み 約 130 億円 (direct cost approx. JPY 9.63 billion, contract price approx. JPY 11.8 billion excl. tax, JPY 13.0 billion incl. tax)",
        "cost_per_tsubo_jpy": "約 174 万円/坪 (approx. JPY 1.74 million per tsubo, JPY 526,000 per m2)",
        "sustainability": "建築物省エネ法適合、屋上緑化 420 平方メートル、Low-E 複層ガラス及び日射遮蔽ルーバー (Energy code compliant, 420 m2 green roof, Low-E glazing and solar shading)",
        "contract": "総価請負契約、民間建設工事標準請負契約約款 (Lump sum contract on the standard form of agreement for private construction works)",
    },
    project_code="TKY-SBR-2026-01",
    budget_boq_name="実行予算書 - 東京都港区芝浦オフィスビル (Control Budget)",
    planned_budget=11_800_000_000.0,
    actual_spend_ratio=0.38,
    spi_override=0.99,
    cpi_override=1.01,
)
