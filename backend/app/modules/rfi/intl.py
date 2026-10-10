# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""International, plain-language helpers for RFI (Request for Information) reporting.

This module is deliberately free of any database, ORM or FastAPI dependency:
every function here is pure and works on primitive values (ISO 8601 date
strings or ``datetime.date`` objects, plain integers and the status /
discipline vocabulary already used by the RFI model). That keeps the maths
that drives dashboards and PDF exports fully unit-testable and identical for
every deployment, in any country.

Design goals:

International
    No locale is hardcoded into any figure. Dates are read and written as
    ISO 8601 (``YYYY-MM-DD``). The response service-level agreement (SLA), in
    calendar days, is always a caller-supplied parameter, never baked in, so a
    team in one country can run a 10-day SLA and a team in another a 21-day
    SLA against the same code.

Clarity
    Status and discipline words localise into every language the RFI PDF
    renders (see :data:`app.modules.rfi.pdf_translations.SUPPORTED_PDF_LOCALES`)
    with an English fallback, so the printed status never stays English under a
    translated heading. Status words match the RFI screens. One-line explainers
    describe each concept in plain language, in English, German and Russian, so
    a site engineer understands every number in under a minute.

Well defined at the edges
    Division by zero, empty sets, negative counts and a response dated before
    the RFI was raised are all handled explicitly. Rates always stay inside
    ``[0, 1]`` (or ``[0, 100]`` as a percentage). A response that predates the
    request raises a clean :class:`ValueError` instead of returning a
    misleading negative number. No function returns ``NaN`` or infinity.

Explainability
    Each derived figure has a ``*_breakdown`` companion that returns the raw
    components (counts, totals, method note) so a reviewer can see exactly how
    a headline number was produced.
