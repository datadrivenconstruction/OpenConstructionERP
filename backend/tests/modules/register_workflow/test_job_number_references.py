# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Per-job references: REG-RFI-24188-0001.

The job number goes INSIDE the reference so a register is per job and a
reference read down the phone says which job it belongs to. Each rail
below fails if the behaviour is removed.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.register_workflow import service
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _job(session: AsyncSession, code: str | None) -> uuid.UUID:
    """A project carrying a given project_code (the job number)."""
    user = User(
        email=f"sp-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="SP",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"SP {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="AUD", project_code=code)
    session.add(proj)
    await session.flush()
    return proj.id


# ── The shape ────────────────────────────────────────────────────────────


def test_the_reference_carries_the_job_number() -> None:
    assert service.format_reference("RFI", 1, "24188") == "REG-RFI-24188-0001"
    assert service.format_reference("RFQ", 123, "24188") == "REG-RFQ-24188-0123"
    # Un-scoped is the six-digit series, unchanged - that is where MSG lives.
    assert service.format_reference("MSG", 42) == "REG-MSG-000042"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("24188", "24188"),
        (" 24188 ", "24188"),
        ("24188-A", "24188A"),
        ("job 24188/2", "JOB241882"),
        ("ab-12", "AB12"),
    ],
)
def test_a_job_number_is_reduced_to_what_can_live_in_a_reference(raw: str, expected: str) -> None:
    """Spaces and slashes would break the word boundaries the inbound
    matcher relies on, so they come out before the number goes in."""
    assert service.normalise_job_number(raw) == expected


@pytest.mark.asyncio
async def test_raising_mints_a_per_job_reference(session: AsyncSession) -> None:
    pid = await _job(session, "24188")
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Earth bar", fields={})
    assert item.reference == "REG-RFI-24188-0001"
    second = await service.raise_item(session, project_id=pid, kind="rfi", title="Next", fields={})
    assert second.reference == "REG-RFI-24188-0002"


@pytest.mark.asyncio
async def test_each_kind_has_its_own_series_on_the_same_job(session: AsyncSession) -> None:
    pid = await _job(session, "24188")
    rfi = await service.raise_item(session, project_id=pid, kind="rfi", title="a", fields={})
    order = await service.raise_item(session, project_id=pid, kind="order", title="b", fields={})
    assert rfi.reference == "REG-RFI-24188-0001"
    assert order.reference == "REG-ORD-24188-0001"


# ── The rail this change exists for ──────────────────────────────────────


@pytest.mark.asyncio
async def test_two_jobs_each_start_at_one_and_never_collide(session: AsyncSession) -> None:
    """The whole point.

    Per-project numbering was removed once because two jobs both held an
    RFI-004. The job number inside the reference is what makes scoping
    safe again: both jobs own an 0001 and the two strings are still
    different.
    """
    a = await _job(session, "24188")
    b = await _job(session, "24190")
    first_a = await service.raise_item(session, project_id=a, kind="rfi", title="a", fields={})
    first_b = await service.raise_item(session, project_id=b, kind="rfi", title="b", fields={})
    second_a = await service.raise_item(session, project_id=a, kind="rfi", title="a2", fields={})

    assert first_a.reference == "REG-RFI-24188-0001"
    assert first_b.reference == "REG-RFI-24190-0001"
    assert second_a.reference == "REG-RFI-24188-0002"
    # One job's traffic must never advance another's series.
    assert first_a.reference != first_b.reference


@pytest.mark.asyncio
async def test_a_job_with_no_number_refuses_to_raise(session: AsyncSession) -> None:
    """A deliberate call: refuse rather than fall back.

    A fallback would put two shapes of reference in one register with no
    way to tell which job an old one belonged to - the mess this ends.
    """
    pid = await _job(session, None)
    with pytest.raises(service.WorkflowError) as exc:
        await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    assert str(exc.value) == (
        "This job has no job number yet. Set it on the project as "
        '"Project number / code" (for example 25406), then raise this again - '
        "every reference carries the job number, so one cannot be minted without it."
    )


@pytest.mark.asyncio
async def test_the_auto_generated_house_code_does_not_count_as_a_job_number(
    session: AsyncSession,
) -> None:
    """``PRJ-2026-0001`` is what the platform invents when a project is
    created with no number. Accepting it would mint
    ``REG-RFI-PRJ20260001-0001``, which means nothing to anybody."""
    pid = await _job(session, "PRJ-2026-0001")
    with pytest.raises(service.WorkflowError) as exc:
        await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    assert str(exc.value) == (
        "This job has no job number yet. Set it on the project as "
        '"Project number / code" (for example 25406), then raise this again - '
        "every reference carries the job number, so one cannot be minted without it."
    )


@pytest.mark.asyncio
async def test_a_project_number_of_only_punctuation_is_refused(
    session: AsyncSession,
) -> None:
    """It normalises to nothing, so it cannot go into a reference."""
    pid = await _job(session, "---/---")
    with pytest.raises(service.WorkflowError) as exc:
        await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    assert "letters or digits" in str(exc.value)


# ── Preview still never burns ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_preview_peeks_the_job_reference_without_burning_it(
    session: AsyncSession,
) -> None:
    pid = await _job(session, "24188")
    peeked = await service._peek_reference(session, pid, "rfi")
    assert peeked == "REG-RFI-24188-0001"
    for _ in range(4):
        assert await service._peek_reference(session, pid, "rfi") == peeked
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    assert item.reference == peeked


@pytest.mark.asyncio
async def test_peeking_on_a_job_with_no_number_refuses_rather_than_crashes(
    session: AsyncSession,
) -> None:
    """The preview runs on every keystroke in the raise form; it has to
    come back as the message that says what to do."""
    pid = await _job(session, None)
    with pytest.raises(service.WorkflowError):
        await service._peek_reference(session, pid, "rfi")


# ── Mail numbers stay global ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_mail_series_is_not_scoped_to_a_job(session: AsyncSession) -> None:
    """A mail number answers "which email", not "which job" - and the job
    is already named by the item reference quoted in the same email."""
    a = await _job(session, "24188")
    b = await _job(session, "24190")
    await service.raise_item(session, project_id=a, kind="rfi", title="a", fields={})
    await service.raise_item(session, project_id=b, kind="rfi", title="b", fields={})
    first = await service.next_email_reference(session)
    second = await service.next_email_reference(session)
    assert first == "REG-MSG-000001"
    assert second == "REG-MSG-000002"


# ── Existing references are never rewritten ──────────────────────────────


@pytest.mark.asyncio
async def test_a_new_job_series_is_not_seeded_from_another_jobs_numbers(
    session: AsyncSession,
) -> None:
    """A fresh job starts at 0001 however busy the rest of the business
    has been. Seeding from a global high-water mark would open a brand new
    register at 0124."""
    busy = await _job(session, "24188")
    for _ in range(5):
        await service.raise_item(session, project_id=busy, kind="rfi", title="x", fields={})
    fresh = await _job(session, "99999")
    item = await service.raise_item(session, project_id=fresh, kind="rfi", title="y", fields={})
    assert item.reference == "REG-RFI-99999-0001"
