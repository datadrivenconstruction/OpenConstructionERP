# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalog and locale resolution for the single-RFI PDF export.

The RFI document is the printable form of one request for information: the
page a site team hands to the design team, files with the contract or
prints for a coordination meeting. Its fixed strings live here, next to the
renderer, the way :mod:`app.modules.daily_diary.pdf_translations` keeps the
diary's, and the rule that picks a language is the shared one in
:mod:`app.core.document_locale`.

Which languages are in the catalogue is decided by two things together: the
language is offered in the interface, and the PDF font ladder in
:mod:`app.core.pdf_fonts` can actually draw it. That gives every offered
left-to-right language except Bengali:

* Latin, Cyrillic and Greek draw in the bundled DejaVu face.
* Chinese and Japanese draw in the Adobe Simplified Chinese CID face, whose
  repertoire carries kana; Korean draws in the Korean CID face.
* Thai and Hindi draw in the bundled Noto faces and are shaped, which only
  happens on the Paragraph path. :mod:`app.modules.rfi.pdf_export` puts every
  string, table cells and footer included, through a Paragraph.
* Bengali stays English. No bundled face has a single Bengali codepoint and
  neither CID pack reaches the script, so a Bengali catalogue would print as
  boxes.
* Arabic, Persian, Hebrew and Urdu stay English. The font ladder draws
  right-to-left text unshaped and in logical order, which reads backwards on
  the page; a document that is wrong is worse than one in English.

:mod:`app.modules.rfi.intl` labels statuses and disciplines in exactly the
same set of languages, so a document never mixes a translated heading with an
untranslated status word. Any other request falls back to English, and the
route serving the PDF declares the language it actually rendered in
``Content-Language``. Regional variants (``pt-BR``, ``es-MX``, ``en-GB``)
read their base language.

The labels follow the RFI screens in each language, so the paper says what
the screen says. The terms are the ones a construction reader expects on the
form: German says "Gestellt von" for raised by, the change order an answer
raised is named with each language's term for the Change Orders module, and
the Slavic strings avoid past tense verbs where they would force a
grammatical gender onto whoever raised or answered the RFI.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from app.core import register_export
from app.core.document_locale import (
    normalize_document_locale,
    resolve_document_locale,
    translate,
)

__all__ = [
    "DEFAULT_PDF_LOCALE",
    "SUPPORTED_PDF_LOCALES",
    "UNRENDERABLE_PDF_LOCALES",
    "days_text",
    "format_date",
    "normalize_pdf_locale",
    "priority_label",
    "resolve_pdf_locale",
    "rfi_pdf_filename",
    "status_caps",
    "tr",
]

DEFAULT_PDF_LOCALE = "en"

#: Languages the RFI PDF can render. Extend every table below, and the status
#: and discipline tables in :mod:`app.modules.rfi.intl`, together when adding
#: one; anything else falls back to English.
SUPPORTED_PDF_LOCALES: tuple[str, ...] = (
    "en",
    "de",
    "ru",
    "bg",
    "cs",
    "da",
    "el",
    "es",
    "et",
    "fi",
    "fil",
    "fr",
    "hi",
    "hr",
    "hu",
    "id",
    "it",
    "ja",
    "kk",
    "ko",
    "ky",
    "nl",
    "no",
    "pl",
    "pt",
    "ro",
    "sv",
    "th",
    "tr",
    "uk",
    "uz",
    "vi",
    "zh",
)

