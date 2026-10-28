# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Catalogue guard for backend/locales: the list and the files must agree.

Two lists decide what a backend locale is. ``SUPPORTED_LOCALES`` in
app/core/i18n.py is what every caller gates on - the Accept-Language
middleware matches against it, the /i18n routes 404 outside it - and
``LOCALE_NAMES`` is what get_available_locales() offers a user. The
translations themselves are the JSON files. Nothing kept the three in step,
and they drifted in both directions at once: bg, hr, id, ro, th and vi were
translated files no request could ever select, while mn was offered in the
language picker with no file behind it, so choosing it served English.

Neither direction is visible from a passing test suite, an HTTP 200 or a
green build, which is why it is asserted here rather than reviewed.

Three checks:

  * The two lists and the set of files on disk are the same set. Measured
    through ``LOCALES_DIR``, the same path the runtime loads from, so a move
    of the directory fails here instead of silently emptying the catalogue.

  * No locale is mostly English. A file can carry every key, parse, load and
    still be the English source text under a foreign name: bg was exactly
    that, 372 of 372 shared values byte-identical to en.json. This is the
    backend twin of scripts/check_i18n_leak_baseline.py, which only ever
    looked at the frontend. The threshold is deliberately loose - a real
    translation lands far below it, since only product names, unit symbols
    and the odd international loanword legitimately match English - so it
    accuses nothing that is merely incomplete.

  * Key coverage against en.json may not get worse. Most locales are still
    short of the full key set and are being filled, so this is declared debt
    rather than a hard equality, recorded per locale in
    scripts/i18n_backend_coverage_baseline.json. That file may only shrink.
    Alongside the count each locale carries a digest of its missing keys,
    compared only when the count is unchanged: without it a locale could
    drop one key and fill another and stay green on an unmoved number.

  * No locale answers a question en.json did not ask. The coverage check above
    runs one way only, and is blind in the other by construction: asking
    whether every English key is present can never notice a locale carrying
    keys English does not have. ar.json held twelve such keys and ru.json four,
    for months, through every gate we had. The two directions get separate
    assertions and separate messages on purpose, because a locale short of a
    key and a locale carrying a spare one are opposite faults with opposite
    fixes, and one symmetric message for both would obscure which had happened.

  * Placeholders survive translation. ``t()`` runs str.format over the value,
    so the braces are code and not text. It catches KeyError and ValueError,
    which makes a renamed field degrade to the untouched string, but it does
    not catch IndexError, so a stray ``{}`` or ``{0}`` anywhere in a locale is
    a 500 on the route that renders it.

Regenerating the baseline after filling a locale, from the repo root:

    python scripts/gen_i18n_backend_coverage_baseline.py
