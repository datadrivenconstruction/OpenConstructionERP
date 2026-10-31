"""Third-party module ZIP install (#540): validation rules, permissions, lifecycle."""

from __future__ import annotations

import asyncio
import io
import json
import re
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.core import module_package as pkg
from app.core.permissions import Role, permission_registry
from app.middleware.module_ui_scope import token_scope

MANIFEST = """from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_zipdemo",
    version="1.2.0",
    display_name="Zip demo",
    author="Example",
    category="community",
    depends=[],
)
"""
ROUTER = """from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/ui/", response_class=HTMLResponse)
async def page() -> str:
    return "<p>demo</p>"
"""
UI = {
    "label": "Zip demo",
    "group": "grp_estimating",
    "icon": "package",
    "mode": "hosted",
    "path": "/api/v1/zipdemo/ui/",
}


def make_zip(files: dict[str, str], *, extra: list[zipfile.ZipInfo] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, text)
        for info in extra or []:
            zf.writestr(info, "x")
    return buf.getvalue()


def good_files(**descriptor: object) -> dict[str, str]:
    desc = {"requires_platform": ">=1.0", "ui": UI, **descriptor}
    return {
        "zipdemo/__init__.py": "",
        "zipdemo/manifest.py": MANIFEST,
        "zipdemo/router.py": ROUTER,
        "zipdemo/module.json": json.dumps(desc),
    }


def rules(preview: pkg.Preview, severity: str = "error") -> set[str]:
    return {c.rule_id for c in preview.checks if c.severity == severity}


@pytest.fixture(autouse=True)
def _runtime_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "modules"
    monkeypatch.setenv("OE_RUNTIME_MODULES_DIR", str(root))
    monkeypatch.setattr(pkg, "platform_version", lambda: "18.9.0")
    return root


def inspect(data: bytes) -> pkg.Preview:
    return pkg.inspect_archive(data, known_modules={"oe_projects": "core"})


class TestValidationRules:
    def test_a_good_package_is_installable(self) -> None:
        preview = inspect(make_zip(good_files()))
        assert preview.installable, preview.checks
        assert preview.module_name == "oe_zipdemo"
        assert preview.ui and preview.ui["mode"] == "hosted"
        assert {f.path for f in preview.files} >= {"zipdemo/manifest.py", "zipdemo/router.py"}
        assert "trust.python" in rules(preview, "warning")

    def test_zip_slip_is_refused(self) -> None:
        files = good_files()
        files["zipdemo/../../evil.py"] = "x"
        assert "archive.unsafe_member" in rules(inspect(make_zip(files)))

    def test_symlink_is_refused(self) -> None:
        link = zipfile.ZipInfo("zipdemo/link.py")
        link.external_attr = (0o120777) << 16
        assert "archive.unsafe_member" in rules(inspect(make_zip(good_files(), extra=[link])))

    def test_disallowed_file_type_is_refused(self) -> None:
        files = good_files()
        files["zipdemo/tool.exe"] = "MZ"
        assert "archive.file_type" in rules(inspect(make_zip(files)))

    def test_two_top_level_dirs_are_refused(self) -> None:
        files = good_files()
        files["other/__init__.py"] = ""
        assert "layout.single_top" in rules(inspect(make_zip(files)))

    def test_missing_manifest_is_refused(self) -> None:
        files = good_files()
        del files["zipdemo/manifest.py"]
        assert "manifest.missing" in rules(inspect(make_zip(files)))

    def test_manifest_without_literal_name_is_refused(self) -> None:
        files = good_files()
        files["zipdemo/manifest.py"] = "manifest = ModuleManifest(name=compute())"
        assert "manifest.name" in rules(inspect(make_zip(files)))

    def test_core_category_is_refused(self) -> None:
        files = good_files()
        files["zipdemo/manifest.py"] = MANIFEST.replace('category="community"', 'category="core"')
        assert "manifest.category" in rules(inspect(make_zip(files)))

    def test_collision_with_installed_module_is_refused(self) -> None:
        preview = pkg.inspect_archive(make_zip(good_files()), known_modules={"oe_zipdemo": "community"})
        assert "manifest.collision" in rules(preview)

    def test_missing_dependency_is_reported(self) -> None:
        files = good_files()
        files["zipdemo/manifest.py"] = MANIFEST.replace("depends=[]", 'depends=["oe_nowhere"]')
        assert "compat.depends" in rules(inspect(make_zip(files)))

    def test_incompatible_platform_version_is_refused(self) -> None:
        assert "compat.platform" in rules(inspect(make_zip(good_files(requires_platform=">=19.0"))))

    def test_bad_version_range_is_refused(self) -> None:
        assert "compat.platform" in rules(inspect(make_zip(good_files(requires_platform="latest"))))

    @pytest.mark.parametrize(
        "path",
        ["https://evil.example/ui/", "/api/v1/projects/ui/", "/api/v1/zipdemo/../projects/", "javascript:alert(1)"],
    )
    def test_ui_path_outside_the_module_is_refused(self, path: str) -> None:
        assert "ui.path" in rules(inspect(make_zip(good_files(ui={**UI, "path": path}))))

    def test_unknown_group_and_icon_are_refused(self) -> None:
        preview = inspect(make_zip(good_files(ui={**UI, "group": "grp_nope", "icon": "skull"})))
        assert {"ui.group", "ui.icon"} <= rules(preview)

    def test_unsupported_ui_mode_is_refused(self) -> None:
        assert "ui.mode" in rules(inspect(make_zip(good_files(ui={**UI, "mode": "native"}))))

    def test_not_a_zip_raises(self) -> None:
        with pytest.raises(pkg.PackageRefused):
            inspect(b"not a zip at all")

    @pytest.mark.parametrize(
        ("version", "spec", "ok"),
        [("18.9.0", ">=18.9,<20", True), ("20.0.0", ">=18.9,<20", False), ("18.8.2", ">=18.9", False)],
    )
    def test_version_ranges(self, version: str, spec: str, ok: bool) -> None:
        assert pkg.version_satisfies(version, spec) is ok


