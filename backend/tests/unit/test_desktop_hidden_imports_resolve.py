"""Guard: every ``app.*`` hidden import in the desktop spec names a real file.

PyInstaller reports a hidden import it cannot find and keeps going:

    ERROR: Hidden import 'app.modules.<name>.repository' not found

The sidecar build for 15.4.0 printed 167 of those, and all 167 were invented by
``desktop/pyinstaller.spec`` itself: the module auto-discovery loop named six
layers for each of the 191 module packages whether or not the files existed.
Nothing was missing and nothing was broken, which is exactly what made it
dangerous. A dependency that really is absent from the frozen sidecar announces
itself in the same words, on the same channel, and it would have arrived as one
more line in a wall of them. The founder-visible end of that is a user with a
broken install and a build log that could not warn anyone.

The spec now asks the disk before it names a layer, so the channel is quiet and
a line on it means something. This test holds that open in both directions.

What it proves and what it does not: it proves the spec generates no ``app.*``
hidden import that the source tree cannot back. It says nothing about a build
log being clean, and it cannot - the residual noise on a real build comes from
upstream hooks (psycopg2's probe for MySQLdb / pysqlite2 / mx.DateTime,
pycparser's generated lextab / yacctab, scipy's _cdflib, torch's optional
tensorboard, nvcuda.dll on a machine with no CUDA) and none of that is ours to
declare.

The last test covers the other route into the bundle. ``module_loader`` imports
some layers by name under ``contextlib.suppress(ModuleNotFoundError)``, so if
one of those does not resolve inside the frozen sidecar the module simply never
registers its subscribers, with no error and no log line. Measured against the
published 15.4.0 Windows installer, 23 ``events.py``, 3 ``validators.py`` and
the single ``pipeline_nodes.py`` are absent from the PYZ and reach the bundle
only as source, carried by the ``backend/app`` tree in ``datas``. They do
resolve: PyInstaller's frozen path finder falls back to python's FileFinder on
the same directory, which is where that tree lands. That makes the ``datas``
line load-bearing for imports and not only for data, which is not what it says
about itself, so the test below fails if it is ever narrowed.

There is a second direction, and for a long time nothing here could see it.
Everything above asks whether a name the spec declares is backed by a file.
Nothing asked the reverse - whether a file the backend reaches for by name is
declared - and the one helper that looked like it could, ``_module_layers``,
reads the tuple out of the spec itself. A seventh layer the spec had never
heard of could not fail a gate that takes its expectation from the spec. That
shape answers the same on a correct tree and on a broken one.

``data_repairs.py`` walked into exactly that hole. It walks ``app.modules`` and
imports ``<name>.repairs`` by name, and ``repairs`` appeared in no layer tuple
anywhere. It did resolve, through the ``datas`` tree described above, which is
the luck this file already documents rather than a design. Had it not, the
repair pass would have registered nothing, attempted nothing, failed nothing,
and left the health endpoint describing a clean boot on the desktop build -
the only install route that ships no migration tree at all.

So the expectation now comes from the backend source rather than from the spec.
Every f-string under ``backend/app`` shaped like ``app.modules.{...}.<layer>``
is parsed out, including the ones whose layer name sits behind a module-level
constant, and the spec has to declare every one of those layers that some
module actually carries a file for. Frequency on disk deliberately plays no
part: ``repairs.py`` exists in three modules against 193 manifests, so any rule
keyed on how common a filename is would rank the layer that most needs naming
with the one-off helpers.

Two things stop that direction going green on an empty read, because it is an
EXISTS-direction gate and those fail open. It carries floors on how much it
examined - source files, layer names, module packages - and a control feeds the
scanner a fixture holding a literal slot, a constant slot and a slot it cannot
resolve. The constant branch is the only one that reaches ``repairs``, so it
has to keep working or the control goes red. An f-string of the right shape
whose layer cannot be resolved is reported as a failure rather than skipped;
that is the one place a future rewrite could hide a layer from this gate, and
it is loud.

It is a pure file-parsing test - the spec is executed with PyInstaller's own
symbols stubbed out, no application import, no build - so it runs anywhere the
suite is collected.
"""

