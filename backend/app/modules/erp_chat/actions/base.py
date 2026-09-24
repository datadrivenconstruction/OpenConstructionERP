# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The action framework: what an action is, who is acting, and how it fails.

An :class:`ActionSpec` describes one kind of change the assistant may propose
(add a BOQ position, create a task, ...). It owns four things:

* ``build`` - turn the model's arguments (or a person's edits) into a checked,
  normalised payload plus the field table the person reviews. It reads the
  database, resolves names to ids and computes derived values, and it writes
  nothing. It is run again at apply time, so every check it makes is made
  against the database as it is when the person clicks Apply.
* ``check_apply_gates`` - the gates the record's own REST route runs: the same
  permission and the same project / owner check, for the person applying.
* ``apply`` - the domain write, through the domain service, plus whatever the
  REST route writes beside the service call (e.g. a ``BOQActivityLog`` row).
* ``revert`` (optional) - undo, refused when the record changed since apply.

Errors are :class:`ActionError` subclasses. Each carries an HTTP status, a
stable ``code`` the dock can branch on, an i18n ``message_key`` and English
``message``, and optional ``field_errors`` / ``options``. The router turns them
into a structured ``detail``; the chat stream turns them into an error result
the model can react to (ask the user which BOQ, fix a value).
"""

from __future__ import annotations

import logging
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, ClassVar

from fastapi import HTTPException, status
from sqlalchemy import select

from app.modules.erp_chat.actions import labels
from app.modules.erp_chat.schemas import (
    ActionEntityRef,
    ActionField,
    ActionFieldKind,
    ActionFieldOption,
    ActionNote,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.erp_chat.models import ChatAction

logger = logging.getLogger(__name__)

# ── Errors ──────────────────────────────────────────────────────────────────


class ActionError(Exception):
    """Base of every refusal an action can produce.

    Args:
        message: English sentence. Defaults to the text of ``code`` in
            :data:`labels.ERRORS`.
        code: Stable machine code; also selects ``message_key``.
        field_errors: ``{payload_key: {"code", "message_key", "message"}}``.
        options: Choices the model or the person can pick from (e.g. the
            project's BOQs when it has several).
        params: Values for the placeholders of the translated message.
    """

    status_code: ClassVar[int] = status.HTTP_400_BAD_REQUEST
    default_code: ClassVar[str] = "validation_error"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        field_errors: dict[str, dict[str, str]] | None = None,
        options: list[dict[str, Any]] | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        self.code = code or self.default_code
        self.message = message or labels.ERRORS.get(self.code) or labels.ERRORS[self.default_code]
        self.field_errors = field_errors or {}
        self.options = options or []
        self.params = params or {}
        super().__init__(self.message)

    @property
    def message_key(self) -> str:
        """i18n key of the message (falls back to the class default code's key)."""
        code = self.code if self.code in labels.ERRORS else self.default_code
        return f"{labels.ERROR_PREFIX}{code}"

    def to_detail(self) -> dict[str, Any]:
        """The structured ``detail`` the router sends (``message`` is what the shared API client shows)."""
        detail: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "message_key": self.message_key,
        }
        if self.field_errors:
            detail["field_errors"] = self.field_errors
        if self.options:
            detail["options"] = self.options
        if self.params:
            detail["params"] = self.params
        return detail

    def to_http(self) -> HTTPException:
        """The equivalent ``HTTPException`` with a structured detail."""
        return HTTPException(status_code=self.status_code, detail=self.to_detail())

    def to_tool_result(self) -> dict[str, Any]:
        """An error result for the model, in the chat's existing ``error`` renderer shape.

        The model reads ``data``: the code, the sentence, which argument is
        wrong and, where it helps, the options to ask the person about.
        """
        data: dict[str, Any] = {"error": self.code, "message": self.message, "i18n_key": self.message_key}
        if self.field_errors:
            data["field_errors"] = {key: err.get("message", "") for key, err in self.field_errors.items()}
        if self.options:
            data["options"] = self.options
        hint = " Nothing was proposed; fix the arguments or ask the user, then call the tool again."
        return {"renderer": "error", "data": data, "summary": f"Error: {self.message}{hint}"}


class ActionValidationError(ActionError):
    """Arguments or edits that do not make a valid change (422)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = "validation_error"


class ActionConflictError(ActionError):
    """The change conflicts with the current state: locked bill, drift, already decided (409)."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "domain_error"


class ActionNotFoundError(ActionError):
    """The action or the record is not there, or the caller may not see it (404)."""

    status_code = status.HTTP_404_NOT_FOUND
    default_code = "not_found"


class ActionPermissionError(ActionError):
    """The caller lacks the permission the record's REST route requires (403)."""

    status_code = status.HTTP_403_FORBIDDEN
    default_code = "forbidden"


def error_from_http(exc: HTTPException) -> ActionError:
    """Translate a domain service's ``HTTPException`` into an :class:`ActionError`.

    The status is kept; the code says what kind of refusal it was so the dock
    can explain it. A locked bill keeps its dedicated ``locked`` code.
    """
    detail = exc.detail
    if isinstance(detail, dict):
        message = str(detail.get("message") or detail.get("detail") or detail.get("error") or "")
    else:
        message = str(detail or "")
    if exc.status_code == status.HTTP_404_NOT_FOUND:
        return ActionNotFoundError(message or None, code="target_missing")
    if exc.status_code == status.HTTP_403_FORBIDDEN:
        return ActionPermissionError(message or None)
    if exc.status_code == status.HTTP_409_CONFLICT:
        code = "locked" if "locked" in message.lower() else "domain_error"
        return ActionConflictError(message or None, code=code)
    return ActionValidationError(message or None, code="domain_error")


# ── Who is acting ───────────────────────────────────────────────────────────


def coerce_uuid(value: Any) -> uuid.UUID | None:
    """Return ``value`` as a UUID, or None when it is empty or malformed."""
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value).strip())
    except (ValueError, TypeError, AttributeError):
        return None


