"""The Windows installer hook must stop our database, and only ours.

The hook is a PowerShell one-liner embedded in an NSIS macro. Nothing compiles
it, nothing type-checks it, and a mistake inside it does not fail a build: it
becomes a silent no-op on a user's machine, which is exactly how the previous
version of this hook spent five releases matching zero of the processes it was
written to match. So the file that ships is read here directly, and the parts
that carry the meaning are asserted one by one.

There are two ways for this hook to be wrong and they pull in opposite
directions. Stopping too little leaves the embedded postmaster running after the
app is gone, holding the data directory and the port, which is the defect this
hook exists to fix. Stopping too much reaches into an unrelated PostgreSQL that
happens to share an image name, which is the older and worse defect the previous
hook had. A test that only checks one direction cannot tell a working guard from
a guard that refuses everything, so on Windows both directions are executed
against real processes.

The data directory the hook looks in has to be the one the backend actually
uses. That agreement is asserted against the backend's own source rather than
against a constant repeated here, because a constant repeated here is just a
second place to forget.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HOOK = ROOT / "desktop" / "src-tauri" / "windows" / "hooks.nsh"
STORAGE = ROOT / "backend" / "app" / "core" / "storage.py"
DEMO_SEED = ROOT / "backend" / "app" / "core" / "demo_seed.py"

#: NSIS truncates strings past this length, silently. The default build limit is
#: 1024; a command line that grows past it would be cut mid-expression and the
#: result would still be a valid-looking script that does the wrong thing.
NSIS_MAX_STRLEN = 1024

#: Every nsExec call in the hook. Asserted rather than merely iterated: a
#: pattern that stops matching this file would otherwise turn both checks
#: below into loops over nothing, which pass.
EXPECTED_NSEXEC_CALLS = 4


@pytest.fixture(scope="module")
def hook_text() -> str:
    assert HOOK.is_file(), f"the installer hook is not at {HOOK}"
    text = HOOK.read_text(encoding="utf-8")
    print(f"\nread {HOOK.name}: {len(text.splitlines())} lines")
    return text


@pytest.fixture(scope="module")
def postmaster_command(hook_text: str) -> str:
    """The PowerShell body of the postmaster stop, as PowerShell will see it.

    NSIS writes a literal dollar sign as ``$$``, so the file carries ``$$env``
    where the shell receives ``$env``. Undoing that doubling is the only change
    made to the text; everything else is what ships.
    """
    macro = re.search(r"!macro OE_STOP_OUR_POSTMASTER(.*?)!macroend", hook_text, re.S)
    assert macro is not None, "the hook no longer defines OE_STOP_OUR_POSTMASTER"
    call = re.search(r"-Command \"(.*)\"`", macro.group(1), re.S)
    assert call is not None, "OE_STOP_OUR_POSTMASTER no longer runs a powershell -Command"
    command = call.group(1).replace("$$", "$")
    print(f"the postmaster stop is {len(command)} characters of PowerShell")
    return command


def _env_names(source: Path, pattern: str) -> list[str]:
    """Pull the data-dir environment variable names out of a source file."""
    text = source.read_text(encoding="utf-8")
    line = re.search(pattern, text, re.M)
    assert line is not None, f"could not find the data-dir resolution in {source.name}"
    return re.findall(r"[\"']([A-Z_]+)[\"']", line.group(0))


def test_the_hook_looks_where_the_backend_actually_keeps_its_data(postmaster_command: str) -> None:
    """The hook, storage.py and demo_seed.py must name the same variables in order.

    If the backend gains a fourth override or reorders the three it has, the hook
    starts looking in a directory nobody uses, finds no pid file, and quietly
    stops stopping anything. Deriving the expected order from the backend's own
    source is what makes that a failure here instead of a support ticket later.
    """
    canonical = _env_names(STORAGE, r"override = os\.environ\.get\(.*?\)\s*$")
    mirrored = _env_names(DEMO_SEED, r"for env_name in \([^)]*\)")
    print(f"storage.py resolves {canonical}")
    print(f"demo_seed.py resolves {mirrored}")
    assert canonical == mirrored, (
        "the backend's two data-dir resolvers disagree with each other, so the "
        "installer cannot be made to agree with both"
    )

    found = re.findall(r"\$env:([A-Z_]+)", postmaster_command)
    ordered = [name for name in found if name in set(canonical)]
    print(f"the installer hook resolves {ordered}")
    assert ordered == canonical, (
        f"the hook reads {ordered} but the backend reads {canonical}; the "
        f"installer would look for the cluster in the wrong directory"
    )

    default_dir = re.search(r"DEFAULT_DATA_DIR = Path\.home\(\) / \"([^\"]+)\"", DEMO_SEED.read_text(encoding="utf-8"))
    assert default_dir is not None, "demo_seed.py no longer declares DEFAULT_DATA_DIR"
    assert f"'{default_dir.group(1)}'" in postmaster_command, (
        f"the hook does not fall back to {default_dir.group(1)}, which is where "
        f"an install with no overrides set actually keeps its cluster"
    )


def test_the_hook_finds_the_postmaster_through_its_own_pid_file(postmaster_command: str) -> None:
    """Identity comes from the pid file, not from the image name.

    The filter on ``$INSTDIR`` in the other macro cannot see the postmaster: it
    runs out of the temporary directory the onefile bundle unpacks into. The pid
    file inside our own data directory names exactly one process and it is by
    construction ours.
    """
    assert "postmaster.pid" in postmaster_command, "the hook no longer reads the cluster's pid file"
    assert "pgdata" in postmaster_command, "the hook no longer looks inside the pgdata directory"
    assert "-TotalCount 3" in postmaster_command, (
        "the hook must read three lines of the pid file: the pid is line 1 and "
        "the start time it is verified against is line 3"
    )


def test_the_hook_refuses_a_pid_it_cannot_confirm(postmaster_command: str) -> None:
    """Both guards against a stale pid file have to be present.

    A pid file outlives the process that wrote it, and Windows reuses pids. The
    name check rejects the common case where the pid now belongs to something
    else entirely; the start-time check rejects the case where it belongs to a
    different PostgreSQL. Neither alone is enough.
    """
    assert "ProcessName -eq 'postgres'" in postmaster_command, (
        "the hook would stop whatever process now holds that pid, which is how "
        "the previous hook killed processes that were not ours"
    )
    assert "StartTime" in postmaster_command and "ToUnixTimeSeconds" in postmaster_command, (
        "the hook does not compare the running process's start time against the "
        "one the pid file recorded, so a recycled pid passes the name check"
    )


def test_no_taskkill_reaches_beyond_this_user(hook_text: str) -> None:
    """The fallback may not match by bare image name.

    ``taskkill /IM`` matches across every session on the machine. An elevated
    installer running it stopped the process in other users' sessions and in
    other installations of the product. Every shipped release from 15.0.0 to
    15.3.1 does this.
    """
    # Only executed lines count. The comment block above the macro quotes the
    # old blunt command on purpose, to record what it did and why it changed,
    # and a check that reads prose would convict the file for explaining itself.
    executed = re.findall(r"nsExec::Exec[^`\n]*`([^`]*)`", hook_text)
    kills = [command for command in executed if "taskkill" in command]
    print(f"the hook runs {len(executed)} commands, {len(kills)} of them taskkill fallbacks")
    assert kills, "the taskkill fallback is gone; a machine without PowerShell now has no path"
    for kill in kills:
        assert re.search(r"/IM\s", kill) is None, f"bare /IM matches every session on the machine: {kill}"
        assert "IMAGENAME eq" in kill, f"taskkill is not filtered by image name: {kill}"
        assert "USERNAME eq" in kill, f"taskkill is not scoped to this user: {kill}"


def test_both_install_and_uninstall_stop_the_cluster(hook_text: str) -> None:
    """Uninstall matters as much as install, and for a worse reason.

    An install that leaves the postmaster running produces a confusing upgrade.
    An uninstall that leaves it running produces a process with no application
    left on disk to explain it, still holding the port.
    """
    for hook in ("NSIS_HOOK_PREINSTALL", "NSIS_HOOK_PREUNINSTALL"):
        body = re.search(rf"!macro {hook}(.*?)!macroend", hook_text, re.S)
        assert body is not None, f"{hook} is not defined"
        assert "OE_STOP_THIS_INSTALL" in body.group(1), f"{hook} does not stop the running install"
    stop_all = re.search(r"!macro OE_STOP_THIS_INSTALL(.*?)!macroend", hook_text, re.S)
    assert stop_all is not None
    assert "OE_STOP_OUR_POSTMASTER" in stop_all.group(1), (
        "the postmaster stop is defined but never inserted, so it runs nowhere"
    )


def test_the_installer_template_kills_nothing_by_image_name() -> None:
    """The vendored template may not call the bundler's name-based process kill.

    Upstream's ``CheckIfAppIsRunning`` on the main binary is ``FindProcess`` plus
    ``KillProcess``: in perMachine mode every process on the machine with that
    image name, compared case-insensitively, and no prompt in silent mode. The
    pip package's console script is ``openconstructionerp.exe``, so an upgrade
    of the desktop app killed a backend served from a Python install. Our hooks
    close what runs from ``$INSTDIR`` by path, which is all the files need.
    """
    template = HOOK.parent / "installer.nsi"
    assert template.is_file(), f"the vendored installer template is not at {template}"
    executed = [
        line.strip()
        for line in template.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith(";")
    ]
    print(f"\nread {template.name}: {len(executed)} executed lines")
    assert any("NSIS_HOOK_PREINSTALL" in line for line in executed), "the template no longer runs the install hook"
    assert any("NSIS_HOOK_PREUNINSTALL" in line for line in executed), "the template no longer runs the uninstall hook"
    offenders = [
        line for line in executed if re.search(r"CheckIfAppIsRunning|nsis_tauri_utils::(FindProcess|KillProcess)", line)
    ]
    assert not offenders, f"the installer kills processes by image name again: {offenders}"


def test_the_installer_refuses_a_non_ascii_install_directory(hook_text: str) -> None:
    """A non-ASCII ``$INSTDIR`` must be refused on the page and in silent mode.

    The onedir backend runs the bundled PostgreSQL from the install directory,
    and its initdb cannot start from a path outside the ANSI code page, so an
    install into such a folder never starts. Measured on a hosted runner: a
    Cyrillic install folder gave "program postgres is needed by initdb but was
    not found" and no healthy backend in 25 minutes. The page check covers the
    wizard, the section check covers ``/S /D=...`` and passive mode, which never
    show the page.
    """
    check = re.search(r"Function OE_InstDirIsAscii(.*?)FunctionEnd", hook_text, re.S)
    assert check is not None, "the hook no longer defines the ASCII check"
    assert "WideCharToMultiByte(i 20127" in check.group(1), "the check no longer round-trips through US-ASCII"
    assert "StrCmpS" in check.group(1), "StrCmp ignores case, the comparison must be StrCmpS"

    refuse = re.search(r"!macro OE_REFUSE_NON_ASCII_INSTDIR(.*?)!macroend", hook_text, re.S)
    assert refuse is not None, "the hook no longer defines the silent-mode refusal"
    level = re.search(r"SetErrorLevel\s+(\d+)", refuse.group(1))
    assert level is not None and int(level.group(1)) != 0, "a refused silent install must exit non-zero"
    assert re.search(r"^\s*(Quit|Abort)\b", refuse.group(1), re.M), "the refusal does not stop the install"

    template = (HOOK.parent / "installer.nsi").read_text(encoding="utf-8")
    executed = "\n".join(
        line.strip() for line in template.splitlines() if line.strip() and not line.strip().startswith(";")
    )
    assert re.search(
        r"!define MUI_PAGE_CUSTOMFUNCTION_LEAVE OE_CheckInstallDirectory\n!insertmacro MUI_PAGE_DIRECTORY\b", executed
    ), "the directory page no longer runs the ASCII check when the user leaves it"
    early = re.search(r"Section EarlyChecks\n(.*?)\nSectionEnd", executed, re.S)
    assert early is not None, "the template no longer has an EarlyChecks section"
    assert early.group(1).splitlines()[0] == "!insertmacro OE_REFUSE_NON_ASCII_INSTDIR", (
        "a silent install no longer checks the install directory before anything else runs"
    )


def test_every_command_line_survives_nsis_string_truncation(hook_text: str) -> None:
    """A command longer than NSIS can hold is truncated, not rejected.

    The result still looks like a script and still runs; it just stops partway
    through an expression. This is the failure mode that would be hardest to
    recognise from a bug report, so it is bounded here.
    """
    commands = re.findall(r"nsExec::Exec[^`\n]*`([^`]*)`", hook_text)

    # The pattern above skips whatever flags sit between the call and its
    # backtick, because it did not always: it required the backtick to follow
    # the call directly, and the first flag added to this file reduced this
    # test to a loop over an empty list that still passed. A count is asserted
    # for the same reason - a sweep that finds nothing is not a clean sweep.
    assert len(commands) == EXPECTED_NSEXEC_CALLS, (
        f"expected {EXPECTED_NSEXEC_CALLS} nsExec commands in the hook, matched "
        f"{len(commands)}; if a call was added or removed on purpose, change the "
        f"constant, and if it was not, the pattern has stopped seeing this file"
    )

    for command in commands:
        length = len(command)
        print(f"  {length:>4} chars: {command[:60]}...")
        assert length < NSIS_MAX_STRLEN, (
            f"a {length} character command exceeds the {NSIS_MAX_STRLEN} character "
            f"NSIS string limit and would be silently cut"
        )


def test_no_call_can_wait_forever(hook_text: str) -> None:
    """nsExec waits for its child indefinitely unless it is given a timeout.

    The uninstaller waits for nsExec and, on an upgrade, the installer waits for
    the uninstaller, so an unbounded call here is an unbounded upgrade. A user
    reported exactly that: the uninstaller stopped on "Closing
    OpenConstructionERP..." and never moved again, with the task manager the
    only way out.

    On expiry nsExec pushes the string "timeout" instead of an exit code, which
    the caller reads as "not zero" and answers with the by-name fallback, so a
    bound turns a hang into the slower path rather than into a failure.
    """
    calls = re.findall(r"nsExec::Exec[^`\n]*", hook_text)
    assert len(calls) == EXPECTED_NSEXEC_CALLS, f"expected {EXPECTED_NSEXEC_CALLS} nsExec calls, found {len(calls)}"

    for call in calls:
        found = re.search(r"/TIMEOUT=(\d+)", call)
        print(f"  {found.group(0) if found else 'UNBOUNDED':<15} {call[:64]}")
        assert found, f"this call can wait forever and would hang an upgrade: {call}"
        assert int(found.group(1)) <= 120_000, (
            f"a {int(found.group(1)) // 1000} second bound is long enough that a user "
            f"reads it as a hang, which is the thing being prevented"
        )


# The static assertions above describe the hook. The test below runs it.

pytestmark_windows = pytest.mark.skipif(
    sys.platform != "win32",
    reason="the hook is PowerShell in a Windows installer; there is nothing to execute elsewhere",
)


def _spawn(exe: Path) -> subprocess.Popen:
    return subprocess.Popen(
        # Outlives any wait below; every test kills it in its finally block. A
        # sleep shorter than the hook's own run could end on its own and pass
        # for a stop.
        [str(exe), "-NoProfile", "-NonInteractive", "-Command", "Start-Sleep -Seconds 900"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _write_pid_file(data_dir: Path, pid: int, start_epoch: int) -> None:
    """Write a pid file in PostgreSQL's own layout: pid, data dir, start time."""
    pgdata = data_dir / "pgdata"
    pgdata.mkdir(parents=True, exist_ok=True)
    (pgdata / "postmaster.pid").write_text(f"{pid}\n{pgdata}\n{start_epoch}\n5432\n", encoding="ascii")


