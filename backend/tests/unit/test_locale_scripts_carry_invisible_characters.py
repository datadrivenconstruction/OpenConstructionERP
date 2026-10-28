"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The locale scripts under ``scripts/`` must be transparent to invisible characters.

Zero-width characters are invisible by construction, so every way of mishandling
them looks correct on screen. Three of those ways were live in this repository at
once, and none of them showed up in a diff, a review or a gate:

* ``scripts/i18n_extract.py`` decoded each value with the ``unicode_escape``
  codec, which reads a string's UTF-8 bytes back as latin-1. A zero-width
  character came out as three characters, and so did every Cyrillic, CJK and
  Arabic letter in the file.
* ``scripts/translate_mn_pass2.py`` and ``scripts/translate_mn_pass6_more_long.py``
  hold translation tables whose keys are English source strings. Some of those
  keys picked up a run of invisible characters from a mechanical pass over the
  tree. A key holding one cannot match the English string it is meant to match,
  so those entries were dead, and the scripts reported success while translating
  nothing.
* Every ``translate_mn_pass*`` script, and ``scripts/i18n_apply.py``, read the
  locale with ``Path.read_text`` and wrote it back with ``Path.write_text``.
  Both translate line endings, so a run that replaced nothing still rewrote the
  whole file - to CRLF on Windows, to LF everywhere else.

The assertions below compare code points and bytes, never rendered strings. A
rendered comparison is what let all three through.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import i18n_apply  # noqa: E402
import i18n_extract  # noqa: E402
import translate_mn_pass2  # noqa: E402
import translate_mn_pass6_more_long  # noqa: E402

# Written as escapes on purpose. A test that spells invisible characters out
# literally cannot be reviewed, which is the whole problem it exists to catch.
ZERO_WIDTH_RUN = "\u200c\u2060\u200d"

# Every script that rewrites frontend/src/app/locales/mn.ts in place.
MN_PASSES = (
    "translate_mn_pass2.py",
    "translate_mn_pass3.py",
    "translate_mn_pass5_long.py",
    "translate_mn_pass6_more_long.py",
    "translate_mn_pass7_fixes.py",
    "translate_mn_pass8_final.py",
    "translate_mn_pass9.py",
)


def _invisible(text: str) -> bool:
    return any(unicodedata.category(ch) == "Cf" for ch in text)


def _printing(text: str) -> str:
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


# ── scripts/i18n_extract.py ──────────────────────────────────────────────────


def test_the_fallbacks_parser_returns_every_code_point_it_read() -> None:
    """A parsed value must equal the source value code point for code point."""
    marked = "Save" + ZERO_WIDTH_RUN
    cyrillic = "Сохранить"
    source = (
        "export const fallbackResources = {\n"
        "  en: {\n"
        "    translation: {\n"
        f"      'action.save': '{marked}',\n"
        "    },\n"
        "  },\n"
        "  ru: {\n"
        "    translation: {\n"
        f"      'action.save': '{cyrillic}',\n"
        "    },\n"
        "  },\n"
        "};\n"
    )

    blocks = i18n_extract.parse_blocks(source)

    assert list(blocks) == ["en", "ru"]
    parsed = blocks["en"]["action.save"]
    assert [ord(ch) for ch in parsed] == [ord(ch) for ch in marked]
    assert parsed.encode("utf-8") == marked.encode("utf-8")
    # The same defect destroyed everything above U+007F, not only the invisibles.
    assert blocks["ru"]["action.save"].encode("utf-8") == cyrillic.encode("utf-8")


def test_the_fallbacks_parser_still_decodes_the_escapes_it_is_meant_to() -> None:
    """Transparency to literal characters must not turn the unescaper off."""
    source = (
        "export const fallbackResources = {\n"
        "  en: {\n"
        "    translation: {\n"
        "      'a.quote': 'It\\'s here',\n"
        "      'a.tab': 'left\\tright',\n"
        "      'a.escaped': 'zero\\u200bwidth',\n"
        "    },\n"
        "  },\n"
        "};\n"
    )

    parsed = i18n_extract.parse_blocks(source)["en"]

    assert parsed["a.quote"] == "It's here"
    assert parsed["a.tab"] == "left\tright"
    assert parsed["a.escaped"] == "zero\u200bwidth"


# ── the stamped translation tables ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("module", "table"),
    [
        (translate_mn_pass2, "PHRASES"),
        (translate_mn_pass6_more_long, "FULL_TRANSLATIONS"),
    ],
    ids=["pass2", "pass6"],
)
def test_a_translation_table_matches_the_english_an_invisible_character_hides(module, table) -> None:
    """A key carrying invisible characters must still match the visible string.

    The English source strings in ``en.ts`` do not carry these characters, so a
    key that does is unreachable. Both sides of the lookup therefore go through
    ``visible()``, and the translation that comes back out must be free of them
    too: it is written into ``mn.ts``, where ``scripts/check_zero_width.py``
    reports a stray as a failure.
    """
    entries = getattr(module, table)
    marked = [key for key in entries if _invisible(key)]
    # Without this the test passes vacuously the day the marks move or go.
    assert marked, f"{table} no longer has a key carrying an invisible character"

    lookup = {module.visible(k): module.visible(v) for k, v in entries.items()}
    for key in marked:
        probe = _printing(key)
        assert probe != key
        assert probe in lookup, f"{probe!r} is unreachable in {table}"
        translation = lookup[probe]
        assert translation, f"{probe!r} translates to nothing"
        assert not _invisible(translation), f"the translation of {probe!r} would carry a stray into mn.ts"


