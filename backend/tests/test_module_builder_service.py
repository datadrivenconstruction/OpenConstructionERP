# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the builder's own service and API surface.

The interesting claims are about refusal rather than success. An assistant that
returns something plausible but unbuildable, a key already taken, a module that
writes its files and then fails to load: each of those has to end with the
server in the state it started in, and each is checked here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest

from app.modules.module_builder import router as builder_router
from app.modules.module_builder import service
from app.modules.module_builder.spec import FieldType, RuleKind, url_prefix_for
from tests.test_module_builder_generator import a_spec


class TestTheWizardIsOfferedWhatTheSpecAccepts:
    """The frontend reads its choices from the API, and the API from the spec.

    A field type added to the spec and not to the list would be unreachable
    from the wizard; one listed and not in the spec would be offered and then
    refused on install. Neither is visible without comparing the two.
    """

    def test_every_field_type_is_offered(self) -> None:
        offered = {t.type for t in builder_router.FIELD_TYPES}
        assert offered == set(get_args(FieldType))

    def test_every_rule_kind_is_offered(self) -> None:
        offered = {k.kind for k in builder_router.RULE_KINDS}
        assert offered == set(get_args(RuleKind))

    def test_each_rule_kind_applies_to_types_that_exist(self) -> None:
        known = set(get_args(FieldType))
        for kind in builder_router.RULE_KINDS:
            assert kind.applies_to, f"{kind.kind} applies to nothing"
            assert set(kind.applies_to) <= known, f"{kind.kind} applies to a type that does not exist"

    def test_the_kinds_that_need_more_input_say_so(self) -> None:
        by_kind = {k.kind: k for k in builder_router.RULE_KINDS}
        assert by_kind["order"].needs_other_field
        assert by_kind["range"].needs_bounds
        assert not by_kind["required"].needs_other_field
        assert not by_kind["required"].needs_bounds


class TestADraftThatCannotBeBuiltIsRefusedReadably:
    """Pydantic's own message names locations like entity.fields.3.name."""

    def test_a_field_named_id_is_refused_by_name(self) -> None:
        payload = a_spec().model_dump(mode="json")
        payload["entity"]["fields"][0]["name"] = "id"
        with pytest.raises(service.DraftRefused) as caught:
            service.spec_from_payload(payload)
        assert "reserved" in str(caught.value)

    def test_a_rule_about_a_field_that_is_not_there(self) -> None:
        payload = a_spec().model_dump(mode="json")
        payload["rules"][0]["field"] = "no_such_field"
        with pytest.raises(service.DraftRefused, match="does not exist"):
            service.spec_from_payload(payload)

    def test_a_module_with_no_rules_is_refused(self) -> None:
        """Validation is not optional on this platform, generated or not."""
        payload = a_spec().model_dump(mode="json")
        payload["rules"] = []
        with pytest.raises(service.DraftRefused):
            service.spec_from_payload(payload)

    def test_the_raw_answer_is_kept_for_the_report(self) -> None:
        payload = a_spec().model_dump(mode="json")
        payload["key"] = "projects"
        with pytest.raises(service.DraftRefused) as caught:
            service.spec_from_payload(payload)
        assert caught.value.raw, "the draft that was refused is not recoverable"

    def test_something_that_is_not_a_module_at_all(self) -> None:
        with pytest.raises(service.DraftRefused):
            service.spec_from_payload({"hello": "world"})


class TestPreviewWritesNothing:
    def test_it_returns_the_files_that_would_land(self) -> None:
        files = service.preview(a_spec())
        paths = {f["path"] for f in files}
        assert {"manifest.py", "models.py", "router.py", "spec.json"} <= paths
        # tests/__init__.py is a package marker and is empty on purpose.
        empty = [f["path"] for f in files if not f["content"].strip()]
        assert empty == ["tests/__init__.py"]

    def test_it_leaves_the_runtime_root_empty(self, tmp_path: Path, monkeypatch) -> None:
        from app.core import module_runtime_root as rr

        monkeypatch.setenv(rr.ENV_VAR, str(tmp_path / "root"))
        service.preview(a_spec())
        assert not (tmp_path / "root").exists()


