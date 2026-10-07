# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Ask one question of every country-shaped registry in the product.

The product has several registries that vary by country, each invented where it
was needed and each with its own shape: a tuple of dicts with a ``country_code``
field, a dict keyed by region code with a ``DEFAULT`` entry, a dict of functions,
a seeded JSON file. Nothing could answer "is Canada covered", and the answer
turned out to be "it has a working calendar and no payment regime" - which
nobody had noticed, because there was nowhere to look.

**This module centralises the question and not the data.** Every registry stays
where it is and keeps its own shape; a probe here knows how to ask it. Adding a
country is still an edit in the owning module. That is the plugin principle and
this file does not trade it.

Reading a report
----------------

The six verdicts are deliberately not collapsible into "yes / no", because the
useful distinctions are between the shades of no:

``COVERED``      the registry has a row of this country's own.
``FALLBACK``     something resolves for this country, but by default or alias
                 rather than on its own terms. A caller sees an answer and
                 cannot tell it was not written for them.
``MISSING``      the registry is country-keyed, is populated, and this country
                 is not in it.
``NOT_KEYED``    the registry exists and has no country axis at all, so the
                 question cannot be put to it. Wanting a per-country answer here
                 means changing its shape, not adding a row.
``ABSENT``       no such registry exists anywhere in the product.
``UNRESOLVED``   the probe could not answer. An import failed, a symbol moved,
                 or a shape changed.

``UNRESOLVED`` is counted separately from ``MISSING`` everywhere, and that
separation is the point of the file. An instrument that reports what it could
not measure as an absence tells you a comfortable lie: it converts "I do not
know" into "there is nothing there", and the second reads as a finished
question. Unmeasured and fine are different words.

An empty population is treated as ``UNRESOLVED`` rather than as "every country
is missing", for the same reason. A probe that finds nothing at all has almost
certainly broken, and a registry that genuinely emptied is worth the same alarm.

Writing a probe
---------------

**A probe has to be able to answer without a database.** That is not a taste in
dependencies, it is a constraint the repository enforces from somewhere you
will not find by reading this file. ``.github/workflows/repo-hygiene.yml:550``,
the step named "Check the instrument runs and no country has fallen to zero"
(grep the step name, the line number will drift), runs
``backend/scripts/country_coverage.py --strict --ignore-unprobed`` in a lane
with no PostgreSQL service that sets no ``DATABASE_URL``. Read what that
flag does and does not do: it suppresses exit 3, the code for a census with
registries nobody probes, and it does **not** suppress exit 1, the code for a
probe that could not resolve its registry. So an import-only probe does not
merely lose a row on a developer's laptop. It takes a green lane red on the
commit that adds it, for a reason that says nothing about the product.

This is easy to walk into, and was walked into: ``demo.catalogue_projects``
below was written import-only and would have done exactly this. Worse, the
failure mode selects for the interesting registries - the ones worth probing
are disproportionately the ones whose module reaches an ORM import and builds
an engine before any literal in it is reachable.

So a probe reads its registry through one of the two-path helpers, which import
where an import is available and parse the file where it is not, and label the
reading either way so a source read is never printed as though the live object
had answered: :func:`_registry_literal` for a plain literal,
:func:`_annotated_attributes` for class attributes, :func:`_isolated_namespace`
for a registry that has to be executed to exist. Where a registry is assembled
at runtime and no literal holds the answer, rebuild the assembly from the same
files the product reads and pin the rebuild against the import with a test -
:func:`_demo_catalogue_countries` is the worked example.

Before shipping a probe, run that lane's argv with no database and read the
printed output rather than the exit code. "instrument healthy: every probe
resolved its registry" is the line that says you have not broken it.
"""

from __future__ import annotations

import ast
import importlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from app.core.country_registries import DiscoveredRegistry, discover_registries

logger = logging.getLogger(__name__)

_APP_ROOT = Path(__file__).resolve().parents[1]

COVERED = "covered"
FALLBACK = "fallback"
MISSING = "missing"
NOT_KEYED = "not_keyed"
ABSENT = "absent"
UNRESOLVED = "unresolved"

#: Verdicts that mean the probe produced an answer about this country.
ANSWERED = (COVERED, FALLBACK, MISSING, NOT_KEYED, ABSENT)

#: What a country's row says when another country is on it too. Unlike the
#: shared spans in app.core.calendar, a shared row here is not a stand-in for an
#: unknown value: DACH and GULF are real regional weeks, written deliberately
#: for every country on them, so the verdict stays COVERED. It is recorded
#: because it is a limit rather than a defect. Per-country divergence has
#: nowhere to go until the row is split, which is how three Gulf states were
#: once given the wrong weekend, and a limit nobody counted is one that gets
#: rediscovered rather than remembered.
SHARED_ROW = "SHARED_ROW"


@dataclass(frozen=True)
class DimensionReport:
    """One registry's answer about one country."""

    dimension: str
    verdict: str
    detail: str
    #: Countries this registry knows, when it is country-keyed. Empty otherwise.
    population: tuple[str, ...] = ()
    #: Other countries that land on this country's row, when the registry has
    #: rows and this one is shared. Empty when the row is this country's alone,
    #: or when the registry has no notion of a row. See SHARED_ROW.
    shares_row_with: tuple[str, ...] = ()
    #: Where the registry lives, so a reader can go and look.
    source: str = ""
    #: How the probe got the value. "import" is the object the product runs on.
    #: "source" is the file on disk, either parsed for a structural question or
    #: executed for a behavioural one; where it was read because a module would
    #: not import, the exception is named in the string. "declared" means the
    #: verdict was reasoned out here because no registry exists to read, and it
    #: names that reason in parentheses the same way. The reporter groups on the
    #: whole string, so a second reason to declare something forms its own group
    #: rather than borrowing this one's explanation and being described wrongly.
    #: "(none)" means the probe raised and read nothing.
    #: The default is "import", so a probe that imports nothing has to say so.
    #: Inheriting the default silently makes a report claim evidence it never
    #: had, and the reporter then counts it among the strongest readings.
    method: str = "import"

    @property
    def answered(self) -> bool:
        return self.verdict in ANSWERED


@dataclass
class CountryReport:
    """Every registry's answer about one country."""

    country_code: str
    dimensions: list[DimensionReport] = field(default_factory=list)

    def by_verdict(self, verdict: str) -> list[DimensionReport]:
        return [d for d in self.dimensions if d.verdict == verdict]

    @property
    def counts(self) -> dict[str, int]:
        out = dict.fromkeys((*ANSWERED, UNRESOLVED), 0)
        for d in self.dimensions:
            out[d.verdict] = out.get(d.verdict, 0) + 1
        return out

    @property
    def shared_rows(self) -> list[DimensionReport]:
        """Dimensions that answered for this country off a row it does not own."""
        return [d for d in self.dimensions if d.shares_row_with]

    def summary(self) -> str:
        """One line, with unresolved kept out of the covered/missing arithmetic."""
        c = self.counts
        return (
            f"{self.country_code}: {c[COVERED]} covered, {c[FALLBACK]} fallback, "
            f"{c[MISSING]} missing, {c[NOT_KEYED]} not country-keyed, "
            f"{c[ABSENT]} absent, {c[UNRESOLVED]} UNRESOLVED, "
            f"{len(self.shared_rows)} on a shared row"
        )


# --------------------------------------------------------------------------- #
# Probe plumbing
#
# A probe returns a DimensionReport. It never raises: _run wraps it, so a moved
# symbol or a changed shape becomes UNRESOLVED with the reason attached rather
# than an absence or a traceback. That wrapper is the only reason a caller can
# trust the difference between "missing" and "could not tell".
# --------------------------------------------------------------------------- #

Probe = Callable[[str], DimensionReport]

_PROBES: list[tuple[str, Probe]] = []

#: Dimension name to the registry symbols that dimension answers for, named the
#: way :func:`app.core.country_registries.discover_registries` names them. This
#: is what lets the census subtract: discovered minus covered is the set of
#: registries nobody is asking about, and it is computed rather than recorded.
#: A probe with no symbols is one with no registry to name - see
#: security_of_payment.deadlines, which is declared from a reading of the tree.
_COVERS: dict[str, tuple[str, ...]] = {}


def _probe(name: str, covers: tuple[str, ...] = ()) -> Callable[[Probe], Probe]:
    """Register a probe and record which registries it answers for.

    Args:
        name: The dimension name, unique across the manifest.
        covers: Registry symbols this probe reads, spelled as
            ``discover_registries`` spells them: a dotted module path plus the
            symbol, or a seed file's path relative to the backend root. Naming
            one that does not exist is harmless to the arithmetic and is caught
            by a test, because a probe claiming to cover a registry that is not
            there is how a symbol rename would go quiet.

    Returns:
        The decorator.
    """

    def register(fn: Probe) -> Probe:
        _PROBES.append((name, fn))
        _COVERS[name] = covers
        return fn

    return register


