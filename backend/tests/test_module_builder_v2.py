# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module builder v2: links, features, suggestions, and what stays as it was.

The claims checked here, in the order a reviewer would ask them:

- every spec written before v2 still validates and still renders the same
  code byte for byte, so a refresh to generator 3 goes through for them;
- a module with links and every feature is as real as one without: it
  compiles, lints, imports, and passes the tests it ships with;
- the assistant is asked for the base module plus suggestions, never for
  links or features inside the module, and nothing it suggests reaches the
  spec on the server;
- the rule-based suggestions read field names in every shipped language and
  do not mistake a contractor for a contract or a pour date for a deadline.

Database behaviour (foreign keys, defaults, indexes, access) is in
``tests/pg/test_module_builder_v2.py``.
"""

from __future__ import annotations

import compileall
import importlib
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, get_args

import pytest
from fastapi import HTTPException

from app.modules.module_builder import generator, links, service, suggest
from app.modules.module_builder.schemas import LOCALE_PATTERN, Suggestion
from app.modules.module_builder.spec import (
    FEATURE_NAMES,
    MAX_IDENTIFIER_BYTES,
    EntitySpec,
    FieldSpec,
    FieldType,
    LinkTarget,
    ModuleSpec,
    RuleSpec,
)
from tests.test_module_builder_generator import _clean_env, _guards, a_minimal_spec, a_spec, ruff_check
from tests.test_module_builder_refresh import hire_spec, notice_spec

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
FIXTURES = Path(__file__).parent / "fixtures"


def featured_spec(key: str = "pour_log", *, scoped: bool = True) -> ModuleSpec:
    """Links to a contract and a person, and every feature the scope allows."""
    features: dict[str, Any] = {
        "status": {
            "states": [
                {"code": "open", "label": "Open"},
                {"code": "in_progress", "label": "In progress"},
                {"code": "done", "label": "Done", "done": True},
            ]
        },
        "export": True,
    }
    if scoped:
        features["due"] = {"field": "due_on", "remind_days_before": 2}
        features["comments"] = True
    return ModuleSpec.model_validate(
        {
            "key": key,
            "display_name": "Pour Log",
            "description": "Every concrete pour, its contract and who signs it off.",
            "schema_version": 2,
            "entity": {
                "name": "pour",
                "display_name": "Pour",
                "plural_name": "Pours",
                "project_scoped": scoped,
                "fields": [
                    {"name": "reference", "label": "Reference", "type": "text", "required": True},
                    {"name": "due_on", "label": "Due", "type": "date"},
                    {"name": "contract", "label": "Contract", "type": "link", "target": "contract", "required": True},
                    {"name": "responsible", "label": "Responsible", "type": "link", "target": "user"},
                ],
            },
            "rules": [
                {"code": "REFERENCE_REQUIRED", "message": "A pour needs a reference.", "kind": "required",
                 "field": "reference"},
                {"code": "CONTRACT_REQUIRED", "message": "Name the contract.", "kind": "required",
                 "field": "contract"},
            ],
            "features": features,
        }
    )  # fmt: skip


# ── spec ────────────────────────────────────────────────────────────────────


class TestOldSpecsStillValidate:
    """extra="forbid" is unforgiving: one new required key and every install breaks."""

    @pytest.mark.parametrize(
        "path", sorted(FIXTURES.glob("module_builder_v*/*/spec.json*")), ids=lambda p: p.parent.name
    )
    def test_every_spec_json_on_disk_validates(self, path: Path) -> None:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("generated_at", None)
        payload.pop("generator", None)
        spec = ModuleSpec.model_validate(payload)
        assert spec.features.status is None and spec.features.due is None
        assert not spec.features.export and not spec.features.comments

    def test_a_spec_without_the_new_keys_reads_as_layout_one(self) -> None:
        payload = a_spec().model_dump(mode="json")
        for key in ("schema_version", "features"):
            payload.pop(key)
        for field in payload["entity"]["fields"]:
            field.pop("target")
        spec = ModuleSpec.model_validate(payload)
        assert spec.schema_version == 1
        assert spec.link_fields == []

    def test_a_field_called_status_is_fine_while_the_feature_is_off(self) -> None:
        assert any(f.name == "status" for f in a_spec().entity.fields)


class TestTheNewSpecRules:
    def _payload(self, **features: Any) -> dict[str, Any]:
        payload = featured_spec().model_dump(mode="json")
        payload["features"] = {**payload["features"], **features}
        return payload

    def test_a_link_must_say_what_it_links_to(self) -> None:
        with pytest.raises(ValueError, match="does not say what it links to"):
            FieldSpec(name="contract", label="Contract", type="link")

    def test_only_a_link_names_a_target(self) -> None:
        with pytest.raises(ValueError, match="names a link target"):
            FieldSpec(name="contract", label="Contract", type="text", target="contract")

    def test_an_unknown_target_is_refused(self) -> None:
        with pytest.raises(ValueError):
            FieldSpec.model_validate({"name": "x", "label": "X", "type": "link", "target": "invoice"})

    def test_status_is_reserved_once_the_feature_is_on(self) -> None:
        payload = a_spec().model_dump(mode="json")
        payload["features"]["status"] = featured_spec().model_dump(mode="json")["features"]["status"]
        with pytest.raises(ValueError, match="called status"):
            ModuleSpec.model_validate(payload)

    def test_status_states_are_two_to_eight_and_distinct(self) -> None:
        one = {"states": [{"code": "open", "label": "Open"}]}
        twins = {"states": [{"code": "open", "label": "Open"}, {"code": "open", "label": "Again"}]}
        with pytest.raises(ValueError):
            ModuleSpec.model_validate(self._payload(status=one))
        with pytest.raises(ValueError, match="duplicate status"):
            ModuleSpec.model_validate(self._payload(status=twins))

    def test_the_deadline_must_be_a_date_field_that_exists(self) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            ModuleSpec.model_validate(self._payload(due={"field": "nowhere"}))
        with pytest.raises(ValueError, match="not a date"):
            ModuleSpec.model_validate(self._payload(due={"field": "reference"}))

    def test_deadlines_and_comments_need_a_project(self) -> None:
        payload = featured_spec(scoped=False).model_dump(mode="json")
        with pytest.raises(ValueError, match="per project"):
            ModuleSpec.model_validate({**payload, "features": {**payload["features"], "due": {"field": "due_on"}}})
        with pytest.raises(ValueError, match="within a project"):
            ModuleSpec.model_validate({**payload, "features": {**payload["features"], "comments": True}})

    def test_a_name_past_postgres_limit_is_refused_in_the_new_layout(self) -> None:
        long_key = "a" * 40
        payload = a_minimal_spec().model_dump(mode="json")
        payload["key"] = long_key
        payload["entity"]["name"] = "b" * 20
        # Layout one is not held to it: such a module may already be installed.
        ModuleSpec.model_validate(payload)
        with pytest.raises(ValueError, match=f"longer than {MAX_IDENTIFIER_BYTES} bytes"):
            ModuleSpec.model_validate({**payload, "schema_version": 2})

    def test_a_link_index_past_the_limit_is_refused_in_any_layout(self) -> None:
        payload = featured_spec().model_dump(mode="json")
        payload["key"] = "k" * 30
        payload["entity"]["name"] = "e" * 15
        payload["schema_version"] = 1
        payload["entity"]["fields"][2]["name"] = "contract_" + "c" * 10
        payload["rules"][1]["field"] = payload["entity"]["fields"][2]["name"]
        with pytest.raises(ValueError, match="longer than"):
            ModuleSpec.model_validate(payload)

    def test_the_index_names_the_spec_checks_are_the_ones_the_model_declares(self) -> None:
        spec = featured_spec()
        models = next(f.content for f in generator.render(spec) if f.path == "models.py")
        declared = re.findall(r'Index\("([^"]+)"', models)
        assert sorted(declared) == sorted(spec.base_index_names + spec.new_index_names)


# ── generator ───────────────────────────────────────────────────────────────


class TestAFeaturelessSpecRendersExactlyAsBefore:
    """Why a module installed under stamp 2 refreshes cleanly to 3.

    The fixtures are the full render of the v2 generator as it was committed,
    before links and features. A spec with none of them must render the same
    bytes in every file but spec.json. Generator 3 only escapes names where
    they land in code, which ordinary names never need, so the table and API
    files a refresh compares still match and the refresh is not refused.
    """

    @pytest.mark.parametrize("make", [hire_spec, notice_spec, a_spec, a_minimal_spec])
    def test_every_file_but_the_spec_matches_the_fixture(self, make) -> None:
        spec = make()
        compared = 0
        for item in generator.render(spec):
            if item.path == "spec.json":
                continue
            expected = (FIXTURES / "module_builder_v2" / spec.key / f"{item.path}.v2").read_text(encoding="utf-8")
            assert item.content == expected, f"{spec.key}/{item.path} renders differently than before v2"
            compared += 1
        assert compared == len(generator.render(spec)) - 1

    def test_the_stamp_is_three(self) -> None:
        assert generator.GENERATOR_STAMP == "openconstructionerp.module_builder/3"

    def test_a_module_installed_under_stamp_two_is_refreshed_to_the_same_code(self, tmp_path: Path) -> None:
        from app.modules.module_builder import refresh

        generator.write(hire_spec(), tmp_path)
        target = tmp_path / hire_spec().key
        payload = json.loads((target / "spec.json").read_text(encoding="utf-8"))
        payload["generator"] = "openconstructionerp.module_builder/2"
        (target / "spec.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        before = {p: p.read_bytes() for p in target.rglob("*.py")}

        assert refresh.refresh_installed(tmp_path) == {hire_spec().key: refresh.REFRESHED}
        assert {p: p.read_bytes() for p in before} == before
        assert json.loads((target / "spec.json").read_text(encoding="utf-8"))["generator"] == generator.GENERATOR_STAMP
        assert refresh.refresh_installed(tmp_path) == {hire_spec().key: refresh.CURRENT}


@pytest.fixture(params=[True, False], ids=["scoped", "unscoped"])
def featured(request, tmp_path: Path):
    """A featured module written to disk and importable, removed afterwards."""
    from app.core import module_runtime_root as rr
    from app.database import Base

    spec = featured_spec(f"pour_log_{'p' if request.param else 'g'}", scoped=request.param)
    generator.write(spec, tmp_path)
    before = list(rr._package_path())
    rr.attach_runtime_root(tmp_path)
    importlib.invalidate_caches()
    try:
        yield spec, tmp_path
    finally:
        rr._package_path()[:] = before
        for name in [n for n in list(sys.modules) if n.startswith(f"app.modules.{spec.key}")]:
            del sys.modules[name]
        existing = Base.metadata.tables.get(spec.table_name)
        if existing is not None:
            Base.metadata.remove(existing)
        Base.registry._class_registry.pop(spec.class_name, None)
        importlib.invalidate_caches()


class TestAFeaturedModuleIsReal:
    def test_it_compiles(self, featured) -> None:
        spec, root = featured
        assert compileall.compile_dir(str(root / spec.key), quiet=1, force=True)

    def test_ruff_accepts_it(self, featured) -> None:
        spec, root = featured
        result = ruff_check(root / spec.key)
        assert result.returncode == 0, result.stdout + result.stderr

    @pytest.mark.parametrize(
        "name",
        ["manifest", "models", "schema", "schemas", "validators", "permissions", "repository", "service", "router"],
    )
    def test_every_file_imports(self, featured, name: str) -> None:
        spec, _root = featured
        importlib.import_module(f"app.modules.{spec.key}.{name}")

    def test_its_own_tests_pass(self, featured) -> None:
        from app.core import module_runtime_root as rr

        spec, root = featured
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(root / spec.key / "tests"),
                "-q",
                "--no-header",
                "-p",
                "no:cacheprovider",
            ],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(BACKEND_ROOT),
            env={**_clean_env(), rr.ENV_VAR: str(root)},
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "passed" in result.stdout

    def test_the_manifest_depends_on_what_the_links_point_at(self, featured) -> None:
        spec, _root = featured
        manifest = importlib.import_module(f"app.modules.{spec.key}.manifest").manifest
        assert {"oe_contracts", "oe_users"} <= set(manifest.depends)
        assert ("oe_projects" in manifest.depends) is spec.entity.project_scoped

    def test_links_are_nullable_foreign_keys_that_set_null(self, featured) -> None:
        spec, _root = featured
        table = getattr(importlib.import_module(f"app.modules.{spec.key}.models"), spec.class_name).__table__
        for name, target in (("contract", "oe_contracts_contract"), ("responsible", "oe_users_user")):
            column = table.c[name]
            assert column.nullable, f"{name} must be nullable so deleting its target cannot be blocked"
            (fk,) = column.foreign_keys
            assert fk.target_fullname == f"{target}.id"
            assert fk.ondelete == "SET NULL"

    def test_the_status_column_defaults_to_the_first_state(self, featured) -> None:
        spec, _root = featured
        table = getattr(importlib.import_module(f"app.modules.{spec.key}.models"), spec.class_name).__table__
        status = table.c["status"]
        assert not status.nullable
        assert status.server_default.arg == "open"
        assert status.type.length == 32

    def test_an_unknown_status_is_refused_and_a_known_one_passes(self, featured) -> None:
        spec, _root = featured
        validators = importlib.import_module(f"app.modules.{spec.key}.validators")
        schemas = importlib.import_module(f"app.modules.{spec.key}.schemas")
        base = {"reference": "P-1", "contract": "6f1c1b1e-4a8e-4bd6-9a3c-2b1f0d1e2f3a"}
        if spec.entity.project_scoped:
            base["project_id"] = "1f1c1b1e-4a8e-4bd6-9a3c-2b1f0d1e2f3a"
        create = getattr(schemas, f"{spec.class_name}Create")
        assert create.model_validate(base).status == "open"
        assert validators.validate(create.model_validate({**base, "status": "done"})) == []
        codes = [f.code for f in validators.validate(create.model_validate({**base, "status": "closed"}))]
        assert codes == ["STATUS_KNOWN"]

    def test_export_is_served_before_the_record_route_and_guarded(self, featured) -> None:
        from app.dependencies import RequirePermission

        spec, _root = featured
        router = importlib.import_module(f"app.modules.{spec.key}.router").router
        gets = [r.path for r in router.routes if "GET" in getattr(r, "methods", ())]
        assert gets.index("/export") < gets.index("/{record_id}"), "/export would be read as a record id"
        export = next(r for r in router.routes if getattr(r, "path", "") == "/export")
        assert [g.permission for g in _guards(export, RequirePermission)] == [f"{spec.key}.read"]

    def test_writes_carry_the_caller_for_the_link_check(self, featured) -> None:
        import inspect

        spec, _root = featured
        service_mod = importlib.import_module(f"app.modules.{spec.key}.service")
        cls = getattr(service_mod, f"{spec.class_name}Service")
        assert "user_id" in inspect.signature(cls.create).parameters
        assert "user_id" in inspect.signature(cls.update).parameters
        assert service_mod.LINKS == {"contract": "contract", "responsible": "user"}


# ── the assistant ───────────────────────────────────────────────────────────


def _prompt_parts() -> tuple[str, str]:
    prompt = service.SYSTEM_PROMPT
    start = prompt.index('"module"')
    split = prompt.index('"suggestions"')
    return prompt[start:split], prompt[split:]


class TestThePromptAsksForTheBaseModuleAndSuggestions:
    def test_the_field_types_offered_for_the_module_are_every_base_type(self) -> None:
        module_part, _ = _prompt_parts()
        line = next(ln for ln in module_part.splitlines() if '"type":' in ln)
        offered = {t.strip() for t in line.split(":", 1)[1].strip().strip('",').split("|")}
        assert offered == set(get_args(FieldType)) - {"link"}

    def test_links_and_features_are_only_offered_as_suggestions(self) -> None:
        module_part, suggestions_part = _prompt_parts()
        for target in get_args(LinkTarget):
            assert target in suggestions_part, f"link target {target} is not offered"
        for feature in FEATURE_NAMES:
            assert feature in suggestions_part, f"feature {feature} is not offered"
        assert '"features"' not in module_part
        assert '"target"' not in module_part

    def test_it_asks_for_a_confidence_band_and_a_reason(self) -> None:
        _, suggestions_part = _prompt_parts()
        assert '"confidence": "high | medium | low"' in suggestions_part
        assert '"reason"' in suggestions_part

    def test_the_reader_language_is_named_when_given(self) -> None:
        assert service.system_prompt(None) == service.SYSTEM_PROMPT
        assert "in German." in service.system_prompt("de")
        assert "in Portuguese." in service.system_prompt("pt-BR")
        assert "the language with the tag kk" in service.system_prompt("kk")

    def test_every_language_the_suggester_knows_has_a_name_for_the_assistant(self) -> None:
        assert set(service.LANGUAGE_NAMES) == set(suggest.LANGUAGES)


class TestNothingSuggestedReachesTheSpec:
    def _module(self) -> dict[str, Any]:
        payload = a_spec().model_dump(mode="json")
        for key in ("schema_version", "features"):
            payload.pop(key)
        return payload

    def test_links_and_features_in_the_module_are_taken_out(self) -> None:
        module = self._module()
        module["entity"]["fields"].append(
            {"name": "contract", "label": "Contract", "type": "link", "target": "contract"}
        )
        module["rules"].append(
            {"code": "CONTRACT_REQUIRED", "message": "Name it.", "kind": "required", "field": "contract"}
        )
        module["features"] = {"export": True}
        spec, suggestions = service.draft_from_payload({"module": module, "suggestions": []})

        assert spec.link_fields == []
        assert spec.features.model_dump() == {"status": None, "due": None, "export": False, "comments": False}
        assert "CONTRACT_REQUIRED" not in {r.code for r in spec.rules}
        assert spec.schema_version == 2
        # Still the assistant's idea, offered for a person to tick.
        assert [s.id for s in suggestions] == ["link:contract"]
        assert suggestions[0].patch.field.label == "Contract"

    def test_the_bare_module_an_older_prompt_returned_still_drafts(self) -> None:
        spec, suggestions = service.draft_from_payload(self._module())
        assert spec.key == a_spec().key
        assert suggestions == []

    def test_patches_are_built_by_the_server_and_bad_ones_dropped(self) -> None:
        raw = [
            {
                "kind": "feature",
                "feature": "status",
                "states": [{"code": "x"}],
                "confidence": "high",
                "reason": "Tracks it.",
            },
            {"kind": "feature", "feature": "due", "due_field": "reference", "confidence": "high"},
            {"kind": "feature", "feature": "due", "due_field": "off_hire_date", "confidence": "certain"},
            {"kind": "feature", "feature": "export", "confidence": "low", "reason": "x" * 500},
            {"kind": "feature", "feature": "export", "confidence": "high"},
            {"kind": "link", "target": "invoice"},
            {"kind": "link", "target": "user", "field_label": "Site manager", "reason": "Who\nsigns\x00 it."},
            {"kind": "sql", "feature": "drop"},
        ]
        module = self._module()
        module["entity"]["fields"] = [f for f in module["entity"]["fields"] if f["name"] != "status"]
        module["rules"] = [r for r in module["rules"] if r["field"] != "status"]
        _spec, suggestions = service.draft_from_payload({"module": module, "suggestions": raw})
        by_id = {s.id: s for s in suggestions}

        assert list(by_id) == ["feature:status", "feature:due", "feature:export", "link:user"]
        # Invalid states fall back to the defaults rather than reaching the spec.
        assert [s.code for s in by_id["feature:status"].patch.status.states] == ["open", "in_progress", "done"]
        assert by_id["feature:due"].patch.due.field == "off_hire_date"
        assert by_id["feature:due"].confidence == "low"
        assert len(by_id["feature:export"].reason) <= service.MAX_REASON
        assert by_id["link:user"].reason == "Who signs it."
        assert by_id["link:user"].patch.field.model_dump(include={"type", "target", "label"}) == {
            "type": "link",
            "target": "user",
            "label": "Site manager",
        }


# ── rule-based suggestions ──────────────────────────────────────────────────

# (language, a contract field label, a deadline label, a responsible-person label)
LABELS = [
    ("en", "Contract", "Due date", "Responsible"),
    ("de", "Vertrag", "Abgabefrist", "Verantwortlich"),
    ("fr", "Contrat", "Échéance", "Responsable"),
    ("es", "Contrato", "Fecha límite", "Responsable"),
    ("it", "Contratto", "Scadenza", "Responsabile"),
    ("pt", "Contrato", "Prazo", "Responsável"),
    ("nl", "Overeenkomst", "Vervaldatum", "Verantwoordelijke"),
    ("pl", "Umowa", "Termin", "Odpowiedzialny"),
    ("ru", "Договор", "Срок", "Ответственный"),
    ("uk", "Договір", "Термін", "Відповідальний"),
    ("tr", "Sözleşme", "Son tarih", "Sorumlu"),
    ("zh", "合同", "截止日期", "负责人"),
    ("ja", "契約", "期限", "担当者"),
]


def _register(*fields: FieldSpec, scoped: bool = True, name: str = "Register") -> ModuleSpec:
    rule_field = fields[0].name
    return ModuleSpec(
        key="field_register",
        display_name=name,
        schema_version=2,
        entity=EntitySpec(name="entry", display_name="Entry", project_scoped=scoped, fields=list(fields)),
        rules=[RuleSpec(code="FIRST_REQUIRED", message="Fill it in.", kind="required", field=rule_field)],
    )


def _apply(spec: ModuleSpec, suggestion: Suggestion) -> ModuleSpec:
    """What ticking the suggestion does to the spec, as the wizard does it."""
    payload = spec.model_dump(mode="json")
    patch = suggestion.patch
    if patch.field is not None:
        fields = [f for f in payload["entity"]["fields"] if f["name"] != patch.field.name]
        payload["entity"]["fields"] = [*fields, patch.field.model_dump(mode="json")]
    for name in ("status", "due"):
        value = getattr(patch, name)
        if value is not None:
            payload["features"][name] = value.model_dump(mode="json")
    for name in ("export", "comments"):
        if getattr(patch, name):
            payload["features"][name] = True
    return ModuleSpec.model_validate(payload)


class TestTheSuggesterReadsEveryShippedLanguage:
    @pytest.mark.parametrize(("lang", "contract", "due", "person"), LABELS, ids=[row[0] for row in LABELS])
    @pytest.mark.parametrize("case", ["as_written", "upper"])
    def test_links_and_the_deadline_are_found(self, lang: str, contract: str, due: str, person: str, case: str) -> None:
        shape = str.upper if case == "upper" else str
        spec = _register(
            FieldSpec(name="party", label=shape(contract), type="text"),
            FieldSpec(name="when_due", label=shape(due), type="date"),
            FieldSpec(name="person", label=shape(person), type="text"),
        )
        found = {s.id: s for s in suggest.suggest(spec, lang)}

        assert found["link:contract"].patch.field.name == "party"
        assert found["link:contract"].reason_code == "link_field_name"
        assert found["link:contract"].reason_params == {"field": shape(contract)}
        assert found["link:user"].patch.field.name == "person"
        assert found["feature:due"].patch.due.field == "when_due"
        assert found["feature:due"].reason_params == {"field": shape(due)}

    def test_a_capital_dotted_i_does_not_split_a_turkish_word(self) -> None:
        spec = _register(FieldSpec(name="party", label="İLETİŞİM", type="text"))
        assert "link:contact" in {s.id for s in suggest.suggest(spec, "tr")}

    @pytest.mark.parametrize("lang", suggest.LANGUAGES)
    def test_a_suggested_status_and_link_are_labelled_in_the_reader_language(self, lang: str) -> None:
        spec = _register(FieldSpec(name="title", label="Title", type="text"), name="Contract changes")
        found = {s.id: s for s in suggest.suggest(spec, lang)}
        labels = [s.label for s in found["feature:status"].patch.status.states]
        assert labels == list(suggest.STATE_LABELS[lang])
        assert [s.done for s in found["feature:status"].patch.status.states] == [False, False, True]
        assert found["link:contract"].reason_code == "link_module_name"
        assert found["link:contract"].patch.field.label == suggest.LINK_LABELS["contract"][lang]

    def test_every_table_covers_every_language(self) -> None:
        for concept, table in suggest.KEYWORDS.items():
            assert set(table) == set(suggest.LANGUAGES), concept
        for target in get_args(LinkTarget):
            assert set(suggest.LINK_LABELS[target]) == set(suggest.LANGUAGES), target
        assert set(suggest.STATE_LABELS) == set(suggest.LANGUAGES)
        assert set(suggest.KEYWORDS) == set(get_args(LinkTarget)) | {"due"}


class TestTheSuggesterDoesNotGuessWild:
    def test_a_subcontractor_is_not_a_contract(self) -> None:
        spec = _register(FieldSpec(name="sub", label="Subcontractor", type="text"))
        ids = {s.id for s in suggest.suggest(spec, "en")}
        assert "link:contract" not in ids
        assert "link:contact" in ids

    def test_a_contractor_is_not_a_contract(self) -> None:
        spec = _register(FieldSpec(name="contractor", label="Contractor", type="text"))
        assert "link:contract" not in {s.id for s in suggest.suggest(spec, "en")}

    def test_a_pour_date_is_not_a_deadline(self) -> None:
        spec = _register(
            FieldSpec(name="title", label="Title", type="text"),
            FieldSpec(name="poured", label="Date poured", type="date"),
        )
        assert "feature:due" not in {s.id for s in suggest.suggest(spec, "en")}

    def test_a_contract_date_is_not_a_link(self) -> None:
        spec = _register(FieldSpec(name="signed", label="Contract signed", type="date"))
        assert "link:contract" not in {s.id for s in suggest.suggest(spec, "en")}

    def test_a_record_with_no_project_gets_no_deadline_or_comments(self) -> None:
        spec = _register(
            FieldSpec(name="title", label="Title", type="text"),
            FieldSpec(name="deadline", label="Deadline", type="date"),
            scoped=False,
        )
        ids = {s.id for s in suggest.suggest(spec, "en")}
        assert "feature:due" not in ids
        assert "feature:comments" not in ids
        assert {"feature:status", "feature:export"} <= ids

    def test_one_field_is_not_turned_into_two_links(self) -> None:
        spec = _register(FieldSpec(name="doc", label="Contract document", type="text"))
        replacing = [s for s in suggest.suggest(spec, "en") if s.reason_code == "link_field_name"]
        assert len(replacing) == 1

    def test_what_the_spec_already_has_is_not_suggested_again(self) -> None:
        spec = featured_spec()
        ids = {s.id for s in suggest.suggest(spec, "en")}
        assert ids.isdisjoint({"link:contract", "link:user", "feature:status", "feature:due", "feature:export"})

    def test_a_target_switched_off_here_is_not_suggested(self) -> None:
        spec = _register(FieldSpec(name="party", label="Contract", type="text"))
        ids = {s.id for s in suggest.suggest(spec, "en", available=lambda target: target != "contract")}
        assert "link:contract" not in ids


class TestEverySuggestionIsSafeToTick:
    @pytest.mark.parametrize("lang", ["en", "de", "ru", "ja"])
    def test_each_one_applied_alone_and_all_together_still_validate(self, lang: str) -> None:
        spec = _register(
            FieldSpec(name="party", label={r[0]: r[1] for r in LABELS}[lang], type="text", required=True),
            FieldSpec(name="when_due", label={r[0]: r[2] for r in LABELS}[lang], type="date"),
            name="Document register",
        )
        suggestions = suggest.suggest(spec, lang)
        assert len(suggestions) >= 5
        everything = spec
        for suggestion in suggestions:
            _apply(spec, suggestion)
            everything = _apply(everything, suggestion)
        assert everything.features.export and everything.features.comments

    def test_the_same_spec_gives_the_same_suggestions(self) -> None:
        spec = a_spec()
        first = [s.model_dump() for s in suggest.suggest(spec, "de")]
        assert first == [s.model_dump() for s in suggest.suggest(spec, "de")]

    def test_only_the_agreed_reason_codes_are_used(self) -> None:
        agreed = {
            "link_field_name",
            "link_module_name",
            "due_date_field",
            "status_register",
            "export_register",
            "comments_register",
        }
        spec = _register(
            FieldSpec(name="party", label="Contract", type="text"),
            FieldSpec(name="deadline", label="Deadline", type="date"),
            name="Document register",
        )
        assert {s.reason_code for s in suggest.suggest(spec, "en")} <= agreed

    def test_unset_parts_are_left_out_of_the_json(self) -> None:
        (status,) = [s for s in suggest.suggest(a_minimal_spec(), "en") if s.id == "feature:status"]
        dumped = status.model_dump(mode="json")
        assert "target" not in dumped and "reason" not in dumped
        assert set(dumped["patch"]) == {"status"}


# ── link targets ────────────────────────────────────────────────────────────


class TestEveryLinkTargetPointsAtSomethingReal:
    """A wrong module name reads as "switched off" forever, and nothing says why."""

    @pytest.mark.parametrize("target", list(links.LINK_TARGETS))
    def test_module_table_and_permission_match_the_owning_module(self, target: str) -> None:
        from app.core.permissions import permission_registry

        definition = links.LINK_TARGETS[target]
        package = definition.models.rsplit(".", 1)[0]
        manifest = importlib.import_module(f"{package}.manifest").manifest
        assert manifest.name == definition.module

        model = getattr(importlib.import_module(definition.models), definition.model)
        assert model.__tablename__ == definition.table

        # People are reached through the projects they share, so the user
        # target is gated by the projects module's read permission.
        owner = "app.modules.projects" if target == "user" else package
        permissions = importlib.import_module(f"{owner}.permissions")
        for name in dir(permissions):
            if name.startswith("register_") and callable(getattr(permissions, name)):
                getattr(permissions, name)()
        assert permission_registry.has(definition.permission), f"{definition.permission} is never registered"

    def test_every_target_in_the_spec_is_defined(self) -> None:
        assert set(links.LINK_TARGETS) == set(get_args(LinkTarget))

    def test_an_editor_may_pick_people_without_the_user_directory(self) -> None:
        """Decided: who may be picked is the people the caller shares a project with.

        So the gate is projects.read, not users.list; the narrowing to shared
        projects happens in the query and is pinned by the PG tests.
        """
        from app.modules.projects.permissions import register_project_permissions

        register_project_permissions()
        assert links.LINK_TARGETS["user"].permission == "projects.read"
        editor = links.Caller(user_id=uuid.uuid4(), role="editor")
        viewer = links.Caller(user_id=uuid.uuid4(), role="viewer")
        assert links.may_read(editor, "user")
        assert links.may_read(viewer, "user")


class TestTheWizardLanguagesAreAccepted:
    def test_every_shipped_locale_code_passes_the_request_pattern(self) -> None:
        source = (REPO_ROOT / "frontend" / "src" / "app" / "i18n.ts").read_text(encoding="utf-8")
        block = source[source.index("export const SUPPORTED_LANGUAGES") :]
        block = block[: block.index("];")]
        codes = re.findall(r"code: '([^']+)'", block)
        assert len(codes) > 20, "the language list was not found, so this proves nothing"
        pattern = re.compile(LOCALE_PATTERN)
        assert [c for c in codes if not pattern.match(c)] == []


# ── comments and deadlines ──────────────────────────────────────────────────


class TestCommentsOnBuiltRecords:
    @pytest.mark.parametrize("entity_type", ["built.pour_log", "built.site_diary"])
    def test_the_shape_is_accepted(self, entity_type: str) -> None:
        from app.modules.collaboration.router import _validate_entity_type

        _validate_entity_type(entity_type)

    @pytest.mark.parametrize("entity_type", ["built.", "built.Pour", "built.pour-log", "built.a.b", "unicorn", "built"])
    def test_anything_else_is_400(self, entity_type: str) -> None:
        from app.modules.collaboration.router import _validate_entity_type

        with pytest.raises(HTTPException) as caught:
            _validate_entity_type(entity_type)
        assert caught.value.status_code == 400

    @pytest.mark.asyncio
    async def test_a_key_that_is_not_a_loaded_built_module_resolves_to_nothing(self) -> None:
        from app.modules.collaboration.router import _resolve_entity_project_id

        assert await _resolve_entity_project_id("built.never_installed", str(uuid.uuid4()), None) is None


class TestBuiltModuleDeadlines:
    def _item(self, **overrides: Any):
        from app.modules.deadlines.schemas import DeadlineItem

        values: dict[str, Any] = {
            "id": "built.pour_log:1",
            "module": "built_modules",
            "entity_type": "built.pour_log",
            "entity_id": "1",
            "project_id": "p",
            "title": "P-1",
            "due_date": "2026-10-08",
            "status": "open",
            "classification": "approaching",
            "days_overdue": -3,
            "severity": "warning",
            "action_url": "/projects/p/modules/pour_log",
            "source_label": "Pour Log",
            "remind_days": 2,
        }
        return DeadlineItem(**{**values, **overrides})

    def test_each_record_is_reminded_inside_its_own_module_window(self) -> None:
        from app.modules.deadlines import sweeper

        assert not sweeper._inside_own_window(self._item(days_overdue=-3))
        assert sweeper._inside_own_window(self._item(days_overdue=-2))
        assert sweeper._inside_own_window(self._item(remind_days=None, days_overdue=-30))
        assert sweeper.APPROACHING_NOTIFY["built_modules"] == 30

    def test_the_notification_names_the_module_the_person_built(self) -> None:
        from app.modules.deadlines import sweeper
        from app.modules.notifications.templates import render

        item = self._item()
        title_key, body_key = sweeper._approaching_keys(item)
        assert body_key == "notifications.deadline.built.approaching.body"
        body = render(body_key, sweeper._approaching_context(item))
        assert body == 'Pour Log: "P-1" is due on 2026-10-08.'
        assert sweeper._overdue_context(self._item(classification="overdue"))["module"] == "Pour Log"
        assert sweeper._approaching_keys(self._item(module="rfi"))[0] == "notifications.deadline.approaching.title"

    def test_both_events_are_in_the_preference_catalogue(self) -> None:
        from app.modules.notifications.service import KNOWN_EVENT_TYPES

        etypes = {e["event_type"] for e in KNOWN_EVENT_TYPES}
        assert {"deadlines.built_modules.overdue", "deadlines.built_modules.approaching"} <= etypes
