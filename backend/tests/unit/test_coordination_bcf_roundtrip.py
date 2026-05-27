# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""BCF I/O round-trip test for the Coordination / Clash module.

Per CLAUDE.md §3: BCF is an allowed I/O format (XML over data, no
IfcOpenShell). This test suite verifies that:

1. The hand-rolled BCF codec (stdlib xml.etree + zipfile) can produce
   a valid .bcfzip archive from a set of clash/issue topics.
2. Parsing that same archive back yields the identical topics (same
   guid, title, description, status, assigned_to, comments).
3. The round-trip is lossless on the fields we own (diff is empty).
4. The codec handles both BCF 2.1 and BCF 3.0.
5. A BCF archive with German umlauts (ä, ö, ü, ß) and Cyrillic chars in
   topic titles / descriptions survives the round-trip without
   mojibake — this doubles as the encoding regression guard.
6. A clash-module end-to-end BCF round-trip: export clash results →
   re-import the .bcfzip → clash rows are patched (status / assignee /
   comments).

No DB required for tests 1-5; test 6 uses an in-process SQLite db.
No IfcOpenShell; stdlib only (zipfile, xml.etree).
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-bcf-rt-"))
_TMP_DB = _TMP_DIR / "bcf_roundtrip.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"


from app.modules.bcf.bcf_xml import (  # noqa: E402
    ParsedComment,
    ParsedTopic,
    build_bcfzip,
    parse_bcfzip,
)

# ── Fixture BCF archive helpers ────────────────────────────────────────────


def _make_topic(
    *,
    title: str = "Test clash",
    description: str | None = None,
    topic_status: str = "Open",
    assigned_to: str | None = None,
    comments: list | None = None,
    version: str = "2.1",
) -> ParsedTopic:
    topic_guid = str(uuid.uuid4())
    return ParsedTopic(
        guid=topic_guid,
        title=title,
        description=description,
        topic_type="Clash",
        topic_status=topic_status,
        priority="Critical",
        assigned_to=assigned_to,
        creation_date=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
        creation_author="tester@example.com",
        comments=comments or [],
    )


def _make_comment(text: str, author: str = "user@example.com") -> ParsedComment:
    return ParsedComment(
        guid=str(uuid.uuid4()),
        comment=text,
        author=author,
        date=datetime(2026, 1, 15, 11, 0, 0, tzinfo=UTC),
    )


def _build_and_parse(topics: list[ParsedTopic], version: str = "2.1") -> list[ParsedTopic]:
    """Build a bcfzip from topics, immediately parse it back."""
    raw = build_bcfzip(
        version=version,
        project_id=str(uuid.uuid4()),
        project_name="Test Project",
        topics=topics,
    )
    result = parse_bcfzip(raw)
    assert not result.has_errors, f"Parse errors: {result.issues}"
    return result.topics


# ── Test 1: Simple round-trip (BCF 2.1) ───────────────────────────────────


def test_bcf_21_simple_roundtrip():
    """A single BCF 2.1 topic survives parse → build → parse unchanged."""
    original = _make_topic(
        title="Wall/Pipe clash Level 2",
        description="Hard clash · Structural ↔ Mechanical",
        topic_status="Open",
        assigned_to="coordinator@example.com",
        comments=[
            _make_comment("Please fix before next run."),
        ],
        version="2.1",
    )
    parsed_topics = _build_and_parse([original], version="2.1")

    assert len(parsed_topics) == 1
    rt = parsed_topics[0]

    assert rt.guid == original.guid
    assert rt.title == original.title
    assert rt.description == original.description
    assert rt.topic_status.lower() == original.topic_status.lower()
    assert rt.assigned_to == original.assigned_to
    assert len(rt.comments) == len(original.comments)
    assert rt.comments[0].comment == original.comments[0].comment


# ── Test 2: BCF 3.0 round-trip ────────────────────────────────────────────


def test_bcf_30_simple_roundtrip():
    """A single BCF 3.0 topic survives the round-trip."""
    original = _make_topic(
        title="Structural/MEP clash",
        description="Hard clash · Structural ↔ MEP",
        topic_status="In Progress",
        assigned_to="bim@example.com",
        version="3.0",
    )
    parsed_topics = _build_and_parse([original], version="3.0")

    assert len(parsed_topics) == 1
    rt = parsed_topics[0]
    assert rt.guid == original.guid
    assert rt.title == original.title


# ── Test 3: Multi-topic archive ───────────────────────────────────────────