#: Offered interface languages the PDF deliberately renders in English, and
#: why. Kept as data so a test pins the decision instead of a comment.
UNRENDERABLE_PDF_LOCALES: dict[str, str] = {
    "ar": "right-to-left, drawn unshaped and in logical order",
    "fa": "right-to-left, drawn unshaped and in logical order",
    "he": "right-to-left, drawn in logical order",
    "ur": "right-to-left, drawn unshaped and in logical order",
    "bn": "no bundled or referenced face carries Bengali glyphs",
}

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "doc_title": "Request for Information",
        "project": "Project",
        "raised_by": "Raised by",
        "assigned_to": "Assigned to",
        "ball_in_court": "Ball in court",
        "date_raised": "Date raised",
        "response_due": "Response due",
        "date_required": "Date required",
        "priority": "Priority",
        "discipline": "Discipline",
        "question": "Question",
        "references": "Referenced documents",
        "references_unavailable": "Linked documents no longer available: {count}",
        "attachments": "Attached files",
        "impact": "Impact",
        "cost_impact": "Cost impact",
        "schedule_impact": "Schedule impact",
        "yes": "Yes",
        "yes_with": "Yes, {detail}",
        "no": "No",
        "response": "Official response",
        "no_response": "No response recorded yet.",
        "answered_by": "Answered by",
        "answer_date": "Answer date",
        "variation": "Linked change order",
        "signatures": "Signatures",
        "name": "Name",
        "signature": "Signature",
        "date": "Date",
        "footer_generated": "Generated {timestamp}",
        "footer_page": "Page {page}",
        "date_format": "%Y-%m-%d",
        "datetime_format": "%Y-%m-%d %H:%M UTC",
    },
    "de": {
        "doc_title": "Technische Anfrage (RFI)",
        "project": "Projekt",
        "raised_by": "Gestellt von",
        "assigned_to": "Gerichtet an",
        "ball_in_court": "Zuständig",
        "date_raised": "Gestellt am",
        "response_due": "Antwort fällig am",
        "date_required": "Benötigt bis",
        "priority": "Priorität",
        "discipline": "Fachbereich",
        "question": "Frage",
        "references": "Bezugsdokumente",
        "references_unavailable": "Nicht mehr verfügbare verknüpfte Dokumente: {count}",
        "attachments": "Angehängte Dateien",
        "impact": "Auswirkungen",
        "cost_impact": "Kostenauswirkung",
        "schedule_impact": "Terminauswirkung",
        "yes": "Ja",
        "yes_with": "Ja, {detail}",
        "no": "Nein",
        "response": "Offizielle Antwort",
        "no_response": "Noch keine Antwort erfasst.",
        "answered_by": "Beantwortet von",
        "answer_date": "Antwortdatum",
        "variation": "Verknüpfter Änderungsauftrag",
        "signatures": "Unterschriften",
        "name": "Name",
        "signature": "Unterschrift",
        "date": "Datum",
        "footer_generated": "Erstellt {timestamp}",
        "footer_page": "Seite {page}",
        "date_format": "%d.%m.%Y",
        "datetime_format": "%d.%m.%Y %H:%M UTC",
    },
    "ru": {
        "doc_title": "Запрос информации (RFI)",
        "project": "Проект",
        "raised_by": "Автор запроса",
        "assigned_to": "Адресат",
        "ball_in_court": "Ответственный",
        "date_raised": "Дата запроса",
        "response_due": "Срок ответа",
        "date_required": "Требуется к",
        "priority": "Приоритет",
        "discipline": "Раздел",
        "question": "Вопрос",
        "references": "Связанные документы",
        "references_unavailable": "Связанные документы больше недоступны: {count}",
        "attachments": "Приложенные файлы",
        "impact": "Влияние",
        "cost_impact": "Влияние на стоимость",
        "schedule_impact": "Влияние на сроки",
        "yes": "Да",
        "yes_with": "Да, {detail}",
        "no": "Нет",
        "response": "Официальный ответ",
        "no_response": "Ответ пока не получен.",
        "answered_by": "Автор ответа",
        "answer_date": "Дата ответа",
        "variation": "Связанное распоряжение об изменении",
        "signatures": "Подписи",
        "name": "ФИО",
        "signature": "Подпись",
        "date": "Дата",
        "footer_generated": "Сформировано {timestamp}",
        "footer_page": "Стр. {page}",
        "date_format": "%d.%m.%Y",
        "datetime_format": "%d.%m.%Y %H:%M UTC",
    },
    "bg": {
        "doc_title": "Искане за информация (RFI)",
        "project": "Проект",
        "raised_by": "Подадено от",
        "assigned_to": "Назначено на",
        "ball_in_court": "Отговорно лице",
        "date_raised": "Дата на подаване",
        "response_due": "Срок за отговор",
        "date_required": "Необходимо до",
        "priority": "Приоритет",
        "discipline": "Дисциплина",
        "question": "Въпрос",
        "references": "Свързани документи",
        "references_unavailable": "Свързани документи, които вече не са налични: {count}",
        "attachments": "Прикачени файлове",
        "impact": "Влияние",
        "cost_impact": "Въздействие върху разходите",
        "schedule_impact": "Въздействие върху графика",
        "yes": "Да",
        "yes_with": "Да, {detail}",
        "no": "Не",
        "response": "Официален отговор",
        "no_response": "Все още няма регистриран отговор.",
        "answered_by": "Автор на отговора",
        "answer_date": "Дата на отговора",
        "variation": "Свързана заповед за промяна",
        "signatures": "Подписи",
        "name": "Име и фамилия",
        "signature": "Подпис",
        "date": "Дата",
        "footer_generated": "Генерирано {timestamp}",
        "footer_page": "Стр. {page}",
        "date_format": "%d.%m.%Y",
        "datetime_format": "%d.%m.%Y %H:%M UTC",
    },
    "cs": {
        "doc_title": "Žádost o informace (RFI)",
        "project": "Projekt",
        "raised_by": "Autor žádosti",
        "assigned_to": "Přiřazeno",
        "ball_in_court": "Aktuálně zodpovědný",
        "date_raised": "Datum podání",
        "response_due": "Termín odpovědi",
        "date_required": "Potřebné do",
        "priority": "Priorita",
        "discipline": "Profese",
        "question": "Dotaz",
        "references": "Související dokumenty",
        "references_unavailable": "Propojené dokumenty, které již nejsou k dispozici: {count}",
        "attachments": "Přiložené soubory",
        "impact": "Dopad",
        "cost_impact": "Dopad na náklady",
        "schedule_impact": "Dopad na harmonogram",
        "yes": "Ano",
        "yes_with": "Ano, {detail}",
        "no": "Ne",
        "response": "Oficiální odpověď",
        "no_response": "Zatím nebyla zaznamenána žádná odpověď.",
        "answered_by": "Autor odpovědi",
        "answer_date": "Datum odpovědi",
        "variation": "Propojený změnový příkaz",
        "signatures": "Podpisy",
        "name": "Jméno a příjmení",
        "signature": "Podpis",
        "date": "Datum",
        "footer_generated": "Vytvořeno {timestamp}",
        "footer_page": "Strana {page}",
        "date_format": "%d.%m.%Y",
        "datetime_format": "%d.%m.%Y %H:%M UTC",
    },
    "da": {
        "doc_title": "Anmodning om information (RFI)",
        "project": "Projekt",
        "raised_by": "Rejst af",
        "assigned_to": "Tildelt til",
        "ball_in_court": "Bolden hos",
        "date_raised": "Dato for anmodning",
        "response_due": "Svarfrist",
        "date_required": "Krævet senest",
        "priority": "Prioritet",
        "discipline": "Disciplin",
        "question": "Spørgsmål",
        "references": "Referencedokumenter",
        "references_unavailable": "Linkede dokumenter, der ikke længere er tilgængelige: {count}",
        "attachments": "Vedhæftede filer",
        "impact": "Påvirkning",
        "cost_impact": "Omkostningspåvirkning",
        "schedule_impact": "Tidsplanspåvirkning",
        "yes": "Ja",
        "yes_with": "Ja, {detail}",
        "no": "Nej",
        "response": "Officielt svar",
        "no_response": "Intet svar registreret endnu.",
        "answered_by": "Besvaret af",
        "answer_date": "Svardato",
        "variation": "Linket ændringsordre",
        "signatures": "Underskrifter",
        "name": "Navn",
        "signature": "Underskrift",
        "date": "Dato",
        "footer_generated": "Genereret {timestamp}",
        "footer_page": "Side {page}",
        "date_format": "%d.%m.%Y",
        "datetime_format": "%d.%m.%Y %H:%M UTC",
    },
    "el": {
        "doc_title": "Αίτημα πληροφοριών (RFI)",
        "project": "Έργο",
        "raised_by": "Υποβλήθηκε από",
        "assigned_to": "Ανατέθηκε σε",
        "ball_in_court": "Υπεύθυνος απάντησης",
        "date_raised": "Ημερομηνία υποβολής",
        "response_due": "Προθεσμία απάντησης",
        "date_required": "Απαιτούμενη ημερομηνία",
        "priority": "Προτεραιότητα",
        "discipline": "Ειδικότητα",
        "question": "Ερώτηση",
        "references": "Έγγραφα αναφοράς",
        "references_unavailable": "Συνδεδεμένα έγγραφα που δεν είναι πλέον διαθέσιμα: {count}",
        "attachments": "Συνημμένα αρχεία",
        "impact": "Επίπτωση",
        "cost_impact": "Επίπτωση στο κόστος",
        "schedule_impact": "Επίπτωση στο χρονοδιάγραμμα",
        "yes": "Ναι",
        "yes_with": "Ναι, {detail}",
        "no": "Όχι",
        "response": "Επίσημη απάντηση",
        "no_response": "Δεν έχει καταγραφεί ακόμη απάντηση.",
        "answered_by": "Απαντήθηκε από",
        "answer_date": "Ημερομηνία απάντησης",
        "variation": "Συνδεδεμένη εντολή αλλαγής",
        "signatures": "Υπογραφές",
        "name": "Ονοματεπώνυμο",
        "signature": "Υπογραφή",
        "date": "Ημερομηνία",
        "footer_generated": "Δημιουργήθηκε {timestamp}",
        "footer_page": "Σελίδα {page}",
        "date_format": "%d/%m/%Y",
        "datetime_format": "%d/%m/%Y %H:%M UTC",
    },
    "es": {
        "doc_title": "Solicitud de información (RFI)",
        "project": "Proyecto",
        "raised_by": "Presentado por",
        "assigned_to": "Asignado a",
        "ball_in_court": "Responsable",
        "date_raised": "Fecha de emisión",
        "response_due": "Fecha límite de respuesta",
        "date_required": "Fecha requerida",
        "priority": "Prioridad",
        "discipline": "Disciplina",
        "question": "Pregunta",
        "references": "Documentos de referencia",
        "references_unavailable": "Documentos vinculados que ya no están disponibles: {count}",
        "attachments": "Archivos adjuntos",
        "impact": "Impacto",
        "cost_impact": "Impacto en costos",
        "schedule_impact": "Impacto en cronograma",
        "yes": "Sí",
        "yes_with": "Sí, {detail}",
        "no": "No",
        "response": "Respuesta oficial",
        "no_response": "Aún no se ha registrado ninguna respuesta.",
        "answered_by": "Respondido por",
        "answer_date": "Fecha de respuesta",
        "variation": "Orden de cambio vinculada",
        "signatures": "Firmas",
        "name": "Nombre",
        "signature": "Firma",
        "date": "Fecha",
        "footer_generated": "Generado el {timestamp}",
        "footer_page": "Página {page}",
        "date_format": "%d/%m/%Y",
        "datetime_format": "%d/%m/%Y %H:%M UTC",
    },
    "et": {
        "doc_title": "Teabepäring (RFI)",
        "project": "Projekt",
        "raised_by": "Esitaja",
        "assigned_to": "Määratud",
        "ball_in_court": "Vastutaja",
        "date_raised": "Esitamise kuupäev",
        "response_due": "Vastamise tähtaeg",
        "date_required": "Vajalik kuupäev",
        "priority": "Prioriteet",
        "discipline": "Eriala",
        "question": "Küsimus",
        "references": "Viitedokumendid",
        "references_unavailable": "Lingitud dokumendid, mis pole enam saadaval: {count}",
        "attachments": "Manustatud failid",
        "impact": "Mõju",
        "cost_impact": "Mõju kuludele",
        "schedule_impact": "Mõju ajakavale",
        "yes": "Jah",
        "yes_with": "Jah, {detail}",
        "no": "Ei",
        "response": "Ametlik vastus",
        "no_response": "Vastust pole veel registreeritud.",
        "answered_by": "Vastaja",
        "answer_date": "Vastuse kuupäev",
        "variation": "Lingitud muudatuskorraldus",
        "signatures": "Allkirjad",
        "name": "Nimi",
        "signature": "Allkiri",
        "date": "Kuupäev",
        "footer_generated": "Loodud {timestamp}",
        "footer_page": "Lk {page}",
        "date_format": "%d.%m.%Y",
        "datetime_format": "%d.%m.%Y %H:%M UTC",
    },
    "fi": {
        "doc_title": "Tietopyyntö (RFI)",
        "project": "Projekti",
        "raised_by": "Lähettäjä",
        "assigned_to": "Määrätty henkilölle",
        "ball_in_court": "Vastuuhenkilö",
        "date_raised": "Lähetyspäivä",
        "response_due": "Vastauksen määräpäivä",
        "date_required": "Tarvitaan viimeistään",
        "priority": "Prioriteetti",
        "discipline": "Ala",
        "question": "Kysymys",
        "references": "Viiteasiakirjat",
        "references_unavailable": "Linkitetyt asiakirjat, jotka eivät ole enää saatavilla: {count}",
        "attachments": "Liitetiedostot",
        "impact": "Vaikutus",
        "cost_impact": "Kustannusvaikutus",
        "schedule_impact": "Aikatauluvaikutus",
        "yes": "Kyllä",
        "yes_with": "Kyllä, {detail}",
        "no": "Ei",
        "response": "Virallinen vastaus",
        "no_response": "Vastausta ei ole vielä kirjattu.",
        "answered_by": "Vastaaja",
        "answer_date": "Vastauspäivä",
        "variation": "Linkitetty muutostilaus",
        "signatures": "Allekirjoitukset",
        "name": "Nimi",
        "signature": "Allekirjoitus",
        "date": "Päivämäärä",
        "footer_generated": "Luotu {timestamp}",
        "footer_page": "Sivu {page}",
        "date_format": "%d.%m.%Y",
        "datetime_format": "%d.%m.%Y %H:%M UTC",
    },
    "fil": {
        "doc_title": "Kahilingan para sa Impormasyon (RFI)",
        "project": "Proyekto",
        "raised_by": "Itinaas ni",
        "assigned_to": "Itinalaga kay",
        "ball_in_court": "Ball-in-Court",
        "date_raised": "Petsa ng paghahain",
        "response_due": "Takdang petsa ng sagot",
        "date_required": "Kinakailangang petsa",
        "priority": "Priyoridad",
        "discipline": "Disiplina",
        "question": "Tanong",
        "references": "Mga sangguniang dokumento",
        "references_unavailable": "Mga naka-link na dokumentong hindi na available: {count}",
        "attachments": "Mga naka-attach na file",
        "impact": "Epekto",
        "cost_impact": "Epekto sa gastos",
        "schedule_impact": "Epekto sa schedule",
        "yes": "Oo",
        "yes_with": "Oo, {detail}",
        "no": "Hindi",
        "response": "Opisyal na tugon",
        "no_response": "Wala pang naitalang tugon.",
        "answered_by": "Sinagot ni",
        "answer_date": "Petsa ng sagot",
        "variation": "Naka-link na change order",
        "signatures": "Mga lagda",
        "name": "Pangalan",
        "signature": "Lagda",
        "date": "Petsa",
        "footer_generated": "Ginawa noong {timestamp}",
        "footer_page": "Pahina {page}",
        "date_format": "%m/%d/%Y",
        "datetime_format": "%m/%d/%Y %H:%M UTC",
    },
    "fr": {
        "doc_title": "Demande de renseignements (RFI)",
        "project": "Projet",
        "raised_by": "Soulevé par",
        "assigned_to": "Attribué à",
        "ball_in_court": "Responsable actuel",
        "date_raised": "Date d'émission",
        "response_due": "Réponse attendue le",
        "date_required": "Date requise",
        "priority": "Priorité",
        "discipline": "Discipline",
        "question": "Question",
        "references": "Documents de référence",
        "references_unavailable": "Documents liés qui ne sont plus disponibles : {count}",
        "attachments": "Fichiers joints",
        "impact": "Impact",
        "cost_impact": "Impact financier",
        "schedule_impact": "Impact sur le planning",
        "yes": "Oui",
        "yes_with": "Oui, {detail}",
        "no": "Non",
        "response": "Réponse officielle",
        "no_response": "Aucune réponse enregistrée pour le moment.",
        "answered_by": "Répondu par",
        "answer_date": "Date de réponse",
        "variation": "Ordre de modification lié",
        "signatures": "Signatures",
        "name": "Nom",
        "signature": "Signature",
        "date": "Date",
        "footer_generated": "Généré le {timestamp}",
        "footer_page": "Page {page}",
        "date_format": "%d/%m/%Y",
        "datetime_format": "%d/%m/%Y %H:%M UTC",
    },
    "hi": {
        "doc_title": "सूचना के लिए अनुरोध (RFI)",
        "project": "प्रोजेक्ट",
        "raised_by": "द्वारा उठाया गया",
        "assigned_to": "असाइन किया गया",
        "ball_in_court": "उत्तरदायी पक्ष",
        "date_raised": "अनुरोध की तिथि",
        "response_due": "उत्तर की अंतिम तिथि",
        "date_required": "आवश्यकता तिथि",
        "priority": "प्राथमिकता",
        "discipline": "डिसिप्लिन",
        "question": "प्रश्न",
        "references": "संदर्भ दस्तावेज़",
        "references_unavailable": "लिंक किए गए दस्तावेज़ जो अब उपलब्ध नहीं हैं: {count}",
        "attachments": "संलग्न फ़ाइलें",
        "impact": "प्रभाव",
        "cost_impact": "लागत प्रभाव",
        "schedule_impact": "शेड्यूल प्रभाव",
        "yes": "हां",
        "yes_with": "हां, {detail}",
        "no": "नहीं",
        "response": "आधिकारिक प्रतिक्रिया",
        "no_response": "अभी तक कोई प्रतिक्रिया दर्ज नहीं की गई है।",
        "answered_by": "उत्तरदाता",
        "answer_date": "उत्तर की तिथि",
        "variation": "लिंक किया गया परिवर्तन आदेश",
        "signatures": "हस्ताक्षर",
        "name": "नाम",
        "signature": "हस्ताक्षर",
        "date": "तारीख",
        "footer_generated": "निर्माण समय: {timestamp}",
        "footer_page": "पृष्ठ {page}",
        "date_format": "%d/%m/%Y",
        "datetime_format": "%d/%m/%Y %H:%M UTC",
    },
    "hr": {
        "doc_title": "Zahtjev za informacijama (RFI)",
        "project": "Projekt",
        "raised_by": "Podnositelj",
        "assigned_to": "Dodijeljeno",
        "ball_in_court": "Strana na potezu",
        "date_raised": "Datum podnošenja",
        "response_due": "Rok za odgovor",
        "date_required": "Potrebno do",
        "priority": "Prioritet",
        "discipline": "Struka",
        "question": "Pitanje",
        "references": "Povezani dokumenti",
        "references_unavailable": "Povezani dokumenti koji više nisu dostupni: {count}",
        "attachments": "Priložene datoteke",
        "impact": "Utjecaj",
        "cost_impact": "Utjecaj na troškove",
        "schedule_impact": "Utjecaj na raspored",
        "yes": "Da",
        "yes_with": "Da, {detail}",
        "no": "Ne",
        "response": "Službeni odgovor",
        "no_response": "Još nije zabilježen nijedan odgovor.",
        "answered_by": "Autor odgovora",
        "answer_date": "Datum odgovora",
        "variation": "Povezani nalog za izmjenu",
        "signatures": "Potpisi",
        "name": "Ime i prezime",
        "signature": "Potpis",
        "date": "Datum",
        "footer_generated": "Generirano {timestamp}",
        "footer_page": "Stranica {page}",
        "date_format": "%d.%m.%Y.",
        "datetime_format": "%d.%m.%Y. %H:%M UTC",
    },
    "hu": {
        "doc_title": "Információkérés (RFI)",
        "project": "Projekt",
        "raised_by": "Beküldő",
        "assigned_to": "Hozzárendelve",
        "ball_in_court": "Felelős",
        "date_raised": "Beküldés dátuma",
        "response_due": "Válaszadási határidő",
        "date_required": "Szükséges dátum",
        "priority": "Prioritás",
        "discipline": "Szakterület",
        "question": "Kérdés",
        "references": "Hivatkozott dokumentumok",
        "references_unavailable": "Már nem elérhető kapcsolt dokumentumok: {count}",
        "attachments": "Csatolt fájlok",
        "impact": "Hatás",
        "cost_impact": "Költséghatás",
        "schedule_impact": "Ütemezési hatás",
        "yes": "Igen",
        "yes_with": "Igen, {detail}",
        "no": "Nem",
        "response": "Hivatalos válasz",
        "no_response": "Még nincs rögzített válasz.",
        "answered_by": "Válaszadó",
        "answer_date": "Válasz dátuma",
        "variation": "Kapcsolt változtatási megrendelés",
        "signatures": "Aláírások",
        "name": "Név",
        "signature": "Aláírás",
        "date": "Dátum",
        "footer_generated": "Készült: {timestamp}",
        "footer_page": "{page}. oldal",
        "date_format": "%Y.%m.%d.",
        "datetime_format": "%Y.%m.%d. %H:%M UTC",
    },
    "id": {
        "doc_title": "Permintaan Informasi (RFI)",
        "project": "Proyek",
        "raised_by": "Diajukan oleh",
        "assigned_to": "Ditugaskan kepada",
        "ball_in_court": "Pihak penanggung jawab",
        "date_raised": "Tanggal pengajuan",
        "response_due": "Batas waktu respons",
        "date_required": "Dibutuhkan paling lambat",
        "priority": "Prioritas",
        "discipline": "Disiplin",
        "question": "Pertanyaan",
        "references": "Dokumen referensi",
        "references_unavailable": "Dokumen tertaut yang tidak tersedia lagi: {count}",
        "attachments": "Berkas terlampir",
        "impact": "Dampak",
        "cost_impact": "Dampak biaya",
        "schedule_impact": "Dampak jadwal",
        "yes": "Ya",
        "yes_with": "Ya, {detail}",
        "no": "Tidak",
        "response": "Respons resmi",
        "no_response": "Belum ada respons yang dicatat.",
        "answered_by": "Dijawab oleh",
        "answer_date": "Tanggal jawaban",
        "variation": "Perintah perubahan tertaut",
        "signatures": "Tanda tangan",
        "name": "Nama",
        "signature": "Tanda tangan",
        "date": "Tanggal",
        "footer_generated": "Dibuat {timestamp}",
        "footer_page": "Halaman {page}",
        "date_format": "%d/%m/%Y",
        "datetime_format": "%d/%m/%Y %H:%M UTC",
    },
    "it": {
        "doc_title": "Richiesta di informazioni (RFI)",
        "project": "Progetto",
        "raised_by": "Sollevato da",
        "assigned_to": "Assegnato a",
        "ball_in_court": "In carico a",
        "date_raised": "Data di emissione",
        "response_due": "Risposta entro il",
        "date_required": "Data necessaria",
        "priority": "Priorità",
        "discipline": "Disciplina",
        "question": "Domanda",
        "references": "Documenti di riferimento",
        "references_unavailable": "Documenti collegati non più disponibili: {count}",
        "attachments": "File allegati",
        "impact": "Impatto",
        "cost_impact": "Impatto sui costi",
        "schedule_impact": "Impatto sul programma",
        "yes": "Sì",
        "yes_with": "Sì, {detail}",
        "no": "No",
        "response": "Risposta ufficiale",
        "no_response": "Nessuna risposta registrata finora.",
        "answered_by": "Risposta di",
        "answer_date": "Data della risposta",
        "variation": "Ordine di modifica collegato",
        "signatures": "Firme",
        "name": "Nome e cognome",
        "signature": "Firma",
        "date": "Data",
        "footer_generated": "Generato il {timestamp}",
        "footer_page": "Pagina {page}",
        "date_format": "%d/%m/%Y",
        "datetime_format": "%d/%m/%Y %H:%M UTC",
    },
    "ja": {
        "doc_title": "情報要求書（RFI）",
        "project": "プロジェクト",
        "raised_by": "提起者",
        "assigned_to": "割り当て先",
        "ball_in_court": "担当者",
        "date_raised": "提起日",
        "response_due": "回答期限",
        "date_required": "必要日",
        "priority": "優先度",
        "discipline": "専門分野",
        "question": "質問",
        "references": "参照文書",
        "references_unavailable": "利用できなくなったリンク文書：{count}件",
        "attachments": "添付ファイル",
        "impact": "影響",
        "cost_impact": "コスト影響",
        "schedule_impact": "スケジュール影響",
        "yes": "はい",
        "yes_with": "はい、{detail}",
        "no": "いいえ",
        "response": "公式回答",
        "no_response": "回答はまだ記録されていません。",
        "answered_by": "回答者",
        "answer_date": "回答日",
        "variation": "関連する変更指示書",
        "signatures": "署名",
        "name": "氏名",
        "signature": "署名",
        "date": "日付",
        "footer_generated": "作成日時 {timestamp}",
        "footer_page": "{page} ページ",
        "date_format": "%Y/%m/%d",
        "datetime_format": "%Y/%m/%d %H:%M UTC",
    },
    "kk": {
        "doc_title": "Ақпарат сұрауы (RFI)",
        "project": "Жоба",
        "raised_by": "Көтерген",
        "assigned_to": "Тағайындалды",
        "ball_in_court": "Кезек кімде",
        "date_raised": "Жіберілген күні",
        "response_due": "Жауап беру мерзімі",
        "date_required": "Қажетті күні",
        "priority": "Басымдық",
        "discipline": "Мамандық",
        "question": "Сұрақ",
        "references": "Сілтеме құжаттар",
        "references_unavailable": "Бұдан былай қолжетімсіз байланысты құжаттар: {count}",
        "attachments": "Тіркелген файлдар",
        "impact": "Әсері",
        "cost_impact": "Шығынға әсер",
        "schedule_impact": "Кестеге әсер",
        "yes": "Иә",
        "yes_with": "Иә, {detail}",
        "no": "Жоқ",
        "response": "Ресми жауап",
        "no_response": "Әзірге жауап тіркелмеген.",
        "answered_by": "Жауап берген",
        "answer_date": "Жауап берілген күні",
        "variation": "Байланысты өзгеріс бұйрығы",
        "signatures": "Қолдар",
        "name": "Аты-жөні",
        "signature": "Қолы",
        "date": "Күні",
        "footer_generated": "Құрылған уақыты: {timestamp}",
        "footer_page": "{page}-бет",
        "date_format": "%d.%m.%Y",
        "datetime_format": "%d.%m.%Y %H:%M UTC",
    },
    "ko": {
        "doc_title": "정보 요청서 (RFI)",
        "project": "프로젝트",
        "raised_by": "등록자",
        "assigned_to": "할당 대상",
        "ball_in_court": "담당자",
        "date_raised": "등록일",
        "response_due": "회신 기한",
        "date_required": "필요 일자",
        "priority": "우선순위",
        "discipline": "분야",
        "question": "질문",
        "references": "참조 문서",
        "references_unavailable": "더 이상 사용할 수 없는 연결 문서: {count}건",
        "attachments": "첨부 파일",
        "impact": "영향",
        "cost_impact": "비용 영향",
        "schedule_impact": "일정 영향",
        "yes": "예",
        "yes_with": "예, {detail}",
        "no": "아니요",
        "response": "공식 응답",
        "no_response": "아직 기록된 응답이 없습니다.",
        "answered_by": "응답자",
        "answer_date": "응답일",
        "variation": "연결된 변경 지시서",
        "signatures": "서명",
        "name": "성명",
        "signature": "서명",
        "date": "날짜",
        "footer_generated": "생성 일시 {timestamp}",
        "footer_page": "{page} 페이지",
        "date_format": "%Y. %m. %d.",
        "datetime_format": "%Y. %m. %d. %H:%M UTC",
    },
    "ky": {
        "doc_title": "Маалымат сурамы (RFI)",
        "project": "Долбоор",
        "raised_by": "Жөнөткөн",
        "assigned_to": "Дайындалган",
        "ball_in_court": "Кезек кимде",
        "date_raised": "Жөнөтүлгөн күнү",
        "response_due": "Жооп берүү мөөнөтү",
        "date_required": "Керектүү дата",
        "priority": "Артыкчылык",
        "discipline": "Дисциплина",
        "question": "Суроо",
        "references": "Шилтеме документтер",
        "references_unavailable": "Мындан ары жеткиликсиз байланышкан документтер: {count}",
        "attachments": "Тиркелген файлдар",
        "impact": "Таасир",
        "cost_impact": "Нарктык таасир",
        "schedule_impact": "График таасири",
        "yes": "Ооба",
        "yes_with": "Ооба, {detail}",
        "no": "Жок",
        "response": "Расмий жооп",
        "no_response": "Азырынча жооп катталган жок.",
        "answered_by": "Жооп берген",
        "answer_date": "Жооп берилген күн",
        "variation": "Байланышкан өзгөртүү буйругу",
        "signatures": "Колдор",
        "name": "Аты-жөнү",
        "signature": "Колу",
        "date": "Күнү",
        "footer_generated": "Түзүлгөн: {timestamp}",
        "footer_page": "{page}-бет",
        "date_format": "%d.%m.%Y",
        "datetime_format": "%d.%m.%Y %H:%M UTC",
    },
    "nl": {
        "doc_title": "Informatieverzoek (RFI)",
        "project": "Project",
        "raised_by": "Ingediend door",
        "assigned_to": "Toegewezen aan",
        "ball_in_court": "Aan zet",
        "date_raised": "Datum ingediend",
        "response_due": "Antwoord uiterlijk",
        "date_required": "Vereiste datum",
        "priority": "Prioriteit",
        "discipline": "Discipline",
        "question": "Vraag",
        "references": "Referentiedocumenten",
        "references_unavailable": "Gekoppelde documenten niet meer beschikbaar: {count}",
        "attachments": "Bijgevoegde bestanden",
        "impact": "Impact",
        "cost_impact": "Kostenimpact",
        "schedule_impact": "Planningsimpact",
        "yes": "Ja",
        "yes_with": "Ja, {detail}",
        "no": "Nee",
        "response": "Officieel antwoord",
        "no_response": "Nog geen antwoord vastgelegd.",
        "answered_by": "Beantwoord door",
        "answer_date": "Datum antwoord",
        "variation": "Gekoppelde wijzigingsopdracht",
        "signatures": "Handtekeningen",
        "name": "Naam",
        "signature": "Handtekening",
        "date": "Datum",
        "footer_generated": "Gegenereerd op {timestamp}",
        "footer_page": "Pagina {page}",
        "date_format": "%d-%m-%Y",
        "datetime_format": "%d-%m-%Y %H:%M UTC",
    },
    "no": {
        "doc_title": "Forespørsel om informasjon (RFI)",
        "project": "Prosjekt",
        "raised_by": "Reist av",
        "assigned_to": "Tildelt til",
        "ball_in_court": "Ballen hos",
        "date_raised": "Dato for forespørsel",
        "response_due": "Svarfrist",
        "date_required": "Kreves innen",
        "priority": "Prioritet",
        "discipline": "Disiplin",
        "question": "Spørsmål",
        "references": "Referansedokumenter",
        "references_unavailable": "Koblede dokumenter som ikke lenger er tilgjengelige: {count}",
        "attachments": "Vedlagte filer",
        "impact": "Påvirkning",
        "cost_impact": "Kostnadspåvirkning",
        "schedule_impact": "Tidsplanspåvirkning",
        "yes": "Ja",
        "yes_with": "Ja, {detail}",
        "no": "Nei",
        "response": "Offisielt svar",
        "no_response": "Ingen svar registrert ennå.",
        "answered_by": "Besvart av",
        "answer_date": "Svardato",
        "variation": "Koblet endringsordre",
        "signatures": "Underskrifter",
        "name": "Navn",
        "signature": "Underskrift",
        "date": "Dato",
        "footer_generated": "Generert {timestamp}",
        "footer_page": "Side {page}",
        "date_format": "%d.%m.%Y",
        "datetime_format": "%d.%m.%Y %H:%M UTC",
    },
    "pl": {
        "doc_title": "Zapytanie o informację (RFI)",
        "project": "Projekt",
        "raised_by": "Zgłaszający",
        "assigned_to": "Przydzielone do",
        "ball_in_court": "Strona odpowiedzialna",
        "date_raised": "Data zgłoszenia",
        "response_due": "Termin odpowiedzi",
        "date_required": "Potrzebne do",
        "priority": "Priorytet",
        "discipline": "Branża",
        "question": "Pytanie",
        "references": "Dokumenty powiązane",
        "references_unavailable": "Powiązane dokumenty, które nie są już dostępne: {count}",
        "attachments": "Załączone pliki",
        "impact": "Wpływ",
        "cost_impact": "Wpływ na koszty",
        "schedule_impact": "Wpływ na harmonogram",
        "yes": "Tak",
        "yes_with": "Tak, {detail}",
        "no": "Nie",
        "response": "Oficjalna odpowiedź",
        "no_response": "Nie zarejestrowano jeszcze odpowiedzi.",
        "answered_by": "Odpowiadający",
        "answer_date": "Data odpowiedzi",
        "variation": "Powiązane zlecenie zmiany",
        "signatures": "Podpisy",
        "name": "Imię i nazwisko",
        "signature": "Podpis",
        "date": "Data",
        "footer_generated": "Wygenerowano {timestamp}",
        "footer_page": "Strona {page}",
        "date_format": "%d.%m.%Y",
        "datetime_format": "%d.%m.%Y %H:%M UTC",
    },
    "pt": {
        "doc_title": "Solicitação de esclarecimento (RFI)",
        "project": "Projeto",
        "raised_by": "Submetido por",
        "assigned_to": "Atribuído a",
        "ball_in_court": "Responsável atual",
        "date_raised": "Data de submissão",
        "response_due": "Prazo de resposta",
        "date_required": "Data necessária",
        "priority": "Prioridade",
        "discipline": "Disciplina",
        "question": "Pergunta",
        "references": "Documentos de referência",
        "references_unavailable": "Documentos vinculados indisponíveis: {count}",
        "attachments": "Anexos",
        "impact": "Impacto",
        "cost_impact": "Impacto financeiro",
        "schedule_impact": "Impacto no cronograma",
        "yes": "Sim",
        "yes_with": "Sim, {detail}",
        "no": "Não",
        "response": "Resposta oficial",
        "no_response": "Ainda sem resposta.",
        "answered_by": "Respondido por",
        "answer_date": "Data da resposta",
        "variation": "Ordem de alteração vinculada",
        "signatures": "Assinaturas",
        "name": "Nome",
        "signature": "Assinatura",
        "date": "Data",
        "footer_generated": "Gerado em {timestamp}",
        "footer_page": "Página {page}",
        "date_format": "%d/%m/%Y",
        "datetime_format": "%d/%m/%Y %H:%M UTC",
    },
    "ro": {
        "doc_title": "Solicitare de informații (RFI)",
        "project": "Proiect",
        "raised_by": "Ridicat de",
        "assigned_to": "Atribuit la",
        "ball_in_court": "Responsabil curent",
        "date_raised": "Data emiterii",
        "response_due": "Termen de răspuns",
        "date_required": "Data necesară",
        "priority": "Prioritate",
        "discipline": "Disciplină",
        "question": "Întrebare",
        "references": "Documente de referință",
        "references_unavailable": "Documente legate care nu mai sunt disponibile: {count}",
        "attachments": "Fișiere atașate",
        "impact": "Impact",
        "cost_impact": "Impact asupra costurilor",
        "schedule_impact": "Impact asupra programului",
        "yes": "Da",
        "yes_with": "Da, {detail}",
        "no": "Nu",
        "response": "Răspuns oficial",
        "no_response": "Încă nu a fost înregistrat niciun răspuns.",
        "answered_by": "Autorul răspunsului",
        "answer_date": "Data răspunsului",
        "variation": "Dispoziție de modificare legată",
        "signatures": "Semnături",
        "name": "Nume și prenume",
        "signature": "Semnătură",
        "date": "Data",
        "footer_generated": "Generat la {timestamp}",
        "footer_page": "Pagina {page}",
        "date_format": "%d.%m.%Y",
        "datetime_format": "%d.%m.%Y %H:%M UTC",
    },
    "sv": {
        "doc_title": "Begäran om information (RFI)",
        "project": "Projekt",
        "raised_by": "Väckt av",
        "assigned_to": "Tilldelad till",
        "ball_in_court": "Bollen hos",
        "date_raised": "Datum för begäran",
        "response_due": "Svar senast",
        "date_required": "Krävs senast",
        "priority": "Prioritet",
        "discipline": "Disciplin",
        "question": "Fråga",
        "references": "Referensdokument",
        "references_unavailable": "Länkade dokument som inte längre är tillgängliga: {count}",
        "attachments": "Bifogade filer",
        "impact": "Påverkan",
        "cost_impact": "Kostnadspåverkan",
        "schedule_impact": "Tidplanspåverkan",
        "yes": "Ja",
        "yes_with": "Ja, {detail}",
        "no": "Nej",
        "response": "Officiellt svar",
        "no_response": "Inget svar registrerat ännu.",
        "answered_by": "Besvarad av",
        "answer_date": "Svarsdatum",
        "variation": "Länkad ändringsorder",
        "signatures": "Underskrifter",
        "name": "Namn",
        "signature": "Underskrift",
        "date": "Datum",
        "footer_generated": "Skapad {timestamp}",
        "footer_page": "Sida {page}",
        "date_format": "%Y-%m-%d",
        "datetime_format": "%Y-%m-%d %H:%M UTC",
    },
    "th": {
        "doc_title": "คำขอข้อมูล (RFI)",
        "project": "โครงการ",
        "raised_by": "ส่งโดย",
        "assigned_to": "มอบหมายให้",
        "ball_in_court": "ผู้รับผิดชอบ",
        "date_raised": "วันที่ส่ง",
        "response_due": "กำหนดตอบกลับ",
        "date_required": "วันที่ต้องการ",
        "priority": "ลำดับความสำคัญ",
        "discipline": "สาขาวิชา",
        "question": "คำถาม",
        "references": "เอกสารอ้างอิง",
        "references_unavailable": "เอกสารที่เชื่อมโยงซึ่งไม่มีให้ใช้งานแล้ว: {count}",
        "attachments": "ไฟล์แนบ",
        "impact": "ผลกระทบ",
        "cost_impact": "ผลกระทบต่อต้นทุน",
        "schedule_impact": "ผลกระทบต่อตารางงาน",
        "yes": "ใช่",
        "yes_with": "ใช่ ({detail})",
        "no": "ไม่",
        "response": "การตอบสนองอย่างเป็นทางการ",
        "no_response": "ยังไม่มีการบันทึกคำตอบ",
        "answered_by": "ผู้ตอบ",
        "answer_date": "วันที่ตอบ",
        "variation": "คำสั่งเปลี่ยนแปลงที่เชื่อมโยง",
        "signatures": "ลายมือชื่อ",
        "name": "ชื่อ-นามสกุล",
        "signature": "ลายมือชื่อ",
        "date": "วันที่",
        "footer_generated": "สร้างเมื่อ {timestamp}",
        "footer_page": "หน้า {page}",
        "date_format": "%d/%m/%Y",
        "datetime_format": "%d/%m/%Y %H:%M UTC",
    },
    "tr": {
        "doc_title": "Bilgi Talebi (RFI)",
        "project": "Proje",
        "raised_by": "Oluşturan",
        "assigned_to": "Atanan",
        "ball_in_court": "Sıradaki sorumlu",
        "date_raised": "Oluşturma tarihi",
        "response_due": "Yanıt son tarihi",
        "date_required": "İhtiyaç tarihi",
        "priority": "Öncelik",
        "discipline": "Disiplin",
        "question": "Soru",
        "references": "Referans belgeler",
        "references_unavailable": "Artık erişilemeyen bağlantılı belgeler: {count}",
        "attachments": "Ekli dosyalar",
        "impact": "Etki",
        "cost_impact": "Maliyet etkisi",
        "schedule_impact": "Süre etkisi",
        "yes": "Evet",
        "yes_with": "Evet, {detail}",
        "no": "Hayır",
        "response": "Resmi yanıt",
        "no_response": "Henüz yanıt kaydedilmedi.",
        "answered_by": "Yanıtlayan",
        "answer_date": "Yanıt tarihi",
        "variation": "Bağlantılı değişiklik emri",
        "signatures": "İmzalar",
        "name": "Adı Soyadı",
        "signature": "İmza",
        "date": "Tarih",
        "footer_generated": "Oluşturulma: {timestamp}",
        "footer_page": "Sayfa {page}",
        "date_format": "%d.%m.%Y",
        "datetime_format": "%d.%m.%Y %H:%M UTC",
    },
    "uk": {
        "doc_title": "Запит на інформацію (RFI)",
        "project": "Проєкт",
        "raised_by": "Автор запиту",
        "assigned_to": "Призначено",
        "ball_in_court": "Черга відповіді",
        "date_raised": "Дата запиту",
        "response_due": "Термін відповіді",
        "date_required": "Потрібно до",
        "priority": "Пріоритет",
        "discipline": "Дисципліна",
        "question": "Питання",
        "references": "Пов'язані документи",
        "references_unavailable": "Пов'язані документи більше недоступні: {count}",
        "attachments": "Прикріплені файли",
        "impact": "Вплив",
        "cost_impact": "Вплив на вартість",
        "schedule_impact": "Вплив на графік",
        "yes": "Так",
        "yes_with": "Так, {detail}",
        "no": "Ні",
        "response": "Офіційна відповідь",
        "no_response": "Відповідь ще не отримано.",
        "answered_by": "Автор відповіді",
        "answer_date": "Дата відповіді",
        "variation": "Пов'язане розпорядження про зміни",
        "signatures": "Підписи",
        "name": "ПІБ",
        "signature": "Підпис",
        "date": "Дата",
        "footer_generated": "Сформовано {timestamp}",
        "footer_page": "Стор. {page}",
        "date_format": "%d.%m.%Y",
        "datetime_format": "%d.%m.%Y %H:%M UTC",
    },
    "uz": {
        "doc_title": "Maʼlumot soʻrovi (RFI)",
        "project": "Loyiha",
        "raised_by": "Kim tomonidan koʻtarilgan",
        "assigned_to": "Tayinlangan",
        "ball_in_court": "Navbat kimda",
        "date_raised": "Soʻrov sanasi",
        "response_due": "Javob muddati",
        "date_required": "Qachongacha kerak",
        "priority": "Ustuvorlik",
        "discipline": "Yoʻnalish",
        "question": "Savol",
        "references": "Havola hujjatlar",
        "references_unavailable": "Endi mavjud boʻlmagan bogʻlangan hujjatlar: {count}",
        "attachments": "Biriktirilgan fayllar",
        "impact": "Taʼsir",
        "cost_impact": "Xarajat taʼsiri",
        "schedule_impact": "Jadval taʼsiri",
        "yes": "Ha",
        "yes_with": "Ha, {detail}",
        "no": "Yoʻq",
        "response": "Rasmiy javob",
        "no_response": "Hozircha javob qayd etilmagan.",
        "answered_by": "Javob bergan",
        "answer_date": "Javob sanasi",
        "variation": "Bogʻlangan oʻzgartirish buyrugʻi",
        "signatures": "Imzolar",
        "name": "F.I.Sh.",
        "signature": "Imzo",
        "date": "Sana",
        "footer_generated": "Yaratilgan: {timestamp}",
        "footer_page": "{page}-sahifa",
        "date_format": "%d.%m.%Y",
        "datetime_format": "%d.%m.%Y %H:%M UTC",
    },
    "vi": {
        "doc_title": "Yêu cầu thông tin (RFI)",
        "project": "Dự án",
        "raised_by": "Được nêu bởi",
        "assigned_to": "Được giao cho",
        "ball_in_court": "Bên phụ trách",
        "date_raised": "Ngày gửi",
        "response_due": "Hạn trả lời",
        "date_required": "Ngày cần thiết",
        "priority": "Ưu tiên",
        "discipline": "Bộ môn",
        "question": "Câu hỏi",
        "references": "Tài liệu tham chiếu",
        "references_unavailable": "Tài liệu liên kết không còn khả dụng: {count}",
        "attachments": "Tệp đính kèm",
        "impact": "Tác động",
        "cost_impact": "Tác động chi phí",
        "schedule_impact": "Tác động tiến độ",
        "yes": "Có",
        "yes_with": "Có, {detail}",
        "no": "Không",
        "response": "Phản hồi chính thức",
        "no_response": "Chưa có phản hồi nào được ghi nhận.",
        "answered_by": "Người trả lời",
        "answer_date": "Ngày trả lời",
        "variation": "Lệnh thay đổi liên kết",
        "signatures": "Chữ ký",
        "name": "Họ và tên",
        "signature": "Chữ ký",
        "date": "Ngày",
        "footer_generated": "Tạo lúc {timestamp}",
        "footer_page": "Trang {page}",
        "date_format": "%d/%m/%Y",
        "datetime_format": "%d/%m/%Y %H:%M UTC",
    },
    "zh": {
        "doc_title": "信息申请单（RFI）",
        "project": "项目",
        "raised_by": "提出人",
        "assigned_to": "分配给",
        "ball_in_court": "当前负责方",
        "date_raised": "提出日期",
        "response_due": "答复截止日期",
        "date_required": "需求日期",
        "priority": "优先级",
        "discipline": "专业",
        "question": "问题",
        "references": "参考文件",
        "references_unavailable": "已不可用的关联文件：{count}",
        "attachments": "附件",
        "impact": "影响",
        "cost_impact": "费用影响",
        "schedule_impact": "进度影响",
        "yes": "是",
        "yes_with": "是，{detail}",
        "no": "否",
        "response": "官方响应",
        "no_response": "尚无答复记录。",
        "answered_by": "答复人",
        "answer_date": "答复日期",
        "variation": "关联变更单",
        "signatures": "签字",
        "name": "姓名",
        "signature": "签名",
        "date": "日期",
        "footer_generated": "生成于 {timestamp}",
        "footer_page": "第 {page} 页",
        "date_format": "%Y-%m-%d",
        "datetime_format": "%Y-%m-%d %H:%M UTC",
    },
}

