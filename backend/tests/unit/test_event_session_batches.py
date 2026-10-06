# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""No network: bounded sessions, context isolation and drain for wildcard work."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.audit_log import AuditContext, get_audit_context, reset_audit_context, set_audit_context
from app.core.event_batches import ContextBatchQueue, run_session_batch
from app.core.events import _DETACHED_TASKS, Event, EventBus
from app.core.rls import current_request_tenant, reset_request_tenant, set_request_tenant


@pytest.mark.parametrize("subscriber", ["webhooks", "timeline"])
async def test_a_thousand_events_keep_order_with_bounded_sessions(monkeypatch, subscriber):
    from app.core import event_handlers
    from app.modules.integrations.service import WebhookService
    from app.modules.timeline import events as timeline

    opened = active = peak = 0
    seen = []

    @asynccontextmanager
    async def factory():
        nonlocal opened, active, peak
        opened += 1
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0)
            yield SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        finally:
            active -= 1

    async def dispatch(_self, _name, payload, **_kwargs):
        seen.append(payload["data"]["number"])
        await asyncio.sleep(0)
        return 0

    async def record(_session, **kwargs):
        seen.append(kwargs["metadata"]["number"])
        await asyncio.sleep(0)

    monkeypatch.setattr("app.database.async_session_factory", factory)
    monkeypatch.setattr(WebhookService, "dispatch_event", dispatch)
    monkeypatch.setattr(timeline, "async_session_factory", factory)
    monkeypatch.setattr(timeline, "log_activity", record)
    handler = event_handlers._dispatch_to_webhooks if subscriber == "webhooks" else timeline._record_event
    await asyncio.gather(
        *(handler(Event(name="ncr.created", data={"ncr_id": str(n), "number": n})) for n in range(1000))
    )
    assert seen == list(range(1000))
    assert (opened, peak, active) == ((1000, 4, 0) if subscriber == "webhooks" else (5, 1, 0))


@pytest.mark.parametrize("subscriber", ["webhooks", "timeline"])
async def test_mixed_contexts_keep_their_tenant_actor_request_and_session(monkeypatch, subscriber):
    from app.core import event_handlers
    from app.modules.integrations.service import WebhookService
    from app.modules.timeline import events as timeline

    seen = []
    session_tenants = []

    @asynccontextmanager
    async def factory():
        tenant = current_request_tenant()
        session_tenants.append(tenant)
        yield SimpleNamespace(tenant=tenant, commit=AsyncMock(), rollback=AsyncMock())

    async def capture(session, number):
        context = get_audit_context()
        seen.append((number, session.tenant, current_request_tenant(), context))
        await asyncio.sleep(0)

    async def dispatch(service, _name, payload, **_kwargs):
        await capture(service.session, payload["data"]["number"])
        return 0

    async def record(session, **kwargs):
        await capture(session, kwargs["metadata"]["number"])

    monkeypatch.setattr("app.database.async_session_factory", factory)
    monkeypatch.setattr(WebhookService, "dispatch_event", dispatch)
    monkeypatch.setattr(timeline, "async_session_factory", factory)
    monkeypatch.setattr(timeline, "log_activity", record)
    handler = event_handlers._dispatch_to_webhooks if subscriber == "webhooks" else timeline._record_event
    tasks = []
    expected = []
    for n, tenant in enumerate(("alpha", "beta", None, "alpha")):
        ctx = AuditContext(actor_id=f"actor-{n}", tenant_id=tenant, request_id=f"request-{n}")
        audit_token = set_audit_context(ctx)
        tenant_token = set_request_tenant(tenant)
        try:
            tasks.append(asyncio.create_task(handler(Event(name="ncr.created", data={"ncr_id": str(n), "number": n}))))
            expected.append((n, tenant, tenant, ctx))
        finally:
            reset_request_tenant(tenant_token)
            reset_audit_context(audit_token)
    await asyncio.gather(*tasks)
    assert seen == expected
    assert session_tenants == ["alpha", "beta", None, "alpha"]


async def test_full_queue_applies_backpressure_without_dropping_or_reordering():
    entered = asyncio.Event()
    release = asyncio.Event()
    seen = []

    async def process(items):
        entered.set()
        await release.wait()
        seen.extend(items)

    queue = ContextBatchQueue("test.capacity", process, batch_size=1, capacity=2)
    tasks = [asyncio.create_task(queue.submit(n)) for n in range(10)]
    await entered.wait()
    assert len(queue._pending) == 1  # plus one in flight; eight await admission
    assert not any(t.done() for t in tasks)
    release.set()
    await asyncio.gather(*tasks)
    assert seen == list(range(10))


