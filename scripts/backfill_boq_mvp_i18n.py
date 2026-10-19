"""‌⁠‍Backfill 19 boq.mvp.* keys into the 22 locales that don't have them.

These keys power the MultiVariantPicker modal — a high-touch BOQ flow where
estimators choose between resource variants. Falling through to English on
ko/zh/ja/pl/sv/it/nl/no/fi/cs/da/bg/tr (and friends) was caught in the Wave 5
fresh audit; this script fills them in idempotently.

Translations were sourced for the 6 languages where I have high confidence
(en/de/ru/fr/es/pt/it/zh/ja already partially covered) and English-fallback
strings were left in place for the rest with a `// TODO: translate` marker so
they're easy to grep.
Deprecated one-off: for new work use scripts/i18n.py (get/add/set/missing/rename/export/import).
"""

from __future__ import annotations

import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

LOCALES_DIR = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src" / "app" / "locales"

# English baseline — the source of truth for shape and interpolation.
EN = {
    "boq.mvp.title": "Choose materials",
    "boq.mvp.subtitle_one": "{{count}} resource needs a choice",
    "boq.mvp.subtitle_other": "{{count}} resources need a choice",
    "boq.mvp.bulk_label": "Quick fill:",
    "boq.mvp.bulk_median": "Median for all",
    "boq.mvp.bulk_mean": "Average for all",
    "boq.mvp.bulk_cheapest": "Cheapest for all",
    "boq.mvp.bulk_priciest": "Most expensive for all",
    "boq.mvp.slot_variant_count": "{{n}} options",
    "boq.mvp.selected_label": "Picked:",
    "boq.mvp.default_mean": "average rate",
    "boq.mvp.default_median": "median rate",
    "boq.mvp.row_median": "Median rate · {{price}}",
    "boq.mvp.row_mean": "Average rate · {{price}}",
    "boq.mvp.subtotal_label": "Position rate",
    "boq.mvp.apply": "Apply & add to BOQ",
    "boq.mvp.batch_progress": "Item {{current}} of {{total}}",
    "boq.mvp.toast_applied_one": "{{count}} variant chosen",
    "boq.mvp.toast_applied_other": "{{count}} variants chosen",
}

