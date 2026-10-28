# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for ``scripts/check_no_proprietary_classification.py``.

The gate's own denylist is stored as hashes so that the script does not become a copy
of the material it exists to keep out of the tree. These tests inherit that property:
every red case is driven by an injected synthetic hash map, so proving that the gate
catches a proprietary title never requires writing one down here.

The green cases are the more interesting half. A denylist that fires on our own
replacement wording, or on the places that legitimately name a standard, would be
worse than no gate at all, so those are asserted against the real hash list.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
GATE_PATH = REPO_ROOT / "scripts" / "check_no_proprietary_classification.py"

# Invented vocabulary. None of it is in the real denylist, which is what lets these
# tests exercise the logic without carrying the material the logic is about.
MULTI_WORD_TITLE = "Fictional Widget Assembly"
SINGLE_WORD_TITLES = (
    "Widgetry",
    "Thingamy",
    "Doodad",
    "Gubbins",
    "Whatsit",
    "Doohickey",
    "Gizmo",
    "Contraption",
)
FAKE_BRAND = "Widgetformat"


def _load_gate() -> ModuleType:
    """Import the gate by file path; ``scripts/`` is not an importable package."""
    spec = importlib.util.spec_from_file_location("_classification_gate", GATE_PATH)
    assert spec is not None and spec.loader is not None, f"cannot load {GATE_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


def _titles(*entries: tuple[str, str, int]) -> dict[str, tuple[str, int]]:
    return {gate._sha(gate._norm(title)): (numbers, words) for title, numbers, words in entries}


def _brands(*tokens: str) -> frozenset[str]:
    return frozenset(gate._sha(token.lower()) for token in tokens)


def _scan(path: str, text: str, **kwargs: object) -> list[object]:
    kwargs.setdefault("title_hashes", {})
    kwargs.setdefault("brand_hashes", frozenset())
    kwargs.setdefault("allowed", {})
    return gate.scan_text(path, text, **kwargs)  # type: ignore[arg-type]


# ── head 1: a code paired with the title that belongs to it ────────────────────


def test_code_paired_with_its_official_title_is_red():
    found = _scan(
        "backend/app/core/demo_packs/example.py",
        f'    "07": "{MULTI_WORD_TITLE}",\n',
        title_hashes=_titles((MULTI_WORD_TITLE, "07", 3)),
    )
    assert [f.head for f in found] == ["pair"]
    assert MULTI_WORD_TITLE not in str(found[0]), "a finding must not echo the title it matched"


def test_pair_is_caught_in_every_shape_a_table_takes():
    titles = _titles((MULTI_WORD_TITLE, "07", 3))
    for text in (
        f'    "07": "{MULTI_WORD_TITLE}",\n',
        f"  {{ code: '07', label: '{MULTI_WORD_TITLE}' }},\n",
        f'    {{"number": "07", "title": "{MULTI_WORD_TITLE}"}},\n',
        f"  Division 07 - {MULTI_WORD_TITLE}\n",
    ):
        assert _scan("x.py", text, title_hashes=titles), f"missed shape: {text.strip()}"


def test_a_bilingual_title_is_read_in_both_languages():
    """The shape that walked past the gate: two titles in one title position.

    A pack written for a bilingual market puts the local title outside the
    brackets and an English gloss inside. Only one of the two can be the
    licensor's, and the gate used to stop at the opening bracket, so it read
    the half that was ours and never the half that was not.
    """
    titles = _titles((MULTI_WORD_TITLE, "07", 3))
    found = _scan(
        "backend/app/core/demo_packs/example.py",
        f'    "Division 07 - Travaux locaux ({MULTI_WORD_TITLE})",\n',
        title_hashes=titles,
    )
    assert [f.head for f in found] == ["pair"]

    # ...and the local-language half on its own is not a finding, which is what
    # makes the fix a rewrite of the gloss rather than a deletion of the title.
    assert _scan("x.py", '    "Division 07 - Travaux locaux",\n', title_hashes=titles) == []