def test_bcf_multi_topic_roundtrip():
    """Five topics; all GUIDs present in parsed output, none duplicated."""
    originals = [_make_topic(title=f"Clash {i}", topic_status="Open") for i in range(5)]
    parsed = _build_and_parse(originals, version="2.1")

    original_guids = {t.guid for t in originals}
    parsed_guids = {t.guid for t in parsed}
    assert original_guids == parsed_guids, (
        f"Mismatched GUIDs after round-trip. "
        f"Missing: {original_guids - parsed_guids}, "
        f"Extra: {parsed_guids - original_guids}"
    )


# ── Test 4: German umlauts + Cyrillic round-trip (encoding regression) ────


def test_bcf_encoding_umlauts_and_cyrillic_roundtrip():
    """German and Cyrillic text survives the round-trip without mojibake.

    Regression guard for the #139 mojibake encoding bug. Both .bcfzip
    member files (markup.bcf) are UTF-8 via xml.etree; zipfile writes
    entry content as raw bytes. This test ensures neither step mangles
    non-ASCII characters.
    """
    german_text = "Kollision: Stahl-Träger ↔ Lüftungskanal (Ü-Bogen/Wärmeäußerer)"
    cyrillic_text = "Пересечение: несущая стена ↔ трубопровод — необходимо устранить до следующего запуска"
    mixed_desc = f"{german_text}\n{cyrillic_text}"

    original = _make_topic(
        title=german_text,
        description=mixed_desc,
        assigned_to="müller@bau-gmbh.de",
        comments=[
            _make_comment(
                "Bitte bis Donnerstag beheben — Dachgeschoß betroffen.",
                author="schmidt@ä.de",
            ),
            _make_comment(cyrillic_text, author="ivanov@строитель.рф"),
        ],
    )
    parsed_topics = _build_and_parse([original], version="2.1")

    assert len(parsed_topics) == 1
    rt = parsed_topics[0]

    # Title
    assert rt.title == german_text, f"Title mangled.\nExpected: {german_text!r}\nGot:      {rt.title!r}"
    # Description
    assert rt.description is not None
    assert german_text in rt.description, f"German text missing from description.\nGot: {rt.description!r}"
    assert cyrillic_text in rt.description, f"Cyrillic text missing from description.\nGot: {rt.description!r}"
    # Comments
    assert len(rt.comments) >= 1
    comment_texts = [c.comment for c in rt.comments]
    assert any("Dachgeschoß" in t for t in comment_texts), (
        f"'Dachgeschoß' missing from parsed comments: {comment_texts!r}"
    )
    assert any(cyrillic_text in t for t in comment_texts), f"Cyrillic comment text missing: {comment_texts!r}"
    # Assigned-to
    assert rt.assigned_to == "müller@bau-gmbh.de", f"Assigned-to mangled: {rt.assigned_to!r}"


# ── Test 5: Clash-description signature recovery ──────────────────────────


def test_bcf_clash_signature_recovery_from_description():
    """_signature_from_description recovers the canonical clash signature."""
    from app.modules.clash.service import _signature, _signature_from_description

    a_sid = "GUID-WALL-001"
    b_sid = "GUID-PIPE-002"
    clash_type = "hard"
    expected_sig = _signature(a_sid, b_sid, clash_type)

    # Build a description in the exact format export_bcf writes:
    desc = (
        f"Hard clash · Structural ↔ Mechanical\n"
        f"A: Wall A ({a_sid})\n"
        f"B: Pipe B ({b_sid})\n"
        f"Penetration: 0.05 m · Clearance gap: 0.0 m"
    )
    recovered = _signature_from_description(desc)
    assert recovered == expected_sig, f"Signature mismatch.\nExpected: {expected_sig!r}\nGot:      {recovered!r}"


def test_bcf_clearance_clash_signature_recovery():
    """_signature_from_description works for clearance clashes too."""
    from app.modules.clash.service import _signature, _signature_from_description

    a_sid = "ELEM-A"
    b_sid = "ELEM-B"
    clash_type = "clearance"
    expected_sig = _signature(a_sid, b_sid, clash_type)

    desc = (
        f"Clearance clash · MEP ↔ Structural\n"
        f"A: Duct-1 ({a_sid})\n"
        f"B: Beam-9 ({b_sid})\n"
        f"Penetration: 0.0 m · Clearance gap: 0.03 m"
    )
    recovered = _signature_from_description(desc)
    assert recovered == expected_sig, f"Clearance signature mismatch: expected {expected_sig!r}, got {recovered!r}"


def test_bcf_signature_recovery_fails_gracefully_on_garbage():
    """Malformed description returns empty string (no crash)."""
    from app.modules.clash.service import _signature_from_description

    assert _signature_from_description("") == ""
    assert _signature_from_description("Not a clash description") == ""
    assert _signature_from_description("Hard clash but no element lines") == ""