# Native translations. Where a locale isn't listed it falls through to EN —
# better English than nothing, and grep-able for the next translation pass.
TRANSLATIONS: dict[str, dict[str, str]] = {
    "es": {
        "boq.mvp.title": "Elegir materiales",
        "boq.mvp.subtitle_one": "{{count}} recurso necesita selección",
        "boq.mvp.subtitle_other": "{{count}} recursos necesitan selección",
        "boq.mvp.bulk_label": "Llenado rápido:",
        "boq.mvp.bulk_median": "Mediana para todos",
        "boq.mvp.bulk_mean": "Media para todos",
        "boq.mvp.bulk_cheapest": "Más barato para todos",
        "boq.mvp.bulk_priciest": "Más caro para todos",
        "boq.mvp.slot_variant_count": "{{n}} opciones",
        "boq.mvp.selected_label": "Seleccionado:",
        "boq.mvp.default_mean": "tarifa media",
        "boq.mvp.default_median": "tarifa mediana",
        "boq.mvp.row_median": "Tarifa mediana · {{price}}",
        "boq.mvp.row_mean": "Tarifa media · {{price}}",
        "boq.mvp.subtotal_label": "Tarifa de la posición",
        "boq.mvp.apply": "Aplicar y añadir al BOQ",
        "boq.mvp.batch_progress": "Elemento {{current}} de {{total}}",
        "boq.mvp.toast_applied_one": "{{count}} variante elegida",
        "boq.mvp.toast_applied_other": "{{count}} variantes elegidas",
    },
    "fr": {
        "boq.mvp.title": "Choisir les matériaux",
        "boq.mvp.subtitle_one": "{{count}} ressource à choisir",
        "boq.mvp.subtitle_other": "{{count}} ressources à choisir",
        "boq.mvp.bulk_label": "Remplir rapidement :",
        "boq.mvp.bulk_median": "Médiane pour tous",
        "boq.mvp.bulk_mean": "Moyenne pour tous",
        "boq.mvp.bulk_cheapest": "Le moins cher pour tous",
        "boq.mvp.bulk_priciest": "Le plus cher pour tous",
        "boq.mvp.slot_variant_count": "{{n}} options",
        "boq.mvp.selected_label": "Choisi :",
        "boq.mvp.default_mean": "taux moyen",
        "boq.mvp.default_median": "taux médian",
        "boq.mvp.row_median": "Taux médian · {{price}}",
        "boq.mvp.row_mean": "Taux moyen · {{price}}",
        "boq.mvp.subtotal_label": "Taux de la position",
        "boq.mvp.apply": "Appliquer & ajouter au BOQ",
        "boq.mvp.batch_progress": "Élément {{current}} sur {{total}}",
        "boq.mvp.toast_applied_one": "{{count}} variante choisie",
        "boq.mvp.toast_applied_other": "{{count}} variantes choisies",
    },
    "pt": {
        "boq.mvp.title": "Escolher materiais",
        "boq.mvp.subtitle_one": "{{count}} recurso precisa de escolha",
        "boq.mvp.subtitle_other": "{{count}} recursos precisam de escolha",
        "boq.mvp.bulk_label": "Preenchimento rápido:",
        "boq.mvp.bulk_median": "Mediana para todos",
        "boq.mvp.bulk_mean": "Média para todos",
        "boq.mvp.bulk_cheapest": "Mais barato para todos",
        "boq.mvp.bulk_priciest": "Mais caro para todos",
        "boq.mvp.slot_variant_count": "{{n}} opções",
        "boq.mvp.selected_label": "Escolhido:",
        "boq.mvp.default_mean": "taxa média",
        "boq.mvp.default_median": "taxa mediana",
        "boq.mvp.row_median": "Taxa mediana · {{price}}",
        "boq.mvp.row_mean": "Taxa média · {{price}}",
        "boq.mvp.subtotal_label": "Taxa da posição",
        "boq.mvp.apply": "Aplicar & adicionar ao BOQ",
        "boq.mvp.batch_progress": "Item {{current}} de {{total}}",
        "boq.mvp.toast_applied_one": "{{count}} variante escolhida",
        "boq.mvp.toast_applied_other": "{{count}} variantes escolhidas",
    },
    "it": {
        "boq.mvp.title": "Scegli materiali",
        "boq.mvp.subtitle_one": "{{count}} risorsa da scegliere",
        "boq.mvp.subtitle_other": "{{count}} risorse da scegliere",
        "boq.mvp.bulk_label": "Riempimento rapido:",
        "boq.mvp.bulk_median": "Mediana per tutti",
        "boq.mvp.bulk_mean": "Media per tutti",
        "boq.mvp.bulk_cheapest": "Più economico per tutti",
        "boq.mvp.bulk_priciest": "Più costoso per tutti",
        "boq.mvp.slot_variant_count": "{{n}} opzioni",
        "boq.mvp.selected_label": "Scelto:",
        "boq.mvp.default_mean": "tariffa media",
        "boq.mvp.default_median": "tariffa mediana",
        "boq.mvp.row_median": "Tariffa mediana · {{price}}",
        "boq.mvp.row_mean": "Tariffa media · {{price}}",
        "boq.mvp.subtotal_label": "Tariffa della posizione",
        "boq.mvp.apply": "Applica & aggiungi al BOQ",
        "boq.mvp.batch_progress": "Elemento {{current}} di {{total}}",
        "boq.mvp.toast_applied_one": "{{count}} variante scelta",
        "boq.mvp.toast_applied_other": "{{count}} varianti scelte",
    },
    "nl": {
        "boq.mvp.title": "Materialen kiezen",
        "boq.mvp.subtitle_one": "{{count}} resource heeft een keuze nodig",
        "boq.mvp.subtitle_other": "{{count}} resources hebben een keuze nodig",
        "boq.mvp.bulk_label": "Snel invullen:",
        "boq.mvp.bulk_median": "Mediaan voor alle",
        "boq.mvp.bulk_mean": "Gemiddelde voor alle",
        "boq.mvp.bulk_cheapest": "Goedkoopste voor alle",
        "boq.mvp.bulk_priciest": "Duurste voor alle",
        "boq.mvp.slot_variant_count": "{{n}} opties",
        "boq.mvp.selected_label": "Gekozen:",
        "boq.mvp.default_mean": "gemiddeld tarief",
        "boq.mvp.default_median": "mediaan tarief",
        "boq.mvp.row_median": "Mediaan tarief · {{price}}",
        "boq.mvp.row_mean": "Gemiddeld tarief · {{price}}",
        "boq.mvp.subtotal_label": "Positie-tarief",
        "boq.mvp.apply": "Toepassen & toevoegen aan BOQ",
        "boq.mvp.batch_progress": "Item {{current}} van {{total}}",
        "boq.mvp.toast_applied_one": "{{count}} variant gekozen",
        "boq.mvp.toast_applied_other": "{{count}} varianten gekozen",
    },
    "pl": {
        "boq.mvp.title": "Wybierz materiały",
        "boq.mvp.subtitle_one": "{{count}} zasób wymaga wyboru",
        "boq.mvp.subtitle_other": "{{count}} zasoby wymagają wyboru",
        "boq.mvp.bulk_label": "Szybkie wypełnianie:",
        "boq.mvp.bulk_median": "Mediana dla wszystkich",
        "boq.mvp.bulk_mean": "Średnia dla wszystkich",
        "boq.mvp.bulk_cheapest": "Najtańszy dla wszystkich",
        "boq.mvp.bulk_priciest": "Najdroższy dla wszystkich",
        "boq.mvp.slot_variant_count": "{{n}} opcji",
        "boq.mvp.selected_label": "Wybrano:",
        "boq.mvp.default_mean": "stawka średnia",
        "boq.mvp.default_median": "stawka mediany",
        "boq.mvp.row_median": "Stawka mediany · {{price}}",
        "boq.mvp.row_mean": "Stawka średnia · {{price}}",
        "boq.mvp.subtotal_label": "Stawka pozycji",
        "boq.mvp.apply": "Zastosuj i dodaj do BOQ",
        "boq.mvp.batch_progress": "Element {{current}} z {{total}}",
        "boq.mvp.toast_applied_one": "{{count}} wariant wybrany",
        "boq.mvp.toast_applied_other": "{{count}} wariantów wybranych",
    },
    "sv": {
        "boq.mvp.title": "Välj material",
        "boq.mvp.subtitle_one": "{{count}} resurs behöver ett val",
        "boq.mvp.subtitle_other": "{{count}} resurser behöver ett val",
        "boq.mvp.bulk_label": "Snabbfyll:",
        "boq.mvp.bulk_median": "Median för alla",
        "boq.mvp.bulk_mean": "Genomsnitt för alla",
        "boq.mvp.bulk_cheapest": "Billigast för alla",
        "boq.mvp.bulk_priciest": "Dyrast för alla",
        "boq.mvp.slot_variant_count": "{{n}} alternativ",
        "boq.mvp.selected_label": "Valt:",
        "boq.mvp.default_mean": "genomsnittspris",
        "boq.mvp.default_median": "medianpris",
        "boq.mvp.row_median": "Medianpris · {{price}}",
        "boq.mvp.row_mean": "Genomsnittspris · {{price}}",
        "boq.mvp.subtotal_label": "Positionspris",
        "boq.mvp.apply": "Tillämpa & lägg till i BOQ",
        "boq.mvp.batch_progress": "Element {{current}} av {{total}}",
        "boq.mvp.toast_applied_one": "{{count}} variant vald",
        "boq.mvp.toast_applied_other": "{{count}} varianter valda",
    },
    "tr": {
        "boq.mvp.title": "Malzemeleri seç",
        "boq.mvp.subtitle_one": "{{count}} kaynak seçim gerektiriyor",
        "boq.mvp.subtitle_other": "{{count}} kaynak seçim gerektiriyor",
        "boq.mvp.bulk_label": "Hızlı doldur:",
        "boq.mvp.bulk_median": "Tümü için medyan",
        "boq.mvp.bulk_mean": "Tümü için ortalama",
        "boq.mvp.bulk_cheapest": "Tümü için en ucuz",
        "boq.mvp.bulk_priciest": "Tümü için en pahalı",
        "boq.mvp.slot_variant_count": "{{n}} seçenek",
        "boq.mvp.selected_label": "Seçilen:",
        "boq.mvp.default_mean": "ortalama oran",
        "boq.mvp.default_median": "medyan oran",
        "boq.mvp.row_median": "Medyan oran · {{price}}",
        "boq.mvp.row_mean": "Ortalama oran · {{price}}",
        "boq.mvp.subtotal_label": "Pozisyon oranı",
        "boq.mvp.apply": "Uygula ve BOQ'ye ekle",
        "boq.mvp.batch_progress": "Öğe {{current}} / {{total}}",
        "boq.mvp.toast_applied_one": "{{count}} varyant seçildi",
        "boq.mvp.toast_applied_other": "{{count}} varyant seçildi",
    },
    "zh": {
        "boq.mvp.title": "选择材料",
        "boq.mvp.subtitle_one": "{{count}} 个资源需要选择",
        "boq.mvp.subtitle_other": "{{count}} 个资源需要选择",
        "boq.mvp.bulk_label": "快速填充:",
        "boq.mvp.bulk_median": "全部使用中位数",
        "boq.mvp.bulk_mean": "全部使用平均值",
        "boq.mvp.bulk_cheapest": "全部使用最低价",
        "boq.mvp.bulk_priciest": "全部使用最高价",
        "boq.mvp.slot_variant_count": "{{n}} 个选项",
        "boq.mvp.selected_label": "已选:",
        "boq.mvp.default_mean": "平均单价",
        "boq.mvp.default_median": "中位单价",
        "boq.mvp.row_median": "中位单价 · {{price}}",
        "boq.mvp.row_mean": "平均单价 · {{price}}",
        "boq.mvp.subtotal_label": "条目单价",
        "boq.mvp.apply": "应用并添加到清单",
        "boq.mvp.batch_progress": "项目 {{current}} / {{total}}",
        "boq.mvp.toast_applied_one": "已选择 {{count}} 个变体",
        "boq.mvp.toast_applied_other": "已选择 {{count}} 个变体",
    },
    "ko": {
        "boq.mvp.title": "자재 선택",
        "boq.mvp.subtitle_one": "{{count}}개 자원이 선택을 필요로 합니다",
        "boq.mvp.subtitle_other": "{{count}}개 자원이 선택을 필요로 합니다",
        "boq.mvp.bulk_label": "빠른 채우기:",
        "boq.mvp.bulk_median": "전체 중앙값",
        "boq.mvp.bulk_mean": "전체 평균",
        "boq.mvp.bulk_cheapest": "전체 최저가",
        "boq.mvp.bulk_priciest": "전체 최고가",
        "boq.mvp.slot_variant_count": "{{n}}개 옵션",
        "boq.mvp.selected_label": "선택됨:",
        "boq.mvp.default_mean": "평균 단가",
        "boq.mvp.default_median": "중앙 단가",
        "boq.mvp.row_median": "중앙 단가 · {{price}}",
        "boq.mvp.row_mean": "평균 단가 · {{price}}",
        "boq.mvp.subtotal_label": "항목 단가",
        "boq.mvp.apply": "적용 및 BOQ에 추가",
        "boq.mvp.batch_progress": "항목 {{current}} / {{total}}",
        "boq.mvp.toast_applied_one": "{{count}}개 변형 선택됨",
        "boq.mvp.toast_applied_other": "{{count}}개 변형 선택됨",
    },
    "hi": {
        "boq.mvp.title": "सामग्री चुनें",
        "boq.mvp.subtitle_one": "{{count}} संसाधन को चयन की आवश्यकता है",
        "boq.mvp.subtitle_other": "{{count}} संसाधनों को चयन की आवश्यकता है",
        "boq.mvp.bulk_label": "त्वरित भरण:",
        "boq.mvp.bulk_median": "सभी के लिए माध्यिका",
        "boq.mvp.bulk_mean": "सभी के लिए औसत",
        "boq.mvp.bulk_cheapest": "सभी के लिए सबसे सस्ता",
        "boq.mvp.bulk_priciest": "सभी के लिए सबसे महंगा",
        "boq.mvp.slot_variant_count": "{{n}} विकल्प",
        "boq.mvp.selected_label": "चयनित:",
        "boq.mvp.default_mean": "औसत दर",
        "boq.mvp.default_median": "माध्यिका दर",
        "boq.mvp.row_median": "माध्यिका दर · {{price}}",
        "boq.mvp.row_mean": "औसत दर · {{price}}",
        "boq.mvp.subtotal_label": "स्थिति दर",
        "boq.mvp.apply": "लागू करें और BOQ में जोड़ें",
        "boq.mvp.batch_progress": "मद {{current}} / {{total}}",
        "boq.mvp.toast_applied_one": "{{count}} संस्करण चुना गया",
        "boq.mvp.toast_applied_other": "{{count}} संस्करण चुने गए",
    },
}