def _run(name: str, fn: Probe, country: str) -> DimensionReport:
    try:
        return fn(country)
    except Exception as exc:  # noqa: BLE001 - any failure is "could not tell", never "absent"
        logger.debug("country-coverage probe %s failed", name, exc_info=True)
        return DimensionReport(
            dimension=name,
            verdict=UNRESOLVED,
            detail=f"probe raised {type(exc).__name__}: {exc}",
            # Not the "import" default: this probe read nothing whatsoever, and
            # a report that inherits the default is counted on the page as
            # evidence taken from the live module.
            method="(none)",
        )


# --------------------------------------------------------------------------- #
# Resolving a registry that lives in a module you cannot import
#
# Several of these registries are plain literals sitting in a service module,
# and importing that module pulls in the database configuration. On a developer
# machine with no cluster running, three probes came back UNRESOLVED for that
# reason alone - which is honest but useless, because the registries themselves
# are static and perfectly readable.
#
# So: import first, because that reads the object the product actually runs on,
# and read the file directly when the import will not come - by parse for a
# structural question, or by executing the registry's own definitions alone for
# a behavioural one. The report says which one answered, because an import and
# a read of the file on disk are not equally good evidence.
#
# WHERE A SOURCE READ IS ALLOWED, AND WHERE IT IS NOT. Parsing a table answers
# structural questions - does this table have a country axis at all, how many
# rungs does this ladder have - because those are properties of what is
# written. It must never stand in for a behavioural question by reading a table
# the behaviour does not read directly, because behaviour can sit in aliasing
# layers the table knows nothing about. calendar.schedule_regions is the worked
# example: sixteen of the eighteen countries on its axis are not keys of the
# table at all, so a membership test on the table calls sixteen countries
# uncovered while the resolver returns a real calendar for every one of them.
#
# Executing the resolver itself is a different act and is allowed. When the
# owning module will not import, that probe runs get_work_calendar and the maps
# it reads, alone, out of the same file - the product's own behaviour, run
# rather than guessed at from a neighbouring table. It is still labelled
# "source", because what ran is the file on disk and not the object the live
# process is holding.
#
# WHY A PROBE IS STILL ALLOWED TO REFUSE. If the import succeeds and the symbol
# is gone, the AttributeError propagates and the dimension comes back
# UNRESOLVED. Read that as the instrument working, not as a bug in it. A
# renamed registry is a real finding about the tree, and the second path exists
# to survive a missing database rather than to route around a missing name:
# reaching for it there would turn "this registry moved" into a confident
# answer assembled out of whatever the old name still matched. A probe that
# refuses is a probe reporting that it could not measure, which is the one
# thing this whole file is for.
# --------------------------------------------------------------------------- #


def _source_of(dotted: str) -> Path:
    if not dotted.startswith("app."):
        raise LookupError(f"{dotted} is outside the app package")
    return _APP_ROOT.joinpath(*dotted.split(".")[1:]).with_suffix(".py")


def _module_level_node(dotted: str, symbol: str) -> ast.AST:
    path = _source_of(dotted)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.ClassDef) and node.name == symbol:
            return node
        if any(isinstance(t, ast.Name) and t.id == symbol for t in targets):
            value = getattr(node, "value", None)
            if value is None:
                raise LookupError(f"{symbol} in {dotted} is annotated but never assigned")
            return value
    raise LookupError(f"{symbol} is not defined at module level in {dotted}")


def _bound_names(node: ast.stmt) -> set[str]:
    """Module-level names one statement binds.

    Args:
        node: A statement from a module body.

    Returns:
        The names the statement binds at module level, empty for statements that
        bind nothing.
    """
    if isinstance(node, ast.Assign):
        return {t.id for t in node.targets if isinstance(t, ast.Name)}
    if isinstance(node, ast.AnnAssign):
        return {node.target.id} if isinstance(node.target, ast.Name) and node.value is not None else set()
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return {node.name}
    if isinstance(node, ast.Import | ast.ImportFrom):
        return {alias.asname or alias.name.split(".")[0] for alias in node.names}
    return set()


def _isolated_namespace(dotted: str, wanted: tuple[str, ...]) -> dict[str, object]:
    """Execute the named module-level definitions, and their dependencies, alone.

    For a registry whose owning module cannot be imported - typically because
    importing it builds a database engine - but whose registry and resolver are
    pure module-level code. The closure of module-level names the wanted symbols
    reach is collected, and only those statements are executed, so the import
    that blocks the module never runs unless something wanted needs it.

    This runs the product's own code rather than a parse of a table that code
    reads, which is why a resolver probe is allowed to use it where a table
    parse would be a known-bad proxy. The caller must still label the result
    "source": the file on disk ran, not the live module.

    Args:
        dotted: Dotted path of a module inside the app package.
        wanted: Module-level symbol names the caller needs.

    Returns:
        The namespace the selected statements executed in, holding at least
        every name in ``wanted``.

    Raises:
        LookupError: A wanted name, or a name it reaches, is not bound exactly
            once at module level. Twice means the probe cannot tell which
            binding the module ends up running on, and a stale one read
            silently is the failure this whole file exists to prevent.
    """
    path = _source_of(dotted)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    defining: dict[str, list[ast.stmt]] = {}
    for node in tree.body:
        for name in _bound_names(node):
            defining.setdefault(name, []).append(node)

    needed: set[str] = set()
    queue = list(wanted)
    while queue:
        name = queue.pop()
        if name in needed:
            continue
        found = defining.get(name, [])
        if len(found) != 1:
            raise LookupError(f"{name} is bound {len(found)} times at module level in {dotted}, expected once")
        needed.add(name)
        # Every module-level name the statement reads is part of the closure. A
        # function local that happens to share a module-level name pulls that
        # statement in too, which costs one extra definition and no correctness.
        queue.extend(
            sub.id
            for sub in ast.walk(found[0])
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load) and sub.id in defining
        )

    selected = [node for node in tree.body if _bound_names(node) & needed]
    module = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
    namespace: dict[str, object] = {"__name__": f"{dotted}:isolated", "__file__": str(path)}
    exec(compile(module, str(path), "exec"), namespace)
    return namespace


def _annotated_attributes(dotted: str, symbol: str) -> tuple[set[str], str]:
    """Annotated attribute names of a class, by import if possible and by parse if not."""
    try:
        module = importlib.import_module(dotted)
    except Exception as exc:  # noqa: BLE001
        node = _module_level_node(dotted, symbol)
        if not isinstance(node, ast.ClassDef):
            raise LookupError(f"{symbol} in {dotted} is not a class") from exc
        names = {b.target.id for b in node.body if isinstance(b, ast.AnnAssign) and isinstance(b.target, ast.Name)}
        if not names:
            raise LookupError(f"{symbol} in {dotted} has no annotated attributes to read") from exc
        return names, f"source ({type(exc).__name__} on import)"
    return {c.name for c in getattr(module, symbol).__table__.columns}, "import"


def _registry_literal(dotted: str, symbol: str) -> tuple[object, str]:
    """A module-level literal registry, by import if possible and by parse if not.

    The same two-path shape as :func:`_annotated_attributes`, for the registries
    that are plain dict or list literals. Import first, because that reads the
    object the product actually runs on; parse the file only when the import
    will not come, which for a module that builds a database engine at import
    time is every developer machine without a cluster.

    Args:
        dotted: Dotted path of a module inside the app package.
        symbol: A module-level name bound to a literal.

    Returns:
        The registry, and the method string a report has to carry. A report that
        inherits the ``"import"`` default after a source read claims evidence it
        never had, which the reporter then counts among its strongest readings.

    Raises:
        AttributeError: The module imported and the symbol is gone. Deliberately
            not caught: reaching for the parse here would answer a renamed
            registry out of whatever the old name still matched, and a renamed
            registry is a real finding about the tree.
        LookupError: The module would not import and the symbol is not defined
            at module level, or is no longer a literal this probe can evaluate.
    """
    try:
        module = importlib.import_module(dotted)
    except Exception as exc:  # noqa: BLE001 - having no cluster is an ordinary state, not a finding
        node = _module_level_node(dotted, symbol)
        try:
            value = ast.literal_eval(node)
        except ValueError as bad:
            raise LookupError(f"{symbol} in {dotted} is not a literal this probe can evaluate") from bad
        return value, f"source ({type(exc).__name__} on import)"
    # Outside the handler on purpose, the same way the schedule registry does it.
    return getattr(module, symbol), "import"


