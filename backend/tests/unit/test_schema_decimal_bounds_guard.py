"""Guard: request-schema Decimal fields must be finite and bounded.

A bare ``Decimal`` accepts NaN/Infinity/1e400 and overflows its NUMERIC column (500 instead
of 422). Use the types from ``app.core.decimal_types``. Response-shaped classes (name ends
in Response/Read/Out/Summary/...) and classes deriving from them are exempt, as are the
entries of ``ALLOWED`` ("module.Class.field" -> reason).
"""

import ast
import re
from pathlib import Path

MODULES = Path(__file__).resolve().parents[2] / "app" / "modules"
RESPONSE = re.compile(r"(Response|Read|Out|Summary|Detail|View|Result|Stats|Report|Snapshot|DTO)$")
CORE_NAMES = re.compile(r"^(FiniteDecimal|Decimal\d+_\d+)$")

ALLOWED: dict[str, str] = {}


def _call_name(node: ast.AST) -> str:
    return getattr(node, "id", getattr(node, "attr", ""))


def _unbounded() -> list[str]:
    found: list[str] = []
    for path in sorted(MODULES.glob("*/schemas.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skipped: set[str] = set()
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            bases = {_call_name(b) for b in cls.bases}
            if RESPONSE.search(cls.name) or bases & skipped or any(RESPONSE.search(b) for b in bases):
                skipped.add(cls.name)
                continue
            for stmt in cls.body:
                if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                    continue
                names = {n.id for n in ast.walk(stmt.annotation) if isinstance(n, ast.Name)}
                if "Decimal" not in names or any(CORE_NAMES.match(n) for n in names):
                    continue
                kw: set[str] = set()
                if isinstance(stmt.value, ast.Call) and _call_name(stmt.value.func) == "Field":
                    kw = {k.arg for k in stmt.value.keywords if k.arg}
                if "max_digits" in kw or ("allow_inf_nan" in kw and kw & {"le", "lt"}):
                    continue
                key = f"{path.parent.name}.{cls.name}.{stmt.target.id}"
                if key not in ALLOWED:
                    found.append(f"{key} (line {stmt.lineno})")
    return found


def test_no_unbounded_decimal_in_request_schemas():
    found = _unbounded()
    assert not found, (
        "Unbounded Decimal fields; annotate with app.core.decimal_types (e.g. Decimal18_2) "
        "or add to ALLOWED with a reason:\n" + "\n".join(found)
    )


SIGNED_NAME = re.compile(r"(variance|delta|adjustment|credit|difference|correction|overrun|balance)")


def test_signed_fields_are_not_constrained_non_negative():
    """Credits, adjustments, variances and deltas may legitimately be negative."""
    found: list[str] = []
    for path in sorted(MODULES.glob("*/schemas.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            for stmt in cls.body:
                if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                    continue
                if not SIGNED_NAME.search(stmt.target.id) or "Decimal" not in ast.unparse(stmt.annotation):
                    continue
                if isinstance(stmt.value, ast.Call):
                    kw = {k.arg: k.value for k in stmt.value.keywords if k.arg}
                    low = [kw[k] for k in ("ge", "gt") if k in kw]
                    if any(isinstance(v, ast.Constant) and v.value == 0 for v in low):
                        found.append(f"{path.parent.name}.{cls.name}.{stmt.target.id}")
    assert not found, "signed-looking Decimal fields constrained >= 0:\n" + "\n".join(found)


def test_real_schema_fields_round_extra_decimals_instead_of_rejecting():
    import importlib

    cases = [
        ("supplier_catalogs", "CatalogEntryCreate", "unit_price", "12.345678", "12.3457"),
        ("geo_hub", "SurveyObservationUpsert", "observed_pct", "55.555", "55.56"),
        ("rebar_schedule", "AbsPreviewShape", "weight_kg", "1.23456", "1.2346"),
    ]
    for mod, cls, field, raw, expected in cases:
        schemas = importlib.import_module(f"app.modules.{mod}.schemas")
        model = getattr(schemas, cls)
        done = model.__pydantic_validator__.validate_assignment(model.model_construct(), field, raw)
        got = getattr(done[0] if isinstance(done, tuple) else done, field)
        assert str(got) == expected, f"{mod}.{cls}.{field}"
