"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the document-register international helpers (``intl.py``).

Pure, database-free logic checks for the additive helpers that make the
document register clear worldwide: ISO 8601 dates, explicit-unit file
sizes, en / de / ru localisation with English fallback, faithful counts,
a latest-revision selector, a zero-guarded approved-share rate, and
one-line explainers.

The suite also pins that no banned character (em dash, en dash, smart
quotes, zero-width spaces) appears anywhere in the helper module source or
in any string it emits. The banned set is built from ``chr()`` code points
so this file itself never contains a banned character.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.documents import intl

# ── Banned-character guard (built from code points, never as literals) ──────

_BANNED_CHARS: frozenset[str] = frozenset(
    chr(cp)
    for cp in (
        0x2014,  # em dash
        0x2013,  # en dash
        0x2018,  # left single quote
        0x2019,  # right single quote
        0x201C,  # left double quote
        0x201D,  # right double quote
        0x200B,  # zero-width space
        0x200C,  # zero-width non-joiner
        0x200D,  # zero-width joiner
        0x2060,  # word joiner
    )
)


def _assert_clean(text: str) -> None:
    offenders = sorted({hex(ord(ch)) for ch in text if ch in _BANNED_CHARS})
    assert not offenders, f"banned characters present: {offenders}"


def _doc(**kwargs) -> SimpleNamespace:  # noqa: ANN003
    base = {
        "id": uuid.uuid4(),
        "name": "A-201 Ground floor plan",
        "category": "drawing",
        "cde_state": "wip",
        "revision_code": "P.01.01",
        "drawing_number": "A-201",
        "version": 1,
        "is_current_revision": True,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "file_size": 0,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


# ── Banned characters ───────────────────────────────────────────────────────


class TestNoBannedCharacters:
    def test_module_source_is_clean(self) -> None:
        source = Path(intl.__file__).read_text(encoding="utf-8")
        _assert_clean(source)

    def test_all_localised_words_are_clean(self) -> None:
        for lang in intl.SUPPORTED_LANGUAGES:
            for category in intl._CATEGORY_LABELS["en"]:
                _assert_clean(intl.localize_category(category, lang))
            for status in list(intl.APPROVAL_STATES) + [intl.STATUS_UNSET]:
                _assert_clean(intl.localize_status(status, lang))
                _assert_clean(intl.explain_approval_status(status, lang))

    def test_explainers_are_clean(self) -> None:
        docs = [_doc(cde_state="published"), _doc(cde_state="wip")]
        _assert_clean(intl.explain_revision(docs[0]))
        _assert_clean(intl.explain_register_coverage(docs))
        _assert_clean(intl.approved_share(docs).explain())
        _assert_clean(intl.explain_register_coverage([]))


# ── Dates ───────────────────────────────────────────────────────────────────


class TestIso8601:
    def test_datetime_renders_iso(self) -> None:
        got = intl.to_iso8601(datetime(2026, 7, 5, 14, 30, tzinfo=UTC))
        assert got == "2026-07-05T14:30:00+00:00"

    def test_date_renders_iso(self) -> None:
        assert intl.to_iso8601(date(2026, 7, 5)) == "2026-07-05"

    def test_none_is_none(self) -> None:
        assert intl.to_iso8601(None) is None

    def test_string_passthrough(self) -> None:
        assert intl.to_iso8601("2026-07-05") == "2026-07-05"

    def test_bad_type_raises_valueerror(self) -> None:
        with pytest.raises(ValueError):
            intl.to_iso8601(12345)  # type: ignore[arg-type]


# ── File sizes ──────────────────────────────────────────────────────────────


class TestFileSize:
    def test_zero_bytes(self) -> None:
        assert intl.format_file_size(0) == "0 B"

    def test_small_bytes_no_decimals(self) -> None:
        assert intl.format_file_size(512) == "512 B"

    def test_binary_units_default(self) -> None:
        assert intl.format_file_size(1024) == "1.0 KiB"
        assert intl.format_file_size(1536) == "1.5 KiB"
        assert intl.format_file_size(1048576) == "1.0 MiB"

    def test_decimal_units(self) -> None:
        assert intl.format_file_size(1000, binary=False) == "1.0 kB"
        assert intl.format_file_size(1_500_000, binary=False) == "1.5 MB"

    def test_always_carries_a_unit(self) -> None:
        for n in (0, 1, 999, 1000, 1024, 10**9, 10**15):
            assert " " in intl.format_file_size(n)
            assert intl.format_file_size(n).split(" ")[1].endswith(("B", "iB"))

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError):
            intl.format_file_size(-1)

    def test_bool_rejected(self) -> None:
        with pytest.raises(ValueError):
            intl.format_file_size(True)  # type: ignore[arg-type]

    def test_float_rejected(self) -> None:
        with pytest.raises(ValueError):
            intl.format_file_size(1024.0)  # type: ignore[arg-type]


# ── Localisation ────────────────────────────────────────────────────────────


class TestLocalisation:
    def test_category_localised(self) -> None:
        assert intl.localize_category("drawing", "en") == "Drawing"
        assert intl.localize_category("drawing", "de") == "Zeichnung"
        assert intl.localize_category("drawing", "ru") == "Чертеж"

    def test_unknown_language_falls_back_to_english(self) -> None:
        assert intl.localize_category("contract", "xx") == "Contract"
        assert intl.localize_status("published", "xx") == "Published (approved)"

    def test_locale_tag_and_case_normalised(self) -> None:
        assert intl.localize_category("photo", "DE-de") == "Foto"
        assert intl.localize_category("photo", "de_DE") == "Foto"

    def test_unknown_category_folds_to_other(self) -> None:
        assert intl.localize_category("engineering", "en") == "Other"
        assert intl.localize_category(None, "de") == "Sonstiges"

    def test_unknown_status_folds_to_unset(self) -> None:
        assert intl.localize_status(None, "en") == "Not set"
        assert intl.localize_status("bogus", "ru") == "Не задан"

    def test_normalize_language(self) -> None:
        assert intl.normalize_language(None) == "en"
        assert intl.normalize_language("RU") == "ru"
        assert intl.normalize_language("fr") == "en"