def _keyed(
    dimension: str,
    source: str,
    population: set[str] | frozenset[str],
    country: str,
    *,
    fallback_note: str = "",
    method: str = "import",
) -> DimensionReport:
    """Standard verdict for a country-keyed registry.

    An empty population is UNRESOLVED, not "everyone is missing": a probe that
    resolved its symbol and then found nothing in it has more likely lost the
    shape than discovered an empty world.
    """
    members = tuple(sorted(population))
    if not members:
        return DimensionReport(
            dimension=dimension,
            verdict=UNRESOLVED,
            detail="registry resolved but its population is empty; the probe has probably lost the shape",
            source=source,
            method=method,
        )
    if country in population:
        return DimensionReport(
            dimension=dimension,
            verdict=COVERED,
            detail=f"a row of its own, among {len(members)} countries",
            population=members,
            source=source,
            method=method,
        )
    verdict = FALLBACK if fallback_note else MISSING
    detail = fallback_note or f"country-keyed and populated ({len(members)}), and this country is not in it"
    return DimensionReport(
        dimension=dimension,
        verdict=verdict,
        detail=detail,
        population=members,
        source=source,
        method=method,
    )


# --------------------------------------------------------------------------- #
# Calendars: four registries, deliberately probed as four.
#
# These are not one dimension wearing four hats. They were written
# independently, they are read by different callers, and they have disagreed
# with each other in production - a country has been correct in one and aliased
# to another country in a second. Collapsing them into a single "calendar" row
# would hide exactly the disagreement this file exists to surface.
# --------------------------------------------------------------------------- #


@_probe("calendar.holiday_functions", covers=("app.core.calendar._HOLIDAY_FUNCS",))
def _holiday_functions(country: str) -> DimensionReport:
    from app.core.calendar import _HOLIDAY_FUNCS

    return _keyed(
        "calendar.holiday_functions",
        "app.core.calendar._HOLIDAY_FUNCS",
        set(_HOLIDAY_FUNCS),
        country,
    )


@_probe("calendar.working_week", covers=("app.core.calendar._WORKING_WEEK",))
def _working_week(country: str) -> DimensionReport:
    from app.core.calendar import _WORKING_WEEK

    return _keyed(
        "calendar.working_week",
        "app.core.calendar._WORKING_WEEK",
        set(_WORKING_WEEK),
        country,
    )


_SCHEDULE_SERVICE = "app.modules.schedule.service"

#: What the schedule probe needs out of that module: the table, the resolver
#: standing in front of it, and the ISO axis that says which countries to ask.
_SCHEDULE_WANTED = ("WORK_CALENDARS", "_get_work_week", "_CALENDAR_BY_COUNTRY")


def _schedule_registry() -> tuple[dict, Callable[[str], dict], dict[str, str], str]:
    """The schedule calendars, their resolver and their country axis, and how they were read.

    Imports the owning module when it will import. When it will not - which off
    a cluster is every developer machine, because importing it reaches
    ``app.database`` and that builds an engine at import time - the module-level
    definitions those three names reach are executed alone out of the same file.

    Returns:
        The calendar table, the resolver, the ISO-code axis, and the method
        string a report should carry.

    Raises:
        AttributeError: The module imported and one of the names is gone.
            Deliberately not caught; see the source-read policy above.
        LookupError: The module would not import and a name is not bound
            exactly once at module level in the file.
    """
    try:
        module = importlib.import_module(_SCHEDULE_SERVICE)
    except Exception as exc:  # noqa: BLE001 - having no cluster is an ordinary state, not a finding
        namespace = _isolated_namespace(_SCHEDULE_SERVICE, _SCHEDULE_WANTED)
        method = f"source ({type(exc).__name__} on import)"
        return (
            namespace["WORK_CALENDARS"],
            namespace["_get_work_week"],
            namespace["_CALENDAR_BY_COUNTRY"],
            method,
        )
    # Outside the handler on purpose: if the import worked and a name has moved,
    # that AttributeError is the finding and must not reach the fallback.
    # The public calendar now adds a country holiday callable to a copy. This
    # dimension measures the regional working week; holiday coverage is a
    # separate probe. Read the very same week resolver used by that wrapper.
    return module.WORK_CALENDARS, module._get_work_week, module._CALENDAR_BY_COUNTRY, "import"


def _calendar_rows(calendars: dict, resolve: Callable[[str], dict], axis: dict[str, str]) -> dict[str, tuple[str, ...]]:
    """Group the countries on the axis by the calendar the resolver returns for each.

    Grouped by the identity of the object that comes back rather than by the
    axis map's values, because the resolver reads more maps than the axis and
    the resolver is what callers use. Two codes that reach one row by different
    routes are then still counted as one row rather than two.

    Args:
        calendars: The calendar table, whose dicts are the objects compared.
        resolve: The resolver.
        axis: The ISO-code axis. Read only for which countries to ask about,
            which is a structural question and so a fair thing to read it for.

    Returns:
        Row name to the sorted country codes that land on it.
    """
    named = {id(calendar): name for name, calendar in calendars.items()}
    rows: dict[str, list[str]] = {}
    for code in sorted(axis):
        rows.setdefault(named[id(resolve(code))], []).append(code)
    return {name: tuple(codes) for name, codes in rows.items()}


@_probe(
    "calendar.schedule_regions",
    covers=(
        "app.modules.schedule.service.WORK_CALENDARS",
        "app.modules.schedule.service._CALENDAR_BY_COUNTRY",
        "app.modules.schedule.service._CALENDAR_BY_LEGACY_HEAD",
    ),
)
def _schedule_calendar(country: str) -> DimensionReport:
    """Ask the resolver, because reading this table gives the wrong answer.

    ``WORK_CALENDARS`` is not keyed by country. Its keys are a mixed vocabulary
    - ISO codes (``US``, ``RU``), a non-ISO abbreviation (``UK``, where ISO says
    ``GB``), regional blocs (``DACH``, ``GULF``) and English country names
    (``CANADA``, ``FRANCE``) - and ``get_work_calendar`` puts three aliasing
    layers in front of it: a whole-label map, and two head maps that cannot
    overlap, one holding ISO country codes and one holding superseded catalogue
    codes that are not and cannot be ISO codes. So membership of the table is
    not the question a caller asks.

    Measured, and stated as a property of the registry rather than of whichever
    countries someone happened to ask about: of the eighteen countries on
    ``_CALENDAR_BY_COUNTRY``, sixteen are not keys of ``WORK_CALENDARS`` at all.
    A membership test on the table calls those sixteen uncovered while the
    resolver returns a real calendar for every one of them. Only ``US`` and
    ``RU`` are spelled the same way in both. Counted over a cohort instead, the
    same fact comes out as five, or ten, or sixteen depending on who was asked,
    which is how a number like this goes stale with nobody having edited it.

    Hence: no reading of the table as a proxy, ever. What the probe does when
    the module will not import is execute the resolver, and the maps it reads,
    alone out of that same file, and put the question to those - the product's
    own behaviour, run rather than guessed at from a neighbouring table, so the
    answer is the one the imported module gives. The report says "source"
    because what ran is the file on disk and not the live module.

    A renamed registry still ends as UNRESOLVED from either direction: the
    attribute lookup in :func:`_schedule_registry` sits outside its handler so
    its AttributeError propagates, and the isolated read raises ``LookupError``
    for a name it cannot find bound exactly once. That is a real finding about
    the tree, and the second path exists to survive a missing database rather
    than to route around a missing name.
    """
    source = "app.modules.schedule.service._get_work_week"
    calendars, resolve, axis, method = _schedule_registry()
    known = tuple(sorted(k for k in calendars if k != "DEFAULT"))
    # Identity, not equality: "has a row of its own" is a question about which
    # object came back, and the resolver returns the table's own dicts.
    calendar = resolve(country)
    if calendar is calendars["DEFAULT"]:
        return DimensionReport(
            dimension="calendar.schedule_regions",
            verdict=FALLBACK,
            detail=(
                "the resolver falls through to WORK_CALENDARS['DEFAULT'] for this code; the caller gets a "
                f"working week and cannot tell it was not theirs ({len(known)} regions are named, none matches)"
            ),
            population=known,
            source=source,
            method=method,
        )
    row = next(name for name, cal in calendars.items() if cal is calendar)
    shares = tuple(c for c in _calendar_rows(calendars, resolve, axis).get(row, ()) if c != country)
    detail = f"the resolver returns the {row} calendar for this code, among {len(known)} regions"
    if shares:
        detail += f"; {SHARED_ROW} with {', '.join(shares)}, so the row is not this country's alone"
    return DimensionReport(
        dimension="calendar.schedule_regions",
        verdict=COVERED,
        detail=detail,
        shares_row_with=shares,
        population=known,
        source=source,
        method=method,
    )


