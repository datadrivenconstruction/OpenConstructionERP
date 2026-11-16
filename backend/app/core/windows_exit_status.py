"""Explain how a Windows program died, in words a user can act on.

A native program that Windows stops reports an NTSTATUS as its exit code, and
Python hands that over as a signed 32-bit int: ``-1073741674`` is 0xC0000096.
Shown alone, that number tells the user nothing and sends support guessing. This
module maps the statuses we see from converters (and from the desktop backend)
to a cause id the UI can dispatch on, a plain sentence and a fix.

It also holds the Visual C++ runtime pre-flight: the DDC packages ship their
own runtime beside the executable, and a folder that has neither its own copy
nor the system one cannot start at all.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

#: Runtime DLLs a 64-bit MSVC 2015-2022 binary loads. ``vcruntime140_1.dll``
#: only exists in redistributables from 2019 on, which is why an old install
#: of "Visual C++ 2015" still fails.
VC_RUNTIME_DLLS: tuple[str, ...] = ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")

VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
DOTNET_URL = "https://dotnet.microsoft.com/download/dotnet"


@dataclass(frozen=True)
class ExitStatusInfo:
    """What a Windows exit status means for the user."""

    status: int
    name: str
    cause: str
    message: str
    fix: str
    actions: tuple[str, ...]

    @property
    def hex(self) -> str:
        """The status as Windows documents it, e.g. ``0xC0000096``."""
        return f"0x{self.status:08X}"


def _info(status: int, name: str, cause: str, message: str, fix: str, *actions: str) -> ExitStatusInfo:
    return ExitStatusInfo(status, name, cause, message, fix, tuple(actions))


_REINSTALL = "Press Uninstall and then Install for this converter so its folder is rebuilt from empty."
_SEND = "If it keeps happening, send the file and this message to info@datadrivenconstruction.io."

_KNOWN: dict[int, ExitStatusInfo] = {
    i.status: i
    for i in (
        _info(
            0xC0000135,
            "STATUS_DLL_NOT_FOUND",
            "runtime_missing",
            "could not start because a library it needs was not found.",
            f"Install the Microsoft Visual C++ Redistributable (x64) from {VC_REDIST_URL}. {_REINSTALL}",
            "install_vc_redist",
            "reinstall_converter",
        ),
        _info(
            0xC0000142,
            "STATUS_DLL_INIT_FAILED",
            "runtime_missing",
            "could not start because one of its libraries failed to initialise.",
            f"Install the Microsoft Visual C++ Redistributable (x64) from {VC_REDIST_URL} and restart the computer. "
            f"{_REINSTALL}",
            "install_vc_redist",
            "reinstall_converter",
        ),
        _info(
            0xC0000139,
            "STATUS_ENTRYPOINT_NOT_FOUND",
            "runtime_outdated",
            "found an older version of one of its libraries than it was built for.",
            f"Install the latest Microsoft Visual C++ Redistributable (x64) from {VC_REDIST_URL}. {_REINSTALL}",
            "install_vc_redist",
            "reinstall_converter",
        ),
        _info(
            0xC000007B,
            "STATUS_INVALID_IMAGE_FORMAT",
            "damaged_install",
            "was refused by Windows because a file in its folder is damaged or does not belong there.",
            _REINSTALL,
            "reinstall_converter",
        ),
        _info(
            0xC0000005,
            "STATUS_ACCESS_VIOLATION",
            "native_crash",
            "crashed while reading this file.",
            f"Install the latest Microsoft Visual C++ Redistributable (x64) from {VC_REDIST_URL}, since an outdated "
            f"runtime is a common cause. If only this file fails, re-save it in the authoring program and try again. "
            f"{_SEND}",
            "install_vc_redist",
            "retry",
        ),
        _info(
            0xC0000409,
            "STATUS_STACK_BUFFER_OVERRUN",
            "native_crash",
            "stopped itself after detecting an internal error while reading this file.",
            f"Re-save the file in the authoring program and try again. {_SEND}",
            "retry",
        ),
        _info(
            0xC00000FD,
            "STATUS_STACK_OVERFLOW",
            "native_crash",
            "ran out of stack while reading this file, usually because of very deeply nested content.",
            f"Split or simplify the model and try again. {_SEND}",
            "retry",
        ),
        _info(
            0xC0000096,
            "STATUS_PRIVILEGED_INSTRUCTION",
            "blocked_instruction",
            "was stopped by Windows on a processor instruction it is not allowed to run. This is not a missing "
            "runtime, so reinstalling Visual C++ does not help.",
            "It usually comes from security software that hooks into the converter, or from a virtual machine or "
            "remote desktop host that hides processor features. Add the converter folder to the antivirus "
            f"exclusions, or run the conversion on a physical Windows computer. {_REINSTALL} {_SEND}",
            "check_security_software",
            "reinstall_converter",
        ),
        _info(
            0xC000001D,
            "STATUS_ILLEGAL_INSTRUCTION",
            "cpu_unsupported",
            "uses a processor instruction this computer does not support.",
            "Run the conversion on a newer computer, or, in a virtual machine, enable passing the host processor "
            f"features (AVX2) to the guest. {_SEND}",
            "use_other_computer",
        ),
        _info(
            0xC0000017,
            "STATUS_NO_MEMORY",
            "out_of_memory",
            "ran out of memory.",
            "Close other programs, or convert the model on a computer with more memory, or split it into smaller "
            "files.",
            "retry",
        ),
        _info(
            0xC000012D,
            "STATUS_COMMITMENT_LIMIT",
            "out_of_memory",
            "ran out of memory (the Windows page file is full).",
            "Close other programs or enlarge the Windows page file, then try again.",
            "retry",
        ),
        _info(
            0xC0000022,
            "STATUS_ACCESS_DENIED",
            "blocked",
            "was denied access by Windows.",
            "Security software or folder permissions blocked it. Add the converter folder to the antivirus "
            f"exclusions and make sure your account can write to it. {_REINSTALL}",
            "check_security_software",
            "check_permissions",
        ),
        _info(
            0xC000013A,
            "STATUS_CONTROL_C_EXIT",
            "stopped",
            "was stopped before it finished.",
            "Start the conversion again.",
            "retry",
        ),
        _info(
            0x80008096,
            "FrameworkMissingFailure",
            "dotnet_missing",
            "needs a .NET runtime that is not installed.",
            f"Install the .NET Desktop Runtime (x64) from {DOTNET_URL}, then try again.",
            "install_dotnet",
        ),
        _info(
            0xE0434352,
            "CLR_EXCEPTION",
            "native_crash",
            "stopped on an unhandled .NET error.",
            f"Install the latest .NET Desktop Runtime (x64) from {DOTNET_URL} and try again. {_SEND}",
            "install_dotnet",
            "retry",
        ),
    )
}


def _unsigned(code: int) -> int:
    return code & 0xFFFFFFFF


def is_windows_status(code: int | None) -> bool:
    """True for exit codes that are an NTSTATUS error or a high-bit HRESULT, not a program's own number."""
    if code is None:
        return False
    return _unsigned(code) >= 0x80000000