async def test_cancelled_publisher_does_not_cancel_admitted_work_or_peers():
    entered = asyncio.Event()
    release = asyncio.Event()
    seen = []

    async def process(items):
        entered.set()
        await release.wait()
        seen.extend(items)

    queue = ContextBatchQueue("test.cancel-publisher", process)
    first = asyncio.create_task(queue.submit(1))
    second = asyncio.create_task(queue.submit(2))
    await entered.wait()
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)
    release.set()
    await second
    assert seen == [1, 2]


async def test_shutdown_waits_for_queued_work_and_closes_session():
    closed = False
    seen = []

    async def process(items):
        nonlocal closed
        try:
            await asyncio.sleep(0.01)
            seen.extend(items)
        finally:
            closed = True

    queue = ContextBatchQueue("test.drain", process, batch_size=2)
    bus = EventBus()
    bus._extra_task_sets.append(_DETACHED_TASKS)

    async def handler(event):
        await queue.submit(event.data["number"])

    bus.subscribe("test", handler)
    for n in range(7):
        bus.publish_detached("test", {"number": n})
    result = await bus.drain(timeout=2)
    assert result.cancelled == 0
    assert seen == list(range(7))
    assert closed and not bus.pending_tasks()


async def test_forced_shutdown_cancels_waiters_closes_session_and_queue_can_restart(caplog):
    entered = asyncio.Event()
    closed = asyncio.Event()
    seen = []

    async def process(items):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    queue = ContextBatchQueue("test.deadline", process, batch_size=1)
    bus = EventBus()
    bus._extra_task_sets.append(_DETACHED_TASKS)

    async def handler(event):
        await queue.submit(event.data["number"])

    bus.subscribe("test", handler)
    tasks = [bus.publish_detached("test", {"number": n}) for n in range(4)]
    await entered.wait()
    result = await bus.drain(timeout=0)
    assert result.cancelled >= 1
    assert closed.is_set()
    assert all(t.done() for t in tasks)
    assert not queue._pending
    assert "events queued" in caplog.text

    async def later(items):
        seen.extend(items)

    queue._process = later
    await queue.submit(9)
    assert seen == [9]


async def test_shutdown_before_worker_starts_releases_capacity_and_queue_can_restart(caplog):
    seen = []

    async def process(items):
        seen.extend(items)

    queue = ContextBatchQueue("test.cancel-before-start", process, capacity=1)
    bus = EventBus()
    bus._extra_task_sets.append(_DETACHED_TASKS)

    async def handler(event):
        await queue.submit(event.data["number"])

    bus.subscribe("test", handler)
    publisher = bus.publish_detached("test", {"number": 1})
    # The publisher admits its item, but its new worker has not run yet.
    await asyncio.sleep(0)
    assert not seen and len(queue._pending) == 1
    assert queue._slots._value == 0
    result = await bus.drain(timeout=0)
    assert result.cancelled >= 1 and publisher.done()
    assert not queue._pending and queue._slots._value == 1
    assert "events queued" in caplog.text
    await asyncio.wait_for(queue.submit(2), timeout=2)
    assert seen == [2]


async def test_immediate_restart_before_old_done_callback_preserves_new_work():
    seen = []

    async def process(items):
        seen.extend(items)

    queue = ContextBatchQueue("test.cancel-restart-race", process, capacity=1)
    publisher = asyncio.create_task(queue.submit(1))
    await asyncio.sleep(0)
    old_worker = queue._worker
    old_worker.cancel()
    await asyncio.sleep(0)
    # Task cancellation has landed, but its queued done callbacks have not.
    assert old_worker.done() and queue._worker is old_worker
    assert len(queue._pending) == 1 and queue._slots._value == 0
    # Start submit inline, before the old callback. It must reclaim the old
    # slot itself; the later callback must not cancel the replacement worker.
    async with asyncio.timeout(2):
        await queue.submit(2)
    result = await asyncio.gather(publisher, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)
    assert seen == [2] and not queue._pending and queue._slots._value == 1