# ── Test 6: DB-backed round-trip via service ──────────────────────────────


from collections.abc import AsyncIterator  # noqa: E402

import pytest_asyncio  # noqa: E402


@pytest_asyncio.fixture(scope="module")
async def app_factory():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    from app.database import async_session_factory

    async with async_session_factory() as session:
        yield session


async def _seed_project_and_run(
    session,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed user + project + completed clash run. Returns (user_id, project_id, run_id)."""
    from app.modules.clash.models import ClashResult, ClashRun
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"bcf-rt-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="BCF Round-Trip Tester",
        role="editor",
    )
    session.add(user)
    await session.flush()
    project = Project(name="BCF Round-Trip Project", owner_id=user.id)
    session.add(project)
    await session.flush()

    run = ClashRun(
        project_id=project.id,
        name="BCF RT Run",
        model_ids=[],
        status="completed",
        created_by=str(user.id),
        summary={},
    )
    session.add(run)
    await session.flush()

    a_sid, b_sid = "stable-A", "stable-B"
    from app.modules.clash.service import _signature

    sig = _signature(a_sid, b_sid, "hard")
    result = ClashResult(
        run_id=run.id,
        a_element_id=uuid.uuid4(),
        b_element_id=uuid.uuid4(),
        a_stable_id=a_sid,
        b_stable_id=b_sid,
        a_name="Stahl-Träger ÄÖÜ",
        b_name="Lüftungskanal ß",
        a_discipline="Structural",
        b_discipline="Mechanical",
        a_model_id=uuid.uuid4(),
        b_model_id=uuid.uuid4(),
        clash_type="hard",
        penetration_m=0.07,
        distance_m=0.0,
        cx=1.0,
        cy=2.0,
        cz=3.0,
        status="new",
        severity="high",
        signature=sig,
    )
    session.add(result)
    await session.commit()
    await session.refresh(run)
    await session.refresh(result)
    return user.id, project.id, run.id


async def test_bcf_clash_import_patches_status_and_comment(app_factory, db_session):
    """Build a BCF archive for one clash result, re-import it.

    After import the clash row must reflect the BCF topic's status
    ('resolved') and the new comment from the BCF topic.
    """
    from sqlalchemy import select

    from app.modules.clash.models import ClashResult
    from app.modules.clash.service import ClashService

    _user_id, project_id, run_id = await _seed_project_and_run(db_session)

    # Retrieve the result row.
    stmt = select(ClashResult).where(ClashResult.run_id == run_id)
    result = (await db_session.execute(stmt)).scalar_one()

    a_sid = result.a_stable_id
    b_sid = result.b_stable_id

    # Build a minimal BCF archive that looks like what export_bcf would produce.
    desc = (
        f"Hard clash · {result.a_discipline} ↔ {result.b_discipline}\n"
        f"A: {result.a_name} ({a_sid})\n"
        f"B: {result.b_name} ({b_sid})\n"
        f"Penetration: {result.penetration_m} m · Clearance gap: 0.0 m"
    )
    topic = ParsedTopic(
        guid=str(uuid.uuid4()),
        title=f"Clash: {result.a_name} × {result.b_name}",
        description=desc,
        topic_type="Clash",
        topic_status="Resolved",  # BCF status we want to import
        assigned_to="koordinator@test.io",
        creation_date=datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC),
        creation_author="tester@test.io",
        comments=[
            ParsedComment(
                guid=str(uuid.uuid4()),
                comment="Fixed in revised model v2.",
                author="koordinator@test.io",
                date=datetime(2026, 5, 1, 10, 0, 0, tzinfo=UTC),
            )
        ],
    )

    raw_bcf = build_bcfzip(
        version="2.1",
        project_id=str(project_id),
        project_name="BCF RT Project",
        topics=[topic],
    )

    # Round-trip import via ClashService.
    svc = ClashService(db_session)
    matched, unmatched, errors = await svc.import_bcf(project_id, run_id, raw_bcf, actor="test-actor")

    assert errors == 0, f"BCF parse errors: {errors}"
    assert matched == 1, f"Expected 1 matched topic, got matched={matched} unmatched={unmatched}"
    assert unmatched == 0, f"Expected 0 unmatched, got {unmatched}"

    # Re-fetch and verify the row was patched.
    await db_session.refresh(result)
    assert result.status == "resolved", f"Status not patched: expected 'resolved', got {result.status!r}"
    assert result.assigned_to == "koordinator@test.io", f"assigned_to not patched: {result.assigned_to!r}"
    comment_texts = [c.get("text", "") for c in (result.comments or [])]
    assert any("Fixed in revised model" in t for t in comment_texts), f"BCF comment not imported: {comment_texts}"