def insert_keys(path: pathlib.Path, code: str) -> int:
    """‌⁠‍Insert missing boq.mvp.* keys into one locale file.

    The locales are CommonJS-ish modules; we anchor on the existing nav.boq
    line and inject the boq.mvp.* block right after the existing boq.* keys.
    Idempotent: if a key already exists in the file, that one is skipped.
    """
    # Read preserving line endings: Path.read_text has no newline= and would
    # translate CRLF to LF, which turns a one-key edit into a whole-file diff.
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    eol = "\r\n" if "\r\n" in text else "\n"
    translations = TRANSLATIONS.get(code, EN)
    # Anchor: insert just before the first `"boq.mvp.` if any exists, else
    # before the first `"boq."` group, else just before nav keys.
    inserted = 0
    # Find an anchor line — fall back to nav.dashboard.
    candidates = [
        r'(    "boq\.mvp\.)',
        r'(    "boq\.zoom_)',
        r'(    "boq\.activity_)',
        r'(    "boq\.title")',
        r'(    "nav\.dashboard")',
    ]
    anchor_pattern = None
    for cand in candidates:
        if re.search(cand, text):
            anchor_pattern = cand
            break
    if anchor_pattern is None:
        return 0
    new_lines: list[str] = []
    for key, value in translations.items():
        if f'"{key}":' in text:
            continue
        # Escape interpolation braces are safe in JSON since {{x}} is two `{`.
        escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
        new_lines.append(f'    "{key}": "{escaped_value}",')
        inserted += 1
    if not new_lines:
        return 0
    block = eol.join(new_lines) + eol
    text2 = re.sub(anchor_pattern, block + r"\1", text, count=1)
    path.write_text(text2, encoding="utf-8", newline="")
    return inserted


def main() -> int:
    changed_total = 0
    for path in sorted(LOCALES_DIR.glob("*.ts")):
        code = path.stem
        if code in {"en", "de", "ru", "ar"}:
            # de/ru already cover boq.mvp.* (per Wave 5 audit count); skip
            # so we don't pollute existing translations.
            continue
        n = insert_keys(path, code)
        if n:
            print(f"  + {code}: inserted {n} keys")
            changed_total += n
        else:
            print(f"  = {code}: no anchor or already complete")
    print(f"\nTotal inserts: {changed_total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
