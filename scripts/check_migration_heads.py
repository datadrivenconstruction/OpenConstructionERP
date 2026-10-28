#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Fail if the Alembic revision graph that ships has more than one head.

Written the day three agents added a revision each in parallel and two of them
chained off the same parent. Every one of them checked ``alembic heads`` inside
its own task and every one of them truthfully reported a single head, because
each ran before the others had written their file. The fork was only visible to
someone looking at all three at once, which is exactly the kind of thing a gate
should be doing instead of a person.

A second head is not a cosmetic problem. ``alembic upgrade head`` refuses to
run against an ambiguous head, so the fork is discovered by whoever upgrades
first, which on a release is the user.

Why this asks about the commit and not only about the disk
----------------------------------------------------------
On 2026-08-28 ``v3311_rebar_schedule`` was committed declaring
``down_revision = "v3310_variation_request_boq"``. ``v3310`` is a complete,
well-written revision that had been sitting untracked in a shared working tree
since the evening before. The author ran this script first and it said 342
revisions, exactly one head. That was a true statement, and it was about a tree
that existed on one disk and nowhere else. In the commit the same graph held a
revision whose parent did not exist, therefore two heads, and ``alembic upgrade
head`` on a fresh clone refused to run at all. Every install built from that
commit could not migrate. It was caught by CI, where the working directory is
the commit, and by then it was pushed.

So the disk answer is not the answer. This script computes both graphs, prints
one line when they agree, and when they differ says so in those words and names
the revisions on each side. The committed graph decides the exit code, because
that is the graph that ships.

Where the committed content comes from
--------------------------------------
From the index, read with ``git ls-files --stage`` and ``git cat-file --batch``.
The index already is HEAD's blobs with the staged changes applied: a tracked
file nobody touched carries HEAD's sha, a staged add or edit replaces it, a
staged delete drops out, and an untracked file was never in it. So the tree
that would be committed needs no reconstruction, no temp directory and nothing
written anywhere. Neither does it need any history, which matters because CI
checks out shallow and the index is fully populated there regardless.

The one thing the index does not model is this repository's own commit form.
Work here goes in as ``git commit --only -F msg -- <paths>``, which builds its
tree from HEAD plus the working-tree content of the named paths and ignores the
index entirely, so nothing is ever staged. Run with no arguments in that
workflow the check would answer about HEAD and stay silent about the file about
to be committed, which is the original failure wearing a new hat. Hence
``--committing``: name the paths you are about to commit and their working-tree
content is laid over the index base. That invocation is the one that reproduces
the incident and goes red.

Why this reads the files instead of asking Alembic
--------------------------------------------------
``ScriptDirectory`` would answer the same question and would answer it more
authoritatively. It also imports the Alembic and SQLAlchemy stack, which on at
least one developer machine here wedges for minutes on an unrelated Windows
management call during ``import sqlalchemy``. A gate that hangs is a gate people
disable. This one reads text and needs no database, no driver and no config.

The cost of that choice is that the parser has to be right, and the first draft
was not: it read ``down_revision`` with a single-line regex, so every merge
revision whose parents are a tuple spread over several lines lost its parents
and was counted as a base. It reported 43 heads and 18 bases. The heads number
looked alarming but plausible; the bases number is what gave it away, because an
Alembic graph has exactly one base. That is why this script prints bases and
edge counts rather than only the answer it was asked for: the number that
refutes a broken scan is usually not the number you were looking at.

The two readers share that parser exactly. ``read_graph`` takes name and text
pairs and has no idea where they came from, because a divergence report built
on two parsers would invent differences that are really disagreements between
the instruments.

Exit codes: 0 the committed graph is sound, 1 it is broken, 2 it could not be
measured. A check that cannot measure never reports a pass.

Usage::

    python scripts/check_migration_heads.py
    python scripts/check_migration_heads.py --committing backend/alembic/versions/v3311_rebar_schedule.py
    python scripts/check_migration_heads.py --selftest
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import Iterable, NamedTuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSIONS_REL = "backend/alembic/versions"
VERSIONS = os.path.join(REPO_ROOT, *VERSIONS_REL.split("/"))

