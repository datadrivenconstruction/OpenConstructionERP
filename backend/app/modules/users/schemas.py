# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""User Pydantic schemas for request/response validation."""

import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core.onboarding_presets import is_saveable_company_size, is_saveable_company_type


def _sanitize_name(name: str) -> str:
    """Strip HTML tags from a name to prevent XSS."""
    return re.sub(r"<[^>]+>", "", name).strip()


# A small set of common/leaked passwords to reject outright. Cheap defence
# against the most embarrassing weak passwords without bringing in a 100k+
# entry breach corpus. Stored lowercase for case-insensitive matching.
_COMMON_PASSWORDS: frozenset[str] = frozenset(
    {
        "password",
        "password1",
        "password123",
        "12345678",
        "123456789",
        "1234567890",
        "1234567",
        "qwerty123",
        "qwertyuiop",
        "qwerty12",
        "letmein",
        "letmein123",
        "admin123",
        "admin1234",
        "welcome1",
        "welcome123",
        "iloveyou",
        "monkey123",
        "abc12345",
        "abcd1234",
        "p@ssw0rd",
        "p@ssword",
        "passw0rd",
        "trustno1",
    }
)


#: Surrounding whitespace is not part of a password on this server.
#:
#: Both ends of a credential have to agree on what the password is, and until
#: this constant existed they did not: ``LoginRequest``, ``AdminUserCreate`` and
#: ``ResetPasswordRequest`` carried ``str_strip_whitespace=True``, while
#: ``UserCreate`` (public registration), ``ChangePasswordRequest`` and
#: ``DeleteAccountRequest`` carried no ``model_config`` at all. Registration
#: therefore hashed exactly what the field held - a trailing space, a newline
#: left by a paste, a leading space from an autofilled form - and sign-in
#: verified the stripped form against it. ``bcrypt.checkpw`` answered False
#: forever, and the screen said "Invalid email or password": the one claim in
#: the whole exchange that was untrue, since the password was right. Changing a
#: password was worse, because ``new_password`` was stored unstripped and locked
#: out an account that had been working.
#:
#: The rule is stated once here and applied by every password the server stores
#: (``_validate_strong_password``, and ``users.service.hash_password`` for the
#: callers that never reach a schema - a seeder reading an environment variable,
#: the CLI's ``reset-password``) and every one it compares
#: (``users.service.verify_password``), so a schema added later cannot drift out
#: of step with the sign-in form the way these three did.
PASSWORD_SURROUNDING_WHITESPACE = " \t\n\r\v\f"


def normalise_password(value: str) -> str:
    """The form of a password this server stores and compares.

    Strips surrounding whitespace, which is what ``str_strip_whitespace`` did for
    the three schemas that had it. Internal spaces are kept: they are a legitimate
    part of a passphrase, and only the ones at the ends are invisible on a form
    and impossible to see when retyping them.
    """
    return value.strip(PASSWORD_SURROUNDING_WHITESPACE)


def _validate_strong_password(value: str) -> str:
    """Reject weak passwords. Used by `UserCreate`, `ChangePasswordRequest`,
    and `ResetPasswordRequest` so the policy is consistent everywhere.

    Rules (intentionally lenient - strong enough to block trivial passwords
    without frustrating power users):
      - 8+ chars
      - Must contain at least one letter and at least one digit
      - Must not be in the common-passwords blacklist (case-insensitive)
      - Must fit bcrypt: 72 bytes or fewer once encoded as UTF-8

    The value returned is :func:`normalise_password`'d, so what the policy
    judges is what gets stored - and what sign-in, which normalises too, will be
    able to reproduce. Judging the raw string instead is how a password whose
    length came from a trailing space passed ``Field(min_length=8)`` and then
    locked its own account.

    The byte limit is the one that reads as a nuisance and is not. ``Field``
    above allows 128 characters, bcrypt accepts 72 *bytes*, and bcrypt refuses
    anything longer with a ``ValueError`` instead of truncating it - the
    behaviour ``test_hash_rejects_password_over_72_bytes`` pins. Without a rule
    here the two limits met inside the request: a 24-character password in a
    script that is not ASCII (three bytes per character) encoded to over 72
    bytes, ``hash_password`` raised, and the registration answered 500. Refusing
    it at the boundary says what the limit is and leaves the stored hashes
    unambiguous - every one of them was made from the whole password, so a
    sign-in can never depend on which bytes an older bcrypt happened to keep.
    """
    value = normalise_password(value)
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters")
    if len(value.encode("utf-8")) > 72:
        raise ValueError(
            "Password must be 72 bytes or fewer when encoded as UTF-8 "
            "(the limit of the bcrypt hash it is stored as); "
            "characters outside ASCII count for more than one byte"
        )
    if not any(ch.isalpha() for ch in value):
        raise ValueError("Password must contain at least one letter")
    if not any(ch.isdigit() for ch in value):
        raise ValueError("Password must contain at least one digit")
    if value.lower() in _COMMON_PASSWORDS:
        raise ValueError("Password is too common - please choose a stronger one")
    return value


