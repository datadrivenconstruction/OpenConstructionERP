# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Customer & Partner Portal Pydantic schemas - request / response models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer

# Upper bound for client-supplied money - a finite-but-absurd claimed_amount
# (e.g. 1e400) otherwise sums into gross and reaches retention quantize() ->
# InvalidOperation -> 500. ge=0 already rejects NaN/Infinity. Mirrors the
# changeorders/subcontractors bound.
_MONEY_MAX = Decimal("1e15")

PORTAL_ROLES = r"^(client|investor|consultant|subcontractor|supplier|building_user)$"
USER_STATUSES = r"^(invited|active|suspended|expired)$"
LINK_PURPOSES = r"^(login|document_signature|payment_submission)$"
ACCESS_ACTIONS = r"^(view|download|sign)$"
ACCESS_PERMISSIONS = r"^(view|comment|submit|sign)$"
NOTIFICATION_KINDS = (
    r"^(document_ready|ticket_update|payment_status|"
    r"award_notification|general)$"
)


# ── Shared documents (portal-user facing) ─────────────────────────────────


class PortalSharedDocument(BaseModel):
    """A document shared with the portal user through a ``document`` access
    rule. Metadata only - the bytes are streamed by the content endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    file_size: int = 0
    mime_type: str = ""
    project_id: UUID


class PortalSharedDocumentList(BaseModel):
    items: list[PortalSharedDocument]
    total: int


# ── Users ─────────────────────────────────────────────────────────────────


class PortalUserInvite(BaseModel):
    """Body for POST /admin/users/invite."""

    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    full_name: str = Field(default="", max_length=255)
    portal_role: str = Field(..., pattern=PORTAL_ROLES)
    language: str = Field(default="en", min_length=2, max_length=10)
    timezone: str = Field(default="UTC", max_length=64)
    redirect_path: str | None = Field(default=None, max_length=512)
    send_email: bool = Field(default=True, description="Email the invitation link when mail is configured.")


class PortalUserResponse(BaseModel):
    """Portal user as returned to internal admins."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str = ""
    portal_role: str
    language: str = "en"
    timezone: str = "UTC"
    status: str = "invited"
    invited_at: datetime | None = None
    last_login_at: datetime | None = None
    failed_login_count: int = 0
    locked_until: datetime | None = None
    notification_email_opt_in: bool = True
    created_at: datetime
    updated_at: datetime


class PortalUserList(BaseModel):
    """Paginated list of portal users."""

    items: list[PortalUserResponse] = Field(default_factory=list)
    total: int = 0


class PortalUserPatch(BaseModel):
    """Body for PATCH /admin/users/{id} - suspend / reactivate / rename."""

    model_config = ConfigDict(str_strip_whitespace=True)

    status: str | None = Field(default=None, pattern=USER_STATUSES)
    full_name: str | None = Field(default=None, max_length=255)
    language: str | None = Field(default=None, min_length=2, max_length=10)
    timezone: str | None = Field(default=None, max_length=64)
    notification_email_opt_in: bool | None = None


