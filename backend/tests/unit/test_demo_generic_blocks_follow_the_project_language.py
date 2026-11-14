# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A German or French demo project reads its generic registers in that language, not in English.

The generic row generator and the hand-written rows of the Berlin and Paris demos used to carry English prose
(tasks, meetings, safety, punch list, site reports, ...). Their wording now comes from the locale tables in
``app.core.demo_locale_text``; English stays the default for every other language. These tests fail when a block
falls back to English for ``de`` or ``fr``, when the tables drift apart, or when a hospital-lyon name carries an
English gloss again.
"""

from __future__ import annotations

import ast
import re
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.core.demo_locale_text import GENERATED_TEXT, PHRASES, authority_text, generated_text, language_of, localise
from app.core.demo_projects import DEMO_TEMPLATES, _generate_module_data

_BASE = datetime(2026, 1, 15, tzinfo=UTC)

#: (demo id, language) pairs: the German and the French showcase project.
_PROJECTS = [("residential-berlin", "de"), ("school-paris", "fr")]

#: Words that mark English prose in a German or French sentence.
_ENGLISH = re.compile(r"\b(the|and|for|with|during|from|not|are|to|of|under|before|after)\b", re.IGNORECASE)

#: Entries whose German or French wording is deliberately the same as the English one.
_SAME_IN_ALL_LANGUAGES = {"punch_description", "requirement_source"}

_DEMO_PROJECTS_SOURCE = Path(__file__).resolve().parents[2] / "app" / "core" / "demo_projects.py"


def _generate(template: Any) -> dict[str, list[Any]]:
    return _generate_module_data(
        template, project_id=uuid.uuid4(), owner_id=uuid.uuid4(), demo_id=template.demo_id, base=_BASE
    )


def _prose(data: dict[str, list[Any]]) -> dict[str, list[str]]:
    """The prose fields of every generic block, in a stable order, so two languages compare position by position."""
    out: dict[str, list[str]] = {}

    def add(block: str, value: Any) -> None:
        if isinstance(value, str) and value:
            out.setdefault(block, []).append(value)

    for row in data["contacts"]:
        add("contacts", row["notes"])
    for row in data["tasks"]:
        add("tasks", row["title"])
        add("tasks", row["description"])
    for row in data["rfis"]:
        add("rfis", row["subject"])
        add("rfis", row["question"])
        add("rfis", row["official_response"])
    for row in data["meetings"]:
        add("meetings", row["title"])
        add("meetings", row["location"])
        add("meetings", row["minutes"])
        for item in row["agenda_items"]:
            add("meetings", item["topic"])
        for item in row["action_items"]:
            add("meetings", item["description"])
    for row in data["safety_incidents"]:
        for key in ("title", "location", "description", "root_cause"):
            add("safety_incidents", row[key])
        for item in row["corrective_actions"]:
            add("safety_incidents", item["description"])
    for row in data["safety_observations"]:
        for key in ("description", "location", "immediate_action", "corrective_action"):
            add("safety_observations", row[key])
    for row in data["inspections"]:
        for key in ("title", "description", "location"):
            add("inspections", row[key])
        for item in row["checklist_data"]:
            add("inspections", item["category"])
            add("inspections", item["question"])
    for row in data["invoices"]:
        add("invoices", row["notes"])
        for item in row["line_items"]:
            add("invoices", item["description"])
    for row in data["punchlist"]:
        for key in ("title", "resolution_notes"):
            add("punchlist", row[key])
    for row in data["field_reports"]:
        add("field_reports", row["work_performed"])
        add("field_reports", row["delays"])
        add("field_reports", row["workforce"][-1]["trade"])
        for item in row["equipment_on_site"]:
            add("field_reports", item)
    for row in data["ncrs"]:
        for key in ("title", "description", "root_cause", "corrective_action", "preventive_action"):
            add("ncrs", row[key])
    for row in data["correspondence"]:
        add("correspondence", row["subject"])
    for row in data["variations"]:
        add("variations", row["title"])
    for row in data["daily_diary"]:
        add("daily_diary", row["notes"])
    for row in data["compliance"]:
        for key in ("name", "issuer", "notes"):
            add("compliance", row[key])
    for row in data["procurement"]:
        add("procurement", row["notes_subject"])
        for item in row["items"]:
            add("procurement", item["description"])
    for row in data["contracts"]:
        add("contracts", row.get("title") or row.get("title_subject"))
    for row in data["transmittals"]:
        add("transmittals", row["subject"])
        add("transmittals", row["cover_note"])
        for item in row["items"]:
            add("transmittals", item["description"])
    for row in data["resources"]:
        if row["resource_type"] != "subcontractor":
            add("resources", row["name"])
    for row in data["requirements"]:
        add("requirements", row["name"])
        add("requirements", row["description"])
    for row in data["progress_plan"]:
        add("progress_plan", row["notes"])
    for row in data["progress"]:
        add("progress", row["notes"])
    for row in data["risks"]:
        add("risks", row[1])
        add("risks", row[2])
        add("risks", row[8])
    return out


def test_the_tables_carry_the_same_keys_in_every_language() -> None:
    assert set(GENERATED_TEXT["de"]) == set(GENERATED_TEXT["en"])
    assert set(GENERATED_TEXT["fr"]) == set(GENERATED_TEXT["en"])


@pytest.mark.parametrize("lang", ["de", "fr"])
def test_no_entry_of_a_table_is_left_in_english(lang: str) -> None:
    same = [
        k for k, v in GENERATED_TEXT[lang].items() if v == GENERATED_TEXT["en"][k] and k not in _SAME_IN_ALL_LANGUAGES
    ]
    assert not same, f"{lang} entries identical to English: {same}"
    english = [k for k, v in GENERATED_TEXT[lang].items() if _ENGLISH.search(v)]
    assert not english, f"{lang} entries with English words: {english}"


@pytest.mark.parametrize("lang", ["de", "fr"])
def test_every_entry_keeps_the_placeholders_of_its_english_original(lang: str) -> None:
    field = re.compile(r"\{(\w+)\}")
    broken = [
        k
        for k, v in GENERATED_TEXT[lang].items()
        if set(field.findall(v)) != set(field.findall(GENERATED_TEXT["en"][k]))
    ]
    assert not broken, f"{lang} placeholders differ from English in: {broken}"


@pytest.mark.parametrize(("demo_id", "lang"), _PROJECTS)
def test_every_generic_block_of_the_demo_is_worded_from_the_locale_table(demo_id: str, lang: str) -> None:
    template = DEMO_TEMPLATES[demo_id]
    assert language_of(template.locale) == lang
    local = _prose(_generate(template))
    english = _prose(_generate(replace(template, locale="en")))
    assert set(local) == set(english)
    # every block the generator hands over is covered, not only the ones listed here by hand
    assert len(local) >= 23
    for block, texts in local.items():
        assert len(texts) == len(english[block]), block
        same = [
            t
            for t, e in zip(texts, english[block], strict=True)
            # German-market variations are worded in German whatever the project language is
            if t == e and " " in t and not t.startswith("Nachtrag - ") and not _from_the_bill(t, template)
        ]
        assert not same, f"{demo_id} {block} falls back to English: {same[:3]}"
        words = [t for t in texts if _ENGLISH.search(t) and not _from_the_bill(t, template)]
        assert not words, f"{demo_id} {block} carries English words: {words[:3]}"


def _from_the_bill(text: str, template: Any) -> bool:
    """True when the sentence is the project's own data (a trade or item title), which no table translates."""
    names = {str(sec[1]) for sec in template.sections if len(sec) > 1}
    names |= {str(item[1]) for sec in template.sections for item in (sec[3] if len(sec) > 3 else [])}
    return text in names


