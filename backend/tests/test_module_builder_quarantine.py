# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A module installed by a generator that wrote names into code unescaped.

Up to generator 2 a name holding quotes could end the docstring it was
written into and leave a statement of its own behind, which ran every time
the server imported the module. The fixtures here are made with exactly that
generator: the current one with its two escaping helpers replaced by what
generator 2 did in their place.

What the refresh at startup must guarantee, for every kind of file the name
can reach: the statement is either rendered away, or the module is moved
where the loader never looks and is not imported at all. And a module whose
names are ordinary refreshes to the same bytes it had, apart from its stamp.
"""

from __future__ import annotations

import ast
import builtins
import json
import logging
from pathlib import Path

import pytest

from app.modules.module_builder import generator, refresh, service
from app.modules.module_builder.spec import EntitySpec, FieldSpec, ModuleSpec, RuleSpec
from tests.test_module_builder_v2 import a_minimal_spec, a_spec, hire_spec, notice_spec

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "module_builder_v2"
V2_STAMP = "openconstructionerp.module_builder/2"

# Ends the docstring, sets a flag, opens a string the rest of the line closes.
# Lower case, so it survives the .lower() some sinks apply.
MARK = "mb_ran"
HOSTILE = f'Pour log""";__import__("builtins").{MARK}=1;"""'

CONTRACT = ("models.py", "schema.py", "schemas.py")


def _spec(display_name: str = HOSTILE, key: str = "rv_hostile") -> ModuleSpec:
    return ModuleSpec(
        key=key,
        display_name=display_name,
        entity=EntitySpec(
            name="pour",
            display_name=display_name,
            project_scoped=True,
            fields=[FieldSpec(name="ref", label="Ref", type="text", required=True)],
        ),
        rules=[RuleSpec(code="REF_REQUIRED", message="Needs a ref.", kind="required", field="ref")],
    )


def _old(spec: ModuleSpec, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Every file as generator 2 rendered it: names straight into the code."""
    with monkeypatch.context() as patch:
        patch.setattr(generator, "_doc", lambda text: text)
        patch.setattr(generator, "_lit", lambda text: f'"{text}"')
        return {f.path: f.content for f in generator.render(spec)}


def _current(spec: ModuleSpec) -> dict[str, str]:
    return {f.path: f.content for f in generator.render(spec)}