class TestListingWhatIsInstalled:
    @pytest.fixture
    def root(self, tmp_path: Path, monkeypatch) -> Path:
        from app.core import module_runtime_root as rr

        target = tmp_path / "runtime-modules"
        monkeypatch.setenv(rr.ENV_VAR, str(target))
        return target

    def test_nothing_installed_is_not_an_error(self, root: Path) -> None:
        assert service.installed() == []

    def test_a_written_module_is_listed_from_its_own_spec(self, root: Path) -> None:
        from app.modules.module_builder import generator

        root.mkdir(parents=True)
        spec = a_spec()
        generator.write(spec, root)

        listed = service.installed()

        assert [m.key for m in listed] == [spec.key]
        assert listed[0].module_name == "oe_scaffold_hire"
        assert listed[0].field_count == len(spec.entity.fields)
        assert listed[0].rule_count == len(spec.rules)
        assert listed[0].generated_at, "the module does not record when it was generated"

    def test_a_directory_that_is_not_a_module_is_ignored(self, root: Path) -> None:
        """Something a user dropped in the folder by hand is not a generated module."""
        (root / "not_a_module").mkdir(parents=True)
        (root / "not_a_module" / "notes.txt").write_text("mine", encoding="utf-8")
        assert service.installed() == []

    def test_an_unreadable_description_leaves_the_rest_listed(self, root: Path) -> None:
        """One damaged module must not make the whole list unavailable."""
        from app.modules.module_builder import generator

        root.mkdir(parents=True)
        generator.write(a_spec(), root)
        broken = root / "broken"
        broken.mkdir()
        (broken / "spec.json").write_text("{not json", encoding="utf-8")

        assert [m.key for m in service.installed()] == ["scaffold_hire"]


class TestInstallRefusesWithoutTouchingAnything:
    @pytest.fixture
    def root(self, tmp_path: Path, monkeypatch) -> Path:
        from app.core import module_runtime_root as rr

        target = tmp_path / "runtime-modules"
        monkeypatch.setenv(rr.ENV_VAR, str(target))
        return target

    @pytest.mark.asyncio
    async def test_a_key_already_installed(self, root: Path) -> None:
        from app.modules.module_builder import generator

        root.mkdir(parents=True)
        spec = a_spec()
        generator.write(spec, root)
        marker = root / spec.key / "models.py"
        original = marker.read_text(encoding="utf-8")

        with pytest.raises(service.InstallRefused, match="already installed"):
            await service.install(spec, object())

        assert marker.read_text(encoding="utf-8") == original, "the refused install overwrote the module in place"

    @pytest.mark.asyncio
    async def test_a_module_that_fails_to_load_is_removed_again(self, root: Path, monkeypatch) -> None:
        """Files written plus a failed load is the worst outcome: invisible and in the way.

        The key would stay taken by a module nobody can see or use, and the
        user's only route out is a shell on the server.
        """
        spec = a_spec()

        async def explode(app, spec_arg):
            raise RuntimeError("the loader said no")

        monkeypatch.setattr(service, "_load_into", explode)
        with pytest.raises(service.InstallRefused, match="did not load"):
            await service.install(spec, object())

        assert not (root / spec.key).exists()

    @pytest.mark.asyncio
    async def test_uninstalling_something_that_is_not_there(self, root: Path) -> None:
        with pytest.raises(service.InstallRefused, match="No module called"):
            await service.uninstall("never_installed", object())

    @pytest.mark.asyncio
    async def test_uninstall_cannot_reach_a_shipped_module(self, root: Path) -> None:
        """The runtime root is the only place it looks, which is the whole guard.

        ``projects`` exists as a shipped module and must not be removable by
        asking the builder to uninstall it.
        """
        from app.core.module_loader import MODULES_DIR

        assert (Path(MODULES_DIR) / "projects").is_dir(), "projects is not shipped, so this proves nothing"
        with pytest.raises(service.InstallRefused):
            await service.uninstall("projects", object())
        assert (Path(MODULES_DIR) / "projects").is_dir()


