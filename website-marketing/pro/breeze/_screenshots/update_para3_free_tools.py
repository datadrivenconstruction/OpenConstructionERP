"""Replace 'open-source tools' with 'free tools' (DE: 'kostenlose Werkzeuge',
RU: 'бесплатные инструменты') in voices.para3 across en/de/ru."""
import json
from pathlib import Path

BASE = Path('C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/website-marketing/pro/breeze/locales')

REPLACEMENTS = {
    'en': (
        'These efforts have resulted in open-source tools—',
        'These efforts have resulted in free tools—',
    ),
    'de': (
        'Diese Arbeit hat Open-Source-Werkzeuge hervorgebracht—',
        'Diese Arbeit hat kostenlose Werkzeuge hervorgebracht—',
    ),
    'ru': (
        'Результатом этих усилий стали open-source инструменты—',
        'Результатом этих усилий стали бесплатные инструменты—',
    ),
}

for lang, (old, new) in REPLACEMENTS.items():
    p = BASE / f'{lang}.json'
    data = json.loads(p.read_text(encoding='utf-8'))
    para3 = data['voices']['para3']
    if old not in para3:
        print(f'!! {lang}: phrase not found')
        continue
    data['voices']['para3'] = para3.replace(old, new)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'updated {lang}.json')
