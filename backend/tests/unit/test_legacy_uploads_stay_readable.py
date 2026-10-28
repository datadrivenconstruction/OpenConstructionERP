"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Files written before upload roots were anchored on the data dir must still be readable.

Moving a write root is only half a repair. Ten modules spent their whole life
writing to a bare ``uploads/...`` literal, so on every deployment that started
the process from the repo root - which is what ``make dev-backend`` and the VPS
both do - real user files physically live at ``<repo>/uploads/...``. Anchoring
the root on the data dir and stopping there would leave every one of those
files addressable by a database row that no longer points at anything: the
upload succeeds, the download 404s, and nobody finds out until a user asks for
a document from last month.

Nothing is moved on disk. Writes go to the data dir, reads probe the active
root first and the old working-directory-relative root second. These tests are
the evidence for that claim, because the fallback is exactly the kind of code
that looks obviously correct and silently resolves to the wrong place: it
depends on the process working directory, on an environment variable, and on
containment checks that must not be fooled by ``..``.

One case deliberately recovers nothing. On the Windows install that motivated
the repair, ``mkdir`` under Program Files raised ``PermissionError``, so no
file was ever written there - there is nothing to fall back to, and the legacy
root correctly finds nothing. The fallback exists for the server and dev
installs, where the writes DID succeed.

The companion guard in ``test_storage_roots_are_data_dir_anchored`` stops a new
module re-introducing the relative root. This file guards the other direction:
that fixing it did not orphan the files already on disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.storage import (
    contained_upload_candidates,
    find_existing_upload,
    module_uploads_dir,
    upload_read_roots,
)


def _seed(path: Path, text: str) -> Path:
    """Create a file and every parent it needs, and return it.

    Args:
        path: File to create.
        text: Contents, used to tell two copies of one relative path apart.

    Returns:
        The path that was written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the platform at a throwaway data dir and start it somewhere else.

    The two locations are deliberately different, because a test whose working
    directory already IS the data dir cannot tell the fallback from the active
    root - both spellings would name one directory and every assertion would
    pass for the wrong reason.

    Args:
        tmp_path: pytest-provided scratch directory.
        monkeypatch: pytest patcher, used for the env var and the chdir.

    Returns:
        The resolved data directory the platform will write under.
    """
    data = tmp_path / "data"
    monkeypatch.setenv("OE_DATA_DIR", str(data))
    # OE_DATA_DIR wins over both, but a leaked value from the ambient
    # environment would still change what "active root" means mid-test.
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("OE_CLI_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    return data


def test_the_write_root_ignores_the_directory_the_process_started_in(
    tmp_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: two different start directories, one write root."""
    from_repo_root = module_uploads_dir("rfi", "attachments")

    started_elsewhere = tmp_path / "some" / "other" / "cwd"
    started_elsewhere.mkdir(parents=True)
    monkeypatch.chdir(started_elsewhere)

    assert module_uploads_dir("rfi", "attachments") == from_repo_root
    assert from_repo_root == data_dir / "uploads" / "rfi" / "attachments"


def test_a_file_written_under_the_old_relative_root_is_still_found(tmp_path: Path, data_dir: Path) -> None:
    """A file only the legacy tree holds resolves to the legacy tree."""
    legacy = _seed(tmp_path / "uploads" / "rfi" / "attachments" / "last-month.pdf", "written before the fix")

    found = find_existing_upload("rfi/attachments/last-month.pdf")

    assert found is not None, "a file written by an earlier release became unreadable"
    assert found == legacy.resolve()
    assert found.read_text(encoding="utf-8") == "written before the fix"


def test_the_active_root_wins_when_both_roots_hold_the_same_path(tmp_path: Path, data_dir: Path) -> None:
    """Re-uploading must not keep serving the stale legacy copy."""
    _seed(tmp_path / "uploads" / "rfi" / "attachments" / "spec.pdf", "stale")
    active = _seed(data_dir / "uploads" / "rfi" / "attachments" / "spec.pdf", "current")

    found = find_existing_upload("rfi/attachments/spec.pdf")

    assert found == active.resolve()
    assert found is not None and found.read_text(encoding="utf-8") == "current"


def test_read_roots_are_ordered_active_first_and_deduplicated(tmp_path: Path, data_dir: Path) -> None:
    """Order is the mechanism behind active-wins; dedup keeps one root one root."""
    assert upload_read_roots() == [
        (data_dir / "uploads").resolve(),
        (tmp_path / "uploads").resolve(),
    ]


def test_a_process_started_inside_the_data_dir_sees_a_single_root(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When both spellings name one directory, it must not be probed twice."""
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(data_dir)

    assert upload_read_roots() == [(data_dir / "uploads").resolve()]


def test_a_path_that_escapes_its_root_is_not_addressable_at_all(data_dir: Path) -> None:
    """An empty candidate list is what a caller turns into 403, so it must be empty."""
    assert contained_upload_candidates("../../../etc/passwd") == []
    assert contained_upload_candidates("rfi/../../secrets.env") == []
    assert find_existing_upload("../../../etc/passwd") is None


def test_an_absolute_stored_path_is_refused_rather_than_joined(tmp_path: Path, data_dir: Path) -> None:
    """Joining an absolute path onto a root silently discards the root."""
    outside = _seed(tmp_path / "outside" / "secret.pdf", "not yours")

    assert contained_upload_candidates(str(outside)) == []
    assert find_existing_upload(str(outside)) is None


def test_a_missing_file_is_addressable_but_absent(data_dir: Path) -> None:
    """The 404 case must stay distinguishable from the 403 case above."""
    candidates = contained_upload_candidates("rfi/attachments/never-uploaded.pdf")

    assert candidates, "a well-formed path stopped being addressable"
    assert find_existing_upload("rfi/attachments/never-uploaded.pdf") is None


def test_a_module_can_redirect_its_own_root(tmp_path: Path, data_dir: Path) -> None:
    """Modules keep a module-level base constant, and tests redirect that constant.

    The lookup therefore has to accept the root rather than always re-deriving
    it, or every existing test that monkeypatches a module's base would go on
    passing while reading a directory the module no longer writes to.
    """
    redirected = tmp_path / "redirected"
    target = _seed(redirected / "rfi" / "attachments" / "a.pdf", "redirected")

    assert find_existing_upload("rfi/attachments/a.pdf", redirected) == target.resolve()
    assert find_existing_upload("rfi/attachments/a.pdf") is None
