"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit + service tests for the Cases module.

Three layers:
  * Schema guards - no DB. The step target is an href in the reader, so the
    cases it must refuse are worth stating one by one.
  * Service layer against the shared PostgreSQL unit DB with per-test
    transaction isolation (same fixture style as ``test_assets_ops.py``).
  * Validation rules, which gate publishing a case to the team.

This file lives in ``tests/unit`` and is named explicitly in
``.github/workflows/ci-postgres.yml``. ``tests/integration`` runs in no
blocking lane, so a guard placed there would pass review and gate nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import get_args

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import load_translations, set_locale
from app.core.validation.engine import RuleCategory, Severity, rule_registry
from app.core.validation.messages import available_locales, is_key_present
from app.modules.cases import schemas, service
from app.modules.cases.models import CASE_CATEGORIES, CasePin, UserCase
from app.modules.cases.permissions import register_cases_permissions
from app.modules.cases.validators import (
    CASES_RULE_SET,
    VALIDATION_UNAVAILABLE,
    blocking_findings,
    evaluate_case,
    register_cases_rules,
)
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


def _step(step_id: str = "s1", **overrides) -> dict:
    body = {
        "id": step_id,
        "title": "Open the bill of quantities",
        "what": "Check the priced lines against the drawing revision.",
        "why": "A rate priced against a superseded drawing is the usual source of a claim.",
        "to": "/boq",
    }
    body.update(overrides)
    return body


def _case_body(**overrides) -> dict:
    body = {
        "title": "How we price a variation here",
        "description": "The route we take from a client instruction to a priced variation.",
        "category": "estimating",
        "est_minutes": 12,
        "steps": [_step("s1"), _step("s2", to="/changeorders", title="Raise the change order")],
    }
    body.update(overrides)
    return body


# ── Schema guards (no DB) ────────────────────────────────────────────────────


class TestStepTargetGuard:
    """``to`` becomes an href, so only an in-app path may pass."""

    @pytest.mark.parametrize(
        "target",
        [
            "javascript:alert(1)",
            "https://evil.example/x",
            "//evil.example/x",  # protocol-relative: "starts with /" is not enough
            "boq",  # no leading slash
            "/../admin",  # traversal out of the named screen
            "/a/../../b",
            "",
        ],
    )
    def test_rejects(self, target):
        with pytest.raises(ValueError):
            schemas.CaseStep(id="s", title="t", to=target)

    @pytest.mark.parametrize(
        "target",
        [
            "/boq",
            "/reports?tab=cost",
            "/projects/new",
            "/bim/viewer",
            "/field-time",
            # A route parameter. The shipped cases use these and the reader
            # substitutes the active project, so refusing the colon made
            # copying one of the product's own cases unsavable.
            "/projects/:projectId/files",
        ],
    )
    def test_accepts(self, target):
        assert schemas.CaseStep(id="s", title="t", to=target).to == target

    def test_a_colon_still_cannot_smuggle_a_scheme(self):
        # The colon is allowed inside the path, so state plainly that it does
        # not reopen the hole it was excluded for.
        for target in ("javascript:alert(1)", "data:text/html,x", "vbscript:x"):
            with pytest.raises(ValueError):
                schemas.CaseStep(id="s", title="t", to=target)


class TestCaseBodyGuards:
    def test_duplicate_step_ids_rejected(self):
        # Reader progress is keyed by step id, so duplicates would mark two
        # different steps complete at once.
        with pytest.raises(ValueError):
            schemas.CaseCreateRequest(**_case_body(steps=[_step("s1"), _step("s1", to="/reports")]))

    def test_unknown_category_rejected(self):
        with pytest.raises(ValueError):
            schemas.CaseCreateRequest(**_case_body(category="procurement"))

    def test_category_literal_matches_the_model_tuple(self):
        # The tuple is what the column is documented against and the Literal is
        # what the API rejects on. A drift lets a category through that the
        # reader has no group to show it in.
        assert set(get_args(schemas.CaseCategoryLiteral)) == set(CASE_CATEGORIES)

    def test_step_ceiling_enforced(self):
        with pytest.raises(ValueError):
            schemas.CaseCreateRequest(**_case_body(steps=[_step(f"s{i}") for i in range(schemas.MAX_STEPS + 1)]))


# ── Service layer (PostgreSQL) ───────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


async def _user(session: AsyncSession, email: str) -> User:
    user = User(email=email, hashed_password="x", full_name=email.split("@")[0])
    session.add(user)
    await session.flush()
    return user


