"""What the project-scoped reads do when a project's ``organization_id`` is NULL.

``oe_projects_project.organization_id`` is nullable and arrived with ADR 005, so an
install upgraded from before it carries projects whose company is unknown until the
tenancy repair fills the column in. The repair only fills it where the project's owner
has an active membership (``app/modules/users/repairs.py``, the ``UPDATE`` over
``oe_projects_project`` that reads the owner's preferred organization), so a project
owned by somebody with no active membership stays NULL permanently.

Before these tests existed the read path answered that state with silence:
``ProcurementConceptService.project_tenant`` returned ``None``, ``project_frameworks``
dropped the project's half of its union, and a project member got a list containing only
their own company's frameworks. That is indistinguishable, from the outside, from "this
project has no frameworks", which is the wrong answer to give an estimator standing on a
site wondering whose rebar agreement they may call off.

The fallback asserted here is the same derivation the repair writes and the same one a
token mint uses - the owner's preferred active organization, ordered ``is_default``
first and then by age. Using one rule in all three places is the point: the repair's
docstring says the value it writes into a row and the value a token later names have to
be the same organization, and a read path that guessed differently would disagree with
both. Where the owner has no active membership either, there is nothing honest to
derive, so the answer stays ``None`` and the read stays narrow rather than widening.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.procurement_concept.models import FrameworkAgreement
from app.modules.procurement_concept.service import ProcurementConceptService
from app.modules.projects.models import Project, ProjectParticipantGrant
from app.modules.users.models import Membership, Organization, User
from tests._pg import isolated_engine

pytestmark = [pytest.mark.asyncio]


async def _legacy_project(
    session: AsyncSession, *, owner_has_membership: bool
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A project whose company column is NULL, its owner, and the owner's company.

    The framework is stamped with the owner's company, which is what the tenancy
    repair would have stamped it with too, so the rows are the ones a real upgraded
    install holds: the framework knows its company and only the project does not.
    """
    owner = uuid.uuid4()
    colleague = uuid.uuid4()
    session.add_all(
        [
            User(
                id=owner,
                email=f"legacy-owner-{owner.hex[:10]}@lane.test",
                hashed_password="not-a-real-hash",
                full_name="Legacy Owner",
                role="admin",
                locale="en",
                is_active=True,
                metadata_={},
            ),
            User(
                id=colleague,
                email=f"legacy-other-{colleague.hex[:10]}@lane.test",
                hashed_password="not-a-real-hash",
                full_name="Other Company",
                role="editor",
                locale="en",
                is_active=True,
                metadata_={},
            ),
        ]
    )
    ours = Organization(name="Legacy Company", slug=f"legacy-ours-{uuid.uuid4().hex[:10]}", status="active")
    theirs = Organization(name="Other Company", slug=f"legacy-theirs-{uuid.uuid4().hex[:10]}", status="active")
    session.add_all([ours, theirs])
    # Flushed before the memberships: a membership names its organization through a
    # plain column, so the unit of work has no dependency edge to order the inserts by.
    await session.flush()
    session.add(
        Membership(user_id=colleague, organization_id=theirs.id, role="editor", status="active", is_default=True)
    )
    if owner_has_membership:
        session.add(Membership(user_id=owner, organization_id=ours.id, role="admin", status="active", is_default=True))
    await session.flush()

    project = uuid.uuid4()
    session.add(
        Project(
            id=project,
            name=f"Legacy {project.hex[:6]}",
            currency="EUR",
            status="active",
            owner_id=owner,
            organization_id=None,
            metadata_={},
        )
    )
    session.add(
        FrameworkAgreement(
            id=uuid.uuid4(),
            tenant_id=str(ours.id),
            created_by=owner,
            state="draft",
            code="FW-LEGACY",
            title="Legacy rebar",
            package_kinds=["supply"],
            lots=[],
            max_value=Decimal("500000"),
            currency="EUR",
            start_date="2026-01-01",
            end_date="2028-01-01",
        )
    )
    await session.flush()
    return project, ours.id, theirs.id


async def test_a_legacy_project_names_its_owners_company() -> None:
    """The owner's active company is the project's company, exactly as the repair writes it."""
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            project, ours, theirs = await _legacy_project(session, owner_has_membership=True)
            await session.commit()
            svc = ProcurementConceptService(session)

            assert await svc.project_tenant(project) == str(ours)

            # And the read a project member actually performs: somebody from another
            # company, on the project's team, asking which frameworks a package here may
            # call off. Narrowing to their own company is the silent-empty failure this
            # test exists to refuse.
            #
            # Since ADR 006 there is a second question in front of the same answer -
            # does the reader's company participate in this project - and both halves are
            # asserted, because the fallback this test exists to pin is what makes the
            # second one answerable at all: with no company resolved there is nobody to
            # have invited anybody, and the read is empty for a reason that has nothing
            # to do with participation.
            assert await svc.project_frameworks(project, str(theirs)) == []

            session.add(
                ProjectParticipantGrant(
                    project_id=project,
                    grantee_organization_id=theirs,
                    # ``_legacy_project`` returns the two companies and not the owner's
                    # id, and the column is nullable for exactly this case: a grant whose
                    # author is a boot repair or a data import rather than a person. The
                    # company it was made on behalf of is the one that matters here,
                    # because that is what an ownership change suspends against.
                    granted_by_user_id=None,
                    granted_on_behalf_of_organization_id=ours,
                    scope="view",
                    status="active",
                    metadata_={},
                )
            )
            await session.flush()

            rows = await svc.project_frameworks(project, str(theirs))
            assert [r.code for r in rows] == ["FW-LEGACY"]


async def test_a_legacy_project_whose_owner_has_no_membership_names_no_company() -> None:
    """With nothing honest to derive, the read stays narrow instead of guessing.

    The owner has no active membership, so there is no company to fall back to. The
    answer is ``None`` and the project's frameworks are not shown to a caller from
    another company: widening here would hand one company's agreements to another on
    the strength of a column nobody has filled in. This is the fail-safe direction,
    and it is the state an administrator has to resolve - the same ambiguity the
    tenancy readiness report raises as ``tenant_is_user`` rather than papering over.
    """
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            project, ours, theirs = await _legacy_project(session, owner_has_membership=False)
            await session.commit()
            svc = ProcurementConceptService(session)

            assert await svc.project_tenant(project) is None

            rows = await svc.project_frameworks(project, str(theirs))
            assert rows == [], "a caller from another company must not read frameworks nobody can attribute"
            # The framework still exists and still belongs to the owner's company; it is
            # the project link that is unknown, not the row.
            assert [r.code for r in await svc.list_frameworks(str(ours))] == ["FW-LEGACY"]
