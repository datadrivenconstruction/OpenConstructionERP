# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Teams ORM models.

Tables:
    oe_teams_team          - project teams for entity visibility
    oe_teams_membership    - user-to-team membership
    oe_teams_visibility    - entity-to-team visibility restrictions
    oe_teams_roster_member - who is on the project, and in what capacity

Membership and roster are not the same thing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``TeamMembership`` is the authorization table: a row in it is what lets a user
reach the project at all, which is why roughly two dozen modules read it through
:func:`app.modules.teams.access.member_project_ids_subquery`. It therefore holds
platform users and nothing else.

``RosterMember`` is the site record: who is working on this job, for which firm,
in which trade, in which role, between which dates, and with which tickets. Most
of those people are not platform users - the subcontractor's foreman and the
client's representative have no login - so a roster row carries its own name and
links to a user or a contact only when one exists. A roster row grants nothing.
The two are kept apart deliberately: making ``user_id`` nullable so one table
could do both jobs would void ``uq_teams_membership_team_user`` (NULLs are
distinct), and every membership-to-user join in the platform would start
rendering nameless members and counting them as viewers.

Visibility semantics
~~~~~~~~~~~~~~~~~~~~
``EntityVisibility`` rows RESTRICT, they never grant. A record with no row is
open to everyone who can already reach its project; a record with one or more
rows is reachable only by the project owner, a system admin, and the members of
the named teams. There is deliberately no direction in which a row widens what a
user can see, so no team assignment can hand out access the user did not already
hold on the parent project. See :mod:`app.modules.teams.access` for the
subtractive resolver every consumer is expected to use.
"""

import uuid
from datetime import date

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class Team(Base):
    """A team within a project for visibility control."""

    __tablename__ = "oe_teams_team"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_translations: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    memberships: Mapped[list["TeamMembership"]] = relationship(
        back_populates="team",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    # A team's restrictions can run to thousands of rows on a large project and
    # are never needed to render the team itself, so they are ordered
    # explicitly rather than loaded with every parent read.
    visibility_grants: Mapped[list["EntityVisibility"]] = relationship(
        back_populates="team",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
    )

    def __repr__(self) -> str:
        return f"<Team {self.name} (project={self.project_id})>"


class TeamMembership(Base):
    """Association between a user and a team."""

    __tablename__ = "oe_teams_membership"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_teams_membership_team_user"),)

    team_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_teams_team.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="member", server_default="member")

    # Relationships
    # ``raise_on_sql``: the FK column already carries the parent id, so an
    # implicit walk upwards is the async lazy-load crash, not a convenience.
    # Reading it is still free when ``Team.memberships`` populated it.
    team: Mapped[Team] = relationship(back_populates="memberships", lazy="raise_on_sql")

    def __repr__(self) -> str:
        return f"<TeamMembership team={self.team_id} user={self.user_id} ({self.role})>"


class EntityVisibility(Base):
    """Restricts one record to one team.

    The row is subtractive. Its presence turns the named record from "open to
    every member of the project" into "reachable only by the project owner, a
    system admin, and the members of the teams named by the rows on this
    record". It cannot make a record reachable to someone who could not already
    reach the project it belongs to.
    """

    __tablename__ = "oe_teams_visibility"
    __table_args__ = (
        UniqueConstraint(
            "entity_type",
            "entity_id",
            "team_id",
            name="uq_teams_visibility_entity_team",
        ),
        Index("ix_teams_visibility_entity", "entity_type", "entity_id"),
    )

    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    team_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_teams_team.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Relationships
    team: Mapped[Team] = relationship(back_populates="visibility_grants", lazy="raise_on_sql")

    def __repr__(self) -> str:
        return f"<EntityVisibility {self.entity_type}/{self.entity_id} -> team={self.team_id}>"


class RosterMember(Base):
    """One person on one project, as the site knows them.

    The row stands on its own: ``display_name`` is always written, and
    ``user_id`` / ``contact_id`` are links that may be absent. That is what lets
    the roster hold the three kinds of person a job actually has - a colleague
    with a login, somebody already in the address book, and the banksman who is
    a name on the induction list and nothing else - without inventing a user
    account for the last two, and without losing the line when a user or a
    contact is later deleted.

    At most one link is set (``ck_teams_roster_single_link``). Both set would
    mean two answers to "who is this", and the resolver would have to pick one.

    No ``relationship()`` is declared on this model, in either direction. The
    team link is ``ON DELETE SET NULL`` - deleting a team must not delete the
    people, they are still on the project - and an ORM collection with that
    ondelete needs ``passive_deletes`` plus foreign keys actually enforced by
    the engine to behave. :meth:`TeamRepository.unassign_roster_from_team`
    clears the column explicitly instead, which reaches the same state on every
    engine and is visible in the code that deletes the team.
    """

    __tablename__ = "oe_teams_roster_member"
    __table_args__ = (
        CheckConstraint(
            "user_id IS NULL OR contact_id IS NULL",
            name="ck_teams_roster_single_link",
        ),
        # Partial uniqueness: the same colleague or the same address-book
        # contact cannot be listed twice on one project. Manually typed people
        # carry no link and are deliberately not constrained - two labourers
        # can genuinely share a name.
        Index(
            "uq_teams_roster_project_user",
            "project_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
            sqlite_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_teams_roster_project_contact",
            "project_id",
            "contact_id",
            unique=True,
            postgresql_where=text("contact_id IS NOT NULL"),
            sqlite_where=text("contact_id IS NOT NULL"),
        ),
        Index("ix_teams_roster_project_active", "project_id", "is_active"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # NULL means "on the project, not yet grouped". The roster screen shows
    # those people in an unassigned band rather than hiding them, because a
    # person nobody has placed is exactly the one somebody has to place.
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_teams_team.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # NB: ``contact_id`` is a plain UUID. The teams module declares a dependency
    # on ``oe_users`` and ``oe_projects`` only, and a module has to keep working
    # when an optional module is not installed, so the FK to the contacts table
    # is declared in the Alembic migration and not here - the same arrangement
    # ``resources.Resource.contact_id`` already uses.
    contact_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    trade: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="", index=True)
    site_role: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="", index=True)
    # Contact details for this person on this job. Empty means "use whatever the
    # linked user or contact carries" - a site phone that differs from the head
    # office one is normal, and overwriting the address book with it is not.
    email: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    phone: Mapped[str] = mapped_column(String(50), nullable=False, default="", server_default="")
    starts_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Share of this person's time the project has been promised, in percent.
    # NULL means nobody has declared it, and the roster reports it as undeclared
    # rather than assuming full time - the same honesty
    # ``resources.Resource.capacity_percent`` keeps about capacity.
    allocation_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Tickets and competencies, as a list of
    # ``{"kind", "number", "issued_by", "valid_until"}`` objects validated by
    # the schema layer. JSON rather than a fourth table: the shape is small,
    # always read with its person, and matches what ``Contact.certifications``
    # already stores.
    certifications: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # Optional link to the costed resource pool. The resources module plans and
    # levels a catalogue of resources; the roster records people on a job. One
    # column joins the two when a person is also a planned resource, and
    # nothing breaks when they are not.
    resource_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # A person who has left is deactivated, not deleted: the diary entries,
    # inspections and snags they signed still name them.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<RosterMember {self.display_name} ({self.site_role or 'no role'}) project={self.project_id}>"
