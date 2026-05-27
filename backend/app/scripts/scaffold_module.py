"""‌⁠‍Scaffold a new OpenEstimate module from the template.

Usage::

    python -m app.scripts.scaffold_module oe_tendering

Or via the top-level Makefile::

    make module-new NAME=oe_tendering

The script:

1. Validates ``NAME`` is snake_case and starts with ``oe_``.
2. Copies ``modules/oe-module-template/`` to
   ``backend/app/modules/<short_name>/`` where ``<short_name>`` is
   ``NAME`` minus the ``oe_`` prefix (matches the existing convention:
   manifest ``oe_projects`` ⇄ package ``backend/app/modules/projects``).
3. Substitutes the ``{{module_name}}`` and ``{{display_name}}``
   placeholders inside every file AND in filenames.
4. Refuses to overwrite an existing module.

Cross-platform — pure ``pathlib`` + ``shutil``, no shell tricks.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

# ── Constants ───────────────────────────────────────────────────────────────
_NAME_RE = re.compile(r"^oe_[a-z][a-z0-9_]*$")
_TOKENS = (
    "{{module_name}}",
    "{{module_short}}",
    "{{display_name}}",
    "{{author}}",
)
_BINARY_SUFFIXES = {".pyc", ".so", ".dll", ".png", ".jpg", ".jpeg", ".gif", ".pdf"}

# ``modules/oe-module-template`` lives at the repo root; this script lives at
# ``backend/app/scripts/scaffold_module.py``. Walk up four levels to reach the
# repo root (scripts → app → backend → repo).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_TEMPLATE_DIR = _REPO_ROOT / "modules" / "oe-module-template"
_MODULES_DIR = _REPO_ROOT / "backend" / "app" / "modules"


def _validate_name(name: str) -> None:
    if not _NAME_RE.match(name):
        raise SystemExit(
            f"Invalid module name: {name!r}\n  Must match snake_case with an 'oe_' prefix, e.g. oe_tendering.",
        )


def _display_name_from(name: str) -> str:
    """``oe_field_ops`` → ``Field Ops``."""
    short = name[len("oe_") :]
    return short.replace("_", " ").title()


def _short_name(name: str) -> str:
    """Package directory name — manifest ``oe_projects`` ⇄ pkg ``projects``."""
    return name[len("oe_") :]


def _is_text_file(path: Path) -> bool:
    if path.suffix.lower() in _BINARY_SUFFIXES:
        return False
    try:
        path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False
    return True


def _substitute_file(path: Path, replacements: dict[str, str]) -> None:
    if not _is_text_file(path):
        return
    original = path.read_text(encoding="utf-8")
    new_text = original
    for token, value in replacements.items():
        new_text = new_text.replace(token, value)
    if new_text != original:
        path.write_text(new_text, encoding="utf-8")


def _substitute_filename(path: Path, replacements: dict[str, str]) -> Path:
    """Rename ``test_{{module_name}}.py`` → ``test_my_module.py``."""
    name = path.name
    new_name = name
    for token, value in replacements.items():
        new_name = new_name.replace(token, value)
    if new_name == name:
        return path
    new_path = path.with_name(new_name)
    path.rename(new_path)
    return new_path


def scaffold(name: str, *, author: str = "Module Author") -> Path:
    """Materialise a new module under ``backend/app/modules/<short_name>/``."""
    _validate_name(name)

    if not _TEMPLATE_DIR.is_dir():
        raise SystemExit(f"Template directory missing: {_TEMPLATE_DIR}")

    target = _MODULES_DIR / _short_name(name)
    if target.exists():
        raise SystemExit(
            f"Refusing to overwrite existing module directory: {target}\n"
            "  Delete it first if you really want to regenerate.",
        )

    replacements = {
        "{{module_name}}": name,
        "{{module_short}}": _short_name(name),
        "{{display_name}}": _display_name_from(name),
        "{{author}}": author,
    }

    # 1. Copy the entire template, ignoring caches.
    shutil.copytree(
        _TEMPLATE_DIR,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
    )

    # 2. Substitute file contents AND filenames.
    #    Walk twice — content first (so renamed files don't go untouched),
    #    then filenames bottom-up so parent renames don't invalidate paths.
    for path in target.rglob("*"):
        if path.is_file():
            _substitute_file(path, replacements)

    for path in sorted(target.rglob("*"), key=lambda p: -len(p.parts)):
        if any(t in path.name for t in _TOKENS):
            _substitute_filename(path, replacements)

    return target


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        sys.stderr.write(
            "Usage: python -m app.scripts.scaffold_module <oe_module_name> [author]\n",
        )
        return 2

    name = args[0].strip()
    author = args[1].strip() if len(args) > 1 else "Module Author"

    target = scaffold(name, author=author)

    sys.stdout.write(
        f"Done — module scaffolded at {target}\n"
        f"  Next:\n"
        f"    1. Edit {target / 'manifest.py'} (description, depends).\n"
        f"    2. Move {target / 'migrations' / 'v0001_initial.py'} into\n"
        f"       backend/alembic/versions/ and set down_revision to the\n"
        f"       current head (run `alembic current` to find it).\n"
        f"    3. Run `make migrate` then `make test-backend`.\n",
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
