"""Tighten para3 closing sentence + simplify para4 (drop the redundant
'10 years' lead-in that already exists earlier in para3)."""
import json
from pathlib import Path

BASE = Path('C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/website-marketing/pro/breeze/locales')

PARA3_OLD_TAIL = {
    'en': 'All of this was a necessary step toward the idea I\u2019ve been pursuing for the past decade\u2014creating an open-source ERP for the construction industry.',
    'de': 'All dies war ein notwendiger Schritt hin zu der Idee, die ich seit einem Jahrzehnt verfolge\u2014ein Open-Source-ERP f\u00fcr das Bauwesen.',
    'ru': 'Всё это было необходимым шагом к идее, которую я несу уже десять лет—создать open-source ERP для строительной отрасли.',
}

PARA3_NEW_TAIL = {
    'en': 'All of this was a necessary step toward an idea I\u2019ve been pursuing for the past decade \u2014 an open-source modular ERP for the construction industry.',
    'de': 'All dies war ein notwendiger Schritt hin zu einer Idee, die ich seit zehn Jahren verfolge \u2014 einem modularen Open-Source-ERP f\u00fcr die Baubranche.',
    'ru': 'Всё это было необходимым шагом к идее, которую я преследую последние десять лет \u2014 модульной open-source ERP для строительной отрасли.',
}

PARA4_NEW = {
    'en': "The recent generation of AI tooling finally made it feasible to consolidate that work \u2014 methodology, data models, and prior implementations \u2014 into a single platform. It\u2019s now public and open source.",
    'de': "Die j\u00fcngste Generation an KI-Werkzeugen hat es endlich erm\u00f6glicht, diese Arbeit \u2014 Methodik, Datenmodelle und fr\u00fchere Implementierungen \u2014 in einer einzigen Plattform zu b\u00fcndeln. Sie ist jetzt \u00f6ffentlich und Open Source.",
    'ru': "Появление нового поколения AI-инструментов наконец позволило свести эту работу \u2014 методологию, модели данных и предыдущие реализации \u2014 в единую платформу. Сегодня она публична и open-source.",
}

for lang in ('en', 'de', 'ru'):
    p = BASE / f'{lang}.json'
    data = json.loads(p.read_text(encoding='utf-8'))
    para3 = data['voices']['para3']
    old_tail = PARA3_OLD_TAIL[lang]
    if old_tail in para3:
        data['voices']['para3'] = para3.replace(old_tail, PARA3_NEW_TAIL[lang])
        print(f'{lang}: para3 tail replaced')
    else:
        print(f'!! {lang}: para3 old tail NOT found')
    data['voices']['para4'] = PARA4_NEW[lang]
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'updated {lang}.json')