def describe_exit_code(code: int | None) -> ExitStatusInfo | None:
    """The known Windows status behind an exit code, signed or unsigned, or ``None``."""
    if not is_windows_status(code):
        return None
    return _KNOWN.get(_unsigned(code))  # type: ignore[arg-type]


def plain_exit_message(code: int | None, program: str) -> str:
    """One readable sentence for how ``program`` ended; a negative code is never shown alone.

    Args:
        code: Exit code as Python reports it.
        program: Subject of the sentence, e.g. ``"The RVT converter"``.

    Returns:
        A sentence with the cause and fix for a known status, a hex status with a
        generic next step for an unknown one, and the plain number otherwise.
    """
    info = describe_exit_code(code)
    if info is not None:
        return f"{program} {info.message} (Windows error {info.hex}) {info.fix}"
    if code is not None and is_windows_status(code):
        return (
            f"{program} was stopped by Windows (error 0x{_unsigned(code):08X}). Restart the computer and try "
            f"again. {_SEND}"
        )
    return f"{program} stopped with error code {code}."


def vc_runtime_imports(exe: Path) -> tuple[str, ...]:
    """Visual C++ runtime DLLs the executable names in its import table.

    Import names are stored as plain ASCII in the image, so a byte search finds
    them without a PE parser. Only the executable itself is read: a runtime
    needed by one of its own libraries is not asked for, so this can miss a
    requirement but never invents one.
    """
    import mmap

    try:
        with exe.open("rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as image:
            found = []
            for name in VC_RUNTIME_DLLS:
                stem = name[: -len(".dll")]
                variants = {f"{stem}.dll", f"{stem.upper()}.dll", f"{stem.upper()}.DLL", name.upper()}
                if any(image.find(v.encode("ascii") + b"\x00") != -1 for v in variants):
                    found.append(name)
            return tuple(found)
    except (OSError, ValueError):
        return ()


def missing_vc_runtime(
    exe_dir: Path, *, system_dir: Path | None = None, required: tuple[str, ...] = VC_RUNTIME_DLLS
) -> list[str]:
    """Visual C++ runtime DLLs that neither the converter folder nor Windows provides.

    Args:
        exe_dir: Folder of the converter executable (packages ship their runtime there).
        system_dir: Windows system folder; defaults to ``%SystemRoot%\\System32``. Passing
            it forces the check on any platform, which is how tests run it.
        required: The DLLs to look for, normally ``vc_runtime_imports`` of the executable.

    Returns:
        Missing DLL names; empty off Windows, when everything is present, or when
        the system folder cannot be located.
    """
    if system_dir is None:
        if sys.platform != "win32":
            return []
        root = os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR")
        if not root:
            return []
        system_dir = Path(root) / "System32"
    return [name for name in required if not (exe_dir / name).is_file() and not (system_dir / name).is_file()]
