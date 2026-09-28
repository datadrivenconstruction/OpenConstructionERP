"""Whether this install may ask the internet for a newer version.

The product carries two update checks. The desktop launcher asks GitHub for
itself (``desktop/src-tauri/src/update_check.rs``), and the signed-in web UI
asks the backend, which then asks PyPI and GitHub
(``GET /api/system/version-check`` in ``app/main.py``). Both are outbound
requests the user did not start, so both have to stop when the user or an
administrator says so.

Until this module existed only the launcher listened. The notice the launcher
paints offers "Turn off update checks" and records the answer in
``~/.openestimate/no-update-check``, a file whose own text says the app "does
not check for a newer version while this file exists". The backend never read
it, so the next sign-in sent the same two requests anyway. An administrator
setting ``OE_DISABLE_UPDATE_CHECK`` was ignored by the backend the same way.

This reads both switches with the launcher's exact spelling, so turning the
check off in either place turns it off in both.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Same name the launcher reads (``update_check::DISABLE_ENV``).
DISABLE_ENV = "OE_DISABLE_UPDATE_CHECK"

#: Same file the launcher writes (``update_check::OPT_OUT_FILE``), in the same
#: folder beside the launcher log.
OPT_OUT_FILE = "no-update-check"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _env_flag_is_on(raw: str | None) -> bool:
    """Mirror ``env_flag_is_on`` in the launcher: 1, true, yes, on, any case."""
    return (raw or "").strip().lower() in _TRUTHY


def opt_out_path(home: Path | None = None) -> Path:
    """Where the launcher records the user's "Turn off update checks"."""
    return (home if home is not None else Path.home()) / ".openestimate" / OPT_OUT_FILE


def update_check_disabled(home: Path | None = None) -> bool:
    """Whether the version check must stay off the network.

    Args:
        home: Home folder to look for the opt-out file in. Defaults to the
            current user's, which is the folder the launcher writes to.

    Returns:
        True when an administrator set :data:`DISABLE_ENV` or the user turned
        the check off from the launcher's notice.
    """
    if _env_flag_is_on(os.environ.get(DISABLE_ENV)):
        return True
    try:
        return opt_out_path(home).exists()
    except OSError:
        # A home folder we cannot stat is not a "yes, check". Asking the
        # internet is the direction that needs permission, so staying quiet is
        # the safe answer when we cannot tell.
        return True
