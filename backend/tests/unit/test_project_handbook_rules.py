# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Project handbook rules, catalogues, lifecycle, messages and wiring, without a database.

Each test names the rule and carries the case that would pass if the rule were missing: a required chapter
nobody approved, an approver who is the submitter, a catalogue chapter that reads a source nobody wrote.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.fsm import FSMError
from app.modules.project_handbook import rules
from app.modules.project_handbook.catalogue import (
    HANDBOOK_KIND,
    HandbookCatalogue,
    register_kinds,
    validate_handbook_model,
)
from app.modules.project_handbook.fsm import CHAPTER_FSM
from app.modules.project_handbook.messages import is_key_present, translate
from app.modules.project_handbook.sources import known_sources

_MODULE = Path(__file__).resolve().parents[2] / "app" / "modules" / "project_handbook"
_PACK = (
    Path(__file__).resolve().parents[3]
    / "packs"
    / "eleven-areas-framework"
    / "src"
    / "openconstructionerp_eleven_areas_framework"
)


def _chapter(**kw):
    base = {
        "code": "organisation",
        "status": "draft",
        "content": "Text",
        "owner_id": "u1",
        "required": False,
        "sources": [],
        "linked_rows": None,
        "approved_version": None,
        "submitted_at": None,
    }
    return {**base, **kw}


def _codes(chapters, **kw):
    return {f.code for f in rules.handbook_findings(chapters, **kw)}


def test_a_handbook_without_chapters_is_a_finding() -> None:
    assert _codes([]) == {"no_chapters"}


def test_a_chapter_without_owner_is_a_finding() -> None:
    assert "chapter_owner_missing" in _codes([_chapter(owner_id=None)])
    assert "chapter_owner_missing" not in _codes([_chapter()])


def test_an_empty_required_chapter_is_an_error_and_an_optional_one_a_warning() -> None:
    required = [f for f in rules.chapter_findings(_chapter(content=" ", required=True)) if f.code == "chapter_empty"]
    optional = [f for f in rules.chapter_findings(_chapter(content="")) if f.code == "chapter_empty"]
    assert [f.severity for f in required] == [rules.ERROR]
    assert [f.severity for f in optional] == [rules.WARNING]


def test_a_required_chapter_without_an_approved_version_is_open() -> None:
    assert "required_chapter_open" in _codes([_chapter(required=True)])
    assert "required_chapter_open" not in _codes([_chapter(required=True, status="approved", approved_version=1)])
    # A revision keeps the approved text in force, so the chapter is not open.
    assert "required_chapter_open" not in _codes([_chapter(required=True, status="revising", approved_version=1)])


def test_a_chapter_whose_sources_find_nothing_is_a_warning() -> None:
    assert "linked_source_empty" in _codes([_chapter(sources=["stakeholders"], linked_rows=0)])
    assert "linked_source_empty" not in _codes([_chapter(sources=["stakeholders"], linked_rows=3)])
    # Unknown (the sources were not asked) is not empty.
    assert "linked_source_empty" not in _codes([_chapter(sources=["stakeholders"], linked_rows=None)])


def test_a_chapter_waiting_longer_than_two_weeks_in_review_is_reported() -> None:
    now = datetime(2026, 10, 14, tzinfo=UTC)
    late = _chapter(status="in_review", submitted_at=now - timedelta(days=15))
    fresh = _chapter(status="in_review", submitted_at=now - timedelta(days=3))
    assert "review_overdue" in _codes([late], now=now)
    assert "review_overdue" not in _codes([fresh], now=now)


def test_submission_is_refused_for_a_missing_owner_and_for_no_text() -> None:
    blockers = rules.submission_blockers({"code": "x", "owner_id": None, "content": ""})
    assert {b.code for b in blockers} == {"chapter_owner_missing", "chapter_empty"}
    assert rules.submission_blockers({"code": "x", "owner_id": "u", "content": "Text"}) == []


@pytest.mark.parametrize(
    ("action", "status", "refused"),
    [
        ("edit", "draft", None),
        ("edit", "approved", None),
        ("edit", "in_review", "not_editable_in_state"),
        ("submit", "draft", None),
        ("submit", "in_review", "already_submitted"),
        ("submit", "approved", "already_submitted"),
        ("approve", "in_review", None),
        ("approve", "draft", "not_in_review"),
        ("return", "in_review", None),
        ("return", "approved", "not_in_review"),
    ],
)
def test_the_state_decides_which_action_is_allowed(action: str, status: str, refused: str | None) -> None:
    assert rules.action_refusal(action, status, can_edit=True, can_manage=True) == refused


def test_the_right_to_act_is_checked_before_the_state() -> None:
    assert rules.action_refusal("submit", "draft", can_edit=False) == "permission_required"
    assert (
        rules.action_refusal("approve", "in_review", can_edit=True, can_manage=False) == "approval_permission_required"
    )


def test_four_eyes_stops_the_submitter_from_approving_and_nobody_else() -> None:
    assert rules.approval_refusal(four_eyes=True, is_submitter=True) == rules.APPROVER_IS_SUBMITTER
    assert rules.approval_refusal(four_eyes=True, is_submitter=False) is None
    assert rules.approval_refusal(four_eyes=False, is_submitter=True) is None


def test_the_capability_flag_says_whether_the_action_applies_at_all() -> None:
    assert rules.capability(None, None) == {"allowed": True, "reason": None, "applies": True}
    assert rules.capability("not_in_review", "not_in_review")["applies"] is False
    assert rules.capability("approver_is_submitter", None)["applies"] is True