async def _project(session: AsyncSession, owner: User, name: str = "Test project") -> Project:
    project = Project(name=name, owner_id=owner.id)
    session.add(project)
    await session.flush()
    return project


@pytest.mark.asyncio
class TestCaseVisibility:
    async def test_private_case_is_invisible_to_everyone_else(self, session):
        author = await _user(session, "author@example.com")
        other = await _user(session, "other@example.com")
        case = await service.create_case(session, owner_id=author.id, body=schemas.CaseCreateRequest(**_case_body()))

        assert await service.get_case(session, case_id=case.id, user_id=author.id) is not None
        # Reported as absent rather than forbidden: saying "forbidden" would
        # confirm the row exists to someone with no right to know it does.
        assert await service.get_case(session, case_id=case.id, user_id=other.id) is None

    async def test_shared_case_is_readable_but_not_writable(self, session):
        author = await _user(session, "author2@example.com")
        other = await _user(session, "other2@example.com")
        case = await service.create_case(
            session, owner_id=author.id, body=schemas.CaseCreateRequest(**_case_body(is_shared=True))
        )

        seen = await service.get_case(session, case_id=case.id, user_id=other.id)
        assert seen is not None
        assert service.can_edit(seen, author.id) is True
        assert service.can_edit(seen, other.id) is False

    async def test_list_returns_own_plus_shared(self, session):
        author = await _user(session, "author3@example.com")
        other = await _user(session, "other3@example.com")
        await service.create_case(
            session, owner_id=author.id, body=schemas.CaseCreateRequest(**_case_body(title="Mine private"))
        )
        await service.create_case(
            session,
            owner_id=author.id,
            body=schemas.CaseCreateRequest(**_case_body(title="Mine shared", is_shared=True)),
        )
        await service.create_case(
            session, owner_id=other.id, body=schemas.CaseCreateRequest(**_case_body(title="Theirs private"))
        )

        titles = {c.title for c in await service.list_cases(session, user_id=author.id)}
        assert "Mine private" in titles
        assert "Mine shared" in titles
        assert "Theirs private" not in titles

        mine_only = {c.title for c in await service.list_cases(session, user_id=author.id, mine_only=True)}
        assert mine_only == {"Mine private", "Mine shared"}


@pytest.mark.asyncio
class TestCaseLifecycle:
    async def test_steps_round_trip_through_the_json_column(self, session):
        author = await _user(session, "rt@example.com")
        case = await service.create_case(session, owner_id=author.id, body=schemas.CaseCreateRequest(**_case_body()))
        assert [s["to"] for s in case.steps] == ["/boq", "/changeorders"]
        assert case.steps[0]["why"].startswith("A rate priced")

    async def test_duplicate_starts_private_and_keeps_the_steps(self, session):
        author = await _user(session, "dup-a@example.com")
        other = await _user(session, "dup-b@example.com")
        source = await service.create_case(
            session, owner_id=author.id, body=schemas.CaseCreateRequest(**_case_body(is_shared=True))
        )

        copy = await service.duplicate_case(session, source=source, owner_id=other.id)
        # Copying somebody else's shared case starts a draft, not a second
        # publication, so the copy must not inherit is_shared.
        assert copy.is_shared is False
        assert copy.owner_id == other.id
        assert [s["to"] for s in copy.steps] == [s["to"] for s in source.steps]
        assert copy.id != source.id

    async def test_duplicate_does_not_alias_the_source_steps(self, session):
        author = await _user(session, "alias@example.com")
        source = await service.create_case(session, owner_id=author.id, body=schemas.CaseCreateRequest(**_case_body()))
        copy = await service.duplicate_case(session, source=source, owner_id=author.id)

        copy.steps[0]["title"] = "Edited in the copy"
        await session.flush()
        assert source.steps[0]["title"] == "Open the bill of quantities"

    async def test_deleting_a_case_removes_the_pins_that_point_at_it(self, session):
        author = await _user(session, "del@example.com")
        project = await _project(session, author)
        case = await service.create_case(session, owner_id=author.id, body=schemas.CaseCreateRequest(**_case_body()))
        await service.add_pin(
            session,
            user_id=author.id,
            project_id=project.id,
            case_source="custom",
            case_id=str(case.id),
        )
        # A pin at a shipped playbook must survive: it points somewhere else.
        await service.add_pin(
            session,
            user_id=author.id,
            project_id=project.id,
            case_source="builtin",
            case_id="build-a-5d-cost-loaded-model",
        )

        await service.delete_case(session, case=case)

        remaining = await service.list_pins(session, user_id=author.id, project_id=project.id)
        assert [(p.case_source, p.case_id) for p in remaining] == [("builtin", "build-a-5d-cost-loaded-model")]


