"""The generic demo rows of the Chinese and Arabic showcase projects are worded in the project language.

Same contract as the German and French tables: identical keys and placeholders as the English table, no ASCII
English prose left in a localised field, and every generic block of a zh/ar demo reads from its own table.
"""

from __future__ import annotations

import re
from dataclasses import replace

import pytest

from app.core.demo_locale_text import GENERATED_TEXT, authority_text, generated_text, language_of
from app.core.demo_projects import DEMO_TEMPLATES

from .test_demo_generic_blocks_follow_the_project_language import _from_the_bill, _generate, _prose

_LANGS = ["zh", "ar"]
_FIELD = re.compile(r"\{(\w+)\}")
#: A run of three or more ASCII letters that is not an acronym (CAR, BIM, ISO) or a placeholder.
_ENGLISH_WORD = re.compile(r"(?<![A-Za-z{])[A-Za-z]{3,}(?![A-Za-z}])")
_ACRONYM = re.compile(r"^[A-Z]{2,}$")
_PROJECTS = [
    (demo_id, language_of(t.locale)) for demo_id, t in DEMO_TEMPLATES.items() if language_of(t.locale) in _LANGS
]


def _english_words(text: str) -> list[str]:
    return [w for w in _ENGLISH_WORD.findall(_FIELD.sub("", text)) if not _ACRONYM.match(w)]


def test_the_showcase_projects_of_both_languages_exist() -> None:
    langs = {lang for _, lang in _PROJECTS}
    assert langs == set(_LANGS)
    assert {"office-shanghai", "hospital-jeddah", "tower-abudhabi"} <= {d for d, _ in _PROJECTS}


@pytest.mark.parametrize("lang", _LANGS)
def test_the_table_carries_the_keys_of_the_english_one(lang: str) -> None:
    assert set(GENERATED_TEXT[lang]) == set(GENERATED_TEXT["en"])


@pytest.mark.parametrize("lang", _LANGS)
def test_every_entry_keeps_the_placeholders_of_its_english_original(lang: str) -> None:
    broken = [
        k
        for k, v in GENERATED_TEXT[lang].items()
        if set(_FIELD.findall(v)) != set(_FIELD.findall(GENERATED_TEXT["en"][k]))
    ]
    assert not broken, f"{lang} placeholders differ from English in: {broken}"


@pytest.mark.parametrize("lang", _LANGS)
def test_no_entry_is_left_in_english(lang: str) -> None:
    same = [k for k, v in GENERATED_TEXT[lang].items() if v == GENERATED_TEXT["en"][k] and k != "punch_description"]
    assert not same, f"{lang} entries identical to English: {same}"
    words = {k: _english_words(v) for k, v in GENERATED_TEXT[lang].items() if _english_words(v)}
    assert not words, f"{lang} entries with ASCII English words: {words}"


@pytest.mark.parametrize(("demo_id", "lang"), _PROJECTS)
def test_every_generic_block_of_the_demo_is_worded_from_the_locale_table(demo_id: str, lang: str) -> None:
    template = DEMO_TEMPLATES[demo_id]
    local = _prose(_generate(template))
    english = _prose(_generate(replace(template, locale="en")))
    assert set(local) == set(english)
    assert len(local) >= 23
    for block, texts in local.items():
        assert len(texts) == len(english[block]), block
        same = [
            t
            for t, e in zip(texts, english[block], strict=True)
            if t == e and " " in t and not _from_the_bill(t, template)
        ]
        assert not same, f"{demo_id} {block} falls back to English: {same[:3]}"


def test_the_notified_authority_is_named_in_the_project_language() -> None:
    assert authority_text("zh-CN", "CN") == "住房和城乡建设主管部门"
    assert authority_text("ar", "AE")
    assert authority_text("ar", "SA")
    assert authority_text("en", "AE") is None


def test_the_language_follows_the_locale_variant() -> None:
    assert language_of("zh-CN") == "zh"
    assert language_of("ar_AE") == "ar"
    assert generated_text("ar", "task_0") == GENERATED_TEXT["ar"]["task_0"]