@_probe(
    "calendar.seeded_rows",
    covers=("app/modules/i18n_foundation/seed_data/work_calendars.json",),
)
def _seeded_calendar(country: str) -> DimensionReport:
    path = Path(__file__).resolve().parents[1] / "modules" / "i18n_foundation" / "seed_data" / "work_calendars.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(rows, dict):
        rows = next(iter(rows.values()))
    known = {str(r.get("country_code")) for r in rows if isinstance(r, dict) and r.get("country_code")}
    return _keyed("calendar.seeded_rows", str(path.name), known, country)


# --------------------------------------------------------------------------- #
# The rest of the dimensions
# --------------------------------------------------------------------------- #


@_probe("payment.prompt_payment_regime", covers=("app.modules.payment_clock.data.PAYMENT_REGIMES",))
def _payment_regimes(country: str) -> DimensionReport:
    from app.modules.payment_clock.data import NO_REGIME_HELD, PAYMENT_REGIMES, no_regime_reason

    known = {str(r.get("country_code")) for r in PAYMENT_REGIMES if r.get("country_code")}
    report = _keyed(
        "payment.prompt_payment_regime",
        "app.modules.payment_clock.data.PAYMENT_REGIMES",
        known,
        country,
    )
    if report.verdict != MISSING:
        return report
    # The country is confirmed absent from PAYMENT_REGIMES at this point (the
    # branch above returned already), so no_regime_reason cannot raise here;
    # its raise is reserved for a country that has a row of its own.
    if country in NO_REGIME_HELD:
        return replace(
            report,
            detail=(
                "no row; under active research and held rather than resolved, because a wrong-"
                "instrument search is not evidence of absence "
                "(see app.modules.payment_clock.data.NO_REGIME_HELD)"
            ),
        )
    reason = no_regime_reason(country)
    if reason is not None:
        return replace(
            report,
            detail=(
                f"no row, and a reason is on record: {reason} (see app.modules.payment_clock.data.no_regime_reason)"
            ),
        )
    return report


@_probe(
    "tax.rates",
    covers=("app/modules/i18n_foundation/seed_data/tax_configurations.json",),
)
def _tax_rates(country: str) -> DimensionReport:
    path = Path(__file__).resolve().parents[1] / "modules" / "i18n_foundation" / "seed_data" / "tax_configurations.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(rows, dict):
        rows = next(iter(rows.values()))
    known = {str(r.get("country_code")) for r in rows if isinstance(r, dict) and r.get("country_code")}
    return _keyed("tax.rates", str(path.name), known, country)


@_probe(
    "contract.notice_periods_by_standard",
    covers=("app.modules.change_intelligence.time_bar.NOTICE_PERIODS",),
)
def _contract_standards(country: str) -> DimensionReport:
    """Keyed by standard, never by country - the question cannot be put to it.

    A standard belongs to a jurisdiction in the world (CCDC to Canada, VOB/B to
    Germany, AIA to the United States) and nothing in the tree records that. So
    this is not "Canada is missing a row": there is no axis on which Canada
    could have one. Making it per-country is a shape change.
    """
    from app.modules.change_intelligence.time_bar import NOTICE_PERIODS, NOTICE_PERIODS_HELD

    standards = tuple(sorted(NOTICE_PERIODS))
    if not standards:
        return DimensionReport(
            dimension="contract.notice_periods_by_standard",
            verdict=UNRESOLVED,
            detail="NOTICE_PERIODS resolved but is empty",
            source="app.modules.change_intelligence.time_bar.NOTICE_PERIODS",
            method="import",
        )
    # Standards that are recognised but carry no periods are named separately
    # rather than left out. Omitting them would read as "not supported" when
    # the truth is "recognised, periods not sourced yet", and the difference
    # decides whether somebody goes looking for the numbers.
    held = tuple(sorted(NOTICE_PERIODS_HELD))
    held_detail = f"; recognised without registered periods: {', '.join(held)}" if held else ""
    return DimensionReport(
        dimension="contract.notice_periods_by_standard",
        verdict=NOT_KEYED,
        detail=(
            f"keyed by standard, not by country ({', '.join(standards)}); "
            "no mapping from a country to the standards used there exists"
            f"{held_detail}"
        ),
        source="app.modules.change_intelligence.time_bar.NOTICE_PERIODS",
        method="import",
    )


@_probe("compliance.document_vocabulary", covers=("app.modules.credentials.schemas.CREDENTIAL_TYPES",))
def _compliance_documents(country: str) -> DimensionReport:
    """The credential vocabulary is closed and has no country axis."""
    from app.modules.credentials.schemas import CREDENTIAL_TYPES

    types = tuple(sorted(CREDENTIAL_TYPES))
    if not types:
        return DimensionReport(
            dimension="compliance.document_vocabulary",
            verdict=UNRESOLVED,
            detail="CREDENTIAL_TYPES resolved but is empty",
            source="app.modules.credentials.schemas.CREDENTIAL_TYPES",
            method="import",
        )
    return DimensionReport(
        dimension="compliance.document_vocabulary",
        verdict=NOT_KEYED,
        detail=(
            f"{len(types)} deliberately generic kinds with no country axis; a country-specific "
            "document (a workers-compensation clearance, a statutory declaration) has no way in"
        ),
        source="app.modules.credentials.schemas.CREDENTIAL_TYPES",
        method="import",
    )


@_probe("estimate.class_ladder", covers=("app.modules.boq.service._AACE_CLASSES",))
def _estimate_ladder(country: str) -> DimensionReport:
    source = "app.modules.boq.service._AACE_CLASSES"
    node = _module_level_node("app.modules.boq.service", "_AACE_CLASSES")
    size = len(node.keys) if isinstance(node, ast.Dict) else 0
    if not size:
        return DimensionReport(
            dimension="estimate.class_ladder",
            verdict=UNRESOLVED,
            detail="_AACE_CLASSES resolved but is empty or is no longer a dict literal",
            source=source,
            method="source",
        )
    return DimensionReport(
        dimension="estimate.class_ladder",
        verdict=NOT_KEYED,
        detail=(
            f"one hardcoded ladder of {size} integer classes, not pack-resolved; "
            "a lettered national ladder has no representation"
        ),
        source=source,
        method="source",
    )


@_probe("security_of_payment.deadlines")
def _security_of_payment(country: str) -> DimensionReport:
    """No registry at all, which is different from an empty one.

    Declared rather than probed, because there is no symbol to resolve. Liens,
    hypothecs, notice-of-intent deadlines and bid security have no home in the
    tree; the only related data is static reference text served read-only for
    one US state, which is not a computed deadline for any country.
    """
    return DimensionReport(
        dimension="security_of_payment.deadlines",
        verdict=ABSENT,
        detail="no registry exists; nothing computes a lien or hypothec deadline from a construction event",
        source="(none)",
        # Declared, in this file, from a reading of the tree. There is no
        # registry to import, so claiming the "import" default would put nine
        # verdicts a run never read into the count of ones it did. The reason
        # travels with the verdict: the reporter must not be the one asserting
        # why, because it cannot check whether its reason fits every verdict.
        method="declared (no registry exists)",
    )


@_probe("labour.rate_regions", covers=("app.modules.labor_rates.models.LaborRateTemplate",))
def _labour_regions(country: str) -> DimensionReport:
    """The rate template has no region column, so there is no axis to be on."""
    source = "app.modules.labor_rates.models.LaborRateTemplate"
    columns, method = _annotated_attributes("app.modules.labor_rates.models", "LaborRateTemplate")
    regional = columns & {"region", "province", "jurisdiction", "country_code", "state", "country"}
    if regional:
        # Not a verdict about the country: a regional column means this probe is
        # reading a model it was not written for, and its NOT_KEYED would be a
        # stale answer stated confidently. Say so instead.
        return DimensionReport(
            dimension="labour.rate_regions",
            verdict=UNRESOLVED,
            detail=f"a regional column appeared ({sorted(regional)}); this probe predates it and needs rewriting",
            source=source,
            method=method,
        )
    return DimensionReport(
        dimension="labour.rate_regions",
        verdict=NOT_KEYED,
        detail=(
            f"LaborRateTemplate carries {len(columns)} fields and none of them is a region, province, "
            "jurisdiction or country; there is no axis a country could be a value on"
        ),
        source=source,
        method=method,
    )