# A scan over an empty or mostly-missing directory reports "one head" for the
# same reason a test suite with no tests reports success. The tree held 324
# revisions when this was written; anything under this floor means the scan did
# not see the migration tree and must say so rather than pass.
MIN_EXPECTED_REVISIONS = 100

REVISION = re.compile(r"^revision(?::[^=]+)?\s*=\s*[\"']([^\"']+)[\"']", re.M)
# Capture the whole ``down_revision`` assignment, up to the next module-level
# name, so a tuple written over several lines is read in full.
DOWN_REVISION = re.compile(
    r"^down_revision(?::[^=]+)?\s*=\s*(.*?)(?=^[A-Za-z_]\w*\s*[:=]|^def |^class |\Z)",
    re.M | re.S,
)
QUOTED = re.compile(r"[\"']([^\"']+)[\"']")


class Refusal(Exception):
    """The graph could not be read, so nothing may be concluded from this run."""


class Graph(NamedTuple):
    """One revision graph, however it was obtained."""

    revisions: dict[str, str]  # revision id -> file name
    parents: dict[str, list[str]]  # revision id -> parent ids
    unparsed: list[str]  # files carrying no usable revision id

    @property
    def edges(self) -> int:
        return sum(len(p) for p in self.parents.values())

    @property
    def referenced(self) -> set[str]:
        return {p for ps in self.parents.values() for p in ps}

    @property
    def heads(self) -> list[str]:
        """Revisions nobody names as a parent. More than one means a fork."""
        referenced = self.referenced
        return sorted(r for r in self.revisions if r not in referenced)

    @property
    def bases(self) -> list[str]:
        return sorted(r for r, ps in self.parents.items() if not ps)

    @property
    def dangling(self) -> list[str]:
        """Named as a parent by somebody, present nowhere. This is the incident."""
        return sorted(p for p in self.referenced if p not in self.revisions)

    @property
    def summary(self) -> str:
        return (
            f"{len(self.revisions)} revisions, {self.edges} parent edges, "
            f"{len(self.heads)} head(s), {len(self.bases)} base(s)"
        )

    def scan_too_small(self) -> str:
        """Non-empty when the scan plainly did not see the migration tree.

        This is a fact about the SCAN, not about the graph, which is why it is
        not one of the faults below. It lived in ``faults`` once, and the cost
        was silent: every in-memory fixture holds three or four revisions, so
        every fixture tripped the floor, so every self-test assertion of the
        form "this sound graph reports no fault" was true of a graph that was
        reporting one. The assertions that mattered most were the ones the
        floor made vacuous.
        """
        if len(self.revisions) < MIN_EXPECTED_REVISIONS:
            return (
                f"only {len(self.revisions)} revisions were read, expected at least "
                f"{MIN_EXPECTED_REVISIONS}. The scan did not see the migration tree, so its "
                f"answer about heads means nothing."
            )
        return ""

    def faults(self) -> list[str]:
        """Everything wrong with this graph, as printable blocks. Empty means sound.

        Structural only: what the revisions say about each other. Whether the
        scan found the tree at all is :meth:`scan_too_small`.
        """
        out: list[str] = []

        if self.unparsed:
            block = [f"{len(self.unparsed)} file(s) carry no usable revision id:"]
            block += [f"    {name}" for name in self.unparsed]
            out.append("\n".join(block))

        if self.dangling:
            block = [f"{len(self.dangling)} revision(s) named as a parent but not present:"]
            for revision in self.dangling:
                named_by = sorted(r for r, ps in self.parents.items() if revision in ps)
                block.append(f"    {revision}   (named by {', '.join(named_by)})")
            out.append("\n".join(block))

        if len(self.bases) != 1:
            block = [f"expected exactly one base, found {len(self.bases)}:"]
            block += [f"    {r}   ({self.revisions[r]})" for r in self.bases]
            out.append("\n".join(block))

        if len(self.heads) != 1:
            block = [f"expected exactly one head, found {len(self.heads)}:"]
            block += [f"    {r}   ({self.revisions[r]})" for r in self.heads]
            out.append("\n".join(block))

        return out


class Divergence(NamedTuple):
    """What the disk holds that the commit does not, and the other way round."""

    only_disk: list[str]
    only_commit: list[str]
    reparented: list[tuple[str, list[str], list[str]]]

    @property
    def real(self) -> bool:
        return bool(self.only_disk or self.only_commit or self.reparented)