def test_a_title_beside_a_local_code_reference_is_read():
    """A separator does the same job as a bracket, with no bracket in sight."""
    titles = _titles((MULTI_WORD_TITLE, "07", 3))
    for text in (
        f'    "07 - Travaux locaux ({MULTI_WORD_TITLE} - LOC 304)",\n',
        f'    "07 - {MULTI_WORD_TITLE} / Local Practice",\n',
        f'    "07 - Travaux, {MULTI_WORD_TITLE}",\n',
    ):
        assert _scan("x.py", text, title_hashes=titles), f"missed: {text.strip()}"


def test_a_title_opening_on_an_accented_capital_is_read():
    """``[A-Z]`` is not the set of capital letters outside English."""
    found = _scan(
        "x.py",
        f'    "Division 07 - Électricité ({MULTI_WORD_TITLE})",\n',
        title_hashes=_titles((MULTI_WORD_TITLE, "07", 3)),
    )
    assert [f.head for f in found] == ["pair"]


def test_one_title_position_reports_one_finding_per_division():
    """Several fragments of one string can hash to the same division.

    A bilingual line whose other language drops out of the normalisation
    matches as the whole title and again as the parenthetical. That is one
    leak in one place, and reporting it twice would inflate every count taken
    from this gate.
    """
    found = _scan(
        "x.py",
        f'    "07 - أعمال ({MULTI_WORD_TITLE})",\n',
        title_hashes=_titles((MULTI_WORD_TITLE, "07", 3)),
    )
    assert len(found) == 1, [str(f) for f in found]


def test_our_own_wording_survives_the_widening_in_every_shape():
    """The negative control, in the convict-case's own shape.

    Widening the matcher is only safe if what separates a finding from our own
    text is whose words they are, not where they sit. So the real scope wording
    is run through the same slots a violation occupies, against the real hash
    list rather than a synthetic one. The bilingual gloss is the shape that
    matters most: it is the one this widening exists to open up.
    """
    config = (REPO_ROOT / "backend" / "app" / "modules" / "us_pack" / "config.py").read_text(encoding="utf-8")
    entries = re.findall(r'"number":\s*"(\d{2})",\s*"scope":\s*"([^"]+)"', config)
    assert len(entries) >= 20, f"expected the full division list, found {len(entries)}"

    shapes = (
        '    "Division {n} - {s}",',
        '    "{n} - {s}",',
        '    "Division {n} - Travaux locaux ({s})",',
        "        # ── Division {n} - {s} ──────",
    )
    for shape in shapes:
        text = "\n".join(shape.format(n=number, s=scope) for number, scope in entries)
        found = gate.scan_text("backend/app/core/demo_packs/example.py", text)
        assert found == [], f"our own wording convicted in shape {shape!r}: {[str(f) for f in found]}"


def test_title_under_the_wrong_number_is_green():
    """Correspondence: the same words beside a different number are a coincidence."""
    found = _scan(
        "x.py",
        f'    "09": "{MULTI_WORD_TITLE}",\n',
        title_hashes=_titles((MULTI_WORD_TITLE, "07", 3)),
    )
    assert found == []


def test_one_single_word_trade_term_is_green():
    """Half the official titles are ordinary trade words; one proves nothing."""
    found = _scan(
        "x.py",
        f'    "07": "{SINGLE_WORD_TITLES[0]}",\n',
        title_hashes=_titles((SINGLE_WORD_TITLES[0], "07", 1)),
    )
    assert found == []


def test_one_division_repeated_many_times_stays_green():
    """The measured false-positive shape: many raw hits, few distinct divisions.

    A crosswalk to another country's standard repeats a handful of trade words across
    every line item. Counting raw hits calls that a copied table; counting distinct
    divisions does not.
    """
    titles = _titles(
        (SINGLE_WORD_TITLES[0], "07", 1),
        (SINGLE_WORD_TITLES[1], "08", 1),
        (SINGLE_WORD_TITLES[2], "09", 1),
        (SINGLE_WORD_TITLES[3], "10", 1),
    )
    lines = []
    for _ in range(15):
        for number, title in zip(("07", "08", "09", "10"), SINGLE_WORD_TITLES[:4], strict=True):
            lines.append(f'    "{number}": "{title}",')
    found = _scan("x.py", "\n".join(lines), title_hashes=titles)
    assert found == [], "60 raw hits at 4 distinct divisions must not fire"


