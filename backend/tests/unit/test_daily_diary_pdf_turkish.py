"""The daily site report prints in Turkish, and no language can be half there.

Two things are pinned.

The first is structural. The diary catalogue is four tables keyed by
language: fixed strings, entry groups, statuses and weather conditions. A
language named in ``SUPPORTED_PDF_LOCALES`` without a row in each of them
prints English under a Turkish heading, silently, because every lookup falls
back. The parity test below makes that state unreachable for any language,
not only Turkish: every supported language carries every English key in
every table, with the same placeholders.

The second is the document itself: a Turkish diary rendered from Turkish text
has Turkish labels, the right capitals, a Turkish date and decimal comma, and
nothing from the English table.

Text assertions go through ``pypdf`` extraction, like the German diary tests.
"""

from __future__ import annotations

import io
import re
import string
import unicodedata
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from pypdf import PdfReader

from app.core.pdf_fonts import register_pdf_fonts
from app.modules.daily_diary import pdf_translations as catalogue
from app.modules.daily_diary.pdf_export import generate_diary_pdf
from app.modules.daily_diary.pdf_translations import (
    SUPPORTED_PDF_LOCALES,
    diary_pdf_filename,
    entry_type_label,
    fmt_number,
    format_iso_date,
    normalize_pdf_locale,
    resolve_pdf_locale,
    status_caps,
    status_label,
    tr,
    weather_summary_text,
)

TABLES: dict[str, dict[str, dict[str, str]]] = {
    "strings": catalogue._STRINGS,
    "entry types": catalogue._ENTRY_TYPE_LABELS,
    "statuses": catalogue._STATUS_LABELS,
    "conditions": catalogue._CONDITION_LABELS,
}

# Keys that are formats or separators, not prose a reader could call English.
NOT_PROSE = {"date_format", "datetime_format", "filename_prefix", "decimal_mark", "percent"}


def _placeholders(value: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(value) if name}


# ── No language without its dictionary ────────────────────────────────────


@pytest.mark.parametrize("table_name", list(TABLES))
def test_every_table_has_exactly_the_supported_languages(table_name: str) -> None:
    assert set(TABLES[table_name]) == set(SUPPORTED_PDF_LOCALES)


@pytest.mark.parametrize("locale", SUPPORTED_PDF_LOCALES)
@pytest.mark.parametrize("table_name", list(TABLES))
def test_every_language_has_every_key_with_the_same_placeholders(table_name: str, locale: str) -> None:
    english = TABLES[table_name]["en"]
    translated = TABLES[table_name][locale]
    assert set(translated) == set(english)
    for key, value in translated.items():
        assert value.strip(), f"{locale}.{key} is empty"
        assert _placeholders(value) == _placeholders(english[key]), f"{locale}.{key}"


def test_turkish_is_a_supported_language() -> None:
    assert "tr" in SUPPORTED_PDF_LOCALES
    assert normalize_pdf_locale("tr-TR") == "tr"
    assert resolve_pdf_locale(None, "tr-TR,tr;q=0.9,en;q=0.8") == "tr"
    assert resolve_pdf_locale("tr", "de-DE") == "tr"


@pytest.mark.parametrize("locale", [code for code in SUPPORTED_PDF_LOCALES if code != "en"])
def test_a_translation_is_not_a_copy_of_the_english_table(locale: str) -> None:
    """A table filled by copying English would pass the parity test above."""
    same = [
        key
        for key, value in catalogue._STRINGS[locale].items()
        if key not in NOT_PROSE and value == catalogue._STRINGS["en"][key]
    ]
    assert len(same) <= 3, same


# ── Turkish helpers ───────────────────────────────────────────────────────


def test_turkish_capitals_numbers_and_dates() -> None:
    assert status_caps(status_label("signed", "tr"), "tr") == "İMZALANDI"
    assert status_caps(status_label("archived", "tr"), "tr") == "ARŞİVLENDİ"
    assert status_caps(status_label("open", "tr"), "tr") == "AÇIK"
    assert status_caps(status_label("closed", "en"), "en") == "CLOSED"
    assert fmt_number(Decimal("12.5"), 1, "tr") == "12,5"
    assert fmt_number(Decimal("12.5"), 1, "en") == "12.5"
    assert format_iso_date("2026-10-10", "tr") == "10.10.2026"
    assert tr("tr", "percent", value=85) == "%85"
    assert tr("en", "percent", value=85) == "85%"
    assert entry_type_label("completion", "tr") == "Yapılan işler"
    assert diary_pdf_filename("2026-10-10", "tr").startswith("santiye-gunluk-raporu")


def test_turkish_weather_line() -> None:
    line = weather_summary_text(
        {"temp_c": 18.5, "conditions": "partly_cloudy", "wind_kmh": 12, "humidity_pct": 60}, "tr"
    )
    assert "18,5 °C" in line
    assert "parçalı bulutlu" in line
    assert "rüzgar 12 km/sa" in line
    assert "nem %60" in line
    assert "partly" not in line


# ── The document ──────────────────────────────────────────────────────────


