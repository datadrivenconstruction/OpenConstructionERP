"""Update locale strings for release-ticker toggle (clamp-mode) and trim
the 'Reply within 1 business day' prefix from custom.form_meta now that
the user wants only the email shown."""
import json
from pathlib import Path

BASE = Path('C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/website-marketing/pro/breeze/locales')

UPDATES = {
    'en': {
        'voices': {
            'show_more_releases': 'Expand release notes',
            'show_less_releases': 'Collapse notes',
        },
        'custom': {
            'form_meta': 'info@datadrivenconstruction.io',
        },
    },
    'de': {
        'voices': {
            'show_more_releases': 'Release-Notizen erweitern',
            'show_less_releases': 'Notizen einklappen',
        },
        'custom': {
            'form_meta': 'info@datadrivenconstruction.io',
        },
    },
    'ru': {
        'voices': {
            'show_more_releases': 'Развернуть описания',
            'show_less_releases': 'Свернуть описания',
        },
        'custom': {
            'form_meta': 'info@datadrivenconstruction.io',
        },
    },
}

for lang, sections in UPDATES.items():
    p = BASE / f'{lang}.json'
    data = json.loads(p.read_text(encoding='utf-8'))
    for section, keys in sections.items():
        for k, v in keys.items():
            data.setdefault(section, {})[k] = v
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'updated {lang}.json')
