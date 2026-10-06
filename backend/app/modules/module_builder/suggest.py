# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Suggestions by rule: what a module could also do, read off its own words.

The wizard proposes links to other parts of the platform and extra functions
(status, deadline, export, comments). With an assistant connected it proposes
them too, but the manual path and the templates must get the same experience
without one, so this module does it deterministically: the same spec gives the
same suggestions, in the same order, every time.

It reads field names, field labels and the module's names, in any of the
languages listed in :data:`LANGUAGES`. The keyword tables below are data, kept
together so a translator can extend them without reading the matcher.

How a keyword matches (see :func:`_matches`):

- ``word`` matches a whole word: ``due`` matches "Due date" but not "Dues".
- ``stem*`` matches a word starting with it: ``contract*`` matches
  "Contracts" and "Contract no." but not "Subcontract". Inflected languages
  (ru, uk, pl) are written as stems for that reason.
- ``*part*`` matches inside a word, for compounding languages: German
  ``*frist*`` matches "Abgabefrist".
- A keyword with a space matches those words in sequence, the last one with
  the same ``*`` rule.
- A keyword in Chinese or Japanese script matches anywhere in the text: those
  scripts do not put spaces between words.

A word that matches a ``NEGATIVE`` entry for a concept never counts for it:
"Contractor" is a company, not a contract.

Nothing here touches a spec. Each suggestion carries the patch that applying
it would make, and the frontend applies it only when a person ticks it. Every
suggestion leaves a valid spec when it is ticked on its own, and so do all of
them ticked at once ("Accept all suggested"): a link field gets a name whose
index fits PostgreSQL's limit, and links stop where the field limit is.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable, Iterable
from typing import Any

from pydantic import ValidationError

from app.modules.module_builder.links import LINK_TARGETS
from app.modules.module_builder.schemas import Suggestion, SuggestionPatch
from app.modules.module_builder.spec import (
    MAX_FIELDS,
    MAX_IDENTIFIER_BYTES,
    STATUS_COLUMN,
    DueFeature,
    FieldSpec,
    ModuleSpec,
    StateSpec,
    StatusFeature,
)

logger = logging.getLogger(__name__)

LANGUAGES = ("en", "de", "fr", "es", "it", "pt", "nl", "pl", "ru", "uk", "tr", "zh", "ja")

# ── keyword tables ──────────────────────────────────────────────────────────
#
# concept -> language -> keywords. A concept is a link target or "due".