def test_english_stays_the_default_for_other_languages() -> None:
    template = DEMO_TEMPLATES["warehouse-dubai"]
    assert language_of(template.locale) == "en"
    assert generated_text(template.locale, "task_0") == "Mobilise site and establish welfare facilities"
    assert generated_text("pt-BR", "task_0") == GENERATED_TEXT["en"]["task_0"]
    assert localise("en", {"a": ["Piling crew"]}) == {"a": ["Piling crew"]}


def test_localise_replaces_only_whole_known_sentences() -> None:
    row = {"note": "Piling crew", "other": ("Piling crew and more", 5, None), "list": ["Piling crew"]}
    out = localise("de", row)
    assert out["note"] == PHRASES["de"]["Piling crew"]
    assert out["other"] == ("Piling crew and more", 5, None)
    assert out["list"] == [PHRASES["de"]["Piling crew"]]
    assert row["note"] == "Piling crew"


def test_the_notified_authority_is_named_in_the_project_language() -> None:
    assert authority_text("de", "DE") == "Bauaufsichtsamt"
    assert authority_text("fr", "FR") == "la mairie"
    assert authority_text("en", "DE") is None


# ── hand-written rows of the Berlin and Paris demos ─────────────────────

_HAND_BLOCKS = {
    "_TASKS",
    "_RFIS",
    "_MEETINGS",
    "_SAFETY_INCIDENTS",
    "_OBSERVATIONS",
    "_INSPECTIONS",
    "_INVOICES",
    "_PUNCHLIST",
    "_FIELD_REPORTS",
    "_SUBMITTALS",
    "_NCRS",
    "_CORRESPONDENCE",
    "_CONTACTS",
}
#: Keys whose values are codes, names or numbers rather than prose.
_NOT_PROSE = {"company", "company_name", "name", "contact_type", "role", "status", "priority", "category", "type"}


