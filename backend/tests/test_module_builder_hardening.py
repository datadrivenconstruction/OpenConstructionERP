# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module builder v2, where a review found it broke, without a database.

- A name is user text in any language, and quotes and backslashes in it ended
  the docstring or string literal it was rendered into, putting code in the
  module. Every rendered file is checked against hostile names for exactly
  the statements an ordinary name gives.
- An export put an apostrophe in front of negative numbers, and a workbook
  failed on a control character pasted from a word processor.
- A suggestion could leave a spec the server refuses: a link name whose index
  is past PostgreSQL's limit, or more fields than a register may hold once
  every suggestion was ticked.

The database side of the same review is in
``tests/pg/test_module_builder_v2_hardening.py``.
"""

from __future__ import annotations

import ast
import asyncio
import json
import warnings
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args, get_origin

import pytest
from pydantic import ValidationError

from app.modules.module_builder import export, generator, refresh, suggest
from app.modules.module_builder.spec import (
    MAX_FIELDS,
    MAX_IDENTIFIER_BYTES,
    EntitySpec,
    FieldSpec,
    ModuleSpec,
    RuleSpec,
    StateSpec,
)

NOW = datetime(2026, 10, 5, tzinfo=UTC)


# ── names in generated code ─────────────────────────────────────────────────

# Every str a person or the assistant writes freely. Identifiers, codes and
# version numbers are validated to a shape that carries no quotes, so they are
# not here; a new free-text field must be added, or the test below says so.
FREE_TEXT = {
    ModuleSpec: {"display_name", "description", "icon", "author"},
    EntitySpec: {"display_name", "plural_name"},
    FieldSpec: {"label", "help_text", "unit", "options"},
    RuleSpec: {"message"},
    StateSpec: {"label"},
}
STRUCTURED = {
    ModuleSpec: {"key", "version"},
    EntitySpec: {"name"},
    FieldSpec: {"name"},
    RuleSpec: {"code", "field", "other_field"},
    StateSpec: {"code"},
}

# Text that ends a string or starts an escape, at the start, the end, or alone.
HOSTILE = [
    '"',
    '""',
    '"""',
    '""""',
    "'''",
    "\\",
    "x\\",
    "\\N{",
    "\\x",
    "\\u",
    "\\'",
    '\\"',
    "{",
    "}",
    '{__import__("os").getcwd()}',
    'Pours", include_in_schema=__import__("os").getcwd() and False, name="x',
    'Pours""" + __import__("os").getcwd() + """',
    "Bétonnage « coulé » 混凝土 ​",
]
# Never meant in a name; refused there, and escaped in a description.
CONTROL = ["\x00", "\x07", "\x0b", "\x1f", "\x7f", "\x85", " ", " "]


def _text_spec(text: str, description: str | None = None) -> ModuleSpec:
    """Every free-text field set to ``text``, on a spec with every feature and field kind."""
    label = text if text.strip() else "x"
    return ModuleSpec.model_validate(
        {
            "key": "hostile_log",
            "display_name": label,
            "description": text if description is None else description,
            "icon": text,
            "author": text,
            "schema_version": 2,
            "entity": {
                "name": "entry",
                "display_name": label,
                "plural_name": label,
                "fields": [
                    {"name": "reference", "label": label, "type": "text", "required": True, "help_text": text},
                    {"name": "amount", "label": f"{label} 2", "type": "money", "unit": text},
                    {"name": "kind", "label": f"{label} 3", "type": "select", "options": [f"a{text}", f"{text}b"]},
                    {"name": "due_on", "label": f"{label} 4", "type": "date"},
                    {"name": "contract", "label": f"{label} 5", "type": "link", "target": "contract"},
                ],
            },
            "rules": [
                {"code": "REFERENCE_REQUIRED", "message": f"Fill {text}", "kind": "required", "field": "reference"},
                {"code": "KIND_KNOWN", "message": f"{text} pick one", "kind": "required", "field": "kind"},
            ],
            "features": {
                "status": {"states": [{"code": "open", "label": label}, {"code": "shut", "label": f"{label}!"}]},
                "due": {"field": "due_on"},
                "export": True,
                "comments": True,
            },
        }
    )


def _shape(source: str, path: str) -> str:
    """The module's syntax tree with every string emptied: what the code does, not what it says."""
    with warnings.catch_warnings():
        # An invalid escape is only a warning today and an error tomorrow.
        warnings.simplefilter("error")
        compile(source, path, "exec")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            node.value = ""
    return ast.dump(tree, include_attributes=False)


def _python(spec: ModuleSpec) -> dict[str, str]:
    return {f.path: f.content for f in generator.render(spec) if f.path.endswith(".py")}