KEYWORDS: dict[str, dict[str, tuple[str, ...]]] = {
    "contract": {
        "en": ("contract*", "agreement*"),
        "de": ("vertrag*", "verträge*", "*vertrag"),
        "fr": ("contrat*",),
        "es": ("contrato*",),
        "it": ("contratt*",),
        "pt": ("contrato*",),
        "nl": ("contract*", "overeenkomst*"),
        "pl": ("umow*", "umów*", "kontrakt*"),
        "ru": ("договор*", "контракт*"),
        "uk": ("договір*", "договор*", "контракт*"),
        "tr": ("sözleşme*", "kontrat*"),
        "zh": ("合同", "契约"),
        "ja": ("契約",),
    },
    "contact": {
        "en": ("contact*", "supplier*", "vendor*", "subcontractor*", "client*", "customer*"),
        "de": ("kontakt*", "lieferant*", "nachunternehmer*", "subunternehmer*", "kunde*", "auftraggeber*"),
        "fr": ("contact*", "fournisseur*", "sous-traitant*", "client*"),
        "es": ("contacto*", "proveedor*", "subcontratista*", "cliente*"),
        "it": ("contatt*", "fornitor*", "subappaltator*", "client*", "committent*"),
        "pt": ("contato*", "contacto*", "fornecedor*", "subempreiteir*", "cliente*"),
        "nl": ("contact*", "leverancier*", "onderaannemer*", "klant*", "opdrachtgever*"),
        "pl": ("kontakt*", "dostawc*", "podwykonawc*", "klient*", "zamawiając*"),
        "ru": ("контакт*", "поставщик*", "субподрядчик*", "подрядчик*", "заказчик*", "клиент*"),
        "uk": ("контакт*", "постачальник*", "субпідрядник*", "підрядник*", "замовник*", "клієнт*"),
        "tr": ("iletişim*", "tedarikçi*", "taşeron*", "müşteri*", "yüklenici*"),
        "zh": ("联系人", "供应商", "分包商", "客户"),
        "ja": ("連絡先", "取引先", "協力会社", "顧客", "業者"),
    },
    "schedule_activity": {
        "en": ("activity", "activities", "task*", "wbs"),
        "de": ("vorgang*", "vorgäng*", "aktivität*", "aufgabe*"),
        "fr": ("activité*", "tâche*"),
        "es": ("actividad*", "tarea*"),
        "it": ("attività", "compito", "compiti"),
        "pt": ("atividade*", "tarefa*"),
        "nl": ("activiteit*", "taak", "taken"),
        "pl": ("czynnoś*", "zadani*"),
        "ru": ("задач*", "работа графика", "позиция графика"),
        "uk": ("завдан*", "робота графіка", "позиція графіка"),
        "tr": ("aktivite*", "faaliyet*", "görev*"),
        "zh": ("任务", "工序", "作业"),
        "ja": ("工程", "タスク", "作業"),
    },
    "document": {
        "en": ("document*", "drawing*", "attachment*"),
        "de": ("dokument*", "zeichnung*", "anhang", "anhänge", "unterlage*"),
        "fr": ("document*", "dessin*", "pièce jointe*", "pièces jointes"),
        "es": ("documento*", "plano", "planos", "adjunto*"),
        "it": ("document*", "disegn*", "allegat*"),
        "pt": ("documento*", "desenho*", "anexo*"),
        "nl": ("document*", "tekening*", "bijlage*"),
        "pl": ("dokument*", "rysun*", "załącznik*"),
        "ru": ("документ*", "чертеж*", "чертёж*", "вложени*"),
        "uk": ("документ*", "креслен*", "вкладен*"),
        "tr": ("belge*", "doküman*", "çizim*"),
        "zh": ("文件", "文档", "图纸", "附件"),
        "ja": ("書類", "文書", "図面", "添付"),
    },
    "user": {
        "en": ("responsible*", "assignee*", "assigned to", "inspector*", "supervisor*", "foreman", "foremen"),
        "de": ("verantwortlich*", "zuständig*", "bearbeiter*", "prüfer*", "bauleiter*", "polier*"),
        "fr": ("responsable*", "assigné*", "inspecteur*", "contrôleur*", "chef de chantier"),
        "es": ("responsable*", "asignado*", "inspector*", "supervisor*", "encargado*"),
        "it": ("responsabil*", "assegnat*", "ispettor*", "supervisor*", "capocantier*"),
        "pt": ("responsável*", "responsavel*", "atribuíd*", "inspetor*", "supervisor*", "encarregad*"),
        "nl": ("verantwoordelijk*", "toegewezen*", "inspecteur*", "uitvoerder*", "opzichter*"),
        "pl": ("odpowiedzialn*", "przypisan*", "inspektor*", "kierownik*"),
        "ru": ("ответственн*", "исполнител*", "инспектор*", "прораб*", "мастер"),
        "uk": ("відповідальн*", "виконавец*", "виконавц*", "інспектор*", "виконроб*", "майстер"),
        "tr": ("sorumlu*", "atanan*", "denetçi*", "müfettiş*", "şantiye şefi"),
        "zh": ("负责人", "责任人", "检查员", "监理"),
        "ja": ("担当者", "責任者", "検査員", "監督"),
    },
    "due": {
        "en": ("due", "deadline*", "expir*", "valid until", "valid to", "target date", "complete by", "renewal*"),
        "de": ("*frist*", "fällig*", "ablauf*", "gültig bis", "deadline*"),
        "fr": ("échéance*", "date limite", "délai*", "expiration*", "valable jusqu*"),
        "es": ("vencimiento*", "fecha límite", "plazo*", "caducidad*", "válido hasta", "valido hasta"),
        "it": ("scadenz*", "data limite", "valido fino", "termine ultimo"),
        "pt": ("vencimento*", "prazo*", "data limite", "validade*", "expira*"),
        "nl": ("vervaldatum*", "deadline*", "*termijn*", "geldig tot", "uiterlijk*"),
        "pl": ("termin*", "data ważności", "ważn* do", "wygasa*"),
        "ru": ("срок*", "дедлайн*", "действует до", "действителен до", "годен до", "истечени*"),
        "uk": ("термін*", "строк*", "дедлайн*", "діє до", "дійсний до", "закінчення дії"),
        "tr": ("son tarih*", "vade*", "geçerlilik*", "termin*", "bitiş tarihi"),
        "zh": ("截止", "到期", "期限", "有效期"),
        "ja": ("期限", "締切", "締め切り", "有効期限", "納期"),
    },
}