import ast
import sys
import types
from functools import lru_cache
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
_DESKTOP = _BACKEND.parent / "desktop"
_SPEC = _DESKTOP / "pyinstaller.spec"
_APP = _BACKEND / "app"
_MODULES = _APP / "modules"

#: Prefix every per-module dotted path starts with. The scanner below keys on
#: it rather than on a list of loader files, so a discovery pass written in a
#: module tomorrow is read by the same code that reads ``module_loader``.
_MODULES_PREFIX = "app.modules."

# A floor on how many names this guard actually looked at. Without it the whole
# file passes green the day the discovery loop moves out of the spec or an
# upstream rename empties the capture: zero unresolvable names out of twelve
# examined reads identically to zero out of twelve hundred. The tree carries
# 195 module packages and roughly 1100 layer files, so anything under this means
# the instrument stopped seeing the population, not that the population shrank.
_MIN_APP_HIDDEN_IMPORTS = 900

# Floors for the source-derived direction, all set under a measurement taken on
# this tree rather than guessed. Every one of them exists because the check they
# guard passes trivially on nothing: an empty scan declares no missing layer.
#
#   * source files examined - 1304 under backend/app mention ``app.modules.``
#     today. A prefilter that stops matching, a walk rooted at the wrong
#     directory, or a suite run from a partial checkout all show up here first.
#   * layer names found - 9 today (events, hooks, manifest, models,
#     pipeline_nodes, repairs, router, schema, validators). ``module_loader``
#     alone accounts for 7 of them, so anything under 6 means a whole discovery
#     site stopped being read.
#   * module packages - 195 today. The same floor the census helpers rest on.
_MIN_SCANNED_SOURCES = 800
_MIN_DYNAMIC_LAYERS = 6
_MIN_MODULE_PACKAGES = 150


class _Opaque:
    """Stand-in for the PyInstaller objects the spec chains attributes off."""

    def __getattr__(self, name: str) -> "_Opaque":
        return _Opaque()


def _run_spec() -> tuple[dict, dict]:
    """Execute ``desktop/pyinstaller.spec``; return its Analysis kwargs and namespace.

    Reading the ``Analysis(hiddenimports=...)`` argument rather than the
    ``hidden_imports`` local is deliberate: the argument is what reaches
    PyInstaller, and a future edit that builds one list and passes another
    would leave this guard measuring the wrong object.

    The namespace comes back with it so the layer names can be read out of the
    spec instead of copied into this file. A second copy would go stale the
    first time the spec learns a layer, and it would go stale in the direction
    that reads worst: the historical control below would report the new layer's
    files as unbacked when they are on disk.
    """
    captured: dict = {}

    def _analysis(*_args, **kwargs) -> _Opaque:
        captured.update(kwargs)
        return _Opaque()

    hooks = types.ModuleType("PyInstaller.utils.hooks")
    # Third-party packages are not installed in the test environment, so the
    # real collect_submodules cannot run and its results are not what this
    # guard is about. The names it returns belong to qdrant_client and
    # sentence_transformers, which requirements-desktop.lock covers and
    # test_desktop_lock_deps.py checks.
    hooks.collect_submodules = lambda *_a, **_k: []
    utils = types.ModuleType("PyInstaller.utils")
    utils.hooks = hooks
    package = types.ModuleType("PyInstaller")
    package.utils = utils

    stubs = {
        "PyInstaller": package,
        "PyInstaller.utils": utils,
        "PyInstaller.utils.hooks": hooks,
    }
    saved = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    try:
        namespace = {
            "__file__": str(_SPEC),
            "__name__": "pyinstaller_spec_under_test",
            # PyInstaller injects SPECPATH into the spec's namespace; the spec
            # derives every path in it from that one value.
            "SPECPATH": str(_DESKTOP),
            "Analysis": _analysis,
            "PYZ": lambda *_a, **_k: _Opaque(),
            "EXE": lambda *_a, **_k: _Opaque(),
            "COLLECT": lambda *_a, **_k: _Opaque(),
        }
        exec(compile(_SPEC.read_text(encoding="utf-8"), str(_SPEC), "exec"), namespace)  # noqa: S102
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    assert captured, f"parsed no Analysis(...) call from {_SPEC}; this guard went blind"
    return captured, namespace


