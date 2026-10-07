"""What the Windows desktop build is allowed to ship, and how it installs.

Two decisions live here, both of which are one line of configuration and both of
which fail silently when reverted. A silent packaging regression is not a
hypothetical in this project: v15.0.0 shipped a desktop bundle with no
translation catalogue, the gate that should have caught it was green, and the
application did not start for a single user.

The tests read the real files rather than a copy, and they print what they
counted. A gate that prints only its verdict cannot be distinguished from a gate
that examined nothing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
TAURI_CONF = ROOT / "desktop" / "src-tauri" / "tauri.conf.json"
WORKFLOW = ROOT / ".github" / "workflows" / "desktop-release.yml"


@pytest.fixture(scope="module")
def tauri_conf() -> dict:
    assert TAURI_CONF.is_file(), f"the desktop bundle config is not at {TAURI_CONF}"
    return json.loads(TAURI_CONF.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def workflow() -> dict:
    assert WORKFLOW.is_file(), f"the desktop release workflow is not at {WORKFLOW}"
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = loaded.get("jobs") or {}
    print(f"\nread {WORKFLOW.name}: {len(jobs)} jobs {sorted(jobs)}")
    assert "build-tauri" in jobs, (
        f"no build-tauri job; the workflow declares {sorted(jobs)}. The assertions below read "
        f"that job's matrix, so a rename makes them read nothing and pass."
    )
    return loaded


def test_webview_is_installed_offline(tauri_conf: dict) -> None:
    """The installer carries WebView2 rather than fetching it.

    ``embedBootstrapper`` embeds a 1.8 MB downloader, so a machine that has no
    WebView2 runtime and no working internet cannot finish the installation.
    ``offlineInstaller`` embeds the runtime itself. It costs about 130 MB on an
    installer already measured in hundreds, and it buys an install that works on
    a site network that blocks Microsoft endpoints, which is an ordinary
    condition on a construction site rather than an edge case.
    """
    mode = tauri_conf["bundle"]["windows"]["webviewInstallMode"]["type"]
    print(f"webviewInstallMode: {mode}")
    assert mode == "offlineInstaller", (
        f"webviewInstallMode is {mode!r}. Anything other than 'offlineInstaller' makes a "
        f"successful install depend on the machine reaching Microsoft during setup, and the "
        f"failure arrives as a WebView2 error rather than as a network one."
    )


def windows_matrix_entry(workflow: dict, *, diagnostic: bool = False) -> dict:
    entries = workflow["jobs"]["build-tauri"]["strategy"]["matrix"]["include"]
    if isinstance(entries, str):
        # Decode both literal JSON arms, never eval a workflow expression.
        # A different expression must fail explicitly instead of silently
        # reading no Windows entries or checking only the release arm.
        match = re.fullmatch(
            r"\$\{\{\s*fromJSON\(inputs\.build_only_windows\s*&&\s*'([^']*)'\s*\|\|\s*'([^']*)'\)\s*\}\}",
            entries,
        )
        assert match, f"unsupported build-tauri matrix expression: {entries}"
        entries = json.loads(match.group(1 if diagnostic else 2))
    assert isinstance(entries, list) and all(isinstance(entry, dict) for entry in entries), entries
    windows = [e for e in entries if "windows" in str(e.get("os", ""))]
    print(f"build-tauri matrix: {len(entries)} entries, {len(windows)} of them Windows")
    assert len(windows) == 1, (
        f"expected exactly one Windows entry in the build-tauri matrix and found {len(windows)}. Entries: {entries}"
    )
    return windows[0]


@pytest.mark.parametrize("diagnostic", [False, True], ids=["release", "diagnostic"])
def test_windows_builds_the_nsis_installer_only(workflow: dict, diagnostic: bool) -> None:
    """One installer per platform.

    Windows shipped both an .exe and an .msi until 15.2.0. They installed the
    same application to the same directory while each kept its own record of
    having done so, so a person who took one and later took the other ended up
    with the app listed twice. The .exe is the one that carries our installer
    hooks, our language selector and the per-machine install mode.
    """
    entry = windows_matrix_entry(workflow, diagnostic=diagnostic)
    bundles = str(entry.get("bundles", ""))
    print(f"Windows bundles argument: {bundles!r}")
    assert "--bundles" in bundles, (
        f"the Windows matrix entry passes {bundles!r}, which means the build falls back to the "
        f"config's own target list. That list is 'all', which puts the .msi back."
    )
    named = bundles.split("--bundles", 1)[1].strip().split(",")
    named = [n.strip() for n in named if n.strip()]
    assert named == ["nsis"], f"Windows builds {named}, expected ['nsis'] alone."
    steps = workflow["jobs"]["build-tauri"]["steps"]
    if diagnostic:
        step = next(s for s in steps if s.get("name") == "Build Windows diagnostic installer without publishing")
        assert re.findall(r"--bundles\s+([^\s]+)", step["run"]) == ["nsis"], step["run"]
    else:
        step = next(s for s in steps if s.get("name") == "Build Tauri app")
        assert "${{ matrix.bundles }}" in step["with"]["args"], step["with"]["args"]


def test_nothing_in_the_release_workflow_still_reaches_for_an_msi(workflow: dict) -> None:
    """The gates went with the format.

    A step that downloads ``*.msi``, or refuses a release for want of one, would
    fail every release from 15.2.0 onward while reading as a completeness check.
    Comments are exempt: the file explains why the format left, and that
    explanation is worth keeping.
    """
    scripts: list[tuple[str, str]] = []
    for job_name, job in workflow["jobs"].items():
        for step in job.get("steps") or []:
            run = step.get("run")
            if run:
                scripts.append((f"{job_name}/{step.get('name', 'unnamed')}", run))
    print(f"scanned {len(scripts)} run steps across {len(workflow['jobs'])} jobs")
    assert scripts, "no run steps were read, so this test proved nothing"

    offenders = []
    for where, script in scripts:
        for line in script.splitlines():
            code = line.split("#", 1)[0]
            if re.search(r"\.msi\b", code):
                offenders.append(f"{where}: {line.strip()}")
    assert not offenders, "these steps still act on an .msi:\n" + "\n".join(offenders)
