# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A module download URL goes through the same outbound check as a webhook.

``install_from_url`` fetched whatever URL it was handed, and ``install`` hands
it the ``download_url`` a registry answers with, so a registry entry naming a
cloud metadata or LAN address would have the server fetch it. The download URL
is now resolved and refused when it points inward, before any request.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.plugin_manager import ModulePluginManager
from app.core.url_safety import UnsafeUrlError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    ["http://169.254.169.254/latest/meta-data/module.zip", "http://127.0.0.1:9000/module.zip", "file:///etc/passwd"],
)
async def test_an_inward_download_url_is_refused_before_any_request(tmp_path: Path, monkeypatch, url: str) -> None:
    mgr = ModulePluginManager(tmp_path / "modules")

    async def _never(*_a: object, **_k: object) -> object:
        raise AssertionError("the plugin manager fetched an inward URL")

    monkeypatch.setattr(mgr._http, "get", _never)
    try:
        with pytest.raises(UnsafeUrlError):
            await mgr.install_from_url(url)
    finally:
        await mgr.close()