_PRIORITY_LABELS: dict[str, dict[str, str]] = {
    "en": {"low": "Low", "normal": "Normal", "high": "High", "critical": "Critical"},
    "de": {"low": "Niedrig", "normal": "Normal", "high": "Hoch", "critical": "Kritisch"},
    "ru": {"low": "Низкий", "normal": "Обычный", "high": "Высокий", "critical": "Критический"},
    "bg": {"low": "Нисък", "normal": "Нормален", "high": "Висок", "critical": "Критичен"},
    "cs": {"low": "Nízká", "normal": "Normální", "high": "Vysoká", "critical": "Kritická"},
    "da": {"low": "Lav", "normal": "Normal", "high": "Høj", "critical": "Kritisk"},
    "el": {"low": "Χαμηλή", "normal": "Κανονική", "high": "Υψηλή", "critical": "Κρίσιμη"},
    "es": {"low": "Baja", "normal": "Normal", "high": "Alta", "critical": "Crítica"},
    "et": {"low": "Madal", "normal": "Tavaline", "high": "Kõrge", "critical": "Kriitiline"},
    "fi": {"low": "Matala", "normal": "Normaali", "high": "Korkea", "critical": "Kriittinen"},
    "fil": {"low": "Mababa", "normal": "Karaniwan", "high": "Mataas", "critical": "Kritikal"},
    "fr": {"low": "Faible", "normal": "Normale", "high": "Élevée", "critical": "Critique"},
    "hi": {"low": "निम्न", "normal": "सामान्य", "high": "उच्च", "critical": "गंभीर"},
    "hr": {"low": "Nizak", "normal": "Normalan", "high": "Visok", "critical": "Kritičan"},
    "hu": {"low": "Alacsony", "normal": "Normál", "high": "Magas", "critical": "Kritikus"},
    "id": {"low": "Rendah", "normal": "Normal", "high": "Tinggi", "critical": "Kritis"},
    "it": {"low": "Bassa", "normal": "Normale", "high": "Alta", "critical": "Critica"},
    "ja": {"low": "低", "normal": "通常", "high": "高", "critical": "緊急"},
    "kk": {"low": "Төмен", "normal": "Қалыпты", "high": "Жоғары", "critical": "Сыни"},
    "ko": {"low": "낮음", "normal": "보통", "high": "높음", "critical": "긴급"},
    "ky": {"low": "Төмөн", "normal": "Кадимки", "high": "Жогорку", "critical": "Өтө маанилүү"},
    "nl": {"low": "Laag", "normal": "Normaal", "high": "Hoog", "critical": "Kritiek"},
    "no": {"low": "Lav", "normal": "Normal", "high": "Høy", "critical": "Kritisk"},
    "pl": {"low": "Niski", "normal": "Normalny", "high": "Wysoki", "critical": "Krytyczny"},
    "pt": {"low": "Baixa", "normal": "Normal", "high": "Alta", "critical": "Crítica"},
    "ro": {"low": "Scăzută", "normal": "Normală", "high": "Ridicată", "critical": "Critică"},
    "sv": {"low": "Låg", "normal": "Normal", "high": "Hög", "critical": "Kritisk"},
    "th": {"low": "ต่ำ", "normal": "ปกติ", "high": "สูง", "critical": "วิกฤต"},
    "tr": {"low": "Düşük", "normal": "Normal", "high": "Yüksek", "critical": "Kritik"},
    "uk": {"low": "Низький", "normal": "Звичайний", "high": "Високий", "critical": "Критичний"},
    "uz": {"low": "Past", "normal": "Oddiy", "high": "Yuqori", "critical": "Kritik"},
    "vi": {"low": "Thấp", "normal": "Bình thường", "high": "Cao", "critical": "Khẩn cấp"},
    "zh": {"low": "低", "normal": "普通", "high": "高", "critical": "紧急"},
}

