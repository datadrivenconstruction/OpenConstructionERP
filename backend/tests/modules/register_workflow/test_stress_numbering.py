# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Second adversarial pass: the per-job reference, attacked at its edges.

The first pass covered the conversation log. This one goes after the
numbering that landed on top of it, and the boundaries it created between
what a job number may be, what fits in a column, and what the inbound
matcher can read back.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.register_workflow import emailing, service
from app.modules.register_workflow.models import RegisterItem
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _job(session: AsyncSession, code: str | None) -> uuid.UUID:
    user = User(
        email=f"sn-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="SN",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"SN {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="AUD", project_code=code)
    session.add(proj)
    await session.flush()
    return proj.id


# ── The reference has to FIT ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_over_long_job_number_is_refused_not_truncated(
    session: AsyncSession,
) -> None:
    """``RegisterItem.reference`` is String(40) and the counter's ``scope``
    is String(40). A 60-character project code would build a reference too
    long for its own column - a database error on raise, or worse a
    silently truncated reference that no reply can ever match.

    Refuse it with a message instead.
    """
    # 50 is the widest ``Project.project_code`` itself allows, so this is
    # the longest code that can actually reach the register.
    pid = await _job(session, "J" * 50)
    with pytest.raises(service.WorkflowError) as exc:
        await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    assert "too long" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_the_longest_allowed_job_number_still_fits_its_column(
    session: AsyncSession,
) -> None:
    """At the cap, everything downstream still has room."""
    job = "9" * service.JOB_NUMBER_MAX
    pid = await _job(session, job)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    assert item.reference == f"REG-RFI-{job}-0001"
    assert len(item.reference) <= 40, "the reference does not fit RegisterItem.reference"
    assert len(job) <= 40, "the job number does not fit RegisterCounter.scope"


@pytest.mark.asyncio
async def test_a_four_digit_series_can_roll_past_its_padding(
    session: AsyncSession,
) -> None:
    """0001..9999 is the padding, not the ceiling. Number 10000 must widen
    rather than wrap back onto a number already issued."""
    pid = await _job(session, "24188")
    assert service.format_reference("RFI", 9999, "24188") == "REG-RFI-24188-9999"
    assert service.format_reference("RFI", 10000, "24188") == "REG-RFI-24188-10000"
    assert len(service.format_reference("RFI", 10000, "9" * service.JOB_NUMBER_MAX)) <= 40
    _ = pid


# ── Two jobs must never share a series ───────────────────────────────────


@pytest.mark.asyncio
async def test_two_projects_normalising_to_the_same_job_are_refused(
    session: AsyncSession,
) -> None:
    """THE ONE THAT MATTERS.

    ``24-188`` and ``24188`` both normalise to ``24188``. Left alone, two
    different jobs would share one counter and their references would be
    indistinguishable: ``REG-RFI-24188-0002`` could belong to either, and
    a reply quoting it could be filed against the wrong job - the exact
    ambiguity per-job numbering exists to remove.
    """
    first = await _job(session, "24188")
    await service.raise_item(session, project_id=first, kind="rfi", title="a", fields={})

    clash = await _job(session, "24-188")
    with pytest.raises(service.WorkflowError) as exc:
        await service.raise_item(session, project_id=clash, kind="rfi", title="b", fields={})
    assert "24188" in str(exc.value)
    assert "another job" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_case_only_differences_are_the_same_job_too(session: AsyncSession) -> None:
    """``ab12`` and ``AB12`` normalise identically."""
    first = await _job(session, "ab12")
    await service.raise_item(session, project_id=first, kind="rfi", title="a", fields={})
    clash = await _job(session, "AB12")
    with pytest.raises(service.WorkflowError):
        await service.raise_item(session, project_id=clash, kind="rfi", title="b", fields={})


@pytest.mark.asyncio
async def test_the_same_project_raising_again_is_never_a_clash(
    session: AsyncSession,
) -> None:
    """The uniqueness check must not fire on the job's own items."""
    pid = await _job(session, "24188")
    for _ in range(3):
        await service.raise_item(session, project_id=pid, kind="rfi", title="x", fields={})
    item = await service.raise_item(
        session,
        project_id=pid,
        kind="rfq",
        title="y",
        fields={
            "Package": "P",
            "Delivery to": "S",
            "Site contact": "D",
            "Delivery window / site hours": "6-2",
            "Estimated value $": "100",
            "Quotes due": "2099-01-01",
        },
    )
    assert item.reference == "REG-RFQ-24188-0001"


# ── What the matcher can read back ───────────────────────────────────────


# ── Regressions on everything the first pass covered ─────────────────────


@pytest.mark.asyncio
async def test_money_is_still_withheld_now_references_carry_a_job(
    session: AsyncSession,
) -> None:
    pid = await _job(session, "24188")
    item = await service.raise_item(
        session,
        project_id=pid,
        kind="variation",
        title="VO",
        fields={
            "Description of change": "Extra circuits",
            "Cost $": "18400",
            "Sell $": "24900",
            "Margin": "26%",
            "Responsible": "Sam Rivera",
            "Ball in court": "The client",
        },
    )
    built = await emailing.build_item_email(session, item, contact_id=None)
    assert "REG-VO-24188-0001" in built["html"], "the job reference is not on the document"
    assert "Sam Rivera" in built["html"]
    assert "The client" in built["html"]
    for leak in ("18400", "24900", "26%", "Margin", "Cost $", "Sell $"):
        assert leak not in built["html"], f"{leak!r} leaked"


