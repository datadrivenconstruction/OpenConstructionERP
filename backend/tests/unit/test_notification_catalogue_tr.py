# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The Turkish notification catalogue says everything the English one says.

A notification added in English without its Turkish line would reach a Turkish
mailbox in English, and nobody would see it until that one event fired on a
Turkish account. So the two tables are held equal here: same keys, same
placeholders, and for the site registers no English word left in the Turkish
sentence, checked against the English catalogue itself rather than a word list
someone has to maintain.

Pure: no database, no event bus.
"""

from __future__ import annotations

import logging
import re
import string

import pytest

from app.modules.notifications import localized
from app.modules.notifications.localized import (
    date_pattern,
    format_day,
    localize_context,
    render,
)
from app.modules.notifications.schemas import reader_text
from app.modules.notifications.templates import all_template_keys, english_template
from app.modules.notifications.templates_tr import TEMPLATES_TR

# The registers a site team works in every day. Their Turkish text is held to
# the stricter "no English word left" rule below.
_SITE_PREFIXES = (
    "notifications.deadline.rfi.",
    "notifications.deadline.submittals.",
    "notifications.deadline.correspondence.",
    "notifications.deadline.variations.",
    "notifications.variation.",
    "notifications.changeorder.",
    "notifications.submittal.approved_as_noted.",
)

# "RFI" is kept on purpose: the site glossary writes "Bilgi Talebi (RFI)".
_KEPT_IN_TURKISH = {"rfi"}

_CONTEXT = {
    "reference": "RFI-007",
    "code": "VR-012",
    "title": "Şaft detayı",
    "project": "Kule Projesi",
    "days_overdue": 4,
    "due_date_iso": "2026-10-10",
    "due_date_display": "10.10.2026",
    "reason": "Birim fiyat eksik",
}


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def _words(template: str) -> set[str]:
    """Lower-cased words of a template, placeholders removed."""
    bare = re.sub(r"\{[^}]*\}", " ", template)
    return {w.lower() for w in re.findall(r"[^\W\d_]+", bare)}


def _site_keys() -> list[str]:
    return [k for k in all_template_keys() if k.startswith(_SITE_PREFIXES)]


def test_the_turkish_table_has_exactly_the_english_keys() -> None:
    english = set(all_template_keys())
    turkish = set(TEMPLATES_TR)
    assert turkish - english == set(), "Turkish text for keys the platform never sends"
    assert english - turkish == set(), "notifications that would reach a Turkish reader in English"


def test_every_turkish_text_takes_the_same_placeholders() -> None:
    different = {
        key: (sorted(_placeholders(english_template(key) or "")), sorted(_placeholders(text)))
        for key, text in TEMPLATES_TR.items()
        if _placeholders(english_template(key) or "") != _placeholders(text)
    }
    assert different == {}


def test_no_turkish_text_is_a_copy_of_the_english() -> None:
    """A copied line passes every structural check and is still English."""
    copies = [
        key
        for key, text in TEMPLATES_TR.items()
        # A body that is only placeholders and punctuation has no words to translate.
        if _words(english_template(key) or "") and text == english_template(key)
    ]
    assert copies == []


def test_site_register_texts_carry_no_english_word() -> None:
    keys = _site_keys()
    assert len(keys) >= 30, f"only {len(keys)} site register keys found, the prefix list drifted"
    leaks = {}
    for key in keys:
        english_words = {w for w in _words(english_template(key) or "") if len(w) >= 3}
        shared = (english_words & _words(TEMPLATES_TR[key])) - _KEPT_IN_TURKISH
        if shared:
            leaks[key] = sorted(shared)
    assert leaks == {}


def test_the_site_glossary_is_the_one_the_site_uses() -> None:
    text = "\n".join(TEMPLATES_TR[k] for k in _site_keys())
    for term in (
        "Bilgi Talebi (RFI)",
        "Onay Belgesi",
        "Yazışma",
        "İlave İş",
        "Değişiklik Emri",
        "son tarih",
        "gecikmiş",
        "Yanıt bekleniyor",
    ):
        assert term in text, term
    # The file is read and written as UTF-8 end to end: no letter was folded
    # to its ASCII neighbour and none came back as a replacement character.
    assert text.encode("utf-8").decode("utf-8") == text
    assert "�" not in text
    assert "?" not in text
    for wrong in ("Yazisma", "Ilave Is", "Degisiklik", "gecikmis", "Yanit"):
        assert wrong not in text, wrong


@pytest.mark.parametrize("key", _site_keys())
@pytest.mark.parametrize("locale", ["en", "tr"])
def test_a_site_register_text_renders_whole(key: str, locale: str) -> None:
    rendered = render(key, _CONTEXT, locale)
    assert "{" not in rendered and "}" not in rendered, rendered
    template = english_template(key) or ""
    for name, value in _CONTEXT.items():
        if name in _placeholders(template):
            assert str(value) in rendered, (name, rendered)


def test_an_overdue_rfi_reads_as_turkish_and_as_english() -> None:
    turkish_title = render("notifications.deadline.rfi.overdue.title", _CONTEXT, "tr")
    turkish_body = render("notifications.deadline.rfi.overdue.body", _CONTEXT, "tr")
    assert turkish_title == "Gecikmiş: Bilgi Talebi (RFI) RFI-007"
    assert turkish_body == (
        'Kule Projesi projesinde RFI-007 numaralı Bilgi Talebi (RFI) "Şaft detayı" gecikmiş: '
        "son tarih 10.10.2026, gecikme 4 gün. Yanıt bekleniyor."
    )
    english = dict(_CONTEXT, due_date_display="2026-10-10")
    assert render("notifications.deadline.rfi.overdue.title", english, "en") == "Overdue: RFI RFI-007"
    assert render("notifications.deadline.rfi.overdue.body", english, "en") == (
        'RFI RFI-007 "Şaft detayı" on Kule Projesi was due on 2026-10-10 and is 4 day(s) overdue. Response required.'
    )


def test_a_regional_tag_is_its_language() -> None:
    assert render("notifications.variation.approved.title", _CONTEXT, "tr-TR") == "İlave İş onaylandı: VR-012"
    assert render("notifications.variation.approved.title", _CONTEXT, "TR_tr") == "İlave İş onaylandı: VR-012"


def test_a_date_is_written_the_way_its_reader_writes_dates() -> None:
    assert format_day("2026-10-09", "tr") == "09.10.2026"
    assert format_day("2026-10-09T08:30:00+00:00", "tr") == "09.10.2026"
    # English has no single order, so nobody is made to guess: ISO.
    assert format_day("2026-10-09", "en") == "2026-10-09"
    # A person's own choice wins over their language.
    assert format_day("2026-10-09", "tr", "MM/DD/YYYY") == "10/09/2026"
    assert format_day("2026-10-09", "en", "DD/MM/YYYY") == "09/10/2026"
    # "auto" and the column's old default both mean nobody chose.
    assert date_pattern("tr", "auto") == "DD.MM.YYYY"
    assert date_pattern("en", "DD.MM.YYYY") == "YYYY-MM-DD"
    # A value that is not a date is shown as stored rather than dropped.
    assert format_day("next week", "tr") == "next week"
    assert format_day(None, "tr") == ""


def test_the_display_date_follows_the_reader_not_the_day_it_was_stored() -> None:
    stored = {"reference": "RFI-007", "due_date_iso": "2026-10-10", "due_date_display": "10.10.2026"}
    assert localize_context(stored, "en")["due_date_display"] == "2026-10-10"
    assert localize_context(stored, "tr")["due_date_display"] == "10.10.2026"
    assert stored["due_date_display"] == "10.10.2026", "the stored params must not be rewritten in place"
    # Params without a canonical date are returned as they are.
    assert localize_context({"due_date": "2026-10-10"}, "tr") == {"due_date": "2026-10-10"}


def test_the_bell_fallback_is_written_for_whoever_opens_the_bell() -> None:
    """One stored row, two readers: the same key and params, two languages."""
    key = "notifications.deadline.correspondence.approaching"
    stored = dict(_CONTEXT, reference="COR-031", due_date_display="10.10.2026")

    title_tr, body_tr, params_tr = reader_text(f"{key}.title", f"{key}.body", stored, "tr")
    title_en, body_en, params_en = reader_text(f"{key}.title", f"{key}.body", stored, "en")

    assert title_tr == "Son tarih yaklaşıyor: Yazışma COR-031"
    assert "son tarih 10.10.2026" in body_tr
    assert title_en == "Due soon: correspondence COR-031"
    assert "by 2026-10-10" in body_en
    assert params_tr["due_date_display"] == "10.10.2026"
    assert params_en["due_date_display"] == "2026-10-10"


def test_a_legacy_key_still_resolves_for_a_turkish_reader() -> None:
    title, body, _ = reader_text(
        "notifications.rfi.assigned",
        "notifications.rfi.assigned",
        {"code": "RFI-007", "title": "Şaft detayı"},
        "tr",
    )
    assert title == "Size bir Bilgi Talebi (RFI) atandı"
    assert body == "RFI-007 - Şaft detayı"


def test_a_language_without_a_catalogue_is_answered_in_english_and_says_so_once(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(localized, "_FALLBACK_LOGGED", set())
    key = "notifications.changeorder.approved.title"
    with caplog.at_level(logging.INFO, logger=localized.__name__):
        first = render(key, _CONTEXT, "de")
        second = render(key, _CONTEXT, "de-AT")
        render(key, _CONTEXT, "hu")
    assert first == second == render(key, _CONTEXT, "en") == "Change order approved: VR-012"
    named = [r.getMessage() for r in caplog.records if "no message catalogue" in r.getMessage()]
    assert len(named) == 2, named
    assert "'de'" in named[0] and "'hu'" in named[1]


def test_an_unknown_key_comes_back_as_the_key_in_any_language() -> None:
    assert render("notifications.nobody.sends.this", {}, "tr") == "notifications.nobody.sends.this"
    assert render(None, {}, "tr") == ""