def _app_hidden_imports() -> list[str]:
    hidden = _run_spec()[0].get("hiddenimports")
    assert isinstance(hidden, list), f"Analysis in {_SPEC} was given no hiddenimports list"
    return [name for name in hidden if name == "app" or name.startswith("app.")]


def _module_layers() -> tuple[str, ...]:
    """The per-module layers the spec declares, read out of the spec itself."""
    layers = _run_spec()[1].get("_MODULE_LAYERS")
    assert layers, (
        f"{_SPEC} no longer defines _MODULE_LAYERS. The historical control in this file rebuilds the "
        "pre-fix cross product from that tuple, so it cannot run without it. Restore the name or "
        "rewrite the control against whatever replaced it - do not leave it reading an empty set."
    )
    return tuple(layers)


def _unresolvable(names) -> list[str]:
    """Names with no ``.py`` file and no package directory under ``backend/``."""
    missing = []
    for dotted in names:
        base = _BACKEND.joinpath(*dotted.split("."))
        if not base.with_suffix(".py").is_file() and not (base / "__init__.py").is_file():
            missing.append(dotted)
    return sorted(missing)


def _module_packages() -> set[str]:
    return {path.parent.name for path in _MODULES.glob("*/__init__.py")}


def _absent_layers_by_census() -> set[str]:
    """The absent layer names, counted a second way.

    ``_unresolvable`` stats one path per candidate name. This globs the tree
    per layer and subtracts, so the two disagree if either instrument is
    miscounting. An upper-bound gate that trusts a single matcher passes when
    that matcher undercounts, and the number this produces is the denominator
    the negative control below rests on.
    """
    packages = _module_packages()
    absent = set()
    for layer in _module_layers():
        present = {path.parent.name for path in _MODULES.glob(f"*/{layer}.py")}
        present |= {path.parent.parent.name for path in _MODULES.glob(f"*/{layer}/__init__.py")}
        absent |= {f"app.modules.{name}.{layer}" for name in packages - present}
    return absent


def _pre_fix_hidden_imports() -> list[str]:
    """The discovery loop as it stood before the disk check, verbatim.

    This is the shipped defect, reproduced. It is what the negative control
    below runs the checker against, so the control is a repeat of the real
    failure rather than an invented one. The defect was the full cross product
    of module packages and whatever layers the spec names, so the layer tuple
    is read from the spec rather than pinned here.
    """
    layers = _module_layers()
    names = []
    for mod_dir in sorted(_MODULES.iterdir()):
        if mod_dir.is_dir() and (mod_dir / "__init__.py").exists():
            names.append(f"app.modules.{mod_dir.name}")
            names.extend(f"app.modules.{mod_dir.name}.{layer}" for layer in layers)
    return names


def test_every_app_hidden_import_in_the_desktop_spec_resolves_to_a_file() -> None:
    names = _app_hidden_imports()
    assert len(names) >= _MIN_APP_HIDDEN_IMPORTS, (
        f"the desktop spec declares only {len(names)} app.* hidden imports, under the floor of "
        f"{_MIN_APP_HIDDEN_IMPORTS}. The tree has {len(_module_packages())} module packages, so this "
        f"guard is no longer reading the discovery loop and a zero from it means nothing. Names seen: "
        f"{sorted(names)}"
    )

    missing = _unresolvable(names)
    assert not missing, (
        f"{len(missing)} hidden import(s) in {_SPEC} name nothing on disk, and PyInstaller will print "
        f"one 'Hidden import ... not found' line for each of them on every desktop build:\n  "
        + "\n  ".join(missing)
        + "\nEither the file is genuinely missing from the sidecar - which is the case this channel "
        "exists to report - or the spec is naming a layer that was never there. Do not silence it by "
        "adding the name to excludes: that list means 'nothing in the sidecar imports this'."
    )


