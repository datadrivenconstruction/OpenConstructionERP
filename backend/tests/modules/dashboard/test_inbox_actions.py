# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for acknowledging and dismissing inbox rows (PostgreSQL).

Seeds a user with one unread alert and one pending change-order approval, then
checks that the actions do what their names promise and, just as importantly,
that they do not do more than that:

* dismissing an alert clears it here AND marks the notification read, so the
  notifications screen tells the same story;
* dismissing an approval clears it here and leaves the step ``pending``, with
  the finding that says so recorded on the state row;
* restoring puts a row back, and un-reads the notification it had read;
* an id from somebody else's inbox is a 404-shaped failure, not a silent write.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import Severity, rule_registry
from app.modules.changeorders.models import ChangeOrder, ChangeOrderApproval
from app.modules.dashboard.inbox import compute_inbox
from app.modules.dashboard.inbox_actions import (
    InboxActionInvalid,
    InboxActionService,
    InboxItemNotFound,
)
from app.modules.dashboard.inbox_logic import STATE_ACKNOWLEDGED, STATE_DISMISSED
from app.modules.dashboard.repository import InboxItemStateRepository
from app.modules.dashboard.validators import (
    INBOX_ACTION_RULE_SET,
    register_inbox_action_rules,
)
from app.modules.notifications.models import Notification
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest.fixture(autouse=True)
def _rules() -> None:
    """Register the module's rules for every test in this file.

    Nothing calls the module ``on_startup`` hook in the test process, so
    without this the rule set resolves to nothing and every action reports a
    clean result having examined nothing at all.
    """
    register_inbox_action_rules()


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _seed(session: AsyncSession) -> tuple[User, Project, Notification, ChangeOrderApproval]:
    """A user with one unread alert and one pending change-order approval."""
    user = User(
        email=f"inbox-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Inbox",
        role="estimator",
    )
    session.add(user)
    await session.flush()

    proj = Project(name=f"Inbox {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()

    alert = Notification(
        user_id=user.id,
        notification_type="rfi.overdue",
        title_key="notifications.rfi_overdue",
        body_key="notifications.rfi_overdue_body",
        body_context={},
        is_read=False,
    )
    order = ChangeOrder(
        project_id=proj.id,
        code=f"CO-{uuid.uuid4().hex[:4]}",
        title="Additional rebar to core wall",
        status="submitted",
    )
    session.add_all([alert, order])
    await session.flush()

    approval = ChangeOrderApproval(
        change_order_id=order.id,
        step_order=1,
        approver_user_id=user.id,
        decision="pending",
    )
    session.add(approval)
    await session.flush()
    return user, proj, alert, approval


async def _inbox_ids(session: AsyncSession, user: User, proj: Project) -> list[str]:
    payload = await compute_inbox(session, [proj], str(user.id), limit=100)
    return [str(it["id"]) for it in payload["items"]]


# ── The rule set ─────────────────────────────────────────────────────────────


def test_the_engine_actually_resolves_the_inbox_action_rule_set() -> None:
    """The set the service passes must resolve to the rules this module wrote."""
    ids = [r.rule_id for r in rule_registry.get_rules_for_sets([INBOX_ACTION_RULE_SET]) if r.enabled]
    assert ids.count("inbox_action.item_id_recognised") == 1
    assert ids.count("inbox_action.state_known") == 1
    assert ids.count("inbox_action.dismissal_decides_nothing") == 1


def test_the_pending_approval_notice_does_not_block_the_action() -> None:
    """It has to be INFO: a warning that stops the dismiss is not a warning."""
    by_id = {r.rule_id: r for r in rule_registry.get_rules_for_sets([INBOX_ACTION_RULE_SET])}
    assert by_id["inbox_action.dismissal_decides_nothing"].severity == Severity.INFO
    assert by_id["inbox_action.item_id_recognised"].severity == Severity.ERROR
    assert by_id["inbox_action.state_known"].severity == Severity.ERROR


# ── Reading the inbox ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_seeded_inbox_holds_one_alert_and_one_approval(session: AsyncSession) -> None:
    user, proj, alert, approval = await _seed(session)
    payload = await compute_inbox(session, [proj], str(user.id), limit=100)
    assert payload["alerts_count"] == 1
    assert payload["approvals_count"] == 1
    ids = {str(it["id"]) for it in payload["items"]}
    assert f"notification:{alert.id}" in ids
    assert f"change_order_approval:{approval.id}" in ids
    assert all(it["acknowledged"] is False for it in payload["items"])


# ── Acknowledge ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_acknowledging_keeps_the_row_but_flags_it(session: AsyncSession) -> None:
    user, proj, alert, _ = await _seed(session)
    item_id = f"notification:{alert.id}"

    state, findings = await InboxActionService(session).act(
        [proj],
        str(user.id),
        item_id=item_id,
        state=STATE_ACKNOWLEDGED,
    )
    assert state == STATE_ACKNOWLEDGED
    assert findings == []

    payload = await compute_inbox(session, [proj], str(user.id), limit=100)
    flagged = [it for it in payload["items"] if str(it["id"]) == item_id]
    assert len(flagged) == 1
    assert flagged[0]["acknowledged"] is True
    assert payload["alerts_count"] == 1


@pytest.mark.asyncio
async def test_acknowledging_an_alert_leaves_the_notification_unread(
    session: AsyncSession,
) -> None:
    """Acknowledge means seen, not read - marking it read would hide it."""
    user, proj, alert, _ = await _seed(session)
    await InboxActionService(session).act(
        [proj],
        str(user.id),
        item_id=f"notification:{alert.id}",
        state=STATE_ACKNOWLEDGED,
    )
    refreshed = (await session.execute(select(Notification).where(Notification.id == alert.id))).scalar_one()
    assert refreshed.is_read is False


# ── Dismiss ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dismissing_an_alert_clears_it_and_marks_the_notification_read(
    session: AsyncSession,
) -> None:
    user, proj, alert, _ = await _seed(session)
    item_id = f"notification:{alert.id}"

    state, findings = await InboxActionService(session).act(
        [proj],
        str(user.id),
        item_id=item_id,
        state=STATE_DISMISSED,
    )
    assert state == STATE_DISMISSED
    # An alert dismissal is the whole truth, so nothing is reported back.
    assert findings == []

    assert item_id not in await _inbox_ids(session, user, proj)
    refreshed = (await session.execute(select(Notification).where(Notification.id == alert.id))).scalar_one()
    assert refreshed.is_read is True


