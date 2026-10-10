# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Read what a pack manifest declares from its source, parent pack included.

Several gates read ``packs/<slug>/src/*/manifest.py`` as text instead of
importing it. They do it on purpose: a text reading is a second, independent
resolution of the same declaration, and it is the one the object reading is
held against (``test_both_readers_see_the_same_declarations``). The price is
that a text reader describes one way of writing a field, and a field written
any other way reads as "this pack declares nothing".

A derived pack is that other way. ``turkey-tr-mep`` builds its manifest from
the ``turkey-tr`` manifest when it is imported and states only the fields that
are its own, so the rule sets it runs appear nowhere in its source. The reader
here follows the pack to its parent instead of reporting silence:

* a derived manifest names its parent in a module-level string literal,
  ``DERIVED_FROM = "<slug>"``, which is read by AST and never by import;
* a field the derived source writes as a literal is the derived pack's own and
  wins;
* a field it does not write is read from the parent's source.

The link is one level deep. A parent that is itself derived, or a parent that
is not in the tree, raises: either would let a pack point at something this
reader cannot check and be reported as declaring nothing.

Nothing here decides whether the declared parent is the true one. The callers
do, by comparing the result with the imported manifest, and
``test_a_derived_pack_names_its_parent_in_both_places`` compares the literal
with the ``derived_from`` the manifest object carries.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

#: Name of the module-level literal a derived manifest states its parent in.
PARENT_LITERAL = "DERIVED_FROM"

#: Layout of a pack manifest under the pack tree.
MANIFEST_GLOB = "*/src/*/manifest.py"


class UnreadableParentError(AssertionError):
    """A manifest names a parent this reader cannot follow."""


def manifest_sources(packs_dir: Path) -> dict[str, Path]:
    """Pack directory name -> its ``manifest.py``, for every pack in the tree."""
    return {path.parts[-4]: path for path in sorted(packs_dir.glob(MANIFEST_GLOB))}


def declared_parent(manifest_path: Path) -> str | None:
    """The slug a manifest says it is derived from, read without executing it.

    Args:
        manifest_path: The pack's ``manifest.py``.

    Returns:
        The parent slug, or ``None`` for a manifest that states none.

    Raises:
        UnreadableParentError: If ``DERIVED_FROM`` is assigned something other
            than a non-empty string literal. A parent this reader cannot see is
            a pack every source gate would silently exempt.
    """
    tree = ast.parse(manifest_path.read_text(encoding="utf-8"), str(manifest_path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not any(isinstance(target, ast.Name) and target.id == PARENT_LITERAL for target in targets):
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value.strip():
            return value.value
        raise UnreadableParentError(
            f"{manifest_path} assigns {PARENT_LITERAL} as {ast.dump(value)}. It has to be a plain "
            f"string literal naming the parent pack's slug, because it is read without importing."
        )
    return None


def _own_list(manifest_path: Path, field: str) -> list[str] | None:
    """The list literal ``field`` is assigned in this source, or ``None`` if it is not written."""
    source = manifest_path.read_text(encoding="utf-8")
    match = re.search(rf"\b{re.escape(field)}\s*=\s*(\[[^\]]*\])", source, re.S)
    return list(ast.literal_eval(match.group(1))) if match else None


def declared_lists(packs_dir: Path, field: str) -> dict[str, list[str]]:
    """Pack directory name -> the list its manifest declares for ``field``.

    Args:
        packs_dir: The pack tree.
        field: A manifest keyword holding a list of strings, for example
            ``validation_rule_sets``.

    Returns:
        One entry per pack. A pack that neither writes the field nor names a
        parent maps to an empty list, as it always did.

    Raises:
        UnreadableParentError: If a pack names a parent that is absent from the
            tree or is itself derived.
    """
    sources = manifest_sources(packs_dir)
    out: dict[str, list[str]] = {}
    for slug, path in sources.items():
        own = _own_list(path, field)
        if own is not None:
            out[slug] = own
            continue
        parent = declared_parent(path)
        if parent is None:
            out[slug] = []
            continue
        if parent not in sources:
            raise UnreadableParentError(
                f"packs/{slug} declares {PARENT_LITERAL} = {parent!r}, and there is no packs/{parent} "
                f"with a manifest in the tree to read {field} from."
            )
        if declared_parent(sources[parent]) is not None:
            raise UnreadableParentError(
                f"packs/{slug} is derived from packs/{parent}, which is itself derived. The reader "
                f"follows one level, so a chain would be read as declaring nothing. Derive from the "
                f"pack that states the fields."
            )
        out[slug] = _own_list(sources[parent], field) or []
    return out