@dataclass
class ActionContext:
    """The person an action runs for, and the project the conversation is about.

    At proposal time ``user_id`` is the person talking to the assistant; at
    apply, reject, edit and undo time it is the person clicking. Every gate is
    evaluated for ``user_id`` and never for anyone else, which is what keeps
    the assistant from having more rights than the person who applies.

    ``role`` is the global role read from the database, and permissions are
    resolved from it through the live registry, exactly as the auth
    dependency re-hydrates a request's permissions.
    """

    session: AsyncSession
    user_id: uuid.UUID
    role: str = ""
    project_id: uuid.UUID | None = None

    @classmethod
    async def load(
        cls,
        session: AsyncSession,
        user_id: str | uuid.UUID,
        *,
        project_id: str | uuid.UUID | None = None,
    ) -> ActionContext:
        """Build a context for ``user_id``, reading their role from the database."""
        from app.modules.users.models import User

        uid = coerce_uuid(user_id)
        if uid is None:
            raise ActionNotFoundError(code="not_found")
        role = (await session.execute(select(User.role).where(User.id == uid))).scalar_one_or_none()
        return cls(session=session, user_id=uid, role=str(role or ""), project_id=coerce_uuid(project_id))

    def with_project(self, project_id: str | uuid.UUID | None) -> ActionContext:
        """The same person, looking at another project."""
        return ActionContext(
            session=self.session,
            user_id=self.user_id,
            role=self.role,
            project_id=coerce_uuid(project_id),
        )

    @property
    def is_admin(self) -> bool:
        """True for the global admin role, which the REST gates let through everywhere."""
        return self.role.strip().lower() == "admin"

    @property
    def auth_payload(self) -> dict[str, Any]:
        """The slice of a JWT payload the module guards read (``role`` for the admin bypass)."""
        return {"sub": str(self.user_id), "role": self.role}

    def has_permission(self, permission: str) -> bool:
        """Whether the role holds ``permission`` in the live registry (admin holds all)."""
        from app.core.permissions import permission_registry

        return permission_registry.role_has_permission(self.role, permission)

    def require_permissions(self, permissions: tuple[str, ...]) -> None:
        """Raise 403 unless every permission is held, like ``RequirePermission`` on the route."""
        for permission in permissions:
            if not self.has_permission(permission):
                raise ActionPermissionError(
                    labels.ERRORS["forbidden"],
                    code="forbidden",
                    params={"permission": permission},
                )

    async def require_project_access(self, project_id: uuid.UUID) -> None:
        """Run ``verify_project_access`` for this person; missing and denied are both 404."""
        from app.dependencies import verify_project_access

        try:
            await verify_project_access(project_id, str(self.user_id), self.session)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_404_NOT_FOUND:
                raise ActionNotFoundError(code="project_not_found") from exc
            raise error_from_http(exc) from exc


# ── Values ──────────────────────────────────────────────────────────────────