class PortalSelfPatch(BaseModel):
    """Body for PATCH /me - fields a portal user is allowed to change.

    Deliberately narrower than :class:`PortalUserPatch`: a portal user
    must not be able to change their own ``status`` (only the GC admin can
    suspend an account) or their email.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str | None = Field(default=None, max_length=255)
    language: str | None = Field(default=None, min_length=2, max_length=10)
    timezone: str | None = Field(default=None, max_length=64)
    notification_email_opt_in: bool | None = None


class PortalUserInviteResponse(BaseModel):
    """Response body that includes the freshly minted magic-link.

    The plaintext link token is shown ONCE; subsequent fetches via
    ``GET /admin/users/{id}`` do not return it.
    """

    user: PortalUserResponse
    magic_link_token: str = Field(
        description=(
            "Plaintext one-time token. The server emails it when mail is configured; "
            "the staff screen still offers it as a copy-link either way."
        ),
    )
    magic_link_expires_at: datetime
    email_status: Literal["sent", "failed", "not_configured", "not_requested"] = Field(
        default="not_requested",
        description="What happened to the invitation email, so the screen can say whether to copy the link.",
    )


# ── Auth ──────────────────────────────────────────────────────────────────


class MagicLinkRequest(BaseModel):
    """Body for POST /auth/magic-link (portal-user-facing)."""

    email: EmailStr


class MagicLinkResponse(BaseModel):
    """Always returns 202 + this body - no email-enumeration leak."""

    accepted: bool = True
    message: str = "If the email is registered, a magic link has been sent."


class MagicLinkConsume(BaseModel):
    """Body for POST /auth/consume."""

    token: str = Field(..., min_length=16, max_length=256)


class SessionResponse(BaseModel):
    """Response body for /auth/consume - gives the caller their session token."""

    session_token: str = Field(
        description="Bearer token - caller passes as 'Authorization: Bearer <token>'",
    )
    expires_at: datetime
    portal_user: PortalUserResponse
    redirect_path: str | None = Field(
        default=None,
        description=(
            "Optional in-app path the inviter chose for this link - the "
            "landing page navigates here after sign-in when present."
        ),
    )


# ── Access rules ──────────────────────────────────────────────────────────


class AccessRuleCreate(BaseModel):
    """Body for POST /admin/access-rules."""

    model_config = ConfigDict(str_strip_whitespace=True)

    portal_user_id: UUID
    resource_type: str = Field(..., min_length=1, max_length=64)
    resource_id: UUID
    permission: str = Field(default="view", pattern=ACCESS_PERMISSIONS)
    expires_at: datetime | None = None


class AccessRuleResponse(BaseModel):
    """An access rule as returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    portal_user_id: UUID
    resource_type: str
    resource_id: UUID
    permission: str
    granted_at: datetime | None = None
    granted_by: str | None = None
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AccessRuleList(BaseModel):
    """Paginated list of access rules for the internal-admin surface."""

    items: list[AccessRuleResponse] = Field(default_factory=list)
    total: int = 0


# ── Notifications ─────────────────────────────────────────────────────────


class NotificationResponse(BaseModel):
    """A portal notification as returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    portal_user_id: UUID
    kind: str
    title: str = ""
    body: str = ""
    link_path: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    read_at: datetime | None = None
    created_at: datetime


class NotificationListResponse(BaseModel):
    """List + unread-count combo for /me/notifications."""

    items: list[NotificationResponse] = Field(default_factory=list)
    unread_count: int = 0
    total: int = 0


# ── Document access log ──────────────────────────────────────────────────


class DocumentAccessLogCreate(BaseModel):
    """Body for POST /me/document-access (portal-user-facing audit ping)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    document_type: str = Field(..., min_length=1, max_length=64)
    document_id: UUID
    action: str = Field(default="view", pattern=ACCESS_ACTIONS)