# -- Day counts ---------------------------------------------------------------
#
# A plural rule maps a count to a CLDR category name; the day table maps each
# category a language uses to a template. Languages without grammatical
# number after a numeral (Chinese, Japanese, Korean, Thai, Vietnamese,
# Indonesian, Hungarian, Turkish, the Turkic languages, Filipino, Hindi) use
# the "other" template for every count.


def _rule_other(_n: int) -> str:
    return "other"


def _rule_one_other(n: int) -> str:
    return "one" if n == 1 else "other"


def _rule_french(n: int) -> str:
    # French counts zero as singular: "0 jour".
    return "one" if n in (0, 1) else "other"


def _rule_east_slavic(n: int) -> str:
    # Russian, Ukrainian and Croatian: 1, 21, 31 take "one"; 2-4, 22-24 "few";
    # the teens and everything else "many".
    tail10, tail100 = n % 10, n % 100
    if tail10 == 1 and tail100 != 11:
        return "one"
    if 2 <= tail10 <= 4 and not 12 <= tail100 <= 14:
        return "few"
    return "many"


def _rule_polish(n: int) -> str:
    # Polish keeps "one" for exactly 1; 21 is "many", unlike Russian.
    if n == 1:
        return "one"
    tail10, tail100 = n % 10, n % 100
    if 2 <= tail10 <= 4 and not 12 <= tail100 <= 14:
        return "few"
    return "many"


