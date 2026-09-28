"""The encoder download is on by default locally, off on a server, never fatal.

Three properties are being pinned here, and the third is the one that is easy to
lose while building the first two:

1. A local install fetches the encoder weights; a server deploy does not.
2. The fetch happens in the background and blocks nothing.
3. Nothing breaks while the weights are missing, failed, or half-arrived.

Every transfer in this file runs against a fake model hub served from a socket
on this machine. A test that pulls real weights is not a test, it is an outage
waiting for CI, and it would take minutes to say what a few kilobytes say here
in milliseconds.
"""

from __future__ import annotations

import http.server
import json
import threading
import time
from pathlib import Path

import pytest

from app.core import embedding_installer as installer
from app.core import vector

REPO = "fake-org/fake-encoder"

#: What the fake hub publishes. Deliberately includes the shapes the filter has
#: to drop: a second serialisation of the same weights, an ONNX runtime tree,
#: and a readme.
HUB_FILES: dict[str, bytes] = {
    "config.json": b'{"hidden_size": 384}',
    "model.safetensors": b"WEIGHTS" * 400,
    "tokenizer.json": b'{"tokenizer": true}',
    "modules.json": b'[{"idx": 0, "path": ""}]',
    "1_Pooling/config.json": b'{"pooling_mode_mean_tokens": true}',
    "pytorch_model.bin": b"PICKLED" * 400,
    "onnx/model.onnx": b"ONNX" * 400,
    "README.md": b"# card",
}


