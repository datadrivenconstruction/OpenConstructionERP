# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A frozen build must build the encoder on the CPU and say which device it used.

``SentenceTransformer`` picks its own device when nobody names one, and on any
Apple Silicon machine that is Metal. The desktop sidecar is a frozen bundle, so
until this existed every macOS desktop build ran its inference through Metal
without anyone deciding that it should.

Measured, desktop-release run 33851623420, macos-latest, on the restart leg: the
encoder loads exactly once and successfully, the process then raises SIGSEGV
before the embedding pool reports itself initialised, and the last line written
before the crash is the multiprocessing resource tracker complaining about a
leaked semaphore. The same leg run with ``OE_VECTOR_POOL_WORKERS=0`` serves
normally. That bisect puts the fault in the pool or in what the pool warms
rather than in the load, and what the pool does immediately after the load is
run several encode calls at once against the one model object.

These tests cannot prove the crash is gone. Nothing on a machine without Metal
can. What they hold is the decision: a frozen build names its device, names
``cpu``, and can still be told otherwise by somebody who means it.

The wiring test is the one that matters most. Resolving the right string and
then not passing it to the constructor would leave the defect exactly where it
was while every other assertion here stayed green, so one test reads what the
constructor was actually handed.
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest

from app.core import vector


class _RecordingModel:
    """Records the keyword arguments the loader hands the constructor."""

    last_kwargs: dict[str, Any] = {}
    last_source: str | None = None

    def __init__(self, source: str, **kwargs: Any) -> None:
        type(self).last_source = source
        type(self).last_kwargs = dict(kwargs)

    def encode(self, *_args: Any, **_kwargs: Any) -> list[float]:
        return [0.0]


@pytest.fixture
def cold_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cold, hermetic embedder singleton.

    ``reset_embedder`` refuses to clear a working instance, so the globals are
    set directly. monkeypatch puts them back, which is what stops a fake model
    leaking into the rest of the run.
    """
    monkeypatch.setattr(vector, "_embedder_instance", None, raising=False)
    monkeypatch.setattr(vector, "_embedder_tried", False, raising=False)
    monkeypatch.setattr(vector, "_active_model_name", None, raising=False)
    monkeypatch.setattr(vector, "_resolve_active_model", lambda: ("a-test-model", 384))
    monkeypatch.setattr(vector, "_candidate_sources", lambda name: [f"local/{name}"])
    _RecordingModel.last_kwargs = {}
    _RecordingModel.last_source = None


@pytest.fixture(autouse=True)
def _no_inherited_device(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear the override so this machine's environment cannot decide the answer.

    Without this the suite would pass or fail according to whether whoever ran
    it happens to have ``OE_VECTOR_DEVICE`` set, which is the kind of green that
    means nothing.
    """
    monkeypatch.delenv("OE_VECTOR_DEVICE", raising=False)
    monkeypatch.delenv("OE_DESKTOP", raising=False)


def _install_fake_library(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put a fake ``sentence_transformers`` where the function-body import looks.

    The loader imports the library inside its own body, so patching an attribute
    on ``app.core.vector`` would never be consulted.
    """
    fake = ModuleType("sentence_transformers")
    fake.SentenceTransformer = _RecordingModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake)


def test_a_frozen_build_resolves_to_the_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    """``sys.frozen`` is the signal PyInstaller and Nuitka both set."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert vector._resolve_device() == "cpu"


def test_the_desktop_sidecar_resolves_to_the_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half of the same predicate.

    The Tauri shell sets ``OE_DESKTOP=1`` on the sidecar's environment, and a
    development desktop run is not frozen, so the frozen check alone would miss
    exactly the configuration a developer reproduces the bug in.
    """
    monkeypatch.setenv("OE_DESKTOP", "1")

    assert vector._resolve_device() == "cpu"


def test_a_server_install_still_lets_the_library_choose() -> None:
    """The control, and it must keep passing.

    A server with a real GPU should go on using it. Answering ``cpu`` here would
    be a performance regression on every deployment that is not a desktop, dealt
    out to fix a crash that only happens in a frozen bundle.
    """
    assert vector._resolve_device() is None


def test_the_environment_can_overrule_both_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Somebody who wants Metal on their own desktop build can ask for it.

    Asserted from the frozen side on purpose: an override that only worked where
    the default already agreed with it would not be an override.
    """
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("OE_VECTOR_DEVICE", "mps")

    assert vector._resolve_device() == "mps"


def test_the_resolved_device_reaches_the_constructor(cold_singleton: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """The wiring, which is the only part of this the crash actually cares about.

    Every other test here would stay green if the resolved string were computed
    and then dropped on the way to ``SentenceTransformer``, so this one reads
    what the constructor was handed rather than what the resolver returned.
    """
    monkeypatch.setattr(vector, "_resolve_device", lambda: "cpu")
    _install_fake_library(monkeypatch)

    model = vector.get_embedder()

    assert model is not None
    assert _RecordingModel.last_kwargs.get("device") == "cpu", (
        f"the constructor was called with {_RecordingModel.last_kwargs!r}; a device resolved "
        "and not passed leaves a frozen build on Metal exactly as before"
    )


def test_a_server_install_is_not_handed_a_device_at_all(cold_singleton: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """The control for the wiring test.

    Passing ``device=None`` is not the same as passing nothing. Some versions of
    sentence-transformers treat an explicit ``None`` as a request rather than as
    silence, so the loader must call the constructor without the argument when
    it has no opinion, and this asserts that shape rather than the value.
    """
    monkeypatch.setattr(vector, "_resolve_device", lambda: None)
    _install_fake_library(monkeypatch)

    model = vector.get_embedder()

    assert model is not None
    assert "device" not in _RecordingModel.last_kwargs, (
        f"the constructor was called with {_RecordingModel.last_kwargs!r}; a server install "
        "should be left to choose its own accelerator"
    )
