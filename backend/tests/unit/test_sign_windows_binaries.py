"""scripts/sign_windows_binaries.py picks the right files and builds the right argv.

The signing itself needs a certificate and a Windows runner, so what is checked
here is everything that decides WHAT gets signed and HOW the command is formed.
A mistake in either is invisible on a run with no certificate, and on a run
with one it ships a half-signed sidecar that Smart App Control still blocks.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "sign_windows_binaries.py"


@pytest.fixture(scope="module")
def signer():
    spec = importlib.util.spec_from_file_location("sign_windows_binaries", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_every_loadable_suffix_is_found_and_nothing_else(signer, tmp_path: Path) -> None:
    (tmp_path / "pkg" / "bin").mkdir(parents=True)
    wanted = [
        tmp_path / "pkg" / "bin" / "postgres.exe",
        tmp_path / "pkg" / "_core.cp312-win_amd64.pyd",
        tmp_path / "pkg" / "libpq.DLL",
    ]
    ignored = [tmp_path / "pkg" / "data.json", tmp_path / "pkg" / "readme.txt", tmp_path / "pkg" / "x.py"]
    for f in wanted + ignored:
        f.write_bytes(b"MZ")

    found = signer.find_candidates([tmp_path, wanted[0]])

    assert found == sorted(p.resolve() for p in wanted)


def test_the_file_replaces_the_token_inside_an_argument(signer) -> None:
    template = json.dumps([r"C:\Program Files (x86)\Windows Kits\signtool.exe", "sign", "/f:%1", "%1"])
    argv = signer.expand_command(template, Path(r"C:\a b\x.dll"))

    # Backslashes and spaces survive, which POSIX shell splitting would not give.
    assert argv[0] == r"C:\Program Files (x86)\Windows Kits\signtool.exe"
    assert argv[2] == "/f:" + str(Path(r"C:\a b\x.dll"))
    assert argv[3] == str(Path(r"C:\a b\x.dll"))


@pytest.mark.parametrize(
    "template",
    [
        '["signtool", "sign"]',  # no %1: would sign nothing and report success
        "signtool sign %1",  # not JSON
        "[]",
        '["signtool", 1, "%1"]',
    ],
)
def test_a_command_that_cannot_name_the_file_is_refused(signer, template: str) -> None:
    with pytest.raises(ValueError):
        signer.expand_command(template, Path("x.dll"))


def test_a_missing_path_is_a_usage_error(signer, tmp_path: Path) -> None:
    assert signer.run([tmp_path / "nope"], list_only=True, jobs=1) == 2


def test_without_signtool_nothing_is_signed_blind(signer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "a.dll").write_bytes(b"MZ")
    monkeypatch.setattr(signer, "find_signtool", lambda: None)
    assert signer.run([tmp_path], list_only=False, jobs=1) == 1


def test_a_file_that_does_not_verify_after_signing_fails_the_run(
    signer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("ours.pyd", "theirs.dll"):
        (tmp_path / name).write_bytes(b"MZ")
    monkeypatch.setattr(signer, "find_signtool", lambda: "signtool")
    # "theirs" already carries its publisher's signature, "ours" never verifies.
    monkeypatch.setattr(signer, "is_signed", lambda _tool, f: f.name == "theirs.dll")
    signed: list[str] = []
    monkeypatch.setattr(signer, "_sign_one", lambda _t, f: (signed.append(f.name), (f, 0, ""))[1])
    monkeypatch.setenv(signer.COMMAND_ENV, '["signer", "%1"]')

    assert signer.run([tmp_path], list_only=False, jobs=1) == 1
    # The other publisher's file was left alone.
    assert signed == ["ours.pyd"]


def test_a_clean_run_signs_only_the_unsigned(signer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ours.pyd", "theirs.dll"):
        (tmp_path / name).write_bytes(b"MZ")
    done: set[str] = {"theirs.dll"}
    monkeypatch.setattr(signer, "find_signtool", lambda: "signtool")
    monkeypatch.setattr(signer, "is_signed", lambda _tool, f: f.name in done)

    def _sign(_t, f):
        done.add(f.name)
        return f, 0, ""

    monkeypatch.setattr(signer, "_sign_one", _sign)
    monkeypatch.setenv(signer.COMMAND_ENV, '["signer", "%1"]')

    assert signer.run([tmp_path], list_only=False, jobs=2) == 0
    assert done == {"ours.pyd", "theirs.dll"}


# --- scripts/setup_windows_signing.py ------------------------------------------------

SETUP_PATH = SCRIPT_PATH.parent / "setup_windows_signing.py"


@pytest.fixture(scope="module")
def setup():
    spec = importlib.util.spec_from_file_location("setup_windows_signing", SETUP_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _full(setup) -> dict[str, str]:
    return dict.fromkeys(setup.REQUIRED, "x")


def test_no_secrets_is_off_one_missing_is_partial_all_is_on(setup) -> None:
    assert setup.classify({}) == ("off", list(setup.REQUIRED))
    env = _full(setup)
    env["AZURE_CLIENT_SECRET"] = " "
    assert setup.classify(env) == ("partial", ["AZURE_CLIENT_SECRET"])
    assert setup.classify(_full(setup)) == ("on", [])


@pytest.mark.parametrize(
    ("ref", "expected"), [("v18.1.1", True), ("main", False), ("wip/wintrust", False), ("v", False)]
)
def test_only_version_tags_sign(setup, ref: str, expected: bool) -> None:
    assert setup.is_release_ref(ref) is expected


def test_the_sign_command_timestamps_and_names_the_file(setup, signer) -> None:
    argv = setup.sign_argv("C:/sdk/signtool.exe", "C:/c/Azure.CodeSigning.Dlib.dll", "C:/m.json")
    assert argv[-1] == "%1"
    assert argv[argv.index("/tr") + 1] == setup.TIMESTAMP_URL
    assert argv[argv.index("/dlib") + 1].endswith(setup.DLIB_NAME)
    # The same argv drives the deep signer, so it has to pass its validation.
    assert signer.expand_command(json.dumps(argv), Path("a.dll"))[-1] == "a.dll"
    conf = setup.tauri_config(argv)["bundle"]["windows"]["signCommand"]
    assert [conf["cmd"], *conf["args"]] == argv


def test_the_secret_never_reaches_a_file_or_a_command_line(setup) -> None:
    env = _full(setup)
    env["AZURE_CLIENT_SECRET"] = "s3cr3t-value"
    written = json.dumps(setup.metadata(env)) + json.dumps(setup.sign_argv("a", "b", "c"))
    assert "s3cr3t-value" not in written


def _run_main(setup, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, env: dict[str, str]) -> tuple[int, str]:
    for name in setup.REQUIRED:
        monkeypatch.delenv(name, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    github_env = tmp_path / "github_env"
    github_env.write_text("")
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return setup.main(), github_env.read_text()


def test_without_secrets_the_pipeline_is_untouched(setup, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    code, written = _run_main(setup, monkeypatch, tmp_path, {"RELEASE_REF": "v18.1.1"})
    assert code == 0
    assert written == "WINDOWS_SIGNING=off\n"


def test_half_a_configuration_fails_the_run(setup, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    code, written = _run_main(setup, monkeypatch, tmp_path, {"RELEASE_REF": "v18.1.1", "AZURE_CLIENT_ID": "x"})
    assert code == 1
    assert written == ""


def test_a_branch_build_stays_unsigned_even_with_secrets(
    setup, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code, written = _run_main(setup, monkeypatch, tmp_path, {**_full(setup), "RELEASE_REF": "main"})
    assert code == 0
    assert written == "WINDOWS_SIGNING=off\n"
