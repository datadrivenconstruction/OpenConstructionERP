"""The backend's version check obeys the same two switches as the launcher's.

In the PG lane because that is the lane CI runs; it needs no database.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core import update_check_policy as policy

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LAUNCHER = _REPO_ROOT / "desktop" / "src-tauri" / "src" / "update_check.rs"


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(policy.DISABLE_ENV, raising=False)


def test_on_by_default(tmp_path: Path) -> None:
    assert policy.update_check_disabled(home=tmp_path) is False


@pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
def test_the_administrator_switch_turns_it_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(policy.DISABLE_ENV, value)
    assert policy.update_check_disabled(home=tmp_path) is True


@pytest.mark.parametrize("value", ["", "0", "false", "off", "no"])
def test_other_values_leave_it_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(policy.DISABLE_ENV, value)
    assert policy.update_check_disabled(home=tmp_path) is False


def test_the_launcher_opt_out_file_turns_it_off(tmp_path: Path) -> None:
    target = policy.opt_out_path(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text("OpenConstructionERP does not check for a newer version while this file exists.\n")
    assert policy.update_check_disabled(home=tmp_path) is True


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
