"""Replace the time-promise community.hero_desc copy with a no-promise
contribution-friendly line, in en/de/ru."""
import json
from pathlib import Path

BASE = Path('C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/website-marketing/pro/breeze/locales')

UPDATES = {
    'en': "Every issue, PR and roadmap item is public on GitHub. Open an issue, comment on what matters, or send a PR — contributions of any size are welcome.",
    'de': "Jedes Issue, jeder PR und jeder Roadmap-Eintrag ist auf GitHub öffentlich. Eröffnen Sie ein Issue, kommentieren Sie bestehende oder schicken Sie einen PR — Beiträge jeder Größe sind willkommen.",
    'ru': "Каждый issue, PR и пункт roadmap публичны на GitHub. Откройте issue, комментируйте существующие или присылайте PR — вклад любого размера приветствуется.",
}

for lang, value in UPDATES.items():
    p = BASE / f'{lang}.json'
    data = json.loads(p.read_text(encoding='utf-8'))
    data.setdefault('community', {})['hero_desc'] = value
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'updated {lang}.json')
