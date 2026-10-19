# -*- coding: utf-8 -*-
"""Pass 6: Translate the remaining 50 long heavily-mixed entries.

Deprecated one-off: for new work use scripts/i18n.py (get/add/set/missing/rename/export/import).
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

# What this script prints when it cannot match an entry is the entry itself,
# and those are locale strings. Standard output does not always speak UTF-8:
# redirected to a pipe on Windows it takes the ANSI code page, and printing a
# dash or a Mongolian letter there raises UnicodeEncodeError. The script then
# dies while REPORTING its findings, after having correctly decided to change
# nothing, and the traceback names an encoder rather than anything about
# translation. Reading the files was already pinned to UTF-8 below; writing
# the report is pinned here, replacing what the stream cannot carry instead of
# raising, because a report is not worth failing a run over.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
EN_PATH = ROOT / "frontend" / "src" / "app" / "locales" / "en.ts"
MN_PATH = ROOT / "frontend" / "src" / "app" / "locales" / "mn.ts"


def visible(text: str) -> str:
    """Drop invisible formatting characters, keeping every character that prints.

    Unicode format characters (general category Cf) are zero-width: they carry
    no letter, and nothing in this file's English source strings or Mongolian
    translations spells anything with one. A mechanical pass over the tree left
    a run of them at the end of some of the literals below, which is enough to
    break the table in both directions - a key holding one can never match the
    English string it is meant to match, so the entry is dead, and a value
    holding one would carry it into mn.ts, where scripts/check_zero_width.py
    reports it as a stray. Both sides are therefore matched and emitted through
    this function; the literals themselves are left exactly as they are.

    Never use this on locale text in general. U+200C is required Persian
    orthography, U+200D forms Bengali conjuncts and U+200E/U+200F place Latin
    tokens inside a right-to-left line; all four are Cf, and removing them
    misspells the language. Here the inputs are English and Mongolian, and
    neither uses any of them.
    """
    if not any(unicodedata.category(ch) == "Cf" for ch in text):
        return text
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


FULL_TRANSLATIONS: dict[str, str] = {
    "Paste your BOQ data here (from Excel, Word, or any table)...\\n\\nExample:\\nPos\\\\tDescription\\\\tUnit\\\\tQty\\\\tRate\\n01.01\\\\tExcavation\\\\tm3\\\\t250\\\\t18.50\\n01.02\\\\tConcrete C30/37\\\\tm3\\\\t120\\\\t145.00\\n01.03\\\\tReinforcement BSt 500\\\\tkg\\\\t12000\\\\t1.85":
        "BOQ өгөгдлөө энд буулгана уу (Excel, Word, эсвэл ямар ч хүснэгтээс)...\\n\\nЖишээ:\\nPos\\\\tТайлбар\\\\tНэгж\\\\tТоо\\\\tТариф\\n01.01\\\\tУхалт\\\\tm3\\\\t250\\\\t18.50\\n01.02\\\\tБетон C30/37\\\\tm3\\\\t120\\\\t145.00\\n01.03\\\\tАрматур BSt 500\\\\tkg\\\\t12000\\\\t1.85",

    "Assemblies are reusable cost recipes that combine multiple resources (materials, labor, equipment) into a single composite rate. For example, a \\\"Reinforced Concrete Wall\\\" assembly includes concrete, rebar, formwork, and labor. Apply assemblies to BOQ positions to auto-populate component costs.":
        "Угсралтууд гэдэг нь олон нөөцийг (материал, хөдөлмөр, тоног төхөөрөмж) нэг нийлмэл тариф болгон нэгтгэдэг дахин ашиглах боломжтой өртгийн жор юм. Жишээ нь, \\\"Армопэлсэн бетон хана\\\" угсралтад бетон, арматур, хашмал, хөдөлмөр багтана. Бүрэлдэхүүний өртгийг автоматаар оруулахын тулд угсралтыг BOQ байрлалд хэрэглэнэ.",

    "Ask me to generate BOQ positions. For example: \\\"Add MEP items for a 5-story office building\\\"":
        "BOQ байрлал үүсгэхийг надаас гуй. Жишээ нь: \\\"5 давхар оффис барилгад MEP зүйлс нэмэх\\\"",

    "Track budgets over time with Earned Value Management (SPI, CPI), S-curve visualization, cash flow projections, cost snapshots, and what-if scenario modeling for informed decision-making.":
        "Earned Value Management (SPI, CPI), S-curve дүрслэл, мөнгөн урсгалын урьдчилсан тооцоо, өртгийн хувилбар, мэдээлэлд суурилсан шийдвэр гаргалтад зориулсан what-if хувилбарын загварчлал ашиглан төсвийг цаг хугацааны явцад хянана.",

    "Compares each unit rate against median market rates from the cost database. Flags overpriced and underpriced positions.":
        "Нэгж тариф бүрийг өртгийн өгөгдлийн сангаас авсан зах зээлийн медиан тарифтай харьцуулдаг. Хэт өндөр болон хэт бага үнэтэй байрлалуудыг тэмдэглэнэ.",

    "Custom columns appear in the BOQ grid before the actions column. Values are stored per position and exported with the BOQ. Removing a column hides it but preserves the underlying data.":
        "Захиалгат баганууд BOQ хүснэгтэд үйлдлийн баганы өмнө харагдана. Утгууд нь байрлал тус бүрээр хадгалагдан BOQ-той хамт экспортлогддог. Баганыг устгахад нуугдах боловч үндсэн өгөгдөл хадгалагдана.",

    "Whole BOQ rendered in {{disp}} at rate {{rate}} ({{base}} → {{disp}}). View-only — server keeps base values. Switch to \\\"Base\\\" to edit prices.":
        "Бүхэл BOQ нь {{rate}} тарифаар {{disp}}-аар харагдана ({{base}} → {{disp}}). Зөвхөн үзэх — сервер үндсэн утгуудыг хадгалдаг. Үнэ засахын тулд \\\"Үндсэн\\\" руу шилжинэ үү.",

    "Pick a numbering scheme. The current order is preserved — only ordinals are rewritten.‌⁠‍":
        "Дугаарлалтын схем сонгоно уу. Одоогийн дараалал хадгалагдана — зөвхөн дугаарууд дахин бичигдэнэ.‌⁠‍",

    "Order preserved — only ordinals were rewritten. Undo with Ctrl+Z is not supported for renumber.":
        "Дараалал хадгалагдсан — зөвхөн дугаарууд дахин бичигдсэн. Дугаарлалтад Ctrl+Z-ээр буцаах боломжгүй.",

    "Short-form decimal numbering common in NRM-style measurement.":
        "NRM хэв маягийн хэмжилтэд түгээмэл богино хэлбэрийн аравтын дугаарлалт.",

    "Leaves room to insert positions like 01.15 between 01.10 and 01.20 later. Standard German tender output.":
        "Хожим нь 01.10 ба 01.20 хооронд 01.15 гэх мэт байрлал нэмэх зайтай. Германы стандарт тендерийн гаралт.",

    "Compact, traditional numbering. Best for fixed-scope BOQs that won't get extra positions later.":
        "Авсаархан, уламжлалт дугаарлалт. Дараа нь нэмэлт байрлал авахгүй тогтсон хүрээтэй BOQ-д хамгийн тохиромжтой.",

    "Define named values you can reference in formulas. e.g. set $GFA = 1500, then write =$GFA * 0.15 in any quantity or rate cell.‌⁠‍":
        "Томьёонд лавласан болох нэрлэсэн утгуудыг тодорхойлоорой. Жишээ нь $GFA = 1500 гэж тохируулаад дурын тоо хэмжээ эсвэл тарифын нүдэнд =$GFA * 0.15 гэж бичнэ үү.‌⁠‍",

    "AI rate suggestions, classification, and anomaly detection require a vector-indexed cost database. This is a one-time setup that takes about 30 seconds.":
        "AI тарифын санал, ангилал, гажиг илрүүлэх нь вектор индекстэй өртгийн өгөгдлийн сан шаардана. Энэ нь 30 орчим секунд үргэлжлэх нэг удаагийн тохиргоо юм.",

    "Promoting {{code}} from SHARED to PUBLISHED requires a signed approval (ISO 19650). Your signature and comments are recorded in the audit log.":
        "{{code}}-г SHARED-ээс PUBLISHED руу дэвшүүлэхэд гарын үсэгтэй зөвшөөрөл (ISO 19650) шаардлагатай. Таны гарын үсэг ба сэтгэгдэл аудитын бүртгэлд бүртгэгдэнэ.",

    "Change Order workflow: Draft (prepare scope change) → Submitted (send for review) → Approved or Rejected. Each order tracks cost impact and schedule impact in days. Add line items to detail what changed — original vs new quantities and rates. The cost delta is computed automatically.":
        "Өөрчлөлтийн тушаалын ажлын урсгал: Ноорог (хүрээ өөрчлөлт бэлдэх) → Илгээсэн (хяналтад илгээх) → Зөвшөөрсөн эсвэл Татгалзсан. Тушаал бүр өртгийн нөлөө, хуваарийн нөлөөг өдрөөр хянадаг. Юу өөрчлөгдсөнийг нарийвчилж — анхны болон шинэ тоо хэмжээ, тариф мөр нэмнэ үү. Өртгийн зөрүү автоматаар тооцоологдоно.",

    "Track insurance policies, permits, bonds and certifications. Get a warning before each one expires.":
        "Даатгалын бодлого, зөвшөөрөл, баталгаа, гэрчилгээг хянана. Тус бүр нь дуусахаас өмнө анхааруулга авна.",

    "Track insurance, permits, bonds and certifications with expiry reminders.":
        "Даатгал, зөвшөөрөл, баталгаа, гэрчилгээг хугацаа дуусах сануулгатай хянана.",

    "5D cost management adds cost tracking over time to your project. Monitor budget vs. actual spend with S-curve charts, track Earned Value (SPI = schedule efficiency, CPI = cost efficiency — both >= 1.0 means healthy), and run what-if scenarios to forecast outcomes.":
        "5D өртгийн удирдлага нь таны төсөлд цаг хугацааны өртгийн хяналтыг нэмдэг. Төсөв vs бодит зарцуулалтыг S-curve диаграмаар хянах, Earned Value хянах (SPI = хуваарийн үр ашиг, CPI = өртгийн үр ашиг — хоёулаа >= 1.0 нь эрүүл гэсэн утгатай), үр дүнг урьдчилан таамаглах what-if хувилбарыг ажиллуулна уу.",

    "Apply the average rate without picking a specific variant. You can refine later by clicking the row.":
        "Тодорхой хувилбар сонгохгүйгээр дундаж тарифыг хэрэглэнэ. Та мөрийг дарж дараа нь сайжруулж болно.",

    "Unit rates and composite prices for materials, labor, and equipment. Import regional databases (CWICR) from Modules or add custom rates. Toggle AI Semantic Search for natural-language queries.":
        "Материал, хөдөлмөр, тоног төхөөрөмжийн нэгж тариф, нийлмэл үнэ. Модулиудаас бүс нутгийн өгөгдлийн сан (CWICR) импортлох эсвэл захиалгат тариф нэмнэ үү. Байгалийн хэлний асуулгад AI семантик хайлтыг идэвхжүүлнэ үү.",

    "Custom deployment, training, and enterprise solutions worldwide":
        "Дэлхий даяар захиалгат байршуулалт, сургалт, аж ахуйн нэгжийн шийдлүүд",

    "Hi,\\n\\nHere is the file you asked about — {{name}} ({{size}}).\\nDownload link (expires {{expires}}):\\n{{url}}\\n\\n— sent from OpenConstructionERP":
        "Сайн байна уу,\\n\\nТаны асуусан файл энд байна — {{name}} ({{size}}).\\nТатах холбоос (хугацаа дуусах: {{expires}}):\\n{{url}}\\n\\n— OpenConstructionERP-ээс илгээв",

    "Email-friendly. BOQs, tables, and links — no attachments. Fits in any inbox.":
        "И-мэйл-д тохиромжтой. BOQ-ууд, хүснэгтүүд, холбоосууд — хавсралтгүй. Ямар ч ирсэн зурвасын хайрцагт багтана.",

    "Earned Value Management (EVM) compares planned progress with actual performance. SPI > 1.0 = ahead of schedule. CPI > 1.0 = under budget. Create snapshots periodically to track trends over time.":
        "Earned Value Management (EVM) нь төлөвлөсөн явцыг бодит гүйцэтгэлтэй харьцуулдаг. SPI > 1.0 = хуваариас түрүүлж. CPI > 1.0 = төсвөөс хямд. Цаг хугацааны хандлагыг хянахын тулд тогтмол хувилбар үүсгэнэ үү.",

    "Smart suggestions with confidence scores. You decide, AI assists.":
        "Итгэлийн оноотой ухаалаг саналууд. Та шийднэ, AI туслана.",

    "Extend OpenEstimate with regional cost databases, resource catalogs (CWICR), vector search indices for AI, language packs, demo projects, and integrations. Install a module to activate it — uninstall anytime.":
        "Бүс нутгийн өртгийн өгөгдлийн сан, нөөцийн каталог (CWICR), AI-д зориулсан вектор хайлтын индекс, хэлний багц, демо төсөл, интеграцуудаар OpenEstimate-г өргөтгөнө үү. Модулийг идэвхжүүлэхийн тулд суулгана уу — дурын үед устгана.",

    "Pick a {{lang}} catalogue below — your project speaks {{lang}}, so matches need to come from a same-language rate book.":
        "Доорх {{lang}} каталогийг сонгоно уу — таны төсөл {{lang}}-аар ярьдаг тул таарцууд ижил хэлний тарифын номноос ирэх ёстой.",

    "{{n}} searches · {{picks}} picks · pick rate {{rate}} · mean score {{score}} · last {{days}}d":
        "{{n}} хайлт · {{picks}} сонголт · сонголтын хувь {{rate}} · дундаж оноо {{score}} · сүүлийн {{days}} өдөр",

    "OpenConstructionERP uses BGE-M3 — a free, open-source multilingual encoder by BAAI. It runs entirely on your machine. No API key. No cloud calls. Install once with one command:":
        "OpenConstructionERP нь BGE-M3-ыг ашигладаг — BAAI-ийн үнэгүй, нээлттэй эх кодтой олон хэлний энкодер. Энэ нь таны машин дээр бүхэлдээ ажилладаг. API түлхүүр шаардлагагүй. Үүлэн дуудлага байхгүй. Нэг командаар нэг удаа суулгана:",

    "Phase A.10–A.12 — multi-select bulk ops, threshold-based confirm, no-match flow, and tenant template library are live. Drag-target chips and 3D-highlight arrive in Phase B.":
        "Үе шат A.10–A.12 — олон-сонголтот багц үйлдэл, босгод суурилсан баталгаажуулалт, таарахгүй ажлын урсгал, түрээслэгчийн загварын сан амьдаар ажиллаж байна. Чирэх-зорилгот чипс, 3D-онцлох нь Үе шат B-д ирнэ.",

    "Each element is searched against the selected cost catalogue using vector similarity + lexical hints + region/unit boost.":
        "Элемент бүр нь вектор төстэй байдал + үгзүйн зөвлөмж + бүс/нэгжийн нэмэгдэл ашиглан сонгосон өртгийн каталогийн эсрэг хайгддаг.",

    "Project region {{region}} speaks {{projLang}}, but the bound catalogue {{catalogue}} is in {{boundLang}}. Match results will surface in the wrong language until you re-bind.":
        "Төслийн бүс {{region}} нь {{projLang}}-аар ярьдаг боловч холбосон каталог {{catalogue}} нь {{boundLang}}-аар байна. Та дахин холбоогүй бол таарцын үр дүн буруу хэлээр гарна.",

    "Upload an .xlsx with at least a \\\"Description\\\" column (or its localised equivalent — Beschreibung, Описание, Descripción, 描述, etc.). Optional columns: Qty, Unit, Code, Category. Decimal-comma quantities are recognised.":
        "Дор хаяж \\\"Description\\\" багана (эсвэл орчуулсан хувилбар — Beschreibung, Описание, Descripción, 描述, гэх мэт) бүхий .xlsx-г байршуулна уу. Сонголтын баганууд: Qty, Unit, Code, Category. Аравтын таслалтай тоо хэмжээг таньдаг.",

    "One line per item. Each line becomes a group; semantic search finds the closest CWICR rates. Use any language — the multilingual encoder handles cross-lang queries.":
        "Зүйл тус бүрд нэг мөр. Мөр бүр бүлэг болно; семантик хайлт нь хамгийн ойрын CWICR тарифыг олдог. Ямар ч хэл ашиглана уу — олон хэлний энкодер хэлээр дамжсан асуулгыг боловсруулдаг.",

    "Templates are tenant-scoped. Confirmed signatures auto-suggest matches in future projects.":
        "Загварууд нь түрээслэгчийн хүрээтэй. Баталгаажсан гарын үсэг нь ирээдүйн төслүүдэд таарцыг автоматаар санал болгодог.",

    "Off = use gross. Default deducts IfcOpeningElement / IfcRelVoidsElement from host quantities.":
        "Унтраалттай = бохир дүн ашиглана. Үндсэн тохиргоо нь хост тоо хэмжээнээс IfcOpeningElement / IfcRelVoidsElement-г хасдаг.",

    "Still working — first runs on large BIM models take longer because vectors are warming up. Subsequent runs on the same project are much faster.":
        "Үргэлжилж байна — том BIM загвар дээрх анхны ажиллагаа удаан үргэлжилнэ, учир нь вектор халаагдаж байна. Тухайн төсөл дээрх дараагийн ажиллагаа хамаагүй хурдан.",

    "OpenConstructionERP has a modular plugin architecture. Anyone can create custom modules — cost databases, regional standards, CAD converters, analytics dashboards, integrations with external systems, or any other functionality. Your module will appear in this Modules section and can be installed by any user.":
        "OpenConstructionERP нь модуль бүтэцтэй плагин архитектуртай. Хэн ч захиалгат модуль үүсгэж болно — өртгийн өгөгдлийн сан, бүс нутгийн стандартууд, CAD хөрвүүлэгчид, аналитик самбар, гадаад системтэй интеграц, эсвэл бусад функциональ байдал. Таны модуль энэ Модулиуд хэсэгт харагдах ба хэрэглэгч бүр суулгах боломжтой.",

    "Each module is a Python package with a manifest.py file. Create your module, test it locally, and share it with the community. Even if you just have an idea — send us a text description and we will help you build it.":
        "Модуль бүр манифест файлтай Python багц юм. Модулиа үүсгэж, дотооддоо тестлээд, хамт олонтой хуваалцаарай. Зөвхөн санаа байсан ч хамаагүй — бидэнд текст тайлбар илгээгээрэй, бид тантай хамтарч бүтээхэд тусална.",

    "Connect an AI provider (Anthropic Claude, OpenAI, or Google Gemini) to get personalized, context-aware recommendations for your project. Without AI, you still see rule-based analysis below.":
        "Өөрийн төсөлд хувийн, контекстээ мэдсэн зөвлөмж авахын тулд AI үйлчилгээ үзүүлэгч (Anthropic Claude, OpenAI, эсвэл Google Gemini)-тэй холбогдоно уу. AI-гүйгээр та доорх дүрэмд суурилсан шинжилгээг үзсээр л байна.",

    "This dashboard runs against the optional Project Intelligence module. It is currently disabled on this server, so the AI advisor, gap detector and analytics grid have nothing to query.":
        "Энэ самбар нь нэмэлт Project Intelligence модуль дээр ажилладаг. Энэ нь одоогоор сервер дээр идэвхгүй байгаа тул AI зөвлөгч, цоорхой илрүүлэгч, аналитик торлой асуух зүйл байхгүй.",

    "Region determines available cost databases and VAT rates. Classification standard defines the cost structure: DIN 276 for DACH countries, NRM for UK, MasterFormat for US/Canada, UniFormat for Oceania. Currency sets all pricing in the BOQ.":
        "Бүс нь боломжтой өртгийн өгөгдлийн сан, VAT тарифыг тогтоодог. Ангиллын стандарт нь өртгийн бүтцийг тодорхойлдог: DACH улсуудад DIN 276, UK-д NRM, US/Canada-д MasterFormat, Oceania-д UniFormat. Валют нь BOQ-н бүх үнийг тогтоодог.",

    "Risk matrix with probability, impact, scores, and mitigation plans.":
        "Магадлал, нөлөө, оноо, бууруулах төлөвлөгөө бүхий эрсдэлийн матриц.",

    "Add requirements to define Entity-Attribute-Constraint triplets for your project.":
        "Төслийнхөө хувьд Entity-Attribute-Constraint гурвалыг тодорхойлохын тулд шаардлага нэмнэ үү.",

    "Paste requirement specifications. Each line should follow the format: entity | attribute | constraint_type | value | unit | category | priority":
        "Шаардлагын тодорхойлолтыг буулгана уу. Мөр бүр дараах форматтай байх ёстой: entity | attribute | constraint_type | value | unit | category | priority",

    "Monte Carlo simulation provides probabilistic estimates only. Results depend on input assumptions.":
        "Monte Carlo симуляц нь зөвхөн магадлалд суурилсан тооцоог өгдөг. Үр дүн нь оруулсан таамаглалаас хамаардаг.",

    "4D scheduling links your BOQ positions to a project timeline. Create activities, set dependencies, and visualize progress on a Gantt chart. The critical path analysis highlights activities that directly affect the project end date. Activity types: Task = work item, Milestone = checkpoint with zero duration, Summary = grouping header.":
        "4D хуваарь нь таны BOQ байрлалуудыг төслийн хугацааны мөртэй холбодог. Үйл ажиллагаа үүсгэх, хамаарал тогтоох, Gantt диаграмм дээр явцыг дүрсэлнэ. Чухал замын шинжилгээ нь төслийн дуусах огноонд шууд нөлөөлдөг үйл ажиллагааг онцолдог. Үйл ажиллагааны төрөл: Даалгавар = ажлын зүйл, Чухал үе = тэг үргэлжлэх хугацаатай хяналтын цэг, Хураангуй = бүлэглэх толгой.",

    "AI features (estimation, takeoff analysis, semantic search) require an API key. Anthropic Claude is recommended for best accuracy. Keys are stored encrypted and never leave your server.":
        "AI боломжууд (тооцоо, тоо хэмжээ гаргалт шинжилгээ, семантик хайлт) нь API түлхүүр шаардлагатай. Хамгийн сайн нарийвчлалд Anthropic Claude-г санал болгодог. Түлхүүрүүд нь шифрлэгдсэн байдлаар хадгалагдах ба таны серверээс хэзээ ч гарахгүй.",

    "Upload a PDF drawing → AI analyzes pages and extracts elements (walls, slabs, doors, etc.) with quantities → Review results and adjust → Add selected items to your BOQ. Confidence scores: green (>80%) = high confidence, yellow (50-80%) = review recommended, red (<50%) = manual verification needed.":
        "PDF зураг байршуулна → AI хуудсыг шинжилж тоо хэмжээтэй элементүүдийг (хана, хавтгай, хаалга гэх мэт) гаргаж авна → Үр дүнг хянаж тохируулна → Сонгосон зүйлсийг BOQ-д нэмнэ. Итгэлийн оноо: ногоон (>80%) = өндөр итгэл, шар (50-80%) = хяналт хийхийг зөвлөж байна, улаан (<50%) = гар баталгаажуулалт шаардлагатай.",

    "Tendering workflow: Draft (prepare package) → Issued (send to bidders) → Collecting (receive bids) → Evaluating (compare offers side-by-side) → Awarded (select winner). Create a package from a BOQ, add subcontractor bids, then use the comparison table to identify the best offer. Add 2+ bids to see a side-by-side analysis.":
        "Тендерийн ажлын урсгал: Ноорог (багц бэлдэх) → Гаргасан (санал өгөгчдөд илгээх) → Цуглуулж байна (саналуудыг хүлээн авах) → Үнэлж байна (саналуудыг зэрэгцүүлэн харьцуулах) → Шагнагдсан (ялагч сонгох). BOQ-оос багц үүсгэж, туслан гүйцэтгэгчийн саналуудыг нэмж, дараа нь харьцуулалтын хүснэгтийг ашиглан хамгийн сайн саналыг тодорхойлно. Зэрэгцүүлсэн шинжилгээ үзэхийн тулд 2 ба түүнээс дээш санал нэмнэ.",
}


def main() -> None:
    # newline="" on both ends, and each line keeps the ending it arrived with.
    # Path.read_text/write_text translate line endings, so on Windows a run that
    # replaces nothing still rewrites every line ending in mn.ts to CRLF.
    with open(EN_PATH, encoding="utf-8", newline="") as fh:
        en_text = fh.read()
    with open(MN_PATH, encoding="utf-8", newline="") as fh:
        mn_text = fh.read()

    en_full = re.compile(r'"((?:[^"\\]|\\.)+)"\s*:\s*"((?:[^"\\]|\\.)*)"')
    en_pairs = {m.group(1): m.group(2) for m in en_full.finditer(en_text)}

    pat = re.compile(r'^(\s*)"((?:[^"\\]|\\.)+)"\s*:\s*"((?:[^"\\]|\\.)*)"(,?)\s*$')

    # The table is matched through its printing characters only. See visible().
    lookup = {visible(k): visible(v) for k, v in FULL_TRANSLATIONS.items()}

    # Build a map of key -> mn translation, by matching ESCAPED EN values (since en_pairs values are raw from regex)
    keys_to_replace: dict[str, str] = {}
    for k, en_v in en_pairs.items():
        probe = visible(en_v)
        if probe in lookup:
            keys_to_replace[k] = lookup[probe]

    print(f"Will replace {len(keys_to_replace)} long entries")
    not_found = set(lookup) - {visible(en_pairs[k]) for k in keys_to_replace}
    if not_found:
        print(f"WARNING: {len(not_found)} EN keys not matched:")
        for nf in not_found:
            print(f"  {nf[:200]}")
            print(f"  repr: {repr(nf[:200])}")

    out_lines: list[str] = []
    count = 0
    for line in mn_text.splitlines(keepends=True):
        stripped = line.rstrip("\n").rstrip("\r")
        eol = line[len(stripped):]
        m = pat.match(stripped)
        if m:
            indent, key, value, comma = m.group(1), m.group(2), m.group(3), m.group(4)
            if key in keys_to_replace:
                new_val = keys_to_replace[key]
                # Use raw escape: our string literals contain Python-parsed
                # versions of TS escape sequences. We need to output exactly
                # the same characters (\, n, ", etc.) as appear in en.ts.
                # Since we wrote `\\n` in source → string has `\n` (backslash+n);
                # we want TS to see `\n`, so just write as-is.
                # Same for `\\\\\"` → string has `\\\"`; we want TS to see `\\\"`.
                # So: NO further escaping. Just embed.
                new_line = f'{indent}"{key}": "{new_val}"{comma}{eol}'
                out_lines.append(new_line)
                count += 1
                continue
        out_lines.append(line)

    with open(MN_PATH, "w", encoding="utf-8", newline="") as fh:
        fh.write("".join(out_lines))
    print(f"Replaced {count} entries")


if __name__ == "__main__":
    main()