class _FakeHub(http.server.BaseHTTPRequestHandler):
    """A model hub in thirty lines: a file listing and byte-range downloads."""

    #: Set per test. ``stall`` blocks the named file mid-transfer until the
    #: event is set; ``fail_on`` closes the connection on the named file.
    stall_on: str | None = None
    stall_gate: threading.Event | None = None
    fail_on: str | None = None
    requested: list[str] = []  # noqa: RUF012 - class-level test spy, reset per test

    def log_message(self, *_args: object) -> None:  # noqa: A003 - silence the default stderr spam
        return

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's contract
        path = self.path.split("?")[0]
        if path == f"/api/models/{REPO}":
            body = json.dumps({"siblings": [{"rfilename": name} for name in HUB_FILES]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        prefix = f"/{REPO}/resolve/main/"
        if not path.startswith(prefix):
            self.send_error(404)
            return
        name = path[len(prefix) :]
        if name not in HUB_FILES:
            self.send_error(404)
            return

        type(self).requested.append(name)
        payload = HUB_FILES[name]

        if type(self).fail_on == name:
            # A connection that dies mid-file - the interruption this whole
            # design is built around.
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload[: len(payload) // 3])
            self.wfile.flush()
            self.close_connection = True
            return

        start = 0
        status = 200
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            start = int(rng.removeprefix("bytes=").split("-")[0])
            if start >= len(payload):
                self.send_error(416)
                return
            status = 206

        chunk = payload[start:]
        self.send_response(status)
        self.send_header("Content-Length", str(len(chunk)))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{len(payload) - 1}/{len(payload)}")
        self.end_headers()

        if type(self).stall_on == name and type(self).stall_gate is not None:
            # Hand over the head of the file, then hold the socket open. The
            # application must keep answering while this is stuck.
            self.wfile.write(chunk[:16])
            self.wfile.flush()
            type(self).stall_gate.wait(timeout=30)
            chunk = chunk[16:]
        self.wfile.write(chunk)


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """A fake hub on localhost, with the installer pointed at it and at tmp_path."""
    _FakeHub.stall_on = None
    _FakeHub.stall_gate = None
    _FakeHub.fail_on = None
    _FakeHub.requested = []

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeHub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    monkeypatch.setenv("HF_ENDPOINT", f"http://127.0.0.1:{server.server_address[1]}")
    monkeypatch.setattr(installer, "resolve_model_home", lambda: tmp_path / "models")
    monkeypatch.setattr(installer, "active_repo_id", lambda: REPO)
    # The library check is a find_spec on sentence_transformers, which is not
    # installed in CI. Every test that exercises the transfer answers it true;
    # the tests ABOUT the missing library set it false themselves.
    monkeypatch.setattr(installer, "semantic_library_available", lambda: True)
    installer.reset_state_for_tests()

    yield server

    server.shutdown()
    server.server_close()
    installer.reset_state_for_tests()


# ── Which deployment downloads ───────────────────────────────────────────


def test_a_server_deploy_does_not_start_a_download(monkeypatch: pytest.MonkeyPatch, hub) -> None:
    """The founder's ruling, stated as a test: the VPS does not need this."""
    monkeypatch.delenv("OE_DESKTOP", raising=False)
    monkeypatch.delenv(installer.ENV_DOWNLOAD, raising=False)

    assert installer.download_enabled() is False
    assert installer.start_background_download() is False
    # Not merely "no thread": nothing reached the network either.
    assert _FakeHub.requested == []


def test_a_desktop_install_starts_the_download(monkeypatch: pytest.MonkeyPatch, hub) -> None:
    monkeypatch.setenv("OE_DESKTOP", "1")
    monkeypatch.delenv(installer.ENV_DOWNLOAD, raising=False)

    assert installer.download_enabled() is True
    assert installer.start_background_download() is True

    _await_state(installer.STATE_READY)
    assert installer.find_installed_model(REPO) is not None


def test_one_variable_overrides_the_default_in_both_directions(monkeypatch: pytest.MonkeyPatch, hub) -> None:
    """An operator who wants an encoder on a server can have one, and vice versa."""
    monkeypatch.delenv("OE_DESKTOP", raising=False)
    monkeypatch.setenv(installer.ENV_DOWNLOAD, "1")
    assert installer.download_enabled() is True

    monkeypatch.setenv("OE_DESKTOP", "1")
    monkeypatch.setenv(installer.ENV_DOWNLOAD, "0")
    assert installer.download_enabled() is False
    assert installer.start_background_download() is False

    # An explicit off is a policy about the machine, so even a person clicking
    # the install button does not overrule it.
    assert installer.start_background_download(requested=True) is False
    assert _FakeHub.requested == []


def test_a_click_downloads_where_the_default_would_not(monkeypatch: pytest.MonkeyPatch, hub) -> None:
    """The default only answers "should this happen unasked"."""
    monkeypatch.delenv("OE_DESKTOP", raising=False)
    monkeypatch.delenv(installer.ENV_DOWNLOAD, raising=False)

    assert installer.start_background_download() is False
    assert installer.start_background_download(requested=True) is True
    _await_state(installer.STATE_READY)


# ── What a half-finished download leaves behind ──────────────────────────


def test_an_interrupted_download_leaves_no_loadable_partial(hub) -> None:
    _FakeHub.fail_on = "model.safetensors"

    with pytest.raises(RuntimeError):
        installer.install_embedding_model(repo_id=REPO)

    target = installer.local_model_dir(REPO)
    # The marker is the only thing the loader consults, and it was never written.
    assert installer.find_installed_model(REPO) is None
    assert not (target / installer.MARKER_FILENAME).exists()
    # The truncated weights never became a file anything could open, and the
    # rubble is gone rather than sitting on the user's disk.
    assert not (target / "model.safetensors").exists()
    assert list(target.rglob("*" + installer.PART_SUFFIX)) == []

    status = installer.download_status(repo_id=REPO)
    assert status["state"] == installer.STATE_FAILED
    assert status["error"]


def test_a_retry_after_an_interruption_completes(hub) -> None:
    _FakeHub.fail_on = "model.safetensors"
    with pytest.raises(RuntimeError):
        installer.install_embedding_model(repo_id=REPO)

    _FakeHub.fail_on = None
    installer.reset_state_for_tests()
    target = installer.install_embedding_model(repo_id=REPO)

    assert installer.find_installed_model(REPO) == target
    assert (target / "model.safetensors").read_bytes() == HUB_FILES["model.safetensors"]


def test_a_resumed_transfer_appends_rather_than_starting_over(hub, tmp_path: Path) -> None:
    """The part file is a resume point, so a big file is not paid for twice."""
    payload = HUB_FILES["model.safetensors"]
    dest = tmp_path / "models" / installer._slug(REPO) / "model.safetensors"
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + installer.PART_SUFFIX)
    part.write_bytes(payload[:500])

    installer._download_one(installer._file_url(REPO, "model.safetensors"), dest)

    assert dest.read_bytes() == payload
    assert not part.exists()


# ── One download at a time, and the app stays up during it ───────────────


def test_a_second_call_while_one_is_running_does_not_start_a_second_download(hub) -> None:
    gate = threading.Event()
    _FakeHub.stall_on = "model.safetensors"
    _FakeHub.stall_gate = gate

    first = threading.Thread(target=lambda: installer.install_embedding_model(repo_id=REPO), daemon=True)
    first.start()
    _await_state(installer.STATE_DOWNLOADING)

    # Both shapes of "ask again" while one is in flight.
    installer.install_embedding_model(repo_id=REPO)
    assert installer.start_background_download(requested=True) is False

    gate.set()
    first.join(timeout=30)

    # The heavy file was fetched exactly once. A second downloader would have
    # asked for it again, and the counter would say two.
    assert _FakeHub.requested.count("model.safetensors") == 1
    assert installer.find_installed_model(REPO) is not None


def test_the_application_answers_requests_while_the_download_runs(hub) -> None:
    """Proved by measuring, not asserted.

    The transfer holds the install lock for its whole duration. If status read
    that same lock, every poll during a multi-minute download would block on
    it, and the UI showing the progress would be the thing the progress hangs.
    """
    gate = threading.Event()
    _FakeHub.stall_on = "model.safetensors"
    _FakeHub.stall_gate = gate

    worker = threading.Thread(target=lambda: installer.install_embedding_model(repo_id=REPO), daemon=True)
    worker.start()
    _await_state(installer.STATE_DOWNLOADING)

    try:
        for _ in range(20):
            started = time.monotonic()
            status = installer.download_status(repo_id=REPO)
            elapsed = time.monotonic() - started
            assert elapsed < 1.0, f"status blocked for {elapsed:.2f}s behind the download"
            assert status["state"] == installer.STATE_DOWNLOADING
            assert status["installed"] is False
    finally:
        gate.set()
        worker.join(timeout=30)

    assert installer.download_status(repo_id=REPO)["state"] == installer.STATE_READY


# ── The weights are used once they land ──────────────────────────────────


def test_a_finished_download_unlatches_the_embedder(hub, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without this the download is decorative until the next restart.

    ``get_embedder`` latches its failure for the life of the process on purpose.
    A first boot with no weights on disk fails that load and sets the latch, so
    weights arriving ten minutes later would be ignored and semantic search
    would keep answering 503 until someone restarted the server.
    """
    monkeypatch.setattr(vector, "_embedder_tried", True)
    monkeypatch.setattr(vector, "_has_module", lambda _name: True)
    assert vector.embedder_status()["state"] == "load_failed"

    installer.install_embedding_model(repo_id=REPO)

    assert vector._embedder_tried is False
    assert vector.embedder_status()["state"] == "not_loaded"


def test_the_loader_prefers_the_downloaded_copy(hub, monkeypatch: pytest.MonkeyPatch) -> None:
    """Otherwise the weights land somewhere nothing looks."""
    assert vector._candidate_sources(REPO) == [REPO]

    target = installer.install_embedding_model(repo_id=REPO)

    assert vector._candidate_sources(REPO) == [str(target), REPO]


def test_a_finished_download_does_not_evict_a_working_embedder(hub, monkeypatch: pytest.MonkeyPatch) -> None:
    """Evicting one would put a cold model load inside the next request.

    An embedder that is already answering means the process found weights some
    other way. Dropping it so the next caller reloads from the freshly
    downloaded copy trades a working answer for tens of seconds of blocking in
    a request thread, at a moment nobody asked for, to gain at most a better
    model. The upgrade waits for the next restart, which costs nobody anything.
    """
    sentinel = object()
    monkeypatch.setattr(vector, "_embedder_instance", sentinel)
    monkeypatch.setattr(vector, "_embedder_tried", True)

    installer.install_embedding_model(repo_id=REPO)

    assert vector._embedder_instance is sentinel


# ── What the real hub actually publishes ─────────────────────────────────

#: The genuine listing of ``intfloat/multilingual-e5-small``, the model this
#: platform configures, captured from the hub's own metadata API on 2026-08-17.
#: A file filter validated only against a listing this test file invented
#: proves nothing about the repo it will really meet.
_REAL_LISTING = [
    ".eval_results/ArguAna.yaml",
    ".eval_results/BrightAopsRetrieval.yaml",
    ".eval_results/BrightBiologyRetrieval.yaml",
    ".gitattributes",
    "1_Pooling/config.json",
    "README.md",
    "config.json",
    "model.safetensors",
    "modules.json",
    "onnx/config.json",
    "onnx/model.onnx",
    "onnx/model_qint8_avx512_vnni.onnx",
    "onnx/sentencepiece.bpe.model",
    "onnx/tokenizer.json",
    "openvino/openvino_model.bin",
    "openvino/openvino_model.xml",
    "pytorch_model.bin",
    "sentence_bert_config.json",
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
]


def test_the_real_listing_keeps_every_loader_input_and_nothing_else() -> None:
    """The filter is only as good as the listing it was written against."""
    kept = installer._select_files(_REAL_LISTING)

    # Everything sentence-transformers reads to build the model.
    assert set(kept) == {
        "1_Pooling/config.json",
        "config.json",
        "model.safetensors",
        "modules.json",
        "sentence_bert_config.json",
        "sentencepiece.bpe.model",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
    }

    # The tokenizer of a multilingual model is a .model file. A filter that
    # skipped that suffix as "some other runtime's weights" would download a
    # model that cannot turn text into tokens.
    assert "sentencepiece.bpe.model" in kept

    # Weights are published four times over here. Taking the duplicates is the
    # difference between one download and roughly four.
    assert "pytorch_model.bin" not in kept
    assert not any(k.startswith(("onnx/", "openvino/")) for k in kept)

    # Benchmark scores and repo metadata are not model inputs, and they are 21
    # of the 42 entries upstream: counted as files they would own the progress
    # bar without moving a byte of the weights.
    assert not any(k.startswith(".") for k in kept)
    assert "README.md" not in kept


def test_the_pickled_weights_are_taken_when_safetensors_are_absent() -> None:
    """A repo published the old way still has to install."""
    kept = installer._select_files([n for n in _REAL_LISTING if not n.endswith(".safetensors")])

    assert "pytorch_model.bin" in kept


def test_an_operator_switching_it_off_is_distinct_from_it_merely_defaulting_off(
    hub, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise the wizard draws a toggle the operator already disabled.

    A server defaults to off and still honours a deliberate click, so the
    toggle there is real. A production unit that sets the variable to 0 refuses
    that click too - correctly - and if the status cannot say so the user ticks
    the box, presses Continue, and nothing happens with nothing said.
    """
    monkeypatch.delenv("OE_DESKTOP", raising=False)
    monkeypatch.delenv(installer.ENV_DOWNLOAD, raising=False)

    # Off by default, but a click is still live. That the click actually
    # downloads is pinned by test_a_click_downloads_where_the_default_would_not;
    # what matters here is that the status does not claim it is disabled.
    defaulted_off = installer.download_status(repo_id=REPO)
    assert defaulted_off["enabled"] is False
    assert defaulted_off["locked"] is False

    monkeypatch.setenv(installer.ENV_DOWNLOAD, "0")

    locked = installer.download_status(repo_id=REPO)
    assert locked["enabled"] is False
    assert locked["locked"] is True
    assert installer.ENV_DOWNLOAD in locked["message"]
    assert installer.start_background_download(requested=True) is False
    assert _FakeHub.requested == []


# ── Refusals and the five states ─────────────────────────────────────────


def test_the_installer_refuses_when_the_semantic_library_is_absent(hub, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fetching weights nothing can load is not an extra, it is waste."""
    monkeypatch.setattr(installer, "semantic_library_available", lambda: False)
    monkeypatch.setenv("OE_DESKTOP", "1")

    assert installer.start_background_download() is False
    assert installer.start_background_download(requested=True) is False
    assert _FakeHub.requested == []

    with pytest.raises(RuntimeError) as raised:
        installer.install_embedding_model(repo_id=REPO)
    assert "semantic" in str(raised.value)

    status = installer.download_status(repo_id=REPO)
    assert status["state"] == installer.STATE_LIBRARY_MISSING
    assert status["library_installed"] is False


def test_the_five_situations_are_told_apart(hub, monkeypatch: pytest.MonkeyPatch) -> None:
    """A reader who cannot tell them apart cannot act, so each names its remedy."""
    monkeypatch.delenv("OE_DESKTOP", raising=False)
    monkeypatch.delenv(installer.ENV_DOWNLOAD, raising=False)
    monkeypatch.setattr(vector, "_embedder_instance", None)
    monkeypatch.setattr(vector, "_embedder_tried", False)
    monkeypatch.setattr(vector, "_has_module", lambda _name: True)

    not_requested = installer.download_status(repo_id=REPO)
    assert not_requested["state"] == installer.STATE_NOT_REQUESTED
    assert not_requested["enabled"] is False
    assert installer.ENV_DOWNLOAD in not_requested["message"]

    installer.install_embedding_model(repo_id=REPO)
    ready = installer.download_status(repo_id=REPO)
    # Weights on disk read as ready even though nothing has loaded them into
    # memory yet. embedder_status() correctly says "not_loaded" to its own
    # question; a caller asking "will semantic search answer" would read that
    # as a no, and calling a working install unavailable is the dishonesty the
    # 503 work just removed.
    assert ready["state"] == installer.STATE_READY
    assert ready["embedder"]["state"] == "not_loaded"
    assert ready["percent"] == 100

    monkeypatch.setattr(installer, "semantic_library_available", lambda: False)
    assert installer.download_status(repo_id=REPO)["state"] == installer.STATE_LIBRARY_MISSING


def test_the_missing_library_outranks_every_other_state(hub, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing else is actionable while there is no encoder to load at all."""
    installer.install_embedding_model(repo_id=REPO)
    assert installer.download_status(repo_id=REPO)["state"] == installer.STATE_READY

    monkeypatch.setattr(installer, "semantic_library_available", lambda: False)
    assert installer.download_status(repo_id=REPO)["state"] == installer.STATE_LIBRARY_MISSING


# ── The file filter ──────────────────────────────────────────────────────


def test_the_filter_takes_one_serialisation_of_the_weights(hub) -> None:
    """The difference between one download and several gigabytes of them."""
    chosen = installer._resolve_file_list(REPO)

    assert "model.safetensors" in chosen
    assert "config.json" in chosen
    assert "1_Pooling/config.json" in chosen
    for dropped in ("pytorch_model.bin", "onnx/model.onnx", "README.md"):
        assert dropped not in chosen


def test_the_pickled_weights_are_taken_when_there_is_no_safetensors() -> None:
    """A repo published the old way still installs."""
    chosen = installer._select_files(["config.json", "pytorch_model.bin", "tokenizer.json"])

    assert chosen == ["config.json", "pytorch_model.bin", "tokenizer.json"]


def test_a_listing_that_escapes_the_install_directory_is_refused(hub, monkeypatch: pytest.MonkeyPatch) -> None:
    """A repo id is caller-influenced in principle; a path is never trusted."""
    monkeypatch.setattr(installer, "_resolve_file_list", lambda _repo: ["../escaped.json"])

    with pytest.raises(RuntimeError) as raised:
        installer.install_embedding_model(repo_id=REPO)
    assert "outside" in str(raised.value)


def test_a_hub_that_lists_no_files_is_a_failure_not_an_empty_install(hub, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(installer, "_resolve_file_list", lambda _repo: [])

    with pytest.raises(RuntimeError) as raised:
        installer.install_embedding_model(repo_id=REPO)
    # No config.json means it is not a model, so no marker is written over it.
    assert "config.json" in str(raised.value)
    assert installer.find_installed_model(REPO) is None


# ── Idempotence ──────────────────────────────────────────────────────────


def test_installing_twice_is_a_no_op_the_second_time(hub) -> None:
    first = installer.install_embedding_model(repo_id=REPO)
    fetched_once = list(_FakeHub.requested)

    second = installer.install_embedding_model(repo_id=REPO)

    assert first == second
    assert _FakeHub.requested == fetched_once


# ── What the desktop splash is told ──────────────────────────────────────


def test_progress_reaches_the_splash_as_stage_markers(hub, capsys: pytest.CaptureFixture) -> None:
    installer.install_embedding_model(repo_id=REPO)

    markers = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("STAGE:model:")]

    assert any(ln.startswith("STAGE:model:start") for ln in markers)
    assert any(ln.startswith("STAGE:model:progress") for ln in markers)
    assert any(ln.startswith("STAGE:model:done") for ln in markers)


def test_a_failed_download_never_claims_the_boot_failed(hub, capsys: pytest.CaptureFixture) -> None:
    """The launcher latches the first STAGE fail as the cause of a failed boot.

    Reported to the user as why the application did not start. An optional
    extra that could not download must therefore never emit one, or the
    loudest thing in the product would be an untrue claim that it is broken.
    """
    _FakeHub.fail_on = "model.safetensors"

    with pytest.raises(RuntimeError):
        installer.install_embedding_model(repo_id=REPO)

    markers = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("STAGE:")]

    assert markers, "the step should still be reported, just not as a failure"
    assert not any(ln.startswith("STAGE:model:fail") for ln in markers)
    assert any("optional" in ln for ln in markers)
    # The real reason is still recoverable - it just travels where an operator
    # acts on it rather than on the splash screen.
    assert installer.download_status(repo_id=REPO)["error"]


# ── The endpoints ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_status_endpoint_reports_without_loading_anything(hub) -> None:
    from app.modules.ai_estimator.router import embedding_model_status

    payload = await embedding_model_status("user-1")

    assert payload["state"] == installer.STATE_NOT_REQUESTED
    assert payload["model"] == REPO
    assert payload["env_var"] == installer.ENV_DOWNLOAD
    # The composed embedder view travels with it, so a caller never has to
    # correlate two endpoints to work out whether search will answer.
    assert "state" in payload["embedder"]


@pytest.mark.asyncio
async def test_the_install_endpoint_answers_rather_than_erroring_when_it_cannot(
    hub, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No exception from this path may reach a request handler.

    A deployment that cannot download says so in the state it returns. Turning
    it into a 500 would make an optional extra look like a broken server.
    """
    from app.modules.ai_estimator.router import embedding_model_install

    monkeypatch.setattr(installer, "semantic_library_available", lambda: False)

    payload = await embedding_model_install("user-1")

    assert payload["started"] is False
    assert payload["state"] == installer.STATE_LIBRARY_MISSING
    assert payload["message"]


@pytest.mark.asyncio
async def test_the_install_endpoint_returns_while_the_transfer_is_still_running(hub) -> None:
    """The request finishes; the download does not have to."""
    from app.modules.ai_estimator.router import embedding_model_install, embedding_model_status

    gate = threading.Event()
    _FakeHub.stall_on = "model.safetensors"
    _FakeHub.stall_gate = gate

    started = time.monotonic()
    payload = await embedding_model_install("user-1")
    assert time.monotonic() - started < 5.0

    try:
        assert payload["started"] is True
        _await_state(installer.STATE_DOWNLOADING)
        # And the status endpoint keeps answering with the transfer stuck.
        during = await embedding_model_status("user-1")
        assert during["state"] == installer.STATE_DOWNLOADING
        assert during["installed"] is False
    finally:
        gate.set()
        _await_state(installer.STATE_READY)


def _await_state(state: str, timeout_s: float = 30.0) -> None:
    """Wait for the installer to report ``state``, or fail saying what it says."""
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        last = installer.download_status(repo_id=REPO)["state"]
        if last == state:
            return
        time.sleep(0.02)
    raise AssertionError(f"installer never reached {state!r}; last state was {last!r}")


def test_the_lock_keeps_the_loader_off_the_hub_as_well(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The download lock has to reach the loader, not only the installer.

    ``download_locked_off`` tells an operator that a production unit will not
    fetch the model. The installer honoured that and ``_candidate_sources`` did
    not: it kept the bare hub id as a candidate, so ``SentenceTransformer``
    resolved it over the network on the first embed anyway. Measured on a first
    run of a shipped build with the lock set, the log carried thirty-four
    requests to the model hub. They returned quickly only because a cache was
    warm; on the air-gapped unit the lock exists for, they are a stall.

    Both polarities are asserted on purpose. A test that only checked the
    locked case would also pass on a function that never offers the hub id at
    all, and that would quietly take semantic search away from every ordinary
    deployment, which is the larger of the two mistakes.
    """
    monkeypatch.setattr(installer, "find_installed_model", lambda name: None)

    # Unlocked and nothing installed: the hub id is the one candidate, exactly
    # as before this behaviour existed.
    monkeypatch.delenv(installer.ENV_DOWNLOAD, raising=False)
    assert vector._candidate_sources(REPO) == [REPO]

    # Locked and nothing installed: nothing is left to try, and saying so beats
    # a slow network failure that reads as a hang.
    monkeypatch.setenv(installer.ENV_DOWNLOAD, "0")
    assert vector._candidate_sources(REPO) == []

    local = tmp_path / "weights"
    local.mkdir()
    monkeypatch.setattr(installer, "find_installed_model", lambda name: local)

    # Locked with a local copy: the copy is used and the hub is not consulted.
    assert vector._candidate_sources(REPO) == [str(local)]

    # Unlocked with a local copy: the copy first, the hub still available.
    monkeypatch.delenv(installer.ENV_DOWNLOAD, raising=False)
    assert vector._candidate_sources(REPO) == [str(local), REPO]