"""

from __future__ import annotations

from datetime import date, datetime

# ── Vocabulary (mirrors the RFI model and Pydantic schema) ────────────────────

# RFI lifecycle states, in the order the finite-state machine walks them.
RFI_STATUSES: tuple[str, ...] = ("draft", "open", "answered", "closed", "void")

# States that count as still needing an answer (the "open" workload).
OPEN_STATUSES: frozenset[str] = frozenset({"draft", "open"})

# States that count as answered (a response has been recorded).
ANSWERED_STATUSES: frozenset[str] = frozenset({"answered", "closed"})

# Engineering disciplines an RFI can be routed to. Free-form on the DB side;
# this is the constrained, user-visible set the frontend picker offers.
RFI_DISCIPLINES: tuple[str, ...] = (
    "architectural",
    "structural",
    "mep",
    "electrical",
    "plumbing",
    "civil",
    "landscape",
)

# Default response SLA in calendar days. Exposed as a sane starting value only;
# every helper takes the SLA as an explicit parameter so nothing is locale- or
# contract-specific by default.
DEFAULT_RESPONSE_SLA_DAYS: int = 14

# ── Localised labels (English fallback) ───────────────────────────────────────

_STATUS_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "draft": "Draft",
        "open": "Open",
        "answered": "Answered",
        "closed": "Closed",
        "void": "Void",
    },
    "de": {
        "draft": "Entwurf",
        "open": "Offen",
        "answered": "Beantwortet",
        "closed": "Geschlossen",
        "void": "Ungültig",
    },
    "ru": {
        "draft": "Черновик",
        "open": "Открыт",
        "answered": "Отвечен",
        "closed": "Закрыт",
        "void": "Аннулирован",
    },
    # The languages below read the words the RFI screens show, from the
    # frontend's rfi.status_* keys, so the printed form and the screen agree.
    "bg": {
        "draft": "Чернова",
        "open": "Отворено",
        "answered": "Отговорено",
        "closed": "Затворено",
        "void": "Анулирано",
    },
    "cs": {"draft": "Koncept", "open": "Otevřeno", "answered": "Zodpovězeno", "closed": "Uzavřeno", "void": "Neplatné"},
    "da": {"draft": "Kladde", "open": "Åben", "answered": "Besvaret", "closed": "Lukket", "void": "Ugyldig"},
    "el": {"draft": "Πρόχειρο", "open": "Ανοιχτό", "answered": "Απαντήθηκε", "closed": "Έκλεισε", "void": "Άκυρο"},
    "es": {"draft": "Borrador", "open": "Abierto", "answered": "Respondido", "closed": "Cerrado", "void": "Anulado"},
    "et": {"draft": "Mustand", "open": "Avatud", "answered": "Vastatud", "closed": "Suletud", "void": "Kehtetu"},
    "fi": {"draft": "Luonnos", "open": "Avoin", "answered": "Vastattu", "closed": "Suljettu", "void": "Mitätöity"},
    "fil": {"draft": "Borador", "open": "Bukas", "answered": "Nasagot", "closed": "Sarado", "void": "Walang Bisa"},
    "fr": {"draft": "Brouillon", "open": "Ouvert", "answered": "Répondu", "closed": "Clôturé", "void": "Annulé"},
    "hi": {"draft": "मसौदा", "open": "खुला", "answered": "उत्तरित", "closed": "बंद", "void": "अमान्य"},
    "hr": {"draft": "Nacrt", "open": "Otvoreno", "answered": "Odgovoreno", "closed": "Zatvoreno", "void": "Ništavno"},
    "hu": {
        "draft": "Piszkozat",
        "open": "Nyitott",
        "answered": "Megválaszolva",
        "closed": "Lezárva",
        "void": "Érvénytelen",
    },
    "id": {"draft": "Draf", "open": "Terbuka", "answered": "Terjawab", "closed": "Ditutup", "void": "Batal"},
    "it": {"draft": "Bozza", "open": "Aperto", "answered": "Risposto", "closed": "Chiuso", "void": "Nullo"},
    "ja": {"draft": "下書き", "open": "未対応", "answered": "回答済み", "closed": "クローズ", "void": "無効"},
    "kk": {"draft": "Жоба", "open": "Ашық", "answered": "Жауап берілді", "closed": "Жабылды", "void": "Күші жойылды"},
    "ko": {"draft": "초안", "open": "미결", "answered": "답변됨", "closed": "종료됨", "void": "무효"},
    "ky": {
        "draft": "Долбоор",
        "open": "Ачык",
        "answered": "Жооп берилди",
        "closed": "Жабылды",
        "void": "Күчүн жоготту",
    },
    "nl": {"draft": "Concept", "open": "Open", "answered": "Beantwoord", "closed": "Gesloten", "void": "Ongeldig"},
    "no": {"draft": "Utkast", "open": "Åpen", "answered": "Besvart", "closed": "Lukket", "void": "Ugyldig"},
    "pl": {
        "draft": "Wersja robocza",
        "open": "Otwarte",
        "answered": "Udzielono odpowiedzi",
        "closed": "Zamknięte",
        "void": "Nieważne",
    },
    "pt": {"draft": "Rascunho", "open": "Aberto", "answered": "Respondido", "closed": "Fechado", "void": "Anulado"},
    "ro": {"draft": "Ciornă", "open": "Deschis", "answered": "Răspuns", "closed": "Închis", "void": "Anulat"},
    "sv": {"draft": "Utkast", "open": "Öppen", "answered": "Besvarad", "closed": "Stängd", "void": "Ogiltig"},
    "th": {"draft": "ร่าง", "open": "เปิดอยู่", "answered": "ตอบแล้ว", "closed": "ปิดแล้ว", "void": "เป็นโมฆะ"},
    "tr": {"draft": "Taslak", "open": "Açık", "answered": "Yanıtlandı", "closed": "Kapalı", "void": "Geçersiz"},
    "uk": {
        "draft": "Чернетка",
        "open": "Відкрито",
        "answered": "Відповідь надано",
        "closed": "Закрито",
        "void": "Анульовано",
    },
    "uz": {
        "draft": "Qoralama",
        "open": "Ochiq",
        "answered": "Javob berilgan",
        "closed": "Yopilgan",
        "void": "Bekor qilingan",
    },
    "vi": {"draft": "Bản nháp", "open": "Đang mở", "answered": "Đã trả lời", "closed": "Đã đóng", "void": "Vô hiệu"},
    "zh": {"draft": "草稿", "open": "未关闭", "answered": "已回答", "closed": "已关闭", "void": "已作废"},
}

_DISCIPLINE_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "architectural": "Architectural",
        "structural": "Structural",
        "mep": "MEP",
        "electrical": "Electrical",
        "plumbing": "Plumbing",
        "civil": "Civil",
        "landscape": "Landscape",
    },
    "de": {
        "architectural": "Architektur",
        "structural": "Tragwerk",
        "mep": "Gebäudetechnik",
        "electrical": "Elektro",
        "plumbing": "Sanitär",
        "civil": "Tiefbau",
        "landscape": "Landschaft",
    },
    "ru": {
        "architectural": "Архитектурный",
        "structural": "Конструктивный",
        "mep": "Инженерные системы",
        "electrical": "Электрика",
        "plumbing": "Сантехника",
        "civil": "Гражданское строительство",
        "landscape": "Ландшафт",
    },
    # The RFI screens have no discipline words of their own yet (they fall back
    # to the English code), so these are the trade terms a construction reader
    # in each language uses for the design disciplines.
    "bg": {
        "architectural": "Архитектура",
        "structural": "Конструкции",
        "mep": "Инсталации",
        "electrical": "Електроинсталации",
        "plumbing": "ВиК",
        "civil": "Инфраструктура",
        "landscape": "Ландшафт",
    },
    "cs": {
        "architectural": "Architektura",
        "structural": "Stavební konstrukce",
        "mep": "Technická zařízení budov",
        "electrical": "Elektroinstalace",
        "plumbing": "Zdravotechnika",
        "civil": "Inženýrské stavby",
        "landscape": "Sadové úpravy",
    },
    "da": {
        "architectural": "Arkitektur",
        "structural": "Konstruktion",
        "mep": "Installationer",
        "electrical": "El",
        "plumbing": "VVS",
        "civil": "Anlæg",
        "landscape": "Landskab",
    },
    "el": {
        "architectural": "Αρχιτεκτονικά",
        "structural": "Στατικά",
        "mep": "Η/Μ εγκαταστάσεις",
        "electrical": "Ηλεκτρολογικά",
        "plumbing": "Υδραυλικά",
        "civil": "Έργα πολιτικού μηχανικού",
        "landscape": "Διαμόρφωση περιβάλλοντος",
    },
    "es": {
        "architectural": "Arquitectura",
        "structural": "Estructuras",
        "mep": "Instalaciones",
        "electrical": "Electricidad",
        "plumbing": "Instalaciones sanitarias",
        "civil": "Obra civil",
        "landscape": "Paisajismo",
    },
    "et": {
        "architectural": "Arhitektuur",
        "structural": "Konstruktsioonid",
        "mep": "Tehnosüsteemid",
        "electrical": "Elekter",
        "plumbing": "Veevarustus ja kanalisatsioon",
        "civil": "Rajatised",
        "landscape": "Maastikuarhitektuur",
    },
    "fi": {
        "architectural": "Arkkitehtuuri",
        "structural": "Rakennetekniikka",
        "mep": "Talotekniikka",
        "electrical": "Sähkö",
        "plumbing": "Putkitekniikka",
        "civil": "Maa- ja vesirakennus",
        "landscape": "Viherrakentaminen",
    },
    "fil": {
        "architectural": "Arkitektural",
        "structural": "Istruktural",
        "mep": "MEP",
        "electrical": "Elektrikal",
        "plumbing": "Plumbing",
        "civil": "Sibil",
        "landscape": "Landscape",
    },
    "fr": {
        "architectural": "Architecture",
        "structural": "Structure",
        "mep": "Lots techniques",
        "electrical": "Électricité",
        "plumbing": "Plomberie",
        "civil": "Génie civil",
        "landscape": "Paysage",
    },
    "hi": {
        "architectural": "वास्तुकला",
        "structural": "संरचना",
        "mep": "एमईपी",
        "electrical": "विद्युत",
        "plumbing": "प्लंबिंग",
        "civil": "सिविल",
        "landscape": "लैंडस्केप",
    },
    "hr": {
        "architectural": "Arhitektura",
        "structural": "Konstrukcija",
        "mep": "Instalacije",
        "electrical": "Elektroinstalacije",
        "plumbing": "Vodovod i odvodnja",
        "civil": "Niskogradnja",
        "landscape": "Krajobrazno uređenje",
    },
    "hu": {
        "architectural": "Építészet",
        "structural": "Tartószerkezet",
        "mep": "Épületgépészet",
        "electrical": "Villamos",
        "plumbing": "Víz- és csatornaszerelés",
        "civil": "Mélyépítés",
        "landscape": "Tájépítészet",
    },
    "id": {
        "architectural": "Arsitektur",
        "structural": "Struktur",
        "mep": "MEP",
        "electrical": "Elektrikal",
        "plumbing": "Plambing",
        "civil": "Sipil",
        "landscape": "Lanskap",
    },
    "it": {
        "architectural": "Architettura",
        "structural": "Strutture",
        "mep": "Impianti",
        "electrical": "Impianti elettrici",
        "plumbing": "Impianti idraulici",
        "civil": "Opere civili",
        "landscape": "Paesaggio",
    },
    "ja": {
        "architectural": "意匠",
        "structural": "構造",
        "mep": "設備",
        "electrical": "電気設備",
        "plumbing": "給排水衛生設備",
        "civil": "土木",
        "landscape": "造園",
    },
    "kk": {
        "architectural": "Сәулет",
        "structural": "Конструкциялар",
        "mep": "Инженерлік жүйелер",
        "electrical": "Электр",
        "plumbing": "Сантехника",
        "civil": "Азаматтық құрылыс",
        "landscape": "Ландшафт",
    },
    "ko": {
        "architectural": "건축",
        "structural": "구조",
        "mep": "설비",
        "electrical": "전기",
        "plumbing": "배관",
        "civil": "토목",
        "landscape": "조경",
    },
    "ky": {
        "architectural": "Архитектура",
        "structural": "Конструкциялар",
        "mep": "Инженердик тутумдар",
        "electrical": "Электр",
        "plumbing": "Сантехника",
        "civil": "Жарандык курулуш",
        "landscape": "Ландшафт",
    },
    "nl": {
        "architectural": "Architectuur",
        "structural": "Constructie",
        "mep": "Installaties",
        "electrical": "Elektrotechniek",
        "plumbing": "Sanitair",
        "civil": "Civiele techniek",
        "landscape": "Landschap",
    },
    "no": {
        "architectural": "Arkitektur",
        "structural": "Konstruksjon",
        "mep": "Tekniske fag",
        "electrical": "Elektro",
        "plumbing": "Rør og sanitær",
        "civil": "Anlegg",
        "landscape": "Landskap",
    },
    "pl": {
        "architectural": "Architektura",
        "structural": "Konstrukcja",
        "mep": "Instalacje budowlane",
        "electrical": "Instalacje elektryczne",
        "plumbing": "Instalacje sanitarne",
        "civil": "Inżynieria lądowa",
        "landscape": "Architektura krajobrazu",
    },
    "pt": {
        "architectural": "Arquitetura",
        "structural": "Estruturas",
        "mep": "Instalações prediais",
        "electrical": "Elétrica",
        "plumbing": "Hidráulica",
        "civil": "Obras civis",
        "landscape": "Paisagismo",
    },
    "ro": {
        "architectural": "Arhitectură",
        "structural": "Structuri",
        "mep": "Instalații",
        "electrical": "Instalații electrice",
        "plumbing": "Instalații sanitare",
        "civil": "Inginerie civilă",
        "landscape": "Peisagistică",
    },
    "sv": {
        "architectural": "Arkitektur",
        "structural": "Konstruktion",
        "mep": "Installationer",
        "electrical": "El",
        "plumbing": "VS",
        "civil": "Anläggning",
        "landscape": "Landskap",
    },
    "th": {
        "architectural": "สถาปัตยกรรม",
        "structural": "โครงสร้าง",
        "mep": "งานระบบ",
        "electrical": "ไฟฟ้า",
        "plumbing": "สุขาภิบาล",
        "civil": "โยธา",
        "landscape": "ภูมิสถาปัตยกรรม",
    },
    "tr": {
        "architectural": "Mimari",
        "structural": "Statik",
        "mep": "Elektromekanik tesisat",
        "electrical": "Elektrik",
        "plumbing": "Sıhhi tesisat",
        "civil": "İnşaat",
        "landscape": "Peyzaj",
    },
    "uk": {
        "architectural": "Архітектура",
        "structural": "Конструкції",
        "mep": "Інженерні системи",
        "electrical": "Електрика",
        "plumbing": "Сантехніка",
        "civil": "Цивільне будівництво",
        "landscape": "Ландшафт",
    },
    "uz": {
        "architectural": "Arxitektura",
        "structural": "Konstruksiyalar",
        "mep": "Muhandislik tizimlari",
        "electrical": "Elektr",
        "plumbing": "Santexnika",
        "civil": "Fuqarolik qurilishi",
        "landscape": "Landshaft",
    },
    "vi": {
        "architectural": "Kiến trúc",
        "structural": "Kết cấu",
        "mep": "Cơ điện",
        "electrical": "Điện",
        "plumbing": "Cấp thoát nước",
        "civil": "Hạ tầng",
        "landscape": "Cảnh quan",
    },
    "zh": {
        "architectural": "建筑",
        "structural": "结构",
        "mep": "机电",
        "electrical": "电气",
        "plumbing": "给排水",
        "civil": "土木",
        "landscape": "景观",
    },
}

# The trades a building services contractor routes an RFI by. The discipline
# column is free text, so these codes are stored even though the picker above
# does not offer them, and without a word of their own they printed in English
# on a Turkish form. Kept apart from ``_DISCIPLINE_LABELS`` because that table
# is the picker's set in every supported language; this one exists in the
# languages it has been written in and any other reads English. The codes and
# the Turkish words are the ones the submittal register uses
# (``submittals.tracking.DISCIPLINES``), so one project prints one vocabulary.
_TRADE_DISCIPLINE_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "mechanical": "Mechanical",
        "hvac": "HVAC",
        "fire_protection": "Fire protection",
        "lighting": "Lighting",
        "elv": "Low current",
        "bms": "Building automation",
    },
    "tr": {
        "mechanical": "Mekanik",
        "hvac": "İklimlendirme",
        "fire_protection": "Yangın tesisatı",
        "lighting": "Aydınlatma",
        "elv": "Zayıf akım",
        "bms": "Bina otomasyonu",
    },
}

# Other spellings of a trade code that reach the free-text column.
_DISCIPLINE_ALIASES: dict[str, str] = {
    "low_current": "elv",
    "building_automation": "bms",
    "fire": "fire_protection",
}

#: Languages the status and discipline words exist in; anything else reads
#: English. Derived from the table so the two cannot drift apart.
_SUPPORTED_LOCALES: frozenset[str] = frozenset(_STATUS_LABELS)

# One-line, plain-language explainers keyed by topic then locale.
_EXPLAINERS: dict[str, dict[str, str]] = {
    "rfi": {
        "en": (
            "An RFI (Request for Information) is a formal written question that asks the design "
            "team to clarify or confirm something before the work can proceed."
        ),
        "de": (
            "Ein RFI (Request for Information) ist eine formelle schriftliche Frage, die das "
            "Planungsteam bittet, etwas zu klären oder zu bestätigen, bevor die Arbeit weitergeht."
        ),
        "ru": (
            "RFI (запрос информации) - это официальный письменный вопрос, который просит проектную "
            "команду уточнить или подтвердить что-либо до продолжения работ."
        ),
    },
    "average_response_time": {
        "en": (
            "Average response time is the mean number of days between raising an RFI and receiving "
            "its official answer, measured over all answered RFIs in the set."
        ),
        "de": (
            "Die durchschnittliche Antwortzeit ist die mittlere Anzahl Tage zwischen dem Stellen "
            "eines RFI und der offiziellen Antwort, gemittelt über alle beantworteten RFIs."
        ),
        "ru": (
            "Среднее время ответа - это среднее число дней между подачей RFI и получением "
            "официального ответа, посчитанное по всем отвеченным RFI в наборе."
        ),
    },
    "overdue_rfi": {
        "en": (
            "An overdue RFI is one that is still open and whose answer is now later than its due "
            "date, so it is holding up the work and needs chasing."
        ),
        "de": (
            "Ein überfälliges RFI ist noch offen und seine Antwort liegt nun nach dem "
            "Fälligkeitsdatum, es hält also die Arbeit auf und muss nachgefasst werden."
        ),
        "ru": (
            "Просроченный RFI все еще открыт, а его ответ уже позже установленного срока, поэтому "
            "он задерживает работу и требует напоминания."
        ),
    },
    "ball_in_court": {
        "en": (
            "Ball in court names the party who is responsible for the next action on an RFI right "
            "now, so everyone can see who the answer is waiting on."
        ),
        "de": (
            "Ball in court benennt die Partei, die aktuell für den nächsten Schritt bei einem RFI "
            "verantwortlich ist, damit jeder sieht, auf wen die Antwort wartet."
        ),
        "ru": (
            "Ball in court указывает сторону, которая сейчас отвечает за следующее действие по RFI, "
            "чтобы всем было видно, от кого ждут ответа."
        ),
    },
}


def _normalise_locale(locale: str | None) -> str:
    """Return a supported locale code, falling back to English.

    Accepts region-tagged codes such as ``de-DE`` or ``ru_RU`` and reduces them
    to the base language. Anything unknown resolves to ``en`` so callers always
    get a usable label rather than an exception.
    """
    if not locale:
        return "en"
    base = locale.replace("_", "-").split("-", 1)[0].strip().lower()
    return base if base in _SUPPORTED_LOCALES else "en"


def _humanise_token(token: str) -> str:
    """Turn an unknown code into a readable English-style label as a last resort."""
    cleaned = token.replace("_", " ").replace("-", " ").strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else token


def coerce_date(value: date | str) -> date:
    """Parse an ISO 8601 date (or accept an existing :class:`date`).

    Accepts ``date``/``datetime`` objects and ISO 8601 strings, including full
    timestamps (only the calendar date is kept). Raises :class:`ValueError` for
    anything that is not a valid ISO 8601 date, so callers never silently work
    with a bad value.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError("date must be an ISO 8601 string or a date object")
    text = value.strip()
    if not text:
        raise ValueError("date string is empty")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        # ``date.fromisoformat`` accepts the plain ``YYYY-MM-DD`` form on every
        # supported Python; try it before giving up.
        return date.fromisoformat(text[:10])


