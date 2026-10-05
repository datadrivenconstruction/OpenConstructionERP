# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The notification email: an absolute link and the reader's language.

A notification stores ``action_url`` as an in-app path (``/boq/{id}``,
``/rfi?id=...``) because the bell hands it to the router. A mail client has
no router, so the email resolves that path against the configured frontend
(:attr:`app.config.Settings.resolved_frontend_url`, the same base the
password-reset and portal sign-in links use), keeping a sub-path prefix such
as ``https://host/erp``. Anything that is not our own app (another scheme,
another host, a protocol-relative ``//host``) is dropped rather than rendered:
the mail goes out without a button.

The text around the notification (greeting, button, footer, digest subject)
is written in the recipient's language (``User.locale``) through the shared
:func:`app.core.document_locale.translate`, in the languages the portal and
tender invitation emails speak, falling back to English key by key. Values are
plain text and every one is escaped where it is spliced in.
"""

from __future__ import annotations

import html
import re
from urllib.parse import SplitResult, urlsplit

from app.core.document_locale import normalize_document_locale, translate

DEFAULT_LOCALE = "en"

_TABLES: dict[str, dict[str, str]] = {
    "en": {
        "greeting": "Hello {name},",
        "greeting_generic": "Hello,",
        "cta": "Open in OpenConstructionERP",
        "footer": "You receive this email because of your notification settings. You can change them in your profile.",
        "digest_subject": "Notification digest ({count})",
        "digest_heading": "Recent notifications:",
    },
    "de": {
        "greeting": "Guten Tag {name},",
        "greeting_generic": "Guten Tag,",
        "cta": "In OpenConstructionERP öffnen",
        "footer": (
            "Sie erhalten diese E-Mail aufgrund Ihrer Benachrichtigungseinstellungen. "
            "Sie können sie in Ihrem Profil ändern."
        ),
        "digest_subject": "Benachrichtigungsübersicht ({count})",
        "digest_heading": "Neueste Benachrichtigungen:",
    },
    "fr": {
        "greeting": "Bonjour {name},",
        "greeting_generic": "Bonjour,",
        "cta": "Ouvrir dans OpenConstructionERP",
        "footer": (
            "Vous recevez cet e-mail en raison de vos paramètres de notification. "
            "Vous pouvez les modifier dans votre profil."
        ),
        "digest_subject": "Récapitulatif des notifications ({count})",
        "digest_heading": "Notifications récentes :",
    },
    "es": {
        "greeting": "Hola, {name}:",
        "greeting_generic": "Hola:",
        "cta": "Abrir en OpenConstructionERP",
        "footer": "Recibe este correo por su configuración de notificaciones. Puede cambiarla en su perfil.",
        "digest_subject": "Resumen de notificaciones ({count})",
        "digest_heading": "Notificaciones recientes:",
    },
    "it": {
        "greeting": "Buongiorno {name},",
        "greeting_generic": "Buongiorno,",
        "cta": "Apri in OpenConstructionERP",
        "footer": "Ricevi questa email in base alle tue impostazioni di notifica. Puoi modificarle nel tuo profilo.",
        "digest_subject": "Riepilogo notifiche ({count})",
        "digest_heading": "Notifiche recenti:",
    },
    "nl": {
        "greeting": "Beste {name},",
        "greeting_generic": "Geachte heer, mevrouw,",
        "cta": "Openen in OpenConstructionERP",
        "footer": "U ontvangt deze e-mail vanwege uw meldingsinstellingen. U kunt ze wijzigen in uw profiel.",
        "digest_subject": "Overzicht van meldingen ({count})",
        "digest_heading": "Recente meldingen:",
    },
    "pl": {
        "greeting": "Dzień dobry {name},",
        "greeting_generic": "Dzień dobry,",
        "cta": "Otwórz w OpenConstructionERP",
        "footer": "Otrzymujesz tę wiadomość zgodnie z ustawieniami powiadomień. Możesz je zmienić w swoim profilu.",
        "digest_subject": "Podsumowanie powiadomień ({count})",
        "digest_heading": "Ostatnie powiadomienia:",
    },
    "pt": {
        "greeting": "Olá, {name},",
        "greeting_generic": "Olá,",
        "cta": "Abrir no OpenConstructionERP",
        "footer": "Recebe este e-mail devido às suas definições de notificação. Pode alterá-las no seu perfil.",
        "digest_subject": "Resumo de notificações ({count})",
        "digest_heading": "Notificações recentes:",
    },
    "cs": {
        "greeting": "Dobrý den, {name},",
        "greeting_generic": "Dobrý den,",
        "cta": "Otevřít v OpenConstructionERP",
        "footer": "Tento e-mail dostáváte kvůli svému nastavení oznámení. Můžete ho změnit ve svém profilu.",
        "digest_subject": "Přehled oznámení ({count})",
        "digest_heading": "Nedávná oznámení:",
    },
    "ru": {
        "greeting": "Здравствуйте, {name}!",
        "greeting_generic": "Здравствуйте!",
        "cta": "Открыть в OpenConstructionERP",
        "footer": "Вы получили это письмо согласно настройкам уведомлений. Изменить их можно в профиле.",
        "digest_subject": "Сводка уведомлений ({count})",
        "digest_heading": "Последние уведомления:",
    },
}

#: Languages the notification email can be written in.
SUPPORTED_LOCALES: tuple[str, ...] = tuple(_TABLES)

# Whitespace or a control character anywhere: browsers strip some of them
# before parsing (``java\tscript:``), so such a link is never trusted.
_UNSAFE_CHARS = re.compile(r"[\x00-\x20\x7f]")
_DEFAULT_PORTS = {"http": 80, "https": 443}


def email_locale(language: str | None) -> str:
    """The catalogue language for a user's locale (``de-AT`` reads ``de``)."""
    return normalize_document_locale(language, SUPPORTED_LOCALES, DEFAULT_LOCALE)


