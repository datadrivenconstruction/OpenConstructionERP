"""Unit tests for the Webhook Leads module.

Covers the four things the issue (#147) explicitly asks for:

  * Security:
      - API key auth (valid + invalid, constant-time path exercised)
      - HMAC-SHA256 over the RAW body (valid + tampered body invalid)
      - JWT auth (valid + invalid)
      - IP allowlist block
      - per-source rate-limit → 429
  * Payload mapping: happy path + missing required field → 422
  * Lead creation: asserts a real CRM Lead row is created and
    ``created_lead_id`` is stored on the log
  * Audit: EVERY attempt (accepted AND every rejection) writes a
    WebhookLog row

A real temp-file SQLite engine is used (never the prod openestimate.db,
per ``feedback_test_isolation.md``) because the lead-creation assertion
needs the CRM ``Lead`` row to actually land in a DB.
"""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.crm.models import Lead
from app.modules.webhook_leads.schemas import (
    PayloadMappingCreate,
    WebhookSourceCreate,
)
from app.modules.webhook_leads.service import (
    WebhookLeadsService,
    extract_path,
    hash_secret,
    ip_allowed,
    map_payload_to_lead,
    source_rate_limiter,
    verify_api_key,
    verify_hmac_signature,
    verify_jwt,
)


def _register_models() -> None:
    import app.modules.crm.models  # noqa: F401
    import app.modules.webhook_leads.models  # noqa: F401


@pytest_asyncio.fixture
async def session():
    tmp_db = Path(tempfile.mkdtemp(prefix="oe-webhook-")) / "wl.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)
    _register_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    source_rate_limiter.reset()
    yield
    source_rate_limiter.reset()


async def _new_source(
    svc: WebhookLeadsService,
    *,
    auth_method: str = "api_key",
    ip_allowlist: list[str] | None = None,
    rate_limit: int = 60,
) -> tuple[uuid.UUID, str]:
    src, secret = await svc.create_source(
        WebhookSourceCreate(
            name="Marketing Form",
            slug=f"mkt-{uuid.uuid4().hex[:8]}",
            auth_method=auth_method,
            ip_allowlist=ip_allowlist or [],
            rate_limit_per_min=rate_limit,
        )
    )
    return src.id, secret


async def _add_default_mappings(svc: WebhookLeadsService, source_id: uuid.UUID) -> None:
    await svc.create_mapping(
        source_id,
        PayloadMappingCreate(
            target_field="contact_name",
            source_path="data.name",
            required=True,
        ),
    )
    await svc.create_mapping(
        source_id,
        PayloadMappingCreate(
            target_field="contact_email",
            source_path="data.email",
            transform="lower",
            required=False,
        ),
    )


# ── Pure helpers ──────────────────────────────────────────────────────────


def test_api_key_constant_time_compare():
    h = hash_secret("super-secret")
    assert verify_api_key("super-secret", h) is True
    assert verify_api_key("wrong", h) is False
    assert verify_api_key(None, h) is False
    assert verify_api_key("super-secret", "") is False


def test_hmac_over_raw_body():
    secret = "s3cr3t"
    body = b'{"data":{"name":"Acme"}}'
    import hashlib
    import hmac as _hmac

    good = _hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_hmac_signature(body, good, secret) is True
    # Prefixed form (GitHub style) accepted.
    assert verify_hmac_signature(body, f"sha256={good}", secret) is True
    # Signature computed over a re-serialised body must NOT validate the
    # original raw bytes — proves verification is over raw bytes.
    tampered = body.replace(b"Acme", b"Evil")
    assert verify_hmac_signature(tampered, good, secret) is False
    assert verify_hmac_signature(body, None, secret) is False


def test_jwt_verify():
    from jose import jwt

    secret = "jwt-secret"
    token = jwt.encode({"sub": "form"}, secret, algorithm="HS256")
    assert verify_jwt(token, secret) is True
    assert verify_jwt(token, "other-secret") is False
    assert verify_jwt("not-a-jwt", secret) is False
    assert verify_jwt(None, secret) is False


def test_ip_allowed():
    assert ip_allowed("1.2.3.4", []) is True  # empty = any
    assert ip_allowed("1.2.3.4", None) is True
    assert ip_allowed("1.2.3.4", ["1.2.3.4"]) is True
    assert ip_allowed("9.9.9.9", ["1.2.3.4"]) is False


def test_extract_path_and_mapping():
    payload = {"data": {"contact": {"email": "A@B.COM"}}, "items": [{"n": "x"}]}
    assert extract_path(payload, "data.contact.email") == "A@B.COM"
    assert extract_path(payload, "items.0.n") == "x"
    assert extract_path(payload, "missing.key") is None

    from types import SimpleNamespace

    mappings = [
        SimpleNamespace(
            target_field="contact_email",
            source_path="data.contact.email",
            transform="lower",
            required=True,
        ),
        SimpleNamespace(
            target_field="contact_name",
            source_path="data.contact.name",
            transform=None,
            required=True,
        ),
    ]
    fields, missing = map_payload_to_lead(payload, mappings)
    assert fields["contact_email"] == "a@b.com"
    assert "contact_name" in missing