def test_a_hidden_import_that_names_a_file_that_is_not_there_is_reported() -> None:
    """Negative control, one injected name: the checker must single it out."""
    invented = "app.modules.boq.this_layer_was_never_written"
    flagged = _unresolvable([*_app_hidden_imports(), invented])
    assert flagged == [invented], (
        "the checker did not isolate a hidden import naming a file that does not exist; it returned "
        f"{flagged} instead of exactly ['{invented}']"
    )


def test_the_checker_reports_the_layers_the_pre_fix_loop_invented() -> None:
    """Negative control, the real defect: the pre-fix loop, measured two ways."""
    pre_fix = _pre_fix_hidden_imports()
    flagged = set(_unresolvable(pre_fix))
    census = _absent_layers_by_census()

    assert flagged, (
        "the pre-fix discovery loop produced no unresolvable name, so this control proves nothing "
        "about the checker. Either every module now carries all six layers or the checker is broken."
    )
    assert flagged == census, (
        "the two ways of counting the absent layers disagree, so one of them is undercounting. "
        f"Only stat() saw: {sorted(flagged - census)}. Only the glob census saw: {sorted(census - flagged)}"
    )

    # 167 on the 15.4.0 tree. Asserted as a relationship rather than as a
    # literal, because the number moves the moment a module gains or loses a
    # layer file and a stale literal would fail for the wrong reason.
    print(f"pre-fix loop: {len(pre_fix)} names, {len(flagged)} of them unresolvable")
    print("\n".join(sorted(flagged)))

    kept = {name for name in _app_hidden_imports() if name.startswith("app.modules.")}
    assert kept == set(pre_fix) - flagged, (
        "the disk-driven loop did not simply drop the names that no file backs. Dropped but still "
        f"backed: {sorted((set(pre_fix) - flagged) - kept)}. Added and not backed: {sorted(kept - set(pre_fix))}"
    )


def _fstring_template(node: ast.JoinedStr) -> tuple[str, list[ast.expr]] | None:
    """Flatten an f-string into a ``{}``-placeholder template plus its expressions.

    Returns ``None`` for an f-string carrying anything other than plain string
    literals and substitutions, which is not a shape any dotted module path in
    this codebase is built with.
    """
    parts: list[str] = []
    expressions: list[ast.expr] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        elif isinstance(value, ast.FormattedValue):
            parts.append("{}")
            expressions.append(value.value)
        else:
            return None
    return "".join(parts), expressions


def _assigned_names(node: ast.AST) -> list[str]:
    targets: list[ast.expr] = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
    return [target.id for target in targets if isinstance(target, ast.Name)]


