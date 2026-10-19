"""‌⁠‍Inject 5 sidebar CTA i18n keys into all locale files.

Idempotent: if a key already exists in a locale, it's left unchanged.
Deprecated one-off: for new work use scripts/i18n.py (get/add/set/missing/rename/export/import).
"""

from __future__ import annotations

from pathlib import Path

# Per-locale translations. en is canonical.
TRANSLATIONS = {
    "en": {
        "nav.add_module": "Add module",
        "nav.add_module_hint": "Build your own · developer guide",
        "nav.request_custom_module": "Request a custom module",
        "nav.request_custom_module_hint": "Missing something? Tell us what you need",
        "modules.dev_guide": "Build a module — developer guide",
    },
    "de": {
        "nav.add_module": "Modul hinzufügen",
        "nav.add_module_hint": "Eigenes erstellen · Entwicklerhandbuch",
        "nav.request_custom_module": "Eigenes Modul anfragen",
        "nav.request_custom_module_hint": "Etwas fehlt? Sag uns, was du brauchst",
        "modules.dev_guide": "Modul erstellen — Entwicklerhandbuch",
    },
    "fr": {
        "nav.add_module": "Ajouter un module",
        "nav.add_module_hint": "Créez le vôtre · guide développeur",
        "nav.request_custom_module": "Demander un module personnalisé",
        "nav.request_custom_module_hint": "Il manque quelque chose ? Dites-nous ce dont vous avez besoin",
        "modules.dev_guide": "Créer un module — guide développeur",
    },
    "es": {
        "nav.add_module": "Añadir módulo",
        "nav.add_module_hint": "Crea el tuyo · guía para desarrolladores",
        "nav.request_custom_module": "Solicitar un módulo personalizado",
        "nav.request_custom_module_hint": "¿Falta algo? Dinos qué necesitas",
        "modules.dev_guide": "Crear un módulo — guía para desarrolladores",
    },
    "pt": {
        "nav.add_module": "Adicionar módulo",
        "nav.add_module_hint": "Crie o seu · guia do desenvolvedor",
        "nav.request_custom_module": "Solicitar módulo personalizado",
        "nav.request_custom_module_hint": "Está faltando algo? Diga-nos o que precisa",
        "modules.dev_guide": "Criar um módulo — guia do desenvolvedor",
    },
    "ru": {
        "nav.add_module": "Добавить модуль",
        "nav.add_module_hint": "Создайте свой · руководство разработчика",
        "nav.request_custom_module": "Запросить свой модуль",
        "nav.request_custom_module_hint": "Чего-то не хватает? Расскажите, что нужно",
        "modules.dev_guide": "Создать модуль — руководство разработчика",
    },
    "zh": {
        "nav.add_module": "添加模块",
        "nav.add_module_hint": "自己构建 · 开发者指南",
        "nav.request_custom_module": "请求自定义模块",
        "nav.request_custom_module_hint": "缺少什么吗？告诉我们您的需求",
        "modules.dev_guide": "构建模块 — 开发者指南",
    },
    "ar": {
        "nav.add_module": "إضافة وحدة",
        "nav.add_module_hint": "أنشئ وحدتك · دليل المطور",
        "nav.request_custom_module": "طلب وحدة مخصصة",
        "nav.request_custom_module_hint": "هل ينقصك شيء؟ أخبرنا بما تحتاجه",
        "modules.dev_guide": "إنشاء وحدة — دليل المطور",
    },
    "hi": {
        "nav.add_module": "मॉड्यूल जोड़ें",
        "nav.add_module_hint": "अपना बनाएँ · डेवलपर गाइड",
        "nav.request_custom_module": "कस्टम मॉड्यूल का अनुरोध करें",
        "nav.request_custom_module_hint": "कुछ छूट रहा है? हमें बताएँ क्या चाहिए",
        "modules.dev_guide": "मॉड्यूल बनाएँ — डेवलपर गाइड",
    },
    "tr": {
        "nav.add_module": "Modül ekle",
        "nav.add_module_hint": "Kendi modülünü oluştur · geliştirici kılavuzu",
        "nav.request_custom_module": "Özel modül talep et",
        "nav.request_custom_module_hint": "Eksik bir şey mi var? Ne gerektiğini bize söyleyin",
        "modules.dev_guide": "Modül oluştur — geliştirici kılavuzu",
    },
    "it": {
        "nav.add_module": "Aggiungi modulo",
        "nav.add_module_hint": "Crea il tuo · guida per sviluppatori",
        "nav.request_custom_module": "Richiedi un modulo personalizzato",
        "nav.request_custom_module_hint": "Manca qualcosa? Dicci di cosa hai bisogno",
        "modules.dev_guide": "Crea un modulo — guida per sviluppatori",
    },
    "nl": {
        "nav.add_module": "Module toevoegen",
        "nav.add_module_hint": "Bouw je eigen · ontwikkelaarsgids",
        "nav.request_custom_module": "Aangepaste module aanvragen",
        "nav.request_custom_module_hint": "Mis je iets? Vertel ons wat je nodig hebt",
        "modules.dev_guide": "Een module bouwen — ontwikkelaarsgids",
    },
    "pl": {
        "nav.add_module": "Dodaj moduł",
        "nav.add_module_hint": "Stwórz własny · przewodnik programisty",
        "nav.request_custom_module": "Zamów moduł niestandardowy",
        "nav.request_custom_module_hint": "Czegoś brakuje? Powiedz nam, czego potrzebujesz",
        "modules.dev_guide": "Zbuduj moduł — przewodnik programisty",
    },
    "cs": {
        "nav.add_module": "Přidat modul",
        "nav.add_module_hint": "Vytvořte si vlastní · průvodce vývojáře",
        "nav.request_custom_module": "Vyžádat vlastní modul",
        "nav.request_custom_module_hint": "Něco chybí? Řekněte nám, co potřebujete",
        "modules.dev_guide": "Sestavit modul — průvodce vývojáře",
    },
    "ja": {
        "nav.add_module": "モジュールを追加",
        "nav.add_module_hint": "自分で作る · 開発者ガイド",
        "nav.request_custom_module": "カスタムモジュールをリクエスト",
        "nav.request_custom_module_hint": "見つからないものは? 必要なものをお知らせください",
        "modules.dev_guide": "モジュールを作る — 開発者ガイド",
    },
    "ko": {
        "nav.add_module": "모듈 추가",
        "nav.add_module_hint": "직접 만들기 · 개발자 가이드",
        "nav.request_custom_module": "맞춤형 모듈 요청",
        "nav.request_custom_module_hint": "찾는 것이 없나요? 필요한 것을 알려주세요",
        "modules.dev_guide": "모듈 빌드하기 — 개발자 가이드",
    },
    "sv": {
        "nav.add_module": "Lägg till modul",
        "nav.add_module_hint": "Bygg din egen · utvecklarguide",
        "nav.request_custom_module": "Beställ en anpassad modul",
        "nav.request_custom_module_hint": "Saknas något? Berätta vad du behöver",
        "modules.dev_guide": "Bygg en modul — utvecklarguide",
    },
    "no": {
        "nav.add_module": "Legg til modul",
        "nav.add_module_hint": "Bygg din egen · utviklerveiledning",
        "nav.request_custom_module": "Be om en tilpasset modul",
        "nav.request_custom_module_hint": "Mangler du noe? Si fra hva du trenger",
        "modules.dev_guide": "Bygg en modul — utviklerveiledning",
    },
    "da": {
        "nav.add_module": "Tilføj modul",
        "nav.add_module_hint": "Byg dit eget · udviklervejledning",
        "nav.request_custom_module": "Anmod om et brugerdefineret modul",
        "nav.request_custom_module_hint": "Mangler du noget? Fortæl os hvad du har brug for",
        "modules.dev_guide": "Byg et modul — udviklervejledning",
    },
    "fi": {
        "nav.add_module": "Lisää moduuli",
        "nav.add_module_hint": "Rakenna omasi · kehittäjäopas",
        "nav.request_custom_module": "Pyydä mukautettu moduuli",
        "nav.request_custom_module_hint": "Puuttuuko jotain? Kerro mitä tarvitset",
        "modules.dev_guide": "Rakenna moduuli — kehittäjäopas",
    },
    "bg": {
        "nav.add_module": "Добавяне на модул",
        "nav.add_module_hint": "Създай свой · ръководство за разработчици",
        "nav.request_custom_module": "Заявка за персонализиран модул",
        "nav.request_custom_module_hint": "Липсва ли нещо? Кажете ни какво ви трябва",
        "modules.dev_guide": "Изграждане на модул — ръководство за разработчици",
    },
    "hr": {
        "nav.add_module": "Dodaj modul",
        "nav.add_module_hint": "Izgradi vlastiti · vodič za programere",
        "nav.request_custom_module": "Zatraži prilagođeni modul",
        "nav.request_custom_module_hint": "Nedostaje li nešto? Recite nam što vam treba",
        "modules.dev_guide": "Izgradi modul — vodič za programere",
    },
    "id": {
        "nav.add_module": "Tambah modul",
        "nav.add_module_hint": "Buat milikmu · panduan pengembang",
        "nav.request_custom_module": "Minta modul kustom",
        "nav.request_custom_module_hint": "Ada yang kurang? Beri tahu kami apa yang Anda butuhkan",
        "modules.dev_guide": "Bangun modul — panduan pengembang",
    },
    "ro": {
        "nav.add_module": "Adaugă modul",
        "nav.add_module_hint": "Construiește-l pe al tău · ghidul dezvoltatorului",
        "nav.request_custom_module": "Solicită un modul personalizat",
        "nav.request_custom_module_hint": "Lipsește ceva? Spune-ne ce ai nevoie",
        "modules.dev_guide": "Construiește un modul — ghidul dezvoltatorului",
    },
    "th": {
        "nav.add_module": "เพิ่มโมดูล",
        "nav.add_module_hint": "สร้างของคุณเอง · คู่มือสำหรับนักพัฒนา",
        "nav.request_custom_module": "ขอโมดูลแบบกำหนดเอง",
        "nav.request_custom_module_hint": "ขาดอะไรหรือไม่? บอกเราว่าคุณต้องการอะไร",
        "modules.dev_guide": "สร้างโมดูล — คู่มือสำหรับนักพัฒนา",
    },
    "vi": {
        "nav.add_module": "Thêm mô-đun",
        "nav.add_module_hint": "Tự tạo riêng · hướng dẫn cho lập trình viên",
        "nav.request_custom_module": "Yêu cầu mô-đun tùy chỉnh",
        "nav.request_custom_module_hint": "Còn thiếu gì? Cho chúng tôi biết bạn cần gì",
        "modules.dev_guide": "Xây dựng một mô-đun — hướng dẫn cho lập trình viên",
    },
    "mn": {
        "nav.add_module": "Модуль нэмэх",
        "nav.add_module_hint": "Өөрөө бүтээх · хөгжүүлэгчийн гарын авлага",
        "nav.request_custom_module": "Тусгай модуль захиалах",
        "nav.request_custom_module_hint": "Дутагдаж байна уу? Юу хэрэгтэйгээ хэлээрэй",
        "modules.dev_guide": "Модуль бүтээх — хөгжүүлэгчийн гарын авлага",
    },
}

