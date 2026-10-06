# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Find routes that an earlier route answers in their place.

Starlette tries routes in order and the first full match wins. A parametric
route declared before a static one therefore takes its requests:
``GET /finance/{invoice_id}`` came before the inbox router's ``GET /finance/inbox``,
so the inbox list answered 422 ("invoice_id: input 'inbox' is not a UUID") on
every install, and nothing failed, because each route was correct on its own.

:func:`shadowed_routes` walks the served routes in matching order (the order
:func:`app.core.module_loader.served_routes` yields them), builds a sample URL
for each route and reports every earlier route that fully matches that URL for
an overlapping method. Only the URL shape is compared; a route that rejects the
sample later (a 404 from the handler) still took the request.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from starlette.routing import Mount, compile_path

#: A value per path convertor that the convertor accepts and that no static
#: path segment in the code base spells.
_SAMPLES = {
    "str": "zz-route-sample",
    "path": "zz-route-sample/zz-tail",
    "int": "7",
    "float": "7.5",
    "uuid": "00000000-0000-4000-8000-00000000abcd",
}


@dataclass(frozen=True)
class Shadow:
    """``hidden`` never receives ``url``: ``by`` answers it first."""

    methods: tuple[str, ...]
    hidden: str
    by: str
    url: str


def _sample_url(full_path: str) -> str:
    _regex, path_format, convertors = compile_path(full_path)
    url = path_format
    for name, convertor in convertors.items():
        kind = next((k for k, v in _convertor_types().items() if isinstance(convertor, v)), "str")
        url = url.replace("{" + name + "}", _SAMPLES[kind])
    return url


def _convertor_types() -> dict[str, type]:
    from starlette.convertors import CONVERTOR_TYPES

    return {name: type(conv) for name, conv in CONVERTOR_TYPES.items()}


def _methods(route: Any) -> frozenset[str]:
    return frozenset(m for m in (getattr(route, "methods", None) or ()) if m != "HEAD")


def shadowed_routes(served: Iterable[tuple[str, Any]]) -> list[Shadow]:
    """Every (route, earlier route) pair where the earlier one takes the request.

    ``served`` is ``(full_path, route)`` in matching order. WebSocket routes are
    skipped (a different scope type never competes with HTTP). A ``Mount``
    earlier in the order takes everything under its path, whatever the method.
    """
    earlier: list[tuple[str, Any, Any]] = []
    found: list[Shadow] = []
    for full_path, route in served:
        is_mount = isinstance(route, Mount)
        methods = _methods(route)
        if not is_mount and not methods:
            continue  # WebSocket routes and other non-HTTP entries
        if not is_mount:
            url = _sample_url(full_path)
            for prev_path, prev, regex in earlier:
                overlap = methods if isinstance(prev, Mount) else methods & _methods(prev)
                if overlap and regex.match(url):
                    found.append(Shadow(tuple(sorted(overlap)), full_path, prev_path, url))
                    break
        pattern = full_path.rstrip("/") + "/{path:path}" if is_mount else full_path
        earlier.append((full_path, route, compile_path(pattern)[0]))
    return found
