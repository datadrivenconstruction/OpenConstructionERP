"""Repoint the second cad2data link ("available on GitHub" / equivalents) to
the DDC GitHub org so the two adjacent links don't duplicate the same target."""
import json, re
from pathlib import Path

BASE = Path('C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/website-marketing/pro/breeze/locales')

OLD = 'https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN'
NEW = 'https://github.com/datadrivenconstruction'

# In each locale, the SECOND occurrence of OLD inside para3 is "available on GitHub" / equivalent.
for lang in ['en', 'de', 'ru']:
    p = BASE / f'{lang}.json'
    data = json.loads(p.read_text(encoding='utf-8'))
    para3 = data['voices']['para3']
    # Replace only the SECOND occurrence.
    pieces = para3.split(OLD)
    if len(pieces) >= 3:
        # Reassemble, replacing the second separator with NEW.
        new_para3 = pieces[0] + OLD + pieces[1] + NEW + OLD.join(pieces[2:])
        data['voices']['para3'] = new_para3
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'updated {p.name}')
    else:
        print(f'{p.name}: fewer than 2 occurrences ({len(pieces) - 1})')
