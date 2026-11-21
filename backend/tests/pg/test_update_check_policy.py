"""The backend's version check obeys the same two switches as the launcher's.

In the PG lane because that is the lane CI runs; it needs no database.

The default moved since this file was written, and the tests that pinned it moved
with it. The check used to be opt-out: it ran unless ``OE_DISABLE_UPDATE_CHECK``
was set or the launcher had written ``~/.openestimate/no-update-check``, so an
installation nobody had configured asked PyPI and GitHub once a day. It is opt-in
now - a workspace setting on the branding record, admin-only to write, public to
read - and the record is what
``tests/unit/test_the_version_check_is_off_until_an_administrator_turns_it_on.py``
holds down. What stays here is the part that file cannot assert without a
launcher: that the two operator switches are still read, still spelled the way the
Rust shell spells them, and still win over a workspace that has asked, so turning
the setting on in the product cannot undo an opt-out a user made from the
launcher's own notice. Each of those tests therefore states the workspace answer
explicitly instead of relying on a default that no longer means "on".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core import update_check_policy as policy

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LAUNCHER = _REPO_ROOT / "desktop" / "src-tauri" / "src" / "update_check.rs"
_WEB_UI = _REPO_ROOT / "frontend" / "src" / "shared" / "ui" / "UpdateChecker.tsx"


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(policy.DISABLE_ENV, raising=False)


def test_off_until_the_workspace_asks(tmp_path: Path) -> None:
    """The default, and the reason the setting exists.

    No record on disk is not a "yes, ask"; only a workspace that has been told
    what the check does and turned it on gets one.
    """
    assert policy.update_check_disabled(home=tmp_path) is True
    assert policy.update_check_disabled(home=tmp_path, workspace_enabled=True) is False


@pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
def test_the_administrator_switch_beats_a_workspace_that_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(policy.DISABLE_ENV, value)
    assert policy.update_check_disabled(home=tmp_path, workspace_enabled=True) is True


@pytest.mark.parametrize("value", ["", "0", "false", "off", "no"])
def test_other_values_leave_the_workspace_in_charge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """A falsy value is not a second opt-out, it is an unset one.

    Asserted against a workspace that asked, because that is the only state in
    which the environment's spelling is visible at all: with the setting off, the
    answer is off whatever the variable holds.
    """
    monkeypatch.setenv(policy.DISABLE_ENV, value)
    assert policy.update_check_disabled(home=tmp_path, workspace_enabled=True) is False


def test_the_launcher_opt_out_file_beats_a_workspace_that_asked(tmp_path: Path) -> None:
    target = policy.opt_out_path(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text("OpenConstructionERP does not check for a newer version while this file exists.\n")
    assert policy.update_check_disabled(home=tmp_path, workspace_enabled=True) is True


def test_the_names_match_the_launcher() -> None:
    """A rename on either side would silently split the two checks again."""
    source = _LAUNCHER.read_text(encoding="utf-8")
    env = re.search(r'pub const DISABLE_ENV: &str = "([^"]+)"', source)
    file_name = re.search(r'const OPT_OUT_FILE: &str = "([^"]+)"', source)
    folder = re.search(r'fn opt_out_path\(\).*?join\("([^"]+)"\)', source, re.S)
    assert env and file_name and folder, "launcher constants moved; update this test"
    assert env.group(1) == policy.DISABLE_ENV
    assert file_name.group(1) == policy.OPT_OUT_FILE
    assert policy.opt_out_path(Path("h")) == Path("h") / folder.group(1) / file_name.group(1)


def test_the_automatic_check_asks_once_a_day() -> None:
    """A day on the server, and the same day in the web UI's copy of the answer.

    If the UI held its copy for less, it would ask a server that answers from
    cache anyway; if for more, a release the server already knows about would
    sit unshown.
    """
    assert policy.VERSION_CHECK_TTL_S == 24 * 60 * 60
    source = _WEB_UI.read_text(encoding="utf-8")
    match = re.search(r"export const VERSION_CHECK_TTL_MS = ([\d\s*]+);", source)
    assert match, "the web UI's interval moved; update this test"
    factors = [int(n) for n in match.group(1).split("*")]
    ms = 1
    for n in factors:
        ms *= n
    assert ms == policy.VERSION_CHECK_TTL_S * 1000
    assert "refetchInterval: VERSION_CHECK_TTL_MS" in source, "a window left open must ask again after a day"


def test_the_web_ui_does_not_ask_until_the_workspace_has() -> None:
    """The other half of an opt-in: the server refuses, and the browser does not ask.

    The endpoint answering ``check_disabled`` is what keeps PyPI and GitHub quiet.
    It is not what keeps the browser quiet - a UI that still called the endpoint
    once a day would be making a request nobody asked for, to a server whose answer
    is "no", and About's sentence would be describing the second hop only. So the
    query the notices read is gated on the same workspace setting, read from the
    branding record the setting lives on.

    Asserted against the source, like the two tests above it, because the two sides
    are in different languages and nothing else in the tree would notice one of them
    moving: a rename in the store, or a gate dropped from the query, splits the
    disclosure from the behaviour it describes.
    """
    source = _WEB_UI.read_text(encoding="utf-8")
    assert "useBrandingStore((s) => s.updateCheckEnabled)" in source, (
        "the web UI reads the workspace setting from somewhere else now; update this test"
    )
    assert "enabled: !UPDATE_CHECK_DISABLED && workspaceEnabled" in source, (
        "the automatic check no longer waits for the workspace; update this test"
    )