# ── Localisation surface ──────────────────────────────────────────────────────


def localize_status(status: str, locale: str | None = "en") -> str:
    """Return the human label for an RFI status in the requested language.

    Falls back to English for an unsupported locale, and to a humanised form of
    the raw code for a status outside the known vocabulary, so the function
    never raises for display purposes.
    """
    key = (status or "").strip().lower()
    table = _STATUS_LABELS[_normalise_locale(locale)]
    if key in table:
        return table[key]
    english = _STATUS_LABELS["en"]
    return english.get(key, _humanise_token(status or ""))


def localize_discipline(discipline: str, locale: str | None = "en") -> str:
    """Return the human label for an RFI discipline in the requested language.

    Same fallback contract as :func:`localize_status`: unsupported locale falls
    back to English, unknown discipline falls back to a humanised code. The
    building services trades (mechanical, HVAC, fire protection and the rest
    of ``_TRADE_DISCIPLINE_LABELS``) are recognised as well, however the code
    was typed ("Fire protection", "fire-protection").
    """
    key = (discipline or "").strip().lower()
    language = _normalise_locale(locale)
    table = _DISCIPLINE_LABELS[language]
    if key in table:
        return table[key]
    trade = "_".join(key.replace("-", " ").split())
    trade = _DISCIPLINE_ALIASES.get(trade, trade)
    for labels in (
        _TRADE_DISCIPLINE_LABELS.get(language, {}),
        _DISCIPLINE_LABELS["en"],
        _TRADE_DISCIPLINE_LABELS["en"],
    ):
        if key in labels:
            return labels[key]
        if trade in labels:
            return labels[trade]
    return _humanise_token(discipline or "")