def _module_level_string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level ``NAME = "literal"`` bindings.

    ``data_repairs.py`` holds its layer name in one of these
    (``REPAIRS_MODULE_NAME = "repairs"``) and interpolates the constant rather
    than the word. A scanner that reads only literal suffixes sees an
    unremarkable f-string there and returns a layer set with the newest layer
    missing from it - the failure being guarded against, one level down.
    """
    constants: dict[str, str] = {}
    for node in tree.body:
        value = getattr(node, "value", None)
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            for name in _assigned_names(node):
                constants[name] = value.value
    return constants


def _layer_slots(source: str, origin: str) -> tuple[dict[str, list[str]], list[str]]:
    """Layer names this source interpolates onto a per-module package path.

    Two shapes count, and both appear in the backend today:

    * ``f"app.modules.{name}.<layer>"`` - the whole path in one f-string.
    * ``f"{package_path}.<layer>"`` where ``package_path`` was itself assigned
      ``f"app.modules.{...}"`` somewhere in the same file, which is how
      ``module_loader`` builds every one of its imports.

    In either shape the trailing segment may be a literal or a substitution. A
    substitution resolves against the module-level string constants; anything
    else comes back in the second return value as an unresolved slot, because a
    layer this cannot read is a layer no gate downstream can demand.

    Args:
        source: Python source text.
        origin: Repo-relative path, used only to describe where a hit was seen.

    Returns:
        Layer name to the sites naming it, and the sites naming a layer this
        could not resolve.
    """
    tree = ast.parse(source)
    constants = _module_level_string_constants(tree)

    package_variables = {
        name
        for node in ast.walk(tree)
        for name in _assigned_names(node)
        if isinstance(getattr(node, "value", None), ast.JoinedStr)
        and (_fstring_template(node.value) or ("", []))[0] == _MODULES_PREFIX + "{}"
    }

    layers: dict[str, list[str]] = {}
    unresolved: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        flattened = _fstring_template(node)
        if flattened is None:
            continue
        template, expressions = flattened

        if template.startswith(_MODULES_PREFIX + "{}."):
            tail = template[len(_MODULES_PREFIX + "{}.") :]
        elif (
            template.startswith("{}.")
            and expressions
            and isinstance(expressions[0], ast.Name)
            and expressions[0].id in package_variables
        ):
            tail = template[len("{}.") :]
        else:
            # Includes ``f"app.modules.{name}"`` with no trailing segment, which
            # names the package itself and no layer, and every f-string built
            # from a bare parameter - ``import_module(module_path)`` carries no
            # f-string at all and is invisible here, which is correct.
            continue

        site = f"{origin}:{node.lineno}"
        if tail == "{}":
            slot = expressions[1] if len(expressions) > 1 else None
            if isinstance(slot, ast.Constant) and isinstance(slot.value, str):
                layers.setdefault(slot.value, []).append(site)
            elif isinstance(slot, ast.Name) and slot.id in constants:
                layers.setdefault(constants[slot.id], []).append(site)
            else:
                unresolved.append(f'{site}: f"{template}"')
        elif tail.isidentifier():
            layers.setdefault(tail, []).append(site)

    return layers, unresolved


@lru_cache(maxsize=1)
def _dynamically_imported_layers() -> tuple[dict[str, list[str]], tuple[str, ...], int]:
    """Scan ``backend/app`` for layer names reached by name rather than by import.

    Returns:
        Layer name to the sites naming it, the sites naming a layer that could
        not be resolved, and how many source files were parsed.
    """
    layers: dict[str, list[str]] = {}
    unresolved: list[str] = []
    scanned = 0
    for path in sorted(_APP.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if _MODULES_PREFIX not in text:
            continue
        scanned += 1
        found, unreadable = _layer_slots(text, path.relative_to(_BACKEND).as_posix())
        for name, sites in found.items():
            layers.setdefault(name, []).extend(sites)
        unresolved.extend(unreadable)
    return layers, tuple(unresolved), scanned


def _layer_file_count(layer: str) -> int:
    """Modules carrying ``<layer>.py`` or a ``<layer>/`` package."""
    files = {path.parent.name for path in _MODULES.glob(f"*/{layer}.py")}
    files |= {path.parent.parent.name for path in _MODULES.glob(f"*/{layer}/__init__.py")}
    return len(files)


def test_the_desktop_spec_declares_every_layer_the_backend_imports_by_name() -> None:
    """The EXISTS direction: a layer on disk that nothing declares is the bug.

    Read from ``backend/app`` and not from the spec. The historical control
    further up reads ``_MODULE_LAYERS`` out of the spec on purpose, because it
    reproduces a past defect; doing that here would make the expectation a copy
    of the answer and the assertion unfalsifiable.
    """
    layers, unresolved, scanned = _dynamically_imported_layers()
    packages = _module_packages()

    assert scanned >= _MIN_SCANNED_SOURCES, (
        f"the layer scanner parsed only {scanned} source files under {_APP}, under the floor of "
        f"{_MIN_SCANNED_SOURCES}. It is no longer reading the backend, so the empty result below "
        "means nothing."
    )
    assert len(layers) >= _MIN_DYNAMIC_LAYERS, (
        f"the layer scanner found only {sorted(layers)} - {len(layers)} names, under the floor of "
        f"{_MIN_DYNAMIC_LAYERS}. module_loader alone declares seven, so a set this small means the "
        "scanner stopped matching the shape the backend actually writes."
    )
    assert len(packages) >= _MIN_MODULE_PACKAGES, (
        f"found {len(packages)} module packages under {_MODULES}, under the floor of "
        f"{_MIN_MODULE_PACKAGES}. The module tree moved and this guard is looking at the wrong place."
    )
    assert not unresolved, (
        "the backend builds a per-module dotted path whose layer name this guard cannot read, so no "
        "gate can tell whether the spec declares it:\n  " + "\n  ".join(unresolved) + "\n"
        "Bind the layer name to a module-level string constant, the way "
        "app/core/data_repairs.py binds REPAIRS_MODULE_NAME, so it stays readable."
    )

    declared = set(_module_layers())
    backed = {layer: _layer_file_count(layer) for layer in layers}
    missing = sorted(layer for layer, count in backed.items() if count and layer not in declared)

    assert not missing, (
        f"the backend imports {missing} by name off a module package path, and modules on disk carry "
        f"the files ({ {layer: backed[layer] for layer in missing} }), but desktop/pyinstaller.spec "
        f"does not declare them in _MODULE_LAYERS.\nNamed at: "
        + "; ".join(f"{layer} -> {layers[layer][0]}" for layer in missing)
        + "\nThey may still reach the frozen sidecar through the backend/app tree in datas, which is "
        "how they reached it before anyone noticed - but that entry describes itself as data, and a "
        "layer that resolves only through it disappears the day it is narrowed. Add the name to "
        "_MODULE_LAYERS; the spec asks the disk before emitting anything, so a layer no module "
        "carries costs nothing."
    )

    unbacked = sorted(layer for layer, count in backed.items() if not count)
    print(f"layers imported by name: {sorted(layers)} across {scanned} sources, {len(packages)} packages")
    print(f"  backed on disk: { {layer: count for layer, count in sorted(backed.items()) if count} }")
    print(f"  named but no module carries the file (nothing to declare): {unbacked}")


#: Fixture for the control below. Holds one layer named literally, one behind a
#: module-level constant, one reached through a variable holding the package
#: path, one path that names the package and no layer, and one import with no
#: f-string at all. Read as a string rather than written to a file so the
#: control cannot be affected by anything on disk.
_CONTROL_SOURCE = """
import importlib

