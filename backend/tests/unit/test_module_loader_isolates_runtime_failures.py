# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
#
# An installed (runtime) module that no longer fits the platform must not take
# the whole backend down on boot. It is skipped, persisted as disabled, and its
# dependents are not started; shipped modules keep failing loudly (#568).

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI

from app.core import module_state
from app.core.module_loader import ModuleLoader, served_paths
from app.core.module_runtime_root import attach_runtime_root, detach_runtime_root
from app.database import Base


def _write_module(
    root: Path,
    dir_name: str,
    *,
    depends: list[str] | None = None,
    requires_platform: str | None = None,
    manifest_body: str = "",
    init_body: str = "",
    router: bool = False,
    models_body: str | None = None,
    category: str = "community",
) -> str:
    d = root / dir_name
    d.mkdir(parents=True)
    (d / "__init__.py").write_text(init_body, encoding="utf-8")
    (d / "manifest.py").write_text(
        manifest_body
        + "from app.core.module_loader import ModuleManifest\n\n"
        + f"manifest = ModuleManifest(name='oe_{dir_name}', version='1.0.0', display_name='{dir_name}', "
        + f"category='{category}', depends={depends or []!r})\n",
        encoding="utf-8",
    )
    if requires_platform is not None:
        (d / "module.json").write_text(json.dumps({"requires_platform": requires_platform}), encoding="utf-8")
    if router:
        (d / "router.py").write_text(
            "from fastapi import APIRouter\n\nrouter = APIRouter()\n\n\n"
            "@router.get('/ping')\nasync def ping():\n    return {'ok': True}\n",
            encoding="utf-8",
        )
    if models_body is not None:
        (d / "models.py").write_text(models_body, encoding="utf-8")
    return f"oe_{dir_name}"


@pytest.fixture
def runtime_root(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    root.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(module_state, "_resolve_data_dir", lambda data_dir=None: data_dir or state_dir)
    attach_runtime_root(root, create=False)
    yield root
    detach_runtime_root(root)


def _loader_for(root: Path, *, rank: int | None = None) -> ModuleLoader:
    loader = ModuleLoader()
    if rank is None:
        loader.discover = lambda modules_dir=None: ModuleLoader.discover(loader, root)  # type: ignore[method-assign]
    else:
        loader.discover = lambda modules_dir=None: loader._discover_in(root, root_rank=rank)  # type: ignore[method-assign]
    return loader


def _tag() -> str:
    return "zz" + uuid.uuid4().hex[:8]


async def test_incompatible_runtime_module_is_skipped_without_executing(runtime_root):
    tag = _tag()
    bad = _write_module(
        runtime_root,
        f"{tag}_old",
        requires_platform=">=999",
        manifest_body="raise RuntimeError('manifest must not execute')\n",
    )
    good = _write_module(runtime_root, f"{tag}_fine", requires_platform=">=1.0")
    loader = _loader_for(runtime_root)

    await loader.load_all(FastAPI())

    assert good in loader.loaded_modules
    assert bad not in loader.loaded_modules
    row = next(m for m in loader.list_modules() if m["name"] == bad)
    assert row["failed"] is True
    assert row["enabled"] is False
    assert "999" in row["failure_reason"]
    assert module_state.load_module_states()[bad].enabled is False


async def test_startup_failure_isolated_routes_removed_and_dependents_skipped(runtime_root):
    tag = _tag()
    broken = _write_module(
        runtime_root,
        f"{tag}_boom",
        router=True,
        init_body="async def on_startup():\n    raise RuntimeError('incompatible API')\n",
    )
    dependent = _write_module(runtime_root, f"{tag}_child", depends=[broken])
    loader = _loader_for(runtime_root)
    app = FastAPI()

    await loader.load_all(app)

    assert broken not in loader.loaded_modules
    assert dependent not in loader.loaded_modules
    assert not any(f"{tag}-boom" in p or f"{tag}_boom" in p for p in served_paths(app))
    rows = {m["name"]: m for m in loader.list_modules()}
    assert "incompatible API" in rows[broken]["failure_reason"]
    assert broken in rows[dependent]["failure_reason"]
    states = module_state.load_module_states()
    assert states[broken].enabled is False
    # A dependent is not broken itself; it only waits for its dependency.
    assert dependent not in states


async def test_broken_models_leave_no_tables_behind(runtime_root):
    tag = _tag()
    table = f"oe_{tag}_thing"
    broken = _write_module(
        runtime_root,
        f"{tag}_models",
        models_body=(
            "from sqlalchemy import String\n"
            "from sqlalchemy.orm import Mapped, mapped_column\n"
            "from app.database import Base\n\n\n"
            f"class Thing(Base):\n    __tablename__ = '{table}'\n"
            "    label: Mapped[str] = mapped_column(String(10))\n\n\n"
            "from app.modules.does_not_exist_anymore import gone  # noqa\n"
        ),
    )
    loader = _loader_for(runtime_root)

    await loader.load_all(FastAPI())

    assert broken not in loader.loaded_modules
    assert table not in Base.metadata.tables


async def test_disabled_failure_survives_restart_and_is_not_reenabled(runtime_root):
    tag = _tag()
    broken = _write_module(
        runtime_root, f"{tag}_once", init_body="async def on_startup():\n    raise RuntimeError('nope')\n"
    )
    await _loader_for(runtime_root).load_all(FastAPI())

    second = _loader_for(runtime_root)
    await second.load_all(FastAPI())

    assert broken not in second.loaded_modules
    assert second.is_enabled(broken) is False
    assert module_state.load_module_states()[broken].enabled is False


async def test_shipped_module_failure_still_aborts_boot(runtime_root):
    tag = _tag()
    _write_module(
        runtime_root, f"{tag}_core", init_body="async def on_startup():\n    raise RuntimeError('core bug')\n"
    )
    loader = _loader_for(runtime_root, rank=0)

    with pytest.raises(RuntimeError, match="core bug"):
        await loader.load_all(FastAPI())