# --------------------------------------------------------------------------- #
# The axes the product claims per-country support on
#
# Units, regional packs, cost classification, the second tax table and
# e-invoicing were all reachable from the tree and none of them was asked a
# question here, so a country could be uncovered on every one of them and the
# page would say nothing at all. E-invoicing is the sharpest of the five: its
# registry names twenty-four countries, it shipped days before this was written,
# and the manifest could not have known about it, because the manifest's
# denominator was the set of probes somebody had already written.
# --------------------------------------------------------------------------- #


#: Every regional pack's configuration, named as the discovery pass names them.
#: All thirteen are listed, including the five that hold fewer than three
#: country codes and so are invisible to discovery: what a probe reads is a fact
#: about the probe, and trimming this to what the walk happens to see would make
#: the denominator agree with the walk by construction.
def _pack_config_modules() -> tuple[str, ...]:
    """The product's own list of regional pack modules, read rather than copied.

    Read from the source of ``app.core.regional_packs`` instead of imported, for
    the reason every other structural question on this page is: the hygiene
    lane that runs this tool has no database, and a module-level import here
    would take the whole reporter down with any dependency that is not
    installed, where a probe failing alone is merely one UNRESOLVED verdict.

    Returns:
        The dotted path of each pack's ``PACK_CONFIG``.

    Raises:
        Exception: If the list cannot be read at all. Loud on purpose. A
            fallback here would silently shrink the set of registries this
            instrument claims to cover, which is the exact failure it exists to
            report on everybody else.
    """
    node = _module_level_node("app.core.regional_packs", "PACK_CONFIG_MODULES")
    return tuple(f"{module}.PACK_CONFIG" for module in ast.literal_eval(node))


#: Every regional pack config, derived from the product's list and not copied
#: beside it. This was a hand-written tuple first, and it went stale the same
#: day: a thirteenth pack was added to PACK_CONFIG_MODULES while this file
#: still named twelve, so the product would have loaded a pack that claims
#: countries on this very page while the census counted it as a registry
#: nobody probes. Two hand-kept mirrors of one registry always drift, and a
#: census whose numerator is a copy has the defect it was written to find.
_PACK_CONFIGS: tuple[str, ...] = _pack_config_modules()


def _pack_countries() -> set[str]:
    """Every country any regional pack claims.

    Returns:
        The union of the packs' own ``countries`` lists, upper-cased.
    """
    from app.core.regional_packs import pack_configs

    return {
        str(code).strip().upper() for config in pack_configs() for code in config.get("countries") or () if str(code)
    }


@_probe("packs.regional_coverage", covers=_PACK_CONFIGS)
def _regional_packs(country: str) -> DimensionReport:
    """Does any regional pack claim this country.

    The population is the union of the packs' own ``countries`` lists rather
    than anything written here, so a pack that adds a market moves this without
    an edit in this file.
    """
    return _keyed(
        "packs.regional_coverage",
        "app.core.regional_packs.pack_configs",
        _pack_countries(),
        country,
    )


@_probe("units.measurement_system", covers=_PACK_CONFIGS)
def _measurement_system(country: str) -> DimensionReport:
    """Ask the resolver, because pack membership is not the question a caller asks.

    ``resolve_measurement_system`` returns ``None`` in two very different
    situations and the difference decides whether anybody has work to do. No
    pack claims the country, so nothing was ever written for it; or several
    packs claim it and disagree about metric versus imperial, in which case the
    data exists and contradicts itself. Reading the packs' ``countries`` lists
    alone reports both as the same absence, which is the proxy-reading mistake
    this file already refuses for ``calendar.schedule_regions``.
    """
    from app.core.regional_packs import packs_for_country, resolve_measurement_system

    source = "app.core.regional_packs.resolve_measurement_system"
    claimed = _pack_countries()
    if not claimed:
        return DimensionReport(
            dimension="units.measurement_system",
            verdict=UNRESOLVED,
            detail="the packs resolved but claim no countries at all; the probe has probably lost the shape",
            source=source,
            method="import",
        )
    system = resolve_measurement_system(country_code=country)
    if system:
        return DimensionReport(
            dimension="units.measurement_system",
            verdict=COVERED,
            detail=f"the packs resolve {system} for this country, among {len(claimed)} claimed",
            population=tuple(sorted(claimed)),
            source=source,
            method="import",
        )
    if country in claimed:
        holders = [
            str(config.get("pack_id") or config.get("region_code") or "?") for config in packs_for_country(country)
        ]
        return DimensionReport(
            dimension="units.measurement_system",
            verdict=FALLBACK,
            detail=(
                f"{len(holders)} pack(s) claim this country ({', '.join(sorted(holders))}) and no measurement "
                "system resolves, so they disagree or name one that is not recognised; a caller is told "
                "'not configured' for a country the packs do claim"
            ),
            population=tuple(sorted(claimed)),
            source=source,
            method="import",
        )
    return DimensionReport(
        dimension="units.measurement_system",
        verdict=MISSING,
        detail=f"no pack claims this country, so no measurement system resolves ({len(claimed)} are claimed)",
        population=tuple(sorted(claimed)),
        source=source,
        method="import",
    )


@_probe(
    "cost_classification.catalogue_standard",
    covers=("app.modules.costs.cwicr_v3_catalogue.CWICR_V3_CATALOGUES",),
)
def _classification_standard(country: str) -> DimensionReport:
    """Which cost classification standard a country's catalogues default to.

    Membership of the catalogue is not the question. ``default_classification_standard``
    used to be a hand-written field left empty on fifteen of the forty-eight
    rows, and a country present in the table with an empty standard would be
    reported COVERED by a membership test while the match pipeline still had no
    standard to fall back on for it. The field is derived from the registry
    now, so an empty answer here means something sharper than it used to: the
    product ships a catalogue for this country and the one classification table
    still names no standard for it.
    """
    from app.modules.costs.cwicr_v3_catalogue import CWICR_V3_CATALOGUES

    source = "app.modules.costs.cwicr_v3_catalogue.CWICR_V3_CATALOGUES"
    if not CWICR_V3_CATALOGUES:
        return DimensionReport(
            dimension="cost_classification.catalogue_standard",
            verdict=UNRESOLVED,
            detail="the catalogue registry resolved but is empty; the probe has probably lost the shape",
            source=source,
            method="import",
        )
    with_standard = {c.country_iso for c in CWICR_V3_CATALOGUES if c.default_classification_standard}
    in_table = {c.country_iso for c in CWICR_V3_CATALOGUES}
    population = tuple(sorted(with_standard))
    if country in with_standard:
        named = sorted({c.default_classification_standard for c in CWICR_V3_CATALOGUES if c.country_iso == country})
        return DimensionReport(
            dimension="cost_classification.catalogue_standard",
            verdict=COVERED,
            detail=f"catalogues default to {', '.join(named)}, among {len(with_standard)} countries that name one",
            population=population,
            source=source,
            method="import",
        )
    if country in in_table:
        return DimensionReport(
            dimension="cost_classification.catalogue_standard",
            verdict=FALLBACK,
            detail=(
                "the country has catalogues but none names a default classification standard, so the match "
                f"pipeline has nothing to fall back on ({len(with_standard)} of {len(in_table)} countries name one)"
            ),
            population=population,
            source=source,
            method="import",
        )
    return _keyed(
        "cost_classification.catalogue_standard",
        source,
        with_standard,
        country,
    )


@_probe("tax.vat_rate_table", covers=("app.core.tax._RAW",))
def _vat_rate_table(country: str) -> DimensionReport:
    """The second tax table, probed separately from the seeded one on purpose.

    ``app.core.tax._RAW`` and ``tax_configurations.json`` are two hand-kept
    tables of different scope - twenty-three countries against forty-one - and
    ``tax.py``'s own comment records the risk that they drift. Collapsing them
    into one "tax" dimension would hide the disagreement, which is the same
    reason the four calendar registries are probed as four.
    """
    from app.core.tax import _RAW

    return _keyed("tax.vat_rate_table", "app.core.tax._RAW", set(_RAW), country)


@_probe(
    "einvoice.clearance_regime",
    covers=("app.modules.einvoice_clearance.regimes.COUNTRY_REGIMES",),
)
def _einvoice_regimes(country: str) -> DimensionReport:
    """Whether a country's e-invoicing regime is known."""
    from app.modules.einvoice_clearance.regimes import COUNTRY_REGIMES

    return _keyed(
        "einvoice.clearance_regime",
        "app.modules.einvoice_clearance.regimes.COUNTRY_REGIMES",
        set(COUNTRY_REGIMES),
        country,
    )


