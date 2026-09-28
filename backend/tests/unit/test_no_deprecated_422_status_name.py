"""The 422 status constant is spelled by its current name everywhere.

Starlette 0.48 renamed ``HTTP_422_UNPROCESSABLE_ENTITY`` to
``HTTP_422_UNPROCESSABLE_CONTENT`` (RFC 9110) and keeps the old one only as a
deprecated alias. The backend was moved over in one sweep and
``pyproject.toml`` floors starlette at 0.48.0 so the new name always exists.
This test keeps the old spelling from creeping back in through copied code.
"""

from __future__ import annotations

import re
from pathlib import Path

import starlette.status

_BACKEND = Path(__file__).resolve().parents[2]
_OLD_NAME = "HTTP_422_UNPROCESSABLE_" + "ENTITY"
_OLD_NAME_RE = re.compile(rf"\b{_OLD_NAME}\b")


def test_installed_starlette_has_the_current_name() -> None:
    assert starlette.status.HTTP_422_UNPROCESSABLE_CONTENT == 422


def test_backend_code_does_not_use_the_deprecated_name() -> None:
    offenders: list[str] = []
    for root in ("app", "tests"):
        for path in sorted((_BACKEND / root).rglob("*.py")):
            if path == Path(__file__).resolve():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if _OLD_NAME_RE.search(line):
                    offenders.append(f"{path.relative_to(_BACKEND).as_posix()}:{lineno}")
    assert not offenders, f"use status.HTTP_422_UNPROCESSABLE_CONTENT instead of {_OLD_NAME}: " + ", ".join(offenders)
