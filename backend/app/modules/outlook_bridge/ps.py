# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""PowerShell COM runner for the Outlook bridge.

Discipline learned the hard way and kept as law here:

- NEVER put message content on a command line. Windows caps a command
  line at 32,767 characters, an HTML email runs ~144,000 - and Python
  surfaces that WinError 206 as ``FileNotFoundError``, which looks like
  a missing powershell.exe and burns hours. Every run is a SCRIPT FILE
  plus a JSON payload file in its own temp dir.
- NEVER interpolate user text into the script source. PowerShell parses
  curly quotes as delimiters; a supplier name with one would break the
  script. The script source is a static constant; all data crosses in
  the JSON payload the script reads with ConvertFrom-Json.
- The answer comes back through a UTF-8 result FILE, not stdout: the
  Windows PowerShell 5.1 console re-encodes stdout through the OEM
  codepage and mangles anything beyond ASCII (a supplier name with a
  curly quote came back as '?'). Scripts write their JSON to the
  ``_out_path`` the payload names; stdout is only a debugging fallback.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Hard wall-clock bound per COM run. Opening a draft is ~2s; a first-run
#: Outlook cold start can take 30s+. A hung Outlook must not pin a worker.
_PS_TIMEOUT_S = 120


class OutlookUnavailable(Exception):
    """COM automation is not possible here (platform, no Outlook, timeout)."""


def _run_sync(script_source: str, payload: dict[str, Any]) -> dict[str, Any]:
    if sys.platform != "win32":
        raise OutlookUnavailable("Outlook COM automation needs Windows with desktop Outlook.")

    run_dir = Path(tempfile.gettempdir()) / "oe_outlook_bridge" / uuid.uuid4().hex[:12]
    run_dir.mkdir(parents=True, exist_ok=True)
    payload_path = run_dir / "payload.json"
    script_path = run_dir / "run.ps1"
    out_path = run_dir / "result.json"
    payload = {**payload, "_out_path": str(out_path)}
    # utf-8-sig: PowerShell 5.1 only reads a .ps1 as UTF-8 when it carries a
    # BOM; without one, any non-ASCII char in the STATIC script would garble.
    payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")
    script_path.write_text(script_source, encoding="utf-8-sig")

    try:
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-PayloadPath",
                str(payload_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_PS_TIMEOUT_S,
        )
    except FileNotFoundError as exc:  # genuinely no powershell.exe
        raise OutlookUnavailable("powershell.exe not found on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise OutlookUnavailable(f"Outlook COM run timed out after {_PS_TIMEOUT_S}s.") from exc

    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        err = (proc.stderr or out or "no output").strip()[:800]
        raise OutlookUnavailable(f"Outlook COM run failed (exit {proc.returncode}): {err}")
    # Primary channel: the UTF-8 result file (codepage-proof).
    if out_path.exists():
        try:
            return json.loads(out_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            pass
    # Fallback: the LAST JSON line on stdout - Outlook add-ins sometimes
    # chat on stdout before our script prints.
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{") or line.startswith("["):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    raise OutlookUnavailable(f"Outlook COM run returned no JSON: {out[:300]!r}")


async def run_outlook_script(script_source: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Run one COM script off the event loop. Raises OutlookUnavailable."""
    return await asyncio.to_thread(_run_sync, script_source, payload)