@pytest.mark.asyncio
class TestPins:
    async def test_pinning_twice_does_not_produce_two_pins(self, session):
        user = await _user(session, "pin@example.com")
        project = await _project(session, user)

        first, created_first = await service.add_pin(
            session, user_id=user.id, project_id=project.id, case_source="builtin", case_id="set-up-a-new-project"
        )
        second, created_second = await service.add_pin(
            session, user_id=user.id, project_id=project.id, case_source="builtin", case_id="set-up-a-new-project"
        )

        assert created_first is True
        assert created_second is False
        assert first.id == second.id

    async def test_the_two_id_spaces_do_not_collide(self, session):
        # A shipped playbook slug and a case UUID share one column. Without the
        # source discriminator these would be one pin, not two.
        user = await _user(session, "spaces@example.com")
        project = await _project(session, user)
        shared_id = "overlapping-identifier"

        await service.add_pin(session, user_id=user.id, project_id=project.id, case_source="builtin", case_id=shared_id)
        await service.add_pin(session, user_id=user.id, project_id=project.id, case_source="custom", case_id=shared_id)

        pins = await service.list_pins(session, user_id=user.id, project_id=project.id)
        assert len(pins) == 2

    async def test_pins_are_per_user(self, session):
        one = await _user(session, "u1@example.com")
        two = await _user(session, "u2@example.com")
        project = await _project(session, one)

        await service.add_pin(session, user_id=one.id, project_id=project.id, case_source="builtin", case_id="x")
        assert len(await service.list_pins(session, user_id=one.id, project_id=project.id)) == 1
        assert await service.list_pins(session, user_id=two.id, project_id=project.id) == []

    async def test_unpin_is_idempotent(self, session):
        user = await _user(session, "unpin@example.com")
        project = await _project(session, user)
        await service.add_pin(session, user_id=user.id, project_id=project.id, case_source="builtin", case_id="y")

        assert (
            await service.remove_pin(
                session, user_id=user.id, project_id=project.id, case_source="builtin", case_id="y"
            )
            is True
        )
        assert (
            await service.remove_pin(
                session, user_id=user.id, project_id=project.id, case_source="builtin", case_id="y"
            )
            is False
        )

    async def test_reorder_ignores_a_pin_the_caller_does_not_own(self, session):
        mine = await _user(session, "mine@example.com")
        theirs = await _user(session, "theirs@example.com")
        project = await _project(session, mine)

        a, _ = await service.add_pin(
            session, user_id=mine.id, project_id=project.id, case_source="builtin", case_id="a"
        )
        b, _ = await service.add_pin(
            session, user_id=mine.id, project_id=project.id, case_source="builtin", case_id="b"
        )
        foreign, _ = await service.add_pin(
            session, user_id=theirs.id, project_id=project.id, case_source="builtin", case_id="c"
        )
        before = foreign.sort_order

        ordered = await service.reorder_pins(
            session,
            user_id=mine.id,
            project_id=project.id,
            pin_ids=[b.id, a.id, foreign.id],
        )

        assert [p.case_id for p in ordered] == ["b", "a"]
        assert foreign.sort_order == before

    async def test_reorder_gives_unmentioned_pins_distinct_places(self, session):
        # A pin the client did not list must not collapse to 0 and collide with
        # the first pin it did list.
        user = await _user(session, "tail@example.com")
        project = await _project(session, user)
        await service.add_pin(session, user_id=user.id, project_id=project.id, case_source="builtin", case_id="a")
        await service.add_pin(session, user_id=user.id, project_id=project.id, case_source="builtin", case_id="b")
        c, _ = await service.add_pin(
            session, user_id=user.id, project_id=project.id, case_source="builtin", case_id="c"
        )

        ordered = await service.reorder_pins(session, user_id=user.id, project_id=project.id, pin_ids=[c.id])

        places = [p.sort_order for p in ordered]
        assert places == sorted(places)
        assert len(set(places)) == 3
        assert ordered[0].case_id == "c"


