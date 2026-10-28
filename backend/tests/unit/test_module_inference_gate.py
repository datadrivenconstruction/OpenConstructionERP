# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
#
# Negative control for the inference-declaration gate.
#
# The gate reports how many modules reach a model without saying so. A count is a
# fact about the gate until it names what it found, so every test here asserts on
# the NAME of the module in the output rather than on the number or on the exit
# code. A gate that goes red for the wrong module is a gate that will be believed
# for the wrong reason.
#
# Nothing here writes into backend/app/modules. The gate takes an app directory
# so the fixture tree lives in tmp_path: the loader discovers modules by walking
# that directory, this tree is shared by many sessions at once, and an untracked
# directory planted there would break a build for everybody.
#
# The fixture tests narrow the primitive set to one root, so the fixture does not
# have to carry a stub of every model entry point in the platform. Only the last
# test scans the real tree, because that scan costs about a minute: it parses
# every file under backend/app, which is what makes it able to see an import that
# a name-based sweep cannot.

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app.core.module_loader import InferenceDeclaration, InferenceRole, ModuleManifest

_GATE = Path(__file__).resolve().parents[3] / "scripts" / "check_module_inference_declarations.py"
_spec = importlib.util.spec_from_file_location("check_module_inference_declarations", _GATE)
assert _spec and _spec.loader, f"gate script not found at {_GATE}"
gate = importlib.util.module_from_spec(_spec)
sys.modules["check_module_inference_declarations"] = gate
_spec.loader.exec_module(gate)

_MANIFEST_HEAD = "from app.core.module_loader import InferenceDeclaration, InferenceRole, ModuleManifest\n\n"


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A minimal app directory holding one real primitive and nothing else."""
    monkeypatch.setattr(gate, "PRIMITIVES", {"app.core.vector": "a local embedding model"})
    root = tmp_path / "app"
    (root / "core").mkdir(parents=True)
    (root / "modules").mkdir(parents=True)
    (root / "core" / "vector.py").write_text("def encode_texts(texts):\n    return []\n", encoding="utf-8")
    return root


def _module(app: Path, name: str, *, imports: str = "", inference: str = "") -> Path:
    directory = app / "modules" / name
    directory.mkdir(parents=True)
    (directory / "service.py").write_text(f"{imports}\n\n\ndef work():\n    return None\n", encoding="utf-8")
    (directory / "manifest.py").write_text(
        f"{_MANIFEST_HEAD}manifest = ModuleManifest(\n"
        f"    name={('oe_' + name)!r},\n"
        f"    version='1.0.0',\n"
        f"    display_name={name!r},\n"
        f"{inference})\n",
        encoding="utf-8",
    )
    return directory


def _run(app: Path, capsys: pytest.CaptureFixture[str], *, strict: bool = False) -> tuple[int, str]:
    code = gate.main([str(app), *(["--strict"] if strict else [])])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_an_undeclared_module_reaching_a_model_is_named(app: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The whole point: the gate has to say which module, not how many."""
    _module(app, "quiet_one", imports="from app.core.vector import encode_texts")
    _module(app, "innocent", imports="import json")

    code, output = _run(app, capsys)

    assert "quiet_one" in output, output
    assert "1 module(s) reach an inference primitive and declare nothing" in output
    assert "innocent" not in output, "a module reaching nothing must not be reported"
    assert code == 0, "the gate reports before it blocks"


