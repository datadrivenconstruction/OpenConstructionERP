# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Find the country-shaped registries in the tree, without being told where they are.

:mod:`app.core.country_coverage` asks one question of every country-shaped
registry in the product. Its denominator used to be the set of probes somebody
had already written, which makes the coverage figure a measurement of the
instrument rather than of the product: a registry nobody wrote a probe for is
reported neither as covered nor as missing, and the percentage stays flattering
because the thing it does not know about is not in the divisor either.

This module supplies the divisor by walking the code. Adding a registry to the
tree moves the number here on its own, with nobody editing a list.

Why the value shape and never the field name
--------------------------------------------

A registry is recognised by the shape of what is written in it - a two-letter
uppercase string - and never by the name of the field holding it. That is not a
stylistic preference. The field name axis in this tree is at least six wide:
``country_code``, ``country_iso``, ``iso_code``, ``country``, ``jurisdiction``
and ``code`` are all in use. A first attempt at this inventory keyed on
``country_code`` and read ``i18n_foundation/seed_data/countries.json`` - 198
rows, the largest country registry in the product - as **zero countries**,
because that file spells the field ``iso_code``; the same pass missed
``CWICR_V3_CATALOGUES`` entirely, because that one spells it ``country_iso``. A
scope defined by the argument a probe happens to look for is blind to the same
argument spelled another way, so this pass does not look for a name at all.

Why there is no ISO filter, and why the denominator is inexact
--------------------------------------------------------------

The obvious sharpening is to keep only tokens that are real countries, taking
the notion of "country" from the product's own list rather than from a list
written here. It was tried and measured, and it fails in both directions.

It does remove real noise: ``eac.evm.METRIC_GLOSSARY`` (AC/CV/EV/PV/SV, earned
value metrics), ``documents.intl._DECIMAL_UNITS`` (EB/GB/MB/PB/TB, byte units)
and ``schedule_advanced.cpm.DEP_TYPE_NAMES`` (FF/FS/SF/SS, dependency types)
all fall below the threshold once non-countries are dropped.

But it also removes a registry that is real, and the flagship one:
``schedule.service.WORK_CALENDARS`` has only three country-shaped keys among
its thirteen - RU, UK and US, the rest being DACH, GULF, CANADA and FRANCE -
and "UK" is not a country code, so an ISO filter leaves two and the table falls
below the threshold. The filter loses the very registry the schedule probe
exists to read.

And it still keeps noise, because the collisions are irreducible. ``GB`` is
Great Britain and a gigabyte. ``IN`` is India and an inch. ``SA`` is Saudi
Arabia and Saturday. ``meetings.service._WEEKDAY_MAP`` keeps FR, SA and TH
through any country filter, and ``bim_hub.ifc_processor._CONVERSION_BASED_FACTORS``
keeps HR, IN and LB.

Measured against the product's own shipped list of 198 codes, 12 of the 72
registries this pass finds are under half ISO 3166, and one of them is why
``iso_hits`` exists at all. ``us_pack.config.PACK_CONFIG`` carries FL, NY, TX
and WA beside its country list, so the shape rule reads six country-shaped
tokens where the product means two. A probe already covers that registry, so it
never reaches the unprobed list, and before the annotation nothing anywhere on
the page could have told a reader that four of the six were states. That is
this census's own defect one level in: not a country nobody answered for, but a
token counted as a country by a rule that cannot see what it is.

The annotation describes and never subtracts. A near miss stays in the divisor,
because the moment a classification can remove a registry from the count, the
divisor is a hand-kept list of what somebody thought was interesting again, and
that is the thing this module was written to replace.

So no rule over the shape of the token, and no rule derived from the product's
own data, separates a country from a weekday, a byte unit or an imperial unit.
A filter tight enough to drop the weekday map also drops the work calendars.
**This pass therefore favours recall and states its noise rather than
suppressing it.** A false positive costs one line on a page a human reads; a
false negative is a registry that goes unmeasured, which is the whole defect
this file exists to close. There is deliberately no suppression list: a list of
things to ignore is the hand-maintained denominator coming back through the
side door, and the way to retire a candidate is to write a probe that records
what it actually is, next to the evidence.

What this pass cannot see
-------------------------

Stated here so a reader does not mistake the inventory for the world:

* **A registry with fewer than three country codes.** ``uk_pack``'s config
  declares one country and is invisible. Three is the lowest threshold that
  does not admit every two-letter enum in the tree, and it is what keeps
  ``WORK_CALENDARS`` (exactly three) in.
* **A population assembled at import time.** ``contracts.compliance_packs.PACK_BY_COUNTRY``
  reads as two countries here and six when imported, because four of its keys
  come from a comprehension over another table. A structural parse cannot run a
  comprehension, which is why the coverage probes read the live object wherever
  they can and say which way they read it.
* **A per-record column.** ``Contact.country_code`` is a field on a row a user
  typed, not a registry of per-country product behaviour, and models are not
  walked.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[1]

#: Distinct country-shaped tokens a literal needs before it counts as a
#: registry. See the module docstring for what three costs and what it buys.
MIN_CODES = 3

#: A floor under the shipped country list, not a count of it. The list is ~198
#: and this only has to be high enough that a file that has moved or lost its
#: field names cannot pass as a valid reference set.
_MIN_ISO_CODES = 150

#: A country-shaped token: two uppercase letters, nothing else.
_CODE = re.compile(r"^[A-Z]{2}$")

#: The same shape, as it appears quoted in source. Used only to decide whether a
#: file is worth parsing at all: parsing every one of the 2355 modules under
#: app/ costs about eighty seconds, and 77 of them hold a literal that could
#: possibly qualify. Verified to change no result - the prefiltered walk returns
#: the identical set of symbols, not merely the same count.
_QUOTED_CODE = re.compile(rb"""['"]([A-Z]{2})['"]""")


@dataclass(frozen=True)
class DiscoveredRegistry:
    """One country-shaped registry found by walking the tree."""

    #: How a probe names this registry: the dotted module path and the symbol,
    #: or the path of a seed file relative to the backend root.
    symbol: str
    #: The country-shaped tokens in it, sorted. Not necessarily countries; see
    #: the module docstring on collisions.
    codes: tuple[str, ...]
    #: Entries in the container, which is larger than ``codes`` when the
    #: registry mixes country keys with regional or named ones.
    entries: int
    #: "literal" for a module-level literal, "seed file" for JSON.
    kind: str
    #: The file it was found in, relative to the backend root. A reader told
    #: only the dotted symbol has to resolve the module themselves before they
    #: can go and look, and a red lane nobody can act on gets silenced.
    path: str
    #: How many of ``codes`` are alpha-2 codes the product itself ships. Used
    #: to describe a registry, NEVER to decide whether it is one; see
    #: ``iso_codes`` and the collision section of the module docstring.
    iso_hits: int

    @property
    def country_count(self) -> int:
        return len(self.codes)

    @property
    def iso_purity(self) -> float:
        """The share of the tokens that are countries by the product's own list."""
        return self.iso_hits / len(self.codes) if self.codes else 0.0

    @property
    def is_near_miss(self) -> bool:
        """Fewer than half the tokens are countries, so say what it really is.

        A near miss is still counted. The whole point of the census is that it
        does not carry a list of things to skip, and a flag that quietly
        removed a registry from the denominator would be that list wearing a
        different hat. This changes what the page says, not what it counts.
        """
        return self.iso_purity < 0.5

    @property
    def non_iso(self) -> tuple[str, ...]:
        """The tokens that are not countries, which is what a reader wants named."""
        shipped = iso_codes()
        return tuple(code for code in self.codes if code not in shipped)


@lru_cache(maxsize=1)
def iso_codes() -> frozenset[str]:
    """The alpha-2 codes the product itself ships.

    Read by field name, which the discovery pass above deliberately refuses to
    do, and the difference is the point rather than an inconsistency. Discovery
    walks files it has never seen and cannot know what any of them call the
    field, which is how a first pass at this read a 198-row country list as
    zero countries. This reads ONE named file with a schema this repository
    owns, to build a reference list to describe the others against.

    Raises:
        RuntimeError: When the list comes back implausibly short. A reference
            set that silently arrives near-empty would mark every registry in
            the tree a near miss, and a count from a reader with a fallback is
            a fact about the reader rather than about the product.

    Returns:
        The codes, uppercased.
    """
    path = _APP_ROOT / "modules/i18n_foundation/seed_data/countries.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else next(iter(data.values()), [])
    found = {
        value.upper()
        for row in rows
        if isinstance(row, dict)
        for key, value in row.items()
        if isinstance(value, str) and _CODE.match(value.upper()) and ("iso" in key.lower() or key.lower() == "code")
    }
    if len(found) < _MIN_ISO_CODES:
        raise RuntimeError(
            f"the shipped country list came back as {len(found)} codes from {path}, which is too few to "
            "describe anything against; the file or its field names have moved"
        )
    return frozenset(found)


