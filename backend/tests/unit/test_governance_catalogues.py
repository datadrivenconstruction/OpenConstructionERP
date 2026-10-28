"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Governance catalogues: shipped data loads, every cross-reference rule can fail.

Each rule has a broken minimal catalogue below that the loader must reject; a
loader missing that rule would accept it, so the test goes red.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.core import regional_packs
from app.modules.project_governance import catalogue as cat
from app.modules.requirements.lifecycle import PHASE_SPINE

_LOCALES_DIR = Path(__file__).resolve().parents[3] / "frontend" / "src" / "app" / "locales"


@pytest.fixture(autouse=True)
def _fresh_cache():
    cat.clear_catalogue_cache()
    yield
    cat.clear_catalogue_cache()


def _minimal() -> dict[str, Any]:
    p = "governance.catalogue.t."
    return {
        "id": "t",
        "version": 1,
        "name_key": p + "name",
        "description_key": p + "description",
        "source_url": None,
        "source_title": "test",
        "review_status": "verified",
        "phases": [
            {"code": "a", "order": 1, "name_key": p + "phase.a", "spine_keys": ["brief"]},
            {"code": "b", "order": 2, "name_key": p + "phase.b", "spine_keys": ["design"]},
            {"code": "c", "order": 3, "name_key": p + "phase.c", "spine_keys": ["construction", "handover"]},
        ],
        "gates": [
            {"code": "ab", "from_phase": "a", "to_phase": "b", "name_key": p + "gate.ab"},
            {"code": "bc", "from_phase": "b", "to_phase": "c", "name_key": p + "gate.bc"},
        ],
        "areas": [
            {"code": "x", "order": 1, "name_key": p + "area.x"},
            {"code": "y", "order": 2, "name_key": p + "area.y", "parent": "x"},
        ],
        "folders": [
            {"code": "f", "area": "x", "phase": "a", "name_key": p + "folder.x.f"},
            {"code": "f_child", "area": "x", "phase": "a", "parent": "f", "name_key": p + "folder.x.f_child"},
        ],
        "document_types": [
            {"code": "d", "area": "x", "name_key": p + "doc.d", "required_at_gates": ["ab"]},
        ],
        "readiness_criteria": [{"code": "r", "area": "x", "gate": "ab", "name_key": p + "criterion.r"}],
    }


def _write(tmp_path: Path, data: dict[str, Any], name: str = "t") -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_minimal_fixture_is_valid(tmp_path: Path) -> None:
    # The broken cases below differ from this one by a single edit.
    c = cat.load_catalogue_file(_write(tmp_path, _minimal()))
    assert c.phase("c").spine_key == "construction"


def _set(path: str, value: Any):
    def edit(d: dict[str, Any]) -> None:
        *head, last = path.split(".")
        node: Any = d
        for part in head:
            node = node[int(part)] if part.isdigit() else node[part]
        if last.isdigit():
            node[int(last)] = value
        else:
            node[last] = value

    return edit


BROKEN = [
    ("duplicate_code", _set("phases.1.code", "a")),
    ("duplicate_code", _set("areas.1.code", "x")),
    ("duplicate_code", lambda d: d["document_types"].append(dict(d["document_types"][0]))),
    ("duplicate_code", lambda d: d["gates"].append(dict(d["gates"][0]))),
    ("order_not_contiguous", _set("phases.2.order", 5)),
    ("unknown_spine_key", _set("phases.0.spine_keys", ["procurement"])),
    ("spine_keys_out_of_order", _set("phases.2.spine_keys", ["handover", "construction"])),
    ("gate_not_consecutive", _set("gates.1.from_phase", "a")),
    ("gate_unknown_phase", _set("gates.0.to_phase", "zz")),
    ("gate_missing", lambda d: d["gates"].pop()),
    ("document_unknown_area", _set("document_types.0.area", "zz")),
    ("document_unknown_gate", _set("document_types.0.required_at_gates", ["zz"])),
    ("area_unknown_parent", _set("areas.1.parent", "zz")),
    ("folder_unknown_phase", _set("folders.0.phase", "zz")),
    ("folder_unknown_parent", _set("folders.1.parent", "zz")),
    ("criterion_unknown_ref", _set("readiness_criteria.0.gate", "zz")),
    ("i18n_key_outside_namespace", _set("phases.0.name_key", "boq.title")),
    ("verified_without_source", _set("source_title", None)),
    ("schema", _set("phases.0.spine_keys", [])),
    ("schema", _set("phases.0.surprise", 1)),
]


