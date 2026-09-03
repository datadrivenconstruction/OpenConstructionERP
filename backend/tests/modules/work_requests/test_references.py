# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The reference: WR-WKS-000001, one series per department, burned once.

The register_workflow lessons, applied here from the start: the counter
row is read under a lock, the first mint's insert race is retried inside
a savepoint, the counter seeds from what is already on the table, and
the unique index is a backstop rather than the mechanism.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.work_requests import service
from app.modules.work_requests.models import WorkRequest, WorkRequestCounter
from tests._pg import isolated_engine, transactional_session
from tests.modules.work_requests._helpers import make_project, make_user, raise_request, seeded


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


def test_the_shape_is_house_prefix_and_six_digits() -> None:
    assert service.format_reference("ENG", 1) == "WR-ENG-000001"
    assert service.format_reference("WKS", 123) == "WR-WKS-000123"
    # 999999 is the padding, not the ceiling.
    assert service.format_reference("AUT", 1_000_000) == "WR-AUT-1000000"
    assert service.derive_prefix("site_services") == "SIT"
    assert service.derive_prefix("qa") == "QAX"


@pytest.mark.asyncio
async def test_each_department_runs_its_own_series(session: AsyncSession) -> None:
    user = await make_user(session)
    proj = await make_project(session, owner=user)
    a = await raise_request(session, project=proj, user=user)
    b = await raise_request(session, project=proj, user=user, department="drafting", request_type="drafting_only")
    c = await raise_request(session, project=proj, user=user)
    assert a.reference == "WR-WKS-000001"
    assert b.reference == "WR-DRF-000001", "drafting does not inherit the workshop's number"
    assert c.reference == "WR-WKS-000002"


@pytest.mark.asyncio
async def test_the_series_is_global_across_jobs(session: AsyncSession) -> None:
    """A workshop reads WR-WKS-000042 off a job card; two jobs must never
    both hold it."""
    user = await make_user(session)
    one = await make_project(session, owner=user, code="25406")
    two = await make_project(session, owner=user, code="25407")
    first = await raise_request(session, project=one, user=user)
    second = await raise_request(session, project=two, user=user)
    assert (first.reference, second.reference) == ("WR-WKS-000001", "WR-WKS-000002")


@pytest.mark.asyncio
async def test_peeking_does_not_burn_a_number(session: AsyncSession) -> None:
    user = await make_user(session)
    proj = await make_project(session, owner=user)
    depts = await seeded(session)
    peeked = await service.peek_reference(session, depts["workshop"])
    assert peeked == await service.peek_reference(session, depts["workshop"])
    raised = await raise_request(session, project=proj, user=user)
    assert raised.reference == peeked


@pytest.mark.asyncio
async def test_a_number_is_never_reissued_after_a_delete(session: AsyncSession) -> None:
    user = await make_user(session)
    proj = await make_project(session, owner=user)
    first = await raise_request(session, project=proj, user=user)
    await session.delete(first)
    await session.flush()
    second = await raise_request(session, project=proj, user=user)
    assert second.reference == "WR-WKS-000002"


@pytest.mark.asyncio
async def test_the_counter_seeds_from_a_reference_already_on_the_table(session: AsyncSession) -> None:
    """A restore must not re-issue a number that is on a drawing."""
    user = await make_user(session)
    proj = await make_project(session, owner=user)
    depts = await seeded(session)
    session.add(
        WorkRequest(
            project_id=proj.id,
            department="workshop",
            reference="WR-WKS-000007",
            title="Old board",
            raised_by_id=str(user.id),
        )
    )
    await session.flush()
    assert await service.peek_reference(session, depts["workshop"]) == "WR-WKS-000008"
    raised = await raise_request(session, project=proj, user=user)
    assert raised.reference == "WR-WKS-000008"


@pytest.mark.asyncio
async def test_losing_the_first_mint_race_retries_instead_of_500(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two people raise the FIRST request on a department in the same
    second: both find no counter row, both insert, and the loser violates
    the unique prefix. That must go back around and mint from the
    winner's row, not escape as a raw IntegrityError."""
    user = await make_user(session)
    proj = await make_project(session, owner=user)
    real = service._highest_existing
    hits = {"n": 0}

    async def with_a_rival(sess: AsyncSession, prefix: str) -> int:
        hits["n"] += 1
        if hits["n"] == 1:
            sess.add(WorkRequestCounter(prefix=prefix, value=0))
        return await real(sess, prefix)

    monkeypatch.setattr(service, "_highest_existing", with_a_rival)
    raised = await raise_request(session, project=proj, user=user)
    assert hits["n"] == 2, "the loser never retried - it would have been a 500"
    assert raised.reference == "WR-WKS-000001"


@pytest.mark.asyncio
async def test_twenty_raises_are_unique_and_in_order(session: AsyncSession) -> None:
    user = await make_user(session)
    proj = await make_project(session, owner=user)
    refs = [(await raise_request(session, project=proj, user=user, title=f"Board {i}")).reference for i in range(20)]
    assert len(set(refs)) == 20
    assert refs[0] == "WR-WKS-000001" and refs[-1] == "WR-WKS-000020"


@pytest.mark.asyncio
async def test_concurrent_sessions_never_share_a_number() -> None:
    """REAL concurrency: separate sessions on separate connections race
    for the first mint and then for every mint after it. The row lock
    serialises them; the savepoint retry handles the first-insert race.
    Every reference must be unique and the series must have no gap."""
    async with isolated_engine() as engine:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as s:
            user = await make_user(s)
            proj = await make_project(s, owner=user)
            await seeded(s)
            await s.commit()
            uid, pid = str(user.id), proj.id

        async def raise_one(i: int) -> str:
            async with maker() as s:
                req = await service.create_request(
                    s,
                    project_id=pid,
                    department="workshop",
                    request_type="switchboard",
                    title=f"Concurrent board {i}",
                    user_id=uid,
                    notify=False,
                )
                await s.commit()
                return req.reference

        refs = await asyncio.gather(*[raise_one(i) for i in range(8)])
        assert len(set(refs)) == 8, f"a number was issued twice: {refs}"
        numbers = sorted(int(r.rsplit("-", 1)[1]) for r in refs)
        assert numbers == list(range(1, 9)), f"the series has a gap or a wrong start: {numbers}"


@pytest.mark.asyncio
async def test_lookup_by_reference_is_case_insensitive(session: AsyncSession) -> None:
    user = await make_user(session)
    proj = await make_project(session, owner=user)
    raised = await raise_request(session, project=proj, user=user)
    assert (await service.request_or_error(session, "wr-wks-000001")).id == raised.id
    assert (await service.request_or_error(session, str(raised.id))).id == raised.id
    with pytest.raises(service.NotFoundError):
        await service.request_or_error(session, "WR-WKS-999999")
    with pytest.raises(service.NotFoundError):
        await service.request_or_error(session, str(uuid.uuid4()))