def _t(locale: str | None, key: str, **params: object) -> str:
    return translate(_TABLES, email_locale(locale), key, DEFAULT_LOCALE, **params)


def digest_subject(locale: str | None, count: int) -> str:
    """The subject of a digest email (plain text, not escaped)."""
    return _t(locale, "digest_subject", count=count)


def digest_heading(locale: str | None) -> str:
    """The line above the bulleted digest entries (plain text, not escaped)."""
    return _t(locale, "digest_heading")


def _origin(parts: SplitResult) -> tuple[str, int | None]:
    scheme = parts.scheme.lower()
    return (parts.hostname or "").lower(), parts.port or _DEFAULT_PORTS.get(scheme)


def absolute_action_url(action_url: str | None, base_url: str) -> str | None:
    """Resolve a notification link for an email, or ``None`` when it is unsafe.

    Args:
        action_url: The stored link, normally an in-app path such as
            ``/rfi?id=7``.
        base_url: The public frontend address, possibly with a sub-path
            (``https://host/erp``).

    Returns:
        ``base_url`` plus the path for a path that starts with exactly one
        ``/``; the link itself for an http(s) link to the same host, port and
        sub-path as ``base_url`` with no credentials in it; ``None`` for
        anything else, including other schemes and protocol-relative links.
    """
    if not action_url or _UNSAFE_CHARS.search(action_url) or "\\" in action_url:
        return None
    base = (base_url or "").rstrip("/")
    try:
        base_parts = urlsplit(base)
        parts = urlsplit(action_url)
        # A malformed port raises on first read, so read both here.
        _ = parts.port, base_parts.port
    except ValueError:
        return None

    if not parts.scheme and not parts.netloc:
        # Exactly one leading slash: ``//host`` is protocol-relative.
        if not action_url.startswith("/") or action_url.startswith("//"):
            return None
        return f"{base}{action_url}"

    if parts.scheme.lower() not in _DEFAULT_PORTS or base_parts.scheme.lower() not in _DEFAULT_PORTS:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    if _origin(parts) != _origin(base_parts):
        return None
    prefix = base_parts.path.rstrip("/")
    if prefix and parts.path != prefix and not parts.path.startswith(prefix + "/"):
        return None
    return action_url


def render_notification_email(
    *,
    locale: str | None,
    recipient_name: str | None,
    subject: str,
    body_text: str,
    action_url: str | None,
    base_url: str,
) -> str:
    """Render the HTML body of a notification email.

    Args:
        locale: The recipient's ``User.locale``; unknown languages read English.
        recipient_name: Display name for the greeting; blank greets without one.
        subject: The notification title, shown as the heading.
        body_text: The notification body; newlines become line breaks.
        action_url: The stored link; see :func:`absolute_action_url`.
        base_url: The public frontend address.

    Returns:
        The HTML body, every interpolated value escaped.
    """
    from app.core.email import wrap

    name = (recipient_name or "").strip()
    if name:
        # Escape the template and splice the escaped name in afterwards, so
        # neither a translation nor a name can inject markup.
        greeting = html.escape(_t(locale, "greeting", name="\x00")).replace("\x00", html.escape(name))
    else:
        greeting = html.escape(_t(locale, "greeting_generic"))
    body = html.escape(body_text or "").replace("\n", "<br>")
    link = absolute_action_url(action_url, base_url)
    return wrap(
        html.escape(subject or ""),
        f"<p>{greeting}</p><p style='color:#374151;'>{body}</p>",
        html.escape(link, quote=True) if link else None,
        html.escape(_t(locale, "cta")),
        footer=html.escape(_t(locale, "footer")),
    )