def explain(topic: str, locale: str | None = "en") -> str:
    """Return a one-line plain-language explainer for an RFI concept.

    Known topics: ``rfi``, ``average_response_time``, ``overdue_rfi`` and
    ``ball_in_court``. An unknown topic returns an empty string rather than
    raising, so a UI can safely request any key.
    """
    entry = _EXPLAINERS.get((topic or "").strip().lower())
    if entry is None:
        return ""
    loc = _normalise_locale(locale)
    return entry.get(loc, entry["en"])


# ── Core figures (pure, edge-safe) ────────────────────────────────────────────


def response_time_days(raised_on: date | str, responded_on: date | str) -> int:
    """Return whole calendar days between raising an RFI and its official answer.

    Both ends are ISO 8601 dates (or ``date`` objects). The result is the number
    of whole days from ``raised_on`` to ``responded_on``; a same-day answer is
    ``0``.

    A response dated before the RFI was raised is impossible and would produce a
    misleading negative figure, so it raises :class:`ValueError` instead. This
    guarantees the value is always ``>= 0``.
    """
    raised = coerce_date(raised_on)
    responded = coerce_date(responded_on)
    delta = (responded - raised).days
    if delta < 0:
        raise ValueError("responded_on is earlier than raised_on: response cannot precede the request")
    return delta


