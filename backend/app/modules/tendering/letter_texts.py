# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Editable wording of the tendering letters, and the labels around it.

Three letters are registered with :mod:`app.core.letter_templates`:

* ``tendering.award_letter`` - the letter of award (PDF);
* ``tendering.rejection_letter`` - the notice to an unsuccessful bidder (PDF);
* ``tendering.invitation_email`` - the invitation to tender (email).

The defaults are business-letter wording for a private client. They make no
statutory statement (no standstill period, no procurement-law citation): a
public-procurement variant belongs in a country pack as its own template key.
The fixed labels printed around the text (``Project:``, ``Date:``) are not
editable and live in :data:`_LABELS`.
"""

from __future__ import annotations

from app.core.document_locale import translate
from app.core.letter_templates import (
    LetterTemplate,
    LetterText,
    Placeholder,
    get_template,
    register_template,
)

AWARD_KEY = "tendering.award_letter"
REJECTION_KEY = "tendering.rejection_letter"
INVITATION_KEY = "tendering.invitation_email"

_COMMON = (
    Placeholder("bidder", "Example Builders Ltd"),
    Placeholder("project", "Riverside Residential, Block A"),
    Placeholder("company", "Example Developer Ltd"),
)

AWARD_PLACEHOLDERS = (
    *_COMMON,
    Placeholder("package", "Concrete and reinforcement works", required=True),
    Placeholder("amount", "1,284,500.00 EUR", required=True),
    Placeholder("award_date", "12.11.2026"),
    Placeholder("sender", "Jane Smith"),
)
REJECTION_PLACEHOLDERS = (
    *_COMMON,
    Placeholder("package", "Concrete and reinforcement works", required=True),
    Placeholder("date", "12.11.2026"),
    Placeholder("sender", "Jane Smith"),
)
INVITATION_PLACEHOLDERS = (
    *_COMMON,
    Placeholder("package", "Concrete and reinforcement works", required=True),
    Placeholder("deadline", "30.11.2026", required=True),
)

# ── Award letter ────────────────────────────────────────────────────────────

AWARD_DEFAULTS: dict[str, LetterText] = {
    "en": LetterText(
        subject="Letter of award: {package}",
        heading="Notification of Contract Award",
        body=(
            "Dear {bidder},\n\n"
            "We are pleased to inform you that, following evaluation of the bids received for the tender "
            "package {package} on the project {project}, your offer has been selected as the successful bid. "
            "The award is made for the contract sum of {amount}, subject to the terms of the tender documents "
            "and any agreed clarifications.\n\n"
            "Please treat this letter as formal notification of our intention to enter into a contract with "
            "you. Our team will be in touch to formalise the contract documentation and confirm the programme."
        ),
        closing="Yours faithfully,",
    ),
    "de": LetterText(
        subject="Auftragserteilung: {package}",
        heading="Auftragserteilung",
        body=(
            "Sehr geehrte Damen und Herren,\n\n"
            "wir bedanken uns für Ihr Angebot zum Vergabepaket {package} im Bauvorhaben {project}. Nach "
            "Prüfung und Wertung der eingegangenen Angebote erteilen wir Ihnen hiermit den Auftrag zu einer "
            "Auftragssumme von {amount}.\n\n"
            "Grundlage des Auftrags sind die Vergabeunterlagen und Ihr Angebot einschließlich der "
            "vereinbarten Aufklärungen. Wir setzen uns in Kürze mit Ihnen in Verbindung, um die "
            "Vertragsunterlagen abzuschließen und die Ausführungstermine abzustimmen.\n\n"
            "Bitte bestätigen Sie uns den Eingang dieses Schreibens."
        ),
        closing="Mit freundlichen Grüßen",
    ),
    "fr": LetterText(
        subject="Notification d'attribution : {package}",
        heading="Notification d'attribution du marché",
        body=(
            "Madame, Monsieur,\n\n"
            "Nous avons le plaisir de vous informer qu'à l'issue de l'analyse des offres reçues pour le lot "
            "{package} du projet {project}, votre offre a été retenue. Le marché vous est attribué pour un "
            "montant de {amount}, conformément aux pièces de la consultation et aux précisions convenues.\n\n"
            "Le présent courrier vaut notification de notre intention de conclure le marché avec vous. Nous "
            "reviendrons vers vous pour finaliser les pièces contractuelles et arrêter le planning."
        ),
        closing="Veuillez agréer, Madame, Monsieur, l'expression de nos salutations distinguées.",
    ),
    "es": LetterText(
        subject="Adjudicación: {package}",
        heading="Notificación de adjudicación",
        body=(
            "Estimados señores de {bidder}:\n\n"
            "Nos complace comunicarles que, tras la evaluación de las ofertas recibidas para el paquete "
            "{package} del proyecto {project}, su oferta ha resultado adjudicataria por un importe de "
            "{amount}, conforme a los documentos de la licitación y a las aclaraciones acordadas.\n\n"
            "Esta carta constituye la notificación formal de nuestra intención de formalizar el contrato con "
            "ustedes. Nos pondremos en contacto para preparar la documentación contractual y confirmar el "
            "programa de trabajos."
        ),
        closing="Atentamente,",
    ),
    "it": LetterText(
        subject="Aggiudicazione: {package}",
        heading="Comunicazione di aggiudicazione",
        body=(
            "Spettabile {bidder},\n\n"
            "siamo lieti di comunicarvi che, a seguito della valutazione delle offerte pervenute per il "
            "pacchetto {package} del progetto {project}, la vostra offerta è risultata aggiudicataria per "
            "l'importo di {amount}, alle condizioni dei documenti di gara e dei chiarimenti concordati.\n\n"
            "La presente vale come comunicazione formale della nostra intenzione di stipulare il contratto. "
            "Vi contatteremo per definire la documentazione contrattuale e il cronoprogramma."
        ),
        closing="Distinti saluti,",
    ),
    "nl": LetterText(
        subject="Gunning: {package}",
        heading="Mededeling van gunning",
        body=(
            "Geachte heer, mevrouw,\n\n"
            "Met genoegen delen wij u mee dat uw inschrijving voor het pakket {package} van het project "
            "{project} na beoordeling van de ontvangen inschrijvingen is gekozen. De opdracht wordt aan u "
            "gegund voor een aanneemsom van {amount}, onder de voorwaarden van de aanbestedingsstukken en de "
            "overeengekomen verduidelijkingen.\n\n"
            "Wij nemen binnenkort contact met u op om de contractstukken af te ronden en de planning af te "
            "stemmen."
        ),
        closing="Met vriendelijke groet,",
    ),
    "pl": LetterText(
        subject="Udzielenie zamówienia: {package}",
        heading="Zawiadomienie o wyborze oferty",
        body=(
            "Szanowni Państwo,\n\n"
            "z przyjemnością informujemy, że po ocenie ofert złożonych na pakiet {package} w projekcie "
            "{project} Państwa oferta została wybrana. Zamówienie zostaje udzielone za kwotę {amount}, na "
            "warunkach dokumentacji przetargowej i uzgodnionych wyjaśnień.\n\n"
            "Wkrótce skontaktujemy się z Państwem w celu przygotowania umowy i uzgodnienia harmonogramu."
        ),
        closing="Z poważaniem,",
    ),
    "pt": LetterText(
        subject="Adjudicação: {package}",
        heading="Notificação de adjudicação",
        body=(
            "Prezados senhores da {bidder},\n\n"
            "Temos o prazer de informar que, após a avaliação das propostas recebidas para o pacote "
            "{package} do projeto {project}, a vossa proposta foi selecionada. A adjudicação é feita pelo "
            "valor de {amount}, nos termos dos documentos do concurso e dos esclarecimentos acordados.\n\n"
            "Entraremos em contacto para formalizar a documentação contratual e confirmar o programa."
        ),
        closing="Com os melhores cumprimentos,",
    ),
    "cs": LetterText(
        subject="Přidělení zakázky: {package}",
        heading="Oznámení o přidělení zakázky",
        body=(
            "Vážení,\n\n"
            "s potěšením vám oznamujeme, že po vyhodnocení nabídek na balíček {package} v projektu "
            "{project} byla vybrána vaše nabídka. Zakázka se vám přiděluje za cenu {amount} za podmínek "
            "zadávací dokumentace a dohodnutých upřesnění.\n\n"
            "Brzy vás budeme kontaktovat ohledně smluvní dokumentace a harmonogramu."
        ),
        closing="S pozdravem,",
    ),
    "ru": LetterText(
        subject="Уведомление о выборе подрядчика: {package}",
        heading="Уведомление о присуждении договора",
        body=(
            "Уважаемые коллеги из {bidder}!\n\n"
            "Сообщаем, что по итогам оценки предложений, поступивших по тендерному пакету {package} "
            "проекта {project}, ваше предложение признано победившим. Договор присуждается на сумму "
            "{amount} на условиях тендерной документации и согласованных уточнений.\n\n"
            "Настоящее письмо является официальным уведомлением о нашем намерении заключить с вами договор. "
            "В ближайшее время мы свяжемся с вами для оформления договорной документации и согласования "
            "графика работ."
        ),
        closing="С уважением,",
    ),
}

# ── Rejection notice ────────────────────────────────────────────────────────

REJECTION_DEFAULTS: dict[str, LetterText] = {
    "en": LetterText(
        subject="Tender outcome: {package}",
        heading="Notification of Unsuccessful Bid",
        body=(
            "Dear {bidder},\n\n"
            "Thank you for the time and effort you invested in preparing your bid for the tender package "
            "{package} on the project {project}. Following a careful evaluation of all submissions, we regret "
            "to inform you that your bid has not been selected on this occasion.\n\n"
            "We value your interest in working with us and would welcome your participation in future tender "
            "opportunities. Should you wish to discuss the outcome, please do not hesitate to contact us."
        ),
        closing="Yours faithfully,",
    ),
    "de": LetterText(
        subject="Nichtberücksichtigung Ihres Angebots: {package}",
        heading="Mitteilung über die Nichtberücksichtigung Ihres Angebots",
        body=(
            "Sehr geehrte Damen und Herren,\n\n"
            "wir bedanken uns für Ihr Angebot zum Vergabepaket {package} im Bauvorhaben {project} und für "
            "die damit verbundene Mühe. Nach sorgfältiger Prüfung und Wertung aller Angebote müssen wir Ihnen "
            "leider mitteilen, dass Ihr Angebot nicht berücksichtigt werden konnte.\n\n"
            "Wir würden uns freuen, Sie bei künftigen Ausschreibungen erneut zur Angebotsabgabe auffordern zu "
            "dürfen. Für Rückfragen stehen wir Ihnen gern zur Verfügung."
        ),
        closing="Mit freundlichen Grüßen",
    ),
    "fr": LetterText(
        subject="Résultat de la consultation : {package}",
        heading="Information des candidats non retenus",
        body=(
            "Madame, Monsieur,\n\n"
            "Nous vous remercions du temps consacré à la préparation de votre offre pour le lot {package} du "
            "projet {project}. Après une analyse attentive de l'ensemble des offres, nous avons le regret de "
            "vous informer que votre offre n'a pas été retenue.\n\n"
            "Nous serions heureux de vous consulter à nouveau lors de prochains appels d'offres. Nous restons "
            "à votre disposition pour tout échange sur ce résultat."
        ),
        closing="Veuillez agréer, Madame, Monsieur, l'expression de nos salutations distinguées.",
    ),
    "es": LetterText(
        subject="Resultado de la licitación: {package}",
        heading="Comunicación de oferta no seleccionada",
        body=(
            "Estimados señores de {bidder}:\n\n"
            "Les agradecemos el tiempo dedicado a preparar su oferta para el paquete {package} del proyecto "
            "{project}. Tras una evaluación detallada de todas las ofertas, lamentamos comunicarles que su "
            "oferta no ha sido seleccionada en esta ocasión.\n\n"
            "Valoramos su interés y nos gustaría contar con su participación en futuras licitaciones. Quedamos "
            "a su disposición para comentar el resultado."
        ),
        closing="Atentamente,",
    ),
    "it": LetterText(
        subject="Esito della gara: {package}",
        heading="Comunicazione di mancata aggiudicazione",
        body=(
            "Spettabile {bidder},\n\n"
            "vi ringraziamo per l'impegno dedicato alla preparazione dell'offerta per il pacchetto {package} "
            "del progetto {project}. A seguito di un'attenta valutazione di tutte le offerte, siamo spiacenti "
            "di comunicarvi che la vostra offerta non è stata selezionata.\n\n"
            "Saremo lieti di invitarvi a future gare. Restiamo a disposizione per qualsiasi chiarimento."
        ),
        closing="Distinti saluti,",
    ),
    "nl": LetterText(
        subject="Uitslag aanbesteding: {package}",
        heading="Mededeling van afwijzing",
        body=(
            "Geachte heer, mevrouw,\n\n"
            "Hartelijk dank voor de tijd en moeite die u in uw inschrijving voor het pakket {package} van "
            "het project {project} hebt gestoken. Na zorgvuldige beoordeling van alle inschrijvingen moeten "
            "wij u helaas meedelen dat uw inschrijving niet is gekozen.\n\n"
            "Wij nodigen u graag uit voor toekomstige aanbestedingen. Voor vragen over de uitslag kunt u "
            "contact met ons opnemen."
        ),
        closing="Met vriendelijke groet,",
    ),
    "pl": LetterText(
        subject="Wynik przetargu: {package}",
        heading="Zawiadomienie o odrzuceniu oferty",
        body=(
            "Szanowni Państwo,\n\n"
            "dziękujemy za przygotowanie oferty na pakiet {package} w projekcie {project}. Po starannej "
            "ocenie wszystkich ofert z przykrością informujemy, że Państwa oferta nie została wybrana.\n\n"
            "Chętnie zaprosimy Państwa do kolejnych przetargów. W razie pytań pozostajemy do dyspozycji."
        ),
        closing="Z poważaniem,",
    ),
    "pt": LetterText(
        subject="Resultado do concurso: {package}",
        heading="Notificação de proposta não selecionada",
        body=(
            "Prezados senhores da {bidder},\n\n"
            "Agradecemos o tempo dedicado à preparação da vossa proposta para o pacote {package} do projeto "
            "{project}. Após uma avaliação cuidada de todas as propostas, lamentamos informar que a vossa "
            "proposta não foi selecionada.\n\n"
            "Teremos todo o gosto em convidar-vos para futuros concursos. Estamos ao dispor para qualquer "
            "esclarecimento."
        ),
        closing="Com os melhores cumprimentos,",
    ),
    "cs": LetterText(
        subject="Výsledek výběrového řízení: {package}",
        heading="Oznámení o nevybrání nabídky",
        body=(
            "Vážení,\n\n"
            "děkujeme za vaši nabídku na balíček {package} v projektu {project}. Po pečlivém vyhodnocení "
            "všech nabídek vám s lítostí oznamujeme, že vaše nabídka nebyla vybrána.\n\n"
            "Rádi vás oslovíme v dalších výběrových řízeních. V případě dotazů jsme vám k dispozici."
        ),
        closing="S pozdravem,",
    ),
    "ru": LetterText(
        subject="Итоги тендера: {package}",
        heading="Уведомление об итогах тендера",
        body=(
            "Уважаемые коллеги из {bidder}!\n\n"
            "Благодарим вас за подготовку предложения по тендерному пакету {package} проекта {project}. По "
            "итогам внимательной оценки всех предложений сообщаем, что, к сожалению, ваше предложение не "
            "было выбрано.\n\n"
            "Будем рады видеть вас среди участников наших будущих тендеров. Если вы хотите обсудить итоги, "
            "свяжитесь с нами."
        ),
        closing="С уважением,",
    ),
}


def _invitation_defaults() -> dict[str, LetterText]:
    """Build the invitation defaults from the email's existing catalogue."""
    from app.modules.tendering.invitation_email import _TABLES

    out: dict[str, LetterText] = {}
    for lang, table in _TABLES.items():
        greeting = table["greeting"].replace("{company}", "{bidder}")
        body = "\n\n".join(
            [
                greeting,
                table["invite_project"],
                table["deadline"],
                table["link_help"],
            ]
        )
        out[lang] = LetterText(
            subject=table["subject"],
            heading=table["heading"],
            body=body,
            # Languages without a sign-off of their own close with the firm's name only.
            closing=(_LABELS[lang]["regards"] + "\n{company}") if lang in _LABELS else "{company}",
        )
    return out


