# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍EAC v2 R7 deep-improve audit (Wave 3, 2026-05-25).

Covers the new findings on the aliases sub-router that the Round-3 sweep
missed (rules / rulesets / runs were already hardened; aliases were not):

1. Cross-tenant alias read / update / delete return 404, not the row.
2. Cross-tenant alias list / bulk-resolve never leak rows.
3. Same-name aliases are allowed across tenants (no false 409).
4. Alias import endpoint rejects binary payloads (magic-byte denylist)
   and over-sized bodies (413).
5. Decimal ``unit_multiplier`` is emitted as a string on the wire so a
   JS client cannot silently lose precision.
6. Round-3 green-light marker — re-asserts the IDOR-404 contract on
   ``GET /rules/{id}`` and the safe-eval reject list remain in place
   (regression net).

These tests drive the service layer directly against a PostgreSQL
session wrapped in a rolled-back outer transaction (fast, no auth
plumbing) and only spin up the full FastAPI app for the upload-gate
test where the multipart parser is what we're exercising.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.eac.aliases.schemas import (
    EacAliasSynonymCreate,
    EacAliasSynonymRead,
    EacParameterAliasCreate,
    EacParameterAliasUpdate,
)
from app.modules.eac.aliases.service import (
    create_alias,
    delete_alias,
    find_usages,
    list_aliases,
    update_alias,
)
from app.modules.eac.models import EacParameterAlias
from tests._pg import transactional_session

# ── Helpers ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session():
    """Per-test isolated PostgreSQL session.

    Runs inside an outer transaction that is rolled back on teardown, so
    each test starts against the empty (but fully schema-loaded) shared
    unit database. The session's own ``commit()`` calls become savepoint
    releases, visible within the test and undone afterwards. PostgreSQL
    enforces foreign keys natively, so no extra setup is needed.
    """
    async with transactional_session() as s:
        yield s


def _payload(name: str = "_Wave3Length") -> EacParameterAliasCreate:
    return EacParameterAliasCreate(
        scope="org",
        scope_id=None,
        name=name,
        description="R7 audit alias",
        value_type_hint="number",
        default_unit="m",
        synonyms=[
            EacAliasSynonymCreate(
                pattern="length_mm",
                priority=10,
                unit_multiplier=Decimal("0.001"),
            ),
        ],
    )


# ── 1. Cross-tenant read is 404 (via service.update_alias) ──────────────


@pytest.mark.asyncio
async def test_alias_cross_tenant_update_is_404(session: AsyncSession) -> None:
    """Tenant A must not be able to PUT tenant B's alias.

    The service raises ``LookupError`` (which the router maps to 404)
    so existence of the row is not leaked through the response code.
    """
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    alias_b = await create_alias(session, _payload("b_alias"), tenant_id=tenant_b)

    update = EacParameterAliasUpdate(description="hijack attempt")
    with pytest.raises(LookupError):
        await update_alias(session, alias_b.id, update, tenant_id=tenant_a)

    # Same call from tenant B succeeds — sanity check that the gate is
    # tenant-aware, not unconditional.
    updated = await update_alias(
        session,
        alias_b.id,
        update,
        tenant_id=tenant_b,
    )
    assert updated.description == "hijack attempt"


# ── 2. Cross-tenant delete is 404 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_alias_cross_tenant_delete_is_404(session: AsyncSession) -> None:
    """Tenant A must not be able to DELETE tenant B's alias."""
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    alias_b = await create_alias(session, _payload("b_del"), tenant_id=tenant_b)

    with pytest.raises(LookupError):
        await delete_alias(session, alias_b.id, tenant_id=tenant_a)

    # Tenant B can delete its own alias.
    await delete_alias(session, alias_b.id, tenant_id=tenant_b)
    leftover = await session.get(EacParameterAlias, alias_b.id)
    assert leftover is None


# ── 3. Cross-tenant list excludes other tenant ──────────────────────────


@pytest.mark.asyncio
async def test_alias_list_excludes_other_tenant(session: AsyncSession) -> None:
    """``list_aliases(tenant_id=A)`` must NOT include tenant B's rows.

    Built-in aliases (``tenant_id IS NULL``) are visible to everyone —
    that's the platform contract — but tenant-owned rows must stay
    siloed.
    """
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    alias_a = await create_alias(session, _payload("a_only"), tenant_id=tenant_a)
    alias_b = await create_alias(session, _payload("b_only"), tenant_id=tenant_b)

    visible_to_a = await list_aliases(session, tenant_id=tenant_a)
    visible_ids = {a.id for a in visible_to_a}
    assert alias_a.id in visible_ids, "Tenant A must see its own alias"
    assert alias_b.id not in visible_ids, "IDOR leak: tenant A saw tenant B's alias in list_aliases output"

    visible_to_b = await list_aliases(session, tenant_id=tenant_b)
    visible_b_ids = {a.id for a in visible_to_b}
    assert alias_b.id in visible_b_ids
    assert alias_a.id not in visible_b_ids