# ── Auth ───────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    """User login request.

    No min_length on password - validation of password format before credential
    check would reveal the password policy to unauthenticated users.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    """JWT token pair response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class SessionResponse(BaseModel):
    """One of the caller's own login sessions.

    Carries no user agent, IP address or location. Those would make the list
    easier to recognise yourself in, and each is personal data with its own
    retention question, so none is collected until somebody decides that
    deliberately. Revoking a session does not need them.
    """

    model_config = ConfigDict(from_attributes=True)

    sid: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    # The one field that makes the list actionable. Without it five sessions
    # are five rows of timestamps and nobody can tell which one they are
    # sitting on, which is exactly the session they must not end; the real
    # request behind this feature is "end all of them except this one".
    #
    # Deliberately required rather than defaulting to False. A default would
    # make a caller that forgot to compute it return a list in which no
    # session is current - a confident wrong answer that reads as an ordinary
    # one, where a required field makes the omission a failure instead.
    #
    # False everywhere is still a legitimate answer: a token minted before
    # sessions existed carries no ``sid``, so it matches no row, and nothing
    # is marked current because nothing can be.
    current: bool


class SessionListResponse(BaseModel):
    """The caller's own sessions, as a page rather than a bare array.

    ``total`` matters more here than on an ordinary list. The action this
    feature exists for is "end every session except the one I am holding", and
    a caller that cannot tell a complete answer from a first page would end
    the sessions it was shown and believe it had ended all of them. The
    envelope is what makes that state reportable; the array could not say it.

    Not paginated at the query yet, so ``total`` is the length of ``items``
    and the page covers everything. Declared with the offset and limit anyway,
    because the field that has to be there on the day a limit is introduced is
    the one nobody remembers to add on that day.
    """

    items: list[SessionResponse] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


class RefreshRequest(BaseModel):
    """Refresh token request."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    refresh_token: str = Field(..., min_length=1, max_length=2048)


class FirstRunResponse(BaseModel):
    """Desktop first-run status (public, never errors).

    Drives the desktop shell's auto-login decision on the ``/login`` route.
    Every field is best-effort: the endpoint always returns 200 so a transient
    DB hiccup degrades to the normal login form rather than an error screen.
    """

    desktop_mode: bool
    fresh_install: bool
    has_local_account: bool
    onboarding_completed: bool | None = None
    demo_enabled: bool = True
    """Whether seeded demo accounts and the password-less demo-login are
    available on this server. The login page hides its "Try demo" block when
    this is ``False`` (production installs with ``SEED_DEMO=false`` or a
    persisted "no demo" first-run choice), so it never offers a demo sign-in
    the server would reject - and never silently creates a demo account."""


# ── User CRUD ──────────────────────────────────────────────────────────────


class UserCreate(BaseModel):
    """Create a new user."""

    email: EmailStr = Field(..., description="Valid email address (used for login)")
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Password (min 8 chars, must contain at least one letter and one digit)",
    )
    full_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Full display name (HTML tags are stripped)",
    )
    role: str = Field(
        default="editor",
        pattern=r"^(admin|manager|editor|viewer)$",
        description="User role. Must be one of: admin, manager, editor, viewer",
    )
    locale: str = Field(default="en", max_length=10, description="Preferred locale code (e.g. en, de, fr)")
    company: str = Field(
        default="",
        max_length=255,
        description="Company or organisation name (optional)",
    )
    job_title: str = Field(
        default="",
        max_length=255,
        description="Job title / role in the company (optional)",
    )

    @field_validator("password")
    @classmethod
    def _check_password_strength(cls, v: str) -> str:
        return _validate_strong_password(v)

    @field_validator("full_name")
    @classmethod
    def _sanitize_full_name(cls, v: str) -> str:
        return _sanitize_name(v)

    @field_validator("company")
    @classmethod
    def _sanitize_company(cls, v: str) -> str:
        return _sanitize_name(v) if v else ""

    @field_validator("job_title")
    @classmethod
    def _sanitize_job_title(cls, v: str) -> str:
        return _sanitize_name(v) if v else ""