# ── Fixed labels around the editable text ───────────────────────────────────

_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "awarded_to": "Awarded to:", "bidder": "Bidder:", "project": "Project:", "package": "Tender package:",
        "award_date": "Award date:", "date": "Date:", "contact": "Contact:", "contract_sum": "Awarded contract sum",
        "your_bid": "Your submitted bid:", "awarded_sum": "Awarded contract sum:", "notes": "Notes",
        "reason": "Reason", "ref": "Ref:", "award_label": "LETTER OF AWARD",
        "rejection_label": "NOTICE OF TENDER OUTCOME", "regards": "Kind regards,",
    },
    "de": {
        "awarded_to": "Auftragnehmer:", "bidder": "Bieter:", "project": "Bauvorhaben:", "package": "Vergabepaket:",
        "award_date": "Zuschlag am:", "date": "Datum:", "contact": "Kontakt:", "contract_sum": "Auftragssumme",
        "your_bid": "Ihre Angebotssumme:", "awarded_sum": "Auftragssumme:", "notes": "Hinweise",
        "reason": "Begründung", "ref": "Az.:", "award_label": "AUFTRAGSERTEILUNG",
        "rejection_label": "MITTEILUNG ZUM VERGABEERGEBNIS", "regards": "Mit freundlichen Grüßen",
    },
    "fr": {
        "awarded_to": "Attributaire :", "bidder": "Candidat :", "project": "Projet :", "package": "Lot :",
        "award_date": "Date d'attribution :", "date": "Date :", "contact": "Contact :",
        "contract_sum": "Montant du marché", "your_bid": "Montant de votre offre :",
        "awarded_sum": "Montant attribué :", "notes": "Remarques", "reason": "Motif", "ref": "Réf. :",
        "award_label": "NOTIFICATION D'ATTRIBUTION", "rejection_label": "RÉSULTAT DE LA CONSULTATION",
        "regards": "Cordialement,",
    },
    "es": {
        "awarded_to": "Adjudicatario:", "bidder": "Licitador:", "project": "Proyecto:", "package": "Paquete:",
        "award_date": "Fecha de adjudicación:", "date": "Fecha:", "contact": "Contacto:",
        "contract_sum": "Importe adjudicado", "your_bid": "Importe de su oferta:",
        "awarded_sum": "Importe adjudicado:", "notes": "Observaciones", "reason": "Motivo", "ref": "Ref.:",
        "award_label": "CARTA DE ADJUDICACIÓN", "rejection_label": "RESULTADO DE LA LICITACIÓN",
        "regards": "Saludos cordiales,",
    },
    "it": {
        "awarded_to": "Aggiudicatario:", "bidder": "Offerente:", "project": "Progetto:", "package": "Pacchetto:",
        "award_date": "Data di aggiudicazione:", "date": "Data:", "contact": "Contatto:",
        "contract_sum": "Importo aggiudicato", "your_bid": "Importo della vostra offerta:",
        "awarded_sum": "Importo aggiudicato:", "notes": "Note", "reason": "Motivazione", "ref": "Rif.:",
        "award_label": "LETTERA DI AGGIUDICAZIONE", "rejection_label": "ESITO DELLA GARA",
        "regards": "Cordiali saluti,",
    },
    "nl": {
        "awarded_to": "Gegund aan:", "bidder": "Inschrijver:", "project": "Project:", "package": "Pakket:",
        "award_date": "Gunningsdatum:", "date": "Datum:", "contact": "Contact:", "contract_sum": "Aanneemsom",
        "your_bid": "Uw inschrijfsom:", "awarded_sum": "Gegunde aanneemsom:", "notes": "Opmerkingen",
        "reason": "Reden", "ref": "Kenmerk:", "award_label": "GUNNINGSBRIEF",
        "rejection_label": "UITSLAG AANBESTEDING", "regards": "Met vriendelijke groet,",
    },
    "pl": {
        "awarded_to": "Wykonawca:", "bidder": "Oferent:", "project": "Projekt:", "package": "Pakiet:",
        "award_date": "Data udzielenia:", "date": "Data:", "contact": "Kontakt:",
        "contract_sum": "Wartość zamówienia", "your_bid": "Kwota Państwa oferty:",
        "awarded_sum": "Wartość zamówienia:", "notes": "Uwagi", "reason": "Uzasadnienie", "ref": "Znak:",
        "award_label": "ZAWIADOMIENIE O WYBORZE", "rejection_label": "WYNIK PRZETARGU",
        "regards": "Z poważaniem,",
    },
    "pt": {
        "awarded_to": "Adjudicatário:", "bidder": "Concorrente:", "project": "Projeto:", "package": "Pacote:",
        "award_date": "Data de adjudicação:", "date": "Data:", "contact": "Contacto:",
        "contract_sum": "Valor adjudicado", "your_bid": "Valor da vossa proposta:",
        "awarded_sum": "Valor adjudicado:", "notes": "Observações", "reason": "Motivo", "ref": "Ref.:",
        "award_label": "CARTA DE ADJUDICAÇÃO", "rejection_label": "RESULTADO DO CONCURSO",
        "regards": "Com os melhores cumprimentos,",
    },
    "cs": {
        "awarded_to": "Zhotovitel:", "bidder": "Uchazeč:", "project": "Projekt:", "package": "Balíček:",
        "award_date": "Datum přidělení:", "date": "Datum:", "contact": "Kontakt:", "contract_sum": "Cena zakázky",
        "your_bid": "Vaše nabídková cena:", "awarded_sum": "Cena zakázky:", "notes": "Poznámky",
        "reason": "Důvod", "ref": "Č. j.:", "award_label": "PŘIDĚLENÍ ZAKÁZKY",
        "rejection_label": "VÝSLEDEK VÝBĚROVÉHO ŘÍZENÍ", "regards": "S pozdravem,",
    },
    "ru": {
        "awarded_to": "Подрядчик:", "bidder": "Участник:", "project": "Проект:", "package": "Тендерный пакет:",
        "award_date": "Дата решения:", "date": "Дата:", "contact": "Контакт:", "contract_sum": "Сумма договора",
        "your_bid": "Сумма вашего предложения:", "awarded_sum": "Сумма договора:", "notes": "Примечания",
        "reason": "Причина", "ref": "Исх.:", "award_label": "УВЕДОМЛЕНИЕ О ВЫБОРЕ",
        "rejection_label": "ИТОГИ ТЕНДЕРА", "regards": "С уважением,",
    },
}  # fmt: skip