def test_nav_groups_match_the_frontend_catalogue() -> None:
    catalog = Path(__file__).resolve().parents[3] / "frontend" / "src" / "app" / "layout" / "navCatalog.ts"
    ids = set(re.findall(r"id: '(grp_[a-z_]+)'", catalog.read_text(encoding="utf-8")))
    assert ids == set(pkg.KNOWN_NAV_GROUPS)


class TestAdminOnly:
    ROUTES = (
        ("POST", "/api/v1/module-packages/preview", "system.modules.install"),
        ("POST", "/api/v1/module-packages/{token}/install", "system.modules.install"),
        ("GET", "/api/v1/module-packages/installed", "system.modules.install"),
        ("DELETE", "/api/v1/module-packages/installed/{module_name}", "system.modules.uninstall"),
    )

    @pytest.mark.parametrize(("method", "path", "key"), ROUTES)
    def test_route_needs_admin_permission(self, method: str, path: str, key: str) -> None:
        from app.core.module_package_router import router

        route = next(r for r in router.routes if isinstance(r, APIRoute) and r.path == path and method in r.methods)
        assert key in {getattr(d.call, "permission", None) for d in route.dependant.dependencies}
        for role in (Role.MANAGER, Role.EDITOR, Role.VIEWER):
            assert permission_registry.role_has_permission(role, key) is False


class TestScopedToken:
    def test_scope_claim_is_read(self) -> None:
        from jose import jwt

        token = jwt.encode({"sub": "u", "oe_mod": "oe_zipdemo"}, "k", algorithm="HS256")
        assert token_scope(f"Bearer {token}") == "oe_zipdemo"
        assert token_scope(f"Bearer {jwt.encode({'sub': 'u'}, 'k', algorithm='HS256')}") is None
        assert token_scope(None) is None


class TestLifecycle:
    def test_install_enable_uninstall_roundtrip(self, _runtime_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.modules
        from app.core import module_state
        from app.core.module_loader import module_loader, served_paths

        monkeypatch.setattr(module_state, "set_module_enabled", lambda *a, **k: None)
        monkeypatch.setattr(module_loader, "discover", lambda *a, **k: module_loader._discover_in(_runtime_root))
        host = FastAPI()
        path_before = list(app.modules.__path__)
        try:
            preview = pkg.stage(make_zip(good_files()))
            assert preview.installable, preview.checks
            assert not (_runtime_root / "zipdemo").exists()

            result = asyncio.run(pkg.install(preview.token, host, enable=True, actor="admin"))
            assert result["status"] == "active"
            assert (_runtime_root / "zipdemo" / pkg.MARKER_FILE).is_file()
            assert "/api/v1/zipdemo/ui/" in set(served_paths(host))
            assert [e["module"] for e in pkg.ui_entries()] == ["oe_zipdemo"]
            assert "/api/v1/zipdemo" in pkg.hosted_prefixes()

            removed = asyncio.run(pkg.uninstall("oe_zipdemo", host))
            assert removed["status"] == "removed"
            assert not (_runtime_root / "zipdemo").exists()
            assert "oe_zipdemo" not in module_loader._manifests
            assert pkg.ui_entries() == []
        finally:
            module_loader.forget_module("oe_zipdemo")
            app.modules.__path__[:] = path_before
            for mod in [m for m in sys.modules if m.startswith("app.modules.zipdemo")]:
                del sys.modules[mod]

    def test_a_module_that_fails_to_load_is_removed(self, _runtime_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.modules
        from app.core import module_state
        from app.core.module_loader import module_loader

        monkeypatch.setattr(module_state, "set_module_enabled", lambda *a, **k: None)
        monkeypatch.setattr(module_loader, "discover", lambda *a, **k: module_loader._discover_in(_runtime_root))
        files = good_files()
        files["zipdemo/router.py"] = "raise RuntimeError('boom')\n"
        path_before = list(app.modules.__path__)
        try:
            preview = pkg.stage(make_zip(files))
            with pytest.raises(pkg.PackageRefused):
                asyncio.run(pkg.install(preview.token, FastAPI(), enable=True, actor="admin"))
            assert not (_runtime_root / "zipdemo").exists()
            assert "oe_zipdemo" not in module_loader._manifests
        finally:
            module_loader.forget_module("oe_zipdemo")
            app.modules.__path__[:] = path_before
            for mod in [m for m in sys.modules if m.startswith("app.modules.zipdemo")]:
                del sys.modules[mod]

    def test_unsigned_change_after_review_is_refused(self) -> None:
        preview = pkg.stage(make_zip(good_files()))
        (pkg.staging_root() / preview.token / "archive.zip").write_bytes(make_zip(good_files(requires_platform=">=1")))
        with pytest.raises(pkg.PackageRefused) as err:
            asyncio.run(pkg.install(preview.token, FastAPI(), enable=False, actor="admin"))
        assert err.value.code == "changed"

    def test_uninstall_refuses_a_shipped_module(self) -> None:
        with pytest.raises(pkg.PackageRefused):
            asyncio.run(pkg.uninstall("oe_projects", FastAPI()))
