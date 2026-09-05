"""Backend ignore rules must live where the wheel build actually reads them.

Written against a leak that shipped. A clean-room build produced a wheel
carrying ``app/scripts/demo_seed_issues.md``, an internal defect log with
BLOCKER and BUG entries, two ``seed_demo_v2*.py`` scripts, and 495 entries of a
stale ``app/_frontend_dist_prev/`` bundle that nothing in the codebase reads.
All four were listed in the repo-root .gitignore and all four were packaged
anyway.

The mechanism is a mismatch of roots. hatchling takes the project root from
pyproject.toml, which for this package is ``backend/``, and its VCS exclusion
walks up from there for the nearest .gitignore
(``locate_file(self.root, ".gitignore", boundary=".git")`` in
hatchling/builders/config.py). With no file in ``backend/`` it reached the
repo-root one, then matched every pattern in it against paths relative to
``backend/``. A line reading ``backend/app/scripts/demo_seed_issues.md`` was
therefore looked for at ``backend/backend/app/scripts/demo_seed_issues.md``.
All 43 repo-root lines beginning ``backend/`` were inert this way. They were
not decorative: git honours them, so the files were correctly untracked and
correctly invisible in ``git status``, which is exactly why nobody noticed the
build disagreed.

The fix was to move those lines into ``backend/.gitignore`` anchored with a
leading slash, which both tools then read the same way. This test guards the
shape of that fix rather than the four filenames, because naming the filenames
is what the hygiene denylist already does and it is what let the class through.

Two things are deliberately NOT asserted here. This does not build a wheel:
that takes minutes and needs a built frontend, and the property under test is a
property of the ignore files. And it does not assert that every backend ignore
lives in backend/.gitignore, only that none is written repo-root-anchored in a
form that silently does nothing.
"""

from __future__ import annotations

from pathlib import Path

import pathspec

ROOT = Path(__file__).resolve().parents[3]
ROOT_GITIGNORE = ROOT / ".gitignore"
BACKEND_GITIGNORE = ROOT / "backend" / ".gitignore"


def _rules(path: Path) -> list[tuple[int, str]]:
    """Numbered, non-blank, non-comment lines of a .gitignore."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [(n, ln) for n, ln in enumerate(lines, 1) if ln.strip() and not ln.lstrip().startswith("#")]


def test_backend_gitignore_exists() -> None:
    """Without this file hatchling walks up and reads the repo-root one instead."""
    assert BACKEND_GITIGNORE.is_file(), (
        f"{BACKEND_GITIGNORE} is missing. hatchling resolves .gitignore by walking up "
        "from the project root, so deleting this file sends it to the repo-root one, "
        "whose backend/... lines cannot match anything relative to backend/."
    )


def test_root_gitignore_has_no_backend_anchored_rules() -> None:
    """A repo-root rule written as ``backend/...`` is inert for the wheel build."""
    offenders = [(n, ln) for n, ln in _rules(ROOT_GITIGNORE) if ln.lstrip("!").startswith("backend/")]
    assert not offenders, (
        "These repo-root .gitignore lines are anchored at backend/ and do nothing for "
        "the wheel build, because hatchling matches repo-root patterns against paths "
        "relative to backend/ and so looks for them at backend/backend/...:\n"
        + "\n".join(f"  .gitignore:{n}: {ln}" for n, ln in offenders)
        + "\nMove each one to backend/.gitignore, dropping the backend/ prefix and "
        "keeping a leading slash so it stays anchored to that directory."
    )


def test_backend_gitignore_rules_are_anchored() -> None:
    """A rule without a leading slash matches at every depth, which is wider than intended.

    ``backend/_*.py`` at the repo root meant only files directly in backend/.
    Written in backend/.gitignore as ``_*.py`` it would match at any depth and
    start ignoring real source such as app/core/_internal helpers, so the slash
    is what keeps the move faithful rather than merely close.
    """
    unanchored = [(n, ln) for n, ln in _rules(BACKEND_GITIGNORE) if not ln.lstrip("!").startswith("/")]
    assert not unanchored, (
        "These backend/.gitignore rules are not anchored with a leading slash, so they "
        "match at every depth beneath backend/ rather than only where the repo-root "
        "form did:\n" + "\n".join(f"  backend/.gitignore:{n}: {ln}" for n, ln in unanchored)
    )


def test_the_four_leaked_paths_are_ignored_by_the_backend_rules() -> None:
    """The specific files that shipped, checked against backend/.gitignore alone.

    Read the backend file on its own rather than asking git, because git would
    answer from every .gitignore in the hierarchy and would have said "ignored"
    throughout the whole period the wheel was leaking these.
    """
    spec = pathspec.GitIgnoreSpec.from_lines(BACKEND_GITIGNORE.read_text(encoding="utf-8").splitlines())
    for leaked in (
        "app/scripts/demo_seed_issues.md",
        "app/scripts/seed_demo_v2.py",
        "app/scripts/seed_demo_v2_resume.py",
        "app/_frontend_dist_prev/index.html",
    ):
        assert spec.match_file(leaked), (
            f"{leaked} is not excluded by backend/.gitignore, so the wheel build would "
            "package it. This exact file reached a built wheel once."
        )

    # The twelve demo site photos are shipped seed assets, negated out of the
    # repo-root *.jpg rule. They must stay includable.
    assert not spec.match_file("app/scripts/flagship_assets/site_photos/01.jpg")
    # Near-misses: real source that the anchored rules must not touch.
    assert not spec.match_file("app/core/_init_helper.py")
    assert not spec.match_file("app/scripts/seed_demo.py")