CONTROL_LAYER_NAME = "layer_behind_a_constant"


def load(name: str) -> None:
    package_path = f"app.modules.{name}"
    importlib.import_module(package_path)
    importlib.import_module(f"app.modules.{name}.layer_written_out")
    importlib.import_module(f"app.modules.{name}.{CONTROL_LAYER_NAME}")
    importlib.import_module(f"{package_path}.layer_through_a_variable")
"""

#: Fixture for the second control: a layer name the scanner cannot resolve.
_CONTROL_SOURCE_UNREADABLE = """
import importlib


def pick() -> str:
    return "computed"


def load(name: str) -> None:
    importlib.import_module(f"app.modules.{name}.{pick()}")
"""


def test_the_layer_scanner_resolves_a_literal_a_constant_and_a_variable_slot() -> None:
    """Positive control. The constant branch is the only route to ``repairs``.

    If it stops resolving, ``repairs`` drops out of the expectation set and the
    gate above passes while the spec is wrong - the same vacuity, moved one
    level down. This is the assertion that stops that, so it does not get to be
    decoration.
    """
    layers, unresolved = _layer_slots(_CONTROL_SOURCE, "control")
    assert set(layers) == {
        "layer_written_out",
        "layer_behind_a_constant",
        "layer_through_a_variable",
    }, f"the scanner read {sorted(layers)} out of the control fixture"
    assert not unresolved, f"the control fixture holds no unreadable slot, but the scanner reported {unresolved}"


def test_the_layer_scanner_reports_a_slot_it_cannot_resolve() -> None:
    """Negative control: an unreadable layer must be loud, not skipped.

    A scanner that quietly drops what it cannot parse would let a future
    discovery pass hide a layer from the gate above, which is the failure this
    whole file exists to make impossible.
    """
    layers, unresolved = _layer_slots(_CONTROL_SOURCE_UNREADABLE, "control")
    assert not layers, f"the scanner invented a layer name out of an unreadable slot: {sorted(layers)}"
    assert len(unresolved) == 1 and "app.modules.{}.{}" in unresolved[0], (
        f"the scanner did not report the unreadable slot; it returned {unresolved}"
    )


def _app_tree_ships_as_data() -> bool:
    """True when the spec ships the whole ``backend/app`` tree at bundle path ``app``.

    That is the route by which a layer with no frozen module still imports: the
    tree lands at ``sys._MEIPASS/app/...``, which is exactly the ``__path__``
    PyInstaller gives the frozen ``app.modules.<name>`` package, and its path
    finder falls back to python's FileFinder for names it has no PYZ entry for.
    """
    datas = _run_spec()[0].get("datas") or []
    wanted = (_BACKEND / "app").resolve()
    for entry in datas:
        if not isinstance(entry, tuple) or len(entry) != 2:
            continue
        source, target = entry
        if Path(str(source)).resolve() == wanted and str(target).replace("\\", "/").strip("/") == "app":
            return True
    return False


def test_every_layer_the_loader_imports_by_name_can_be_imported_from_the_bundle() -> None:
    """A layer that reaches the sidecar by neither route fails silently at runtime.

    ``module_loader`` wraps these imports in ``contextlib.suppress``, so a
    module whose ``events.py`` is missing loads, logs nothing and never
    registers a subscriber. ``data_repairs`` swallows the same exception for
    the same reason and reports a boot with nothing attempted. On the published
    15.4.0 sidecar 27 of these files have no frozen module and arrive only
    through the ``datas`` tree, so narrowing that entry - an obvious way to slim
    a bundle that carries 2333 source files next to 2176 frozen modules - would
    silence 27 modules and no gate we own would notice.

    Measured on PyInstaller 6.20.0 with a three-way onefile experiment rather
    than reasoned about: with the tree in ``datas`` and the layer undeclared the
    import succeeds out of ``sys._MEIPASS``; with the tree removed and the layer
    still undeclared it raises ModuleNotFoundError while ``pkgutil.iter_modules``
    goes on listing every package, which is the silent shape; with the layer
    declared the tree is not needed at all.
    """
    layers = set(_dynamically_imported_layers()[0])
    declared = set(_app_hidden_imports())
    ships_tree = _app_tree_ships_as_data()

    unreachable = []
    covered = 0
    for layer in sorted(layers):
        for path in sorted(_MODULES.glob(f"*/{layer}.py")):
            dotted = f"app.modules.{path.parent.name}.{layer}"
            covered += 1
            if dotted not in declared and not ships_tree:
                unreachable.append(dotted)

    assert covered, (
        f"found no {sorted(layers)} file under {_MODULES}, so this guard examined nothing. Either the "
        "layers were renamed or the module tree moved."
    )
    assert not unreachable, (
        f"{len(unreachable)} layer(s) that module_loader imports by name reach the frozen sidecar by "
        "neither route this guard can check - they are not named as hidden imports, and the "
        f"backend/app tree is no longer shipped whole in datas:\n  " + "\n  ".join(unreachable) + "\n"
        "Some of these may still arrive because another module imports them with a plain import "
        "statement, which nothing here can see without running PyInstaller. Every one that does not "
        "loads under contextlib.suppress(ModuleNotFoundError), so its module starts, logs nothing and "
        "registers no subscribers. Restore the datas entry (backend/app -> 'app'), or name these "
        "layers in the spec's _MODULE_LAYERS so they are frozen."
    )
    print(f"loader-dynamic layers {sorted(layers)}: {covered} files, app tree in datas: {ships_tree}")
