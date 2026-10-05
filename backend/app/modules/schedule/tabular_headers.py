# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Vocabulary of the spreadsheet schedule import: headers, link types, units, flags.

Everything :mod:`app.modules.schedule.tabular_import` recognises in a user's
sheet lives here, so adding a language is a data change:

* :data:`HEADER_SYNONYMS` - per field, per language, the column headers that
  name it. The first entry of each language is the header the downloadable
  template writes (:data:`TEMPLATE_HEADERS`) and reads back as an exact match.
* :data:`RELATIONSHIP_TYPE_ALIASES` - the two-letter link types planning tools
  print in each language ("EA" is the German finish-to-start).
* :data:`DURATION_UNITS` - the unit words a duration or lag may carry.
* :data:`YES_WORDS` / :data:`NO_WORDS` - flag cell values.

Headers are compared in the BOQ importer's comparison form
(:func:`~app.modules.boq.importers.excel.normalise_label`): lowercased, accents
and bracketed parts dropped, punctuation folded to single spaces. Every table is
checked at import time for an entry that would read two ways, so a clash
between two languages fails loudly here instead of mapping a column at random.
"""

from __future__ import annotations

import difflib
import unicodedata
from dataclasses import dataclass
from typing import Final

from app.modules.boq.importers.excel import normalise_label

#: The fields a sheet column can map to, in template column order.
FIELDS: Final[tuple[str, ...]] = (
    "id",
    "name",
    "wbs",
    "outline_level",
    "start",
    "finish",
    "duration",
    "predecessors",
    "percent_complete",
    "milestone",
    "resource",
    "notes",
    "client_visible",
)

#: Languages the synonym table covers.
LANGUAGES: Final[tuple[str, ...]] = ("en", "de", "es", "fr", "ru", "pt", "it", "nl", "pl", "tr")

CONFIDENCE_EXACT: Final[float] = 1.0
CONFIDENCE_SYNONYM: Final[float] = 0.8
CONFIDENCE_FUZZY: Final[float] = 0.5
CONFIDENCE_NONE: Final[float] = 0.0

# fmt: off
HEADER_SYNONYMS: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "id": {
        "en": ("ID", "Activity ID", "Activity Code", "Task ID", "Code", "No.", "Number", "Ref"),
        "de": ("Nr.", "Vorgangsnummer", "Vorgangs-ID", "Kennung", "Lfd. Nr."),
        "es": ("Código", "Id", "Nº", "Número", "Código de actividad"),
        "fr": ("N°", "Code activité", "Identifiant", "Numéro"),
        "ru": ("№", "Код", "Код работы", "Номер"),
        "pt": ("Código", "Número", "Código da atividade"),
        "it": ("Codice", "N.", "Numero", "Codice attività"),
        "nl": ("Nr", "Activiteitcode", "Nummer"),
        "pl": ("Lp.", "Kod", "Numer", "Identyfikator"),
        "tr": ("Kod", "Sıra No", "Faaliyet Kodu"),
    },
    "name": {
        "en": ("Name", "Task Name", "Activity Name", "Activity", "Task"),
        "de": ("Vorgangsname", "Bezeichnung", "Vorgang", "Tätigkeit", "Aktivität"),
        "es": ("Nombre de tarea", "Nombre", "Actividad", "Tarea"),
        "fr": ("Nom de la tâche", "Nom", "Tâche", "Activité", "Désignation"),
        "ru": ("Наименование", "Название", "Название задачи", "Наименование работ", "Работа", "Задача"),
        "pt": ("Nome da tarefa", "Nome", "Atividade", "Tarefa"),
        "it": ("Nome attività", "Attività", "Compito"),
        "nl": ("Taaknaam", "Naam", "Activiteit", "Taak"),
        "pl": ("Nazwa zadania", "Nazwa", "Zadanie", "Czynność"),
        "tr": ("Görev Adı", "Ad", "Adı", "Faaliyet", "Görev", "İş Kalemi"),
    },
    "wbs": {
        "en": ("WBS", "WBS Code", "WBS Number", "Outline Number"),
        "de": ("PSP-Code", "PSP", "PSP-Element", "Projektstrukturplan", "Gliederungsnummer"),
        "es": ("EDT", "Código EDT", "Número de esquema"),
        "fr": ("Code WBS", "SDP", "Numéro hiérarchique"),
        "ru": ("Код СДР", "СДР", "ИСР", "Структурный номер"),
        "pt": ("EAP", "Código EAP", "Número da estrutura de tópicos"),
        "it": ("Codice WBS", "Numero struttura"),
        "nl": ("WBS-code", "Overzichtsnummer"),
        "pl": ("Kod WBS", "Numer konspektu"),
        "tr": ("İYA Kodu", "İYA", "İş Kırılım Yapısı"),
    },
    "outline_level": {
        "en": ("Outline Level", "Level", "Indent Level", "Indent"),
        "de": ("Gliederungsebene", "Ebene", "Stufe"),
        "es": ("Nivel de esquema", "Nivel"),
        "fr": ("Niveau hiérarchique", "Niveau"),
        "ru": ("Уровень структуры", "Уровень"),
        "pt": ("Nível da estrutura de tópicos", "Nível"),
        "it": ("Livello struttura", "Livello"),
        "nl": ("Overzichtsniveau", "Niveau"),
        "pl": ("Poziom konspektu", "Poziom"),
        "tr": ("Anahat Düzeyi", "Düzey", "Seviye"),
    },
    "start": {
        "en": ("Start", "Start Date", "Begin", "Planned Start"),
        "de": ("Anfang", "Beginn", "Anfangstermin", "Startdatum"),
        "es": ("Comienzo", "Inicio", "Fecha de inicio", "Fecha inicio"),
        "fr": ("Début", "Date de début"),
        "ru": ("Начало", "Дата начала"),
        "pt": ("Início", "Data de início"),
        "it": ("Inizio", "Data inizio"),
        "nl": ("Begindatum", "Begin", "Startdatum"),
        "pl": ("Rozpoczęcie", "Data rozpoczęcia", "Początek"),
        "tr": ("Başlangıç", "Başlangıç Tarihi", "Başlama"),
    },
    "finish": {
        "en": ("Finish", "End", "Finish Date", "End Date", "Planned Finish", "Due"),
        "de": ("Ende", "Endtermin", "Enddatum", "Fertigstellung"),
        "es": ("Fin", "Fecha de fin", "Fecha fin"),
        "fr": ("Fin", "Date de fin"),
        "ru": ("Окончание", "Дата окончания", "Конец", "Завершение"),
        "pt": ("Término", "Data de término", "Fim", "Conclusão"),
        "it": ("Fine", "Data fine"),
        "nl": ("Einddatum", "Einde", "Eind"),
        "pl": ("Zakończenie", "Data zakończenia", "Koniec"),
        "tr": ("Bitiş", "Bitiş Tarihi"),
    },
    "duration": {
        "en": ("Duration", "Duration (days)", "Days", "Dur", "Original Duration"),
        "de": ("Dauer", "Tage", "Arbeitstage"),
        "es": ("Duración", "Días"),
        "fr": ("Durée", "Jours"),
        "ru": ("Длительность", "Продолжительность", "Дни", "Дней"),
        "pt": ("Duração", "Dias"),
        "it": ("Durata", "Giorni"),
        "nl": ("Duur", "Dagen"),
        "pl": ("Czas trwania", "Dni"),
        "tr": ("Süre", "Gün"),
    },
    "predecessors": {
        "en": ("Predecessors", "Predecessor", "Depends On", "Dependencies", "Preds"),
        "de": ("Vorgänger", "Vorgaenger", "Abhängigkeiten"),
        "es": ("Predecesoras", "Predecesores", "Predecesora", "Dependencias"),
        "fr": ("Prédécesseurs", "Prédécesseur", "Antécédents", "Dépendances"),
        "ru": ("Предшественники", "Предшественник", "Предшествующие", "Зависимости"),
        "pt": ("Predecessoras", "Predecessores", "Antecessoras", "Dependências"),
        "it": ("Predecessori", "Predecessore", "Dipendenze"),
        "nl": ("Voorgangers", "Voorganger", "Afhankelijkheden"),
        "pl": ("Poprzedniki", "Poprzednik", "Zależności"),
        "tr": ("Öncüller", "Öncül", "Bağımlılıklar", "Önceki Faaliyetler"),
    },
    "percent_complete": {
        "en": ("% Complete", "Percent Complete", "Progress", "Progress (%)", "% Done"),
        "de": ("% Abgeschlossen", "Fortschritt", "Fertigstellungsgrad", "Erledigt"),
        "es": ("% Completado", "Porcentaje completado", "Avance", "Progreso"),
        "fr": ("% Achevé", "Pourcentage achevé", "Avancement", "Progression"),
        "ru": ("% Завершения", "Процент завершения", "Выполнено", "Готовность", "Прогресс"),
        "pt": ("% Concluída", "% Concluído", "Porcentagem concluída", "Progresso", "Avanço"),
        "it": ("% Completamento", "Percentuale completamento", "Avanzamento"),
        "nl": ("% Voltooid", "Percentage voltooid", "Voortgang"),
        "pl": ("% Ukończenia", "Procent ukończenia", "Postęp", "Zaawansowanie"),
        "tr": ("% Tamamlanan", "Tamamlanma Yüzdesi", "İlerleme"),
    },
    "milestone": {
        "en": ("Milestone", "Is Milestone"),
        "de": ("Meilenstein",),
        "es": ("Hito",),
        "fr": ("Jalon",),
        "ru": ("Веха", "Контрольная точка"),
        "pt": ("Marco",),
        "it": ("Pietra miliare",),
        "nl": ("Mijlpaal",),
        "pl": ("Kamień milowy",),
        "tr": ("Kilometre Taşı", "Dönüm Noktası"),
    },
    "resource": {
        "en": ("Resource", "Resources", "Resource Names", "Resource Name", "Crew", "Assigned To"),
        "de": ("Ressource", "Ressourcen", "Ressourcennamen", "Kolonne", "Gewerk"),
        "es": ("Recurso", "Recursos", "Nombres de los recursos", "Cuadrilla"),
        "fr": ("Ressource", "Ressources", "Noms ressources", "Équipe"),
        "ru": ("Ресурс", "Ресурсы", "Названия ресурсов", "Исполнитель", "Бригада"),
        "pt": ("Recurso", "Recursos", "Nomes dos recursos", "Equipe"),
        "it": ("Risorsa", "Risorse", "Nomi risorse", "Squadra"),
        "nl": ("Resource", "Resourcenamen", "Ploeg"),
        "pl": ("Zasób", "Zasoby", "Nazwy zasobów", "Brygada", "Wykonawca"),
        "tr": ("Kaynak", "Kaynaklar", "Kaynak Adları", "Ekip"),
    },
    "notes": {
        "en": ("Notes", "Note", "Comments", "Comment", "Description", "Remarks"),
        "de": ("Notizen", "Bemerkung", "Bemerkungen", "Kommentar", "Beschreibung", "Anmerkungen"),
        "es": ("Notas", "Comentarios", "Descripción", "Observaciones"),
        "fr": ("Remarques", "Commentaires", "Observations"),
        "ru": ("Примечание", "Примечания", "Комментарий", "Описание"),
        "pt": ("Notas", "Observações", "Comentários", "Descrição"),
        "it": ("Note", "Commenti", "Descrizione", "Osservazioni"),
        "nl": ("Notities", "Opmerkingen", "Omschrijving", "Beschrijving"),
        "pl": ("Uwagi", "Notatki", "Komentarz", "Opis"),
        "tr": ("Notlar", "Açıklama", "Yorum", "Not"),
    },
    "client_visible": {
        "en": ("Client Visible", "Visible to Client", "Show to Client", "Share with Client"),
        "de": ("Für Kunden sichtbar", "Kunde sichtbar", "Im Portal"),
        "es": ("Visible para el cliente", "Visible al cliente"),
        "fr": ("Visible par le client", "Visible client"),
        "ru": ("Видно заказчику", "Показывать заказчику"),
        "pt": ("Visível para o cliente", "Visível ao cliente"),
        "it": ("Visibile al cliente", "Visibile cliente"),
        "nl": ("Zichtbaar voor klant", "Klant zichtbaar"),
        "pl": ("Widoczne dla klienta", "Dla klienta"),
        "tr": ("Müşteriye Görünür", "Müşteri Görünür"),
    },
}

#: Headers the platform's own schedule CSV export writes; they read back exactly.
EXPORT_HEADERS: Final[dict[str, str]] = {
    "Activity Code": "id",
    "Name": "name",
    "WBS": "wbs",
    "Start": "start",
    "End": "finish",
    "Duration (days)": "duration",
    "Progress (%)": "percent_complete",
    "Predecessors": "predecessors",
}

# Words that turn a header into a different measurement of the same thing:
# "Actual Start", "Baseline Finish", "Remaining Duration", "Unique ID". A header
# carrying one is never matched by the fuzzy tier, only by an explicit synonym.
QUALIFIER_WORDS: Final[frozenset[str]] = frozenset({
    "actual", "baseline", "early", "late", "remaining", "unique", "total", "free", "float", "critical",
    "forecast", "variance", "ist", "basis", "basisplan", "fruhester", "spatester", "fruheste", "spateste",
    "real", "reel", "reelle", "base", "fact", "факт", "фактическое", "фактическая", "базовое", "базовая",
    "ранее", "раннее", "позднее", "effettivo", "effettiva", "werkelijke", "basislijn", "rzeczywiste",
    "rzeczywisty", "bazowe", "gercek", "temel", "cost", "costs", "kosten", "budget", "type", "status", "calendar",
})

# Duration and lag units, compact form (lowercase, no accents, spaces or dots).
DURATION_UNITS: Final[dict[str, str]] = {
    **dict.fromkeys((
        "d", "dy", "dys", "day", "days", "wd", "workday", "workdays", "workingday", "workingdays",
        "t", "tg", "tag", "tage", "at", "arbeitstag", "arbeitstage",
        "д", "дн", "день", "дня", "дней", "рд", "рабдн", "рабочихдней",
        "j", "jr", "jrs", "jour", "jours", "dia", "dias", "g", "gg", "giorno", "giorni",
        "dag", "dagen", "dni", "dzien", "gun",
    ), "day"),
    **dict.fromkeys((
        "w", "wk", "wks", "week", "weeks", "wo", "woche", "wochen", "нед", "неделя", "недели", "недель",
        "sem", "semaine", "semaines", "semana", "semanas", "sett", "settimana", "settimane",
        "weken", "tydz", "tydzien", "tygodnie", "tygodni", "hafta",
    ), "week"),
    **dict.fromkeys((
        "h", "hr", "hrs", "hour", "hours", "std", "stunde", "stunden", "ч", "час", "часа", "часов",
        "heure", "heures", "hora", "horas", "ora", "ore", "u", "uur", "godz", "godzina", "godziny",
        "godzin", "saat",
    ), "hour"),
    **dict.fromkeys((
        "ed", "eday", "edays", "ew", "ewk", "eweek", "eweeks", "eh", "ehr", "ehour", "ehours", "emin",
        "edy", "emo", "elapsed", "elapseddays", "calendardays", "cd", "kt", "kalendertag", "kalendertage",
        "кд", "кдн", "калдн", "календарныхдней",
    ), "elapsed"),
    **dict.fromkeys((
        "m", "min", "mins", "minute", "minutes", "mo", "mon", "mons", "month", "months", "monat", "monate",
        "мин", "мес", "месяц", "месяца", "месяцев", "mois", "mes", "meses", "mese", "mesi", "maand",
        "maanden", "mies", "miesiac", "miesiace", "ay", "dakika",
    ), "unsupported"),
}

#: Two-letter link types per language, mapped to the CPM type they mean.
RELATIONSHIP_TYPE_ALIASES: Final[dict[str, str]] = {
    # en
    "FS": "FS", "SS": "SS", "FF": "FF", "SF": "SF",
    # de: Ende-Anfang, Anfang-Anfang, Ende-Ende, Anfang-Ende
    "EA": "FS", "AA": "SS", "EE": "FF", "AE": "SF",
    # fr: fin-debut, debut-debut, fin-fin, debut-fin
    "FD": "FS", "DD": "SS", "DF": "SF",
    # es: fin-comienzo, comienzo-comienzo, fin-fin, comienzo-fin
    "FC": "FS", "CC": "SS", "CF": "SF",
    # pt: termino-inicio, inicio-inicio, termino-termino, inicio-termino
    "TI": "FS", "II": "SS", "TT": "FF", "IT": "SF",
    # it: fine-inizio, inizio-inizio, fine-fine, inizio-fine
    "FI": "FS", "IF": "SF",
    # nl: einde-begin, begin-begin, einde-einde, begin-einde
    "EB": "FS", "BB": "SS", "BE": "SF",
    # pl: zakonczenie-rozpoczecie, rozpoczecie-rozpoczecie, ...
    "ZR": "FS", "RR": "SS", "ZZ": "FF", "RZ": "SF",
    # ru: okonchanie-nachalo, nachalo-nachalo, okonchanie-okonchanie, nachalo-okonchanie
    "ОН": "FS", "НН": "SS", "ОО": "FF", "НО": "SF",
    "ON": "FS", "NN": "SS", "OO": "FF", "NO": "SF",
}

YES_WORDS: Final[frozenset[str]] = frozenset({
    "yes", "y", "true", "1", "x", "✓", "✔", "ja", "j", "wahr", "si", "s", "oui", "o", "vrai",
    "да", "д", "истина", "sim", "verdadeiro", "vero", "waar", "tak", "t", "prawda", "evet", "e", "dogru",
})
NO_WORDS: Final[frozenset[str]] = frozenset({
    "no", "n", "false", "0", "-", "nein", "falsch", "non", "faux", "нет", "н", "ложь", "nao", "falso",
    "nee", "onwaar", "nie", "falsz", "hayir", "h",
})
# fmt: on


def compact_word(text: str) -> str:
    """Lowercase, strip accents, and drop spaces, dots and apostrophes: ``"Jours."`` -> ``"jours"``."""
    decomposed = unicodedata.normalize("NFKD", str(text).strip().lower())
    kept = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    kept = kept.replace("ı", "i").replace("ł", "l").replace("ß", "ss")
    return "".join(ch for ch in kept if ch not in " .' \t")


@dataclass(frozen=True)
class HeaderMatch:
    """How one header cell reads: the field it names and how sure the reading is."""

    field: str | None
    confidence: float
    tier: str  # "exact" | "synonym" | "fuzzy" | "none"


def _build_header_index() -> tuple[dict[str, str], dict[str, str]]:
    """``(exact, synonym)`` maps from normalised header to field, refusing any clash."""
    exact: dict[str, str] = {}
    synonym: dict[str, str] = {}
    owner: dict[str, str] = {}

    def _claim(label: str, field: str, target: dict[str, str]) -> None:
        key = normalise_label(label)
        if not key:
            raise ValueError(f"header synonym {label!r} normalises to nothing")
        if owner.setdefault(key, field) != field:
            raise ValueError(f"header synonym {label!r} reads as both {owner[key]!r} and {field!r}")
        target[key] = field

    for field in FIELDS:
        _claim(field.replace("_", " "), field, exact)
        for words in HEADER_SYNONYMS[field].values():
            _claim(words[0], field, exact)
    for label, field in EXPORT_HEADERS.items():
        _claim(label, field, exact)
    for field in FIELDS:
        for words in HEADER_SYNONYMS[field].values():
            for label in words:
                if normalise_label(label) in exact:
                    # Claimed again only to catch a clash with another field.
                    _claim(label, field, exact)
                else:
                    _claim(label, field, synonym)
    return exact, synonym


def _check_tables() -> None:
    """Refuse a vocabulary entry that reads two ways."""
    if set(HEADER_SYNONYMS) != set(FIELDS):
        raise ValueError("HEADER_SYNONYMS must cover exactly FIELDS")
    for field, by_lang in HEADER_SYNONYMS.items():
        missing = set(LANGUAGES) - set(by_lang)
        if missing:
            raise ValueError(f"field {field!r} has no headers for {sorted(missing)}")
    clash = YES_WORDS & NO_WORDS
    if clash:
        raise ValueError(f"flag words read as both yes and no: {sorted(clash)}")
    for alias in RELATIONSHIP_TYPE_ALIASES:
        if len(alias) != 2 or alias.upper() != alias:
            raise ValueError(f"link type alias {alias!r} must be two upper-case letters")


_check_tables()
_EXACT_HEADERS, _SYNONYM_HEADERS = _build_header_index()

# Multi-character synonyms the fuzzy tier may find inside a longer header,
# longest (most specific) first.
_FUZZY_CANDIDATES: tuple[tuple[tuple[str, ...], str], ...] = tuple(
    sorted(
        ((tuple(key.split()), field) for key, field in {**_EXACT_HEADERS, **_SYNONYM_HEADERS}.items()),
        key=lambda item: (-len(item[0]), -len(" ".join(item[0]))),
    )
)


def match_header(text: object) -> HeaderMatch:
    """Read one header cell: exact (1.0), synonym (0.8), fuzzy (0.5) or nothing (0).

    The fuzzy tier takes a header that contains every word of a known header
    ("Start date planned" holds "start date") or misspells one closely
    ("Duraton"), and never one that carries a qualifier word such as
    "Actual" or "Baseline", because that column measures something else.
    """
    if text is None:
        return HeaderMatch(None, CONFIDENCE_NONE, "none")
    key = normalise_label(str(text))
    if not key:
        return HeaderMatch(None, CONFIDENCE_NONE, "none")
    if key in _EXACT_HEADERS:
        return HeaderMatch(_EXACT_HEADERS[key], CONFIDENCE_EXACT, "exact")
    if key in _SYNONYM_HEADERS:
        return HeaderMatch(_SYNONYM_HEADERS[key], CONFIDENCE_SYNONYM, "synonym")
    words = key.split()
    if any(word in QUALIFIER_WORDS for word in words):
        return HeaderMatch(None, CONFIDENCE_NONE, "none")
    word_set = set(words)
    for candidate, field in _FUZZY_CANDIDATES:
        if len(candidate) == 1:
            # A lone word only counts as the header's head noun, its last word:
            # "Task name" is a name, "Activity type" is not an activity.
            if len(candidate[0]) >= 3 and words[-1] == candidate[0]:
                return HeaderMatch(field, CONFIDENCE_FUZZY, "fuzzy")
        elif word_set.issuperset(candidate):
            return HeaderMatch(field, CONFIDENCE_FUZZY, "fuzzy")
    if len(key) >= 5:
        best_field, best_ratio = None, 0.0
        for known, field in {**_EXACT_HEADERS, **_SYNONYM_HEADERS}.items():
            if len(known) < 5:
                continue
            ratio = difflib.SequenceMatcher(None, key, known).ratio()
            if ratio > best_ratio:
                best_field, best_ratio = field, ratio
        if best_field is not None and best_ratio >= 0.88:
            return HeaderMatch(best_field, CONFIDENCE_FUZZY, "fuzzy")
    return HeaderMatch(None, CONFIDENCE_NONE, "none")


def known_header(text: str) -> str | None:
    """The field a header names by the exact or synonym tier only, for header-row search."""
    found = match_header(text)
    return found.field if found.tier in ("exact", "synonym") else None


# Month names in text dates, per language: full and abbreviated forms, and the
# genitive a date is written in where the language declines it (Russian and
# Polish: "4 maja"). Matched in compact form, so accents and a trailing dot do not matter.
# fmt: off
MONTH_NAMES: Final[dict[str, tuple[tuple[str, ...], ...]]] = {
    "en": (("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",),
           ("jun", "june"), ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
           ("oct", "october"), ("nov", "november"), ("dec", "december")),
    "de": (("jan", "januar", "jän", "jänner"), ("feb", "februar"), ("mär", "mrz", "märz"), ("apr", "april"),
           ("mai",), ("jun", "juni"), ("jul", "juli"), ("aug", "august"), ("sep", "sept", "september"),
           ("okt", "oktober"), ("nov", "november"), ("dez", "dezember")),
    "fr": (("janv", "janvier"), ("févr", "fév", "février"), ("mars",), ("avr", "avril"), ("mai",),
           ("juin",), ("juil", "juillet"), ("août", "aou"), ("sept", "septembre"), ("oct", "octobre"),
           ("nov", "novembre"), ("déc", "décembre")),
    "es": (("ene", "enero"), ("feb", "febrero"), ("mar", "marzo"), ("abr", "abril"), ("may", "mayo"),
           ("jun", "junio"), ("jul", "julio"), ("ago", "agosto"), ("sep", "sept", "set", "septiembre", "setiembre"),
           ("oct", "octubre"), ("nov", "noviembre"), ("dic", "diciembre")),
    "it": (("gen", "gennaio"), ("feb", "febbraio"), ("mar", "marzo"), ("apr", "aprile"), ("mag", "maggio"),
           ("giu", "giugno"), ("lug", "luglio"), ("ago", "agosto"), ("set", "sett", "settembre"),
           ("ott", "ottobre"), ("nov", "novembre"), ("dic", "dicembre")),
    "nl": (("jan", "januari"), ("feb", "februari"), ("mrt", "maart"), ("apr", "april"), ("mei",),
           ("jun", "juni"), ("jul", "juli"), ("aug", "augustus"), ("sep", "sept", "september"),
           ("okt", "oktober"), ("nov", "november"), ("dec", "december")),
    "pl": (("sty", "styczeń", "stycznia"), ("lut", "luty", "lutego"), ("mar", "marzec", "marca"),
           ("kwi", "kwiecień", "kwietnia"), ("maj", "maja"), ("cze", "czerwiec", "czerwca"),
           ("lip", "lipiec", "lipca"), ("sie", "sierpień", "sierpnia"), ("wrz", "wrzesień", "września"),
           ("paź", "październik", "października"), ("lis", "listopad", "listopada"),
           ("gru", "grudzień", "grudnia")),
    "pt": (("jan", "janeiro"), ("fev", "fevereiro"), ("mar", "março"), ("abr", "abril"), ("mai", "maio"),
           ("jun", "junho"), ("jul", "julho"), ("ago", "agosto"), ("set", "setembro"), ("out", "outubro"),
           ("nov", "novembro"), ("dez", "dezembro")),
    "ru": (("янв", "январь", "января"), ("фев", "февр", "февраль", "февраля"), ("мар", "март", "марта"),
           ("апр", "апрель", "апреля"), ("май", "мая"), ("июн", "июнь", "июня"), ("июл", "июль", "июля"),
           ("авг", "август", "августа"), ("сен", "сент", "сентябрь", "сентября"),
           ("окт", "октябрь", "октября"), ("ноя", "нояб", "ноябрь", "ноября"), ("дек", "декабрь", "декабря")),
}
# fmt: on


def _build_month_index() -> dict[str, int]:
    """Compact month word -> month number across every language, refusing a word that reads two ways."""
    index: dict[str, int] = {}
    for lang, months in MONTH_NAMES.items():
        if len(months) != 12:
            raise ValueError(f"{lang} must list twelve months")
        for number, words in enumerate(months, start=1):
            for word in words:
                key = compact_word(word)
                if index.setdefault(key, number) != number:
                    raise ValueError(f"month word {word!r} ({lang}) reads as both {index[key]} and {number}")
    return index


_MONTH_INDEX = _build_month_index()


def month_number(word: str) -> int | None:
    """1..12 for a month name or abbreviation in any listed language, else ``None``."""
    return _MONTH_INDEX.get(compact_word(word))


_UNIT_INDEX: dict[str, str] = {compact_word(word): kind for word, kind in DURATION_UNITS.items()}
_YES_INDEX: frozenset[str] = frozenset(compact_word(word) for word in YES_WORDS)
_NO_INDEX: frozenset[str] = frozenset(compact_word(word) for word in NO_WORDS)
if _YES_INDEX & _NO_INDEX:
    raise ValueError(f"flag words read as both yes and no: {sorted(_YES_INDEX & _NO_INDEX)}")


def unit_kind(word: str) -> str | None:
    """``"day"``, ``"week"``, ``"hour"``, ``"elapsed"`` or ``"unsupported"`` for a unit word, else ``None``."""
    return _UNIT_INDEX.get(compact_word(word))


def flag_value(text: object) -> bool | None:
    """Read a flag cell: ``True`` / ``False``, or ``None`` when the word is not a yes or a no."""
    if isinstance(text, bool):
        return text
    if isinstance(text, (int, float)):
        return None if text not in (0, 1) else bool(text)
    word = compact_word(str(text))
    if word in _YES_INDEX:
        return True
    if word in _NO_INDEX or not word:
        return False
    return None


def relationship_type(alias: str) -> str | None:
    """The CPM link type a (localised) two-letter alias names, case-insensitively."""
    return RELATIONSHIP_TYPE_ALIASES.get(alias.strip().upper())


#: Template header row per language: the first synonym of each field.
TEMPLATE_HEADERS: Final[dict[str, tuple[str, ...]]] = {
    lang: tuple(HEADER_SYNONYMS[field][lang][0] for field in FIELDS) for lang in LANGUAGES
}

#: The yes and no a template writes in its flag columns, per language.
TEMPLATE_YES_NO: Final[dict[str, tuple[str, str]]] = {
    "en": ("yes", "no"),
    "de": ("ja", "nein"),
    "es": ("sí", "no"),
    "fr": ("oui", "non"),
    "ru": ("да", "нет"),
    "pt": ("sim", "não"),
    "it": ("sì", "no"),
    "nl": ("ja", "nee"),
    "pl": ("tak", "nie"),
    "tr": ("evet", "hayır"),
}

#: Example activity names the template's sample rows carry, per language:
#: a phase, two tasks under it and a handover milestone.
TEMPLATE_EXAMPLE_NAMES: Final[dict[str, tuple[str, str, str, str]]] = {
    "en": ("Shell and core", "Excavation", "Foundations", "Foundations accepted"),
    "de": ("Rohbau", "Erdarbeiten", "Fundamente", "Abnahme Fundamente"),
    "es": ("Estructura", "Excavación", "Cimentación", "Cimentación aceptada"),
    "fr": ("Gros œuvre", "Terrassement", "Fondations", "Réception des fondations"),
    "ru": ("Каркас", "Земляные работы", "Фундаменты", "Приёмка фундаментов"),
    "pt": ("Estrutura", "Escavação", "Fundações", "Fundações aceitas"),
    "it": ("Struttura", "Scavi", "Fondazioni", "Collaudo fondazioni"),
    "nl": ("Ruwbouw", "Grondwerk", "Funderingen", "Oplevering funderingen"),
    "pl": ("Stan surowy", "Roboty ziemne", "Fundamenty", "Odbiór fundamentów"),
    "tr": ("Kaba inşaat", "Kazı", "Temeller", "Temel kabulü"),
}


__all__ = [
    "CONFIDENCE_EXACT",
    "CONFIDENCE_FUZZY",
    "CONFIDENCE_NONE",
    "CONFIDENCE_SYNONYM",
    "DURATION_UNITS",
    "EXPORT_HEADERS",
    "FIELDS",
    "HEADER_SYNONYMS",
    "LANGUAGES",
    "MONTH_NAMES",
    "NO_WORDS",
    "QUALIFIER_WORDS",
    "RELATIONSHIP_TYPE_ALIASES",
    "TEMPLATE_EXAMPLE_NAMES",
    "TEMPLATE_HEADERS",
    "TEMPLATE_YES_NO",
    "YES_WORDS",
    "HeaderMatch",
    "compact_word",
    "flag_value",
    "known_header",
    "match_header",
    "month_number",
    "relationship_type",
    "unit_kind",
]
