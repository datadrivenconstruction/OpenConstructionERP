# DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
"""An install instruction must be worded for the install that will read it.

Most remedies in this tree are written for a pip install, which is where most
of them are read. Inside the frozen desktop sidecar they are not merely awkward
but impossible: ``sys.executable`` is the application binary, so a pip command
feeds its own tokens back into this CLI. ``app.core.self_upgrade.repair_hint``
exists to answer that at runtime, and it takes two frozen wordings because the
two failures need opposite advice:

* ``DESKTOP_REPAIR`` when the named thing IS in ``requirements-desktop.lock``.
  The bundle ships it, so a bundle that cannot load it is damaged, and the
  reader must be sent to the installer rather than told to add what is already
  there. ``DESKTOP_NO_EXTRA`` would be a lie at these sites.
* ``DESKTOP_NO_EXTRA`` when it is not in the lock. A reinstall from the same
  installer carries exactly the same fixed set, so "reinstall" sends the reader
  round a loop that changes nothing.

Getting the constant backwards produces a message that is confidently wrong, so
the census below prints, per site, whether the named distribution is in the
lock. Choosing between the two is a reading of the call site and stays with the
author; what this file gates is that the choice was made at all.

What is in scope and why: a string that instructs somebody to install a NAMED
distribution or a NAMED ``openconstructionerp`` extra. Two deliberate exclusions,
both stated rather than listed, so that a new site cannot fall outside the rule
by being absent from a hand-maintained roster:

* Advice that only names ``openconstructionerp`` itself is the app-reinstall
  class, governed by ``FROZEN_REFUSAL`` and the upgrade endpoints instead.
* ``apt``/``brew``/``npm`` instructions are followable on a frozen desktop's
  host, because they do not run through ``sys.executable``. That boundary is
  the one ``repair_hint``'s own docstring draws.
* Prose that DESCRIBES an install instead of prescribing one. "a model can be
  resident even on an install where the shared path is never used" is the noun,
  and a register entry that happens to name a package is not a remedy handed to
  anybody. A determiner in front of the word is what tells the two apart.

Measured on 2026-08-29 against the tree: 34 sites in the population, all routed.
The figure was also 34 on 2026-08-23, under a detector that additionally counted
one register entry describing an install, so a number that matches is not by
itself evidence that the corpus and the reading of it both stood still.
A count on its own would let this pass by going blind, so the population size
carries a floor, the extractor's vocabulary comes from the lock and from
pyproject rather than from a regex guess after the word "install", and the
failure prints the offending sites by name.

The census is only half the proof. It reads source and can therefore show that
every remedy goes THROUGH ``repair_hint``; it cannot show what comes out the
other side, and a site that hands over the wrong constant satisfies the census
while telling a desktop reader something confidently false. So the second half
of this file runs a sample of the real producers under both installs, prints
both strings, and asserts the two frozen wordings are not interchangeable.

That half imports the application; the census half is pure file parsing and
stays that way, so a collection that cannot import the app still gets the
corpus-wide gate.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import re
import sys
import tomllib
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
_APP = _BACKEND / "app"
_LOCK = _BACKEND / "requirements-desktop.lock"
_PYPROJECT = _BACKEND / "pyproject.toml"

#: Below this the census has stopped seeing the tree and its silence means
#: nothing. The measured figure is 34; the floor leaves room to remove a site
#: without editing this file, and none to lose the corpus.
_MIN_POPULATION = 25

_PIP_INSTALL = re.compile(
    r"(?:pip3?|python\s+-m\s+pip|uv\s+pip)\s+install\b|\buv\s+add\b|\bpoetry\s+add\b",
    re.IGNORECASE,
)

#: "install" the errand, not "installed" the diagnosis and not the "install" of
#: "a broken install". The word boundary drops the participle. The noun is
#: dropped by ``_NOUN_PHRASE`` below, at the one place that judges an errand.
_IMPERATIVE = re.compile(r"\b(?:re)?install\b", re.IGNORECASE)

#: The same word as a noun: the install somebody HAS, not the one they are being
#: sent on. A determiner to its left is what marks it, optionally across one
#: adjective, as in "a broken install" or "a desktop install". This has to read
#: the left of the word and never the right: half the real remedies in the tree
#: read "Install the [semantic] extra", and a determiner AFTER the verb is the
#: ordinary shape of an errand rather than a sign that it is not one.
_NOUN_PHRASE = re.compile(
    r"\b(?:an?|the|this|that|these|those|each|every|one|its|our|your|their|my)"
    r"(?:\s+[\w-]+)?\s+(?:re)?install$",
    re.IGNORECASE,
)

_EXTRA = re.compile(
    r"openconstructionerp\s*\[\s*([\w,-]+)\s*\]|\[(\w[\w-]*)\]\s+extra|\bthe\s+'?(\w[\w-]*)'?\s+extra\b",
    re.IGNORECASE,
)

#: Distribution names that are also ordinary words in our own prose ("click
#: Retry", "install all of them"). Matching them would report sentences that
#: name no package at all.
_HOMOGRAPHS = frozenset({"click", "all", "six", "wheel", "packaging", "requests", "rich", "distro"})

#: Import name -> distribution name, for the messages that spell the module.
_ALIASES = {
    "sentence_transformers": "sentence-transformers",
    "qdrant_client": "qdrant-client",
    "PIL": "pillow",
}


def _normalise(name: str) -> str:
    return name.lower().replace("_", "-")


def _requirement_name(spec: str) -> str:
    return _normalise(re.split(r"[=<>!~\[; ]", spec.strip(), maxsplit=1)[0])


def _desktop_lock() -> set[str]:
    """Distributions the frozen sidecar actually carries."""
    names = {
        _requirement_name(line)
        for line in _LOCK.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    names.discard("")
    assert len(names) > 50, f"requirements-desktop.lock parsed to only {len(names)} names; the parser is wrong"
    return names


def _declared() -> tuple[set[str], set[str]]:
    """Every distribution pyproject names, and the set of declared extras."""
    project = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]
    extras = project.get("optional-dependencies", {})
    dists = {_requirement_name(s) for s in project.get("dependencies", [])}
    for specs in extras.values():
        dists |= {_requirement_name(s) for s in specs}
    dists -= {"openconstructionerp", ""}
    return dists, set(extras)


def _string_pieces(node: ast.AST):
    """(lineno, text) for every string constant, f-string literal parts included."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.lineno, node.value
    elif isinstance(node, ast.JoinedStr):
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                yield node.lineno, part.value