def read_graph(entries: Iterable[tuple[str, str]]) -> Graph:
    """Build the graph from file name and file text pairs, whatever produced them."""
    revisions: dict[str, str] = {}
    parents: dict[str, list[str]] = {}
    unparsed: list[str] = []

    for name, text in sorted(entries):
        if not name.endswith(".py") or name.startswith("__"):
            continue
        found = REVISION.search(text)
        if found is None:
            unparsed.append(name)
            continue
        revision = found.group(1)
        if revision in revisions:
            # Two files claiming one id is its own defect: Alembic would load
            # whichever it walked last and silently drop the other.
            unparsed.append(f"{name} (duplicate id {revision}, also in {revisions[revision]})")
            continue
        revisions[revision] = name
        block = DOWN_REVISION.search(text)
        parents[revision] = QUOTED.findall(block.group(1)) if block else []

    return Graph(revisions, parents, unparsed)


def compare(disk: Graph, commit: Graph) -> Divergence:
    """Every way the two graphs disagree, by revision id and by parentage.

    Parentage is compared as well as membership because the same revision id can
    sit in both trees naming different parents, which is the incident written the
    other way round: an edited ``down_revision`` that closes a fork on disk and
    leaves it open in the commit. A comparison of id sets alone is blind to it and
    would print that the two trees agree.
    """
    only_disk = sorted(r for r in disk.revisions if r not in commit.revisions)
    only_commit = sorted(r for r in commit.revisions if r not in disk.revisions)
    reparented = [
        (r, disk.parents[r], commit.parents[r])
        for r in sorted(set(disk.revisions) & set(commit.revisions))
        if disk.parents[r] != commit.parents[r]
    ]
    return Divergence(only_disk, only_commit, reparented)