@pytest.mark.parametrize(("rule", "edit"), BROKEN, ids=[f"{i}-{r}" for i, (r, _) in enumerate(BROKEN)])
def test_each_rule_rejects_its_broken_case(tmp_path: Path, rule: str, edit) -> None:
    data = copy.deepcopy(_minimal())
    edit(data)
    with pytest.raises(cat.InvalidCatalogueError) as info:
        cat.load_catalogue_file(_write(tmp_path, data))
    assert any(e.startswith(rule) for e in info.value.errors), info.value.errors


def test_areas_from_resolves_and_conflicts(tmp_path: Path) -> None:
    base = _minimal()
    _write(tmp_path, base, "t")
    child = copy.deepcopy(base)
    child["areas_from"] = "t"
    child_areas = child.pop("areas")
    loaded = cat.load_catalogue_file(_write(tmp_path, child, "t2"))
    assert [a.code for a in loaded.areas] == ["x", "y"]
    child["areas"] = child_areas
    with pytest.raises(cat.InvalidCatalogueError, match="areas_conflict"):
        cat.load_catalogue_file(_write(tmp_path, child, "t2"))


# ── shipped catalogues ──────────────────────────────────────────────────


@pytest.mark.parametrize("cid", cat.CATALOGUE_IDS)
def test_every_shipped_catalogue_loads(cid: str) -> None:
    c = cat.get_catalogue(cid)
    assert c.id == cid
    assert cat.validate_catalogue(c) == []
    assert all(s in PHASE_SPINE for p in c.phases for s in p.spine_keys)
    assert c.areas, "every catalogue needs areas, own or borrowed"
    for gate in c.gates:
        assert c.phase(gate.to_phase).order == c.phase(gate.from_phase).order + 1


def test_files_on_disk_match_the_listed_ids() -> None:
    on_disk = {p.stem for p in cat.CATALOGUE_DIR.glob("*.json") if p.stem != "schema"}
    assert on_disk == set(cat.CATALOGUE_IDS)


def test_elf_framework_shape() -> None:
    c = cat.get_catalogue("elf_module_framework")
    assert len(c.areas) == 11
    assert [p.code for p in c.phases] == ["development", "execution"]
    assert [g.code for g in c.gates] == ["development_to_execution"]
    for area in c.areas:
        docs = c.documents_for_area(area.code)
        assert len(docs) == 1 and docs[0].required_at_gates == ("development_to_execution",)
        assert c.folders_for(area.code, "development") and c.folders_for(area.code, "execution")
    assert len(c.documents_required_at("development_to_execution")) == 11


def test_aho_is_five_by_five() -> None:
    c = cat.get_catalogue("aho_heft9")
    assert [a.code for a in c.areas] == ["a", "b", "c", "d", "e"]
    assert len(c.phases) == 5


def test_statutory_phase_counts() -> None:
    assert [p.code for p in cat.get_catalogue("hoai_lph").phases] == [f"lph{i}" for i in range(1, 10)]
    assert [p.code for p in cat.get_catalogue("riba_2020").phases] == [f"stage{i}" for i in range(8)]
    assert len(cat.get_catalogue("aia_b101").phases) == 5


def test_neutral_follows_the_spine_one_to_one() -> None:
    assert tuple(p.spine_key for p in cat.get_catalogue("neutral").phases) == PHASE_SPINE


_NEUTRAL_AREAS = [
    "integration",
    "scope",
    "schedule",
    "cost_finance",
    "quality",
    "resources",
    "stakeholders",
    "risk",
    "procurement",
    "hse",
]


def test_neutral_has_ten_management_areas_each_with_gate_documents() -> None:
    c = cat.get_catalogue("neutral")
    assert [a.code for a in c.areas] == _NEUTRAL_AREAS
    assert c.review_status is cat.ReviewStatus.unconfirmed and c.source_url
    for area in c.areas:
        assert any(d.required_at_gates for d in c.documents_for_area(area.code)), area.code
    # every gate asks for at least one frame document, so no gate passes on readiness alone
    for gate in c.gates:
        assert c.documents_required_at(gate.code), gate.code


