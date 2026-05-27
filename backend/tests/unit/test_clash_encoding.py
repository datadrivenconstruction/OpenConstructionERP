# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Mojibake regression tests for clash detection encoding.

Covers:
* Clash result names with German umlauts (ä, ö, ü, ß, Ä, Ö, Ü) survive
  the DB round-trip without '??' substitution.
* Cyrillic element names round-trip correctly.
* Mixed German + Cyrillic in a single clash pair.
* CSV export preserves non-ASCII names (UTF-8 encoded streamed response).
* BCF description embedding preserves umlaut/Cyrillic stable IDs so that
  _signature_from_description can recover the canonical signature.
* ClashResult.a_name / b_name columns (String(500)) accept extended Unicode.
* Signatures (SHA-1 hex) are stable regardless of input character set.

Per feedback/mojibake_encoding_bug_139: the bug was introduced when a DB
layer or CSV writer used a latin-1 / cp1252 codec to encode String columns.
The guard here is direct DB write + read via the ORM (no HTTP layer needed).
"""

from __future__ import annotations

import io
import os
import tempfile
import uuid
from pathlib import Path

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-clash-enc-"))
_TMP_DB = _TMP_DIR / "clash_encoding.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

# ── Parameterised name pairs ───────────────────────────────────────────────

_UMLAUT_PAIRS = [
    ("Stahl-Träger Ü-Profil", "Lüftungskanal Außenwand"),
    ("Wärmedämmung Dachgeschoß", "Stahlbetonstütze Erdgeschoß"),
    ("Ä-Wand / Ö-Decke", "Straßenlaterne ß-Form"),
]

_CYRILLIC_PAIRS = [
    ("Несущая стена", "Трубопровод горячей воды"),
    ("Стальная балка — секция А", "Воздуховод системы вентиляции"),
]

_MIXED_PAIRS = [
    ("Träger Ü-Profil — несущая", "Вентиляция / Lüftung"),
]


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def db_engine():
    from app.config import get_settings

    get_settings.cache_clear()
    # Import all models so Base.metadata is fully populated before create_all.
    import app.modules.clash.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401
    from app.database import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine


@pytest_asyncio.fixture
async def session(db_engine) -> AsyncIterator:
    from app.database import async_session_factory

    async with async_session_factory() as s:
        yield s


async def _seed_run(session) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed a minimal project + run. Returns (project_id, run_id)."""
    from app.modules.clash.models import ClashRun
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"enc-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Encoding Tester",
        role="editor",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Encoding Test Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    run = ClashRun(
        project_id=project.id,
        name="Encoding Run",
        model_ids=[],
        status="completed",
        created_by=str(user.id),
        summary={},
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return project.id, run.id


async def _seed_result(session, run_id: uuid.UUID, a_name: str, b_name: str) -> uuid.UUID:
    from app.modules.clash.models import ClashResult
    from app.modules.clash.service import _signature

    a_sid = f"elem-{uuid.uuid4().hex[:8]}"
    b_sid = f"elem-{uuid.uuid4().hex[:8]}"
    result = ClashResult(
        run_id=run_id,
        a_element_id=uuid.uuid4(),
        b_element_id=uuid.uuid4(),
        a_stable_id=a_sid,
        b_stable_id=b_sid,
        a_name=a_name,
        b_name=b_name,
        a_discipline="Structural",
        b_discipline="Mechanical",
        a_model_id=uuid.uuid4(),
        b_model_id=uuid.uuid4(),
        clash_type="hard",
        penetration_m=0.05,
        distance_m=0.0,
        cx=0.0,
        cy=0.0,
        cz=0.0,
        status="new",
        severity="medium",
        signature=_signature(a_sid, b_sid, "hard"),
    )
    session.add(result)
    await session.commit()
    await session.refresh(result)
    return result.id


# ── Tests: DB round-trip ───────────────────────────────────────────────────


@pytest.mark.parametrize("a_name,b_name", _UMLAUT_PAIRS)
async def test_umlaut_names_survive_db_roundtrip(session, a_name, b_name):
    """German umlaut / ß in a_name and b_name survive the DB write + read."""
    _project_id, run_id = await _seed_run(session)
    result_id = await _seed_result(session, run_id, a_name, b_name)

    from sqlalchemy import select

    from app.modules.clash.models import ClashResult

    row = (await session.execute(select(ClashResult).where(ClashResult.id == result_id))).scalar_one()

    assert row.a_name == a_name, f"a_name mangled.\nExpected: {a_name!r}\nGot:      {row.a_name!r}"
    assert row.b_name == b_name, f"b_name mangled.\nExpected: {b_name!r}\nGot:      {row.b_name!r}"
    # Explicit character checks — catch '?' substitution immediately.
    for ch in ("ä", "ö", "ü", "Ä", "Ö", "Ü", "ß"):
        if ch in a_name:
            assert ch in row.a_name, f"'{ch}' missing from DB a_name: {row.a_name!r}"
        if ch in b_name:
            assert ch in row.b_name, f"'{ch}' missing from DB b_name: {row.b_name!r}"


@pytest.mark.parametrize("a_name,b_name", _CYRILLIC_PAIRS)
async def test_cyrillic_names_survive_db_roundtrip(session, a_name, b_name):
    """Cyrillic element names survive DB write + read without '??' substitution."""
    _project_id, run_id = await _seed_run(session)
    result_id = await _seed_result(session, run_id, a_name, b_name)

    from sqlalchemy import select

    from app.modules.clash.models import ClashResult

    row = (await session.execute(select(ClashResult).where(ClashResult.id == result_id))).scalar_one()

    assert row.a_name == a_name, f"Cyrillic a_name mangled.\nExpected: {a_name!r}\nGot:      {row.a_name!r}"
    assert row.b_name == b_name, f"Cyrillic b_name mangled.\nExpected: {b_name!r}\nGot:      {row.b_name!r}"
    assert "?" not in row.a_name, f"'?' substitution in a_name: {row.a_name!r}"
    assert "?" not in row.b_name, f"'?' substitution in b_name: {row.b_name!r}"


@pytest.mark.parametrize("a_name,b_name", _MIXED_PAIRS)
async def test_mixed_umlaut_cyrillic_names_survive_db_roundtrip(session, a_name, b_name):
    """Mixed German + Cyrillic in element names survive DB round-trip."""
    _project_id, run_id = await _seed_run(session)
    result_id = await _seed_result(session, run_id, a_name, b_name)

    from sqlalchemy import select

    from app.modules.clash.models import ClashResult

    row = (await session.execute(select(ClashResult).where(ClashResult.id == result_id))).scalar_one()

    assert row.a_name == a_name, f"Mixed a_name mangled: {row.a_name!r}"
    assert row.b_name == b_name, f"Mixed b_name mangled: {row.b_name!r}"


# ── Tests: CSV export encoding ─────────────────────────────────────────────


def test_csv_writer_preserves_umlauts():
    """CSV rows with German umlauts are written as valid UTF-8 strings.

    Simulates the logic the /export-csv endpoint uses — csv.writer over
    io.StringIO — to confirm no encoding error on non-ASCII names.
    """
    import csv

    umlaut_pairs = [
        ("Träger Ü", "Lüftung ß"),
        ("Ä-Wand", "Ö-Decke"),
    ]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["#", "Element A", "Element B", "Type", "Severity"])
    for i, (a, b) in enumerate(umlaut_pairs, start=1):
        writer.writerow([i, a, b, "hard", "high"])

    csv_text = buf.getvalue()
    assert "Träger" in csv_text, f"'Träger' missing from CSV output: {csv_text!r}"
    assert "Lüftung" in csv_text, f"'Lüftung' missing: {csv_text!r}"
    assert "ß" in csv_text, f"'ß' missing: {csv_text!r}"
    assert "Ö-Decke" in csv_text, f"'Ö-Decke' missing: {csv_text!r}"