@dataclass(frozen=True)
class SharedRowCensus:
    """How a registry's countries split between rows of their own and shared rows.

    A per-country report structurally cannot carry this. Germany's report knows
    Germany is on a row with Austria and Switzerland; it cannot know how much of
    the registry is like that, and a figure that can only be had by reading
    every country's report one at a time is a figure that stops being counted.
    """

    dimension: str
    source: str
    #: How the registry was read, the same way a DimensionReport says it.
    method: str
    #: Row name to the countries on it, for every row more than one reaches.
    shared: dict[str, tuple[str, ...]]
    #: Countries whose row no other country on the axis reaches.
    on_own_row: tuple[str, ...]

    @property
    def on_shared_row(self) -> tuple[str, ...]:
        return tuple(sorted(code for codes in self.shared.values() for code in codes))

    @property
    def on_axis(self) -> int:
        return len(self.on_own_row) + len(self.on_shared_row)

    def summary(self) -> str:
        """One line, in the shape CountryReport.summary uses."""
        rows = "; ".join(f"{name} ({', '.join(codes)})" for name, codes in sorted(self.shared.items()))
        return (
            f"{self.dimension}: {len(self.on_shared_row)} of {self.on_axis} countries on the axis "
            f"are on a row shared with another country - {rows}"
        )


def shared_calendar_rows() -> SharedRowCensus:
    """Count the schedule calendar's shared rows, over its whole axis.

    Only calendar.schedule_regions answers this today. That is a statement about
    what has been measured and not a claim that nothing else groups countries:
    app.core.calendar points several holiday codes at another country's
    function, which is the same shape of question and is counted nowhere yet.
    If a second registry is given this treatment, this is the shape to give it.

    Returns:
        The census, taken over the registry's own axis rather than over any
        cohort, so the figure does not move when the list of countries somebody
        asked about does.

    Raises:
        AttributeError: A name has moved and the module still imports.
        LookupError: The module will not import and a name is not bound exactly
            once at module level.
    """
    calendars, resolve, axis, method = _schedule_registry()
    rows = _calendar_rows(calendars, resolve, axis)
    return SharedRowCensus(
        dimension="calendar.schedule_regions",
        source="app.modules.schedule.service._CALENDAR_BY_COUNTRY",
        method=method,
        shared={name: codes for name, codes in sorted(rows.items()) if len(codes) > 1},
        on_own_row=tuple(sorted(code for codes in rows.values() if len(codes) == 1 for code in codes)),
    )


def dimensions() -> tuple[str, ...]:
    """Every dimension this manifest knows how to ask about."""
    return tuple(name for name, _ in _PROBES)


@_probe(
    "contract.compliance_pack",
    covers=(
        "app.modules.contracts.compliance_packs.PACK_BY_COUNTRY",
        "app.modules.contracts.compliance_packs.RULE_PACKS",
    ),
)
def _contract_compliance_pack(country: str) -> DimensionReport:
    """Whether a country has contract compliance rules of its own.

    This is the question ``contract.notice_periods_by_standard`` cannot answer
    and used to look as though it had. That dimension reads NOTICE_PERIODS,
    which really is keyed by contract standard, so it correctly reports that it
    has no country axis; but under its old name, ``contract.standard_families``,
    a reader scanning for "does this country have contract rules" took that no
    for an answer about the country. The answer exists, keyed by country, and
    until now nothing on this page asked it. Renaming the old dimension without
    adding this one would have replaced a confident wrong answer with an
    accurate silence, and silence is how a registry ships unnoticed.

    ``PACK_BY_COUNTRY`` is assembled at import time from the jurisdictions in
    ``RULE_PACKS`` plus two hand-written rows, so the discovery walk cannot see
    it and says so; a probe that imports the module can. Both symbols are named
    as covered because one population is built out of the other.
    """
    from app.modules.contracts.compliance_packs import PACK_BY_COUNTRY

    return _keyed(
        "contract.compliance_pack",
        "app.modules.contracts.compliance_packs.PACK_BY_COUNTRY",
        set(PACK_BY_COUNTRY),
        country,
    )


@_probe(
    "cost_classification.match_standard",
    covers=("app.core.classification_registry.COUNTRY_TO_STANDARD",),
)
def _match_standard(country: str) -> DimensionReport:
    """Which classification standard the match pipeline picks for a country.

    This used to read a third hand-kept copy of the mapping inside
    ``match_elements.service``, compare it against the copy the shipped
    catalogues carried, and report the countries where the two had drifted.
    There was a fourth copy in the validation rules and two more elsewhere.
    They are one table now, so the drift branch this probe existed to surface
    cannot happen and the dimension answers a plainer question: does the one
    table name a standard for this country.

    The dimension is kept separate from ``cost_classification.catalogue_standard``
    even though both now read the same table, because they still ask different
    things. This one asks whether the resolver has an answer at all; that one
    asks whether the country the product ships a catalogue for has one.

    Imported rather than read from source. The old copy lived in a module that
    imports ``app.database`` at module scope, which is why it had to be parsed;
    the registry deliberately imports nothing but the standard library, so the
    lane that runs this tool without a cluster can import it.
    """
    from app.core.classification_registry import COUNTRY_TO_STANDARD

    source = "app.core.classification_registry.COUNTRY_TO_STANDARD"
    return _keyed("cost_classification.match_standard", source, set(COUNTRY_TO_STANDARD), country)


def _iban_length_tables() -> tuple[dict[str, int], dict[str, int]]:
    """Both copies of the IBAN length table, payment path first.

    Returns:
        The e-invoicing table and the validation table.
    """
    from app.core.validation.rules import _IBAN_LENGTHS as validated
    from app.modules.einvoice.bank import _IBAN_LENGTHS as paid

    return dict(paid), dict(validated)


@_probe("payment.iban_length", covers=("app.modules.einvoice.bank._IBAN_LENGTHS",))
def _payment_iban_length(country: str) -> DimensionReport:
    """The exact IBAN length the payment path enforces for a country.

    One of two copies of this table in the tree, probed separately from the
    other for the reason the classification tables are: a merged dimension can
    only report the union, and the union is what hides a divergence between
    copies. Here the copies agree wherever they overlap, and the divergence is
    in who they cover, which the other dimension reports.
    """
    source = "app.modules.einvoice.bank._IBAN_LENGTHS"
    paid, _ = _iban_length_tables()
    if not paid:
        return DimensionReport(
            dimension="payment.iban_length",
            verdict=UNRESOLVED,
            detail="the payment IBAN table resolved but is empty; the probe has probably lost the shape",
            source=source,
            method="import",
        )
    if country in paid:
        return DimensionReport(
            dimension="payment.iban_length",
            verdict=COVERED,
            detail=f"an exact length of {paid[country]} characters, among {len(paid)} countries",
            population=tuple(sorted(paid)),
            source=source,
            method="import",
        )
    return DimensionReport(
        dimension="payment.iban_length",
        verdict=MISSING,
        detail=(
            f"no length of its own among {len(paid)} countries, so an account number for this country is "
            "accepted on its check digits alone; mod-97 catches a wrong length about ninety-six times in "
            "ninety-seven, and this table is what makes that deterministic"
        ),
        population=tuple(sorted(paid)),
        source=source,
        method="import",
    )


@_probe("validation.iban_length", covers=("app.core.validation.rules.__init__._IBAN_LENGTHS",))
def _validation_iban_length(country: str) -> DimensionReport:
    """The exact IBAN length the validation rule enforces for a country.

    The second copy, and the smaller one. Where both tables name a country they
    agree, so the finding is not a wrong number: it is that one path holds an
    exact length for far more countries than the other, and the validator falls
    back to accepting anything between fifteen and thirty-four characters for
    the rest. The exact length is in the product; this path just cannot see it.

    The two copies also encode "this country has no IBAN regime" differently.
    Here it is a zero, read at two call sites as skip the length check; in the
    payment copy it is the absence of a row. Anybody merging the tables has to
    preserve both readings, or India and the United States start being length
    checked against nothing.
    """
    source = "app.core.validation.rules._IBAN_LENGTHS"
    paid, validated = _iban_length_tables()
    if not validated:
        return DimensionReport(
            dimension="validation.iban_length",
            verdict=UNRESOLVED,
            detail="the validation IBAN table resolved but is empty; the probe has probably lost the shape",
            source=source,
            method="import",
        )
    expected = validated.get(country)
    if expected == 0:
        return DimensionReport(
            dimension="validation.iban_length",
            verdict=COVERED,
            detail="recorded as having no IBAN regime, so the length check is skipped on purpose",
            population=tuple(sorted(validated)),
            source=source,
            method="import",
        )
    if expected:
        return DimensionReport(
            dimension="validation.iban_length",
            verdict=COVERED,
            detail=f"an exact length of {expected} characters, among {len(validated)} countries",
            population=tuple(sorted(validated)),
            source=source,
            method="import",
        )
    elsewhere = paid.get(country)
    if elsewhere:
        return DimensionReport(
            dimension="validation.iban_length",
            verdict=FALLBACK,
            detail=(
                f"this validator accepts any length from 15 to 34 here, while the payment path holds an "
                f"exact length of {elsewhere} for the same country; the number is in the product and this "
                "copy cannot see it"
            ),
            population=tuple(sorted(validated)),
            source=source,
            method="import",
        )
    return DimensionReport(
        dimension="validation.iban_length",
        verdict=MISSING,
        detail=(
            f"no length in either copy among {len(validated)} countries here and {len(paid)} on the payment "
            "path, so an account number is accepted on its length range and check digits alone"
        ),
        population=tuple(sorted(validated)),
        source=source,
        method="import",
    )


