#!/usr/bin/env python3
"""Generate architecture_manifest.json by scanning backend modules and frontend features.

This script uses ONLY the Python standard library (ast, pathlib, re, json, os)
to introspect the codebase and produce a machine-readable manifest that describes:

- Backend modules (from backend/app/modules/)
- SQLAlchemy models with columns, foreign keys, and relationships
- FastAPI routes with HTTP methods, paths, and schema references
- Pydantic schemas with typed fields
- Cross-module import dependency graph
- Frontend feature folder mapping

Usage:
    python scripts/generate_architecture_manifest.py [--root /path/to/repo]

Output:
    frontend/src/features/architecture/architecture_manifest.json
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import textwrap
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _safe_parse(filepath: Path) -> ast.Module | None:
    """Parse a Python file into an AST, returning None on failure."""
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
        return ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError, OSError) as exc:
        print(f"  [WARN] Could not parse {filepath}: {exc}")
        return None


def _unparse_annotation(node: ast.expr | None) -> str:
    """Best-effort conversion of a type annotation AST node to a string."""
    if node is None:
        return "Any"
    try:
        return ast.unparse(node)
    except Exception:
        return "?"


def _extract_string_kwarg(call_node: ast.Call, kwarg_name: str) -> str | None:
    """Extract a string-valued keyword argument from a Call node."""
    for kw in call_node.keywords:
        if kw.arg == kwarg_name and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    return None


def _extract_list_kwarg(call_node: ast.Call, kwarg_name: str) -> list[str]:
    """Extract a list-of-strings keyword argument from a Call node."""
    for kw in call_node.keywords:
        if kw.arg == kwarg_name and isinstance(kw.value, ast.List):
            return [
                elt.value
                for elt in kw.value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            ]
    return []


def _extract_bool_kwarg(call_node: ast.Call, kwarg_name: str) -> bool | None:
    """Extract a bool keyword argument from a Call node."""
    for kw in call_node.keywords:
        if kw.arg == kwarg_name and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, bool):
            return kw.value.value
    return None


# ---------------------------------------------------------------------------
# 1. Module manifest scanning
# ---------------------------------------------------------------------------

def scan_module_manifest(manifest_path: Path) -> dict[str, Any]:
    """Parse a manifest.py and extract ModuleManifest(...) keyword arguments."""
    tree = _safe_parse(manifest_path)
    if tree is None:
        return {}

    result: dict[str, Any] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Match: ModuleManifest(...)
        func = node.func
        name_matches = (
            (isinstance(func, ast.Name) and func.id == "ModuleManifest")
            or (isinstance(func, ast.Attribute) and func.attr == "ModuleManifest")
        )
        if not name_matches:
            continue

        result["name"] = _extract_string_kwarg(node, "name") or ""
        result["version"] = _extract_string_kwarg(node, "version") or ""
        result["display_name"] = _extract_string_kwarg(node, "display_name") or ""
        result["description"] = _extract_string_kwarg(node, "description") or ""
        result["author"] = _extract_string_kwarg(node, "author") or ""
        result["category"] = _extract_string_kwarg(node, "category") or "core"
        result["depends"] = _extract_list_kwarg(node, "depends")
        result["auto_install"] = _extract_bool_kwarg(node, "auto_install")
        result["enabled"] = _extract_bool_kwarg(node, "enabled")
        break

    return result


# ---------------------------------------------------------------------------
# 2. SQLAlchemy model extraction
# ---------------------------------------------------------------------------

def _is_mapped_column_call(node: ast.expr) -> bool:
    """Check if node is a call to mapped_column(...)."""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id == "mapped_column":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "mapped_column":
            return True
    return False


def _extract_column_info(assign_node: ast.AnnAssign) -> dict[str, Any] | None:
    """Extract column metadata from an annotated assignment with mapped_column(...)."""
    if assign_node.value is None or not _is_mapped_column_call(assign_node.value):
        return None
    if not isinstance(assign_node.target, ast.Name):
        return None

    col_name = assign_node.target.id
    call = assign_node.value
    annotation_str = _unparse_annotation(assign_node.annotation)

    # Determine SQL type from positional args (e.g., String(255), Integer, JSON)
    sql_type = None
    for arg in call.args:
        if isinstance(arg, ast.Name):
            sql_type = arg.id
            break
        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
            sql_type = arg.func.id
            break
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            # e.g., mapped_column("metadata", JSON, ...)
            continue
        if isinstance(arg, ast.Attribute):
            sql_type = arg.attr
            break

    # Nullable
    nullable = None
    for kw in call.keywords:
        if kw.arg == "nullable" and isinstance(kw.value, ast.Constant):
            nullable = kw.value.value

    # Foreign key
    fk_target = None
    for arg in call.args:
        if isinstance(arg, ast.Call):
            func = arg.func
            is_fk = (
                (isinstance(func, ast.Name) and func.id == "ForeignKey")
                or (isinstance(func, ast.Attribute) and func.attr == "ForeignKey")
            )
            if is_fk and arg.args and isinstance(arg.args[0], ast.Constant):
                fk_target = arg.args[0].value

    info: dict[str, Any] = {
        "name": col_name,
        "annotation": annotation_str,
    }
    if sql_type:
        info["sql_type"] = sql_type
    if nullable is not None:
        info["nullable"] = nullable
    if fk_target:
        info["is_fk"] = True
        info["fk_target"] = fk_target

    return info


def _extract_relationship_info(assign_node: ast.AnnAssign) -> dict[str, Any] | None:
    """Extract relationship metadata from an annotated assignment with relationship(...)."""
    if assign_node.value is None:
        return None
    if not isinstance(assign_node.value, ast.Call):
        return None

    func = assign_node.value.func
    is_rel = (
        (isinstance(func, ast.Name) and func.id == "relationship")
        or (isinstance(func, ast.Attribute) and func.attr == "relationship")
    )
    if not is_rel:
        return None
    if not isinstance(assign_node.target, ast.Name):
        return None

    rel_name = assign_node.target.id
    annotation_str = _unparse_annotation(assign_node.annotation)

    # Try to extract target model from annotation (e.g., Mapped[list["Position"]])
    target_model = None
    # Pattern: strip Mapped[], list[], Optional[], quotes
    match = re.search(r'"(\w+)"', annotation_str)
    if match:
        target_model = match.group(1)
    elif re.search(r'Mapped\[(\w+)\]', annotation_str):
        target_model = re.search(r'Mapped\[(\w+)\]', annotation_str).group(1)

    # Determine type: list -> one-to-many, single -> many-to-one
    rel_type = "one-to-many" if "list" in annotation_str.lower() else "many-to-one"

    # Check back_populates
    back_populates = _extract_string_kwarg(assign_node.value, "back_populates")

    info: dict[str, Any] = {
        "name": rel_name,
        "type": rel_type,
        "annotation": annotation_str,
    }
    if target_model:
        info["target_model"] = target_model
    if back_populates:
        info["back_populates"] = back_populates

    return info


def scan_models(models_path: Path) -> list[dict[str, Any]]:
    """Parse models.py and extract SQLAlchemy model definitions."""
    tree = _safe_parse(models_path)
    if tree is None:
        return []

    models: list[dict[str, Any]] = []

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Check if it inherits from Base (or similar)
        base_names = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                base_names.append(base.id)
            elif isinstance(base, ast.Attribute):
                base_names.append(base.attr)

        if "Base" not in base_names:
            continue

        model_info: dict[str, Any] = {
            "class_name": node.name,
            "tablename": None,
            "docstring": ast.get_docstring(node) or "",
            "columns": [],
            "relationships": [],
        }

        # Extract __tablename__
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id == "__tablename__":
                        if isinstance(item.value, ast.Constant):
                            model_info["tablename"] = item.value.value

        # Extract columns and relationships
        for item in node.body:
            if not isinstance(item, ast.AnnAssign):
                continue

            col = _extract_column_info(item)
            if col:
                model_info["columns"].append(col)
                continue

            rel = _extract_relationship_info(item)
            if rel:
                model_info["relationships"].append(rel)

        models.append(model_info)

    return models


# ---------------------------------------------------------------------------
# 3. FastAPI route extraction
# ---------------------------------------------------------------------------

_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


def _is_router_decorator(decorator: ast.expr) -> dict[str, Any] | None:
    """If the decorator is router.get("/path", ...) return method+path, else None."""
    if not isinstance(decorator, ast.Call):
        return None
    func = decorator.func
    if not isinstance(func, ast.Attribute):
        return None
    method = func.attr.lower()
    if method not in _HTTP_METHODS:
        return None

    path = None
    if decorator.args and isinstance(decorator.args[0], ast.Constant):
        path = decorator.args[0].value

    # Extract response_model / response schema from keywords
    response_model = None
    for kw in decorator.keywords:
        if kw.arg == "response_model":
            response_model = _unparse_annotation(kw.value)

    return {"method": method.upper(), "path": path or "/", "response_model": response_model}


def scan_routes(router_path: Path) -> list[dict[str, Any]]:
    """Parse router.py and extract FastAPI route definitions."""
    tree = _safe_parse(router_path)
    if tree is None:
        return []

    routes: list[dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        for decorator in node.decorator_list:
            info = _is_router_decorator(decorator)
            if info is None:
                continue

            route_entry: dict[str, Any] = {
                "method": info["method"],
                "path": info["path"],
                "handler": node.name,
            }
            if info.get("response_model"):
                route_entry["response_model"] = info["response_model"]

            # Try to extract request body schema from function parameters
            request_schema = None
            for arg in node.args.args:
                ann = arg.annotation
                if ann is None:
                    continue
                ann_str = _unparse_annotation(ann)
                # Skip dependency-injection params (Session, CurrentUser, etc.)
                if any(skip in ann_str for skip in ["Session", "Depends", "CurrentUser", "UUID", "str", "int", "float", "bool", "Query", "Path"]):
                    continue
                # Likely a Pydantic schema
                request_schema = ann_str
                break

            if request_schema:
                route_entry["request_schema"] = request_schema

            routes.append(route_entry)
            break  # Only first matching decorator per function

    return routes


# ---------------------------------------------------------------------------
# 4. Pydantic schema extraction
# ---------------------------------------------------------------------------

_PYDANTIC_BASES = {"BaseModel", "BaseSchema", "BaseCreate", "BaseUpdate", "BaseResponse"}


def scan_schemas(schemas_path: Path) -> list[dict[str, Any]]:
    """Parse schemas.py and extract Pydantic model definitions."""
    tree = _safe_parse(schemas_path)
    if tree is None:
        return []

    schemas: list[dict[str, Any]] = []

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Check if it inherits from BaseModel or similar
        base_names = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                base_names.append(base.id)
            elif isinstance(base, ast.Attribute):
                base_names.append(base.attr)

        # Accept any class that inherits from a known Pydantic base or from
        # another class (which is likely also a schema in the same file).
        # We'll be liberal: include any class with typed fields.
        is_pydantic = bool(set(base_names) & _PYDANTIC_BASES) or bool(base_names)
        if not is_pydantic:
            continue

        schema_info: dict[str, Any] = {
            "class_name": node.name,
            "bases": base_names,
            "docstring": ast.get_docstring(node) or "",
            "fields": [],
        }

        for item in node.body:
            if not isinstance(item, ast.AnnAssign):
                continue
            if not isinstance(item.target, ast.Name):
                continue
            # Skip model_config and similar class-level config
            if item.target.id.startswith("model_") or item.target.id.startswith("_"):
                continue

            field_info: dict[str, Any] = {
                "name": item.target.id,
                "type": _unparse_annotation(item.annotation),
            }

            # Check for Field(...) default
            if item.value and isinstance(item.value, ast.Call):
                func = item.value.func
                is_field = (
                    (isinstance(func, ast.Name) and func.id == "Field")
                    or (isinstance(func, ast.Attribute) and func.attr == "Field")
                )
                if is_field:
                    desc = _extract_string_kwarg(item.value, "description")
                    if desc:
                        field_info["description"] = desc
            elif item.value and isinstance(item.value, ast.Constant):
                field_info["default"] = repr(item.value.value)

            schema_info["fields"].append(field_info)

        schemas.append(schema_info)

    return schemas


# ---------------------------------------------------------------------------
# 5. Cross-module import dependency graph
# ---------------------------------------------------------------------------

def scan_imports(module_dir: Path, modules_root: Path) -> list[str]:
    """Scan all .py files in a module directory for imports from other modules."""
    # Determine the import prefix for the modules root
    # e.g., "app.modules."
    deps: set[str] = set()
    this_module = module_dir.name

    for py_file in module_dir.rglob("*.py"):
        tree = _safe_parse(py_file)
        if tree is None:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                # Match imports like "from app.modules.projects.models import ..."
                match = re.match(r"app\.modules\.(\w+)", node.module)
                if match:
                    dep_module = match.group(1)
                    if dep_module != this_module:
                        deps.add(dep_module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    match = re.match(r"app\.modules\.(\w+)", alias.name)
                    if match:
                        dep_module = match.group(1)
                        if dep_module != this_module:
                            deps.add(dep_module)

    return sorted(deps)


# ---------------------------------------------------------------------------
# 6. Frontend feature scanning
# ---------------------------------------------------------------------------

def scan_frontend_features(features_dir: Path) -> list[dict[str, Any]]:
    """Scan frontend/src/features/ and list feature directories with file counts."""
    if not features_dir.is_dir():
        return []

    features: list[dict[str, Any]] = []
    for entry in sorted(features_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue

        # Count file types
        ts_files = list(entry.rglob("*.ts")) + list(entry.rglob("*.tsx"))
        css_files = list(entry.rglob("*.css"))
        test_files = [f for f in ts_files if ".test." in f.name or ".spec." in f.name]

        features.append({
            "name": entry.name,
            "ts_files": len(ts_files),
            "css_files": len(css_files),
            "test_files": len(test_files),
            "total_files": len(list(entry.rglob("*.*"))),
        })

    return features


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def generate_manifest(root: Path) -> dict[str, Any]:
    """Generate the full architecture manifest dictionary."""
    backend_modules_dir = root / "backend" / "app" / "modules"
    frontend_features_dir = root / "frontend" / "src" / "features"

    if not backend_modules_dir.is_dir():
        print(f"ERROR: Backend modules directory not found: {backend_modules_dir}")
        sys.exit(1)

    manifest: dict[str, Any] = {
        "_meta": {
            "generator": "generate_architecture_manifest.py",
            "description": "Auto-generated architecture manifest for OpenConstructionERP",
            "version": "1.0.0",
        },
        "modules": [],
        "frontend_features": [],
        "dependency_graph": {},
        "statistics": {},
    }

    # ── Scan backend modules ────────────────────────────────────────────
    total_models = 0
    total_routes = 0
    total_schemas = 0
    total_columns = 0
    total_relationships = 0
    modules_with_manifests = 0

    module_dirs = sorted(
        d for d in backend_modules_dir.iterdir()
        if d.is_dir() and not d.name.startswith("_") and d.name != "__pycache__"
    )

    print(f"\nScanning {len(module_dirs)} backend modules...")

    for module_dir in module_dirs:
        module_id = module_dir.name
        print(f"  [{module_id}]", end="")

        py_files = sorted(
            str(f.relative_to(module_dir)).replace("\\", "/")
            for f in module_dir.rglob("*.py")
            if f.name != "__pycache__" and "__pycache__" not in str(f)
        )

        module_entry: dict[str, Any] = {
            "module_id": module_id,
            "module_label": module_id.replace("_", " ").title(),
            "module_category": "core",
            "files": py_files,
            "manifest": None,
            "models": [],
            "routes": [],
            "schemas": [],
            "import_dependencies": [],
        }

        # Manifest
        manifest_path = module_dir / "manifest.py"
        if manifest_path.is_file():
            mdata = scan_module_manifest(manifest_path)
            if mdata:
                module_entry["manifest"] = mdata
                module_entry["module_label"] = mdata.get("display_name") or module_entry["module_label"]
                module_entry["module_category"] = mdata.get("category") or "core"
                modules_with_manifests += 1

        # Models
        models_path = module_dir / "models.py"
        if models_path.is_file():
            models = scan_models(models_path)
            module_entry["models"] = models
            total_models += len(models)
            total_columns += sum(len(m["columns"]) for m in models)
            total_relationships += sum(len(m["relationships"]) for m in models)

        # Routes
        router_path = module_dir / "router.py"
        if router_path.is_file():
            routes = scan_routes(router_path)
            module_entry["routes"] = routes
            total_routes += len(routes)

        # Schemas
        schemas_path = module_dir / "schemas.py"
        if schemas_path.is_file():
            schemas = scan_schemas(schemas_path)
            module_entry["schemas"] = schemas
            total_schemas += len(schemas)

        # Import dependencies
        import_deps = scan_imports(module_dir, backend_modules_dir)
        module_entry["import_dependencies"] = import_deps

        # Print inline summary
        parts = []
        if module_entry["models"]:
            parts.append(f"{len(module_entry['models'])} models")
        if module_entry["routes"]:
            parts.append(f"{len(module_entry['routes'])} routes")
        if module_entry["schemas"]:
            parts.append(f"{len(module_entry['schemas'])} schemas")
        if import_deps:
            parts.append(f"deps: {', '.join(import_deps)}")
        summary = f" — {', '.join(parts)}" if parts else " — (empty)"
        print(summary)

        manifest["modules"].append(module_entry)

    # ── Dependency graph (module_id -> [dep_module_ids]) ────────────────
    dep_graph: dict[str, list[str]] = {}
    for mod in manifest["modules"]:
        # Combine manifest depends + import dependencies
        declared_deps = []
        if mod["manifest"] and mod["manifest"].get("depends"):
            # Convert oe_projects -> projects
            declared_deps = [
                d.replace("oe_", "") for d in mod["manifest"]["depends"]
            ]
        import_deps = mod["import_dependencies"]
        combined = sorted(set(declared_deps) | set(import_deps))
        dep_graph[mod["module_id"]] = combined

    manifest["dependency_graph"] = dep_graph

    # ── Frontend features ───────────────────────────────────────────────
    print(f"\nScanning frontend features...")
    frontend_features = scan_frontend_features(frontend_features_dir)
    manifest["frontend_features"] = frontend_features

    # ── Frontend-to-backend mapping ─────────────────────────────────────
    backend_module_ids = {m["module_id"] for m in manifest["modules"]}
    frontend_mapping: dict[str, str | None] = {}
    for feat in frontend_features:
        # Normalize: cad-explorer -> cad, etc.
        normalized = feat["name"].replace("-", "_")
        if normalized in backend_module_ids:
            frontend_mapping[feat["name"]] = normalized
        else:
            # Try partial match
            matched = None
            for mid in backend_module_ids:
                if mid in normalized or normalized in mid:
                    matched = mid
                    break
            frontend_mapping[feat["name"]] = matched

    manifest["frontend_backend_mapping"] = frontend_mapping
    print(f"  {len(frontend_features)} frontend features found")
    mapped_count = sum(1 for v in frontend_mapping.values() if v is not None)
    print(f"  {mapped_count} mapped to backend modules")

    # ── Statistics ──────────────────────────────────────────────────────
    manifest["statistics"] = {
        "backend_modules": len(module_dirs),
        "modules_with_manifests": modules_with_manifests,
        "total_models": total_models,
        "total_columns": total_columns,
        "total_relationships": total_relationships,
        "total_routes": total_routes,
        "total_schemas": total_schemas,
        "total_python_files": sum(len(m["files"]) for m in manifest["modules"]),
        "frontend_features": len(frontend_features),
        "frontend_ts_files": sum(f["ts_files"] for f in frontend_features),
        "frontend_backend_mapped": mapped_count,
    }

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate architecture manifest for OpenConstructionERP."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root directory (default: current directory)",
    )
    args = parser.parse_args()
    root = args.root.resolve()

    print(f"Repository root: {root}")

    manifest = generate_manifest(root)

    # Write output
    output_dir = root / "frontend" / "src" / "features" / "architecture"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "architecture_manifest.json"

    output_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"\nOutput written to: {output_path}")

    # Print summary
    stats = manifest["statistics"]
    print("\n" + "=" * 60)
    print("  ARCHITECTURE MANIFEST — SUMMARY")
    print("=" * 60)
    print(f"  Backend modules:       {stats['backend_modules']}")
    print(f"    with manifest.py:    {stats['modules_with_manifests']}")
    print(f"    Python files:        {stats['total_python_files']}")
    print(f"  SQLAlchemy models:     {stats['total_models']}")
    print(f"    columns:             {stats['total_columns']}")
    print(f"    relationships:       {stats['total_relationships']}")
    print(f"  FastAPI routes:        {stats['total_routes']}")
    print(f"  Pydantic schemas:      {stats['total_schemas']}")
    print(f"  Frontend features:     {stats['frontend_features']}")
    print(f"    TypeScript files:    {stats['frontend_ts_files']}")
    print(f"    mapped to backend:   {stats['frontend_backend_mapped']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
