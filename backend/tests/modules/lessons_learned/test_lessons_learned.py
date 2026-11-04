# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Lessons learned: matching, validation rules and router permission gates (no database)."""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://oe:oe@localhost:5432/openestimate")
os.environ.setdefault("DATABASE_SYNC_URL", "postgresql://oe:oe@localhost:5432/openestimate")

import pytest

from app.modules.lessons_learned.logic import code_related, seen_on
from app.modules.lessons_learned.router import router
from app.modules.lessons_learned.validators import RULE_IDS, evaluate

P1, P2, P3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def lesson(project, **kw):
    base = {
        "project_id": project,
        "title": "t",
        "trade": "",
        "cost_code": "",
        "risk_category": "",
        "impact": "medium",
        "status": "confirmed",
    }
    return SimpleNamespace(id=uuid.uuid4(), **{**base, **kw})


def test_cost_code_prefix_both_ways():
    assert code_related("331.10", "330") is False
    assert code_related("331.10", "331")
    assert code_related("331", "331.10")
    assert not code_related("", "330")
    assert not code_related("330", None)


def test_counts_distinct_projects_and_skips_own_and_drafts():
    pool = [
        lesson(P1, trade="Concrete"),
        lesson(P1, trade="concrete "),
        lesson(P2, trade="CONCRETE"),
        lesson(P3, trade="Concrete", status="draft"),
        lesson(P3, trade="Roofing"),
    ]
    res = seen_on(pool, trade="concrete", exclude_project_id=P2)
    assert res.projects == 1
    assert res.lessons == 2


def test_best_match_first_and_top_limited():
    pool = [
        lesson(P1, trade="Concrete", title="b"),
        lesson(P2, trade="Concrete", cost_code="331", title="a"),
    ]
    res = seen_on(pool, trade="Concrete", cost_code="331.10", top_n=1)
    assert res.projects == 2
    assert [le.title for le, _ in res.top] == ["a"]
    assert res.top[0][1] == ["trade", "cost_code"]


def test_untagged_query_matches_everything_tagged_query_only_matches():
    pool = [lesson(P1, trade="Concrete")]
    assert seen_on(pool).projects == 1
    assert seen_on(pool, trade="Roofing").projects == 0


@pytest.mark.asyncio
async def test_validation_rules():
    assert len(RULE_IDS) == 4
    bad = {rule.rule_id for rule in await evaluate({"title": " ", "status": "draft"})}
    assert bad == {
        "lessons_learned.title_required",
        "lessons_learned.has_tag",
        "lessons_learned.has_content",
    }
    ok = {"title": "x", "trade": "Concrete", "description": "d", "status": "draft"}
    assert await evaluate(ok) == []
    warn = await evaluate({**ok, "status": "confirmed"})
    assert [r.rule_id for r in warn] == ["lessons_learned.confirmed_has_recommendation"]


def _route(path, method):
    return next(
        (r for r in router.routes if getattr(r, "path", None) == path and method in getattr(r, "methods", set())),
        None,
    )


@pytest.mark.parametrize(
    ("path", "method", "perm"),
    [
        ("/", "GET", "lessons_learned.read"),
        ("/seen", "GET", "lessons_learned.read"),
        ("/", "POST", "lessons_learned.create"),
        ("/{lesson_id}", "PATCH", "lessons_learned.update"),
        ("/{lesson_id}/confirm", "POST", "lessons_learned.confirm"),
        ("/{lesson_id}", "DELETE", "lessons_learned.delete"),
    ],
)
def test_route_permissions(path, method, perm):
    route = _route(path, method)
    assert route is not None
    perms = {getattr(getattr(d, "dependency", None), "permission", None) for d in route.dependencies}
    assert perm in perms


@pytest.mark.asyncio
async def test_confirming_twice_keeps_first_confirmer():
    from types import SimpleNamespace

    from app.modules.lessons_learned.service import LessonService

    lesson = SimpleNamespace(
        id=uuid.uuid4(),
        title="t",
        description="d",
        recommendation="r",
        trade="roofing",
        cost_code="",
        risk_category="",
        status="confirmed",
        confirmed_by="first",
        confirmed_at=None,
        impact="low",
        project_id=uuid.uuid4(),
        created_at=None,
    )
    svc = LessonService(session=None)  # type: ignore[arg-type]
    await svc.confirm(lesson, "second")
    assert lesson.confirmed_by == "first"