@_probe("estimate.markup_region", covers=("app.modules.boq.markup_templates.REGION_BY_COUNTRY",))
def _markup_region(country: str) -> DimensionReport:
    """Which markup stack a country's bill is seeded with.

    Imported rather than read from source, for the reason
    ``cost_classification.match_standard`` is: ``markup_templates`` imports
    nothing but ``__future__``, so the lane that runs this tool without a
    cluster can import it, and an import reads the object the product runs on.

    The region names are not a second country axis, even though most of them
    are two uppercase letters. ``GB`` reaches a region spelled ``UK``, and
    ``US``, ``FR``, ``IN``, ``AU``, ``JP``, ``BR``, ``CN`` and ``KR`` each name
    a region that happens to share its spelling with the one country reaching
    it. The discovery walk counts twenty-one country-shaped tokens here for
    that reason, against twenty entries. The country axis is the keys, and only
    the keys.
    """
    from app.modules.boq.markup_templates import REGION_BY_COUNTRY

    return _keyed(
        "estimate.markup_region",
        "app.modules.boq.markup_templates.REGION_BY_COUNTRY",
        set(REGION_BY_COUNTRY),
        country,
    )


@_probe("estimate.markup_stack", covers=("app.modules.boq.markup_templates.DEFAULT_MARKUP_TEMPLATES",))
def _markup_stack(country: str) -> DimensionReport:
    """The markup stacks themselves are keyed by region, and a region is not a country.

    The registry the discovery walk most convincingly mistakes for a country
    table, and so the clearest case of the thing the reporter asks for: a probe
    that records what a registry actually is, rather than one that answers a
    question the registry has not got.

    Its fourteen keys include ten two-letter uppercase tokens, which is what the
    walk counts. Nine of them are real ISO codes; the tenth is ``UK``, which is
    not a country code at all - ``GB`` is, and ``GB`` is not a key here. The
    walk reports that split itself, ten codes against nine ISO hits, and it is
    the whole finding in one line.

    A probe that read these keys as countries would therefore report ``UK``
    covered and ``GB`` missing, and would call Austria, Switzerland and the Gulf
    states missing while every one of them is served - through ``DACH`` and
    ``GULF``, which do not look like countries and so would not be counted.
    Confidently wrong in both directions, and it is the natural probe to write.

    The country question has an owner: ``estimate.markup_region``, reading
    ``REGION_BY_COUNTRY``, where twenty countries map onto twelve of these
    stacks. Covering a new country means a row there, not a key here. And a
    country with no row still prices, because :func:`resolve_region_lines`
    falls back to ``DEFAULT``, which is why that dimension's MISSING is a
    statement about tailoring and not about a bill failing to seed.
    """
    from app.modules.boq.markup_templates import DEFAULT_MARKUP_TEMPLATES

    source = "app.modules.boq.markup_templates.DEFAULT_MARKUP_TEMPLATES"
    regions = tuple(sorted(DEFAULT_MARKUP_TEMPLATES))
    if not regions:
        return DimensionReport(
            dimension="estimate.markup_stack",
            verdict=UNRESOLVED,
            detail="DEFAULT_MARKUP_TEMPLATES resolved but is empty",
            source=source,
            method="import",
        )
    return DimensionReport(
        dimension="estimate.markup_stack",
        verdict=NOT_KEYED,
        detail=(
            f"{len(regions)} stacks keyed by region, not by country ({', '.join(regions)}); "
            "a country reaches one through REGION_BY_COUNTRY, so estimate.markup_region is the "
            "dimension that answers for a country and this one cannot be asked"
        ),
        source=source,
        method="import",
    )


# --------------------------------------------------------------------------- #
# The demo dataset: four registries in one module, probed as four.
#
# ``app.core.demo_projects`` imports its ORM models at module scope, so without
# a cluster it raises before any of these literals is reachable and every probe
# below answers through the source read. That is why they carry a "source"
# method where the markup probe above carries "import".
#
# Four dimensions rather than one, for the reason the calendars are four: they
# were written independently, they are read at different points of the demo
# build, and they already disagree with each other. Fifteen countries can name
# the authority a notice of commencement goes to, eleven can name the clause it
# is raised under, and five have a demo project at all. A single "demo" row
# would report the union and hide exactly that spread.
# --------------------------------------------------------------------------- #

_DEMO_PROJECTS = "app.core.demo_projects"


def _demo_dict(symbol: str) -> tuple[dict, str]:
    """One of the demo module's country tables, and how it was read.

    Raises:
        LookupError: The symbol no longer holds a dict, so the probe cannot ask
            its question and must say so rather than report an absence.
    """
    registry, method = _registry_literal(_DEMO_PROJECTS, symbol)
    if not isinstance(registry, dict):
        raise LookupError(f"{symbol} in {_DEMO_PROJECTS} is not a dict any more, so it has no country axis to read")
    return registry, method


@_probe("demo.notice_authority", covers=("app.core.demo_projects._AUTHORITY_BY_COUNTRY",))
def _demo_notice_authority(country: str) -> DimensionReport:
    """Whether the demo data knows who receives a notice of commencement here.

    A country with no row does not break the demo; it gets the generic English
    wording, which is the failure the table's own comment describes - a
    correspondence register that addresses "the authority" in Heidelberg, Delhi
    and Sao Paulo alike is not a register of anything. So the absence is worth a
    verdict even though nothing raises.
    """
    registry, method = _demo_dict("_AUTHORITY_BY_COUNTRY")
    return _keyed(
        "demo.notice_authority",
        "app.core.demo_projects._AUTHORITY_BY_COUNTRY",
        {str(code) for code in registry},
        country,
        method=method,
    )


@_probe("demo.address_country_names", covers=("app.core.demo_projects._COUNTRY_ISO2",))
def _demo_address_country_names(country: str) -> DimensionReport:
    """Whether a pack template's address in this country resolves to an ISO code.

    **The country axis here is the values, not the keys.** This table is keyed
    by English country name - "Germany", "United Arab Emirates" - and holds the
    ISO code as the value, the opposite way round from every other registry on
    this page. A probe that copied its siblings and asked ``set(_COUNTRY_ISO2)``
    would take a population of fifteen English names, find no two-letter code in
    it, and report every country in the world MISSING with a full population
    printed underneath to make it look measured.

    That is also why the discovery walk sees this registry at all: it recognises
    a registry by the shape of what is written, never by the field holding it,
    so it counted the fifteen values and not the fifteen names.
    """
    registry, method = _demo_dict("_COUNTRY_ISO2")
    return _keyed(
        "demo.address_country_names",
        "app.core.demo_projects._COUNTRY_ISO2",
        {str(code) for code in registry.values()},
        country,
        method=method,
    )


@_probe("demo.notice_clause", covers=("app.core.demo_projects._NOTICE_CLAUSE_BY_COUNTRY",))
def _demo_notice_clause(country: str) -> DimensionReport:
    """Whether the demo register can cite the provision a notice is raised under.

    Absence is deliberate here and the table says so: a country whose usual form
    cannot be named with confidence is left out, because an empty clause
    reference is honest and an invented clause number is not. Read a MISSING on
    this dimension as "not sourced yet", never as an oversight.
    """
    registry, method = _demo_dict("_NOTICE_CLAUSE_BY_COUNTRY")
    return _keyed(
        "demo.notice_clause",
        "app.core.demo_projects._NOTICE_CLAUSE_BY_COUNTRY",
        {str(code) for code in registry},
        country,
        method=method,
    )


def _pack_template_call(path: Path) -> ast.Call | None:
    """The ``TEMPLATE = DemoTemplate(...)`` call a pack file declares, if any.

    Args:
        path: A file in the pack directory.

    Returns:
        The call node, or None when the file binds no module-level ``TEMPLATE``
        or binds something that is not a call. The loader reads the attribute
        with a ``getattr(..., None)`` and skips a file that has not got one, so
        None here is the same ordinary outcome and not an error.
    """
    for node in ast.parse(path.read_text(encoding="utf-8"), filename=str(path)).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TEMPLATE" for t in node.targets):
            return node.value if isinstance(node.value, ast.Call) else None
    return None


