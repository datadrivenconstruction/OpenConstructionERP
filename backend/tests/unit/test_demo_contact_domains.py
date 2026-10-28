# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A demo contact must carry a domain a resolver could actually use.

The German demo packs name their firms properly, umlauts and all, and the
addresses were written the same way: ``vergabe@sommerfeld-kältetechnik.de``.
A domain label cannot carry an umlaut on the wire. It has to be punycode, and
punycode on a screen reads as line noise, so the spelling a German firm
actually registers is the transliterated one. Twenty addresses across four
files were written the unusable way and read on camera as typos.

The name is not the address. ``Sommerfeld Kältetechnik GmbH`` keeps its
umlauts here and must keep them; only the part after the ``@`` is constrained,
which is why this reads the two spans separately rather than banning non-ASCII
from the file.

A source scan rather than a seeded database: the demo writers outnumber the
seeders any suite executes, so most of this data has no runtime coverage and
reading the source is the only thing that sees all of it.
"""

from __future__ import annotations

import re
from pathlib import Path

CORE = Path(__file__).resolve().parents[2] / "app" / "core"

#: Where demo contact details are authored.
SOURCES = [CORE / "demo_projects.py", *sorted((CORE / "demo_packs").glob("*.py"))]

#: The domain of an address and the host of a URL, as written in a literal.
EMAIL_DOMAIN = re.compile(r"[A-Za-z0-9._%+\-]+@([^\s\"'<>,)]+)")
URL_HOST = re.compile(r"https?://([^\s\"'<>,)/]+)")


def _offenders() -> list[str]:
    """Every authored domain that a DNS lookup could not be given as written."""
    found: list[str] = []
    for path in SOURCES:
        text = path.read_text(encoding="utf-8")
        for pattern in (EMAIL_DOMAIN, URL_HOST):
            for domain in pattern.findall(text):
                if not domain.isascii():
                    found.append(f"{path.name}: {domain}")
    return sorted(set(found))


def test_no_demo_domain_needs_punycode_to_be_valid() -> None:
    """Fold the umlauts the way the firm would when registering the domain."""
    offenders = _offenders()
    assert not offenders, "demo domains that are not resolvable as written: " + ", ".join(offenders)


def test_the_scan_reaches_the_files_it_claims_to_read() -> None:
    """A scan that reads nothing passes for the wrong reason.

    Cheap to state and it has caught worse: a walk that visited zero files and
    printed OK. If the demo pack directory is ever renamed, this fails instead
    of quietly certifying an empty set.
    """
    assert len(SOURCES) >= 4, f"expected the demo pack sources, found {[p.name for p in SOURCES]}"
    addresses = sum(len(EMAIL_DOMAIN.findall(p.read_text(encoding="utf-8"))) for p in SOURCES)
    assert addresses > 50, f"only {addresses} addresses found across {len(SOURCES)} demo sources"


def test_the_firm_names_keep_their_umlauts() -> None:
    """The fix must not have spread from the domain into the company name."""
    joined = "".join(p.read_text(encoding="utf-8") for p in SOURCES)
    assert "Kältetechnik" in joined, "a German firm name lost its umlauts along with its domain"