def _diary(**overrides: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "diary_date": "2026-10-10",
        "status": "signed",
        "labour_count": 42,
        "equipment_count": 6,
        "weather_summary": {"temp_c": 18.5, "conditions": "partly_cloudy", "wind_kmh": 12},
        "notes": "Şaft içi çalışmada iş güvenliği önlemleri gözden geçirildi. IĞÜŞÖÇİ ığüşöç",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _entries() -> list[SimpleNamespace]:
    texts = {
        "completion": "Üçüncü kat yangın tesisatı boruları döşendi",
        "delivery": "Soğutma grubu şantiyeye indirildi",
        "visitor": "İşveren temsilcisi Çağrı Öztürk",
        "incident_summary": "Iskarta malzeme ayrıldı, kaza yok",
        "inspection_summary": "Basınç testi görüldü",
        "event": "Vinç bakımı",
        "photo_note": "Şaft fotoğrafları çekildi",
        "general": "Öğle arası uzadı",
    }
    return [
        SimpleNamespace(
            entry_type=entry_type,
            entry_time=datetime(2026, 10, 10, 9 + index, 0, tzinfo=UTC),
            title=title,
            description="Ölçüm: 12,5 m.",
        )
        for index, (entry_type, title) in enumerate(texts.items())
    ]


def _weather() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            captured_at=datetime(2026, 10, 10, 8, 0, tzinfo=UTC),
            source="manual",
            temperature_c=Decimal("18.5"),
            wind_speed_kmh=Decimal("12.0"),
            precipitation_mm=Decimal("0.4"),
            conditions_text="Parçalı bulutlu",
        )
    ]


def _text(pdf: bytes) -> str:
    raw = " ".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(pdf)).pages)
    return " ".join(unicodedata.normalize("NFC", raw).replace(" ", " ").split())


def _turkish_text(**overrides: Any) -> str:
    params: dict[str, Any] = {
        "project_name": "Işıklı Veri Merkezi",
        "entries": _entries(),
        "weather_records": _weather(),
        "supervisor_name": "Şükrü Iğdır",
        "completeness": Decimal("0.85"),
        "locale": "tr",
    }
    params.update(overrides)
    pdf = generate_diary_pdf(_diary(), **params)
    assert pdf.startswith(b"%PDF")
    return _text(pdf)


def test_the_bundled_faces_are_in_use() -> None:
    """Without them the page falls back to a face that has no ğ, ı, İ or ş."""
    assert register_pdf_fonts() is True


def test_turkish_diary_has_turkish_labels_dates_and_numbers() -> None:
    text = _turkish_text()
    for expected in (
        "Şantiye Günlük Raporu",
        "Işıklı Veri Merkezi",
        "İMZALANDI",
        "10.10.2026",
        "Genel bilgiler",
        "Saha amiri",
        "Şükrü Iğdır",
        "Sahadaki iş gücü",
        "Sahadaki ekipman",
        "Tamlık oranı",
        "%85",
        "Hava durumu",
        "Sıcaklık (°C)",
        "18,5",
        "0,4",
        "Şantiye kayıtları",
        "Yapılan işler",
        "Malzeme teslimatları",
        "Ziyaretçiler",
        "İş güvenliği ve olaylar",
        "Denetimler",
        "Notlar",
        "Oluşturulma:",
        "Sayfa 1",
        # Row text, with every letter Turkish adds.
        "Üçüncü kat yangın tesisatı boruları döşendi",
        "Iskarta malzeme ayrıldı, kaza yok",
        "IĞÜŞÖÇİ ığüşöç",
    ):
        assert expected in text, f"missing Turkish fragment: {expected!r}"
    assert "2026-10-10" not in text
    assert "85%" not in text
    assert "18.5" not in text
    # The capital of "i" is "İ" in Turkish; plain upper-casing would print this.
    assert "IMZALANDI" not in text


def _fragments(locale: str) -> set[str]:
    """The fixed words of every string of a language, placeholders cut out."""
    fragments: set[str] = set()
    for name, table in TABLES.items():
        for key, value in table[locale].items():
            if name == "strings" and key in NOT_PROSE:
                continue
            for part in re.split(r"\{[a-z_]+\}", value):
                fragment = part.strip(" :,()/.-%")
                if re.search(r"[A-Za-z]{2}", fragment):
                    fragments.add(fragment)
    return fragments


def _english_only() -> set[str]:
    """English words with a different Turkish form; a unit such as "mm" is the same in both."""
    return _fragments("en") - _fragments("tr")


def test_no_english_label_shows_in_the_turkish_diary() -> None:
    english_only = _english_only()
    assert len(english_only) >= 40
    for text in (_turkish_text(), _turkish_text(entries=[], weather_records=[], supervisor_name=None)):
        leaks = sorted(value for value in english_only if re.search(rf"(?<!\w){re.escape(value)}(?!\w)", text))
        assert leaks == []


def test_the_leak_check_sees_english_when_it_is_there() -> None:
    """The same check, pointed at the English diary, must find what it looks for."""
    pdf = generate_diary_pdf(_diary(), project_name="Işıklı Veri Merkezi", entries=_entries(), locale="en")
    text = _text(pdf)
    found = [value for value in _english_only() if re.search(rf"(?<!\w){re.escape(value)}(?!\w)", text)]
    assert len(found) >= 12, found
    assert "Daily Site Diary" in text
    assert "Üçüncü kat yangın tesisatı boruları döşendi" in text


def test_an_empty_turkish_diary_says_so_in_turkish() -> None:
    text = _turkish_text(entries=[], weather_records=[], supervisor_name=None, completeness=None)
    assert "Bu rapor için kayıt girilmedi." in text
    assert "Kaydedilmedi" in text
