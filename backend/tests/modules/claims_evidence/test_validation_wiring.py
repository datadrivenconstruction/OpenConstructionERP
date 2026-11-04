# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""The ``claims_evidence`` rule set runs where a pack or score is produced."""

from __future__ import annotations

import dataclasses
import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.claims_evidence.evidence_pack import EvidenceEntry, assemble_pack
from app.modules.claims_evidence.service import assemble_evidence, check_pack, check_score
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.variations.models import Notice
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


def _entry(ref: str, when: str | None = "2026-03-10T08:00:00+00:00") -> EvidenceEntry:
    return EvidenceEntry(
        ref_id=ref, source_module="notices", kind="notice", title="Notice", occurred_at=when, actor_id=None, summary=""
    )


async def test_valid_pack_from_real_rows_passes(session) -> None:
    user = User(email=f"ce-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="Ce", role="admin")
    session.add(user)
    await session.flush()
    proj = Project(name=f"Ce {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()
    session.add(Notice(project_id=proj.id, code="NOT-1", title="Early warning"))
    await session.flush()
    pack = await assemble_evidence(session, project_id=proj.id, subject_ref="CLAIM-1")
    assert pack.entry_count == 1
    assert await check_pack(pack) == []


async def test_inconsistent_pack_is_rejected_with_its_code() -> None:
    pack = assemble_pack("CLAIM-2", [_entry("a"), _entry("b")], basis="dispute")
    with pytest.raises(HTTPException) as exc:
        await check_pack(dataclasses.replace(pack, entry_count=9))
    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "claims_evidence_validation_failed"
    assert "claims_evidence.count_matches_entries" in {r["rule_id"] for r in exc.value.detail["results"]}


async def test_missing_basis_blocks() -> None:
    pack = assemble_pack("CLAIM-3", [_entry("a")], basis="dispute")
    with pytest.raises(HTTPException) as exc:
        await check_pack(dataclasses.replace(pack, basis=""))
    assert "claims_evidence.references_present" in {r["rule_id"] for r in exc.value.detail["results"]}


async def test_entry_outside_window_is_a_warning() -> None:
    pack = assemble_pack("CLAIM-4", [_entry("a"), _entry("b", "2026-03-20T08:00:00+00:00")], basis="dispute")
    narrowed = dataclasses.replace(pack, date_to="2026-03-15T00:00:00+00:00")
    warnings = await check_pack(narrowed)
    assert [w["rule_id"] for w in warnings] == ["claims_evidence.dates_ordered"]
    assert warnings[0]["severity"] == "warning"


class _Sub:
    def __init__(self, signal: str, weight: int, earned: int) -> None:
        self.signal, self.weight, self.earned = signal, weight, earned


class _Score:
    def __init__(self, score: int) -> None:
        self.score = score
        self.sub_scores = [_Sub("notice", 40, 30), _Sub("ack", 60, 20)]


async def test_valid_score_passes() -> None:
    assert await check_score("s1", _Score(50)) == []


async def test_score_that_does_not_add_up_blocks() -> None:
    with pytest.raises(HTTPException) as exc:
        await check_score("s1", _Score(80))
    assert exc.value.detail["error"] == "claims_evidence_validation_failed"
    assert "claims_evidence.score_in_range" in {r["rule_id"] for r in exc.value.detail["results"]}