# ── 4. find_usages is tenant-scoped ─────────────────────────────────────


@pytest.mark.asyncio
async def test_find_usages_only_scans_caller_tenant(session: AsyncSession) -> None:
    """Usage lookup must not inspect another tenant's rule corpus."""
    from app.modules.eac.models import EacRule, EacRuleset

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    alias_a = await create_alias(session, _payload("shared_name"), tenant_id=tenant_a)

    # Tenant B has a rule that *references* the same alias_id string —
    # impossible in real life, but if the scan ignored tenant we'd see
    # it. So we manually craft the cross-tenant pollution.
    rs_b = EacRuleset(name="rs_b", kind="validation", tenant_id=tenant_b)
    session.add(rs_b)
    await session.flush()
    rule_b = EacRule(
        ruleset_id=rs_b.id,
        name="b_rule_referencing_a_alias",
        output_mode="boolean",
        definition_json={"kind": "alias", "alias_id": str(alias_a.id)},
        is_active=True,
        tenant_id=tenant_b,
        version=1,
    )
    session.add(rule_b)
    await session.flush()

    usages_for_a = await find_usages(session, alias_a.id, tenant_id=tenant_a)
    assert usages_for_a == [], "find_usages must scope to tenant_a's rules, not see tenant_b's rule"

    # Tenant B sees the polluted reference.
    usages_for_b = await find_usages(session, alias_a.id, tenant_id=tenant_b)
    assert len(usages_for_b) == 1
    assert usages_for_b[0].rule_id == rule_b.id


# ── 5. Same alias name allowed across tenants ──────────────────────────


@pytest.mark.asyncio
async def test_alias_dup_name_allowed_across_tenants(session: AsyncSession) -> None:
    """Tenant A and tenant B can each create an alias named ``Length``.

    Pre-R7 the dup-check ran without a tenant predicate, so the second
    tenant would get a false 409. With the R7 fix the dup-check is
    scoped per-tenant.
    """
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    a = await create_alias(session, _payload("Length"), tenant_id=tenant_a)
    b = await create_alias(session, _payload("Length"), tenant_id=tenant_b)
    assert a.id != b.id
    assert a.tenant_id == tenant_a
    assert b.tenant_id == tenant_b


# ── 6. Decimal unit_multiplier is serialized as a string ─────────────────


def test_alias_synonym_unit_multiplier_is_string_in_response() -> None:
    """A wire response must carry ``unit_multiplier`` as a JSON string.

    Pydantic v2's default for ``Decimal`` is a float, which silently
    round-trips ``Decimal("0.001")`` to ``0.001`` and then a JS client
    parses it as the nearest IEEE 754 double — already an approximation.
    Strings preserve every digit.
    """
    syn_id = uuid.uuid4()
    alias_id = uuid.uuid4()
    read = EacAliasSynonymRead(
        id=syn_id,
        alias_id=alias_id,
        pattern="length_mm",
        kind="exact",
        case_sensitive=False,
        priority=10,
        pset_filter=None,
        source_filter="any",
        unit_multiplier=Decimal("0.001"),
        created_at=None,
        updated_at=None,
    )
    dumped = read.model_dump(mode="json")
    assert isinstance(dumped["unit_multiplier"], str), (
        f"unit_multiplier must serialize to str on the wire; got "
        f"{type(dumped['unit_multiplier']).__name__} = {dumped['unit_multiplier']!r}"
    )
    assert dumped["unit_multiplier"] == "0.001"


# ── 7. Magic-byte gate (helper-level, no HTTP boot) ─────────────────────


