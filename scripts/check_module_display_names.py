#!/usr/bin/env python3
"""Module-name guard: every module name a user reads must be reachable by a translator.

`ModuleManifest` carries `display_name` and an optional `display_name_i18n`
dict. The module registry page used to render `display_name` straight, so all
185 module names showed in English in every one of the 40 languages, and had
since the page was written.

What made it survive is worth stating, because it decides what this guard has
to check. The field existed in the model and the type declared it on the page,
so from either end it looked implemented. No existing gate could see it:

  * the orphan guard asks whether a `t()` key has a locale file behind it, and
    there was no `t()` call to find
  * the leak and mixed-script guards ask about the value of a key that exists,
    and no key existed
  * `tsc` and the build are satisfied by a string rendered as a string

There is no missing key to detect when nobody ever asked for one. So this guard
does not look for a gap in the locale files. It starts from the modules, which
are the thing that actually exists, and asks of each one whether the name it
shows can be translated at all.

Four ways that fails, all blocking:

  1. A module whose name has no `modules.catalog.<name>` key. Nothing can
     translate it, and it will render English forever without any gate
     noticing. This is the original defect.
  2. A `modules.catalog.*` key with no module behind it. Left alone these
     accumulate as work for 39 translators on names nobody will ever see.
  3. A key whose English value disagrees with the manifest `display_name`.
     Two spellings of one module's name is what #134 found: a module the app
     calls Project Files whose manifest said Document Management. Translators
     work from the locale value and backend logs print the manifest one, so a
     drift here means the product is quietly using two names for one thing.
  4. A manifest this guard cannot read the two fields out of. That is a
     failure and not a skip, because a manifest the guard cannot read still
     ships: `module_loader` imports the file and checks `isinstance`, so it
     never looks at how the call is written.

That fourth one is why the manifests are parsed rather than matched. The reader
used to be two line-anchored regexes and it dropped every manifest they missed,
on the stated grounds that the loader would refuse such a manifest anyway. The
loader does no such thing, and the layout that defeats the anchors is one our
own formatter produces: a `ModuleManifest(...)` call whose last argument has no
trailing comma is collapsed onto one line if it fits in 120 characters, and
then `display_name` sits mid-line where a start-of-line anchor cannot match. A
module that fell out of the reader was never asked for a
`modules.catalog.<name>` key, rendered English in all 40 languages, and took
nothing red with it, because the count in the verdict was taken after the drop
and so came out looking merely smaller.

Run from the repo root:

    python scripts/check_module_display_names.py
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys
from typing import NamedTuple

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULES = ROOT / "backend" / "app" / "modules"
EN_LOCALE = ROOT / "frontend" / "src" / "app" / "locales" / "en.ts"

KEY_PREFIX = "modules.catalog."

MANIFEST_GLOB = "*/manifest.py"
MANIFEST_CLASS = "ModuleManifest"

# "key": "value", where either may contain escaped quotes
PAIR_RE = re.compile(r'"((?:[^"\\]|\\.)+)"\s*:\s*"((?:[^"\\]|\\.)*)"')


class ManifestRead(NamedTuple):
    """One `manifest.py` on disk and the two fields this guard needs from it.

    Every manifest found gets an entry, including the ones nothing could be
    read out of, which carry `None`. Keeping them in the list is the point:
    the population the verdict reports is then the population on disk, and a
    manifest the reader cannot handle has to be answered for instead of
    quietly shrinking the denominator.
    """

    path: pathlib.Path
    name: str | None
    display_name: str | None


def locale_key(module_name: str) -> str:
    """Mirror of `moduleDisplayNameKey` in frontend/src/features/modules/moduleDisplayName.ts.

    Kept deliberately trivial and duplicated rather than generated, because the
    two sides must agree and a one-line rule is easier to check by eye than a
    build step. If you change one, change the other and its test.
    """
    return KEY_PREFIX + module_name.removeprefix("oe_")


def _string_argument(node: ast.expr | None) -> str | None:
    """The value of a plain string literal argument, or None for anything else.

    Adjacent string literals are one `Constant` by the time they reach here, so
    a wrapped description still reads. A value built at runtime - an f-string,
    a concatenation, a reference to a constant - does not, and returning None
    for it makes the manifest a named failure rather than a guess.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _manifest_call(tree: ast.Module) -> ast.Call | None:
    """The `ModuleManifest(...)` call in a parsed manifest, if there is one."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == MANIFEST_CLASS:
            return node
        if isinstance(func, ast.Name) and func.id == MANIFEST_CLASS:
            return node
    return None


def read_manifests() -> list[ManifestRead]:
    """Every manifest under `MODULES`, parsed, one entry per file on disk.

    Parsed and not matched: quoting and line layout are invisible to the
    module loader, which imports the file, so they must be invisible here too
    or the guard's population stops being the product's.
    """
    out: list[ManifestRead] = []
    for manifest in sorted(MODULES.glob(MANIFEST_GLOB)):
        try:
            tree = ast.parse(manifest.read_text(encoding="utf-8"))
        except SyntaxError:
            out.append(ManifestRead(manifest, None, None))
            continue
        call = _manifest_call(tree)
        if call is None:
            out.append(ManifestRead(manifest, None, None))
            continue
        arguments = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}
        out.append(
            ManifestRead(
                manifest,
                _string_argument(arguments.get("name")),
                _string_argument(arguments.get("display_name")),
            ),
        )
    return out


def read_english() -> dict[str, str]:
    text = EN_LOCALE.read_text(encoding="utf-8")
    return {k: v for k, v in PAIR_RE.findall(text)}


def main() -> int:
    manifests = read_manifests()
    on_disk = len(list(MODULES.glob(MANIFEST_GLOB)))
    if not manifests:
        print(f"no manifests found under {MODULES}", file=sys.stderr)
        return 1

    # The same glob the reader walked, counted again. A reader that starts
    # dropping manifests would otherwise report a smaller number rather than a
    # wrong one, and a smaller number reads as fine.
    if len(manifests) != on_disk:
        print(
            f"\nread {len(manifests)} manifests but {on_disk} exist under {MODULES}. "
            "The reader is skipping files, so every check below runs on a short population.",
            file=sys.stderr,
        )
        return 1

    unparsed = [m for m in manifests if not m.name or not m.display_name]
    if unparsed:
        print(f"\n{len(unparsed)} manifests do not spell out both name and display_name:", file=sys.stderr)
        for entry in unparsed:
            missing = ", ".join(
                field for field, value in (("name", entry.name), ("display_name", entry.display_name)) if not value
            )
            print(f"  {entry.path.relative_to(ROOT).as_posix()}  cannot read: {missing}", file=sys.stderr)
        print(
            "\nThe module loader imports the manifest and checks isinstance, so a module whose\n"
            "fields this guard cannot read still loads and still shows its name to users. Write\n"
            "both as plain string literals in the ModuleManifest call. Reporting it here rather\n"
            "than skipping the file is deliberate: a skipped manifest is never asked for a\n"
            f"{KEY_PREFIX}<name> key and renders English in every language with nothing red.",
            file=sys.stderr,
        )
        return 1

    modules = [(m.name, m.display_name, m.path) for m in manifests]

    english = read_english()
    catalog = {k: v for k, v in english.items() if k.startswith(KEY_PREFIX)}

    unreachable: list[tuple[str, str]] = []
    drifted: list[tuple[str, str, str]] = []
    expected: set[str] = set()

    for name, display, _path in modules:
        key = locale_key(name)
        expected.add(key)
        if key not in catalog:
            unreachable.append((name, display))
        elif catalog[key] != display:
            drifted.append((key, display, catalog[key]))

    orphans = sorted(set(catalog) - expected)

    failed = False

    if unreachable:
        failed = True
        print(
            f"\n{len(unreachable)} module names no translator can reach:",
            file=sys.stderr,
        )
        for name, display in unreachable[:20]:
            print(f'  {name:<28} "{display}"  needs {locale_key(name)}', file=sys.stderr)
        if len(unreachable) > 20:
            print(f"  and {len(unreachable) - 20} more", file=sys.stderr)
        print(
            "\nAdd the key to frontend/src/app/locales/en.ts with the manifest wording as its\n"
            "English value. Until then this module renders English in all 40 languages and\n"
            "no other i18n gate can see it, because there is no key for them to miss.",
            file=sys.stderr,
        )

    if drifted:
        failed = True
        print(
            f"\n{len(drifted)} module names are spelled two different ways:",
            file=sys.stderr,
        )
        for key, manifest_value, locale_value in drifted:
            print(f"  {key}", file=sys.stderr)
            print(f'    manifest: "{manifest_value}"', file=sys.stderr)
            print(f'    en.ts:    "{locale_value}"', file=sys.stderr)
        print(
            "\nTranslators work from the locale value and backend logs print the manifest one,\n"
            "so a disagreement here ships the module under two names. Pick one and set both.",
            file=sys.stderr,
        )

    if orphans:
        failed = True
        print(f"\n{len(orphans)} catalog keys have no module behind them:", file=sys.stderr)
        for key in orphans[:20]:
            print(f'  {key}  = "{catalog[key]}"', file=sys.stderr)
        if len(orphans) > 20:
            print(f"  and {len(orphans) - 20} more", file=sys.stderr)
        print(
            "\nA module was renamed or removed and its name key stayed. Delete the key from\n"
            "every locale file, or these become translation work on a name nobody can see.",
            file=sys.stderr,
        )

    if failed:
        return 1

    print(
        f"module display names: {len(modules)} of {on_disk} manifests under "
        f"{MODULES.relative_to(ROOT).as_posix()} read, {len(catalog)} catalog keys, "
        f"every name reachable as {KEY_PREFIX}<name>, no drift, no orphans"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
