# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Learner provisioning: a paid order becomes an account, a role and an enrolment.

Two phases, with the caller's commit between them:

1. :func:`provision_order_paid` (or :func:`provision_learner` for the admin
   route) writes inside the caller's transaction and never commits:

   * finds the account by email, or creates it through
     :meth:`UserService.admin_create`. A new account is active, so the
     platform's reset flow accepts it, but its password is a throwaway
     random value that is never stored, logged or sent: the learner sets
     their own through the reset link in the welcome email;
   * raises the account to ``manager``, the role a learner needs. A
     self-registered account is only a viewer, and a viewer cannot award a
     bid package. An account already at manager or above (an admin) is never
     touched: provisioning never lowers a role;
   * enrols the account on every course the store product grants. One
     course runs at a time per learner, so a course bought while another one
     is running is created ``queued``.

2. :func:`complete_provisioning` runs after the commit, because the seeder
   opens its own session and must see the enrolment:

   * calls the injected ``seed_on_enrol`` (stream C's seed stage S0) for each
     enrolment that starts now; a seed failure marks that enrolment
     ``failed`` and never propagates;
   * sends one welcome email through the platform mail service, in the
     buyer's language. For a new account it carries the reset link minted by
     :func:`app.modules.users.service.create_reset_token`, the same token and
     URL the forgot-password flow uses, and explains that the link expires
     after :data:`RESET_TOKEN_LIFETIME_MINUTES` minutes and how to ask for a
     new one. No new password path is added.

Every step is idempotent, so a store resend of a failed event can safely run
both phases again: no second account, enrolment, role audit row, seed of a
running course or welcome email.
"""

from __future__ import annotations

import html
import logging
import re
import secrets
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import ValidationError
from sqlalchemy import select, update

from app.core.document_locale import normalize_document_locale, translate
from app.core.permissions import ROLE_ALIASES, ROLE_HIERARCHY, Role
from app.modules.trainer.models import TrainerCourse, TrainerEnrolment, TrainerOffer
from app.modules.users.models import User
from app.modules.users.schemas import AdminUserCreate
from app.modules.users.service import RESET_TOKEN_LIFETIME_MINUTES, UserService, create_reset_token

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.config import Settings
    from app.core.email import EmailService
    from app.modules.trainer.webhook import OrderPaid

logger = logging.getLogger(__name__)

#: Stream C's seed entry point: seeds stage S0 for one enrolment. It opens
#: its own session, and raising means the seed failed.
SeedOnEnrol = Callable[[uuid.UUID], Awaitable[None]]

#: The role a learner needs. A viewer cannot award a bid package.
LEARNER_ROLE = Role.MANAGER

#: Enrolment states that occupy the learner's one running course.
_RUNNING = frozenset({"provisioning", "active"})
#: Enrolment states a repeated purchase leaves alone.
_KEPT = frozenset({"provisioning", "active", "queued", "completed"})

_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})?$")

ProvisioningStatus = Literal["processed", "ignored", "failed", "disabled"]
EnrolmentAction = Literal["created", "retried", "reactivated", "unchanged"]


class ProvisioningError(RuntimeError):
    """Provisioning could not build a valid account request.

    The message names fields only, never the submitted values.
    """


@dataclass(frozen=True)
class EnrolmentOutcome:
    """What provisioning did to one enrolment."""

    enrolment_id: uuid.UUID
    course_key: str
    course_title: str
    status: str
    action: EnrolmentAction


@dataclass(frozen=True)
class ProvisioningResult:
    """The outcome of one provisioning run.

    ``status`` is ``processed`` when the learner is enrolled, ``ignored`` when
    the store product grants no course here, ``failed`` when money was taken
    but nothing could be granted (``error`` says why; an admin must act), and
    ``disabled`` when the academy flag is off.
    """

    status: ProvisioningStatus
    error: str | None = None
    user_id: uuid.UUID | None = None
    is_new_user: bool = False
    role_before: str | None = None
    role_after: str | None = None
    mail_locale: str | None = None
    enrolments: tuple[EnrolmentOutcome, ...] = ()
    to_seed: tuple[uuid.UUID, ...] = ()
    needs_welcome: bool = False
    seed_failures: tuple[uuid.UUID, ...] = ()
    welcome_sent: bool = False

    @property
    def needs_completion(self) -> bool:
        """True when :func:`complete_provisioning` has work to do."""
        return self.status == "processed" and (bool(self.to_seed) or self.needs_welcome)


# ── Roles ────────────────────────────────────────────────────────────────────


def learner_role_for(current_role: str | None) -> str | None:
    """The role to raise an existing account to, or None to leave it alone.

    Only a recognised role below manager is raised. Manager, admin and their
    aliases are kept, and so is a role this platform does not recognise:
    it cannot be ranked, so changing it could lower it.
    """
    key = (current_role or "").strip().lower()
    if not key:
        return None
    try:
        role: Role | None = Role(key)
    except ValueError:
        role = ROLE_ALIASES.get(key)
    if role is None:
        return None
    if ROLE_HIERARCHY.get(role, -1) >= ROLE_HIERARCHY[LEARNER_ROLE]:
        return None
    return LEARNER_ROLE.value


def _throwaway_password() -> str:
    """A password nobody knows, satisfying the admin-create policy.

    ``token_urlsafe`` alone may lack a letter or a digit; the suffix makes the
    policy check unconditional. The value is used once and dropped.
    """
    return f"{secrets.token_urlsafe(32)}a1"


def _account_locale(locale: str | None) -> str:
    if locale and _LOCALE_RE.match(locale.strip()) and len(locale.strip()) <= 10:
        return locale.strip().replace("_", "-")
    return "en"


# ── Phase 1: inside the caller's transaction ─────────────────────────────────


async def _active_course(session: AsyncSession, course_key: str) -> TrainerCourse | None:
    """The newest active version of a course."""
    return (
        await session.execute(
            select(TrainerCourse)
            .where(TrainerCourse.course_key == course_key, TrainerCourse.status == "active")
            .order_by(TrainerCourse.loaded_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _offer_course_keys(session: AsyncSession, provider: str, offer_code: str) -> list[str]:
    rows = await session.execute(
        select(TrainerOffer.course_key)
        .where(
            TrainerOffer.provider == provider,
            TrainerOffer.product_ref == offer_code,
            TrainerOffer.is_active.is_(True),
        )
        .order_by(TrainerOffer.course_key)
    )
    return list(dict.fromkeys(rows.scalars().all()))


async def _create_account(
    session: AsyncSession,
    settings: Settings,
    *,
    email: str,
    name: str,
    locale: str,
    source: str,
) -> User:
    try:
        request = AdminUserCreate(
            email=email,
            password=_throwaway_password(),
            full_name=name or email.split("@", 1)[0],
            role=LEARNER_ROLE.value,
            locale=locale,
            is_active=True,
        )
    except ValidationError as exc:
        names = sorted({str(err["loc"][0]) for err in exc.errors() if err.get("loc")})
        # ``from None``: the ValidationError repeats the submitted values,
        # the throwaway password among them.
        raise ProvisioningError(f"invalid account fields: {', '.join(names)}") from None
    user = await UserService(session, settings).admin_create(request)
    user.metadata_ = {**(user.metadata_ or {}), "trainer": {"provisioned_by": source}}
    await session.flush()
    return user


async def provision_learner(
    session: AsyncSession,
    settings: Settings,
    *,
    email: str,
    name: str,
    locale: str | None,
    course_keys: Iterable[str],
    source: Literal["webhook", "admin"],
    order_ref: str | None = None,
    order_meta: dict | None = None,
) -> ProvisioningResult:
    """Account, role and enrolments for one buyer. Writes, never commits.

    The admin route (``POST /api/v1/trainer/admin/enrolments/``, Wave 2)
    calls this with ``source="admin"``, commits, then calls
    :func:`complete_provisioning`.

    Args:
        session: The caller's session; the caller commits.
        settings: Application settings.
        email: The buyer's email; matched case-insensitively.
        name: The buyer's name, used only for a new account.
        locale: The buyer's language, for a new account and the email.
        course_keys: Courses to enrol on, in order; the first one that can
            start starts, the rest queue.
        source: ``webhook`` or ``admin``, stored on new enrolments.
        order_ref: The store's order reference, stored on new enrolments.
        order_meta: Extra order facts stored in the enrolment metadata.

    Returns:
        The result; nothing is written when its status is not ``processed``.
    """
    if not settings.academy_mode:
        return ProvisioningResult(status="disabled", error="academy_mode_off")

    keys = list(dict.fromkeys(key for key in course_keys if key))
    if not keys:
        return ProvisioningResult(status="ignored", error="no_course")
    courses: list[TrainerCourse] = []
    for key in keys:
        course = await _active_course(session, key)
        if course is None:
            logger.error("Trainer provisioning: course %r is not loaded or not active", key)
            return ProvisioningResult(status="failed", error=f"course_not_available: {key}")
        courses.append(course)

    email_norm = email.strip().lower()
    user = (await session.execute(select(User).where(User.email == email_norm))).scalar_one_or_none()
    is_new = user is None
    role_before: str | None = None
    if user is None:
        user = await _create_account(
            session,
            settings,
            email=email_norm,
            name=name.strip(),
            locale=_account_locale(locale or courses[0].language),
            source=source,
        )
        role_after = user.role
        logger.info("Trainer provisioning created learner account %s", user.id)
    else:
        if not user.is_active or user.deleted_at is not None:
            # A deactivated account was switched off on purpose; a purchase
            # does not override that. An admin decides.
            logger.error("Trainer provisioning: account %s is deactivated, not enrolled", user.id)
            return ProvisioningResult(status="failed", error="account_inactive", user_id=user.id)
        role_before = user.role
        raised = learner_role_for(user.role)
        if raised is not None:
            # Through the user service, which writes the role_changed audit row.
            user = await UserService(session, settings).update_profile(user.id, role=raised)
            logger.info("Trainer provisioning raised account %s from %s to %s", user.id, role_before, raised)
        role_after = user.role

    user_id = user.id
    existing_rows = (
        await session.execute(
            select(TrainerEnrolment, TrainerCourse.course_key)
            .join(TrainerCourse, TrainerCourse.id == TrainerEnrolment.course_id)
            .where(TrainerEnrolment.user_id == user_id)
        )
    ).all()
    by_key: dict[str, TrainerEnrolment] = {}
    running = False
    for enrolment, course_key in existing_rows:
        by_key.setdefault(course_key, enrolment)
        running = running or enrolment.status in _RUNNING

    outcomes: list[EnrolmentOutcome] = []
    to_seed: list[uuid.UUID] = []
    needs_welcome = False
    for course in courses:
        enrolment = by_key.get(course.course_key)
        action: EnrolmentAction
        if enrolment is None:
            starts = not running
            enrolment = TrainerEnrolment(
                user_id=user_id,
                course_id=course.id,
                course_sha256=course.sha256,
                status="provisioning" if starts else "queued",
                source=source,
                order_ref=order_ref,
                current_task_n=1,
                seeded_refs={},
                metadata_={"order": dict(order_meta or {})},
            )
            session.add(enrolment)
            await session.flush()
            action = "created"
        elif enrolment.status in _KEPT:
            outcomes.append(
                EnrolmentOutcome(enrolment.id, course.course_key, course.title, enrolment.status, "unchanged")
            )
            needs_welcome = needs_welcome or not (enrolment.metadata_ or {}).get("welcome_sent_at")
            continue
        elif enrolment.status == "revoked":
            enrolment.revoked_at = None
            if running:
                enrolment.status = "queued"
            elif enrolment.project_id is not None:
                # The project survived the revoke; the course resumes in it.
                enrolment.status = "active"
            else:
                enrolment.status = "provisioning"
            action = "reactivated"
        else:  # failed
            enrolment.status = "queued" if running else "provisioning"
            action = "retried"
        await session.flush()
        if enrolment.status in _RUNNING:
            running = True
        if enrolment.status == "provisioning":
            to_seed.append(enrolment.id)
        needs_welcome = needs_welcome or not (enrolment.metadata_ or {}).get("welcome_sent_at")
        outcomes.append(EnrolmentOutcome(enrolment.id, course.course_key, course.title, enrolment.status, action))

    # A new account took the order locale, else the course language.
    mail_locale = locale or user.locale or courses[0].language
    return ProvisioningResult(
        status="processed",
        user_id=user_id,
        is_new_user=is_new,
        role_before=role_before,
        role_after=role_after,
        mail_locale=mail_locale,
        enrolments=tuple(outcomes),
        to_seed=tuple(to_seed),
        needs_welcome=needs_welcome,
    )


async def provision_order_paid(
    session: AsyncSession,
    settings: Settings,
    order: OrderPaid,
    *,
    provider: str,
    source: Literal["webhook", "admin"] = "webhook",
) -> ProvisioningResult:
    """Provision the buyer of one paid order. Writes, never commits.

    The store product is looked up in ``oe_trainer_offer`` under
    ``provider``; a product with no active offer grants nothing here and is
    ``ignored`` (it may be another product in the same store).
    """
    if not settings.academy_mode:
        return ProvisioningResult(status="disabled", error="academy_mode_off")
    keys = await _offer_course_keys(session, provider, order.offer_code)
    if not keys:
        logger.info("Trainer provisioning: no active offer for product %r of %s", order.offer_code, provider)
        return ProvisioningResult(status="ignored", error="unknown_offer")
    return await provision_learner(
        session,
        settings,
        email=order.email,
        name=order.name,
        locale=order.locale,
        course_keys=keys,
        source=source,
        order_ref=order.order_ref,
        order_meta={
            "provider": provider,
            "event_id": order.event_id,
            "offer_code": order.offer_code,
            "paid_at": order.paid_at.isoformat(),
        },
    )


# ── Phase 2: after the caller's commit ───────────────────────────────────────


async def complete_provisioning(
    session: AsyncSession,
    settings: Settings,
    result: ProvisioningResult,
    *,
    seed_on_enrol: SeedOnEnrol,
    email_service: EmailService | None = None,
) -> ProvisioningResult:
    """Seed the courses that start now and send the welcome email. Commits.

    A seed failure marks that enrolment ``failed`` with the error class in
    its metadata, logs it for the admin and is returned in
    ``seed_failures``; it never raises, so the store is still answered 200
    (a retry cannot fix our seed). The enrolment the seeder finished is
    switched from ``provisioning`` to ``active`` unless the seeder already
    moved it on.
    """
    if not result.needs_completion or result.user_id is None:
        return result

    failures: list[uuid.UUID] = []
    for enrolment_id in result.to_seed:
        try:
            await seed_on_enrol(enrolment_id)
        except Exception as exc:
            logger.error(
                "Trainer seed stage S0 failed for enrolment %s: %s",
                enrolment_id,
                type(exc).__name__,
                exc_info=True,
            )
            enrolment = await session.get(TrainerEnrolment, enrolment_id)
            if enrolment is not None:
                enrolment.status = "failed"
                enrolment.metadata_ = {
                    **(enrolment.metadata_ or {}),
                    "seed_error": type(exc).__name__,
                }
            failures.append(enrolment_id)
        else:
            await session.execute(
                update(TrainerEnrolment)
                .where(TrainerEnrolment.id == enrolment_id, TrainerEnrolment.status == "provisioning")
                .values(status="active", started_at=datetime.now(UTC))
                .execution_options(synchronize_session="fetch")
            )
        await session.commit()

    welcome_sent = False
    if result.needs_welcome:
        welcome_sent = await _send_welcome(session, settings, result, email_service)

    statuses = {}
    for item in result.enrolments:
        enrolment = await session.get(TrainerEnrolment, item.enrolment_id, populate_existing=True)
        statuses[item.enrolment_id] = enrolment.status if enrolment is not None else item.status
    return replace(
        result,
        enrolments=tuple(replace(item, status=statuses[item.enrolment_id]) for item in result.enrolments),
        seed_failures=tuple(failures),
        welcome_sent=welcome_sent,
    )


async def _send_welcome(
    session: AsyncSession,
    settings: Settings,
    result: ProvisioningResult,
    email_service: EmailService | None,
) -> bool:
    """Send the welcome email once and stamp the enrolments it covered."""
    from app.core.email import EmailMessage, get_email_service

    user = await session.get(User, result.user_id)
    if user is None:
        return False
    service = email_service or get_email_service()
    base_url = settings.resolved_frontend_url
    reset_url = None
    if result.is_new_user:
        token = create_reset_token(user, settings)
        # The same URL ``UserService.forgot_password`` sends.
        reset_url = f"{base_url}/auth/reset?token={token}"
    locale = welcome_locale(result.mail_locale)
    titles = [item.course_title for item in result.enrolments]
    queued = bool(result.enrolments) and all(item.status == "queued" for item in result.enrolments)
    subject = welcome_subject(locale, titles, queued=queued)
    body = welcome_html(
        locale=locale,
        name=user.full_name or user.email.split("@", 1)[0],
        email=user.email,
        course_titles=titles,
        queued=queued,
        reset_url=reset_url,
        forgot_url=f"{base_url}/forgot-password",
        academy_url=f"{base_url}/academy",
    )
    try:
        delivery = await service.send(
            EmailMessage(to=user.email, subject=subject, html_body=body, tags=["trainer_welcome"]),
        )
    except Exception:
        logger.error("Trainer welcome email for account %s could not be sent", user.id, exc_info=True)
        return False
    if not delivery.ok:
        logger.warning("Trainer welcome email for account %s was not delivered: %s", user.id, delivery.reason)
        return False

    stamp = datetime.now(UTC).isoformat()
    for item in result.enrolments:
        enrolment = await session.get(TrainerEnrolment, item.enrolment_id)
        if enrolment is not None:
            enrolment.metadata_ = {**(enrolment.metadata_ or {}), "welcome_sent_at": stamp}
    await session.commit()
    logger.info("Trainer welcome email sent to account %s", user.id)
    return True


# ── The welcome email ────────────────────────────────────────────────────────

DEFAULT_LOCALE = "en"

#: Plain text only. The renderer escapes every value and adds the markup, so a
#: translation never carries HTML. The reset link is only ever the button
#: target, never body text, so it is not in the opening lines a log preview
#: of the email shows.
_TABLES: dict[str, dict[str, str]] = {
    "en": {
        "subject_ready": "Your course is ready: {course}",
        "subject_queued": "Your course is booked: {course}",
        "heading": "Welcome to the Academy",
        "greeting": "Hello {name},",
        "intro_ready": "Thank you for your purchase. Your course {course} is ready in your own practice project.",
        "intro_queued": (
            "Thank you for your purchase. Your course {course} is booked. "
            "It starts when you finish the course you are taking now."
        ),
        "new_account": (
            "We have created an account for you with the email address {email}. "
            "Use the button below to choose your password."
        ),
        "link_expiry": (
            "The button works once and expires after {minutes} minutes. If it has expired, "
            "open {forgot_url}, enter this email address and we will send you a new link."
        ),
        "existing_account": "Sign in with your existing account {email}. Your course is waiting in the Academy.",
        "forgot_hint": "Forgot your password? Open {forgot_url} and enter this email address to get a new link.",
        "cta_set_password": "Choose your password",
        "cta_open": "Open the Academy",
    },
    "de": {
        "subject_ready": "Ihr Kurs ist bereit: {course}",
        "subject_queued": "Ihr Kurs ist gebucht: {course}",
        "heading": "Willkommen in der Academy",
        "greeting": "Hallo {name},",
        "intro_ready": (
            "Vielen Dank für Ihren Kauf. Ihr Kurs {course} ist in Ihrem eigenen Übungsprojekt für Sie bereit."
        ),
        "intro_queued": (
            "Vielen Dank für Ihren Kauf. Ihr Kurs {course} ist gebucht. "
            "Er beginnt, sobald Sie Ihren aktuellen Kurs abgeschlossen haben."
        ),
        "new_account": (
            "Wir haben ein Konto für Sie mit der E-Mail-Adresse {email} angelegt. "
            "Über die Schaltfläche unten legen Sie Ihr Passwort fest."
        ),
        "link_expiry": (
            "Die Schaltfläche funktioniert einmal und läuft nach {minutes} Minuten ab. Ist sie abgelaufen, "
            "öffnen Sie {forgot_url}, geben Sie diese E-Mail-Adresse ein, und wir senden Ihnen einen neuen Link."
        ),
        "existing_account": (
            "Melden Sie sich mit Ihrem bestehenden Konto {email} an. Ihr Kurs wartet in der Academy auf Sie."
        ),
        "forgot_hint": (
            "Passwort vergessen? Öffnen Sie {forgot_url} und geben Sie diese E-Mail-Adresse ein, "
            "um einen neuen Link zu erhalten."
        ),
        "cta_set_password": "Passwort festlegen",
        "cta_open": "Academy öffnen",
    },
    "fr": {
        "subject_ready": "Votre formation est prête : {course}",
        "subject_queued": "Votre formation est réservée : {course}",
        "heading": "Bienvenue à l'Academy",
        "greeting": "Bonjour {name},",
        "intro_ready": (
            "Merci pour votre achat. Votre formation {course} vous attend dans votre propre projet d'entraînement."
        ),
        "intro_queued": (
            "Merci pour votre achat. Votre formation {course} est réservée. "
            "Elle commencera lorsque vous aurez terminé la formation en cours."
        ),
        "new_account": (
            "Nous avons créé un compte pour vous avec l'adresse e-mail {email}. "
            "Utilisez le bouton ci-dessous pour choisir votre mot de passe."
        ),
        "link_expiry": (
            "Le bouton fonctionne une seule fois et expire au bout de {minutes} minutes. S'il a expiré, "
            "ouvrez {forgot_url}, saisissez cette adresse e-mail et nous vous enverrons un nouveau lien."
        ),
        "existing_account": (
            "Connectez-vous avec votre compte existant {email}. Votre formation vous attend dans l'Academy."
        ),
        "forgot_hint": (
            "Mot de passe oublié ? Ouvrez {forgot_url} et saisissez cette adresse e-mail pour recevoir un nouveau lien."
        ),
        "cta_set_password": "Choisir mon mot de passe",
        "cta_open": "Ouvrir l'Academy",
    },
    "es": {
        "subject_ready": "Su curso está listo: {course}",
        "subject_queued": "Su curso está reservado: {course}",
        "heading": "Bienvenido a la Academy",
        "greeting": "Hola, {name}:",
        "intro_ready": "Gracias por su compra. Su curso {course} le espera en su propio proyecto de práctica.",
        "intro_queued": (
            "Gracias por su compra. Su curso {course} está reservado. "
            "Empezará cuando termine el curso que está haciendo ahora."
        ),
        "new_account": (
            "Hemos creado una cuenta para usted con la dirección de correo {email}. "
            "Use el botón de abajo para elegir su contraseña."
        ),
        "link_expiry": (
            "El botón funciona una sola vez y caduca a los {minutes} minutos. Si ha caducado, "
            "abra {forgot_url}, introduzca esta dirección de correo y le enviaremos un enlace nuevo."
        ),
        "existing_account": "Inicie sesión con su cuenta actual {email}. Su curso le espera en la Academy.",
        "forgot_hint": (
            "¿Ha olvidado su contraseña? Abra {forgot_url} e introduzca esta dirección de correo "
            "para recibir un enlace nuevo."
        ),
        "cta_set_password": "Elegir contraseña",
        "cta_open": "Abrir la Academy",
    },
    "ru": {
        "subject_ready": "Ваш курс готов: {course}",
        "subject_queued": "Ваш курс оплачен: {course}",
        "heading": "Добро пожаловать в Academy",
        "greeting": "Здравствуйте, {name}!",
        "intro_ready": "Спасибо за покупку. Курс {course} уже ждёт вас в вашем учебном проекте.",
        "intro_queued": ("Спасибо за покупку. Курс {course} оплачен и начнётся, когда вы закончите текущий курс."),
        "new_account": (
            "Мы создали для вас учётную запись с адресом {email}. Нажмите кнопку ниже, чтобы задать пароль."
        ),
        "link_expiry": (
            "Кнопка срабатывает один раз и действует {minutes} минут. Если срок истёк, откройте "
            "{forgot_url}, введите этот адрес электронной почты, и мы пришлём новую ссылку."
        ),
        "existing_account": "Войдите под своей учётной записью {email}. Курс ждёт вас в разделе Academy.",
        "forgot_hint": (
            "Забыли пароль? Откройте {forgot_url} и введите этот адрес электронной почты, чтобы получить новую ссылку."
        ),
        "cta_set_password": "Задать пароль",
        "cta_open": "Открыть Academy",
    },
}

#: Languages the welcome email is written in; others read English.
WELCOME_LOCALES: tuple[str, ...] = tuple(_TABLES)


def welcome_locale(locale: str | None) -> str:
    """The catalogue language for a locale (``de-AT`` reads ``de``)."""
    return normalize_document_locale(locale, WELCOME_LOCALES, DEFAULT_LOCALE)


def _t(locale: str, key: str, **params: str) -> str:
    return translate(_TABLES, welcome_locale(locale), key, DEFAULT_LOCALE, **params)


def welcome_subject(locale: str, course_titles: list[str], *, queued: bool) -> str:
    """The subject line, plain text."""
    return _t(locale, "subject_queued" if queued else "subject_ready", course=", ".join(course_titles))


def welcome_html(
    *,
    locale: str,
    name: str,
    email: str,
    course_titles: list[str],
    queued: bool,
    reset_url: str | None,
    forgot_url: str,
    academy_url: str,
) -> str:
    """Render the welcome email through the shared email shell.

    ``reset_url`` is given for a new account only; it becomes the button.
    An existing account gets a button to the Academy and the forgot-password
    hint instead.
    """
    from app.core.email import wrap

    def sentence(key: str, **values: str) -> str:
        # Escape the template, then splice in the already-escaped values, so
        # neither a translation nor a buyer's name can inject markup.
        marks = {key_: f"\x00{key_}\x00" for key_ in values}
        text = html.escape(_t(locale, key, **marks))
        for key_, value in values.items():
            text = text.replace(f"\x00{key_}\x00", value)
        return text

    def strong(value: str) -> str:
        return f"<strong>{html.escape(value)}</strong>"

    courses = ", ".join(course_titles)
    parts = [
        f"<p>{sentence('greeting', name=html.escape(name))}</p>",
        f"<p>{sentence('intro_queued' if queued else 'intro_ready', course=strong(courses))}</p>",
    ]
    forgot = html.escape(forgot_url)
    heading = html.escape(_t(locale, "heading"))
    if reset_url is not None:
        parts.append(f"<p>{sentence('new_account', email=strong(email))}</p>")
        parts.append(
            "<p style='font-size:13px; color:#6e6e73;'>"
            f"{sentence('link_expiry', minutes=str(RESET_TOKEN_LIFETIME_MINUTES), forgot_url=forgot)}</p>"
        )
        return wrap(
            heading, "".join(parts), html.escape(reset_url, quote=True), html.escape(_t(locale, "cta_set_password"))
        )
    parts.append(f"<p>{sentence('existing_account', email=strong(email))}</p>")
    parts.append(f"<p style='font-size:13px; color:#6e6e73;'>{sentence('forgot_hint', forgot_url=forgot)}</p>")
    return wrap(heading, "".join(parts), html.escape(academy_url, quote=True), html.escape(_t(locale, "cta_open")))


__all__ = [
    "DEFAULT_LOCALE",
    "LEARNER_ROLE",
    "WELCOME_LOCALES",
    "EnrolmentOutcome",
    "ProvisioningError",
    "ProvisioningResult",
    "SeedOnEnrol",
    "complete_provisioning",
    "learner_role_for",
    "provision_learner",
    "provision_order_paid",
    "welcome_html",
    "welcome_locale",
    "welcome_subject",
]
