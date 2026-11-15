# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The construction-control register and the HSE investigations of a German or French demo carry no English prose.

``seed_phrases`` and ``seed_text`` (construction control) and ``hse_advanced.seed_text`` hold the wording; the
seeders read it by the project's locale. These tests fail when a package, a sentence or an investigation method
falls back to English for ``de`` or ``fr``.
"""

from __future__ import annotations

import re

import pytest

from app.modules.construction_control.seed import _WORK_PACKAGES, _localised_package
from app.modules.construction_control.seed_phrases import PHRASES, category_text, instrument_kind, phrase
from app.modules.construction_control.seed_text import WORDING, control_text
from app.modules.hse_advanced.seed import _INVESTIGATION_NOTES
from app.modules.hse_advanced.seed_text import INVESTIGATION_NOTES, investigation_notes

#: English words that never occur in the German or French wording.
_ENGLISH = re.compile(
    r"\b(the|and|for|with|from|before|after|works|measured|inspection|supplier|laboratory|accredited|survey|"
    r"released|judged|specimen|applies|attends|tested|record|certificate|submitted|rework|plant|wholesaler)\b",
    re.IGNORECASE,
)
_FIELD = re.compile(r"\{(\w+)\}")


def _prose(package) -> list[str]:
    spec = package.criterion
    texts = [
        package.location,
        package.inspection_title,
        package.gate_title,
        spec.title,
        spec.characteristic,
        spec.method,
    ]
    if package.material is not None:
        texts += [package.material.name, package.material.supplier_kind]
    if package.lab is not None:
        texts.append(package.lab.title)
    if package.survey is not None:
        texts.append(package.survey.title)
    return [t for t in texts if t]


@pytest.mark.parametrize("lang", ["de", "fr"])
def test_every_package_reads_in_the_project_language(lang: str) -> None:
    for package in _WORK_PACKAGES:
        local = _localised_package(lang, package)
        for english, translated in zip(_prose(package), _prose(local), strict=True):
            assert translated != english, (package.key, english)
            assert not _ENGLISH.search(translated), (package.key, translated)
        # Codes, standards and measured values are data and stay as they are.
        assert local.criterion.code == package.criterion.code
        assert local.criterion.standard_ref == package.criterion.standard_ref
        assert local.criterion.breach_value == package.criterion.breach_value
        assert category_text(lang, package.category) != package.category


def test_english_is_the_default_and_other_languages_are_untouched() -> None:
    for locale in (None, "en", "es", "zh"):
        for package in _WORK_PACKAGES:
            assert _localised_package(locale, package) == package
    assert phrase("zh", "Reinforcement fabricator") == "Reinforcement fabricator"
    assert category_text("en", "concrete") == "concrete"
    assert category_text("en", "concrete", head=True) == "Concrete"
    assert instrument_kind("en", "gnss") == "Gnss"


@pytest.mark.parametrize("lang", ["de", "fr"])
def test_the_register_wording_keeps_its_placeholders_and_reads_in_the_language(lang: str) -> None:
    assert set(WORDING[lang]) == set(WORDING["en"])
    for key, text in WORDING[lang].items():
        assert set(_FIELD.findall(text)) == set(_FIELD.findall(WORDING["en"][key])), key
        assert not _ENGLISH.search(text), key
        if key not in {"coordinate_system"}:
            assert text != WORDING["en"][key], key
    values = dict.fromkeys(
        ("category", "location", "code", "standard", "characteristic", "title", "number", "value"), "x"
    )
    values.update(unit="mm", method="m", kind="k", notes="n")
    assert control_text(lang, "gate_waived", **values) != control_text("en", "gate_waived", **values)


def test_the_phrase_tables_cover_the_same_sentences() -> None:
    assert set(PHRASES["de"]) == set(PHRASES["fr"])
    for lang in ("de", "fr"):
        for english, translated in PHRASES[lang].items():
            assert translated != english, english
            assert not _ENGLISH.search(translated), (lang, translated)


def test_every_english_register_phrase_has_a_translation() -> None:
    from app.modules.construction_control import seed

    english = {*seed._LAB_NAMES, *seed._LAB_ACCREDITATIONS, *seed._SURVEY_PARTIES, *seed._CERT_ISSUERS}
    for package in _WORK_PACKAGES:
        english.add(package.criterion.characteristic)
        english.add(package.criterion.method)
        english.add(package.gate_title) if package.gate_title else None
        if package.material is not None:
            english.update((package.material.name, package.material.supplier_kind))
        if package.survey is not None:
            english.add(package.survey.title)
    english.update(
        (
            "Whole works - acceptance package",
            "Sectional handover - car park and external works",
            "Section 1: car park levels -1 and -2, external works",
        )
    )
    missing = sorted(text for text in english if text not in PHRASES["de"] or text not in PHRASES["fr"])
    assert not missing, missing


@pytest.mark.parametrize("lang", ["de", "fr"])
def test_hse_investigations_read_in_the_project_language(lang: str) -> None:
    assert set(INVESTIGATION_NOTES[lang]) == set(_INVESTIGATION_NOTES)
    for method, default in _INVESTIGATION_NOTES.items():
        findings, recommendations = investigation_notes(lang, method, default)
        assert (findings, recommendations) != default
        assert not _ENGLISH.search(f"{findings} {recommendations}"), method
        assert investigation_notes("en", method, default) == default