# ── Validation rules ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCaseValidation:
    @staticmethod
    def _ids(findings) -> set[str]:
        return {f.rule_id for f in findings}

    async def test_empty_case_blocks_publishing(self):
        register_cases_rules()
        findings = await evaluate_case(_case_body(steps=[], description=""))
        assert "cases.has_steps" in self._ids(findings)
        # has_steps is an ERROR, so it must be in the set that stops sharing.
        assert "cases.has_steps" in {f.rule_id for f in blocking_findings(findings)}

    async def test_a_complete_case_has_nothing_blocking(self):
        register_cases_rules()
        findings = await evaluate_case(_case_body())
        assert blocking_findings(findings) == []

    async def test_repeated_screen_is_flagged_but_does_not_block(self):
        register_cases_rules()
        findings = await evaluate_case(_case_body(steps=[_step("s1"), _step("s2", title="Still the BOQ")]))
        assert "cases.distinct_screens" in self._ids(findings)
        assert blocking_findings(findings) == []

    async def test_missing_why_is_flagged_but_does_not_block(self):
        register_cases_rules()
        findings = await evaluate_case(_case_body(steps=[_step("s1", why="")]))
        assert "cases.step_purpose" in self._ids(findings)
        assert blocking_findings(findings) == []

    async def test_implausible_duration_is_flagged(self):
        register_cases_rules()
        findings = await evaluate_case(
            _case_body(est_minutes=1, steps=[_step(f"s{i}", to=f"/screen-{i}") for i in range(10)])
        )
        assert "cases.duration_plausible" in self._ids(findings)

    async def test_a_step_with_no_title_blocks_publishing(self):
        # The schema refuses this shape, so the rule exists for cases that
        # reached the database another way (an import, a seeded pack, an older
        # row). Build the dict directly rather than through the schema.
        register_cases_rules()
        findings = await evaluate_case(_case_body(steps=[{"id": "s1", "title": "", "to": "/boq"}]))
        assert "cases.step_titled" in {f.rule_id for f in blocking_findings(findings)}


class TestCaseMessageCoverage:
    """The rule set's messages must be reachable in every locale the bundle ships.

    ``rule_registry`` reads the registered rule classes, which is not the JSON
    catalog this test checks, so a rule dropped from the bundle is caught. The
    locale axis cannot lean on that same trick: ``available_locales()`` reads
    whatever ``*.json`` files exist on disk, which *is* the thing under test,
    so a whole locale file going missing would shrink both the loop and its
    own would-be failure together and this test would stay green. The
    required set below is a literal, independent of what is actually on disk,
    so that failure mode is closed.
    """

    #: The four locales ``cases`` rules are translated into, matching every
    #: rule set added since ``es.json`` shipped (2026-07-01): variations,
    #: subcontract, submittal, rfq, procurement, sheet_completeness, mexico.
    #: A literal, not ``available_locales()`` - see the class docstring.
    _REQUIRED_LOCALES = {"en", "de", "ru", "es"}

    def test_every_cases_rule_has_fail_and_suggestion_in_every_shipped_locale(self):
        register_cases_rules()
        rules = rule_registry.get_rules_for_sets([CASES_RULE_SET])
        assert rules, "no cases rules registered; the coverage check below would be vacuous"
        locales = available_locales()
        assert set(locales) >= self._REQUIRED_LOCALES, sorted(self._REQUIRED_LOCALES - set(locales))
        missing: list[str] = []
        for rule in rules:
            for locale in self._REQUIRED_LOCALES:
                for suffix in ("fail", "suggestion"):
                    key = f"{rule.rule_id}.{suffix}"
                    if not is_key_present(key, locale):
                        missing.append(f"{locale}:{key}")
        assert missing == []

    async def test_a_finding_actually_changes_text_with_locale(self):
        """Coverage in the JSON is not enough - the rule has to read it."""
        register_cases_rules()
        empty_case = _case_body(steps=[], description="")
        english = await evaluate_case(empty_case, locale="en")
        german = await evaluate_case(empty_case, locale="de")
        en_message = next(f.message for f in english if f.rule_id == "cases.has_steps")
        de_message = next(f.message for f in german if f.rule_id == "cases.has_steps")
        assert en_message != de_message

    async def test_the_request_locale_is_used_when_the_caller_names_none(self):
        """The router never passes ``locale=`` explicitly; it relies on this default.

        Before this fix the metadata locale defaulted to an empty string, which
        the rules read as English no matter what the accept-language middleware
        had already resolved for the request.
        """
        register_cases_rules()
        # SUPPORTED_LOCALES gates set_locale(); idempotent if the app already
        # loaded it, but a bare unit test process never has on its own.
        load_translations()
        set_locale("de")
        try:
            findings = await evaluate_case(_case_body(steps=[], description=""))
        finally:
            set_locale("en")
        with_context_locale = next(f.message for f in findings if f.rule_id == "cases.has_steps")
        english = await evaluate_case(_case_body(steps=[], description=""), locale="en")
        en_message = next(f.message for f in english if f.rule_id == "cases.has_steps")
        assert with_context_locale != en_message


