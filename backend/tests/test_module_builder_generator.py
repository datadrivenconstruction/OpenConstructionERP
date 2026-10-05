# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tests for the module builder's spec and generator.

The generator's claim is strong and so the tests are correspondingly literal:
a spec that validates renders a module that compiles, that ruff accepts, and
whose own generated tests pass. Anything weaker - asserting that a rendered
file contains a substring - would pass on output that cannot be imported, and
the failure would then arrive on a user's server at startup.
"""

from __future__ import annotations

import compileall
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.module_builder import generator
from app.modules.module_builder.spec import EntitySpec, FieldSpec, ModuleSpec, RuleSpec

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Lint a generated tree with the same ruff the repo pins, found wherever it
# happens to live. The interpreter running these tests has it: ruff==0.16.6 is
# a dev dependency, and pytest arrives from the same extra, so anything able to
# collect this file can import it. Developers who follow the repo convention
# reach for uvx instead, hence the second attempt.
#
# The config is named rather than discovered. The tree under test sits in a
# temp directory, so discovery would walk out of it into whatever happens to be
# above. --isolated used to stop that walk, but it judged generated code against
# ruff's built-in defaults, and those move between releases: 0.16 enabled I, B
# and RUF by default, and the same unchanged generator output went from clean to
# fifteen findings. The defaults are also the wrong ruleset for this project,
# in three ways that all read as false positives:
#
#   I001    without known-first-party = ["app"] isort files the generated
#           `from app.modules.<key>...` imports as third-party and wants them
#           merged into the sqlalchemy block, so a correct import layout is
#           reported as unsorted.
#   B008    the generated router declares `limit: int = Query(100, ...)`, which
#           is how FastAPI parameters are written; pyproject ignores B008 for
#           exactly that reason.
#   RUF100  schemas.py carries `# noqa: F401` on its date and Decimal imports
#           because whether they are used depends on the spec's field types.
#           That suppression is load-bearing for a spec with no date and no
#           money field and merely redundant for one that has both, so it
#           cannot be deleted; the project simply never selects RUF.
#
# Naming backend/pyproject.toml holds generated modules to the standard the
# platform holds its own code to, which is the only standard we own and the
# only one that does not shift under us on a ruff upgrade.
_RUFF_CONFIG = BACKEND_ROOT / "pyproject.toml"
_RUFF_ARGS = ("check", "--config", str(_RUFF_CONFIG))


def ruff_check(target: Path) -> subprocess.CompletedProcess[str]:
    """Run ruff over a generated module and hand back the finished process.

    Never skips. A lint check that quietly opts out is exactly the one that
    lets the generator ship a module carrying an import nothing references.
    """
    # Named config, so its absence is a broken harness rather than a lint
    # result. Ruff would exit 2 for a config it cannot open, which reads as a
    # confusing failure of whichever generated file happened to be under test.
    assert _RUFF_CONFIG.is_file(), f"the ruff config the lint gate names is missing: {_RUFF_CONFIG}"
    installed = subprocess.run(
        [sys.executable, "-m", "ruff", *_RUFF_ARGS, str(target)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if "No module named ruff" not in installed.stderr:
        return installed
    try:
        return subprocess.run(
            ["uvx", "ruff@0.16.6", *_RUFF_ARGS, str(target)],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except OSError as exc:
        pytest.fail(f"no ruff to run: {sys.executable} -m ruff is absent and uvx is not on PATH ({exc})")


def a_spec(**overrides: object) -> ModuleSpec:
    """A realistic spec: every field type, every rule kind, project scoped."""
    payload: dict[str, object] = {
        "key": "scaffold_hire",
        "display_name": "Scaffold Hire",
        "description": "Track hired scaffolding, its rate and its off-hire date.",
        "entity": EntitySpec(
            name="hire",
            display_name="Hire",
            plural_name="Hires",
            fields=[
                FieldSpec(name="reference", label="Reference", type="text", required=True),
                FieldSpec(name="notes", label="Notes", type="long_text"),
                FieldSpec(name="bay_count", label="Bays", type="integer", required=True),
                FieldSpec(name="area_m2", label="Area", type="number", unit="m2"),
                FieldSpec(name="weekly_rate", label="Weekly rate", type="money", required=True),
                FieldSpec(name="on_hire_date", label="On hire", type="date", required=True),
                FieldSpec(name="off_hire_date", label="Off hire", type="date"),
                FieldSpec(name="inspected_at", label="Last inspection", type="datetime"),
                FieldSpec(name="is_tagged", label="Tagged", type="boolean"),
                FieldSpec(
                    name="status",
                    label="Status",
                    type="select",
                    options=["erected", "struck", "on hold"],
                    required=True,
                ),
            ],
        ),
        "rules": [
            RuleSpec(
                code="REFERENCE_REQUIRED",
                message="A hire needs a reference to be found by.",
                kind="required",
                field="reference",
            ),
            RuleSpec(
                code="RATE_POSITIVE",
                message="A weekly rate must be above zero.",
                kind="positive",
                field="weekly_rate",
            ),
            RuleSpec(
                code="BAYS_IN_RANGE",
                message="A hire covers between 1 and 500 bays.",
                kind="range",
                field="bay_count",
                min_value=1,
                max_value=500,
            ),
            RuleSpec(
                code="STATUS_KNOWN",
                message="Status must be one the register recognises.",
                kind="one_of",
                field="status",
            ),
            RuleSpec(
                code="INSPECTION_NOT_FUTURE",
                message="An inspection cannot be recorded before it happens.",
                kind="not_future",
                field="inspected_at",
            ),
            RuleSpec(
                code="OFF_HIRE_AFTER_ON_HIRE",
                message="Off hire cannot precede on hire.",
                kind="order",
                field="on_hire_date",
                other_field="off_hire_date",
            ),
        ],
    }
    payload.update(overrides)
    return ModuleSpec(**payload)  # type: ignore[arg-type]


class TestSpecRefusesWhatCannotWork:
    def test_reserved_field_name(self) -> None:
        with pytest.raises(ValidationError, match="reserved"):
            FieldSpec(name="id", label="Id")

    def test_metadata_is_reserved_too(self) -> None:
        # Parses as an identifier and collides with SQLAlchemy's own attribute.
        with pytest.raises(ValidationError, match="reserved"):
            FieldSpec(name="metadata", label="Meta")

    def test_camel_case_field_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="snake_case"):
            FieldSpec(name="bayCount", label="Bays")

    def test_python_keyword_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="keyword"):
            FieldSpec(name="class", label="Class")

    def test_select_needs_more_than_one_option(self) -> None:
        with pytest.raises(ValidationError, match="not a choice"):
            FieldSpec(name="status", label="Status", type="select", options=["only"])

    def test_non_select_may_not_carry_options(self) -> None:
        with pytest.raises(ValidationError, match="select options"):
            FieldSpec(name="title", label="Title", type="text", options=["a", "b"])

    def test_duplicate_field_names(self) -> None:
        with pytest.raises(ValidationError, match="duplicate field"):
            EntitySpec(
                name="hire",
                display_name="Hire",
                fields=[
                    FieldSpec(name="reference", label="A"),
                    FieldSpec(name="reference", label="B"),
                ],
            )

    def test_a_module_must_carry_rules(self) -> None:
        with pytest.raises(ValidationError):
            a_spec(rules=[])

    def test_rule_naming_a_missing_field(self) -> None:
        with pytest.raises(ValidationError, match="does not exist"):
            a_spec(rules=[RuleSpec(code="NO_SUCH", message="Nope, missing.", kind="required", field="ghost")])

    def test_numeric_rule_on_a_text_field(self) -> None:
        with pytest.raises(ValidationError, match="numeric"):
            a_spec(rules=[RuleSpec(code="BAD", message="Text is not a number.", kind="positive", field="reference")])

    def test_order_rule_between_non_dates(self) -> None:
        with pytest.raises(ValidationError, match="not dates"):
            a_spec(
                rules=[
                    RuleSpec(
                        code="BAD_ORDER",
                        message="These are not dates.",
                        kind="order",
                        field="bay_count",
                        other_field="area_m2",
                    )
                ]
            )

    def test_key_colliding_with_a_shipped_module(self) -> None:
        with pytest.raises(ValidationError, match="ships with the platform"):
            a_spec(key="projects")

    def test_version_must_be_semver(self) -> None:
        with pytest.raises(ValidationError, match="MAJOR.MINOR.PATCH"):
            a_spec(version="1.0")

    def test_a_sound_spec_validates(self) -> None:
        spec = a_spec()
        assert spec.module_name == "oe_scaffold_hire"
        assert spec.table_name == "oe_scaffold_hire_hire"
        assert spec.class_name == "Hire"


class TestRendering:
    def test_every_expected_file_is_rendered(self) -> None:
        paths = {f.path for f in generator.render(a_spec())}
        assert {
            "manifest.py",
            "models.py",
            "schemas.py",
            "repository.py",
            "service.py",
            "router.py",
            "validators.py",
            "permissions.py",
            "schema.py",
            "spec.json",
            "locales/en.json",
            "README.md",
        } <= paths

    def test_rendering_is_deterministic(self) -> None:
        # spec.json carries a timestamp, so it is the one file allowed to move.
        first = {f.path: f.content for f in generator.render(a_spec())}
        second = {f.path: f.content for f in generator.render(a_spec())}
        for path in first:
            if path == "spec.json":
                continue
            assert first[path] == second[path], f"{path} is not deterministic"

    def test_money_is_never_a_float(self) -> None:
        """The platform's own decimal column, not a bare Numeric.

        Plain Numeric hands back a float on backends that have no decimal type,
        so a rate written as 1450.75 can come back as 1450.7499999. MoneyType
        binds and returns Decimal on every backend and still compiles to
        NUMERIC(18, 2) on PostgreSQL - which the DDL test checks separately.
        """
        models = next(f for f in generator.render(a_spec()) if f.path == "models.py").content
        assert "MoneyType(18, 2)" in models
        assert "Float" not in models

    def test_permissions_are_registered_not_just_named(self) -> None:
        """Defining a registration function nobody calls registers nothing.

        A permission the registry has never heard of is denied to everyone
        except an administrator, so a module whose hook is missing works for
        whoever tested it as an admin and for no one else.
        """
        rendered = {f.path: f.content for f in generator.render(a_spec())}
        assert "register_module_permissions" in rendered["permissions.py"]
        # The loader awaits on_startup after importing the package. That is the
        # only place the call can go: import time is too early for anything
        # that touches the database, and nothing else imports permissions.py.
        assert "async def on_startup()" in rendered["__init__.py"]
        assert "register_scaffold_hire_permissions()" in rendered["__init__.py"]

    def test_the_startup_hook_also_creates_the_table(self) -> None:
        """Nothing else will. The module has no migration and never can have one."""
        init = next(f for f in generator.render(a_spec()) if f.path == "__init__.py").content
        assert "await ensure_table(engine)" in init

    def test_deleting_is_not_the_same_permission_as_writing(self) -> None:
        rendered = {f.path: f.content for f in generator.render(a_spec())}
        assert '"scaffold_hire.delete": Role.MANAGER' in rendered["permissions.py"]
        assert 'RequirePermission("scaffold_hire.delete")' in rendered["router.py"]

    def test_locales_are_english_only(self) -> None:
        paths = {f.path for f in generator.render(a_spec())}
        assert [p for p in paths if p.startswith("locales/")] == ["locales/en.json"]


class TestWriting:
    def test_write_refuses_to_overwrite(self, tmp_path: Path) -> None:
        spec = a_spec()
        generator.write(spec, tmp_path)
        with pytest.raises(FileExistsError):
            generator.write(spec, tmp_path)

    def test_a_failed_write_leaves_nothing_behind(self, tmp_path: Path, monkeypatch) -> None:
        spec = a_spec()
        real = generator.render

        def explode(s):
            files = real(s)
            files[3] = generator.GeneratedFile("models.py", "fine")
            raise RuntimeError("disk gave out")

        monkeypatch.setattr(generator, "render", explode)
        with pytest.raises(RuntimeError):
            generator.write(spec, tmp_path)
        assert not (tmp_path / spec.key).exists()

    def test_files_are_written_with_unix_newlines(self, tmp_path: Path) -> None:
        # Same spec, same bytes, whichever operating system generated it.
        generator.write(a_spec(), tmp_path)
        raw = (tmp_path / "scaffold_hire" / "models.py").read_bytes()
        assert b"\r\n" not in raw


class TestTheGeneratedModuleIsReal:
    """Compiles, lints, and passes the tests it came with."""

    @pytest.fixture
    def written(self, tmp_path: Path) -> Path:
        generator.write(a_spec(), tmp_path)
        return tmp_path / "scaffold_hire"

    def test_it_compiles(self, written: Path) -> None:
        assert compileall.compile_dir(str(written), quiet=1, force=True), "the generated module does not compile"

    def test_ruff_accepts_it(self, written: Path) -> None:
        result = ruff_check(written)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_its_own_tests_pass(self, written: Path, tmp_path: Path) -> None:
        """The generated validator, exercised by the generated tests.

        Run in a subprocess against the real module tree, with the temp root on
        the import path, so the generated ``app.modules.<key>`` imports resolve
        exactly as they will on a user's instance.
        """
        from app.core import module_runtime_root as rr

        before = list(rr._package_path())
        rr.attach_runtime_root(tmp_path)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(written / "tests"), "-q", "--no-header", "-p", "no:cacheprovider"],
                capture_output=True,
                text=True,
                timeout=600,
                cwd=str(BACKEND_ROOT),
                env={**_clean_env(), rr.ENV_VAR: str(tmp_path)},
            )
        finally:
            rr._package_path()[:] = before
        assert result.returncode == 0, result.stdout + result.stderr
        assert "passed" in result.stdout


def a_minimal_spec() -> ModuleSpec:
    """The other end of the range: one text field, no project, no dates.

    The full spec exercises every branch and therefore uses every import the
    generator could emit. This one uses almost none, which is what catches an
    import block written as a fixed list.
    """
    return ModuleSpec(
        key="site_notice",
        display_name="Site Notice",
        entity=EntitySpec(
            name="notice",
            display_name="Notice",
            project_scoped=False,
            fields=[FieldSpec(name="title", label="Title", type="text", required=True)],
        ),
        rules=[RuleSpec(code="TITLE_REQUIRED", message="A notice needs a title.", kind="required", field="title")],
    )


class TestASpecThatUsesAlmostNothing:
    @pytest.fixture
    def written(self, tmp_path: Path) -> Path:
        generator.write(a_minimal_spec(), tmp_path)
        return tmp_path / "site_notice"

    def test_it_compiles(self, written: Path) -> None:
        assert compileall.compile_dir(str(written), quiet=1, force=True)

    def test_ruff_accepts_it(self, written: Path) -> None:
        """An unused import is a hard error here, which is the point.

        The generator emits imports per field type. A spec with no money, no
        dates and no project would otherwise carry Numeric, Date and
        ForeignKey that nothing references.
        """
        result = ruff_check(written)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_it_carries_no_project_column(self, written: Path) -> None:
        models = (written / "models.py").read_text(encoding="utf-8")
        assert "project_id" not in models
        assert "ForeignKey" not in models


class TestTheLintGateItselfCanStillFail:
    """Every ``test_ruff_accepts_it`` above asserts an exit code of zero.

    That assert is worth nothing on its own: a mistyped config path, a ruff
    that resolves no files, or a ruleset that quietly stopped selecting F would
    each leave those tests green while checking nothing. It is equally worth
    nothing if the gate drifts back to ruff's defaults, because then it fails
    on generated code that is correct. So pin both directions.
    """

    def test_it_reports_a_plain_unused_import(self, tmp_path: Path) -> None:
        """The gate is live: real breakage still fails it.

        F401, deliberately, and not RUF100 or B008. The project config selects
        F and exempts the other two, so only a rule the config actually turns
        on proves the ruleset we apply is the one we think we apply.
        """
        offender = tmp_path / "unused_import.py"
        offender.write_text("import json\n", encoding="utf-8")

        result = ruff_check(offender)

        assert result.returncode != 0, "ruff passed a plain unused import, so the lint gate is reading nothing"
        assert "F401" in result.stdout, result.stdout + result.stderr

    def test_it_reads_the_projects_own_ruleset_and_not_ruffs_defaults(self, tmp_path: Path) -> None:
        """The gate is not over-tightened: it judges by pyproject, not defaults.

        Every generated module imports from ``app``, and the layout below is
        the one the generator emits: first-party separated from third-party.
        That is correct only because pyproject sets
        ``known-first-party = ["app"]``. Ruff's built-in defaults do not know
        the name, file ``app`` as third-party, and demand it be merged into the
        sqlalchemy block, so this file is I001 the moment the gate falls back
        to ruff's own configuration.
        """
        sample = tmp_path / "first_party_layout.py"
        sample.write_text(
            "from sqlalchemy import Table\n"
            "\n"
            "from app.modules.site_notice.models import Notice\n"
            "\n"
            '__all__ = ["Notice", "Table"]\n',
            encoding="utf-8",
        )

        result = ruff_check(sample)

        assert result.returncode == 0, result.stdout + result.stderr


class TestEveryGeneratedFileImports:
    """Import each module, not merely compile it.

    Compiling proves the syntax and ruff proves the style. Neither resolves a
    name: a model importing a type from the wrong module, or a router asking
    for a dependency the platform does not have, compiles and lints clean and
    then fails at load time on the user's server. Both of those were real, and
    both were invisible until something imported the files.
    """

    @pytest.fixture
    def imported(self, tmp_path: Path):
        import importlib

        from app.core import module_runtime_root as rr
        from app.database import Base

        spec = a_spec()
        generator.write(spec, tmp_path)
        before = list(rr._package_path())
        rr.attach_runtime_root(tmp_path)
        importlib.invalidate_caches()
        try:
            yield spec, importlib.import_module
        finally:
            rr._package_path()[:] = before
            for name in [n for n in list(sys.modules) if n.startswith(f"app.modules.{spec.key}")]:
                del sys.modules[name]
            existing = Base.metadata.tables.get(spec.table_name)
            if existing is not None:
                Base.metadata.remove(existing)
            Base.registry._class_registry.pop(spec.class_name, None)
            importlib.invalidate_caches()

    @pytest.mark.parametrize(
        "name",
        ["manifest", "models", "schema", "schemas", "validators", "permissions", "repository", "service", "router"],
    )
    def test_it_imports(self, imported, name: str) -> None:
        spec, import_module = imported
        import_module(f"app.modules.{spec.key}.{name}")

    def test_the_manifest_is_one_the_loader_accepts(self, imported) -> None:
        from app.core.module_loader import ModuleManifest

        spec, import_module = imported
        manifest = import_module(f"app.modules.{spec.key}.manifest").manifest
        assert isinstance(manifest, ModuleManifest)
        assert manifest.name == spec.module_name
        assert manifest.version == spec.version

    def test_the_router_serves_what_the_module_needs(self, imported) -> None:
        spec, import_module = imported
        router = import_module(f"app.modules.{spec.key}.router").router
        paths = {(r.path, m) for r in router.routes for m in getattr(r, "methods", ())}

        assert ("/ui-spec", "GET") in paths
        assert ("", "GET") in paths
        assert ("", "POST") in paths
        assert ("/{record_id}", "GET") in paths
        assert ("/{record_id}", "PATCH") in paths
        assert ("/{record_id}", "DELETE") in paths

    def test_every_endpoint_is_behind_a_permission(self, imported) -> None:
        """An unguarded endpoint on a generated module is the whole risk of this feature.

        Checked on the dependency the platform actually enforces with, so
        renaming that dependency breaks this test rather than silently
        unguarding every module built from here on.
        """
        from app.dependencies import RequirePermission

        spec, import_module = imported
        router = import_module(f"app.modules.{spec.key}.router").router

        for route in router.routes:
            path = getattr(route, "path", "")
            if path == "/ui-spec":
                continue  # the screen description, readable by anyone who reached the app
            assert _guards(route, RequirePermission), f"{path} has no permission guard"

    def test_the_permissions_the_router_asks_for_are_the_ones_registered(self, imported) -> None:
        """Otherwise every request is denied to everyone but an administrator.

        A guard naming a permission the registry does not know is not a loud
        failure. It is a quiet 403 for every role except admin, and a test run
        as an admin cannot see it.
        """
        from app.dependencies import RequirePermission

        spec, import_module = imported
        declared = set(import_module(f"app.modules.{spec.key}.permissions").SCAFFOLD_HIRE_PERMISSIONS)
        router = import_module(f"app.modules.{spec.key}.router").router

        asked = {guard.permission for route in router.routes for guard in _guards(route, RequirePermission)}
        assert asked, "no permission guards found, so this test proves nothing"
        assert asked <= declared, f"the router asks for {sorted(asked - declared)}, which nothing registers"

    def test_the_startup_hook_runs(self, imported) -> None:
        """The hook the loader awaits, exercised rather than read.

        It registers the permissions and creates the table, so it is the one
        piece of a generated module that cannot be checked by looking at it.
        """
        import asyncio

        from app.core.permissions import Role, permission_registry

        spec, import_module = imported
        package = import_module(f"app.modules.{spec.key}")

        created: list[object] = []

        class _FakeEngine:
            def begin(self):
                created.append(self)
                return _FakeTransaction()

        class _FakeTransaction:
            async def __aenter__(self):
                return _FakeConnection()

            async def __aexit__(self, *exc):
                return False

        class _FakeConnection:
            async def run_sync(self, fn, *args, **kwargs):
                created.append(fn)

        import app.database as database

        real_engine = database.engine
        database.engine = _FakeEngine()  # type: ignore[assignment]
        try:
            asyncio.run(package.on_startup())
        finally:
            database.engine = real_engine

        assert created, "the startup hook never reached the database"
        # A viewer can read and cannot delete: registration happened, and it
        # registered the roles the module meant rather than merely a name.
        assert permission_registry.role_has_permission(Role.VIEWER, "scaffold_hire.read")
        assert not permission_registry.role_has_permission(Role.EDITOR, "scaffold_hire.delete")
        assert permission_registry.role_has_permission(Role.MANAGER, "scaffold_hire.delete")


def _guards(route: object, kind: type) -> list:
    """The RequirePermission instances a route is actually wired with.

    Read off the resolved dependency tree rather than off the source, so a
    guard that was written but never reached - a default argument FastAPI does
    not treat as a dependency, say - does not count as one.
    """
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return []
    return [d.call for d in dependant.dependencies if isinstance(d.call, kind)]


@contextmanager
def _imported_module(spec: ModuleSpec, root: Path):
    """Write a module under ``root``, make it importable, and clean up after."""
    import importlib

    from app.core import module_runtime_root as rr
    from app.database import Base

    generator.write(spec, root)
    before = list(rr._package_path())
    rr.attach_runtime_root(root)
    importlib.invalidate_caches()
    try:
        yield importlib.import_module
    finally:
        rr._package_path()[:] = before
        for name in [n for n in list(sys.modules) if n.startswith(f"app.modules.{spec.key}")]:
            del sys.modules[name]
        existing = Base.metadata.tables.get(spec.table_name)
        if existing is not None:
            Base.metadata.remove(existing)
        Base.registry._class_registry.pop(spec.class_name, None)
        importlib.invalidate_caches()


_UNREACHABLE = uuid.UUID(int=1)
_REACHABLE = uuid.UUID(int=2)


class TestProjectScopedRoutesCheckProjectAccess:
    """A project-scoped module answers only inside projects the caller may reach.

    The module permission says what a person may do with this kind of record,
    not in which projects. Every route therefore has to ask the platform's
    project access rule as well, and these tests drive each route with that
    rule refusing and check the refusal is what comes back.

    The endpoints are called directly with the access rule and the service
    replaced, so nothing here needs a database. The service hands back a record
    for any id, so a 404 can only have come from the access check; the same
    behaviour against real users and projects is in
    ``tests/pg/test_module_builder_project_access.py``.
    """

    @pytest.fixture
    def guarded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        spec = a_spec()
        with _imported_module(spec, tmp_path) as import_module:
            router = import_module(f"app.modules.{spec.key}.router")
            calls: dict[str, list] = {"checked": [], "scoped": [], "service": []}

            async def verify_project_access(project_id, user_id, session) -> None:
                calls["checked"].append(project_id)
                if project_id != _REACHABLE:
                    raise HTTPException(status_code=404, detail="Project not found")

            async def accessible_project_ids(session, user_id, **kwargs):
                calls["scoped"].append(user_id)
                return {_REACHABLE}

            class FakeService:
                def __init__(self, db: object) -> None:
                    pass

                async def get(self, record_id):
                    return SimpleNamespace(id=record_id, project_id=_UNREACHABLE)

                async def list_page(self, **kwargs):
                    calls["service"].append(("list_page", kwargs))
                    return [], 0

                async def create(self, payload):
                    calls["service"].append(("create", payload))
                    raise AssertionError("created a record in a project the caller cannot reach")

                async def update(self, record, payload):
                    calls["service"].append(("update", record))
                    raise AssertionError("updated a record in a project the caller cannot reach")

                async def delete(self, record):
                    calls["service"].append(("delete", record))
                    raise AssertionError("deleted a record in a project the caller cannot reach")

            # raising=False, so a router that never imported the access rule
            # fails below on what it does rather than here on a missing name.
            monkeypatch.setattr(router, "verify_project_access", verify_project_access, raising=False)
            monkeypatch.setattr(router, "accessible_project_ids", accessible_project_ids, raising=False)
            monkeypatch.setattr(router, f"{spec.class_name}Service", FakeService)
            yield router, calls

    @staticmethod
    def _arguments(endpoint) -> dict[str, object]:
        """Arguments for a direct call, naming the unreachable project wherever one is asked for."""
        import inspect

        arguments: dict[str, object] = {}
        for name, parameter in inspect.signature(endpoint).parameters.items():
            if name == "record_id":
                arguments[name] = uuid.uuid4()
            elif name == "project_id":
                arguments[name] = _UNREACHABLE
            elif name == "payload":
                model = parameter.annotation
                fields = {"project_id": _UNREACHABLE} if "project_id" in model.model_fields else {}
                arguments[name] = model.model_construct(**fields)
            elif name == "user_id":
                arguments[name] = "someone-else"
            elif name == "limit":
                arguments[name] = 100
            elif name == "offset":
                arguments[name] = 0
            else:
                arguments[name] = None
        return arguments

    def test_every_route_refuses_an_unreachable_project(self, guarded) -> None:
        import asyncio

        router, calls = guarded
        routes = [r for r in router.router.routes if getattr(r, "path", "") != "/ui-spec"]
        assert len(routes) == 5, "a route was added or lost; this test must cover each one"

        for route in routes:
            calls["checked"].clear()
            with pytest.raises(HTTPException) as refused:
                asyncio.run(route.endpoint(**self._arguments(route.endpoint)))
            label = f"{sorted(route.methods)} {route.path or '/'}"
            assert refused.value.status_code == 404, label
            assert calls["checked"] == [_UNREACHABLE], f"{label} never asked whether the project is reachable"

        assert calls["service"] == [], "a route reached the service before the access check refused it"

    def test_a_refused_record_reads_like_a_missing_one(self, guarded) -> None:
        """The access rule says "Project not found"; a record route must not repeat it."""
        import asyncio

        router, _ = guarded
        record_routes = [r for r in router.router.routes if getattr(r, "path", "") == "/{record_id}"]
        assert len(record_routes) == 3
        for route in record_routes:
            with pytest.raises(HTTPException) as refused:
                asyncio.run(route.endpoint(**self._arguments(route.endpoint)))
            assert refused.value.detail == "not found", sorted(route.methods)

    def test_listing_without_a_project_is_limited_to_reachable_ones(self, guarded) -> None:
        import asyncio

        router, calls = guarded
        arguments = self._arguments(router.list_records)
        arguments["project_id"] = None

        listed = asyncio.run(router.list_records(**arguments))

        assert listed.total == 0
        assert calls["scoped"] == ["someone-else"]
        assert [name for name, _ in calls["service"]] == ["list_page"]
        assert calls["service"][0][1]["within"] == {_REACHABLE}, "the list was not narrowed to the caller's projects"

    def test_a_record_cannot_be_moved_between_projects(self, tmp_path: Path) -> None:
        """Nothing to check on update when the update cannot name a project at all."""
        spec = a_spec()
        with _imported_module(spec, tmp_path) as import_module:
            schemas = import_module(f"app.modules.{spec.key}.schemas")
            assert "project_id" in schemas.HireCreate.model_fields
            assert "project_id" not in schemas.HireUpdate.model_fields
            with pytest.raises(ValidationError):
                schemas.HireUpdate(project_id=str(_REACHABLE))

    def test_a_module_without_projects_stays_permission_only(self, tmp_path: Path) -> None:
        """Its records belong to no project, so there is no project to check."""
        spec = a_minimal_spec()
        with _imported_module(spec, tmp_path) as import_module:
            router = import_module(f"app.modules.{spec.key}.router")
            assert not hasattr(router, "verify_project_access")
            assert not hasattr(router, "accessible_project_ids")


class TestTheTableActuallyExists:
    """The generated module creates its own table, and only its own.

    A runtime module is outside Alembic's history, so nothing else will ever
    create this table. Rendering a correct ``models.py`` is not the claim being
    made here: the claim is that after install there is a table on the database
    that accepts the module's own rows.
    """

    @pytest.fixture
    def installed(self, tmp_path: Path):
        """The generated module, imported for real, then unregistered.

        Importing the model registers its table on the process-wide
        ``Base.metadata``. Left there, the next test to import it would fail on
        a duplicate table and the failure would land nowhere near its cause.
        """
        import importlib

        from app.core import module_runtime_root as rr
        from app.database import Base

        spec = a_spec()
        generator.write(spec, tmp_path)
        before = list(rr._package_path())
        rr.attach_runtime_root(tmp_path)
        importlib.invalidate_caches()
        try:
            yield spec, importlib.import_module(f"app.modules.{spec.key}.schema")
        finally:
            rr._package_path()[:] = before
            for name in [n for n in list(sys.modules) if n.startswith(f"app.modules.{spec.key}")]:
                del sys.modules[name]
            existing = Base.metadata.tables.get(spec.table_name)
            if existing is not None:
                Base.metadata.remove(existing)
            Base.registry._class_registry.pop(spec.class_name, None)
            importlib.invalidate_caches()

    def test_the_ddl_postgres_would_run_is_the_ddl_we_meant(self, installed) -> None:
        """Production is PostgreSQL, so that is the dialect that has to accept it."""
        from sqlalchemy.dialects import postgresql
        from sqlalchemy.schema import CreateTable

        spec, schema = installed
        ddl = str(CreateTable(schema.table()).compile(dialect=postgresql.dialect()))

        assert f"CREATE TABLE {spec.table_name} (" in ddl
        # Money keeps its cents. A rate rendered as DOUBLE PRECISION is a defect
        # the user finds in an invoice, months later.
        assert "weekly_rate NUMERIC(18, 2) NOT NULL" in ddl
        assert "area_m2 NUMERIC(18, 4)" in ddl
        assert "PRIMARY KEY (id)" in ddl
        assert "FOREIGN KEY(project_id) REFERENCES oe_projects_project (id) ON DELETE CASCADE" in ddl
        assert "DOUBLE PRECISION" not in ddl

    def test_the_table_is_created_and_holds_a_row(self, installed) -> None:
        import uuid
        from datetime import date
        from decimal import Decimal

        from sqlalchemy import create_engine, insert, select

        _, schema = installed
        engine = create_engine("sqlite://")
        try:
            schema.create_table(engine)
            table = schema.table()
            row_id, project_id = uuid.uuid4(), uuid.uuid4()
            with engine.begin() as connection:
                connection.execute(
                    insert(table).values(
                        id=row_id,
                        project_id=project_id,
                        reference="SC-014",
                        bay_count=12,
                        weekly_rate=Decimal("1450.75"),
                        on_hire_date=date(2026, 3, 1),
                        status="erected",
                    )
                )
                found = connection.execute(select(table).where(table.c.id == row_id)).mappings().one()

            assert found["reference"] == "SC-014"
            assert found["bay_count"] == 12
            assert Decimal(str(found["weekly_rate"])) == Decimal("1450.75")
            assert found["project_id"] == project_id
            # Not required by the spec, so it has to be nullable in the table too.
            assert found["off_hire_date"] is None
        finally:
            engine.dispose()

    def test_it_creates_that_table_and_nothing_else(self, installed) -> None:
        """The whole point of scoping ``create_all`` to one table.

        ``Base.metadata`` carries every table the platform owns. An unscoped
        create_all would raise the entire schema outside Alembic and still look
        green here, so the count is what is asserted, not the presence.
        """
        from sqlalchemy import create_engine, inspect

        from app.database import Base

        spec, schema = installed
        assert len(Base.metadata.tables) > 50, "metadata is too small for this test to mean anything"

        engine = create_engine("sqlite://")
        try:
            schema.create_table(engine)
            tables = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()

        assert tables == {spec.table_name}

    def test_creating_twice_is_not_an_error(self, installed) -> None:
        """Install, restart, reinstall. All three call this."""
        from sqlalchemy import create_engine, inspect

        spec, schema = installed
        engine = create_engine("sqlite://")
        try:
            schema.create_table(engine)
            schema.create_table(engine)
            assert set(inspect(engine).get_table_names()) == {spec.table_name}
        finally:
            engine.dispose()

    def test_drop_takes_the_table_away_and_tolerates_its_absence(self, installed) -> None:
        from sqlalchemy import create_engine, inspect

        _, schema = installed
        engine = create_engine("sqlite://")
        try:
            schema.create_table(engine)
            schema.drop_table(engine)
            assert inspect(engine).get_table_names() == []
            schema.drop_table(engine)
        finally:
            engine.dispose()

    # ensure_table / remove_table run against the platform's async engine and
    # are covered in tests/pg/test_module_builder_table.py. There is no async
    # SQLite driver in this environment, and adding a dependency so that a test
    # can avoid the database it actually runs on would prove the wrong thing.


def _clean_env() -> dict[str, str]:
    import os

    env = dict(os.environ)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    return env
