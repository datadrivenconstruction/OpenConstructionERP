"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Clean shutdown request served for the desktop launcher.

Why this exists. The desktop shell stopped its backend by killing the process
tree, which crash-stops the embedded PostgreSQL cluster on every normal close of
the app, not only on upgrade. The next start then has a write-ahead log to
replay, which on a large cluster takes minutes, and the launcher reported that
healthy-but-slow start to the user as "the application backend did not start in
time". Retrying reproduced it, because nothing had gone wrong to clear.

The clean stop is this process's own shutdown handler (``app.main``, which stops
the collaboration sweeper, disposes the engine and then stops the cluster). On
POSIX the launcher reaches it with SIGTERM. On Windows there is no signal a
windowless parent can deliver to a console child, so the honest answer is a
shutdown the backend serves for itself - this endpoint - and the launcher then
uses the same request on every platform.

An endpoint that stops the server is exactly the one nobody else may reach, so
it is guarded three times over:

* **desktop mode only** - a shared server never answers it at all;
* **loopback only** - the request must come from this machine;
* **shared secret** - the launcher generates a fresh random token for every run
  and hands it to the backend in the environment when it spawns it. The token
  never leaves the machine, and a browser cannot forge the header that carries
  it: a cross-origin request with a custom header is preflighted, and the
  preflight is refused, so a web page cannot close somebody's application by
  posting at their loopback port.

Missing configuration always refuses. A backend started without the token
environment variable cannot be stopped this way at all, which is the correct
answer for every backend the launcher did not start.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import signal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.core.loopback import is_loopback_request

logger = logging.getLogger(__name__)

#: Environment variable carrying the per-run shared secret. Set by the desktop
#: launcher on the sidecar it spawns (``desktop/src-tauri/src/main.rs``).
SHUTDOWN_TOKEN_ENV = "OE_DESKTOP_SHUTDOWN_TOKEN"

#: Header the launcher sends the secret in. A custom header is deliberate: it is
#: what forces a browser to preflight a cross-origin call and therefore what
#: keeps a web page from reaching this endpoint at all.
SHUTDOWN_TOKEN_HEADER = "X-Desktop-Shutdown-Token"  # noqa: S105 - header name, not a secret

#: Delay between answering the request and asking the process to stop, so the
#: response is on the wire before the shutdown starts. uvicorn also drains
#: in-flight requests, so this is a margin rather than the only thing keeping
#: the caller from reading a closed socket.
SHUTDOWN_SIGNAL_DELAY = 0.25


def configured_shutdown_token() -> str:
    """Return the shared secret this process will accept, empty when unset."""
    return os.environ.get(SHUTDOWN_TOKEN_ENV, "").strip()


def _forbid(detail: str) -> HTTPException:
    """Build the one refusal shape every guard uses."""
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def authorise_shutdown_request(request: Request) -> None:
    """Run the full guard chain, or raise ``HTTPException`` 403.

    Args:
        request: The incoming request.

    Raises:
        HTTPException: 403 when the backend is not the desktop sidecar, when the
            caller is not on this machine, when no shared secret is configured,
            or when the presented secret does not match it.
    """
    from app.config import desktop_mode

    if not desktop_mode():
        raise _forbid("Shutdown on request is only available in the desktop app.")

    if not is_loopback_request(request):
        raise _forbid("Shutdown on request is only available from the local machine.")

    expected = configured_shutdown_token()
    if not expected:
        raise _forbid("Shutdown on request is not configured on this backend.")

    presented = request.headers.get(SHUTDOWN_TOKEN_HEADER, "")
    # compare_digest, so a caller cannot learn the token one character at a time
    # from how long the refusal takes.
    if not presented or not secrets.compare_digest(presented, expected):
        raise _forbid("Shutdown on request requires the launcher's token.")


def _sigterm_handler_installed() -> bool:
    """True when something in this process is listening for SIGTERM.

    This is the safety the whole trigger rests on. uvicorn installs a handler
    that starts its graceful shutdown, so in the shipped server the signal means
    "run the shutdown handler". Anywhere else - a pytest run, an embedded use of
    the app object - the disposition is still the default, where SIGTERM means
    "terminate the process". Raising it there would kill the host process
    instead of asking a server to stop, so the trigger refuses instead, and the
    launcher falls back to stopping the process itself.

    ``signal.getsignal`` answers ``None`` for a handler that was installed from
    C rather than from Python; that is not a handler we can reason about, so it
    counts as absent.
    """
    handler = signal.getsignal(signal.SIGTERM)
    return handler not in (None, signal.SIG_DFL, signal.SIG_IGN)


def _raise_sigterm() -> None:
    """Deliver SIGTERM to this process, in-process.

    ``signal.raise_signal`` and not ``os.kill``: on Windows ``os.kill`` with
    SIGTERM is ``TerminateProcess``, which is the forced stop this endpoint
    exists to avoid, while ``raise_signal`` runs the handler that is installed.
    """
    try:
        signal.raise_signal(signal.SIGTERM)
    except Exception:  # noqa: BLE001 - a failed stop must not take the server down
        logger.exception("desktop shutdown: raising SIGTERM failed")


def request_process_shutdown(delay: float = SHUTDOWN_SIGNAL_DELAY) -> bool:
    """Schedule the graceful stop of this process.

    Args:
        delay: Seconds to wait before delivering the signal, so the HTTP
            response is written first.

    Returns:
        ``True`` when the stop was scheduled, ``False`` when nothing in this
        process handles SIGTERM and the caller must stop it another way.
    """
    if not _sigterm_handler_installed():
        logger.warning(
            "desktop shutdown requested, but no SIGTERM handler is installed in this process; "
            "the caller has to stop it another way"
        )
        return False

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover - the endpoint is always on a loop
        _raise_sigterm()
        return True

    loop.call_later(delay, _raise_sigterm)
    logger.info("desktop shutdown requested from the local launcher; stopping in %.2fs", delay)
    return True


class DesktopShutdownResponse(BaseModel):
    """What the launcher is told when its shutdown request is accepted."""

    status: str = Field(description="Always ``stopping`` - the process is on its way down.")
    detail: str = Field(description="Human-readable note for the launcher log.")


router = APIRouter(tags=["System"])


@router.post(
    "/api/system/desktop-shutdown",
    response_model=DesktopShutdownResponse,
    status_code=status.HTTP_202_ACCEPTED,
    include_in_schema=False,
)
async def desktop_shutdown(request: Request) -> DesktopShutdownResponse:
    """Stop this backend cleanly at the desktop launcher's request.

    Answers before it acts, then runs the process's own shutdown handler, which
    stops the embedded PostgreSQL cluster cleanly - so the next start has no
    write-ahead log to replay.

    Args:
        request: The incoming request, carrying the launcher's token.

    Returns:
        The acknowledgement the launcher logs.

    Raises:
        HTTPException: 403 when any guard refuses (see
            :func:`authorise_shutdown_request`), or 503 when this process has no
            shutdown handler to run, which tells the launcher to fall back
            immediately instead of waiting out its budget.
    """
    authorise_shutdown_request(request)

    if not request_process_shutdown():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="This backend cannot stop itself; stop the process instead.",
        )

    return DesktopShutdownResponse(
        status="stopping",
        detail="Shutting down and stopping the local database cleanly.",
    )
