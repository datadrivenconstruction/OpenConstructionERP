# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bringing an installed module's code up to the current generator, on boot.

The generator never overwrites a module directory, so a fix to what it renders
reaches modules built from then on and none of those already installed. When
the fix closes a hole, that is not good enough: the router written by the first
generator let anyone with the module's read permission see every project's
records. So at startup, before anything imports a runtime module, every
installed module whose ``spec.json`` names an older generator has its code files
rendered again from that spec.

What these tests hold the refresh to:

* only code is replaced. The table definition and the API schema must render
  byte for byte as they stand on disk, otherwise nothing is touched;
* a spec that no longer validates leaves its module exactly as it was;
* the swap is all or nothing, and the old code is kept;
* running it again does nothing.

The "old" files are the first generator's real output for these two specs,
captured before the generator changed and kept under ``tests/fixtures``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from app.modules.module_builder import generator, refresh
from app.modules.module_builder.spec import EntitySpec, FieldSpec, ModuleSpec, RuleSpec

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "module_builder_v1"
V1_STAMP = "openconstructionerp.module_builder/1"
V1_GENERATED_AT = "2026-08-10T09:00:00+00:00"
CODE_FILES = ("router.py", "repository.py", "service.py")


def hire_spec() -> ModuleSpec:
    """Project scoped: the case the refresh exists for."""
    return ModuleSpec(
        key="refresh_hire",
        display_name="Plant Hire",
        description="Hired plant per project, with its weekly rate.",
        entity=EntitySpec(
            name="hire",
            display_name="Hire",
            plural_name="Hires",
            project_scoped=True,
            fields=[
                FieldSpec(name="reference", label="Reference", type="text", required=True),
                FieldSpec(name="weekly_rate", label="Weekly rate", type="money", required=True),
                FieldSpec(name="on_hire_date", label="On hire", type="date"),
            ],
        ),
        rules=[
            RuleSpec(
                code="RATE_POSITIVE", message="A weekly rate must be above zero.", kind="positive", field="weekly_rate"
            )
        ],
    )


def notice_spec() -> ModuleSpec:
    """Not project scoped: refreshed too, and stays permission only."""
    return ModuleSpec(
        key="refresh_notice",
        display_name="Site Notice",
        entity=EntitySpec(
            name="notice",
            display_name="Notice",
            project_scoped=False,
            fields=[FieldSpec(name="title", label="Title", type="text", required=True)],
        ),
        rules=[RuleSpec(code="TITLE_REQUIRED", message="A notice needs a title.", kind="required", field="title")],
    )


def v1_bytes(key: str, path: str) -> bytes:
    """One file of the first generator's output, with the LF endings it wrote.

    Normalised because a checkout may have turned the fixture's line endings
    into CRLF, and the generator never wrote CRLF on any platform.
    """
    return (FIXTURES / key / f"{path}.v1").read_bytes().replace(b"\r\n", b"\n")


def install_as_v1(root: Path, spec: ModuleSpec) -> Path:
    """Lay out a module exactly as the first generator left it on a server.

    Every file, not only the ones a refresh rewrites: the table definition and
    the API schema come from the first generator too, so a refresh that goes
    through proves the current generator renders them byte for byte the same.
    """
    target = root / spec.key
    source = FIXTURES / spec.key
    for fixture in sorted(source.rglob("*.v1")):
        path = fixture.relative_to(source).as_posix().removesuffix(".v1")
        destination = target / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(v1_bytes(spec.key, path))
    payload = json.loads((target / "spec.json").read_text(encoding="utf-8"))
    assert payload["generator"] == V1_STAMP, "the fixture is not the first generator's output"
    return target