def _rule_czech(n: int) -> str:
    if n == 1:
        return "one"
    if 2 <= n <= 4:
        return "few"
    return "other"


def _rule_romanian(n: int) -> str:
    # Romanian inserts "de" once the last two digits reach 20: "19 zile" but
    # "20 de zile" and "101 zile".
    if n == 1:
        return "one"
    if n == 0 or 1 <= n % 100 <= 19:
        return "few"
    return "other"


_PLURAL_RULES: dict[str, Callable[[int], str]] = {
    "en": _rule_one_other,
    "de": _rule_one_other,
    "ru": _rule_east_slavic,
    "bg": _rule_one_other,
    "cs": _rule_czech,
    "da": _rule_one_other,
    "el": _rule_one_other,
    "es": _rule_one_other,
    "et": _rule_one_other,
    "fi": _rule_one_other,
    "fil": _rule_other,
    "fr": _rule_french,
    "hi": _rule_other,
    "hr": _rule_east_slavic,
    "hu": _rule_other,
    "id": _rule_other,
    "it": _rule_one_other,
    "ja": _rule_other,
    "kk": _rule_other,
    "ko": _rule_other,
    "ky": _rule_other,
    "nl": _rule_one_other,
    "no": _rule_one_other,
    "pl": _rule_polish,
    "pt": _rule_one_other,
    "ro": _rule_romanian,
    "sv": _rule_one_other,
    "th": _rule_other,
    "tr": _rule_other,
    "uk": _rule_east_slavic,
    "uz": _rule_other,
    "vi": _rule_other,
    "zh": _rule_other,
}