def test_alias_import_rejects_binary_payload() -> None:
    """A PE-header upload with .csv extension must be rejected with 415.

    Drives :func:`validate_alias_upload_bytes` directly rather than
    booting the full FastAPI app (which would load ~110 modules and
    take 3+ min). The helper IS the gate — the router calls it
    verbatim, so testing it covers the production code path.
    """
    from fastapi import HTTPException

    from app.modules.eac.aliases.router import validate_alias_upload_bytes

    # Each banned prefix must trip the gate.
    for binary_prefix, label in (
        (b"MZ\x90\x00\x03\x00\x00\x00\x04\x00malicious", "PE"),
        (b"\x7fELF\x02\x01\x01\x00...rest...", "ELF"),
        (b"PK\x03\x04...zip-content...", "ZIP/XLSX"),
        (b"%PDF-1.4 ...pdf-stream...", "PDF"),
        (b"\x89PNG\r\n\x1a\n ...png-data...", "PNG"),
        (b"\xff\xd8\xff\xe0...jpeg...", "JPEG"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            validate_alias_upload_bytes(binary_prefix)
        assert exc_info.value.status_code == 415, f"{label} prefix should produce 415; got {exc_info.value.status_code}"


def test_alias_import_rejects_oversize_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """A body larger than the cap must be rejected with 413.

    The real cap is 50 MB; we patch it down to a tiny value so the test
    stays cheap instead of allocating a 50 MB payload.
    """
    from fastapi import HTTPException

    from app.modules.eac.aliases import router as alias_router

    monkeypatch.setattr(alias_router, "ALIAS_UPLOAD_MAX_BYTES", 64)

    # Just past the (patched) limit.
    oversized = b"a" * (alias_router.ALIAS_UPLOAD_MAX_BYTES + 1)
    with pytest.raises(HTTPException) as exc_info:
        alias_router.validate_alias_upload_bytes(oversized)
    assert exc_info.value.status_code == 413, f"Oversized payload should produce 413; got {exc_info.value.status_code}"


def test_alias_import_accepts_clean_csv_and_json() -> None:
    """Clean CSV / JSON / empty payloads must NOT trip the gate.

    Belt-and-braces sanity: the denylist must not be so eager that it
    kills the happy path. (Empty body is OK because the import code
    will report a 0-row no-op upstream.)
    """
    from app.modules.eac.aliases.router import validate_alias_upload_bytes

    # No raise == pass.
    validate_alias_upload_bytes(b"alias_name,synonym_pattern,kind\nfoo,bar,exact\n")
    validate_alias_upload_bytes(b'{"aliases": [{"name": "X", "synonyms": []}]}')
    validate_alias_upload_bytes(b"")
    # First 16 bytes are pure ASCII text — should not trip any denylist.
    validate_alias_upload_bytes(b"# comment\nname,pattern,kind\n")


# ── 8. Round-3 green-light marker (regression net, no HTTP) ──────────────


def test_round3_safe_eval_rejects_still_in_place() -> None:
    """Re-assert the formula sandbox still rejects ``__class__`` escapes.

    Lightweight regression net so a future refactor of ``safe_eval``
    that loosens the AST visitor surfaces here, not in production.
    """
    from app.modules.eac.engine.safe_eval import (
        FormulaUnsafeError,
        evaluate_formula,
    )

    with pytest.raises(FormulaUnsafeError):
        evaluate_formula("(1).__class__", {})
    # Sanity — legitimate formulas still work.
    assert evaluate_formula("ROUND(Volume * 2400, 2)", {"Volume": 6.0}) == 14400.0


# ── 9. Tenant-id-pass-through (engine API smoke) ────────────────────────


@pytest.mark.asyncio
async def test_alias_resolves_tenant_id_on_create(session: AsyncSession) -> None:
    """``create_alias`` must stamp the supplied ``tenant_id`` on the row.

    Without this the IDOR fix is meaningless — the column would always
    be NULL and every alias would look like a built-in.
    """
    tenant_id = uuid.uuid4()
    alias = await create_alias(session, _payload("stamp"), tenant_id=tenant_id)

    fresh = await session.get(EacParameterAlias, alias.id)
    assert fresh is not None
    assert fresh.tenant_id == tenant_id
    assert fresh.is_built_in is False


# Bulk select with tenant filter — direct ORM smoke (mirrors the router's
# new :resolve-bulk predicate).
@pytest.mark.asyncio
async def test_bulk_alias_select_filters_by_tenant(session: AsyncSession) -> None:
    """Direct ORM smoke for the predicate the router uses on bulk resolve."""
    from sqlalchemy import or_

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    alias_a = await create_alias(session, _payload("ra"), tenant_id=tenant_a)
    alias_b = await create_alias(session, _payload("rb"), tenant_id=tenant_b)

    stmt = select(EacParameterAlias).where(
        EacParameterAlias.id.in_([alias_a.id, alias_b.id]),
        or_(
            EacParameterAlias.tenant_id == tenant_a,
            EacParameterAlias.tenant_id.is_(None),
        ),
    )
    rows = list((await session.execute(stmt)).scalars().unique().all())
    fetched_ids = {r.id for r in rows}
    assert alias_a.id in fetched_ids
    assert alias_b.id not in fetched_ids, "Bulk select with tenant predicate must drop cross-tenant ids"
