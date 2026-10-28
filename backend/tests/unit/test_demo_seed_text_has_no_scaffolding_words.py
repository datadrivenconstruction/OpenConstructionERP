# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠No seeded row tells the reader it was seeded.

A demo estate is meant to read like a project someone is running. A row whose
title is "Demo Opportunity 0041" or whose note is "Seeded activity body" says
the opposite, and it says it on the screens we put in front of evaluators.

Why this is a source scan rather than a database assertion. The companion PG
test (``tests/pg/test_demo_seed_text_is_product_grade.py``) executes twelve
module seeders and reads the rows back, which is the stronger check, but the
seed writers are far more numerous than that: this file discovers every
``app/modules/*/seed.py``, ``app/core/demo_*.py`` and
``app/scripts/seed_demo_*.py``, and most of them are not executed by any test
at all. Scanning them is the only coverage they have.

WHAT THIS CHECK CANNOT SEE. Worth stating plainly, because a scanner's silence
is easy to mistake for a clean result:

* It reads literal text only. A name assembled at runtime - ``" ".join(parts)``,
  ``template.format(word)`` or ``prefix + suffix`` where either side is a
  variable - is invisible here. The f-string case IS covered (see
  ``_literal_text``) and is proven by
  :func:`test_the_scanner_can_see_inside_an_f_string`, because that was the
  shape the original leak took.
* Rule one only reaches values tagged by a field name, as ``title=...`` or
  ``{"title": ...}``. Data carried positionally, such as a tuple of
  ``(code, label, unit)`` unpacked later, is not tagged and is not seen. Rule
  two exists precisely because that blind spot is real: ``catalog/seed.py``
  held thirty-three user-visible codes in positional tuples.
* Rule one reads Python only. Rule two also reads the JSON seed payloads,
  because scanning Python alone was not enough: fifty-three of the catalogue
  codes lived in ``app/scripts/starter_seed_data.json``, from where
  ``seed_starter.py`` copies them verbatim into ``CostItem.components`` and the
  BOQ resource editor prints them in its Code field. A source scan that stops at
  the file extension the defect was first found in will keep reporting clean.
* It says nothing about whether a value is *correct*, only whether it admits to
  being scaffolding.

DELIBERATELY NOT FLAGGED. Six classes carry these words on purpose. They are
listed so the next person does not read them as misses and start "fixing" them:

1. the demo user's login credential, which has to stay typeable and published;
2. ``/api/demo/*`` route paths and storage prefixes, which are API surface;
3. log, print and exception strings, which are read by operators, not users -
   excluded structurally by :func:`_logging_argument_nodes`;
4. legacy ``DEMO-`` prefixes kept so a re-seed can recognise rows an older
   seeder wrote, whether to delete them or, in ``catalog/seed.py``, to rename
   them forward. Excluded by the shape of :data:`_DEMO_CODE`, which requires a
   character after the separator and so never matches a bare prefix constant;
5. the input to a ``uuid5`` derivation, where the text is an id ingredient and
   never displayed;
6. ``Document.file_path``, whose row marks itself demo through
   ``metadata_={"is_demo": True}`` rather than through the displayed string.
7. the names inside ``__all__``, which are identifiers rather than values.
   Excluded by :func:`_export_list_nodes`. This class arrived when the public
   demo's read-only guard was added: it exports ``DEMO_READ_ONLY_ERROR``, whose
   value is the lowercase ``demo_read_only``, and rule two convicted the export
   name while the value it names was never a hit. Note what the shape of that
   miss says about the globs below - ``app/core/demo_*.py`` selects on the
   filename, so a module that is about the demo rather than one that seeds it
   joins this scan by being named well.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]

# Words that admit the row came from a seeder rather than from a project.
#
# "sample" is not one of them on its own, and treating it as one made this test
# reject the product's own vocabulary. In construction English a sample is a
# thing you take and test: a water sample sent for potability, a concrete cube,
# a sample room built for the client to approve. The seed tree writes it in
# that sense sixty-odd times, and the only reason this rule stayed green for so
# long is that most of those are ``rng.sample`` calls the AST walk never reads.
# The one that finally fired, "sample taken for potability", admits nothing.
#
# So the word is matched by sense rather than by spelling. It counts as
# scaffolding only where it modifies a noun naming an artefact a seeder
# produces, or where the sentence says outright that the row is an example.
# "sample data" and "sample record" still fail. "sample taken", "sample room",
# "sample with the laboratory" do not, because in each of those the word is the
# head noun of a real thing on a real site.
#
# The same collision exists for "demo", which is how this trade abbreviates
# demolition - ``bid_management/seed.py`` already carries a "DEMO" bid for a
# demolition phase. Nothing trips on it today because that value is a bare
# code rather than prose, so it is left alone rather than pre-emptively
# loosened; if a demolition description ever fails here, this is the reason.
_SCAFFOLDING = re.compile(
    r"""
      \b (?: demo | seeded | placeholder | dummy ) \b
    | \b samples? \b (?= \s+ (?: data | dataset | record s? | row s? | entry | entries
                              | value s? | text | string s? | content | payload
                              | fixture s? | placeholder s? | seed | only ) \b )
    | \b (?: this \s+ is \s+ (?: a | an ) \s+ sample | for \s+ sample \s+ purposes ) \b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Rule two. A code opening with DEMO- is user-visible wherever it sits: the
# estimator reads it off the card. Position-independent on purpose, because the
# field-name rule below cannot see values held in positional tuples.
#
# Case-sensitive, and that is the whole point of the rule. Upper case is what
# separates a code from an identifier: ``DEMO-LAB-001`` is printed on a
# catalogue card, while ``demo_id``, ``demo-seed`` and ``demo_asset_seed`` are
# variable names, dict keys and filenames that no user ever sees. Matching case
# insensitively flagged sixty of those and would have made the rule useless.
#
# The trailing character class is what separates a code from a prefix. A code
# continues into its own body, ``DEMO-LAB-001``. A legacy match pattern does
# not: ``f"DEMO-{project_key}-"`` contributes the literal text ``DEMO--``, and
# those are the read-only prefixes of class 4, which exist so a re-seed can
# find and delete rows an older seeder wrote. Excluding them by shape rather
# than by an allowlist entry means there is no list here to rot.
_DEMO_CODE = re.compile(r"^DEMO[-_][A-Z0-9]")

# Columns a user reads on a screen or in an export.
_USER_FIELDS = frozenset(
    {
        "address",
        "body",
        "caption",
        "code",
        "comment",
        "comments",
        "company_name",
        "content",
        "description",
        "display_name",
        "full_name",
        "heading",
        "justification",
        "label",
        "location_address",
        "message",
        "name",
        "note",
        "notes",
        "reason",
        "ref",
        "reference",
        "remarks",
        "scope_description",
        "subject",
        "summary",
        "text",
        "title",
    },
)

# Calls whose string arguments are read by operators rather than by users.
_LOG_CALLERS = frozenset({"log", "logger", "logging", "print", "warnings"})

# There is deliberately no allowlist of permitted literals. All six classes
# above are excluded by structure instead: logger arguments by
# ``_logging_argument_nodes``, credentials, route paths, uuid5 inputs and file
# paths by not being tagged with a user-facing field name, and legacy prefixes
# by the code shape in ``_DEMO_CODE``. A named list of blessed strings is the
# part of a checker that rots first, because it keeps passing after the string
# it described has moved on. There are now no file-level exceptions either: the
# catalogue seeder was the last one, and it was renamed rather than blessed.


def _sources() -> list[Path]:
    """Every demo seed writer, discovered rather than listed.

    A hand-kept list silently stops covering the module added after it was
    written, which is the failure this whole file exists to prevent.
    """
    found: list[Path] = []
    found += sorted((_BACKEND / "app" / "modules").glob("*/seed.py"))
    found += sorted((_BACKEND / "app" / "core").glob("demo_*.py"))
    found += sorted((_BACKEND / "app" / "scripts").glob("seed_demo_*.py"))
    assert found, f"no seed writers found under {_BACKEND} - the globs have gone stale"
    return found