class TestNamesNeverBecomeCode:
    def test_the_free_text_fields_are_the_ones_listed(self) -> None:
        """A new text field on the spec has to be added to FREE_TEXT, or this property proves less than it says."""
        for model, free in FREE_TEXT.items():
            texts = set()
            for name, info in model.model_fields.items():
                annotation = info.annotation
                if annotation is str or (get_origin(annotation) is list and get_args(annotation) == (str,)):
                    texts.add(name)
            assert texts == free | STRUCTURED[model], model.__name__

    @pytest.mark.parametrize("text", HOSTILE, ids=repr)
    @pytest.mark.parametrize("where", ["alone", "first", "last"])
    def test_every_file_does_what_an_ordinary_name_does(self, text: str, where: str) -> None:
        placed = {"alone": text, "first": f"{text} log", "last": f"Log {text}"}[where]
        hostile = _python(_text_spec(placed))
        plain = _python(_text_spec("Plain"))
        assert set(hostile) == set(plain)
        for path, source in hostile.items():
            assert _shape(source, path) == _shape(plain[path], path), f"{path} holds different code"

    @pytest.mark.parametrize("text", HOSTILE, ids=repr)
    def test_names_come_back_exactly_as_written(self, text: str) -> None:
        """Escaping that changed the name would be safe and wrong."""
        placed = f"Log {text}"
        spec = _text_spec(placed)
        files = {f.path: f.content for f in generator.render(spec)}

        manifest = ast.parse(files["manifest.py"])
        call = next(
            n for n in ast.walk(manifest) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "ModuleManifest"
        )
        values = {k.arg: ast.literal_eval(k.value) for k in call.keywords if k.arg in {"display_name", "description"}}
        assert values == {"display_name": placed.strip(), "description": placed}

        init = ast.get_docstring(ast.parse(files["__init__.py"]), clean=False)
        assert init.startswith(f"{placed.strip()}.\n\n{placed}\n")

        router = ast.parse(files["router.py"])
        summaries = {
            ast.literal_eval(k.value)
            for n in ast.walk(router)
            if isinstance(n, ast.Call)
            for k in n.keywords
            if k.arg == "summary"
        }
        assert f"List {placed.strip().lower()}" in summaries

        stored = json.loads(files["spec.json"])
        stored.pop("generator")
        stored.pop("generated_at")
        assert ModuleSpec.model_validate(stored) == spec
        assert json.loads(files["locales/en.json"])  # parses

    @pytest.mark.parametrize("char", CONTROL, ids=repr)
    def test_a_description_with_a_control_character_still_renders_safely(self, char: str) -> None:
        text = f"First line{char}second"
        hostile = _python(_text_spec("Plain", description=text))
        plain = _python(_text_spec("Plain"))
        for path, source in hostile.items():
            assert _shape(source, path) == _shape(plain[path], path), f"{path} holds different code"
        init = ast.get_docstring(ast.parse(hostile["__init__.py"]), clean=False)
        assert text in init

    def test_ordinary_names_render_byte_for_byte_as_before(self) -> None:
        """What lets a refresh rewrite the code of a module installed under stamp 2."""
        for text in ["Pour Log", "Bétonnage", "混凝土浇筑", "Журнал бетонирования", "Pour 'A' log", 'Pour "A" log']:
            assert generator._doc(text) == text
        for text in ["List pours", "Bétonnage", "混凝土浇筑"]:
            assert generator._lit(text) == f'"{text}"'


class TestTheSpecRefusesWhatNoNameNeeds:
    @pytest.mark.parametrize("char", CONTROL, ids=repr)
    @pytest.mark.parametrize("where", ["display_name", "entity", "plural", "label", "state", "option", "unit"])
    def test_control_characters_in_a_name(self, char: str, where: str) -> None:
        data = _text_spec("Plain").model_dump(mode="json")
        bad = f"Pour{char}log"
        if where == "display_name":
            data["display_name"] = bad
        elif where == "entity":
            data["entity"]["display_name"] = bad
        elif where == "plural":
            data["entity"]["plural_name"] = bad
        elif where == "label":
            data["entity"]["fields"][0]["label"] = bad
        elif where == "state":
            data["features"]["status"]["states"][0]["label"] = bad
        elif where == "option":
            data["entity"]["fields"][2]["options"][0] = bad
        else:
            data["entity"]["fields"][1]["unit"] = bad
        with pytest.raises(ValidationError, match="control character"):
            ModuleSpec.model_validate(data)

    def test_a_lone_surrogate_anywhere(self) -> None:
        data = _text_spec("Plain").model_dump(mode="json")
        data["description"] = "Half a pair \ud800 here"
        with pytest.raises(ValidationError, match="cannot be stored"):
            ModuleSpec.model_validate(data)

    def test_quotes_and_scripts_are_fine(self) -> None:
        assert _text_spec('Pour "A" \\ log 混凝土').display_name == 'Pour "A" \\ log 混凝土'