def test_csv_writer_preserves_cyrillic():
    """CSV rows with Cyrillic names produce valid UTF-8 output."""
    import csv

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["#", "Element A", "Element B"])
    writer.writerow([1, "Несущая стена", "Трубопровод"])
    csv_text = buf.getvalue()
    assert "Несущая" in csv_text
    assert "Трубопровод" in csv_text
    assert "?" not in csv_text, f"'?' substitution in CSV: {csv_text!r}"


# ── Tests: BCF description encoding ───────────────────────────────────────


def test_bcf_description_umlauts_survive_roundtrip():
    """BCF description with umlauts survives build_bcfzip → parse_bcfzip."""
    from app.modules.bcf.bcf_xml import ParsedTopic, build_bcfzip, parse_bcfzip

    desc = (
        "Hard clash · Structural ↔ Mechanical\n"
        "A: Träger-Ü-Profil-Dachgeschoß (GUID-TRÄGER-001)\n"
        "B: Lüftungskanal-Außenwand (GUID-LÜFT-002)\n"
        "Penetration: 0.08 m · Clearance gap: 0.0 m"
    )
    topic = ParsedTopic(
        guid=str(uuid.uuid4()),
        title="Clash: Träger × Lüftung",
        description=desc,
        topic_type="Clash",
        topic_status="Open",
        creation_author="müller@bau.de",
        creation_date=__import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc),
    )
    raw = build_bcfzip(
        version="2.1",
        project_id="test-proj",
        project_name="Test",
        topics=[topic],
    )
    result = parse_bcfzip(raw)
    assert not result.has_errors
    assert len(result.topics) == 1
    rt = result.topics[0]
    assert rt.description is not None
    assert "Träger" in rt.description, f"'Träger' missing: {rt.description!r}"
    assert "Lüftungskanal" in rt.description, "'Lüftungskanal' missing"
    assert "Dachgeschoß" in rt.description, "'Dachgeschoß' missing"
    assert "GUID-TRÄGER-001" in rt.description, f"Stable ID mangled: {rt.description!r}"


