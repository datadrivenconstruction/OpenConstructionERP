# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalogue for the invitation-to-tender email.

The email goes to a subcontractor outside the platform, so it is written in
the project's language (``Project.locale``) rather than in the language of
whoever pressed "send". The catalogue sits next to the module like the other
module-owned documents (``rfi/pdf_translations.py``) and resolves through the
shared :func:`app.core.document_locale.translate`, which falls back to English
key by key. A locale the catalogue does not carry reads English.

Values are plain text. The renderer escapes every value it interpolates and
adds the markup around them, so a translation never carries HTML.
"""

from __future__ import annotations

import html

from app.core.document_locale import normalize_document_locale, translate

DEFAULT_LOCALE = "en"

_TABLES: dict[str, dict[str, str]] = {
    "en": {
        "subject": "Invitation to tender: {package}",
        "heading": "Invitation to tender",
        "greeting": "Dear {company},",
        "greeting_generic": "Dear Sir or Madam,",
        "invite": "You are invited to submit a bid for the tender package {package}.",
        "invite_project": "You are invited to submit a bid for the tender package {package} for the project {project}.",
        "deadline": "Submission deadline: {deadline}",
        "link_help": (
            "The button below opens the bill of quantities. Enter your unit prices online, "
            "save a draft whenever you like and submit before the deadline. No account is needed."
        ),
        "link_personal": "This link is personal to your company. Please do not forward it.",
        "cta": "Open the bill and enter prices",
        "no_link": "Please review the package details and respond with your offer before the deadline above.",
    },
    "de": {
        "subject": "Aufforderung zur Angebotsabgabe: {package}",
        "heading": "Aufforderung zur Angebotsabgabe",
        "greeting": "Sehr geehrte Damen und Herren der Firma {company},",
        "greeting_generic": "Sehr geehrte Damen und Herren,",
        "invite": "Sie sind eingeladen, ein Angebot für das Vergabepaket {package} abzugeben.",
        "invite_project": "Sie sind eingeladen, ein Angebot für das Vergabepaket {package} im Projekt {project} abzugeben.",
        "deadline": "Angebotsfrist: {deadline}",
        "link_help": (
            "Über die Schaltfläche unten öffnen Sie das Leistungsverzeichnis. Tragen Sie Ihre "
            "Einheitspreise online ein, speichern Sie jederzeit einen Entwurf und geben Sie Ihr "
            "Angebot vor Ablauf der Frist ab. Ein Benutzerkonto ist nicht erforderlich."
        ),
        "link_personal": "Dieser Link ist nur für Ihr Unternehmen bestimmt. Bitte leiten Sie ihn nicht weiter.",
        "cta": "Leistungsverzeichnis öffnen und Preise eintragen",
        "no_link": "Bitte prüfen Sie die Unterlagen und senden Sie uns Ihr Angebot vor Ablauf der oben genannten Frist.",
    },
    "fr": {
        "subject": "Appel d'offres : {package}",
        "heading": "Appel d'offres",
        "greeting": "Madame, Monsieur ({company}),",
        "greeting_generic": "Madame, Monsieur,",
        "invite": "Vous êtes invité à remettre une offre pour le lot {package}.",
        "invite_project": "Vous êtes invité à remettre une offre pour le lot {package} du projet {project}.",
        "deadline": "Date limite de remise des offres : {deadline}",
        "link_help": (
            "Le bouton ci-dessous ouvre le bordereau des prix. Saisissez vos prix unitaires en ligne, "
            "enregistrez un brouillon quand vous le souhaitez et remettez votre offre avant la date "
            "limite. Aucun compte n'est nécessaire."
        ),
        "link_personal": "Ce lien est réservé à votre entreprise. Merci de ne pas le transférer.",
        "cta": "Ouvrir le bordereau et saisir les prix",
        "no_link": "Merci d'examiner le dossier et de nous transmettre votre offre avant la date limite indiquée.",
    },
    "es": {
        "subject": "Invitación a licitar: {package}",
        "heading": "Invitación a licitar",
        "greeting": "Estimados señores de {company}:",
        "greeting_generic": "Estimados señores:",
        "invite": "Les invitamos a presentar una oferta para el paquete de licitación {package}.",
        "invite_project": "Les invitamos a presentar una oferta para el paquete de licitación {package} del proyecto {project}.",
        "deadline": "Plazo de presentación: {deadline}",
        "link_help": (
            "El botón de abajo abre el presupuesto con las mediciones. Introduzca sus precios unitarios "
            "en línea, guarde un borrador cuando quiera y envíe su oferta antes del plazo. No necesita "
            "una cuenta."
        ),
        "link_personal": "Este enlace es personal para su empresa. Por favor, no lo reenvíe.",
        "cta": "Abrir el presupuesto e introducir precios",
        "no_link": "Revisen la documentación y envíennos su oferta antes del plazo indicado.",
    },
    "it": {
        "subject": "Invito a presentare offerta: {package}",
        "heading": "Invito a presentare offerta",
        "greeting": "Spettabile {company},",
        "greeting_generic": "Gentili Signori,",
        "invite": "Siete invitati a presentare un'offerta per il pacchetto di gara {package}.",
        "invite_project": "Siete invitati a presentare un'offerta per il pacchetto di gara {package} del progetto {project}.",
        "deadline": "Termine di presentazione: {deadline}",
        "link_help": (
            "Il pulsante qui sotto apre il computo. Inserite i vostri prezzi unitari online, salvate "
            "una bozza quando volete e inviate l'offerta entro il termine. Non serve un account."
        ),
        "link_personal": "Questo link è riservato alla vostra azienda. Vi preghiamo di non inoltrarlo.",
        "cta": "Apri il computo e inserisci i prezzi",
        "no_link": "Vi preghiamo di esaminare la documentazione e di inviarci la vostra offerta entro il termine indicato.",
    },
    "nl": {
        "subject": "Uitnodiging tot inschrijving: {package}",
        "heading": "Uitnodiging tot inschrijving",
        "greeting": "Geachte heer, mevrouw van {company},",
        "greeting_generic": "Geachte heer, mevrouw,",
        "invite": "U wordt uitgenodigd een offerte in te dienen voor het aanbestedingspakket {package}.",
        "invite_project": "U wordt uitgenodigd een offerte in te dienen voor het aanbestedingspakket {package} van het project {project}.",
        "deadline": "Uiterste inschrijfdatum: {deadline}",
        "link_help": (
            "Met de knop hieronder opent u de staat van hoeveelheden. Vul uw eenheidsprijzen online in, "
            "sla een concept op wanneer u wilt en dien uw offerte voor de uiterste datum in. Een "
            "account is niet nodig."
        ),
        "link_personal": "Deze link is persoonlijk voor uw bedrijf. Stuur hem alstublieft niet door.",
        "cta": "Staat openen en prijzen invullen",
        "no_link": "Bekijk de stukken en stuur ons uw offerte voor de bovengenoemde uiterste datum.",
    },
    "pl": {
        "subject": "Zaproszenie do składania ofert: {package}",
        "heading": "Zaproszenie do składania ofert",
        "greeting": "Szanowni Państwo ({company}),",
        "greeting_generic": "Szanowni Państwo,",
        "invite": "Zapraszamy do złożenia oferty na pakiet przetargowy {package}.",
        "invite_project": "Zapraszamy do złożenia oferty na pakiet przetargowy {package} w projekcie {project}.",
        "deadline": "Termin składania ofert: {deadline}",
        "link_help": (
            "Przycisk poniżej otwiera przedmiar robót. Wpisz ceny jednostkowe online, zapisuj wersję "
            "roboczą w dowolnym momencie i złóż ofertę przed terminem. Konto nie jest potrzebne."
        ),
        "link_personal": "Ten link jest przeznaczony wyłącznie dla Państwa firmy. Prosimy go nie przekazywać.",
        "cta": "Otwórz przedmiar i wpisz ceny",
        "no_link": "Prosimy o zapoznanie się z dokumentacją i przesłanie oferty przed podanym terminem.",
    },
    "pt": {
        "subject": "Convite para apresentação de proposta: {package}",
        "heading": "Convite para apresentação de proposta",
        "greeting": "Prezados senhores da {company},",
        "greeting_generic": "Prezados senhores,",
        "invite": "Convidamos a apresentar uma proposta para o pacote de concurso {package}.",
        "invite_project": "Convidamos a apresentar uma proposta para o pacote de concurso {package} do projeto {project}.",
        "deadline": "Prazo de entrega: {deadline}",
        "link_help": (
            "O botão abaixo abre o mapa de quantidades. Introduza os seus preços unitários online, "
            "guarde um rascunho quando quiser e submeta a proposta antes do prazo. Não é necessária "
            "uma conta."
        ),
        "link_personal": "Este link é pessoal para a sua empresa. Por favor, não o reencaminhe.",
        "cta": "Abrir o mapa e introduzir preços",
        "no_link": "Analise a documentação e envie-nos a sua proposta antes do prazo indicado.",
    },
    "cs": {
        "subject": "Výzva k podání nabídky: {package}",
        "heading": "Výzva k podání nabídky",
        "greeting": "Vážení ({company}),",
        "greeting_generic": "Vážení,",
        "invite": "Zveme vás k podání nabídky na balíček zakázky {package}.",
        "invite_project": "Zveme vás k podání nabídky na balíček zakázky {package} v projektu {project}.",
        "deadline": "Lhůta pro podání nabídek: {deadline}",
        "link_help": (
            "Tlačítko níže otevře výkaz výměr. Zadejte jednotkové ceny online, kdykoli uložte koncept "
            "a nabídku odešlete před uplynutím lhůty. Účet není potřeba."
        ),
        "link_personal": "Tento odkaz je určen pouze vaší firmě. Prosíme, nepřeposílejte jej.",
        "cta": "Otevřít výkaz a zadat ceny",
        "no_link": "Prosíme, prostudujte podklady a zašlete nám nabídku před uvedenou lhůtou.",
    },
    "ru": {
        "subject": "Приглашение к участию в тендере: {package}",
        "heading": "Приглашение к участию в тендере",
        "greeting": "Уважаемые коллеги из {company}!",
        "greeting_generic": "Уважаемые коллеги!",
        "invite": "Приглашаем вас подать предложение по тендерному пакету {package}.",
        "invite_project": "Приглашаем вас подать предложение по тендерному пакету {package} проекта {project}.",
        "deadline": "Срок подачи предложений: {deadline}",
        "link_help": (
            "Кнопка ниже открывает ведомость объёмов работ. Укажите единичные расценки онлайн, "
            "сохраняйте черновик в любой момент и отправьте предложение до окончания срока. "
            "Учётная запись не нужна."
        ),
        "link_personal": "Эта ссылка предназначена только для вашей компании. Пожалуйста, не пересылайте её.",
        "cta": "Открыть ведомость и указать цены",
        "no_link": "Пожалуйста, ознакомьтесь с документацией и пришлите предложение до указанного срока.",
    },
}

#: Languages the email can be written in.
SUPPORTED_LOCALES: tuple[str, ...] = tuple(_TABLES)


def email_locale(project_locale: str | None) -> str:
    """The catalogue language for a project's locale (``pt-BR`` reads ``pt``)."""
    return normalize_document_locale(project_locale, SUPPORTED_LOCALES, DEFAULT_LOCALE)