_DAY_FORMS: dict[str, dict[str, str]] = {
    "en": {"one": "{n} day", "other": "{n} days"},
    "de": {"one": "{n} Tag", "other": "{n} Tage"},
    "ru": {"one": "{n} день", "few": "{n} дня", "many": "{n} дней"},
    "bg": {"one": "{n} ден", "other": "{n} дни"},
    "cs": {"one": "{n} den", "few": "{n} dny", "other": "{n} dní"},
    "da": {"one": "{n} dag", "other": "{n} dage"},
    "el": {"one": "{n} ημέρα", "other": "{n} ημέρες"},
    "es": {"one": "{n} día", "other": "{n} días"},
    # Estonian and Finnish put the noun after a numeral in the partitive
    # singular, not the nominative plural.
    "et": {"one": "{n} päev", "other": "{n} päeva"},
    "fi": {"one": "{n} päivä", "other": "{n} päivää"},
    "fil": {"other": "{n} araw"},
    "fr": {"one": "{n} jour", "other": "{n} jours"},
    "hi": {"other": "{n} दिन"},
    "hr": {"one": "{n} dan", "few": "{n} dana", "many": "{n} dana"},
    "hu": {"other": "{n} nap"},
    "id": {"other": "{n} hari"},
    "it": {"one": "{n} giorno", "other": "{n} giorni"},
    "ja": {"other": "{n}日"},
    "kk": {"other": "{n} күн"},
    "ko": {"other": "{n}일"},
    "ky": {"other": "{n} күн"},
    "nl": {"one": "{n} dag", "other": "{n} dagen"},
    "no": {"one": "{n} dag", "other": "{n} dager"},
    "pl": {"one": "{n} dzień", "few": "{n} dni", "many": "{n} dni"},
    "pt": {"one": "{n} dia", "other": "{n} dias"},
    "ro": {"one": "{n} zi", "few": "{n} zile", "other": "{n} de zile"},
    "sv": {"one": "{n} dag", "other": "{n} dagar"},
    "th": {"other": "{n} วัน"},
    "tr": {"other": "{n} gün"},
    "uk": {"one": "{n} день", "few": "{n} дні", "many": "{n} днів"},
    "uz": {"other": "{n} kun"},
    "vi": {"other": "{n} ngày"},
    "zh": {"other": "{n}天"},
}