def test_enough_distinct_divisions_is_the_compilation_and_is_red():
    numbers = [f"{index:02d}" for index in range(1, len(SINGLE_WORD_TITLES) + 1)]
    titles = _titles(*((title, number, 1) for title, number in zip(SINGLE_WORD_TITLES, numbers, strict=True)))
    text = "\n".join(f'    "{number}": "{title}",' for number, title in zip(numbers, SINGLE_WORD_TITLES, strict=True))

    found = _scan("x.py", text, title_hashes=titles)
    assert [f.head for f in found] == ["table"]
    assert str(len(SINGLE_WORD_TITLES)) in found[0].detail

    one_short = "\n".join(text.split("\n")[:-1])
    assert _scan("x.py", one_short, title_hashes=titles) == []


# ── head 2: the standard's name where a user reads it ──────────────────────────


def test_brand_in_a_user_visible_field_is_red():
    found = _scan(
        "backend/app/core/demo_packs/example.py",
        f'    boq_description="Detailed estimate for a hospital, {FAKE_BRAND} divisions",\n',
        brand_hashes=_brands(FAKE_BRAND),
    )
    assert [f.head for f in found] == ["brand"]
    assert "boq_description" in found[0].detail


def test_the_lowercase_technical_key_is_green():
    """``classification_standard`` is interop and is deliberately left alone."""
    text = (
        f'    classification_standard="{FAKE_BRAND.lower()}",\n'
        f'    "standard": "{FAKE_BRAND.lower()}",\n'
        f'    validation_rule_sets=["{FAKE_BRAND.lower()}", "boq_quality"],\n'
        f'        description="Classification standard: din276, nrm, {FAKE_BRAND.lower()}",\n'
    )
    assert _scan("x.py", text, brand_hashes=_brands(FAKE_BRAND)) == []


def test_a_description_split_across_lines_is_still_scanned():
    """The field name and the brand can sit on different lines of one statement."""
    text = (
        "    description=(\n"
        '        "US construction standards: payment applications, "\n'
        f'        "{FAKE_BRAND} divisions, imperial units."\n'
        "    ),\n"
    )
    found = _scan("x.py", text, brand_hashes=_brands(FAKE_BRAND))
    assert [f.head for f in found] == ["brand"]
    assert found[0].line_no == 1, "a spliced finding is reported at the line the field opens"


# ── the allowlist is by location, not global ───────────────────────────────────


def test_a_nominative_place_is_green_and_only_that_place():
    picker = "frontend/src/features/example/StandardPicker.tsx"
    text = f"  {{ value: '{FAKE_BRAND.lower()}', label: '{FAKE_BRAND}' }},\n"
    brands = _brands(FAKE_BRAND)

    assert _scan(picker, text, brand_hashes=brands, allowed={picker: frozenset({"label"})}) == []
    assert _scan("frontend/src/features/other/Page.tsx", text, brand_hashes=brands) != []


def test_an_allowlisted_file_is_still_examined_in_its_other_fields():
    picker = "frontend/src/features/example/StandardPicker.tsx"
    found = _scan(
        picker,
        f"  {{ label: 'Fine', description: 'Our estimate uses {FAKE_BRAND}' }},\n",
        brand_hashes=_brands(FAKE_BRAND),
        allowed={picker: frozenset({"label"})},
    )
    assert [f.head for f in found] == ["brand"]


def test_a_pack_can_be_exempted_by_path_prefix():
    allowed = {"packs/vendor-pack/": frozenset({"name"})}
    text = f'  "name": "{FAKE_BRAND} rule pack",\n'
    brands = _brands(FAKE_BRAND)

    assert _scan("packs/vendor-pack/rule_packs/a.json", text, brand_hashes=brands, allowed=allowed) == []
    assert _scan("packs/other-pack/rule_packs/a.json", text, brand_hashes=brands, allowed=allowed) != []


def test_an_inline_marker_clears_a_single_line():
    text = f'    boq_description="{FAKE_BRAND} divisions",  # denylist-ok\n'
    assert _scan("x.py", text, brand_hashes=_brands(FAKE_BRAND)) == []


# ── green against the real denylist, not a synthetic one ───────────────────────


