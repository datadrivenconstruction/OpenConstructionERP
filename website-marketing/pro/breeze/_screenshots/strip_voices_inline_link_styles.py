"""Strip inline style="..." from <a> tags inside voices.para1..pull keys
so the unified .voices-copy a CSS rule renders every link in one voice."""
import json, re
from pathlib import Path

BASE = Path('C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/website-marketing/pro/breeze/locales')

# Match <a ...> tag and remove its style="..." attribute.
STYLE_ATTR = re.compile(r'(<a\b[^>]*?)\s+style="[^"]*"', re.IGNORECASE)

# Keys whose values are HTML strings rendered into the founder note.
KEYS = ['para1', 'para2', 'para3', 'para4', 'pull']

for lang in ['en', 'de', 'ru']:
    p = BASE / f'{lang}.json'
    data = json.loads(p.read_text(encoding='utf-8'))
    voices = data['voices']
    changed = 0
    for k in KEYS:
        if k not in voices:
            continue
        before = voices[k]
        # Strip style attrs from <a> tags only (not other tags).
        after = before
        while True:
            new = STYLE_ATTR.sub(r'\1', after)
            if new == after:
                break
            after = new
        if after != before:
            voices[k] = after
            changed += 1
    if changed:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'updated {p.name}: stripped style attrs in {changed} keys')
    else:
        print(f'{p.name}: no inline styles found')
