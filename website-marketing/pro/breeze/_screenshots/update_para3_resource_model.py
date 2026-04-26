"""Replace the 'research journey / reverse-engineering closed formats' opening
   of voices.para3 with a softer, plain-spoken version, in en/de/ru."""
import json
from pathlib import Path

BASE = Path('C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/website-marketing/pro/breeze/locales')

REPLACEMENTS = {
    'en': (
        'My research journey has also taken me into areas that few take seriously: reverse-engineering closed formats and systematizing descriptions of construction work using a resource model.',
        'Two other things have kept me busy: helping non-developers get into proprietary formats that were never meant to be opened, and finding a cleaner way to describe construction work through a resource model.',
    ),
    'de': (
        'Mein Forschungsweg hat mich auch in Bereiche gef\u00fchrt, die nur wenige ernst nehmen: das Reverse Engineering geschlossener Formate und die Systematisierung von Baubeschreibungen \u00fcber ein Ressourcenmodell.',
        'Zwei weitere Themen haben mich besch\u00e4ftigt: Nicht-Entwicklern den Zugang zu propriet\u00e4ren Formaten zu erm\u00f6glichen, die nie zum \u00d6ffnen gedacht waren, und einen saubereren Weg zu finden, Bauleistungen \u00fcber ein Ressourcenmodell zu beschreiben.',
    ),
    'ru': (
        'Моё исследовательское путешествие завело меня в области, к которым мало кто относится серьёзно: реверс-инжиниринг закрытых форматов и систематизация описаний строительных работ через ресурсную модель.',
        'Ещё два направления заняли много моего времени: помогать тем, кто не пишет код, открывать проприетарные форматы, никогда не предполагавшие открытия, и искать более чистый способ описывать строительные работы через ресурсную модель.',
    ),
}

for lang, (old, new) in REPLACEMENTS.items():
    p = BASE / f'{lang}.json'
    data = json.loads(p.read_text(encoding='utf-8'))
    para3 = data['voices']['para3']
    if old not in para3:
        print(f'!! {lang}: old phrase not found, skipping')
        continue
    data['voices']['para3'] = para3.replace(old, new)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'updated {lang}.json')