NEGATIVE: dict[str, tuple[str, ...]] = {
    # A contractor is a company (a contact), and a subcontract is a different
    # record from the main contract this register would link.
    "contract": ("contractor*", "subcontract*", "vertragspartner*", "contraente*"),
}

# Words that may sit beside a concept in a label without making it something
# else: "Contract no." is still the contract.
REFERENCE_WORDS = frozenset(
    {
        "no",
        "nr",
        "number",
        "ref",
        "reference",
        "id",
        "code",
        "nummer",
        "numéro",
        "numero",
        "número",
        "numer",
        "номер",
        "numara",
        "linked",
        "related",
        # A deadline is a date: "Due date" is the deadline itself.
        "date",
        "datum",
        "fecha",
        "data",
        "дата",
        "tarih",
        "tarihi",
    }
)

# The label a suggested link field gets, per language.
LINK_LABELS: dict[str, dict[str, str]] = {
    "contract": {
        "en": "Contract", "de": "Vertrag", "fr": "Contrat", "es": "Contrato", "it": "Contratto", "pt": "Contrato",
        "nl": "Contract", "pl": "Umowa", "ru": "Договор", "uk": "Договір", "tr": "Sözleşme", "zh": "合同", "ja": "契約",
    },
    "contact": {
        "en": "Contact", "de": "Kontakt", "fr": "Contact", "es": "Contacto", "it": "Contatto", "pt": "Contato",
        "nl": "Contact", "pl": "Kontakt", "ru": "Контакт", "uk": "Контакт", "tr": "Kişi", "zh": "联系人", "ja": "連絡先",
    },
    "schedule_activity": {
        "en": "Schedule activity", "de": "Vorgang", "fr": "Activité", "es": "Actividad", "it": "Attività",
        "pt": "Atividade", "nl": "Activiteit", "pl": "Czynność", "ru": "Работа графика", "uk": "Робота графіка",
        "tr": "Faaliyet", "zh": "进度任务", "ja": "工程",
    },
    "document": {
        "en": "Document", "de": "Dokument", "fr": "Document", "es": "Documento", "it": "Documento", "pt": "Documento",
        "nl": "Document", "pl": "Dokument", "ru": "Документ", "uk": "Документ", "tr": "Belge", "zh": "文件", "ja": "書類",
    },
    "user": {
        "en": "Responsible", "de": "Verantwortlich", "fr": "Responsable", "es": "Responsable", "it": "Responsabile",
        "pt": "Responsável", "nl": "Verantwoordelijke", "pl": "Odpowiedzialny", "ru": "Ответственный",
        "uk": "Відповідальний", "tr": "Sorumlu", "zh": "负责人", "ja": "担当者",
    },
}  # fmt: skip

# The three states a suggested status starts with: open, in progress, done.
STATE_LABELS: dict[str, tuple[str, str, str]] = {
    "en": ("Open", "In progress", "Done"),
    "de": ("Offen", "In Bearbeitung", "Erledigt"),
    "fr": ("Ouvert", "En cours", "Terminé"),
    "es": ("Abierto", "En curso", "Terminado"),
    "it": ("Aperto", "In corso", "Completato"),
    "pt": ("Aberto", "Em andamento", "Concluído"),
    "nl": ("Open", "In behandeling", "Gereed"),
    "pl": ("Otwarte", "W toku", "Zakończone"),
    "ru": ("Открыто", "В работе", "Готово"),
    "uk": ("Відкрито", "В роботі", "Готово"),
    "tr": ("Açık", "Devam ediyor", "Tamamlandı"),
    "zh": ("待处理", "进行中", "已完成"),
    "ja": ("未着手", "進行中", "完了"),
}
STATE_CODES = ("open", "in_progress", "done")

# Days before a deadline a suggested reminder fires.
DEFAULT_REMIND_DAYS = 3

LINK_REASONS = ("link_field_name", "link_module_name")


def language_of(locale: str | None) -> str:
    """The table language for a UI locale: ``pt-BR`` reads as ``pt``, anything unknown as ``en``."""
    base = (locale or "en").split("-")[0].lower()
    return base if base in LANGUAGES else "en"


