# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The two emails a portal user receives: the invitation and the sign-in link.

Both carry a one-time magic link. The email goes to a client or partner
outside the company, so it is written in the portal user's own language
(``PortalUser.language``) and resolves through the shared
:func:`app.core.document_locale.translate`, which falls back to English key
by key. A locale the catalogue does not carry reads English.

The link is built here, on the server, the same way the staff screen builds
the copy-link (``frontend/src/features/portal/portalLanding.ts``): the
role's landing page plus ``?token=``. The two must agree, or an emailed link
and a copied link would open different pages.

Values are plain text. The renderer escapes every value it interpolates and
adds the markup around them, so a translation never carries HTML.
"""

from __future__ import annotations

import html
import logging
import math
from datetime import datetime
from typing import Literal
from urllib.parse import quote

from app.core.document_locale import normalize_document_locale, translate

logger = logging.getLogger(__name__)

DEFAULT_LOCALE = "en"

EmailKind = Literal["invite", "login"]

#: What the staff screen is told about the invitation email.
EmailStatus = Literal["sent", "failed", "not_configured"]

_TABLES: dict[str, dict[str, str]] = {
    "en": {
        "invite_subject": "{sender} invited you to the client portal",
        "login_subject": "Your sign-in link for the client portal",
        "invite_heading": "Welcome to the client portal",
        "login_heading": "Sign in to the client portal",
        "greeting": "Hello {name},",
        "greeting_generic": "Hello,",
        "invite_body": (
            "{sender} has given you access to the client portal. There you can follow your project: "
            "progress reports, documents, invoices and the next milestones."
        ),
        "login_body": "Here is the sign-in link you asked for.",
        "link_help": "The button below signs you in. No password is needed. The link works once and expires in {hours} hours.",
        "ignore": "If you did not expect this email, you can ignore it. Nobody gets access without this link.",
        "invite_cta": "Open the portal",
        "login_cta": "Sign in",
        "sender_generic": "Your project team",
    },
    "de": {
        "invite_subject": "{sender} hat Sie zum Kundenportal eingeladen",
        "login_subject": "Ihr Anmeldelink für das Kundenportal",
        "invite_heading": "Willkommen im Kundenportal",
        "login_heading": "Anmeldung im Kundenportal",
        "greeting": "Guten Tag {name},",
        "greeting_generic": "Guten Tag,",
        "invite_body": (
            "{sender} hat Ihnen Zugang zum Kundenportal eingerichtet. Dort verfolgen Sie Ihr Projekt: "
            "Fortschrittsberichte, Dokumente, Rechnungen und die nächsten Meilensteine."
        ),
        "login_body": "Hier ist der Anmeldelink, den Sie angefordert haben.",
        "link_help": (
            "Mit der Schaltfläche unten melden Sie sich an. Ein Passwort ist nicht nötig. "
            "Der Link funktioniert einmal und läuft in {hours} Stunden ab."
        ),
        "ignore": (
            "Wenn Sie diese E-Mail nicht erwartet haben, können Sie sie ignorieren. "
            "Ohne diesen Link erhält niemand Zugang."
        ),
        "invite_cta": "Portal öffnen",
        "login_cta": "Anmelden",
        "sender_generic": "Ihr Projektteam",
    },
    "fr": {
        "invite_subject": "{sender} vous a invité sur le portail client",
        "login_subject": "Votre lien de connexion au portail client",
        "invite_heading": "Bienvenue sur le portail client",
        "login_heading": "Connexion au portail client",
        "greeting": "Bonjour {name},",
        "greeting_generic": "Bonjour,",
        "invite_body": (
            "{sender} vous a donné accès au portail client. Vous pouvez y suivre votre projet : "
            "rapports d'avancement, documents, factures et prochains jalons."
        ),
        "login_body": "Voici le lien de connexion que vous avez demandé.",
        "link_help": (
            "Le bouton ci-dessous vous connecte. Aucun mot de passe n'est nécessaire. "
            "Le lien ne fonctionne qu'une fois et expire dans {hours} heures."
        ),
        "ignore": (
            "Si vous n'attendiez pas cet e-mail, vous pouvez l'ignorer. Personne n'obtient l'accès sans ce lien."
        ),
        "invite_cta": "Ouvrir le portail",
        "login_cta": "Se connecter",
        "sender_generic": "Votre équipe de projet",
    },
    "es": {
        "invite_subject": "{sender} le ha invitado al portal de clientes",
        "login_subject": "Su enlace de acceso al portal de clientes",
        "invite_heading": "Bienvenido al portal de clientes",
        "login_heading": "Acceso al portal de clientes",
        "greeting": "Hola, {name}:",
        "greeting_generic": "Hola:",
        "invite_body": (
            "{sender} le ha dado acceso al portal de clientes. Allí puede seguir su proyecto: "
            "informes de avance, documentos, facturas y los próximos hitos."
        ),
        "login_body": "Aquí tiene el enlace de acceso que ha solicitado.",
        "link_help": (
            "El botón de abajo inicia la sesión. No necesita contraseña. "
            "El enlace funciona una sola vez y caduca en {hours} horas."
        ),
        "ignore": "Si no esperaba este correo, puede ignorarlo. Nadie obtiene acceso sin este enlace.",
        "invite_cta": "Abrir el portal",
        "login_cta": "Iniciar sesión",
        "sender_generic": "Su equipo de proyecto",
    },
    "it": {
        "invite_subject": "{sender} ti ha invitato al portale clienti",
        "login_subject": "Il tuo link di accesso al portale clienti",
        "invite_heading": "Benvenuto nel portale clienti",
        "login_heading": "Accesso al portale clienti",
        "greeting": "Buongiorno {name},",
        "greeting_generic": "Buongiorno,",
        "invite_body": (
            "{sender} ti ha dato accesso al portale clienti. Lì puoi seguire il tuo progetto: "
            "rapporti di avanzamento, documenti, fatture e le prossime milestone."
        ),
        "login_body": "Ecco il link di accesso che hai richiesto.",
        "link_help": (
            "Il pulsante qui sotto ti fa accedere. Non serve una password. "
            "Il link funziona una sola volta e scade tra {hours} ore."
        ),
        "ignore": "Se non aspettavi questa email, puoi ignorarla. Nessuno ottiene l'accesso senza questo link.",
        "invite_cta": "Apri il portale",
        "login_cta": "Accedi",
        "sender_generic": "Il tuo team di progetto",
    },
    "nl": {
        "invite_subject": "{sender} heeft u uitgenodigd voor het klantportaal",
        "login_subject": "Uw inloglink voor het klantportaal",
        "invite_heading": "Welkom in het klantportaal",
        "login_heading": "Inloggen op het klantportaal",
        "greeting": "Beste {name},",
        "greeting_generic": "Geachte heer, mevrouw,",
        "invite_body": (
            "{sender} heeft u toegang gegeven tot het klantportaal. Daar volgt u uw project: "
            "voortgangsrapporten, documenten, facturen en de volgende mijlpalen."
        ),
        "login_body": "Hier is de inloglink die u hebt aangevraagd.",
        "link_help": (
            "Met de knop hieronder logt u in. Een wachtwoord is niet nodig. "
            "De link werkt één keer en verloopt over {hours} uur."
        ),
        "ignore": "Had u deze e-mail niet verwacht, dan kunt u hem negeren. Zonder deze link krijgt niemand toegang.",
        "invite_cta": "Portaal openen",
        "login_cta": "Inloggen",
        "sender_generic": "Uw projectteam",
    },
    "pl": {
        "invite_subject": "{sender} zaprasza Cię do portalu klienta",
        "login_subject": "Twój link do logowania w portalu klienta",
        "invite_heading": "Witamy w portalu klienta",
        "login_heading": "Logowanie do portalu klienta",
        "greeting": "Dzień dobry {name},",
        "greeting_generic": "Dzień dobry,",
        "invite_body": (
            "{sender} udostępnia Ci portal klienta. Możesz w nim śledzić swój projekt: "
            "raporty postępu, dokumenty, faktury i najbliższe kamienie milowe."
        ),
        "login_body": "Oto link do logowania, o który prosiłeś.",
        "link_help": (
            "Przycisk poniżej loguje Cię do portalu. Hasło nie jest potrzebne. "
            "Link działa jeden raz i wygasa za {hours} godz."
        ),
        "ignore": "Jeśli nie spodziewałeś się tej wiadomości, możesz ją zignorować. Bez tego linku nikt nie uzyska dostępu.",
        "invite_cta": "Otwórz portal",
        "login_cta": "Zaloguj się",
        "sender_generic": "Twój zespół projektowy",
    },
    "pt": {
        "invite_subject": "{sender} convidou-o para o portal do cliente",
        "login_subject": "O seu link de acesso ao portal do cliente",
        "invite_heading": "Bem-vindo ao portal do cliente",
        "login_heading": "Acesso ao portal do cliente",
        "greeting": "Olá, {name},",
        "greeting_generic": "Olá,",
        "invite_body": (
            "{sender} deu-lhe acesso ao portal do cliente. Aí pode acompanhar o seu projeto: "
            "relatórios de progresso, documentos, faturas e os próximos marcos."
        ),
        "login_body": "Aqui está o link de acesso que pediu.",
        "link_help": (
            "O botão abaixo inicia a sessão. Não é preciso palavra-passe. "
            "O link funciona uma única vez e expira dentro de {hours} horas."
        ),
        "ignore": "Se não esperava este e-mail, pode ignorá-lo. Ninguém obtém acesso sem este link.",
        "invite_cta": "Abrir o portal",
        "login_cta": "Entrar",
        "sender_generic": "A sua equipa de projeto",
    },
    "cs": {
        "invite_subject": "{sender} vás pozval do klientského portálu",
        "login_subject": "Váš přihlašovací odkaz do klientského portálu",
        "invite_heading": "Vítejte v klientském portálu",
        "login_heading": "Přihlášení do klientského portálu",
        "greeting": "Dobrý den, {name},",
        "greeting_generic": "Dobrý den,",
        "invite_body": (
            "{sender} vám zpřístupnil klientský portál. Můžete v něm sledovat svůj projekt: "
            "zprávy o postupu, dokumenty, faktury a nejbližší milníky."
        ),
        "login_body": "Zde je přihlašovací odkaz, o který jste požádali.",
        "link_help": (
            "Tlačítko níže vás přihlásí. Heslo není potřeba. "
            "Odkaz funguje jednou a jeho platnost vyprší za {hours} hodin."
        ),
        "ignore": "Pokud jste tento e-mail nečekali, můžete jej ignorovat. Bez tohoto odkazu nikdo přístup nezíská.",
        "invite_cta": "Otevřít portál",
        "login_cta": "Přihlásit se",
        "sender_generic": "Váš projektový tým",
    },
    "ru": {
        "invite_subject": "{sender} приглашает вас в клиентский портал",
        "login_subject": "Ссылка для входа в клиентский портал",
        "invite_heading": "Добро пожаловать в клиентский портал",
        "login_heading": "Вход в клиентский портал",
        "greeting": "Здравствуйте, {name}!",
        "greeting_generic": "Здравствуйте!",
        "invite_body": (
            "{sender} открывает вам доступ к клиентскому порталу. В нём видно ход вашего проекта: "
            "отчёты о ходе работ, документы, счета и ближайшие вехи."
        ),
        "login_body": "Вот ссылка для входа, которую вы запросили.",
        "link_help": (
            "Кнопка ниже выполняет вход. Пароль не нужен. Ссылка срабатывает один раз и действует {hours} ч."
        ),
        "ignore": "Если вы не ждали этого письма, просто проигнорируйте его. Без этой ссылки доступ никто не получит.",
        "invite_cta": "Открыть портал",
        "login_cta": "Войти",
        "sender_generic": "Ваша проектная команда",
    },
}

#: Languages the email can be written in.
SUPPORTED_LOCALES: tuple[str, ...] = tuple(_TABLES)

#: Roles whose portal opens on the payments page, mirrored from
#: ``PAYMENT_FIRST_ROLES`` in ``portalLanding.ts``.
_PAYMENT_FIRST_ROLES = frozenset({"subcontractor", "supplier"})


def email_locale(language: str | None) -> str:
    """The catalogue language for a portal user's language (``pt-BR`` reads ``pt``)."""
    return normalize_document_locale(language, SUPPORTED_LOCALES, DEFAULT_LOCALE)


