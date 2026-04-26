"""Rewrite custom.form_title + form_sub to honest solo-founder copy
   that filters for projects ready to allocate real resources."""
import json
from pathlib import Path

BASE = Path('C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/website-marketing/pro/breeze/locales')

UPDATES = {
    'en': {
        'form_title': "Tell me what you\u2019re after. <em>I read every message myself.</em>",
        'form_sub': "I work on this project solo, so I prioritize teams that are ready to allocate real resources to a pilot \u2014 budget, timeline, a sponsor. Send the brief and I\u2019ll get back to you within a few days.",
    },
    'de': {
        'form_title': "Sagen Sie, worum es Ihnen geht. <em>Ich lese jede Nachricht selbst.</em>",
        'form_sub': "Ich arbeite allein an diesem Projekt und bevorzuge daher Teams, die bereit sind, einem Pilot echte Ressourcen zuzuweisen \u2014 Budget, Zeitplan, einen Sponsor. Schicken Sie mir das Briefing und ich melde mich innerhalb weniger Tage zur\u00fcck.",
    },
    'ru': {
        'form_title': "Расскажите, что нужно. <em>Я читаю каждое сообщение сам.</em>",
        'form_sub': "Я работаю над этим проектом один, поэтому в первую очередь беру команды, готовые выделить реальные ресурсы на пилот \u2014 бюджет, сроки, ответственного. Пришлите бриф \u2014 отвечу в течение нескольких дней.",
    },
}

for lang, vals in UPDATES.items():
    p = BASE / f'{lang}.json'
    data = json.loads(p.read_text(encoding='utf-8'))
    data.setdefault('custom', {})['form_title'] = vals['form_title']
    data['custom']['form_sub'] = vals['form_sub']
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'updated {lang}.json')