def default_status(locale: str | None) -> StatusFeature:
    """Open, in progress, done, labelled in the reader's language."""
    labels = STATE_LABELS[language_of(locale)]
    return StatusFeature(
        states=[
            StateSpec(code=code, label=label, done=code == "done")
            for code, label in zip(STATE_CODES, labels, strict=True)
        ]
    )


def link_label(target: str, locale: str | None) -> str:
    return LINK_LABELS[target][language_of(locale)]


# ── matching ────────────────────────────────────────────────────────────────

_CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿]")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def _normalise(text: str) -> str:
    # Casefolding the Turkish capital dotted I gives "i" plus a combining dot,
    # which would split "İletişim" into two words. The dot carries nothing here.
    return unicodedata.normalize("NFKC", text or "").casefold().replace("̇", "")


def _words(text: str) -> list[str]:
    """Lower-cased words, splitting snake_case and punctuation alike."""
    return _WORD.findall(_normalise(text))


def _word_matches(word: str, pattern: str) -> bool:
    if pattern.startswith("*") and pattern.endswith("*") and len(pattern) > 2:
        return pattern[1:-1] in word
    if pattern.startswith("*"):
        return word.endswith(pattern[1:])
    if pattern.endswith("*"):
        return word.startswith(pattern[:-1])
    return word == pattern


def _keyword_hits(words: list[str], raw: str, keyword: str) -> list[int]:
    """Indexes of the words a keyword covers; empty when it does not match."""
    keyword = _normalise(keyword)
    if _CJK.search(keyword):
        return [-1] if keyword in raw else []
    parts = keyword.replace("-", " ").split()
    for start in range(len(words) - len(parts) + 1):
        if all(_word_matches(words[start + i], part) for i, part in enumerate(parts)):
            return list(range(start, start + len(parts)))
    return []


def _matches(concept: str, *texts: str) -> tuple[bool, bool]:
    """Whether any text names the concept, and whether one names nothing else.

    The second flag is what makes a match "high": a label that is the concept
    and at most a reference word ("Contract no.") rather than a phrase that
    merely mentions it ("Contract type").
    """
    table = KEYWORDS[concept]
    negatives = NEGATIVE.get(concept, ())
    found = exact = False
    for text in texts:
        raw = _normalise(text)
        words = _words(text)
        if not raw:
            continue
        banned = {i for i, w in enumerate(words) if any(_word_matches(w, n) for n in negatives)}
        for keywords in table.values():
            for keyword in keywords:
                hits = _keyword_hits(words, raw, keyword)
                if not hits or banned.intersection(hits):
                    continue
                found = True
                rest = [w for i, w in enumerate(words) if i not in hits and w not in REFERENCE_WORDS]
                if hits == [-1]:
                    rest = [w for w in words if not _CJK.search(w)]
                if not rest:
                    exact = True
    return found, exact


# ── suggestions ─────────────────────────────────────────────────────────────


def suggest(
    spec: ModuleSpec,
    locale: str | None = None,
    *,
    available: Callable[[str], bool] | None = None,
) -> list[Suggestion]:
    """Every suggestion the rules make for ``spec``, links first.

    Args:
        spec: The module as the wizard holds it now.
        locale: The reader's language, for the labels of anything proposed.
        available: Whether a link target can be built here. Defaults to
            every target; the router passes the module loader's answer.
    """
    is_available = available or (lambda _target: True)
    out: list[Suggestion] = []
    out += _link_suggestions(spec, locale, is_available)
    out += _feature_suggestions(spec, locale)
    return _only_valid(spec, out)


# ── names that fit ──────────────────────────────────────────────────────────

_RANK = {"high": 0, "medium": 1, "low": 2}


def _name_room(spec: ModuleSpec) -> int:
    """How many bytes a link field's name may have.

    A link column gets the index ``ix_<table>_<name>``, and PostgreSQL cuts a
    name past :data:`MAX_IDENTIFIER_BYTES`, so the spec refuses one. The status
    column's index is named the same way.
    """
    return MAX_IDENTIFIER_BYTES - len(f"ix_{spec.table_name}_".encode())