def _install(root: Path, spec: ModuleSpec, files: dict[str, str]) -> Path:
    """Lay the files out as an install under stamp 2."""
    target = root / spec.key
    for path, content in files.items():
        destination = target / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8", newline="\n")
    payload = json.loads(files["spec.json"])
    payload["generator"] = V2_STAMP
    (target / "spec.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def _mixed(spec: ModuleSpec, monkeypatch: pytest.MonkeyPatch, hostile: tuple[str, ...]) -> dict[str, str]:
    """The current render, with the named files as generator 2 wrote them."""
    old = _old(spec, monkeypatch)
    files = _current(spec)
    for name in hostile:
        files[name] = old[name]
    return files


def _code_sets_the_mark(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(isinstance(n, ast.Attribute) and n.attr == MARK for n in ast.walk(tree))


def _python_under(directory: Path) -> dict[str, str]:
    return {
        p.relative_to(directory).as_posix(): p.read_text(encoding="utf-8")
        for p in directory.rglob("*.py")
        if "__pycache__" not in p.parts
    }


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {
        p.relative_to(directory).as_posix(): p.read_bytes()
        for p in sorted(directory.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "runtime-modules"
    path.mkdir()
    return path


@pytest.fixture(autouse=True)
def no_mark():
    yield
    if hasattr(builtins, MARK):
        delattr(builtins, MARK)


class TestTheFixtureIsARealInjection:
    """Otherwise every test below checks that nothing happens to harmless files."""

    def test_the_old_package_file_runs_the_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        source = _old(_spec(), monkeypatch)["__init__.py"]
        assert not hasattr(builtins, MARK)
        exec(compile(source, "__init__.py", "exec"), {"__name__": "rv_hostile_probe"})  # noqa: S102
        assert getattr(builtins, MARK) == 1

    @pytest.mark.parametrize("name", ["__init__.py", "manifest.py", *CONTRACT, "permissions.py", "validators.py"])
    def test_the_name_is_a_statement_in_every_file_it_reaches(self, name: str, monkeypatch: pytest.MonkeyPatch) -> None:
        assert _code_sets_the_mark(_old(_spec(), monkeypatch)[name]), name

    def test_the_current_generator_keeps_it_text(self) -> None:
        for name, source in _current(_spec()).items():
            if name.endswith(".py"):
                assert not _code_sets_the_mark(source), name


class TestWhatTheRefreshRepairs:
    def test_code_files_are_rendered_again(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec()
        code = (*refresh.CODE_FILES, f"tests/test_{spec.key}.py")
        target = _install(root, spec, _mixed(spec, monkeypatch, code))
        assert any(_code_sets_the_mark(source) for source in _python_under(target).values())

        assert refresh.refresh_installed(root) == {spec.key: refresh.REFRESHED}

        current = _current(spec)
        for name, source in _python_under(target).items():
            assert source == current[name], name
            assert not _code_sets_the_mark(source), name

    def test_a_manifest_holding_a_statement_is_rendered_again(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = _spec()
        target = _install(root, spec, _mixed(spec, monkeypatch, ("manifest.py",)))

        assert refresh.refresh_installed(root) == {spec.key: refresh.REFRESHED}

        assert (target / "manifest.py").read_text(encoding="utf-8") == _current(spec)["manifest.py"]
        assert not any(_code_sets_the_mark(s) for s in _python_under(target).values())

    def test_a_name_with_a_backslash_only_changes_docstrings(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Escaped now, raw before: the same table, so the contract files are rewritten, not refused."""
        spec = _spec(display_name="Pipes A\\B", key="rv_pipes")
        old = _old(spec, monkeypatch)
        assert old["models.py"] != _current(spec)["models.py"]
        target = _install(root, spec, old)

        assert refresh.refresh_installed(root) == {spec.key: refresh.REFRESHED}

        # The manifest holds no statement the render lacks, so it is left as it was.
        expected = {k: v for k, v in _current(spec).items() if k.endswith(".py")}
        expected["manifest.py"] = old["manifest.py"]
        assert _python_under(target) == expected


class TestWhatIsQuarantined:
    @pytest.mark.parametrize("name", CONTRACT)
    def test_a_contract_file_holding_a_statement(
        self, root: Path, name: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        spec = _spec()
        target = _install(root, spec, _mixed(spec, monkeypatch, (name,)))
        before = _snapshot(target)

        with caplog.at_level(logging.ERROR, logger=refresh.logger.name):
            outcome = refresh.refresh_installed(root)

        assert outcome == {spec.key: refresh.QUARANTINED}
        self._is_out_of_reach(root, spec.key, before, refresh.UNSAFE_CODE, {"files": [name]})
        errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
        assert any(spec.key in m and name in m for m in errors), errors

    def test_a_whole_old_install(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec()
        target = _install(root, spec, _old(spec, monkeypatch))
        before = _snapshot(target)

        assert refresh.refresh_installed(root) == {spec.key: refresh.QUARANTINED}
        self._is_out_of_reach(root, spec.key, before, refresh.UNSAFE_CODE, {"files": list(CONTRACT)})

    def test_a_spec_that_no_longer_validates_and_could_hold_code(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A control character is refused by the spec now, so the module cannot be rendered to check it."""
        spec = _spec(display_name='The "Pour" log', key="rv_unrenderable")
        files = _old(spec, monkeypatch)
        payload = json.loads(files["spec.json"])
        payload["entity"]["fields"][0]["label"] = "Ref\nnext"
        files["spec.json"] = json.dumps(payload)
        target = _install(root, spec, files)
        before = _snapshot(target)

        assert refresh.refresh_installed(root) == {spec.key: refresh.QUARANTINED}
        self._is_out_of_reach(root, spec.key, before, refresh.UNVERIFIABLE, {})

    def test_an_invalid_spec_with_ordinary_names_still_loads(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The control: no character in it could have left a literal, so the old behaviour stands."""
        spec = _spec(display_name="Pour log", key="rv_plain_invalid")
        files = _old(spec, monkeypatch)
        payload = json.loads(files["spec.json"])
        payload["rules"] = []
        files["spec.json"] = json.dumps(payload)
        target = _install(root, spec, files)
        before = _snapshot(target)

        assert refresh.refresh_installed(root) == {spec.key: refresh.INVALID}
        assert _snapshot(target) == before

    def test_a_hand_edit_beside_a_name_that_could_break_out(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec(display_name='The "Pour" log', key="rv_hand_edit")
        target = _install(root, spec, _old(spec, monkeypatch))
        with (target / "models.py").open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("# changed by hand\n")
        before = _snapshot(target)

        assert refresh.refresh_installed(root) == {spec.key: refresh.QUARANTINED}
        self._is_out_of_reach(root, spec.key, before, refresh.UNVERIFIABLE, {})

    def test_a_failed_rewrite_of_code_a_name_reached(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        spec = _spec()
        target = _install(root, spec, _mixed(spec, monkeypatch, ("router.py", "__init__.py")))
        before = _snapshot(target)

        def broken(directory: Path, files: dict[str, str]) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(refresh, "_write_files", broken)

        assert refresh.refresh_installed(root) == {spec.key: refresh.QUARANTINED}
        self._is_out_of_reach(root, spec.key, before, refresh.UNVERIFIABLE, {})

    def test_a_failed_rewrite_of_ordinary_code_keeps_it_loading(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = _spec(display_name="Pour log", key="rv_plain_failed")
        target = _install(root, spec, _current(spec))

        def broken(directory: Path, files: dict[str, str]) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(refresh, "_write_files", broken)

        assert refresh.refresh_installed(root) == {spec.key: refresh.FAILED}
        assert target.is_dir()

    def test_the_listing_shows_it_and_removing_it_imports_nothing(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = _spec()
        _install(root, spec, _old(spec, monkeypatch))
        refresh.refresh_installed(root)
        monkeypatch.setattr(service, "runtime_modules_dir", lambda: root)

        listed = {m.key: m for m in service.installed()}
        assert listed[spec.key].status == "quarantined"
        assert listed[spec.key].problem == {"code": refresh.UNSAFE_CODE, "params": {"files": list(CONTRACT)}}

        import asyncio

        result = asyncio.run(service.uninstall(spec.key, app=None, drop_data=False))

        assert result == {"key": spec.key, "module_name": spec.module_name, "removed": True, "data_dropped": False}
        assert not (refresh.quarantine_dir(root) / spec.key).exists()
        assert service.installed() == []
        assert not hasattr(builtins, MARK)

    def test_the_router_reports_it(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.module_builder.router import _read

        spec = _spec()
        _install(root, spec, _old(spec, monkeypatch))
        refresh.refresh_installed(root)
        monkeypatch.setattr(service, "runtime_modules_dir", lambda: root)

        read = _read(next(m for m in service.installed() if m.key == spec.key)).model_dump()

        assert read["status"] == "quarantined"
        assert read["problem"] == {"code": "unsafe_code", "params": {"files": list(CONTRACT)}}

    def test_quarantine_is_not_refreshed_again_and_not_a_module(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = _spec()
        _install(root, spec, _old(spec, monkeypatch))
        refresh.refresh_installed(root)

        assert refresh.refresh_installed(root) == {}
        assert refresh._installed(root) == []

    def test_when_the_refresh_cannot_run_an_exposed_module_still_does_not_load(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A refresh lock held past its wait: the loader runs next anyway."""
        hostile = _spec()
        _install(root, hostile, _mixed(hostile, monkeypatch, ("router.py",)))
        plain = _spec(display_name="Pour log", key="rv_plain")
        plain_target = _install(root, plain, _current(plain))
        plain_before = _snapshot(plain_target)

        def held(work: Path):
            raise TimeoutError("another process holds the lock")

        monkeypatch.setattr(refresh, "_exclusive", held)

        assert refresh.refresh_installed(root) == {}
        assert not (root / hostile.key).exists()
        assert refresh._installed(root) == [plain_target]
        assert _snapshot(plain_target) == plain_before, "an ordinary module keeps loading the code it has"
        note = json.loads((refresh.quarantine_dir(root) / hostile.key / refresh.QUARANTINE_NOTE).read_text("utf-8"))
        assert note["code"] == refresh.UNVERIFIABLE

    @pytest.mark.parametrize("key", ["..", ".", "_module_builder", "a/b", "A"])
    def test_uninstall_takes_only_a_module_key(self, key: str, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import asyncio

        monkeypatch.setattr(service, "runtime_modules_dir", lambda: root)
        with pytest.raises(service.InstallRefused):
            asyncio.run(service.uninstall(key, app=None, drop_data=True))
        assert root.is_dir()

    @staticmethod
    def _is_out_of_reach(root: Path, key: str, before: dict[str, bytes], code: str, params: dict) -> None:
        assert not (root / key).exists(), "the module is still where the loader looks"
        place = refresh.quarantine_dir(root) / key
        # The loader skips every directory whose name starts with an underscore.
        assert place.relative_to(root).parts[0].startswith("_")
        after = _snapshot(place)
        note = json.loads(after.pop(refresh.QUARANTINE_NOTE))
        assert after == before, "the quarantined files were changed"
        assert (note["code"], note["params"], note["generator"]) == (code, params, 2)
        assert not hasattr(builtins, MARK)


class TestOrdinaryModulesRefreshToTheSameBytes:
    """The four v2 fixtures: generator 3 renders them byte for byte, so only the stamp moves."""

    @pytest.mark.parametrize("make", [hire_spec, notice_spec, a_spec, a_minimal_spec])
    def test_zero_diff_but_the_stamp(self, root: Path, make) -> None:
        spec = make()
        source = FIXTURES / spec.key
        target = root / spec.key
        for fixture in sorted(source.rglob("*.v2")):
            path = fixture.relative_to(source).as_posix().removesuffix(".v2")
            destination = target / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(fixture.read_bytes().replace(b"\r\n", b"\n"))
        before = _snapshot(target)
        assert json.loads(before["spec.json"])["generator"] == V2_STAMP

        assert refresh.refresh_installed(root) == {spec.key: refresh.REFRESHED}

        after = _snapshot(target)
        assert set(after) == set(before)
        assert {p for p in before if before[p] != after[p]} == {"spec.json"}
        old_spec, new_spec = json.loads(before["spec.json"]), json.loads(after["spec.json"])
        assert new_spec.pop("generator") == generator.GENERATOR_STAMP
        old_spec.pop("generator")
        assert new_spec.pop("generated_at") == old_spec.pop("generated_at")
        assert ModuleSpec.model_validate(new_spec) == ModuleSpec.model_validate(old_spec) == spec


class TestTellingCodeFromText:
    def test_docstring_only_differences(self) -> None:
        a = b'"""One."""\n\nx = 1\n'
        b = b'"""Two, longer."""\n\nx = 1\n'
        assert refresh.same_apart_from_docstrings(a, b)
        assert not refresh.same_apart_from_docstrings(a, b'"""One."""\n\nx = 2\n')
        assert not refresh.same_apart_from_docstrings(a, b'"""One."""\n\nx = 1  # note\n')

    def test_a_docstring_turned_into_an_expression_adds_code(self) -> None:
        rendered = '"""Pour log module manifest."""\n\nmanifest = make()\n'
        assert refresh.adds_code(
            b'"""A""" + __import__("os").getcwd() + """ module."""\n\nmanifest = make()\n', rendered
        )
        assert refresh.adds_code(b'"""A"""\nmanifest = evil()\n"""x"""\nmanifest = make()\n', rendered)
        assert not refresh.adds_code(b'"""Other words."""\n\nmanifest = make()\n', rendered)
        assert not refresh.adds_code(b"def broken(:\n", rendered), "a file Python cannot parse never runs"

    @pytest.mark.parametrize(
        ("value", "exposed"),
        [
            ({"a": "Plain words, l'apostrophe, Ümlaut"}, False),
            ({"a": ['say "hi"']}, True),
            ({"a": {"b": "back\\slash"}}, True),
            ({"a": "line\nbreak"}, True),
            ({"a": "para graph"}, True),
            ({"a": 3, "b": None}, False),
        ],
    )
    def test_what_could_break_out(self, value: dict, exposed: bool) -> None:
        assert refresh.could_break_out(value) is exposed