def average_response_time_days(response_times: list[int | float]) -> float | None:
    """Return the mean response time in days over a set of answered RFIs.

    ``response_times`` is a sequence of per-RFI response times in whole days
    (for example produced by :func:`response_time_days`). The average is rounded
    to one decimal place.

    Edge handling:

    * An empty set returns ``None`` (no answered RFIs, so there is nothing to
      average), which guards the division-by-zero case explicitly.
    * A negative response time is impossible and raises :class:`ValueError`.
    """
    values = list(response_times)
    if not values:
        return None
    for value in values:
        if value < 0:
            raise ValueError("response time cannot be negative")
    return round(sum(values) / len(values), 1)


def average_response_time_breakdown(response_times: list[int | float]) -> dict[str, object]:
    """Return the components behind :func:`average_response_time_days`.

    Exposes ``count``, ``total_days``, ``average_days`` and a ``method`` note so
    a reviewer can audit exactly how the headline average was derived.
    """
    values = list(response_times)
    average = average_response_time_days(values)
    return {
        "count": len(values),
        "total_days": sum(values) if values else 0,
        "average_days": average,
        "method": "sum of per-RFI response times in days divided by the number of answered RFIs",
    }


def sla_due_date(raised_on: date | str, sla_days: int) -> date:
    """Return the due date for an RFI given when it was raised and the SLA.

    The due date is ``raised_on`` plus ``sla_days`` calendar days. ``sla_days``
    must be zero or positive; a negative SLA is meaningless and raises
    :class:`ValueError`.
    """
    if sla_days < 0:
        raise ValueError("sla_days cannot be negative")
    from datetime import timedelta

    return coerce_date(raised_on) + timedelta(days=sla_days)


