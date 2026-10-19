"""‌⁠‍Insert the 6 new match_elements.group_by_* keys into 25 non-EN locales.

Native translations sourced from each language's standard
construction/UI dictionary. EN is already done in en.ts.

Anchor: existing line `"match_elements.trade_filter":` — insert the
six new lines RIGHT AFTER it so the file stays diff-friendly.
Deprecated one-off: for new work use scripts/i18n.py (get/add/set/missing/rename/export/import).
"""

from __future__ import annotations

import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

LOCALES_DIR = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src" / "app" / "locales"

TRANSLATIONS: dict[str, dict[str, str]] = {
    "de": {
        "group_by": "Gruppieren nach",
        "group_by_empty": "Mindestens ein Attribut auswählen",
        "group_by_active": "{{count}} aktiv · klicken zum Entfernen",
        "group_by_remove": "Klicken zum Entfernen",
        "group_by_sample": "z. B.",
        "loading_attributes": "Wird geladen…",
    },
    "ru": {
        "group_by": "Группировать по",
        "group_by_empty": "Выберите хотя бы один атрибут",
        "group_by_active": "{{count}} активно · нажмите чтобы убрать",
        "group_by_remove": "Нажмите чтобы убрать из группировки",
        "group_by_sample": "напр.",
        "loading_attributes": "Загрузка…",
    },
    "es": {
        "group_by": "Agrupar por",
        "group_by_empty": "Selecciona al menos un atributo",
        "group_by_active": "{{count}} activos · clic para quitar",
        "group_by_remove": "Clic para quitar de la agrupación",
        "group_by_sample": "ej.",
        "loading_attributes": "Cargando…",
    },
    "fr": {
        "group_by": "Grouper par",
        "group_by_empty": "Choisir au moins un attribut",
        "group_by_active": "{{count}} actifs · cliquer pour retirer",
        "group_by_remove": "Cliquer pour retirer du groupement",
        "group_by_sample": "p. ex.",
        "loading_attributes": "Chargement…",
    },
    "pt": {
        "group_by": "Agrupar por",
        "group_by_empty": "Selecione pelo menos um atributo",
        "group_by_active": "{{count}} ativos · clique para remover",
        "group_by_remove": "Clique para remover do agrupamento",
        "group_by_sample": "ex.",
        "loading_attributes": "Carregando…",
    },
    "it": {
        "group_by": "Raggruppa per",
        "group_by_empty": "Seleziona almeno un attributo",
        "group_by_active": "{{count}} attivi · clic per rimuovere",
        "group_by_remove": "Clic per rimuovere dal raggruppamento",
        "group_by_sample": "es.",
        "loading_attributes": "Caricamento…",
    },
    "nl": {
        "group_by": "Groeperen op",
        "group_by_empty": "Kies minstens één attribuut",
        "group_by_active": "{{count}} actief · klik om te verwijderen",
        "group_by_remove": "Klik om uit de groepering te verwijderen",
        "group_by_sample": "bv.",
        "loading_attributes": "Laden…",
    },
    "pl": {
        "group_by": "Grupuj według",
        "group_by_empty": "Wybierz przynajmniej jeden atrybut",
        "group_by_active": "{{count}} aktywne · kliknij, aby usunąć",
        "group_by_remove": "Kliknij, aby usunąć z grupowania",
        "group_by_sample": "np.",
        "loading_attributes": "Ładowanie…",
    },
    "sv": {
        "group_by": "Gruppera efter",
        "group_by_empty": "Välj minst ett attribut",
        "group_by_active": "{{count}} aktiva · klicka för att ta bort",
        "group_by_remove": "Klicka för att ta bort från gruppering",
        "group_by_sample": "t.ex.",
        "loading_attributes": "Laddar…",
    },
    "tr": {
        "group_by": "Grupla",
        "group_by_empty": "En az bir öznitelik seçin",
        "group_by_active": "{{count}} aktif · kaldırmak için tıklayın",
        "group_by_remove": "Gruplamadan kaldırmak için tıklayın",
        "group_by_sample": "ör.",
        "loading_attributes": "Yükleniyor…",
    },
    "zh": {
        "group_by": "分组依据",
        "group_by_empty": "至少选择一个属性",
        "group_by_active": "{{count}} 个已启用 · 点击移除",
        "group_by_remove": "点击从分组中移除",
        "group_by_sample": "例如",
        "loading_attributes": "加载中…",
    },
    "ja": {
        "group_by": "グループ化",
        "group_by_empty": "少なくとも1つの属性を選択",
        "group_by_active": "{{count}}個有効 · クリックで削除",
        "group_by_remove": "クリックでグループ化から削除",
        "group_by_sample": "例:",
        "loading_attributes": "読み込み中…",
    },
    "ko": {
        "group_by": "그룹화 기준",
        "group_by_empty": "속성을 하나 이상 선택하세요",
        "group_by_active": "{{count}}개 활성 · 클릭하여 제거",
        "group_by_remove": "클릭하여 그룹화에서 제거",
        "group_by_sample": "예:",
        "loading_attributes": "로드 중…",
    },
    "hi": {
        "group_by": "समूह बनाएं",
        "group_by_empty": "कम से कम एक विशेषता चुनें",
        "group_by_active": "{{count}} सक्रिय · हटाने के लिए क्लिक करें",
        "group_by_remove": "समूहीकरण से हटाने के लिए क्लिक करें",
        "group_by_sample": "उदा.",
        "loading_attributes": "लोड हो रहा है…",
    },
    "ar": {
        "group_by": "تجميع حسب",
        "group_by_empty": "اختر سمة واحدة على الأقل",
        "group_by_active": "{{count}} نشط · انقر للإزالة",
        "group_by_remove": "انقر للإزالة من التجميع",
        "group_by_sample": "مثال",
        "loading_attributes": "جارٍ التحميل…",
    },
    "cs": {
        "group_by": "Seskupit podle",
        "group_by_empty": "Vyberte alespoň jeden atribut",
        "group_by_active": "{{count}} aktivní · klikněte pro odstranění",
        "group_by_remove": "Kliknutím odstraníte ze seskupení",
        "group_by_sample": "např.",
        "loading_attributes": "Načítání…",
    },
    "da": {
        "group_by": "Gruppér efter",
        "group_by_empty": "Vælg mindst én attribut",
        "group_by_active": "{{count}} aktive · klik for at fjerne",
        "group_by_remove": "Klik for at fjerne fra gruppering",
        "group_by_sample": "f.eks.",
        "loading_attributes": "Indlæser…",
    },
    "no": {
        "group_by": "Grupper etter",
        "group_by_empty": "Velg minst ett attributt",
        "group_by_active": "{{count}} aktive · klikk for å fjerne",
        "group_by_remove": "Klikk for å fjerne fra gruppering",
        "group_by_sample": "f.eks.",
        "loading_attributes": "Laster inn…",
    },
    "fi": {
        "group_by": "Ryhmittele",
        "group_by_empty": "Valitse vähintään yksi määrite",
        "group_by_active": "{{count}} aktiivista · napsauta poistaaksesi",
        "group_by_remove": "Napsauta poistaaksesi ryhmittelystä",
        "group_by_sample": "esim.",
        "loading_attributes": "Ladataan…",
    },
    "id": {
        "group_by": "Kelompokkan menurut",
        "group_by_empty": "Pilih setidaknya satu atribut",
        "group_by_active": "{{count}} aktif · klik untuk menghapus",
        "group_by_remove": "Klik untuk menghapus dari pengelompokan",
        "group_by_sample": "mis.",
        "loading_attributes": "Memuat…",
    },
    "vi": {
        "group_by": "Nhóm theo",
        "group_by_empty": "Chọn ít nhất một thuộc tính",
        "group_by_active": "{{count}} đang hoạt động · nhấp để xóa",
        "group_by_remove": "Nhấp để xóa khỏi nhóm",
        "group_by_sample": "ví dụ:",
        "loading_attributes": "Đang tải…",
    },
    "th": {
        "group_by": "จัดกลุ่มตาม",
        "group_by_empty": "เลือกแอตทริบิวต์อย่างน้อยหนึ่งรายการ",
        "group_by_active": "{{count}} รายการ · คลิกเพื่อลบ",
        "group_by_remove": "คลิกเพื่อลบออกจากการจัดกลุ่ม",
        "group_by_sample": "เช่น",
        "loading_attributes": "กำลังโหลด…",
    },
    "bg": {
        "group_by": "Групиране по",
        "group_by_empty": "Изберете поне един атрибут",
        "group_by_active": "{{count}} активни · щракнете, за да премахнете",
        "group_by_remove": "Щракнете, за да премахнете от групирането",
        "group_by_sample": "напр.",
        "loading_attributes": "Зареждане…",
    },
    "hr": {
        "group_by": "Grupiraj prema",
        "group_by_empty": "Odaberite barem jedan atribut",
        "group_by_active": "{{count}} aktivnih · kliknite za uklanjanje",
        "group_by_remove": "Kliknite za uklanjanje iz grupiranja",
        "group_by_sample": "npr.",
        "loading_attributes": "Učitavanje…",
    },
    "ro": {
        "group_by": "Grupează după",
        "group_by_empty": "Selectează cel puțin un atribut",
        "group_by_active": "{{count}} active · clic pentru a elimina",
        "group_by_remove": "Clic pentru a elimina din grupare",
        "group_by_sample": "ex.",
        "loading_attributes": "Se încarcă…",
    },
}