def _t(locale: str, key: str, **params: str) -> str:
    return translate(_TABLES, email_locale(locale), key, DEFAULT_LOCALE, **params)


def landing_path(role: str | None) -> str:
    """The page a magic link opens for ``role``."""
    return "/portal/payments" if role in _PAYMENT_FIRST_ROLES else "/portal/home"


def portal_link_url(token: str, role: str | None) -> str:
    """The absolute address of a portal magic link."""
    from app.config import get_settings

    base = (get_settings().resolved_frontend_url or "").rstrip("/")
    return f"{base}{landing_path(role)}?token={quote(token, safe='')}"


def login_subject(kind: EmailKind, locale: str, sender: str) -> str:
    """The email subject line (plain text, no escaping)."""
    if kind == "invite":
        return _t(locale, "invite_subject", sender=sender or _t(locale, "sender_generic"))
    return _t(locale, "login_subject")


def login_html(
    *,
    kind: EmailKind,
    locale: str,
    full_name: str,
    sender: str,
    action_url: str,
    valid_hours: int,
) -> str:
    """Render the email body through the shared email shell."""
    from app.core.email import wrap

    def sentence(key: str, **values: str) -> str:
        # Escape the template text and splice the already-escaped values in
        # afterwards, so neither a translation nor a name can inject markup.
        marks = {name: f"\x00{name}\x00" for name in values}
        text = html.escape(_t(locale, key, **marks))
        for name, value in values.items():
            text = text.replace(f"\x00{name}\x00", value)
        return text

    parts: list[str] = []
    name = (full_name or "").strip()
    if name:
        parts.append(f"<p>{sentence('greeting', name=html.escape(name))}</p>")
    else:
        parts.append(f"<p>{sentence('greeting_generic')}</p>")
    if kind == "invite":
        who = (sender or "").strip() or _t(locale, "sender_generic")
        parts.append(f"<p>{sentence('invite_body', sender=f'<strong>{html.escape(who)}</strong>')}</p>")
    else:
        parts.append(f"<p>{sentence('login_body')}</p>")
    parts.append(f"<p>{sentence('link_help', hours=html.escape(str(valid_hours)))}</p>")
    parts.append(f"<p style='font-size:13px; color:#6e6e73;'>{sentence('ignore')}</p>")
    heading = html.escape(_t(locale, f"{kind}_heading"))
    cta = html.escape(_t(locale, f"{kind}_cta"))
    # The body already says why the mail came and what to do if it was not
    # expected, in the reader's language; the shell's English footer about
    # notification preferences would only contradict it.
    return wrap(heading, "".join(parts), html.escape(action_url, quote=True), cta, footer="")