def _called_names(node: ast.AST):
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call):
            func = inner.func
            yield func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)


def _router_names(tree: ast.AST) -> set[str]:
    """``repair_hint`` plus any local function that delegates to one, to a fixpoint.

    ``cli.py`` wraps it twice, as ``_repair_hint`` and ``_no_extra_hint``, and one
    of those sites never says "pip" at all. A detector that knew only the base
    name called two already-correct lines defects, which is how a gate earns its
    reputation for crying wolf and then gets switched off.
    """
    names = {"repair_hint"}
    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
    changed = True
    while changed:
        changed = False
        for func in functions:
            if func.name not in names and names & set(_called_names(func)):
                names.add(func.name)
                changed = True
    return names


def _routed_line_ranges(tree: ast.AST) -> list[tuple[int, int]]:
    routers = _router_names(tree)
    ranges = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name in routers:
                for arg in list(node.args) + [kw.value for kw in node.keywords]:
                    ranges.append((arg.lineno, getattr(arg, "end_lineno", arg.lineno)))
    return ranges


def _docstring_lines(tree: ast.AST) -> set[int]:
    """Lines belonging to a docstring, which a developer reads and an operator does not."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = getattr(node, "body", [])
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            const = body[0].value
            if isinstance(const.value, str):
                lines.update(range(const.lineno, getattr(const, "end_lineno", const.lineno) + 1))
    return lines


class _Vocabulary:
    """Names an install instruction may be talking about, taken from the project.

    Deliberately not "whatever token follows the word install": that extractor
    returned ``-y`` and ``failed`` as package names on real lines here, and a
    checker that cannot name the package in a string it is judging passes by
    going blind.
    """

    def __init__(self) -> None:
        dists, self.extras = _declared()
        self.lock = _desktop_lock()
        self._patterns = {
            dist: re.compile(rf"(?<![\w-]){re.escape(dist)}(?![\w-])", re.IGNORECASE)
            for dist in (dists | self.lock) - _HOMOGRAPHS
        }
        self._alias_patterns = {
            alias: re.compile(rf"(?<![\w-]){re.escape(alias)}(?![\w-])", re.IGNORECASE) for alias in _ALIASES
        }

    def names_in(self, text: str) -> tuple[set[str], set[str]]:
        found = {dist for dist, pattern in self._patterns.items() if pattern.search(text)}
        for alias, pattern in self._alias_patterns.items():
            if pattern.search(text):
                found.add(_ALIASES[alias])
        extras: set[str] = set()
        for match in _EXTRA.finditer(text):
            for group in match.groups():
                if group:
                    extras.update(part.strip().lower() for part in group.split(","))
        return found, extras & self.extras


def _is_instruction(text: str, vocab: _Vocabulary) -> bool:
    """True when the string tells the reader to install a thing it names.

    A name is allowed to sit anywhere after the word, because it genuinely
    does: ``cli.py`` says "Install a paddlepaddle build for this platform" and
    only names the ``[cv]`` extra in the next sentence. That latitude is what
    makes the reading of the word itself carry the whole decision, so the noun
    has to be excluded here or a paragraph that mentions a package a hundred
    words later is read as an errand.
    """
    if _PIP_INSTALL.search(text):
        return True
    for match in _IMPERATIVE.finditer(text):
        if _NOUN_PHRASE.search(text[: match.end()]):
            continue
        rest = text[match.end() :]
        dists, extras = vocab.names_in(rest)
        if dists or extras or "openconstructionerp" in rest.lower():
            return True
    return False


def _census(root: Path, vocab: _Vocabulary) -> list[dict]:
    """Every operator-facing install instruction under ``root`` that names a package."""
    rows: list[dict] = []
    for path in sorted(root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        # A file that never writes any of these words cannot hold an install
        # instruction, and skipping it here is most of what keeps this census
        # to the ~31s measured over the ~290k string constants under
        # backend/app; before these gates it ran for minutes. The tokens are
        # the complete set the two patterns below can match on, not a sample.
        lowered = source.lower()
        if not any(token in lowered for token in ("install", "uv add", "poetry add")):
            continue
        tree = ast.parse(source)
        ranges = _routed_line_ranges(tree)
        docstrings = _docstring_lines(tree)
        for node in ast.walk(tree):
            for lineno, raw in _string_pieces(node):
                if lineno in docstrings:
                    continue
                text = " ".join(raw.split())
                # Cheap gate first. The vocabulary is ~250 compiled patterns
                # and this walks every string in the tree, so putting the two
                # regexes ahead of it is what stops ~250 pattern searches from
                # running against every string constant in the file.
                if not _PIP_INSTALL.search(text) and not _IMPERATIVE.search(text):
                    continue
                dists, extras = vocab.names_in(text)
                if not dists and not extras:
                    continue  # names only the app itself: the reinstall class
                if not _is_instruction(text, vocab):
                    continue
                where = path.relative_to(_BACKEND).as_posix() if path.is_relative_to(_BACKEND) else path.name
                rows.append(
                    {
                        "at": f"{where}:{lineno}",
                        "text": text,
                        "routed": any(lo <= lineno <= hi for lo, hi in ranges),
                        "dists": sorted(dists),
                        "extras": sorted(extras),
                    }
                )
    seen: set[tuple[str, str]] = set()
    unique = []
    for row in rows:
        key = (row["at"], row["text"])
        if key not in seen:
            seen.add(key)
            unique.append(row)
    unique.sort(key=lambda r: r["at"])
    return unique


def _describe(rows: list[dict], lock: set[str]) -> str:
    lines = []
    for row in rows:
        ships = sorted(d for d in row["dists"] if d in lock)
        absent = sorted(d for d in row["dists"] if d not in lock)
        constant = "DESKTOP_NO_EXTRA" if absent else "DESKTOP_REPAIR"
        lines.append(f"  {row['at']}")
        lines.append(f"      {row['text'][:130]}")
        lines.append(f"      names={row['dists'] or row['extras']} in_lock={ships} absent={absent}")
        lines.append(f"      -> route it, and the constant this reads as is {constant}")
    return "\n".join(lines)


def test_every_install_instruction_that_names_a_package_is_routed_through_repair_hint() -> None:
    vocab = _Vocabulary()
    rows = _census(_APP, vocab)

    assert len(rows) >= _MIN_POPULATION, (
        f"the census found only {len(rows)} install instructions under backend/app, below the floor of "
        f"{_MIN_POPULATION}. Either the extractor stopped matching or the corpus moved; a checker that "
        "counts must not be allowed to pass by counting nothing."
    )

    unrouted = [row for row in rows if not row["routed"]]
    assert not unrouted, (
        f"{len(unrouted)} of {len(rows)} operator-facing install instructions do not pass their remedy "
        "through repair_hint, so a frozen desktop reader is handed a pip command that cannot run there:\n"
        + _describe(unrouted, vocab.lock)
        + "\n\nWrap the remedy in app.core.self_upgrade.repair_hint. Pass DESKTOP_NO_EXTRA when the named "
        "thing is outside requirements-desktop.lock and leave the default DESKTOP_REPAIR when it is inside, "
        "because telling a reader to add what the bundle already ships sends them after the wrong fault."
    )


def test_every_extra_a_hint_names_is_declared_in_pyproject() -> None:
    """A hint may not send anybody after an extra that does not exist.

    ``coord_transforms`` told operators to run ``pip install openconstructionerp[geo]``
    for a while before any such extra existed. pip answers that with a warning
    and no package, so the instruction read as followed and the capability was
    still missing - the quietest possible way for advice to be wrong.
    """
    vocab = _Vocabulary()
    rows = _census(_APP, vocab)
    undeclared = sorted({(row["at"], extra) for row in rows for extra in row["extras"] if extra not in vocab.extras})
    assert not undeclared, (
        "these hints name an extra that pyproject does not declare, so pip warns and installs nothing:\n"
        + "\n".join(f"  {at} -> [{extra}]" for at, extra in undeclared)
    )


def _census_of_source(source: str, vocab: _Vocabulary, tmp_path: Path) -> list[dict]:
    module = tmp_path / "probe.py"
    module.write_text(source, encoding="utf-8")
    return _census(tmp_path, vocab)


def test_an_unrouted_hint_naming_an_unshipped_package_is_reported(tmp_path: Path) -> None:
    """Control, the direction that must fail: a new hint arrives unrouted."""
    rows = _census_of_source(
        'def blow_up():\n    raise RuntimeError("pye57 is missing. Install it with: pip install openconstructionerp[pointcloud]")\n',
        _Vocabulary(),
        tmp_path,
    )
    assert len(rows) == 1, f"the checker did not see the planted hint at all: {rows}"
    assert not rows[0]["routed"], "the checker called an unrouted hint routed"
    assert rows[0]["dists"] == ["pye57"], f"the checker could not name the package: {rows[0]}"
    assert rows[0]["extras"] == ["pointcloud"], f"the checker could not name the extra: {rows[0]}"


def test_a_correctly_routed_hint_is_accepted(tmp_path: Path) -> None:
    """Control, the direction that must pass: the same hint, routed."""
    rows = _census_of_source(
        "def blow_up():\n"
        "    from app.core.self_upgrade import DESKTOP_NO_EXTRA, repair_hint\n"
        '    raise RuntimeError("pye57 is missing. " + repair_hint(\n'
        '        "Install it with: pip install openconstructionerp[pointcloud]", DESKTOP_NO_EXTRA))\n',
        _Vocabulary(),
        tmp_path,
    )
    assert len(rows) == 1, f"the checker lost the hint once it was routed: {rows}"
    assert rows[0]["routed"], "a hint wrapped in repair_hint was still reported as unrouted"


def test_a_hint_routed_through_a_local_wrapper_is_accepted(tmp_path: Path) -> None:
    """The wrapper case, which a name-matching detector gets wrong.

    ``cli.py`` routes through ``_no_extra_hint``, and one of those sites does not
    contain the word "pip" at all. Both were already correct and both were
    reported as defects until the detector learned to follow a local delegate.
    """
    rows = _census_of_source(
        "def _no_extra_hint(advice):\n"
        "    from app.core.self_upgrade import DESKTOP_NO_EXTRA, repair_hint\n"
        "    return repair_hint(advice, DESKTOP_NO_EXTRA)\n"
        "\n"
        "def check():\n"
        '    return _no_extra_hint("Install a paddleocr build for this platform.")\n',
        _Vocabulary(),
        tmp_path,
    )
    assert len(rows) == 1, f"the checker lost the wrapped hint: {rows}"
    assert rows[0]["routed"], "a hint routed through a local wrapper was reported as unrouted"


def test_a_diagnosis_is_not_mistaken_for_an_errand(tmp_path: Path) -> None:
    """ "a broken install" names no package to install and is not a remedy.

    Without this the checker reports the half of a message that merely reports
    absence, while the half carrying the remedy is routed a line below - a
    failure that reads exactly like a real one and is not.
    """
    rows = _census_of_source(
        'def report():\n    return "Could not load its PDF reader (pypdfium2). This usually means a broken install."\n',
        _Vocabulary(),
        tmp_path,
    )
    assert rows == [], f"a diagnosis with no remedy was counted as an instruction: {rows}"


def test_prose_about_an_install_is_not_an_errand_and_a_late_extra_still_is(tmp_path: Path) -> None:
    """Both halves of the reading, because narrowing one breaks the other.

    The first source is the shape of ``costs/manifest.py``: a register entry
    saying that the matcher loads sentence-transformers itself "even on an
    install where the shared path is never used", which mentions the semantic
    extra a couple of clauses later. Nobody is told to run anything and there
    is no pip command in it to hand a frozen reader, yet it was reported,
    because the noun matched and the name the checker wanted after it was
    allowed to be anywhere at all in the paragraph.

    The second is ``cli.py``'s refusal, which is a real errand and names its
    extra only in the NEXT sentence. It sits here so that the obvious
    narrowing, keeping the name in the same sentence as the word, cannot be
    mistaken for a fix: that rule reads this one as prose and goes quiet on an
    instruction an operator is genuinely being given.
    """
    vocab = _Vocabulary()

    prose = _census_of_source(
        "REGISTER_BASIS = (\n"
        '    "matcher.py prefers the shared embedder in app.core.vector and loads sentence-transformers "\n'
        '    "itself when that is unavailable, so a model can be resident in this module even on an "\n'
        '    "install where the shared path is never used. When the semantic extra is not installed the "\n'
        '    "matcher logs once at WARNING and answers from the lexical path instead."\n'
        ")\n",
        vocab,
        tmp_path,
    )
    assert prose == [], f"prose describing an install was read as an instruction to perform one: {prose}"

    remedy = _census_of_source(
        "def refuse():\n"
        '    return ("Install a paddlepaddle build for this platform. The [cv] extra deliberately does "\n'
        '            "not choose one, because the right build depends on CPU vs GPU and OS.")\n',
        vocab,
        tmp_path,
    )
    assert len(remedy) == 1, f"the checker lost a remedy that names its extra one sentence later: {remedy}"
    assert remedy[0]["extras"] == ["cv"], f"the checker could not name the extra: {remedy[0]}"


# ── The other half: what the reader is actually handed ───────────────────────
#
# Everything above reads source. Source can show that a remedy passes through
# ``repair_hint``; it cannot show which of the two frozen wordings comes back,
# and passing the wrong one is the failure this whole change exists to prevent -
# it satisfies every check above while telling a desktop reader either to add a
# package the bundle already ships or to reinstall for one it never carried.
#
# So the sites below are run. Twice: once with ``sys.frozen`` absent, which is
# every pip install, and once with it set, which is what the PyInstaller
# bootloader does before any application module is imported. Both strings are
# printed, because a polarity claimed in prose is not a polarity shown.


def _install_advice_from_message_for(monkeypatch: pytest.MonkeyPatch) -> str:
    """The semantic-search status line, the one the install card renders."""
    from app.core.embedding_installer import STATE_LIBRARY_MISSING, _message_for  # noqa: PLC0415

    return _message_for(STATE_LIBRARY_MISSING, "BAAI/bge-m3", enabled=True)


def _install_advice_from_require_ezdxf(monkeypatch: pytest.MonkeyPatch) -> str:
    """The DXF reader's refusal. ``HAS_EZDXF`` is decided at import, so patch it."""
    from app.modules.dwg_takeoff import dxf_processor  # noqa: PLC0415

    monkeypatch.setattr(dxf_processor, "HAS_EZDXF", False)
    try:
        dxf_processor._require_ezdxf()
    except ImportError as exc:
        return str(exc)
    raise AssertionError("_require_ezdxf() did not raise with HAS_EZDXF false")