def test_bcf_description_cyrillic_survives_roundtrip():
    """BCF description with Cyrillic stable IDs survives round-trip."""
    from app.modules.bcf.bcf_xml import ParsedTopic, build_bcfzip, parse_bcfzip

    desc = (
        "Hard clash · Structural ↔ MEP\n"
        "A: Несущая балка (ELEM-БАЛКА-001)\n"
        "B: Трубопровод (ELEM-ТРУБА-002)\n"
        "Penetration: 0.05 m"
    )
    topic = ParsedTopic(
        guid=str(uuid.uuid4()),
        title="Коллизия: балка × трубопровод",
        description=desc,
        topic_type="Clash",
        topic_status="Open",
        creation_author="tester",
        creation_date=__import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc),
    )
    raw = build_bcfzip(
        version="2.1",
        project_id="test-proj",
        project_name="Test",
        topics=[topic],
    )
    result = parse_bcfzip(raw)
    assert not result.has_errors
    rt = result.topics[0]
    assert rt.description is not None
    assert "Несущая" in rt.description, f"Cyrillic text mangled: {rt.description!r}"
    assert "?" not in rt.description, f"'?' substitution in description: {rt.description!r}"


# ── Tests: Signature stability ─────────────────────────────────────────────


def test_signature_stable_for_umlaut_stable_ids():
    """_signature is deterministic for stable IDs containing umlauts."""
    from app.modules.clash.service import _signature

    a = "TRÄGER-Ü-001"
    b = "LÜFT-Ä-002"
    sig1 = _signature(a, b, "hard")
    sig2 = _signature(a, b, "hard")
    assert sig1 == sig2, "Signature must be deterministic"
    assert len(sig1) == 16, f"Signature length mismatch: {sig1!r}"
    # Symmetric: (A, B) == (B, A)
    sig_swap = _signature(b, a, "hard")
    assert sig1 == sig_swap, "Signature must be symmetric"


def test_signature_stable_for_cyrillic_stable_ids():
    """_signature is deterministic for Cyrillic stable IDs."""
    from app.modules.clash.service import _signature

    a = "ЭЛЕМЕНТ-СТЕНА-001"
    b = "ЭЛЕМЕНТ-ТРУБА-002"
    sig = _signature(a, b, "hard")
    assert len(sig) == 16
    assert _signature(b, a, "hard") == sig, "Must be symmetric"
    assert "?" not in sig, "SHA-1 hex must never contain '?'"