def _run(command: str, data_dir: Path) -> None:
    env = dict(os.environ)
    env["OE_DATA_DIR"] = str(data_dir)
    env.pop("DATA_DIR", None)
    env.pop("OE_CLI_DATA_DIR", None)
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
        env=env,
        capture_output=True,
        text=True,
        # The hook itself is bounded by nsExec's /TIMEOUT in the installer. Here
        # a loaded Windows runner has taken longer than 120 s just to start
        # PowerShell and query the process table, which failed the run without
        # saying anything about the hook.
        timeout=600,
    )


def _still_running(proc: subprocess.Popen) -> bool:
    time.sleep(1.0)
    return proc.poll() is None


def _stopped_within(proc: subprocess.Popen, seconds: float = 15.0) -> bool:
    """A stopped process can take a moment to leave the table on a busy machine."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(0.25)
    return False


@pytest.fixture
def impostor_postgres() -> Iterator[Path]:
    """A real executable actually named postgres.exe.

    The guard reads the process name Windows reports, so a test that fakes the
    name in a string proves nothing. Copying an executable is the cheapest way
    to make Windows report the name for real.
    """
    staging = Path(tempfile.mkdtemp(prefix="oe-hook-test-"))
    source = Path(os.environ["SYSTEMROOT"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    target = staging / "postgres.exe"
    shutil.copy2(source, target)
    yield target
    shutil.rmtree(staging, ignore_errors=True)


@pytestmark_windows
def test_it_stops_the_postmaster_its_pid_file_names(postmaster_command: str, impostor_postgres: Path) -> None:
    """The positive control, without which the two refusals below prove nothing."""
    with tempfile.TemporaryDirectory() as directory:
        proc = _spawn(impostor_postgres)
        try:
            _write_pid_file(Path(directory), proc.pid, int(time.time()))
            _run(postmaster_command, Path(directory))
            stopped = _stopped_within(proc)
            print(f"postmaster pid {proc.pid}: stopped={stopped}")
            assert stopped, "the hook left the cluster running that its own pid file named"
        finally:
            if proc.poll() is None:
                proc.kill()


@pytestmark_windows
def test_it_leaves_a_process_that_is_not_a_postmaster_alone(postmaster_command: str) -> None:
    """A stale pid file whose pid now belongs to something else entirely."""
    with tempfile.TemporaryDirectory() as directory:
        real_powershell = Path(os.environ["SYSTEMROOT"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        proc = _spawn(real_powershell)
        try:
            _write_pid_file(Path(directory), proc.pid, int(time.time()))
            _run(postmaster_command, Path(directory))
            survived = _still_running(proc)
            print(f"unrelated pid {proc.pid}: survived={survived}")
            assert survived, "the hook stopped a process that was never a postmaster"
        finally:
            if proc.poll() is None:
                proc.kill()


@pytestmark_windows
def test_it_leaves_a_recycled_pid_alone(postmaster_command: str, impostor_postgres: Path) -> None:
    """Right name, wrong process: the start time is what tells them apart."""
    with tempfile.TemporaryDirectory() as directory:
        proc = _spawn(impostor_postgres)
        try:
            _write_pid_file(Path(directory), proc.pid, int(time.time()) - 9000)
            _run(postmaster_command, Path(directory))
            survived = _still_running(proc)
            print(f"recycled pid {proc.pid}: survived={survived}")
            assert survived, (
                "the hook stopped a process whose start time did not match the pid "
                "file, which is another PostgreSQL that inherited the pid"
            )
        finally:
            if proc.poll() is None:
                proc.kill()


@pytestmark_windows
def test_it_follows_the_pointer_to_a_relocated_cluster(postmaster_command: str, impostor_postgres: Path) -> None:
    """A data directory PostgreSQL cannot use keeps its cluster elsewhere.

    The backend then writes the cluster's path into ``pgdata.location`` and
    leaves ``<data dir>/pgdata`` absent. A hook that only looks in the default
    place finds no pid file and stops nothing, which is the same quiet no-op
    the positive control above exists to rule out, so the relocated layout gets
    its own positive control, under a data directory named the way the
    affected accounts are.
    """
    with tempfile.TemporaryDirectory() as directory:
        data_dir = Path(directory) / "田田" / ".openestimate"
        data_dir.mkdir(parents=True)
        cluster_home = Path(directory) / "clusters" / "0123456789abcdef"
        proc = _spawn(impostor_postgres)
        try:
            _write_pid_file(cluster_home, proc.pid, int(time.time()))
            (data_dir / "pgdata.location").write_text(str(cluster_home / "pgdata"), encoding="utf-8")
            assert not (data_dir / "pgdata").exists()
            _run(postmaster_command, data_dir)
            stopped = _stopped_within(proc)
            print(f"relocated postmaster pid {proc.pid}: stopped={stopped}")
            assert stopped, "the hook did not follow pgdata.location to the cluster the backend placed elsewhere"
        finally:
            if proc.poll() is None:
                proc.kill()
