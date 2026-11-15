# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Where startup is, for a server that answers while it is still starting.

The port opens at once and startup (schema build, module load, baseline seeds)
runs behind it. Until it finishes, :class:`BootGateMiddleware` answers every
API call except the health probe with a 503 that names the phase, and the SPA
shows a "setting up" screen built from the same snapshot. Static files pass
through, so the browser has something to render from the first second.

State is process-wide and written from one place (the startup sequence), so a
plain module-level object is enough; readers only ever take a snapshot.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

#: The section headers the startup sequence prints, in order. Used only to turn
#: a phase name into "step k of n"; a phase missing here still reports its name.
BOOT_PHASES: tuple[str, ...] = (
    "OpenConstructionERP",
    "i18n",
    "Database",
    "Modules",
    "Validation",
    "Demo data",
    "Vector DB",
    "Ready",
    "Routing",
)

#: Paths answered normally while starting. Everything else under ``/api`` waits.
_OPEN_PATHS: frozenset[str] = frozenset({"/api/health", "/api/health/"})

#: Seconds a client should wait before asking again.
RETRY_AFTER_S = 3


@dataclass
class BootState:
    """Progress of the startup sequence of this process."""

    phase: str = "startup"
    started_at: float = field(default_factory=time.monotonic)
    phase_started_at: float = field(default_factory=time.monotonic)
    ready: bool = False
    failed: bool = False
    #: True only while startup runs behind an open port. Inline startup (tests,
    #: ``OE_BOOT_INLINE``) never sets it, so nothing is ever gated there.
    gating: bool = False

    def set_phase(self, name: str) -> None:
        """Record the phase that is running now and restart its clock."""
        self.phase = name
        self.phase_started_at = time.monotonic()

    def begin_background(self) -> None:
        """Startup is about to run behind an open port: close the API until it ends."""
        self.ready = False
        self.failed = False
        self.gating = True

    @property
    def api_open(self) -> bool:
        """Whether API requests may pass."""
        return self.ready or not self.gating

    def mark_ready(self) -> None:
        """Startup finished: the API is open."""
        self.ready = True
        self.failed = False

    def mark_failed(self) -> None:
        """Startup raised: the API stays closed, health says so."""
        self.failed = True
        self.ready = False

    def reset(self) -> None:
        """Back to a fresh, not-yet-started state (a new app in the same process)."""
        now = time.monotonic()
        self.phase = "startup"
        self.started_at = now
        self.phase_started_at = now
        self.ready = False
        self.failed = False
        self.gating = False

    @property
    def status(self) -> str:
        """``ready``, ``failed`` or ``starting``."""
        if self.ready:
            return "ready"
        if self.failed:
            return "failed"
        return "starting"

    def snapshot(self) -> dict[str, Any]:
        """Public, internals-free view: safe for the unauthenticated health probe."""
        now = time.monotonic()
        step = BOOT_PHASES.index(self.phase) + 1 if self.phase in BOOT_PHASES else 0
        return {
            "status": self.status,
            "phase": self.phase,
            "step": step,
            "steps": len(BOOT_PHASES),
            "elapsed_seconds": int(now - self.started_at),
            "phase_elapsed_seconds": int(now - self.phase_started_at),
        }


boot_state = BootState()


#: Pause between blocking import steps while the port is open: long enough for
#: the loop to accept and answer a queued health or static request.
YIELD_S = 0.005


async def yield_to_requests(state: BootState | None = None) -> None:
    """Give queued requests a turn, but only while startup runs behind the port.

    Inline startup has no listener yet, so it skips the pause entirely.
    """
    current = state or boot_state
    if current.gating and not current.ready:
        await asyncio.sleep(YIELD_S)


def is_gated_path(path: str) -> bool:
    """Whether a request to ``path`` has to wait for startup to finish."""
    if path in _OPEN_PATHS:
        return False
    return path == "/api" or path.startswith("/api/")


class BootGateMiddleware:
    """Hold the API closed with a clear 503 until startup has finished.

    Pure ASGI and one attribute read per request once open, so it costs nothing
    after boot. Websockets under ``/api`` are refused the same way.
    """

    def __init__(self, app: Any, state: BootState | None = None) -> None:
        self.app = app
        self.state = state or boot_state

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if self.state.api_open or scope.get("type") not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        if not is_gated_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1013})
            return
        snap = self.state.snapshot()
        body = json.dumps(
            {
                "detail": "The server is still starting. Try again in a few seconds.",
                "code": "server_starting" if snap["status"] == "starting" else "server_start_failed",
                "boot": snap,
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", str(RETRY_AFTER_S).encode()),
                    (b"cache-control", b"no-store"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


#: Set to 1 to run startup before the port opens, as earlier releases
#: did: for a harness that wants the first 200 on any route to mean "fully up".
BOOT_INLINE_ENV = "OE_BOOT_INLINE"

#: Set by the server entry points (``serve``, ``python -m app``, the container
#: image). An in-process host (TestClient, ``lifespan_context``) never sets it,
#: so its lifespan still returns a fully mounted, seeded app.
BOOT_BACKGROUND_ENV = "OE_BOOT_BACKGROUND"


def boot_in_background(env: Mapping[str, str] | None = None) -> bool:
    """Should startup run behind an already open port?

    Only when a real server asked for it (``OE_BOOT_BACKGROUND``) and neither
    the test suite's fast startup nor ``OE_BOOT_INLINE`` asks for the old order.
    Anything that hosts the app in-process reads it as soon as the lifespan
    returns, so for it startup stays inline.
    """
    source = os.environ if env is None else env

    def _on(var: str) -> bool:
        return source.get(var, "").strip().lower() in ("1", "true", "yes")

    if _on("OE_TEST_FAST_STARTUP") or _on(BOOT_INLINE_ENV):
        return False
    return _on(BOOT_BACKGROUND_ENV)


def request_server_exit() -> None:
    """Ask the server to shut down, as Ctrl+C would, after a failed background boot.

    uvicorn handles SIGINT on every platform, so this takes the same orderly
    path (shutdown hooks, embedded PostgreSQL stopped) as a user pressing
    Ctrl+C. The CLI then exits with uvicorn's startup-failure code.
    """
    import signal

    try:
        signal.raise_signal(signal.SIGINT)
    except Exception:  # noqa: BLE001 - nothing better left to do; health reports the failure
        logging.getLogger(__name__).warning("Could not signal the server to stop after a failed startup", exc_info=True)


__all__ = [
    "BOOT_BACKGROUND_ENV",
    "BOOT_INLINE_ENV",
    "BOOT_PHASES",
    "RETRY_AFTER_S",
    "BootGateMiddleware",
    "BootState",
    "boot_in_background",
    "boot_state",
    "is_gated_path",
    "yield_to_requests",
    "request_server_exit",
]
