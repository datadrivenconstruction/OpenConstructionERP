#!/usr/bin/env python3
"""‌⁠‍Backfill match_elements i18n keys across all 26 locales.

Inserts the new keys introduced by the /match-elements UX redesign:
project-context bar, session resume picker, settings rail, confidence
legend, trade filter, apply-to-BOQ flow, and a few group-row hints.

Idempotent: skips keys already present in a locale file.
Deprecated one-off: for new work use scripts/i18n.py (get/add/set/missing/rename/export/import).
"""

from __future__ import annotations

from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent.parent / "frontend" / "src" / "app" / "locales"

# Each entry maps locale → string. Locales not listed for a given key
# fall back to the "en" entry (i18next defaultValue handles it at runtime
# but we'd rather ship explicit translations).
TRANSLATIONS: dict[str, dict[str, str]] = {
    "match_elements.no_project_title": {
        "en": "No active project selected.",
        "de": "Kein aktives Projekt ausgewählt.",
        "ru": "Активный проект не выбран.",
        "es": "Ningún proyecto activo seleccionado.",
        "fr": "Aucun projet actif sélectionné.",
        "it": "Nessun progetto attivo selezionato.",
        "pt": "Nenhum projeto ativo selecionado.",
        "nl": "Geen actief project geselecteerd.",
        "sv": "Inget aktivt projekt valt.",
        "pl": "Nie wybrano aktywnego projektu.",
        "tr": "Aktif proje seçilmedi.",
        "ja": "アクティブなプロジェクトが選択されていません。",
        "ko": "활성 프로젝트가 선택되지 않았습니다.",
        "zh": "未选择活动项目。",
        "ar": "لم يتم تحديد مشروع نشط.",
    },
    "match_elements.no_project_hint": {
        "en": "Open the project picker in the header, or visit",
        "de": "Projektauswahl in der Kopfzeile öffnen, oder besuche",
        "ru": "Откройте выбор проекта в шапке или перейдите в",
        "es": "Abre el selector de proyectos en la cabecera o visita",
        "fr": "Ouvrez le sélecteur de projet dans l'en-tête, ou visitez",
        "it": "Apri il selettore di progetti nell'intestazione, o visita",
        "pt": "Abra o seletor de projetos no cabeçalho ou acesse",
        "ja": "ヘッダーでプロジェクトピッカーを開くか、",
        "ko": "헤더의 프로젝트 선택기를 열거나 방문",
        "zh": "在标题中打开项目选择器,或访问",
        "ar": "افتح محدد المشروع في الرأس، أو قم بزيارة",
    },
    "match_elements.active_project": {
        "en": "Active project",
        "de": "Aktives Projekt",
        "ru": "Активный проект",
        "es": "Proyecto activo",
        "fr": "Projet actif",
        "it": "Progetto attivo",
        "pt": "Projeto ativo",
        "nl": "Actief project",
        "sv": "Aktivt projekt",
        "pl": "Aktywny projekt",
        "tr": "Aktif proje",
        "ja": "アクティブプロジェクト",
        "ko": "활성 프로젝트",
        "zh": "活动项目",
        "ar": "المشروع النشط",
    },
    "match_elements.loading_sessions": {
        "en": "Loading sessions…",
        "de": "Sitzungen werden geladen…",
        "ru": "Загрузка сессий…",
        "es": "Cargando sesiones…",
        "fr": "Chargement des sessions…",
        "it": "Caricamento sessioni…",
        "pt": "Carregando sessões…",
        "ja": "セッションを読み込み中…",
        "ko": "세션 로딩 중…",
        "zh": "加载会话中…",
        "ar": "جارٍ تحميل الجلسات…",
    },
    "match_elements.no_prior_sessions": {
        "en": "No prior matching sessions for this project.",
        "de": "Keine vorherigen Matching-Sitzungen für dieses Projekt.",
        "ru": "Нет предыдущих сессий сопоставления для этого проекта.",
        "es": "No hay sesiones de coincidencia previas para este proyecto.",
        "fr": "Aucune session de correspondance précédente pour ce projet.",
        "it": "Nessuna sessione di matching precedente per questo progetto.",
        "pt": "Sem sessões de correspondência anteriores para este projeto.",
        "ja": "このプロジェクトの以前のマッチングセッションはありません。",
        "ko": "이 프로젝트에 대한 이전 매칭 세션이 없습니다.",
        "zh": "此项目没有以前的匹配会话。",
        "ar": "لا توجد جلسات مطابقة سابقة لهذا المشروع.",
    },
    "match_elements.session_default_name": {
        "en": "Session {{id}}",
        "de": "Sitzung {{id}}",
        "ru": "Сессия {{id}}",
        "es": "Sesión {{id}}",
        "fr": "Session {{id}}",
        "it": "Sessione {{id}}",
        "pt": "Sessão {{id}}",
        "ja": "セッション {{id}}",
        "ko": "세션 {{id}}",
        "zh": "会话 {{id}}",
        "ar": "جلسة {{id}}",
    },
    "match_elements.new_session": {
        "en": "New session",
        "de": "Neue Sitzung",
        "ru": "Новая сессия",
        "es": "Nueva sesión",
        "fr": "Nouvelle session",
        "it": "Nuova sessione",
        "pt": "Nova sessão",
        "nl": "Nieuwe sessie",
        "sv": "Ny session",
        "pl": "Nowa sesja",
        "tr": "Yeni oturum",
        "ja": "新規セッション",
        "ko": "새 세션",
        "zh": "新建会话",
        "ar": "جلسة جديدة",
    },
    "match_elements.legend_label": {
        "en": "Confidence",
        "de": "Konfidenz",
        "ru": "Уверенность",
        "es": "Confianza",
        "fr": "Confiance",
        "it": "Confidenza",
        "pt": "Confiança",
        "ja": "信頼度",
        "ko": "신뢰도",
        "zh": "置信度",
        "ar": "الثقة",
    },
    "match_elements.legend_high": {
        "en": "High",
        "de": "Hoch",
        "ru": "Высокая",
        "es": "Alta",
        "fr": "Élevée",
        "it": "Alta",
        "pt": "Alta",
        "nl": "Hoog",
        "sv": "Hög",
        "pl": "Wysoka",
        "tr": "Yüksek",
        "ja": "高",
        "ko": "높음",
        "zh": "高",
        "ar": "عالية",
    },
    "match_elements.legend_medium": {
        "en": "Medium",
        "de": "Mittel",
        "ru": "Средняя",
        "es": "Media",
        "fr": "Moyenne",
        "it": "Media",
        "pt": "Média",
        "nl": "Gemiddeld",
        "sv": "Medel",
        "pl": "Średnia",
        "tr": "Orta",
        "ja": "中",
        "ko": "보통",
        "zh": "中",
        "ar": "متوسطة",
    },
    "match_elements.legend_low": {
        "en": "Low",
        "de": "Niedrig",
        "ru": "Низкая",
        "es": "Baja",
        "fr": "Faible",
        "it": "Bassa",
        "pt": "Baixa",
        "nl": "Laag",
        "sv": "Låg",
        "pl": "Niska",
        "tr": "Düşük",
        "ja": "低",
        "ko": "낮음",
        "zh": "低",
        "ar": "منخفضة",
    },
    "match_elements.col.suggested": {
        "en": "Suggested cost",
        "de": "Vorgeschlagene Kosten",
        "ru": "Предложенная стоимость",
        "es": "Coste sugerido",
        "fr": "Coût suggéré",
        "it": "Costo suggerito",
        "pt": "Custo sugerido",
        "ja": "推奨コスト",
        "ko": "추천 비용",
        "zh": "建议成本",
        "ar": "التكلفة المقترحة",
    },
    "match_elements.subtractive_hint": {
        "en": "Subtractive / non-billable",
        "de": "Subtraktiv / nicht abrechenbar",
        "ru": "Вычитающий / не учитывается",
        "es": "Sustractivo / no facturable",
        "fr": "Soustractif / non facturable",
        "it": "Sottrattivo / non fatturabile",
        "pt": "Subtrativo / não faturável",
        "ja": "減算 / 非請求",
        "ko": "차감 / 비청구",
        "zh": "减项 / 不计费",
        "ar": "خصم / غير قابل للفوترة",
    },
    "match_elements.detail.opening_warning": {
        "en": "host has openings but gross == net (IFC export bug)",
        "de": "Host hat Öffnungen, aber brutto == netto (IFC-Export-Bug)",
        "ru": "у хоста есть проёмы, но брутто == нетто (баг IFC-экспорта)",
        "es": "el anfitrión tiene aberturas pero bruto == neto (bug de exportación IFC)",
        "fr": "l'hôte a des ouvertures mais brut == net (bug d'export IFC)",
        "it": "l'host ha aperture ma lordo == netto (bug export IFC)",
        "pt": "o host tem aberturas mas bruto == líquido (bug de exportação IFC)",
        "ja": "ホストに開口部があるが gross == net (IFC エクスポート不具合)",
        "ko": "호스트에 개구부가 있지만 gross == net (IFC 내보내기 버그)",
        "zh": "宿主存在洞口但毛量 == 净量(IFC 导出错误)",
        "ar": "المضيف به فتحات لكن الإجمالي == الصافي (خطأ تصدير IFC)",
    },
    "match_elements.detail.candidate_no_id": {
        "en": "Candidate has no DB id — cannot confirm",
        "de": "Kandidat hat keine DB-ID — Bestätigung nicht möglich",
        "ru": "У кандидата нет ID в БД — невозможно подтвердить",
        "es": "El candidato no tiene id de BD — no se puede confirmar",
        "fr": "Candidat sans id BD — impossible de confirmer",
        "it": "Il candidato non ha id DB — impossibile confermare",
        "pt": "Candidato sem id de BD — não é possível confirmar",
        "ja": "候補に DB ID がありません — 確定できません",
        "ko": "후보에 DB ID가 없습니다 — 확정할 수 없습니다",
        "zh": "候选项无数据库 ID — 无法确认",
        "ar": "المرشح ليس له معرف قاعدة بيانات — لا يمكن التأكيد",
    },
    "match_elements.detail.apply_total": {
        "en": "Total",
        "de": "Gesamt",
        "ru": "Итого",
        "es": "Total",
        "fr": "Total",
        "it": "Totale",
        "pt": "Total",
        "nl": "Totaal",
        "sv": "Totalt",
        "pl": "Razem",
        "tr": "Toplam",
        "ja": "合計",
        "ko": "합계",
        "zh": "合计",
        "ar": "الإجمالي",
    },
    "match_elements.auto_confirm_threshold": {
        "en": "Auto-confirm threshold",
        "de": "Auto-Bestätigungs-Schwellwert",
        "ru": "Порог авто-подтверждения",
        "es": "Umbral de auto-confirmación",
        "fr": "Seuil d'auto-confirmation",
        "it": "Soglia di auto-conferma",
        "pt": "Limite de auto-confirmação",
        "ja": "自動確定しきい値",
        "ko": "자동 확정 임계값",
        "zh": "自动确认阈值",
        "ar": "حد التأكيد التلقائي",
    },
    "match_elements.auto_confirm_help": {
        "en": "Suggested matches at or above this score auto-confirm.",
        "de": "Vorschläge auf oder über diesem Wert werden automatisch bestätigt.",
        "ru": "Предложения с этой оценкой и выше подтверждаются автоматически.",
        "es": "Las coincidencias sugeridas en o por encima de esta puntuación se auto-confirman.",
        "fr": "Les correspondances suggérées à ou au-dessus de ce score sont auto-confirmées.",
        "it": "Le corrispondenze suggerite a o sopra questo punteggio si auto-confermano.",
        "pt": "Correspondências sugeridas a ou acima desta pontuação são auto-confirmadas.",
        "ja": "このスコア以上の候補は自動的に確定します。",
        "ko": "이 점수 이상의 추천은 자동 확정됩니다.",
        "zh": "高于或等于此分数的建议匹配将自动确认。",
        "ar": "تأكيد المرشحين تلقائيًا عند هذه الدرجة أو أعلى.",
    },
    "match_elements.use_net": {
        "en": "Use net quantities (deduct openings)",
        "de": "Netto-Mengen verwenden (Öffnungen abziehen)",
        "ru": "Использовать чистые объёмы (вычитать проёмы)",
        "es": "Usar cantidades netas (deducir aberturas)",
        "fr": "Utiliser quantités nettes (déduire les ouvertures)",
        "it": "Usa quantità nette (sottrai aperture)",
        "pt": "Usar quantidades líquidas (subtrair aberturas)",
        "ja": "正味数量を使用 (開口部を控除)",
        "ko": "순 수량 사용 (개구부 차감)",
        "zh": "使用净量(扣除洞口)",
        "ar": "استخدام الكميات الصافية (خصم الفتحات)",
    },
    "match_elements.use_net_help": {
        "en": "Off = use gross. Default deducts IfcOpeningElement / IfcRelVoidsElement from host quantities.",
        "de": "Aus = brutto. Standard zieht IfcOpeningElement / IfcRelVoidsElement von Host-Mengen ab.",
        "ru": "Выкл. = брутто. По умолчанию IfcOpeningElement / IfcRelVoidsElement вычитаются из объёмов хоста.",
        "es": "Apagado = bruto. Por defecto deduce IfcOpeningElement / IfcRelVoidsElement de las cantidades del host.",
        "fr": "Désactivé = brut. Par défaut soustrait IfcOpeningElement / IfcRelVoidsElement des quantités hôtes.",
        "it": "Off = lordo. Default sottrae IfcOpeningElement / IfcRelVoidsElement dalle quantità host.",
        "pt": "Desligado = bruto. Por padrão deduz IfcOpeningElement / IfcRelVoidsElement das quantidades do host.",
        "ja": "オフ = 総量。デフォルトはホスト数量から IfcOpeningElement / IfcRelVoidsElement を控除。",
        "ko": "끄면 = 총량. 기본은 호스트 수량에서 IfcOpeningElement / IfcRelVoidsElement 차감.",
        "zh": "关闭 = 使用毛量。默认从宿主数量中扣除 IfcOpeningElement / IfcRelVoidsElement。",
        "ar": "إيقاف = إجمالي. الإعداد الافتراضي يخصم IfcOpeningElement / IfcRelVoidsElement من كميات المضيف.",
    },
    "match_elements.trade_filter": {
        "en": "Filter by trade",
        "de": "Nach Gewerk filtern",
        "ru": "Фильтр по специальности",
        "es": "Filtrar por especialidad",
        "fr": "Filtrer par corps d'état",
        "it": "Filtra per specialità",
        "pt": "Filtrar por especialidade",
        "ja": "工種で絞り込み",
        "ko": "공종으로 필터",
        "zh": "按专业筛选",
        "ar": "تصفية حسب التخصص",
    },
    "match_elements.action.apply": {
        "en": "Apply to BOQ ({{n}})",
        "de": "In LV übertragen ({{n}})",
        "ru": "Применить к Смете ({{n}})",
        "es": "Aplicar a BOQ ({{n}})",
        "fr": "Appliquer au BOQ ({{n}})",
        "it": "Applica al computo ({{n}})",
        "pt": "Aplicar ao BOQ ({{n}})",
        "ja": "BOQ に適用 ({{n}})",
        "ko": "BOQ에 적용 ({{n}})",
        "zh": "应用到工程量清单 ({{n}})",
        "ar": "تطبيق على BOQ ({{n}})",
    },
    "match_elements.action.apply_title": {
        "en": "Write confirmed matches to the project BOQ",
        "de": "Bestätigte Übereinstimmungen ins Projekt-LV schreiben",
        "ru": "Записать подтверждённые совпадения в смету проекта",
        "es": "Escribir coincidencias confirmadas en el BOQ del proyecto",
        "fr": "Écrire les correspondances confirmées dans le BOQ du projet",
        "it": "Scrivi le corrispondenze confermate nel computo del progetto",
        "pt": "Gravar correspondências confirmadas no BOQ do projeto",
        "ja": "確定済み候補をプロジェクト BOQ に書き込む",
        "ko": "확정된 매칭을 프로젝트 BOQ에 기록",
        "zh": "将已确认匹配写入项目工程量清单",
        "ar": "كتابة المطابقات المؤكدة في BOQ المشروع",
    },
    "match_elements.busy.applying": {
        "en": "Applying confirmed groups to BOQ…",
        "de": "Bestätigte Gruppen werden ins LV übertragen…",
        "ru": "Применение подтверждённых групп к смете…",
        "es": "Aplicando grupos confirmados al BOQ…",
        "fr": "Application des groupes confirmés au BOQ…",
        "it": "Applico gruppi confermati al computo…",
        "pt": "Aplicando grupos confirmados ao BOQ…",
        "ja": "確定グループを BOQ に適用中…",
        "ko": "확정된 그룹을 BOQ에 적용 중…",
        "zh": "正在将已确认分组应用到工程量清单…",
        "ar": "جارٍ تطبيق المجموعات المؤكدة على BOQ…",
    },
    "match_elements.alert.applied": {
        "en": "Created {{n}} BOQ positions · total {{total}} {{ccy}}",
        "de": "{{n}} LV-Positionen erstellt · Gesamt {{total}} {{ccy}}",
        "ru": "Создано позиций сметы: {{n}} · итого {{total}} {{ccy}}",
        "es": "Creadas {{n}} posiciones de BOQ · total {{total}} {{ccy}}",
        "fr": "{{n}} positions BOQ créées · total {{total}} {{ccy}}",
        "it": "Create {{n}} posizioni · totale {{total}} {{ccy}}",
        "pt": "Criadas {{n}} posições do BOQ · total {{total}} {{ccy}}",
        "ja": "{{n}} 件の BOQ ポジションを作成 · 合計 {{total}} {{ccy}}",
        "ko": "{{n}}개의 BOQ 항목 생성 · 합계 {{total}} {{ccy}}",
        "zh": "创建了 {{n}} 项工程量清单项 · 合计 {{total}} {{ccy}}",
        "ar": "تم إنشاء {{n}} بنود BOQ · الإجمالي {{total}} {{ccy}}",
    },
    "match_elements.visible_groups": {
        "en": "{{n}} visible",
        "de": "{{n}} sichtbar",
        "ru": "видимых: {{n}}",
        "es": "{{n}} visibles",
        "fr": "{{n}} visibles",
        "it": "{{n}} visibili",
        "pt": "{{n}} visíveis",
        "ja": "表示中 {{n}} 件",
        "ko": "{{n}}개 표시",
        "zh": "可见 {{n}} 项",
        "ar": "{{n}} مرئية",
    },
    "match_elements.selected_count": {
        "en": "{{n}} selected",
        "de": "{{n}} ausgewählt",
        "ru": "выбрано: {{n}}",
        "es": "{{n}} seleccionados",
        "fr": "{{n}} sélectionnés",
        "it": "{{n}} selezionati",
        "pt": "{{n}} selecionados",
        "ja": "{{n}} 件選択中",
        "ko": "{{n}}개 선택",
        "zh": "已选择 {{n}} 项",
        "ar": "{{n}} محددة",
    },
    "match_elements.trade.architectural": {
        "en": "Architectural",
        "de": "Architektur",
        "ru": "Архитектура",
        "es": "Arquitectura",
        "fr": "Architecture",
        "it": "Architettura",
        "pt": "Arquitetura",
        "ja": "建築",
        "ko": "건축",
        "zh": "建筑",
        "ar": "معماري",
    },
    "match_elements.trade.structural": {
        "en": "Structural",
        "de": "Tragwerk",
        "ru": "Конструкции",
        "es": "Estructural",
        "fr": "Structure",
        "it": "Strutturale",
        "pt": "Estrutural",
        "ja": "構造",
        "ko": "구조",
        "zh": "结构",
        "ar": "إنشائي",
    },
    "match_elements.trade.mep": {
        "en": "MEP",
        "de": "TGA",
        "ru": "Инженерные системы",
        "es": "MEP",
        "fr": "MEP",
        "it": "MEP",
        "pt": "MEP",
        "ja": "MEP",
        "ko": "MEP",
        "zh": "机电",
        "ar": "MEP",
    },
    "match_elements.trade.civil": {
        "en": "Civil",
        "de": "Tiefbau",
        "ru": "Земляные работы",
        "es": "Obra civil",
        "fr": "Génie civil",
        "it": "Opere civili",
        "pt": "Civil",
        "ja": "土木",
        "ko": "토목",
        "zh": "土建",
        "ar": "هندسة مدنية",
    },
    "match_elements.trade.spatial": {
        "en": "Spatial",
        "de": "Raum",
        "ru": "Пространство",
        "es": "Espacial",
        "fr": "Spatial",
        "it": "Spaziale",
        "pt": "Espacial",
        "ja": "空間",
        "ko": "공간",
        "zh": "空间",
        "ar": "مكاني",
    },
    "match_elements.trade.subtractive": {
        "en": "Voids",
        "de": "Aussparungen",
        "ru": "Пустоты",
        "es": "Vacíos",
        "fr": "Vides",
        "it": "Vuoti",
        "pt": "Vazios",
        "ja": "ボイド",
        "ko": "보이드",
        "zh": "空洞",
        "ar": "فراغات",
    },
    "match_elements.trade.annotation": {
        "en": "Annotation",
        "de": "Beschriftung",
        "ru": "Аннотация",
        "es": "Anotación",
        "fr": "Annotation",
        "it": "Annotazione",
        "pt": "Anotação",
        "ja": "注釈",
        "ko": "주석",
        "zh": "注释",
        "ar": "تعليق",
    },
    "match_elements.trade.other": {
        "en": "Other",
        "de": "Sonstiges",
        "ru": "Прочее",
        "es": "Otro",
        "fr": "Autre",
        "it": "Altro",
        "pt": "Outro",
        "nl": "Overig",
        "sv": "Övrigt",
        "pl": "Inne",
        "tr": "Diğer",
        "ja": "その他",
        "ko": "기타",
        "zh": "其他",
        "ar": "أخرى",
    },
    "match_elements.subtractive_badge": {
        "en": "void",
        "de": "Void",
        "ru": "пустота",
        "es": "vacío",
        "fr": "vide",
        "it": "vuoto",
        "pt": "vazio",
        "nl": "leegte",
        "sv": "tomrum",
        "pl": "pustka",
        "tr": "boşluk",
        "ja": "ボイド",
        "ko": "보이드",
        "zh": "空洞",
        "ar": "فراغ",
    },
}