class AdminUserCreate(BaseModel):
    """Admin-only: create a user with an arbitrary role.

    BUG-USERS-CREATE - kept distinct from ``UserCreate`` (which is wired to
    the open ``/auth/register`` endpoint) so the public registration policy
    (default-to-viewer, bootstrap-first-admin, common-password blacklist)
    cannot be subverted by anyone hitting the admin endpoint, and so
    ``role="god"`` / empty email / weak passwords are rejected at the schema
    boundary instead of bubbling up as 500s from the service.

    Constraints versus ``UserCreate``:
      - ``role`` is a strict ``Literal`` whitelist - admin / manager /
        editor / viewer - so unknown values produce 422 instead of being
        silently persisted as the literal string.
      - ``password`` minimum length is bumped to 12 (admins can mint
        long-lived elevated accounts; weak passwords are unacceptable here
        even though the public flow tolerates 8-char passwords).
      - ``is_active`` is exposed so the admin can pre-create dormant rows.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr = Field(..., description="Valid email address (used for login)")
    password: str = Field(
        ...,
        min_length=12,
        max_length=128,
        description="Password (min 12 chars, must contain at least one letter and one digit)",
    )
    full_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Full display name (HTML tags are stripped)",
    )
    role: Literal["admin", "manager", "editor", "viewer"] = Field(
        default="viewer",
        description="User role. One of: admin, manager, editor, viewer.",
    )
    locale: str = Field(default="en", max_length=10)
    is_active: bool = Field(default=True)

    @field_validator("password")
    @classmethod
    def _check_password_strength(cls, v: str) -> str:
        return _validate_strong_password(v)

    @field_validator("full_name")
    @classmethod
    def _sanitize_full_name(cls, v: str) -> str:
        return _sanitize_name(v)


class UserUpdate(BaseModel):
    """Update user profile."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    locale: str | None = Field(default=None, max_length=10)
    metadata: dict[str, Any] | None = None
    timezone: str | None = Field(default=None, max_length=50)
    measurement_system: str | None = Field(default=None, max_length=20)
    paper_size: str | None = Field(default=None, max_length=10)
    number_format: str | None = Field(default=None, max_length=20)
    date_format: str | None = Field(default=None, max_length=20)
    currency_code: str | None = Field(default=None, max_length=10)

    @field_validator("full_name")
    @classmethod
    def _sanitize_full_name(cls, v: str | None) -> str | None:
        if v is not None:
            return _sanitize_name(v)
        return v


class UserAdminUpdate(BaseModel):
    """Admin-level user update (role, active status)."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: str | None = Field(default=None, pattern=r"^(admin|manager|editor|viewer)$")
    is_active: bool | None = None
    locale: str | None = Field(default=None, max_length=10)

    @field_validator("full_name")
    @classmethod
    def _sanitize_full_name(cls, v: str | None) -> str | None:
        if v is not None:
            return _sanitize_name(v)
        return v


class UserResponse(BaseModel):
    """User in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    role: str
    locale: str
    is_active: bool
    last_login_at: datetime | None
    timezone: str
    measurement_system: str
    paper_size: str
    number_format: str
    date_format: str
    currency_code: str
    created_at: datetime
    updated_at: datetime


class UserMeResponse(UserResponse):
    """Current user response with extra details."""

    permissions: list[str] = Field(default_factory=list)


#: Digit shapes a reader can ask for, as CLDR numbering systems, plus ``auto``
#: (whatever the language and the market print). Mirrors the frontend's
#: ``DIGIT_SYSTEMS`` and ``app.core.regional_format.DIGIT_SYSTEMS``.
DigitSystem = Literal["auto", "latn", "arab", "arabext"]


class UserPreferencesUpdate(BaseModel):
    """Update regional preferences only."""

    timezone: str | None = Field(default=None, max_length=50)
    measurement_system: str | None = Field(default=None, max_length=20)
    paper_size: str | None = Field(default=None, max_length=10)
    number_format: str | None = Field(default=None, max_length=20)
    date_format: str | None = Field(default=None, max_length=20)
    currency_code: str | None = Field(default=None, max_length=10)
    digit_system: DigitSystem | None = None


class UserPreferencesResponse(BaseModel):
    """Regional preferences response."""

    model_config = ConfigDict(from_attributes=True)

    timezone: str
    measurement_system: str
    paper_size: str
    number_format: str
    date_format: str
    currency_code: str
    digit_system: str = "auto"