# ── End-to-end ingestion (real DB) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_apikey_happy_path_creates_lead_and_log(session):
    svc = WebhookLeadsService(session)
    sid, secret = await _new_source(svc, auth_method="api_key")
    await _add_default_mappings(svc, sid)
    src = await svc.get_source(sid)

    body = json.dumps({"data": {"name": "Jane Doe", "email": "JANE@EXAMPLE.COM"}}).encode()
    log, lead_id = await svc.ingest(
        source_slug=src.slug,
        raw_body=body,
        parsed_payload=json.loads(body),
        headers={"x-api-key": secret},
        remote_ip="203.0.113.7",
    )

    assert log.status == "accepted"
    assert log.http_status == 201
    assert log.created_lead_id == lead_id

    lead = await session.get(Lead, lead_id)
    assert lead is not None
    assert lead.contact_name == "Jane Doe"
    assert lead.contact_email == "jane@example.com"  # lower transform applied
    assert lead.source == "web"  # default_lead_source


@pytest.mark.asyncio
async def test_invalid_apikey_rejected_and_logged(session):
    svc = WebhookLeadsService(session)
    sid, _secret = await _new_source(svc, auth_method="api_key")
    await _add_default_mappings(svc, sid)
    src = await svc.get_source(sid)

    with pytest.raises(HTTPException) as ei:
        await svc.ingest(
            source_slug=src.slug,
            raw_body=b"{}",
            parsed_payload={},
            headers={"x-api-key": "WRONG"},
            remote_ip="203.0.113.7",
        )
    assert ei.value.status_code == 401

    logs, total = await svc.log_repo.list_all()
    assert total == 1
    assert logs[0].status == "rejected"
    assert logs[0].http_status == 401
    # No lead created.
    cnt = (await session.execute(select(func.count()).select_from(Lead))).scalar_one()
    assert cnt == 0


@pytest.mark.asyncio
async def test_hmac_valid_and_tampered(session):
    import hashlib
    import hmac as _hmac

    svc = WebhookLeadsService(session)
    sid, secret = await _new_source(svc, auth_method="hmac")
    await _add_default_mappings(svc, sid)
    src = await svc.get_source(sid)

    body = json.dumps({"data": {"name": "HMAC Lead"}}).encode()
    sig = _hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    log, lead_id = await svc.ingest(
        source_slug=src.slug,
        raw_body=body,
        parsed_payload=json.loads(body),
        headers={"x-webhook-signature": sig},
        remote_ip="198.51.100.4",
        presented_secret_for_test=secret,
    )
    assert log.status == "accepted"
    assert (await session.get(Lead, lead_id)) is not None

    # Same signature, mutated raw body → reject (raw-body binding).
    with pytest.raises(HTTPException) as ei:
        await svc.ingest(
            source_slug=src.slug,
            raw_body=body.replace(b"HMAC Lead", b"Tampered!"),
            parsed_payload={"data": {"name": "Tampered!"}},
            headers={"x-webhook-signature": sig},
            remote_ip="198.51.100.4",
            presented_secret_for_test=secret,
        )
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_jwt_auth(session):
    from jose import jwt

    svc = WebhookLeadsService(session)
    sid, secret = await _new_source(svc, auth_method="jwt")
    await _add_default_mappings(svc, sid)
    src = await svc.get_source(sid)

    token = jwt.encode({"sub": "ext"}, secret, algorithm="HS256")
    body = json.dumps({"data": {"name": "JWT Lead"}}).encode()
    log, lead_id = await svc.ingest(
        source_slug=src.slug,
        raw_body=body,
        parsed_payload=json.loads(body),
        headers={"authorization": f"Bearer {token}"},
        remote_ip="203.0.113.9",
        presented_secret_for_test=secret,
    )
    assert log.status == "accepted"
    assert (await session.get(Lead, lead_id)) is not None

    with pytest.raises(HTTPException) as ei:
        await svc.ingest(
            source_slug=src.slug,
            raw_body=body,
            parsed_payload=json.loads(body),
            headers={"authorization": "Bearer not.a.jwt"},
            remote_ip="203.0.113.9",
            presented_secret_for_test=secret,
        )
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_ip_allowlist_block_logged(session):
    svc = WebhookLeadsService(session)
    sid, secret = await _new_source(svc, auth_method="api_key", ip_allowlist=["10.0.0.1"])
    await _add_default_mappings(svc, sid)
    src = await svc.get_source(sid)

    with pytest.raises(HTTPException) as ei:
        await svc.ingest(
            source_slug=src.slug,
            raw_body=b"{}",
            parsed_payload={},
            headers={"x-api-key": secret},
            remote_ip="8.8.8.8",
        )
    assert ei.value.status_code == 403
    logs, total = await svc.log_repo.list_all()
    assert total == 1
    assert logs[0].status == "rejected"
    assert logs[0].http_status == 403