def fitting_name(base: str, room: int, taken: set[str]) -> str | None:
    """A field name made from ``base`` that is at most ``room`` bytes and not taken.

    Shortened by whole words from the end first ("supplier_contract_number"
    becomes "supplier_contract"), then by letters, then numbered ("contract_2")
    when the short form is taken. The same input always gives the same name.
    None when no name fits.
    """
    for n in range(1, 100):
        suffix = "" if n == 1 else f"_{n}"
        budget = room - len(suffix)
        if budget < 1:
            return None
        parts = base.split("_")
        while len("_".join(parts)) > budget and len(parts) > 1:
            parts.pop()
        stem = "_".join(parts)[:budget].rstrip("_")
        if not stem:
            return None
        candidate = stem + suffix
        if candidate not in taken and _a_field_name(candidate):
            return candidate
    return None


def _a_field_name(name: str) -> bool:
    try:
        FieldSpec(name=name, label=name)
    except ValueError:
        return False
    return True


def _link_suggestions(spec: ModuleSpec, locale: str | None, available: Callable[[str], bool]) -> list[Suggestion]:
    linked = {f.target for f in spec.link_fields}
    module_texts = (
        spec.display_name,
        spec.entity.display_name,
        spec.entity.plural_name,
        spec.entity.name,
        spec.description,
    )
    room = _name_room(spec)
    # Every name in use, by the spec or by a suggestion made before this one:
    # two shortened names can come out the same ("contract", "contact").
    taken = {f.name for f in spec.entity.fields} | {STATUS_COLUMN}
    out: list[Suggestion] = []
    # A field turned into one link is not offered as another as well.
    claimed: set[str] = set()
    for target in LINK_TARGETS:
        if target in linked or not available(target):
            continue
        suggestion = _from_field(spec, target, claimed, taken, room) or _from_module(
            spec, target, module_texts, taken, room, locale
        )
        if suggestion is not None and suggestion.patch.field is not None:
            taken.add(suggestion.patch.field.name)
            out.append(suggestion)
    return _within_the_field_limit(spec, out)


def _within_the_field_limit(spec: ModuleSpec, links: list[Suggestion]) -> list[Suggestion]:
    """The link suggestions that still fit when every one of them is ticked.

    A link that turns an existing field into the link adds no field; the others
    add one each. Past :data:`MAX_FIELDS` the least confident are left out, so
    "Accept all suggested" never builds a spec the server then refuses.
    """
    existing = {f.name for f in spec.entity.fields}
    adding = [s for s in links if s.patch.field is not None and s.patch.field.name not in existing]
    room = max(0, MAX_FIELDS - len(spec.entity.fields))
    if len(adding) <= room:
        return links
    ranked = sorted(range(len(adding)), key=lambda i: (_RANK[adding[i].confidence], i))
    dropped = {id(adding[i]) for i in ranked[room:]}
    return [s for s in links if id(s) not in dropped]


def _from_field(spec: ModuleSpec, target: str, claimed: set[str], taken: set[str], room: int) -> Suggestion | None:
    """A text field that already names the target becomes the link.

    In place, under the field's own name, when the link's index fits with it.
    When it does not, the link is a new field beside it with a shorter name:
    the reason is still the field's name, and the person keeps their text.
    """
    for field in spec.entity.fields:
        if field.type != "text" or field.name in claimed:
            continue
        found, exact = _matches(target, field.label, field.name)
        if not found:
            continue
        name = field.name if len(field.name.encode()) <= room else fitting_name(field.name, room, taken)
        if name is None:
            continue
        patch_field = FieldSpec(
            name=name,
            label=field.label,
            type="link",
            target=target,
            required=field.required,
            help_text=field.help_text,
            in_list=field.in_list,
        )
        claimed.add(field.name)
        return Suggestion(
            id=f"link:{target}",
            kind="link",
            target=target,
            confidence="high" if exact else "medium",
            reason_code="link_field_name",
            reason_params={"field": field.label},
            patch=SuggestionPatch(field=patch_field),
        )
    return None


def _from_module(
    spec: ModuleSpec, target: str, texts: Iterable[str], taken: set[str], room: int, locale: str | None
) -> Suggestion | None:
    """The module's own name or description names the target: add a link field."""
    texts = list(texts)
    in_name, _ = _matches(target, *texts[:4])
    in_description, _ = _matches(target, texts[4])
    if not (in_name or in_description):
        return None
    candidate = fitting_name(LINK_TARGETS[target].field_name, room, taken)
    if candidate is None:
        return None
    return Suggestion(
        id=f"link:{target}",
        kind="link",
        target=target,
        confidence="medium" if in_name else "low",
        reason_code="link_module_name",
        patch=SuggestionPatch(
            field=FieldSpec(name=candidate, label=link_label(target, locale), type="link", target=target)
        ),
    )


