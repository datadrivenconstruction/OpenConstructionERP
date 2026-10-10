# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The seam where a partner pack switches validation rule sets on.

A pack manifest carries two lists that read alike and mean opposite things.
``validation_rule_packs`` names the reference documents the pack ships under
``rule_packs/``; the engine never executes those, and the name is asserted
elsewhere to equal the JSON file stem. ``validation_rule_sets`` names engine
rule-set identifiers, and those are the ones that make rules run.

Before this field existed there was nowhere to write the second kind of name.
Seven packs wrote the standard into the document list instead - ``din_276``
where the registry has ``din276`` - and the installer answered "no built-in
engine match", which is a true statement about the string and a false one about
the standard. It was never the whole defect though: ``validation_rule_packs``
had no runtime consumer at all, so a correctly spelled entry activated exactly
as much as a misspelled one, which is nothing. Both halves are tested here.

Every test that needs the registry measures it in a subprocess with a stated
load set. The registry is not a constant - modules register their own sets when
their ``validators`` module is imported - so an in-process reading describes
whatever the pytest session happens to have loaded rather than the software.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.partner_pack.apply import (
    UnknownRuleSetError,
    inherited_rule_sets,
    resolve_declared_rule_sets,
)
from app.core.partner_pack.manifest import PartnerPackManifest
from tests._pack_manifest_source import (
    PARENT_LITERAL,
    UnreadableParentError,
    declared_lists,
    declared_parent,
    manifest_sources,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND = REPO_ROOT / "backend"
PACKS_DIR = REPO_ROOT / "packs"

# The engine identifier each of the seven affected packs must now declare. The
# fifteen document ids they used to rely on collapse to these eight sets: three
# uk-jct NRM documents all mean ``nrm``, three brazil-sinapi NBR documents all
# mean ``nbr``, and two doker-formwork documents both mean ``formwork``.
EXPECTED_RULE_SETS: dict[str, set[str]] = {
    "bimhessen-de": {"din276", "gaeb"},
    "brazil-sinapi": {"sinapi", "nbr"},
    "doker-formwork": {"formwork"},
    "india-cpwd": {"cpwd"},
    "retail-grocery-dach": {"din276", "gaeb"},
    "uk-jct": {"nrm"},
    "us-costdata": {"masterformat"},
}

_PROBE = """
import importlib, json, pathlib, warnings
warnings.filterwarnings("ignore")
from app.core.validation.rules import register_builtin_rules
from app.core.validation.engine import rule_registry
register_builtin_rules()
for p in sorted(pathlib.Path("app/modules").glob("*/validators.py")):
    try:
        importlib.import_module("app.modules." + p.parent.name + ".validators")
    except Exception:
        pass
print(json.dumps(sorted(rule_registry.list_rule_sets())))
"""


_RULE_ID_PROBE = """
import importlib, json, pathlib, warnings
warnings.filterwarnings("ignore")
from app.core.validation.rules import register_builtin_rules
from app.core.validation.engine import rule_registry
register_builtin_rules()
for p in sorted(pathlib.Path("app/modules").glob("*/validators.py")):
    try:
        importlib.import_module("app.modules." + p.parent.name + ".validators")
    except Exception:
        pass
print(json.dumps(sorted(r["rule_id"] for r in rule_registry.list_rules())))
"""


def _shipped_rule_sets() -> set[str]:
    """Every rule set a clean interpreter registers, core plus module owned."""
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", _PROBE],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, f"the registry probe would not run: {result.stderr[-2000:]}"
    return set(json.loads(result.stdout.strip().splitlines()[-1]))


def _shipped_rule_ids() -> set[str]:
    """Every rule *id* with a real body, measured the same way as the sets.

    One level below :func:`_shipped_rule_sets`. A rule set is what a pack
    switches on; a rule id is what a document's ``enables_rule_ids`` points at,
    and the two answer different questions. Measured in a subprocess for the
    reason given in the module docstring: the registry is filled by imports, so
    an in-process reading describes the pytest session rather than the software.
    """
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", _RULE_ID_PROBE],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, f"the rule-id probe would not run: {result.stderr[-2000:]}"
    return set(json.loads(result.stdout.strip().splitlines()[-1]))


@pytest.fixture(scope="module")
def shipped_rule_sets() -> set[str]:
    return _shipped_rule_sets()


@pytest.fixture(scope="module")
def shipped_rule_ids() -> set[str]:
    return _shipped_rule_ids()


def declared_rule_sets() -> dict[str, list[str]]:
    """Pack slug -> the engine rule-set identifiers its manifest declares.

    Read from the source, never by importing. A pack derived from another one
    states only its own fields, so the reader follows the parent it names; see
    ``tests/_pack_manifest_source.py`` for the rule and for what it refuses.
    """
    return declared_lists(PACKS_DIR, "validation_rule_sets")


def declared_rule_packs() -> dict[str, list[str]]:
    """Pack slug -> the document ids its manifest declares, read the same way."""
    return declared_lists(PACKS_DIR, "validation_rule_packs")


@lru_cache(maxsize=1)
def _manifest_objects() -> dict[str, PartnerPackManifest]:
    """Pack slug -> the manifest object its ``manifest.py`` actually builds.

    The two readers above work on the text of the file. That is what lets them
    run without importing pack code, and it is also what makes them blind to
    any declaration written in a shape their regular expression does not
    describe - a list built from a module constant, a field assigned outside
    the constructor call, a literal carrying a nested bracket. A pack that
    drops out that way reads exactly like a pack that declares nothing, which
    is this file's own defect one level up: the reader returns an empty answer
    and the assertion built on it passes by measuring nothing.

    So the manifests are loaded as objects too, and the readers are held to
    each other by :func:`test_both_readers_see_the_same_declarations`. An
    import that fails raises here rather than yielding an empty list, because
    a discovery step that swallows its own failures is the thing being guarded
    against.

    Returns:
        Every pack's manifest, keyed by the directory name under ``packs/``.
    """
    out: dict[str, PartnerPackManifest] = {}
    for path in sorted(PACKS_DIR.glob("*/src/*/manifest.py")):
        module_name = f"_pack_manifest_under_test_{path.parts[-2]}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        assert spec and spec.loader, f"{path} could not be loaded as a module"
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        out[path.parts[-4]] = module.MANIFEST
    return out


def _shipped_rule_pack_documents() -> list[tuple[str, Path, dict]]:
    """Every ``rule_packs/*.json`` in the tree as ``(slug, path, payload)``.

    The stem reader above answers "which files exist". This one opens them, so
    the assertions below can ask what a document says about itself rather than
    only what its file is called.
    """
    out: list[tuple[str, Path, dict]] = []
    for path in sorted(PACKS_DIR.glob("*/src/*/rule_packs/*.json")):
        out.append((path.parts[-5], path, json.loads(path.read_text(encoding="utf-8"))))
    return out


def _declared_rule_ids(payload: dict) -> list[str]:
    """The ``enables_rule_ids`` a document declares, as written."""
    raw = payload.get("enables_rule_ids")
    return [item for item in raw if isinstance(item, str)] if isinstance(raw, list) else []


def _shipped_rule_pack_stems(slug: str) -> set[str]:
    """The ``rule_packs/*.json`` file stems a pack directory actually contains.

    Args:
        slug: The pack's directory name under ``packs/``.

    Returns:
        The file stems, empty when the pack ships no ``rule_packs`` directory.
    """
    matches = list(PACKS_DIR.glob(f"{slug}/src/*/rule_packs"))
    if not matches:
        return set()
    return {path.stem for path in matches[0].glob("*.json")}


# ── What the packs declare ──────────────────────────────────────────────────


def test_the_probe_measured_a_registry_that_is_actually_loaded(shipped_rule_sets: set[str]) -> None:
    """The control on every other test in this file.

    A probe that reads an under-loaded registry answers "not registered" for
    everything, and every membership assertion below would then pass by
    reading nothing. Ten module ``validators`` imports fail when
    ``DATABASE_URL`` is unset, and the probe swallows those, so the size of
    the answer depends on the environment it ran in. Name the sets the packs
    rely on and check they are present rather than trusting a count.
    """
    assert shipped_rule_sets, "the registry probe came back empty"
    for expected in sorted({name for names in EXPECTED_RULE_SETS.values() for name in names}):
        assert expected in shipped_rule_sets, (
            f"the probe did not see the {expected!r} rule set, so this file cannot "
            "tell a pack that declares it from a pack that does not"
        )


def test_the_discovery_found_packs_and_advertised_rule_sets() -> None:
    """The other control, on the side the registry probe does not cover.

    ``test_the_probe_measured_a_registry_that_is_actually_loaded`` proves the
    engine half was read. Nothing proved the pack half was. Every assertion
    that iterates the packs walks a list built by globbing ``packs/`` and
    reading each manifest, and if that walk comes back empty then "no pack
    advertises a rule set the engine does not register" is true because no
    pack was read. Moving the directory, renaming the file or renaming the
    field would each do it silently.

    Floors, not equalities. A test that asserted the exact counts of the day
    it was written would have to be edited by whoever adds the nineteenth
    pack, and the edit that makes a red test green is the edit nobody reads.
    """
    manifests = sorted(PACKS_DIR.glob("*/src/*/manifest.py"))
    assert len(manifests) >= 15, f"only {len(manifests)} pack manifests were discovered under {PACKS_DIR}"

    declared = declared_rule_sets()
    assert set(declared) == {path.parts[-4] for path in manifests}, (
        "the rule-set reader did not answer for every manifest that was found"
    )

    advertised = sum(len(names) for names in declared.values())
    assert advertised >= 10, (
        f"the packs advertise {advertised} rule sets in total, which is too few for the "
        "reachability assertion below to be measuring anything. Either the field was "
        "renamed or the reader has stopped seeing the shape it is written in."
    )

    documents = sum(len(names) for names in declared_rule_packs().values())
    assert documents >= 80, f"only {documents} rule-pack documents were discovered across {len(manifests)} packs"


def test_both_readers_see_the_same_declarations() -> None:
    """A declaration the text reader cannot see has to fail, not vanish.

    The reader is a regular expression over the source, so it describes one
    way of writing the field. Write it another way - from a constant, or with
    a bracket inside the literal - and the reader returns nothing for that
    pack, which is indistinguishable from a pack that advertises nothing.
    That is the same blind spot that once let a rule set with full
    translations ship without ever executing, and the repair is the same one:
    resolve the name a second way and make the two answers agree.

    The manifest object is the truth here, because it is what the installer
    reads. A disagreement names the pack and the field rather than leaving the
    reader's silence to be read as a clean answer.
    """
    text_sets = declared_rule_sets()
    text_documents = declared_rule_packs()
    objects = _manifest_objects()

    assert set(objects) == set(text_sets), (
        f"the two readers disagree about which packs exist: object reader {sorted(objects)}, "
        f"text reader {sorted(text_sets)}"
    )

    disagreements: dict[str, str] = {}
    for slug, manifest in objects.items():
        if list(manifest.validation_rule_sets) != text_sets[slug]:
            disagreements[f"{slug}.validation_rule_sets"] = (
                f"manifest declares {list(manifest.validation_rule_sets)}, the reader saw {text_sets[slug]}"
            )
        if list(manifest.validation_rule_packs) != text_documents[slug]:
            disagreements[f"{slug}.validation_rule_packs"] = (
                f"manifest declares {list(manifest.validation_rule_packs)}, the reader saw {text_documents[slug]}"
            )

    assert not disagreements, (
        f"a pack declares something the source reader in this file cannot see: {disagreements}. "
        "Every check here that iterates the packs reads the source, so a pack it cannot parse "
        "is a pack it silently exempts. Write the declaration as a plain list literal in the "
        f"constructor call, name the pack it is inherited from in a module-level {PARENT_LITERAL} "
        "literal, or teach the reader the new shape."
    )


# ── A pack derived from another pack ────────────────────────────────────────
#
# A derived manifest is built from its parent's when it is imported, so the
# fields it inherits are written nowhere in its source. The text reader follows
# it to the parent, and that would be a way to satisfy the agreement test above
# with a lie if the parent it follows were not the parent the manifest is
# really built from. These tests close that: the link is stated in two places
# that have to agree, and a link the reader cannot follow raises.


def test_a_derived_pack_names_its_parent_in_both_places() -> None:
    """The literal the text reader follows is the parent the manifest carries.

    ``metadata["derived_from"]`` is what the running product reads (the
    first-run picker, and project creation when it looks for a country's own
    pack). ``DERIVED_FROM`` is what the source gates read. A pack that states
    one and not the other, or two different slugs, is refused here, in both
    directions, so neither can drift from the other unnoticed.
    """
    objects = _manifest_objects()
    sources = manifest_sources(PACKS_DIR)
    from_object = {
        slug: str(manifest.metadata.get("derived_from"))
        for slug, manifest in objects.items()
        if manifest.metadata.get("derived_from")
    }
    from_source = {slug: parent for slug, path in sources.items() if (parent := declared_parent(path))}

    assert from_object, (
        "no pack in the tree carries metadata['derived_from'], so nothing below measures a derived "
        "pack. turkey-tr-mep is one; if it stopped being one, delete this guard with it."
    )
    assert from_source == from_object, (
        f"the parent a manifest object carries and the parent its source names disagree. From the "
        f"objects: {from_object}. From the {PARENT_LITERAL} literals: {from_source}."
    )
    for slug, parent in from_object.items():
        assert parent in objects, f"packs/{slug} is derived from {parent!r}, which is not a pack in the tree"
        assert objects[parent].slug == parent
        assert not objects[parent].metadata.get("derived_from"), (
            f"packs/{slug} is derived from packs/{parent}, which is itself derived"
        )


def test_a_derived_pack_runs_the_rule_sets_of_its_parent() -> None:
    """Not vacuous: the inherited names are really there, on both readers."""
    objects = _manifest_objects()
    text_sets = declared_rule_sets()
    derived = {slug: str(m.metadata["derived_from"]) for slug, m in objects.items() if m.metadata.get("derived_from")}
    assert derived
    for slug, parent in derived.items():
        assert objects[parent].validation_rule_sets, f"packs/{parent} declares no rule set to inherit"
        assert list(objects[slug].validation_rule_sets) == list(objects[parent].validation_rule_sets)
        assert text_sets[slug] == text_sets[parent] == list(objects[parent].validation_rule_sets)


def _plant_manifest(packs_dir: Path, slug: str, body: str) -> None:
    package = packs_dir / slug / "src" / f"openconstructionerp_{slug.replace('-', '_')}"
    package.mkdir(parents=True)
    (package / "manifest.py").write_text(body, encoding="utf-8")


def test_the_source_reader_follows_one_parent_and_lets_an_own_literal_win(tmp_path: Path) -> None:
    _plant_manifest(tmp_path, "base", 'MANIFEST = M(validation_rule_sets=["alpha"], validation_rule_packs=["doc"])\n')
    _plant_manifest(tmp_path, "child", 'DERIVED_FROM = "base"\nMANIFEST = derive(validation_rule_packs=[])\n')
    _plant_manifest(tmp_path, "plain", "MANIFEST = M()\n")

    assert declared_lists(tmp_path, "validation_rule_sets") == {"base": ["alpha"], "child": ["alpha"], "plain": []}
    assert declared_lists(tmp_path, "validation_rule_packs") == {"base": ["doc"], "child": [], "plain": []}


@pytest.mark.parametrize(
    ("child", "why"),
    [
        ('DERIVED_FROM = "absent"\n', "no packs/absent"),
        ('DERIVED_FROM = "middle"\n', "itself derived"),
        ('PARENT = "base"\nDERIVED_FROM = PARENT\n', "plain string literal"),
        ('DERIVED_FROM = ""\n', "plain string literal"),
    ],
)
def test_the_source_reader_refuses_a_parent_it_cannot_follow(tmp_path: Path, child: str, why: str) -> None:
    """Silence is the failure being guarded: each of these used to read as "declares nothing"."""
    _plant_manifest(tmp_path, "base", 'MANIFEST = M(validation_rule_sets=["alpha"])\n')
    _plant_manifest(tmp_path, "middle", 'DERIVED_FROM = "base"\n')
    _plant_manifest(tmp_path, "child", child)

    with pytest.raises(UnreadableParentError, match=why):
        declared_lists(tmp_path, "validation_rule_sets")


def test_every_declared_rule_set_is_one_the_engine_registers(shipped_rule_sets: set[str]) -> None:
    """No pack may name a rule set that does not exist. This is the whole point."""
    unknown = {
        pack: [name for name in names if name not in shipped_rule_sets] for pack, names in declared_rule_sets().items()
    }
    unknown = {pack: names for pack, names in unknown.items() if names}
    assert not unknown, (
        f"these packs declare rule sets the engine does not register: {unknown}. "
        "A rule set the registry has never heard of activates nothing, and nothing "
        "reports it, so it is indistinguishable from a pack that deliberately "
        "activates nothing."
    )


def test_the_seven_affected_packs_declare_the_engine_identifier() -> None:
    """The fifteen. Listed rather than counted, so one cannot arrive under
    cover of another being fixed."""
    declared = declared_rule_sets()
    missing: dict[str, set[str]] = {}
    for pack, expected in EXPECTED_RULE_SETS.items():
        gap = expected - set(declared.get(pack, []))
        if gap:
            missing[pack] = gap
    assert not missing, f"these packs still do not declare the rule sets their documents describe: {missing}"


def test_a_document_id_that_names_a_standard_carries_its_engine_identifier(
    shipped_rule_sets: set[str],
) -> None:
    """The durable form of the guard, covering packs that do not exist yet.

    The predecessor of this test held an allow-list of the fifteen pairings
    that were wrong on the day it was written, and asserted the set of
    findings equalled that list. It could only ever catch a sixteenth. These
    fifteen were grandfathered into it and stayed broken while it read green.

    This asks the question that has an answer worth having: when a pack's
    document id plainly names a standard the engine implements, does the pack
    also declare that engine identifier, so the rules can run?
    """
    from app.core.partner_pack.apply import _near_miss_rule_set

    declared_sets = declared_rule_sets()
    unfixed: dict[tuple[str, str], str] = {}
    for pack, documents in declared_rule_packs().items():
        for document in documents:
            if document in shipped_rule_sets:
                continue
            neighbour = _near_miss_rule_set(document, shipped_rule_sets)
            if neighbour and neighbour not in declared_sets.get(pack, []):
                unfixed[(pack, document)] = neighbour
    assert not unfixed, (
        f"a pack ships a document naming a standard the engine implements, and does not declare "
        f"the engine identifier that would run it: {unfixed}. Add the identifier to "
        "validation_rule_sets. Do not rename the document: its id has to keep matching the "
        "rule_packs/*.json file stem."
    )


def test_the_two_lists_are_kept_in_separate_keyspaces() -> None:
    """A document id must never appear in the rule-set list, or the confusion
    the two fields exist to separate is back in one of them."""
    packs = declared_rule_packs()
    overlap = {pack: sorted(set(names) & set(packs.get(pack, []))) for pack, names in declared_rule_sets().items()}
    overlap = {pack: names for pack, names in overlap.items() if names}
    assert not overlap, (
        f"these names appear in both validation_rule_sets and validation_rule_packs: {overlap}. "
        "An engine identifier is not a document id; a pack that ships a document under the "
        "engine's own name should rename the document."
    )


# ── What the installer does with them ───────────────────────────────────────


def _manifest(**kwargs: object) -> PartnerPackManifest:
    base: dict[str, object] = {
        "slug": "probe-pack",
        "partner_name": "Probe Partner",
        "pack_version": "1.0.0",
        "description": "A manifest built for a test.",
    }
    base.update(kwargs)
    return PartnerPackManifest(**base)  # type: ignore[arg-type]


def test_every_declared_document_id_is_a_file_the_pack_ships() -> None:
    """The document field's own version of "names something that does not exist".

    ``validation_rule_sets`` is refused at apply time when the registry does not
    know a name. ``validation_rule_packs`` had no equivalent across the tree: a
    single test covered two US packs, so the other sixteen could declare a
    document they do not ship and nothing would say so. Both directions are
    asserted because both are silent: a declared id with no file is a reference
    into nothing, and a shipped file no id names is a document that never
    reaches the operator.

    This is a property of each pack measured against its own directory, not a
    pinned list, so a new pack neither needs to be added here nor can slip past.
    """
    missing_file: list[tuple[str, list[str]]] = []
    missing_id: list[tuple[str, list[str]]] = []
    for slug, declared in declared_rule_packs().items():
        on_disk = _shipped_rule_pack_stems(slug)
        names = set(declared)
        if names - on_disk:
            missing_file.append((slug, sorted(names - on_disk)))
        if on_disk - names:
            missing_id.append((slug, sorted(on_disk - names)))

    assert not missing_file, f"pack(s) declare a rule-pack document they do not ship: {missing_file}"
    assert not missing_id, f"pack(s) ship a rule-pack document nothing declares: {missing_id}"


# ── What a document says about itself ───────────────────────────────────────
#
# The test above pairs a manifest declaration with a file name. Nothing paired
# a file with its own contents: a document could call itself something else,
# repeat a rule id, or point its whole ``enables_rule_ids`` list at rules that
# do not exist, and every assertion in this file would still read green.


def test_a_document_calls_itself_by_its_own_file_name() -> None:
    """``rule_pack_id`` has to equal the stem, because the stem is the join key.

    ``test_every_declared_document_id_is_a_file_the_pack_ships`` matches the
    manifest's declared ids against file names, and the coverage resolver keys
    a document by the ``rule_pack_id`` *inside* it. When those two disagree the
    operator is told the pack covers a standard under one name while every
    report about it comes back under another, and nothing raises.

    The older sibling of this assertion exists five times over, once each in
    the uk, us-state, china, hungary and russia pack tests, which between them
    cover five of the packs under ``packs/``. Written once here it covers all
    of them, including the ones that do not have a per-country test file.

    ``slug`` is accepted in place of ``rule_pack_id`` because a minority of
    documents use it, and the resolver's ``_pack_identity`` accepts it too; the
    point is that whichever field carries the identity agrees with the name the
    rest of the system joins on.
    """
    documents = _shipped_rule_pack_documents()
    assert len(documents) >= 150, (
        f"only {len(documents)} rule-pack documents were opened; the glob has stopped "
        "seeing the tree and every assertion below would pass by reading nothing"
    )

    disagreements = {
        f"{slug}/{path.name}": identity
        for slug, path, payload in documents
        if (identity := payload.get("rule_pack_id") or payload.get("slug")) != path.stem
    }
    assert not disagreements, (
        f"document(s) disagree with their own file name: {disagreements}. The file stem is "
        "what a manifest declares and what the coverage resolver reports under, so a "
        "document that calls itself something else is reachable under neither name."
    )


def test_a_document_does_not_declare_the_same_rule_twice() -> None:
    """A repeated rule id is a typo that inflates a coverage count.

    The resolver de-duplicates before counting, so a repeat never reaches a
    report as a double. That is exactly why it has to be caught here: the one
    place it would show up is a partner writing two different rules and getting
    one of them wrong, and the de-duplication hides the evidence.
    """
    repeats = {}
    for slug, path, payload in _shipped_rule_pack_documents():
        ids = _declared_rule_ids(payload)
        if len(ids) != len(set(ids)):
            repeats[f"{slug}/{path.name}"] = sorted({rid for rid in ids if ids.count(rid) > 1})
    assert not repeats, f"document(s) declare the same rule id more than once: {repeats}"


def test_a_document_whose_rule_ids_name_nothing_is_reported_and_never_counted_as_covered() -> None:
    """The negative control for ``enables_rule_ids``, run against shipped code.

    A document is a declaration; the rules it names are written separately, so
    an id that resolves to nothing is common in this register. It is common
    because it is recorded debt, not because it is the intended shape:
    ``test_uk_pack`` pins the count per pack precisely so a pack that is clean
    stays clean. What ``pack_coverage`` has to guarantee is the narrower thing,
    that the debt is never indistinguishable from coverage. It is the component
    that draws that line, so the guard belongs on it: feed it a document whose
    every id names nothing and require it to say so.

    Built inline rather than pinned to a real pack, so the assertion keeps its
    meaning when somebody implements the rules a real document is waiting for.
    """
    from app.core.validation.pack_coverage import _coverage_for_file, _PackFile

    real = "boq_quality.position_has_quantity"
    invented = [
        "spurious_pack.rule_that_does_not_exist",
        "spurious_pack.another_one",
        "din276.a_well_formed_id_in_a_real_namespace_that_names_nothing",
    ]
    document = {
        "rule_pack_id": "probe_document",
        "name": "A document built for a test",
        "standard": "none",
        "enables_rule_ids": [real, *invented],
    }

    with tempfile.TemporaryDirectory() as tmp:
        written = Path(tmp) / "probe_document.json"
        written.write_text(json.dumps(document), encoding="utf-8")
        coverage = _coverage_for_file(_PackFile(source_pack="probe-pack", path=written), {real})

    assert coverage is not None, "the resolver refused a well-formed document"
    assert coverage.implemented == (real,), (
        f"the one implemented rule was not reported as implemented: {coverage.implemented}"
    )
    assert list(coverage.declared_only) == invented, (
        f"a rule id that names nothing was not reported as declared-only: {coverage.declared_only}"
    )
    assert coverage.implemented_count == 1, "the count over-claims"
    assert coverage.declared_only_count == len(invented)
    assert coverage.fully_implemented is False, (
        "a document whose rules mostly do not exist reported itself as fully implemented, "
        "which is the 'looks validated, isn't' failure this resolver exists to prevent"
    )


def test_the_three_repaired_packs_name_only_rules_that_actually_run(shipped_rule_ids: set[str]) -> None:
    """austria-at, canada-ca and switzerland-ch declare nothing the engine lacks.

    These three shipped a manifest declaring documents they did not carry, so
    every rule id they advertised resolved to nothing by way of a file that was
    not there. Writing the files is only half a repair: a document that lands
    and then names rules nobody wrote reproduces the same lie one layer down,
    and this time with a file to back it up.

    The property asserted is total rather than a floor. A floor ("at least one
    id resolves") passes a document that grounds one id and invents twelve,
    which is the shape the debt in ``test_uk_pack`` was accumulated in. These
    three packs were absent from that debt list before the repair and have to
    stay absent, so the bar here is the one that keeps them absent.

    The honest way to meet it is an empty list, not a padded one. Eleven of the
    twelve Canadian documents and two of the three Swiss ones enable nothing,
    because the engine registers no Canadian or Swiss rules and a building code
    is not satisfied by a bill-arithmetic check wearing its name. Each of those
    carries ``why_no_rules``, which is the shape ``uk-jct`` already uses.
    """
    assert shipped_rule_ids, "the rule-id probe came back empty"
    assert "boq_quality.position_has_quantity" in shipped_rule_ids, (
        "the probe did not see a rule this repo certainly registers, so it is measuring "
        "an under-loaded registry and every assertion below would read as 'names nothing'"
    )

    unbacked: dict[str, list[str]] = {}
    silent: list[str] = []
    for slug in ("austria-at", "canada-ca", "switzerland-ch"):
        documents = [(p, d) for s, p, d in _shipped_rule_pack_documents() if s == slug]
        assert documents, f"{slug} ships no rule-pack document at all"

        for path, payload in documents:
            declared = _declared_rule_ids(payload)
            missing = [rid for rid in declared if rid not in shipped_rule_ids]
            if missing:
                unbacked[f"{slug}/{path.name}"] = missing
            if not declared and len((payload.get("why_no_rules") or "").strip()) <= 80:
                silent.append(f"{slug}/{path.name}")

    assert not unbacked, (
        f"document(s) promise checks the engine does not define: {unbacked}. Measured against "
        f"{len(shipped_rule_ids)} registered rule ids. An id nothing implements reads to an "
        "operator as a check that runs, and the pack reports no error either way; remove it, or "
        "write the rule."
    )
    assert not silent, (
        f"document(s) enable nothing and do not say why, or explain themselves in a sentence "
        f"fragment: {silent}. An empty list is the right answer for a standard the engine does "
        "not check, but it is also what a document looks like when the ids were deleted without "
        "a decision, so it has to explain itself. The 80-character floor is the one "
        "``test_uk_pack`` already applies to the same field."
    )


def test_a_demo_project_carries_its_own_rule_sets_rather_than_inheriting_them() -> None:
    """The one project the inheritance does not reach, asserted so it stays covered.

    ``install_demo_project`` builds its project straight from the template and
    never goes through ``ProjectService.create``, so a pack's demo does not
    inherit the pack's ``validation_rule_sets`` - it validates against whatever
    the template declares. That is why applying a pack changes nothing about
    its own demo, and it is fine as long as every template declares something.
    A template with an empty list would hand its project the empty list, which
    is the original defect in a new place: rules registered, nothing running,
    no error anywhere.
    """
    from app.core.demo_projects import DEMO_TEMPLATES, PACK_DEMO_PROJECT

    silent = sorted(name for name, tpl in DEMO_TEMPLATES.items() if not (tpl.validation_rule_sets or []))
    assert not silent, f"demo template(s) {silent} would create a project that validates against nothing"

    unregistered = sorted(slug for slug, demo in PACK_DEMO_PROJECT.items() if demo not in DEMO_TEMPLATES)
    assert not unregistered, f"pack(s) {unregistered} point at a demo project that is not registered"


@pytest.mark.parametrize(
    ("bad", "why"),
    [
        ("DIN276", "upper case"),
        ("din_276.json", "a file extension, which is what a document id looks like"),
        ("ids_custom:42", "the colon form of a project-scoped set"),
        ("276din", "a leading digit"),
        ("din 276", "a space"),
        ("", "empty"),
    ],
)
def test_a_name_shaped_wrong_is_refused_when_the_manifest_is_built(bad: str, why: str) -> None:
    """The shape check on the field itself.

    It runs at import time, when the registry is still empty, so it can only
    judge the string. Each of these is a shape no registered set has, and each
    is a plausible thing to write: the file name and the upper-case spelling
    are how the fifteen document ids were written in the first place.
    """
    with pytest.raises(ValidationError) as excinfo:
        _manifest(validation_rule_sets=[bad])
    assert "validation_rule_sets" in str(excinfo.value), f"the refusal of {bad!r} ({why}) did not name the field"


def test_the_shape_check_does_not_pretend_to_know_the_registry() -> None:
    """``din_276`` is well-formed and is not a rule set, and this check passes it.

    That is deliberate and it is the whole reason a second check exists at
    apply time, so assert it rather than leave it to be discovered. If someone
    ever moves the registry lookup into the validator this test fails, and the
    thing to notice then is that pack manifests are built before any rule is
    registered: the lookup would read an empty registry and refuse everything.
    """
    manifest = _manifest(validation_rule_sets=["din_276"])
    assert manifest.validation_rule_sets == ["din_276"]
    with pytest.raises(UnknownRuleSetError):
        resolve_declared_rule_sets(manifest, strict=True)


def test_the_same_rule_set_cannot_be_declared_twice() -> None:
    """A repeat is a typo worth naming, not something to silently de-duplicate.

    The engine tolerates a repeated set, so nothing downstream would ever
    complain; a pack listing ``['nrm', 'nrm']`` is a partner who meant to write
    two different standards and got one of them wrong.
    """
    with pytest.raises(ValidationError, match="repeats"):
        _manifest(validation_rule_sets=["nrm", "nrm"])


def test_a_rule_set_the_engine_does_not_register_is_refused_loudly() -> None:
    """The negative control.

    ``spurious_ruleset_for_this_test`` is a name nothing in the tree uses, so
    a refusal here cannot come from anything but the check under test. The
    original defect was silent, and a check that only proves the good path
    would reproduce it exactly: activating nothing is green.
    """
    m = _manifest(validation_rule_sets=["boq_quality", "spurious_ruleset_for_this_test"])
    with pytest.raises(UnknownRuleSetError) as excinfo:
        resolve_declared_rule_sets(m, strict=True)
    assert "spurious_ruleset_for_this_test" in str(excinfo.value)
    assert "boq_quality" not in str(excinfo.value), "the message should name the offender, not the innocent entry"


def test_a_misspelled_standard_is_refused_and_the_message_names_the_spelling_that_works() -> None:
    """The exact fifteen-declaration shape: right standard, wrong spelling."""
    m = _manifest(validation_rule_sets=["din_276"])
    with pytest.raises(UnknownRuleSetError) as excinfo:
        resolve_declared_rule_sets(m, strict=True)
    message = str(excinfo.value)
    assert "din_276" in message
    assert "din276" in message, "a refusal that does not name the working spelling makes the reader guess"


def test_an_empty_registry_is_refused_rather_than_read_as_a_clean_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A reader that returns nothing on failure answers "not registered" for
    every name, which is the same shape as the bug: nothing activates and
    nothing complains. Refuse instead of concluding."""
    import app.core.partner_pack.apply as apply_module

    monkeypatch.setattr(apply_module, "_known_rule_sets", set)
    with pytest.raises(UnknownRuleSetError) as excinfo:
        resolve_declared_rule_sets(_manifest(validation_rule_sets=["boq_quality"]), strict=True)
    assert "registry" in str(excinfo.value).lower()


def test_a_pack_that_declares_nothing_is_not_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Most packs declare no rule set at all, and an empty list is a decision,
    not an error. It must survive even the empty-registry refusal above."""
    import app.core.partner_pack.apply as apply_module

    monkeypatch.setattr(apply_module, "_known_rule_sets", set)
    assert resolve_declared_rule_sets(_manifest(), strict=True) == []


def test_a_module_owned_rule_set_is_refused_while_its_module_is_unloaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deliberate behaviour change, recorded here so it is not a surprise.

    ``formwork`` is registered by ``app.modules.formwork.validators``, which the
    module loader imports only for the modules it loads. Disable the formwork
    module and the set leaves the registry, so applying doker-formwork raises
    instead of installing a pack whose validation cannot run. The message has to
    say that, or the admin reads "the engine does not have it" and goes looking
    for a rule that exists.
    """
    import app.core.partner_pack.apply as apply_module

    monkeypatch.setattr(apply_module, "_known_rule_sets", lambda: {"boq_quality", "din276"})
    with pytest.raises(UnknownRuleSetError) as excinfo:
        resolve_declared_rule_sets(_manifest(slug="doker-formwork", validation_rule_sets=["formwork"]), strict=True)
    message = str(excinfo.value)
    assert "formwork" in message
    assert "module" in message, "the message does not tell the admin a disabled module is the likely cause"


def test_the_registered_sets_come_back_in_the_order_declared() -> None:
    m = _manifest(validation_rule_sets=["gaeb", "din276", "boq_quality"])
    assert resolve_declared_rule_sets(m, strict=True) == ["gaeb", "din276", "boq_quality"]


# ── What a project inherits ─────────────────────────────────────────────────


def test_a_project_created_under_a_pack_keeps_its_own_rule_sets_and_gains_the_packs() -> None:
    """Inheritance is additive. A caller who asked for a rule set keeps it."""
    m = _manifest(validation_rule_sets=["din276", "gaeb"])
    assert inherited_rule_sets(["boq_quality"], m) == ["boq_quality", "din276", "gaeb"]


def test_inheritance_does_not_repeat_a_rule_set_the_project_already_had() -> None:
    m = _manifest(validation_rule_sets=["din276", "gaeb"])
    assert inherited_rule_sets(["gaeb", "boq_quality"], m) == ["gaeb", "boq_quality", "din276"]


def test_inheritance_without_a_pack_returns_the_project_list_untouched() -> None:
    assert inherited_rule_sets(["boq_quality"], None) == ["boq_quality"]


def test_inheritance_never_hands_back_an_empty_list() -> None:
    """``Project.validation_rule_sets`` empty means "validate nothing", and a
    project that inherited a pack has more reason to validate, not less."""
    assert inherited_rule_sets([], None) == ["boq_quality"]
    assert inherited_rule_sets(None, _manifest(validation_rule_sets=["nrm"])) == ["boq_quality", "nrm"]


def test_inheritance_drops_a_rule_set_the_engine_does_not_register(monkeypatch: pytest.MonkeyPatch) -> None:
    """Project creation must never fail because a pack is wrong, and must never
    write an identifier that would silently match nothing later."""
    import app.core.partner_pack.apply as apply_module

    monkeypatch.setattr(apply_module, "_known_rule_sets", lambda: {"boq_quality", "din276"})
    m = _manifest(validation_rule_sets=["din276", "spurious_ruleset_for_this_test"])
    assert inherited_rule_sets(["boq_quality"], m) == ["boq_quality", "din276"]


# ── What the newly declared sets do to a bill of quantities ─────────────────

_FORMWORK_SCOPE_PROBE = """
import asyncio, json, warnings
warnings.filterwarnings("ignore")
from app.core.validation.rules import register_builtin_rules
from app.core.validation.engine import validation_engine
from app.modules.formwork.validators import FORMWORK_RULE_SET, register_formwork_rules

register_builtin_rules()
register_formwork_rules()

BOQ = {
    "positions": [
        {
            "id": "p1",
            "ordinal": "01.001",
            "description": "Wall formwork, framed panel system, class SB2",
            "unit": "m2",
            "quantity": "1200.000",
            "unit_rate": "38.50",
            "total_price": "46200.00",
        }
    ]
}
FORMWORK = {
    "scope": "assignment",
    "assignment": {"id": "a1", "system_name": "Probe system", "area_m2": "0"},
    "pours": [],
}


async def main():
    out = {}
    for label, data, target in (("boq", BOQ, "boq"), ("formwork", FORMWORK, "formwork_assignment")):
        report = await validation_engine.validate(
            data=data, rule_sets=[FORMWORK_RULE_SET], target_type=target, target_id=label
        )
        out[label] = {
            "results": len(report.results),
            "engine_errors": len(report.engine_errors),
            "failures": len(report.errors) + len(report.warnings) + len(report.infos),
            "unsupported": list(report.unsupported_rule_sets),
        }
    print(json.dumps(out))


asyncio.run(main())
"""


def test_the_formwork_rule_set_is_scope_gated_and_says_nothing_about_a_bill_of_quantities() -> None:
    """``formwork`` is the one newly declared set that does not read BOQ rows.

    Its rules take an assignment-and-pours payload and return nothing for any
    other scope. That is what makes declaring it on doker-formwork safe: a
    project that inherits it and then validates a BOQ gets no findings from it
    and, crucially, no rule-execution errors either. The formwork endpoints
    still request the set explicitly and still get real answers.

    The second half of the probe is the positive control. Without it a green
    result would equally well mean the rules never registered, which is the
    original bug wearing a passing test.
    """
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", _FORMWORK_SCOPE_PROBE],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, f"the formwork probe would not run: {result.stderr[-2000:]}"
    measured = json.loads(result.stdout.strip().splitlines()[-1])

    assert measured["formwork"]["results"] > 0, (
        "the formwork rules produced nothing on a formwork payload, so the run below "
        "measures an empty registry rather than a scope gate"
    )
    assert measured["formwork"]["failures"] > 0, (
        "the formwork payload was built to fail (zero area, no pours) and passed, so the "
        "positive control does not discriminate"
    )
    assert measured["boq"]["results"] == 0, f"the formwork rules reported on a bill of quantities: {measured['boq']}"
    assert measured["boq"]["engine_errors"] == 0, (
        f"the formwork rules raised on a bill of quantities: {measured['boq']}"
    )