def test_our_own_scope_wording_is_not_on_the_denylist():
    """The replacement wording must survive the gate that motivated writing it.

    Run against the real hashes: if someone ever hashes our own scope descriptions
    into the title list, every file we cleaned turns red and this is what says so.
    """
    config = (REPO_ROOT / "backend" / "app" / "modules" / "us_pack" / "config.py").read_text(encoding="utf-8")
    entries = re.findall(r'"number":\s*"(\d{2})",\s*"scope":\s*"([^"]+)"', config)
    assert len(entries) >= 20, f"expected the full division list in config.py, found {len(entries)}"

    text = "\n".join(f'    "{number}": "{scope}",' for number, scope in entries)
    assert gate.scan_text("backend/app/modules/us_pack/config.py", text) == []


def test_every_division_we_publish_wording_for_can_also_be_convicted():
    """Absence must not acquit.

    The gate is only as wide as its denylist. A division we ship replacement
    wording for but hold no title hash for is a division where a leak cannot be
    caught however it is written, and nothing would say so: the run would go
    green for want of an entry rather than for want of a violation. Deriving
    the expected set from our own config rather than restating it here means a
    new division, edition or scheme cannot enter the product and quietly shrink
    what is checked, because the two have to move together.
    """
    config = (REPO_ROOT / "backend" / "app" / "modules" / "us_pack" / "config.py").read_text(encoding="utf-8")
    published = {number for number, _ in re.findall(r'"number":\s*"(\d{2})",\s*"scope":\s*"([^"]+)"', config)}
    assert len(published) >= 20, f"expected the full division list, found {len(published)}"

    covered = {number for numbers, _ in gate._TITLE_HASHES.values() for number in numbers.split(",")}
    missing = sorted(published - covered)
    assert not missing, (
        f"divisions with our own wording but no title hash, so unconvictable: {missing}. "
        "Add the hash, or the gate is silent about them."
    )


def test_the_gate_is_green_over_the_tracked_tree(capsys):
    """The gate can only be wired into CI while the tree it guards passes it.

    The scanned count is asserted, not just the exit code. pytest runs from
    ``backend/``, and an earlier version of the gate listed the tree relative to the
    caller's directory, resolved none of those paths, scanned nothing and returned
    success. A green exit code alone would not have caught that.
    """
    assert gate.main(["check_no_proprietary_classification.py"]) == 0

    scanned = int(re.search(r"OK: (\d+) files scanned", capsys.readouterr().out).group(1))
    assert scanned > 1000, f"only {scanned} files scanned, the sweep did not reach the tree"


def test_a_sweep_that_reaches_nothing_is_not_reported_as_clean(monkeypatch):
    monkeypatch.setattr(gate, "_tracked_files", list)
    assert gate.main(["check_no_proprietary_classification.py"]) == 1


def test_a_directory_argument_scans_the_directory(capsys):
    """Pointing the gate at a package must read the package, not shrug at it.

    A directory failed the ``is_file`` test and was dropped without a word, so
    asking the gate about the demo packs scanned zero of them and printed OK. The
    count is the assertion: a green exit was exactly what the broken version gave.
    """
    assert gate.main(["check_no_proprietary_classification.py", "backend/app/core/demo_packs"]) == 0

    scanned = int(re.search(r"OK: (\d+) files scanned", capsys.readouterr().out).group(1))
    assert scanned > 10, f"only {scanned} files scanned, the directory was not expanded"


def test_an_argument_that_names_nothing_is_an_error_not_a_pass():
    """A typo in a pathspec must fail loudly rather than quietly guard less.

    Absence cannot acquit. A path matching no scannable file means the sweep is
    smaller than whoever wrote the invocation believes, and the only safe report
    for that is a failure naming the argument.
    """
    argv = ["check_no_proprietary_classification.py", "backend/app/core/no_such_directory"]
    assert gate.main(argv) == 1


def test_an_explicit_selection_of_unscannable_files_is_not_a_pass(capsys):
    """Every argument being a file type we skip is a fact, not a clean bill of health.

    The file here exists and is readable; it simply is not a type this gate parses.
    That has to be said out loud, because "0 files scanned, OK" and "nothing wrong
    here" are the same sentence to whoever reads the log.
    """
    argv = ["check_no_proprietary_classification.py", ".gitignore"]
    assert gate.main(argv) == 1
    assert "no files to scan" in capsys.readouterr().err
