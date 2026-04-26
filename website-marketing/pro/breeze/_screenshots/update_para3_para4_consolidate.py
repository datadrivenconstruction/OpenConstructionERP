"""Drop the closing sentence of para3 and replace para4 with a tighter,
3-sentence version. Updates en/de/ru locale files."""
import json
from pathlib import Path

BASE = Path('C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/website-marketing/pro/breeze/locales')

PARA3_TAIL = {
    'en': ' Those who have asked me over the past ten years what tools I was developing inevitably heard my ideas about creating an open-source modular ERP system.',
    'de': ' Diejenigen, die mich in den letzten zehn Jahren fragten, woran ich arbeite, hörten unweigerlich meine Gedanken zu einem modularen Open-Source-ERP-System.',
    'ru': ' Те, кто спрашивал меня последние десять лет, какие инструменты я разрабатываю, неизбежно слышали мои идеи о создании открытой модульной ERP-системы.',
}

NEW_PARA4 = {
    'en': "I’ve been working toward an open-source modular ERP for construction for about ten years. The recent generation of AI tooling made it feasible to consolidate that decade of work — methodology, data models, and prior implementations — into a single platform. It’s now public and open source.",
    'de': "Ich arbeite seit etwa zehn Jahren auf ein modulares Open-Source-ERP für die Baubranche hin. Die jüngste Generation an KI-Werkzeugen hat es möglich gemacht, dieses Jahrzehnt an Arbeit — Methodik, Datenmodelle und frühere Implementierungen — in einer einzigen Plattform zu bündeln. Sie ist jetzt öffentlich und Open Source.",
    'ru': "Я около десяти лет шёл к идее модульной open-source ERP для строительной отрасли. Появление нового поколения AI-инструментов позволило свести этот десятилетний задел — методологию, модели данных и предыдущие реализации — в единую платформу. Сегодня она публична и open-source.",
}

for lang in ('en', 'de', 'ru'):
    p = BASE / f'{lang}.json'
    data = json.loads(p.read_text(encoding='utf-8'))
    para3 = data['voices']['para3']
    tail = PARA3_TAIL[lang]
    if para3.endswith(tail):
        data['voices']['para3'] = para3[: -len(tail)]
        print(f'{lang}: stripped para3 tail')
    else:
        print(f'!! {lang}: para3 tail not found at end')
    data['voices']['para4'] = NEW_PARA4[lang]
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'updated {lang}.json')
