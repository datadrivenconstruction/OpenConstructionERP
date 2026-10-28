"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The commit-subject guard rejects shell artefacts and nothing else.

Twelve published commits open with ``@`` before their real subject, one of them
the v14.6.0 release commit, because a PowerShell here-string opener was written
on the same line as ``git commit -m``. scripts/check_commit_subject.py exists to
stop the thirteenth.

Two things are worth testing and they pull in opposite directions. The guard has
to catch every shape the artefact takes, and it has to stay quiet on the ordinary
subjects that merely resemble one, because a guard that cries wolf on ``bump
@types/node`` gets disabled and then catches nothing at all.

The allowlist gets its own test. A list of exempt commits is only honest while
each entry still names a commit that really does carry the defect; once an entry
rots, the list is quietly suppressing something nobody has looked at.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "check_commit_subject.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("check_commit_subject", _SCRIPT)
    assert spec and spec.loader, f"cannot load {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


# Every shape the artefact has taken, plus the ones the shell can produce next.
REJECTED = [
    "@'",
    '@"',
    "@ fix(cases): give every module chip a translated name, not an English one",
    "@ chore(release): 14.6.0, and make the sidecar certain",
    "'@",
    '"@',
    "<<EOF",
    "EOF",
    "PY",
    "chore(ci): drop the trailing continuation `",
]

# Subjects that look like the artefact to a careless rule and are perfectly fine.
ACCEPTED = [
    "chore(release): 14.7.0",
    "chore(deps): bump @types/node to 22",
    "fix(cli): stop the flag breaking `--help`",
    "fix(email): treat @ in a display name as literal",
    "feat(einvoice): read a ZUGFeRD attachment out of a PDF",
    "docs: explain why EOF matters to the importer",
]


@pytest.mark.parametrize("subject", REJECTED)
def test_shell_artefacts_are_rejected(subject: str) -> None:
    assert guard._artefact_reasons(subject), f"guard accepted a shell artefact: {subject!r}"


@pytest.mark.parametrize("subject", ACCEPTED)
def test_ordinary_subjects_are_accepted(subject: str) -> None:
    assert not guard._artefact_reasons(subject), f"guard rejected an ordinary subject: {subject!r}"


def test_the_subject_is_the_first_non_empty_line() -> None:
    """git shows the first line, so that is the line the guard has to read."""
    assert guard._subject_of("\n\n@ fix(x): real subject\n\nbody\n") == "@ fix(x): real subject"
    assert guard._subject_of("") == ""


def test_a_long_dash_is_caught_but_only_in_a_message_being_written() -> None:
    assert guard._dash_reasons("fix(ui): tidy the header — it wrapped")
    assert guard._dash_reasons("fix(ui): a range of 3 – 5 rows")
    assert not guard._dash_reasons("fix(ui): tidy the header - it wrapped")
    # The artefact rule is the one that runs over history; the dash rule is not,
    # so a dash must never make a historical subject look like a shell fragment.
    assert not guard._artefact_reasons("fix(ui): tidy the header — it wrapped")


def test_a_closing_code_span_is_not_a_continuation_backtick() -> None:
    """Parity, not position: what opened a backtick is allowed to close it."""
    assert guard._has_dangling_backtick("chore: drop the continuation `")
    assert not guard._has_dangling_backtick("fix(cli): the flag `--help` works")
    assert not guard._has_dangling_backtick("fix(cli): mention `--help`")


@pytest.mark.parametrize("sha", sorted(guard._PUBLISHED_OFFENDERS))
def test_every_allowlisted_commit_still_exists_and_still_offends(sha: str) -> None:
    """An exemption that no longer names a real defect is suppression, not a record."""
    result = subprocess.run(
        ["git", "log", "-1", "--format=%s", sha],
        cwd=_REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        pytest.skip(f"commit {sha[:12]} is unreachable in this checkout (shallow clone?)")
    subject = result.stdout.strip()
    assert guard._artefact_reasons(subject), (
        f"{sha[:12]} is allowlisted but its subject is clean: {subject!r}. "
        "Remove it from _PUBLISHED_OFFENDERS rather than leaving a dead exemption."
    )


def test_history_is_clean_once_the_published_twelve_are_excused() -> None:
    """The guard must be green on the tree as it stands, or nobody will run it."""
    result = subprocess.run(
        ["python", str(_SCRIPT)],
        cwd=_REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if "not a git repository" in (result.stderr or "").lower():
        pytest.skip("not a git checkout")
    assert result.returncode == 0, f"guard is red on current history:\n{result.stderr}"