def git(*args: str, stdin: bytes = b"") -> tuple[int, bytes]:
    """Run git in the repository root. Bytes throughout, see ``cat_blobs``."""
    try:
        proc = subprocess.run(  # noqa: S603
            ["git", "-C", REPO_ROOT, *args],
            input=stdin,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise Refusal(f"could not run git ({exc}), so this check proved nothing") from exc
    return proc.returncode, proc.stdout


def cat_blobs(shas: list[str]) -> dict[str, bytes]:
    """Fetch every blob in one ``cat-file --batch``, not one process per file.

    Three hundred and forty subprocesses is a second and a half on Windows and
    this runs before a commit. Bytes, deliberately: the batch header states a
    byte length and text mode would translate CRLF underneath it, so the reader
    would lose its place partway down the stream and the tail of the graph would
    silently disappear.
    """
    if not shas:
        return {}
    code, out = git(
        "cat-file",
        "--batch",
        stdin=("\n".join(sorted(set(shas))) + "\n").encode("ascii"),
    )
    if code != 0:
        raise Refusal("git cat-file could not read the indexed blobs, so this check proved nothing")

    blobs: dict[str, bytes] = {}
    pos = 0
    while pos < len(out):
        end = out.find(b"\n", pos)
        if end < 0:
            break
        header = out[pos:end].split(b" ")
        pos = end + 1
        if len(header) < 3:
            # "<sha> missing", which cannot happen for an index entry, but a
            # reader that guesses past a header it did not understand would
            # report a truncated graph as a real one.
            raise Refusal(f"git cat-file did not return an object for {header[0].decode('ascii', 'replace')}")
        size = int(header[2])
        blobs[header[0].decode("ascii")] = out[pos : pos + size]
        pos += size + 1  # the batch writes a newline after each object
    return blobs


def disk_entries() -> list[tuple[str, str]]:
    """The revision files as they sit in this working tree, untracked ones included."""
    if not os.path.isdir(VERSIONS):
        raise Refusal(f"no versions directory at {VERSIONS}")
    entries: list[tuple[str, str]] = []
    for name in sorted(os.listdir(VERSIONS)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(VERSIONS, name), encoding="utf-8", errors="replace") as fh:
            entries.append((name, fh.read()))
    return entries


def index_entries() -> dict[str, str]:
    """The revision files as the next commit would carry them: HEAD plus what is staged."""
    code, _ = git("rev-parse", "--verify", "HEAD^{commit}")
    if code != 0:
        raise Refusal(
            "could not read HEAD (not a git repository, or a repository with no commits), so this check proved nothing"
        )

    code, out = git("ls-files", "--stage", "-z", "--", VERSIONS_REL)
    if code != 0:
        raise Refusal(f"git ls-files could not read the index under {VERSIONS_REL}, so this check proved nothing")

    shas: dict[str, str] = {}
    for record in out.split(b"\0"):
        if not record:
            continue
        meta, _, path = record.partition(b"\t")
        fields = meta.split(b" ")
        if len(fields) < 3:
            raise Refusal(f"could not parse an index entry ({meta!r}), so this check proved nothing")
        stage = fields[2].decode("ascii")
        name = os.path.basename(path.decode("utf-8", "replace"))
        if stage != "0":
            # Stages 1, 2 and 3 are the three sides of an unresolved merge. The
            # index is not one tree in that state and picking a side would be
            # inventing an answer.
            raise Refusal(
                f"the index holds unmerged entries under {VERSIONS_REL} ({name} at stage {stage}), "
                "so there is no single tree to check and this run proved nothing. "
                "Resolve the merge first."
            )
        if name.endswith(".py"):
            shas[name] = fields[1].decode("ascii")

    if not shas:
        # "found nothing" and "did not look" must not print the same thing.
        raise Refusal(f"the index carries no python files under {VERSIONS_REL}, so this check proved nothing")

    blobs = cat_blobs(list(shas.values()))
    return {name: blobs[sha].decode("utf-8", "replace") for name, sha in shas.items()}


def overlay_working_tree(entries: dict[str, str], paths: list[str]) -> dict[str, str]:
    """Lay the working-tree content of the named paths over the index base.

    This models ``git commit --only -- <paths>`` exactly, which is how work goes
    in here: HEAD's tree with those paths replaced by what is on disk. A named
    path that no longer exists is a deletion and leaves the graph. Paths outside
    the versions directory are ignored rather than refused, so a hook may pass
    the whole changed set without filtering it first.
    """
    merged = dict(entries)
    for raw in paths:
        full = os.path.abspath(os.path.join(REPO_ROOT, raw))
        if os.path.dirname(full) != VERSIONS or not full.endswith(".py"):
            continue
        name = os.path.basename(full)
        if not os.path.exists(full):
            merged.pop(name, None)
            continue
        with open(full, encoding="utf-8", errors="replace") as fh:
            merged[name] = fh.read()
    return merged


def print_faults(label: str, graph: Graph, prefix: str) -> None:
    for fault in graph.faults():
        print(f"{prefix}: {label}: {fault}")


def report_divergence(disk: Graph, commit: Graph, div: Divergence) -> None:
    """Say plainly that the two trees are different and which is which.

    Not averaged and no winner picked silently. The whole reason this check was
    rewritten is that one of these two answers was reported as the answer.
    """
    print("DIVERGENCE: the disk and the commit do not hold the same revision graph.")
    print(f"  on disk ({VERSIONS_REL}/): {disk.summary}")
    print(f"  in the commit:              {commit.summary}")

    if div.only_disk:
        print(f"\n  {len(div.only_disk)} revision(s) on disk that the commit does not carry:")
        for r in div.only_disk:
            name = disk.revisions[r]
            tracked = "" if name in commit.revisions.values() else ", untracked"
            print(f"    {r}   ({name}{tracked})")
        print("  Anything chaining onto one of those names a parent that ships nowhere.")

    if div.only_commit:
        print(f"\n  {len(div.only_commit)} revision(s) in the commit that the disk does not carry:")
        for r in div.only_commit:
            print(f"    {r}   ({commit.revisions[r]})")
        print("  Deleted or renamed here and not yet committed, or the deletion is staged.")

    if div.reparented:
        print(f"\n  {len(div.reparented)} revision(s) present in both, chained differently:")
        for r, on_disk, in_commit in div.reparented:
            print(f"    {r}   disk parent {on_disk or ['(base)']}, commit parent {in_commit or ['(base)']}")
        print("  The edit that moved it is on disk and not in the commit.")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in args:
        self_test()
        return 0

    committing: list[str] = []
    if "--committing" in args:
        committing = [a for a in args[args.index("--committing") + 1 :] if a != "--"]

    self_test()

    # The disk answer is still worth having: a fork here is a fork the author is
    # about to commit. It is obtained first and separately so that a disk that
    # cannot be read does not stop the question that actually decides the run.
    disk: Graph | None = None
    disk_refusal = ""
    try:
        disk = read_graph(disk_entries())
    except Refusal as exc:
        disk_refusal = str(exc)

    try:
        entries = index_entries()
        if committing:
            entries = overlay_working_tree(entries, committing)
        commit = read_graph(entries.items())
    except Refusal as exc:
        print(f"ERROR: {exc}")
        print("The graph that ships was not measured, so this run is not a pass. Nothing was concluded.")
        return 2

    base = "HEAD plus the index"
    if committing:
        base += f", with the working-tree content of {len(committing)} named path(s) laid over it"

    if disk is None:
        print(f"migration graph in the commit ({base}): {commit.summary}")
        print(f"NOTE: the disk graph was not read ({disk_refusal}), so the two were not compared.")
    else:
        div = compare(disk, commit)
        if not div.real:
            print(f"migration graph: {commit.summary} (disk and commit agree)")
        else:
            report_divergence(disk, commit, div)
            print(f"\nThe commit is the graph that ships ({base}), and it decides this run.")

    too_small = commit.scan_too_small()
    if too_small:
        print(f"ERROR: {too_small}")
        print("The graph that ships was not measured, so this run is not a pass. Nothing was concluded.")
        return 2

    commit_faults = commit.faults()
    print_faults("the committed graph", commit, "ERROR")

    if disk is not None:
        disk_faults = disk.faults()
        if disk_faults and not commit_faults:
            # The everyday shape of this: an uncommitted revision forks against a
            # committed one. Say in the same breath that HEAD is clean, because
            # otherwise the obvious repair is to edit a revision file that is
            # already correct and already pushed.
            print(
                "\nWARNING: the graph on disk is broken while the committed graph is sound, "
                "so the fault is in uncommitted files and ships nowhere as things stand. "
                "Do not re-chain a revision that is already in HEAD to close it."
            )
            print_faults("the working tree", disk, "WARNING")
        elif disk_faults:
            print_faults("the working tree", disk, "WARNING")

    if commit_faults:
        if len(commit.heads) != 1:
            print(
                "\nRe-chain the newer revision onto the older one so the line stays linear. "
                "Do not add a merge revision to close a fork that has not shipped yet: it is "
                "permanent, and it records a branch nobody ever ran."
            )
        if commit.dangling:
            print(
                "\nA parent that the commit does not carry is usually a revision file still "
                "sitting untracked in a working tree. Commit the parent in the same commit as "
                "the child, or chain the child onto a revision that is already in HEAD. "
                "A clone of this commit cannot run `alembic upgrade head` at all."
            )
        return 1

    print(f"committed graph OK: single head {commit.heads[0]}   ({commit.revisions[commit.heads[0]]})")
    return 0


def _fixture(revision: str, down: str | None = None, parents: list[str] | None = None) -> str:
    """One revision file, written the way the real ones are."""
    if parents is not None:
        joined = ",\n    ".join(f'"{p}"' for p in parents)
        value = f"(\n    {joined},\n)"
    else:
        value = "None" if down is None else f'"{down}"'
    return (
        f'"""fixture revision."""\n\nfrom typing import Sequence, Union\n\n'
        f'revision: str = "{revision}"\n'
        f"down_revision: Union[str, Sequence[str], None] = {value}\n\n\n"
        f"def upgrade() -> None:\n    pass\n"
    )


def _fail(message: str) -> None:
    print(f"SELF-TEST FAILED: {message}", file=sys.stderr)
    raise SystemExit(2)


def self_test() -> None:
    """Prove the parser and the divergence report before either is trusted on the tree.

    Runs on every invocation, so the CI step exercises the comparison logic even
    though the tree it checks is clean and the two graphs there always agree.
    A guard whose interesting branch only runs on a dirty tree is a guard nobody
    ever sees run.

    Fixtures are built in memory. Nothing is written anywhere, which matters in a
    shared working tree where a stray file under the versions directory would be
    read as a revision by every other session.
    """
    # The parser, including the multi-line tuple that the first draft lost.
    line = {"a.py": _fixture("a"), "b.py": _fixture("b", "a")}
    merge = dict(line, m=_fixture("m", parents=["a", "b"]))
    merge["m.py"] = merge.pop("m")
    graph = read_graph(merge.items())
    if graph.parents.get("m") != ["a", "b"]:
        _fail(f"a down_revision tuple over several lines read as {graph.parents.get('m')}, not ['a', 'b']")
    if graph.bases != ["a"]:
        _fail(f"expected one base, the parser found {graph.bases}")

    if read_graph({"junk.py": "print('no revision here')"}.items()).unparsed != ["junk.py"]:
        _fail("a file with no revision id was not reported as unparsed")
    twins = read_graph({"x.py": _fixture("dup"), "y.py": _fixture("dup", "a")}.items())
    if len(twins.unparsed) != 1 or "duplicate id dup" not in twins.unparsed[0]:
        _fail("two files claiming one revision id were not reported")

    # The everyday case, and the one that decides whether this check survives
    # contact with people: a new revision that chains onto the current head. It
    # is in both trees, so the two agree and the run is clean.
    everyday = dict(line, **{"c.py": _fixture("c", "b")})
    if compare(read_graph(everyday.items()), read_graph(everyday.items())).real:
        _fail("a new revision present in both trees was reported as a divergence")
    if read_graph(everyday.items()).faults():
        _fail("a revision chained onto the current head was reported as a fault")

    # A genuine fork, both sides committed. Nothing to do with the disk, and it
    # has to keep failing.
    fork = read_graph(dict(line, **{"c.py": _fixture("c", "a")}).items())
    if fork.heads != ["b", "c"]:
        _fail(f"a fork of two committed heads read as heads {fork.heads}")
    if not fork.faults():
        _fail("a fork of two committed heads was reported as sound")

    # The incident itself. The parent is on disk and not in the commit, so the
    # disk graph is a clean line and the committed graph has a parent that does
    # not exist and therefore two heads. This is the branch the whole rewrite
    # exists for, so it is asserted from both sides rather than as one verdict.
    on_disk = dict(line, **{"c.py": _fixture("c", "b"), "d.py": _fixture("d", "c")})
    in_commit = dict(line, **{"d.py": _fixture("d", "c")})  # "c" never committed
    disk_graph, commit_graph = (
        read_graph(on_disk.items()),
        read_graph(in_commit.items()),
    )

    if disk_graph.faults():
        _fail("the reconstructed incident should look clean on disk, and did not")
    if commit_graph.dangling != ["c"]:
        _fail(f"the committed graph should name 'c' as a missing parent, it named {commit_graph.dangling}")
    if commit_graph.heads != ["b", "d"]:
        _fail(f"the committed graph should hold two heads, it holds {commit_graph.heads}")
    div = compare(disk_graph, commit_graph)
    if div.only_disk != ["c"] or div.only_commit:
        _fail(f"the divergence should be 'c' on disk only, it was {div.only_disk} and {div.only_commit}")

    # And the mirror, where a check comparing revision ids alone would print that
    # the two trees agree: the same revision, re-chained on disk and not in the
    # commit. Disk clean, commit forked, identical id sets.
    edited = read_graph(dict(line, **{"c.py": _fixture("c", "b")}).items())
    stale = read_graph(dict(line, **{"c.py": _fixture("c", "a")}).items())
    edit_div = compare(edited, stale)
    if edit_div.only_disk or edit_div.only_commit:
        _fail("the re-chained case should differ only in parentage, and the id sets differed")
    if edit_div.reparented != [("c", ["b"], ["a"])]:
        _fail(f"a revision re-chained on disk only was not reported, compare returned {edit_div.reparented}")
    if edited.faults() or not stale.faults():
        _fail("the re-chained case should be clean on disk and forked in the commit")

    print(
        "SELF-TEST OK: reads multi-line parents, refuses duplicate and idless files,\n"
        "              passes a new revision chained onto the head, fails a fork of two\n"
        "              committed heads, and reports the disk-versus-commit divergence\n"
        "              both by missing revision and by changed parentage.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    sys.exit(main())
