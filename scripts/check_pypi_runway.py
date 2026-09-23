"""Run the publish workflow's size gate here, before the tag exists.

PyPI caps a project two ways. Each file must be under 100 MiB, and the total
stored size of every version must be under 10 GiB. The second one stopped a
release once: 17.0.1 was tagged, built clean, passed every check and was
refused at upload with ``400 Project size too large``, which leaves a public
tag with no wheel on it and no way to take the tag back.

``pypi-publish.yml`` measures both, and measures them honestly, but it runs on
a tag. By the time it speaks the expensive part has already happened. The
remedy is outside the repository as well: either old releases get deleted from
PyPI, which is irreversible and breaks anyone pinned to them, or PyPI is asked
to raise the project limit, which is a support request answered by a volunteer
on their own schedule. Both want days.

So this runs the same check before tagging. It does not reimplement the
arithmetic, it extracts the step's script out of the workflow and executes it
with the wheel size stubbed, because a second copy of the numbers would drift
from the first and the drift would be invisible until a release failed. The
PyPI query inside is real.

    python scripts/check_pypi_runway.py           # assume a wheel the size of the last one
    python scripts/check_pypi_runway.py 85 40     # ask about specific sizes, in MiB

Exit code is 1 if any size would be refused outright, 0 otherwise, warnings
included. A warning means the release still publishes; it means start the
conversation today rather than on the release that fails.

One thing to know when reading the cadence it prints: the workflow adds one to
the release count for the wheel being published at that moment, which is not on
the index yet when it runs on a tag. Run between tags, that wheel is already
there and gets counted twice, so the rate reads about one release high over the
shortest window. That errs toward warning early, which is the safe direction.
"""

from __future__ import annotations

import ast
import glob
import json
import os
import runpy
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "pypi-publish.yml"
STEP = "Check the wheel fits, per file and against the project total"
HEREDOC = "python - <<'PY'"
PROJECT = "openconstructionerp"


def extract_gate() -> str:
    """Pull the gate's Python out of the workflow YAML and check it parses.

    Located by the step name rather than by position, so reordering the job
    does not silently start running some other step's script.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    if STEP not in text:
        sys.exit(f"ERROR: no step named {STEP!r} in {WORKFLOW}. It was renamed or removed; fix this script.")
    start = text.index(HEREDOC, text.index(STEP))
    end = text.index("\n          PY\n", start)
    body = text[start + len(HEREDOC) : end]
    source = "\n".join(line[10:] if line.startswith(" " * 10) else line for line in body.split("\n")).strip("\n")
    ast.parse(source)  # a YAML edit that breaks the indentation should fail here, not on a tag
    return source


def last_wheel_mib() -> float:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{PROJECT}/json", timeout=60) as response:
        meta = json.load(response)
    wheels = [f for files in meta["releases"].values() for f in files if f["filename"].endswith(".whl")]
    newest = max(wheels, key=lambda f: f["upload_time_iso_8601"])
    return newest["size"] / 1048576


def main() -> int:
    sizes = [float(a) for a in sys.argv[1:]]
    if not sizes:
        sizes = [last_wheel_mib()]
        print(f"no size given, using the last published wheel: {sizes[0]:.1f} MiB\n")

    source = extract_gate()
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "gate.py"
        script.write_text(source, encoding="utf-8")
        real_glob, real_getsize = glob.glob, os.path.getsize
        failed = False
        try:
            for mib in sizes:
                size = int(mib * 1048576)
                glob.glob = lambda _pattern: ["dist/openconstructionerp-0.0.0-py3-none-any.whl"]
                os.path.getsize = lambda _path, _s=size: _s
                print(f"===== a wheel of {mib:.1f} MiB =====")
                try:
                    runpy.run_path(str(script), run_name="__main__")
                except SystemExit as exc:
                    if exc.code:
                        print(f"REFUSED: {exc.code}")
                        failed = True
                print()
        finally:
            glob.glob, os.path.getsize = real_glob, real_getsize
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
