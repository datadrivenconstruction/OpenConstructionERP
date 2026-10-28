# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠One Chinese fee name, one markup category, in every file that states one.

建标[2013]44号 describes a construction price along two axes that are
alternatives rather than layers. By cost element it is labour, material, plant,
the enterprise management fee, profit, statutory charges and tax. By price
formation it is bill items, preliminaries, other items, statutory charges and
tax. Under 清单计价 the management fee and profit sit inside the 综合单价, so on
a bill they describe how a unit rate is built; preliminaries and statutory
charges are heads beside the bill items and describe nothing about a rate.

That distinction is carried in this codebase by the markup ``category`` field,
and it is load-bearing rather than decorative. ``price_breakdown.mapping``
derives a unit rate's overhead and profit by summing the markup lines whose
category is ``overhead`` and ``profit``, so a bill head filed under ``overhead``
is reported to the estimator as part of the rate. Four separate files stated a
Chinese stack and they disagreed about 规费 alone three ways, filing it as
``other`` in one, ``overhead`` in two and ``tax`` in the fourth. A decision
that lives in four copies is not made until all four say it.

The census is taken by parsing rather than importing, because two of the four
files are demo packs whose names contain a hyphen and are loaded by path.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import app
from app.modules.boq.markup_templates import DEFAULT_MARKUP_TEMPLATES
from app.modules.price_breakdown.mapping import _markup_pct

#: The category each Chinese fee must carry, and the reason in one word.
#:
#: ``overhead`` and ``profit`` mean "this is a component of a 综合单价" to the
#: price analysis, so only the two fees that 清单计价 puts inside the unit rate
#: may hold them. Everything else on the 造价形成 axis is a head: it belongs to
#: the bill, not to any rate, and ``other`` is what says so.
FEE_CATEGORY: dict[str, str] = {
    "企业管理费": "overhead",  # a 综合单价 component
    "利润": "profit",  # a 综合单价 component
    "措施项目费": "other",  # head
    "安全文明施工费": "other",  # head, a 总价措施项目
    "规费": "other",  # head, provincially set
    "增值税": "tax",  # head
}

_APP_ROOT = Path(app.__file__).resolve().parent

#: Files that state a Chinese markup stack and are part of the repository. A
#: new one belongs here, and the count below is asserted so that one leaving
#: quietly is a failure rather than a smaller test.
REQUIRED_SOURCES: dict[str, Path] = {
    "residential-shenzhen": _APP_ROOT / "core" / "demo_packs" / "residential-shenzhen.py",
    "office-shanghai": _APP_ROOT / "core" / "demo_packs" / "office-shanghai.py",
}

#: Files that state one but may not be present in a given tree. ``seed_demo_v2``
#: is the v2 demo seeder, which is not committed yet; it is judged when it is
#: there and skipped when it is not, so this suite passes on a clean checkout
#: without pretending the file was checked. Move an entry up once it lands.
OPTIONAL_SOURCES: dict[str, Path] = {
    "seed_demo_v2": _APP_ROOT / "scripts" / "seed_demo_v2.py",
}


def _present_sources() -> dict[str, Path]:
    return {
        **REQUIRED_SOURCES,
        **{name: path for name, path in OPTIONAL_SOURCES.items() if path.is_file()},
    }


_CATEGORIES = frozenset({"overhead", "profit", "tax", "contingency", "other"})
_LEADING_HAN = re.compile(r"^([一-鿿]+)")


def _fee_key(name: str) -> str | None:
    """The bare fee name, dropping the English gloss the sources append.

    The four sources write the same fee three ways: bare, with a parenthesised
    translation, and with the rate repeated inside the parentheses. Only the
    leading run of Han characters is the fee.
    """
    match = _LEADING_HAN.match(name.strip())
    return match.group(1) if match else None


def _census_from_source(path: Path) -> list[tuple[str, str]]:
    """Every ``(fee, category)`` pair a source file states, by parsing it.

    Both tuple shapes in use put the category third: a demo pack writes
    ``(name, rate, category, apply_to)`` and the v2 seeder writes
    ``(name, kind, category, rate)``. A tuple qualifies only when its first
    element opens with Han characters and its third is a known category, so an
    unrelated four-element tuple of strings cannot join the census.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Tuple) or len(node.elts) < 3:
            continue
        first, third = node.elts[0], node.elts[2]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue
        if not (isinstance(third, ast.Constant) and third.value in _CATEGORIES):
            continue
        fee = _fee_key(first.value)
        if fee is not None:
            found.append((fee, third.value))
    return found


def _census_from_canonical() -> list[tuple[str, str]]:
    """The regional table's CN stack, read as the same kind of pair."""
    found: list[tuple[str, str]] = []
    for line in DEFAULT_MARKUP_TEMPLATES["CN"]:
        fee = _fee_key(str(line["name"]))
        if fee is not None:
            found.append((fee, str(line["category"])))
    return found


