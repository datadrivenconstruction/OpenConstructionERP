# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A pack must not boot the generic parent of a locale it ships itself.

``default_locale`` is not documentation. The onboarding wizard hands it
straight to the language switcher (``onActivateLocale(pack.default_locale)`` in
frontend/src/features/onboarding/OnboardingWizard.tsx), so it is the language a
person sees the moment they finish picking their country.

The frontend resolver already does the right thing with a region subtag:
``matchSupportedLanguage`` in frontend/src/app/i18n.ts prefers ``pt-BR`` over
``pt`` whenever the platform offers it, and its docstring records the first
round of this defect - a Brazilian first run opening in European Portuguese
"with pt-BR.ts sitting unused a few lines away". The resolver can only prefer a
region it is given. The Mexico pack declared the bare ``es`` while shipping its
own ``locales/es-MX.json`` and while the platform offered a complete ``es-MX``
bundle, so the same failure survived one layer up, in the manifest: costo read
as coste, cimbra as encofrado, estimacion de obra as certificacion de obra.

This gate asks the question of every shipped pack rather than of Mexico, and it
asks it of the two lists that actually decide - the platform's
``SUPPORTED_LANGUAGES`` and the pack's own ``additional_locales`` - so a pack
added later cannot re-open it. The population is asserted so a gate that stops
finding any packs to check fails instead of passing quietly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.partner_pack.discovery import discover_packs

#: The registration list the UI language switcher is built from. Parsed rather
#: than duplicated: a hand-kept copy in this file would drift the first time a
#: language is offered or withdrawn, and it is exactly the drift between two
#: mirrors of one registry that this test is about.
_I18N_TS = Path(__file__).resolve().parents[3] / "frontend" / "src" / "app" / "i18n.ts"

_CODE = re.compile(r"^\s*\{\s*code:\s*'([A-Za-z-]+)'", re.MULTILINE)

#: The wheel ships ``app`` and ``packs`` without ``frontend``, so the file this
#: gate parses is a source-checkout fact. Skipping there is the honest answer:
#: the alternative is an error that reads as a broken gate, and a hand-kept copy
#: of the language list in this file is the exact drift the gate is about.
pytestmark = pytest.mark.skipif(
    not _I18N_TS.is_file(),
    reason=f"{_I18N_TS} is absent (installed layout, not a source checkout)",
)


def _offered_languages() -> list[str]:
    """Every language code the switcher offers, in declaration order.

    Only entries inside the ``SUPPORTED_LANGUAGES`` array count. A language
    whose bundle exists on disk but is commented out of that array - Mongolian
    today - is deliberately not offered and must not be treated as available.
    """
    text = _I18N_TS.read_text(encoding="utf-8")
    start = text.index("export const SUPPORTED_LANGUAGES")
    end = text.index("\n];", start)
    return _CODE.findall(text[start:end])


def _match_supported(raw: str, offered: set[str]) -> str | None:
    """The Python twin of ``matchSupportedLanguage`` in i18n.ts.

    Region first, then the base language. Kept deliberately short so it stays
    readable against the original; the original is the authority and this
    exists so the backend can answer the same question about pack manifests.
    """
    parts = raw.strip().split("-")
    if len(parts) >= 2 and parts[1]:
        regional = f"{parts[0].lower()}-{parts[1].upper()}"
        if regional in offered:
            return regional
    base = parts[0].lower()
    return base if base in offered else None


def test_the_offered_language_list_is_readable() -> None:
    """Guard the parser: a silent zero here would wave every pack through."""
    offered = _offered_languages()
    assert len(offered) >= 30, f"parsed only {len(offered)} offered languages from {_I18N_TS}"
    assert "en" in offered
    assert "es-MX" in offered, "es-MX is the case this file was written for"
    assert "mn" not in offered, "Mongolian is deliberately not offered; the parser must not pick it up"


def test_no_pack_boots_the_parent_of_a_locale_it_ships() -> None:
    """A pack that carries a regional bundle has to boot into it."""
    offered = set(_offered_languages())
    packs = list(discover_packs())
    assert packs, "no packs discovered - the gate would pass on an empty population"

    checked: list[str] = []
    offenders: list[str] = []
    for m in packs:
        declared = (m.default_locale or "").strip()
        for shipped in m.additional_locales or {}:
            if shipped not in offered:
                # The pack ships a bundle for a language the platform does not
                # offer. Serving it is the streaming endpoint's business; it
                # cannot be a boot default, so it is not this gate's business.
                continue
            if "-" not in shipped:
                continue
            checked.append(f"{m.slug}:{shipped}")
            if shipped.split("-", 1)[0].lower() == declared.lower():
                offenders.append(
                    f"{m.slug} declares default_locale={declared!r} while shipping {shipped!r}, "
                    f"which the platform offers - the workspace boots into the generic parent"
                )

    assert checked, "no pack ships an offered regional bundle - population is empty, gate proves nothing"
    assert not offenders, "; ".join(offenders)


@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        ("mexico-mx", "es-MX"),
        ("brazil-sinapi", "pt-BR"),
    ],
)
def test_the_declared_locale_survives_the_frontend_resolver(slug: str, expected: str) -> None:
    """Named individually: a population floor stays green while one pack slips.

    Brazil is here as the control. It was already right, and it is the pack the
    resolver's own docstring cites, so a change that broke the parsing above
    would take both rows down together rather than leave Mexico looking fine.
    """
    offered = set(_offered_languages())
    m = next((p for p in discover_packs() if p.slug == slug), None)
    assert m is not None, f"{slug} is not discoverable"
    assert _match_supported(m.default_locale, offered) == expected