def normalize_pdf_locale(value: str | None) -> str:
    """Reduce a locale-ish value to a supported primary subtag.

    Args:
        value: A locale code such as ``"de"``, ``"de-DE"`` or ``"DE"``.
            ``None`` and unsupported values normalise to ``"en"``.

    Returns:
        A member of :data:`SUPPORTED_PDF_LOCALES`.
    """
    return normalize_document_locale(value, SUPPORTED_PDF_LOCALES, DEFAULT_PDF_LOCALE)


def resolve_pdf_locale(locale_param: str | None, accept_language: str | None) -> str:
    """Pick the PDF language for an HTTP request.

    See :func:`app.core.document_locale.resolve_document_locale` for the rule.
    When this returns ``"en"`` for a reader who asked for something else, the
    route must declare ``Content-Language: en`` so the fallback is visible.

    Args:
        locale_param: Explicit ``?locale=`` query value, if any.
        accept_language: Raw ``Accept-Language`` header value, if any.

    Returns:
        A member of :data:`SUPPORTED_PDF_LOCALES`.
    """
    return resolve_document_locale(locale_param, accept_language, SUPPORTED_PDF_LOCALES, DEFAULT_PDF_LOCALE)


def tr(locale: str, key: str, **params: Any) -> str:
    """Resolve ``key`` for ``locale``, falling back to English, then the key.

    Args:
        locale: A locale code; a regional one such as ``de-AT`` reads its
            language's table, an unknown one the English table.
        key: Catalog key, e.g. ``"question"``.
        **params: ``str.format`` interpolation values.

    Returns:
        The resolved, formatted string.
    """
    return translate(_STRINGS, normalize_pdf_locale(locale), key, DEFAULT_PDF_LOCALE, **params)