class TestThePromptDescribesTheSchemaItWillBeValidatedAgainst:
    """A prompt that drifts from the spec produces drafts that are always refused."""

    def test_every_field_type_appears_in_the_prompt(self) -> None:
        for field_type in get_args(FieldType):
            assert field_type in service.SYSTEM_PROMPT, f"{field_type} is not offered to the assistant"

    def test_every_rule_kind_appears_in_the_prompt(self) -> None:
        for kind in get_args(RuleKind):
            assert kind in service.SYSTEM_PROMPT, f"{kind} is not offered to the assistant"

    def test_it_asks_for_json_and_not_for_code(self) -> None:
        prompt = service.SYSTEM_PROMPT.lower()
        assert "you never write code" in prompt
        assert "return json only" in prompt

    def test_the_shape_it_asks_for_is_the_shape_that_validates(self) -> None:
        """The prompt carries an example object. It has to be one the spec accepts."""
        start = service.SYSTEM_PROMPT.index("{")
        end = service.SYSTEM_PROMPT.rindex("}") + 1
        skeleton = service.SYSTEM_PROMPT[start:end]
        # Not parsed as JSON: the example is annotated with the choices rather
        # than filled in. What is checked is that every key the spec requires is
        # named in it, so the assistant is never asked for a field that does not
        # exist or left to guess one that does.
        for required in ("key", "display_name", "entity", "fields", "rules", "kind", "code", "message"):
            assert f'"{required}"' in skeleton, f"the prompt never mentions {required}"


class TestTheDraftPathRefusesBeforeItSpends:
    @pytest.mark.asyncio
    async def test_an_empty_description_never_reaches_the_assistant(self) -> None:
        """No provider call, so no tokens and no waiting for a refusal."""
        with pytest.raises(service.DraftRefused, match="sentence or two"):
            await service.draft_spec(None, "irrelevant", "  ")

    @pytest.mark.asyncio
    async def test_an_enormous_description_is_refused_by_length(self) -> None:
        with pytest.raises(service.DraftRefused, match="longer than"):
            await service.draft_spec(None, "irrelevant", "x" * (service.MAX_DESCRIPTION + 1))


class TestWhereAGeneratedModuleIsServed:
    """The wizard shows a URL, the frontend fetches it, the loader mounts it.

    Three places and one rule, and the loader owns it: a router goes up at the
    hyphenated form of the module directory name, so a key with an underscore
    is served from a path without one. Getting this wrong is not a 404 - the
    loader also mirrors the underscore form for legacy callers - it is a
    frontend built against the path nobody documents.
    """

    def test_an_underscore_in_the_key_becomes_a_hyphen(self) -> None:
        assert url_prefix_for("site_diary") == "/api/v1/site-diary"

    def test_a_key_with_no_underscore_is_unchanged(self) -> None:
        assert url_prefix_for("diary") == "/api/v1/diary"

    def test_the_spec_carries_it(self) -> None:
        assert a_spec().url_prefix == "/api/v1/scaffold-hire"

    def test_the_listing_says_where_each_module_is_served(self, tmp_path: Path, monkeypatch) -> None:
        """The screen is opened from this field, so it comes back from the API."""
        from app.core import module_runtime_root as rr
        from app.modules.module_builder import generator

        root = tmp_path / "runtime-modules"
        monkeypatch.setenv(rr.ENV_VAR, str(root))
        root.mkdir(parents=True)
        generator.write(a_spec(), root)

        assert [m.base_path for m in service.installed()] == ["/api/v1/scaffold-hire"]

    def test_the_generated_readme_names_the_url_it_answers_on(self) -> None:
        """Whoever installed it reads this file to find out what they can call."""
        files = {f["path"]: f["content"] for f in service.preview(a_spec())}
        assert "/api/v1/scaffold-hire" in files["README.md"]
        assert "/api/v1/scaffold_hire" not in files["README.md"], "the README points at the mirror, not the URL"


class TestSpecJsonIsWhatTheScreenIsBuiltFrom:
    def test_it_round_trips_back_into_a_spec(self, tmp_path: Path) -> None:
        """The frontend renders from this file, so it has to describe the module fully."""
        from app.modules.module_builder import generator
        from app.modules.module_builder.spec import ModuleSpec

        spec = a_spec()
        generator.write(spec, tmp_path)
        payload = json.loads((tmp_path / spec.key / "spec.json").read_text(encoding="utf-8"))
        payload.pop("generated_at", None)
        payload.pop("generator", None)

        assert ModuleSpec.model_validate(payload) == spec
