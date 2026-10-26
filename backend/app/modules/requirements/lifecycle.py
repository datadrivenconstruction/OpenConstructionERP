# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The six questions a requirement has to answer, and the words for them.

A requirement stored as an EAC triplet says *what* is required. On its own that
is a fact without a life: nobody knows who asked for it, at which point of the
job it applies, how anyone would prove it was met, or which priced work it
touches. Those are the questions a requirements cycle closes, and this module
holds the vocabularies for them.

Everything here is pure data and pure functions. No ORM, no database, no
``app.*`` import, so it unit-tests on any runner, exactly like
:mod:`app.modules.requirements.intl`.

Three deliberate design rules:

*Every controlled value is a neutral key, never a display word.* The database
stores ``detail``; a German screen renders "Ausführungsplanung" and a British
one "Technical Design". Storing the display word would make the data readable
in one country and untranslatable everywhere else.

*A mapping is allowed to be empty.* HOAI has a permit phase that RIBA does not
name separately, and RIBA opens with a strategic stage that HOAI does not pay
for. Forcing every spine phase into every national system would invent
equivalences that do not exist, so :data:`PHASE_SYSTEMS` may answer ``None``.

*Both vocabularies carry the same keys.* A project switching between the ISO
19650 wording and the neutral wording must not lose or gain a concept, only
rename one. :func:`vocabulary_term` guarantees a term either way.
"""

from __future__ import annotations

from app.core.i18n import catalogue_table

# ── The cycle ────────────────────────────────────────────────────────────────

#: The six questions, in the order a requirement acquires answers to them, each
#: paired with the ``Requirement`` field that answers it. ``what`` is answered
#: by the EAC triplet that was always there; the other five are the cycle.
CYCLE_QUESTIONS: tuple[tuple[str, str], ...] = (
    ("what", "entity"),
    ("why", "rationale"),
    ("who", "originator"),
    ("when", "phase"),
    ("how", "verification_method"),
    ("with_what", "position_links"),
)

#: The German construction industry states the same six as Was, Warum, Wer,
#: Wann, Wie, Womit. Kept as a comment rather than a lookup: it is the origin of
#: the model, not a language the model has to speak.

# ── Wann: the phase spine ────────────────────────────────────────────────────

#: Neutral project phases, earliest first. This is the spine every national
#: stage system maps onto, and the value actually stored on a requirement.
PHASE_SPINE: tuple[str, ...] = (
    "strategy",
    "brief",
    "concept",
    "design",
    "approval",
    "detail",
    "tender",
    "award",
    "construction",
    "handover",
    "operation",
)

#: Neutral words for the spine, for the majority of projects that run neither
#: HOAI nor RIBA. A project that runs one of those reads :data:`PHASE_SYSTEMS`
#: instead and sees its own official stage names.
PHASE_LABELS: dict[str, dict[str, str]] = catalogue_table(
    "requirements.phase_labels",
    (
        "strategy",
        "brief",
        "concept",
        "design",
        "approval",
        "detail",
        "tender",
        "award",
        "construction",
        "handover",
        "operation",
    ),
    by_key=True,
)

#: National stage systems keyed by spine phase. ``None`` means the system has no
#: separate stage for that phase, which is information, not a gap to fill.
#:
#: HOAI Leistungsphasen match the titles already carried by the DACH pack, so a
#: German user reads one set of words across the platform. RIBA stage numbers
#: follow the 2020 Plan of Work. ISO 19650 splits a project into a delivery
#: phase and an operational phase and does not subdivide further, so it answers
#: coarsely on purpose.
PHASE_SYSTEMS: dict[str, dict[str, str | None]] = {
    "hoai": {
        "strategy": None,
        "brief": "LP 1 Grundlagenermittlung",
        "concept": "LP 2 Vorplanung",
        "design": "LP 3 Entwurfsplanung",
        "approval": "LP 4 Genehmigungsplanung",
        "detail": "LP 5 Ausführungsplanung",
        "tender": "LP 6 Vorbereitung der Vergabe",
        "award": "LP 7 Mitwirkung bei der Vergabe",
        "construction": "LP 8 Objektüberwachung",
        "handover": "LP 8 Objektüberwachung",
        "operation": "LP 9 Objektbetreuung",
    },
    "riba": {
        "strategy": "Stage 0 Strategic Definition",
        "brief": "Stage 1 Preparation and Briefing",
        "concept": "Stage 2 Concept Design",
        "design": "Stage 3 Spatial Coordination",
        "approval": None,
        "detail": "Stage 4 Technical Design",
        "tender": "Stage 4 Technical Design",
        "award": None,
        "construction": "Stage 5 Manufacturing and Construction",
        "handover": "Stage 6 Handover",
        "operation": "Stage 7 Use",
    },
    "iso19650": {
        "strategy": "Delivery phase",
        "brief": "Delivery phase",
        "concept": "Delivery phase",
        "design": "Delivery phase",
        "approval": "Delivery phase",
        "detail": "Delivery phase",
        "tender": "Delivery phase",
        "award": "Delivery phase",
        "construction": "Delivery phase",
        "handover": "Delivery phase",
        "operation": "Operational phase",
    },
}

# ── Wie: how a requirement is proven met ─────────────────────────────────────

#: Verification methods. The first four are the classic set named by
#: ISO/IEC/IEEE 29148 for any engineering requirement; the last two are the
#: construction-specific ones this platform can actually run.
VERIFICATION_METHODS: tuple[str, ...] = (
    "inspection",
    "analysis",
    "demonstration",
    "test",
    "document_review",
    "model_check",
)

#: The one verification method the platform executes by itself, through the
#: BIM validator. Every other method ends in a human recording a result.
AUTOMATED_VERIFICATION: str = "model_check"

#: Words for the methods. Without these a German screen offers the reader
#: ``document_review``, which is a key, not a language.
VERIFICATION_LABELS: dict[str, dict[str, str]] = {
    "inspection": {"en": "Inspection", "de": "Sichtprüfung", "ru": "Осмотр"},
    "analysis": {"en": "Analysis", "de": "Berechnung", "ru": "Расчёт"},
    "demonstration": {"en": "Demonstration", "de": "Vorführung", "ru": "Демонстрация"},
    "test": {"en": "Test", "de": "Prüfung", "ru": "Испытание"},
    "document_review": {"en": "Document review", "de": "Dokumentenprüfung", "ru": "Проверка документов"},
    "model_check": {"en": "Model check", "de": "Modellprüfung", "ru": "Проверка модели"},
}

# ── Wer: who raised it ───────────────────────────────────────────────────────

#: Party roles a requirement can originate from. Deliberately the parties to a
#: construction project rather than job titles, which differ by country.
ORIGINATOR_ROLES: tuple[str, ...] = (
    "client",
    "designer",
    "contractor",
    "authority",
    "operator",
    "end_user",
)

#: Words for the party roles.
ORIGINATOR_ROLE_LABELS: dict[str, dict[str, str]] = {
    "client": {"en": "Client", "de": "Bauherr", "ru": "Заказчик"},
    "designer": {"en": "Designer", "de": "Planer", "ru": "Проектировщик"},
    "contractor": {"en": "Contractor", "de": "Auftragnehmer", "ru": "Подрядчик"},
    "authority": {"en": "Authority", "de": "Behörde", "ru": "Надзорный орган"},
    "operator": {"en": "Operator", "de": "Betreiber", "ru": "Эксплуатирующая организация"},
    "end_user": {"en": "End user", "de": "Nutzer", "ru": "Пользователь"},
}

# ── Vocabularies ─────────────────────────────────────────────────────────────

#: Terms whose wording changes with the vocabulary a project has chosen. Both
#: vocabularies must answer all of these; :func:`vocabulary_term` and the tests
#: hold them to it.
VOCABULARY_TERMS: tuple[str, ...] = (
    "requirement_set",
    "requirement",
    "deliverable",
    "originator",
    "phase",
    "verification",
    "acceptance",
)

VOCABULARY_ISO19650 = "iso19650"
VOCABULARY_NEUTRAL = "neutral"

#: Both vocabularies, term key to per-language label.
#:
#: The ISO 19650 column is the wording of the standard, which is why several of
#: its entries are longer and none of them are invented here. The neutral column
#: is for the majority of jobs that never adopted the standard and would not
#: recognise "information container" as a word for a drawing.
VOCABULARIES: dict[str, dict[str, dict[str, str]]] = {
    VOCABULARY_ISO19650: {
        "requirement_set": {
            "en": "Exchange Information Requirements",
            "de": "Austausch-Informationsanforderungen",
            "ru": "Требования к обмену информацией",
        },
        "requirement": {
            "en": "Information requirement",
            "de": "Informationsanforderung",
            "ru": "Информационное требование",
        },
        "deliverable": {
            "en": "Information container",
            "de": "Informationscontainer",
            "ru": "Информационный контейнер",
        },
        "originator": {"en": "Appointing party", "de": "Auftraggeber", "ru": "Назначающая сторона"},
        "phase": {"en": "Project stage", "de": "Projektphase", "ru": "Стадия проекта"},
        "verification": {"en": "Information verification", "de": "Informationsprüfung", "ru": "Проверка информации"},
        "acceptance": {"en": "Authorization", "de": "Freigabe", "ru": "Авторизация"},
    },
    VOCABULARY_NEUTRAL: {
        "requirement_set": {"en": "Requirement list", "de": "Anforderungsliste", "ru": "Перечень требований"},
        "requirement": {"en": "Requirement", "de": "Anforderung", "ru": "Требование"},
        "deliverable": {"en": "Deliverable", "de": "Lieferleistung", "ru": "Результат"},
        "originator": {"en": "Raised by", "de": "Gefordert von", "ru": "Кем заявлено"},
        "phase": {"en": "Phase", "de": "Phase", "ru": "Этап"},
        "verification": {"en": "Check", "de": "Prüfung", "ru": "Проверка"},
        "acceptance": {"en": "Sign-off", "de": "Abnahme", "ru": "Приёмка"},
    },
}

#: Vocabulary a project gets when it has not chosen one. Neutral, because the
#: standard's wording is precise for the projects that run it and opaque for the
#: ones that do not.
DEFAULT_VOCABULARY: str = VOCABULARY_NEUTRAL


# ── Lookups ──────────────────────────────────────────────────────────────────


def base_language(lang: str) -> str:
    """Language subtag of a locale code: ``es-CL`` to ``es``, ``de`` to ``de``.

    Case and separator are normalized, so ``pt_BR`` and ``PT-br`` both answer
    ``pt``.
    """
    return lang.replace("_", "-").split("-", 1)[0].lower()


def resolve_label(per_lang: dict[str, str], lang: str) -> str:
    """Pick a label for ``lang``, falling back regionally and then to English.

    The chain is exact match, then the base language, then English. Without the
    middle step every regional locale the platform ships - es-CL, es-CO, es-MX,
    pt-BR - would skip a perfectly good Spanish or Portuguese label and render
    English, because no catalog here is keyed by region.
    """
    exact = per_lang.get(lang)
    if exact:
        return exact
    base = per_lang.get(base_language(lang))
    if base:
        return base
    return per_lang["en"]


def vocabulary_term(term: str, vocabulary: str = DEFAULT_VOCABULARY, lang: str = "en") -> str:
    """Label for ``term`` in the given vocabulary and language.

    An unknown vocabulary falls back to the neutral one rather than raising, so
    a project row carrying a value from a future release still renders words.
    An unknown term is returned as itself, matching :mod:`intl`.
    """
    catalog = VOCABULARIES.get(vocabulary) or VOCABULARIES[DEFAULT_VOCABULARY]
    per_lang = catalog.get(term)
    if per_lang is None:
        return term
    return resolve_label(per_lang, lang)


def verification_label(method: str, lang: str = "en") -> str:
    """Localized name for a verification method, the key itself if unknown."""
    per_lang = VERIFICATION_LABELS.get(method)
    return resolve_label(per_lang, lang) if per_lang else method


def originator_role_label(role: str, lang: str = "en") -> str:
    """Localized name for a party role, the key itself if unknown."""
    per_lang = ORIGINATOR_ROLE_LABELS.get(role)
    return resolve_label(per_lang, lang) if per_lang else role


def phase_label(phase: str, lang: str = "en") -> str:
    """Localized neutral name for a spine phase, the key itself if unknown."""
    per_lang = PHASE_LABELS.get(phase)
    return resolve_label(per_lang, lang) if per_lang else phase


def phase_rank(phase: str) -> int:
    """Position of a phase on the spine (0 = strategy). Unknown sorts last."""
    try:
        return PHASE_SPINE.index(phase)
    except ValueError:
        return len(PHASE_SPINE)


def phase_in_system(phase: str, system: str) -> str | None:
    """Name of a spine phase in a national stage system.

    Answers ``None`` both when the system does not subdivide that far and when
    the system is unknown. Callers that need to tell those apart should check
    :data:`PHASE_SYSTEMS` directly.
    """
    return PHASE_SYSTEMS.get(system, {}).get(phase)


def is_verifiable(method: str | None) -> bool:
    """Whether a requirement carries a verification method we recognise."""
    return method in VERIFICATION_METHODS


def unanswered_questions(answers: dict[str, object]) -> tuple[str, ...]:
    """Which of the six questions this requirement has not answered yet.

    ``answers`` maps field name to value, so a caller passes whatever it has -
    an ORM row, a dict from an import, a draft. Empty strings, empty
    collections and ``None`` all count as unanswered; a zero or a ``False``
    does not, because those are answers.
    """
    missing: list[str] = []
    for question, field in CYCLE_QUESTIONS:
        value = answers.get(field)
        if value is None or value == "" or (isinstance(value, (list, tuple, set, dict)) and not value):
            missing.append(question)
    return tuple(missing)


def cycle_completeness(answers: dict[str, object]) -> float:
    """Share of the six questions answered, as a percent in [0, 100]."""
    answered = len(CYCLE_QUESTIONS) - len(unanswered_questions(answers))
    return round(answered / len(CYCLE_QUESTIONS) * 100.0, 2)


__all__ = [
    "AUTOMATED_VERIFICATION",
    "CYCLE_QUESTIONS",
    "DEFAULT_VOCABULARY",
    "ORIGINATOR_ROLES",
    "ORIGINATOR_ROLE_LABELS",
    "PHASE_LABELS",
    "PHASE_SPINE",
    "PHASE_SYSTEMS",
    "VERIFICATION_LABELS",
    "VERIFICATION_METHODS",
    "VOCABULARIES",
    "VOCABULARY_ISO19650",
    "VOCABULARY_NEUTRAL",
    "VOCABULARY_TERMS",
    "base_language",
    "cycle_completeness",
    "is_verifiable",
    "originator_role_label",
    "phase_in_system",
    "phase_label",
    "phase_rank",
    "resolve_label",
    "unanswered_questions",
    "verification_label",
    "vocabulary_term",
]