def test_the_lifecycle_has_one_way_to_approval_and_a_revision_loop() -> None:
    with pytest.raises(FSMError):
        CHAPTER_FSM.validate("draft", "approved")
    CHAPTER_FSM.validate("draft", "in_review")
    CHAPTER_FSM.validate("in_review", "approved")
    CHAPTER_FSM.validate("approved", "revising")
    CHAPTER_FSM.validate("revising", "in_review")
    CHAPTER_FSM.validate("in_review", "revising")


def _catalogue(path: Path) -> HandbookCatalogue:
    return HandbookCatalogue.model_validate(json.loads(path.read_text(encoding="utf-8")))


def test_the_shipped_catalogue_is_valid_and_has_fifteen_chapters_over_eleven_areas() -> None:
    cat = _catalogue(_MODULE / "catalogues" / "neutral.json")
    assert validate_handbook_model(cat, "shipped") == []
    assert len(cat.chapters) == 15
    assert len({c.area for c in cat.chapters}) == 11


def test_the_pack_catalogue_is_valid_and_says_its_text_in_german_and_english() -> None:
    cat = _catalogue(_PACK / "catalogues" / "handbook_model" / "eleven_areas_framework.json")
    assert validate_handbook_model(cat, "pack") == []
    assert all(c.labels and {"de", "en"} <= set(c.labels) for c in cat.chapters)
    assert {c.code for c in cat.chapters} == {
        c.code for c in _catalogue(_MODULE / "catalogues" / "neutral.json").chapters
    }


def test_a_chapter_that_reads_a_source_nobody_registered_is_refused() -> None:
    cat = _catalogue(_MODULE / "catalogues" / "neutral.json")
    broken = cat.model_copy(
        update={"chapters": (cat.chapters[0].model_copy(update={"sources": ("no_such_source",)}), *cat.chapters[1:])}
    )
    assert validate_handbook_model(broken, "shipped") == ["chapter_source_unknown: principles:no_such_source"]


def test_a_shipped_chapter_label_must_be_an_i18n_key() -> None:
    cat = _catalogue(_MODULE / "catalogues" / "neutral.json")
    broken = cat.model_copy(
        update={"chapters": (cat.chapters[0].model_copy(update={"name_key": "plain"}), *cat.chapters[1:])}
    )
    assert validate_handbook_model(broken, "shipped") == ["shipped_label_not_i18n_key: chapter:principles"]


def test_every_source_a_catalogue_names_is_registered() -> None:
    cat = _catalogue(_MODULE / "catalogues" / "neutral.json")
    used = {s for c in cat.chapters for s in c.sources}
    assert used <= known_sources()
    assert {
        "stakeholders",
        "staffing",
        "engineering_brief",
        "governance_gates",
        "governance_areas",
        "data_room",
    } <= used


def test_the_kind_is_registered_and_loads_the_shipped_catalogue() -> None:
    from app.modules.project_governance.catalogue_kinds import get_catalogue_kind

    register_kinds()
    ids = {c.id for c in get_catalogue_kind(HANDBOOK_KIND).shipped()}
    assert "neutral" in ids


@pytest.mark.parametrize("locale", ["en", "de"])
def test_every_catalogue_key_and_every_error_code_has_a_message(locale: str) -> None:
    cat = _catalogue(_MODULE / "catalogues" / "neutral.json")
    missing = [c.name_key for c in cat.chapters if not is_key_present(c.name_key, locale)]
    assert missing == []
    for code in (
        "handbook_missing",
        "approver_is_submitter",
        "submission_refused",
        "no_governance_model",
        "not_in_review",
    ):
        assert is_key_present(f"project_handbook.errors.{code}", locale), code
    for rule in ("chapters_present", "chapters_owned", "chapters_written", "required_chapters_approved"):
        assert is_key_present(f"project_handbook.rules.{rule}.fail", locale), rule
        assert is_key_present(f"project_handbook.rules.{rule}.suggestion", locale), rule


def test_the_german_messages_are_german_and_carry_their_placeholders() -> None:
    assert translate("project_handbook.chapter.organisation", locale="de") == "Projektorganisation"
    assert (
        "{ref}"
        in json.loads((_MODULE / "messages" / "de.json").read_text(encoding="utf-8"))[
            "project_handbook.rules.chapters_owned.fail"
        ]
    )
    assert translate("project_handbook.rules.chapters_owned.fail", locale="de", ref="organisation").endswith(
        "organisation hat keinen Verantwortlichen."
    )


def test_both_message_files_carry_the_same_keys_and_no_dash_punctuation() -> None:
    en = json.loads((_MODULE / "messages" / "en.json").read_text(encoding="utf-8"))
    de = json.loads((_MODULE / "messages" / "de.json").read_text(encoding="utf-8"))
    assert set(en) == set(de)
    for path in [*(_MODULE.glob("**/*.json")), *(_MODULE.glob("*.py"))]:
        text = path.read_text(encoding="utf-8")
        assert not {chr(0x2014), chr(0x2013)} & set(text), path.name


def test_the_demo_texts_are_german_and_name_the_project() -> None:
    from app.modules.project_handbook.seed import _PLAN, _PROFILES, _texts

    cat = _catalogue(_MODULE / "catalogues" / "neutral.json")
    for profile in _PROFILES.values():
        texts = _texts(profile)
        assert set(texts) == {c.code for c in cat.chapters}
        assert set(_PLAN) == set(texts)
        assert all(len(t) > 150 for t in texts.values())
        assert profile["name"] in texts["principles"]
        assert not {chr(0x2014), chr(0x2013)} & set("".join(texts.values()))