ANCHOR = re.compile(r'(    "match_elements\.trade_filter":\s*"[^"]*",\n)')


def insert_keys(path: pathlib.Path, keys: dict[str, str]) -> bool:
    # Read preserving line endings: Path.read_text has no newline= and would
    # translate CRLF to LF, which turns a one-key edit into a whole-file diff.
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    eol = "\r\n" if "\r\n" in text else "\n"
    if '"match_elements.group_by":' in text:
        return False
    m = ANCHOR.search(text)
    if not m:
        return False
    lines: list[str] = []
    for short, value in keys.items():
        full_key = f"match_elements.{short}"
        safe = value.replace('"', '\\"')
        lines.append(f'    "{full_key}": "{safe}",')
    block = eol.join(lines) + eol
    new_text = text.replace(m.group(1), m.group(1) + block, 1)
    path.write_text(new_text, encoding="utf-8", newline="")
    return True


def main() -> int:
    changed = 0
    for code, keys in TRANSLATIONS.items():
        path = LOCALES_DIR / f"{code}.ts"
        if not path.exists():
            print(f"  skip: {code}.ts not found")
            continue
        if insert_keys(path, keys):
            print(f"  + {code}: 6 keys inserted")
            changed += 1
        else:
            print(f"  = {code}: already present or no anchor")
    print(f"\n{changed} locale(s) updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
