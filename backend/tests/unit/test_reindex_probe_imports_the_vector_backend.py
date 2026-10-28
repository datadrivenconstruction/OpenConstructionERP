# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The reindex probe must import the backend, not merely locate it.

``find_spec`` resolves a module without executing it. lancedb is almost
entirely one Rust extension, so it can sit on disk, resolve perfectly, and
still fail to load. A build in that state passed the old probe and then failed
inside the reindex, which turns a clean 503 naming the fault into a 500 that
names nothing.

The same blind spot was closed in ``doctor`` first. This is the copy that
answers a user rather than an operator, which is the reason it matters more
here: the operator can read a stack trace, and the user gets whatever this
message says.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import HTTPException

import app.modules.admin.router as admin_router
from app.core import self_upgrade
from app.modules.admin.router import require_vector_backend


def _detail(exc: HTTPException) -> dict:
    assert isinstance(exc.detail, dict), f"the probe stopped returning a structured detail: {exc.detail!r}"
    return exc.detail


def _lancedb(monkeypatch: pytest.MonkeyPatch, *, present: bool, loads: bool) -> None:
    real_find_spec = importlib.util.find_spec
    real_import = importlib.import_module

    def fake_find_spec(name: str, package: str | None = None):
        if name == "lancedb":
            return (ModuleType(name).__spec__ or object()) if present else None
        return real_find_spec(name, package)

    def fake_import(name: str, package: str | None = None):
        if name == "lancedb":
            if not loads:
                raise ImportError("DLL load failed while importing lancedb: %1 is not a valid Win32 application")
            return ModuleType(name)
        return real_import(name, package)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    monkeypatch.setattr(importlib, "import_module", fake_import)


class TestABackendThatResolvesButWillNotLoad:
    def test_it_is_refused_rather_than_allowed_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _lancedb(monkeypatch, present=True, loads=False)

        with pytest.raises(HTTPException) as caught:
            require_vector_backend()

        assert caught.value.status_code == 503
        detail = _detail(caught.value)
        assert detail["code"] == "vector_extra_broken", (
            "a lancedb that resolves but cannot load was let through, so the reindex "
            "fails later with a 500 instead of here with a reason"
        )
        assert "DLL load failed" in detail["message"], "the caller needs the load error, not just a verdict"

    def test_broken_is_not_reported_as_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Different faults, different fixes, so different codes.

        Installing what is already installed changes nothing, so a client that
        keys on the code would show the wrong instruction.
        """
        _lancedb(monkeypatch, present=True, loads=False)
        with pytest.raises(HTTPException) as broken:
            require_vector_backend()

        _lancedb(monkeypatch, present=False, loads=False)
        with pytest.raises(HTTPException) as absent:
            require_vector_backend()

        assert _detail(broken.value)["code"] != _detail(absent.value)["code"]


class TestTheOtherTwoStatesAreUnchanged:
    def test_absent_still_answers_with_the_established_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The existing contract, pinned so the new branch cannot displace it."""
        _lancedb(monkeypatch, present=False, loads=False)

        with pytest.raises(HTTPException) as caught:
            require_vector_backend()

        assert caught.value.status_code == 503
        assert _detail(caught.value)["code"] == "vector_extra_missing"

    def test_a_working_backend_is_let_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The control. Without it the tests above pass on a probe that refuses everything."""
        _lancedb(monkeypatch, present=True, loads=True)

        require_vector_backend()


class TestTheProbeIsNotRunOnTheEventLoop:
    """Importing a Rust extension is not something to do on the loop.

    Answering by importing is what makes this probe honest, and it is also what
    makes it slow: a first lancedb load takes real time, and a damaged one can
    take a great deal of it. This handler is ``async def``, so an import inline
    holds the event loop for that whole duration and a single-worker deployment
    answers nothing at all meanwhile. That is not hypothetical here, it is the
    failure this codebase already recorded once, and the desktop sidecar is
    exactly the single-worker case.

    Measured by thread identity rather than by reading the source, so the
    property survives the call being rewritten in any other form that still
    keeps the import off the loop.
    """

    async def test_the_handler_hands_the_probe_to_a_worker_thread(self, monkeypatch: pytest.MonkeyPatch) -> None:
        loop_thread = threading.current_thread()
        ran_on: list[threading.Thread] = []

        def recording_probe() -> None:
            ran_on.append(threading.current_thread())
            # Raise so the handler stops here. Which thread this ran on is the
            # whole question; everything after it belongs to other tests.
            raise HTTPException(status_code=503, detail={"code": "vector_extra_missing", "message": "stub"})

        monkeypatch.setattr(admin_router, "check_gates", lambda **kwargs: None)
        monkeypatch.setattr(admin_router, "require_vector_backend", recording_probe)

        with pytest.raises(HTTPException):
            await admin_router.cost_vector_reindex(
                body=SimpleNamespace(confirm_token="unused, the gate is stubbed"),
                request=SimpleNamespace(url=SimpleNamespace(hostname="localhost")),
                background_tasks=None,
                session=None,
            )

        assert ran_on, "the probe was never reached, so this test measured nothing"
        assert ran_on[0] is not loop_thread, (
            "the vector backend was imported on the event loop, so the server stops "
            "answering every other request for as long as the import takes"
        )


class TestTheAdviceSuitsTheInstallReadingIt:
    def test_a_pip_install_is_told_to_use_pip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        _lancedb(monkeypatch, present=False, loads=False)

        with pytest.raises(HTTPException) as caught:
            require_vector_backend()

        assert "openconstructionerp[vector]" in _detail(caught.value)["message"]

    @pytest.mark.parametrize(
        ("present", "loads"),
        [(False, False), (True, False)],
        ids=["absent", "will not load"],
    )
    def test_a_bundle_is_never_told_to_run_pip(
        self, monkeypatch: pytest.MonkeyPatch, present: bool, loads: bool
    ) -> None:
        """This route runs in the desktop sidecar too, where pip does not exist.

        Both failing branches are checked, because a remedy that is right in
        one and impossible in the other is still a remedy somebody is shown.
        """
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        _lancedb(monkeypatch, present=present, loads=loads)

        with pytest.raises(HTTPException) as caught:
            require_vector_backend()

        message = _detail(caught.value)["message"]
        assert "pip install" not in message, f"a bundle with no pip was told to run pip: {message!r}"
        assert self_upgrade.DESKTOP_REPAIR in message, "the bundle was left with a diagnosis and no instruction"