def _call_kwarg(call: ast.Call, name: str) -> object | None:
    """One keyword argument of a call, evaluated, or None if it is not a literal."""
    for keyword in call.keywords:
        if keyword.arg == name:
            try:
                return ast.literal_eval(keyword.value)
            except ValueError:
                return None
    return None


def _catalogue_from_source() -> set[str]:
    """The catalogue's countries, rebuilt from the files the loader reads.

    A re-implementation of the merge, deliberately, and worth stating plainly
    because a re-implementation can drift from the thing it copies. It follows
    the loader step for step: the same ``*.py`` glob over the pack directory
    with ``__init__`` and underscore-prefixed files skipped, the same module
    level ``TEMPLATE`` name, the same ``address["country"]`` looked up in the
    same ``_COUNTRY_ISO2``, and the same ``demo_id`` rule that keeps a
    hand-written row authoritative over a pack that would collide with it.

    A pack this cannot read contributes nothing and raises nothing, which is
    the loader's behaviour too: it wraps each file in its own handler so one
    broken pack cannot take out the rest.

    Returns:
        The ISO codes with at least one catalogue row.

    Raises:
        LookupError: The seed list or the ISO map is no longer the shape this
            reads, so the answer would be a guess.
    """
    try:
        rows = ast.literal_eval(_module_level_node(_DEMO_PROJECTS, "DEMO_CATALOG"))
        iso = ast.literal_eval(_module_level_node(_DEMO_PROJECTS, "_COUNTRY_ISO2"))
    except ValueError as bad:
        raise LookupError(f"DEMO_CATALOG in {_DEMO_PROJECTS} is not a literal this probe can evaluate") from bad
    if not isinstance(rows, list) or not isinstance(iso, dict):
        raise LookupError(f"DEMO_CATALOG in {_DEMO_PROJECTS} is not a list of rows keyed the way this probe reads")

    seeds = [row for row in rows if isinstance(row, dict)]
    known = {str(row["country"]) for row in seeds if row.get("country")}
    seen_ids = {str(row.get("demo_id")) for row in seeds}

    for path in sorted(_source_of(_DEMO_PROJECTS).parent.joinpath("demo_packs").glob("*.py")):
        if path.name == "__init__.py" or path.name.startswith("_"):
            continue
        call = _pack_template_call(path)
        if call is None:
            continue
        demo_id = str(_call_kwarg(call, "demo_id"))
        address = _call_kwarg(call, "address")
        if demo_id in seen_ids or not isinstance(address, dict):
            continue
        seen_ids.add(demo_id)
        code = iso.get(str(address.get("country", "")))
        if code:
            known.add(str(code))
    return known


def _demo_catalogue_countries() -> tuple[set[str], str]:
    """The countries the demo catalogue offers, and how they were read.

    Import first, like every registry on this page, because that reads the list
    the product actually serves. The fallback is the unusual half: this list is
    built while the module runs, so there is no literal to parse for an answer
    and :func:`_catalogue_from_source` rebuilds the merge instead.

    The two paths are pinned against each other by a test that runs where the
    import works, comparing the full sets rather than a cohort. That test is
    what makes the rebuild safe to trust, and it is the thing to read first if
    the loader ever changes how it selects a pack.

    Returns:
        The ISO codes with at least one catalogue row, and the method string a
        report has to carry so a source reading is not printed as an import.
    """
    try:
        module = importlib.import_module(_DEMO_PROJECTS)
    except Exception as exc:  # noqa: BLE001 - having no cluster is an ordinary state, not a finding
        return _catalogue_from_source(), f"source ({type(exc).__name__} on import)"
    # Outside the handler on purpose, the same way _registry_literal does it: a
    # renamed registry is a finding, not a reason to fall back to the parse.
    catalogue = module.DEMO_CATALOG
    if not isinstance(catalogue, list):
        raise LookupError(f"DEMO_CATALOG in {_DEMO_PROJECTS} is not a list any more, so it has no country axis to read")
    return {str(row.get("country")) for row in catalogue if isinstance(row, dict) and row.get("country")}, "import"


@_probe("demo.catalogue_projects", covers=("app.core.demo_projects.DEMO_CATALOG",))
def _demo_catalogue(country: str) -> DimensionReport:
    """Whether a visitor from this country sees a demo project set where they work.

    The narrowest country axis on the page, and the most visible: this is the
    list somebody lands on before they have entered any data of their own, so a
    country missing here is a country whose first look at the product is a
    building somewhere else, under another currency and another classification
    standard.

    A list of rows rather than a keyed table, so the country arrives in a
    ``country`` field, the same shape ``calendar.seeded_rows`` reads out of its
    JSON file.

    **Assembled at import time, so the fallback rebuilds the merge instead of
    parsing the literal.** Alone among the four here this registry is nowhere
    written down in full: the literal holds five hand-written rows and
    ``register_pack_templates`` appends one per pack template. Parsing the
    literal alone was measured against the live list and disagreed about nine
    countries, calling CA, CN, IN, BR, NL, AU, MX, SA and ZA missing while the
    product offers a project in every one of them. That is the known-bad proxy
    the source-read policy above forbids; :func:`_demo_catalogue_countries`
    says what the second path does in its place.

    **This row and the registry census disagree about this registry on purpose,
    and neither of them is broken.** The census walks the tree with ``ast`` and
    can only ever see what is written down, so it records ``DEMO_CATALOG`` as
    five entries with the codes AE, DE, FR, GB and US. This probe reports
    fifteen countries. The gap is the ten the pack templates add while the
    module runs, which no walk over the source can see. Read the census figure
    for this symbol as the size of the seed and not as the size of the
    catalogue. The walk is left alone deliberately: teaching it to execute
    modules to find out what they build would make a static census a runtime
    one, and every other registry it counts is honestly counted today.
    """
    known, method = _demo_catalogue_countries()
    return _keyed(
        "demo.catalogue_projects",
        "app.core.demo_projects.DEMO_CATALOG",
        known,
        country,
        method=method,
    )


def covered_symbols() -> frozenset[str]:
    """Every registry symbol some probe declares it reads."""
    return frozenset(symbol for symbols in _COVERS.values() for symbol in symbols)


@dataclass(frozen=True)
class RegistryCensus:
    """How much of the product's country-shaped data this manifest actually asks about.

    The figure this carries is the one the instrument used to get wrong. A
    denominator that is the set of probes somebody wrote makes the percentage a
    fact about the instrument: a registry nobody probed is absent from the
    divisor as well as the dividend, so the number stays flattering and moves
    only when somebody adds a probe. Here the divisor is walked out of the tree,
    so adding a registry to the product moves it with nobody editing a list.
    """

    #: Every country-shaped registry the discovery walk found.
    discovered: tuple[DiscoveredRegistry, ...]
    #: Registry symbols the probes declare they read.
    covered: frozenset[str]
    #: Discovered registries no probe names. The finding.
    unprobed: tuple[DiscoveredRegistry, ...]

    @property
    def denominator(self) -> int:
        """Registries in the universe: discovered, union what the probes name.

        The union and not the walk alone. Four probes read registries the walk
        structurally cannot see - a table keyed by contract standard, a closed
        vocabulary, a ladder of integers, a model column - and counting only
        what the walk found would drop those four out of the universe and make
        the ratio a fact about the walk instead.
        """
        return len({r.symbol for r in self.discovered} | self.covered)

    @property
    def probed(self) -> int:
        return self.denominator - len(self.unprobed)

    def summary(self) -> str:
        """One line, in the shape the other summaries use."""
        return (
            f"registries: {self.probed} of {self.denominator} probed, "
            f"{len(self.unprobed)} discovered with no probe "
            f"({len(self.discovered)} found by walking the tree, {len(self.covered)} named by probes)"
        )


def registry_census() -> RegistryCensus:
    """Subtract what the probes name from what the tree holds.

    Returns:
        The census. ``unprobed`` is the set a reader has to act on: each one is
        a registry that varies by country and that no dimension on the page is
        asking a question about, so a country can be uncovered on it and the
        report will say nothing either way.
    """
    discovered = discover_registries()
    covered = covered_symbols()
    return RegistryCensus(
        discovered=discovered,
        covered=covered,
        unprobed=tuple(r for r in discovered if r.symbol not in covered),
    )


def country_coverage(country_code: str) -> CountryReport:
    """Every registry's verdict for one ISO country code."""
    code = (country_code or "").strip().upper()
    report = CountryReport(country_code=code)
    for name, fn in _PROBES:
        report.dimensions.append(_run(name, fn, code))
    return report