# ── Permissions ──────────────────────────────────────────────────────────────


class TestCasePermissions:
    """Every permission the router names has to exist in the registry.

    ``RequirePermission`` denies an unregistered key rather than waving it
    through, so a module that forgets its ``permissions.py`` ships endpoints
    only an admin can reach, and no test that calls them as an admin notices.
    """

    @staticmethod
    def _router_permissions() -> set[str]:
        from app.modules.cases.router import router

        found: set[str] = set()
        for route in router.routes:
            for dependency in getattr(route, "dependencies", []) or []:
                call = getattr(dependency, "dependency", None)
                key = getattr(call, "permission", None)
                if isinstance(key, str):
                    found.add(key)
        return found

    def test_every_permission_the_router_asks_for_is_registered(self):
        from app.core.permissions import permission_registry

        register_cases_permissions()
        asked = self._router_permissions()
        assert asked, "no route declared a permission; the guard would be vacuous"
        registered = set(permission_registry.list_all())
        assert asked <= registered, f"unregistered: {sorted(asked - registered)}"

    def test_a_viewer_can_read_and_an_editor_can_write(self):
        from app.core.permissions import Role, permission_registry

        register_cases_permissions()
        assert permission_registry.role_has_permission(Role.VIEWER, "cases.read") is True
        # A viewer curating a pinned set would be writing to the account.
        assert permission_registry.role_has_permission(Role.VIEWER, "cases.write") is False
        assert permission_registry.role_has_permission(Role.EDITOR, "cases.write") is True


@pytest.mark.asyncio
async def test_case_and_pin_tables_are_named_by_convention():
    assert UserCase.__tablename__ == "oe_cases_user_case"
    assert CasePin.__tablename__ == "oe_cases_pin"
    assert isinstance(uuid.uuid4(), uuid.UUID)


@pytest.mark.asyncio
async def test_a_case_whose_validation_engine_died_does_not_look_publishable(monkeypatch):
    """An engine failure must not read as a clean bill of health.

    ``evaluate_case`` is guarded so that a broken rule cannot stop somebody
    saving their work, which is a real requirement. The guard returned an
    empty list, and an empty list already meant "checked, nothing wrong". One
    value carrying both meanings is the defect: ``blocking_findings`` saw
    nothing to block on and the router shared the case, so a case nobody had
    been able to check went out to the team marked as validated.

    Validation is not optional in this product. Not being able to run it is a
    reason to withhold publication, never a reason to grant it.
    """
    from app.modules.cases import validators

    async def _die(**_kwargs):
        raise RuntimeError("rule registry exploded")

    monkeypatch.setattr(validators.validation_engine, "validate", _die)

    findings = await evaluate_case(_case_body(), case_id="c1")

    # The save itself must still work, so this call may not raise.
    assert [f.rule_id for f in findings] == [VALIDATION_UNAVAILABLE]
    assert [f.rule_id for f in blocking_findings(findings)] == [VALIDATION_UNAVAILABLE]
    # DIAGNOSTIC records that the infrastructure failed rather than the case.
    assert findings[0].category is RuleCategory.DIAGNOSTIC


@pytest.mark.asyncio
async def test_a_case_that_validates_clean_is_still_publishable():
    """The negative control: the fix must not make every case unpublishable.

    Without this, returning a blocking finding unconditionally would satisfy
    the test above while making it impossible to share any case at all.
    """
    register_cases_rules()
    findings = await evaluate_case(_case_body(), case_id="c2")
    assert VALIDATION_UNAVAILABLE not in {f.rule_id for f in findings}
    assert blocking_findings(findings) == []