LOCALES_DIR = Path(__file__).parent.parent / "frontend" / "src" / "app" / "locales"

CLOSING_BRACE_PATTERNS = [
    "  }\n} as { translation: Record<string, string> };",
    "  }\n} as const;",
    "  },\n} as { translation: Record<string, string> };",
]


def inject_keys(locale_code: str, keys: dict[str, str]) -> tuple[int, int]:
    """‌⁠‍Return (added, skipped) count."""
    fp = LOCALES_DIR / f"{locale_code}.ts"
    if not fp.exists():
        print(f"  SKIP {locale_code}: file missing")
        return (0, 0)
    # Read preserving line endings: Path.read_text has no newline= and would
    # translate CRLF to LF, which turns a one-key edit into a whole-file diff.
    with open(fp, encoding="utf-8", newline="") as fh:
        text = fh.read()
    eol = "\r\n" if "\r\n" in text else "\n"
    added = 0
    skipped = 0
    new_lines: list[str] = []
    for key, value in keys.items():
        if f'"{key}"' in text:
            skipped += 1
            continue
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        new_lines.append(f'    "{key}": "{escaped}",')
        added += 1
    if not new_lines:
        return (0, skipped)
    # Find the closing brace and inject before it
    inject_block = eol.join(new_lines) + eol
    # The anchors are written with \n; match them against the endings the file
    # actually uses rather than assuming the ones this host writes.
    for pattern in CLOSING_BRACE_PATTERNS:
        anchor = pattern.replace("\n", eol)
        if anchor in text:
            text = text.replace(anchor, inject_block + anchor, 1)
            fp.write_text(text, encoding="utf-8", newline="")
            return (added, skipped)
    # Fallback: find last "  }\n}"
    idx = text.rfind("  }" + eol + "}")
    if idx == -1:
        print(f"  ERROR {locale_code}: closing brace pattern not found")
        return (0, skipped)
    text = text[:idx] + inject_block + text[idx:]
    fp.write_text(text, encoding="utf-8", newline="")
    return (added, skipped)


def main() -> None:
    total_added = 0
    total_skipped = 0
    for code, keys in TRANSLATIONS.items():
        added, skipped = inject_keys(code, keys)
        print(f"  {code}: +{added} added, {skipped} skipped (already present)")
        total_added += added
        total_skipped += skipped
    print(f"\nTotal: +{total_added} keys added, {total_skipped} already present")


if __name__ == "__main__":
    main()