def _hand_rows() -> dict[tuple[str, str], list[tuple[str, str]]]:
    """(block, demo id) -> every (key, string) the hand-written rows of that demo carry."""
    tree = ast.parse(_DEMO_PROJECTS_SOURCE.read_text(encoding="utf-8"))
    found: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for node in ast.walk(tree):
        is_block = (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id in _HAND_BLOCKS
            and isinstance(node.value, ast.Dict)
        )
        if not is_block:
            continue
        for key, value in zip(node.value.keys, node.value.values, strict=True):
            if not (isinstance(key, ast.Constant) and key.value in dict(_PROJECTS)):
                continue
            pairs = [
                (str(k.value), str(v.value))
                for d in ast.walk(value)
                if isinstance(d, ast.Dict)
                for k, v in zip(d.keys, d.values, strict=True)
                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant) and isinstance(v.value, str)
            ]
            found[(node.target.id, key.value)] = pairs
    return found


def test_the_hand_written_rows_of_berlin_and_paris_have_no_english_prose_left() -> None:
    langs = dict(_PROJECTS)
    rows = _hand_rows()
    assert {demo for _, demo in rows} == set(langs)
    leftovers: list[str] = []
    for (block, demo), pairs in rows.items():
        for key, text in pairs:
            if key in _NOT_PROSE or " " not in text:
                continue
            shown = localise(langs[demo], text)
            if _ENGLISH.search(shown):
                leftovers.append(f"{block}/{demo}/{key}: {shown[:70]}")
    assert not leftovers, leftovers


@pytest.mark.parametrize("lang", ["de", "fr"])
def test_the_phrase_table_translates_into_the_project_language(lang: str) -> None:
    table = PHRASES[lang]
    assert all(src != dst for src, dst in table.items())
    assert not [dst for dst in table.values() if _ENGLISH.search(dst)]


# ── hospital-lyon ───────────────────────────────────────────────────────


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    if isinstance(value, (list, tuple)):
        return [s for item in value for s in _strings(item)]
    return []


def test_hospital_lyon_names_carry_no_english_glosses() -> None:
    template = DEMO_TEMPLATES["hospital-lyon"]
    names = _strings(template.sections) + _strings(template.tender_packages) + [template.tender_name]
    # A trailing "(...)" is allowed for a legal form or a group a firm belongs to, never for a translation.
    gloss = [n for n in names if re.search(r"\([^()]*\)\s*$", n) and not re.search(r"\((Groupe |Ardevin )", n)]
    assert not gloss, gloss[:5]


# ── construction-control non-conformance reports ────────────────────────


@pytest.mark.parametrize("lang", ["de", "fr"])
def test_the_control_reports_cover_every_work_package_and_keep_their_placeholders(lang: str) -> None:
    from app.modules.construction_control.seed import _WORK_PACKAGES
    from app.modules.construction_control.seed_text import PACKAGE_TEXT, WORDING, control_text, package_text

    field = re.compile(r"\{(\w+)\}")
    assert set(WORDING[lang]) == set(WORDING["en"])
    for key, text in WORDING[lang].items():
        assert set(field.findall(text)) == set(field.findall(WORDING["en"][key])), key
        assert not _ENGLISH.search(text), key
    assert {p.key for p in _WORK_PACKAGES} == set(PACKAGE_TEXT[lang])
    for package in _WORK_PACKAGES:
        location, title, criterion, lab = package_text(
            lang,
            package.key,
            location=package.location,
            inspection_title=package.inspection_title,
            criterion_title=package.criterion.title,
            lab_title=package.lab.title if package.lab else "",
        )
        assert (location, title, criterion) != (package.location, package.inspection_title, package.criterion.title)
        assert bool(lab) == bool(package.lab), package.key
        assert not _ENGLISH.search(" ".join((location, title, criterion, lab))), package.key
    english = control_text("en", "failed_inspection", number="INS-1", title="x")
    assert english == "Failed inspection INS-1: x"
    assert control_text(lang, "failed_inspection", number="INS-1", title="x") != english