# ── Counts ──────────────────────────────────────────────────────────────────


class TestCounts:
    def test_count_by_category_mixed_objects_and_dicts(self) -> None:
        items = [
            _doc(category="drawing"),
            {"category": "drawing"},
            _doc(category="contract"),
            _doc(category="engineering"),  # unknown -> other
            {"category": None},  # blank -> other
        ]
        counts = intl.count_by_category(items)
        assert counts == {"drawing": 2, "contract": 1, "other": 2}
        assert sum(counts.values()) == len(items)

    def test_count_by_status(self) -> None:
        items = [
            _doc(cde_state="wip"),
            _doc(cde_state="published"),
            _doc(cde_state="published"),
            {"cde_state": None},  # -> unset
        ]
        counts = intl.count_by_status(items)
        assert counts == {"wip": 1, "published": 2, "unset": 1}

    def test_empty_register_counts_are_empty(self) -> None:
        assert intl.count_by_category([]) == {}
        assert intl.count_by_status([]) == {}


# ── Latest revision ─────────────────────────────────────────────────────────


class TestLatestRevision:
    def test_picks_flagged_current(self) -> None:
        old = _doc(revision_code="P.01", is_current_revision=False, version=1)
        new = _doc(revision_code="P.02", is_current_revision=True, version=2)
        assert intl.latest_revision([old, new]) is new

    def test_falls_back_to_highest_revision_code(self) -> None:
        a = _doc(revision_code="C.01", is_current_revision=False)
        b = _doc(revision_code="C.03", is_current_revision=False)
        assert intl.latest_revision([a, b]) is b

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            intl.latest_revision([])

    def test_group_by_drawing_number(self) -> None:
        a1 = _doc(drawing_number="A-201", revision_code="P.01", is_current_revision=False)
        a2 = _doc(drawing_number="A-201", revision_code="P.02", is_current_revision=True)
        s1 = _doc(drawing_number="S-101", revision_code="C.01", is_current_revision=True)
        latest = intl.latest_revisions_by_document([a1, a2, s1])
        assert latest["A-201"] is a2
        assert latest["S-101"] is s1

    def test_missing_key_becomes_own_group(self) -> None:
        d = _doc(drawing_number=None)
        latest = intl.latest_revisions_by_document([d])
        assert list(latest.values()) == [d]
        assert next(iter(latest)).startswith("id:")

    def test_empty_grouping_is_empty(self) -> None:
        assert intl.latest_revisions_by_document([]) == {}


# ── Approved share ──────────────────────────────────────────────────────────


class TestApprovedShare:
    def test_basic_rate(self) -> None:
        items = [
            _doc(cde_state="published"),
            _doc(cde_state="published"),
            _doc(cde_state="wip"),
            _doc(cde_state="shared"),
        ]
        share = intl.approved_share(items)
        assert share.approved == 2
        assert share.total == 4
        assert share.rate == 0.5
        assert share.percent == 50.0

    def test_empty_register_is_zero_guarded(self) -> None:
        share = intl.approved_share([])
        assert share.total == 0
        assert share.rate == 0.0  # no divide by zero, no NaN
        assert share.percent == 0.0
        # A well-defined float, never NaN or infinity.
        assert share.rate == share.rate
        assert share.rate not in (float("inf"), float("-inf"))

    def test_components_exposed(self) -> None:
        share = intl.approved_share([_doc(cde_state="published"), _doc(cde_state="wip")])
        d = share.as_dict()
        assert d["approved"] == 1
        assert d["total"] == 2
        assert d["not_approved"] == 1
        assert d["approved_states"] == ["published"]

    def test_custom_approved_states(self) -> None:
        items = [_doc(cde_state="published"), _doc(cde_state="archived"), _doc(cde_state="wip")]
        share = intl.approved_share(items, approved_states={"published", "archived"})
        assert share.approved == 2

    def test_explain_empty(self) -> None:
        text = intl.approved_share([]).explain()
        assert "0.0%" in text
        _assert_clean(text)


# ── Explainers ──────────────────────────────────────────────────────────────


class TestExplainers:
    def test_explain_revision_current(self) -> None:
        text = intl.explain_revision(_doc(cde_state="published", is_current_revision=True))
        assert "current (latest)" in text
        assert "P.01.01" in text

    def test_explain_revision_superseded(self) -> None:
        text = intl.explain_revision(_doc(is_current_revision=False))
        assert "superseded" in text

    def test_explain_approval_status_localised(self) -> None:
        assert "Approved and issued" in intl.explain_approval_status("published", "en")
        assert intl.explain_approval_status("wip", "de").startswith("In Bearbeitung")

    def test_explain_register_coverage(self) -> None:
        items = [_doc(cde_state="published"), _doc(cde_state="wip"), _doc(cde_state="shared")]
        text = intl.explain_register_coverage(items)
        assert "3 document(s)" in text
        assert "1 approved" in text
        assert "2 awaiting approval" in text

    def test_explain_register_coverage_empty(self) -> None:
        assert "empty" in intl.explain_register_coverage([])
