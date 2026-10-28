# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The E57 refusal must not tell a desktop user to run pip.

This message is different in kind from the ones in ``doctor``. It is a response
detail an ordinary user reads after opening a scan, not a line an operator finds
in a diagnostic report, and the desktop build has no pip for them to act on it
with: ``sys.executable`` is the app binary, so the command feeds its own tokens
back into this application's CLI.

It is also reachable, which is what separates it from the rest of the family.
The ``pointcloud`` extra is ``pye57``, and ``pye57`` is not in
``requirements-desktop.lock``, so LAS, LAZ and COPC open in the bundle and E57
lands here every time. That is why the frozen answer is DESKTOP_NO_EXTRA rather
than the repair wording: the bundle is lean, not damaged.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core import self_upgrade
from app.modules.pointcloud import decode as decode_mod
from app.modules.pointcloud.service import PointCloudService

#: The advice exactly as it stood before it was routed. Asserted verbatim on a
#: pip install, so the frozen arm can only ever be a redirection: a change that
#: quietly stopped telling the larger audience what to do would fail here.
PIP_ADVICE = "install the 'pointcloud' extra (pip install openconstructionerp[pointcloud]) to add E57 support."


@pytest.fixture
def refusing_service(monkeypatch: pytest.MonkeyPatch) -> PointCloudService:
    """A service whose decoder reports that no E57 reader is installed.

    The session is never touched: ``get_scan`` is stubbed, so nothing below it
    reaches the database, and the decode call is the only thing under test.
    """
    service = PointCloudService(session=None)  # type: ignore[arg-type]

    async def fake_get_scan(self, scan_id, *, payload=None):  # noqa: ANN001, ARG001
        return SimpleNamespace(
            upload_key="scans/whatever.e57",
            original_format="e57",
            status="ready",
            point_count=None,
            bbox_json=None,
        )

    def fake_local_path(self, upload_key: str):  # noqa: ANN001, ARG001
        return Path("whatever.e57")

    def fake_decode(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        raise decode_mod.PointDecodeUnavailable(fmt="e57", reader="pye57")

    monkeypatch.setattr(PointCloudService, "get_scan", fake_get_scan)
    monkeypatch.setattr(PointCloudService, "_local_path_for", fake_local_path)
    monkeypatch.setattr(decode_mod, "decode_points", fake_decode)
    return service


async def _refusal(service: PointCloudService) -> HTTPException:
    with pytest.raises(HTTPException) as caught:
        await service.get_points(uuid.uuid4())
    return caught.value


class TestTheRefusalItself:
    async def test_it_is_still_a_501_naming_the_reader(
        self, refusing_service: PointCloudService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The control. Without it the advice tests could pass on a broken path."""
        monkeypatch.setattr(sys, "frozen", False, raising=False)

        exc = await _refusal(refusing_service)

        assert exc.status_code == 501
        assert exc.detail["reason"] == "reader_unavailable"
        assert exc.detail["format"] == "e57"
        assert "pye57" in exc.detail["message"]


class TestTheAdviceSuitsTheInstallReadingIt:
    async def test_a_pip_install_keeps_the_advice_it_had(
        self, refusing_service: PointCloudService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "frozen", False, raising=False)

        exc = await _refusal(refusing_service)

        assert PIP_ADVICE in exc.detail["message"], (
            "the server audience is the larger one and its instruction is correct, "
            "so routing the remedy must not change what they are told"
        )

    async def test_a_bundle_is_not_told_to_run_pip(
        self, refusing_service: PointCloudService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "frozen", True, raising=False)

        exc = await _refusal(refusing_service)

        message = exc.detail["message"]
        assert "pip install" not in message, f"a desktop user with no pip was told to run pip: {message!r}"
        assert self_upgrade.DESKTOP_NO_EXTRA in message, "the user was left with a refusal and no way forward"

    async def test_the_diagnosis_survives_in_both(
        self, refusing_service: PointCloudService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Swapping the remedy must not swallow what the reader needs to know.

        The half of the message that says which formats do work is the half that
        tells a desktop user their LAS files are fine, and it is the half most
        easily lost when a string is split around a helper.
        """
        for frozen in (False, True):
            monkeypatch.setattr(sys, "frozen", frozen, raising=False)
            message = (await _refusal(refusing_service)).detail["message"]
            assert "LAS, LAZ and COPC work out of the box" in message, (
                f"lost the working-formats half when frozen={frozen}"
            )