def _violations(pairs: list[tuple[str, str]]) -> list[str]:
    """Fees whose category is not the one :data:`FEE_CATEGORY` requires."""
    return [
        f"{fee} is {category}, expected {FEE_CATEGORY[fee]}"
        for fee, category in pairs
        if fee in FEE_CATEGORY and category != FEE_CATEGORY[fee]
    ]


def _full_census() -> dict[str, list[tuple[str, str]]]:
    census = {name: _census_from_source(path) for name, path in _present_sources().items()}
    census["markup_templates"] = _census_from_canonical()
    return census


# ── The parser has to be shown to work before it is trusted ─────────────────


def test_the_required_sources_are_all_present() -> None:
    """The optional list must not become a hiding place.

    A source moved from required to optional would shrink this suite to
    whatever is left while every remaining assertion stayed green, so the
    membership of the required list is asserted rather than assumed.
    """
    assert sorted(REQUIRED_SOURCES) == ["office-shanghai", "residential-shenzhen"]
    missing = [name for name, path in REQUIRED_SOURCES.items() if not path.is_file()]
    assert missing == [], f"required sources are gone from the tree: {missing}"


@pytest.mark.parametrize("source", sorted({*REQUIRED_SOURCES, "markup_templates"}))
def test_every_source_yields_a_chinese_fee_line(source: str) -> None:
    """A scanner that has stopped looking reports what a clean file reports.

    Every assertion below is of the form "nothing found is wrong", so an empty
    census would pass all of them while proving nothing. This is the positive
    control: each source must actually give the parser something to judge.
    """
    pairs = _full_census()[source]

    assert pairs, f"{source} contributed no Chinese fee lines; the parser or the file moved"
    assert any(fee in FEE_CATEGORY for fee, _ in pairs), (
        f"{source} yielded {sorted({fee for fee, _ in pairs})}, none of them a fee this test knows"
    )


def test_the_census_covers_the_fee_table_it_asserts_against() -> None:
    """Every fee named in :data:`FEE_CATEGORY` is really observed somewhere.

    Without this, a fee could be renamed out of all four files and the table
    would keep describing a rule nothing is subject to any more.
    """
    observed = {fee for pairs in _full_census().values() for fee, _ in pairs}

    assert set(FEE_CATEGORY) <= observed, f"named but never seen: {sorted(set(FEE_CATEGORY) - observed)}"


# ── The rule ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("source", sorted({*_present_sources(), "markup_templates"}))
def test_a_chinese_fee_carries_the_category_its_axis_implies(source: str) -> None:
    """A 综合单价 component is overhead or profit; a bill head is not."""
    problems = _violations(_full_census()[source])

    assert problems == [], f"{source}: {problems}"


def test_the_rule_rejects_the_arrangement_it_was_written_for() -> None:
    """The negative control, in the exact shape the defect had.

    Both bill heads were filed as overhead, which is what put them inside the
    unit-rate analysis. If a future edit widened the rule until it accepted
    anything, the assertion above would stay green on a broken tree; this is
    what stops that.
    """
    as_it_was = [("措施项目费", "overhead"), ("企业管理费", "overhead"), ("规费", "overhead")]

    problems = _violations(as_it_was)

    assert len(problems) == 2
    assert any("措施项目费" in p for p in problems)
    assert any("规费" in p for p in problems)


def test_one_fee_never_has_two_categories_across_the_sources() -> None:
    """Agreement, asserted for every fee rather than only the known ones.

    :data:`FEE_CATEGORY` covers the six fees that exist today. A seventh added
    to two files with two different categories would satisfy every assertion
    above, because neither copy would be judged at all.
    """
    by_fee: dict[str, dict[str, set[str]]] = {}
    for source, pairs in _full_census().items():
        for fee, category in pairs:
            by_fee.setdefault(fee, {}).setdefault(category, set()).add(source)

    split = {fee: {cat: sorted(src) for cat, src in cats.items()} for fee, cats in by_fee.items() if len(cats) > 1}

    assert split == {}, f"one fee, two categories: {split}"


# ── What the category field actually decides ────────────────────────────────


def test_the_unit_rate_analysis_reads_the_rate_and_not_the_bill_heads() -> None:
    """The behavioural half: the defect was a number on a screen.

    ``from_position`` derives a position's overhead and profit by summing the
    bill's markup lines by category, so this asserts the sums rather than the
    field, and asserts them as equalities. The management fee is what a Chinese
    unit rate carries as overhead; 措施项目费 and 规费 are not part of it.
    """
    lines = list(DEFAULT_MARKUP_TEMPLATES["CN"])

    assert _markup_pct(lines, "overhead") == 8
    assert _markup_pct(lines, "profit") == 5

    heads = sum(1 for line in lines if str(line["category"]) == "other")
    assert heads == 2, "措施项目费 and 规费 are the two heads; a third would change what the analysis omits"