def priority_label(priority: str | None, locale: str) -> str:
    """Priority label in the document language; an unknown value passes through."""
    key = (priority or "").strip().lower()
    table = _PRIORITY_LABELS[normalize_pdf_locale(locale)]
    return table.get(key) or _PRIORITY_LABELS[DEFAULT_PDF_LOCALE].get(key) or (priority or "")


def status_caps(label: str, locale: str) -> str:
    """Upper-case a status word the way the language writes capitals.

    ``str.upper`` is right for most languages and wrong for two on this list.
    Turkish keeps the dot on a capital i ("Geçersiz" is "GEÇERSİZ", not
    "GEÇERSIZ"), and Greek drops the stress accent in all capitals ("Ανοιχτό"
    is "ΑΝΟΙΧΤΟ").

    Args:
        label: The localised status word.
        locale: A supported PDF locale.

    Returns:
        The word in capitals.
    """
    locale = normalize_pdf_locale(locale)
    if locale == "tr":
        return label.replace("i", "İ").upper()
    upper = label.upper()
    if locale == "el":
        stripped = "".join(ch for ch in unicodedata.normalize("NFD", upper) if ch != "́")
        return unicodedata.normalize("NFC", stripped)
    return upper


def days_text(count: int, locale: str) -> str:
    """A number of days with the noun in the form the language needs.

    Russian picks between three forms by the last digits (1 день, 3 дня,
    5 дней, 11 дней, 21 день), Polish, Czech, Ukrainian, Croatian and
    Romanian have rules of their own, Finnish and Estonian use the partitive
    after a numeral, and several languages take no plural at all, so the
    count cannot be glued to one word the way English and German allow.

    Args:
        count: The number of days.
        locale: A supported PDF locale.

    Returns:
        The count with the noun, e.g. ``"3 days"``, ``"3 дня"`` or ``"3日"``.
    """
    locale = normalize_pdf_locale(locale)
    forms = _DAY_FORMS[locale]
    category = _PLURAL_RULES[locale](abs(count))
    template = forms.get(category) or forms["other"]
    return template.format(n=count)


def page_of_total(page: int, total: int, locale: str) -> str:
    """ "Page 2 of 5" for the footer, in the document language.

    The form is translated into thirty-three languages and each has its own
    "Page {page}" phrase. English and Turkish, the two languages the site
    registers print in, use the registers' own phrase so the whole set of a
    project carries one footer. Every other language keeps its phrase and
    gets the total after a slash, which reads the same in all of them and
    needs no thirty-three new translations.
    """
    shared = register_export.FURNITURE.get(normalize_pdf_locale(locale))
    if shared is not None:
        return shared["footer_page"].format(page=page, total=total)
    return f"{tr(locale, 'footer_page', page=page)} / {total}"


def format_date(value: date | datetime | str | None, locale: str, date_format: str | None = None) -> str:
    """Render a stored date in the locale's format, or a dash when absent.

    The RFI keeps its dates in three shapes: ``created_at`` is a timestamp,
    ``date_required`` a ``YYYY-MM-DD`` string, and ``responded_at`` /
    ``response_due_date`` either of the two, depending on which code path
    wrote them. Only the calendar date is printed. A value that parses as
    neither is returned as stored, so a malformed row still renders.

    Args:
        value: The stored value.
        locale: A supported PDF locale.
        date_format: A ``strftime`` pattern that overrides the language's
            own, for a caller that knows the project's country.

    Returns:
        The formatted date, the raw value when unparseable, or ``"-"``.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return "-"
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text).date()
        except ValueError:
            try:
                parsed = date.fromisoformat(text[:10])
            except ValueError:
                return text
    return parsed.strftime(date_format or tr(locale, "date_format"))


def rfi_pdf_filename(rfi_number: str | None) -> str:
    """Download filename for one RFI, e.g. ``RFI-007.pdf``.

    Everything outside letters, digits, dot, dash and underscore becomes an
    underscore, so a number typed with a slash or a space still gives a name
    every operating system accepts.
    """
    stem = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in (rfi_number or "").strip())
    return f"{stem or 'rfi'}.pdf"