def is_overdue(
    due_date: date | str | None,
    reference_date: date | str,
    *,
    sla_days: int | None = None,
    raised_on: date | str | None = None,
) -> bool:
    """Return whether an RFI is overdue on ``reference_date``.

    An RFI is overdue when the reference date is strictly after its due date.
    "Due today" is therefore not yet overdue.

    The effective due date is resolved in this order:

    1. an explicit ``due_date`` when supplied, otherwise
    2. ``raised_on`` plus the parameterised ``sla_days`` when both are supplied.

    When neither can be resolved the RFI has no deadline to miss, so the result
    is ``False`` (never an exception). This keeps the SLA a caller-supplied
    parameter rather than a hardcoded assumption.
    """
    reference = coerce_date(reference_date)
    if due_date is not None:
        effective_due = coerce_date(due_date)
    elif raised_on is not None and sla_days is not None:
        effective_due = sla_due_date(raised_on, sla_days)
    else:
        return False
    return reference > effective_due


def open_answered_rate(
    open_count: int,
    answered_count: int,
    *,
    as_percent: bool = False,
) -> float:
    """Return the answered share of the open-plus-answered population.

    This is a resolution rate: of the RFIs that are either still open or already
    answered, what fraction has been answered. The result is clamped to
    ``[0.0, 1.0]`` (or ``[0.0, 100.0]`` when ``as_percent`` is set).

    Edge handling:

    * Both counts zero means there is no population to measure, so the rate is
      ``0.0`` (the division-by-zero guard), never ``NaN``.
    * A negative count is impossible and raises :class:`ValueError`.
    """
    if open_count < 0 or answered_count < 0:
        raise ValueError("counts cannot be negative")
    total = open_count + answered_count
    if total == 0:
        return 0.0
    rate = answered_count / total
    # Clamp defensively; with non-negative inputs this is always already in range.
    rate = min(1.0, max(0.0, rate))
    return round(rate * 100.0, 1) if as_percent else round(rate, 4)