def _json_sources() -> list[Path]:
    """Seed payloads that ship as data rather than as code."""
    found = sorted((_BACKEND / "app" / "scripts").glob("*seed*.json"))
    assert found, f"no seed payloads found under {_BACKEND} - the glob has gone stale"
    return found


def _json_strings(node: object, trail: str = "") -> list[tuple[str, str]]:
    """Every string in a decoded payload, paired with the path that reaches it."""
    if isinstance(node, str):
        return [(trail, node)]
    if isinstance(node, dict):
        return [pair for key, value in node.items() for pair in _json_strings(value, f"{trail}.{key}")]
    if isinstance(node, list):
        return [pair for i, value in enumerate(node) for pair in _json_strings(value, f"{trail}[{i}]")]
    return []


def _literal_text(node: ast.AST) -> list[str]:
    """Literal text a node contributes, descending into f-strings.

    The f-string branch is the load-bearing one. Reading these files with
    ``tokenize`` instead would work on Python 3.11, where an f-string is a
    single STRING token, and go blind on 3.12, where it becomes
    FSTRING_START/MIDDLE/END. CI runs 3.12. Walking the AST is version-proof,
    and :func:`test_the_scanner_can_see_inside_an_f_string` proves it stays so.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return ["".join(p.value for p in node.values if isinstance(p, ast.Constant) and isinstance(p.value, str))]
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return [text for element in node.elts for text in _literal_text(element)]
    if isinstance(node, ast.IfExp):
        # ``"a" if flag else "b"`` puts two candidate values in one slot.
        return _literal_text(node.body) + _literal_text(node.orelse)
    return []


def _logging_argument_nodes(tree: ast.AST) -> set[int]:
    """Ids of string nodes passed to a logger, so class 3 drops out."""
    inside_log: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        root = None
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            root = func.value.id
        elif isinstance(func, ast.Name):
            root = func.id
        if root not in _LOG_CALLERS:
            continue
        for descendant in ast.walk(node):
            if isinstance(descendant, ast.Constant) and isinstance(descendant.value, str):
                inside_log.add(id(descendant))
    return inside_log


def _export_list_nodes(tree: ast.AST) -> set[int]:
    """Ids of the string nodes inside ``__all__``, so class 7 drops out.

    Every entry in ``__all__`` is the name of something the module exports, not
    a value anybody reads. ``"DEMO_READ_ONLY_ERROR"`` there is the identifier
    of a constant whose actual value is ``"demo_read_only"``, and that value is
    scanned where it is assigned, a few lines further down the same file. So
    this exclusion costs no coverage at all: a demo-prefixed code cannot hide
    in an export list, because the only thing an export list can hold is the
    name of a definition that is itself in scope here.

    Structural rather than an allowlist, for the reason given above the source
    globs. A blessed-literals list would have to name this string, and would
    keep passing after the constant behind it was renamed or deleted.
    """
    inside_exports: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            continue
        for descendant in ast.walk(node.value):
            if isinstance(descendant, ast.Constant) and isinstance(descendant.value, str):
                inside_exports.add(id(descendant))
    return inside_exports


def _user_facing_hits(tree: ast.AST) -> list[tuple[int, str, str]]:
    """Rule one: scaffolding words in a value tagged with a user-facing name."""
    skip = _logging_argument_nodes(tree)
    hits: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg in _USER_FIELDS and id(keyword.value) not in skip:
                    line = getattr(keyword.value, "lineno", node.lineno)
                    hits += [
                        (line, keyword.arg, text) for text in _literal_text(keyword.value) if _SCAFFOLDING.search(text)
                    ]
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value in _USER_FIELDS:
                    hits += [
                        (getattr(value, "lineno", 0), str(key.value), text)
                        for text in _literal_text(value)
                        if _SCAFFOLDING.search(text)
                    ]
    return hits


def _demo_code_hits(tree: ast.AST) -> list[tuple[int, str]]:
    """Rule two: a DEMO- code literal anywhere, tagged by a field name or not."""
    skip = _export_list_nodes(tree)
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in skip and _DEMO_CODE.match(node.value):
                hits.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            for text in _literal_text(node):
                if _DEMO_CODE.match(text):
                    hits.append((node.lineno, text))
    return hits


def test_no_seeded_value_a_user_reads_admits_to_being_seeded() -> None:
    """Rule one over every discovered seed writer."""
    leaks: list[str] = []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(_BACKEND).as_posix()
        leaks += [f"{rel}:{line} {field}={text!r}" for line, field, text in _user_facing_hits(tree)]

    assert not leaks, "seeded values that tell the reader they were seeded:\n" + "\n".join(leaks)


def test_no_user_visible_code_opens_with_a_demo_prefix() -> None:
    """Rule two, which reaches the positional data rule one cannot tag."""
    leaks: list[str] = []
    for path in _sources():
        rel = path.relative_to(_BACKEND).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        leaks += [f"{rel}:{line} {text!r}" for line, text in _demo_code_hits(tree)]

    assert not leaks, "codes that open with DEMO- and are shown to users:\n" + "\n".join(leaks)


def test_no_seeded_json_payload_carries_a_demo_prefixed_code() -> None:
    """Rule two again, over the payloads that ship as data.

    ``seed_starter.py`` copies these dicts straight into ``CostItem.components``
    and the BOQ resource editor renders their ``code`` in its Code field, so a
    code here is exactly as visible as one written in Python.
    """
    leaks: list[str] = []
    for path in _json_sources():
        rel = path.relative_to(_BACKEND).as_posix()
        payload = json.loads(path.read_text(encoding="utf-8"))
        leaks += [f"{rel}{trail} {text!r}" for trail, text in _json_strings(payload) if _DEMO_CODE.match(text)]

    assert not leaks, "codes that open with DEMO- and are shown to users:\n" + "\n".join(leaks)


def test_an_export_list_is_skipped_without_blinding_the_rule() -> None:
    """Prove class 7 removes the export list and nothing else.

    Both halves matter and the second is the one worth the test. Skipping
    ``__all__`` is only safe if the scanner still reads the rest of a module
    that has one, so this asserts the negative and the positive together on a
    single tree: the exported *name* is not a hit, and a real demo-prefixed
    code sitting a few lines below it in the same file still is.

    Without the positive half this test would keep passing if the skip set ever
    widened to the whole module, which is the failure mode of every structural
    exclusion: it is invisible, because a checker that has stopped looking
    reports exactly what a clean file reports.
    """
    tree = ast.parse('__all__ = ["DEMO_READ_ONLY_ERROR"]\nCODE = "DEMO-0041"\nVALUE = "demo_read_only"\n')
    hits = _demo_code_hits(tree)
    found = {text for _, text in hits}

    assert "DEMO_READ_ONLY_ERROR" not in found, "the export list is still being read as user-visible text"
    assert "DEMO-0041" in found, (
        "the export-list skip has swallowed the rest of the module - rule two is "
        "now blind to exactly the codes it exists to catch"
    )


def test_the_scanner_can_see_inside_an_f_string() -> None:
    """Prove the extractor descends into f-strings on whatever Python runs.

    Not decoration. The original leak was ``f"Demo Account {i + 1:03d}"``, and
    an extractor that stopped seeing f-string text would leave every test above
    green while blind to the exact shape it was written for.
    """
    tree = ast.parse('Model(title=f"Demo Account {index:03d}", name="plain")\n')
    hits = _user_facing_hits(tree)
    fields = {field for _, field, _ in hits}

    assert "title" in fields, (
        "the scanner did not see inside an f-string - every check in this file "
        "is blind to the shape the original leak took"
    )
