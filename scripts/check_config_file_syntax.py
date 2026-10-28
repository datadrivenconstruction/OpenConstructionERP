#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Parse every tracked YAML and JSON file, as a category rather than by name.

These files are already parsed in a number of places, and saying so precisely
matters, because the first thing said about this gap was that nothing checks
them at all and that was wrong. Workflow YAML is loaded by five unit tests:
test_ci_lane_coverage.py, test_workflow_expressions_are_legal_where_they_stand.py,
test_release_signing_trigger.py, test_desktop_windows_packaging.py and
test_pre_commit_declares_what_the_lanes_run.py, which also loads
.pre-commit-config.yaml. On the JSON side 25 scripts and 80 files under
backend/tests call a JSON loader over the trees they own, locales and
capabilities and basemap styles among them.

What none of those do is cover the CATEGORY. Every one of them is addressed at
a named file or at one directory glob, so a new file of either kind, written
where no existing reader looks, is parsed by nothing at all. It can be
malformed and every lane stays green. That is the hole this closes and the only
one it closes.

For YAML the consequence is worse than a late failure. A workflow whose YAML
will not parse is not run by GitHub: no job, no log, no annotation on the
commit, no red. What arrives is silence, and we have already written down that
silence from a lane is indistinguishable from health. Two lanes here are read
as authoritative verdicts, so a broken workflow file would turn one of them
into a verdict nobody notices is missing.

Run from the repository root. The file list comes from git rather than from a
tree walk, so it sees what a checkout sees and ignores untracked scratch files,
which are the working tree's business and not the lane's.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

YAML_SUFFIXES = (".yml", ".yaml")
JSON_SUFFIX = ".json"

# tsconfig files are JSONC by format, comments are legal in them, and three of
# the four open with one. Strict json.loads is simply the wrong instrument
# here, and writing a comment stripper would make this gate's verdict depend on
# the stripper rather than on the file. They already have a stronger reader:
# npm run typecheck:e2e runs tsc -p over tsconfig.e2e.json, tsconfig.e2e-root.json
# and tsconfig.configs.json, tsconfig.json is the default project for the build,
# and TypeScript checks far more of them than syntax. So they are skipped by
# name and counted out loud.
JSONC_PREFIX = "tsconfig"
# tsconfig.locales.json is the fifth: npm run typecheck builds it first with tsc -b.
EXPECTED_JSONC = 5

# Anchored to this file rather than to the caller's working directory. git
# ls-files answers about the directory it is run in, so from backend/ it lists
# backend/ alone and reports zero tsconfig files - which is not a smaller tree,
# it is a different question. The hygiene workflow runs this from the root and
# saw four; CI runs the test from backend/ and saw none.
ROOT = Path(__file__).resolve().parents[1]


def _tracked() -> list[str]:
    """Every tracked YAML and JSON path, from git rather than from a tree walk."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "*.yml", "*.yaml", "*.json"],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    if result.returncode != 0:
        print(f"ERROR: git ls-files failed: {result.stderr.strip()}", file=sys.stderr)
        return []
    return sorted(path for path in result.stdout.split("\0") if path)


def is_jsonc(path: str) -> bool:
    """True for a tsconfig file, which is JSONC and belongs to tsc."""
    return path.endswith(JSON_SUFFIX) and Path(path).name.startswith(JSONC_PREFIX)


def check_paths(paths: list[str]) -> list[tuple[str, str]]:
    """Return (path, message) for every file that will not parse.

    Takes the paths rather than finding them, so a test can hand it a planted
    broken file and see the refusal for itself. Paths from _tracked are relative
    to the repository root, so they are joined to it; an absolute path, which is
    what a planted-file test hands over, survives that join unchanged.
    """
    failures: list[tuple[str, str]] = []
    for path in paths:
        try:
            text = (ROOT / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            failures.append((path, f"{type(exc).__name__}: {exc}"))
            continue
        try:
            if path.endswith(YAML_SUFFIXES):
                list(yaml.safe_load_all(text))
            else:
                json.loads(text)
        except (yaml.YAMLError, ValueError) as exc:
            failures.append((path, " ".join(str(exc).split())[:300]))
    return failures


def main() -> int:
    paths = _tracked()
    if not paths:
        print(
            "ERROR: no tracked YAML or JSON file was found, so this gate proved nothing",
            file=sys.stderr,
        )
        return 1

    jsonc = [path for path in paths if is_jsonc(path)]
    checked = [path for path in paths if not is_jsonc(path)]
    yaml_files = [path for path in checked if path.endswith(YAML_SUFFIXES)]
    json_files = [path for path in checked if path.endswith(JSON_SUFFIX)]

    if len(jsonc) != EXPECTED_JSONC:
        print(
            f"ERROR: {len(jsonc)} {JSONC_PREFIX}*.json file(s) found, {EXPECTED_JSONC} expected:",
            file=sys.stderr,
        )
        for path in jsonc:
            print(f"  {path}", file=sys.stderr)
        print(
            "\nThese are skipped because they are JSONC and tsc reads them. A new one "
            "arriving should be a decision somebody makes, not a silent widening of "
            "the exemption, so update EXPECTED_JSONC once you have checked that tsc "
            "really covers the new file.",
            file=sys.stderr,
        )
        return 1

    failures = check_paths(checked)
    if failures:
        print(
            f"ERROR: {len(failures)} of {len(checked)} tracked config file(s) will not parse:",
            file=sys.stderr,
        )
        for path, message in failures:
            print(f"  {path}: {message}", file=sys.stderr)
        print(
            "\nA malformed JSON file fails wherever something happens to read it, which "
            "may be nowhere. A malformed workflow YAML is worse: GitHub declines to run "
            "the workflow and reports no failure, so the lane goes quiet rather than red.",
            file=sys.stderr,
        )
        return 1

    print(
        f"config syntax OK: {len(yaml_files)} YAML and {len(json_files)} JSON parsed, "
        f"{len(jsonc)} JSONC skipped ({JSONC_PREFIX}*.json, read by tsc in npm run typecheck:e2e)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