def _t(locale: str, key: str, **params: str) -> str:
    return translate(_TABLES, locale, key, DEFAULT_LOCALE, **params)


def invitation_subject(locale: str, package_name: str) -> str:
    """The email subject line (plain text, no escaping)."""
    return _t(locale, "subject", package=package_name)


def invitation_html(
    *,
    locale: str,
    company_name: str,
    package_name: str,
    project_name: str,
    description: str,
    deadline: str,
    custom_message: str | None,
    action_url: str,
) -> str:
    """Render the invitation body through the shared email shell."""
    from app.core.email import wrap

    def strong(value: str) -> str:
        return f"<strong>{html.escape(value)}</strong>"

    # Escape the template text and splice the already-escaped, marked-up
    # values in afterwards, so neither a translation nor a package name can
    # inject markup.
    def sentence(key: str, **values: str) -> str:
        marks = {name: f"\x00{name}\x00" for name in values}
        text = html.escape(_t(locale, key, **marks))
        for name, value in values.items():
            text = text.replace(f"\x00{name}\x00", value)
        return text

    parts: list[str] = []
    if company_name:
        parts.append(f"<p>{sentence('greeting', company=html.escape(company_name))}</p>")
    else:
        parts.append(f"<p>{sentence('greeting_generic')}</p>")
    if project_name:
        parts.append(f"<p>{sentence('invite_project', package=strong(package_name), project=strong(project_name))}</p>")
    else:
        parts.append(f"<p>{sentence('invite', package=strong(package_name))}</p>")
    if description:
        parts.append(
            "<blockquote style='border-left:3px solid #0071e3; padding-left:12px; "
            f"margin:12px 0; color:#1d1d1f;'>{html.escape(description)}</blockquote>"
        )
    if deadline:
        parts.append(f"<p>{sentence('deadline', deadline=strong(deadline))}</p>")
    if custom_message:
        parts.append(
            "<blockquote style='border-left:3px solid #86868b; padding-left:12px; "
            f"margin:12px 0; color:#444;'>{html.escape(custom_message)}</blockquote>"
        )
    # The shared shell interpolates title, link and label as given.
    heading = html.escape(_t(locale, "heading"))
    if action_url:
        parts.append(f"<p>{sentence('link_help')}</p>")
        parts.append(f"<p style='font-size:13px; color:#6e6e73;'>{sentence('link_personal')}</p>")
        return wrap(heading, "".join(parts), html.escape(action_url, quote=True), html.escape(_t(locale, "cta")))
    parts.append(f"<p style='font-size:13px; color:#6e6e73;'>{sentence('no_link')}</p>")
    return wrap(heading, "".join(parts))
