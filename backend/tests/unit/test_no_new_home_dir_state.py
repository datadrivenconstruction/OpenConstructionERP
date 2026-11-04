"""Guard: no new code may put persistent state under the account's home dir.

In the container image the home is ``/app``, inside the image layer, so a file
written under ``Path.home()`` is lost whenever the container is recreated.
Persistent paths go through :func:`app.core.home_state.home_state_dir` (or the
data-dir resolvers in :mod:`app.core.storage`). The uses left below are reads,
desktop-only launcher files, or rebuildable caches; adding one to a file, or a
new file, fails this test until it is reviewed and listed here.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "app"

_HOME_USE = re.compile(r"Path\.home\(\)|expanduser\(\s*[\"']~")

#: Reviewed uses, per file: (count, why it is not a persistent container write).
ALLOWED: dict[str, tuple[int, str]] = {
    "core/home_state.py": (1, "the resolver itself, legacy location only"),
    "cli.py": (3, "desktop CLI default data dir, launcher log path, help text"),
    "config.py": (2, "JWT secret dir after the operator override; legacy secret read"),
    "core/storage.py": (2, "pip default after the operator override; legacy read roots"),
    "core/embedded_pg.py": (2, "desktop embedded PostgreSQL: launcher log, per-user hash"),
    "core/embedding_installer.py": (1, "reads a finished legacy install, else the data dir"),
    "core/update_check_policy.py": (1, "reads the desktop launcher's opt-out file"),
    "main.py": (1, "demo credentials after the operator override"),
    "modules/ai/ai_client.py": (1, "reads the CLI's config.json"),
    "modules/catalog/router.py": (1, "rebuildable catalog cache"),
    "modules/clash/geometry.py": (1, "developer script locating the desktop cluster"),
    "modules/costs/router.py": (5, "rebuildable snapshot caches; developer source probes"),
    "modules/documents/service.py": (1, "uploads root after the operator override"),
    "modules/match_elements/qdrant_supervisor.py": (1, "reads a finished legacy install, else the data dir"),
    "modules/projects/file_manager_service.py": (1, "informational note only"),
    "modules/takeoff/router.py": (1, "converter download cache (temporary archives)"),
    "modules/takeoff/service.py": (1, "legacy read candidate"),
    "scripts/seed_demo_assets.py": (1, "developer script output folder"),
}


def _count_uses(path: Path) -> int:
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        count += len(_HOME_USE.findall(line))
    return count


def test_home_dir_uses_are_only_the_reviewed_ones() -> None:
    found: dict[str, int] = {}
    for path in APP_ROOT.rglob("*.py"):
        uses = _count_uses(path)
        if uses:
            found[path.relative_to(APP_ROOT).as_posix()] = uses

    unexpected = {name: uses for name, uses in found.items() if uses > ALLOWED.get(name, (0, ""))[0]}
    assert not unexpected, (
        f"New home-directory paths in {unexpected}. Persistent state must go through "
        "app.core.home_state.home_state_dir so it follows OE_DATA_DIR; if this one is "
        "a read or a rebuildable cache, add it to ALLOWED with the reason."
    )
    stale = {name for name, (allowed, _) in ALLOWED.items() if found.get(name, 0) < allowed}
    assert not stale, f"Lower the ALLOWED counts for {sorted(stale)} so they cannot be refilled."