def _feature_suggestions(spec: ModuleSpec, locale: str | None) -> list[Suggestion]:
    features = spec.features
    scoped = spec.entity.project_scoped
    out: list[Suggestion] = []
    names = {f.name for f in spec.entity.fields}
    status_fits = len(STATUS_COLUMN.encode()) <= _name_room(spec)
    if features.status is None and STATUS_COLUMN not in names and status_fits:
        out.append(
            Suggestion(
                id="feature:status",
                kind="feature",
                feature="status",
                confidence="medium",
                reason_code="status_register",
                patch=SuggestionPatch(status=default_status(locale)),
            )
        )
    if features.due is None and scoped:
        due = _due_field(spec)
        if due is not None:
            field, exact = due
            out.append(
                Suggestion(
                    id="feature:due",
                    kind="feature",
                    feature="due",
                    confidence="high" if exact else "medium",
                    reason_code="due_date_field",
                    reason_params={"field": field.label},
                    patch=SuggestionPatch(due=DueFeature(field=field.name, remind_days_before=DEFAULT_REMIND_DAYS)),
                )
            )
    if not features.export:
        out.append(
            Suggestion(
                id="feature:export",
                kind="feature",
                feature="export",
                confidence="medium",
                reason_code="export_register",
                patch=SuggestionPatch(export=True),
            )
        )
    if not features.comments and scoped:
        out.append(
            Suggestion(
                id="feature:comments",
                kind="feature",
                feature="comments",
                confidence="low",
                reason_code="comments_register",
                patch=SuggestionPatch(comments=True),
            )
        )
    return out


def _only_valid(spec: ModuleSpec, suggestions: list[Suggestion]) -> list[Suggestion]:
    """The suggestions whose patch the spec accepts, alone and all together.

    The rules above are written to make this a no-op. It is the backstop for
    the case they miss: a suggestion the server would refuse after a person
    ticked it is worse than none, so it is dropped here and logged as the
    defect it is. All together, the least confident link goes first.
    """
    if not _accepts(spec, []):
        return suggestions
    kept = []
    for suggestion in suggestions:
        if _accepts(spec, [suggestion]):
            kept.append(suggestion)
        else:
            logger.warning(
                "module_builder: suggestion %s for %s does not apply and was dropped", suggestion.id, spec.key
            )
    while kept and not _accepts(spec, kept):
        links = [i for i, s in enumerate(kept) if s.kind == "link"]
        if not links:
            break
        weakest = max(links, key=lambda i: (_RANK[kept[i].confidence], i))
        logger.warning("module_builder: suggestion %s for %s does not fit with the rest", kept[weakest].id, spec.key)
        del kept[weakest]
    return kept


def apply_patches(spec: ModuleSpec, suggestions: Iterable[Suggestion]) -> dict[str, Any]:
    """The spec, as data, with these suggestions applied the way the wizard applies them.

    A link field replaces the field of the same name, which is how a text field
    becomes the link, and is added otherwise.
    """
    data = spec.model_dump(mode="json")
    fields: list[dict[str, Any]] = data["entity"]["fields"]
    for suggestion in suggestions:
        patch = suggestion.patch
        if patch.field is not None:
            new = patch.field.model_dump(mode="json")
            at = next((i for i, f in enumerate(fields) if f["name"] == new["name"]), None)
            if at is None:
                fields.append(new)
            else:
                fields[at] = new
        if patch.status is not None:
            data["features"]["status"] = patch.status.model_dump(mode="json")
        if patch.due is not None:
            data["features"]["due"] = patch.due.model_dump(mode="json")
        if patch.export:
            data["features"]["export"] = True
        if patch.comments:
            data["features"]["comments"] = True
    return data


def _accepts(spec: ModuleSpec, suggestions: list[Suggestion]) -> bool:
    try:
        ModuleSpec.model_validate(apply_patches(spec, suggestions))
    except ValidationError:
        return False
    return True


def _due_field(spec: ModuleSpec) -> tuple[FieldSpec, bool] | None:
    """The first date field whose name reads as a deadline, preferring an exact one."""
    best: tuple[FieldSpec, bool] | None = None
    for field in spec.entity.fields:
        if field.type not in {"date", "datetime"}:
            continue
        found, exact = _matches("due", field.label, field.name)
        if found and (best is None or (exact and not best[1])):
            best = (field, exact)
    return best
