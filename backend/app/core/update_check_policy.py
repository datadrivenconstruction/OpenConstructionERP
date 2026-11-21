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

Both were opt-outs, which left the third case unhandled: an installation nobody
had configured still asked. The automatic check is an opt-in now, held on the
workspace branding record beside the support destination and the Legal-link flag
- server-side, admin-only to write, public to read, so every user can see whether
their installation asks and only an administrator can change the answer. The two
switches above still win over it: a workspace record that says "ask" while an
operator set :data:`DISABLE_ENV` or a user pressed the launcher's opt-out is a
contradiction, and it resolves against sending anything outward.
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

#: How long an automatic answer is held before the internet is asked again: a
#: day. The web UI holds its copy for the same window
#: (``VERSION_CHECK_TTL_MS`` in ``frontend/src/shared/ui/UpdateChecker.tsx``).
#: About's "Check for updates" button skips it.
VERSION_CHECK_TTL_S = 24 * 60 * 60


def _env_flag_is_on(raw: str | None) -> bool:
    """Mirror ``env_flag_is_on`` in the launcher: 1, true, yes, on, any case."""
    return (raw or "").strip().lower() in _TRUTHY


def opt_out_path(home: Path | None = None) -> Path:
    """Where the launcher records the user's "Turn off update checks"."""
    return (home if home is not None else Path.home()) / ".openestimate" / OPT_OUT_FILE


def workspace_check_enabled(data_dir: Path | None = None) -> bool:
    """Whether the workspace record says the automatic check is on.

    Reads ``update_check_enabled`` off the branding record, which sanitises on the
    way out, so only an exact ``True`` counts: a corrupt file, a hand-edited
    ``"yes"`` and a missing key all answer ``False``. The import is inside the
    function to keep this module stdlib-only at import time and to leave no import
    cycle with the branding module, which does not know this one exists.

    Anything unreadable answers ``False`` rather than raising, for the reason the
    rest of this module does: the endpoint that reads this key is the one that
    would make the connection, so it must not fail inside a request handler, and
    silence is the answer that sends nothing outward.
    """
    try:
        from app.core.app_branding import read_branding

        return read_branding(data_dir=data_dir).get("update_check_enabled") is True
    except Exception:  # noqa: BLE001 - an unreadable record means "off", never a 500
        return False


def update_check_disabled(
    home: Path | None = None,
    *,
    data_dir: Path | None = None,
    workspace_enabled: bool | None = None,
) -> bool:
    """Whether the version check must stay off the network.

    Args:
        home: Home folder to look for the opt-out file in. Defaults to the
            current user's, which is the folder the launcher writes to.
        data_dir: Where the workspace branding record lives. Only read when
            ``workspace_enabled`` is None; both default to the same resolution
            the rest of the backend uses.
        workspace_enabled: The record's answer, stated by a caller that already
            holds it. This is the seam the tests use to pin the precedence
            without writing a file, and the one an endpoint that has just read the
            record for its own response can use instead of reading it twice.

    Returns:
        True when an administrator set :data:`DISABLE_ENV`, when the user turned
        the check off from the launcher's notice, or - the case this setting
        exists for - when nobody has turned the workspace setting on.
    """
    if _env_flag_is_on(os.environ.get(DISABLE_ENV)):
        return True
    try:
        if opt_out_path(home).exists():
            return True
    except OSError:
        # A home folder we cannot stat is not a "yes, check". Asking the
        # internet is the direction that needs permission, so staying quiet is
        # the safe answer when we cannot tell.
        return True
    asked = workspace_enabled if workspace_enabled is not None else workspace_check_enabled(data_dir)
    return asked is not True
