"""The qms, closeout, site_prep, temporary_works and hse bulk demo rows follow the project language.

Every English sentence a seeder writes must have a German and a French wording, keep its placeholders and carry no
English words; the cleanup specs of qms and hse_advanced must still match the localised rows.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest

from app.modules.closeout import seed as closeout_seed
from app.modules.closeout.seed_text import PHRASES as CLOSEOUT_PHRASES
from app.modules.closeout.seed_text import closeout_text
from app.modules.hse_advanced import seed as hse_seed
from app.modules.hse_advanced.seed_text import BULK_PHRASES, BULK_WORDING, PERMIT_KIND, bulk_phrase, bulk_text
from app.modules.qms import seed as qms_seed
from app.modules.qms.seed_text import LANGUAGES, qms_text
from app.modules.qms.seed_text import PHRASES as QMS_PHRASES
from app.modules.site_prep import seed as site_prep_seed
from app.modules.site_prep.seed_text import PHRASES as SITE_PREP_PHRASES
from app.modules.site_prep.seed_text import site_prep_text
from app.modules.temporary_works import seed as tw_seed
from app.modules.temporary_works.seed_text import PHRASES as TW_PHRASES
from app.modules.temporary_works.seed_text import temporary_works_text

_ENGLISH = re.compile(
    r"\b(the|and|for|with|during|from|not|are|to|of|under|before|after|is|be|must|all|any)\b", re.IGNORECASE
)
_FIELD = re.compile(r"\{(\w+)\}")
_LANGS = ["de", "fr"]


def _flat(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _flat(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _flat(v)]
    return []


def _prose(texts: list[str]) -> list[str]:
    return [t for t in texts if " " in t or len(t) > 12]


_QMS_SOURCES = _flat(
    [
        qms_seed._PLAN["name"],
        [i[0] for i in qms_seed._ITP_ITEMS],
        qms_seed._ITP_ITEM_CRITERIA,
        qms_seed._INSPECTION_LOCATION,
        qms_seed._NCR_OPEN[:2],
        qms_seed._NCR_VARIATION[:2],
        qms_seed._NCR_VARIATION_ROOT_CAUSE,
        [p[0] for p in qms_seed._PUNCH_ITEMS],
        qms_seed._AUDIT["audit_scope"],
        [f[2] for f in qms_seed._AUDIT_FINDINGS],
    ]
)
_SITE_PREP_SOURCES = _flat(
    [[e["title"], e["description"], e["responsible_party"]] for e in site_prep_seed._CHECKLIST]
    + [site_prep_seed._BLOCKED_REASONS, site_prep_seed._NOT_APPLICABLE_REASONS]
)
_TW_SOURCES = _flat(
    [[s.title, s.description, s.location] for s in tw_seed._ITEM_SPECS]
    + [list(tw_seed._STATUS_NOTES.values()), list(tw_seed._PERMIT_CONDITIONS.values())]
)
_CLOSEOUT_SOURCES = _flat([[s[1] for s in closeout_seed._EXTRA_SLOTS], "Handover & Closeout Package"])

_CASES: list[tuple[str, dict[str, dict[str, str]], list[str], Callable[[str, str], str]]] = [
    ("qms", QMS_PHRASES, _QMS_SOURCES, qms_text),
    ("site_prep", SITE_PREP_PHRASES, _SITE_PREP_SOURCES, site_prep_text),
    ("temporary_works", TW_PHRASES, _TW_SOURCES, temporary_works_text),
    ("closeout", CLOSEOUT_PHRASES, _CLOSEOUT_SOURCES, closeout_text),
]


@pytest.mark.parametrize("lang", _LANGS)
@pytest.mark.parametrize(("module", "phrases", "sources", "translate"), _CASES, ids=[c[0] for c in _CASES])
def test_every_sentence_the_seeder_writes_has_a_translation(module, phrases, sources, translate, lang) -> None:
    missing = [s for s in _prose(sources) if translate(lang, s) == s]
    assert not missing, f"{module} {lang} has no wording for: {missing[:5]}"


@pytest.mark.parametrize("lang", _LANGS)
@pytest.mark.parametrize(("module", "phrases", "sources", "translate"), _CASES, ids=[c[0] for c in _CASES])
def test_the_translations_keep_placeholders_and_carry_no_english(module, phrases, sources, translate, lang) -> None:
    table = phrases[lang]
    broken = [k for k, v in table.items() if set(_FIELD.findall(v)) != set(_FIELD.findall(k))]
    assert not broken, f"{module} {lang} placeholders differ: {broken[:3]}"
    english = [v for v in table.values() if _ENGLISH.search(v)]
    assert not english, f"{module} {lang} still English: {english[:3]}"


@pytest.mark.parametrize(("module", "phrases", "sources", "translate"), _CASES, ids=[c[0] for c in _CASES])
def test_both_languages_translate_the_same_sentences(module, phrases, sources, translate) -> None:
    # block and zone labels are written the same in one language and not in the other
    def keys(lang: str) -> set[str]:
        return {k for k in phrases[lang] if not k.startswith(("Block ", "Zone "))}

    assert keys("de") == keys("fr")


def test_english_text_is_left_alone() -> None:
    for module, _phrases, sources, translate in _CASES:
        assert all(translate("en", s) == s for s in sources), module
        assert all(translate(None, s) == s for s in sources), module


@pytest.mark.parametrize("lang", _LANGS)
def test_the_hse_bulk_wording_is_complete_and_in_the_project_language(lang: str) -> None:
    assert set(BULK_WORDING[lang]) == set(BULK_WORDING["en"])
    broken = [
        k for k, v in BULK_WORDING[lang].items() if set(_FIELD.findall(v)) != set(_FIELD.findall(BULK_WORDING["en"][k]))
    ]
    assert not broken, f"{lang} placeholders differ: {broken}"
    english = [k for k, v in BULK_WORDING[lang].items() if _ENGLISH.search(v)]
    assert not english, f"{lang} still English: {english}"
    assert set(PERMIT_KIND["de"]) == set(PERMIT_KIND["fr"])
    assert not [v for v in BULK_PHRASES[lang].values() if _ENGLISH.search(v)]
    assert bulk_text(lang, "permit_conditions") != bulk_text("en", "permit_conditions")
    assert bulk_phrase("en", "anything") == "anything"


def test_the_cleanup_of_qms_still_recognises_the_localised_rows() -> None:
    assert set(LANGUAGES) == {"en", "de", "fr"}
    assert len({qms_text(lang, qms_seed._PLAN["name"]) for lang in LANGUAGES}) == 3
    assert len({qms_text(lang, qms_seed._ITP_ITEM_CRITERIA) for lang in LANGUAGES}) == 3


def test_the_cleanup_of_hse_advanced_matches_every_language_variant() -> None:
    assert set(hse_seed._BULK_LANGUAGES) == {"en", "de", "fr"}