class TestAnOldInstallIsRenderedAgainEscaped:
    def test_the_stamp_moved_to_three(self) -> None:
        assert generator.GENERATOR_STAMP == "openconstructionerp.module_builder/3"

    def test_a_router_with_a_name_that_was_code_is_rewritten(self, tmp_path: Path) -> None:
        """A /2 install whose plural name ended the summary string: the refresh takes the code out."""
        plural = 'Pours", include_in_schema=__import__("os").getcwd() and False, name="x'
        data = _text_spec("Plain").model_dump(mode="json")
        data["entity"]["plural_name"] = plural
        spec = ModuleSpec.model_validate(data)
        generator.write(spec, tmp_path)
        target = tmp_path / spec.key
        current = (target / "router.py").read_text(encoding="utf-8")

        # As generator 2 wrote it: the name straight into the literal.
        escaped = generator._lit(f"List {plural.lower()}")
        old = current.replace(escaped, f'"List {plural.lower()}"')
        assert old != current
        calls = [n for n in ast.walk(ast.parse(old)) if isinstance(n, ast.Call)]
        assert any(getattr(c.func, "id", "") == "__import__" for c in calls), "the fixture is not an injection"
        (target / "router.py").write_text(old, encoding="utf-8", newline="\n")
        payload = json.loads((target / "spec.json").read_text(encoding="utf-8"))
        payload["generator"] = "openconstructionerp.module_builder/2"
        (target / "spec.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        assert refresh.refresh_installed(tmp_path) == {spec.key: refresh.REFRESHED}
        assert (target / "router.py").read_text(encoding="utf-8") == current
        calls = [n for n in ast.walk(ast.parse(current)) if isinstance(n, ast.Call)]
        assert not any(getattr(c.func, "id", "") == "__import__" for c in calls)


# ── export cells ────────────────────────────────────────────────────────────


def _unscoped_money_spec() -> dict:
    return {
        "key": "rv_costs",
        "entity": {
            "name": "cost",
            "project_scoped": False,
            "fields": [
                {"name": "ref", "label": "Ref", "type": "text"},
                {"name": "amount", "label": "Amount", "type": "money"},
                {"name": "count", "label": "Count", "type": "integer"},
                {"name": "qty", "label": "Qty", "type": "number"},
            ],
        },
    }


def _export(row: SimpleNamespace, *, native: bool) -> dict[str, Any]:
    header, table = asyncio.run(export.rows_for_export(None, None, _unscoped_money_spec(), [row], native=native))
    return dict(zip(header, table[0], strict=True))


class TestCsvNumbers:
    def test_negative_numbers_survive_csv_export(self) -> None:
        row = SimpleNamespace(
            ref="credit note", amount=Decimal("-5.00"), count=-3, qty=-1.5, created_at=NOW, updated_at=NOW
        )
        cells = _export(row, native=False)
        assert cells["Amount"] == "-5.00", cells
        assert cells["Count"] == "-3", cells
        assert cells["Qty"] == "-1.5", cells

    def test_text_that_looks_like_a_number_is_still_neutralised(self) -> None:
        """The control: typed text starting with a minus can still be a formula."""
        row = SimpleNamespace(ref="-5+cmd", amount=None, count=None, qty=None, created_at=NOW, updated_at=NOW)
        assert _export(row, native=False)["Ref"] == "'-5+cmd"


class TestXlsxControlCharacters:
    def test_a_vertical_tab_in_a_value_does_not_break_the_workbook(self) -> None:
        content = export._xlsx(["Reference"], [["Line one\x0bline two"]], title="rv")
        assert content[:2] == b"PK"

    def test_the_value_keeps_its_visible_text(self) -> None:
        row = SimpleNamespace(
            ref="Pour A\x0bLevel 2", amount=None, count=None, qty=None, created_at=NOW, updated_at=NOW
        )
        cells = _export(row, native=True)
        assert cells["Ref"] == "Pour ALevel 2"
        export._xlsx(list(cells), [list(cells.values())], title="rv")

    def test_a_dropped_control_character_does_not_uncover_a_formula(self) -> None:
        row = SimpleNamespace(
            ref="\x0b=HYPERLINK(1)", amount=None, count=None, qty=None, created_at=NOW, updated_at=NOW
        )
        assert _export(row, native=True)["Ref"] == "'=HYPERLINK(1)"

    def test_the_list_is_openpyxls_own(self) -> None:
        from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

        assert export._NOT_IN_A_WORKBOOK.pattern == ILLEGAL_CHARACTERS_RE.pattern


# ── suggestions ─────────────────────────────────────────────────────────────


def _base(key: str, entity: str, fields: list[dict], display: str = "Register", description: str = "") -> ModuleSpec:
    return ModuleSpec.model_validate(
        {
            "key": key,
            "display_name": display,
            "description": description,
            "schema_version": 2,
            "entity": {"name": entity, "display_name": "Item", "project_scoped": True, "fields": fields},
            "rules": [
                {"code": "FIRST_REQUIRED", "message": "Fill it in.", "kind": "required", "field": fields[0]["name"]}
            ],
            "features": {},
        }
    )


def _valid(data: dict) -> str | None:
    try:
        ModuleSpec.model_validate(data)
    except ValidationError as exc:
        return exc.errors()[0]["msg"]
    return None


class TestEverySuggestionIsSafeToTick:
    def test_a_field_turned_into_a_link_keeps_the_spec_valid(self) -> None:
        spec = _base(
            "material_deliveries_register",
            "delivery",
            [
                {"name": "delivery_note", "label": "Delivery note", "type": "text"},
                {"name": "supplier_contract_number", "label": "Supplier contract number", "type": "text"},
            ],
        )
        found = [s for s in suggest.suggest(spec, "en") if s.kind == "link"]
        # The same suggestion as before the fix, with a name that fits beside the text field.
        assert [(s.id, s.reason_code, s.patch.field.name) for s in found] == [
            ("link:contract", "link_field_name", "supplier_contract")
        ]
        assert _valid(suggest.apply_patches(spec, found)) is None

    def test_a_short_name_converts_in_place(self) -> None:
        spec = _base("deliveries", "delivery", [{"name": "contract", "label": "Contract", "type": "text"}])
        (link,) = [s for s in suggest.suggest(spec, "en") if s.kind == "link"]
        assert link.patch.field.name == "contract"
        assert len(suggest.apply_patches(spec, [link])["entity"]["fields"]) == 1

    def test_a_link_from_the_module_name_keeps_a_long_spec_valid(self) -> None:
        spec = _base(
            "subcontract_works_contract_register_xyz",
            "work_item",
            [{"name": "title", "label": "Title", "type": "text"}],
            display="Contract register",
        )
        assert len(spec.table_name) == 52
        found = [s for s in suggest.suggest(spec, "en") if s.kind == "link"]
        assert [s.id for s in found] == ["link:contract"]
        for s in found:
            name = s.patch.field.name
            assert len(f"ix_{spec.table_name}_{name}".encode()) <= MAX_IDENTIFIER_BYTES
            assert _valid(suggest.apply_patches(spec, [s])) is None

    def test_accept_all_keeps_the_field_count_valid(self) -> None:
        fields = [{"name": f"item_{i:02d}", "label": f"Item {i}", "type": "text"} for i in range(MAX_FIELDS - 2)]
        spec = _base(
            "site_paperwork",
            "paper",
            fields,
            display="Contract documents and activities",
            description="Who is responsible for each contract document and schedule activity, with the contact.",
        )
        found = suggest.suggest(spec, "en")
        links = [s for s in found if s.kind == "link"]
        # Two places left. Named by the module name (medium) outranks named only
        # in its description (low); among equals, the earlier target stays.
        assert [s.id for s in links] == ["link:contract", "link:schedule_activity"]
        assert {s.confidence for s in links} == {"medium"}
        for s in found:
            assert _valid(suggest.apply_patches(spec, [s])) is None, s.id
        everything = suggest.apply_patches(spec, found)
        assert len(everything["entity"]["fields"]) == MAX_FIELDS
        assert _valid(everything) is None

    def test_shortened_names_never_collide(self) -> None:
        taken = {"contract"}
        first = suggest.fitting_name("contract", 7, taken)
        second = suggest.fitting_name("contact", 7, taken | {first})
        assert first == "contrac"
        assert second not in {first, "contract"} and len(second) <= 7

    def test_shortening_is_deterministic_and_word_first(self) -> None:
        assert suggest.fitting_name("supplier_contract_number", 19, set()) == "supplier_contract"
        assert suggest.fitting_name("supplier_contract_number", 19, {"supplier_contract"}) == "supplier_contract_2"
        assert suggest.fitting_name("contract", 0, set()) is None

    def test_no_status_when_its_index_would_not_fit(self) -> None:
        """Only a spec in the first layout can get here; the current one already refuses the table."""
        data = _base("a" * 40, "b", [{"name": "title", "label": "Title", "type": "text"}]).model_dump(mode="json")
        data["schema_version"] = 1
        data["entity"]["name"] = "b" * 11
        spec = ModuleSpec.model_validate(data)
        assert len(f"ix_{spec.table_name}_status") > MAX_IDENTIFIER_BYTES
        assert "feature:status" not in {s.id for s in suggest.suggest(spec, "en")}