class DocumentAccessLogEntry(BaseModel):
    """An audit log entry as returned to internal admins."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    portal_user_id: UUID
    document_type: str
    document_id: UUID
    action: str
    occurred_at: datetime | None = None
    ip_address: str | None = None
    created_at: datetime


# ── Portal-side ticket intake / change-order visibility ───────────────────


class PortalTicketCreate(BaseModel):
    """Body for POST /me/tickets - a portal user files a service ticket.

    The contract_id must belong to a ``service_contract`` access rule the
    caller holds; the service-layer RLS gate enforces this. ``priority``
    defaults to ``med`` - portal users cannot file ``critical`` tickets
    (escalation is internal staff's call to make).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    contract_id: UUID
    title: str = Field(..., min_length=1, max_length=500)
    description: str = Field(default="", max_length=10_000)
    priority: str = Field(
        default="med",
        pattern=r"^(low|med|high)$",  # critical is internal-only
    )
    asset_id: UUID | None = None


class PortalTicketResponse(BaseModel):
    """Buyer-side ticket view - strips internal-only fields."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contract_id: UUID
    ticket_number: str
    title: str
    description: str = ""
    priority: str = "med"
    status: str = "new"
    reported_at: str
    sla_due_at: str | None = None
    resolved_at: str | None = None
    closed_at: str | None = None


class PortalTicketList(BaseModel):
    """Paginated portal-side ticket list."""

    items: list[PortalTicketResponse] = Field(default_factory=list)
    total: int = 0


class PortalChangeOrderEntry(BaseModel):
    """Read-only buyer view of an executed change order.

    Internal commentary, submission workflow, internal markup, and
    pre-decision rejection trails are deliberately omitted. The buyer sees:
    code, title, description, status, approved_amount + currency,
    approved_time_days, approved_at.
    """

    id: UUID
    code: str
    title: str
    description: str = ""
    status: str
    approved_amount: Decimal | None = None
    approved_time_days: int | None = None
    currency: str = ""
    approved_at: str | None = None


class PortalChangeOrderList(BaseModel):
    """List of executed change orders the caller can see."""

    items: list[PortalChangeOrderEntry] = Field(default_factory=list)
    total: int = 0


class PortalInvoiceEntry(BaseModel):
    """Read-only client view of an issued invoice.

    Only the fields a client needs to recognise and reconcile an invoice:
    number, dates, total amount + currency, status and its project. Internal
    line items, tax configuration, retention breakdown and draft rows are
    deliberately omitted.
    """

    id: UUID
    project_id: UUID
    invoice_number: str
    invoice_date: str = ""
    due_date: str | None = None
    currency_code: str = ""
    amount_total: Decimal | None = None
    status: str = ""
    is_overdue: bool = False
    days_overdue: int | None = Field(default=None, description="Whole days past the due date, when overdue.")


class PortalInvoiceList(BaseModel):
    """List of issued invoices the caller can see."""

    items: list[PortalInvoiceEntry] = Field(default_factory=list)
    total: int = 0


# ── Portal-side BIM/CAD model visibility (view-only) ──────────────────────


class PortalBimModelEntry(BaseModel):
    """Read-only client view of a BIM/CAD model shared through the portal.

    Only what the client needs to pick a model from a list and open it in
    the view-only 3D viewer. No file paths, no conversion internals, no
    BOQ/cost linkage - the geometry and element endpoints enforce the same
    grant separately.
    """

    id: UUID
    project_id: UUID
    name: str
    discipline: str = ""
    model_format: str = ""
    element_count: int = 0
    status: str = ""


class PortalBimModelList(BaseModel):
    """List of BIM/CAD models the caller can see, view-only."""

    items: list[PortalBimModelEntry] = Field(default_factory=list)
    total: int = 0


# ── Portal-side progress-report visibility ────────────────────────────────


class PortalProgressReportEntry(BaseModel):
    """Read-only client view of a generated progress report.

    A flat projection of ``GeneratedReport`` carrying only what the client
    needs to list and open a report: identity, title, generated timestamp,
    output format, the reporting period (lifted from the snapshot when
    present) and whether a rendered body is available to open or download.
    """

    id: UUID
    title: str
    generated_at: str
    report_type: str
    format: str = "pdf"
    period: str | None = None
    has_content: bool = False


class PortalProgressReportList(BaseModel):
    """List of progress reports the caller can see for a project."""

    items: list[PortalProgressReportEntry] = Field(default_factory=list)
    total: int = 0


class PortalMilestoneEntry(BaseModel):
    """A schedule milestone a person marked for the client.

    Only what the client needs: the name, the date it was planned for, the
    date the schedule now expects, and whether it is done or running late.
    Dependencies, float, resources and costs stay internal.
    """

    id: UUID
    name: str
    planned_date: str
    expected_date: str
    status: str
    is_done: bool = False
    is_late: bool = Field(default=False, description="Not done and its expected date has passed.")
    days_until: int = Field(description="Days from today to the expected date; negative when late.")


class PortalMilestoneList(BaseModel):
    """Late milestones and the ones expected within the window, soonest first."""

    items: list[PortalMilestoneEntry] = Field(default_factory=list)
    window_days: int


class PortalProjectSummary(BaseModel):
    """A project the portal caller can see, with just enough to label it.

    Backs the portal Progress Reports tab so the client can pick a project by
    name instead of pasting a UUID. Scoped to the caller's non-expired
    ``project`` access rules.
    """

    id: UUID
    name: str
    project_code: str | None = None


class PortalProjectSummaryList(BaseModel):
    """List of projects the portal caller can see."""

    items: list[PortalProjectSummary] = Field(default_factory=list)
    total: int = 0


# ── Portal-side payment-application submission ────────────────────────────


class PaymentApplicationListItem(BaseModel):
    """One row in the subcontractor's payment-application list.

    Money fields are serialised as strings so the frontend never receives a
    lossy JSON float. Currency comes from the application / agreement, never
    hardcoded.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agreement_id: UUID
    application_number: str
    period_start: date | None = None
    period_end: date | None = None
    gross_amount: Decimal = Decimal("0")
    net_amount: Decimal = Decimal("0")
    currency: str = ""
    status: str = "submitted"
    submitted_at: datetime | None = None

    @field_serializer("gross_amount", "net_amount")
    def _ser_money(self, value: Decimal) -> str:
        return str(value)


class PaymentApplicationListResponse(BaseModel):
    """Paginated list of payment applications for the portal user."""

    items: list[PaymentApplicationListItem] = Field(default_factory=list)
    total: int = 0


class PaymentApplicationLineDetail(BaseModel):
    """A single work-package line within a payment-application detail view."""

    work_package_id: UUID
    work_package_name: str = ""
    planned_value: Decimal = Decimal("0")
    claimed_amount: Decimal = Decimal("0")
    certified_amount: Decimal = Decimal("0")
    approved_amount: Decimal = Decimal("0")

    @field_serializer(
        "planned_value",
        "claimed_amount",
        "certified_amount",
        "approved_amount",
    )
    def _ser_money(self, value: Decimal) -> str:
        return str(value)


class PaymentApplicationDetailResponse(BaseModel):
    """Full payment-application view for the portal user."""

    id: UUID
    agreement_id: UUID
    application_number: str
    period_start: date | None = None
    period_end: date | None = None
    gross_amount: Decimal = Decimal("0")
    retention_amount: Decimal = Decimal("0")
    net_amount: Decimal = Decimal("0")
    currency: str = ""
    status: str = "submitted"
    submitted_at: datetime | None = None
    lines: list[PaymentApplicationLineDetail] = Field(default_factory=list)

    @field_serializer("gross_amount", "retention_amount", "net_amount")
    def _ser_money(self, value: Decimal) -> str:
        return str(value)


class PaymentApplicationSubmitLine(BaseModel):
    """One work-package line in a submission payload."""

    model_config = ConfigDict(str_strip_whitespace=True)

    work_package_id: UUID
    claimed_amount: Decimal = Field(..., ge=0, le=_MONEY_MAX)


class PaymentApplicationSubmitPayload(BaseModel):
    """Body for POST /me/payment-applications.

    The gross amount is the sum of the line ``claimed_amount`` values; the
    backend recomputes retention and net from the agreement so the client
    cannot drive those numbers. ``currency`` is never accepted from the
    client - it is taken from the agreement / project.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    agreement_id: UUID
    period_start: date | None = None
    period_end: date | None = None
    lines: list[PaymentApplicationSubmitLine] = Field(..., min_length=1)


class PortalWorkPackageEntry(BaseModel):
    """A work package the portal user can claim against, for the submit form."""

    id: UUID
    name: str
    planned_value: Decimal = Decimal("0")

    @field_serializer("planned_value")
    def _ser_money(self, value: Decimal) -> str:
        return str(value)


class PortalAgreementSummary(BaseModel):
    """Light agreement projection for the portal submit form (no internals)."""

    id: UUID
    title: str
    currency: str = ""
    retention_percent: Decimal = Decimal("0")
    status: str = ""
    work_packages: list[PortalWorkPackageEntry] = Field(default_factory=list)

    @field_serializer("retention_percent")
    def _ser_pct(self, value: Decimal) -> str:
        return str(value)


class PortalAgreementSummaryList(BaseModel):
    """Agreements the portal user can submit / view, with their work packages."""

    items: list[PortalAgreementSummary] = Field(default_factory=list)
    total: int = 0


__all__ = [
    "AccessRuleCreate",
    "AccessRuleList",
    "AccessRuleResponse",
    "DocumentAccessLogCreate",
    "DocumentAccessLogEntry",
    "MagicLinkConsume",
    "MagicLinkRequest",
    "MagicLinkResponse",
    "NotificationListResponse",
    "NotificationResponse",
    "PaymentApplicationDetailResponse",
    "PaymentApplicationLineDetail",
    "PaymentApplicationListItem",
    "PaymentApplicationListResponse",
    "PaymentApplicationSubmitLine",
    "PaymentApplicationSubmitPayload",
    "PortalAgreementSummary",
    "PortalAgreementSummaryList",
    "PortalBimModelEntry",
    "PortalBimModelList",
    "PortalChangeOrderEntry",
    "PortalChangeOrderList",
    "PortalProgressReportEntry",
    "PortalProgressReportList",
    "PortalSelfPatch",
    "PortalTicketCreate",
    "PortalTicketList",
    "PortalTicketResponse",
    "PortalUserInvite",
    "PortalUserInviteResponse",
    "PortalUserList",
    "PortalUserPatch",
    "PortalUserResponse",
    "PortalWorkPackageEntry",
    "SessionResponse",
]
