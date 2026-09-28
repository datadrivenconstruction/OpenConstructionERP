#!/usr/bin/env python3
"""Authenticode-sign every Windows executable and library under some folders.

Why signing the installer is not enough. Windows 11 Smart App Control checks
every executable file as the loader maps it, not only the file that was
downloaded, and it has no per-app exception. The desktop sidecar is a
PyInstaller onefile build: at each start it unpacks about 490 ``.exe``,
``.dll`` and ``.pyd`` files and runs them from the unpacked folder. Measured on
the 17.x sidecar, 409 of those 492 carried no signature at all (every
PostgreSQL program, and most of scipy, sklearn, pandas, pyarrow, numpy), and the
launcher, the sidecar and the uninstaller carried none either. A signature on
the installer reaches none of them.

So the release pipeline signs from the inside out: the Python packages the
sidecar collects, before PyInstaller packs them (the archive seals them and no
later pass can reach them); then the onefile executable PyInstaller writes; then
the converters shipped as resources; and finally Tauri signs the launcher,
the sidecar copy, the NSIS plugins, the uninstaller and the installer through
``bundle.windows.signCommand``.

The signer is a command given in ``WINDOWS_SIGN_COMMAND`` as a JSON array of
arguments, the same ``cmd`` plus ``args`` shape Tauri's ``signCommand`` takes,
where ``%1`` stands for the file. JSON rather than a shell string because the
command carries Windows paths, and POSIX splitting eats their backslashes. That keeps
this script independent of which service holds the key (Azure Artifact
Signing through signtool, or a Key Vault certificate through AzureSignTool).

Files that already carry a valid signature (the Python Software Foundation's
own DLLs, Microsoft's runtime, Intel's MKL) are left alone: re-signing another
publisher's file would replace their name with ours.

Exit codes: 0 when every candidate ends up with a valid signature, 1 when any
does not, 2 on a usage error. ``--list`` signs nothing and only prints what
would be signed, so the selection can be checked without a certificate.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

#: Portable-executable suffixes the Windows loader runs or maps.
PE_SUFFIXES = frozenset({".exe", ".dll", ".pyd"})

COMMAND_ENV = "WINDOWS_SIGN_COMMAND"
FILE_TOKEN = "%1"


def find_candidates(roots: Iterable[Path]) -> list[Path]:
    """Every PE file under ``roots``, sorted, each listed once."""
    found: set[Path] = set()
    for root in roots:
        if root.is_file():
            if root.suffix.lower() in PE_SUFFIXES:
                found.add(root.resolve())
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in PE_SUFFIXES:
                found.add(path.resolve())
    return sorted(found)


def expand_command(template: str, file: Path) -> list[str]:
    """Turn the JSON argument array into argv for one file.

    ``%1`` is replaced as a whole argument or inside one, so ``/f:%1`` style
    flags work too. A command without ``%1`` is refused rather than run,
    because it would sign nothing and report success.
    """
    try:
        parts = json.loads(template)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{COMMAND_ENV} must be a JSON array of strings: {exc}") from exc
    if not isinstance(parts, list) or not parts or not all(isinstance(p, str) for p in parts):
        raise ValueError(f"{COMMAND_ENV} must be a non-empty JSON array of strings")
    if not any(FILE_TOKEN in p for p in parts):
        raise ValueError(f"{COMMAND_ENV} must contain {FILE_TOKEN} where the file path goes")
    return [part.replace(FILE_TOKEN, str(file)) for part in parts]


def find_signtool() -> str | None:
    """The newest x64 signtool.exe from the Windows SDK, if there is one."""
    kits = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"
    tools = sorted(kits.glob("*/x64/signtool.exe")) if kits.is_dir() else []
    return str(tools[-1]) if tools else None


def is_signed(signtool: str, file: Path) -> bool:
    """Whether ``file`` carries a signature Windows accepts."""
    result = subprocess.run(
        [signtool, "verify", "/pa", "/q", str(file)],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _sign_one(template: str, file: Path) -> tuple[Path, int, str]:
    result = subprocess.run(expand_command(template, file), capture_output=True, text=True, check=False)
    return file, result.returncode, (result.stderr or result.stdout).strip()[-400:]


def run(roots: Sequence[Path], *, list_only: bool, jobs: int) -> int:
    missing = [str(r) for r in roots if not r.exists()]
    if missing:
        print(f"error: no such path: {', '.join(missing)}", file=sys.stderr)
        return 2

    candidates = find_candidates(roots)
    signtool = find_signtool()
    if signtool is None:
        # Without signtool we cannot tell which files are already signed, and
        # we cannot check our own work. Signing blind is not an option.
        print("error: signtool.exe was not found in the Windows SDK", file=sys.stderr)
        return 1

    already = {f for f in candidates if is_signed(signtool, f)}
    todo = [f for f in candidates if f not in already]
    print(f"{len(candidates)} PE files, {len(already)} already signed, {len(todo)} to sign")

    if list_only:
        for f in todo:
            print(f"  would sign {f}")
        return 0

    template = os.environ.get(COMMAND_ENV, "").strip()
    if not template:
        print(f"error: {COMMAND_ENV} is not set", file=sys.stderr)
        return 2
    try:
        expand_command(template, Path("probe.dll"))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    failures: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for file, code, tail in pool.map(lambda f: _sign_one(template, f), todo):
            if code != 0:
                failures.append(f"{file}: exit {code}: {tail}")

    unverified = [f for f in todo if not is_signed(signtool, f)]
    for line in failures:
        print(f"::error title=Signing failed::{line}")
    for f in unverified:
        print(f"::error title=Signature does not verify::{f}")
    signed = len(todo) - len(unverified)
    print(f"signed and verified {signed} of {len(todo)}; {len(already)} kept their own publisher's signature")
    return 0 if not failures and not unverified else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", type=Path, help="folders or files to sign")
    parser.add_argument("--list", action="store_true", help="print what would be signed, sign nothing")
    parser.add_argument("--jobs", type=int, default=8, help="parallel signing calls (default 8)")
    args = parser.parse_args(argv)
    return run(args.paths, list_only=args.list, jobs=args.jobs)


if __name__ == "__main__":
    sys.exit(main())
