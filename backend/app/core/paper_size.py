# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Which sheet of paper a generated document is laid out on.

``oe_users_user.paper_size`` was offered in Settings, stored, and read by no
generator in the tree, so choosing a size changed nothing. This module is the
resolver that makes it reach one, and it exists as its own leaf because the
question it answers is not "what did the user pick" but "what does this
document default to when nobody picked anything".

The default is the whole problem
--------------------------------

Two answers are both wrong. Defaulting the world to Letter prints every German
contract on a sheet no European printer tray holds; defaulting the United
States to A4 does the same thing in reverse to the country that has the largest
construction market in the product's addressable set. So the unset state is
``"auto"``, meaning "follow the country", and the country is looked up rather
than guessed.

This follows the ``'auto'`` of ``formatDateWithPreference`` in
``frontend/src/shared/lib/formatters.ts`` in shape but **deliberately not in
effect**, and the difference is worth stating because that preference's
docstring makes inertness the point. There ``'auto'`` reproduces the previous
rendering byte for byte, because the previous rendering already followed the
language. Here it cannot: the previous rendering was A4 for the entire world
regardless of country, so an inert ``'auto'`` would be the defect restated as a
default. ``'auto'`` is therefore inert everywhere except the Letter-family
countries below, which is exactly the population the defect was about.

Where the country comes from, and where it does not
---------------------------------------------------

From ``oe_projects_project.country_code``. It is the only country the product
stores: a ``User`` row carries ``locale``, which is a language and not a
country, and the distinction is not pedantic here. The interface language
``en`` declares country ``xx`` in ``SUPPORTED_LANGUAGES``, which is this
codebase's way of saying no country at all, so a resolver that read the
language would learn nothing about anyone reading in plain English. It used to
declare ``gb``, which was worse than learning nothing: an American reading the
product in English was served A4 by any resolver that read the language, and
the one country the setting exists for was the one country it got wrong.
``en-GB`` and ``en-US`` do declare a country, but only for a reader who went
and picked a region, which is not the population a default is written for.

``country_code`` is nullable and its own column comment is emphatic that NULL
means unknown rather than neutral, and that no reader may substitute a
plausible country for it. So an unknown country resolves to A4 as the
platform's metric-first default and **not** as a claim about the project. That
is a statement about this product, which ships metric first, rather than an
inference about a row that declined to say where it is.

Why this list of countries and not another
------------------------------------------

The tree already answers this question and is not read. Every regional pack
config declares a ``paper_size`` beside the ``countries`` it covers, and a
search of the whole backend for a consumer of that key returns nothing: the
pack declaration is write-only in exactly the way the user preference was.
:data:`LETTER_COUNTRIES` is therefore derived from those declarations rather
than invented here, and ``test_paper_size_defaults.py`` asserts it against them
so a pack added later cannot declare Letter without this set noticing.

Two entries need their reasoning recorded, because the derivation is not clean:

* **MX is declared twice, in conflict.** ``mexico_pack`` (``region_code`` "MX",
  ``countries`` ``["MX"]``) says Letter; ``latam_pack`` (``region_code``
  "LATAM") lists MX among six countries and says A4. The country-specific pack
  wins, because a declaration written about one country is evidence about that
  country and a declaration written about a continent is evidence about the
  continent's common case. Mexico does print business documents on Carta, so
  the specific pack is also the correct one on the merits.
* **CA is in this set and no pack declares it.** There is no Canada pack; the
  ``us_ca_pack`` that looks like one is the state of California. Canada's
  business standard is the Letter family, so leaving it out would ship the
  defect for the second of the two countries it is about. It is named here as
  the one entry the tree does not corroborate, and the test asserts that
  absence on purpose so that adding a Canada pack forces someone to look here.
"""

from __future__ import annotations

from typing import Final

#: The sizes a document can be laid out on, in points, keyed by the spelling
#: the Settings toggle stores. The four here are the four that toggle offers;
#: :data:`app.core.pdf_appearance.PAGE_SIZES` is the workspace-level appearance
#: setting and offers three of them, and it is built from this dict so the two
#: settings cannot drift on what "A4" measures.
#:
#: A3 is included because the toggle offers it. Before this module it resolved
#: nowhere, which is the same class of defect as the preference itself: a value
#: a user can pick that silently becomes a different value is worse than one
#: that is not offered.
PAPER_SIZES: Final[dict[str, tuple[float, float]]] = {
    "A4": (595.27, 841.89),
    "A3": (841.89, 1190.55),
    "LETTER": (612.0, 792.0),
    "LEGAL": (612.0, 1008.0),
}

#: The unset preference. Stored, not absent: an account that never opened
#: Settings holds this value, so "never chose" and "chose A4" stay distinct.
AUTO: Final[str] = "auto"

#: The size an unknown country gets, and the size every non-Letter country
#: gets. Named rather than inlined so the metric-first default has one home.
DEFAULT_PAPER_SIZE: Final[str] = "A4"

#: ISO 3166-1 alpha-2 countries whose business documents default to the Letter
#: family. Derived from the regional packs' own ``paper_size`` declarations;
#: see the module docstring for MX (declared twice, in conflict) and CA (not
#: declared at all).
LETTER_COUNTRIES: Final[frozenset[str]] = frozenset({"US", "CA", "MX"})

#: What a Letter-family country resolves to under ``"auto"``. Letter and not
#: Legal: Legal is a US size but not the US default, and a document that
#: arrives three inches longer than the tray expects is not a milder error.
LETTER_PAPER_SIZE: Final[str] = "LETTER"


def resolve_paper_size_name(preference: str | None, country_code: str | None) -> str:
    """Return the key into :data:`PAPER_SIZES` this document should use.

    ``preference`` is ``oe_users_user.paper_size``: ``"auto"``, one of the
    toggle's spellings ("A4", "A3", "Letter", "Legal"), or something else
    entirely, because the column is free-form ``String(10)`` with no validator
    and the regional packs seed it in their own vocabulary. Anything
    unrecognised is treated as unset rather than raising, which is the same
    never-break contract :mod:`app.core.pdf_appearance` documents: a document a
    customer is waiting for must not be lost to a settings value.

    ``country_code`` is ``oe_projects_project.country_code``, or ``None`` when
    the project did not state one. ``None`` is not read as a country.

    An explicit preference wins over the country unconditionally. A user who
    picked A4 while working on a US project meant A4; second-guessing that from
    the project's country would be the setting ignoring the setting.
    """
    if preference is not None:
        name = preference.strip().upper()
        if name in PAPER_SIZES:
            return name
    if country_code is not None and country_code.strip().upper() in LETTER_COUNTRIES:
        return LETTER_PAPER_SIZE
    return DEFAULT_PAPER_SIZE


def resolve_paper_size(preference: str | None, country_code: str | None) -> tuple[float, float]:
    """Return ``(width, height)`` in points for this document.

    The pair reportlab wants for ``pagesize=``. See
    :func:`resolve_paper_size_name` for how the two arguments are read.
    """
    return PAPER_SIZES[resolve_paper_size_name(preference, country_code)]