class FieldErrors:
    """Collects per-field problems so the person (or the model) sees all of them at once."""

    def __init__(self) -> None:
        self.errors: dict[str, dict[str, str]] = {}

    def add(self, key: str, code: str, message: str | None = None) -> None:
        """Record one problem with payload key ``key`` (the first one per key wins)."""
        if key in self.errors:
            return
        self.errors[key] = {
            "code": code,
            "message_key": f"{labels.FIELD_ERROR_PREFIX}{code}",
            "message": message or labels.FIELD_ERRORS.get(code, code),
        }

    def __bool__(self) -> bool:
        return bool(self.errors)

    def raise_if_any(self) -> None:
        """Raise one 422 carrying every collected problem."""
        if self.errors:
            fields = ", ".join(sorted(self.errors))
            raise ActionValidationError(
                f"{labels.ERRORS['validation_error']} ({fields})",
                code="validation_error",
                field_errors=dict(self.errors),
            )


def _present(args: dict[str, Any], key: str) -> bool:
    value = args.get(key)
    return value is not None and not (isinstance(value, str) and value.strip() == "")


def parse_text(
    args: dict[str, Any],
    key: str,
    errors: FieldErrors,
    *,
    required: bool = False,
    max_length: int = 500,
) -> str | None:
    """A trimmed string, or None when absent. Too long is an error, not a silent cut."""
    if not _present(args, key):
        if required:
            errors.add(key, "required")
        return None
    raw = args[key]
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float, Decimal)):
        errors.add(key, "required")
        return None
    text = str(raw).strip()
    if len(text) > max_length:
        errors.add(key, "too_long", f"{labels.FIELD_ERRORS['too_long']} (max {max_length})")
        return None
    return text


_NUMBER_JUNK = re.compile(r"[\s  ']")


def parse_decimal(
    args: dict[str, Any],
    key: str,
    errors: FieldErrors,
    *,
    required: bool = False,
    allow_negative: bool = False,
) -> Decimal | None:
    """A Decimal from a JSON number or a numeric string, or None when absent.

    Accepts the spellings a model or a person produces: ``120``, ``"120.5"``,
    ``"1 200,50"``, ``"1,200.50"``. A comma alone is a decimal separator; with
    a dot present the comma is a thousands separator.
    """
    if not _present(args, key):
        if required:
            errors.add(key, "required")
        return None
    raw = args[key]
    if isinstance(raw, bool):
        errors.add(key, "not_a_number")
        return None
    if isinstance(raw, float):
        value = Decimal(repr(raw))
    elif isinstance(raw, (int, Decimal)):
        value = Decimal(raw)
    else:
        text = _NUMBER_JUNK.sub("", str(raw))
        if "," in text and "." in text:
            text = text.replace(",", "")
        elif "," in text:
            text = text.replace(",", ".")
        try:
            value = Decimal(text)
        except InvalidOperation:
            errors.add(key, "not_a_number")
            return None
    if not value.is_finite():
        errors.add(key, "not_a_number")
        return None
    if value < 0 and not allow_negative:
        errors.add(key, "negative")
        return None
    return value


def parse_date(args: dict[str, Any], key: str, errors: FieldErrors) -> str | None:
    """An ISO ``YYYY-MM-DD`` date from a date or datetime string, or None when absent."""
    if not _present(args, key):
        return None
    raw = args[key]
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()
    text = str(raw).strip()
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        errors.add(key, "invalid_date")
        return None


def parse_enum(
    args: dict[str, Any],
    key: str,
    errors: FieldErrors,
    *,
    allowed: tuple[str, ...],
    default: str | None = None,
) -> str | None:
    """One of ``allowed`` (case-insensitive), the default when absent."""
    if not _present(args, key):
        return default
    value = str(args[key]).strip().lower().replace(" ", "_")
    if value not in allowed:
        errors.add(key, "invalid_option", f"{labels.FIELD_ERRORS['invalid_option']} ({', '.join(allowed)})")
        return None
    return value


_YES: frozenset[str] = frozenset({"yes", "true", "y", "1", "on"})
_NO: frozenset[str] = frozenset({"no", "false", "n", "0", "off"})


def parse_flag(args: dict[str, Any], key: str, errors: FieldErrors, *, default: bool = False) -> bool:
    """A yes/no value from a JSON boolean (the model) or the card's ``yes`` / ``no`` option."""
    if not _present(args, key):
        return default
    raw = args[key]
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in _YES:
        return True
    if text in _NO:
        return False
    errors.add(key, "invalid_option", f"{labels.FIELD_ERRORS['invalid_option']} (yes, no)")
    return default


def flag_option(value: bool) -> str:
    """The ``yes_no`` option a flag is shown and stored as."""
    return "yes" if value else "no"


def parse_whole(args: dict[str, Any], key: str, errors: FieldErrors, *, required: bool = False) -> int | None:
    """A whole, non-negative number (days, counts), or None when absent."""
    number = parse_decimal(args, key, errors, required=required)
    if number is None:
        return None
    if number != number.to_integral_value():
        errors.add(key, "not_whole_number")
        return None
    return int(number)