def label(locale: str, key: str) -> str:
    """A fixed PDF label in *locale*, English when the language is missing."""
    return translate(_LABELS, locale, key, "en")


def _award_preview(text: LetterText, language: str) -> tuple[bytes, str]:
    from app.modules.tendering.pdf_documents import generate_award_letter_pdf

    samples = {p.name: p.sample for p in AWARD_PLACEHOLDERS}
    pdf = generate_award_letter_pdf(
        package_name=samples["package"],
        package_ref="PREVIEW",
        project_name=samples["project"],
        company_name=samples["bidder"],
        contact_email="",
        awarded_amount="1284500.00",
        currency="EUR",
        awarded_by_name=samples["sender"],
        text=text,
        locale=language,
    )
    return pdf, "application/pdf"


def _rejection_preview(text: LetterText, language: str) -> tuple[bytes, str]:
    from app.modules.tendering.pdf_documents import generate_rejection_letter_pdf

    samples = {p.name: p.sample for p in REJECTION_PLACEHOLDERS}
    pdf = generate_rejection_letter_pdf(
        package_name=samples["package"],
        package_ref="PREVIEW",
        project_name=samples["project"],
        company_name=samples["bidder"],
        contact_email="",
        signed_by_name=samples["sender"],
        text=text,
        locale=language,
    )
    return pdf, "application/pdf"