"""

from __future__ import annotations

import hashlib
import json
import string
from pathlib import Path

import pytest

from app.core.i18n import LOCALE_NAMES, LOCALES_DIR, SUPPORTED_LOCALES, _flatten_dict

# A genuine translation sits far below this. It exists to catch a file that is
# English wearing a foreign name, not to grade translation quality.
MAX_ENGLISH_IDENTITY = 0.80

BASELINE_PATH = Path(__file__).resolve().parents[3] / "scripts" / "i18n_backend_coverage_baseline.json"


def _load_locale(code: str) -> dict[str, str]:
    """Return the flattened key/value map for one locale file."""
    path = LOCALES_DIR / f"{code}.json"
    return _flatten_dict(json.loads(path.read_text(encoding="utf-8")))


def _locale_files() -> set[str]:
    """Return the locale codes that actually have a JSON file on disk."""
    codes = {p.stem for p in LOCALES_DIR.glob("*.json")}
    # "found nothing" and "did not look" must not produce the same verdict.
    assert codes, f"No locale files under {LOCALES_DIR} - the check would pass on an empty set"
    assert "en" in codes, f"{LOCALES_DIR} has no en.json to compare against"
    return codes


def test_supported_locales_match_the_files_on_disk() -> None:
    """A file with no list entry is unreachable; a list entry with no file serves English."""
    files = _locale_files()
    listed = set(SUPPORTED_LOCALES)
    assert listed == files, (
        f"listed but no file: {sorted(listed - files)}; file but not listed: {sorted(files - listed)}"
    )


def test_supported_locales_has_no_duplicates() -> None:
    """The set comparison above cannot see a code entered twice."""
    assert len(SUPPORTED_LOCALES) == len(set(SUPPORTED_LOCALES))


def test_locale_names_match_the_files_on_disk() -> None:
    """get_available_locales() reads LOCALE_NAMES, so it drifts on its own."""
    files = _locale_files()
    named = set(LOCALE_NAMES)
    assert named == files, f"named but no file: {sorted(named - files)}; file but unnamed: {sorted(files - named)}"


@pytest.mark.parametrize("code", sorted(_locale_files() - {"en"}))
def test_locale_is_not_mostly_english(code: str) -> None:
    """Byte-identical to en.json over most shared keys means it was never translated."""
    en = _load_locale("en")
    other = _load_locale(code)
    shared = [k for k in en if k in other]
    assert shared, f"{code}.json shares no keys with en.json"

    identical = [k for k in shared if other[k] == en[k]]
    ratio = len(identical) / len(shared)
    assert ratio <= MAX_ENGLISH_IDENTITY, (
        f"{code}.json is {ratio:.1%} byte-identical to en.json over {len(shared)} shared keys "
        f"({len(identical)} untranslated values) - that is an English file under a {code} name"
    )


@pytest.mark.parametrize("code", sorted(_locale_files() - {"en"}))
def test_locale_declares_no_key_english_lacks(code: str) -> None:
    """en.json defines the key set; a locale translates it and adds nothing.

    A spare key is unreachable rather than harmless. t() looks up the key the
    caller names, so a key no caller names is never read, and it costs nothing
    to keep only until someone reads the file and concludes the platform
    supports something it does not.

    Two kinds turned up when this was first measured. Plural variants (_few,
    _many, _two, _zero), and keys copied in from the frontend catalogue, which
    is a separate and much larger key set that this side never renders.

    The plural case needs stating carefully, because the obvious argument is
    too strong. Backend t() is a flat dictionary lookup with no plural
    resolution, so t() itself can never select a _few. But t() is not the only
    reader: app/core/i18n_router.py serves this catalogue over GET
    /i18n/{locale}, shaped for an i18next-style client, and i18next does
    resolve plurals. So the forms are unreachable because no such consumer
    exists - this product's frontend carries its own boq.mvp keys and does not
    fetch that route - and not because the shape is meaningless. If an external
    i18next client ever becomes a real consumer, the deleted Arabic and Russian
    forms are the ones you would want back; they are in history at 87e8c161c.
    """
    extra = sorted(set(_load_locale(code)) - set(_load_locale("en")))
    assert not extra, (
        f"{code}.json declares {len(extra)} key(s) that en.json does not: {extra}. "
        f"This is the opposite of a coverage gap - nothing is missing, these are spare. "
        f"Delete them from {code}.json, or add them to en.json first if the backend really "
        f"should render them, since en.json is what defines the key set."
    )


def _placeholders(value: str) -> tuple[set[str], list[str]]:
    """Split a value's str.format fields into named ones and positional ones.

    Doubled braces are not fields: ``{{count}}`` reaches the client as literal
    text and is resolved there, so only single-brace fields are the backend's.
    """
    named: set[str] = set()
    positional: list[str] = []
    for _, field, _, _ in string.Formatter().parse(value):
        if field is None:
            continue
        root = field.split(".")[0].split("[")[0]
        if root == "" or root.isdigit():
            positional.append(field)
        else:
            named.add(root)
    return named, positional


@pytest.mark.parametrize("code", sorted(_locale_files() - {"en"}))
def test_placeholders_survive_translation(code: str) -> None:
    """A translated value has to keep exactly the fields its English source had."""
    en = _load_locale("en")
    other = _load_locale(code)

    faults: list[str] = []
    for key, english in en.items():
        if key not in other:
            continue
        want, _ = _placeholders(english)
        got, positional = _placeholders(other[key])
        if positional:
            # t() catches KeyError and ValueError but not IndexError, so this
            # one does not degrade to English, it 500s the rendering route.
            faults.append(f"{key}: positional field {positional} raises IndexError in t()")
        if got != want:
            faults.append(f"{key}: expected {sorted(want)}, found {sorted(got)} in {other[key]!r}")

    assert not faults, f"{code}.json breaks interpolation:\n  " + "\n  ".join(faults)


def _read_baseline() -> dict:
    assert BASELINE_PATH.exists(), f"coverage baseline missing at {BASELINE_PATH}"
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def test_key_coverage_does_not_regress() -> None:
    """Declared coverage debt may only shrink, never grow."""
    baseline = _read_baseline()
    recorded = baseline["locales"]
    en = _load_locale("en")

    regressions: list[str] = []
    for code in sorted(_locale_files() - {"en"}):
        missing = sorted(k for k in en if k not in _load_locale(code))
        digest = hashlib.sha256("\n".join(missing).encode("utf-8")).hexdigest()[:16]

        if code not in recorded:
            # A new locale joins at zero debt; anything else has to be declared.
            if missing:
                regressions.append(f"{code}: {len(missing)} keys missing and no baseline entry")
            continue

        allowed = recorded[code]["missing"]
        if len(missing) > allowed:
            regressions.append(f"{code}: {len(missing)} keys missing, baseline allows {allowed}")
        elif len(missing) == allowed and digest != recorded[code]["digest"]:
            regressions.append(
                f"{code}: same count of {allowed} missing keys but a different set - "
                f"a key was dropped while another was filled"
            )

    assert not regressions, "backend locale coverage regressed:\n  " + "\n  ".join(regressions)


def test_baseline_declares_no_locale_that_lost_its_file() -> None:
    """A stale baseline entry would let a deleted locale pass unnoticed."""
    stale = sorted(set(_read_baseline()["locales"]) - _locale_files())
    assert not stale, f"baseline names locales with no file: {stale}"


def test_baseline_english_key_count_is_current() -> None:
    """The recorded debt is only meaningful against the en.json it was measured on."""
    baseline = _read_baseline()
    assert baseline["english_keys"] == len(_load_locale("en")), (
        "en.json changed size since the baseline was written - regenerate it with "
        "scripts/gen_i18n_backend_coverage_baseline.py"
    )