def _codes_in(node: ast.AST) -> set[str]:
    """Every country-shaped string constant anywhere inside a literal.

    Walked rather than read off the keys, because a registry keeps its country
    codes wherever it likes: as dict keys (``_HOLIDAY_FUNCS``), as the value of
    a field on a row (``CWICR_V3_CATALOGUES`` spells it ``country_iso``), or as
    a list under a key (a regional pack's ``countries``). Anything narrower
    would encode a guess about where the codes sit, which is the same mistake as
    guessing what the field is called.

    Args:
        node: The value node of a module-level assignment.

    Returns:
        The distinct country-shaped tokens found, in no order.
    """
    return {
        sub.value
        for sub in ast.walk(node)
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and _CODE.match(sub.value)
    }


def _module_registries(path: Path, dotted: str) -> list[DiscoveredRegistry]:
    """Country-shaped module-level literals in one file.

    Args:
        path: The file to read.
        dotted: Its dotted module path.

    Returns:
        One entry per qualifying module-level assignment, possibly empty.
    """
    blob = path.read_bytes()
    if len(set(_QUOTED_CODE.findall(blob))) < MIN_CODES:
        return []
    try:
        tree = ast.parse(blob.decode("utf-8", errors="replace"), filename=str(path))
    except SyntaxError:
        # A file that will not parse is not a registry that was missed; it is a
        # file that no interpreter could read either, and it will announce
        # itself long before this pass runs.
        return []

    found: list[DiscoveredRegistry] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            names = [node.target.id]
        else:
            continue
        value = getattr(node, "value", None)
        if not names or not isinstance(value, ast.Dict | ast.Tuple | ast.List):
            continue
        codes = _codes_in(value)
        if len(codes) < MIN_CODES:
            continue
        entries = len(value.keys) if isinstance(value, ast.Dict) else len(value.elts)
        found.append(
            DiscoveredRegistry(
                symbol=f"{dotted}.{names[0]}",
                codes=tuple(sorted(codes)),
                entries=entries,
                kind="literal",
                path=path.relative_to(_APP_ROOT.parent).as_posix(),
                iso_hits=len(codes & iso_codes()),
            )
        )
    return found


def _seed_registries(path: Path) -> DiscoveredRegistry | None:
    """A seed file, when its rows carry country-shaped values.

    The prefilter is not applied here: seed files are few and are read whole
    anyway, and a JSON file has no cheap textual tell that a module has.

    Args:
        path: The JSON file to read.

    Returns:
        The registry, or None when the file holds no rows or too few codes.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rows = next(iter(data.values()), None) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return None
    codes = {
        value
        for row in rows
        if isinstance(row, dict)
        for value in row.values()
        if isinstance(value, str) and _CODE.match(value)
    }
    if len(codes) < MIN_CODES:
        return None
    return DiscoveredRegistry(
        symbol=path.relative_to(_APP_ROOT.parent).as_posix(),
        codes=tuple(sorted(codes)),
        entries=len(rows),
        kind="seed file",
        path=path.relative_to(_APP_ROOT.parent).as_posix(),
        iso_hits=len(codes & iso_codes()),
    )


@lru_cache(maxsize=1)
def discover_registries() -> tuple[DiscoveredRegistry, ...]:
    """Every country-shaped registry in the tree, found by walking it.

    Cached for the life of the process. The walk reads every module under
    ``app/`` once, which is a second or two warm and can be minutes on a cold
    or heavily contended filesystem, and no caller needs it twice.

    Returns:
        The registries, ordered by how many country-shaped tokens each holds,
        largest first, then by symbol so the order is stable.
    """
    found: list[DiscoveredRegistry] = []
    for path in _APP_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        dotted = "app." + ".".join(path.relative_to(_APP_ROOT).with_suffix("").parts)
        found.extend(_module_registries(path, dotted))
    for path in sorted(_APP_ROOT.rglob("seed_data/*.json")):
        seed = _seed_registries(path)
        if seed is not None:
            found.append(seed)
    return tuple(sorted(found, key=lambda r: (-r.country_count, r.symbol)))