def parse_percent(args: dict[str, Any], key: str, errors: FieldErrors, *, required: bool = False) -> Decimal | None:
    """Percentage points from 0 to 100, read from ``60``, ``"60"``, ``"60 %"`` or ``"60,5"``."""
    raw = args.get(key)
    if isinstance(raw, str):
        args = {**args, key: raw.strip().removesuffix("%")}
    number = parse_decimal(args, key, errors, required=required)
    if number is not None and number > 100:
        errors.add(key, "percent_range")
        return None
    return number


def decimal_str(value: Decimal | str | int | float | None) -> str | None:
    """Canonical plain string of a number: no exponent, no trailing zeros (``"120"``, ``"12.5"``)."""
    if value is None:
        return None
    number = value if isinstance(value, Decimal) else to_decimal(value)
    if number is None:
        return None
    text = format(number.normalize(), "f")
    return "0" if text in {"-0", ""} else text


def to_decimal(value: Any) -> Decimal | None:
    """Best-effort Decimal of a stored number (strings in the BOQ tables), None when unreadable."""
    if value is None or value == "":
        return None
    try:
        number = Decimal(repr(value)) if isinstance(value, float) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() else None


def to_number(value: Any) -> int | float | None:
    """A JSON number for display in a field (ints stay ints)."""
    number = to_decimal(value)
    if number is None:
        return None
    if number == number.to_integral_value():
        return int(number)
    return float(number)


def same_value(a: Any, b: Any) -> bool:
    """Equality that treats ``"120.0000"`` and ``120`` as the same number and strips text."""
    da, db = to_decimal(a), to_decimal(b)
    if da is not None and db is not None:
        return da == db
    norm_a = a.strip() if isinstance(a, str) else a
    norm_b = b.strip() if isinstance(b, str) else b
    if norm_a in ("", None) and norm_b in ("", None):
        return True
    return norm_a == norm_b


# ── Preview pieces ──────────────────────────────────────────────────────────


def make_field(
    key: str,
    kind: ActionFieldKind,
    value: Any,
    *,
    before: Any = None,
    currency: str | None = None,
    unit: str | None = None,
    editable: bool = False,
    required: bool = False,
    options_for: str | None = None,
    options: list[ActionFieldOption] | None = None,
) -> ActionField:
    """One field-table row, labelled from :mod:`labels` so every key has English text.

    An ``enum`` offers the fixed choices of ``labels.OPTIONS`` (``options_for``
    names another field's list), or ``options`` when the choices are data, such
    as the members of a project.
    """
    if kind == "enum" and options is None:
        source = options_for or key
        options = [
            ActionFieldOption(value=value_, label_key=labels.option_key(source, value_), label=text)
            for value_, text in labels.OPTIONS[source].items()
        ]
    return ActionField(
        key=key,
        label_key=labels.field_key(key),
        label=labels.FIELDS[key],
        kind=kind,
        value=value,
        before=before,
        currency=currency or None,
        unit=unit or None,
        options=options,
        editable=editable,
        required=required,
    )


def make_note(
    name: str,
    *,
    params: dict[str, Any] | None = None,
    field_key: str | None = None,
    tone: str = "info",
) -> ActionNote:
    """A note from :data:`labels.NOTES`, with the English rendered from ``params``."""
    text = labels.NOTES[name]
    for param, value in (params or {}).items():
        text = text.replace("{{" + param + "}}", str(value))
    return ActionNote(
        key=f"{labels.NOTE_PREFIX}{name}",
        text=text,
        params=dict(params or {}),
        field=field_key,
        tone="warning" if tone == "warning" else "info",
    )


@dataclass
class ActionDraft:
    """What ``build`` returns: a checked payload and everything the person reviews.

    ``payload`` must be accepted by ``build`` again unchanged (build is run on
    the stored payload at edit and at apply time).
    """

    payload: dict[str, Any]
    fields: list[ActionField]
    project_id: uuid.UUID | None
    subtitle: str | None = None
    target: ActionEntityRef | None = None
    before_state: dict[str, Any] | None = None
    notes: list[ActionNote] = field(default_factory=list)

    def preview(self) -> dict[str, Any]:
        """The JSON stored in ``ChatAction.preview``."""
        return {
            "fields": [f.model_dump(mode="json") for f in self.fields],
            "subtitle": self.subtitle,
            "target": self.target.model_dump(mode="json") if self.target else None,
            "notes": [n.model_dump(mode="json") for n in self.notes],
        }