def _install_advice_from_encode_texts(monkeypatch: pytest.MonkeyPatch) -> str:
    """The encoder refusal on the sentence-transformers path."""
    from app.core import vector  # noqa: PLC0415

    monkeypatch.setattr(vector, "get_embedder", lambda: None)
    try:
        vector.encode_texts(["anything"])
    except RuntimeError as exc:
        return str(exc)
    raise AssertionError("encode_texts() did not raise with no embedder available")


def _install_advice_from_cwicr_encoder(monkeypatch: pytest.MonkeyPatch) -> str:
    """The CWICR/BGE-M3 refusal, whose library is deliberately outside the lock."""
    from app.modules.costs.qdrant_adapter import _encoder_missing_message  # noqa: PLC0415

    return _encoder_missing_message()


#: (where, producer, expected frozen constant, what the pip reader must still be
#: told). Four sites rather than all thirty-three: the census already covers
#: breadth, and what needs demonstrating here is that both constants come back
#: correctly out of real code, which needs one site of each kind at minimum.
_RUNTIME_SITES = [
    (
        "app/core/embedding_installer.py::_message_for",
        _install_advice_from_message_for,
        "DESKTOP_REPAIR",
        "pip install openconstructionerp[semantic]",
    ),
    (
        "app/modules/dwg_takeoff/dxf_processor.py::_require_ezdxf",
        _install_advice_from_require_ezdxf,
        "DESKTOP_REPAIR",
        "pip install 'ezdxf>=0.18.0'",
    ),
    (
        "app/core/vector.py::encode_texts",
        _install_advice_from_encode_texts,
        "DESKTOP_REPAIR",
        "Install fastembed or sentence-transformers.",
    ),
    (
        "app/modules/costs/qdrant_adapter.py::_encoder_missing_message",
        _install_advice_from_cwicr_encoder,
        "DESKTOP_NO_EXTRA",
        "pip install openconstructionerp[semantic]",
    ),
]