def test_the_same_module_declaring_the_call_is_not_reported(app: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Guard the guard: the report must respond to the declaration, not the name."""
    _module(
        app,
        "quiet_one",
        imports="from app.core.vector import encode_texts",
        inference=(
            "    inference=InferenceDeclaration(\n"
            "        role=InferenceRole.CALLS_MODEL,\n"
            "        what='free text into candidate catalogue items',\n"
            "    ),\n"
        ),
    )

    _, output = _run(app, capsys)

    assert "declare nothing" not in output
    assert "1 reach an inference primitive on their own account, 1 of those declare it" in output


def test_declaring_no_inference_while_calling_one_is_reported_as_worse(
    app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A wrong entry gets quoted; an absent one does not. They must not read alike."""
    _module(
        app,
        "insists_not",
        imports="from app.core.vector import encode_texts",
        inference="    inference=InferenceDeclaration(role=InferenceRole.NONE),\n",
    )

    _, output = _run(app, capsys)

    assert "insists_not  declares none, reaches app.core.vector" in output
    assert "declare the opposite" in output


def test_a_claim_of_not_being_a_model_without_a_reason_is_reported(
    app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """rule_based is an argument. An argument with no ground is evasion."""
    _module(app, "hand_rolled", inference="    inference=InferenceDeclaration(role=InferenceRole.RULE_BASED),\n")

    _, output = _run(app, capsys)

    assert "hand_rolled: rule_based with no `basis`" in output


def test_a_role_outside_the_vocabulary_is_named_with_its_value(app: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Four spellings of one idea is how a register stops being quotable."""
    _module(app, "improvised", inference="    inference=InferenceDeclaration(role='llm'),\n")

    _, output = _run(app, capsys)

    assert "improvised: 'llm' is not one of" in output


def test_a_model_built_in_place_is_reported_even_though_it_imports_nothing(
    app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The case an import graph structurally cannot find."""
    directory = _module(app, "rolls_its_own", imports="import json")
    (directory / "matcher.py").write_text(
        "def encode(texts):\n    return SentenceTransformer('all-MiniLM-L6-v2').encode(texts)\n",
        encoding="utf-8",
    )

    _, output = _run(app, capsys)

    assert "rolls_its_own: matcher.py" in output
    assert "REACHES NO PRIMITIVE, visible only here" in output


def test_a_primitive_that_is_not_in_the_tree_stops_the_gate(app: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A root that is not in the tree is reached by nobody, and that reads green.

    This is the failure that would be silent otherwise. Rename app/core/vector.py
    without touching the list in the gate and every module stops reaching it, so
    the scan finds nothing wrong with a tree it can no longer see.
    """
    _module(app, "quiet_one", imports="from app.core.vector import encode_texts")
    (app / "core" / "vector.py").rename(app / "core" / "embeddings.py")

    code, output = _run(app, capsys)

    assert code == 1
    assert "app.core.vector" in output
    assert "are not in" in output


def test_a_file_it_cannot_parse_stops_the_gate(app: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A partial graph reports fewer modules and does not say why."""
    _module(app, "quiet_one", imports="from app.core.vector import encode_texts")
    (app / "modules" / "quiet_one" / "broken.py").write_text("def (:\n", encoding="utf-8")

    code, output = _run(app, capsys)

    assert code == 1
    assert "could not be parsed" in output


def test_strict_turns_a_finding_into_a_failure(app: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The switch that makes this blocking later, proved before it is flipped."""
    _module(app, "quiet_one", imports="from app.core.vector import encode_texts")

    assert _run(app, capsys)[0] == 0
    assert _run(app, capsys, strict=True)[0] == 1


@pytest.mark.slow
def test_the_live_tree_is_scanned_and_the_scan_is_not_empty(capsys: pytest.CaptureFixture[str]) -> None:
    """A green run on the real tree must not come from having looked at nothing.

    Pinned as floors rather than as exact counts. Both numbers move with every
    module that gains or loses a model call, and a test that has to be edited on
    every such change gets edited without being read.
    """
    code = gate.main([])
    output = capsys.readouterr().out

    assert code == 0
    scanned = int(output.split(" modules scanned", 1)[0].rsplit(" ", 1)[-1])
    reach = int(output.split("modules scanned under", 1)[1].split(",", 1)[1].split(" reach")[0])

    assert scanned > 150, f"only {scanned} module directories were scanned"
    assert reach > 20, f"only {reach} modules reach a primitive, so the root set has stopped matching the tree"


def test_a_module_that_denies_on_one_path_and_admits_on_another_is_not_contradicted(
    app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The mode-dependent case. Denying for one mode is not denying."""
    _module(
        app,
        "two_modes",
        imports="from app.core.vector import encode_texts",
        inference=(
            "    inference=(\n"
            "        InferenceDeclaration(\n"
            "            role=InferenceRole.RULE_BASED,\n"
            "            when=\"mode='lexical'\",\n"
            "            basis='a fixed string ratio, written in the file',\n"
            "        ),\n"
            "        InferenceDeclaration(\n"
            "            role=InferenceRole.CALLS_MODEL,\n"
            "            when=\"mode='semantic'\",\n"
            "            what='the same ranking, by embedding both sides',\n"
            "        ),\n"
            "    ),\n"
        ),
    )

    _, output = _run(app, capsys)

    assert "two_modes" not in output, "a module that admits inference on one path is declared, not contradicted"
    assert "1 reach an inference primitive on their own account, 1 of those declare it" in output


def test_a_module_whose_every_declaration_denies_is_still_contradicted(
    app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Guard the guard above: several denials are still a denial."""
    _module(
        app,
        "denies_twice",
        imports="from app.core.vector import encode_texts",
        inference=(
            "    inference=(\n"
            "        InferenceDeclaration(role=InferenceRole.RULE_BASED, when='a', basis='x'),\n"
            "        InferenceDeclaration(role=InferenceRole.NONE, when='b'),\n"
            "    ),\n"
        ),
    )

    _, output = _run(app, capsys)

    assert "denies_twice  declares none, rule_based, reaches app.core.vector" in output


def test_two_declarations_without_a_when_are_named_as_too_thin(app: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Two unconditional statements about one module cannot both be reported."""
    _module(
        app,
        "unscoped",
        inference=(
            "    inference=(\n"
            "        InferenceDeclaration(role=InferenceRole.NONE),\n"
            "        InferenceDeclaration(role=InferenceRole.CALLS_MODEL, what='something'),\n"
            "    ),\n"
        ),
    )

    _, output = _run(app, capsys)

    # Both roles, not just one. A findings map keyed by module and written once
    # per declaration reports the last one and counts modules while calling them
    # declarations, which passes an assertion that only asks whether the module
    # was named at all.
    assert "unscoped: none is one of 2 declarations here and has no `when`" in output
    assert "unscoped: calls_model is one of 2 declarations here and has no `when`" in output
    assert "2 declaration(s) in 1 module(s) are too thin to quote" in output


def test_two_declarations_claiming_the_same_condition_are_named(app: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Saying `when` is not enough if both entries say the same thing.

    This is the one rule that has to read the value out of the manifest rather
    than notice that a field was filled, and it is also the rule that the two
    copies of this vocabulary first drifted on: the manifest objects enforced it
    and the gate did not, so a module could answer one question twice and the
    scan stayed silent about it.
    """
    _module(
        app,
        "double_booked",
        inference=(
            "    inference=(\n"
            "        InferenceDeclaration(role=InferenceRole.RULE_BASED, when=\"mode='lexical'\", basis='a fixed "
            "ratio'),\n"
            "        InferenceDeclaration(role=InferenceRole.CALLS_MODEL, when=\"mode='lexical'\", what='a "
            "ranking'),\n"
            "    ),\n"
        ),
    )

    _, output = _run(app, capsys)

    assert "double_booked: two declarations both claim `when` \"mode='lexical'\"" in output


def _render(declarations: tuple[InferenceDeclaration, ...]) -> str:
    """The manifest source that states exactly these declarations.

    Rendered from the objects rather than written out beside them, so the parity
    test below has one source of truth and cannot pass by having been given two
    inputs that quietly differ.
    """
    entries = []
    for declaration in declarations:
        fields = [f"role={declaration.role.value!r}"]
        fields += [
            f"{field}={value!r}"
            for field, value in (
                ("when", declaration.when),
                ("what", declaration.what),
                ("basis", declaration.basis),
            )
            if value
        ]
        entries.append("InferenceDeclaration(" + ", ".join(fields) + ")")
    if len(entries) == 1:
        return f"    inference={entries[0]},\n"
    return "    inference=(\n" + "".join(f"        {entry},\n" for entry in entries) + "    ),\n"


_PARITY_SHAPES: list[tuple[InferenceDeclaration, ...]] = [
    (InferenceDeclaration(role=InferenceRole.NONE),),
    (InferenceDeclaration(role=InferenceRole.CALLS_MODEL),),
    (InferenceDeclaration(role=InferenceRole.CALLS_MODEL, what="a drawing into measurements"),),
    (InferenceDeclaration(role=InferenceRole.CONSUMES_RESULT),),
    (InferenceDeclaration(role=InferenceRole.CONSUMES_RESULT, what="the estimate oe_ai produced"),),
    (InferenceDeclaration(role=InferenceRole.RULE_BASED),),
    (InferenceDeclaration(role=InferenceRole.RULE_BASED, basis="hard-coded predicates, nothing is loaded"),),
    (
        InferenceDeclaration(role=InferenceRole.NONE),
        InferenceDeclaration(role=InferenceRole.CALLS_MODEL, what="a ranking"),
    ),
    (
        InferenceDeclaration(role=InferenceRole.RULE_BASED, when="mode='lexical'", basis="a fixed ratio"),
        InferenceDeclaration(role=InferenceRole.CALLS_MODEL, when="mode='lexical'", what="a ranking"),
    ),
    (
        InferenceDeclaration(role=InferenceRole.RULE_BASED, when="mode='lexical'", basis="a fixed ratio"),
        InferenceDeclaration(role=InferenceRole.CALLS_MODEL, when="mode='semantic'", what="a ranking"),
    ),
]


@pytest.mark.parametrize("declarations", _PARITY_SHAPES, ids=lambda shape: "+".join(d.role.value for d in shape))
def test_the_gate_and_the_manifest_agree_on_which_declarations_are_too_thin(
    declarations: tuple[InferenceDeclaration, ...], app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The rules live in two places, so something has to hold the two together.

    The gate refuses to import a manifest, so it re-states in ast what
    InferenceDeclaration.gaps and ModuleManifest.inference_gaps state in Python.
    Both files say to edit one and edit the other, and an instruction in prose
    that nothing checks is how the register ends up describing a tree it no
    longer matches.
    """
    manifest = ModuleManifest(name="oe_parity", version="1.0.0", display_name="Parity", inference=declarations)
    _module(app, "parity", inference=_render(declarations))

    _, output = _run(app, capsys)

    assert ("\n  parity: " in output) == bool(manifest.inference_gaps()), output
