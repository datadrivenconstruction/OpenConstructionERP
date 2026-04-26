"""Replace 'We'll reply in 1 day' style time-promise in custom.form_title
with a no-time-promise human-acknowledgement line, in en/de/ru."""
import json
from pathlib import Path

BASE = Path('C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/website-marketing/pro/breeze/locales')

REPLACEMENTS = {
    'en': "Tell us what you're after. <em>A human will read it.</em>",
    'de': "Sagen Sie uns, was Sie suchen. <em>Ein Mensch liest jede Nachricht.</em>",
    'ru': "Расскажите, что вам нужно. <em>Каждое сообщение читает человек.</em>",
}

for lang, value in REPLACEMENTS.items():
    p = BASE / f'{lang}.json'
    data = json.loads(p.read_text(encoding='utf-8'))
    data.setdefault('custom', {})['form_title'] = value
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'updated {lang}.json')