@pytest.mark.asyncio
async def test_rate_limit_429_and_logged(session):
    svc = WebhookLeadsService(session)
    sid, secret = await _new_source(svc, auth_method="api_key", rate_limit=2)
    await _add_default_mappings(svc, sid)
    src = await svc.get_source(sid)
    body = json.dumps({"data": {"name": "RL"}}).encode()

    async def _post():
        return await svc.ingest(
            source_slug=src.slug,
            raw_body=body,
            parsed_payload=json.loads(body),
            headers={"x-api-key": secret},
            remote_ip="203.0.113.10",
        )

    await _post()
    await _post()
    with pytest.raises(HTTPException) as ei:
        await _post()
    assert ei.value.status_code == 429

    logs, total = await svc.log_repo.list_all()
    # 2 accepted + 1 rejected(429) = 3 audit rows.
    assert total == 3
    assert sum(1 for li in logs if li.status == "accepted") == 2
    assert sum(1 for li in logs if li.status == "rejected" and li.http_status == 429) == 1


@pytest.mark.asyncio
async def test_missing_required_mapped_field_422(session):
    svc = WebhookLeadsService(session)
    sid, secret = await _new_source(svc, auth_method="api_key")
    await _add_default_mappings(svc, sid)  # contact_name is required
    src = await svc.get_source(sid)

    body = json.dumps({"data": {"email": "only@email.com"}}).encode()
    with pytest.raises(HTTPException) as ei:
        await svc.ingest(
            source_slug=src.slug,
            raw_body=body,
            parsed_payload=json.loads(body),
            headers={"x-api-key": secret},
            remote_ip="203.0.113.11",
        )
    assert ei.value.status_code == 422
    assert "contact_name" in ei.value.detail

    logs, total = await svc.log_repo.list_all()
    assert total == 1
    assert logs[0].status == "rejected"
    assert logs[0].http_status == 422
    cnt = (await session.execute(select(func.count()).select_from(Lead))).scalar_one()
    assert cnt == 0


@pytest.mark.asyncio
async def test_unknown_slug_404_logged(session):
    svc = WebhookLeadsService(session)
    with pytest.raises(HTTPException) as ei:
        await svc.ingest(
            source_slug="does-not-exist",
            raw_body=b"{}",
            parsed_payload={},
            headers={},
            remote_ip="203.0.113.12",
        )
    assert ei.value.status_code == 404
    logs, total = await svc.log_repo.list_all()
    assert total == 1
    assert logs[0].source_id is None
    assert logs[0].source_slug == "does-not-exist"
    assert logs[0].status == "rejected"


@pytest.mark.asyncio
async def test_disabled_source_rejected(session):
    svc = WebhookLeadsService(session)
    sid, secret = await _new_source(svc, auth_method="api_key")
    await _add_default_mappings(svc, sid)
    src = await svc.get_source(sid)
    slug = src.slug  # capture before expire_all() in update_fields
    await svc.source_repo.update_fields(sid, is_active=False)

    with pytest.raises(HTTPException) as ei:
        await svc.ingest(
            source_slug=slug,
            raw_body=b"{}",
            parsed_payload={},
            headers={"x-api-key": secret},
            remote_ip="203.0.113.13",
        )
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_secret_rotation_invalidates_old_key(session):
    svc = WebhookLeadsService(session)
    sid, old_secret = await _new_source(svc, auth_method="api_key")
    await _add_default_mappings(svc, sid)
    src = await svc.get_source(sid)
    slug = src.slug  # capture before expire_all() in rotate_secret
    _src, new_secret = await svc.rotate_secret(sid)
    assert new_secret != old_secret

    with pytest.raises(HTTPException) as ei:
        await svc.ingest(
            source_slug=slug,
            raw_body=b'{"data":{"name":"x"}}',
            parsed_payload={"data": {"name": "x"}},
            headers={"x-api-key": old_secret},
            remote_ip="203.0.113.14",
        )
    assert ei.value.status_code == 401

    log, lead_id = await svc.ingest(
        source_slug=slug,
        raw_body=b'{"data":{"name":"x"}}',
        parsed_payload={"data": {"name": "x"}},
        headers={"x-api-key": new_secret},
        remote_ip="203.0.113.14",
    )
    assert log.status == "accepted"
    assert (await session.get(Lead, lead_id)) is not None