@pytest.mark.parametrize(
    ("where", "produce", "constant", "pip_text"),
    _RUNTIME_SITES,
    ids=[site[0] for site in _RUNTIME_SITES],
)
def test_a_hint_words_itself_for_the_install_it_is_read_on(
    where: str,
    produce,
    constant: str,
    pip_text: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Both polarities, produced rather than asserted, and told apart.

    The last assertion is the one that earns its keep. "no pip command in the
    frozen text" is satisfied by BOTH constants, so a check that stops there
    passes at every site whose author picked the wrong one. Naming the constant
    that must NOT appear is what turns this into a test of the choice.
    """
    from app.core.self_upgrade import DESKTOP_NO_EXTRA, DESKTOP_REPAIR  # noqa: PLC0415

    wanted = {"DESKTOP_REPAIR": DESKTOP_REPAIR, "DESKTOP_NO_EXTRA": DESKTOP_NO_EXTRA}[constant]
    unwanted = DESKTOP_NO_EXTRA if constant == "DESKTOP_REPAIR" else DESKTOP_REPAIR

    monkeypatch.delattr(sys, "frozen", raising=False)
    ordinary = produce(monkeypatch)

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    frozen = produce(monkeypatch)

    with capsys.disabled():
        print(f"\n  {where}")
        print(f"    ordinary install -> {ordinary}")
        print(f"    frozen desktop   -> {frozen}")

    assert pip_text in ordinary, (
        f"{where}: the ordinary install lost its install line. A reader who CAN run pip must still be "
        f"told what to run.\n  expected to contain: {pip_text}\n  got: {ordinary}"
    )
    assert "pip install" not in frozen, (
        f"{where}: the frozen desktop was handed a pip command. sys.executable there is the app binary, "
        f"so following it prints this application's own CLI usage.\n  got: {frozen}"
    )
    assert wanted in frozen, f"{where}: expected the {constant} wording on a frozen build.\n  got: {frozen}"
    assert unwanted not in frozen, (
        f"{where}: the frozen build got the opposite constant. That message is confidently wrong - it "
        f"either denies shipping what the lock ships or offers a reinstall that changes nothing.\n"
        f"  got: {frozen}"
    )


def test_the_two_import_time_hints_word_themselves_for_the_build_they_load_in(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two sites resolve their hint at import time, not at read time.

    ``marketplace._VECTOR_INDEX_ENCODER`` and ``qdrant_supervisor._MISSING_CLIENT_HINT``
    are module constants, so ``repair_hint`` runs once while the module is
    executing rather than each time somebody reads the text. In production that
    is the same answer either way - the PyInstaller bootloader sets
    ``sys.frozen`` before any application module is imported and nothing clears
    it - but it means these two cannot be proved by patching the flag alone.
    Reloading under the patched flag is what makes them answer the question, and
    is also what would notice if either constant were moved somewhere the import
    order stopped being decided for us.
    """
    import app.core.marketplace as marketplace  # noqa: PLC0415
    import app.modules.match_elements.qdrant_supervisor as supervisor  # noqa: PLC0415
    from app.core.self_upgrade import DESKTOP_REPAIR  # noqa: PLC0415

    try:
        monkeypatch.delattr(sys, "frozen", raising=False)
        importlib.reload(marketplace)
        importlib.reload(supervisor)
        ordinary_card = marketplace._VECTOR_INDEX_ENCODER
        ordinary_client = supervisor._MISSING_CLIENT_HINT

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        importlib.reload(marketplace)
        importlib.reload(supervisor)
        frozen_card = marketplace._VECTOR_INDEX_ENCODER
        frozen_client = supervisor._MISSING_CLIENT_HINT
    finally:
        # Restore before anything else imports these. ``monkeypatch`` undoes the
        # flag at teardown, but the modules would keep whichever text they were
        # last executed with, and that text is global.
        monkeypatch.undo()
        importlib.reload(marketplace)
        importlib.reload(supervisor)

    with capsys.disabled():
        print("\n  app/core/marketplace.py::_VECTOR_INDEX_ENCODER")
        print(f"    ordinary install -> {ordinary_card}")
        print(f"    frozen desktop   -> {frozen_card}")
        print("\n  app/modules/match_elements/qdrant_supervisor.py::_MISSING_CLIENT_HINT")
        print(f"    ordinary install -> {ordinary_client}")
        print(f"    frozen desktop   -> {frozen_client}")

    assert "pip install sentence-transformers" in ordinary_card
    assert "pip install" not in frozen_card, f"a marketplace card offered pip to a frozen reader: {frozen_card}"
    assert DESKTOP_REPAIR in frozen_card

    assert "pip install openconstructionerp[semantic-clients]" in ordinary_client
    assert "pip install" not in frozen_client, f"the client hint offered pip to a frozen reader: {frozen_client}"
    assert DESKTOP_REPAIR in frozen_client

    # The routing must not eat the reassurance. ``repair_hint`` returns the whole
    # of its argument or none of it, so a sentence that is true on both installs
    # has to sit outside the call or one of the two readers never sees it.
    for text in (ordinary_client, frozen_client):
        assert "Everything else works without it." in text, (
            "the sentence that stops this reading as a broken install was parked inside the pip branch, "
            f"so the other reader lost it: {text}"
        )


def test_the_embedder_card_drops_its_copy_box_rather_than_filling_it_with_a_dead_command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The third polarity: a frozen branch that is deliberately empty.

    ``/api/costs/embedder-status`` feeds a copy-to-clipboard box. A copy box is
    only honest where the thing in it can be run, so on a frozen build
    ``pip_command`` empties and ``install_hint`` carries the sentence instead.
    The card is about the BGE-M3 stack, whose library is FlagEmbedding, and
    FlagEmbedding is outside ``requirements-desktop.lock`` - hence
    ``DESKTOP_NO_EXTRA`` here and not the repair wording.
    """
    from app.core.self_upgrade import DESKTOP_NO_EXTRA, DESKTOP_REPAIR  # noqa: PLC0415
    from app.modules.costs.router import embedder_status  # noqa: PLC0415

    monkeypatch.delattr(sys, "frozen", raising=False)
    ordinary = asyncio.run(embedder_status())

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    frozen = asyncio.run(embedder_status())

    with capsys.disabled():
        print("\n  app/modules/costs/router.py::embedder_status")
        print(f"    ordinary pip_command  -> {ordinary['pip_command']!r}")
        print(f"    ordinary install_hint -> {ordinary['install_hint']}")
        print(f"    frozen   pip_command  -> {frozen['pip_command']!r}")
        print(f"    frozen   install_hint -> {frozen['install_hint']}")

    assert ordinary["pip_command"] == "pip install --upgrade openconstructionerp[semantic]"
    assert "command above" in ordinary["install_hint"]

    assert frozen["pip_command"] == "", (
        f"the frozen build kept a copy box holding a command that cannot run there: {frozen['pip_command']!r}"
    )
    assert frozen["install_hint"] == DESKTOP_NO_EXTRA
    assert DESKTOP_REPAIR not in frozen["install_hint"], (
        "FlagEmbedding is not in requirements-desktop.lock, so offering a reinstall here sends the reader "
        "round a loop that arrives at the same missing package"
    )


#: (file, sentence). A remedy a frozen reader CAN follow must not sit inside the
#: pip branch. ``repair_hint`` swaps its whole argument, so anything parked in
#: there is invisible to the other install - and at both of these sites the
#: swallowed sentence was the one that mattered most to the desktop reader.
_ALTERNATIVES_THAT_MUST_SURVIVE_FREEZING = [
    ("app/modules/takeoff/service.py", "Or use the online AI analysis instead."),
    ("app/modules/match_elements/qdrant_supervisor.py", "Everything else works without it."),
]


@pytest.mark.parametrize(("where", "sentence"), _ALTERNATIVES_THAT_MUST_SURVIVE_FREEZING)
def test_a_remedy_a_frozen_reader_can_follow_is_not_parked_inside_the_pip_branch(where: str, sentence: str) -> None:
    """Source-level, because reaching one of these call sites needs a request and a document.

    The runtime proof above already covers the supervisor sentence; this covers
    the takeoff one, which sits behind ``recognize_candidates`` and a database
    session, and it states the rule for both so the next author reads it once.
    """
    path = _BACKEND / where
    source = path.read_text(encoding="utf-8")
    assert sentence in source, f"{where} no longer contains the sentence {sentence!r}; update this test with it"

    tree = ast.parse(source)
    inside_pip_branch = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name != "repair_hint":
            continue
        for arg in node.args:
            # Walk the argument rather than reading it directly: the moment
            # anyone writes it as "a " + b it is a BinOp, and a helper that
            # only knows Constant and JoinedStr would yield nothing and let
            # this assertion pass without having looked at anything.
            pieces = [text for inner in ast.walk(arg) for _lineno, text in _string_pieces(inner)]
            blob = " ".join(" ".join(piece.split()) for piece in pieces)
            if sentence in blob:
                inside_pip_branch.append(node.lineno)

    assert not inside_pip_branch, (
        f"{where}:{inside_pip_branch}: {sentence!r} is inside the repair_hint argument, so a frozen desktop "
        "reader never sees it - and that reader is the one it was written for, because it is the remedy that "
        "still works where pip does not. Concatenate it outside the call instead."
    )