@pytest.mark.parametrize(
    ("module", "table"),
    [
        (translate_mn_pass2, "PHRASES"),
        (translate_mn_pass6_more_long, "FULL_TRANSLATIONS"),
    ],
    ids=["pass2", "pass6"],
)
def test_hiding_an_invisible_character_never_splices_an_escape(module, table) -> None:
    """Dropping the invisibles must not join a backslash to the character after it.

    ``translate_mn_pass6_more_long`` holds its values as raw TypeScript literal
    bodies and writes them back with no further escaping, so a mark that landed
    between a backslash and the character it escapes would not merely be lost -
    it would weld two escapes together and put malformed TypeScript in the
    locale. The marks in the table today all sit at the end of a literal; these
    assertions are what keeps that true if the stamping pass runs again.
    """
    for key, value in getattr(module, table).items():
        for text in (key, value):
            hidden = module.visible(text)
            assert hidden.count("\\\\") == text.count("\\\\"), f"escaped backslash changed in {table}[{key!r}]"
            assert hidden.count('\\"') == text.count('\\"'), f"escaped quote changed in {table}[{key!r}]"
            assert all(text[i - 1] != "\\" for i, ch in enumerate(text) if i and unicodedata.category(ch) == "Cf"), (
                f"an invisible character sits inside an escape sequence in {table}[{key!r}]"
            )


def test_pass2_translate_reaches_a_phrase_an_invisible_character_hid() -> None:
    """The behaviour above, through the function the script actually calls."""
    marked = [key for key in translate_mn_pass2.PHRASES if _invisible(key)]
    assert marked, "PHRASES no longer has a key carrying an invisible character"

    for key in marked:
        probe = _printing(key)
        translated = translate_mn_pass2.translate(probe)
        assert translated != probe, f"translate({probe!r}) returned the English unchanged"
        assert not _invisible(translated)


# ── scripts/i18n_apply.py ────────────────────────────────────────────────────

# Mixed endings again, and a blank line right after the entry that gets
# replaced: the old pattern ended in ``,?\s*$``, which is greedy and matches
# before any newline, so it swallowed the entry's own ending and the blank line
# with it. The value that carries the marks is on a line the patch does not
# touch, so the same fixture shows that an untouched line comes back verbatim.
_FALLBACKS_FIXTURE = (
    "export const fallbackResources = {\n"
    "  en: {\n"
    "    translation: {\n"
    f"      'action.save': 'Save{ZERO_WIDTH_RUN}',\r\n"
    "      'action.close': 'Close',\r\n"
    "\n"
    "      'action.open': 'Open',\n"
    "    },\n"
    "  },\n"
    "};\n"
)


def test_the_fallbacks_writer_changes_only_the_value_it_was_asked_to_change() -> None:
    """Replacing one value must leave every other byte of the file alone."""
    updated = i18n_apply._replace_or_append(_FALLBACKS_FIXTURE, "en", {"action.close": "Zavrit"}, {})

    assert updated == _FALLBACKS_FIXTURE.replace("'action.close': 'Close',", "'action.close': 'Zavrit',")


def test_the_fallbacks_writer_appends_with_the_ending_the_block_already_uses() -> None:
    """A new entry gets the block's own line ending, and the marks stay put."""
    updated = i18n_apply._replace_or_append(_FALLBACKS_FIXTURE, "en", {"action.new": "Nove"}, {})

    assert "      'action.new': 'Nove',\r\n" in updated
    assert f"      'action.save': 'Save{ZERO_WIDTH_RUN}',\r\n" in updated


# ── byte-for-byte round trip ─────────────────────────────────────────────────

# Deliberately mixed line endings. A fixture that is all LF passes on Linux with
# the defect still in place, and one that is all CRLF passes on Windows; only a
# mixture fails on both. The stamped value is there so the same run proves the
# invisible characters survive the rewrite as well.
_LOCALE_FIXTURE = (
    b"// Locale source. Edit this file directly: nothing generates it.\n"
    b"const resource = {\r\n"
    b'  "translation": {\n'
    b'    "fixture.plain": "Plain value",\r\n'
    b'    "fixture.marked": "Marked value' + ZERO_WIDTH_RUN.encode("utf-8") + b'",\n'
    b'    "fixture.last": "Last value"\r\n'
    b"  }\n"
    b"} as { translation: Record<string, string> };\r\n"
    b"\n"
    b"export default resource;\n"
)


@pytest.mark.parametrize("script_name", MN_PASSES)
def test_an_mn_pass_leaves_the_locale_byte_identical_when_it_replaces_nothing(tmp_path: Path, script_name: str) -> None:
    """Nothing in the fixture matches, so the file must come back unchanged.

    Byte comparison, not text: the defect this catches is a line-ending rewrite,
    and reading both sides back as text hides it by construction.
    """
    (tmp_path / "scripts").mkdir()
    locales = tmp_path / "frontend" / "src" / "app" / "locales"
    locales.mkdir(parents=True)
    shutil.copyfile(_SCRIPTS / script_name, tmp_path / "scripts" / script_name)
    # pass2 and pass3 read this; the others ignore it.
    (tmp_path / "scripts" / "_mn_remaining.json").write_bytes(b"{}\n")
    for name in ("en.ts", "mn.ts"):
        (locales / name).write_bytes(_LOCALE_FIXTURE)

    mn = locales / "mn.ts"
    before = mn.read_bytes()
    assert b"\r\n" in before and before.count(b"\n") > before.count(b"\r\n")

    result = subprocess.run(  # noqa: S603
        [sys.executable, str(Path("scripts") / script_name)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    after = mn.read_bytes()
    assert after == before, (
        f"{script_name} rewrote mn.ts without replacing anything: "
        f"{len(before)} bytes in, {len(after)} bytes out, "
        f"CRLF {before.count(chr(13).encode() + chr(10).encode())} -> "
        f"{after.count(chr(13).encode() + chr(10).encode())}"
    )