def open_answered_breakdown(
    open_count: int,
    answered_count: int,
) -> dict[str, object]:
    """Return the components behind :func:`open_answered_rate`.

    Exposes the two input counts, their total, the fractional rate and the
    percentage form so the figure is fully auditable.
    """
    return {
        "open_count": open_count,
        "answered_count": answered_count,
        "total": open_count + answered_count,
        "rate": open_answered_rate(open_count, answered_count),
        "rate_percent": open_answered_rate(open_count, answered_count, as_percent=True),
        "method": "answered divided by (open + answered); zero population resolves to 0.0",
    }


def counts_by_status(statuses: list[str]) -> dict[str, int]:
    """Return a count of RFIs per status.

    Each entry in ``statuses`` is normalised (trimmed, lower-cased) before
    counting so mixed-case inputs collapse together. Unknown status values are
    counted as-is rather than dropped, so nothing is silently lost. An empty
    input returns an empty mapping.
    """
    counts: dict[str, int] = {}
    for raw in statuses:
        key = (raw or "").strip().lower()
        if not key:
            key = "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts


def status_distribution(statuses: list[str]) -> dict[str, object]:
    """Return counts by status plus derived totals for a dashboard tile.

    Combines :func:`counts_by_status` with the open / answered rollups and the
    resolution rate, so a caller gets one auditable object covering the whole
    status picture. Every figure here is derived only from the input list.
    """
    counts = counts_by_status(statuses)
    total = sum(counts.values())
    open_count = sum(counts.get(s, 0) for s in OPEN_STATUSES)
    answered_count = sum(counts.get(s, 0) for s in ANSWERED_STATUSES)
    return {
        "total": total,
        "by_status": counts,
        "open": open_count,
        "answered": answered_count,
        "resolution_rate": open_answered_rate(open_count, answered_count),
        "method": "counts grouped by normalised status; open and answered rolled up from the vocabulary sets",
    }
