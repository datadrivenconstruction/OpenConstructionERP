"""Every backend WebSocket route must be proxied as a WebSocket by the shipped nginx config.

The generic ``/api/`` location does not forward the Upgrade handshake, so a WebSocket
path that the dedicated location misses reaches FastAPI as a plain GET and answers 404.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
NGINX_CONF = REPO / "deploy" / "docker" / "nginx.conf"
MODULES = REPO / "backend" / "app" / "modules"

_WS_DECORATOR = re.compile(r'@router\.websocket\(\s*"([^"]+)"')
_WS_LOCATION = re.compile(r"location\s+~\s+(\S+)\s*\{[^}]*proxy_set_header\s+Upgrade", re.S)


def _websocket_paths() -> list[str]:
    paths = []
    for router in sorted(MODULES.glob("*/router.py")):
        module = router.parent.name
        for route in _WS_DECORATOR.findall(router.read_text(encoding="utf-8")):
            # The module loader mounts each module under its hyphenated prefix and
            # mirrors it under the legacy underscore one; browsers use either.
            for prefix in {module, module.replace("_", "-")}:
                paths.append(f"/api/v1/{prefix}{route}")
    return paths


def _websocket_locations() -> list[re.Pattern[str]]:
    return [re.compile(rx) for rx in _WS_LOCATION.findall(NGINX_CONF.read_text(encoding="utf-8"))]


def test_backend_declares_websocket_routes() -> None:
    assert _websocket_paths(), "no @router.websocket found; the scan below would pass vacuously"


@pytest.mark.parametrize("path", _websocket_paths())
def test_websocket_route_is_proxied_with_upgrade(path: str) -> None:
    locations = _websocket_locations()
    assert locations, f"{NGINX_CONF} has no location that forwards the Upgrade header"
    assert any(rx.match(path) for rx in locations), (
        f"{path} is a WebSocket route but no Upgrade-forwarding location in deploy/docker/nginx.conf matches it"
    )
