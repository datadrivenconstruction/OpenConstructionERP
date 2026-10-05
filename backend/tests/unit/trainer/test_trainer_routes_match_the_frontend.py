# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every learner path the frontend calls is a route of the trainer router.

The app runs with ``redirect_slashes=False``, so a trailing slash that differs
between ``TRAINER_PATHS`` (``frontend/src/features/trainer/api.ts``) and the
router is a 404 in production, not a redirect (decision 31). This test reads
the frontend table as text and compares method-free path shapes.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.routing import APIRoute

from app.modules.trainer.router import router

API_TS = Path(__file__).resolve().parents[4] / "frontend" / "src" / "features" / "trainer" / "api.ts"

#: The module loader mounts the trainer router here; the frontend client
#: prefixes ``/api`` itself.
MOUNT = "/v1/trainer"


def _frontend_paths() -> dict[str, str]:
    text = API_TS.read_text(encoding="utf-8")
    block = re.search(r"export const TRAINER_PATHS = \{(.*?)\} as const;", text, re.S)
    assert block, "TRAINER_PATHS not found in api.ts"
    paths: dict[str, str] = {}
    for key, body in re.findall(r"^\s*(\w+):\s*(.+?),?\s*$", block.group(1), re.M):
        literal = re.search(r"['`]([^'`]+)['`]", body)
        assert literal, f"{key}: no path literal"
        paths[key] = re.sub(r"\$\{seg\((\w+)\)\}", lambda m: "{" + m.group(1) + "}", literal.group(1))
    return paths


def _shape(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def _backend_shapes() -> set[str]:
    return {_shape(MOUNT + r.path) for r in router.routes if isinstance(r, APIRoute)}


def test_every_frontend_path_is_a_backend_route_with_the_same_slash() -> None:
    frontend = _frontend_paths()
    assert set(frontend) >= {"publicStatus", "me", "task", "answers", "check", "readback", "revealHint", "unlockSeen"}
    backend = _backend_shapes()
    missing = {key: path for key, path in frontend.items() if _shape(path) not in backend}
    assert missing == {}


def test_only_the_public_status_carries_a_trailing_slash() -> None:
    frontend = _frontend_paths()
    slashed = sorted(key for key, path in frontend.items() if path.endswith("/"))
    assert slashed == ["publicStatus"]


def test_learner_routes_take_the_methods_the_frontend_uses() -> None:
    methods = {_shape(MOUNT + r.path): set(r.methods or ()) for r in router.routes if isinstance(r, APIRoute)}
    assert "GET" in methods[f"{MOUNT}/me"]
    assert "GET" in methods[f"{MOUNT}/tasks/{{}}"]
    assert "PUT" in methods[f"{MOUNT}/tasks/{{}}/answers"]
    assert "POST" in methods[f"{MOUNT}/tasks/{{}}/check"]
    assert "GET" in methods[f"{MOUNT}/tasks/{{}}/readback"]
    assert "POST" in methods[f"{MOUNT}/tasks/{{}}/hints/reveal"]
    assert "POST" in methods[f"{MOUNT}/unlocks/{{}}/seen"]
    assert "GET" in methods[f"{MOUNT}/public/status/"]
