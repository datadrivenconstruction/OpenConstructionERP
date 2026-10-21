"""Unit tests for the non-blocking converter install.

Covers the v8.8.0 fix for the user-reported "signal timed out" on a slow
server: the install endpoint must return immediately (the heavy download runs
in the background and is observed via /install-progress/), a platform with no
converter build is answered at once, and a terminal progress record must
auto-expire.

These import ``app.modules.takeoff.router`` which pulls the app/database, so
they run on the CI py3.12 image (the local py3.11 dev env can't import them).
"""

from __future__ import annotations

import types

import pytest

from app.modules.takeoff import router as tk


@pytest.mark.asyncio
async def test_install_converter_returns_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    """The install endpoint must NOT block on the download (the root cause of
    the client-side "signal timed out"). It returns ``async_install`` at once
    and the heavy work runs in a background task."""
    import asyncio

    from app.modules.boq import cad_import

    cid = "ifc"
    tk._INSTALL_TASKS.pop(cid, None)
    tk._clear_install_progress(cid)

    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: None)

    # The platform is pinned because the endpoint answers differently on one
    # that has no converter build: it returns synchronously and says so, and
    # there is no background task to observe. The other branch is pinned below.
    monkeypatch.setattr("sys.platform", "win32")

    ran = asyncio.Event()

    async def _fake_impl(converter_id: str, force: bool, app: object) -> dict[str, object]:
        ran.set()
        return {"converter_id": converter_id, "installed": True, "path": "C:/converters/ifc_windows/runtime/python.exe"}

    monkeypatch.setattr(tk, "_install_converter_impl", _fake_impl)

    fake_request = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace()))
    result = await tk.install_converter(cid, fake_request, "user-1", force=False)

    assert result["async_install"] is True
    assert result["started"] is True
    assert result["installed"] is False

    # The background task eventually runs the (mocked) heavy work to completion.
    await asyncio.wait_for(ran.wait(), timeout=2.0)
    # Let the background wrapper publish its terminal record.
    for _ in range(50):
        prog = await tk.get_install_progress(cid)
        if prog.get("stage") == "done":
            break
        await asyncio.sleep(0.01)
    prog = await tk.get_install_progress(cid)
    assert prog["active"] is True
    assert prog["stage"] == "done"
    assert prog["installed"] is True
    tk._clear_install_progress(cid)
    tk._INSTALL_TASKS.pop(cid, None)


@pytest.mark.asyncio
async def test_install_converter_on_a_platform_without_a_build_answers_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No native build means an answer, not a download that cannot happen.

    Linux and macOS have builds now, so the host is one the release has none
    for. Asserting it here means both answers are pinned on every platform
    instead of depending on which machine ran them.
    """
    from app.modules.boq import cad_import

    cid = "ifc"
    tk._INSTALL_TASKS.pop(cid, None)
    tk._clear_install_progress(cid)

    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: None)
    monkeypatch.setattr("sys.platform", "sunos5")

    async def _must_not_run(converter_id: str, force: bool, app: object) -> dict[str, object]:
        raise AssertionError("no background install may start where there is nothing to install")

    monkeypatch.setattr(tk, "_install_converter_impl", _must_not_run)

    fake_request = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace()))
    result = await tk.install_converter(cid, fake_request, "user-1", force=False)

    assert result["platform_unsupported"] is True
    assert result["installed"] is False
    assert "async_install" not in result
    assert cid not in tk._INSTALL_TASKS


@pytest.mark.asyncio
async def test_install_progress_terminal_record_expires() -> None:
    """A done/error record lingers briefly for the poll, then auto-expires."""
    import time

    cid = "ifc"
    tk._set_install_progress(
        cid,
        stage="done",
        installed=True,
        finished_at=time.time() - (tk._INSTALL_RESULT_TTL_SEC + 10.0),
    )
    prog = await tk.get_install_progress(cid)
    assert prog == {"active": False}
