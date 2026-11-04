# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Webhook delivery: signed headers, retry schedule, dead letters, SSRF re-check, redeliver."""

from __future__ import annotations

import socket
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.modules.projects.models  # noqa: F401 - the endpoint table references projects
from app.core.url_safety import UnsafeUrlError
from app.modules.integrations import event_catalogue
from app.modules.integrations import service as svc_mod
from app.modules.integrations import webhook_signing as ws
from app.modules.integrations.models import WebhookDelivery, WebhookEndpoint
from app.modules.integrations.router import redeliver_webhook_delivery
from app.modules.integrations.schemas import WebhookCreate, WebhookUpdate
from app.modules.integrations.service import MAX_ENDPOINTS_PER_USER, RETRY_BATCH, WebhookService
from app.modules.users.models import User
from tests.modules._partner_db import partner_engine

URL = "https://hooks.example.com/oe"
T0 = datetime(2026, 11, 3, 12, 0, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def maker():
    async with partner_engine([User.__table__, WebhookEndpoint.__table__, WebhookDelivery.__table__]) as engine:
        yield async_sessionmaker(engine, expire_on_commit=False)


class FakeNet:
    """Replaces the network: records requests and answers from a queue of statuses."""

    def __init__(self, monkeypatch, *statuses: int | Exception) -> None:
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []
        self.statuses = list(statuses)

        async def _post(url, body, headers):
            self.calls.append((url, body, headers))
            nxt = self.statuses.pop(0) if self.statuses else 200
            if isinstance(nxt, Exception):
                raise nxt
            return nxt, "ok"

        async def _ok(url):
            return url

        monkeypatch.setattr(svc_mod, "_post", _post)
        monkeypatch.setattr(svc_mod, "resolve_and_validate_external_url", _ok)


def _freeze(monkeypatch, now: datetime) -> None:
    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(svc_mod, "datetime", _Clock)


async def _user(maker) -> uuid.UUID:
    async with maker() as s:
        user = User(email=f"{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role="manager", is_active=True)
        s.add(user)
        await s.commit()
        return user.id


async def _hook(maker, user_id, **fields) -> uuid.UUID:
    async with maker() as s:
        hook = WebhookEndpoint(
            user_id=user_id,
            name=fields.pop("name", "h"),
            url=fields.pop("url", URL),
            secret=fields.pop("secret", "s" * 32),
            events=fields.pop("events", ["*"]),
            **fields,
        )
        s.add(hook)
        await s.commit()
        return hook.id


async def _load(maker, model, row_id):
    async with maker() as s:
        return await s.get(model, row_id)


# ── Headers and first attempt ──────────────────────────────────────────────


async def test_delivery_is_signed_and_carries_event_and_delivery_ids(maker, monkeypatch):
    net = FakeNet(monkeypatch, 200)
    uid = await _user(maker)
    hook_id = await _hook(maker, uid, secret="whsec_test_secret_0123456789abcdef")
    async with maker() as s:
        hook = await s.get(WebhookEndpoint, hook_id)
        delivery = await WebhookService(s).deliver_to(hook, "rfi.created", {"event": "rfi.created", "n": 1})

    ((url, body, headers),) = net.calls
    assert url == URL
    assert headers[ws.EVENT_HEADER] == "rfi.created"
    assert headers[ws.DELIVERY_HEADER] == str(delivery.id)
    assert ws.verify_signature("whsec_test_secret_0123456789abcdef", headers[ws.SIGNATURE_HEADER], body)
    assert headers[ws.LEGACY_SIGNATURE_HEADER] == ws.legacy_signature("whsec_test_secret_0123456789abcdef", body)
    assert delivery.status == "delivered"
    assert delivery.attempt == 1
    assert delivery.next_retry_at is None


async def test_unsigned_when_endpoint_has_no_secret(maker, monkeypatch):
    net = FakeNet(monkeypatch, 200)
    uid = await _user(maker)
    hook_id = await _hook(maker, uid, secret=None)
    async with maker() as s:
        await WebhookService(s).deliver_to(await s.get(WebhookEndpoint, hook_id), "x.y", {})
    assert ws.SIGNATURE_HEADER not in net.calls[0][2]


async def test_redirects_are_not_followed_and_timeout_is_10s(monkeypatch):
    seen: dict = {}

    class _Resp:
        status_code = 302
        text = ""

    class _Client:
        def __init__(self, **kw):
            seen.update(kw)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, content, headers):
            return _Resp()

    monkeypatch.setattr(svc_mod.httpx, "AsyncClient", _Client)
    assert await svc_mod._post(URL, b"{}", {}) == (302, "")
    assert seen == {"timeout": 10.0, "follow_redirects": False}


# ── Retry schedule ─────────────────────────────────────────────────────────


async def test_retry_schedule_with_a_frozen_clock_ends_dead_after_five_sends(maker, monkeypatch):
    net = FakeNet(monkeypatch, 500, 503, 502, 500, 500)
    uid = await _user(maker)
    hook_id = await _hook(maker, uid)
    _freeze(monkeypatch, T0)
    async with maker() as s:
        delivery = await WebhookService(s).deliver_to(await s.get(WebhookEndpoint, hook_id), "a.b", {"k": 1})
        did = delivery.id
    row = await _load(maker, WebhookDelivery, did)
    assert (row.status, row.attempt) == ("retrying", 1)
    assert _utc(row.next_retry_at) == T0 + timedelta(minutes=1)

    expected = [
        (T0 + timedelta(minutes=1), T0 + timedelta(minutes=6)),  # second failure: +5 min
        (T0 + timedelta(minutes=6), T0 + timedelta(minutes=36)),  # third: +30 min
        (T0 + timedelta(minutes=36), T0 + timedelta(minutes=36, hours=6)),  # fourth: +6 h
    ]
    for run_at, next_at in expected:
        async with maker() as s:
            assert await WebhookService(s).run_due_retries(now=run_at) == 1
        row = await _load(maker, WebhookDelivery, did)
        assert row.status == "retrying"
        assert _utc(row.next_retry_at) == next_at

    async with maker() as s:  # the fifth send is the last
        await WebhookService(s).run_due_retries(now=T0 + timedelta(minutes=36, hours=6))
    row = await _load(maker, WebhookDelivery, did)
    assert (row.status, row.attempt, row.next_retry_at) == ("dead", 5, None)
    assert len(net.calls) == 5
    # every send is signed afresh but names the same delivery
    assert {c[2][ws.DELIVERY_HEADER] for c in net.calls} == {str(did)}


async def test_not_due_yet_is_not_sent(maker, monkeypatch):
    net = FakeNet(monkeypatch, 500)
    uid = await _user(maker)
    hook_id = await _hook(maker, uid)
    _freeze(monkeypatch, T0)
    async with maker() as s:
        await WebhookService(s).deliver_to(await s.get(WebhookEndpoint, hook_id), "a.b", {})
    async with maker() as s:
        assert await WebhookService(s).run_due_retries(now=T0 + timedelta(seconds=59)) == 0
    assert len(net.calls) == 1


async def test_recovery_marks_delivered_and_resets_the_failure_count(maker, monkeypatch):
    FakeNet(monkeypatch, 500, 200)
    uid = await _user(maker)
    hook_id = await _hook(maker, uid, failure_count=3)
    _freeze(monkeypatch, T0)
    async with maker() as s:
        d = await WebhookService(s).deliver_to(await s.get(WebhookEndpoint, hook_id), "a.b", {})
        did = d.id
    async with maker() as s:
        await WebhookService(s).run_due_retries(now=T0 + timedelta(minutes=1))
    row = await _load(maker, WebhookDelivery, did)
    assert (row.status, row.attempt, row.next_retry_at) == ("delivered", 2, None)
    assert (await _load(maker, WebhookEndpoint, hook_id)).failure_count == 0


@pytest.mark.parametrize("code", [400, 401, 403, 404, 410, 422])
async def test_client_errors_are_dead_at_once(maker, monkeypatch, code):
    net = FakeNet(monkeypatch, code)
    uid = await _user(maker)
    hook_id = await _hook(maker, uid)
    async with maker() as s:
        d = await WebhookService(s).deliver_to(await s.get(WebhookEndpoint, hook_id), "a.b", {})
    assert (d.status, d.attempt, d.next_retry_at, d.status_code) == ("dead", 1, None, code)
    assert len(net.calls) == 1


@pytest.mark.parametrize("code", [408, 429, 500])
async def test_408_429_and_5xx_retry(maker, monkeypatch, code):
    FakeNet(monkeypatch, code)
    uid = await _user(maker)
    hook_id = await _hook(maker, uid)
    async with maker() as s:
        d = await WebhookService(s).deliver_to(await s.get(WebhookEndpoint, hook_id), "a.b", {})
    assert d.status == "retrying"
    assert d.next_retry_at is not None


async def test_network_error_retries_and_keeps_the_reason(maker, monkeypatch):
    FakeNet(monkeypatch, TimeoutError("read timed out"))
    uid = await _user(maker)
    hook_id = await _hook(maker, uid)
    async with maker() as s:
        d = await WebhookService(s).deliver_to(await s.get(WebhookEndpoint, hook_id), "a.b", {})
    assert d.status == "retrying"
    assert "TimeoutError" in d.last_error


async def test_endpoint_is_switched_off_after_ten_dead_deliveries(maker, monkeypatch):
    FakeNet(monkeypatch, *([410] * 10))
    uid = await _user(maker)
    hook_id = await _hook(maker, uid)
    for _ in range(10):
        async with maker() as s:
            await WebhookService(s).deliver_to(await s.get(WebhookEndpoint, hook_id), "a.b", {})
    hook = await _load(maker, WebhookEndpoint, hook_id)
    assert (hook.failure_count, hook.is_active) == (10, False)


async def test_retrying_deliveries_do_not_count_toward_switching_off(maker, monkeypatch):
    FakeNet(monkeypatch, *([500] * 12))
    uid = await _user(maker)
    hook_id = await _hook(maker, uid)
    for _ in range(12):
        async with maker() as s:
            await WebhookService(s).deliver_to(await s.get(WebhookEndpoint, hook_id), "a.b", {})
    hook = await _load(maker, WebhookEndpoint, hook_id)
    assert (hook.failure_count, hook.is_active) == (0, True)


async def test_ping_is_sent_once_and_never_retried(maker, monkeypatch):
    net = FakeNet(monkeypatch, 500)
    uid = await _user(maker)
    hook_id = await _hook(maker, uid)
    async with maker() as s:
        d = await WebhookService(s).send_test(await s.get(WebhookEndpoint, hook_id))
    assert d.event_type == "ping"
    assert d.payload["event"] == "ping"
    assert (d.status, d.next_retry_at) == ("dead", None)
    assert net.calls[0][2][ws.EVENT_HEADER] == "ping"


# ── Worker bounds ──────────────────────────────────────────────────────────


async def test_worker_takes_a_bounded_batch_and_leases_what_it_took(maker, monkeypatch):
    net = FakeNet(monkeypatch)
    uid = await _user(maker)
    hook_id = await _hook(maker, uid)
    async with maker() as s:
        for _ in range(RETRY_BATCH + 5):
            s.add(
                WebhookDelivery(
                    webhook_id=hook_id,
                    event_type="a.b",
                    payload={},
                    status="retrying",
                    attempt=1,
                    next_retry_at=T0 - timedelta(minutes=1),
                )
            )
        await s.commit()
    async with maker() as s:
        assert await WebhookService(s).run_due_retries(now=T0) == RETRY_BATCH
    assert len(net.calls) == RETRY_BATCH
    async with maker() as s:
        assert await WebhookService(s).run_due_retries(now=T0) == 5  # the rest, never the same 50 twice
    assert len(net.calls) == RETRY_BATCH + 5


async def test_worker_ends_deliveries_of_a_removed_or_disabled_endpoint(maker, monkeypatch):
    net = FakeNet(monkeypatch)
    uid = await _user(maker)
    hook_id = await _hook(maker, uid, is_active=False)
    async with maker() as s:
        d = WebhookDelivery(
            webhook_id=hook_id,
            event_type="a.b",
            payload={},
            status="retrying",
            attempt=1,
            next_retry_at=T0 - timedelta(minutes=1),
        )
        s.add(d)
        await s.commit()
        did = d.id
    async with maker() as s:
        await WebhookService(s).run_due_retries(now=T0)
    row = await _load(maker, WebhookDelivery, did)
    assert (row.status, row.next_retry_at) == ("dead", None)
    assert net.calls == []


# ── SSRF ───────────────────────────────────────────────────────────────────


async def test_dns_rebinding_to_loopback_is_blocked_at_send_time(maker, monkeypatch):
    calls: list = []

    async def _post(url, body, headers):
        calls.append(url)
        return 200, ""

    monkeypatch.setattr(svc_mod, "_post", _post)

    def fake_getaddrinfo(host, port, *a, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    uid = await _user(maker)
    hook_id = await _hook(maker, uid, url="https://rebind.example.com/hook")
    async with maker() as s:
        d = await WebhookService(s).deliver_to(await s.get(WebhookEndpoint, hook_id), "a.b", {})
    assert d.status == "dead"
    assert "refused address" in d.last_error
    assert calls == []


async def test_metadata_address_is_blocked_without_dns(maker, monkeypatch):
    async def _post(url, body, headers):
        raise AssertionError("must not be sent")

    monkeypatch.setattr(svc_mod, "_post", _post)
    uid = await _user(maker)
    hook_id = await _hook(maker, uid, url="https://169.254.169.254/latest")
    async with maker() as s:
        d = await WebhookService(s).deliver_to(await s.get(WebhookEndpoint, hook_id), "a.b", {})
    assert d.status == "dead"


# ── Redeliver ──────────────────────────────────────────────────────────────


async def test_redeliver_resets_to_pending_and_the_worker_sends_it(maker, monkeypatch):
    net = FakeNet(monkeypatch, 404, 200)
    uid = await _user(maker)
    hook_id = await _hook(maker, uid)
    async with maker() as s:
        d = await WebhookService(s).deliver_to(await s.get(WebhookEndpoint, hook_id), "a.b", {"k": 1})
        did = d.id
        assert d.status == "dead"
    async with maker() as s:
        out = await redeliver_webhook_delivery(did, str(uid), WebhookService(s), None)
        await s.commit()
        assert (out.status, out.attempt, out.last_error) == ("pending", 0, "")
    async with maker() as s:
        assert await WebhookService(s).run_due_retries(now=datetime.now(UTC) + timedelta(seconds=1)) == 1
    row = await _load(maker, WebhookDelivery, did)
    assert (row.status, row.attempt) == ("delivered", 1)
    assert net.calls[1][2][ws.DELIVERY_HEADER] == str(did)


async def test_redeliver_of_someone_elses_delivery_is_404(maker, monkeypatch):
    FakeNet(monkeypatch, 404)
    owner, stranger = await _user(maker), await _user(maker)
    hook_id = await _hook(maker, owner)
    async with maker() as s:
        d = await WebhookService(s).deliver_to(await s.get(WebhookEndpoint, hook_id), "a.b", {})
        did = d.id
    async with maker() as s:
        with pytest.raises(HTTPException) as exc:
            await redeliver_webhook_delivery(did, str(stranger), WebhookService(s), None)
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException):
            await redeliver_webhook_delivery(uuid.uuid4(), str(owner), WebhookService(s), None)


# ── Creating endpoints ─────────────────────────────────────────────────────


async def test_create_generates_a_strong_secret_when_none_is_given(maker):
    uid = await _user(maker)
    async with maker() as s:
        hook = await WebhookService(s).create_webhook({"name": "n", "url": URL, "events": ["*"]}, str(uid))
        assert len(hook.secret) >= 43  # token_urlsafe(32)
        given = await WebhookService(s).create_webhook(
            {"name": "m", "url": URL, "events": ["*"], "secret": "x" * 30}, str(uid)
        )
        assert given.secret == "x" * 30


async def test_twenty_endpoints_at_most_per_user(maker):
    uid, other = await _user(maker), await _user(maker)
    async with maker() as s:
        svc = WebhookService(s)
        for i in range(MAX_ENDPOINTS_PER_USER):
            await svc.create_webhook({"name": f"h{i}", "url": URL, "events": ["*"]}, str(uid))
        with pytest.raises(HTTPException) as exc:
            await svc.create_webhook({"name": "extra", "url": URL, "events": ["*"]}, str(uid))
        assert exc.value.status_code == 409
        await svc.create_webhook({"name": "theirs", "url": URL, "events": ["*"]}, str(other))


async def test_reenabling_a_switched_off_endpoint_resets_its_failure_count(maker):
    uid = await _user(maker)
    hid = await _hook(maker, uid, is_active=False, failure_count=10)
    async with maker() as s:
        svc = WebhookService(s)
        hook = await svc.get_webhook(hid)
        await svc.update_webhook(hook, {"is_active": True})
        await s.commit()
    hook = await _load(maker, WebhookEndpoint, hid)
    assert hook.is_active is True
    assert hook.failure_count == 0


# ── Schema rules (no database) ─────────────────────────────────────────────


def _body(**over):
    base = {"name": "n", "url": URL, "events": ["boq.position.created"]}
    base.update(over)
    return base


def test_https_is_required_unless_debug(monkeypatch):
    monkeypatch.setattr("app.config.get_settings", lambda: SimpleNamespace(app_debug=False))
    with pytest.raises(ValidationError) as exc:
        WebhookCreate(**_body(url="http://hooks.example.com/oe"))
    assert "https" in str(exc.value)
    monkeypatch.setattr("app.config.get_settings", lambda: SimpleNamespace(app_debug=True))
    assert WebhookCreate(**_body(url="http://hooks.example.com/oe")).url.startswith("http://")


@pytest.mark.parametrize(
    "url", ["https://127.0.0.1/x", "https://10.0.0.5/x", "https://169.254.169.254/x", "https://localhost/x"]
)
def test_private_targets_are_refused_at_write_time(url):
    with pytest.raises(ValidationError):
        WebhookCreate(**_body(url=url))


def test_secret_must_be_24_characters_when_given():
    with pytest.raises(ValidationError):
        WebhookCreate(**_body(secret="short"))
    with pytest.raises(ValidationError):
        WebhookUpdate(secret="x" * 23)
    assert WebhookCreate(**_body(secret="x" * 24)).secret == "x" * 24
    assert WebhookCreate(**_body(secret="")).secret is None


def test_events_must_come_from_the_catalogue():
    assert "boq.position.created" in event_catalogue.event_names()
    assert WebhookCreate(**_body(events=["*"])).events == ["*"]
    with pytest.raises(ValidationError) as exc:
        WebhookCreate(**_body(events=["boq.position.created", "made.up.event"]))
    assert "made.up.event" in str(exc.value)
    with pytest.raises(ValidationError):
        WebhookUpdate(events=["made.up.event"])
    assert WebhookUpdate(name="renamed").events is None


def test_catalogue_rows_carry_module_and_i18n_key():
    row = next(r for r in event_catalogue.catalogue() if r["name"] == "boq.position.created")
    assert row == {"name": "boq.position.created", "module": "boq", "i18n_key": "developer.event.boq.position.created"}


def test_unsafe_url_error_is_a_value_error():
    assert issubclass(UnsafeUrlError, ValueError)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