def snapshot(directory: Path) -> dict[str, bytes]:
    return {
        p.relative_to(directory).as_posix(): p.read_bytes()
        for p in sorted(directory.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def rendered(spec: ModuleSpec) -> dict[str, str]:
    return {f.path: f.content for f in generator.render(spec)}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "runtime-modules"
    path.mkdir()
    return path


class TestTheFixtureIsReallyTheOldCode:
    """Otherwise every test below refreshes something that was never broken."""

    def test_the_old_router_does_not_check_project_access(self) -> None:
        old = v1_bytes("refresh_hire", "router.py").decode("utf-8")
        assert "verify_project_access" not in old
        assert "project_id: uuid.UUID | None = Query(None" in old

    def test_the_current_generator_renders_something_else(self) -> None:
        current = rendered(hire_spec())
        for name in CODE_FILES:
            assert v1_bytes("refresh_hire", name).decode("utf-8") != current[name], name

    def test_the_stamp_has_moved_on(self) -> None:
        assert generator.GENERATOR_STAMP != V1_STAMP


class TestRefreshingAnOldInstall:
    def test_the_code_is_rendered_again_from_the_spec(self, root: Path) -> None:
        target = install_as_v1(root, hire_spec())

        outcome = refresh.refresh_installed(root)

        assert outcome == {"refresh_hire": refresh.REFRESHED}
        current = rendered(hire_spec())
        for name in CODE_FILES:
            assert (target / name).read_text(encoding="utf-8") == current[name], f"{name} was not refreshed"

    def test_the_table_and_the_api_schema_are_untouched(self, root: Path) -> None:
        target = install_as_v1(root, hire_spec())
        before = snapshot(target)

        refresh.refresh_installed(root)

        after = snapshot(target)
        changed = {path for path in before if before[path] != after.get(path)}
        assert set(after) == set(before), "the refresh added or removed files"
        assert changed == {*CODE_FILES, "spec.json"}
        for name in refresh.CONTRACT_FILES:
            assert after[name] == before[name]

    def test_the_spec_is_restamped_and_keeps_its_date(self, root: Path) -> None:
        target = install_as_v1(root, hire_spec())

        refresh.refresh_installed(root)

        payload = json.loads((target / "spec.json").read_text(encoding="utf-8"))
        assert payload["generator"] == generator.GENERATOR_STAMP
        # When the module was built, which the builder lists, not when its code
        # was last refreshed.
        assert payload["generated_at"] == V1_GENERATED_AT
        payload.pop("generator")
        payload.pop("generated_at")
        assert ModuleSpec.model_validate(payload) == hire_spec()

    def test_an_install_from_before_manifests_declared_inference(self, root: Path) -> None:
        """The first generator's manifest changed while its stamp did not.

        Modules installed before that change carry a manifest without the
        inference declaration. It has nothing to do with the table or the
        routes, so it must not keep such a module on the leaky router.
        """
        target = install_as_v1(root, hire_spec())
        manifest = (target / "manifest.py").read_text(encoding="utf-8")
        start = manifest.index("    inference=InferenceDeclaration(")
        end = manifest.index("    ),\n", start) + len("    ),\n")
        (target / "manifest.py").write_text(manifest[:start] + manifest[end:], encoding="utf-8", newline="\n")
        older_manifest = (target / "manifest.py").read_bytes()

        assert refresh.refresh_installed(root) == {"refresh_hire": refresh.REFRESHED}
        assert (target / "manifest.py").read_bytes() == older_manifest

    def test_a_module_without_projects_is_refreshed_too(self, root: Path) -> None:
        target = install_as_v1(root, notice_spec())

        assert refresh.refresh_installed(root) == {"refresh_notice": refresh.REFRESHED}
        assert (target / "router.py").read_text(encoding="utf-8") == rendered(notice_spec())["router.py"]

    def test_the_old_code_is_kept(self, root: Path) -> None:
        """A hand edit to an old router is recoverable, not overwritten and gone."""
        install_as_v1(root, hire_spec())

        refresh.refresh_installed(root)

        backups = list((root / refresh.WORK_DIR / "backups").iterdir())
        assert len(backups) == 1
        assert backups[0].name.startswith("refresh_hire-")
        assert (backups[0] / "router.py").read_bytes() == v1_bytes("refresh_hire", "router.py")

    def test_running_it_again_changes_nothing(self, root: Path) -> None:
        target = install_as_v1(root, hire_spec())
        refresh.refresh_installed(root)
        once = snapshot(target)
        backups = sorted(p.name for p in (root / refresh.WORK_DIR / "backups").iterdir())

        assert refresh.refresh_installed(root) == {"refresh_hire": refresh.CURRENT}
        assert snapshot(target) == once
        assert sorted(p.name for p in (root / refresh.WORK_DIR / "backups").iterdir()) == backups

    def test_its_working_directories_are_not_modules(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Neither the builder's list nor the loader may see a backup as a module."""
        from app.core import module_runtime_root as rr
        from app.modules.module_builder import service

        install_as_v1(root, hire_spec())
        refresh.refresh_installed(root)
        monkeypatch.setenv(rr.ENV_VAR, str(root))

        assert [m.key for m in service.installed()] == ["refresh_hire"]
        assert refresh.WORK_DIR.startswith("_"), "the loader skips only underscore directories"

    def test_an_empty_or_missing_root_is_fine(self, root: Path, tmp_path: Path) -> None:
        assert refresh.refresh_installed(root) == {}
        assert refresh.refresh_installed(tmp_path / "never-created") == {}


class TestWhatIsLeftAlone:
    def test_a_spec_that_no_longer_validates(self, root: Path, caplog: pytest.LogCaptureFixture) -> None:
        target = install_as_v1(root, hire_spec())
        payload = json.loads((target / "spec.json").read_text(encoding="utf-8"))
        payload["rules"] = []  # a module with no rules is refused by the spec
        (target / "spec.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
        before = snapshot(target)

        with caplog.at_level(logging.ERROR, logger=refresh.logger.name):
            outcome = refresh.refresh_installed(root)

        assert outcome == {"refresh_hire": refresh.INVALID}
        assert snapshot(target) == before
        assert any("refresh_hire" in r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)

    def test_an_unreadable_spec(self, root: Path) -> None:
        target = install_as_v1(root, hire_spec())
        (target / "spec.json").write_text("{not json", encoding="utf-8")
        before = snapshot(target)

        assert refresh.refresh_installed(root) == {"refresh_hire": refresh.INVALID}
        assert snapshot(target) == before

    def test_a_spec_naming_another_directory(self, root: Path) -> None:
        target = install_as_v1(root, hire_spec())
        moved = root / "refresh_hire_copy"
        target.rename(moved)
        before = snapshot(moved)

        assert refresh.refresh_installed(root) == {"refresh_hire_copy": refresh.INVALID}
        assert snapshot(moved) == before

    @pytest.mark.parametrize("name", ["models.py", "schema.py", "schemas.py"])
    def test_a_module_whose_table_or_api_would_change(
        self, root: Path, name: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Hand edited, or built by something else. Either way not ours to rewrite."""
        target = install_as_v1(root, hire_spec())
        with (target / name).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("# changed by hand\n")
        before = snapshot(target)

        with caplog.at_level(logging.ERROR, logger=refresh.logger.name):
            outcome = refresh.refresh_installed(root)

        assert outcome == {"refresh_hire": refresh.REFUSED}
        assert snapshot(target) == before
        messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
        assert any("refresh_hire" in m and name in m for m in messages), messages

    def test_a_module_from_a_newer_generator(self, root: Path) -> None:
        target = install_as_v1(root, hire_spec())
        payload = json.loads((target / "spec.json").read_text(encoding="utf-8"))
        payload["generator"] = "openconstructionerp.module_builder/99"
        (target / "spec.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
        before = snapshot(target)

        assert refresh.refresh_installed(root) == {"refresh_hire": refresh.CURRENT}
        assert snapshot(target) == before

    def test_one_bad_module_does_not_stop_the_others(self, root: Path) -> None:
        bad = install_as_v1(root, notice_spec())
        (bad / "spec.json").write_text("[]", encoding="utf-8")
        install_as_v1(root, hire_spec())

        assert refresh.refresh_installed(root) == {
            "refresh_hire": refresh.REFRESHED,
            "refresh_notice": refresh.INVALID,
        }


class TestAFailedSwap:
    def test_a_failure_while_staging_leaves_the_module_as_it_was(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = install_as_v1(root, hire_spec())
        before = snapshot(target)

        def explode(*args: object, **kwargs: object) -> None:
            raise OSError("disk gave out")

        monkeypatch.setattr(refresh, "_write_files", explode)

        assert refresh.refresh_installed(root) == {"refresh_hire": refresh.FAILED}
        assert snapshot(target) == before
        assert not list((root / refresh.WORK_DIR / "staging").iterdir())

    def test_a_failure_while_swapping_puts_the_old_module_back(
        self, root: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The second rename is the one that can strand a module with no directory."""
        target = install_as_v1(root, hire_spec())
        before = snapshot(target)
        real = refresh.os.replace
        calls: list[tuple[str, str]] = []

        def second_fails(src: object, dst: object) -> None:
            calls.append((str(src), str(dst)))
            if len(calls) == 2:
                raise OSError("locked")
            real(src, dst)

        monkeypatch.setattr(refresh.os, "replace", second_fails)

        with caplog.at_level(logging.ERROR, logger=refresh.logger.name):
            outcome = refresh.refresh_installed(root)

        assert outcome == {"refresh_hire": refresh.FAILED}
        assert snapshot(target) == before
        assert any("refresh_hire" in r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)

    def test_leftovers_from_an_interrupted_run_are_cleared(self, root: Path) -> None:
        install_as_v1(root, hire_spec())
        stale = root / refresh.WORK_DIR / "staging" / "refresh_hire"
        stale.mkdir(parents=True)
        (stale / "router.py").write_text("half written", encoding="utf-8")

        assert refresh.refresh_installed(root) == {"refresh_hire": refresh.REFRESHED}
        assert not stale.exists()


class TestOneRefreshAtATime:
    """Two processes starting together must not refresh one root together.

    One would clear the other's staging, and one that went ahead to load its
    modules would find a module directory that, mid-swap, does not exist.
    """

    def test_a_refresh_held_elsewhere_is_waited_for_and_never_raced(
        self, root: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        target = install_as_v1(root, hire_spec())
        before = snapshot(target)
        lock = root / refresh.WORK_DIR / "lock"
        lock.mkdir(parents=True)
        monkeypatch.setattr(refresh, "_LOCK_WAIT_SECONDS", 0.3)

        with caplog.at_level(logging.ERROR, logger=refresh.logger.name):
            outcome = refresh.refresh_installed(root)

        assert outcome == {}
        assert snapshot(target) == before
        assert lock.is_dir(), "the other process's lock was taken away from it"
        assert any(r.levelno >= logging.ERROR for r in caplog.records)

    def test_it_goes_ahead_once_the_other_process_is_done(self, root: Path) -> None:
        import threading

        install_as_v1(root, hire_spec())
        lock = root / refresh.WORK_DIR / "lock"
        lock.mkdir(parents=True)
        release = threading.Timer(0.3, lock.rmdir)
        release.start()
        try:
            assert refresh.refresh_installed(root) == {"refresh_hire": refresh.REFRESHED}
        finally:
            release.cancel()

    def test_a_lock_left_by_a_process_that_died_is_broken(self, root: Path) -> None:
        import os
        import time

        install_as_v1(root, hire_spec())
        lock = root / refresh.WORK_DIR / "lock"
        lock.mkdir(parents=True)
        long_ago = time.time() - 2 * refresh._LOCK_STALE_SECONDS
        os.utime(lock, (long_ago, long_ago))

        assert refresh.refresh_installed(root) == {"refresh_hire": refresh.REFRESHED}
        assert not lock.exists()

    def test_the_lock_is_let_go(self, root: Path) -> None:
        install_as_v1(root, hire_spec())
        refresh.refresh_installed(root)
        assert not (root / refresh.WORK_DIR / "lock").exists()

    def test_a_root_with_nothing_installed_is_not_written_to(self, root: Path) -> None:
        (root / "not_a_built_module").mkdir()
        assert refresh.refresh_installed(root) == {}
        assert not (root / refresh.WORK_DIR).exists()


def test_startup_refreshes_after_attaching_the_root_and_before_loading_modules() -> None:
    """Read off the source, because running the real startup needs the whole platform.

    Before attaching, the runtime root is not where installed modules are found;
    after loading, the old router has already been imported and mounted. The
    refresh is only worth anything between the two.
    """
    source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    calls = ["attach_runtime_root()\n", "refresh_installed()\n", "await module_loader.load_all(app)\n"]
    for call in calls:
        assert source.count(call) == 1, f"expected exactly one {call.strip()!r} in app/main.py"
    attach, refreshed, loaded = (source.index(call) for call in calls)
    assert attach < refreshed < loaded