def _invitation_preview(text: LetterText, language: str) -> tuple[bytes, str]:
    from app.modules.tendering.invitation_email import invitation_html

    samples = {p.name: p.sample for p in INVITATION_PLACEHOLDERS}
    page = invitation_html(
        locale=language,
        company_name=samples["bidder"],
        package_name=samples["package"],
        project_name=samples["project"],
        description="",
        deadline=samples["deadline"],
        custom_message=None,
        action_url="https://example.com/bid/preview",
        text=text,
        sender_company=samples["company"],
    )
    return page.encode("utf-8"), "text/html; charset=utf-8"


def register_tendering_letter_templates() -> None:
    """Register the three tendering letters. Idempotent."""
    if get_template(AWARD_KEY) is not None:
        return
    register_template(
        LetterTemplate(AWARD_KEY, "tendering", "pdf", AWARD_PLACEHOLDERS, AWARD_DEFAULTS, preview=_award_preview)
    )
    register_template(
        LetterTemplate(
            REJECTION_KEY, "tendering", "pdf", REJECTION_PLACEHOLDERS, REJECTION_DEFAULTS, preview=_rejection_preview
        )
    )
    register_template(
        LetterTemplate(
            INVITATION_KEY,
            "tendering",
            "email",
            INVITATION_PLACEHOLDERS,
            _invitation_defaults(),
            preview=_invitation_preview,
        )
    )


def tendering_template(key: str) -> LetterTemplate:
    """The registered tendering letter, registering on first use."""
    register_tendering_letter_templates()
    template = get_template(key)
    assert template is not None
    return template
