# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rule-pack coverage resolver - honest "declared vs implemented" accounting.

Background
----------
Each shipped pack under ``packs/<slug>/src/openconstructionerp_*/rule_packs/``
carries one or more ``*.json`` rule-pack files. Every such file lists an
``enables_rule_ids`` array - a set of validation rule ids the pack intends to
switch on (e.g. ``masterformat.division_code_valid``,
``cpwd.item_code_format_chapter_section_item``).

Those JSON files are **declarations only**. Inspected across the whole repo
they contain *no* executable predicate: no ``expression`` / ``assert`` /
``forEach`` block, no ``field`` + ``operator`` + ``value`` triple, no regex,
no threshold. The pack-level ``parameters`` / ``metadata`` blocks are reference
data (consistency classes, pour-speed tables, code references), not per-rule
logic. So a declared rule id only ever "runs" when a hand-written
:class:`~app.core.validation.engine.ValidationRule` (or a compiled
:mod:`~app.core.validation.dsl` rule) with that exact ``rule_id`` is registered
in the engine's :data:`~app.core.validation.engine.rule_registry`.

The validation engine already no-ops an unknown *rule set* honestly
(``RuleRegistry.resolve_rule_sets`` -> ``unsupported_rule_sets``,
``ValidationStatus.UNSUPPORTED``). What was missing is the same honesty one
level down, at the *rule id* granularity the packs declare: out of the ~1440
rule ids the packs advertise, only the subset that maps to a registered rule
body actually executes. Without surfacing that split, a counter or report that
echoes a pack's ``enables_rule_ids`` would over-claim coverage - implying every
declared rule validates when most do not.

What this module does (and deliberately does NOT do)
----------------------------------------------------
This resolver reads the pack JSON files and, for each declared rule id, asks
the live ``rule_registry`` whether a real rule body exists for it. It returns a
clear split:

* ``implemented`` - the rule id resolves to a registered, executing rule.
* ``declared_only`` - the rule id is declared by the pack but has NO
  implementation; it would never run and must be reported as "not run", never
  as a silent pass.

It does **not** synthesise rules, does **not** register anything, and does
**not** touch the engine, the registry, or any existing behaviour. Faking
execution for a rule that carries no machine-readable condition is exactly the
"looks validated, isn't" failure mode we refuse to ship - so when the data has
no predicate, we report the truth instead of inventing one.

The result is plain data (dataclasses + dicts) so an API / UI / report layer
can show "12 of 28 rules implemented" instead of a misleading "28 rules".
Everything is lazy and cached; nothing here runs at import time.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Sub-directory inside a pack package that holds the declarative rule-pack
# JSON files. Mirrors the repo convention
# ``packs/<slug>/src/openconstructionerp_*/rule_packs/*.json``.
RULE_PACKS_SUBDIR = "rule_packs"

# The single array key every shipped rule-pack file uses to list the rule ids
# it intends to enable. Kept as a constant so a future schema rename is a
# one-line change here.
ENABLES_KEY = "enables_rule_ids"

# Ids a shipped pack intends to check but the engine does not define yet,
# kept apart from ENABLES_KEY so switching a document on never claims them.
PLANNED_KEY = "planned_not_built_rule_ids"


# ── Result value objects ────────────────────────────────────────────────────