@pytest.mark.asyncio
async def test_sharing_is_refused_while_validation_is_down_but_a_draft_still_saves(monkeypatch):
    """The two halves of the requirement, at the gate that enforces them.

    Saving privately must keep working, because a validation outage is not the
    author's fault and losing their work would be the worse failure. Sharing
    must not, because sharing is the claim that the case was checked.
    """
    from app.modules.cases import router as cases_router
    from app.modules.cases import validators

    async def _die(**_kwargs):
        raise RuntimeError("rule registry exploded")

    monkeypatch.setattr(validators.validation_engine, "validate", _die)

    # A private draft saves: no exception, and the finding is reported back.
    draft = schemas.CaseCreateRequest(**_case_body(is_shared=False))
    findings = await cases_router._validated(draft)
    assert [f.rule_id for f in findings] == [VALIDATION_UNAVAILABLE]

    # Sharing the same case is refused rather than granted.
    shared = schemas.CaseCreateRequest(**_case_body(is_shared=True))
    with pytest.raises(HTTPException) as exc:
        await cases_router._validated(shared)
    assert exc.value.status_code == 422
    assert exc.value.detail["findings"][0]["rule_id"] == VALIDATION_UNAVAILABLE


def _break_one_rule(monkeypatch, rule_id: str) -> None:
    """Make one registered cases rule raise, leaving the others running.

    This is the half of the failure the whole-engine tests above do not cover:
    the engine survives, catches the exception itself, and writes an
    ``is_engine_error`` row for that one rule.
    """

    async def _boom(_context):
        raise RuntimeError("this rule cannot read the case")

    crashed = next(rule for rule in rule_registry.get_rules_for_sets([CASES_RULE_SET]) if rule.rule_id == rule_id)
    monkeypatch.setattr(crashed, "validate", _boom)


@pytest.mark.asyncio
async def test_a_rule_that_crashed_reaches_the_reader_instead_of_vanishing(monkeypatch):
    """A check that could not run is the row most worth showing, not the least.

    ``evaluate_case`` used to end ``and not result.is_engine_error``. That is
    the right filter for a list that feeds a gate, and the wrong one here,
    because this one list is also everything the author is ever shown. A case
    where a rule crashed came back indistinguishable from a case where every
    rule ran and found nothing, and the check that failed was the one worth
    reading about.

    Nothing is stored on this path - findings are computed per save and travel
    in the response - so there is no row to read back from a column.
    """
    from app.modules.cases import router as cases_router

    register_cases_rules()
    _break_one_rule(monkeypatch, "cases.step_purpose")

    findings = await evaluate_case(_case_body(), case_id="c3")

    engine_errors = [f for f in findings if f.is_engine_error]
    assert [f.rule_id for f in engine_errors] == ["cases.step_purpose"]
    # Reported as infrastructure rather than as a verdict on the case: the
    # author is told a check did not run, and publishing is not held on it.
    assert engine_errors[0].category is RuleCategory.DIAGNOSTIC
    assert engine_errors[0].severity is Severity.INFO
    assert "could not run" in engine_errors[0].message
    assert blocking_findings(findings) == []
    # Passing rules are still dropped: widening the filter must not turn this
    # into "return everything the engine produced".
    assert all(not f.passed for f in findings)

    # The same silence has a second home one layer up, so assert on the
    # serialised payload. A field the response object holds but never emits
    # hides the row just as completely as dropping it here would.
    payload = [f.model_dump() for f in cases_router._to_findings(findings)]
    emitted = [row for row in payload if row.get("is_engine_error")]
    assert len(emitted) == 1
    assert emitted[0]["rule_id"] == "cases.step_purpose"
    # Not under the crashed rule's own key. Every locale translates that key
    # into the sentence for a check that ran and found something, so rendering
    # the crash there would read as a finding about the case.
    assert emitted[0]["key"] == "cases.validation.engine_error"


@pytest.mark.asyncio
async def test_a_crashed_rule_is_reported_without_making_every_case_unpublishable(monkeypatch):
    """The negative control for the fix above.

    Surfacing the row must not become a second way to block sharing. One rule
    crashing means almost everything was checked, which is not the same as the
    engine dying and nothing being checked at all - that case still blocks, two
    tests up. What the author gets here is the case shared and the row shown.
    """
    from app.modules.cases import router as cases_router

    register_cases_rules()
    _break_one_rule(monkeypatch, "cases.step_purpose")

    shared = schemas.CaseCreateRequest(**_case_body(is_shared=True))
    findings = await cases_router._validated(shared)

    assert [f.rule_id for f in findings if f.is_engine_error] == ["cases.step_purpose"]
    assert VALIDATION_UNAVAILABLE not in {f.rule_id for f in findings}
