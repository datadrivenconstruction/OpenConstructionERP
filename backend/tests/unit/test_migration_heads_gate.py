# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The single-head gate sees a fork that no single author can see.

Three revisions were added in parallel and two chained off the same parent.
Each author ran ``alembic heads`` inside their own task, each saw one head, and
each was telling the truth: they ran before the others had written a file. The
fork existed only in the union.

The parser is the part worth testing rather than the arithmetic. The first
draft read ``down_revision`` with a single-line regex and lost the parents of
every merge revision written as a multi-line tuple, which turned 39 merges into
39 orphans and reported 43 heads over a tree that had one. So the tuple cases
are here as fixtures, both shapes.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_GATE = Path(__file__).resolve().parents[3] / "scripts" / "check_migration_heads.py"
_spec = importlib.util.spec_from_file_location("check_migration_heads", _GATE)
assert _spec and _spec.loader, f"gate script not found at {_GATE}"
gate = importlib.util.module_from_spec(_spec)
sys.modules["check_migration_heads"] = gate
_spec.loader.exec_module(gate)


def _write(directory: Path, name: str, revision: str, down: str) -> None:
    """Write a revision file the way the tree writes them."""
    directory.joinpath(name).write_text(
        '"""A revision."""\n'
        "from __future__ import annotations\n\n"
        f"revision: str = {revision!r}\n"
        f"down_revision = {down}\n"
        "branch_labels = None\n"
        "depends_on = None\n\n"
        "def upgrade() -> None:\n    pass\n",
        encoding="utf-8",
    )


def _entries(directory: Path) -> list[tuple[str, str]]:
    """Read a fixture directory into the name and text pairs the gate parses.

    ``read_graph`` stopped taking a directory when the gate moved off the disk
    and onto the committed graph. It takes pairs now, so whoever produced them
    is the caller's business: the gate reads them from the index, and these
    tests read them from a temporary directory.
    """
    return sorted((path.name, path.read_text(encoding="utf-8")) for path in directory.glob("*.py"))


def test_a_linear_chain_has_one_head(tmp_path: Path) -> None:
    _write(tmp_path, "v1.py", "v1", "None")
    _write(tmp_path, "v2.py", "v2", '"v1"')
    _write(tmp_path, "v3.py", "v3", '"v2"')

    graph = gate.read_graph(_entries(tmp_path))

    assert graph.unparsed == []
    assert graph.heads == ["v3"]


def test_two_revisions_on_one_parent_are_two_heads(tmp_path: Path) -> None:
    """The exact shape that reached the tree: same parent, two children."""
    _write(tmp_path, "v1.py", "v1", "None")
    _write(tmp_path, "v2a.py", "v2a", '"v1"')
    _write(tmp_path, "v2b.py", "v2b", '"v1"')

    graph = gate.read_graph(_entries(tmp_path))

    assert graph.heads == ["v2a", "v2b"]


def test_a_merge_revision_written_as_a_multiline_tuple_keeps_both_parents(tmp_path: Path) -> None:
    """The bug that made the first parser report 43 heads over a one-head tree.

    A merge whose parents are a tuple across several lines must not lose them,
    or every branch it closed reappears as a head and the merge itself as a
    base.
    """
    _write(tmp_path, "v1.py", "v1", "None")
    _write(tmp_path, "v2a.py", "v2a", '"v1"')
    _write(tmp_path, "v2b.py", "v2b", '"v1"')
    _write(tmp_path, "v3.py", "v3", '(\n    "v2a",\n    "v2b",\n)')

    graph = gate.read_graph(_entries(tmp_path))

    assert sorted(graph.parents["v3"]) == ["v2a", "v2b"]
    assert graph.heads == ["v3"]
    assert graph.bases == ["v1"]


def test_a_merge_written_on_one_line_keeps_both_parents(tmp_path: Path) -> None:
    _write(tmp_path, "v1.py", "v1", "None")
    _write(tmp_path, "v2a.py", "v2a", '"v1"')
    _write(tmp_path, "v2b.py", "v2b", '"v1"')
    _write(tmp_path, "v3.py", "v3", '("v2a", "v2b")')

    graph = gate.read_graph(_entries(tmp_path))

    assert sorted(graph.parents["v3"]) == ["v2a", "v2b"]
    assert graph.heads == ["v3"]


def test_two_files_claiming_one_revision_id_are_reported(tmp_path: Path) -> None:
    """Alembic would load whichever it walked last and drop the other silently."""
    _write(tmp_path, "v1.py", "v1", "None")
    _write(tmp_path, "v2.py", "v2", '"v1"')
    _write(tmp_path, "v2_again.py", "v2", '"v1"')

    graph = gate.read_graph(_entries(tmp_path))

    assert len(graph.unparsed) == 1
    assert "duplicate id v2" in graph.unparsed[0]


def test_the_committed_graph_has_exactly_one_head() -> None:
    """The gate over the graph that ships, which is the one it actually guards.

    This is the assertion that would have caught the fork it was written for,
    and it is deliberately not a fixture: a gate proven only against fixtures
    is proven against the author's idea of the repository.

    It asks HEAD plus the index rather than the versions directory. In a tree
    several sessions write to at once, an untracked revision file forks the
    graph on one disk and nowhere else, and a test that read the directory
    would go red for everybody over a file that ships to nobody. The gate
    itself made that move; this follows it, and the disk stays a warning.
    """
    graph = gate.read_graph(gate.index_entries().items())

    assert graph.unparsed == [], f"unparsable revision files: {graph.unparsed}"
    assert len(graph.revisions) >= gate.MIN_EXPECTED_REVISIONS, (
        f"only {len(graph.revisions)} revisions found, so this assertion is not about the tree"
    )
    assert graph.dangling == [], f"revisions named as a parent but present nowhere: {graph.dangling}"
    assert len(graph.heads) == 1, f"expected one head, found {graph.heads}"
