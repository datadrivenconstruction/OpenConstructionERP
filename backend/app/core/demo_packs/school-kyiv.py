# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: ukraine-ua - School, Kyiv
# ---------------------------------------------------------------------------
# A new school for 600 pupils in Kyiv, publicly funded, and so the estimate in
# its statutory form. What makes it a Ukrainian school of 2026 rather than of
# 2021 is the protective shelter under it, sized for the pupils and staff and
# budgeted with its hermetic doors and filter ventilation, and the survey for
# explosive objects before the site is touched.
#
# Every line names its chapter of the зведений кошторисний розрахунок under
# ``zkr`` next to its DIN 276 cost group. Unit rates are all-in direct costs
# at Kyiv 2026 levels in UAH excluding ПДВ. The cascade stays inside the
# wartime ceilings of постанова КМУ №1512 and adds the Додаток 28 risk
# allowance for public buildings, 3.0 percent.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="school-kyiv",
    project_name="Будівництво загальноосвітнього закладу на 600 учнів - Київ, Дарницький район (School, Kyiv)",
    project_description=(
        "Нове будівництво закладу загальної середньої освіти на 600 учнів у "
        "Дарницькому районі Києва, приблизно 9 800 m2 загальної площі, три "
        "поверхи, спортивний зал, харчоблок і захисна споруда цивільного "
        "захисту в підвальному поверсі. New school for 600 pupils in the "
        "Darnytskyi district of Kyiv, approx. 9,800 m2 gross floor area on "
        "three storeys, with a sports hall, a kitchen and a civil protection "
        "shelter in the basement. Publicly funded, priced at Kyiv 2026 levels "
        "in UAH excluding VAT."
    ),
    region="UA",
    classification_standard="din276",
    currency="UAH",
    locale="uk",
    address={
        "street": "вулиця Архітектора Вербицького 12",
        "city": "Київ",
        "postcode": "02081",
        "country": "Ukraine",
        "lat": 50.3990,
        "lng": 30.6360,
    },
    validation_rule_sets=["ukraine", "din276", "boq_quality"],
    boq_name="Зведений кошторисний розрахунок - Школа, Дарницький район (Summary estimate)",
    boq_description=(
        "Кошторис за главами зведеного кошторисного розрахунку (Настанова, "
        "наказ Мінрегіону №281) із класифікацією за DIN 276, для закупівлі "
        "робіт за Законом №922-VIII. Ціни Києва 2026 року в гривнях, без ПДВ."
    ),
    boq_metadata={
        "standard": "Настанова з визначення вартості будівництва (наказ №281) / DIN 276",
        "phase": "Кошторисна документація, стадія П, для очікуваної вартості закупівлі (Pre-tender estimate)",
        "base_date": "2026-Q3",
        "price_level": "Київ 2026 (UAH, без ПДВ)",
    },
    sections=[
        (
            "1",
            "Глава 1 - Підготовка території будівництва (Site preparation)",
            {"din276": "210", "zkr": "1"},
            [
                ("1.01", "Обстеження ділянки на наявність вибухонебезпечних предметів (Survey for explosive objects)", "lsum", 1, 450000, {"din276": "215", "zkr": "1"}),
                ("1.02", "Розчищення території та знесення зелених насаджень (Site clearance)", "m2", 12000, 45, {"din276": "214", "zkr": "1"}),
                ("1.03", "Винесення існуючих інженерних мереж з плями забудови (Divert existing utilities)", "lsum", 1, 2400000, {"din276": "211", "zkr": "1"}),
            ],
        ),
        (
            "2-310",
            "Глава 2 - Земляні роботи і фундаменти (Earthworks and foundations)",
            {"din276": "320", "zkr": "2"},
            [
                ("2.01", "Розробка ґрунту в котловані екскаватором (Bulk excavation)", "m3", 16000, 200, {"din276": "311", "zkr": "2"}),
                ("2.02", "Зворотна засипка пазух котловану (Backfill)", "m3", 5000, 150, {"din276": "311", "zkr": "2"}),
                ("2.03", "Навантаження і вивезення ґрунту (Load and cart away spoil)", "m3", 11000, 230, {"din276": "311", "zkr": "2"}),
                ("2.04", "Буронабивні палі діаметром 620 мм (Bored piles, 620 mm)", "m", 3800, 3100, {"din276": "323", "zkr": "2"}),
                ("2.05", "Монолітні фундаменти з бетону C25/30 (Foundations)", "m3", 2600, 5300, {"din276": "322", "zkr": "2"}),
                ("2.06", "Арматура А500С фундаментів (Foundation reinforcement)", "t", 300, 44000, {"din276": "322", "zkr": "2"}),
                ("2.07", "Гідроізоляція фундаментів і стін підвалу (Foundation waterproofing)", "m2", 4200, 650, {"din276": "325", "zkr": "2"}),
            ],
        ),
        (
            "2-shelter",
            "Глава 2 - Захисна споруда цивільного захисту (Civil protection shelter)",
            {"din276": "340", "zkr": "2"},
            [
                ("2.08", "Монолітні стіни та перекриття захисної споруди з бетону C30/37 (Shelter walls and roof slab)", "m3", 1100, 6300, {"din276": "341", "zkr": "2"}),
                ("2.09", "Захисно-герметичні двері (Blast and gas-tight doors)", "pcs", 8, 420000, {"din276": "344", "zkr": "2"}),
                ("2.10", "Фільтровентиляційне обладнання захисної споруди (Shelter filter ventilation)", "lsum", 1, 6200000, {"din276": "431", "zkr": "2"}),
            ],
        ),
        (
            "2-340",
            "Глава 2 - Монолітний каркас (Reinforced concrete frame)",
            {"din276": "350", "zkr": "2"},
            [
                ("2.11", "Монолітні колони і діафрагми з бетону C30/37 (Columns and shear walls)", "m3", 1100, 6200, {"din276": "343", "zkr": "2"}),
                ("2.12", "Монолітні перекриття з бетону C25/30 (Floor slabs)", "m3", 2400, 5400, {"din276": "351", "zkr": "2"}),
                ("2.13", "Арматура А500С каркаса (Frame reinforcement)", "t", 460, 44000, {"din276": "351", "zkr": "2"}),
                ("2.14", "Щитова опалубка (System formwork)", "m2", 23000, 360, {"din276": "351", "zkr": "2"}),
                ("2.15", "Збірні залізобетонні сходові марші (Precast stair flights)", "pcs", 16, 42000, {"din276": "351", "zkr": "2"}),
            ],
        ),
        (
            "2-330",
            "Глава 2 - Стіни, фасад і покрівля (Walls, facade and roof)",
            {"din276": "330", "zkr": "2"},
            [
                ("2.16", "Кладка зовнішніх стін з газобетонних блоків D500, 300 мм (Aerated block external walls)", "m3", 2600, 3700, {"din276": "332", "zkr": "2"}),
                ("2.17", "Цегляні перегородки класних кімнат, 120 мм (Brick classroom partitions)", "m2", 9500, 780, {"din276": "342", "zkr": "2"}),
                ("2.18", "Скріплена система теплоізоляції фасаду, мінеральна вата 150 мм (ETICS, mineral wool)", "m2", 6800, 1600, {"din276": "335", "zkr": "2"}),
                ("2.19", "Енергоефективні вікна з алюмінієвого профілю (Aluminium windows)", "m2", 2300, 4800, {"din276": "334", "zkr": "2"}),
                ("2.20", "Вхідні алюмінієві та протипожежні двері (Entrance and fire doors)", "pcs", 40, 38000, {"din276": "344", "zkr": "2"}),
                ("2.21", "Плоска покрівля з ПВХ мембраною та утепленням (Flat roof, PVC membrane)", "m2", 3700, 1700, {"din276": "363", "zkr": "2"}),
            ],
        ),
        (
            "2-345",
            "Глава 2 - Оздоблювальні роботи (Finishes)",
            {"din276": "340", "zkr": "2"},
            [
                ("2.22", "Механізована штукатурка стін (Machine-applied plaster)", "m2", 24000, 330, {"din276": "345", "zkr": "2"}),
                ("2.23", "Стяжка та комерційний лінолеум (Screed and commercial vinyl)", "m2", 7500, 900, {"din276": "352", "zkr": "2"}),
                ("2.24", "Спортивне покриття підлоги спортзалу (Sports hall floor)", "m2", 900, 2600, {"din276": "352", "zkr": "2"}),
                ("2.25", "Акустичні підвісні стелі (Acoustic suspended ceilings)", "m2", 6500, 650, {"din276": "354", "zkr": "2"}),
                ("2.26", "Фарбування стін водно-дисперсійними фарбами (Emulsion paint)", "m2", 24000, 160, {"din276": "345", "zkr": "2"}),
            ],
        ),
        (
            "2-400",
            "Глава 2 - Інженерні системи та технологічне обладнання (Services and equipment)",
            {"din276": "400", "zkr": "2"},
            [
                ("2.27", "Внутрішні водопровід і каналізація (Water supply and drainage)", "m2", 9800, 750, {"din276": "412", "zkr": "2"}),
                ("2.28", "Індивідуальний тепловий пункт (Heat substation)", "pcs", 1, 3600000, {"din276": "421", "zkr": "2"}),
                ("2.29", "Опалення (Heating)", "m2", 9800, 900, {"din276": "422", "zkr": "2"}),
                ("2.30", "Припливно-витяжна вентиляція з рекуперацією (Mechanical ventilation with heat recovery)", "m2", 9800, 1000, {"din276": "431", "zkr": "2"}),
                ("2.31", "Електропостачання та освітлення (Power and lighting)", "m2", 9800, 850, {"din276": "444", "zkr": "2"}),
                ("2.32", "Резервне живлення, дизель-генератор (Standby generator)", "pcs", 1, 2300000, {"din276": "442", "zkr": "2"}),
                ("2.33", "Слабкострумні мережі, структурована кабельна мережа (Low-current and data cabling)", "m2", 9800, 320, {"din276": "451", "zkr": "2"}),
                ("2.34", "Пожежна сигналізація та оповіщення (Fire alarm and voice alarm)", "m2", 9800, 260, {"din276": "456", "zkr": "2"}),
                ("2.35", "Ліфти для маломобільних груп населення (Accessible lifts)", "pcs", 2, 2300000, {"din276": "461", "zkr": "2"}),
                ("2.36", "Технологічне обладнання харчоблоку (Kitchen equipment)", "lsum", 1, 5200000, {"din276": "471", "zkr": "2"}),
            ],
        ),
        (
            "6",
            "Глава 6 - Зовнішні мережі та споруди (External networks)",
            {"din276": "540", "zkr": "6"},
            [
                ("6.01", "Зовнішні мережі водопостачання і каналізації (External water and sewer)", "m", 650, 10500, {"din276": "540", "zkr": "6"}),
                ("6.02", "Приєднання до електричних мереж (Grid connection)", "lsum", 1, 4800000, {"din276": "225", "zkr": "6"}),
                ("6.03", "Теплова мережа до ІТП (Heat network connection)", "m", 180, 22000, {"din276": "540", "zkr": "6"}),
            ],
        ),
        (
            "7",
            "Глава 7 - Благоустрій та озеленення території (External works and landscaping)",
            {"din276": "500", "zkr": "7"},
            [
                ("7.01", "Спортивний майданчик зі штучним покриттям (Sports ground, artificial surface)", "m2", 3200, 1600, {"din276": "520", "zkr": "7"}),
                ("7.02", "Проїзди і тротуари з бетонної бруківки (Block paved roads and footpaths)", "m2", 4500, 950, {"din276": "520", "zkr": "7"}),
                ("7.03", "Озеленення та огородження території (Planting and boundary fence)", "m2", 6000, 450, {"din276": "570", "zkr": "7"}),
            ],
        ),
        (
            "2-extra",
            "Глава 2 - Додаткові роботи та обладнання (Complementary works and equipment)",
            {"din276": "340", "zkr": "2"},
            [
                ("2.37", "Підвіконня (Window boards)", "m", 900, 480, {"din276": "334", "zkr": "2"}),
                ("2.38", "Облицювання цоколя клінкерною плиткою (Clinker tiles to plinth)", "m2", 600, 1950, {"din276": "335", "zkr": "2"}),
                ("2.39", "Протипожежні двері EI 30 (Fire doors EI 30)", "pcs", 30, 17000, {"din276": "344", "zkr": "2"}),
                ("2.40", "Внутрішні водостоки (Internal rainwater drainage)", "m2", 3700, 420, {"din276": "411", "zkr": "2"}),
                ("2.41", "Блискавкозахист (Lightning protection)", "lsum", 1, 320000, {"din276": "446", "zkr": "2"}),
                ("2.42", "Відеоспостереження та контроль доступу (CCTV and access control)", "lsum", 1, 1200000, {"din276": "456", "zkr": "2"}),
                ("2.43", "Обладнання спортивного залу (Sports hall equipment)", "lsum", 1, 1600000, {"din276": "610", "zkr": "2"}),
            ],
        ),
        (
            "7b",
            "Глава 7 - Зовнішнє освітлення та малі архітектурні форми (External lighting and site furniture)",
            {"din276": "500", "zkr": "7"},
            [
                ("7.04", "Зовнішнє освітлення території (External lighting)", "m2", 6000, 70, {"din276": "540", "zkr": "7"}),
                ("7.05", "Велопарковка та малі архітектурні форми (Cycle stands and site furniture)", "lsum", 1, 450000, {"din276": "550", "zkr": "7"}),
            ],
        ),
        (
            "8",
            "Глава 8 - Тимчасові будівлі і споруди (Temporary buildings and works)",
            {"din276": "390", "zkr": "8"},
            [
                ("8.01", "Тимчасові будівлі, огородження та охорона (Site buildings, hoarding and security)", "month", 22, 220000, {"din276": "391", "zkr": "8"}),
                ("8.02", "Баштовий кран (Tower crane)", "month", 16, 300000, {"din276": "391", "zkr": "8"}),
            ],
        ),
    ],
    # Risk is a percentage of chapters 1 to 12, which hold the general
    # production costs but not profit or administrative costs, so it follows
    # the first line cumulatively and precedes the other two.
    markups=[
        ("Загальновиробничі витрати (General production costs)", 9.0, "overhead", "direct_cost"),
        ("Кошти на покриття ризиків (Risk allowance)", 3.0, "contingency", "cumulative"),
        ("Адміністративні витрати (Administrative costs)", 2.5, "overhead", "direct_cost"),
        ("Кошторисний прибуток (Profit)", 7.0, "profit", "direct_cost"),
        ("ПДВ 20% (VAT)", 20.0, "tax", "cumulative"),
    ],
    total_months=22,
    tender_name="Відкриті торги - Будівництво школи, Дарницький район",
    tender_companies=[
        ("Дніпробудінвест ТОВ", "tender@dniprobudinvest.example", 0.95),
        ("Київміськбуд-Сервіс ТОВ", "zakupivli@kyivmiskbud-servis.example", 0.99),
        ("Лівобережна будівельна компанія ПрАТ", "oferta@livoberezhna-bk.example", 1.04),
    ],
    tender_packages=[
        (
            "Генеральний підряд (General contract)",
            "Будівництво школи із захисною спорудою, інженерними мережами та благоустроєм",
            "evaluating",
            [
                ("Дніпробудінвест ТОВ", "tender@dniprobudinvest.example", 0.95),
                ("Київміськбуд-Сервіс ТОВ", "zakupivli@kyivmiskbud-servis.example", 0.99),
                ("Лівобережна будівельна компанія ПрАТ", "oferta@livoberezhna-bk.example", 1.04),
            ],
        ),
    ],
    project_metadata={
        "address": "вулиця Архітектора Вербицького 12, 02081 Київ, Ukraine",
        "client": "Департамент будівництва міської адміністрації (contracting authority)",
        "architect": "Проєктний інститут «Дніпровські схили»",
        "gfa_m2": 9800,
        "storeys_above": 3,
        "storeys_below": 1,
        "pupils": 600,
        "consequence_class": "CC2 (ДБН В.1.2-14:2018)",
        "procurement": "Закон №922-VIII «Про публічні закупівлі», works above 1.5 млн грн",
        "construction_standards": [
            "Настанова з визначення вартості будівництва, наказ Мінрегіону №281 від 01.11.2021",
            "ДБН В.1.2-14:2018 - Загальні принципи забезпечення надійності та конструктивної безпеки",
            "Постанова КМУ №1512 від 19.11.2025 - граничні розміри витрат і прибутку",
        ],
        "vat_note": "Усі ціни без ПДВ. ПДВ 20% нараховується на підсумок.",
    },
)
