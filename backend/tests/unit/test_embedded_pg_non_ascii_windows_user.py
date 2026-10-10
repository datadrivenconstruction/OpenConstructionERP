"""Embedded PostgreSQL bring-up for a Windows account with a non-ASCII name.

A user named ``田田`` on a Chinese Windows install (ANSI code page 936) could not
start the desktop app at all. initdb prints the operating-system user name and
the data directory in the ANSI code page, pixeltable-pgserver read that output
back as strict UTF-8, and the ``UnicodeDecodeError`` replaced whatever initdb
had actually done, on every one of the three bring-up attempts.

These tests spawn a real child that writes GBK and cp1251 bytes, so the decode
happens where it happened in the field, and pin where a non-ASCII data
directory's cluster goes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.core import embedded_pg

# "...owned by user "田田"." in GBK, then a data directory under that profile.
_GBK_INITDB = (
    b'The files belonging to this database system will be owned by user "\xcc\xef\xcc\xef".\r\n'
    b"creating directory C:/Users/\xcc\xef\xcc\xef/.openestimate/pgdata ... ok\r\n"
)
# The same line for a Russian account, in cp1251.
_CP1251_INITDB = b'will be owned by user "\xc8\xe2\xe0\xed".\r\n'


def _fake_bin(tmp_path: Path, name: str, payload: bytes, exit_code: int = 0) -> Path:
    """A stand-in for a bundled PostgreSQL program that prints ``payload``."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    script = bindir / f"{name}.py"
    script.write_text(
        "import sys\n"
        f"sys.stdout.buffer.write({payload!r})\n"
        f"sys.stderr.buffer.write({payload!r})\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    return script


@pytest.fixture
def run_fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Make ``_safe_pgexec`` run a Python script in place of a PostgreSQL binary."""
    pytest.importorskip("pixeltable_pgserver")
    import pixeltable_pgserver.utils as pg_utils

    monkeypatch.setattr(pg_utils, "POSTGRES_BIN_PATH", tmp_path / "bin")
    real_run = subprocess.run

    def run(cmdline, **kwargs):
        script = Path(str(cmdline[0]).removesuffix(".exe") + ".py")
        return real_run([sys.executable, str(script), *cmdline[1:]], **kwargs)

    monkeypatch.setattr(embedded_pg.subprocess, "run", run)
    return tmp_path


@pytest.mark.parametrize("payload", [_GBK_INITDB, _CP1251_INITDB], ids=["gbk", "cp1251"])
def test_a_successful_initdb_printing_ansi_bytes_is_a_success(run_fake: Path, payload: bytes) -> None:
    _fake_bin(run_fake, "initdb", payload)

    out = embedded_pg._safe_pgexec("initdb", ("--version",))

    assert "owned by user" in out


def test_a_failed_initdb_keeps_its_own_message_instead_of_a_decode_error(run_fake: Path) -> None:
    _fake_bin(run_fake, "initdb", _GBK_INITDB + b"initdb: error: something real\r\n", exit_code=1)

    with pytest.raises(subprocess.CalledProcessError) as caught:
        embedded_pg._safe_pgexec("initdb", ())

    assert "initdb: error: something real" in embedded_pg._child_failure_text(caught.value)


def test_the_library_binding_used_by_get_server_is_replaced_too() -> None:
    pytest.importorskip("pixeltable_pgserver")
    import pixeltable_pgserver.pgexec as pgexec_module
    import pixeltable_pgserver.postgres_server as server_module

    original = (pgexec_module.pgexec, server_module.pgexec)
    try:
        embedded_pg._install_safe_pgexec()
        assert pgexec_module.pgexec is embedded_pg._safe_pgexec
        # postgres_server imported the name, so this is the binding that runs
        # pixeltable's own initdb and pg_ctl start.
        assert server_module.pgexec is embedded_pg._safe_pgexec
    finally:
        pgexec_module.pgexec, server_module.pgexec = original


@pytest.mark.parametrize("raw", [_GBK_INITDB, _CP1251_INITDB, b"\xff\xfe\x00broken"])
def test_decoding_child_output_never_raises(raw: bytes) -> None:
    assert isinstance(embedded_pg.decode_child_output(raw), str)


def test_decoding_reads_gbk_as_gbk_on_a_chinese_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedded_pg, "_windows_ansi_encoding", lambda: "cp936")

    assert "田田" in embedded_pg.decode_child_output(_GBK_INITDB)


class TestWhereTheClusterLives:
    def test_an_ascii_data_dir_keeps_its_cluster_in_place(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(embedded_pg, "cluster_path_must_be_ascii", lambda: True)
        data_dir = tmp_path / "plain"

        assert embedded_pg.resolve_pgdata(data_dir) == data_dir / "pgdata"

    def test_a_non_ascii_home_moves_the_cluster_to_an_ascii_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(embedded_pg, "cluster_path_must_be_ascii", lambda: True)
        monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))
        data_dir = tmp_path / "Users" / "田田" / ".openestimate"

        pgdata = embedded_pg.resolve_pgdata(data_dir)

        assert str(pgdata).isascii()
        assert pgdata.is_relative_to(tmp_path / "ProgramData" / "OpenConstructionERP")
        # Same answer for every caller, before anything exists: the CLI, doctor
        # and boot must all agree on where the cluster is.
        assert embedded_pg.resolve_pgdata(data_dir) == pgdata
        assert embedded_pg.resolve_pgdata(tmp_path / "Users" / "Иван" / ".openestimate") != pgdata

    def test_initdb_debris_on_the_non_ascii_path_does_not_pin_the_cluster_there(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(embedded_pg, "cluster_path_must_be_ascii", lambda: True)
        monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))
        data_dir = tmp_path / "田田"
        debris = data_dir / "pgdata"
        (debris / "global").mkdir(parents=True)
        # What an initdb that died in post-bootstrap leaves behind.
        (debris / "PG_VERSION").write_text("17\n", encoding="utf-8")
        (debris / "global" / "pg_control").write_bytes(b"\0")

        assert embedded_pg.resolve_pgdata(data_dir) != debris

    def test_a_cluster_that_has_run_on_the_non_ascii_path_stays_there(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(embedded_pg, "cluster_path_must_be_ascii", lambda: True)
        data_dir = tmp_path / "田田"
        existing = data_dir / "pgdata"
        existing.mkdir(parents=True)
        (existing / "PG_VERSION").write_text("17\n", encoding="utf-8")
        (existing / "postmaster.opts").write_text("postgres\n", encoding="utf-8")

        assert embedded_pg.resolve_pgdata(data_dir) == existing

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX behaviour")
    def test_posix_never_relocates(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "田田"

        assert embedded_pg.resolve_pgdata(data_dir) == data_dir / "pgdata"

    def test_the_relocation_leaves_a_pointer_for_the_launcher(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(embedded_pg, "_restrict_to_current_user", lambda _d: None)
        data_dir = tmp_path / "田田"
        pgdata = tmp_path / "ProgramData" / "x" / "pgdata"

        embedded_pg._prepare_relocated_pgdata(data_dir, pgdata)

        assert pgdata.parent.is_dir()
        assert (data_dir / embedded_pg.PGDATA_POINTER_NAME).read_text(encoding="utf-8") == str(pgdata)
