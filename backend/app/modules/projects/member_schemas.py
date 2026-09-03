# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project Member API schemas.

The Team Strip on ProjectDetailPage works at the project level rather than the
fine-grained ``Team`` level. Internally each project gets a "Default Team"
on creation (see ``ProjectService.create_project``); these schemas describe the
project-member contract exposed at ``/api/v1/projects/{project_id}/members/``.

Each ``ProjectMemberResponse`` is a denormalised view of a row in
``oe_teams_membership`` joined to ``oe_users_user`` so the frontend can render
avatar circles (initials + tooltip) without a second roundtrip.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

#: Every role a project member may hold, in display order.
#:
#: The list is deliberately shaped for a construction / electrical-contracting
#: business rather than a generic SaaS "member / viewer" pair: the people on a
#: switchboard or automation job are engineers, drafters, workshop leads, site
#: supervisors, sparkies and apprentices, and the commercial side is contracts
#: admin, estimating and procurement. Client contacts and subcontractors are
#: kept as first-class roles so an external party on the CDE is labelled
#: honestly instead of being filed as a plain "member".
#:
#: The four historical values (``member``, ``lead``, ``owner``, ``viewer``) plus
#: the two the Team Strip already offered (``estimator``, ``project_manager``)
#: are all retained so existing membership rows keep validating - this list
#: only ever grows.
#: The comment groups mirror the optgroups the picker renders - see
#: ``frontend/src/features/projects/components/projectRoles.ts``, which holds
#: the same keys plus their display labels.
PROJECT_MEMBER_ROLES: tuple[str, ...] = (
    # Project
    "owner",
    "lead",
    "member",
    "project_manager",
    # Engineering
    "estimator",
    "engineer",
    "drafter",
    "automation_engineer",
    # Workshop & site
    "workshop_lead",
    "site_supervisor",
    "electrician",
    "apprentice",
    # Commercial (incl. assurance)
    "contracts_admin",
    "hse",
    "quality",
    "procurement",
    # External
    "client_contact",
    "subcontractor",
    "viewer",
)

#: Regex the request schemas validate against. Built from the tuple above so
#: the whitelist can never drift between the constant and the pattern.
PROJECT_MEMBER_ROLE_PATTERN = r"^(" + "|".join(PROJECT_MEMBER_ROLES) + r")$"


class ProjectMemberResponse(BaseModel):
    """A single project member.

    ``user_id`` is the canonical join key; ``email`` and ``full_name`` are
    pre-joined for the avatar tooltip + initials. ``role`` mirrors the team
    membership role and accepts the whitelist in ``PROJECT_MEMBER_ROLES``.

    The response deliberately does *not* re-validate ``role`` against that
    whitelist: a legacy row carrying a role we no longer offer must still be
    listable (and therefore fixable) rather than 500-ing the whole strip.
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    email: str
    full_name: str = ""
    role: str = "member"
    is_owner: bool = False
    created_at: datetime | None = None


class AddProjectMemberRequest(BaseModel):
    """Add a user to the project's default team."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    user_id: UUID
    role: str = Field(default="member", pattern=PROJECT_MEMBER_ROLE_PATTERN)


class UpdateProjectMemberRoleRequest(BaseModel):
    """Change an existing member's role on the project.

    Separate from ``AddProjectMemberRequest`` because the user is identified by
    the path (``/members/{user_id}/``), not the body - so sending a ``user_id``
    here would create a second, contradictory source of truth.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    role: str = Field(pattern=PROJECT_MEMBER_ROLE_PATTERN)


class BulkAddProjectMembersRequest(BaseModel):
    """Invite several users to the project at once (mass invite).

    This is the "open the CDE to the whole team" path, so it is subject to the
    CDE go-live gate: when the gate is enabled the project's common data
    environment must have reached the required readiness level before the bulk
    invite is allowed.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    members: list[AddProjectMemberRequest] = Field(min_length=1, max_length=200)


class BulkAddProjectMembersResponse(BaseModel):
    """Result of a mass invite: the members added this call."""

    added: list[ProjectMemberResponse] = Field(default_factory=list)