@pytest.mark.asyncio
async def test_the_stored_document_still_holds_the_job_reference(
    session: AsyncSession,
) -> None:
    pid = await _job(session, "24188")
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    built = await emailing.build_item_email(session, item, contact_id=None)
    await emailing.record_send(
        session,
        item,
        contact_id=None,
        contact_name="A",
        subject=built["subject"],
        channel="outlook",
        user_id="u1",
        email_ref="REG-MSG-000001",
        html=built["html"],
    )
    kept = emailing.send_log(item)[-1]
    assert "REG-RFI-24188-0001" in kept["html"]
    assert kept["email_ref"] == "REG-MSG-000001"


@pytest.mark.asyncio
async def test_a_forged_send_log_is_still_refused(session: AsyncSession) -> None:
    pid = await _job(session, "24188")
    item = await service.raise_item(
        session,
        project_id=pid,
        kind="rfi",
        title="Q",
        fields={"Question": "real", "_send_log": [{"html": "<p>forged</p>"}]},
    )
    assert emailing.send_log(item) == []


@pytest.mark.asyncio
async def test_markup_in_a_job_number_can_never_reach_the_document(
    session: AsyncSession,
) -> None:
    """The job number goes into the SUBJECT and the body. Normalisation
    should leave nothing but letters and digits, so there is nothing to
    escape - this proves it rather than assuming it."""
    pid = await _job(session, '24188"><script>alert(1)</script>')
    # Normalisation leaves 24188SCRIPTALERT1SCRIPT - letters and digits
    # only, nothing to escape - and that is over the cap, so it is refused
    # outright. Two independent reasons this can never reach a document.
    with pytest.raises(service.WorkflowError) as exc:
        await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    assert "<" not in str(exc.value.args[0].split("normalises")[-1] if "normalises" in str(exc.value) else "")
    assert service.normalise_job_number('24188"><script>alert(1)</script>') == "24188SCRIPTALERT1SCRIPT"

    # A SHORT one is minted, and still carries nothing but letters/digits.
    ok = await _job(session, "<b>24188</b>")
    item = await service.raise_item(session, project_id=ok, kind="rfi", title="Q", fields={})
    assert item.reference == "REG-RFI-B24188B-0001"
    built = await emailing.build_item_email(session, item, contact_id=None)
    assert "<script" not in built["html"].lower()
    assert "<b>24188</b>" not in built["subject"]


# ── The counter, under pressure ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_legacy_reference_shaped_like_this_job_does_seed_it(
    session: AsyncSession,
) -> None:
    """A re-install must not re-issue numbers already on emails. If the
    table already holds REG-RFI-24188-0007, the next mint is 0008."""
    pid = await _job(session, "24188")
    session.add(RegisterItem(project_id=pid, kind="rfi", reference="REG-RFI-24188-0007", title="Old", fields={}))
    await session.flush()
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="New", fields={})
    assert item.reference == "REG-RFI-24188-0008"


@pytest.mark.asyncio
async def test_another_jobs_reference_never_seeds_this_one(session: AsyncSession) -> None:
    pid = await _job(session, "24188")
    session.add(RegisterItem(project_id=pid, kind="rfi", reference="REG-RFI-99999-0500", title="Other", fields={}))
    await session.flush()
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="New", fields={})
    assert item.reference == "REG-RFI-24188-0001"


@pytest.mark.asyncio
async def test_two_jobs_each_open_their_own_series_for_the_same_kind(
    session: AsyncSession,
) -> None:
    """THE 31 AUG LIVE FAILURE, pinned.

    Both live databases had kept v0002's UNIQUE index on ``prefix`` alone
    (an early cut of v0003 never dropped it), so the first job to use a
    kind claimed the prefix and every OTHER job's raise of that kind died
    on a duplicate-key 500. Two jobs opening the same kind's series is the
    entire point of per-job numbering - it must just work.
    """
    a = await _job(session, "24188")
    b = await _job(session, "24190")
    ia = await service.raise_item(session, project_id=a, kind="rfi", title="a", fields={})
    ib = await service.raise_item(session, project_id=b, kind="rfi", title="b", fields={})
    assert ia.reference == "REG-RFI-24188-0001"
    assert ib.reference == "REG-RFI-24190-0001"


@pytest.mark.asyncio
async def test_losing_the_first_mint_race_retries_instead_of_500(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two people raise the FIRST item of a kind on one job in the same
    second: both find no counter row, both insert, and the loser violates
    uq_(prefix, scope). That used to escape as a raw IntegrityError - a
    500 - and the failed flush poisoned the session besides. The loser
    must go back around and mint from the winner's row instead.

    The rival is injected between the SELECT and the INSERT by riding the
    ``_highest_legacy`` call that sits exactly there.
    """
    from app.modules.register_workflow.models import RegisterCounter

    pid = await _job(session, "24188")
    real = service._highest_legacy
    hits = {"n": 0}

    async def with_a_rival(sess: AsyncSession, prefix: str, job: str) -> int:
        hits["n"] += 1
        if hits["n"] == 1:
            sess.add(RegisterCounter(prefix=prefix, scope=job, value=0))
        return await real(sess, prefix, job)

    monkeypatch.setattr(service, "_highest_legacy", with_a_rival)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    assert hits["n"] == 2, "the loser never retried - it would have been a 500"
    assert item.reference == "REG-RFI-24188-0001"


@pytest.mark.asyncio
async def test_twenty_raises_on_one_job_are_unique_and_in_order(
    session: AsyncSession,
) -> None:
    pid = await _job(session, "24188")
    refs = [
        (await service.raise_item(session, project_id=pid, kind="rfi", title=f"Q{i}", fields={})).reference
        for i in range(20)
    ]
    assert len(set(refs)) == 20
    assert refs[0] == "REG-RFI-24188-0001"
    assert refs[-1] == "REG-RFI-24188-0020"
