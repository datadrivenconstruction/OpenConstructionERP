"""Demo-account password generation (BUG-D01 fix).

Until v2.5.x the platform shipped a hardcoded ``DemoPass1234!`` at four
call sites in ``main.py``. README claimed *"passwords are randomly
generated per installation"* — they were not. The fix introduces
``_resolve_demo_password`` (env-var first, otherwise random) and
``_persist_demo_credentials`` (save generated passwords to a chmod-600
JSON file so the operator can recover them).

These unit tests pin the helper contracts so the seeding code in
``main.py`` cannot drift back into shipping a global constant.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.main import _persist_demo_credentials, _resolve_demo_password


# ─────────────────────────────────────────────────────────────────────────
# _resolve_demo_password
# ─────────────────────────────────────────────────────────────────────────


def test_resolve_uses_env_when_set():
    """If the env var is set we honour it verbatim."""
    with patch.dict(os.environ, {"TEST_DEMO_PW": "explicit-secret"}, clear=False):
        password, was_generated = _resolve_demo_password("TEST_DEMO_PW")
    assert password == "explicit-secret"
    assert was_generated is False


def test_resolve_generates_when_unset():
    """Empty / missing env var → fresh random password."""
    # Defensively unset both possible names. ``clear=False`` keeps the rest.
    env = os.environ.copy()
    env.pop("TEST_DEMO_PW_UNSET", None)
    with patch.dict(os.environ, env, clear=True):
        password, was_generated = _resolve_demo_password("TEST_DEMO_PW_UNSET")
    assert was_generated is True
    assert password
    # token_urlsafe(16) yields exactly 22 URL-safe chars, no padding.
    assert len(password) == 22


def test_resolve_generates_unique_each_call():
    """Two consecutive generations must differ — proves it isn't a constant."""
    env = os.environ.copy()
    env.pop("TEST_DEMO_PW_UNIQ", None)
    with patch.dict(os.environ, env, clear=True):
        a, _ = _resolve_demo_password("TEST_DEMO_PW_UNIQ")
        b, _ = _resolve_demo_password("TEST_DEMO_PW_UNIQ")
    assert a != b


def test_resolve_treats_empty_string_as_unset():
    """Setting the env var to an empty string must not be honoured.

    A blank string would silently weaken the password to nothing. We treat
    it as "unset" and generate a fresh one.
    """
    with patch.dict(os.environ, {"TEST_DEMO_PW_EMPTY": ""}, clear=False):
        password, was_generated = _resolve_demo_password("TEST_DEMO_PW_EMPTY")
    assert was_generated is True
    assert len(password) == 22


# ─────────────────────────────────────────────────────────────────────────
# _persist_demo_credentials
# ─────────────────────────────────────────────────────────────────────────


def test_persist_writes_json_in_data_dir(tmp_path: Path):
    """Honours OE_CLI_DATA_DIR and writes pretty-printed JSON."""
    creds = {"demo@openestimator.io": "secret-A", "estimator@openestimator.io": "secret-B"}

    with patch.dict(os.environ, {"OE_CLI_DATA_DIR": str(tmp_path)}, clear=False):
        path = _persist_demo_credentials(creds)

    assert path is not None
    assert path == tmp_path / ".demo_credentials.json"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk == creds


def test_persist_falls_back_to_home_when_no_cli_dir(tmp_path: Path):
    """Without OE_CLI_DATA_DIR we fall back to ~/.openestimator/."""
    creds = {"demo@openestimator.io": "fallback-secret"}

    env = os.environ.copy()
    env.pop("OE_CLI_DATA_DIR", None)
    with patch.dict(os.environ, env, clear=True), patch(
        "app.main.Path.home", return_value=tmp_path
    ):
        path = _persist_demo_credentials(creds)

    assert path is not None
    assert path == tmp_path / ".openestimator" / ".demo_credentials.json"
    assert json.loads(path.read_text(encoding="utf-8")) == creds


def test_persist_merges_with_existing_file(tmp_path: Path):
    """Calling persist twice merges keys instead of clobbering them.

    On a slow boot the seeder may run, the box may be killed mid-startup,
    and the next boot finds some demo rows already created and others
    not. The credentials file should accumulate, not lose entries.
    """
    path = tmp_path / ".demo_credentials.json"
    path.write_text(json.dumps({"demo@openestimator.io": "first"}), encoding="utf-8")

    with patch.dict(os.environ, {"OE_CLI_DATA_DIR": str(tmp_path)}, clear=False):
        _persist_demo_credentials({"estimator@openestimator.io": "second"})

    merged = json.loads(path.read_text(encoding="utf-8"))
    assert merged == {
        "demo@openestimator.io": "first",
        "estimator@openestimator.io": "second",
    }


def test_persist_overwrites_same_key_in_merge(tmp_path: Path):
    """Merge semantics: same email re-persisted wins (last-writer-wins)."""
    path = tmp_path / ".demo_credentials.json"
    path.write_text(json.dumps({"demo@openestimator.io": "old"}), encoding="utf-8")

    with patch.dict(os.environ, {"OE_CLI_DATA_DIR": str(tmp_path)}, clear=False):
        _persist_demo_credentials({"demo@openestimator.io": "new"})

    final = json.loads(path.read_text(encoding="utf-8"))
    assert final == {"demo@openestimator.io": "new"}


def test_persist_returns_none_on_unwritable_dir(monkeypatch):
    """Best-effort persistence: a write failure must not crash startup."""
    import app.main as _main

    def _explode(*_args, **_kwargs):  # noqa: ANN001 — test stub
        raise OSError("disk full simulation")

    monkeypatch.setattr(_main.Path, "mkdir", _explode)

    result = _persist_demo_credentials({"demo@openestimator.io": "x"})
    assert result is None


def test_persist_no_corruption_on_existing_unparseable_file(tmp_path: Path):
    """If the existing creds file is corrupt, we treat it as empty.

    Otherwise a stray ``{`` left over from a partial earlier write would
    permanently block the seeder from updating the file.
    """
    path = tmp_path / ".demo_credentials.json"
    path.write_text("{ not valid json", encoding="utf-8")

    with patch.dict(os.environ, {"OE_CLI_DATA_DIR": str(tmp_path)}, clear=False):
        result = _persist_demo_credentials({"demo@openestimator.io": "after-corruption"})

    assert result is not None
    final = json.loads(path.read_text(encoding="utf-8"))
    assert final == {"demo@openestimator.io": "after-corruption"}


# ─────────────────────────────────────────────────────────────────────────
# Source-level guard: no hardcoded DemoPass1234 anywhere in main.py
# ─────────────────────────────────────────────────────────────────────────


def test_main_module_has_no_hardcoded_demo_password():
    """Codebase invariant: the literal must never come back.

    The original BUG-D01 had four occurrences of ``DemoPass1234!`` in
    ``main.py``. This grep-style test fails if any are reintroduced —
    which would silently weaken every new installation's demo accounts.
    """
    main_path = Path(__file__).resolve().parents[2] / "app" / "main.py"
    source = main_path.read_text(encoding="utf-8")
    assert "DemoPass1234!" not in source, (
        "Hardcoded demo password reintroduced in main.py — see BUG-D01. "
        "Use _resolve_demo_password() + _persist_demo_credentials() instead."
    )