@pytest.mark.parametrize("cid", ["hoai_lph", "riba_2020", "aia_b101"])
def test_catalogues_borrowing_neutral_areas_get_all_ten(cid: str) -> None:
    assert [a.code for a in cat.get_catalogue(cid).areas] == _NEUTRAL_AREAS


def _locale_keys(name: str) -> set[str]:
    text = (_LOCALES_DIR / f"{name}.ts").read_text(encoding="utf-8")
    return set(re.findall(r'^\s*"(governance\.catalogue\.[^"]+)":', text, re.MULTILINE))


@pytest.mark.skipif(not _LOCALES_DIR.is_dir(), reason="frontend locales not beside the backend")
@pytest.mark.parametrize("locale", ["en", "de"])
def test_every_catalogue_i18n_key_exists_in_locale(locale: str) -> None:
    present = _locale_keys(locale)
    missing = sorted({k for c in cat.list_catalogues() for k in c.i18n_keys() if k not in present})
    assert missing == [], f"{len(missing)} keys missing in {locale}.ts, first: {missing[:5]}"


# ── lookup ──────────────────────────────────────────────────────────────


def test_versioned_lookup() -> None:
    assert cat.get_catalogue("hoai_lph", 1).version == 1
    assert cat.get_catalogue("hoai_lph").version == 1
    with pytest.raises(cat.UnknownCatalogueVersionError) as info:
        cat.get_catalogue("hoai_lph", 99)
    assert info.value.available == (1,)


def test_unknown_id_raises_typed_error() -> None:
    with pytest.raises(cat.UnknownCatalogueError) as info:
        cat.get_catalogue("no_such_model")
    assert info.value.catalogue_id == "no_such_model"
    assert isinstance(info.value, LookupError)


def test_helpers() -> None:
    c = cat.get_catalogue("hoai_lph")
    assert c.next_gate("lph8").to_phase == "lph9"
    assert c.next_gate("lph9") is None
    assert {d.code for d in c.documents_required_at("lph2_to_lph3")} == {"kostenschaetzung", "terminplan"}
    with pytest.raises(KeyError):
        c.phase("lph10")


# ── country default ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("country", "expected"),
    [
        ("DE", "hoai_lph"),
        ("de ", "hoai_lph"),
        ("GB", "riba_2020"),
        ("US", "aia_b101"),
        ("TR", "neutral"),
        ("AT", "neutral"),  # dach_pack claims AT, HOAI does not bind it
        ("CH", "neutral"),
        ("ZZ", "neutral"),
        (None, "neutral"),
        ("", "neutral"),
    ],
)
def test_country_default(country: str | None, expected: str) -> None:
    assert cat.default_catalogue_id_for_country(country, region="DACH") == expected


def _patch_packs(monkeypatch: pytest.MonkeyPatch, configs: tuple[dict[str, Any], ...]) -> None:
    monkeypatch.setattr(regional_packs, "pack_configs", lambda: configs)


def test_pack_declaration_wins_over_jurisdiction(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_packs(monkeypatch, ({"countries": ["DE"], "governance_catalogue": {"DE": "aho_heft9"}},))
    assert cat.default_catalogue_id_for_country("DE") == "aho_heft9"


def test_pack_declaration_is_keyed_by_exact_country(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_packs(monkeypatch, ({"countries": ["DE", "AT"], "governance_catalogue": {"DE": "aho_heft9"}},))
    assert cat.default_catalogue_id_for_country("AT") == "neutral"


@pytest.mark.parametrize(
    "configs",
    [
        # two national packs disagree
        (
            {"countries": ["DE"], "governance_catalogue": {"DE": "aho_heft9"}},
            {"countries": ["DE"], "governance_catalogue": {"DE": "elf_module_framework"}},
        ),
        # a state pack never votes
        ({"countries": ["DE"], "parent_pack": "x", "governance_catalogue": {"DE": "aho_heft9"}},),
        # an id that is not shipped is ignored
        ({"countries": ["DE"], "governance_catalogue": {"DE": "no_such_model"}},),
    ],
)
def test_pack_declarations_that_do_not_count(monkeypatch: pytest.MonkeyPatch, configs) -> None:
    _patch_packs(monkeypatch, configs)
    assert cat.default_catalogue_id_for_country("DE") == "hoai_lph"