@dataclass
class AppliedResult:
    """What ``apply`` returns: the record written and its state, for the result and the audit row."""

    entity_type: str
    entity_id: str
    label: str | None
    url: str | None
    after_state: dict[str, Any]
    audit_action: str = "created"
    before_state: dict[str, Any] | None = None


# ── The spec ────────────────────────────────────────────────────────────────

_CONFIDENCE_SCHEMA: dict[str, Any] = {
    "type": "number",
    "minimum": 0,
    "maximum": 1,
    "description": "How sure you are that this is what the user asked for, from 0 to 1.",
}
_RATIONALE_SCHEMA: dict[str, Any] = {
    "type": "string",
    "maxLength": 500,
    "description": "One short sentence, in the user's language, saying why you propose this change.",
}


class ActionSpec(ABC):
    """One kind of change the assistant may propose. Subclass, fill the class vars, register."""

    action_type: ClassVar[str]
    tool_name: ClassVar[str]
    tool_description: ClassVar[str]
    input_properties: ClassVar[dict[str, Any]]
    required_args: ClassVar[tuple[str, ...]] = ()
    entity_type: ClassVar[str]
    apply_permissions: ClassVar[tuple[str, ...]]
    revert_permissions: ClassVar[tuple[str, ...]] = ()
    reversible: ClassVar[bool] = False
    # Manifest names of the modules the change is written to (``"oe_rfi"``). The registry offers
    # the tool, and the service applies the change, only while all of them are loaded and enabled.
    modules: ClassVar[tuple[str, ...]] = ()

    @property
    def title(self) -> str:
        """English title of the action type (the dock translates ``title_key``)."""
        return labels.TITLES[self.action_type]

    @property
    def title_key(self) -> str:
        """i18n key of the title."""
        return labels.title_key(self.action_type)

    def input_schema(self) -> dict[str, Any]:
        """JSON schema of the tool's arguments, with ``confidence`` and ``rationale`` added."""
        return {
            "type": "object",
            "properties": {
                **self.input_properties,
                "confidence": dict(_CONFIDENCE_SCHEMA),
                "rationale": dict(_RATIONALE_SCHEMA),
            },
            "required": list(self.required_args),
        }

    def tool_definition(self) -> dict[str, Any]:
        """The tool as the Anthropic API takes it (``name``, ``description``, ``input_schema``)."""
        return {
            "name": self.tool_name,
            "description": self.tool_description,
            "input_schema": self.input_schema(),
        }

    # Keys a PATCH may carry besides the editable fields (e.g. a picked member id).
    patch_aliases: ClassVar[frozenset[str]] = frozenset()

    def merge_patch(self, payload: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        """Lay a person's edits over the stored payload before it is built again."""
        return {**payload, **patch}

    def edit_view(self, payload: dict[str, Any]) -> dict[str, Any]:
        """The part of a payload that counts when asking "did a person edit this?".

        A spec drops values it derives itself (an automatic position number
        re-assigned at apply time), so ``edited`` means a human changed it.
        """
        return dict(payload)

    @abstractmethod
    async def build(
        self,
        ctx: ActionContext,
        args: dict[str, Any],
        *,
        prior: ChatAction | None = None,
    ) -> ActionDraft:
        """Check and normalise ``args`` into a draft. Reads, never writes.

        ``prior`` is the stored action when this is an edit or an apply; a
        spec uses it to keep what the proposal was based on (``before_state``)
        instead of re-reading it, so drift since the proposal is detected.
        """

    @abstractmethod
    async def check_apply_gates(self, ctx: ActionContext, payload: dict[str, Any]) -> None:
        """The REST route's gates for ``ctx.user_id``: permission first (403), then access (404)."""

    @abstractmethod
    async def apply(self, ctx: ActionContext, action: ChatAction, draft: ActionDraft) -> AppliedResult:
        """The domain write through the domain service, plus the route's own side effects."""

    async def check_revert_gates(self, ctx: ActionContext, action: ChatAction) -> None:
        """The gates of the REST route that undoing corresponds to. Not reversible by default."""
        raise ActionConflictError(code="not_reversible")

    async def revert(self, ctx: ActionContext, action: ChatAction) -> dict[str, Any] | None:
        """Undo an applied action.

        Raise ``changed_since_apply`` when the record was edited since, and
        ``target_missing`` when it no longer exists. Returns the record's state
        after the undo (None when the undo deleted it).
        """
        raise ActionConflictError(code="not_reversible")

    def revert_hint_key(self, action: ChatAction) -> str | None:
        """i18n key of a side effect that undo cannot take back, when there is one."""
        return None