def test_cancelled_queue_can_restart_on_a_new_event_loop():
    seen = []

    async def process(items):
        seen.extend(items)

    queue = ContextBatchQueue("test.cancel-new-loop", process, capacity=1)

    async def cancel_first():
        publisher = asyncio.create_task(queue.submit(1))
        await asyncio.sleep(0)
        queue._worker.cancel()
        result = await asyncio.gather(publisher, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert not queue._pending and queue._slots._value == 1
        return asyncio.get_running_loop()

    async def restart(old_loop):
        assert asyncio.get_running_loop() is not old_loop
        await asyncio.wait_for(queue.submit(2), timeout=2)
        assert seen == [2] and queue._slots._value == 1

    asyncio.run(restart(asyncio.run(cancel_first())))


@pytest.mark.parametrize("rollback_fails", [False, True])
async def test_failed_dispatch_is_never_retried_and_later_events_survive(rollback_fails):
    opened = closed = 0
    attempted = []
    committed = []

    @asynccontextmanager
    async def factory():
        nonlocal opened, closed
        opened += 1
        session = SimpleNamespace(number=opened, commit=AsyncMock(), rollback=AsyncMock())
        if rollback_fails and opened == 1:
            session.rollback.side_effect = ConnectionError("connection lost")
        try:
            yield session
        finally:
            closed += 1

    async def dispatch(session, item):
        attempted.append(item)  # represents a delivery that might already be sent
        if item == 2:
            raise ConnectionError("delivery log failed after HTTP")
        committed.append((item, session.number))

    await run_session_batch("test.no-retry", [1, 2, 3], factory, dispatch)
    assert attempted == [1, 2, 3]
    assert committed == [(1, 1), (3, 2 if rollback_fails else 1)]
    assert opened == closed == (2 if rollback_fails else 1)


async def test_poisoned_session_close_failure_does_not_discard_unstarted_events(caplog):
    sessions = []
    attempted = []
    completed = []

    @asynccontextmanager
    async def factory():
        session = SimpleNamespace(number=len(sessions) + 1, commit=AsyncMock(), rollback=AsyncMock())
        sessions.append(session)
        if session.number == 1:
            session.rollback.side_effect = ConnectionError("rollback failed")
        try:
            yield session
        finally:
            if session.number == 1:
                raise ConnectionError("close failed too")

    async def dispatch(session, item):
        attempted.append(item)
        if item == 1:
            raise ConnectionError("write failed after possible side effect")
        completed.append((item, session.number))

    async def process(items):
        await run_session_batch("test.poisoned-close", items, factory, dispatch)

    queue = ContextBatchQueue("test.poisoned-close", process)
    assert await asyncio.gather(*(queue.submit(n) for n in (1, 2, 3))) == [None, None, None]
    assert attempted == [1, 2, 3]  # the already-started event is never retried
    assert completed == [(2, 2), (3, 2)]
    assert len(sessions) == 2
    sessions[0].commit.assert_not_awaited()
    sessions[0].rollback.assert_awaited_once()
    assert sessions[1].commit.await_count == 2
    assert "poisoned session close failed" in caplog.text


@pytest.mark.parametrize("failure_stage", ["factory", "enter"])
async def test_session_setup_failure_still_propagates_without_retry(failure_stage, caplog):
    calls = []
    dispatch = AsyncMock()

    @asynccontextmanager
    async def context():
        raise ConnectionError("session enter failed")
        yield  # pragma: no cover - an async context manager must be a generator

    def factory():
        calls.append(failure_stage)
        if failure_stage == "factory":
            raise ConnectionError("session factory failed")
        return context()

    with pytest.raises(ConnectionError, match=f"session {failure_stage} failed"):
        await run_session_batch("test.setup", [1, 2], factory, dispatch)
    assert calls == [failure_stage]
    dispatch.assert_not_awaited()
    assert "poisoned session close failed" not in caplog.text


async def test_arbitrary_unhashable_context_values_are_preserved():
    variable = ContextVar("test.unhashable")
    seen = []

    async def process(items):
        seen.append((items, variable.get()))

    queue = ContextBatchQueue("test.context", process)
    first, second = [], []
    variable.set(first)
    task = asyncio.create_task(queue.submit(1))
    variable.set(second)
    await queue.submit(2)
    await task
    assert len(seen) == 2
    assert seen[0][0] == [2] and seen[0][1] is second
    assert seen[1][0] == [1] and seen[1][1] is first


async def test_unbound_background_context_does_not_share_a_batch_with_anonymous_request():
    from contextvars import Context

    from app.core import rls

    seen = []

    async def process(items):
        seen.append((items, rls._request_tenant.get()))

    queue = ContextBatchQueue("test.system-vs-anonymous", process)
    background = asyncio.create_task(queue.submit(1), context=Context())
    token = set_request_tenant(None)
    try:
        anonymous = asyncio.create_task(queue.submit(2))
    finally:
        reset_request_tenant(token)
    await asyncio.gather(background, anonymous)
    assert seen == [([1], rls._UNSET), ([2], None)]


async def test_a_commit_failure_is_rolled_back_without_replaying_the_delivery():
    delivered = []
    session = SimpleNamespace(commit=AsyncMock(side_effect=[RuntimeError("commit failed"), None]), rollback=AsyncMock())

    @asynccontextmanager
    async def factory():
        yield session

    async def dispatch(_session, item):
        delivered.append(item)

    await run_session_batch("test.commit", [1, 2], factory, dispatch)
    assert delivered == [1, 2]
    assert session.commit.await_count == 2
    session.rollback.assert_awaited_once()


async def test_failed_batch_releases_capacity_and_allows_later_work(caplog):
    calls = []

    async def process(items):
        calls.append(items)
        if items == [1]:
            raise ConnectionError("session setup failed")

    queue = ContextBatchQueue("test.recovery", process, capacity=1)
    await asyncio.gather(queue.submit(1), queue.submit(2))
    assert calls == [[1], [2]]
    assert "not retried" in caplog.text


async def test_real_named_handler_can_await_nested_publish_before_the_wildcard(monkeypatch):
    from app.core import event_handlers
    from app.modules.integrations.service import WebhookService

    seen = []

    @asynccontextmanager
    async def factory():
        yield SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    async def dispatch(_service, name, _payload, **_kwargs):
        seen.append(name)
        return 0

    bus = EventBus()
    monkeypatch.setattr(event_handlers, "event_bus", bus)
    monkeypatch.setattr("app.database.async_session_factory", factory)
    monkeypatch.setattr(WebhookService, "dispatch_event", dispatch)
    bus.subscribe("inspection.completed.failed", event_handlers._handle_inspection_completed_failed)
    bus.subscribe("*", event_handlers._dispatch_to_webhooks)
    result = await asyncio.wait_for(
        bus.publish("inspection.completed.failed", {"inspection_id": "inspection", "result": "fail"}), timeout=2
    )
    assert result.success
    assert seen == ["punchlist.suggestion.from_inspection", "inspection.completed.failed"]


async def test_detached_publication_from_a_commit_does_not_wait_on_its_own_worker(monkeypatch):
    from app.modules.timeline import events as timeline

    seen = []
    emitted = False
    bus = EventBus()
    bus._extra_task_sets.append(_DETACHED_TASKS)

    async def commit():
        nonlocal emitted
        if not emitted:
            emitted = True
            # The actual publish_after_commit hook uses publish_detached,
            # never await publish while the caller's commit is in progress.
            bus.publish_detached("ncr.created", {"ncr_id": "child"})

    @asynccontextmanager
    async def factory():
        yield SimpleNamespace(commit=commit, rollback=AsyncMock())

    async def record(_session, **kwargs):
        seen.append(kwargs["entity_id"])

    monkeypatch.setattr(timeline, "async_session_factory", factory)
    monkeypatch.setattr(timeline, "log_activity", record)
    bus.subscribe("*", timeline._record_event)
    await asyncio.wait_for(bus.publish("ncr.created", {"ncr_id": "parent"}), timeout=2)
    result = await bus.drain(timeout=2)
    assert result.cancelled == 0
    assert seen == ["parent", "child"]


async def test_one_slow_webhook_does_not_monopolise_dispatch(monkeypatch):
    from app.core import event_handlers
    from app.modules.integrations.service import WebhookService

    blocked = asyncio.Event()
    release = asyncio.Event()
    completed = []

    @asynccontextmanager
    async def factory():
        yield SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    async def dispatch(_service, name, _payload, **_kwargs):
        if name == "slow":
            blocked.set()
            await release.wait()
        completed.append(name)
        return 0

    monkeypatch.setattr("app.database.async_session_factory", factory)
    monkeypatch.setattr(WebhookService, "dispatch_event", dispatch)
    slow = asyncio.create_task(event_handlers._dispatch_to_webhooks(Event(name="slow", data={})))
    await blocked.wait()
    try:
        await asyncio.wait_for(event_handlers._dispatch_to_webhooks(Event(name="fast", data={})), timeout=2)
        assert completed == ["fast"]
        assert not slow.done()
    finally:
        release.set()
        await slow


@pytest.mark.parametrize("failure", ["cancel", "exception"])
async def test_webhook_failure_or_cancellation_releases_the_slot_without_retry(monkeypatch, failure):
    from app.core import event_handlers
    from app.modules.integrations.service import WebhookService

    entered = asyncio.Event()
    release = asyncio.Event()
    attempted = []
    closed = 0

    @asynccontextmanager
    async def factory():
        nonlocal closed
        try:
            yield SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        finally:
            closed += 1

    async def dispatch(_service, name, _payload, **_kwargs):
        attempted.append(name)
        if name == "first":
            entered.set()
            await release.wait()
            raise ConnectionError("HTTP may have been sent before audit failure")
        return 0

    monkeypatch.setattr("app.database.async_session_factory", factory)
    monkeypatch.setattr(WebhookService, "dispatch_event", dispatch)
    first = asyncio.create_task(event_handlers._dispatch_to_webhooks(Event(name="first", data={})))
    await entered.wait()
    if failure == "cancel":
        first.cancel()
    else:
        release.set()
    await asyncio.gather(first, return_exceptions=True)
    await event_handlers._dispatch_to_webhooks(Event(name="next", data={}))
    assert attempted == ["first", "next"]
    assert closed == 2
    assert event_handlers._webhook_gate()._value == event_handlers._WEBHOOK_CONCURRENCY