@dataclass(frozen=True)
class RulePackCoverage:
    """Declared-vs-implemented coverage for a single rule-pack JSON file.

    ``implemented`` and ``declared_only`` together partition the file's
    de-duplicated ``enables_rule_ids`` (order-preserving). A rule id lands in
    ``implemented`` only when the live registry has a rule body for it; every
    other declared id is ``declared_only`` and will NOT run.
    """

    pack_id: str  # rule_pack_id / slug / filename stem - whatever the file gives.
    source_pack: str  # The owning partner-pack slug (directory), for provenance.
    display_name: str
    standard: str
    file: str  # Absolute path to the JSON file, for traceability.
    implemented: tuple[str, ...] = ()
    declared_only: tuple[str, ...] = ()

    @property
    def declared_count(self) -> int:
        """Total distinct rule ids the pack declares."""
        return len(self.implemented) + len(self.declared_only)

    @property
    def implemented_count(self) -> int:
        return len(self.implemented)

    @property
    def declared_only_count(self) -> int:
        return len(self.declared_only)

    @property
    def fully_implemented(self) -> bool:
        """True only when every declared rule id resolves to a real rule."""
        return self.declared_count > 0 and not self.declared_only

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe summary for an API / report layer.

        The shape is intentionally explicit (separate ``implemented`` and
        ``declared_only`` lists plus counts) so a caller can render "N of M
        rules active" and list exactly which declared rules do NOT run, rather
        than inferring coverage from a single opaque number.
        """
        return {
            "pack_id": self.pack_id,
            "source_pack": self.source_pack,
            "display_name": self.display_name,
            "standard": self.standard,
            "declared_count": self.declared_count,
            "implemented_count": self.implemented_count,
            "declared_only_count": self.declared_only_count,
            "fully_implemented": self.fully_implemented,
            "implemented": list(self.implemented),
            "declared_only": list(self.declared_only),
        }


@dataclass(frozen=True)
class CoverageSummary:
    """Repo-wide rollup over every discovered rule-pack file.

    ``implemented_rule_ids`` / ``declared_only_rule_ids`` are the DISTINCT
    unions across all packs, so the headline numbers describe unique rules, not
    per-pack repetitions (the same ``boq_quality.position_has_quantity`` is
    declared by many packs but counts once).
    """

    packs: tuple[RulePackCoverage, ...] = ()
    implemented_rule_ids: tuple[str, ...] = ()
    declared_only_rule_ids: tuple[str, ...] = ()

    @property
    def pack_count(self) -> int:
        return len(self.packs)

    @property
    def distinct_declared_count(self) -> int:
        return len(self.implemented_rule_ids) + len(self.declared_only_rule_ids)

    @property
    def distinct_implemented_count(self) -> int:
        return len(self.implemented_rule_ids)

    @property
    def distinct_declared_only_count(self) -> int:
        return len(self.declared_only_rule_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_count": self.pack_count,
            "distinct_declared_count": self.distinct_declared_count,
            "distinct_implemented_count": self.distinct_implemented_count,
            "distinct_declared_only_count": self.distinct_declared_only_count,
            "implemented_rule_ids": list(self.implemented_rule_ids),
            "declared_only_rule_ids": list(self.declared_only_rule_ids),
            "packs": [p.to_dict() for p in self.packs],
        }


# ── Pack-file discovery ──────────────────────────────────────────────────────
#
# A rule-pack JSON file can live in three places, matching how partner packs
# themselves are discovered (see ``app.core.partner_pack.discovery``):
#   1. pip-installed packs - addressed via importlib.resources by module name,
#   2. repo source-checkout packs under ``packs/<slug>/src/...``,
#   3. dropped (data-dir) packs under ``<data_dir>/packs/<slug>/``.
#
# We enumerate the union, de-duped by (source_pack, filename), reusing the
# discovery module's resolvers so this stays in lock-step with how a pack is
# located elsewhere. Discovery is imported lazily inside the functions so a
# missing/half-built partner-pack layer can never break importing this module.


@dataclass(frozen=True)
class _PackFile:
    """A located rule-pack JSON file plus the slug of its owning pack."""

    source_pack: str
    path: Path


def _iter_dir_json(source_pack: str, rule_packs_dir: Path) -> list[_PackFile]:
    """Return every ``*.json`` directly inside ``rule_packs_dir`` (sorted)."""
    if not rule_packs_dir.is_dir():
        return []
    out: list[_PackFile] = []
    for entry in sorted(rule_packs_dir.glob("*.json")):
        if entry.is_file():
            out.append(_PackFile(source_pack=source_pack, path=entry))
    return out


def _discover_pack_files() -> list[_PackFile]:
    """Locate every rule-pack JSON file across all pack sources.

    De-duplicated by ``(source_pack, filename)`` with the same precedence the
    partner-pack discovery uses (entry-point > repo > data-dir), so a
    pip-installed pack's files win over a same-named source-checkout copy.

    Best-effort: any resolver that raises is skipped with a logged warning so
    one broken source never hides the others.
    """
    try:
        from app.core.partner_pack import discovery
    except Exception as exc:  # noqa: BLE001 - partner-pack layer is optional here
        logger.warning("Rule-pack coverage: partner-pack discovery unavailable: %s", exc)
        return []

    try:
        manifests = discovery.discover_packs()
    except Exception as exc:  # noqa: BLE001 - discovery is best-effort
        logger.warning("Rule-pack coverage: discover_packs() failed: %s", exc)
        return []

    # Keyed by (source_pack_slug, filename); later (higher-precedence) sources
    # overwrite earlier ones. We fill data-dir first, then repo, then
    # entry-point, mirroring discover_packs precedence (entry-point wins).
    by_key: dict[tuple[str, str], _PackFile] = {}

    def _add(files: list[_PackFile]) -> None:
        for f in files:
            by_key[(f.source_pack, f.path.name)] = f

    for m in manifests:
        slug = getattr(m, "slug", None)
        if not slug:
            continue

        # 3) data-dir dropped pack (lowest precedence).
        try:
            ddir = discovery._data_dir_package_dir_for_slug(slug)  # noqa: SLF001 - same package family
            if ddir is not None:
                _add(_iter_dir_json(slug, ddir / RULE_PACKS_SUBDIR))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Rule-pack coverage: data-dir lookup failed for %s: %s", slug, exc)

        # 2) repo source-checkout pack.
        try:
            fsdir = discovery._fs_package_dir_for_slug(slug)  # noqa: SLF001
            if fsdir is not None:
                _add(_iter_dir_json(slug, fsdir / RULE_PACKS_SUBDIR))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Rule-pack coverage: repo lookup failed for %s: %s", slug, exc)

        # 1) pip-installed pack via importlib.resources (highest precedence).
        try:
            mod_name = discovery._entrypoint_module_for_slug(slug)  # noqa: SLF001
            if mod_name:
                _add(_iter_resource_json(slug, mod_name))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Rule-pack coverage: entry-point lookup failed for %s: %s", slug, exc)

    return sorted(by_key.values(), key=lambda f: (f.source_pack, f.path.name))


def _iter_resource_json(source_pack: str, module_name: str) -> list[_PackFile]:
    """Enumerate ``rule_packs/*.json`` shipped inside a pip-installed pack.

    Uses ``importlib.resources`` so it works whether the package is a plain
    directory on disk or a wheel; falls back to ``[]`` on any access error.
    """
    try:
        from importlib import resources

        root = resources.files(module_name).joinpath(RULE_PACKS_SUBDIR)
        if not root.is_dir():
            return []
        out: list[_PackFile] = []
        for entry in sorted(root.iterdir(), key=lambda p: p.name):
            if entry.name.endswith(".json") and entry.is_file():
                # ``Path(str(entry))`` is safe for importlib.resources Traversables
                # backed by the filesystem (the only case for our packs). The
                # path is used solely for reading + provenance display.
                out.append(_PackFile(source_pack=source_pack, path=Path(str(entry))))
        return out
    except (ModuleNotFoundError, FileNotFoundError, AttributeError, NotADirectoryError, TypeError):
        return []


# ── Pack-file parsing ────────────────────────────────────────────────────────


def _read_declared_rule_ids(payload: dict[str, Any]) -> list[str]:
    """Pull the de-duplicated, order-preserving ``enables_rule_ids`` list.

    Tolerant of a missing or malformed key: a file with no array (or a
    non-string entry) simply contributes the strings it does have. Non-string
    members are dropped rather than raising so one odd file never breaks the
    whole rollup.

    Ids a shipped pack lists under ``planned_not_built_rule_ids`` are read too:
    they are the pack's stated intent, so the coverage report keeps counting
    them as declared and shows them as not run.
    """
    raw: list[Any] = []
    for key in (ENABLES_KEY, PLANNED_KEY):
        value = payload.get(key)
        if isinstance(value, list):
            raw.extend(value)
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        rid = item.strip()
        if rid and rid not in seen:
            seen.add(rid)
            out.append(rid)
    return out


def _pack_identity(payload: dict[str, Any], file: Path) -> tuple[str, str, str]:
    """Best-effort ``(pack_id, display_name, standard)`` from a pack file."""
    pack_id = payload.get("rule_pack_id") or payload.get("slug") or file.stem
    display_name = payload.get("display_name") or payload.get("name") or str(pack_id)
    standard = payload.get("standard") or ""
    return str(pack_id), str(display_name), str(standard)


def _coverage_for_file(
    pack_file: _PackFile,
    implemented_lookup: set[str],
) -> RulePackCoverage | None:
    """Resolve one pack file against the set of registered rule ids.

    Returns ``None`` (with a logged warning) when the file cannot be read or
    parsed, so a single corrupt pack never aborts the rollup.
    """
    try:
        text = pack_file.path.read_text(encoding="utf-8")
        payload = json.loads(text)
    except Exception as exc:  # noqa: BLE001 - one bad file must not break the rest
        logger.warning("Rule-pack coverage: could not read %s: %s", pack_file.path, exc)
        return None
    if not isinstance(payload, dict):
        logger.warning("Rule-pack coverage: %s is not a JSON object; skipping", pack_file.path)
        return None

    declared = _read_declared_rule_ids(payload)
    implemented = tuple(rid for rid in declared if rid in implemented_lookup)
    declared_only = tuple(rid for rid in declared if rid not in implemented_lookup)
    pack_id, display_name, standard = _pack_identity(payload, pack_file.path)

    return RulePackCoverage(
        pack_id=pack_id,
        source_pack=pack_file.source_pack,
        display_name=display_name,
        standard=standard,
        file=str(pack_file.path),
        implemented=implemented,
        declared_only=declared_only,
    )


# ── Registry snapshot ────────────────────────────────────────────────────────


def _registered_rule_ids() -> set[str]:
    """Snapshot of every rule id with a real body in the live registry.

    A rule id is "implemented" iff ``rule_registry.get_rule(id)`` returns a
    rule object. We read the registry's internal id->rule map through the
    public ``get_rule`` accessor, keyed off the rule-set membership lists, so a
    rule registered under any set (built-in OR a dynamically-imported set such
    as an IDS upload) is counted exactly once.
    """
    try:
        from app.core.validation.engine import rule_registry
    except Exception as exc:  # noqa: BLE001 - engine must exist, but stay defensive
        logger.warning("Rule-pack coverage: validation engine unavailable: %s", exc)
        return set()

    ids: set[str] = set()
    # ``list_rule_sets`` returns {set_name: count}; iterate members per set and
    # confirm each resolves to a real rule via the public accessor. This avoids
    # reaching into the registry's private ``_rules`` dict.
    try:
        for set_name in rule_registry.list_rule_sets():
            for entry in rule_registry.list_rules(rule_set=set_name):
                rid = entry.get("rule_id")
                if rid and rule_registry.get_rule(rid) is not None:
                    ids.add(rid)
    except Exception as exc:  # noqa: BLE001 - never let introspection crash a report
        logger.warning("Rule-pack coverage: could not enumerate registered rules: %s", exc)
    return ids


# ── Public API ───────────────────────────────────────────────────────────────


def resolve_pack_coverage() -> CoverageSummary:
    """Compute declared-vs-implemented coverage for every shipped rule pack.

    This is the single entry point. It:

    1. snapshots the rule ids that currently have a real, executing rule body
       in the engine's registry;
    2. discovers every rule-pack JSON file across all pack sources;
    3. for each file, splits its declared ``enables_rule_ids`` into the ones
       that map to a registered rule (``implemented``) and the ones that do not
       (``declared_only`` - these will NOT run and must never be presented as
       passing).

    The returned :class:`CoverageSummary` carries both the per-pack breakdown
    and the repo-wide distinct unions, so a caller can render honest numbers
    ("X of Y rules implemented") at either granularity.

    NOTE: this is a read-only accounting helper. It never registers rules,
    never mutates the registry, and never changes how validation runs. It is
    intentionally NOT called at import time; call it on demand (it is cheap and
    cached). Call :func:`reset_cache` after the set of registered rules or
    installed packs changes within a process.
    """
    implemented_lookup = _registered_rule_ids()

    packs: list[RulePackCoverage] = []
    impl_union: list[str] = []
    impl_seen: set[str] = set()
    decl_only_union: list[str] = []
    decl_only_seen: set[str] = set()

    for pack_file in _discover_pack_files():
        coverage = _coverage_for_file(pack_file, implemented_lookup)
        if coverage is None:
            continue
        packs.append(coverage)
        for rid in coverage.implemented:
            if rid not in impl_seen:
                impl_seen.add(rid)
                impl_union.append(rid)
        for rid in coverage.declared_only:
            if rid not in decl_only_seen:
                decl_only_seen.add(rid)
                decl_only_union.append(rid)

    # A rule id implemented for one pack but declared-only for another is, in
    # truth, implemented: keep the distinct declared-only union strictly
    # disjoint from the implemented union so the global rollup never lists an
    # implemented rule as a gap.
    decl_only_union = [rid for rid in decl_only_union if rid not in impl_seen]

    summary = CoverageSummary(
        packs=tuple(packs),
        implemented_rule_ids=tuple(impl_union),
        declared_only_rule_ids=tuple(decl_only_union),
    )
    logger.info(
        "Rule-pack coverage resolved: %d pack file(s), %d distinct rule id(s) declared, "
        "%d implemented, %d declared-only (not run)",
        summary.pack_count,
        summary.distinct_declared_count,
        summary.distinct_implemented_count,
        summary.distinct_declared_only_count,
    )
    return summary


@lru_cache(maxsize=1)
def get_pack_coverage() -> CoverageSummary:
    """Cached :func:`resolve_pack_coverage` for the lifetime of the process.

    Pack files and the built-in rule set are static within a normal run, so the
    rollup is computed once. Tests (or a runtime that installs a pack / imports
    new rules) must call :func:`reset_cache` to recompute.
    """
    return resolve_pack_coverage()


def is_rule_implemented(rule_id: str) -> bool:
    """Return True iff ``rule_id`` resolves to a registered, executing rule.

    A thin, honest predicate other code can use to decide whether a declared
    rule id will actually run, instead of assuming a declaration means
    execution. Reads the live registry directly (not the cached rollup) so it
    always reflects the current set of registered rules.
    """
    try:
        from app.core.validation.engine import rule_registry

        return rule_registry.get_rule(rule_id) is not None
    except Exception:  # noqa: BLE001 - absence of the engine means "not implemented"
        return False


def reset_cache() -> None:
    """Clear the cached coverage rollup. Call after packs/rules change."""
    get_pack_coverage.cache_clear()


__all__ = [
    "CoverageSummary",
    "RulePackCoverage",
    "get_pack_coverage",
    "is_rule_implemented",
    "reset_cache",
    "resolve_pack_coverage",
]
