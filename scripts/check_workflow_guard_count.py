"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Check that the guard count in the repo-hygiene header still matches the file.

The header of `.github/workflows/repo-hygiene.yml` opens by saying how many
guards the file runs. That number was written by hand on 2026-08-24 and nobody
recounted it: it still read twenty-one on 2026-08-29, when the file had grown
past fifty. A count nobody recounts does not merely go stale, it dates the file
falsely - a reader who trusts it believes the gate is a third of its real size
and stops looking. The same header carried a second hand-written count ("two
ten-step jobs") that went wrong in the same week for the same reason, which is
why this exists rather than a third correction.

What counts as a guard: a named step (`- name:`) that is not a tooling install.
That definition is not a preference. It is the rule that reproduces BOTH counts
the header carried at 95a136ed0, the commit that wrote them - twenty-one guards
spread over jobs of ten, ten and one steps, with no install steps in the file at
the time. A rule that cannot reproduce the number it is replacing would be a
second guess wearing the clothes of a measurement.

Install steps are excluded because they set up tooling and cannot refuse
anything: a missing compiler fails the job as an error, not as a verdict about
the tree. Everything else - Check, Prove, Report, Scan, Lint - fails the job on
a finding, so all of it guards.

Exit codes: 0 when the line and the file agree, 1 when they have drifted, 2 when
the guard could not prove it still refuses.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "repo-hygiene.yml"

# The header line this owns. Digits, not an English number word: the word form
# is what let the old count survive five days of edits, because nothing could
# read it without a spelling table and so nothing tried.
DECLARED = re.compile(r"^#\s*Guards:\s*(\d+)\b")

STEP_NAME = re.compile(r"^\s*-\s+name:\s*(.+?)\s*$")
JOB_NAME = re.compile(r"^(\s*)([A-Za-z0-9_-]+):\s*$")
INSTALL_STEP = re.compile(r"^Install\b")


def step_names(text: str) -> list[str]:
    """Return every step name in a workflow, in file order.

    A job's own `name:` has no leading dash, so it cannot be confused with a
    step; `with:` inputs called `name` would be `name: x` without a dash too.
    """
    return [m.group(1) for line in text.splitlines() if (m := STEP_NAME.match(line))]


def split_guards(names: list[str]) -> tuple[list[str], list[str]]:
    """Split step names into (guards, tooling installs)."""
    installs = [n for n in names if INSTALL_STEP.match(n)]
    guards = [n for n in names if not INSTALL_STEP.match(n)]
    return guards, installs


def job_names(text: str) -> list[str]:
    """Return the job keys under `jobs:`, so the header's "three jobs" is checked too."""
    jobs: list[str] = []
    in_jobs = False
    for line in text.splitlines():
        if line.rstrip() == "jobs:":
            in_jobs = True
            continue
        if in_jobs:
            if line and not line[0].isspace():
                break
            m = JOB_NAME.match(line)
            if m and len(m.group(1)) == 2:
                jobs.append(m.group(2))
    return jobs


def declared_count(text: str) -> int | None:
    """Return the number the header declares, or None when the line is gone."""
    for line in text.splitlines():
        m = DECLARED.match(line)
        if m:
            return int(m.group(1))
    return None


SELF_TEST_FIXTURE = """\
# Repo hygiene gate.
#
# Guards: 2. They run on every push, grouped into two jobs.
name: Repo hygiene
jobs:
  structural:
    name: Whole-tree structural guards
    steps:
      - uses: actions/checkout@v7
      - name: Install the ruff the backend pins
        run: true
      - name: Check nothing internal reached the tree
        run: true
  i18n:
    name: Locale and i18n guards
    steps:
      - name: Prove the leak guard can fail
        run: true
"""


def self_test() -> int:
    """Prove the counter can refuse, and that it can tell a guard from an install."""
    names = step_names(SELF_TEST_FIXTURE)
    if names != [
        "Install the ruff the backend pins",
        "Check nothing internal reached the tree",
        "Prove the leak guard can fail",
    ]:
        print(f"SELF-TEST FAIL: step names came back as {names!r}.")
        print("                The step pattern no longer reads a workflow the way this file is written.")
        return 1

    guards, installs = split_guards(names)
    if len(guards) != 2 or len(installs) != 1:
        print(f"SELF-TEST FAIL: split {len(guards)} guards / {len(installs)} installs, expected 2 / 1.")
        return 1

    if job_names(SELF_TEST_FIXTURE) != ["structural", "i18n"]:
        print(f"SELF-TEST FAIL: jobs came back as {job_names(SELF_TEST_FIXTURE)!r}, expected structural and i18n.")
        print("                A job key with a digit in it is the one that gets missed.")
        return 1

    if declared_count(SELF_TEST_FIXTURE) != 2:
        print("SELF-TEST FAIL: the declared count did not parse out of the header.")
        return 1

    # The refusal itself. A counter that only ever agrees is indistinguishable
    # from one that reads nothing, so make it disagree on purpose.
    drifted = SELF_TEST_FIXTURE.replace("# Guards: 2.", "# Guards: 21.")
    if declared_count(drifted) == len(guards):
        print("SELF-TEST FAIL: a header claiming 21 guards over a 2-guard file was accepted.")
        print("                The guard cannot refuse, so its verdict means nothing.")
        return 1

    missing = SELF_TEST_FIXTURE.replace("# Guards: 2. ", "# ")
    if declared_count(missing) is not None:
        print("SELF-TEST FAIL: a header with no count line still parsed a number.")
        return 1

    print("SELF-TEST OK: reads step names, separates tooling installs from guards,")
    print("              finds a job key containing a digit, and refuses a stale count.")
    return 0


def _rel(path: Path) -> str:
    """Path for printing, relative to the repo when it lives inside it."""
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def report(path: Path) -> int:
    """Compare the header's count with the file and print the population beside the verdict."""
    if not path.is_file():
        print(f"FAIL: {path} does not exist, so there is nothing to count.")
        return 2

    text = path.read_text(encoding="utf-8")
    names = step_names(text)
    guards, installs = split_guards(names)
    jobs = job_names(text)
    declared = declared_count(text)

    print(_rel(path))
    print(f"  named steps:      {len(names)}")
    print(f"  tooling installs: {len(installs)}  ({', '.join(installs) if installs else 'none'})")
    print(f"  guards:           {len(guards)}")
    print(f"  jobs:             {len(jobs)}  ({', '.join(jobs)})")

    if declared is None:
        print()
        print("FAIL: the header no longer carries a `# Guards: <n>` line.")
        print("      Either restore it or delete this guard; a count with no reader goes stale silently,")
        print("      which is the failure this exists to stop.")
        return 1

    print(f"  header declares:  {declared}")

    if declared != len(guards):
        print()
        print(f"FAIL: the header says {declared} guards, the file has {len(guards)}.")
        print(f"      Set the `# Guards:` line in {_rel(path)} to {len(guards)}.")
        print("      A guard is a named step that is not a tooling install; see this script's docstring")
        print("      for why that is the rule and not a matter of taste.")
        return 1

    print()
    print(f"OK: header and file agree on {len(guards)} guards across {len(jobs)} jobs.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Check the repo-hygiene header's guard count against the file.")
    ap.add_argument("--self-test", action="store_true", help="prove the guard can fail, then exit")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    # The self test runs before every real count, not only on demand. This one
    # is a pattern match over a text file: tighten the pattern by one character
    # and it reads zero steps, and zero steps against a header that no longer
    # parses would report a clean run in a confident voice.
    if self_test() != 0:
        print("FAIL: the guard could not prove it still refuses, so its verdict means nothing.")
        return 2
    print()
    return report(WORKFLOW)


if __name__ == "__main__":
    sys.exit(main())