@pytest.mark.asyncio
async def test_dismissing_an_approval_hides_it_and_says_it_is_still_pending(
    session: AsyncSession,
) -> None:
    user, proj, _, approval = await _seed(session)
    item_id = f"change_order_approval:{approval.id}"

    state, findings = await InboxActionService(session).act(
        [proj],
        str(user.id),
        item_id=item_id,
        state=STATE_DISMISSED,
    )
    assert state == STATE_DISMISSED
    assert [f["rule_id"] for f in findings] == ["inbox_action.dismissal_decides_nothing"]

    assert item_id not in await _inbox_ids(session, user, proj)

    # The obligation itself is untouched: still pending, still the user's.
    refreshed = (
        await session.execute(select(ChangeOrderApproval).where(ChangeOrderApproval.id == approval.id))
    ).scalar_one()
    assert refreshed.decision == "pending"

    # And the finding is on the state row, so an audit can tell a hidden
    # approval from a decided one.
    stored = await InboxItemStateRepository(session).get(user.id, item_id)
    assert stored is not None
    assert [f["rule_id"] for f in stored.findings] == ["inbox_action.dismissal_decides_nothing"]


@pytest.mark.asyncio
async def test_acting_twice_on_one_row_leaves_a_single_state(session: AsyncSession) -> None:
    user, proj, alert, _ = await _seed(session)
    item_id = f"notification:{alert.id}"
    service = InboxActionService(session)

    await service.act([proj], str(user.id), item_id=item_id, state=STATE_ACKNOWLEDGED)
    await service.act([proj], str(user.id), item_id=item_id, state=STATE_DISMISSED)

    rows = await InboxItemStateRepository(session).list_for_user(user.id)
    assert len(rows) == 1
    assert rows[0].state == STATE_DISMISSED


# ── Restore ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_restoring_a_dismissed_alert_brings_it_back_and_un_reads_it(
    session: AsyncSession,
) -> None:
    user, proj, alert, _ = await _seed(session)
    item_id = f"notification:{alert.id}"
    service = InboxActionService(session)

    await service.act([proj], str(user.id), item_id=item_id, state=STATE_DISMISSED)
    assert await service.restore(str(user.id), item_id) is True

    assert item_id in await _inbox_ids(session, user, proj)
    refreshed = (await session.execute(select(Notification).where(Notification.id == alert.id))).scalar_one()
    assert refreshed.is_read is False


@pytest.mark.asyncio
async def test_restoring_a_dismissed_approval_brings_it_back(session: AsyncSession) -> None:
    user, proj, _, approval = await _seed(session)
    item_id = f"change_order_approval:{approval.id}"
    service = InboxActionService(session)

    await service.act([proj], str(user.id), item_id=item_id, state=STATE_DISMISSED)
    assert item_id not in await _inbox_ids(session, user, proj)

    assert await service.restore(str(user.id), item_id) is True
    assert item_id in await _inbox_ids(session, user, proj)


@pytest.mark.asyncio
async def test_restoring_something_never_acted_on_reports_nothing_to_undo(
    session: AsyncSession,
) -> None:
    user, _, alert, _ = await _seed(session)
    service = InboxActionService(session)
    assert await service.restore(str(user.id), f"notification:{alert.id}") is False


# ── Refusals ─────────────────────────────────────────────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_an_item_from_another_users_inbox_is_refused(session: AsyncSession) -> None:
    owner, proj, alert, _ = await _seed(session)
    intruder = User(
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Other",
        role="estimator",
    )
    session.add(intruder)
    await session.flush()

    with pytest.raises(InboxItemNotFound):
        await InboxActionService(session).act(
            [proj],
            str(intruder.id),
            item_id=f"notification:{alert.id}",
            state=STATE_DISMISSED,
        )
    assert await InboxItemStateRepository(session).list_for_user(intruder.id) == []


@pytest.mark.asyncio
async def test_an_id_naming_an_unknown_source_is_refused(session: AsyncSession) -> None:
    user, proj, _, _ = await _seed(session)
    with pytest.raises(InboxActionInvalid) as exc:
        await InboxActionService(session).act(
            [proj],
            str(user.id),
            item_id=f"rfi:{uuid.uuid4()}",
            state=STATE_DISMISSED,
        )
    assert any(f["rule_id"] == "inbox_action.item_id_recognised" for f in exc.value.findings)


@pytest.mark.asyncio
async def test_an_unknown_state_is_refused(session: AsyncSession) -> None:
    user, proj, alert, _ = await _seed(session)
    with pytest.raises(InboxActionInvalid) as exc:
        await InboxActionService(session).act(
            [proj],
            str(user.id),
            item_id=f"notification:{alert.id}",
            state="snoozed",
        )
    assert any(f["rule_id"] == "inbox_action.state_known" for f in exc.value.findings)
    assert await InboxItemStateRepository(session).get(user.id, f"notification:{alert.id}") is None