class ChangePasswordRequest(BaseModel):
    """Change password request."""

    current_password: str = Field(..., min_length=8, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _check_new_password_strength(cls, v: str) -> str:
        return _validate_strong_password(v)

    @model_validator(mode="after")
    def _reject_same_password(self) -> "ChangePasswordRequest":
        if self.new_password == self.current_password:
            raise ValueError("New password must differ from the current one")
        return self


class DeleteAccountRequest(BaseModel):
    """Confirmation body for self-service account erasure (GDPR Art. 17).

    The caller must prove intent so an account is never erased by accident or
    by a leaked/replayed token alone:

      - Password accounts re-supply their ``current_password``; the service
        verifies it against the stored bcrypt hash and rejects a mismatch.
      - SSO / passwordless accounts (no usable password hash) instead type the
        literal confirmation phrase into ``confirm`` - the service checks it
        equals ``DELETE``.

    Both fields are optional at the schema layer because which one is required
    depends on whether the account has a password; the service decides and
    returns 400 when neither satisfies the guard.
    """

    model_config = ConfigDict(extra="ignore")

    current_password: str | None = Field(default=None, max_length=128)
    confirm: str | None = Field(default=None, max_length=64)


class DeleteAccountResponse(BaseModel):
    """Confirmation returned after a successful self-erasure."""

    status: str = "erased"
    detail: str = "Your account has been erased."


class ForgotPasswordRequest(BaseModel):
    """Forgot password request - triggers reset token generation."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    """Forgot password response.

    Always returns a generic message to prevent email enumeration.
    The reset token is NEVER included in the response - it must only
    be delivered via a secure side-channel (email).
    """

    message: str


class ResetPasswordRequest(BaseModel):
    """Reset password using a previously issued reset token."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    token: str = Field(..., min_length=1, max_length=512)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _check_new_password_strength(cls, v: str) -> str:
        return _validate_strong_password(v)


class ResetPasswordResponse(BaseModel):
    """Reset password response."""

    message: str


# ── API Keys ───────────────────────────────────────────────────────────────


class APIKeyCreate(BaseModel):
    """Create a new API key."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    expires_in_days: int | None = Field(default=None, ge=1, le=365)
    permissions: list[str] = Field(default_factory=list)


class APIKeyResponse(BaseModel):
    """API key in responses (no secret)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    key_prefix: str
    description: str
    is_active: bool
    permissions: list[str]
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class APIKeyCreatedResponse(APIKeyResponse):
    """Response when creating an API key - includes the full key (shown only once)."""

    key: str  # Full API key - shown only at creation time


# ── Onboarding ────────────────────────────────────────────────────────────────


class OnboardingRequest(BaseModel):
    """Save onboarding wizard choices."""

    company_type: str | None = Field(
        ...,
        # Required, so a client cannot leave it out by accident, but nullable:
        # null is the answer of a user who chose their modules one by one
        # without a profile. A string must name a preset in
        # ``core/onboarding_presets.py``; the check reads the catalogue itself,
        # so it grows with it and cannot drift. It used to accept any slug,
        # which stored a typo as the user's profile and left every screen that
        # reads it to guess.
        max_length=64,
        description="Selected company profile preset key, or null for modules chosen without a profile",
    )
    company_size: str | None = Field(
        default=None,
        # Optional parallel dimension to ``company_type``: the company-size
        # preset key (``size_solo`` .. ``size_large``). The wizard no longer
        # asks for it; older clients and stored accounts still carry one. Left
        # out of a request, the stored value is kept (see ``save_onboarding``).
        max_length=64,
        description="Selected company-size preset key (optional)",
    )
    enabled_modules: list[str] = Field(
        default_factory=list,
        description="Final list of module keys the user wants enabled",
    )
    interface_mode: str | None = Field(
        # No default mode. The Simple / Advanced choice is a per-browser setting
        # the app keeps client-side and never reads from here. This used to
        # default to "advanced", so every save that did not name a mode stored
        # a claim about the user nobody had made; the wizard also sent
        # "advanced" while switching the user to Simple. A client that still
        # sends a mode has it stored as sent.
        default=None,
        pattern=r"^(simple|advanced)$",
        description="Interface mode, if the client reports one. Not read by the app.",
    )
    completed: bool = Field(
        default=True,
        description="Whether onboarding is considered complete",
    )

    @field_validator("company_type")
    @classmethod
    def _company_type_is_a_preset(cls, value: str | None) -> str | None:
        if value is not None and not is_saveable_company_type(value):
            raise ValueError("company_type must be one of the onboarding profile presets")
        return value

    @field_validator("company_size")
    @classmethod
    def _company_size_is_a_preset(cls, value: str | None) -> str | None:
        if value is not None and not is_saveable_company_size(value):
            raise ValueError("company_size must be one of the company-size presets")
        return value


class OnboardingResponse(BaseModel):
    """Onboarding state for the current user."""

    completed: bool = False
    company_type: str | None = None
    company_size: str | None = None
    enabled_modules: list[str] = Field(default_factory=list)
    interface_mode: str | None = None