# Locale → ISO mapping for fallback resolution.
# Locales not in TRANSLATIONS get the "en" string as fallback.
SUPPORTED_LOCALES = [
    "ar",
    "bg",
    "cs",
    "da",
    "de",
    "en",
    "es",
    "fi",
    "fr",
    "hi",
    "hr",
    "id",
    "it",
    "ja",
    "ko",
    "nl",
    "no",
    "pl",
    "pt",
    "ro",
    "ru",
    "sv",
    "th",
    "tr",
    "vi",
    "zh",
]


def value_for(locale: str, key: str) -> str:
    table = TRANSLATIONS[key]
    return table.get(locale) or table["en"]


def escape_for_ts_double_quoted(s: str) -> str:
    """‌⁠‍Escape backslash and double-quote for TS double-quoted string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def insert_keys(locale: str, path: Path) -> tuple[int, int]:
    # Read preserving line endings: Path.read_text has no newline= and would
    # translate CRLF to LF, which turns a one-key edit into a whole-file diff.
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    eol = "\r\n" if "\r\n" in text else "\n"
    inserted = 0
    skipped = 0

    # Find the last `match_elements.` line so we know where to insert.
    last_match_line_idx = -1
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if '"match_elements.' in line:
            last_match_line_idx = i

    if last_match_line_idx == -1:
        raise RuntimeError(f"{locale}: no match_elements.* keys found, cannot anchor insertion")

    # Detect the indentation by reading the existing line.
    ref_line = lines[last_match_line_idx]
    indent_len = len(ref_line) - len(ref_line.lstrip(" "))
    indent = " " * indent_len

    new_lines: list[str] = []
    for key in TRANSLATIONS:
        if f'"{key}"' in text:
            skipped += 1
            continue
        v = escape_for_ts_double_quoted(value_for(locale, key))
        new_lines.append(f'{indent}"{key}": "{v}",{eol}')
        inserted += 1

    if not new_lines:
        return (0, skipped)

    # The existing last line must end with comma so the new keys parse;
    # if it ends with `,\n` we're fine, otherwise we add a comma.
    existing = lines[last_match_line_idx]
    stripped = existing.rstrip()
    if not stripped.endswith(","):
        # Replace the trailing newline with `,\n`.
        if stripped.endswith('"'):
            lines[last_match_line_idx] = existing.rstrip() + "," + eol
        # If it doesn't end with `"` it might be `,` already.

    # The very last new key inserted must have NO trailing comma if the
    # block closes immediately after with `}`. But because we inserted
    # before existing closing braces and the last existing key already
    # has a comma (since other keys follow it in the source structure),
    # always-comma is safe. Verify by checking what comes after.

    # Simpler approach: check the character after the last_match_line to
    # determine whether a trailing comma is needed on our inserted block.
    # If next non-blank line is `}` and our last inserted line has a
    # comma, the trailing comma is fine in TS object literal syntax
    # (TS allows trailing commas).
    out_lines = lines[: last_match_line_idx + 1] + new_lines + lines[last_match_line_idx + 1 :]
    path.write_text("".join(out_lines), encoding="utf-8", newline="")
    return (inserted, skipped)


def main() -> None:
    grand_total_inserted = 0
    grand_total_skipped = 0
    for locale in SUPPORTED_LOCALES:
        path = LOCALES_DIR / f"{locale}.ts"
        if not path.exists():
            print(f"SKIP {locale}: {path} missing")
            continue
        inserted, skipped = insert_keys(locale, path)
        grand_total_inserted += inserted
        grand_total_skipped += skipped
        print(f"{locale}: +{inserted} new, {skipped} already present")
    print()
    print(f"TOTAL inserted: {grand_total_inserted}  skipped: {grand_total_skipped}")


if __name__ == "__main__":
    main()
