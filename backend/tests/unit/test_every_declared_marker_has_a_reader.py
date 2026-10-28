# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A declared marker that nothing reads is a name with no effect.

The other direction is already closed and closed harder. ``--strict-markers``
in ``backend/pyproject.toml`` turns a marker used but not declared into a
collection error, so a typo in a decorator refuses rather than warns. This file
is the remaining half: a marker DECLARED and read by nothing at all.

The obvious form of that check would be "declared and not used in any
decorator", and it is the wrong one. A marker can be entirely legitimate with
zero decorators: an escape hatch that an autouse fixture looks up with
``get_closest_marker`` is real and load-bearing on the day no test yet needs to
opt out. A rule that counted decorators alone would call that dead and be
wrong, and it would be wrong about exactly the marker whose absence is hardest
to notice.

So a marker counts as read when any of three channels mentions it: a decorator
(``pytest.mark.NAME`` in any of its forms), a runtime lookup
(``get_closest_marker``/``iter_markers``), or a lane selecting on it with
``-m``. A name in none of the three is dead config: it makes ``-m NAME`` select
nothing, which exits 5, and it makes a reader believe a category exists that
does not.

The set this finds is empty today and that is the honest outcome, not a reason
to skip the gate. What matters is that it can fail, which the accompanying test
shows by planting a marker no channel mentions.
"""

from __future__ import annotations

import re
import tomllib
from functools import lru_cache
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
WORKFLOWS = ROOT / ".github" / "workflows"
PYPROJECT = BACKEND / "pyproject.toml"

#: One pass per file for all three shapes at once. Splitting these into three
#: searches meant three reads of a 2400-file tree for no gain.
_REFERENCE = re.compile(
    rb"""pytest\.mark\.([A-Za-z_][A-Za-z0-9_]*)"""
    rb"""|(?:get_closest_marker|iter_markers)\(\s*["']([A-Za-z_][A-Za-z0-9_]*)["']"""
)

#: ``-m`` selection in a lane. The expression may be quoted and may carry
#: ``not``/``and``/``or``, so every identifier in it counts as a mention.
_DASH_M = re.compile(r"""-m\s+(?:"([^"]*)"|'([^']*)'|(\S+))""")


def declared_markers() -> list[str]:
    """Marker names from the pytest ini table, without their descriptions."""
    ini = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]
    return [entry.split(":")[0].split("(")[0].strip() for entry in ini.get("markers", [])]


def _python_sources() -> list[Path]:
    paths = sorted(p for p in (BACKEND / "tests").rglob("*.py") if "__pycache__" not in p.parts)
    conftest = BACKEND / "conftest.py"
    if conftest.exists():
        paths.append(conftest)
    return paths


def readers_by_marker(extra_names: tuple[str, ...] = ()) -> dict[str, set[str]]:
    """Map every declared marker to the channels that mention it.

    Args:
        extra_names: Names to report on besides the declared ones. The test
            uses this to plant a marker no channel mentions and see the gate
            find it, rather than trusting that it would.

    Returns:
        Marker name to the set of channels naming it: ``decorator``,
        ``runtime`` or ``lane``. A name mapped to an empty set is the finding.
    """
    mentions = _mentions()
    names = set(declared_markers()) | set(extra_names)
    return {name: set(mentions.get(name, ())) for name in names}


@lru_cache(maxsize=1)
def _mentions() -> dict[str, frozenset[str]]:
    """Every marker name any channel mentions, mapped to those channels.

    Cached and computed over all names rather than only the declared ones, so
    the planted case in the tests below costs nothing extra. The scan reads
    bytes and matches a bytes pattern, because nothing here needs the text.

    About five seconds on a quiet machine: 0.5 to list 1939 files, 2.3 to read
    23 MB of them and 2.4 for the pattern. Measured much higher while the rest
    of the tree was busy, which is contention rather than this code. The cache
    is what keeps the three tests below to one scan between them.
    """
    found: dict[str, set[str]] = {}

    for path in _python_sources():
        for decorator, runtime in _REFERENCE.findall(path.read_bytes()):
            if decorator:
                found.setdefault(decorator.decode(), set()).add("decorator")
            if runtime:
                found.setdefault(runtime.decode(), set()).add("runtime")

    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        text = workflow.read_text(encoding="utf-8", errors="replace")
        for groups in _DASH_M.findall(text):
            expression = next((g for g in groups if g), "")
            for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression):
                found.setdefault(token, set()).add("lane")

    return {name: frozenset(channels) for name, channels in found.items()}


def test_every_declared_marker_is_read_somewhere() -> None:
    """A declared marker has to be used, looked up, or selected on."""
    readers = readers_by_marker()
    assert readers, "no markers are declared at all, so this test proved nothing"

    unread = sorted(name for name, channels in readers.items() if not channels)
    assert not unread, (
        f"{len(unread)} of {len(readers)} declared markers are named by no decorator, no "
        f"get_closest_marker or iter_markers lookup, and no -m expression in any lane: {unread}. "
        "A marker nothing reads makes `-m NAME` select nothing and exit 5, and tells the next "
        "reader a category exists that does not. Delete the declaration, or give it a reader."
    )


def test_the_gate_finds_a_marker_nothing_mentions() -> None:
    """The planted case, because a green list here is otherwise unfalsifiable."""
    planted = "marker_no_channel_mentions_zzz"
    readers = readers_by_marker(extra_names=(planted,))

    assert readers[planted] == set(), (
        f"{planted} was reported as read by {sorted(readers[planted])}, so this gate cannot "
        "distinguish a dead declaration from a live one and its green means nothing."
    )
    assert any(readers[name] for name in declared_markers()), (
        "no declared marker resolved to any channel, so the scan is finding nothing at all "
        "and would report every marker as dead"
    )


def test_the_scan_recognises_all_three_shapes() -> None:
    """Each channel is proven against a sample, not against today's tree.

    Asserting instead that some real marker currently uses each channel would
    tie this file to whatever the suite happens to contain. The runtime channel
    in particular can legitimately have no user for a while, and a gate that
    went red when a marker stopped being looked up would be measuring the wrong
    thing. What has to hold is that the scan can SEE each shape.
    """
    sample = "\n".join(
        [
            "@pytest.mark.sample_decorated",
            "pytestmark = pytest.mark.sample_module_level",
            'request.node.get_closest_marker("sample_looked_up")',
            "for m in item.iter_markers('sample_iterated'):",
        ]
    )
    matches = _REFERENCE.findall(sample.encode())
    decorators = {name.decode() for name, _ in matches if name}
    runtimes = {name.decode() for _, name in matches if name}

    assert decorators == {"sample_decorated", "sample_module_level"}, decorators
    assert runtimes == {"sample_looked_up", "sample_iterated"}, runtimes

    lane_sample = "\n".join(['run: pytest -m "not tenant_isolation" tests', "run: pytest -m slow"])
    lane = _DASH_M.findall(lane_sample)
    tokens = {
        tok for groups in lane for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", next((g for g in groups if g), ""))
    }
    assert {"tenant_isolation", "slow"} <= tokens, tokens
