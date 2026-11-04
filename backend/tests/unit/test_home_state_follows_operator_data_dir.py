"""Persistent state follows ``OE_DATA_DIR`` instead of the account's home.

In the container image the service account's home is ``/app``, inside the image
layer. Every writer here used to put its state under ``~/.openestimate`` or
``~/.openestimator`` and so lost it whenever the container was recreated. Each
test points ``OE_DATA_DIR`` at one temp dir and the home at another, runs the
writer, and checks the file landed in the data dir and nothing landed at home.
"""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core import home_state


def _files_under(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: fake_home))
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    for name in (
        "OE_DATA_DIR",
        "DATA_DIR",
        "OE_CLI_DATA_DIR",
        "OE_RUNTIME_MODULES_DIR",
        "MEETING_SIGNATURE_DIR",
        "CWICR_PARQUET_ROOT",
    ):
        monkeypatch.delenv(name, raising=False)
    return fake_home


@pytest.fixture
def data_dir(tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    target = tmp_path / "data"
    monkeypatch.setenv("OE_DATA_DIR", str(target))
    yield target
    assert _files_under(home) == [], "a writer put persistent state under the home directory"


# ── Writers ───────────────────────────────────────────────────────────────


def test_module_states_land_in_the_data_dir(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.module_state import load_module_states, set_module_enabled

    monkeypatch.delenv("DATABASE_URL", raising=False)
    set_module_enabled("oe_widgets", False)

    assert (data_dir / "module_states.json").is_file()
    assert load_module_states()["oe_widgets"].enabled is False


def test_applied_pack_lands_in_the_data_dir(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.partner_pack.state import AppliedPackState, load_applied_state, save_applied_state

    monkeypatch.setenv("OE_CLI_DATA_DIR", str(data_dir.parent / "cli"))
    save_applied_state(AppliedPackState(slug="acme", pack_version="1.0.0"))

    assert (data_dir / "pack_state.json").is_file()
    state = load_applied_state()
    assert state is not None
    assert state.slug == "acme"


def test_translation_dictionaries_land_in_the_data_dir(data_dir: Path) -> None:
    from app.core.translation.paths import translations_root

    root = translations_root()
    (root / "probe.tsv").write_text("a\tb\n", encoding="utf-8")

    assert root == data_dir / "translations"


def test_meeting_signatures_land_in_the_data_dir(data_dir: Path) -> None:
    from app.modules.meetings.service import _save_signature_image

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    saved = asyncio.run(_save_signature_image(uuid.uuid4(), base64.b64encode(png).decode("ascii")))

    assert Path(saved).is_relative_to(data_dir / "meetings" / "signatures")
    assert Path(saved).is_file()


def test_meeting_transcripts_land_in_the_data_dir(data_dir: Path) -> None:
    from app.modules.meetings.router import _transcript_upload_dir

    project_id = uuid.uuid4()
    target = _transcript_upload_dir(project_id)
    target.mkdir(parents=True)
    (target / "t.txt").write_text("minutes", encoding="utf-8")

    assert target == data_dir / "uploads" / str(project_id)


def test_match_photos_land_in_the_data_dir(data_dir: Path) -> None:
    from app.modules.match_elements.router import _match_images_dir

    assert _match_images_dir() == data_dir / "match_images"


def test_resumable_chunks_land_in_the_data_dir(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.resumable_uploads import chunk_store

    monkeypatch.setenv("OE_CLI_DATA_DIR", str(data_dir.parent / "cli"))
    session_id = uuid.uuid4()
    chunk_store.write_chunk(session_id, 0, b"chunk")

    assert chunk_store.chunk_path(session_id, 0).is_relative_to(data_dir / "resumable")
    assert chunk_store.has_chunk(session_id, 0)


def test_runtime_modules_land_in_the_data_dir(data_dir: Path) -> None:
    from app.core.module_runtime_root import runtime_modules_dir

    assert runtime_modules_dir() == data_dir / "modules"


def test_converters_install_into_the_data_dir_and_legacy_installs_stay_found(data_dir: Path, home: Path) -> None:
    from app.core.converter_source import converter_install_root, converter_install_roots

    assert converter_install_root() == data_dir / "converters"
    assert converter_install_roots() == [data_dir / "converters", home / ".openestimator" / "converters"]


def test_cwicr_indexes_and_vectors_land_in_the_data_dir(data_dir: Path) -> None:
    from app.core.vector import _get_vector_dir
    from app.modules.costs.parquet_lookup import _resolve_root
    from app.modules.costs.qdrant_adapter import resolve_cwicr_target

    settings = type("S", (), {"cwicr_qdrant_url": None, "cwicr_qdrant_path": ""})()

    assert Path(resolve_cwicr_target(settings).location) == data_dir / "qdrant_cwicr"
    assert _resolve_root() == data_dir / "cwicr"
    assert _get_vector_dir() == data_dir / "data" / "vectors"


def test_demo_seed_choice_lands_in_the_data_dir(data_dir: Path) -> None:
    from app.core.demo_seed import write_demo_seed_choice

    write_demo_seed_choice(True)

    assert (data_dir / "demo_seed_choice.json").is_file()


# ── Desktop and pip installs: no operator data dir, nothing moves ─────────


def test_without_an_operator_data_dir_paths_stay_under_home(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.converter_source import converter_install_roots
    from app.core.module_runtime_root import runtime_modules_dir
    from app.core.module_state import _resolve_data_dir
    from app.modules.match_elements.router import _match_images_dir
    from app.modules.meetings.service import _signature_dir

    monkeypatch.delenv("DATABASE_URL", raising=False)
    # The desktop launcher always exports this; it must not move ~/.openestimator data.
    monkeypatch.setenv("OE_CLI_DATA_DIR", str(home / ".openestimate"))

    assert _resolve_data_dir() == home / ".openestimate"
    assert runtime_modules_dir() == home / ".openestimator" / "modules"
    assert _match_images_dir() == home / ".openestimator" / "match_images"
    assert _signature_dir() == home / ".openestimator" / "meetings" / "signatures"
    assert converter_install_roots() == [home / ".openestimator" / "converters"]


def test_a_populated_legacy_index_keeps_being_used(home: Path, data_dir: Path) -> None:
    legacy = home / ".openestimator" / "qdrant_cwicr"
    legacy.mkdir(parents=True)
    (legacy / "meta.json").write_text("{}", encoding="utf-8")

    assert home_state.home_state_dir_or_legacy(".openestimator", "qdrant_cwicr") == legacy
    (data_dir / "qdrant_cwicr").mkdir(parents=True)
    assert home_state.home_state_dir_or_legacy(".openestimator", "qdrant_cwicr") == data_dir / "qdrant_cwicr"
    # The fixture's "nothing under home" check does not apply to a file the test planted.
    (legacy / "meta.json").unlink()


# ── One-time copy of legacy state ─────────────────────────────────────────


def _plant_legacy(home: Path) -> None:
    (home / ".openestimate").mkdir(parents=True)
    (home / ".openestimate" / "module_states.json").write_text('{"oe_x": {"enabled": false}}', encoding="utf-8")
    sig = home / ".openestimator" / "meetings" / "signatures"
    sig.mkdir(parents=True)
    (sig / "a.png").write_bytes(b"png")


def test_legacy_state_is_copied_once_and_kept(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "data"
    monkeypatch.setenv("OE_DATA_DIR", str(data))
    _plant_legacy(home)

    migrated = home_state.migrate_legacy_home_state()

    assert set(migrated) == {".openestimate/module_states.json", ".openestimator/meetings/signatures"}
    assert json.loads((data / "module_states.json").read_text(encoding="utf-8")) == {"oe_x": {"enabled": False}}
    assert (data / "meetings" / "signatures" / "a.png").read_bytes() == b"png"
    # Never deleted.
    assert (home / ".openestimate" / "module_states.json").is_file()
    assert (home / ".openestimator" / "meetings" / "signatures" / "a.png").is_file()

    # Once: a later change in the data dir is not overwritten or re-copied.
    (data / "module_states.json").write_text("{}", encoding="utf-8")
    (data / "meetings" / "signatures" / "a.png").unlink()
    assert home_state.migrate_legacy_home_state() == []
    assert (data / "module_states.json").read_text(encoding="utf-8") == "{}"
    assert not (data / "meetings" / "signatures" / "a.png").exists()


def test_legacy_copy_never_overwrites_the_data_dir(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "module_states.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("OE_DATA_DIR", str(data))
    _plant_legacy(home)

    home_state.migrate_legacy_home_state()

    assert (data / "module_states.json").read_text(encoding="utf-8") == "{}"


def test_legacy_copy_is_a_no_op_without_an_operator_data_dir(home: Path) -> None:
    _plant_legacy(home)

    assert home_state.migrate_legacy_home_state() == []


def test_legacy_copy_skips_when_the_data_dir_is_the_legacy_dir(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OE_DATA_DIR", str(home / ".openestimate"))
    _plant_legacy(home)

    assert ".openestimate/module_states.json" not in home_state.migrate_legacy_home_state()
