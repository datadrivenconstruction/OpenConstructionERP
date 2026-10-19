# -*- coding: utf-8 -*-
"""Second-pass translator targeting the 497 entries still untranslated
after pass 1. These are mostly:
  - short tech labels with placeholders ({{count}}, {{name}}, etc.)
  - shortcut chips (Ctrl+D, F1, etc.)
  - construction-specific terms (HVAC, EVM, BOQ Templates)
  - "e.g." placeholders
  - "Showing {{count}} X" patterns
  - field names like "Inspector", "Chairperson"
Deprecated one-off: for new work use scripts/i18n.py (get/add/set/missing/rename/export/import).
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN_PATH = ROOT / "frontend" / "src" / "app" / "locales" / "en.ts"
MN_PATH = ROOT / "frontend" / "src" / "app" / "locales" / "mn.ts"
UNTRANS_JSON = ROOT / "scripts" / "_mn_remaining.json"


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


PHRASES: dict[str, str] = {
    # boq
    "(Uncategorized)": "(Ангилаагүй)",
    "Compare": "Харьцуулах",
    "Diff": "Зөрүү",
    "Contingency (P80 - P50)": "Нөөц (P80 - P50)",
    "iter.": "давталт",
    "%": "%",
    "Excel (.xlsx)": "Excel (.xlsx)",
    "CSV (.csv)": "CSV (.csv)",
    "PDF": "PDF",
    "GAEB XML (.x83)": "GAEB XML (.x83)",
    "final": "эцсийн",
    "Fair": "Дунд",
    "Great": "Маш сайн",
    "Needs work": "Сайжруулах шаардлагатай",
    "Use Template": "Загвар ашиглах",
    "Redo (Ctrl+Y)": "Дахин хийх (Ctrl+Y)",
    "Redone": "Дахин хийсэн",
    "Waste": "Үрэлгэн",
    "Impact (+)": "Нөлөө (+)",
    "Impact (-)": "Нөлөө (-)",
    "Sensitivity Analysis": "Мэдрэмжийн шинжилгээ",
    "Variation": "Хэлбэлзэл",
    "BOQ Templates": "BOQ загварууд",
    "Templates coming soon": "Загварууд удахгүй",
    "Undo (Ctrl+Z)": "Буцаах (Ctrl+Z)",
    "Undone": "Буцаасан",
    "Ungrouped": "Бүлэглээгүй",
    "Assistant": "Туслах",
    "Smart AI": "Ухаалаг AI",
    "Quick fill:": "Хурдан бөглөх:",
    "Picked:": "Сонгосон:",
    "{{count}} variants chosen": "{{count}} хувилбар сонгосон",
    "Accept": "Хүлээн зөвшөөрөх",
    "[Root]": "[Үндэс]",
    "AI Classification": "AI ангилал",
    "Escalated": "Дээшлүүлсэн",
    "Regional": "Бүс нутгийн",
    "Find missing prerequisites, companions, successors": "Дутуу шаардлага, хамт олон, дараагийнхыг олох",
    "AI Smart Actions‌⁠‍": "AI ухаалаг үйлдлүүд‌⁠‍",
    "Specifications": "Тодорхойлолт",
    "Anomalies ({{count}})": "Гажиг ({{count}})",
    "Classification‌⁠‍": "Ангилал‌⁠‍",
    "/": "/",
    "Batch actions‌⁠‍": "Багц үйлдэл‌⁠‍",
    "Decimals": "Аравтын орон",
    "Formula": "Томьёо",
    "Calculated": "Тооцоологдсон",
    "{{count}} comment(s)": "{{count}} сэтгэгдэл",
    "{{count}} components": "{{count}} бүрэлдэхүүн",
    "Conceptual": "Үзэл баримтлал",
    "Definitive": "Тодорхой",
    "Detailed": "Дэлгэрэнгүй",
    "Preliminary": "Урьдчилсан",
    "filled": "бөглөгдсөн",
    "GLOBAL": "ДЭЛХИЙН",
    "Ignore": "Үл хайхрах",
    "Parsing GAEB XML — namespace-agnostic, X81/X83/X84 supported.": "GAEB XML задлан шинжилж байна — namespace-аас үл хамаарах, X81/X83/X84 дэмжинэ.",
    "Linked Geometry": "Холбосон геометр",
    "LOCKED": "ТҮГЖСЭН",
    "Partial": "Хэсэгчлэн",
    "per {{unit}}": "{{unit}} тутамд",
    "Regional standards": "Бүс нутгийн стандартууд",
    "Updating...": "Шинэчилж байна...",
    "Renumbering...": "Дугаарлаж байна...",
    "e.g. Concrete C30/37": "ж.нь Concrete C30/37",
    "set FX": "FX тохируулах",
    "{{foreign}} ≈ {{base}} (1 {{code}} = {{rate}} {{baseCode}})": "{{foreign}} ≈ {{base}} (1 {{code}} = {{rate}} {{baseCode}})",
    "Explicit variant: {{label}}{{captured}}": "Тодорхой хувилбар: {{label}}{{captured}}",
    "▾ {{count}}": "▾ {{count}}",
    "ABC %": "ABC %",
    "e.g. Structural Works, MEP, Finishes...": "ж.нь Бүтцийн ажил, MEP, Өнгөлгөө...",
    "Classification...‌⁠‍": "Ангилал...‌⁠‍",
    "Toggle AI Chat": "AI чатыг солих",
    "Ctrl+D": "Ctrl+D",
    "Ctrl+E": "Ctrl+E",
    "Ctrl+Enter": "Ctrl+Enter",
    "Ctrl+I": "Ctrl+I",
    "Ctrl+L": "Ctrl+L",
    "Ctrl+Shift+V": "Ctrl+Shift+V",
    "Ctrl+/": "Ctrl+/",
    "Ctrl+Y": "Ctrl+Y",
    "Ctrl+Z": "Ctrl+Z",
    "Del": "Del",
    "F1": "F1",
    "Keyboard Shortcuts (F1)": "Гарын товчлуурын товчлол (F1)",
    "Snapshot restored‌⁠‍": "Хувилбар сэргээгдсэн‌⁠‍",
    "Page {{page}}": "Хуудас {{page}}",
    "Classify": "Ангилах",
    "Suggested‌⁠‍": "Санал болгосон‌⁠‍",
    "Untitled BOQ‌⁠‍": "Гарчиггүй BOQ‌⁠‍",
    "(untitled)": "(гарчиггүй)",
    "{{count}} errors found": "{{count}} алдаа олдсон",
    "Validation errors": "Баталгаажуулалтын алдаа",
    "{{count}} warnings": "{{count}} анхааруулга",
    "Validation warnings": "Баталгаажуулалтын анхааруулга",
    "Maximum {{cap}} variables per BOQ.": "BOQ тус бүрд хамгийн ихдээ {{cap}} хувьсагч.",
    "BOQ variables‌⁠‍": "BOQ хувьсагч‌⁠‍",
    "Variant updated: {{label}}": "Хувилбар шинэчлэгдсэн: {{label}}",
    "Vector Database Ready": "Вектор өгөгдлийн сан бэлэн",
    "Indexing...": "Индекслэж байна...",
    "AI Features Setup": "AI боломжуудын тохиргоо",
    # nav
    "Databases": "Өгөгдлийн сан",
    "CAD / BIM & BI": "CAD / BIM ба BI",
    "BIM Rules": "BIM дүрэм",
    "Asset Register": "Хөрөнгийн бүртгэл",
    "Commercial": "Худалдаа",
    "CRM": "CRM",
    "PRO": "PRO",
    "STD": "STD",
    "PDF Measurements": "PDF хэмжилт",
    "Collaboration": "Хамтын ажиллагаа",
    "AU BOQ Exchange": "AU BOQ Exchange",
    "BR SINAPI Exchange": "BR SINAPI Exchange",
    "CA BOQ Exchange": "CA BOQ Exchange",
    "CN BOQ Exchange": "CN BOQ Exchange",
    "CZ BOQ Exchange": "CZ BOQ Exchange",
    "DE DIN 276 Exchange": "DE DIN 276 Exchange",
    "ES PBC Exchange": "ES PBC Exchange",
    "FR DPGF Exchange": "FR DPGF Exchange",
    "GAEB Exchange": "GAEB Exchange",
    "IT Computo Exchange": "IT Computo Exchange",
    "JP Sekisan Exchange": "JP Sekisan Exchange",
    "KR BOQ Exchange": "KR BOQ Exchange",
    "NL STABU Exchange": "NL STABU Exchange",
    "Nordic NS 3420 Exchange": "Nordic NS 3420 Exchange",
    "PL KNR Exchange": "PL KNR Exchange",
    "RU GESN Exchange": "RU GESN Exchange",
    "TR Birim Fiyat Exchange": "TR Birim Fiyat Exchange",
    "UAE BOQ Exchange": "UAE BOQ Exchange",
    "UK NRM Exchange": "UK NRM Exchange",
    # match_elements
    "BIM (live)": "BIM (амьдаар)",
    "Session {{id}}…": "Сесс {{id}}…",
    "Vector match ({{count}})": "Векторын тааруулалт ({{count}})",
    "Vector match — top 10": "Векторын тааруулалт — топ 10",
    "Lexical ({{count}})": "Үгзүйн ({{count}})",
    "Lexical match — top 10": "Үгзүйн тааруулалт — топ 10",
    "Skip {{count}} (TBD)": "{{count}}-ыг алгасах (TBD)",
    "Bulk-confirming matches ≥ {{thr}}…": "≥ {{thr}} таарцуудыг багцлан баталгаажуулж байна…",
    "Mark TBD": "TBD гэж тэмдэглэх",
    "Template library": "Загварын сан",
    "{{count}} signatures": "{{count}} гарын үсэг",
    "(unnamed)": "(нэргүй)",
    "sig: {{prefix}}…": "гарын үсэг: {{prefix}}…",
    "Used": "Ашигласан",
    "Session {{id}}": "Сесс {{id}}",
    "Subtractive / non-billable": "Хасах / тооцоологдохгүй",
    "MEP": "MEP",
    "e.g.": "ж.нь",
    "Matching session": "Тааруулах сесс",
    "Vector DB ready": "Вектор DB бэлэн",
    "Vector DB empty": "Вектор DB хоосон",
    "Legacy LanceDB backend": "Хуучны LanceDB бэкэнд",
    "Vector DB unreachable": "Вектор DB-д хүрэх боломжгүй",
    "Best": "Хамгийн сайн",
    "~{{mb}} MB · {{lang}}": "~{{mb}} MB · {{lang}}",
    "BIM → BOQ": "BIM → BOQ",
    "Review matches": "Таарцуудыг хянах",
    "{{confirmed}}/{{total}} confirmed": "{{confirmed}}/{{total}} баталгаажсан",
    "{{n}} visible": "{{n}} харагдах",
    # costs
    "Base year‌⁠‍": "Үндсэн он‌⁠‍",
    "Class.": "Анг.",
    "Database cleared": "Өгөгдлийн сан цэвэрлэгдсэн",
    "e.g. WALL-001": "ж.нь WALL-001",
    "Vector": "Вектор",
    "Hybrid‌⁠‍": "Холимог‌⁠‍",
    "Lexical‌⁠‍": "Үгзүйн‌⁠‍",
    "Semantic‌⁠‍": "Семантик‌⁠‍",
    "Query": "Асуулга",
    "Installing {{name}}...": "{{name}}-г суулгаж байна...",
    "e.g. Reinforced concrete wall C30/37, 25cm": "ж.нь Армопэлсэн бетон хана C30/37, 25см",
    "duplicates skipped": "давхардлуудыг алгассан",
    "Escalation": "Эскалаци",
    "Factor": "Коэффициент",
    "Favourites": "Дуртай",
    "Supported formats": "Дэмжигдсэн форматууд",
    "Unsupported file format": "Дэмжигдээгүй файлын формат",
    "Fetching installed databases...": "Суулгасан өгөгдлийн санг авч байна...",
    "Recently Used": "Сүүлд ашигласан",
    "Region cleared": "Бүс цэвэрлэгдсэн",
    "Finalizing...": "Дуусгаж байна...",
    "Reading Parquet file...": "Parquet файлыг уншиж байна...",
    "regions": "бүсүүд",
    "Parse": "Задлан шинжлэх",
    "Target year‌⁠‍": "Зорилтот он‌⁠‍",
    "{{min}} – {{max}}": "{{min}} – {{max}}",
    "Average‌⁠‍": "Дундаж‌⁠‍",
    "1 variant": "1 хувилбар",
    "median {{price}}": "медиан {{price}}",
    "Sort variants": "Хувилбаруудыг эрэмбэлэх",
    "Embed": "Embed",
    "Fetch": "Татах",
    # costmodel
    "Actual Spent": "Бодит зарцуулсан",
    "e.g. 1200": "ж.нь 1200",
    "{{area}} m²": "{{area}} m²",
    "per m²": "м² тутамд",
    "Benchmark Range": "Жишгийн хүрээ",
    "CPI": "CPI",
    "CV": "CV",
    "EAC": "EAC",
    "ETC": "ETC",
    "SPI": "SPI",
    "SV": "SV",
    "VAC": "VAC",
    "Forecast (EAC)": "Урьдчилсан таамаг (EAC)",
    "S-Curve (EVM)": "S-Curve (EVM)",
    "S-Curve Chart": "S-Curve график",
    # bim
    "Architecture": "Архитектур",
    "3D Visualization": "3D дүрслэл",
    "BOQ Linking": "BOQ холболт",
    "Format Agnostic": "Форматаас үл хамаарах",
    "Supported: RVT, IFC, DWG, DGN": "Дэмжигддэг: RVT, IFC, DWG, DGN",
    "CAD / BIM File": "CAD / BIM файл",
    "Storeys:": "Давхрууд:",
    "CSV / Excel": "CSV / Excel",
    "3D Geometry": "3D геометр",
    "DAE / COLLADA": "DAE / COLLADA",
    "Conversion depth": "Хөрвүүлэлтийн гүн",
    "IFC, RVT, CSV, Excel": "IFC, RVT, CSV, Excel",
    "Note: RVT files require DDC cad2data. Consider IFC.": "Тэмдэглэл: RVT файлд DDC cad2data шаардлагатай. IFC ашиглахыг бодолцоно уу.",
    "Revit (.rvt), IFC (.ifc)": "Revit (.rvt), IFC (.ifc)",
    "Unsupported format.": "Дэмжигдээгүй формат.",
    # requirements
    "Gate {{num}}": "Хаалга {{num}}",
    "Coverage": "Хамрах хүрээ",
    "Entity": "Объект",
    "e.g. wall, floor, roof": "ж.нь хана, шал, дээвэр",
    "Attribute": "Шинж",
    "e.g. thickness, fire_rating": "ж.нь зузаан, галд тэсвэртэй зэрэг",
    "Constraint Type": "Хязгаарлалтын төрөл",
    "e.g. 200, C30/37, F90": "ж.нь 200, C30/37, F90",
    "Source Reference": "Эх сурвалжийн лавлагаа",
    "Gate {{num}}: {{status}}": "Хаалга {{num}}: {{status}}",
    "Constraint": "Хязгаарлалт",
    "{{count}} requirements": "{{count}} шаардлага",
    "^F[0-9]+$": "^F[0-9]+$",
    # cde
    "Promote": "Дэвшүүлэх",
    "e.g. Uniclass 2015": "ж.нь Uniclass 2015",
    "e.g. PRJ-STR-DWG-001": "ж.нь PRJ-STR-DWG-001",
    "Container promoted": "Контейнер дэвшсэн",
    "Showing {{count}} containers": "{{count}} контейнерийг харуулж байна",
    "e.g. S2": "ж.нь S2",
    "State transition history": "Төлвийн шилжилтийн түүх",
    "Signed: {{signer}}": "Гарын үсэг зурсан: {{signer}}",
    "Gate {{code}}": "Хаалга {{code}}",
    "{{count}} transmittals": "{{count}} дамжуулалт",
    "Gate B approval signature": "Хаалга B-ийн зөвшөөрлийн гарын үсэг",
    "Signature": "Гарын үсэг",
    # finance
    "Behind": "Хоцорсон",
    "Subcontract": "Туслан гүйцэтгэх",
    "Data Date": "Өгөгдлийн огноо",
    "Invoice Ref": "Нэхэмжлэхийн дугаар",
    "Receivable‌⁠‍": "Авлага‌⁠‍",
    "WBS": "WBS",
    "e.g., 01.02": "ж.нь 01.02",
    # risk
    "Critical (16-25)": "Эмзэг (16-25)",
    "PERT": "PERT",
    "High (11-15)": "Өндөр (11-15)",
    "High / Critical": "Өндөр / Эмзэг",
    "Low (1-5)": "Бага (1-5)",
    "Medium (6-10)": "Дунд (6-10)",
    "Run Monte Carlo Simulation": "Monte Carlo симуляц ажиллуулах",
    "Impact Severity": "Нөлөөллийн хүндрэл",
    "e.g. Foundation soil instability": "ж.нь Суурийн хөрсний тогтворгүй байдал",
    # markups
    "Full Text": "Бүтэн текст",
    "Geometry": "Геометр",
    "Stamp Templates": "Тамгын загвар",
    "Resolve": "Шийдвэрлэх",
    "e.g. Wall measurement, Review note": "ж.нь Ханын хэмжилт, Хяналтын тэмдэглэл",
    "Markup Type": "Тэмдэглэгээний төрөл",
    "Stamps": "Тамгууд",
    "Annotation text...": "Тайлбарын текст...",
    # files
    "Sheet": "Хуудас",
    "Email link": "И-мэйл холбоос",
    "Renamed": "Нэр өөрчилсөн",
    "CDE state changed": "CDE төлөв өөрчлөгдсөн",
    "Tables": "Хүснэгтүүд",
    "Bundle size": "Багцын хэмжээ",
    "File: {{name}}": "Файл: {{name}}",
    "{{count}} file(s) queued": "{{count}} файл дараалалд орсон",
    "{{count}} skipped (unsupported)": "{{count}} алгассан (дэмжигдэхгүй)",
    # projects
    "{{count}} BOQs": "{{count}} BOQ",
    "e.g. XAF": "ж.нь XAF",
    "Sort photos": "Зургуудыг эрэмбэлэх",
    "Photo viewer": "Зураг үзэгч",
    "{{current}} / {{total}}": "{{current}} / {{total}}",
    "Regional Factor": "Бүсийн коэффициент",
    "Newest": "Хамгийн шинэ",
    "Oldest": "Хамгийн хуучин",
    # backup
    ".zip backup file": ".zip нөөц файл",
    "Record counts": "Бичлэгийн тоо",
    "Restore error": "Сэргээх алдаа",
    "Restore Mode": "Сэргээх горим",
    "Backup restored": "Нөөц сэргээгдсэн",
    "Restoring...": "Сэргээж байна...",
    "Backup & Restore": "Нөөцлөлт ба сэргээх",
    "Validation error": "Баталгаажуулалтын алдаа",
    # explorer
    "CAD Converters": "CAD хөрвүүлэгчид",
    "Converting {{name}}...": "{{name}}-г хөрвүүлж байна...",
    "Data Completeness": "Өгөгдлийн бүрэн байдал",
    "File exceeds 100 MB limit.": "Файл 100 МБ хязгаараас хэтэрсэн.",
    "like df.describe()": "df.describe() мэт",
    "Setup Guide": "Тохиргооны заавар",
    "Top {{n}}": "Дээд {{n}}",
    "Bottom {{n}}": "Доод {{n}}",
    # reporting
    "Avg Response (days)": "Дундаж хариу (өдрөөр)",
    "BOQs": "BOQ-ууд",
    "Net Cash Flow": "Цэвэр мөнгөн урсгал",
    "Invoices Due (Month)": "Хугацаа дуусах нэхэмжлэх (Сар)",
    "Invoices Due (Week)": "Хугацаа дуусах нэхэмжлэх (Долоо хоног)",
    "Recalculate KPIs": "KPI-г дахин тооцоолох",
    # dashboard
    "AI Providers": "AI үйлчилгээ үзүүлэгчид",
    "API Server": "API сервер",
    "BOQ Status": "BOQ төлөв",
    "System Status": "Системийн төлөв",
    "Vector DB": "Вектор DB",
    "Portfolio Overview": "Портфолиогийн тойм",
    "Run Setup Wizard": "Тохиргооны мастер ажиллуулах",
    # integrations
    "Receive email notifications (SMTP)": "И-мэйл мэдэгдэл хүлээн авах (SMTP)",
    "Setup instructions": "Тохиргооны заавар",
    "Slack": "Slack",
    "Microsoft Teams": "Microsoft Teams",
    "Telegram": "Telegram",
    "Get notified via Telegram bot": "Telegram bot-оор мэдэгдэл авах",
    "Webhooks": "Webhooks",
    # meetings
    "Due": "Хугацаа",
    "Chair": "Дарга",
    "Chairperson": "Хурлын дарга",
    "Meeting location": "Уулзалтын байршил",
    "Meeting Minutes": "Уулзалтын тэмдэглэл",
    "Showing {{count}} meetings": "{{count}} уулзалт харуулж байна",
    "Scheduled": "Хуваарьласан",
    # settings
    "Gemini 1.5 Pro — multimodal capabilities": "Gemini 1.5 Pro — олон төрлийн боломжтой",
    "GPT-4o / GPT-4 Turbo — widely supported": "GPT-4o / GPT-4 Turbo — өргөн дэмжигдсэн",
    "Imperial (ft, lb)": "Imperial (ft, lb)",
    "English": "Англи хэл",
    "Key": "Түлхүүр",
    "Translated": "Орчуулсан",
    # takeoff
    "e.g., External wall area": "ж.нь, Гадаад ханын талбай",
    "Extract Tables": "Хүснэгт гаргаж авах",
    "Extracting...": "Гаргаж авч байна...",
    "Quick Measurements": "Хурдан хэмжилт",
    "Enter measurements manually:": "Хэмжилтийг гараар оруулна уу:",
    "Markup comments": "Тэмдэглэгээний сэтгэгдэл",
    # correspondence
    "Docs": "Баримт",
    "Date Received": "Хүлээн авсан огноо",
    "Received": "Хүлээн авсан",
    "Additional notes...": "Нэмэлт тэмдэглэл...",
    "Correspondence Log": "Захидлын бүртгэл",
    "Showing {{count}} entries": "{{count}} бичлэг харуулж байна",
    # inspections
    "Inspector": "Шалгагч",
    "Checklist": "Шалгах хуудас",
    "Inspection location": "Шалгалтын байршил",
    "Showing {{count}} inspections": "{{count}} шалгалт харуулж байна",
    # submittals
    "Review comments...": "Хяналтын сэтгэгдэл...",
    "Decision": "Шийдвэр",
    "Review Submittal": "Илгээлтийг хянах",
    "Submittal reviewed": "Илгээлт хянагдсан",
    "Showing {{count}} submittals": "{{count}} илгээлт харуулж байна",
    "e.g. 03 30 00": "ж.нь 03 30 00",
    # fieldreports
    "Condition": "Нөхцөл",
    "Humidity (%)": "Чийгшил (%)",
    "Workforce Hours": "Ажиллах цаг",
    "Temp (°C)": "Темп (°C)",
    "Site visitors today...": "Өнөөдрийн талбайн зочид...",
    "e.g. 15 km/h NW": "ж.нь 15 км/ц БХ",
    # project_intelligence
    "BOQ line count vs baseline": "BOQ мөрийн тоо ба үндсэн утга",
    "Session expired‌⁠‍": "Сессийн хугацаа дууссан‌⁠‍",
    "Toggle chat‌⁠‍": "Чатыг солих‌⁠‍",
    "Enabling…": "Идэвхжүүлж байна…",
    "±{{band}} (90% CI, {{count}} anomalies)": "±{{band}} (90% CI, {{count}} гажиг)",
    # tendering
    "e.g. Schmidt Bau GmbH": "ж.нь Schmidt Bau GmbH",
    "{{count}} hidden": "{{count}} нуугдсан",
    "Variance threshold": "Хэлбэлзлийн босго",
    "e.g. Concrete Works Package": "ж.нь Бетон ажлын багц",
    "Packages": "Багцууд",
    # rfi
    "Close RFI": "RFI хаах",
    "Original Question": "Анхны асуулт",
    "Showing {{count}} RFIs": "{{count}} RFI харуулж байна",
    "Avg. Response Days": "Дундаж хариуны өдөр",
    # modules
    "Regional Standards": "Бүс нутгийн стандартууд",
    "Tools & Analytics": "Хэрэгсэл ба аналитик",
    "Core": "Цөм",
    "Requires: {{deps}}": "Шаардлагатай: {{deps}}",
    # quantities
    "AI": "AI",
    "CAD": "CAD",
    "Quick Manual Entry": "Хурдан гар оруулга",
    "AI Text Input": "AI текст оруулга",
    # schedule
    "e.g. Foundation Works": "ж.нь Суурийн ажил",
    "Buffer": "Нөөц",
    "Critical: {{count}}": "Чухал: {{count}}",
    "e.g. 01.02.003": "ж.нь 01.02.003",
    # transmittals
    "Link CDE Revision": "CDE хувилбар холбох",
    "Revision": "Хувилбар",
    "Transmittal issued": "Дамжуулалт гаргасан",
    "Showing {{count}} transmittals": "{{count}} дамжуулалт харуулж байна",
    # contacts
    "Street, city, postal code": "Гудамж, хот, шуудангийн код",
    "Prequalification": "Урьдчилсан мэргэшил",
    "Showing {{count}} contacts": "{{count}} холбоо барих харуулж байна",
    # compliance
    "Insurance, permits, bonds nearing expiry.": "Даатгал, зөвшөөрөл, баталгаа дуусах дөхсөн.",
    "Nothing expiring soon": "Удахгүй дуусах зүйл байхгүй",
    "{{n}}d left": "{{n}}ө үлдсэн",
    # common
    "Collapse {{label}}": "{{label}}-ийг хураах",
    "Expand {{label}}": "{{label}}-ийг дэлгэх",
    "Filters": "Шүүлтүүр",
    # documents
    "File skipped": "Файл алгасагдсан",
    "{{name}} exceeds 100 MB limit": "{{name}} 100 МБ хязгаараас хэтэрсэн",
    "{{count}} files · {{size}}": "{{count}} файл · {{size}}",
    # punch
    "HVAC": "HVAC",
    "Start Work": "Ажил эхлүүлэх",
    "Reopen": "Дахин нээх",
    # onboarding
    "Company Type": "Компанийн төрөл",
    "Finish": "Дуусгах",
    "Navigation Sidebar": "Навигацийн самбар",
    # safety
    "Incident #": "Тохиолдол #",
    "Observation #": "Ажиглалт #",
    "Treatment": "Эмчилгээ",
    # changeorders
    "Change Type": "Өөрчлөлтийн төрөл",
    "e.g. Additional foundation work": "ж.нь Нэмэлт суурийн ажил",
    "m2, m3, pcs...": "м2, м3, ширхэг...",
    # match_progress
    "Elapsed": "Өнгөрсөн",
    "Overall match progress": "Нийт тааруулалтын явц",
    "Lexical + region boost": "Үгзүйн + бүсийн нэмэгдэл",
    # catalog
    "e.g. Reinforced Concrete Wall C30/37": "ж.нь Армопэлсэн бетон хана C30/37",
    "Usage": "Хэрэглээ",
    # login
    "International standards": "Олон улсын стандартууд",
    "reimagined": "шинэчилсэн",
    # marketplace
    "Demo installed": "Демо суулгасан",
    "Unknown region": "Үл мэдэгдэх бүс",
    # sustainability
    "CO2 footprint analysis": "CO2 ул мөрийн шинжилгээ",
    "Rating": "Үнэлгээ",
    # ncr
    "Linked Inspection": "Холбосон шалгалт",
    "Showing {{count}} NCRs": "{{count}} NCR харуулж байна",
    # procurement
    "Net {{days}} days": "Цэвэр {{days}} өдөр",
    "PO Type": "PO төрөл",
    # analytics
    "{{amount}} actual": "{{amount}} бодит",
    "Var. %": "Хэлб. %",
    # app
    "OpenConstructionERP": "OpenConstructionERP",
    # command_palette
    "navigate": "навигац",
    # share
    "Verifying…": "Шалгаж байна…",
    # field_reports already handled above
    # reports
    "GAEB XML": "GAEB XML",
    # notifications - rfi/risk/submittal/transmittal templates
    "{{code}} — {{title}}": "{{code}} — {{title}}",
    "RFI answered": "RFI хариулагдсан",
    "Submittal awaiting review": "Илгээлт хяналт хүлээж байна",
    "{{code}} ({{title}}). Reason: {{reason}}": "{{code}} ({{title}}). Шалтгаан: {{reason}}",
    "Submittal needs revision": "Илгээлт засвар хэрэгтэй",
    "Transmittal acknowledged": "Дамжуулалт хүлээн зөвшөөрөгдсөн",
    "Recipient confirmed {{code}} ({{title}}).": "Хүлээн авагч {{code}} ({{title}}) баталгаажуулсан.",
    "Transmittal answered": "Дамжуулалт хариулагдсан",
    "{{code}} ({{title}}). {{response_summary}}": "{{code}} ({{title}}). {{response_summary}}",
    # remaining boq
    "AI Smart Actions‌⁠‍": "AI ухаалаг үйлдлүүд‌⁠‍",
    # markups
    "Stamps": "Тамгууд",
    # punch
    # Notification (singular)
    "Submittal approved": "Илгээлт зөвшөөрөгдсөн",
    "Submittal rejected": "Илгээлт татгалзагдсан",
    "Transmittal issued": "Дамжуулалт гаргасан",
    # additional finance, dashboard etc
    "Behind Schedule": "Хуваариас хоцорсон",
    # Catch a few common patterns - "e.g. ..." prefix
    "e.g. ...": "ж.нь ...",
}


INTERP_RE = re.compile(r"\{\{[^}]+\}\}")
INTERP2_RE = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")
HTML_RE = re.compile(r"</?[a-zA-Z][^>]*>")

# The table above is matched through its printing characters only. See visible().
LOOKUP: dict[str, str] = {visible(k): visible(v) for k, v in PHRASES.items()}


def translate(text: str) -> str:
    if not text:
        return text
    probe = visible(text)
    # Exact match
    if probe in LOOKUP:
        return LOOKUP[probe]
    # Try without trailing punctuation
    m = re.match(r"^(.+?)([.!?:…]+)$", probe.strip())
    if m and m.group(1) in LOOKUP:
        return LOOKUP[m.group(1)] + m.group(2)
    return text


def main() -> None:
    with open(UNTRANS_JSON, encoding="utf-8") as f:
        untranslated = json.load(f)

    # Build new translations
    new_translations: dict[str, str] = {}
    for k, en_v in untranslated.items():
        t = translate(en_v)
        if t != en_v:
            new_translations[k] = t

    print(f"Translating {len(new_translations)} / {len(untranslated)} remaining entries")

    # newline="" on both ends, and each line keeps the ending it arrived with.
    # Path.read_text/write_text translate line endings, so on Windows a run that
    # replaces nothing still rewrites all 38288 of mn.ts's line endings to CRLF.
    with open(MN_PATH, encoding="utf-8", newline="") as fh:
        mn_text = fh.read()
    out_lines: list[str] = []
    pat = re.compile(r'^(\s*)"((?:[^"\\]|\\.)+)"\s*:\s*"((?:[^"\\]|\\.)*)"(,?)\s*$')

    count_replaced = 0
    for line in mn_text.splitlines(keepends=True):
        stripped = line.rstrip("\n").rstrip("\r")
        eol = line[len(stripped):]
        m = pat.match(stripped)
        if m:
            indent, key, value, comma = m.group(1), m.group(2), m.group(3), m.group(4)
            if key in new_translations:
                new_val = new_translations[key]
                esc = new_val.replace("\\", "\\\\").replace('"', '\\"')
                new_line = f'{indent}"{key}": "{esc}"{comma}{eol}'
                out_lines.append(new_line)
                count_replaced += 1
                continue
        out_lines.append(line)

    with open(MN_PATH, "w", encoding="utf-8", newline="") as fh:
        fh.write("".join(out_lines))
    print(f"Replaced {count_replaced} entries in mn.ts")


if __name__ == "__main__":
    main()