def sender_name() -> str:
    """The company name the workspace shows, or empty when it shows its default brand.

    The stored name survives switching branding back to the default, so the
    mode decides: only a workspace that presents its own brand signs with it.
    """
    try:
        from app.core.app_branding import read_branding

        branding = read_branding()
        if branding.get("mode") not in ("logo", "text"):
            return ""
        return str(branding.get("company_name") or "").strip()
    except Exception:  # noqa: BLE001 - a broken branding file must not block a login email
        logger.warning("portal email: branding unreadable, using the generic sender", exc_info=True)
        return ""


async def send_login_email(
    *,
    kind: EmailKind,
    email: str,
    full_name: str,
    language: str | None,
    role: str | None,
    token: str,
    expires_at: datetime,
    now: datetime,
) -> EmailStatus:
    """Email a magic link. Never raises: the caller falls back to the copy-link."""
    from app.config import get_settings
    from app.core.email import EmailMessage, email_delivery_enabled, get_email_service

    if not email_delivery_enabled(get_settings()):
        return "not_configured"
    locale = email_locale(language)
    sender = sender_name()
    valid_hours = max(1, math.ceil((expires_at - now).total_seconds() / 3600))
    try:
        result = await get_email_service().send(
            EmailMessage(
                to=email,
                subject=login_subject(kind, locale, sender),
                html_body=login_html(
                    kind=kind,
                    locale=locale,
                    full_name=full_name,
                    sender=sender,
                    action_url=portal_link_url(token, role),
                    valid_hours=valid_hours,
                ),
                tags=["portal", kind],
            )
        )
    except Exception as exc:  # noqa: BLE001 - degrade to the copy-link, never fail the invite
        logger.warning("portal %s email crashed: %s", kind, type(exc).__name__)
        return "failed"
    return "sent" if getattr(result, "ok", False) else "failed"
